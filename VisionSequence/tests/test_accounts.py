"""帳號、流程擁有者、引擎鎖定。"""

from __future__ import annotations

import copy
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

    def make_user(self, admin_token, name="alice", is_staff=False, role=None):
        body = {"username": name, "password": "pass123", "is_staff": is_staff}
        if role:
            body["role"] = role
        r = self.post("/api/users", body, token=admin_token)
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
    def test_flows_belong_to_the_line_not_to_a_person(self):
        """工廠模型：流程是「這條線的檢測程式」，任何工程師都看得到、改得動。"""
        admin = self.setup_admin()
        alice = self.make_user(admin, "alice")  # 預設 engineer
        bob = self.make_user(admin, "bob")
        r = self.post("/api/vision/flows", {"name": "alice-flow", "graph": graph_for(self.source.id)}, token=alice)
        self.assertEqual(r.status_code, 201)
        fid = r.json()["id"]
        self.assertEqual(r.json()["owner_name"], "alice")  # owner 仍記錄建立者
        Flow.objects.create(name="shared", graph=graph_for(self.source.id))
        # 另一位工程師看得到也改得動——工程師離職不會讓流程變成沒人能改的孤兒
        self.assertEqual({f["name"] for f in self.get("/api/vision/flows", token=bob).json()["items"]}, {"alice-flow", "shared"})
        self.assertEqual(self.get(f"/api/vision/flows/{fid}", token=bob).status_code, 200)
        self.assertEqual(self.client.patch(f"/api/vision/flows/{fid}", data=json.dumps({"description": "x"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {bob}").status_code, 200)
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/preview", {"graph": graph_for(self.source.id)}, token=bob).status_code, 200)
        self.assertEqual(self.get("/api/vision/flows", token=admin).json()["total"], 2)
        self.assertEqual(self.get("/api/vision/flows?mine=true", token=alice).json()["total"], 1)
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/run", {}, token=alice).status_code, 200)
        # 刪除建立者 → 流程還在，只是沒有建立者
        uid = User.objects.get(username="alice").id
        self.assertEqual(self.client.delete(f"/api/users/{uid}", HTTP_AUTHORIZATION=f"Bearer {admin}").status_code, 204)
        self.assertIsNone(Flow.objects.get(pk=fid).owner_id)
        self.assertEqual(self.get(f"/api/vision/flows/{fid}", token=bob).status_code, 200)

    def test_operator_can_run_and_change_over_but_not_edit(self):
        """現場作業員：執行、啟停連續、換線、微調現場參數；不能改流程結構。"""
        admin = self.setup_admin()
        op = self.make_user(admin, "op1", role="operator")
        graph = graph_for(self.source.id)
        fid = self.post("/api/vision/flows", {"name": "line-a", "graph": graph}, token=admin).json()["id"]

        # 看得到、跑得動、能啟停連續
        self.assertEqual(self.get(f"/api/vision/flows/{fid}", token=op).status_code, 200)
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/run", {}, token=op).status_code, 200)
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/continuous", {"running": True}, token=op).status_code, 200)
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/continuous", {"running": False}, token=op).status_code, 200)

        # 換線：切換預設配方可以，改配方內容不行
        rid = self.post(f"/api/vision/flows/{fid}/recipes", {"name": "partB", "param_overrides": {}}, token=admin).json()["id"]
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/recipes/{rid}/activate", {}, token=op).status_code, 200)
        self.assertTrue(self.get(f"/api/vision/flows/{fid}/recipes", token=op).json()["items"][0]["is_default"])
        self.assertEqual(self.post(f"/api/vision/flows/{fid}/recipes", {"name": "partC", "param_overrides": {}}, token=op).status_code, 403)

        # 建立與刪除流程不行
        self.assertEqual(self.post("/api/vision/flows", {"name": "nope", "graph": graph}, token=op).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/vision/flows/{fid}", HTTP_AUTHORIZATION=f"Bearer {op}").status_code, 403)
        self.assertEqual(self.get("/api/users", token=op).status_code, 403)

    def test_operator_may_only_change_teach_parameters(self):
        """參數卡頁的現場微調：只有標了 teach 的參數能動，結構一律擋下。"""
        admin = self.setup_admin()
        op = self.make_user(admin, "op2", role="operator")
        graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": self.source.id}},
                {"id": "thr", "type": "threshold", "params": {"method": "fixed", "threshold": 60}},
            ],
            "edges": [{"source": "src", "source_handle": "image", "target": "thr", "target_handle": "image"}],
        }
        fid = self.post("/api/vision/flows", {"name": "teachable", "graph": graph}, token=admin).json()["id"]

        def send(g, token=op):
            return self.client.patch(f"/api/vision/flows/{fid}", data=json.dumps({"graph": g}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")

        teach = copy.deepcopy(graph)
        next(n for n in teach["nodes"] if n["id"] == "thr")["params"]["threshold"] = 99
        self.assertEqual(send(teach).status_code, 200, "threshold 標了 teach，操作員應該可以調")

        not_teach = copy.deepcopy(graph)
        next(n for n in not_teach["nodes"] if n["id"] == "thr")["params"]["method"] = "otsu"
        r = send(not_teach)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "teach_only"), "method 沒標 teach，不該讓操作員換演算法")

        structure = copy.deepcopy(graph)
        structure["nodes"] = structure["nodes"][:-1]
        r = send(structure)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "teach_only")

        renamed = copy.deepcopy(graph)
        r = self.client.patch(f"/api/vision/flows/{fid}", data=json.dumps({"graph": renamed, "name": "new"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {op}")
        self.assertEqual(r.status_code, 403, "改名不是現場作業")

    def test_role_round_trip(self):
        admin = self.setup_admin()
        self.make_user(admin, "eng")
        users = {u["username"]: u for u in self.get("/api/users", token=admin).json()["items"]}
        self.assertEqual((users["admin"]["role"], users["eng"]["role"]), ("admin", "engineer"))
        uid = User.objects.get(username="eng").id
        r = self.client.patch(f"/api/users/{uid}", data=json.dumps({"role": "operator"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {admin}")
        self.assertEqual((r.status_code, r.json()["role"], r.json()["is_staff"]), (200, "operator", False))
        r = self.client.patch(f"/api/users/{uid}", data=json.dumps({"role": "admin"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {admin}")
        self.assertEqual((r.json()["role"], r.json()["is_staff"]), ("admin", True))  # admin 與 is_staff 同步
        r = self.client.patch(f"/api/users/{uid}", data=json.dumps({"role": "wizard"}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {admin}")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "bad_role"))
        me = self.get("/api/auth/me", token=admin).json()
        self.assertEqual(me["role"], "admin")

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
