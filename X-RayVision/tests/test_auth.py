"""第 4 階段：帳號、登入、權限"""
import pytest
from fastapi.testclient import TestClient

from xrayvision.config import Settings
from xrayvision.service import auth
from xrayvision.service.api import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=str(tmp_path / "data")), workers=1, watch=False, start=False, enforce_license=False)


def _login(c, u, p):
    return c.post("/api/auth/login", json={"username": u, "password": p})


def test_password_hashing():
    h = auth.hash_password("secret-123")
    assert h.startswith("scrypt$") and "secret-123" not in h
    assert auth.verify_password("secret-123", h) and not auth.verify_password("secret-124", h)
    assert auth.hash_password("secret-123") != h                     # 每次鹽值不同


def test_first_run_setup_then_login_required(app):
    c = TestClient(app)
    st = c.get("/api/auth/state").json()
    assert st["setup_required"] and st["user"] is None
    assert c.get("/api/runs").status_code == 401                    # 未登入
    assert c.get("/api/i18n/zh-TW").status_code == 200              # 語系不需登入 (登入畫面使用)
    r = c.post("/api/auth/setup", json={"username": "admin", "password": "short"})
    assert r.status_code == 400 and r.json()["error"] == "password_too_short"
    r = c.post("/api/auth/setup", json={"username": "admin", "password": "Adm1nPass"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert c.get("/api/runs").status_code == 200                    # 設定後自動登入
    assert c.post("/api/auth/setup", json={"username": "x", "password": "Adm1nPass"}).json()["error"] == "setup_already_done"
    st = c.get("/api/auth/state").json()
    assert not st["setup_required"] and "user_manage" in st["permissions"]
    c.post("/api/auth/logout")
    assert c.get("/api/runs").status_code == 401


def test_roles_and_permissions(app):
    admin = TestClient(app)
    admin.post("/api/auth/setup", json={"username": "admin", "password": "Adm1nPass"})
    r = admin.post("/api/users", json={"username": "op1", "display_name": "作業員一", "role": "operator",
                                       "password": "OpPass123"})
    assert r.status_code == 200 and r.json()["must_change_password"]
    admin.post("/api/users", json={"username": "eng1", "role": "engineer", "password": "EngPass123"})
    assert admin.post("/api/users", json={"username": "OP1", "role": "operator", "password": "OpPass123"}).status_code == 409

    op = TestClient(app)
    assert _login(op, "op1", "OpPass123").status_code == 200
    # 首次登入須先變更密碼
    r = op.get("/api/runs")
    assert r.status_code == 403 and r.json()["error"] == "password_change_required"
    assert op.post("/api/auth/password", json={"old_password": "wrong", "new_password": "NewPass123"}).status_code == 400
    assert op.post("/api/auth/password", json={"old_password": "OpPass123", "new_password": "NewPass123"}).status_code == 200
    assert op.get("/api/runs").status_code == 200
    # 操作員不可編輯配方、管理帳號、看稽核
    r = op.post("/api/recipes", json={"body": {"recipe_id": "x", "version": 1, "modules": []}})
    assert r.status_code == 403 and r.json()["detail"] == "recipe_edit"
    assert op.get("/api/users").status_code == 403
    assert op.get("/api/audit").status_code == 403
    perms = op.get("/api/auth/state").json()["permissions"]
    assert "review" in perms and "recipe_edit" not in perms

    eng = TestClient(app)
    _login(eng, "eng1", "EngPass123")
    eng.post("/api/auth/password", json={"old_password": "EngPass123", "new_password": "EngPass456"})
    assert eng.get("/api/audit").status_code == 200
    assert eng.get("/api/users").status_code == 403
    # 稽核紀錄記錄的是登入帳號
    actions = {(a["actor"], a["action"]) for a in admin.get("/api/audit").json()}
    assert ("admin", "user.create") in actions and ("op1", "auth.login") in actions


def test_lockout_and_admin_protection(app):
    admin = TestClient(app)
    admin.post("/api/auth/setup", json={"username": "admin", "password": "Adm1nPass"})
    admin.post("/api/users", json={"username": "u2", "role": "operator", "password": "U2Pass123"})
    c = TestClient(app)
    for _ in range(4):
        assert _login(c, "u2", "bad").status_code == 401
    r = _login(c, "u2", "bad")
    assert r.status_code == 423 and r.json()["error"] == "account_locked"
    assert _login(c, "u2", "U2Pass123").status_code == 423            # 鎖定期間正確密碼也不行
    uid = [u for u in admin.get("/api/users").json() if u["username"] == "u2"][0]["id"]
    assert admin.post(f"/api/users/{uid}/reset-password", json={"new_password": "Reset1234"}).status_code == 200
    assert _login(c, "u2", "Reset1234").status_code == 200           # 重設後解除鎖定
    # 停用帳號後工作階段立即失效
    admin.patch(f"/api/users/{uid}", json={"active": False})
    assert c.get("/api/auth/state").json()["user"] is None
    # 不可停用或降級最後一個管理員
    me = [u for u in admin.get("/api/users").json() if u["username"] == "admin"][0]["id"]
    r = admin.patch(f"/api/users/{me}", json={"role": "operator"})
    assert r.status_code == 409 and r.json()["error"] == "last_admin"
    assert _login(c, "nobody", "whatever").json()["error"] == "invalid_credentials"


def test_local_reset_password_cli(tmp_path, capsys):
    """忘記密碼的本機救援：一次性密碼、解除鎖定、重新啟用，下次登入須變更密碼"""
    from xrayvision import cli
    data = str(tmp_path / "data")
    c = TestClient(create_app(Settings(data_dir=data), workers=1, watch=False, start=False, enforce_license=False))
    c.post("/api/auth/setup", json={"username": "admin", "password": "Adm1nPass"})
    c.post("/api/auth/logout")
    for _ in range(auth.MAX_FAILED):
        _login(c, "admin", "wrong-pass")
    assert _login(c, "admin", "Adm1nPass").json()["error"] == "account_locked"
    assert cli.main(["reset-password", "nobody", "--data", data]) == 2
    assert cli.main(["reset-password", "admin", "--data", data]) == 0
    pw = capsys.readouterr().out.strip().split(": ", 1)[1]
    r = _login(c, "admin", pw)
    assert r.status_code == 200 and r.json()["user"]["must_change_password"]
