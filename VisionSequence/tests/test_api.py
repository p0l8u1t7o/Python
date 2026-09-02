"""HTTP API：流程 CRUD、run、preview、影像、來源、資產、TCP 指令。"""

from __future__ import annotations

import io
import json
import time

import cv2
import numpy as np
from django.test import TestCase, TransactionTestCase, override_settings

from apps.vision.models import Flow, FlowRun, ImageSource
from apps.vision.tcp_server import handle_command


def png_bytes(w=64, h=48, value=180):
    ok, buf = cv2.imencode(".png", np.full((h, w, 3), value, np.uint8))
    assert ok
    return buf.tobytes()


class ApiTests(TestCase):
    def setUp(self):
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 320, "height": 240})
        self.graph = {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": self.source.id}},
                {"id": "g", "type": "grayscale", "params": {}},
                {"id": "t", "type": "threshold", "params": {"method": "otsu"}},
                {"id": "o", "type": "output", "params": {"name": "otsu"}},
                {"id": "j", "type": "judge", "params": {"verdict": "ok"}},
            ],
            "edges": [
                {"source": "src", "target": "g"},
                {"source": "g", "target": "t"},
                {"source": "t", "source_handle": "threshold_used", "target": "o", "target_handle": "value"},
            ],
        }

    def create_flow(self, name="f1"):
        r = self.client.post("/api/vision/flows", data=json.dumps({"name": name, "graph": self.graph}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_tool_types(self):
        r = self.client.get("/api/vision/tool-types")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        keys = {t["key"] for t in body["items"]}
        self.assertIn("image_source", keys)
        self.assertIn("if_number", keys)
        tool = next(t for t in body["items"] if t["key"] == "threshold")
        self.assertTrue(any(p["kind"] == "select" for p in tool["params"]))
        self.assertEqual(tool["inputs"][0]["type"], "image")

    def test_flow_crud_and_version(self):
        flow = self.create_flow()
        self.assertEqual(flow["version"], 1)
        r = self.client.patch(f"/api/vision/flows/{flow['id']}", data=json.dumps({"graph": self.graph, "description": "d"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["version"], 2)
        # 同名衝突
        r = self.client.post("/api/vision/flows", data=json.dumps({"name": "f1"}), content_type="application/json")
        self.assertEqual(r.status_code, 409)
        # 壞圖 422
        r = self.client.patch(f"/api/vision/flows/{flow['id']}", data=json.dumps({"graph": {"nodes": [{"id": "x", "type": "nope"}], "edges": []}}), content_type="application/json")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "unknown_tool_type")
        r = self.client.post(f"/api/vision/flows/{flow['id']}/duplicate")
        self.assertEqual(r.status_code, 201)
        self.assertIn("副本", r.json()["name"])
        r = self.client.delete(f"/api/vision/flows/{flow['id']}")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Flow.objects.filter(pk=flow["id"]).exists())

    def test_run_json_sync(self):
        flow = self.create_flow()
        r = self.client.post(f"/api/vision/flows/{flow['id']}/run", data=json.dumps({"context": {"lot": "A1"}}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("otsu", body["outputs"])
        self.assertEqual(body["outputs"]["judge"], "OK")
        # 預設不含節點輸出（產線回傳要小）
        self.assertEqual(body["nodes"]["g"]["outputs"], {})
        self.assertGreater(body["duration_ms"], 0)

    def test_run_multipart_with_image(self):
        flow = self.create_flow()
        upload = io.BytesIO(png_bytes(100, 50))
        upload.name = "x.png"
        r = self.client.post(f"/api/vision/flows/{flow['id']}/run?include_images=true", data={"image": upload, "context": json.dumps({"k": 1})})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["nodes"]["src"]["outputs"]["width"], 100)
        self.assertIn("input", body["nodes"]["src"]["message"])

    def test_run_async(self):
        flow = self.create_flow()
        r = self.client.post(f"/api/vision/flows/{flow['id']}/run?wait=false", data=json.dumps({}), content_type="application/json")
        self.assertEqual(r.status_code, 202)
        time.sleep(0.3)
        self.assertGreaterEqual(self.client.get(f"/api/vision/flows/{flow['id']}/recent").json()["stats"]["runs"], 1)

    def test_preview_keeps_images_and_image_endpoint(self):
        flow = self.create_flow()
        r = self.client.post(f"/api/vision/flows/{flow['id']}/preview", data=json.dumps({"graph": self.graph}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        ref = body["nodes"]["t"]["outputs"]["image"]["ref"]
        self.assertTrue(ref)
        img = self.client.get(f"/api/vision/images/{ref}?max=64")
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img["Content-Type"], "image/jpeg")
        decoded = cv2.imdecode(np.frombuffer(img.content, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(max(decoded.shape[:2]), 64)
        png = self.client.get(f"/api/vision/images/{ref}?fmt=png")
        self.assertEqual(png["Content-Type"], "image/png")
        # 用同一張影像重跑
        src_ref = body["nodes"]["src"]["outputs"]["image"]["ref"]
        r2 = self.client.post(f"/api/vision/flows/{flow['id']}/preview", data=json.dumps({"graph": self.graph, "reuse_image_ref": src_ref}), content_type="application/json")
        self.assertEqual(r2.status_code, 200)
        self.assertIn("input", r2.json()["nodes"]["src"]["message"])
        # 詳情
        detail = self.client.get(f"/api/vision/runs/{body['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.json()["persisted"])
        self.assertEqual(self.client.get("/api/vision/images/nope:x:y").status_code, 404)

    def test_capacity(self):
        r = self.client.get("/api/vision/capacity")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["max_workers"], 10)

    def test_sources(self):
        r = self.client.get("/api/vision/sources/kinds")
        self.assertIn("synthetic", [k["kind"] for k in r.json()["items"]])
        r = self.client.post("/api/vision/sources", data=json.dumps({"name": "up", "kind": "upload", "config": {}}), content_type="application/json")
        self.assertEqual(r.status_code, 201)
        sid = r.json()["id"]
        upload = io.BytesIO(png_bytes(30, 20))
        upload.name = "a.png"
        r = self.client.post(f"/api/vision/sources/{sid}/push", data={"image": upload})
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.get(f"/api/vision/sources/{sid}/preview")
        self.assertEqual(r.status_code, 200)
        r = self.client.get(f"/api/vision/sources/{self.source.id}/preview?max=100")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        r = self.client.post("/api/vision/sources", data=json.dumps({"name": "bad", "kind": "folder", "config": {"path": "Z:/nope"}}), content_type="application/json")
        self.assertEqual(r.status_code, 201)
        r = self.client.get(f"/api/vision/sources/{r.json()['id']}/preview")
        self.assertEqual(r.status_code, 422)
        r = self.client.delete(f"/api/vision/sources/{sid}")
        self.assertEqual(r.status_code, 204)

    def test_source_and_asset_groups(self):
        """群組分類管理：來源／資產帶 group 建立、可 PATCH 改群組。"""
        r = self.client.post("/api/vision/sources", data=json.dumps({"name": "g1", "kind": "synthetic", "config": {"width": 64, "height": 48}, "group": "站別A"}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        sid = r.json()["id"]
        self.assertEqual(r.json()["group"], "站別A")
        r = self.client.patch(f"/api/vision/sources/{sid}", data=json.dumps({"group": " 站別B "}), content_type="application/json")
        self.assertEqual(r.json()["group"], "站別B")
        upload = io.BytesIO(png_bytes(20, 20))
        upload.name = "g.png"
        r = self.client.post("/api/vision/assets", data={"file": upload, "kind": "image", "name": "g", "group": "料號X"})
        self.assertEqual(r.status_code, 201, r.content)
        aid = r.json()["id"]
        self.assertEqual(r.json()["group"], "料號X")
        r = self.client.patch(f"/api/vision/assets/{aid}", data=json.dumps({"group": "料號Y", "name": "g2"}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["group"], r.json()["name"]), ("料號Y", "g2"))
        r = self.client.get("/api/vision/assets")
        row = next(a for a in r.json()["items"] if a["id"] == aid)
        self.assertEqual(row["group"], "料號Y")

    def test_assets_upload_and_from_image(self):
        upload = io.BytesIO(png_bytes(40, 30))
        upload.name = "tpl.png"
        r = self.client.post("/api/vision/assets", data={"file": upload, "kind": "image", "name": "tpl"})
        self.assertEqual(r.status_code, 201, r.content)
        asset = r.json()
        self.assertEqual(asset["meta"]["width"], 40)
        f = self.client.get(f"/api/vision/assets/{asset['id']}/file?max=20")
        self.assertEqual(f.status_code, 200)
        flow = self.create_flow()
        body = self.client.post(f"/api/vision/flows/{flow['id']}/preview", data=json.dumps({"graph": self.graph}), content_type="application/json").json()
        ref = body["nodes"]["src"]["outputs"]["image"]["ref"]
        r = self.client.post("/api/vision/assets/from-image", data=json.dumps({"ref": ref, "region": {"shape": "rect", "x": 10, "y": 10, "w": 50, "h": 40}, "name": "crop"}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["meta"]["width"], 50)
        r = self.client.delete(f"/api/vision/assets/{asset['id']}")
        self.assertEqual(r.status_code, 204)

    def test_tcp_commands(self):
        flow = self.create_flow("tcpflow")
        self.assertTrue(handle_command("PING")["pong"])
        self.assertIn("flows", handle_command("LIST"))
        res = handle_command("RUN tcpflow lot=7")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["judge"], "OK")
        self.assertIn("otsu", res["outputs"])
        res = handle_command(f"RUN {flow['id']}")
        self.assertTrue(res["ok"])
        self.assertFalse(handle_command("RUN nope")["ok"])
        self.assertFalse(handle_command("WHAT")["ok"])
        self.assertTrue(handle_command("STATUS tcpflow")["ok"])

    @override_settings(VISION={**__import__("django.conf").conf.settings.VISION, "API_KEY": "secret"})
    def test_api_key(self):
        from django.contrib.auth.models import User

        User.objects.create_user("someone", password="x")  # 有使用者後 bootstrap 不再放行
        self.assertEqual(self.client.get("/api/vision/capacity").status_code, 401)
        self.assertEqual(self.client.get("/api/vision/capacity", HTTP_X_API_KEY="secret").status_code, 200)
        self.assertEqual(self.client.get("/api/vision/capacity?api_key=secret").status_code, 200)

    def test_events_stream_smoke(self):
        r = self.client.get("/api/vision/events?since=0&max_seconds=0.2")
        body = b"".join(r.streaming_content)
        self.assertIn(b"event: hello", body)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/event-stream")


class PersistedRunTests(TransactionTestCase):
    """背景執行緒寫入 FlowRun：TestCase 的交易會鎖住 SQLite 表，這裡用真交易。"""

    def setUp(self):
        ApiTests.setUp(self)

    create_flow = ApiTests.create_flow

    def test_scratch_image_until_node_analysis_and_reset(self):
        flow = self.create_flow()
        upload = io.BytesIO(png_bytes(120, 90, 200))
        upload.name = "scratch.png"
        r = self.client.post(f"/api/vision/flows/{flow['id']}/scratch-image", data={"image": upload})
        self.assertEqual(r.status_code, 201, r.content)
        ref = r.json()["ref"]
        self.assertTrue(ref.startswith("scratch"))
        body = self.client.post(
            f"/api/vision/flows/{flow['id']}/preview",
            data=json.dumps({"graph": self.graph, "reuse_image_ref": ref, "until_node": "t", "analysis": True}),
            content_type="application/json",
        ).json()
        self.assertEqual(body["nodes"]["src"]["outputs"]["width"], 120)
        self.assertEqual(body["nodes"]["t"]["status"], "ok")
        self.assertNotIn("o", body["nodes"])  # 只跑到 t 與其祖先
        analysis = body["analysis"]
        self.assertEqual(len(analysis["input"]["histogram"]), 256)
        self.assertEqual(analysis["output"]["port"], "image")
        self.assertEqual(analysis["input"]["stats"]["width"], 120)
        # 只用暫存影像但沒有上傳 → 該節點錯誤
        g2 = json.loads(json.dumps(self.graph))
        g2["nodes"][0]["params"] = {"mode": "input"}
        body = self.client.post(f"/api/vision/flows/{flow['id']}/preview", data=json.dumps({"graph": g2}), content_type="application/json").json()
        self.assertEqual(body["status"], "failed")
        self.assertIn("暫存影像", body["nodes"]["src"]["message"])
        # 重置
        self.assertGreater(self.client.get(f"/api/vision/flows/{flow['id']}/recent").json()["stats"]["runs"], 0)
        self.assertEqual(self.client.delete(f"/api/vision/flows/{flow['id']}/recent").status_code, 204)
        recent = self.client.get(f"/api/vision/flows/{flow['id']}/recent").json()
        self.assertEqual(recent["stats"]["runs"], 0)
        self.assertEqual(recent["items"], [])
        self.assertEqual(self.client.post(f"/api/vision/flows/{flow['id']}/preview", data=json.dumps({"graph": self.graph, "until_node": "nope"}), content_type="application/json").status_code, 422)

    def test_run_history_persisted(self):
        import time as _t

        _t.sleep(0.3)  # 前面測試的背景寫入落地後清掉：flow id 會被重用，舊列會混進來
        FlowRun.objects.all().delete()
        flow = self.create_flow()
        for _ in range(3):
            self.client.post(f"/api/vision/flows/{flow['id']}/run", data=json.dumps({}), content_type="application/json")
        # 背景寫入：等佇列清空
        for _ in range(50):
            if FlowRun.objects.filter(flow_id=flow["id"]).count() >= 3:
                break
            time.sleep(0.05)
        r = self.client.get(f"/api/vision/flows/{flow['id']}/runs")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()["total"], 3)
        self.assertEqual(r.json()["items"][0]["status"], "ok")
        stats = self.client.get(f"/api/vision/flows/{flow['id']}/stats").json()
        self.assertGreaterEqual(stats["total"], 3)
        self.assertGreaterEqual(stats["by_status"].get("ok", 0), 3)


class ResourceGroupTests(ApiTests.__bases__[0]):
    """資源群組管理：清單（含回填）、新增、改名（項目連動）、刪除（連刪或改未分組）。"""

    def test_group_lifecycle(self):
        def mk(name, group):
            return self.client.post("/api/vision/sources", data=json.dumps({"name": name, "kind": "synthetic", "config": {"width": 32, "height": 32}, "group": group}), content_type="application/json").json()
        a = mk("ga", "甲組")
        mk("gb", "甲組")
        mk("gc", "")
        # 清單：項目上的群組自動回填成列
        r = self.client.get("/api/vision/groups", {"kind": "source"})
        items = {g["name"]: g for g in r.json()["items"]}
        self.assertEqual(items["甲組"]["count"], 2)
        gid = items["甲組"]["id"]
        # 新增空群組
        r = self.client.post("/api/vision/groups", data=json.dumps({"kind": "source", "name": "乙組"}), content_type="application/json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["count"], 0)
        r = self.client.post("/api/vision/groups", data=json.dumps({"kind": "source", "name": "乙組"}), content_type="application/json")
        self.assertEqual(r.status_code, 409)
        # 改名：項目的 group 字串連動
        r = self.client.patch(f"/api/vision/groups/{gid}", data=json.dumps({"name": "甲組2"}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        row = self.client.get(f"/api/vision/sources/{a['id']}").json()
        self.assertEqual(row["group"], "甲組2")
        # 刪除（不連刪）：項目變未分組
        r = self.client.delete(f"/api/vision/groups/{gid}")
        self.assertEqual(r.status_code, 204)
        row = self.client.get(f"/api/vision/sources/{a['id']}").json()
        self.assertEqual(row["group"], "")
        # 刪除（連刪）：資產走檔案刪除路徑
        upload = io.BytesIO(png_bytes(16, 16))
        upload.name = "z.png"
        asset = self.client.post("/api/vision/assets", data={"file": upload, "kind": "image", "name": "z", "group": "丙組"}).json()
        r = self.client.get("/api/vision/groups", {"kind": "asset"})
        gid2 = next(g["id"] for g in r.json()["items"] if g["name"] == "丙組")
        r = self.client.delete(f"/api/vision/groups/{gid2}?delete_items=1")
        self.assertEqual(r.status_code, 204)
        r = self.client.get("/api/vision/assets")
        self.assertNotIn(asset["id"], [x["id"] for x in r.json()["items"]])


class FsBrowseTests(ApiTests.__bases__[0]):
    """伺服器檔案瀏覽與相機掃描端點。"""

    def test_browse_fs(self):
        import os
        import tempfile

        base = tempfile.mkdtemp(prefix="vs-fs-")
        os.makedirs(os.path.join(base, "sub"))
        with open(os.path.join(base, "a.png"), "wb") as f:
            f.write(b"x")
        with open(os.path.join(base, "b.txt"), "wb") as f:
            f.write(b"x")
        r = self.client.get("/api/vision/fs", {"path": base})
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertIn("sub", data["dirs"])
        self.assertEqual(data["files"], ["a.png"])  # 非影像檔被濾掉
        self.assertTrue(data["parent"])
        r = self.client.get("/api/vision/fs", {"path": os.path.join(base, "nope")})
        self.assertEqual(r.status_code, 404)
        r = self.client.get("/api/vision/fs")
        self.assertEqual(r.status_code, 200)  # 根：磁碟機清單／根目錄

    def test_usb_scan_shape(self):
        r = self.client.get("/api/vision/sources/usb-scan", {"max_index": 1})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("items", r.json())  # 無相機環境回空清單
