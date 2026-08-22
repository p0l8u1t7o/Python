from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ninja import Schema
from pydantic import EmailStr, Field

from apps.accounts.models import Role, Theme


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
class LoginIn(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(Schema):
    refresh_token: str


class TokenOut(Schema):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_expires_in: int


class PasswordChangeIn(Schema):
    current_password: str
    new_password: str = Field(min_length=10, max_length=256)


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
class UserOut(Schema):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    phone: str
    is_active: bool
    is_staff: bool
    language: str
    theme: Theme
    timezone_name: str
    created_at: dt.datetime
    last_login: dt.datetime | None = None


class PreferencesIn(Schema):
    """UI preferences kept server-side so theme/language follow the account."""

    language: str | None = Field(default=None, max_length=16)
    theme: Theme | None = None
    timezone_name: str | None = Field(default=None, max_length=64)


class ProfileIn(Schema):
    full_name: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=40)


class MeOut(Schema):
    user: UserOut
    organization: "OrganizationOut"
    role: Role
    organizations: list["OrganizationMembershipOut"]
    permissions: list[str]
    #: Sites this session may see, already expanded to include descendants.
    #: Empty means the whole organisation - the console uses it to explain why
    #: a page looks smaller than someone expects, not to enforce anything.
    site_scope: list[uuid.UUID] = Field(default_factory=list)
    #: The sites actually granted, before subtree expansion. What an admin
    #: picked, so an editor can show it back unchanged.
    scoped_site_ids: list[uuid.UUID] = Field(default_factory=list)


class UiPreferenceIn(Schema):
    """A blob of console state. The server stores it and never reads it."""

    value: dict[str, Any] = Field(default_factory=dict)


class UiPreferenceOut(Schema):
    key: str
    value: dict[str, Any] = Field(default_factory=dict)


class UserCreateIn(Schema):
    email: EmailStr
    full_name: str = Field(default="", max_length=150)
    password: str = Field(min_length=10, max_length=256)
    role: Role = Role.VIEWER
    language: str = "en"


# --------------------------------------------------------------------------
# Organizations / membership
# --------------------------------------------------------------------------
class OrganizationOut(Schema):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    default_timezone: str
    #: ISO 4217. Every money figure in this tenant is already in this currency;
    #: nothing here converts between currencies.
    reporting_currency: str = ""
    created_at: dt.datetime


class OrganizationMembershipOut(Schema):
    organization: OrganizationOut
    role: Role


class OrganizationIn(Schema):
    name: str = Field(max_length=200)
    slug: str = Field(max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    default_timezone: str = "UTC"


class OrganizationUpdateIn(Schema):
    name: str | None = Field(default=None, max_length=200)
    default_timezone: str | None = Field(default=None, max_length=64)
    #: ISO 4217. Changing it relabels every money figure; nothing converts.
    reporting_currency: str | None = Field(default=None, min_length=3, max_length=8)
    is_active: bool | None = None


class MemberOut(Schema):
    user: UserOut
    role: Role
    created_at: dt.datetime
    #: Sites this member is restricted to. Empty means the whole organisation.
    site_ids: list[uuid.UUID] = Field(default_factory=list)


class MemberInviteIn(Schema):
    email: EmailStr
    role: Role = Role.VIEWER


class MemberRoleIn(Schema):
    role: Role
    #: Restrict this member to these sites and their subtrees. ``null`` leaves
    #: the current scope alone; ``[]`` clears it back to the whole
    #: organisation. The distinction matters - a client that always sent the
    #: field would otherwise wipe a scope every time it changed a role.
    site_ids: list[uuid.UUID] | None = None


# --------------------------------------------------------------------------
# API keys
# --------------------------------------------------------------------------
class ApiKeyOut(Schema):
    id: uuid.UUID
    name: str
    prefix: str
    role: Role
    is_active: bool
    expires_at: dt.datetime | None = None
    revoked_at: dt.datetime | None = None
    last_used_at: dt.datetime | None = None
    created_at: dt.datetime


class ApiKeyCreateIn(Schema):
    name: str = Field(max_length=120)
    role: Role = Role.VIEWER
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyCreatedOut(Schema):
    key: ApiKeyOut
    # Returned exactly once; the server only stores a hash.
    secret: str


MeOut.model_rebuild()
