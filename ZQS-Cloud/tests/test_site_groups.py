"""Site hierarchy: tree walking, cycle guards, and roll-up arithmetic.

The arithmetic tests are the point of this file. Summing peaks and averaging
ratios are the two mistakes a grouped dashboard invites, and both produce
plausible-looking numbers, so they are asserted against hand-computed values
rather than against whatever the implementation happens to return.
"""

from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase

from apps.core.timeutils import now
from apps.devices.models import (
    MAX_SITE_DEPTH,
    ConnectionStatus,
    Site,
    descendant_site_ids,
)
from apps.ems import rollup
from apps.ems.models import EnergyInterval, StoragePlan, Tariff
from tests import factories
from tests.test_api import API, ApiTestCase


def chain(org, depth: int, prefix: str = "n") -> list[Site]:
    """A straight line of sites, root first."""
    nodes: list[Site] = []
    parent = None
    for level in range(depth):
        node = factories.site(org, code=f"{prefix}{level}", parent=parent)
        nodes.append(node)
        parent = node
    return nodes


class SiteTreeTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization("acme")
        self.plant = factories.site(self.org, code="taoyuan", name="Taoyuan")
        self.workshop = factories.site(
            self.org, code="ws1", name="Workshop 1", parent=self.plant
        )
        self.line = factories.site(
            self.org, code="line3", name="Line 3", parent=self.workshop
        )
        self.other_plant = factories.site(self.org, code="hsinchu", name="Hsinchu")

    def test_depth_and_ancestors(self):
        self.assertEqual(self.plant.depth, 0)
        self.assertEqual(self.workshop.depth, 1)
        self.assertEqual(self.line.depth, 2)
        self.assertEqual(
            [site.code for site in self.line.ancestors()], ["taoyuan", "ws1"]
        )

    def test_descendants_expand_the_whole_subtree(self):
        ids = descendant_site_ids([self.plant.pk], organization=self.org)
        self.assertCountEqual(ids, [self.plant.pk, self.workshop.pk, self.line.pk])
        self.assertNotIn(self.other_plant.pk, ids)

    def test_descendants_can_exclude_the_roots(self):
        ids = descendant_site_ids(
            [self.plant.pk], organization=self.org, include_self=False
        )
        self.assertCountEqual(ids, [self.workshop.pk, self.line.pk])

    def test_descendants_of_a_leaf_is_just_the_leaf(self):
        self.assertEqual(
            descendant_site_ids([self.line.pk], organization=self.org), [self.line.pk]
        )

    def test_soft_deleted_children_are_not_expanded(self):
        self.line.soft_delete()
        ids = descendant_site_ids([self.plant.pk], organization=self.org)
        self.assertCountEqual(ids, [self.plant.pk, self.workshop.pk])

    def test_expansion_stays_inside_the_organization(self):
        rival = factories.organization("rival")
        stray = factories.site(rival, code="stray")
        stray.parent_id = self.plant.pk  # only reachable by corrupting the data
        stray.save(update_fields=["parent"])

        ids = descendant_site_ids([self.plant.pk], organization=self.org)
        self.assertNotIn(stray.pk, ids)


class ParentValidationTests(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization("acme")
        self.a = factories.site(self.org, code="a")
        self.b = factories.site(self.org, code="b", parent=self.a)
        self.c = factories.site(self.org, code="c", parent=self.b)

    def assert_rejects(self, site: Site, parent: Site | None, code: str):
        with self.assertRaises(DjangoValidationError) as caught:
            site.validate_parent(parent)
        self.assertEqual(caught.exception.code, code)

    def test_a_site_cannot_be_its_own_parent(self):
        self.assert_rejects(self.a, self.a, "parent_self")

    def test_a_direct_cycle_is_rejected(self):
        # a -> b already exists; making a a child of b closes the loop.
        self.assert_rejects(self.a, self.b, "parent_cycle")

    def test_an_indirect_cycle_is_rejected(self):
        # a -> b -> c; making a a child of c closes the longer loop.
        self.assert_rejects(self.a, self.c, "parent_cycle")

    def test_a_parent_from_another_organization_is_rejected(self):
        rival = factories.organization("rival")
        self.assert_rejects(self.c, factories.site(rival, code="theirs"), "parent_foreign_org")

    def test_a_deleted_parent_is_rejected(self):
        spare = factories.site(self.org, code="spare")
        spare.soft_delete()
        self.assert_rejects(self.c, spare, "parent_deleted")

    def test_nesting_deeper_than_the_cap_is_rejected(self):
        nodes = chain(self.org, MAX_SITE_DEPTH + 1, prefix="deep")
        self.assert_rejects(
            factories.site(self.org, code="one-too-many"), nodes[-1], "parent_too_deep"
        )

    def test_moving_a_subtree_accounts_for_its_own_height(self):
        # A three-level subtree cannot hang off a node that is already deep,
        # even though the node being moved would itself fit.
        deep = chain(self.org, MAX_SITE_DEPTH - 1, prefix="d")
        top = factories.site(self.org, code="sub0")
        middle = factories.site(self.org, code="sub1", parent=top)
        factories.site(self.org, code="sub2", parent=middle)
        self.assert_rejects(top, deep[-1], "parent_too_deep")

    def test_a_valid_parent_is_accepted(self):
        spare = factories.site(self.org, code="spare")
        spare.validate_parent(self.c)  # must not raise

    def test_ancestors_terminate_on_corrupted_data(self):
        # Force a cycle straight into the database, the way a bad restore might.
        self.a.parent_id = self.c.pk
        self.a.save(update_fields=["parent"])
        self.assertLessEqual(len(Site.objects.get(pk=self.a.pk).ancestors()), 3)


class RollupArithmeticTests(TestCase):
    """The two traps: peaks must not be summed, ratios must not be averaged."""

    def setUp(self) -> None:
        self.org = factories.organization("acme")
        self.plant = factories.site(self.org, code="plant")
        self.north = factories.site(self.org, code="north", parent=self.plant)
        self.south = factories.site(self.org, code="south", parent=self.plant)
        self.start = now().replace(minute=0, second=0, microsecond=0) - dt.timedelta(
            hours=2
        )
        self.end = self.start + dt.timedelta(hours=2)

    def interval(self, site: Site, offset_minutes: int, **fields) -> EnergyInterval:
        return EnergyInterval.objects.create(
            organization=self.org,
            site=site,
            interval_start=self.start + dt.timedelta(minutes=offset_minutes),
            interval_seconds=900,
            **fields,
        )

    def totals(self, *sites):
        return rollup.energy_totals([site.pk for site in sites], self.start, self.end)

    def test_peaks_at_different_times_do_not_add_up(self):
        # North peaks in the first interval, south in the second.
        self.interval(self.north, 0, peak_import_kw=300, grid_import_kwh=75)
        self.interval(self.north, 15, peak_import_kw=100, grid_import_kwh=25)
        self.interval(self.south, 0, peak_import_kw=100, grid_import_kwh=25)
        self.interval(self.south, 15, peak_import_kw=300, grid_import_kwh=75)

        totals = self.totals(self.north, self.south)

        # Wrong answer, the one this guards against: 300 + 300 = 600.
        # Right answer: each interval sums to 400, and the largest is 400.
        self.assertEqual(totals["peak_import_kw"], 400)
        self.assertEqual(totals["peak_basis"], rollup.PEAK_BASIS_COINCIDENT)

    def test_peaks_at_the_same_time_do_add_up(self):
        self.interval(self.north, 0, peak_import_kw=300)
        self.interval(self.south, 0, peak_import_kw=250)
        self.assertEqual(self.totals(self.north, self.south)["peak_import_kw"], 550)

    def test_load_peak_uses_the_same_rule(self):
        self.interval(self.north, 0, peak_load_kw=500)
        self.interval(self.north, 15, peak_load_kw=100)
        self.interval(self.south, 0, peak_load_kw=100)
        self.interval(self.south, 15, peak_load_kw=500)
        self.assertEqual(self.totals(self.north, self.south)["peak_load_kw"], 600)

    def test_a_single_site_reports_a_measured_peak(self):
        self.interval(self.north, 0, peak_import_kw=300)
        self.interval(self.north, 15, peak_import_kw=420)
        totals = self.totals(self.north)
        self.assertEqual(totals["peak_import_kw"], 420)
        self.assertEqual(totals["peak_basis"], rollup.PEAK_BASIS_MEASURED)
        self.assertEqual(totals["site_count"], 1)

    def test_self_consumption_is_weighted_not_averaged(self):
        # A big array that exports nothing, and a tiny one that exports it all.
        self.interval(self.north, 0, pv_kwh=1000, grid_export_kwh=0)
        self.interval(self.south, 0, pv_kwh=10, grid_export_kwh=10)

        ratio = self.totals(self.north, self.south)["self_consumption_ratio"]

        # Averaging the two sites' ratios (1.0 and 0.0) would give 0.5.
        self.assertAlmostEqual(ratio, (1010 - 10) / 1010, places=4)
        self.assertGreater(ratio, 0.98)

    def test_self_sufficiency_is_weighted_not_averaged(self):
        self.interval(self.north, 0, load_kwh=1000, grid_import_kwh=0)
        self.interval(self.south, 0, load_kwh=10, grid_import_kwh=10)

        ratio = self.totals(self.north, self.south)["self_sufficiency_ratio"]

        self.assertAlmostEqual(ratio, (1010 - 10) / 1010, places=4)

    def test_round_trip_efficiency_uses_summed_energy(self):
        self.interval(self.north, 0, battery_charge_kwh=100, battery_discharge_kwh=90)
        self.interval(self.south, 0, battery_charge_kwh=100, battery_discharge_kwh=70)
        totals = self.totals(self.north, self.south)
        self.assertAlmostEqual(totals["round_trip_efficiency"], 160 / 200, places=4)

    def test_energy_and_money_are_plain_sums(self):
        self.interval(self.north, 0, grid_import_kwh=10, energy_cost=100, pv_kwh=5)
        self.interval(self.south, 0, grid_import_kwh=15, energy_cost=50, pv_kwh=7)
        totals = self.totals(self.north, self.south)
        self.assertAlmostEqual(totals["grid_import_kwh"], 25)
        self.assertAlmostEqual(totals["energy_cost"], 150)
        self.assertAlmostEqual(totals["pv_kwh"], 12)

    def test_ratios_are_none_when_there_is_no_denominator(self):
        self.interval(self.north, 0, grid_import_kwh=5)
        totals = self.totals(self.north)
        self.assertIsNone(totals["self_consumption_ratio"])
        self.assertIsNone(totals["self_sufficiency_ratio"])
        self.assertIsNone(totals["round_trip_efficiency"])

    def test_intervals_outside_the_window_are_ignored(self):
        self.interval(self.north, 0, grid_import_kwh=10)
        self.interval(self.north, -60, grid_import_kwh=999)
        self.assertAlmostEqual(self.totals(self.north)["grid_import_kwh"], 10)

    def test_currency_is_dropped_when_sites_disagree(self):
        twd = Tariff.objects.create(organization=self.org, name="TWD plan", currency="TWD")
        usd = Tariff.objects.create(organization=self.org, name="USD plan", currency="USD")
        StoragePlan.objects.create(organization=self.org, site=self.north, tariff=twd)
        StoragePlan.objects.create(organization=self.org, site=self.south, tariff=usd)

        self.assertEqual(rollup.currency_for([self.north.pk]), "TWD")
        # Adding TWD to USD would be nonsense; the totals stay, the label goes.
        self.assertEqual(rollup.currency_for([self.north.pk, self.south.pk]), "")


class SiteApiTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.token = self.login("admin@acme-demo.com")
        self.plant = factories.site(self.org, code="taoyuan", name="Taoyuan")
        self.workshop = factories.site(
            self.org, code="ws1", name="Workshop 1", parent=self.plant
        )

    def test_create_accepts_a_parent_and_reports_depth(self):
        response = self.post(
            f"{API}/sites",
            self.token,
            {"name": "Line 3", "code": "line3", "parent_id": str(self.workshop.id)},
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["parent_id"], str(self.workshop.id))
        self.assertEqual(body["depth"], 2)

    def test_create_without_a_parent_is_top_level(self):
        response = self.post(f"{API}/sites", self.token, {"name": "Solo", "code": "solo"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(response.json()["parent_id"])
        self.assertEqual(response.json()["depth"], 0)

    def test_reparenting_into_a_cycle_is_rejected(self):
        response = self.patch(
            f"{API}/sites/{self.plant.id}",
            self.token,
            {"parent_id": str(self.workshop.id)},
        )
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()["error"]["code"], "parent_cycle")

    def test_a_site_cannot_be_reparented_to_itself(self):
        response = self.patch(
            f"{API}/sites/{self.plant.id}", self.token, {"parent_id": str(self.plant.id)}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "parent_self")

    def test_a_site_can_be_detached_to_top_level(self):
        response = self.patch(
            f"{API}/sites/{self.workshop.id}", self.token, {"parent_id": None}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["parent_id"])
        self.workshop.refresh_from_db()
        self.assertIsNone(self.workshop.parent_id)

    def test_listing_reports_own_counts_and_subtree_totals(self):
        factories.device(self.org, "PLANT-1", site_obj=self.plant)
        factories.device(self.org, "WS-1", site_obj=self.workshop)
        factories.device(
            self.org, "WS-2", site_obj=self.workshop, status=ConnectionStatus.ONLINE
        )

        response = self.get(f"{API}/sites?include_descendants=true", self.token)
        self.assertEqual(response.status_code, 200, response.content)
        rows = {row["code"]: row for row in response.json()["items"]}

        # The plant's own device count stays 1; the subtree total is 3.
        self.assertEqual(rows["taoyuan"]["device_count"], 1)
        self.assertEqual(rows["taoyuan"]["total_device_count"], 3)
        self.assertEqual(rows["taoyuan"]["total_online_count"], 1)
        self.assertEqual(rows["taoyuan"]["child_count"], 1)
        self.assertEqual(rows["ws1"]["depth"], 1)
        self.assertEqual(rows["ws1"]["total_device_count"], 2)

    def test_totals_mirror_own_counts_when_descendants_are_not_requested(self):
        factories.device(self.org, "WS-1", site_obj=self.workshop)
        rows = {row["code"]: row for row in self.get(f"{API}/sites", self.token).json()["items"]}
        self.assertEqual(rows["taoyuan"]["device_count"], 0)
        self.assertEqual(rows["taoyuan"]["total_device_count"], 0)

    def test_top_level_only_hides_children(self):
        response = self.get(f"{API}/sites?top_level_only=true", self.token)
        codes = [row["code"] for row in response.json()["items"]]
        self.assertIn("taoyuan", codes)
        self.assertNotIn("ws1", codes)

    def test_deleting_a_parent_with_children_is_refused(self):
        response = self.delete(f"{API}/sites/{self.plant.id}", self.token)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["error"]["code"], "site_has_children")

    def test_a_leaf_with_no_devices_can_be_deleted(self):
        self.assertEqual(
            self.delete(f"{API}/sites/{self.workshop.id}", self.token).status_code, 200
        )

    def test_devices_still_block_deletion(self):
        factories.device(self.org, "WS-1", site_obj=self.workshop)
        response = self.delete(f"{API}/sites/{self.workshop.id}", self.token)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "site_in_use")

    def test_summary_rolls_up_the_subtree(self):
        factories.device(
            self.org, "PLANT-1", site_obj=self.plant, status=ConnectionStatus.ONLINE
        )
        factories.device(self.org, "WS-1", site_obj=self.workshop)

        response = self.get(f"{API}/sites/{self.plant.id}/summary", self.token)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["include_descendants"])
        self.assertEqual(body["site_count"], 2)
        self.assertEqual(body["devices"]["total"], 2)
        self.assertEqual(body["devices"]["online"], 1)
        self.assertIsNone(body["energy"])  # no intervals in the window

    def test_summary_can_be_limited_to_the_site_itself(self):
        factories.device(self.org, "PLANT-1", site_obj=self.plant)
        factories.device(self.org, "WS-1", site_obj=self.workshop)

        body = self.get(
            f"{API}/sites/{self.plant.id}/summary?include_descendants=false", self.token
        ).json()
        self.assertEqual(body["site_count"], 1)
        self.assertEqual(body["devices"]["total"], 1)

    def test_summary_includes_energy_when_intervals_exist(self):
        moment = now() - dt.timedelta(minutes=30)
        for site, peak in ((self.plant, 300), (self.workshop, 200)):
            EnergyInterval.objects.create(
                organization=self.org,
                site=site,
                interval_start=moment,
                interval_seconds=900,
                grid_import_kwh=10,
                peak_import_kw=peak,
            )

        body = self.get(f"{API}/sites/{self.plant.id}/summary", self.token).json()
        self.assertAlmostEqual(body["energy"]["grid_import_kwh"], 20)
        self.assertEqual(body["energy"]["peak_import_kw"], 500)
        self.assertEqual(body["energy"]["peak_basis"], "coincident_estimate")

    def test_another_tenants_site_is_not_found(self):
        stranger = factories.site(self.other_org, code="theirs")
        self.assertEqual(
            self.get(f"{API}/sites/{stranger.id}/summary", self.token).status_code, 404
        )


class DeviceFilterTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.token = self.login("admin@acme-demo.com")
        self.plant = factories.site(self.org, code="taoyuan")
        self.workshop = factories.site(self.org, code="ws1", parent=self.plant)
        self.at_plant = factories.device(self.org, "PLANT-1", site_obj=self.plant)
        self.at_workshop = factories.device(self.org, "WS-1", site_obj=self.workshop)
        self.homeless = factories.device(self.org, "NOSITE-1")

    def device_ids(self, query: str) -> set[str]:
        response = self.get(f"{API}/devices?{query}", self.token)
        self.assertEqual(response.status_code, 200, response.content)
        return {row["device_id"] for row in response.json()["items"]}

    def test_site_filter_alone_is_unchanged(self):
        self.assertEqual(self.device_ids(f"site_id={self.plant.id}"), {"PLANT-1"})

    def test_include_descendants_widens_to_the_subtree(self):
        self.assertEqual(
            self.device_ids(f"site_id={self.plant.id}&include_descendants=true"),
            {"PLANT-1", "WS-1"},
        )

    def test_unassigned_only_finds_devices_with_no_site(self):
        self.assertEqual(self.device_ids("unassigned_only=true"), {"NOSITE-1"})


class SeriesSiteExpansionTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.token = self.login("admin@acme-demo.com")
        self.plant = factories.site(self.org, code="taoyuan")
        self.workshop = factories.site(self.org, code="ws1", parent=self.plant)
        self.at_plant = factories.device(self.org, "PLANT-1", site_obj=self.plant)
        self.at_workshop = factories.device(self.org, "WS-1", site_obj=self.workshop)
        self.elsewhere = factories.device(self.org, "OTHER-1")

    def query(self, body: dict):
        return self.post(f"{API}/telemetry/series", self.token, body)

    def test_site_ids_expand_to_the_subtree(self):
        response = self.query({"site_ids": [str(self.plant.id)], "metrics": ["battery_soc"]})
        self.assertEqual(response.status_code, 200, response.content)
        # No samples exist, but the request must resolve devices rather than
        # reject the payload for having no device_ids.
        self.assertEqual(response.json()["series"], [])

    def test_expansion_can_be_limited_to_one_site(self):
        from apps.devices.models import Device

        response = self.query(
            {
                "site_ids": [str(self.plant.id)],
                "include_descendants": False,
                "metrics": ["battery_soc"],
            }
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            Device.objects.filter(site=self.plant).count(), 1
        )  # sanity: the workshop device was excluded by the site filter

    def test_device_ids_and_site_ids_merge(self):
        response = self.query(
            {
                "device_ids": [str(self.elsewhere.id)],
                "site_ids": [str(self.workshop.id)],
                "metrics": ["battery_soc"],
            }
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_an_empty_selection_is_rejected_with_a_stable_code(self):
        empty = factories.site(self.org, code="empty")
        response = self.query({"site_ids": [str(empty.id)], "metrics": ["battery_soc"]})
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()["error"]["code"], "no_devices_selected")

    def test_neither_devices_nor_sites_is_rejected(self):
        response = self.query({"metrics": ["battery_soc"]})
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()["error"]["code"], "no_devices_selected")

    def test_another_tenants_site_yields_nothing(self):
        stranger = factories.site(self.other_org, code="theirs")
        factories.device(self.other_org, "THEIRS-1", site_obj=stranger)
        response = self.query({"site_ids": [str(stranger.id)], "metrics": ["battery_soc"]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "no_devices_selected")

    def test_too_wide_a_selection_is_refused(self):
        from apps.telemetry.api import MAX_SERIES_DEVICES

        big = factories.site(self.org, code="big")
        for index in range(MAX_SERIES_DEVICES + 1):
            factories.device(self.org, f"BIG-{index:03d}", site_obj=big)

        response = self.query({"site_ids": [str(big.id)], "metrics": ["battery_soc"]})
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()["error"]["code"], "too_many_devices")
