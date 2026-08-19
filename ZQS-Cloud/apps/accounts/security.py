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
    organization: Organization
    role: str
    user: User | None = None
    api_key: ApiKey | None = None

    @property
    def is_service(self) -> bool:
        return self.api_key is not None

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


def _resolve_organization(request, user: User) -> tuple[Organization, str]:
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
            return membership.organization, membership.role

        if user.is_superuser:
            qs = Organization.objects.filter(
                **({"id": org_id} if org_id else {"slug": org_slug})
            )
            organization = qs.first()
            if organization is not None:
                return organization, Role.OWNER

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
    return membership.organization, membership.role


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
        organization, role = _resolve_organization(request, user)
        user.last_login_ip = client_ip(request) or user.last_login_ip
        return AuthContext(organization=organization, role=role, user=user)


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
