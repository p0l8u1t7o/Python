"""Authentication, organisation, membership and API-key endpoints."""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja import Query, Router

from apps.accounts import schemas as s
from apps.accounts import tokens
from apps.accounts.models import (
    ApiKey,
    Membership,
    Organization,
    Role,
    User,
    UserPreference,
)
from apps.accounts.permissions import permissions_for
from apps.accounts.security import AuthContext, role_required
from apps.audit.models import AuditAction
from apps.audit.services import record, record_failure
from apps.core.errors import (
    AuthenticationError,
    Conflict,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from apps.core.middleware import client_ip
from apps.core.schemas import OkResponse, Page, PageParams, paginate
from apps.core.throttle import throttle

router = Router(tags=["auth"])


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
@router.post("/auth/login", response=s.TokenOut, auth=None, url_name="login")
def login(request, payload: s.LoginIn):
    """Exchange credentials for an access/refresh token pair."""
    throttle(request, bucket=f"login:{payload.email.lower()}", limit=10, window_s=300)
    throttle(request, bucket=f"login-ip:{client_ip(request)}", limit=50, window_s=300)

    user = authenticate(request, username=payload.email.lower(), password=payload.password)
    if user is None:
        record_failure(
            AuditAction.LOGIN_FAILED,
            "Invalid credentials",
            target_type="user",
            target_label=payload.email,
        )
        raise AuthenticationError("Incorrect email or password", code="invalid_credentials")
    if not user.is_active:
        raise AuthenticationError("Account is disabled", code="account_disabled")

    pair = tokens.issue_pair(
        user,
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        ip_address=client_ip(request) or None,
    )
    User.objects.filter(pk=user.pk).update(
        last_login=timezone.now(), last_login_ip=client_ip(request) or None
    )
    # No organization is selected yet at login time, so attribute the event to
    # the membership the user will land in by default. Without this the entry
    # is organization-less and therefore invisible in the tenant audit trail -
    # which is exactly where sign-ins need to be reviewable.
    primary = (
        Membership.objects.select_related("organization")
        .filter(user=user)
        .order_by("created_at")
        .first()
    )
    record(
        AuditAction.LOGIN,
        organization=primary.organization if primary else None,
        actor=user,
        target=user,
        target_label=user.email,
    )
    return pair


@router.post("/auth/refresh", response=s.TokenOut, auth=None)
def refresh(request, payload: s.RefreshIn):
    """Rotate a refresh token. Reuse of a spent token revokes all sessions."""
    throttle(request, bucket=f"refresh-ip:{client_ip(request)}", limit=120, window_s=300)
    return tokens.rotate_refresh_token(
        payload.refresh_token,
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        ip_address=client_ip(request) or None,
    )


@router.post("/auth/logout", response=OkResponse, auth=None)
def logout(request, payload: s.RefreshIn):
    tokens.revoke_refresh_token(payload.refresh_token)
    return {"ok": True, "message": "signed_out"}


@router.get("/auth/me", response=s.MeOut)
def me(request):
    ctx: AuthContext = request.auth
    if ctx.user is None:
        raise PermissionDenied("API keys have no user profile", code="not_a_user")

    memberships = (
        Membership.objects.select_related("organization")
        .filter(user=ctx.user)
        .order_by("organization__name")
    )
    current = next(
        (m for m in memberships if m.organization_id == ctx.organization.id), None
    )
    return {
        "user": ctx.user,
        "organization": ctx.organization,
        "role": ctx.role,
        "organizations": [
            {"organization": m.organization, "role": m.role} for m in memberships
        ],
        "permissions": permissions_for(ctx.role, is_superuser=ctx.user.is_superuser),
        "site_scope": sorted(ctx.site_scope) if ctx.site_scope else [],
        "scoped_site_ids": (
            list(current.sites.values_list("pk", flat=True)) if current else []
        ),
    }


#: How many separate layouts one person may keep, and how big each may be.
#:
#: Without a cap this is an unbounded write-anything store attached to every
#: session. The numbers are generous for the real use - a metric layout per
#: device on a large site is a few hundred rows of a few hundred bytes.
MAX_UI_PREFERENCES = 500
MAX_UI_PREFERENCE_BYTES = 8 * 1024

_UI_KEY = re.compile(UserPreference.KEY_PATTERN)


@router.get("/auth/me/ui", response=list[s.UiPreferenceOut])
def list_ui_preferences(request, prefix: str = ""):
    """Console layout state this user has saved.

    Separate from ``/auth/me/preferences``, which holds theme, language and
    timezone - those the API itself reads and every client must honour. These
    the server only stores, so that a layout somebody arranged follows them to
    another machine instead of living in one browser's localStorage.
    """
    ctx: AuthContext = request.auth
    if ctx.user is None:
        raise PermissionDenied("API keys have no user profile", code="not_a_user")

    queryset = UserPreference.objects.filter(user=ctx.user)
    if prefix:
        queryset = queryset.filter(key__startswith=prefix)
    return [{"key": row.key, "value": row.value} for row in queryset]


@router.get("/auth/me/ui/{key}", response=s.UiPreferenceOut)
def get_ui_preference(request, key: str):
    """An unset key returns an empty value rather than 404.

    "This user has not customised it yet" is the normal case on first visit,
    not an error, and making every page handle a 404 for it would put the same
    try/catch on every caller.
    """
    ctx: AuthContext = request.auth
    if ctx.user is None:
        raise PermissionDenied("API keys have no user profile", code="not_a_user")
    _validate_ui_key(key)

    row = UserPreference.objects.filter(user=ctx.user, key=key).first()
    return {"key": key, "value": row.value if row else {}}


@router.put("/auth/me/ui/{key}", response=s.UiPreferenceOut)
def set_ui_preference(request, key: str, payload: s.UiPreferenceIn):
    ctx: AuthContext = request.auth
    if ctx.user is None:
        raise PermissionDenied("API keys have no user profile", code="not_a_user")
    _validate_ui_key(key)

    encoded = json.dumps(payload.value, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_UI_PREFERENCE_BYTES:
        raise ValidationError(
            f"A preference value may not exceed {MAX_UI_PREFERENCE_BYTES} bytes",
            code="preference_too_large",
        )

    existing = UserPreference.objects.filter(user=ctx.user, key=key).first()
    if existing is None:
        count = UserPreference.objects.filter(user=ctx.user).count()
        if count >= MAX_UI_PREFERENCES:
            raise Conflict(
                f"You already have {count} saved layouts, the maximum is "
                f"{MAX_UI_PREFERENCES}. Reset one you no longer use.",
                code="too_many_preferences",
            )

    row, _created = UserPreference.objects.update_or_create(
        user=ctx.user, key=key, defaults={"value": payload.value}
    )
    return {"key": row.key, "value": row.value}


@router.delete("/auth/me/ui/{key}", response=OkResponse)
def clear_ui_preference(request, key: str):
    """Forget a customisation, so the page falls back to its default."""
    ctx: AuthContext = request.auth
    if ctx.user is None:
        raise PermissionDenied("API keys have no user profile", code="not_a_user")
    _validate_ui_key(key)

    UserPreference.objects.filter(user=ctx.user, key=key).delete()
    return {"ok": True, "message": "preference_cleared"}


def _validate_ui_key(key: str) -> None:
    if not _UI_KEY.match(key):
        raise ValidationError(
            "Preference keys are lowercase words, optionally followed by "
            "':' and an identifier",
            code="invalid_preference_key",
            details={"key": key[:100]},
        )


@router.patch("/auth/me/preferences", response=s.UserOut)
def update_preferences(request, payload: s.PreferencesIn):
    """Persist theme / language / timezone so they follow the account."""
    ctx: AuthContext = request.auth
    if ctx.user is None:
        raise PermissionDenied("API keys have no preferences", code="not_a_user")

    from django.conf import settings

    fields: list[str] = []
    if payload.language is not None:
        allowed = {code for code, _ in settings.LANGUAGES}
        if payload.language not in allowed:
            raise ValidationError(
                f"Unsupported language: {payload.language}",
                details={"supported": sorted(allowed)},
            )
        ctx.user.language = payload.language
        fields.append("language")
    if payload.theme is not None:
        ctx.user.theme = payload.theme
        fields.append("theme")
    if payload.timezone_name is not None:
        _validate_timezone(payload.timezone_name)
        ctx.user.timezone_name = payload.timezone_name
        fields.append("timezone_name")

    if fields:
        ctx.user.save(update_fields=[*fields, "updated_at"])
    return ctx.user


@router.patch("/auth/me/profile", response=s.UserOut)
def update_profile(request, payload: s.ProfileIn):
    ctx: AuthContext = request.auth
    if ctx.user is None:
        raise PermissionDenied("API keys have no profile", code="not_a_user")

    fields: list[str] = []
    if payload.full_name is not None:
        ctx.user.full_name = payload.full_name
        fields.append("full_name")
    if payload.phone is not None:
        ctx.user.phone = payload.phone
        fields.append("phone")
    if fields:
        ctx.user.save(update_fields=[*fields, "updated_at"])
        record(AuditAction.USER_UPDATED, ctx=ctx, target=ctx.user)
    return ctx.user


@router.post("/auth/me/password", response=OkResponse)
def change_password(request, payload: s.PasswordChangeIn):
    ctx: AuthContext = request.auth
    if ctx.user is None:
        raise PermissionDenied("API keys have no password", code="not_a_user")
    if not ctx.user.check_password(payload.current_password):
        raise AuthenticationError("Current password is incorrect", code="invalid_credentials")

    _validate_password(payload.new_password, ctx.user)
    ctx.user.set_password(payload.new_password)
    ctx.user.save(update_fields=["password", "updated_at"])
    # Force every other session to re-authenticate.
    ctx.user.bump_token_version()
    record(AuditAction.PASSWORD_CHANGED, ctx=ctx, target=ctx.user)
    return {"ok": True, "message": "password_changed"}


# --------------------------------------------------------------------------
# Organizations
# --------------------------------------------------------------------------
org_router = Router(tags=["organizations"])


@org_router.get("", response=list[s.OrganizationMembershipOut])
def list_my_organizations(request):
    ctx: AuthContext = request.auth
    if ctx.user is None:
        return [{"organization": ctx.organization, "role": ctx.role}]
    memberships = (
        Membership.objects.select_related("organization")
        .filter(user=ctx.user)
        .order_by("organization__name")
    )
    return [{"organization": m.organization, "role": m.role} for m in memberships]


@org_router.post("", response={201: s.OrganizationOut})
def create_organization(request, payload: s.OrganizationIn):
    """Create a tenant; the caller becomes its owner."""
    ctx: AuthContext = request.auth
    if ctx.user is None:
        raise PermissionDenied("API keys cannot create organizations", code="not_a_user")
    _validate_timezone(payload.default_timezone)

    try:
        with transaction.atomic():
            organization = Organization.objects.create(
                name=payload.name,
                slug=payload.slug,
                default_timezone=payload.default_timezone,
            )
            Membership.objects.create(
                organization=organization, user=ctx.user, role=Role.OWNER
            )
    except IntegrityError as exc:
        raise Conflict(f"Slug '{payload.slug}' is already taken", code="slug_taken") from exc

    record(
        AuditAction.ORG_CREATED,
        organization=organization,
        actor=ctx.user,
        target=organization,
    )
    return 201, organization


@org_router.get("/current", response=s.OrganizationOut)
def get_current_organization(request):
    return request.auth.organization


@org_router.patch("/current", response=s.OrganizationOut, auth=role_required(Role.OWNER))
def update_current_organization(request, payload: s.OrganizationUpdateIn):
    ctx: AuthContext = request.auth
    organization = ctx.organization

    fields: list[str] = []
    if payload.name is not None:
        organization.name = payload.name
        fields.append("name")
    if payload.default_timezone is not None:
        _validate_timezone(payload.default_timezone)
        organization.default_timezone = payload.default_timezone
        fields.append("default_timezone")
    if payload.reporting_currency is not None:
        code = payload.reporting_currency.strip().upper()
        if not code.isalpha():
            raise ValidationError("reporting_currency must be an ISO 4217 code", code="invalid_currency")
        organization.reporting_currency = code
        fields.append("reporting_currency")
    if payload.is_active is not None:
        organization.is_active = payload.is_active
        fields.append("is_active")
    if fields:
        organization.save(update_fields=[*fields, "updated_at"])
        record(AuditAction.ORG_UPDATED, ctx=ctx, target=organization, payload=payload.dict())
    return organization


# --------------------------------------------------------------------------
# Members
# --------------------------------------------------------------------------
member_router = Router(tags=["members"])


@member_router.get("", response=Page[s.MemberOut], auth=role_required(Role.VIEWER))
def list_members(request, params: Query[PageParams]):
    ctx: AuthContext = request.auth
    queryset = (
        Membership.objects.select_related("user")
        .prefetch_related("sites")
        .filter(organization=ctx.organization)
        .order_by("user__email")
    )
    page = paginate(queryset, params)
    page["items"] = [
        {
            "user": m.user,
            "role": m.role,
            "created_at": m.created_at,
            "site_ids": [site.pk for site in m.sites.all()],
        }
        for m in page["items"]
    ]
    return page


@member_router.post("", response={201: s.MemberOut}, auth=role_required(Role.ADMIN))
def add_member(request, payload: s.MemberInviteIn):
    """Attach an existing user to this organisation."""
    ctx: AuthContext = request.auth
    if payload.role == Role.OWNER:
        ctx.require(Role.OWNER)

    user = User.objects.filter(email=payload.email.lower()).first()
    if user is None:
        raise NotFound(
            "No user with that email; create the account first",
            code="user_not_found",
        )
    if Membership.objects.filter(organization=ctx.organization, user=user).exists():
        raise Conflict("User is already a member", code="already_member")

    membership = Membership.objects.create(
        organization=ctx.organization, user=user, role=payload.role, invited_by=ctx.user
    )
    record(
        AuditAction.MEMBER_INVITED,
        ctx=ctx,
        target=user,
        target_type="user",
        target_label=user.email,
        payload={"role": payload.role},
    )
    return 201, {
        "user": user,
        "role": membership.role,
        "created_at": membership.created_at,
        "site_ids": [],
    }


@member_router.post("/users", response={201: s.UserOut}, auth=role_required(Role.ADMIN))
def create_user(request, payload: s.UserCreateIn):
    """Create a user account and add it to the current organisation."""
    ctx: AuthContext = request.auth
    if payload.role == Role.OWNER:
        ctx.require(Role.OWNER)
    if User.objects.filter(email=payload.email.lower()).exists():
        raise Conflict("Email is already registered", code="email_taken")

    _validate_password(payload.password)
    with transaction.atomic():
        user = User.objects.create_user(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            language=payload.language,
        )
        Membership.objects.create(
            organization=ctx.organization, user=user, role=payload.role, invited_by=ctx.user
        )
    record(
        AuditAction.USER_CREATED,
        ctx=ctx,
        target=user,
        target_label=user.email,
        payload={"role": payload.role},
    )
    return 201, user


@member_router.patch("/{user_id}", response=s.MemberOut, auth=role_required(Role.ADMIN))
def update_member_role(request, user_id: uuid.UUID, payload: s.MemberRoleIn):
    """Change a member's role and, optionally, which sites they may see.

    Site scope and role are two independent dimensions: narrowing someone to
    one plant does not change what they may do there. An owner is deliberately
    *not* exempt - if an organisation wants a plant-level owner, that is a
    coherent thing to want - but the usual owner guards still apply to the
    role itself.
    """
    from apps.devices.models import Site

    ctx: AuthContext = request.auth
    membership = _get_membership(ctx, user_id)

    # Changing anything about an owner, or granting owner, needs owner rights.
    if Role.OWNER in {membership.role, payload.role}:
        ctx.require(Role.OWNER)
    if membership.role == Role.OWNER and payload.role != Role.OWNER:
        _guard_last_owner(ctx, membership)

    membership.role = payload.role
    membership.save(update_fields=["role", "updated_at"])

    audit: dict = {"role": payload.role}
    if payload.site_ids is not None:
        sites = list(
            Site.objects.filter(
                organization=ctx.organization,
                pk__in=payload.site_ids,
                deleted_at__isnull=True,
            )
        )
        unknown = set(payload.site_ids) - {site.pk for site in sites}
        if unknown:
            raise NotFound(
                "Unknown site(s) in this organization",
                code="site_not_found",
                details={"site_ids": sorted(str(pk) for pk in unknown)},
            )
        # An admin cannot grant access they do not have themselves; otherwise
        # scoping would be trivially self-defeating.
        for site in sites:
            ctx.require_site(site.pk)
        membership.sites.set(sites)
        audit["site_ids"] = [str(site.pk) for site in sites]

    record(
        AuditAction.MEMBER_ROLE_CHANGED,
        ctx=ctx,
        target=membership.user,
        target_type="user",
        target_label=membership.user.email,
        payload=audit,
    )
    return {
        "user": membership.user,
        "role": membership.role,
        "created_at": membership.created_at,
        "site_ids": list(membership.sites.values_list("pk", flat=True)),
    }


@member_router.delete("/{user_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def remove_member(request, user_id: uuid.UUID):
    ctx: AuthContext = request.auth
    membership = _get_membership(ctx, user_id)
    if membership.role == Role.OWNER:
        ctx.require(Role.OWNER)
        _guard_last_owner(ctx, membership)

    email = membership.user.email
    membership.delete()
    record(
        AuditAction.MEMBER_REMOVED,
        ctx=ctx,
        target_type="user",
        target_id=str(user_id),
        target_label=email,
    )
    return {"ok": True, "message": "member_removed"}


# --------------------------------------------------------------------------
# API keys
# --------------------------------------------------------------------------
apikey_router = Router(tags=["api-keys"])


@apikey_router.get("", response=Page[s.ApiKeyOut], auth=role_required(Role.ADMIN))
def list_api_keys(request, params: Query[PageParams]):
    ctx: AuthContext = request.auth
    queryset = ApiKey.objects.filter(organization=ctx.organization).order_by("-created_at")
    return paginate(queryset, params)


@apikey_router.post("", response={201: s.ApiKeyCreatedOut}, auth=role_required(Role.ADMIN))
def create_api_key(request, payload: s.ApiKeyCreateIn):
    """Issue a machine credential. The secret is returned only in this response."""
    ctx: AuthContext = request.auth
    if payload.role == Role.OWNER:
        raise ValidationError("API keys cannot hold the owner role", code="role_forbidden")
    if ctx.role != Role.OWNER and payload.role == Role.ADMIN:
        ctx.require(Role.OWNER)

    expires_at = None
    if payload.expires_in_days:
        expires_at = timezone.now() + dt.timedelta(days=payload.expires_in_days)

    key, secret = ApiKey.generate(
        organization=ctx.organization,
        name=payload.name,
        role=payload.role,
        created_by=ctx.user,
        expires_at=expires_at,
    )
    record(
        AuditAction.APIKEY_CREATED,
        ctx=ctx,
        target=key,
        payload={"name": payload.name, "role": payload.role},
    )
    return 201, {"key": key, "secret": secret}


@apikey_router.delete("/{key_id}", response=OkResponse, auth=role_required(Role.ADMIN))
def revoke_api_key(request, key_id: uuid.UUID):
    ctx: AuthContext = request.auth
    key = ApiKey.objects.filter(organization=ctx.organization, pk=key_id).first()
    if key is None:
        raise NotFound("API key not found")
    if key.revoked_at is None:
        key.revoked_at = timezone.now()
        key.save(update_fields=["revoked_at", "updated_at"])
    record(AuditAction.APIKEY_REVOKED, ctx=ctx, target=key)
    return {"ok": True, "message": "api_key_revoked"}


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------
def _get_membership(ctx: AuthContext, user_id: uuid.UUID) -> Membership:
    membership = (
        Membership.objects.select_related("user")
        .filter(organization=ctx.organization, user_id=user_id)
        .first()
    )
    if membership is None:
        raise NotFound("Member not found")
    return membership


def _guard_last_owner(ctx: AuthContext, membership: Membership) -> None:
    remaining = (
        Membership.objects.filter(organization=ctx.organization, role=Role.OWNER)
        .exclude(pk=membership.pk)
        .count()
    )
    if remaining == 0:
        raise Conflict(
            "An organization must keep at least one owner", code="last_owner"
        )


def _validate_password(password: str, user: User | None = None) -> None:
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError(
            "Password does not meet complexity requirements",
            code="weak_password",
            details=list(exc.messages),
        ) from exc


def _validate_timezone(name: str) -> None:
    import zoneinfo

    try:
        zoneinfo.ZoneInfo(name)
    except Exception as exc:  # noqa: BLE001 - any zoneinfo failure is user error
        raise ValidationError(
            f"Unknown timezone: {name}", code="invalid_timezone"
        ) from exc
