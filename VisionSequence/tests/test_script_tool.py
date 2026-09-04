"""Python 腳本工具：受限執行、回傳正規化、錯誤翻譯、看門狗、輸入唯讀；核准守門（只有管理員能儲存新腳本）。"""

from __future__ import annotations

import json

import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.vision.tools.base import ToolError
from tests._helpers import blank, circle_image, run_tool

ADMIN = {"_script_admin": True}
VISION_TEST = {**settings.VISION, "PERSIST_RUNS": False}


class ScriptToolTests(SimpleTestCase):
    def setUp(self):
        from apps.vision import scripts

        scripts.seed_cache(set())  # 核准集合空、不碰 DB：沒帶管理員旗標的執行一律被擋

    def tearDown(self):
        from apps.vision import scripts

        scripts.reset_cache()

    def test_template_and_return_shapes(self):
        from apps.vision.tools.builtin.script import TEMPLATE

        img = circle_image()
        snapshot = img.copy()
        r = run_tool("python_script", img, {"code": TEMPLATE, "p1": 10}, context=dict(ADMIN))
        self.assertEqual((r.status, r.branch), ("ok", "pass"), r.message)
        self.assertGreater(r.outputs["value"], 10)
        self.assertTrue(r.outputs["result"])
        self.assertIn("平均灰階", r.message)
        r = run_tool("python_script", img, {"code": TEMPLATE, "p1": 250}, context=dict(ADMIN))
        self.assertEqual((r.status, r.branch), ("ng", "fail"))
        self.assertTrue(np.array_equal(img, snapshot))  # 輸入影像不被改
        # 回傳影像（新陣列）＋資料＋文字＋標記；有 ROI 時先畫 ROI 標記
        code = "def run(ctx):\n    g = ctx.gray()\n    out = cv2.GaussianBlur(g, (5, 5), 0)\n    return {'image': out, 'data': {'n': int(g.max())}, 'overlays': [{'kind': 'point', 'x': 1, 'y': 2}], 'text': 'hi'}\n"
        r = run_tool("python_script", img, {"code": code, "roi": {"shape": "rect", "x": 0, "y": 0, "w": 50, "h": 50}}, context=dict(ADMIN))
        self.assertEqual(r.outputs["image"].shape, img.shape[:2])
        self.assertEqual(r.outputs["data"], {"n": 220})
        self.assertEqual(r.outputs["text"], "hi")
        self.assertEqual([o["kind"] for o in r.overlays], ["rect", "point"])
        # 單一值回傳：數值／布林／文字／影像
        r = run_tool("python_script", None, {"code": "def run(ctx):\n    return ctx.inputs['a'] * 2\n"}, inputs={"a": 21}, context=dict(ADMIN))
        self.assertEqual(r.outputs["value"], 42)
        r = run_tool("python_script", None, {"code": "def run(ctx):\n    return False\n"}, context=dict(ADMIN))
        self.assertEqual((r.status, r.branch, r.outputs["result"]), ("ng", "fail", False))
        r = run_tool("python_script", img, {"code": "def run(ctx):\n    return ctx.crop().image.copy()\n", "roi": {"shape": "rect", "x": 10, "y": 10, "w": 30, "h": 20}}, context=dict(ADMIN))
        self.assertEqual(r.outputs["image"].shape, (20, 30))
        # 回傳輸入影像本身（唯讀 view）→ 複製後往下傳
        r = run_tool("python_script", img, {"code": "def run(ctx):\n    return ctx.image\n"}, context=dict(ADMIN))
        self.assertFalse(np.shares_memory(r.outputs["image"], img))
        self.assertTrue(r.outputs["image"].flags.writeable)

    def test_restrictions_and_errors(self):
        from apps.vision.tools.builtin.script import TEMPLATE

        img = blank()
        cases = [
            ("import os\ndef run(ctx):\n    return 1\n", "may not import"),
            ("from subprocess import run as r\ndef run(ctx):\n    return 1\n", "may not import"),
            ("def run(ctx):\n    return ().__class__\n", "may not access"),
            ("def run(ctx):\n    return __builtins__\n", "may not use"),
            ("def run(ctx):\n    return open('x')\n", "may not call"),
            ("def run(ctx):\n    return eval('1')\n", "may not call"),
            ("def run(ctx)\n    return 1\n", "syntax error"),
            ("def go(ctx):\n    return 1\n", "must define"),
            ("def run(ctx):\n    x = 1 / 0\n    return x\n", "line 2"),
            ("def run(ctx):\n    ctx.image[0, 0] = 9\n    return 1\n", "line 2"),
            ("def run(ctx):\n    return {1, 2}\n", "unsupported type"),
            ("def run(ctx):\n    return {'status': 'maybe'}\n", "status must be"),
            ("def run(ctx):\n    return {'overlays': [1]}\n", "overlays must be"),
        ]
        for code, needle in cases:
            with self.assertRaises(ToolError, msg=code) as cm:
                run_tool("python_script", img, {"code": code}, context=dict(ADMIN))
            self.assertIn(needle, str(cm.exception), code)
        # 白名單模組可以用；動態 import 走同一個守門
        r = run_tool("python_script", img, {"code": "import math\nimport numpy as np2\nfrom collections import Counter\ndef run(ctx):\n    return math.hypot(3, 4) + float(np2.zeros(1)[0]) + len(Counter('ab'))\n"}, context=dict(ADMIN))
        self.assertEqual(r.outputs["value"], 7)
        # 看門狗：純 Python 無窮迴圈在 max_ms 內中止
        with self.assertRaises(ToolError) as cm:
            run_tool("python_script", img, {"code": "def run(ctx):\n    while True:\n        pass\n", "max_ms": 200}, context=dict(ADMIN))
        self.assertIn("was aborted", str(cm.exception))
        # 未核准且沒有管理員旗標 → 拒絕執行；內建範本例外（插入工具就能試執行）；沒填 code 就用範本
        with self.assertRaises(ToolError) as cm:
            run_tool("python_script", img, {"code": TEMPLATE + "\n# mine\n"})
        self.assertIn("has not been approved", str(cm.exception))
        self.assertEqual(run_tool("python_script", img, {"code": TEMPLATE}).status, "ok")
        self.assertEqual(run_tool("python_script", img, {}).status, "ok")
        with self.assertRaises(ToolError):
            run_tool("python_script", img, {"code": "   "}, context=dict(ADMIN))


@override_settings(VISION=VISION_TEST)
class ScriptApprovalApiTests(TransactionTestCase):
    """儲存流程時的核准守門與試執行放行。"""

    def setUp(self):
        from apps.vision import scripts
        from apps.vision.models import ImageSource

        scripts.reset_cache()
        self.source = ImageSource.objects.create(name="syn", kind="synthetic", config={"width": 64, "height": 48})

    def tearDown(self):
        from apps.vision import scripts

        scripts.reset_cache()

    def _graph(self, code: str, **params):
        return {
            "nodes": [
                {"id": "src", "type": "image_source", "params": {"source_id": self.source.id}},
                {"id": "py", "type": "python_script", "params": {"code": code, **params}},
            ],
            "edges": [{"source": "src", "target": "py"}],
        }

    def _json(self, method: str, path: str, body=None, **kw):
        fn = getattr(self.client, method)
        return fn(path, data=json.dumps(body) if body is not None else None, content_type="application/json", **kw)

    def test_admin_approves_worker_cannot_change(self):
        from apps.accounts.models import AuthToken
        from apps.vision.models import ScriptApproval
        from apps.vision.tools.builtin.script import TEMPLATE

        token = self._json("post", "/api/auth/setup", {"username": "admin", "password": "secret123"}).json()["token"]
        admin = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        worker = User.objects.create_user("worker", password="x")
        wauth = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(worker)}"}
        code = TEMPLATE
        # 一般使用者送未核准腳本 → 403
        r = self._json("post", "/api/vision/flows", {"name": "w1", "graph": self._graph(code)}, **wauth)
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(ScriptApproval.objects.count(), 0)
        # 管理員儲存 → 核准登記
        r = self._json("post", "/api/vision/flows", {"name": "a1", "graph": self._graph(code)}, **admin)
        self.assertEqual(r.status_code, 201, r.content)
        admin_flow = r.json()["id"]
        self.assertEqual(ScriptApproval.objects.count(), 1)
        self.assertEqual(ScriptApproval.objects.get().approved_by.username, "admin")
        # 一般使用者可以用已核准的腳本建流程、改其他參數；改程式碼 → 403
        r = self._json("post", "/api/vision/flows", {"name": "w2", "graph": self._graph(code)}, **wauth)
        self.assertEqual(r.status_code, 201, r.content)
        fid = r.json()["id"]
        changed = code + "\n# tweak\n"
        r = self._json("patch", f"/api/vision/flows/{fid}", {"graph": self._graph(changed)}, **wauth)
        self.assertEqual(r.status_code, 403, r.content)
        r = self._json("patch", f"/api/vision/flows/{fid}", {"graph": self._graph(code, p1=5)}, **wauth)
        self.assertEqual(r.status_code, 200, r.content)
        # 配方不能覆寫程式碼
        r = self._json("post", f"/api/vision/flows/{fid}/recipes", {"name": "r", "param_overrides": {"py": {"code": "x"}}}, **wauth)
        self.assertEqual(r.status_code, 422, r.content)
        r = self._json("post", f"/api/vision/flows/{fid}/recipes", {"name": "r", "param_overrides": {"py": {"p1": 3}}}, **wauth)
        self.assertEqual(r.status_code, 201, r.content)
        # 試執行：管理員可跑未核准的新腳本；一般使用者跑未核准腳本 → 該節點錯誤（不是 403）；外部 context 偷帶旗標無效
        r = self._json("post", f"/api/vision/flows/{admin_flow}/preview", {"graph": self._graph(changed)}, **admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["nodes"]["py"]["status"], "ok", r.json()["nodes"]["py"])
        r = self._json("post", f"/api/vision/flows/{fid}/preview", {"graph": self._graph(changed), "context": {"_script_admin": True}}, **wauth)
        self.assertEqual(r.status_code, 200, r.content)
        node = r.json()["nodes"]["py"]
        self.assertEqual(node["status"], "error")
        self.assertIn("approved", node["message"])
        # 已核准的腳本一般使用者照常跑
        r = self._json("post", f"/api/vision/flows/{fid}/preview", {"graph": self._graph(code)}, **wauth)
        self.assertEqual(r.json()["nodes"]["py"]["status"], "ok", r.json()["nodes"]["py"])
        # 匯入含新腳本的流程檔：一般使用者 403、管理員可
        doc = {"schema_version": 1, "name": "imported", "graph": self._graph(changed)}
        r = self._json("post", "/api/vision/flows/import", doc, **wauth)
        self.assertEqual(r.status_code, 403, r.content)
        r = self._json("post", "/api/vision/flows/import", doc, **admin)
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertEqual(ScriptApproval.objects.count(), 2)
