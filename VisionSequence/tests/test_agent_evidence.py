"""助手影像證據、獨立驗收與失敗案例的入口回歸。"""

import base64
import copy
import json
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np
from django.test import TestCase

from apps.vision.agent import actions, autotune, loop, memory, providers, service
from apps.vision.images import store
from apps.vision.models import Flow
from tests.test_agent_loop import call, part_image, reply, LLM


def graph():
    return {"nodes": [{"id": "src", "type": "image_source", "params": {"mode": "input"}},
                      {"id": "blob", "type": "blob", "params": {"polarity": "dark", "min_area": 50}}],
            "edges": [{"source": "src", "source_handle": "image", "target": "blob", "target_handle": "image"}]}


def report(status="ok"):
    return SimpleNamespace(status=status, outputs={}, nodes={})


class EvidenceTests(TestCase):
    def state(self):
        return service.build_state("edit", [part_image(1)], [], "", graph=graph(), instruction="inspect")

    def test_node_picture_real_engine_and_cache_cleanup(self):
        state = self.state()
        original = state.images[0].copy()
        before = store.stats()["images"]
        result = actions.dispatch(state, "inspect_node", {"node": "blob", "max_side": 321})
        self.assertNotIn("error", result)
        self.assertEqual(result["picture"]["width"], 321)
        self.assertTrue(result["overlay_summary"])
        self.assertEqual(store.stats()["images"], before)
        np.testing.assert_array_equal(original, state.images[0])
        invalid = actions.dispatch(state, "inspect_node", {"node": "blob", "image_port": "count"})
        self.assertIn("error", invalid)
        self.assertEqual(store.stats()["images"], before)
        state.pictures = actions.MAX_PICTURES
        with mock.patch.object(service, "trial_run") as trial:
            self.assertEqual(actions.h_inspect_node(state, {"node": "blob"}), {"error": "picture budget exhausted"})
            trial.assert_not_called()

    def test_real_circle_node_thumbnail_coordinates(self):
        from apps.vision import inspect
        from tests.test_inspect import annulus_image, base_graph, diameter_task

        scene = annulus_image()
        task_graph = inspect.build(base_graph(), diameter_task("diameter"))
        node = next(n["id"] for n in task_graph["nodes"] if n["type"] == "find_circle")
        state = service.build_state("edit", [scene], [], "", graph=task_graph)
        out = actions.dispatch(state, "inspect_node", {"node": node, "crop": {"shape": "rect", "x": 200, "y": 100, "w": 601, "h": 501}, "max_side": 333})
        self.assertNotIn("error", out)
        circle = next(ov for ov in out["overlay_summary"] if ov["kind"] == "circle")
        width, height = out["picture"]["width"], out["picture"]["height"]
        error = float(np.hypot(circle["cx"] - (500 - 200) * width / 601, circle["cy"] - (350 - 100) * height / 501))
        self.assertLess(error, 1)
        raw = base64.b64decode(out["picture"]["data_base64"])
        decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        x, y = round(circle["cx"] + circle["r"]), round(circle["cy"])
        patch = decoded[max(0, y - 3):y + 4, max(0, x - 3):x + 4]
        self.assertGreater(int(patch[:, :, 1].max()), 100)
        print(f"Real inspect_node circle: {width}x{height}, {len(raw)} bytes, centre error {error:.6f} px")

    def test_crop_overlay_coordinates_bytes_and_colors(self):
        image = np.zeros((701, 1001, 3), np.uint8)
        overlays = [{"kind": "circle", "cx": 400., "cy": 300., "r": 80., "color": "#22c55e"}]
        saved = copy.deepcopy(overlays)
        for status, channel in (("ok", 1), ("ng", 2)):
            out = actions.evidence_picture(image, overlays, {"shape": "rect", "x": 100, "y": 50, "w": 601, "h": 501}, 333, status)
            pic = out["picture"]
            data = base64.b64decode(pic["data_base64"])
            decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(decoded.shape[:2], (pic["height"], pic["width"]))
            self.assertLessEqual(len(data), 200 * 1024)
            ov = out["overlay_summary"][0]
            self.assertLess(abs(ov["cx"] - 300 * 333 / 601), 1)
            self.assertLess(abs(ov["cy"] - 250 * pic["height"] / 501), 1)
            x, y = round(ov["cx"] + ov["r"]), round(ov["cy"])
            patch = decoded[y - 2:y + 3, x - 2:x + 3]
            self.assertGreater(patch[:, :, channel].max(), 80)
            self.assertEqual(int(patch.reshape(-1, 3).sum(axis=0).argmax()), channel)
        self.assertEqual(overlays, saved)
        self.assertFalse(image.any())
        noise = np.random.default_rng(12).integers(0, 256, (1201, 1601, 3), np.uint8)
        pic = actions.evidence_picture(noise, [], max_side=5000)["picture"]
        self.assertLessEqual(max(pic["width"], pic["height"]), 1024)
        self.assertLessEqual(len(base64.b64decode(pic["data_base64"])), 200 * 1024)
        self.assertLess(pic["width"], 1024)
        print(f"Evidence: {pic['width']}x{pic['height']}, {len(base64.b64decode(pic['data_base64']))} bytes; circle coordinate error < 1 px")

    def test_provider_images_and_tool_order(self):
        picture = {"mime": "image/jpeg", "data_base64": "aGVsbG8=", "width": 1, "height": 1}
        history = [{"role": "assistant", "tool_calls": [{"id": "a", "name": "inspect_node"}, {"id": "b", "name": "get_state"}]},
                   {"role": "tool", "tool_call_id": "a", "name": "inspect_node", "content": '{"node":"blob"}', "picture": picture},
                   {"role": "tool", "tool_call_id": "b", "name": "get_state", "content": '{}'}]
        original = copy.deepcopy(history)
        cm = providers.claude_messages(history)
        self.assertEqual(cm[1]["content"][0]["content"][1]["source"]["data"], picture["data_base64"])
        om = providers.openai_messages("system", history)
        self.assertEqual([m["role"] for m in om], ["system", "assistant", "tool", "tool", "user"])
        self.assertIn(picture["data_base64"], om[-1]["content"][1]["image_url"]["url"])
        gm = providers.gemini_contents(history)
        self.assertEqual(gm[1]["parts"][1]["inlineData"]["data"], picture["data_base64"])
        self.assertIn("functionResponse", gm[1]["parts"][2])
        text = providers.text_only_history(history)
        self.assertNotIn("picture", text[1])
        self.assertIn("text-only", text[1]["content"])
        self.assertEqual(history, original)

    def test_loop_keeps_picture_outside_truncated_text_and_counts_initial(self):
        state = self.state()
        history = []
        with mock.patch.object(providers, "complete_tools", side_effect=[reply(call("inspect_node", {"node": "blob"})), reply(call("finish", {"rationale": "Done"}))]):
            out = loop.run_loop(LLM, state, history)
        self.assertEqual(out.status, "done")
        turn = next(t for t in history if t["role"] == "tool" and t["name"] == "inspect_node")
        self.assertIn("picture", turn)
        self.assertNotIn("data_base64", turn["content"])
        self.assertIn("overlay_summary", json.loads(turn["content"]))
        self.assertEqual(state.pictures, 2)

    def test_autotune_search_never_receives_acceptance(self):
        images = [np.full((3, 3), i, np.uint8) for i in range(3)]
        state = service.build_state("edit", images, [], "", graph=graph(), labels=[{"expected": "ok", "group": "tune"}, {"expected": "ng", "group": "accept"}, "ok"])
        searched, validated = [], []

        def search(g, samples, **kw):
            searched.extend(int(s.image[0, 0]) for s in samples)
            return {"graph": g, "before": {"match": 1, "total": 2}, "after": {"match": 2, "total": 2}, "improved": False, "change_text": [], "evals": 1, "budget_hit": False, "changes": [], "elapsed_ms": 1}

        def trial(g, im, **kw):
            validated.append(int(im[0, 0]))
            return report("ng" if im[0, 0] == 1 else "ok")

        with mock.patch.object(autotune, "coordinate_search", side_effect=search), mock.patch.object(service, "trial_run", side_effect=trial):
            out = actions.h_auto_tune(state, {})
        self.assertEqual(searched, [0, 2])
        self.assertEqual(validated, [1])
        self.assertEqual(out["acceptance"], {"ok": 0, "ng": 1, "matches": 1, "labeled": 1})
        runs = [{"image_ref": str(i), "expected": "ng" if i == 1 else "ok", "group": "accept" if i == 1 else "tune"} for i in range(3)]
        searched.clear()
        with mock.patch.object(autotune, "coordinate_search", side_effect=search), mock.patch.object(service, "_rerun_items", return_value=[{**r, "after": r["expected"]} for r in runs]):
            out = service.autotune_runs(graph(), runs, dict(zip(map(str, range(3)), images)))
        self.assertEqual(searched, [0, 2])
        self.assertEqual(out["acceptance"]["matches"], 1)
        self.assertIn("Tune group", out["rationale"])
        self.assertIn("Acceptance group", out["rationale"])

    def test_search_defense_and_empty_acceptance(self):
        seen = []
        samples = [autotune.Labeled(np.full((1, 1), i), "ok", group=g) for i, g in enumerate(["tune", "accept"])]
        autotune.coordinate_search(graph(), samples, trial=lambda g, im: (seen.append(int(im[0, 0])) or report()))
        self.assertEqual(seen, [0])
        self.assertEqual(autotune.acceptance_text(autotune.acceptance_rows([])), "No independent acceptance.")

    def test_lessons_roundtrip_failure_recall_not_prior(self):
        feats = {"full": {"mean": 100, "area": 100}}
        failed = memory.remember(owner=None, task="generate", prompt="glare", intent_kind="count", images=[], regions=[], answers=[], labels=[],
                                 analysis=feats, graph=graph(), rationale="Wrong edge", candidates=[], statuses=["failed"], provider="rules",
                                 lessons={"outcome": "failure", "failure_reasons": ["glare"], "conditions": {"lighting": "side light"}})
        self.assertIsNotNone(failed)
        found, priors, examples = service.recall("count", feats)
        self.assertEqual(found[0][0].pk, failed.pk)
        self.assertFalse(priors)
        self.assertIn("Avoid", examples)
        self.assertIn("glare", examples)
        self.assertIn("side light", examples)
        path = f"/api/vision/agent/sessions/{failed.pk}"
        response = self.client.patch(path, data=json.dumps({"lessons": {"outcome": "failure", "failure_reasons": ["wrong_edge"]}}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["lessons"]["failure_reasons"], ["wrong_edge"])
        response = self.client.patch(path, data=json.dumps({"lessons": {"failure_reasons": ["invented"]}}), content_type="application/json")
        self.assertEqual(response.status_code, 422)

    def test_batch_group_api_and_autotune_subset(self):
        from apps.vision.batch import jobs, store as bstore
        from apps.vision.models import BatchSet, BatchRun

        flow = Flow.objects.create(name="Evidence", graph=graph())
        batch = BatchSet.objects.create(flow=flow, name="Groups")
        bstore.save_images(batch, [(str(i), np.full((3, 3), i, np.uint8)) for i in range(3)])
        response = self.client.patch(f"/api/vision/batch/sets/{batch.pk}", data=json.dumps({"labels": [{"index": i, "expected": "ok", "group": "accept" if i == 1 else "tune"} for i in range(3)]}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        batch.refresh_from_db()
        self.assertEqual([im["group"] for im in response.json()["images"]], ["tune", "accept", "tune"])
        run = BatchRun.objects.create(batch_set=batch, flow=flow, graph=graph())
        with mock.patch.object(autotune, "coordinate_search", wraps=autotune.coordinate_search) as search, mock.patch.object(service, "trial_run", return_value=report()):
            jobs._autotune_graph(jobs.BatchJob(run_id=run.pk, set_id=batch.pk), run, batch, batch.images)
        self.assertEqual([int(lb.image[0, 0]) for lb in search.call_args.args[1]], [0, 2])

    def test_golden_autotune_group_mapping(self):
        from apps.golden.models import GoldenCase

        flow = Flow.objects.create(name="Golden evidence", graph=graph())
        cases = [GoldenCase.objects.create(flow=flow, name=str(i), image_path=str(i), expect_status="ok") for i in range(3)]
        validated = []

        def trial(g, im, **kw):
            validated.append(int(im[0, 0]))
            return report()

        original = autotune.coordinate_search
        with mock.patch("apps.golden.regress.load_image", side_effect=lambda path: np.full((2, 2), int(path))), mock.patch.object(service, "trial_run", side_effect=trial), mock.patch.object(autotune, "coordinate_search", wraps=original) as search_mock:
            response = self.client.post(f"/api/vision/flows/{flow.pk}/golden/autotune", data=json.dumps({"groups": {str(cases[1].pk): "accept"}}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([int(s.image[0, 0]) for s in search_mock.call_args.args[1]], [0, 2])
        self.assertEqual(validated, [0, 2, 1])
        self.assertEqual(response.json()["acceptance"]["matches"], 1)

    def test_generation_and_jobs_labels_keep_acceptance_out_of_search(self):
        refs = [store.put(f"stage12:{i}", part_image(i + 1), flow_id=0, run_id=f"stage12-{i}", pinned=True)["ref"] for i in range(3)]
        labels = [{"expected": "ok", "group": "tune"}, {"expected": "ng", "group": "accept"}, {"expected": "ng", "group": "tune"}]
        body = {"images": refs, "labels": labels, "prompt": "count 1", "use_llm": False}
        with mock.patch.object(autotune, "coordinate_search", wraps=autotune.coordinate_search) as search, mock.patch.object(service, "_rank_candidates", wraps=service._rank_candidates) as rank:
            response = self.client.post("/api/vision/agent/generate", data=json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(rank.call_args.args[3], ["tune", "accept", "tune"])
        for called in search.call_args_list:
            self.assertEqual(len(called.args[1]), 2)
            self.assertTrue(all(lb.group == "tune" for lb in called.args[1]))
        self.assertEqual(response.json()["acceptance"]["labeled"], 1)
        with mock.patch("apps.vision.agent.jobs.start", return_value={"id": "test"}) as start:
            response = self.client.post("/api/vision/agent/jobs", data=json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(start.call_args.args[2].groups, ["tune", "accept", "tune"])
        for i in range(3):
            store.drop_run(f"stage12-{i}")

    def test_failure_job_without_graph_is_remembered(self):
        from apps.vision.agent import jobs
        from apps.vision.models import AgentSession

        state = self.state()
        state.graph = None
        job = jobs.AgentJob("failure", "generate", providers.AgentSettings(), state, loop.Budget())
        with mock.patch.object(jobs, "_run_single", side_effect=ValueError("test failure")), mock.patch("django.db.close_old_connections"):
            jobs._run(job)
        self.assertEqual(job.status, "error")
        saved = AgentSession.objects.get(pk=job.result["session_id"])
        self.assertEqual(saved.lessons["outcome"], "failure")
        self.assertIn("tool_error", saved.lessons["failure_reasons"])

    def test_batch_creation_interval_and_validation(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        flow = Flow.objects.create(name="Grouped upload", graph=graph())
        raw = cv2.imencode(".png", part_image(1))[1].tobytes()
        response = self.client.post("/api/vision/batch/sets", {"flow_id": flow.pk, "accept_every": 2,
                                   "images": [SimpleUploadedFile(f"{i}.png", raw, content_type="image/png") for i in range(3)]})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([im["group"] for im in response.json()["images"]], ["tune", "accept", "tune"])
        response = self.client.patch(f"/api/vision/batch/sets/{response.json()['id']}", data=json.dumps({"labels": [{"index": 0, "group": "invalid"}]}), content_type="application/json")
        self.assertEqual(response.status_code, 422)

    def test_persisted_acceptance_survives_later_group_changes(self):
        from apps.vision.agent import jobs
        from apps.vision.batch import store as bstore
        from apps.vision.models import BatchSet, BatchRun

        flow = Flow.objects.create(name="Evidence snapshot", graph=graph())
        batch = BatchSet.objects.create(flow=flow, name="Snapshot", images=[{"index": 0, "expected": "ok", "group": "accept"}])
        run = BatchRun.objects.create(batch_set=batch, flow=flow, graph=graph())
        accepted = {"ok": 1, "ng": 0, "matches": 1, "labeled": 1}
        job = jobs.AgentJob("persist", "tune", providers.AgentSettings(), self.state(), loop.Budget(), batch_run_id=run.pk, result={"acceptance": accepted})
        jobs._persist_batch(job, graph(), [{"index": 0, "status": "ok", "duration_ms": 1, "outputs": {}, "error": "", "error_node": None, "nodes": {}}], "Done", [])
        saved = BatchRun.objects.get(pk=job.result["batch_run_id"])
        batch.images[0]["group"] = "tune"
        batch.save(update_fields=["images"])
        bstore.refresh_matches(batch)
        saved.refresh_from_db()
        self.assertEqual(saved.meta["acceptance"], accepted)
