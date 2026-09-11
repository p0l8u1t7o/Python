"""工程筆記的 API 權限、狀態、版本與助手接縫回歸。"""

import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.accounts.models import AuthToken, UserPref
from apps.accounts.security import Principal
from apps.core.models import AuditLog
from apps.vision import notes
from apps.vision.agent import actions, help as help_mod, loop, providers, service
from apps.vision.models import EngineeringNote, Flow, FlowRecipe


class EngineeringNotesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.maker = User.objects.create_user("maker", is_staff=True)
        cls.reviewer = User.objects.create_user("reviewer", is_staff=True)
        cls.operator = User.objects.create_user("operator")
        UserPref.objects.create(user=cls.operator, role="operator")
        cls.flow = Flow.objects.create(name="Cup", version=4, graph={"nodes": [], "edges": []})
        cls.other = Flow.objects.create(name="Other", version=4)

    def setUp(self):
        self.p = Principal(kind="user", user=self.maker)
        self.review = Principal(kind="user", user=self.reviewer)

    def call(self, method, path="", data=None, user=None):
        token = AuthToken.issue(user or self.maker)
        if method == "get":
            return self.client.get("/api/vision/notes" + path, HTTP_AUTHORIZATION=f"Bearer {token}")
        return getattr(self.client, method)("/api/vision/notes" + path, data=json.dumps(data or {}),
                                           content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")

    def create(self, **extra):
        return notes.create(self.p, {"title": "Use diffuse light", "body": "Reduces glare on polished parts", "flow": self.flow.pk, **extra})

    @override_settings(VISION={**settings.VISION, "ENGINEERING_NOTE_SELF_CONFIRM": "0"})
    def test_read_shared_write_and_confirm_permissions(self):
        row = self.create()
        self.assertEqual(self.call("get", f"/{row.pk}", user=self.operator).status_code, 200)
        self.assertEqual(self.call("post", data={"title": "X", "body": "Y"}, user=self.operator).status_code, 403)
        self.assertEqual(self.call("patch", f"/{row.pk}", {"body": "New"}, self.operator).status_code, 403)
        self.assertEqual(self.call("post", f"/{row.pk}/confirm", user=self.operator).status_code, 403)
        self.assertEqual(self.call("post", f"/{row.pk}/confirm").status_code, 403)
        response = self.call("post", f"/{row.pk}/confirm", user=self.reviewer)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["confirmed_by"], self.reviewer.pk)
        self.assertTrue(response.json()["confirmed_at"])
        self.assertEqual(self.call("patch", f"/{row.pk}", {"body": "Changed"}).status_code, 409)
        self.assertEqual(self.client.get("/api/vision/notes").status_code, 401)

    def test_self_confirm_by_default(self):
        self.assertTrue(notes.self_confirm())
        row = self.create()
        self.assertTrue(notes.out(row, self.p)["can_confirm"])
        self.assertEqual(self.call("post", f"/{row.pk}/confirm").status_code, 200)

    @override_settings(VISION={**settings.VISION, "ENGINEERING_NOTE_SELF_CONFIRM": "false"})
    def test_false_string_requires_another_engineer(self):
        row = self.create()
        self.assertEqual(self.call("post", f"/{row.pk}/confirm").status_code, 403)
        self.assertEqual(self.call("post", f"/{row.pk}/confirm", user=self.reviewer).status_code, 200)

    def test_replacement_chain_and_retract(self):
        first = self.create()
        notes.transition(self.review, first.pk, "confirm")
        second = self.create(supersedes=first.pk)
        first.refresh_from_db()
        self.assertEqual(first.status, "superseded")
        self.assertEqual(notes.out(first)["replacement"], second.pk)
        self.assertEqual(notes.for_flow(self.flow.pk), [])
        response = self.call("post", data={"title": "Duplicate", "body": "Body", "supersedes": first.pk})
        self.assertEqual(response.status_code, 409)
        notes.transition(self.review, second.pk, "confirm")
        third = self.create(supersedes=second.pk)
        self.assertEqual(third.supersedes_id, second.pk)
        self.assertEqual(notes.out(second)["replacement"], third.pk)
        self.assertEqual(self.call("post", f"/{third.pk}/retract").status_code, 200)
        self.assertEqual(self.call("post", f"/{third.pk}/confirm", user=self.reviewer).status_code, 409)

    def test_version_boundaries_and_same_part(self):
        current = self.create(part_number="P1", applies_from_version=4, applies_to_version=4)
        related = self.create(flow=self.other.pk, part_number="P1")
        expired = self.create(applies_to_version=3)
        future = self.create(applies_from_version=5)
        unrelated = self.create(flow=self.other.pk, part_number="P2")
        for row in (current, related, expired, future, unrelated):
            notes.transition(self.review, row.pk, "confirm")
        self.create(title="Unconfirmed")
        self.assertEqual({r.pk for r in notes.for_flow(self.flow.pk)}, {current.pk, related.pk})
        self.flow.version = 5
        self.flow.save()
        self.assertEqual({r.pk for r in notes.for_flow(self.flow.pk)}, {future.pk})

    def test_validation_and_no_forged_status(self):
        recipe = FlowRecipe.objects.create(flow=self.other, name="Other")
        for extra in ({"status": "confirmed"}, {"confirmed_by": self.reviewer.pk}, {"kind": "unknown"},
                      {"applies_from_version": 5, "applies_to_version": 4}, {"applies_from_version": True},
                      {"conditions": []}, {"images": ["image"] * 9}, {"runs": ["run"] * 21}, {"flow": 9999},
                      {"flow": self.flow.pk, "recipe": recipe.pk}, {"images": [{"id": "x", "width": "bad"}]}, {"images": [{"id": "x", "size": "bad"}]}):
            with self.subTest(extra=extra):
                response = self.call("post", data={"title": "Title", "body": "Body", **extra})
                self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(EngineeringNote.objects.count(), 0)

    def test_api_round_trip_filter_and_audit(self):
        response = self.call("post", data={"title": "Lighting decision", "body": "Use a diffuser", "project": "Cup", "part_number": "P1", "flow": self.flow.pk,
                                          "conditions": {"material": "steel", "temperature": 25}, "images": [{"id": "fixed1", "name": "Glare", "width": 11, "height": 13}, "cache:ref"], "runs": ["run-1"]})
        self.assertEqual(response.status_code, 201, response.content)
        pk = response.json()["id"]
        self.assertEqual(self.call("patch", f"/{pk}", {"body": "Use diffuse backlight"}).status_code, 200)
        self.assertEqual(self.call("get", f"?flow={self.flow.pk}&part_number=P1&kind=decision&status=draft&q=Lighting").json()["total"], 1)
        self.assertEqual(self.call("get", "?q=missing").json()["total"], 0)
        self.assertEqual(self.call("get", f"/{pk}").json()["images"][0]["width"], 11)
        self.call("post", f"/{pk}/confirm", user=self.reviewer)
        self.call("post", f"/{pk}/retract")
        events = list(AuditLog.objects.filter(target_type="engineering_note", target_id=str(pk)).order_by("id").values_list("action", flat=True))
        self.assertEqual(events, ["note.create", "note.update", "note.confirm", "note.retract"])

    def test_agent_proposes_only_draft_and_checks_permission(self):
        state = service.build_state("edit", [], [], "", owner=self.maker)
        state.flow_id = self.flow.pk
        result = actions.dispatch(state, "propose_note", {"title": "New decision", "body": "Check lighting"})
        self.assertEqual(result["status"], "draft")
        self.assertEqual(EngineeringNote.objects.get(pk=result["id"]).flow_id, self.flow.pk)
        self.assertIn("error", actions.dispatch(state, "propose_note", {"title": "Forged", "body": "Body", "status": "confirmed"}))
        state.owner = self.operator
        self.assertIn("error", actions.dispatch(state, "propose_note", {"title": "Forbidden", "body": "Body"}))
        self.assertNotIn("confirm_note", actions.ACTION_MAP)

    def test_fixed_evidence_survives_orphan_cleanup(self):
        import numpy as np
        from apps.vision import fixed_images

        image = fixed_images.store(np.full((13, 17), 127, np.uint8), "Evidence")
        row = self.create(images=[image])
        notes.transition(self.p, row.pk, "retract")
        self.assertIn(image["id"], fixed_images.referenced_ids())
        self.assertNotIn(image["id"], fixed_images.orphans())

    def test_help_and_loop_receive_confirmed_notes(self):
        row = self.create(title="Confirmed guidance")
        notes.transition(self.review, row.pk, "confirm")
        self.create(title="Secret draft")
        state = service.build_state("edit", [], [], "", owner=self.maker)
        state.engineering_notes = notes.prompt(self.flow.pk)
        text = loop.initial_text(state)
        self.assertIn("Confirmed guidance", text)
        self.assertNotIn("Secret draft", text)
        config = providers.AgentSettings(provider="openai", model="test", api_key="test")
        with patch.object(help_mod, "lookups_enabled", return_value=False), patch.object(providers, "complete", return_value="Answer") as complete:
            help_mod.answer("lighting", config, context={"flow_id": self.flow.pk}, user=self.maker, principal=self.p)
        self.assertIn("Confirmed guidance", complete.call_args.args[3])
        self.assertNotIn("Secret draft", complete.call_args.args[3])

    def test_job_endpoint_passes_flow_and_engineering_context(self):
        row = self.create(title="Job guidance")
        notes.transition(self.review, row.pk, "confirm")
        token = AuthToken.issue(self.maker)
        with patch("apps.vision.agent.api.jobs.start", return_value={"id": "job", "status": "running"}) as start:
            response = self.client.post("/api/vision/agent/jobs", data=json.dumps({"task": "edit", "flow_id": self.flow.pk,
                                       "graph": {"nodes": [{"id": "src", "type": "image_source", "params": {}}], "edges": []}, "instruction": "Review lighting"}),
                                       content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(response.status_code, 202, response.content)
        state = start.call_args.args[2]
        self.assertEqual(state.flow_id, self.flow.pk)
        self.assertIn("Job guidance", loop.initial_text(state))

    def test_context_cap_and_excludes_retracted_notes(self):
        for i in range(7):
            row = self.create(title=f"Note {i}")
            notes.transition(self.review, row.pk, "confirm")
        notes.transition(self.review, row.pk, "retract")
        rows = notes.for_flow(self.flow.pk)
        self.assertEqual(len(rows), 5)
        self.assertEqual([r.title for r in rows], [f"Note {i}" for i in range(5, 0, -1)])
        self.assertNotIn("Note 6", notes.prompt(self.flow.pk))
        self.assertEqual([r.title for r in notes.for_flow(self.flow.pk, q="Note 0")], ["Note 0"])
