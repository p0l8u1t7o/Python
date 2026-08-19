"""JWT issuing / verification.

Access tokens are short-lived and stateless. Refresh tokens are long-lived and
tracked in the database so a session can be revoked and reuse can be detected.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

import jwt
from django.conf import settings
from django.utils import timezone

from apps.accounts.models import RefreshToken, User
from apps.core.errors import AuthenticationError

ACCESS = "access"
REFRESH = "refresh"


@dataclass(slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int
    token_type: str = "Bearer"


def _encode(payload: dict) -> str:
    return jwt.encode(
        payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALGORITHM
    )


def _base_claims(user: User, kind: str, ttl: int) -> dict:
    issued = timezone.now()
    return {
        "iss": settings.JWT_ISSUER,
        "sub": str(user.pk),
        "typ": kind,
        "ver": user.token_version,
        "jti": uuid.uuid4().hex,
        "iat": int(issued.timestamp()),
        "exp": int((issued + dt.timedelta(seconds=ttl)).timestamp()),
    }


def issue_pair(
    user: User, *, user_agent: str = "", ip_address: str | None = None
) -> TokenPair:
    access_ttl = settings.JWT_ACCESS_TTL_SECONDS
    refresh_ttl = settings.JWT_REFRESH_TTL_SECONDS

    access_claims = _base_claims(user, ACCESS, access_ttl)
    refresh_claims = _base_claims(user, REFRESH, refresh_ttl)

    RefreshToken.objects.create(
        jti=RefreshToken.hash_jti(refresh_claims["jti"]),
        user=user,
        expires_at=timezone.now() + dt.timedelta(seconds=refresh_ttl),
        user_agent=user_agent[:256],
        ip_address=ip_address or None,
    )

    return TokenPair(
        access_token=_encode(access_claims),
        refresh_token=_encode(refresh_claims),
        expires_in=access_ttl,
        refresh_expires_in=refresh_ttl,
    )


def decode(token: str, *, expected_type: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SIGNING_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid token", code="token_invalid") from exc

    if claims.get("typ") != expected_type:
        raise AuthenticationError(
            f"Expected a {expected_type} token", code="token_wrong_type"
        )
    return claims


def user_from_access_token(token: str) -> User:
    claims = decode(token, expected_type=ACCESS)
    try:
        user = User.objects.get(pk=claims["sub"])
    except (User.DoesNotExist, ValueError, TypeError) as exc:
        raise AuthenticationError("Unknown subject", code="token_invalid") from exc

    if not user.is_active:
        raise AuthenticationError("Account is disabled", code="account_disabled")
    if claims.get("ver") != user.token_version:
        raise AuthenticationError("Token has been revoked", code="token_revoked")
    return user


def rotate_refresh_token(
    token: str, *, user_agent: str = "", ip_address: str | None = None
) -> TokenPair:
    """Exchange a refresh token, revoking the old one (single-use rotation).

    Presenting an already-revoked token is treated as theft: every session for
    that user is invalidated.
    """
    claims = decode(token, expected_type=REFRESH)
    hashed = RefreshToken.hash_jti(claims["jti"])

    try:
        record = RefreshToken.objects.select_related("user").get(jti=hashed)
    except RefreshToken.DoesNotExist as exc:
        raise AuthenticationError("Unknown refresh token", code="token_invalid") from exc

    if record.revoked_at is not None:
        record.user.bump_token_version()
        raise AuthenticationError(
            "Refresh token reuse detected; all sessions revoked",
            code="token_reuse_detected",
        )
    if not record.is_valid:
        raise AuthenticationError("Refresh token expired", code="token_expired")

    user = record.user
    if not user.is_active:
        raise AuthenticationError("Account is disabled", code="account_disabled")
    if claims.get("ver") != user.token_version:
        raise AuthenticationError("Token has been revoked", code="token_revoked")

    pair = issue_pair(user, user_agent=user_agent, ip_address=ip_address)
    new_claims = jwt.decode(
        pair.refresh_token, options={"verify_signature": False}
    )
    record.revoke(replaced_by=RefreshToken.hash_jti(new_claims["jti"]))
    return pair


def revoke_refresh_token(token: str) -> None:
    """Best-effort logout: an already invalid token is not an error."""
    try:
        claims = decode(token, expected_type=REFRESH)
    except AuthenticationError:
        return
    RefreshToken.objects.filter(
        jti=RefreshToken.hash_jti(claims["jti"]), revoked_at__isnull=True
    ).update(revoked_at=timezone.now())
