"""助手對話：建立／列出／載入／覆寫／刪除、只看得到自己的、上限淘汰。"""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from apps.accounts.models import AuthToken
from apps.vision.agent import chats
from apps.vision.models import AssistantChat, Flow


def msg(role: str, text: str) -> dict:
    return {"id": f"{role}-{text}", "role": role, "text": text, "at": 1}


class ChatStoreTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("kate", password="x")

    def test_title_comes_from_the_first_question(self):
        row = chats.create(self.user, [msg("assistant", "您好"), msg("user", "怎麼建立流程？"), msg("user", "第二句")])
        self.assertEqual(row.title, "怎麼建立流程？")
        self.assertEqual(len(row.messages), 3)

    def test_messages_are_capped_and_cleaned(self):
        row = chats.create(self.user, [*(msg("user", str(i)) for i in range(chats.MAX_MESSAGES + 10)), {"role": "nonsense"}, "junk"])
        self.assertEqual(len(row.messages), chats.MAX_MESSAGES)
        self.assertEqual(row.messages[-1]["text"], str(chats.MAX_MESSAGES + 9))

    def test_huge_messages_drop_the_oldest(self):
        big = [msg("user", "x" * (chats.MAX_BYTES + 1000)), msg("user", "小的")]
        row = chats.create(self.user, big)
        self.assertEqual([m["text"] for m in row.messages], ["小的"])

    def test_prune_keeps_the_newest(self):
        for i in range(chats.MAX_CHATS + 3):
            chats.create(self.user, [msg("user", f"q{i}")])
        self.assertEqual(AssistantChat.objects.filter(owner=self.user).count(), chats.MAX_CHATS)
        self.assertEqual(AssistantChat.objects.filter(owner=self.user).first().title, f"q{chats.MAX_CHATS + 2}")


class ChatApiTests(TestCase):
    def _token(self, username: str = "admin") -> str:
        if not User.objects.exists():
            r = self.client.post("/api/auth/setup", data=json.dumps({"username": username, "password": "Admin12345"}), content_type="application/json")
            self.assertIn(r.status_code, (200, 201), r.content)
            return r.json()["token"]
        return AuthToken.issue(User.objects.create_user(username, password="Passw0rd!"))

    def test_round_trip(self):
        head = {"HTTP_AUTHORIZATION": f"Bearer {self._token()}"}
        r = self.client.get("/api/vision/agent/chats", **head)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["items"], [])
        self.assertEqual(r.json()["limits"]["messages"], chats.MAX_MESSAGES)

        r = self.client.post("/api/vision/agent/chats", data=json.dumps({"messages": [msg("user", "怎麼標定？")]}),
                             content_type="application/json", **head)
        self.assertEqual(r.status_code, 201, r.content)
        chat = r.json()
        self.assertEqual(chat["title"], "怎麼標定？")

        r = self.client.patch(f"/api/vision/agent/chats/{chat['id']}",
                              data=json.dumps({"messages": [msg("user", "怎麼標定？"), msg("assistant", "看標定頁")]}),
                              content_type="application/json", **head)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["count"], 2)

        r = self.client.get(f"/api/vision/agent/chats/{chat['id']}", **head)
        self.assertEqual([m["role"] for m in r.json()["messages"]], ["user", "assistant"])
        self.assertEqual(self.client.get("/api/vision/agent/chats", **head).json()["items"][0]["count"], 2)

        r = self.client.patch(f"/api/vision/agent/chats/{chat['id']}", data=json.dumps({"title": "標定筆記"}),
                              content_type="application/json", **head)
        self.assertEqual(r.json()["title"], "標定筆記")

        self.assertEqual(self.client.delete(f"/api/vision/agent/chats/{chat['id']}", **head).status_code, 204)
        self.assertEqual(self.client.get("/api/vision/agent/chats", **head).json()["items"], [])
        self.assertEqual(self.client.get(f"/api/vision/agent/chats/{chat['id']}", **head).status_code, 404)

    def test_only_my_own_conversations(self):
        mine = self._token()
        other_user = User.objects.create_user("bob", password="Passw0rd!")
        chats.create(other_user, [msg("user", "別人的")])
        head = {"HTTP_AUTHORIZATION": f"Bearer {mine}"}
        self.assertEqual(self.client.get("/api/vision/agent/chats", **head).json()["items"], [])
        theirs = AssistantChat.objects.get(owner=other_user)
        self.assertEqual(self.client.get(f"/api/vision/agent/chats/{theirs.pk}", **head).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/vision/agent/chats/{theirs.pk}", **head).status_code, 404)
        self.assertTrue(AssistantChat.objects.filter(pk=theirs.pk).exists())

    def test_integrator_has_no_conversations(self):
        self._token()  # 有使用者了，未帶 token 就是整合方／未登入
        self.assertEqual(self.client.get("/api/vision/agent/chats").status_code, 401)


class WorkStateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("progress", password="x", is_staff=True, is_superuser=True)
        self.other = User.objects.create_user("other", password="x", is_staff=True, is_superuser=True)
        self.head = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(self.user)}"}
        self.flow = Flow.objects.create(name="Cup", graph={"nodes": [{"id": "threshold", "type": "threshold", "params": {"threshold": 60}}], "edges": []})
        self.chat = chats.create(self.user, flow_id=self.flow.pk)

    def patch(self, body):
        return self.client.patch(f"/api/vision/agent/chats/{self.chat.pk}", data=json.dumps(body), content_type="application/json", **self.head)

    def resume(self):
        result = self.client.get(f"/api/vision/agent/chats/{self.chat.pk}/resume", **self.head)
        self.assertEqual(result.status_code, 200, result.content)
        return result.json()

    def test_binding_can_be_assigned_once_and_same_flow_can_have_many_chats(self):
        second = chats.create(self.user)
        second = chats.save(second, flow_id=self.flow.pk)
        self.assertEqual(second.flow_id, self.flow.pk)
        self.assertEqual(self.patch({"flow_id": self.flow.pk}).status_code, 200)
        another = Flow.objects.create(name="Other")
        for value in (another.pk, None):
            response = self.patch({"flow_id": value})
            self.assertEqual(response.status_code, 422, response.content)
            self.assertEqual(response.json()["error"]["code"], "chat_bound")

    def test_unknown_flow_is_rejected(self):
        response = self.client.post("/api/vision/agent/chats", data=json.dumps({"flow_id": 999999}), content_type="application/json", **self.head)
        self.assertEqual(response.status_code, 404)

    def test_unchanged_resume_and_message_save_preserve_baseline(self):
        self.assertFalse(self.resume()["changed"])
        baseline = self.resume()["work_state"]["flow_updated_at"]
        self.patch({"messages": [msg("user", "Continue")], "work_state": {"decisions": [{"at": "2026-09-11", "text": "Use the left reference", "by": "user"}]}})
        result = self.resume()
        self.assertEqual(result["work_state"]["flow_updated_at"], baseline)
        self.assertEqual(result["work_state"]["decisions"][0]["by"], "user")
        self.assertNotIn("graph", result["work_state"])

    def test_next_day_other_user_save_returns_parameter_diff(self):
        state = {"pending_questions": [{"id": "unit", "text": "Which unit?", "kind": "text"}],
                 "last_trial": {"at": "2026-09-10", "status": "ng", "summary": "One task failed", "per_task": [{"task_id": "t1", "status": "fail", "value": 9.5}]}}
        self.assertEqual(self.patch({"work_state": state}).status_code, 200)
        graph = {"nodes": [{"id": "threshold", "type": "threshold", "params": {"threshold": 46}}], "edges": []}
        result = self.client.patch(f"/api/vision/flows/{self.flow.pk}", data=json.dumps({"graph": graph, "expected_updated_at": self.flow.updated_at.isoformat()}),
                                   content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {AuthToken.issue(self.other)}")
        self.assertEqual(result.status_code, 200, result.content)
        # 普通訊息的 autosave 不可抹掉跨天變更證據。
        self.patch({"messages": [msg("user", "Continue tomorrow")]})
        resumed = self.resume()
        self.assertTrue(resumed["changed"])
        self.assertIn("threshold 60 → 46", resumed["diff_summary"])
        self.assertEqual(resumed["work_state"]["last_trial"]["per_task"][0]["value"], 9.5)
        self.assertEqual(resumed["flow"]["version"], 2)
        self.assertEqual(resumed["work_state"]["flow_version"], 1)

    def test_deleted_flow_still_cannot_be_rebound_or_forged_in_state(self):
        original = self.flow.pk
        self.flow.delete()
        result = self.resume()
        self.assertTrue(result["flow_missing"])
        self.assertEqual(result["work_state"]["flow_id"], original)
        another = Flow.objects.create(name="Replacement")
        self.patch({"work_state": {"flow_id": another.pk}})
        self.assertEqual(self.patch({"flow_id": another.pk}).status_code, 422)
        self.assertEqual(self.resume()["work_state"]["flow_id"], original)

    def test_pruned_history_reports_unavailable_without_inventing_changes(self):
        self.flow.versions.all().delete()
        self.flow.name = "Renamed"
        self.flow.save()
        self.assertTrue(self.resume()["changed"])
        self.assertIn("no longer available", self.resume()["diff_summary"])

    def test_other_user_cannot_read_patch_resume_or_use_chat(self):
        self.head = {"HTTP_AUTHORIZATION": f"Bearer {AuthToken.issue(self.other)}"}
        for suffix in ("", "/resume"):
            self.assertEqual(self.client.get(f"/api/vision/agent/chats/{self.chat.pk}{suffix}", **self.head).status_code, 404)
        self.assertEqual(self.patch({"work_state": {"version": 1}}).status_code, 404)
        response = self.client.post("/api/vision/agent/chat", data=json.dumps({"chat_id": self.chat.pk, "message": "How to continue?"}), content_type="application/json", **self.head)
        self.assertEqual(response.status_code, 404)

    def test_clean_state_whitelist_and_utf8_limit(self):
        draft = {"draft_id": "d", "op": "add", "kind": "count_objects", "fields": {"roi": {"value": "x" * 2000, "status": "confirmed"}}, "regions": []}
        state = chats.clean_state({"version": 1, "graph": self.flow.graph, "specifications": {"diameter": 10},
                                   "decisions": [{"at": "today", "text": "甲" * 1000, "by": "user"}] * 60,
                                   "drafts": [draft] * 60, "sample_groups": {"tune": ["ref"], "accept": ["data:image/png;base64,abc"]},
                                   "assumptions": [{"field": "roi", "value": {"x": float("inf"), "image": "secret"}}]})
        self.assertLessEqual(len(json.dumps(state, ensure_ascii=False).encode("utf-8")), 64 * 1024)
        self.assertNotIn("graph", state)
        self.assertNotIn("specifications", state)
        self.assertEqual(state["sample_groups"], {"tune": ["ref"], "accept": []})
        self.assertEqual(state["assumptions"][0]["value"], {"x": None})
        single = chats.clean_state({"drafts": [draft]})
        self.assertEqual(single["drafts"][0]["fields"]["roi"]["status"], "missing")
        self.assertEqual(chats.clean_state([]), {})
        self.assertEqual(chats.clean_state({"assumptions": [{"field": "n", "value": 10 ** 1000}]})["assumptions"][0]["value"], None)

    def test_unknown_state_version_rejected_and_malformed_rows_ignored(self):
        self.assertEqual(self.patch({"work_state": {"version": 2}}).status_code, 422)
        state = chats.clean_state({"pending_questions": [None, {}, {"id": "q", "text": "Unit?", "kind": "number"}],
                                   "drafts": ["bad", {"draft_id": "d", "op": "invalid"}], "decisions": [{"text": "bad", "by": "model"}]})
        self.assertEqual(len(state["pending_questions"]), 1)
        self.assertEqual(state["drafts"], [])
        self.assertEqual(state["decisions"], [])

    def test_progress_enters_help_context_and_writes_are_best_effort(self):
        chats.save(self.chat, work_state={"pending_questions": [{"id": "q", "text": "Which unit?"}]})
        with mock.patch("apps.vision.agent.help.answer", return_value={"answer": "Check the unit", "provider": "rules"}) as answer:
            response = self.client.post("/api/vision/agent/chat", data=json.dumps({"chat_id": self.chat.pk, "message": "How can I continue?", "context": {"flow_id": self.flow.pk}}), content_type="application/json", **self.head)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(answer.call_args.kwargs["context"]["work_state"]["pending_questions"][0]["text"], "Which unit?")
        with mock.patch.object(chats, "save", side_effect=RuntimeError("write failed")), self.assertLogs(chats.log, level="ERROR"):
            chats.record(self.chat, {}, "Trial completed")

    def test_backend_decisions_survive_an_older_frontend_snapshot(self):
        chats.record(self.chat, {}, "Tuning completed")
        self.patch({"work_state": {"decisions": []}})
        self.assertEqual(self.resume()["work_state"]["decisions"][0]["text"], "Tuning completed")

    def test_proposals_persist_across_replies_and_progress_failure_does_not_fail_action(self):
        draft = {"draft_id": "d1", "kind": "count_objects", "op": "add", "regions": [],
                 "fields": {"min_count": {"value": 5, "status": "assumed", "source": "rule", "note": "Confirm count"}}}
        body = {"chat_id": self.chat.pk, "message": "Count 5 objects", "context": {"kind": "inspect", "flow_id": self.flow.pk, "graph": self.flow.graph}}
        result = {"drafts": [draft], "questions": [], "warnings": [], "kinds": [], "provider": "rules"}
        with mock.patch("apps.vision.agent.tasklist.propose", return_value=result):
            response = self.client.post("/api/vision/agent/chat", data=json.dumps(body), content_type="application/json", **self.head)
        self.assertEqual(response.status_code, 200, response.content)
        state = self.resume()["work_state"]
        self.assertEqual(state["drafts"][0]["draft_id"], "d1")
        self.assertEqual(state["assumptions"][0]["value"], 5)
        with mock.patch("apps.vision.agent.tasklist.propose", return_value=result), mock.patch.object(chats, "save", side_effect=RuntimeError("write failed")), self.assertLogs(chats.log, level="ERROR"):
            response = self.client.post("/api/vision/agent/chat", data=json.dumps(body), content_type="application/json", **self.head)
        self.assertEqual(response.status_code, 200, response.content)

    def test_chat_action_cannot_switch_the_bound_flow(self):
        flow = Flow.objects.create(name="Other")
        body = {"chat_id": self.chat.pk, "message": "How to continue?", "context": {"flow_id": flow.pk}}
        response = self.client.post("/api/vision/agent/chat", data=json.dumps(body), content_type="application/json", **self.head)
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()["error"]["code"], "chat_bound")

    def test_agent_job_receives_the_same_progress_context(self):
        chats.save(self.chat, work_state={"pending_questions": [{"id": "q", "text": "Which unit?"}]})
        with mock.patch("apps.vision.agent.jobs.start", return_value={"id": "j", "status": "running"}) as start:
            response = self.client.post("/api/vision/agent/jobs", data=json.dumps({"chat_id": self.chat.pk, "flow_id": self.flow.pk,
                "task": "edit", "graph": self.flow.graph, "instruction": "Set the threshold to 40"}), content_type="application/json", **self.head)
        self.assertEqual(response.status_code, 202, response.content)
        self.assertIn("Which unit?", start.call_args.args[2].batch_summary)

    def test_create_returns_the_persisted_work_state(self):
        state = {"decisions": [{"at": "today", "text": "Use reference A", "by": "user"}]}
        response = self.client.post("/api/vision/agent/chats", data=json.dumps({"flow_id": self.flow.pk, "work_state": state}), content_type="application/json", **self.head)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["work_state"]["decisions"], state["decisions"])

    def test_empty_autosave_does_not_create_a_resume_card_for_general_chat(self):
        row = chats.create(self.user)
        row = chats.save(row, [msg("user", "How does calibration work?")], work_state={})
        self.assertEqual(chats.out(row, with_messages=True)["work_state"], {})

    def test_background_job_saves_progress_without_frontend_polling(self):
        from apps.vision.agent import jobs

        chats.save(self.chat, work_state={"pending_questions": [{"id": "other", "text": "Which reference?"}]})
        def complete(job):
            job.status = "done"
            job.result = {"report": {"status": "ng"}, "rationale": "One inspection failed"}
        with mock.patch.object(jobs, "_spawn", side_effect=jobs._run), mock.patch.object(jobs, "_run_single", side_effect=complete), \
                mock.patch.object(jobs.providers, "available", return_value=False), mock.patch.object(jobs.memory, "remember", return_value=None), \
                mock.patch("django.db.close_old_connections"):
            response = self.client.post("/api/vision/agent/jobs", data=json.dumps({"chat_id": self.chat.pk, "flow_id": self.flow.pk,
                "task": "edit", "graph": self.flow.graph, "instruction": "Set the threshold to 40"}), content_type="application/json", **self.head)
        self.assertEqual(response.status_code, 202, response.content)
        state = self.resume()["work_state"]
        self.assertEqual(state["last_trial"]["status"], "ng")
        self.assertEqual(state["last_trial"]["summary"], "One inspection failed")
        self.assertEqual(state["decisions"][-1]["by"], "assistant")
        self.assertEqual(state["pending_questions"][0]["id"], "other")
