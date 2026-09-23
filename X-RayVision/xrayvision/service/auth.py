"""
帳號、登入與權限 (規劃書第 8 節：操作員／工程師／管理員三級)

- 帳號為產品內建，與 Windows 帳號無關；由系統管理員建立與停用。
- 密碼以 scrypt 雜湊保存 (含隨機鹽值)；長度至少 8 字元。
- 連續登入失敗 5 次鎖定 5 分鐘。
- 登入後發給工作階段權杖 (HttpOnly Cookie)；閒置 12 小時失效。資料庫只保存權杖的雜湊值。
- 首次啟動沒有任何帳號時，只允許建立第一個系統管理員。
- 權限於後端逐一檢查；前端依權限清單隱藏功能，僅為便利。
"""
import base64
import hashlib
import hmac
import secrets
import time

from ..store.db import now

ROLES = ("operator", "engineer", "admin")
MIN_PASSWORD = 8
MAX_FAILED = 5
LOCK_SECONDS = 300
SESSION_IDLE_SECONDS = 12 * 3600
COOKIE = "xrv_session"

# 權限 → 最低角色
PERMISSIONS = {
    "view": "operator",                 # 檢視總覽、紀錄、影像、配方、工作、監看狀態
    "import": "operator",               # 上傳影像、重新分析、取消／重新執行工作
    "review": "operator",               # 人工複判
    "import_path": "engineer",          # 以本機路徑匯入 (工程用)
    "recipe_edit": "engineer",          # 建立、修改、發布、停用配方
    "watch_manage": "engineer",         # 管理監看資料夾
    "diagnostics": "engineer",          # 匯出問題回報包
    "audit_view": "engineer",           # 檢視稽核紀錄
    "annotate": "engineer",             # 標註空洞、匯出訓練資料
    "user_manage": "admin",             # 帳號管理
    "settings": "admin",                # 系統設定、資料保留
    "license": "admin",                 # 授權
    "update": "admin",                  # 軟體更新與退版
}
_RANK = {r: i for i, r in enumerate(ROLES)}


class AuthError(Exception):
    def __init__(self, status, code, detail=""):
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail


def permissions_of(role):
    return sorted(p for p, r in PERMISSIONS.items() if _RANK[role] >= _RANK[r])


def allowed(role, perm):
    return _RANK.get(role, -1) >= _RANK[PERMISSIONS[perm]]


# ---------------------------------------------------------------------------
# 密碼
# ---------------------------------------------------------------------------
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(pw, stored):
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(base64.b64decode(h)))
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def check_password_policy(pw):
    if len(pw or "") < MIN_PASSWORD:
        raise AuthError(400, "password_too_short", str(MIN_PASSWORD))


# ---------------------------------------------------------------------------
# 帳號
# ---------------------------------------------------------------------------
def _ts(offset=0):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + offset))


def public_user(u):
    return dict(id=u["id"], username=u["username"], display_name=u["display_name"], role=u["role"],
                active=bool(u["active"]), must_change_password=bool(u["must_change_password"]),
                created_at=u["created_at"], last_login_at=u["last_login_at"],
                locked=bool(u["locked_until"] and u["locked_until"] > now()))


def user_count(db):
    return db.one("SELECT COUNT(*) AS n FROM users")["n"]


def create_user(db, username, display_name, role, password, actor, must_change=True):
    username = (username or "").strip()
    if not username or len(username) > 64:
        raise AuthError(400, "invalid_username")
    if role not in ROLES:
        raise AuthError(400, "invalid_role", role)
    check_password_policy(password)
    if db.one("SELECT id FROM users WHERE username = ?", (username,)):
        raise AuthError(409, "username_exists", username)
    uid = db.insert("users", username=username, display_name=(display_name or username).strip()[:64], role=role,
                    password_hash=hash_password(password), active=1, must_change_password=int(must_change),
                    created_at=now(), created_by=actor)
    db.audit(actor, "user.create", "user", uid, username=username, role=role)
    return public_user(db.one("SELECT * FROM users WHERE id = ?", (uid,)))


def setup_first_admin(db, username, display_name, password):
    """首次啟動：尚無任何帳號時建立第一個系統管理員"""
    if user_count(db) > 0:
        raise AuthError(409, "setup_already_done")
    return create_user(db, username, display_name, "admin", password, "setup", must_change=False)


def update_user(db, uid, actor, role=None, active=None, display_name=None):
    u = db.one("SELECT * FROM users WHERE id = ?", (uid,))
    if u is None:
        raise AuthError(404, "user_not_found", uid)
    changes = {}
    if role is not None and role != u["role"]:
        if role not in ROLES:
            raise AuthError(400, "invalid_role", role)
        changes["role"] = role
    if active is not None and int(active) != u["active"]:
        changes["active"] = int(active)
    if display_name is not None:
        changes["display_name"] = display_name.strip()[:64] or u["username"]
    # 不可讓系統失去最後一個啟用中的管理員
    if u["role"] == "admin" and (changes.get("role", "admin") != "admin" or changes.get("active", 1) == 0):
        n = db.one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = 1")["n"]
        if n <= 1:
            raise AuthError(409, "last_admin")
    for k, v in changes.items():
        db.execute(f"UPDATE users SET {k} = ? WHERE id = ?", (v, uid))
    if changes.get("active") == 0 or "role" in changes:
        db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
    if changes:
        db.audit(actor, "user.update", "user", uid, **changes)
    return public_user(db.one("SELECT * FROM users WHERE id = ?", (uid,)))


def reset_password(db, uid, new_password, actor):
    """管理員重設密碼：使用者下次登入須變更密碼，並解除鎖定"""
    check_password_policy(new_password)
    if db.one("SELECT id FROM users WHERE id = ?", (uid,)) is None:
        raise AuthError(404, "user_not_found", uid)
    db.execute("UPDATE users SET password_hash = ?, must_change_password = 1, failed_attempts = 0, locked_until = NULL "
               "WHERE id = ?", (hash_password(new_password), uid))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
    db.audit(actor, "user.reset_password", "user", uid)


def change_password(db, uid, old, new):
    u = db.one("SELECT * FROM users WHERE id = ?", (uid,))
    if u is None or not verify_password(old, u["password_hash"]):
        raise AuthError(400, "wrong_password")
    check_password_policy(new)
    if old == new:
        raise AuthError(400, "password_unchanged")
    db.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?", (hash_password(new), uid))
    db.audit(u["username"], "user.change_password", "user", uid)


# ---------------------------------------------------------------------------
# 登入與工作階段
# ---------------------------------------------------------------------------
def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(db, username, password):
    u = db.one("SELECT * FROM users WHERE username = ?", ((username or "").strip(),))
    if u is None:
        db.audit(username or "?", "auth.login_failed", "user", "", reason="unknown_user")
        raise AuthError(401, "invalid_credentials")
    if not u["active"]:
        db.audit(u["username"], "auth.login_failed", "user", u["id"], reason="inactive")
        raise AuthError(401, "invalid_credentials")
    if u["locked_until"] and u["locked_until"] > now():
        raise AuthError(423, "account_locked", u["locked_until"])
    if not verify_password(password or "", u["password_hash"]):
        n = u["failed_attempts"] + 1
        locked = _ts(LOCK_SECONDS) if n >= MAX_FAILED else None
        db.execute("UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                   (0 if locked else n, locked, u["id"]))
        db.audit(u["username"], "auth.login_failed", "user", u["id"], reason="wrong_password", locked=bool(locked))
        raise AuthError(423 if locked else 401, "account_locked" if locked else "invalid_credentials", locked or "")
    token = secrets.token_urlsafe(32)
    db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
               (now(), u["id"]))
    db.insert("sessions", token_hash=_token_hash(token), user_id=u["id"], created_at=now(),
              expires_at=_ts(SESSION_IDLE_SECONDS), last_seen_at=now())
    db.audit(u["username"], "auth.login", "user", u["id"])
    return token, public_user(db.one("SELECT * FROM users WHERE id = ?", (u["id"],)))


def logout(db, token):
    s = session_user(db, token, touch=False)
    db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token or ""),))
    if s:
        db.audit(s["username"], "auth.logout", "user", s["id"])


def session_user(db, token, touch=True):
    """回傳有效工作階段的使用者 (dict)，否則 None；有效時延長閒置期限"""
    if not token:
        return None
    th = _token_hash(token)
    s = db.one("SELECT * FROM sessions WHERE token_hash = ?", (th,))
    if s is None:
        return None
    if s["expires_at"] < now():
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (th,))
        return None
    u = db.one("SELECT * FROM users WHERE id = ?", (s["user_id"],))
    if u is None or not u["active"]:
        return None
    if touch:
        db.execute("UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
                   (now(), _ts(SESSION_IDLE_SECONDS), th))
    return u
