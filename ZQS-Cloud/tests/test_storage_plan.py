"""Storage plans as named templates: CRUD, binding, and the round trips.

Plans stopped being per-site rows: they are named profiles a site binds to,
so one profile can drive a fleet. These tests cover the template CRUD, the
bind/unbind endpoint, and the settings round trips the old per-site API used
to guard (``savings_baseline`` / ``enforce_limits`` silently ignoring the
form is the bug that started this file).
"""

from __future__ import annotations

import orjson

from apps.ems.models import SavingsBaseline, StoragePlan
from tests import factories
from tests.test_api import API, ApiTestCase


class PlanTemplateTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.site = factories.site(self.org, "plant")
        self.token = self.login(self.admin.email)

    def create_plan(self, body: dict):
        return self.post(f"{API}/ems/plans", self.token, body)

    def bind(self, site, plan_id):
        return self.client.put(
            f"{API}/ems/sites/{site.id}/plan",
            data=orjson.dumps({"plan_id": plan_id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    # ---- CRUD -------------------------------------------------------------
    def test_create_bind_and_read_back(self) -> None:
        created = self.create_plan(
            {"name": "廠區標準方案", "strategy": "peak_shaving",
             "savings_baseline": "grid_only"}
        )
        self.assertEqual(created.status_code, 201, created.content)
        plan_id = created.json()["id"]

        bound = self.bind(self.site, plan_id)
        self.assertEqual(bound.status_code, 200, bound.content)

        body = self.get(f"{API}/ems/sites/{self.site.id}/plan", self.token).json()
        self.assertEqual(body["name"], "廠區標準方案")
        self.assertEqual(body["savings_baseline"], "grid_only")
        self.assertIn("enforce_limits", body)

        listing = self.get(f"{API}/ems/plans", self.token).json()
        mine = next(p for p in listing if p["id"] == plan_id)
        self.assertEqual([s["name"] for s in mine["sites"]], [self.site.name])

    def test_one_plan_can_drive_several_sites(self) -> None:
        second = factories.site(self.org, "plant-2")
        plan_id = self.create_plan({"name": "共用方案", "strategy": "manual"}).json()["id"]
        self.bind(self.site, plan_id)
        self.bind(second, plan_id)

        listing = self.get(f"{API}/ems/plans", self.token).json()
        mine = next(p for p in listing if p["id"] == plan_id)
        self.assertEqual(len(mine["sites"]), 2)

    def test_unbinding_with_null(self) -> None:
        plan_id = self.create_plan({"name": "tmp", "strategy": "manual"}).json()["id"]
        self.bind(self.site, plan_id)
        self.bind(self.site, None)
        response = self.get(f"{API}/ems/sites/{self.site.id}/plan", self.token)
        self.assertEqual(response.status_code, 404)

    def test_deleting_a_plan_unbinds_its_sites(self) -> None:
        plan_id = self.create_plan({"name": "doomed", "strategy": "manual"}).json()["id"]
        self.bind(self.site, plan_id)
        response = self.delete(f"{API}/ems/plans/{plan_id}", self.token)
        self.assertEqual(response.status_code, 200)
        self.site.refresh_from_db()
        self.assertIsNone(self.site.storage_plan_id)

    def test_duplicate_names_are_refused(self) -> None:
        self.create_plan({"name": "唯一", "strategy": "manual"})
        response = self.create_plan({"name": "唯一", "strategy": "manual"})
        self.assertEqual(response.status_code, 409)

    # ---- settings round trips (the original reason for this file) --------
    def test_enforce_limits_survives_a_round_trip(self) -> None:
        created = self.create_plan(
            {"name": "limits", "strategy": "manual", "enforce_limits": False}
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertFalse(created.json()["enforce_limits"])
        self.assertFalse(
            StoragePlan.objects.get(pk=created.json()["id"]).enforce_limits
        )

    def test_the_baseline_default_is_no_storage(self) -> None:
        created = self.create_plan({"name": "base", "strategy": "manual"})
        self.assertEqual(created.json()["savings_baseline"], "no_storage")
        self.assertEqual(
            StoragePlan.objects.get(pk=created.json()["id"]).savings_baseline,
            SavingsBaseline.NO_STORAGE,
        )

    def test_an_unknown_baseline_is_refused(self) -> None:
        response = self.create_plan(
            {"name": "bad", "strategy": "manual", "savings_baseline": "wishful"}
        )
        self.assertEqual(response.status_code, 422)


class PlanInheritanceTests(ApiTestCase):
    """A plan bound to a parent covers its children unless they override."""

    def setUp(self) -> None:
        super().setUp()
        self.parent = factories.site(self.org, "hsinchu")
        self.child = factories.site(self.org, "greenlab", parent=self.parent)
        self.token = self.login(self.admin.email)

    def _plan(self, name: str):
        return self.post(
            f"{API}/ems/plans", self.token, {"name": name, "strategy": "manual"}
        ).json()

    def _bind(self, site, plan_id):
        return self.client.put(
            f"{API}/ems/sites/{site.id}/plan",
            data=orjson.dumps({"plan_id": plan_id}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    def test_a_child_inherits_the_parents_plan(self) -> None:
        plan = self._plan("父場域方案")
        self._bind(self.parent, plan["id"])

        body = self.get(f"{API}/ems/sites/{self.child.id}/plan", self.token).json()
        self.assertEqual(body["name"], "父場域方案")
        self.assertEqual(body["inherited_from"], self.parent.name)

        # The parent's own view is a direct binding, not an inheritance.
        own = self.get(f"{API}/ems/sites/{self.parent.id}/plan", self.token).json()
        self.assertIsNone(own["inherited_from"])

    def test_a_childs_own_binding_overrides(self) -> None:
        parent_plan = self._plan("父場域方案")
        child_plan = self._plan("子場域方案")
        self._bind(self.parent, parent_plan["id"])
        self._bind(self.child, child_plan["id"])

        body = self.get(f"{API}/ems/sites/{self.child.id}/plan", self.token).json()
        self.assertEqual(body["name"], "子場域方案")
        self.assertIsNone(body["inherited_from"])

    def test_the_dispatch_engine_resolves_through_the_chain(self) -> None:
        from apps.ems.dispatch import plan_for_site

        plan = self._plan("父場域方案")
        self._bind(self.parent, plan["id"])
        resolved = plan_for_site(self.child.id)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, "父場域方案")
