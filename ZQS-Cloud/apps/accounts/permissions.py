"""Role -> permission expansion.

The API enforces access with role ranks; this module turns a role into an
explicit permission list so the React console can hide controls the user cannot
use, without hard-coding the role hierarchy in the frontend.
"""

from __future__ import annotations

from apps.accounts.models import ROLE_RANK, Role

#: permission -> minimum role required
PERMISSIONS: dict[str, str] = {
    # Read
    "device:read": Role.VIEWER,
    "telemetry:read": Role.VIEWER,
    "alert:read": Role.VIEWER,
    "audit:read": Role.VIEWER,
    "ems:read": Role.VIEWER,
    "site:read": Role.VIEWER,
    # Operate
    "device:command": Role.OPERATOR,
    "alert:acknowledge": Role.OPERATOR,
    "alert:resolve": Role.OPERATOR,
    "ems:dispatch": Role.OPERATOR,
    # Configure
    "device:write": Role.ADMIN,
    "site:write": Role.ADMIN,
    "telemetry:policy:write": Role.ADMIN,
    "alert:rule:write": Role.ADMIN,
    "ems:write": Role.ADMIN,
    "apikey:manage": Role.ADMIN,
    "member:manage": Role.ADMIN,
    # Own
    "organization:write": Role.OWNER,
    "organization:delete": Role.OWNER,
    "member:manage_owner": Role.OWNER,
}


def permissions_for(role: str, *, is_superuser: bool = False) -> list[str]:
    if is_superuser:
        return sorted(PERMISSIONS)
    rank = ROLE_RANK.get(role, 0)
    return sorted(
        name
        for name, minimum in PERMISSIONS.items()
        if rank >= ROLE_RANK.get(minimum, 999)
    )


def role_for_permission(permission: str) -> str:
    try:
        return PERMISSIONS[permission]
    except KeyError as exc:
        raise KeyError(f"Unknown permission: {permission}") from exc
