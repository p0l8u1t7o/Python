"""AI 助手記憶：工作階段儲存／相似案例先驗／評分／還原／刪除，與站點／個人技能補充。"""

from __future__ import annotations

import json
import os

import cv2
import numpy as np
from django.contrib.auth.models import User
from django.test import TestCase

from apps.vision.agent import autotune, memory, service, skills
from apps.vision.images import store
from apps.vision.models import AgentSession, AgentSkill, Flow


def part_image(holes: int = 5) -> np.ndarray:
    img = np.full((480, 640, 3), 200, np.uint8)
    for i in range(holes):
        cv2.circle(img, (100 + i * 110, 240), 30, (40, 40, 40), -1)
    return img


class MemoryTests(TestCase):
    def tearDown(self):
        for s in AgentSession.objects.all():
            memory.forget(s)

    def test_remember_find_similar_priors_and_thumbs_down(self):
        r = service.generate([part_image(5), part_image(4)], [], "應該有 5 個孔", use_llm=False, labels=["ok", "ng"])
        self.assertIsNotNone(r["session_id"])
        s = AgentSession.objects.get(pk=r["session_id"])
        self.assertTrue(s.success)
        self.assertEqual(s.intent, "count")
        self.assertEqual(len(s.images), 2)
        self.assertTrue(os.path.exists(s.images[0]["path"]))
        self.assertEqual(len(s.features["vector"]), len(memory.FEATURE_KEYS))
        # 成功案例的 teach 參數變成下一次的先驗：候選「沿用過去成功參數」排第一並被採用
        blob = next(n for n in s.graph["nodes"] if n["id"] == "blob")
        blob["params"]["min_area"] = 123
        s.save(update_fields=["graph"])
        r2 = service.generate([part_image(5)], [], "應該有 5 個孔", use_llm=False)
        self.assertEqual(r2["similar"][0]["id"], s.id)
        self.assertEqual(r2["candidates"][0]["key"], "prior")
        self.assertEqual(next(n for n in r2["graph"]["nodes"] if n["id"] == "blob")["params"]["min_area"], 123)
        self.assertIn("沿用相似成功案例", r2["rationale"])
        # 倒讚的案例不再當先驗；其他意圖也不會拿到
        s.rating = -1
        s.save(update_fields=["rating"])
        r3 = service.generate([part_image(5)], [], "應該有 5 個孔", use_llm=False)
        self.assertEqual(r3["similar"], [])
        self.assertEqual(r3["candidates"][0]["key"], "primary")
        self.assertEqual(memory.find_similar("defect", service.analysis_mod.analyze([part_image(5)], [])), [])

    def test_no_labels_means_unknown_success_and_examples_text(self):
        r = service.generate([part_image(5)], [], "應該有 5 個孔", use_llm=False)
        s = AgentSession.objects.get(pk=r["session_id"])
        self.assertIsNone(s.success)
        s.rating = 1
        s.save(update_fields=["rating"])
        rows = memory.find_similar("count", service.analysis_mod.analyze([part_image(5)], []))
        self.assertEqual([x.id for x, _ in rows], [s.id])
        text = memory.examples_text(rows)
        self.assertIn(f"#{s.id}", text)
        self.assertIn("blob.min_area", text)

    def test_autotune_tries_prior_first(self):
        graph = service.generate([part_image(5)], [], "應該有 5 個孔", use_llm=False, remember=False)["graph"]
        dims = autotune.search_space(graph, {("blob", "min_area"): 77})
        dim = next(d for d in dims if d.node_id == "blob" and d.key == "min_area")
        self.assertEqual(dim.candidates[0], 77)
        self.assertEqual(dim.tool_type, "blob")


class SessionApiTests(TestCase):
    def tearDown(self):
        for s in AgentSession.objects.all():
            memory.forget(s)

    def test_list_get_patch_restore_delete(self):
        r = service.generate([part_image(5)], [], "應該有 5 個孔", use_llm=False)
        sid = r["session_id"]
        body = self.client.get("/api/vision/agent/sessions").json()
        self.assertIn(sid, [it["id"] for it in body["items"]])
        full = self.client.get(f"/api/vision/agent/sessions/{sid}").json()
        self.assertIn("graph", full)
        self.assertEqual(full["image_count"], 1)
        flow = Flow.objects.create(name="from-agent", graph=full["graph"])
        res = self.client.patch(f"/api/vision/agent/sessions/{sid}", data=json.dumps({"rating": 1, "note": "好用", "flow_id": flow.id}), content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["rating"], res.json()["flow_id"], res.json()["note"]), (1, flow.id, "好用"))
        res = self.client.patch(f"/api/vision/agent/sessions/{sid}", data=json.dumps({"rating": 5}), content_type="application/json")
        self.assertEqual(res.status_code, 422)
        res = self.client.post(f"/api/vision/agent/sessions/{sid}/restore")
        self.assertEqual(res.status_code, 200, res.content)
        restored = res.json()
        self.assertEqual(len(restored["images"]), 1)
        self.assertIsNotNone(store.get(restored["images"][0]["ref"]))
        self.assertEqual(restored["prompt"], "應該有 5 個孔")
        folder = memory.session_dir(sid)
        self.assertTrue(os.path.isdir(folder))
        res = self.client.delete(f"/api/vision/agent/sessions/{sid}")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(os.path.isdir(folder))
        self.assertEqual(self.client.get(f"/api/vision/agent/sessions/{sid}").status_code, 404)

    def test_generate_via_api_records_owner(self):
        token = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret123"}), content_type="application/json").json()["token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        ok, buf = cv2.imencode(".png", part_image(5))
        from django.core.files.uploadedfile import SimpleUploadedFile

        ref = self.client.post("/api/vision/agent/image", {"image": SimpleUploadedFile("a.png", buf.tobytes(), content_type="image/png")}, **auth).json()["ref"]
        r = self.client.post("/api/vision/agent/generate", data=json.dumps({"images": [ref], "prompt": "應該有 5 個孔", "use_llm": False}), content_type="application/json", **auth)
        self.assertEqual(r.status_code, 200, r.content)
        s = AgentSession.objects.get(pk=r.json()["session_id"])
        self.assertEqual(s.owner, User.objects.get(username="admin"))
        self.assertEqual(self.client.get("/api/vision/agent/sessions", **auth).json()["total"], 1)


class CustomSkillTests(TestCase):
    def setUp(self):
        token = self.client.post("/api/auth/setup", data=json.dumps({"username": "admin", "password": "secret123"}), content_type="application/json").json()["token"]
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.user = User.objects.get(username="admin")

    def test_put_get_delete_and_system_epoch(self):
        e0 = skills.epoch()
        res = self.client.put("/api/vision/agent/skills/custom/blob", data=json.dumps({"markdown": "# 我們的粒子要領\n最小面積永遠 ≥ 80。", "scope": "user"}), content_type="application/json", **self.auth)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("個人補充", res.json()["markdown"])
        doc = self.client.get("/api/vision/agent/skills/blob", **self.auth).json()
        self.assertIn("最小面積永遠 ≥ 80", doc["markdown"])
        self.assertEqual(doc["custom"]["user"].startswith("# 我們的粒子要領"), True)
        self.assertTrue(doc["can_site"])
        listed = self.client.get("/api/vision/agent/skills/custom", **self.auth).json()["items"]
        self.assertEqual([(it["key"], it["scope"]) for it in listed], [("blob", "user")])
        # 個人補充進 user 訊息（focus_text），不進快取的 system 段
        self.assertIn("最小面積永遠 ≥ 80", skills.focus_text(["blob"], self.user))
        self.assertNotIn("最小面積永遠 ≥ 80", skills.build_system(skills.epoch()))
        # 站點補充改變 epoch 並進 system 段
        res = self.client.put("/api/vision/agent/skills/custom/design", data=json.dumps({"markdown": "本廠：所有量測一律 mm。", "scope": "site"}), content_type="application/json", **self.auth)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertGreater(skills.epoch(), e0)
        self.assertIn("本廠：所有量測一律 mm", skills.build_system(skills.epoch()))
        self.assertIn("本廠：所有量測一律 mm", skills.build_system_agentic(skills.epoch()))
        # 個人指南補充進 focus_text
        self.client.put("/api/vision/agent/skills/custom/platform", data=json.dumps({"markdown": "我習慣用 ROI 命名 A/B。", "scope": "user"}), content_type="application/json", **self.auth)
        self.assertIn("個人補充：平台規則", skills.focus_text(["blob"], self.user))
        # 刪除與錯誤
        self.assertEqual(self.client.delete("/api/vision/agent/skills/custom/blob?scope=user", **self.auth).status_code, 204)
        self.assertNotIn("最小面積永遠 ≥ 80", self.client.get("/api/vision/agent/skills/blob", **self.auth).json()["markdown"])
        self.assertEqual(self.client.delete("/api/vision/agent/skills/custom/blob?scope=user", **self.auth).status_code, 404)
        self.assertEqual(self.client.put("/api/vision/agent/skills/custom/nope", data=json.dumps({"markdown": "x"}), content_type="application/json", **self.auth).status_code, 404)
        self.assertEqual(self.client.put("/api/vision/agent/skills/custom/blob", data=json.dumps({"markdown": "x", "scope": "bogus"}), content_type="application/json", **self.auth).status_code, 422)
        self.assertEqual(AgentSkill.objects.count(), 2)
