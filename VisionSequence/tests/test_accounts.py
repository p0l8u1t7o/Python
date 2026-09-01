"""帳號、流程擁有者、引擎鎖定。"""

from __future__ import annotations

import json
import time

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accounts.models import EngineLock
from apps.vision.models import Flow, ImageSource
from apps.vision.runner import runner
from apps.vision.tcp_server import handle_command


def graph_for(source_id: int) -> dict:
    return {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": source_id}},
            {"id": "j", "type": "judge", "params": {"verdict": "ok"}},
        ],
        "edges": [],
    }


class AccountsTests(TestCase):
    def setUp(self):
        for fid in list(runner._runtimes):
            runner.forget(fid)
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 160, "height": 120})

    # -- helpers ----------------------------------------------------------
    def post(self, path, body=None, token=None, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.post(path, data=json.dumps(body or {}), content_type="application/json", **headers, **extra)

    def get(self, path, token=None, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.get(path, **headers, **extra)

    def setup_admin(self):
        r = self.post("/api/auth/setup", {"username": "admin", "password": "secret1"})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["token"]

    def make_user(self, admin_token, name="alice", is_staff=False):
        r = self.post("/api/users", {"username": name, "password": "pass123", "is_staff": is_staff}, token=admin_token)
        self.assertEqual(r.status_code, 201, r.content)
        r = self.post("/api/auth/login", {"username": name, "password": "pass123"})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["token"]

    # -- auth -------------------------------------------------------------
    def test_bootstrap_then_setup_then_login(self):
        self.assertTrue(self.get("/api/auth/status").json()["setup_required"])
        # 尚無使用者：放行為 bootstrap，讓前端能呼叫 setup
        self.assertEqual(self.get("/api/vision/capacity").status_code, 200)
        token = self.setup_admin()
        self.assertEqual(self.post("/api/auth/setup", {"username": "x", "password": "secret1"}).status_code, 409)
        # 有使用者之後，沒帶權杖就 401
        self.assertEqual(self.get("/api/vision/capacity").status_code, 401)
        me = self.get("/api/auth/me", token=token).json()
        self.assertEqual(me["user"]["username"], "admin")
        self.assertTrue(me["is_admin"])
        self.assertEqual(self.post("/api/auth/login", {"username": "admin", "password": "wrong"}).status_code, 401)
        self.assertEqual(self.post("/api/auth/logout", token=token).status_code, 200)
        self.assertEqual(self.get("/api/auth/me", token=token).status_code, 401)

    def test_token_in_query_for_images_and_stream(self):
        token = self.setup_admin()
        self.assertEqual(self.get(f"/api/vision/sources/{self.source.id}/preview?max=50").status_code, 401)
        self.assertEqual(self.get(f"/api/vision/sources/{self.source.id}/preview?max=50&token={token}").status_code, 200)
        r = self.get(f"/api/vision/events?since=0&max_seconds=0.1&token={token}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.get("/api/vision/events?since=0&max_seconds=0.1").status_code, 401)

    def test_user_management_requires_admin(self):
        admin = self.setup_admin()
        alice = self.make_user(admin)
        self.assertEqual(self.get("/api/users", token=alice).status_code, 403)
        self.assertEqual(self.get("/api/users", token=admin).status_code, 200)
        uid = User.objects.get(username="alice").id
        r = self.client.patch(f"/api/users/{uid}", data=json.dumps({"is_active": False}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {admin}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.get("/api/auth/me", token=alice).status_code, 401)  # 停用即失效
        admin_id = User.objects.get(username="admin").id
        self.assertEqual(self.client.delete(f"/api/users/{admin_id}", HTTP_AUTHORIZATION=f"Bearer {admin}").status_code, 422)
        self.assertEqual(self.post("/api/users", {"username": "alice", "password": "pass123"}, token=admin).status_code, 409)
        self.assertEqual(self.post("/api/users", {"username": "bob", "password": "12"}, token=admin).status_code, 422)

    def test_ui_prefs_roundtrip(self):
        """主題偏好：登入者 PATCH /auth/prefs 儲存 → /auth/me 帶回；非法主題 422、bootstrap 沒使用者 422。"""
        # bootstrap（還沒有任何使用者）：沒有 user 可存
        r = self.client.patch("/api/auth/prefs", data='{"theme": "cyber"}', content_type="application/json")
        self.assertEqual(r.status_code, 422, r.content)
        token = self.setup_admin()
        r = self.get("/api/auth/me", token=token)
        self.assertEqual(r.json()["prefs"], {})
        r = self.client.patch("/api/auth/prefs", data='{"theme": "cyber"}', content_type="application/json",
                              HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["prefs"]["theme"], "cyber")
        r = self.get("/api/auth/me", token=token)
        self.assertEqual(r.json()["prefs"]["theme"], "cyber")
        # 換主題會覆蓋、非法主題擋下
        r = self.client.patch("/api/auth/prefs", data='{"theme": "dark"}', content_type="application/json",
                              HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.json()["prefs"]["theme"], "dark")
        r = self.client.patch("/api/auth/prefs", data='{"theme": "rainbow"}', content_type="application/json",
                              HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(r.status_code, 422)
        # 各使用者各自一份
        alice = self.make_user(token)
        r = self.get("/api/auth/me", token=alice)
        self.assertEqual(r.json()["prefs"], {})

    def test_change_password(self):
        token = self.setup_admin()
        self.assertEqual(self.post("/api/auth/password", {"old_password": "bad", "new_password": "newpass1"}, token=token).status_code, 400)
        self.assertEqual(self.post("/api/auth/password", {"old_password": "secret1", "new_password": "newpass1"}, token=token).status_code, 200)
        self.assertEqual(self.post("/api/auth/login", {"username": "admin", "password": "newpass1"}).status_code, 200)

    # -- ownership ---------------------------------------------------------
    def test_flows_are_per_user(self):
        admin = self.setup_admin()
        alice = self.make_user(admin, "alice")
        bob = self.make_user(admin, "bob")
        r = self.post("/api/vision/flows", {"name": "alice-flow", "graph": graph_for(self.source.id)}, token=alice)
        self.assertEqual(r.status_code, 201)
        fid = r.json()["id"]
        self.assertEqual(r.json()["owner_name"], "alice")
        shared = Flow.objects.create(name="shared", graph=graph_for(self.source.id))
        # bob 看不到 alice 的，看得到共用的
        r = self.get("/api/vision/flows", token=bob)
        self.assertEqual(r.status_code, 200, r.content)
        names = {f["name"] for f in r.json()["items"]}
        self.assertEqual(names, {"shared"})
        self.assertEqual(self.get(f"/api/vision/flows/{fid}", token=bob).status_code, 404)
        self.assertEqual(self.client.patch(f"/api/vision/flows/{fid}", data=json.dumps({"description": "x"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {bob}").status_code, 403)
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/preview", {"graph": graph_for(self.source.id)}, token=bob).status_code, 404)
        # 共用流程可試跑（看得到就能試），但不能改
        self.assertEqual(self.post(f"/api/vision/flows/{shared.id}/preview", {"graph": graph_for(self.source.id)}, token=bob).status_code, 200)
        # 共用流程一般使用者不能改，管理員可以
        self.assertEqual(self.client.patch(f"/api/vision/flows/{shared.id}", data=json.dumps({"description": "x"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {bob}").status_code, 403)
        self.assertEqual(self.client.patch(f"/api/vision/flows/{shared.id}", data=json.dumps({"description": "x"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {admin}").status_code, 200)
        # 管理員看全部；?mine=1 只看自己的
        self.assertEqual(self.get("/api/vision/flows", token=admin).json()["total"], 2)
        self.assertEqual(self.get("/api/vision/flows?mine=true", token=alice).json()["total"], 1)
        # alice 自己可執行、可複製（副本歸自己）
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/run", {}, token=alice).status_code, 200)
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/duplicate", token=alice).json()["owner_name"], "alice")
        # 刪除使用者 → 流程變共用
        uid = User.objects.get(username="alice").id
        self.assertEqual(self.client.delete(f"/api/users/{uid}", HTTP_AUTHORIZATION=f"Bearer {admin}").status_code, 204)
        self.assertIsNone(Flow.objects.get(pk=fid).owner_id)

    # -- lock --------------------------------------------------------------
    @override_settings(VISION={**settings.VISION, "API_KEY": "integrator-key"})
    def test_engine_lock_blocks_users_but_not_integrator(self):
        admin = self.setup_admin()
        alice = self.make_user(admin, "alice")
        fid = self.post("/api/vision/flows", {"name": "f", "graph": graph_for(self.source.id)}, token=alice).json()["id"]
        # 使用者啟動連續模式，整合方上鎖後應被停掉
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/continuous", {"running": True}, token=alice).status_code, 200)
        self.assertTrue(runner.is_continuous(fid))
        # 一般使用者不能上鎖
        self.assertEqual(self.post("/api/vision/lock", {"reason": "x"}, token=alice).status_code, 403)
        r = self.client.post("/api/vision/lock", data=json.dumps({"reason": "產線量產中", "ttl_s": 3600}), content_type="application/json", HTTP_X_API_KEY="integrator-key")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["locked"])
        self.assertEqual(r.json()["holder"], "integrator")
        time.sleep(0.2)
        self.assertFalse(runner.is_continuous(fid))
        # 使用者：可編輯、不可執行
        self.assertEqual(self.client.patch(f"/api/vision/flows/{fid}", data=json.dumps({"description": "edit ok"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {alice}").status_code, 200)
        for path, body in ((f"/api/vision/flows/{fid}/run", {}), (f"/api/vision/flows/{fid}/preview", {"graph": graph_for(self.source.id)}), (f"/api/vision/flows/{fid}/continuous", {"running": True})):
            r = self.post(path, body, token=alice)
            self.assertEqual(r.status_code, 423, (path, r.content))
            self.assertEqual(r.json()["error"]["code"], "engine_locked")
        # 管理員也不能執行（硬體留給整合方）
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/run", {}, token=admin).status_code, 423)
        # 整合方可以：HTTP 與 TCP
        r = self.client.post(f"/api/vision/flows/{fid}/run", data=json.dumps({}), content_type="application/json", HTTP_X_API_KEY="integrator-key")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(handle_command("RUN f")["ok"])
        # 狀態所有人可看
        self.assertTrue(self.get("/api/vision/lock", token=alice).json()["locked"])
        self.assertTrue(self.get("/api/auth/me", token=alice).json()["lock"]["locked"])
        # 使用者不能解鎖；整合方可以
        self.assertEqual(self.client.delete("/api/vision/lock", HTTP_AUTHORIZATION=f"Bearer {alice}").status_code, 403)
        self.assertEqual(self.client.delete("/api/vision/lock", HTTP_X_API_KEY="integrator-key").status_code, 200)
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/run", {}, token=alice).status_code, 200)

    def test_admin_lock_and_expiry(self):
        admin = self.setup_admin()
        alice = self.make_user(admin, "alice")
        fid = self.post("/api/vision/flows", {"name": "f", "graph": graph_for(self.source.id)}, token=alice).json()["id"]
        self.assertEqual(self.post("/api/vision/lock", {"reason": "維護", "ttl_s": 1}, token=admin).status_code, 200)
        # 持有者自己能執行
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/run", {}, token=admin).status_code, 200)
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/run", {}, token=alice).status_code, 423)
        lock = EngineLock.objects.get(pk=1)
        from datetime import timedelta

        lock.expires_at = lock.expires_at - timedelta(seconds=5)
        lock.save()
        self.assertFalse(self.get("/api/vision/lock", token=alice).json()["locked"])  # 自動過期
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/run", {}, token=alice).status_code, 200)
