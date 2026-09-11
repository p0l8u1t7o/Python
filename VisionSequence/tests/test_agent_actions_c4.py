"""動作授權與證據回歸；所有執行均走平台 dispatch／工作回答入口。"""

import copy
import json
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import AuthToken, EngineLock
from apps.core.errors import ValidationError
from apps.vision import fixed_images, inspect
from apps.vision.agent import actions, jobs, loop, providers, service
from apps.vision.models import Asset, Flow, ImageSource
from apps.vision.sources_pick import candidates
from tests.fakes import MemoryWriter
from tests.test_agent_loop import LLM, call, reply


def graph():
    return {"nodes": [{"id": "src", "type": "image_source", "params": {"mode": "auto"}},
                      {"id": "thr", "type": "threshold", "params": {"threshold": 60}}],
            "edges": [{"source": "src", "source_handle": "image", "target": "thr", "target_handle": "image"}]}


class ActionC4Tests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.admin = get_user_model().objects.create_user("action-admin", is_staff=True)
        self.state = service.build_state("edit", [np.full((97, 133, 3), 180, np.uint8)], [], "", graph=graph(), instruction="Review", owner=self.admin)
        self.flow = Flow.objects.create(name="Action flow", graph=self.state.graph, owner=self.admin)
        self.state.flow_id = self.flow.id
        self.writer = MemoryWriter({})
        self.addCleanup(jobs._jobs.clear)

    def invoke(self, name, args=None):
        return actions.dispatch(self.state, name, args or {})

    def approve(self, value="approve"):
        pending = self.state.pending_action
        self.assertIsNotNone(pending)
        job = jobs.AgentJob(self.state.job_id, "edit", LLM, self.state, loop.Budget(), status="needs_input", questions=self.state.questions)
        jobs._jobs[job.id] = job
        with mock.patch.object(jobs, "_spawn"):
            jobs.answer(job.id, [{"id": pending["id"], "value": value}])
        self.state.resume_action = False
        return self.invoke(pending["name"], {**pending["args"], "idempotency_key": pending["key"]})

    def assertSucceeded(self, result):
        self.assertEqual(result.get("result"), "succeeded", result)
        self.assertTrue(result.get("evidence"), result)

    def asset(self, kind="image"):
        path = Path(self.temp.name) / (kind + ".json")
        path.write_text('{}', encoding="utf-8")
        return Asset.objects.create(name=kind, kind=kind, path=str(path))

    def task(self):
        self.state.graph = inspect.build(self.state.graph, {"kind": "measure_diameter", "task_id": "diam", "fields": {
            "roi": {"shape": "circle", "cx": 65, "cy": 48, "r": 30}, "unit": "px", "nominal": 40,
            "lower_tol": -2, "upper_tol": 2}})

    def test_select_source_success(self):
        source = ImageSource.objects.create(name="source", kind="synthetic")
        self.assertSucceeded(self.invoke("select_source", {"source_id": source.id}))
        self.assertEqual(self.state.graph["nodes"][0]["params"]["source_id"], source.id)
        result = self.invoke("run_trial")
        self.assertEqual(result["summary"]["ok"], 1, result)

    def test_select_fixed_image_success(self):
        picture = fixed_images.store(self.state.images[0], "sample")
        self.assertSucceeded(self.invoke("select_source", {"type": "fixed_image", "images": [picture]}))
        self.assertEqual(self.state.graph["nodes"][0]["type"], "fixed_image")

    def test_select_asset_success(self):
        self.state.graph["nodes"].append({"id": "match", "type": "template_match", "params": {}})
        asset = self.asset()
        self.assertSucceeded(self.invoke("select_asset", {"node": "match", "param": "template", "asset_id": str(asset.id)}))

    def test_apply_calibration_success(self):
        self.task()
        asset = self.asset("calibration")
        out = self.invoke("apply_calibration", {"task_id": "diam", "asset_id": str(asset.id)})
        self.assertEqual(out["result"], "not_executed", out)
        self.assertSucceeded(self.approve())
        self.assertEqual(inspect.read(self.state.graph)["tasks"][0]["fields"]["unit"], "mm")

    def test_build_task_success(self):
        self.assertSucceeded(self.invoke("build_task", {"kind": "check_presence", "fields": {"method": "blob", "roi": {"shape": "rect", "x": 2, "y": 2, "w": 40, "h": 40}}}))
        self.assertTrue(inspect.read(self.state.graph)["tasks"])

    def test_update_task_success(self):
        self.task()
        self.assertSucceeded(self.invoke("update_task", {"task_id": "diam", "fields": {"num_rays": 90}}))

    def test_remove_task_success(self):
        self.task()
        self.assertSucceeded(self.invoke("remove_task", {"task_id": "diam"}))
        self.assertFalse(inspect.read(self.state.graph)["tasks"])

    def test_connect_source_success(self):
        self.state.graph["edges"] = []
        self.assertSucceeded(self.invoke("connect_source", {"source": "src", "source_handle": "image", "target": "thr", "target_handle": "image"}))
        self.assertEqual(len(self.state.graph["edges"]), 1)

    def test_run_trial_success(self):
        self.assertSucceeded(self.invoke("run_trial"))
        self.assertSucceeded(self.invoke("finish", {"rationale": "Verified"}))

    def test_auto_tune_success(self):
        self.state.expected = ["ok"]
        self.assertSucceeded(self.invoke("auto_tune", {"max_evals": 1}))

    def test_save_flow_version_success_and_replay(self):
        self.state.graph["nodes"][1]["params"]["threshold"] = 70
        args = {"expected_updated_at": self.flow.updated_at.isoformat(), "idempotency_key": "save"}
        self.assertEqual(self.invoke("save_flow_version", args)["result"], "not_executed")
        result = self.approve()
        self.assertSucceeded(result)
        self.assertEqual(self.invoke("save_flow_version", args), result)
        self.flow.refresh_from_db()
        self.assertEqual(self.flow.graph["nodes"][1]["params"]["threshold"], 70)
        self.assertEqual(self.flow.updated_at.isoformat(), result["evidence"]["updated_at"])

    def test_run_batch_success(self):
        self.state.images *= 2
        self.state.expected = ["ok", "ok"]
        self.state.groups = ["tune", "accept"]
        result = self.invoke("run_batch")
        self.assertSucceeded(result)
        self.assertEqual([r["group"] for r in result["results"]], ["tune", "accept"])

    def test_write_output_success_and_idempotency(self):
        args = {"connection_id": 7, "values": {"DO1": 1}, "idempotency_key": "pulse"}
        with mock.patch("apps.comm.writers.get_connection", return_value=mock.Mock(id=7)), mock.patch("apps.comm.writers.open_connection", return_value=self.writer):
            self.assertEqual(self.invoke("write_output", args)["result"], "not_executed")
            self.assertEqual(self.writer.history, [])
            result = self.approve()
            self.assertSucceeded(result)
            self.assertEqual(self.invoke("write_output", args), result)
            self.assertEqual(len(self.writer.history), 1)

    def test_write_text_success(self):
        with mock.patch("apps.comm.writers.get_connection", return_value=mock.Mock(id=7)), mock.patch("apps.comm.writers.open_connection", return_value=self.writer):
            self.invoke("write_output", {"connection_id": 7, "text": "OK"})
            self.assertSucceeded(self.approve())
            self.assertEqual(self.writer.lines, ["OK"])

    def test_save_to_share_success(self):
        path = Path(self.temp.name) / "result.png"
        self.assertEqual(self.invoke("save_to_share", {"path": str(path)})["result"], "not_executed")
        self.assertFalse(path.exists())
        self.assertSucceeded(self.approve())
        self.assertTrue(path.is_file())

    def test_enable_reporting_success(self):
        self.invoke("enable_reporting", {"expected_updated_at": self.flow.updated_at.isoformat(), "comm": [{"connection": "upper", "ok": "OK"}]})
        self.flow.refresh_from_db()
        self.assertFalse(self.flow.comm)
        self.assertSucceeded(self.approve())
        self.flow.refresh_from_db()
        self.assertEqual(self.flow.comm[0]["connection"], "upper")

    def test_unlock_engine_success(self):
        lock = EngineLock.current()
        lock.locked, lock.holder = True, "other"
        lock.save()
        self.invoke("unlock_engine")
        self.assertTrue(EngineLock.current().locked)
        self.assertSucceeded(self.approve())
        self.assertFalse(EngineLock.current().locked)

    def test_delete_flow_success(self):
        self.invoke("delete_flow")
        self.assertTrue(Flow.objects.filter(pk=self.flow.id).exists())
        self.assertSucceeded(self.approve())
        self.assertFalse(Flow.objects.filter(pk=self.flow.id).exists())

    def test_delete_asset_success(self):
        asset = self.asset()
        self.invoke("delete_asset", {"asset_id": str(asset.id)})
        self.assertTrue(Path(asset.path).exists())
        self.assertSucceeded(self.approve())
        self.assertFalse(Path(asset.path).exists())
        self.assertFalse(Asset.objects.filter(pk=asset.id).exists())

    def test_every_action_rejects_missing_permissions(self):
        self.state.principal = mock.Mock(can=mock.Mock(return_value=False))
        for name in actions.ACTION_MAP:
            with self.subTest(action=name):
                out = self.invoke(name)
                self.assertEqual(out["code"], "forbidden")
                self.assertEqual(out["result"], "not_executed")

    def test_each_required_feature_is_checked(self):
        for name, features in actions.FEATURES.items():
            for feature in features:
                with self.subTest(action=name, feature=feature):
                    self.state.principal = mock.Mock(can=lambda f: f != feature)
                    self.assertEqual(self.invoke(name)["code"], "forbidden")

    def test_six_sensitive_actions_reject_without_effects(self):
        cases = [("write_output", {"connection_id": 7, "values": {"DO1": 1}}), ("save_to_share", {"path": str(Path(self.temp.name) / "never.png")}),
                 ("enable_reporting", {"comm": [{}], "expected_updated_at": self.flow.updated_at.isoformat()}), ("unlock_engine", {}),
                 ("delete_flow", {}), ("delete_asset", {"asset_id": str(self.asset().id)})]
        for name, args in cases:
            with self.subTest(action=name), mock.patch.object(actions.ACTION_MAP[name], "handler") as handler:
                self.assertEqual(self.invoke(name, args)["result"], "not_executed")
                self.assertEqual(self.approve("reject")["result"], "not_executed")
                handler.assert_not_called()
        self.assertEqual(self.writer.history, [])
        self.assertTrue(Flow.objects.filter(pk=self.flow.id).exists())

    def test_confirm_cannot_be_skipped_or_forged(self):
        self.invoke("write_output", {"connection_id": 1, "values": {"DO1": 1}, "approved": True})
        pending = self.state.pending_action
        job = jobs.AgentJob(self.state.job_id, "edit", LLM, self.state, loop.Budget(), status="needs_input", questions=self.state.questions)
        jobs._jobs[job.id] = job
        for answers in ([], [{"id": pending["id"], "answer": "approve"}], [{"id": "other", "value": "approve"}]):
            with self.subTest(answers=answers), self.assertRaises(ValidationError):
                jobs.answer(job.id, answers)
        self.assertEqual(job.status, "needs_input")
        self.assertEqual(self.writer.history, [])

    def test_confirmation_bound_to_graph_and_arguments(self):
        self.invoke("delete_flow", {"idempotency_key": "delete"})
        self.state.graph["nodes"][1]["params"]["threshold"] = 72
        self.assertEqual(self.approve()["result"], "not_executed")
        self.assertTrue(Flow.objects.filter(pk=self.flow.id).exists())

    def test_idempotency_key_cannot_change_payload(self):
        self.invoke("delete_flow", {"idempotency_key": "one"})
        out = self.invoke("delete_asset", {"idempotency_key": "one", "asset_id": str(self.asset().id)})
        self.assertEqual(out["result"], "not_executed")
        self.assertIn("different arguments", out["error"])

    def test_timeout_is_uncertain_and_never_retried(self):
        args = {"connection_id": 7, "values": {"DO1": 1}, "idempotency_key": "timeout"}
        with mock.patch("apps.comm.writers.get_connection", return_value=mock.Mock(id=7)), mock.patch("apps.comm.writers.open_connection", return_value=self.writer), mock.patch.object(self.writer, "write", side_effect=TimeoutError("No response")) as write:
            self.invoke("write_output", args)
            result = self.approve()
            self.assertEqual(result["result"], "uncertain")
            self.assertEqual(self.invoke("write_output", args), result)
            write.assert_called_once()

    def test_save_conflict_never_overwrites(self):
        self.invoke("save_flow_version", {"expected_updated_at": self.flow.updated_at.isoformat()})
        other = copy.deepcopy(self.flow.graph)
        other["nodes"][1]["params"]["threshold"] = 81
        editor = get_user_model().objects.create_user("other-editor", is_staff=True)
        response = self.client.patch(f"/api/vision/flows/{self.flow.id}", data=json.dumps({"graph": other, "expected_updated_at": self.flow.updated_at.isoformat()}),
                                     content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {AuthToken.issue(editor)}")
        self.assertEqual(response.status_code, 200, response.content)
        result = self.approve()
        self.assertEqual(result["result"], "not_executed", result)
        self.assertEqual(result["status_code"], 409)
        self.assertTrue(result["evidence"])
        self.flow.refresh_from_db()
        self.assertEqual(self.flow.graph, other)

    def test_guard_engineering_specification_requires_confirmation(self):
        self.task()
        before = copy.deepcopy(self.state.graph)
        out = self.invoke("update_task", {"task_id": "diam", "fields": {"upper_tol": 20}})
        self.assertTrue(out["waiting_for_user"], out)
        self.assertEqual(self.state.graph, before)
        self.assertSucceeded(self.approve())

    def test_guard_missing_calibration_rejected(self):
        self.task()
        before = copy.deepcopy(self.state.graph)
        out = self.invoke("update_task", {"task_id": "diam", "fields": {"unit": "mm", "calibration": ""}})
        self.assertEqual(out["result"], "not_executed")
        self.assertEqual(self.state.graph, before)

    def test_guard_failed_trial_is_not_not_found(self):
        self.state.graph["nodes"][0]["params"]["mode"] = "source"
        out = self.invoke("run_trial")
        self.assertEqual(out["summary"]["failed"], 1, out)
        self.assertEqual(out["summary"]["ng"], 0)
        self.assertTrue(out["summary"]["error_nodes"])

    def test_guard_locator_failure_has_no_valid_measurement(self):
        reference = np.random.default_rng(7).integers(0, 255, (21, 21, 3), dtype=np.uint8)
        picture = fixed_images.store(reference, "locator")
        self.state.graph = inspect.build(self.state.graph, {"kind": "locate_part", "task_id": "loc", "fields": {"template_images": [picture], "ref_x": 10, "ref_y": 10, "threshold": 0.99}})
        self.task()
        self.state.graph = inspect.update(self.state.graph, {"task_id": "diam", "fields": {"locator": "loc"}})
        out = self.invoke("run_trial")
        reading = next(r for r in out["results"][0]["readings"] if r["task_id"] == "diam")
        self.assertEqual(reading["verdict"], "locate_failed")
        self.assertFalse(reading["valid"])
        self.assertIsNone(reading["value"])
        for node in self.state.graph["nodes"]:
            if node.get("meta", {}).get("inspect", {}).get("task_id") == "diam":
                self.assertNotIn("outputs", out["results"][0]["nodes"][node["id"]])

    def test_guard_tune_samples_are_not_acceptance(self):
        self.state.expected = ["ok"]
        out = self.invoke("run_trial")
        self.assertEqual(out["tuning"]["labeled"], 1)
        self.assertIn("No", out["acceptance_note"])

    def test_guard_finish_requires_trial_of_current_graph(self):
        self.assertEqual(self.invoke("finish")["code"], "trial_required")
        self.invoke("run_trial")
        self.invoke("patch_graph", {"ops": [{"op": "set_param", "node": "thr", "key": "threshold", "value": 61}]})
        self.assertEqual(self.invoke("finish", {"idempotency_key": "finish-after-edit"})["code"], "trial_required")
        self.invoke("run_trial", {"idempotency_key": "rerun"})
        self.assertSucceeded(self.invoke("finish", {"idempotency_key": "finish-after-trial"}))

    def test_not_executed_result_is_replayed_with_same_key(self):
        rejected = self.invoke("finish", {"idempotency_key": "finish-attempt"})
        self.invoke("run_trial")
        self.assertEqual(self.invoke("finish", {"idempotency_key": "finish-attempt"}), rejected)
        self.assertFalse(self.state.finished)
        self.assertSucceeded(self.invoke("finish", {"idempotency_key": "finish-new-attempt"}))

    def test_guard_incompatible_source_is_rejected(self):
        self.state.graph["nodes"].append({"id": "number", "type": "formula", "params": {"expression": "1"}})
        out = self.invoke("connect_source", {"source": "number", "source_handle": "value", "target": "thr", "target_handle": "image"})
        self.assertEqual(out["result"], "not_executed")

    def test_guard_ambiguous_source_waits_for_choice(self):
        self.state.graph["nodes"].append({"id": "blur", "type": "blur", "params": {}})
        before = copy.deepcopy(self.state.graph)
        out = self.invoke("connect_source", {"target": "thr", "target_handle": "image"})
        self.assertTrue(out["waiting_for_user"], out)
        self.assertEqual(self.state.questions[0]["kind"], "choice")
        self.assertEqual(self.state.graph, before)
        self.assertSucceeded(self.approve("0"))

    def test_sources_reject_cycles_and_semantic_mismatch(self):
        self.state.graph["nodes"] += [{"id": "fit", "type": "fit_circle", "params": {}}, {"id": "dist", "type": "distance", "params": {}}]
        self.state.graph["nodes"].append({"id": "blur", "type": "blur", "params": {}})
        self.state.graph["edges"].append({"source": "thr", "source_handle": "image", "target": "blur", "target_handle": "image"})
        self.assertFalse(any(e["source"] == "blur" for e in candidates(self.state.graph, "thr", "image")))
        self.assertFalse(any(e["source"] == "fit" and e["source_handle"] == "circle" for e in candidates(self.state.graph, "dist", "a")))

    def test_acquisition_guard_allows_fixed_reference_but_not_two_acquisitions(self):
        g = graph()
        g["nodes"][0].update(type="fixed_image", params={"role": "acquire", "images": []})
        g["nodes"].append({"id": "ref", "type": "fixed_image", "params": {"role": "reference", "images": []}})
        actions.check_graph(g)
        g["nodes"][-1]["params"]["role"] = "acquire"
        with self.assertRaises(ValueError):
            actions.check_graph(g)

    def test_sources_rank_same_task_before_locator_and_other_steps(self):
        g = graph()
        g["nodes"][1]["meta"] = {"inspect": {"task_id": "measure"}}
        g["nodes"] += [
            {"id": "locator", "type": "blur", "params": {}, "meta": {"inspect": {"kind": "locate_part"}}},
            {"id": "same", "type": "blur", "params": {}, "meta": {"inspect": {"task_id": "measure"}}},
        ]
        choices = candidates(g, "thr", "image")
        self.assertEqual([e["source"] for e in choices[:2]], ["same", "locator"])

    def test_multiple_sources_exclude_existing_default_handle(self):
        g = graph()
        g["nodes"].append({"id": "write", "type": "write_modbus", "params": {}})
        g["edges"].append({"source": "src", "source_handle": "", "target": "write", "target_handle": "values"})
        self.assertFalse(any(e["source"] == "src" for e in candidates(g, "write", "values")))

    def test_sensitive_steps_only_added_through_confirmation(self):
        node = {"id": "write", "type": "write_modbus", "params": {"connection": "line", "mapping": [{"src": "judge", "address": "coil:0", "dtype": "bool"}]}}
        unsafe = graph()
        unsafe["nodes"].append(node)
        with self.assertRaises(ValueError):
            actions.check_graph(unsafe)
        self.invoke("write_output", {"node": node})
        self.assertSucceeded(self.approve())
        actions.check_graph(self.state.graph, self.state.approved_nodes)

    def test_crop_template_preserves_approved_output_and_blocks_unapproved_edit(self):
        node = {"id": "write", "type": "write_modbus", "params": {"connection": "line", "mapping": [{"src": "judge", "address": "coil:0", "dtype": "bool"}]}}
        self.invoke("write_output", {"node": node})
        self.assertSucceeded(self.approve())
        picture = fixed_images.store(np.ones((11, 13, 3), dtype=np.uint8), "reference")
        self.state.make_asset = lambda *_: picture
        self.assertSucceeded(self.invoke("crop_template", {"image": 1, "target": "thr", "port": "image", "region": {"shape": "rect", "x": 0, "y": 0, "w": 13, "h": 11}}))
        before = copy.deepcopy(self.state.graph)
        out = self.invoke("patch_graph", {"ops": [{"op": "set_param", "node": "write", "key": "connection", "value": "unreviewed"}]})
        self.assertEqual(out["result"], "not_executed")
        self.assertEqual(self.state.graph, before)

    def test_locked_execution_is_423(self):
        lock = EngineLock.current()
        lock.locked, lock.holder = True, "someone-else"
        lock.save()
        for name in actions.EXECUTION:
            with self.subTest(action=name):
                self.assertEqual(self.invoke(name)["status_code"], 423)

    def test_other_user_cannot_answer_job(self):
        self.invoke("delete_flow")
        job = jobs.AgentJob(self.state.job_id, "edit", LLM, self.state, loop.Budget(), status="needs_input", questions=self.state.questions)
        jobs._jobs[job.id] = job
        other = get_user_model().objects.create_user("other", is_staff=True)
        response = self.client.post(f"/api/vision/agent/jobs/{job.id}/answer", data=json.dumps({"answers": [{"id": self.state.pending_action["id"], "value": "approve"}]}), content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {AuthToken.issue(other)}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(job.status, "needs_input")

    def test_full_provider_loop_confirmation_and_answer(self):
        script = [reply(call("write_output", {"connection_id": 7, "values": {"DO1": 1}}), call("delete_flow")),
                  reply(call("run_trial", {"idempotency_key": "verified"})), reply(call("finish", {"rationale": "Verified"}))]
        history = []
        with mock.patch.object(providers, "complete_tools", side_effect=script), mock.patch("apps.comm.writers.get_connection", return_value=mock.Mock(id=7)), mock.patch("apps.comm.writers.open_connection", return_value=self.writer):
            first = loop.run_loop(LLM, self.state, history)
            self.assertEqual(first.status, "needs_input")
            self.assertFalse(self.writer.history)
            job = jobs.AgentJob(self.state.job_id, "edit", LLM, self.state, loop.Budget(), history=history, turns=first.turns, status="needs_input", questions=self.state.questions)
            jobs._jobs[job.id] = job
            with mock.patch.object(jobs, "_spawn"):
                jobs.answer(job.id, [{"id": self.state.pending_action["id"], "value": "approve"}])
            with mock.patch("django.db.close_old_connections"):
                jobs._run(job)
            self.assertEqual(job.status, "done", job.error)
            self.assertEqual(len(self.writer.history), 1)
            self.assertTrue(Flow.objects.filter(pk=self.flow.id).exists())
            skipped = next(row for row in history if row.get("role") == "tool" and row.get("name") == "delete_flow")
            self.assertEqual(json.loads(skipped["content"])["result"], "not_executed")

    def test_permissions_revoked_while_waiting_are_rechecked(self):
        self.invoke("delete_flow")
        self.admin.is_active = False
        self.admin.save()
        result = self.approve()
        self.assertEqual(result["code"], "forbidden")
        self.assertTrue(Flow.objects.filter(pk=self.flow.id).exists())

    def test_changed_payload_does_not_destroy_cached_evidence(self):
        args = {"connection_id": 7, "values": {"DO1": 1}, "idempotency_key": "pulse"}
        with mock.patch("apps.comm.writers.get_connection", return_value=mock.Mock(id=7)), mock.patch("apps.comm.writers.open_connection", return_value=self.writer):
            self.invoke("write_output", args)
            result = self.approve()
            self.assertEqual(self.invoke("write_output", {**args, "values": {"DO1": 2}})["result"], "not_executed")
            self.assertEqual(self.invoke("write_output", args), result)
            self.assertEqual(len(self.writer.history), 1)

    def test_implicit_idempotency_replays_task_build_without_duplicate(self):
        args = {"kind": "count_objects", "fields": {"min_count": 1, "max_count": 2}}
        first = self.invoke("build_task", args)
        before = copy.deepcopy(self.state.graph)
        self.assertSucceeded(first)
        self.assertEqual(self.invoke("build_task", args), first)
        self.assertEqual(self.state.graph, before)

    def test_no_images_cannot_create_trial_evidence(self):
        self.state.images = []
        self.assertEqual(self.invoke("run_trial")["result"], "not_executed")
        self.assertEqual(self.invoke("finish")["code"], "trial_required")

    def test_free_text_completion_cannot_bypass_finish_guard(self):
        with mock.patch.object(providers, "complete_tools", side_effect=[reply(text="Done"), reply(text="Done")]):
            out = loop.run_loop(LLM, self.state, [])
        self.assertEqual(out.status, "error")

    def test_action_evidence_is_audited(self):
        from apps.core.models import AuditLog

        self.invoke("save_flow_version", {"expected_updated_at": self.flow.updated_at.isoformat()})
        self.assertSucceeded(self.approve())
        self.assertTrue(AuditLog.objects.filter(action="agent.save_flow_version", target_id=str(self.flow.id)).exists())

    def test_pending_confirmation_retains_kind_after_chat_cleanup(self):
        from apps.vision.agent import chats

        self.invoke("delete_flow")
        cleaned = chats.clean_state({"pending_questions": self.state.questions})
        self.assertEqual(cleaned["pending_questions"][0]["kind"], "confirm")

    def test_unlock_request_reaches_action_loop_while_locked(self):
        lock = EngineLock.current()
        lock.locked, lock.holder = True, "another-holder"
        lock.save()
        headers = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(self.admin)}"}
        with mock.patch.object(providers, "resolve", return_value=LLM):
            response = self.client.post("/api/vision/agent/chat", data=json.dumps({"message": "unlock the engine", "context": {"kind": "flow_editor", "flow_id": self.flow.id, "graph": self.state.graph}}), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["agentic"])
        with mock.patch.object(jobs, "_spawn"):
            response = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "edit", "flow_id": self.flow.id, "graph": self.state.graph, "instruction": "unlock the engine"}), content_type="application/json", **headers)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertTrue(EngineLock.current().locked)
