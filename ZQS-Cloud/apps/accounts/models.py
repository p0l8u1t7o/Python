"""Users, organisations (tenants), role membership and API keys."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel, UUIDPrimaryKeyModel


class Role(models.TextChoices):
    """Ordered from most to least privileged; see :data:`ROLE_RANK`."""

    OWNER = "owner", _("Owner")
    ADMIN = "admin", _("Administrator")
    OPERATOR = "operator", _("Operator")
    VIEWER = "viewer", _("Viewer")


#: Higher rank implies every permission of the lower ranks.
ROLE_RANK: dict[str, int] = {
    Role.OWNER: 40,
    Role.ADMIN: 30,
    Role.OPERATOR: 20,
    Role.VIEWER: 10,
}


class Theme(models.TextChoices):
    SYSTEM = "system", _("Follow system")
    LIGHT = "light", _("Light")
    DARK = "dark", _("Dark")


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if not extra["is_staff"] or not extra["is_superuser"]:
            raise ValueError("Superuser must have is_staff and is_superuser set")
        return self._create_user(email, password, **extra)


class User(UUIDPrimaryKeyModel, AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=40, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # UI preferences persisted server-side so they follow the user across devices.
    language = models.CharField(max_length=16, default="en")
    theme = models.CharField(max_length=16, choices=Theme.choices, default=Theme.SYSTEM)
    timezone_name = models.CharField(max_length=64, default="UTC")

    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    # Bumping this invalidates every previously issued access/refresh token.
    token_version = models.PositiveIntegerField(default=1)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "accounts_user"
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    @property
    def display_name(self) -> str:
        return self.full_name or self.email.split("@")[0]

    def bump_token_version(self) -> None:
        User.objects.filter(pk=self.pk).update(token_version=models.F("token_version") + 1)
        self.refresh_from_db(fields=["token_version"])


class Organization(UUIDPrimaryKeyModel, TimeStampedModel):
    """Tenant boundary. Every device, site and alert belongs to exactly one."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)
    default_timezone = models.CharField(max_length=64, default="UTC")
    #: The currency every money figure in this tenant is reported in.
    #:
    #: One per organisation, not one per tariff. Currency scattered across
    #: tariffs means a site with no tariff yet has no currency at all, and its
    #: costs render as bare numbers next to properly labelled ones - which is
    #: how the same column ends up showing "0" and "$0" in adjacent rows.
    #:
    #: Deliberately not a conversion mechanism. Exchange rates have a time
    #: dimension, a buy/sell spread and an accounting policy behind them; that
    #: is another system's job. This says what the numbers already are.
    reporting_currency = models.CharField(
        max_length=8,
        default="TWD",
        help_text="ISO 4217. Every tariff in this organization must match it.",
    )
    # Free-form tenant settings (branding, notification defaults, ...).
    settings = models.JSONField(default=dict, blank=True)

    # through_fields is required because Membership also has an `invited_by`
    # FK to User, which would otherwise make the join ambiguous.
    members = models.ManyToManyField(
        User,
        through="Membership",
        through_fields=("organization", "user"),
        related_name="organizations",
    )

    class Meta:
        db_table = "accounts_organization"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Membership(TimeStampedModel):
    """A user's role in one organisation, and optionally in only part of it.

    Access used to have two dimensions - which tenant, which role - and that
    is enough right up until a contractor needs to see the Taoyuan plant and
    nothing else. :attr:`sites` is the third dimension.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    #: Sites this membership may see. **Empty means the whole organisation** -
    #: which is what every existing membership is, so adding this field
    #: changed nobody's access.
    #:
    #: Naming a site grants its whole subtree: someone given "Taoyuan plant"
    #: gets its workshops and lines too, because a person responsible for a
    #: plant is responsible for what is inside it. The expansion happens once
    #: per request in :class:`~apps.accounts.security.AuthContext`.
    #:
    #: Scoping never *raises* privilege. It intersects with the role, so a
    #: viewer restricted to one site is still a viewer there.
    sites = models.ManyToManyField(
        "devices.Site",
        blank=True,
        related_name="scoped_memberships",
        help_text="Empty means every site in the organization.",
    )
    invited_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "accounts_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"], name="uniq_membership_org_user"
            )
        ]
        indexes = [models.Index(fields=["user", "organization"])]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.organization_id}:{self.role}"

    @property
    def rank(self) -> int:
        return ROLE_RANK.get(self.role, 0)


class UserPreference(TimeStampedModel):
    """A scrap of console state that belongs to one person.

    Distinct from the columns on :class:`User` - ``theme``, ``language``,
    ``timezone_name`` - which the API itself reads and which every client has
    to honour. Nothing on the server reads *these*; they exist so a layout
    someone arranged follows them to another machine instead of living in one
    browser's localStorage.

    Free-form keys rather than a column per feature. The alternative is a
    migration every time a page grows a toggle, and none of those columns
    would mean anything to the backend either.

    Two limits are enforced in the API rather than here, because a database
    constraint cannot express them usefully: a cap on rows per user and on the
    size of one value. Without them this is an unbounded write-anything store
    attached to every session.
    """

    #: Keys are namespaced by the feature that owns them, e.g.
    #: ``device-metrics:<device uuid>`` or ``dashboard-view``.
    KEY_PATTERN = r"^[a-z][a-z0-9-]{0,31}(:[A-Za-z0-9_.-]{1,64})?$"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ui_preferences"
    )
    key = models.CharField(max_length=100)
    value = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "accounts_user_preference"
        ordering = ["key"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key"], name="uniq_user_preference_key"
            )
        ]
        indexes = [models.Index(fields=["user", "key"])]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.key}"


class ApiKeyQuerySet(models.QuerySet):
    def active(self):
        now = timezone.now()
        return self.filter(revoked_at__isnull=True).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )


class ApiKey(UUIDPrimaryKeyModel, TimeStampedModel):
    """Machine credential for server-to-server access (BI jobs, SCADA bridges).

    The full secret is shown once at creation; only a hash is stored. The
    ``prefix`` gives a cheap indexed lookup before the constant-time compare.
    """

    PREFIX_LENGTH = 12
    SECRET_LENGTH = 32

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="api_keys"
    )
    name = models.CharField(max_length=120)
    prefix = models.CharField(max_length=16, unique=True, db_index=True)
    hashed_secret = models.CharField(max_length=256)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    objects = ApiKeyQuerySet.as_manager()

    class Meta:
        db_table = "accounts_api_key"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix})"

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    @classmethod
    def generate(cls, **kwargs) -> tuple["ApiKey", str]:
        """Create a key and return ``(instance, plaintext)``."""
        prefix = secrets.token_hex(cls.PREFIX_LENGTH // 2)
        secret = secrets.token_urlsafe(cls.SECRET_LENGTH)
        instance = cls(
            prefix=prefix, hashed_secret=make_password(secret), **kwargs
        )
        instance.save()
        return instance, f"zqs_{prefix}.{secret}"

    def verify(self, secret: str) -> bool:
        return check_password(secret, self.hashed_secret)


class RefreshToken(TimeStampedModel):
    """Server-side refresh token registry so sessions can be revoked.

    Only the SHA-256 of the JWT id is stored - enough to look up and revoke,
    useless to an attacker who reads the table.
    """

    jti = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    # Set when this token is exchanged, so replay of an old token is detectable.
    replaced_by = models.CharField(max_length=64, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "accounts_refresh_token"
        ordering = ["-created_at"]

    @staticmethod
    def hash_jti(raw_jti: str) -> str:
        return hashlib.sha256(raw_jti.encode()).hexdigest()

    @property
    def is_valid(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()

    def revoke(self, *, replaced_by: str = "") -> None:
        self.revoked_at = timezone.now()
        self.replaced_by = replaced_by
        self.save(update_fields=["revoked_at", "replaced_by"])

    @classmethod
    def purge_expired(cls, older_than: dt.timedelta = dt.timedelta(days=30)) -> int:
        cutoff = timezone.now() - older_than
        deleted, _ = cls.objects.filter(expires_at__lt=cutoff).delete()
        return deleted
