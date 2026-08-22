"""Authentication + authorisation plumbing for the Ninja API.

Two principal kinds are supported:

* **User** - ``Authorization: Bearer <jwt>``, for the React console.
* **API key** - ``Authorization: ApiKey zqs_<prefix>.<secret>`` (or the
  ``X-API-Key`` header), for server-to-server integrations.

Both resolve to an :class:`AuthContext` pinned to exactly one organisation, so
every downstream query can filter by ``ctx.organization`` and multi-tenancy is
enforced in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from django.utils import timezone
from ninja.security import HttpBearer

from apps.accounts.models import (
    ROLE_RANK,
    ApiKey,
    Membership,
    Organization,
    Role,
    User,
)
from apps.accounts.tokens import user_from_access_token
from apps.core.errors import AuthenticationError, PermissionDenied
from apps.core.middleware import client_ip

ORG_ID_HEADER = "HTTP_X_ORGANIZATION_ID"
ORG_SLUG_HEADER = "HTTP_X_ORGANIZATION"
API_KEY_HEADER = "HTTP_X_API_KEY"


@dataclass(slots=True)
class AuthContext:
    """One authenticated principal, pinned to one organisation.

    Access has three dimensions, not two: which tenant, which role, and -
    since site scoping - which part of the tenant. :attr:`site_scope` is the
    third. ``None`` means unrestricted, which is what every membership is
    unless somebody narrows it, so the addition changed nobody's access.
    """

    organization: Organization
    role: str
    user: User | None = None
    api_key: ApiKey | None = None
    #: Site primary keys this principal may see, already expanded to include
    #: descendants. ``None`` means "the whole organisation" - deliberately not
    #: an empty set, which would read as "nothing" and is a mistake that would
    #: lock everyone out on the day someone forgets the difference.
    site_scope: frozenset | None = None

    @property
    def is_service(self) -> bool:
        return self.api_key is not None

    # ---- Site scope ------------------------------------------------------
    @property
    def is_site_scoped(self) -> bool:
        return self.site_scope is not None

    def allows_site(self, site_id) -> bool:
        """Whether this principal may see ``site_id``.

        A device with no site at all is visible only to an unscoped
        principal. Somebody restricted to one plant has no business seeing
        equipment that has not been placed anywhere yet - that is exactly the
        pool a new device lands in before an admin assigns it.
        """
        if self.site_scope is None:
            return True
        if site_id is None:
            return False
        return site_id in self.site_scope

    def require_site(self, site_id) -> None:
        if not self.allows_site(site_id):
            raise PermissionDenied(
                "Your access does not include this site",
                code="site_out_of_scope",
                details={"site_id": str(site_id) if site_id else None},
            )

    def scope_queryset(self, queryset, field: str = "site_id"):
        """Narrow ``queryset`` to the sites this principal may see.

        ``field`` is the lookup path to the site, so the same call works for
        ``Site`` (``id``), ``Device`` (``site_id``) and anything reached
        through a relation (``device__site_id``).
        """
        if self.site_scope is None:
            return queryset
        return queryset.filter(**{f"{field}__in": list(self.site_scope)})

    @property
    def principal_id(self) -> str:
        if self.user is not None:
            return str(self.user.pk)
        return f"apikey:{self.api_key.prefix}" if self.api_key else "anonymous"

    @property
    def principal_label(self) -> str:
        if self.user is not None:
            return self.user.email
        return f"api-key:{self.api_key.name}" if self.api_key else "anonymous"

    def has_role(self, minimum: str) -> bool:
        if self.user is not None and self.user.is_superuser:
            return True
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK.get(minimum, 999)

    def require(self, minimum: str) -> None:
        if not self.has_role(minimum):
            raise PermissionDenied(
                f"Requires {minimum} role or higher in this organization",
                details={"required_role": minimum, "current_role": self.role},
            )


def resolve_site_scope(membership: Membership | None) -> frozenset | None:
    """Expand a membership's site list to the subtrees it covers.

    ``None`` for an unrestricted membership. Naming a parent grants its
    children: someone responsible for a plant is responsible for the workshops
    inside it, and forcing an admin to list every line would make the feature
    unusable and, worse, silently wrong the day a line is added.
    """
    if membership is None:
        return None

    roots = list(membership.sites.values_list("pk", flat=True))
    if not roots:
        return None

    # Imported here, not at module scope: apps.devices imports apps.accounts.
    from apps.devices.models import descendant_site_ids

    return frozenset(
        descendant_site_ids(roots, organization=membership.organization)
    )


def _resolve_organization(request, user: User) -> tuple[Organization, str, Membership | None]:
    """Pick the organisation this request operates on and the user's role in it."""
    org_id = request.META.get(ORG_ID_HEADER, "").strip()
    org_slug = request.META.get(ORG_SLUG_HEADER, "").strip()
    if not org_id and not org_slug:
        org_id = (request.GET.get("organization_id") or "").strip()
        org_slug = (request.GET.get("organization") or "").strip()

    memberships = Membership.objects.select_related("organization").filter(user=user)

    if org_id or org_slug:
        lookup = {"organization__id": org_id} if org_id else {"organization__slug": org_slug}
        membership = memberships.filter(**lookup).first()
        if membership is not None:
            if not membership.organization.is_active:
                raise AuthenticationError(
                    "Organization is disabled", code="organization_disabled"
                )
            return membership.organization, membership.role, membership

        if user.is_superuser:
            qs = Organization.objects.filter(
                **({"id": org_id} if org_id else {"slug": org_slug})
            )
            organization = qs.first()
            if organization is not None:
                # A superuser acting outside their own memberships has no
                # membership row to scope by, and is unrestricted.
                return organization, Role.OWNER, None

        raise PermissionDenied(
            "You are not a member of the requested organization",
            code="organization_forbidden",
        )

    membership = memberships.order_by("created_at").first()
    if membership is None:
        raise PermissionDenied(
            "User does not belong to any organization", code="no_organization"
        )
    if not membership.organization.is_active:
        raise AuthenticationError(
            "Organization is disabled", code="organization_disabled"
        )
    return membership.organization, membership.role, membership


def _authenticate_api_key(request, raw: str) -> AuthContext:
    raw = raw.strip()
    if raw.startswith("zqs_"):
        raw = raw[4:]
    prefix, _, secret = raw.partition(".")
    if not prefix or not secret:
        raise AuthenticationError("Malformed API key", code="api_key_malformed")

    key = (
        ApiKey.objects.select_related("organization")
        .filter(prefix=prefix)
        .first()
    )
    if key is None or not key.verify(secret):
        raise AuthenticationError("Invalid API key", code="api_key_invalid")
    if not key.is_active:
        raise AuthenticationError("API key is revoked or expired", code="api_key_expired")
    if not key.organization.is_active:
        raise AuthenticationError(
            "Organization is disabled", code="organization_disabled"
        )

    # Throttled write: one UPDATE per minute per key is enough for auditing.
    now = timezone.now()
    if key.last_used_at is None or (now - key.last_used_at).total_seconds() > 60:
        ApiKey.objects.filter(pk=key.pk).update(last_used_at=now)

    return AuthContext(organization=key.organization, role=key.role, api_key=key)


class ApiAuth(HttpBearer):
    """Accepts both ``Bearer <jwt>`` and ``ApiKey <secret>`` authorization."""

    openapi_scheme = "bearer"

    def __call__(self, request):
        header = request.headers.get("Authorization", "")
        api_key_header = request.META.get(API_KEY_HEADER, "")

        if api_key_header:
            ctx = _authenticate_api_key(request, api_key_header)
        elif header.lower().startswith("apikey "):
            ctx = _authenticate_api_key(request, header[7:])
        elif header.lower().startswith("bearer "):
            ctx = self.authenticate(request, header[7:])
        else:
            raise AuthenticationError(
                "Authorization header is missing", code="unauthenticated"
            )

        request.auth_context = ctx
        return ctx

    def authenticate(self, request, token: str) -> AuthContext:
        user = user_from_access_token(token)
        organization, role, membership = _resolve_organization(request, user)
        user.last_login_ip = client_ip(request) or user.last_login_ip
        # A superuser sees the whole tenant regardless of how their membership
        # is scoped: the escape hatch has to stay usable when the thing being
        # debugged is the scoping itself.
        scope = None if user.is_superuser else resolve_site_scope(membership)
        return AuthContext(
            organization=organization, role=role, user=user, site_scope=scope
        )


api_auth = ApiAuth()


class RoleAuth(ApiAuth):
    """Authenticate, then require a minimum role in the resolved organisation.

    Used as a per-operation ``auth=`` rather than a view decorator: a decorator
    would have to wrap the view, and Ninja resolves ``from __future__ import
    annotations`` string annotations against the *wrapper's* module globals,
    which breaks every schema reference in the signature.
    """

    def __init__(self, minimum: str) -> None:
        super().__init__()
        self.minimum = minimum

    def __call__(self, request):
        ctx = super().__call__(request)
        ctx.require(self.minimum)
        return ctx


@lru_cache(maxsize=None)
def role_required(minimum: str) -> RoleAuth:
    """``auth=role_required(Role.ADMIN)`` - one shared instance per role."""
    return RoleAuth(minimum)
