"""帳號與引擎鎖定 API。

POST   /auth/setup            系統沒有任何使用者時建立第一個管理員（之後 409）
POST   /auth/login            {username, password} → {token, user}
POST   /auth/logout
GET    /auth/me
POST   /auth/password         {old_password, new_password}
GET    /users                 管理員
POST   /users                 管理員 {username, password, is_staff, display_name}
PATCH  /users/{id}            管理員 {password?, is_staff?, is_active?, display_name?}
DELETE /users/{id}            管理員（不能刪自己）；其流程改為共用（owner=null）
GET    /vision/lock           鎖定狀態（所有人）
PATCH  /auth/profile          自己的顯示名稱 {display_name}
POST   /vision/lock           整合方或管理員 {reason?, ttl_s?}
DELETE /vision/lock           整合方、管理員或持有者
"""

from __future__ import annotations


from django.contrib.auth import authenticate as dj_authenticate
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema

from apps.accounts import permissions
from apps.accounts.models import DEFAULT_ROLE, ROLES, AuthToken, EngineLock, RolePermission, UserPref, hash_token
from apps.accounts.security import principal, require_admin
from apps.core import audit
from apps.core.errors import APIError, Conflict, NotFound, ValidationError

router = Router(tags=["auth"])
users_router = Router(tags=["users"])
lock_router = Router(tags=["lock"])


class LoginIn(Schema):
    username: str
    password: str


class SetupIn(Schema):
    username: str
    password: str
    display_name: str = ""


class PasswordIn(Schema):
    old_password: str
    new_password: str


#: 前端可選的主題風格（封閉集合；前端 ThemeProvider 的 THEME 清單同步）。
UI_THEMES = ("light", "dark", "system", "cyber")


class PrefsIn(Schema):
    theme: str | None = None


class ProfileIn(Schema):
    display_name: str


def _prefs(user: User | None) -> dict:
    if user is None:
        return {}
    row = UserPref.objects.filter(user=user).first()
    return dict(row.ui or {}) if row else {}


class UserIn(Schema):
    username: str
    password: str
    #: admin | engineer | operator；舊的 is_staff 仍可用（True＝admin），兩者都給時以 role 為準。
    role: str | None = None
    is_staff: bool = False
    display_name: str = ""


class UserPatch(Schema):
    password: str | None = None
    role: str | None = None
    is_staff: bool | None = None
    is_active: bool | None = None
    display_name: str | None = None


class LockIn(Schema):
    reason: str = ""
    ttl_s: int | None = None


def role_of(user: User) -> str:
    """使用者的角色；admin 以 User.is_staff 為準（Django admin 也看它）。"""
    if user.is_staff:
        return "admin"
    pref = getattr(user, "pref", None)
    role = getattr(pref, "role", "") or DEFAULT_ROLE
    return role if role in ROLES else DEFAULT_ROLE


def set_role(user: User, role: str) -> None:
    """設定角色：admin 同步寫回 is_staff，其餘存在 UserPref。"""
    if role not in ROLES:
        raise ValidationError(f"role must be one of {', '.join(ROLES)}", code="bad_role")
    if user.is_staff != (role == "admin"):
        user.is_staff = role == "admin"
        user.save(update_fields=["is_staff"])
    pref, _ = UserPref.objects.get_or_create(user=user)
    if pref.role != role:
        pref.role = role
        pref.save(update_fields=["role", "updated_at"])


def user_out(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.first_name,
        "role": role_of(user),
        "is_staff": user.is_staff,
        "is_active": user.is_active,
        "created_at": user.date_joined.isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


def _check_password(pw: str) -> None:
    if len(pw) < 6:
        raise ValidationError("A password needs at least 6 characters", code="weak_password")


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
@router.post("/setup", auth=None, response={201: dict})
def setup(request: HttpRequest, payload: SetupIn):
    if User.objects.exists():
        raise Conflict("The system already has users", code="already_setup")
    _check_password(payload.password)
    user = User.objects.create_user(username=payload.username.strip(), password=payload.password, is_staff=True, is_superuser=True, first_name=payload.display_name)
    token = AuthToken.issue(user, user_agent=request.META.get("HTTP_USER_AGENT", ""))
    return 201, {"token": token, "user": user_out(user)}


@router.get("/status", auth=None)
def status(request: HttpRequest):
    """登入頁用：系統是否已初始化。"""
    return {"setup_required": not User.objects.exists()}


@router.post("/login", auth=None)
def login(request: HttpRequest, payload: LoginIn):
    user = dj_authenticate(request, username=payload.username.strip(), password=payload.password)
    if user is None or not user.is_active:
        raise APIError("Wrong username or password", code="bad_credentials", status_code=401)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    token = AuthToken.issue(user, user_agent=request.META.get("HTTP_USER_AGENT", ""))
    return {"token": token, "user": user_out(user)}


@router.post("/logout")
def logout(request: HttpRequest):
    p = principal(request)
    if p.token:
        AuthToken.revoke(p.token)
    return {"ok": True}


@router.get("/me")
def me(request: HttpRequest):
    p = principal(request)
    return {"kind": p.kind, "is_admin": p.is_admin, "role": p.role, "user": user_out(p.user) if p.user else None,
            "permissions": sorted(permissions.allowed(p.role), key=list(permissions.FEATURES).index),
            "prefs": _prefs(p.user), "lock": EngineLock.current().to_dict()}


@router.patch("/prefs")
def patch_prefs(request: HttpRequest, payload: PrefsIn):
    """更新自己的介面偏好（主題風格等）；整合方金鑰沒有使用者，不適用。"""
    p = principal(request)
    if p.user is None:
        raise ValidationError("An API key has no user preferences to save", code="no_user")
    if payload.theme is not None and payload.theme not in UI_THEMES:
        raise ValidationError(f"Unknown theme '{payload.theme}'", code="bad_theme", details={"available": list(UI_THEMES)})
    row, _ = UserPref.objects.get_or_create(user=p.user)
    ui = dict(row.ui or {})
    if payload.theme is not None:
        ui["theme"] = payload.theme
    row.ui = ui
    row.save(update_fields=["ui", "updated_at"])
    return {"prefs": ui}


@router.patch("/profile")
def patch_profile(request: HttpRequest, payload: ProfileIn):
    """改自己的顯示名稱。帳號名稱與角色不在這裡——那是管理員在使用者頁做的事。"""
    p = principal(request)
    if p.user is None:
        raise APIError("An API key has no profile to change", code="not_a_user", status_code=400)
    name = payload.display_name.strip()[:150]
    before = p.user.first_name
    if name != before:
        p.user.first_name = name
        p.user.save(update_fields=["first_name"])
        audit.record(request, "user.update", p.user, summary=f"display_name: {before or '—'} → {name or '—'}",
                     detail={"display_name": {"before": before, "after": name}})
    return user_out(p.user)


@router.post("/password")
def change_password(request: HttpRequest, payload: PasswordIn):
    p = principal(request)
    if p.user is None:
        raise APIError("This identity has no password", code="not_a_user", status_code=400)
    if not p.user.check_password(payload.old_password):
        raise APIError("The current password is wrong", code="bad_credentials", status_code=400)
    _check_password(payload.new_password)
    p.user.set_password(payload.new_password)
    p.user.save()
    AuthToken.objects.filter(user=p.user).exclude(token_hash=hash_token(p.token)).delete()
    return {"ok": True}


# ---------------------------------------------------------------------------
# users（管理員）
# ---------------------------------------------------------------------------
@users_router.get("")
def list_users(request: HttpRequest):
    require_admin(request)
    return {"items": [user_out(u) for u in User.objects.select_related("pref").order_by("username")], "roles": list(ROLES)}


@users_router.post("", response={201: dict})
def create_user(request: HttpRequest, payload: UserIn):
    require_admin(request)
    _check_password(payload.password)
    role = payload.role or ("admin" if payload.is_staff else DEFAULT_ROLE)
    if role not in ROLES:
        raise ValidationError(f"role must be one of {', '.join(ROLES)}", code="bad_role")
    try:
        with transaction.atomic():
            user = User.objects.create_user(username=payload.username.strip(), password=payload.password, is_staff=role == "admin", first_name=payload.display_name)
            UserPref.objects.create(user=user, role=role)
    except IntegrityError:
        raise Conflict("That username is taken", code="username_taken") from None
    audit.record(request, "user.create", user, summary=f"role {role}")
    return 201, user_out(user)


# ---------------------------------------------------------------------------
# 角色權限（管理員）
# ---------------------------------------------------------------------------
class RolePermissionIn(Schema):
    role: str
    features: list[str]


@users_router.get("/permissions")
def get_permissions(request: HttpRequest):
    """勾選畫面要的三份資料：功能清單（含出廠值）、目前的勾選、可調整的角色。"""
    require_admin(request)
    return {"features": permissions.catalogue(), "matrix": permissions.matrix(), "roles": list(permissions.EDITABLE_ROLES)}


@users_router.patch("/permissions")
def patch_permissions(request: HttpRequest, payload: RolePermissionIn):
    """改一個角色的功能。管理員不能被改（改了就沒人救得回來）。"""
    require_admin(request)
    if payload.role not in permissions.EDITABLE_ROLES:
        raise ValidationError(f"role must be one of {', '.join(permissions.EDITABLE_ROLES)}", code="bad_role")
    features = permissions.clean(payload.features)
    before = sorted(permissions.allowed(payload.role))
    row, _ = RolePermission.objects.get_or_create(role=payload.role)
    row.features = features
    row.save(update_fields=["features", "updated_at"])
    added = [f for f in features if f not in before]
    removed = [f for f in before if f not in features]
    audit.record(request, "role.permissions", target_type="role", target_name=payload.role,
                 summary=", ".join([f"+{f}" for f in added] + [f"-{f}" for f in removed]) or "no change",
                 detail={"before": before, "after": features})
    return {"role": payload.role, "features": features}


def _get_user(user_id: int) -> User:
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise NotFound("User not found", code="user_not_found")
    return user


@users_router.patch("/{user_id}")
def patch_user(request: HttpRequest, user_id: int, payload: UserPatch):
    p = require_admin(request)
    user = _get_user(user_id)
    before = {"role": role_of(user), "is_active": user.is_active, "display_name": user.first_name}
    if payload.password is not None:
        _check_password(payload.password)
        user.set_password(payload.password)
        AuthToken.objects.filter(user=user).delete()
    role = payload.role if payload.role is not None else ("admin" if payload.is_staff else DEFAULT_ROLE) if payload.is_staff is not None else None
    if role is not None:
        if role not in ROLES:
            raise ValidationError(f"role must be one of {', '.join(ROLES)}", code="bad_role")
        if p.user and p.user.id == user.id and role != "admin":
            raise ValidationError("You cannot remove your own administrator role", code="self_demote")
        user.is_staff = role == "admin"
        pref, _ = UserPref.objects.get_or_create(user=user)
        if pref.role != role:
            pref.role = role
            pref.save(update_fields=["role", "updated_at"])
        user.pref = pref  # 反向 OneToOne 會被快取，不更新的話 user_out 會回舊角色
    if payload.is_active is not None:
        if p.user and p.user.id == user.id and not payload.is_active:
            raise ValidationError("You cannot disable your own account", code="self_disable")
        user.is_active = payload.is_active
        if not user.is_active:
            AuthToken.objects.filter(user=user).delete()
    if payload.display_name is not None:
        user.first_name = payload.display_name
    user.save()
    after_role = role if role is not None else before["role"]
    changed = audit.fields_diff(before, {"role": after_role, "is_active": user.is_active, "display_name": user.first_name}, ("role", "is_active", "display_name"))
    if payload.password is not None:
        changed["password"] = {"before": "", "after": "reset"}
    audit.record(request, "user.update", user, summary=audit.summarize_fields(changed), detail=changed)
    return user_out(user)


@users_router.delete("/{user_id}", response={204: None})
def delete_user(request: HttpRequest, user_id: int):
    p = require_admin(request)
    user = _get_user(user_id)
    if p.user and p.user.id == user.id:
        raise ValidationError("You cannot delete your own account", code="self_delete")
    from apps.vision.models import Flow

    Flow.objects.filter(owner=user).update(owner=None)  # owner 只是建立者；流程本身照樣能被工程師維護
    audit.record(request, "user.delete", user, summary=role_of(user))
    user.delete()
    return 204, None


# ---------------------------------------------------------------------------
# engine lock
# ---------------------------------------------------------------------------
@lock_router.get("")
def get_lock(request: HttpRequest):
    return EngineLock.current().to_dict()


@lock_router.post("")
def acquire_lock(request: HttpRequest, payload: LockIn):
    p = principal(request)
    if not p.is_admin:
        raise APIError("Only an integrator (API key) or an administrator can lock the engine", code="permission_denied", status_code=403)
    lock = EngineLock.current()
    holder = "integrator" if p.is_integrator else p.name
    if lock.locked and lock.holder != holder and not p.is_integrator:
        raise Conflict(f"The engine is locked by {lock.holder}", code="already_locked", details=lock.to_dict())
    lock.acquire(holder, payload.reason, payload.ttl_s)
    audit.record(request, "lock.acquire", summary=lock.reason or holder, target_type="engine", target_name=holder)
    return lock.to_dict()


@lock_router.delete("")
def release_lock(request: HttpRequest):
    p = principal(request)
    lock = EngineLock.current()
    if lock.locked and not (p.is_admin or lock.holder == p.name):
        raise APIError("Only an integrator, an administrator or the lock holder can unlock", code="permission_denied", status_code=403)
    lock.release()
    audit.record(request, "lock.release", target_type="engine")
    return lock.to_dict()
