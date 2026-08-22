"""Site-scoped access: a membership limited to part of an organisation.

Access used to have two dimensions, tenant and role. These pin the third one,
and in particular pin the two decisions that are easy to get wrong later:

* an **empty** site list means the whole organisation, not nothing;
* naming a parent grants its **subtree**, so a site added under it later is
  covered without anybody re-editing the membership.
"""

from __future__ import annotations

from apps.accounts.models import Role
from tests import factories
from tests.test_api import API, ApiTestCase


class SiteScopeTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.plant = factories.site(self.org, "plant")
        self.workshop = factories.site(self.org, "workshop", parent=self.plant)
        self.other_plant = factories.site(self.org, "other-plant")

        self.inside = factories.device(
            self.org, "SCOPE-INSIDE", site_obj=self.workshop, name="Inside"
        )
        self.outside = factories.device(
            self.org, "SCOPE-OUTSIDE", site_obj=self.other_plant, name="Outside"
        )
        self.unplaced = factories.device(self.org, "SCOPE-NONE", name="Unplaced")

        self.scoped, self.scoped_membership = factories.member(
            self.org, Role.ADMIN, email="scoped@acme-demo.com"
        )
        self.scoped_membership.sites.set([self.plant])

    def test_an_unscoped_member_sees_every_site(self):
        token = self.login(self.admin.email)
        response = self.get(f"{API}/sites", token)
        codes = {item["code"] for item in response.json()["items"]}
        self.assertEqual(codes, {"plant", "workshop", "other-plant"})

    def test_a_scoped_member_sees_only_their_subtree(self):
        token = self.login(self.scoped.email)
        response = self.get(f"{API}/sites", token)
        codes = {item["code"] for item in response.json()["items"]}
        # The workshop was never named; it is included because it hangs off
        # the plant that was.
        self.assertEqual(codes, {"plant", "workshop"})

    def test_a_scoped_member_cannot_open_a_site_outside_their_scope(self):
        token = self.login(self.scoped.email)
        response = self.get(f"{API}/sites/{self.other_plant.id}", token)
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"]["code"], "site_out_of_scope")

    def test_device_listing_is_narrowed_to_the_scope(self):
        token = self.login(self.scoped.email)
        response = self.get(f"{API}/devices", token)
        names = {item["device_id"] for item in response.json()["items"]}
        self.assertEqual(names, {"SCOPE-INSIDE"})

    def test_a_device_outside_the_scope_reads_as_missing_not_forbidden(self):
        """404, not 403: "it exists but is not yours" is itself information."""
        token = self.login(self.scoped.email)
        response = self.get(f"{API}/devices/{self.outside.id}", token)
        self.assertEqual(response.status_code, 404, response.content)

    def test_a_device_with_no_site_is_invisible_to_a_scoped_member(self):
        """Unplaced equipment belongs to whoever can see the whole tenant."""
        token = self.login(self.scoped.email)
        response = self.get(f"{API}/devices/{self.unplaced.id}", token)
        self.assertEqual(response.status_code, 404, response.content)

    def test_fleet_counts_reflect_the_scope(self):
        token = self.login(self.scoped.email)
        stats = self.get(f"{API}/system/fleet", token).json()
        self.assertEqual(stats["total_devices"], 1)
        self.assertEqual(stats["sites"], 2)

    def test_telemetry_cannot_be_read_by_naming_an_out_of_scope_device_id(self):
        """The series endpoint takes ids directly, so it needs its own guard."""
        token = self.login(self.scoped.email)
        response = self.post(
            f"{API}/series",
            token,
            {
                "device_ids": [str(self.outside.id)],
                "metric_keys": ["battery_soc"],
            },
        )
        self.assertEqual(response.status_code, 404, response.content)

    def test_an_admin_cannot_grant_access_they_do_not_have(self):
        token = self.login(self.scoped.email)
        response = self.patch(
            f"{API}/members/{self.viewer.id}",
            token,
            {"role": Role.VIEWER, "site_ids": [str(self.other_plant.id)]},
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_an_empty_site_list_clears_the_scope(self):
        token = self.login(self.admin.email)
        response = self.patch(
            f"{API}/members/{self.scoped.id}",
            token,
            {"role": Role.ADMIN, "site_ids": []},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["site_ids"], [])

        scoped_token = self.login(self.scoped.email)
        listing = self.get(f"{API}/sites", scoped_token).json()
        self.assertEqual(len(listing["items"]), 3)

    def test_omitting_site_ids_leaves_the_scope_alone(self):
        """A role change must not silently wipe a scope."""
        token = self.login(self.admin.email)
        response = self.patch(
            f"{API}/members/{self.scoped.id}", token, {"role": Role.OPERATOR}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["site_ids"], [str(self.plant.id)])

    def test_a_scoped_admin_must_create_inside_their_scope(self):
        """Otherwise the new site vanishes from their own listing."""
        token = self.login(self.scoped.email)
        response = self.post(
            f"{API}/sites", token, {"name": "Orphan", "code": "orphan"}
        )
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(
            response.json()["error"]["code"], "parent_required_in_scope"
        )

    def test_a_scoped_admin_can_create_under_a_site_they_hold(self):
        token = self.login(self.scoped.email)
        response = self.post(
            f"{API}/sites",
            token,
            {"name": "Line 4", "code": "line-4", "parent_id": str(self.plant.id)},
        )
        self.assertEqual(response.status_code, 201, response.content)

        # And it is immediately visible, because the scope is a subtree.
        codes = {item["code"] for item in self.get(f"{API}/sites", token).json()["items"]}
        self.assertIn("line-4", codes)

    def test_an_unscoped_admin_can_still_create_a_top_level_site(self):
        token = self.login(self.admin.email)
        response = self.post(f"{API}/sites", token, {"name": "New", "code": "new"})
        self.assertEqual(response.status_code, 201, response.content)

    def test_me_reports_the_expanded_scope(self):
        token = self.login(self.scoped.email)
        payload = self.get(f"{API}/auth/me", token).json()
        self.assertEqual(
            set(payload["site_scope"]), {str(self.plant.id), str(self.workshop.id)}
        )
        self.assertEqual(payload["scoped_site_ids"], [str(self.plant.id)])
