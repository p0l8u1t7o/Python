"""One currency per tenant, and every money figure labelled with it.

The symptom this closes: a site with no tariff had no currency at all, so its
costs came back as a bare number while the site next to it came back as money.
Adjacent rows in one column read `0` and `$0`, which looks like a rendering
fault rather than a missing tariff.

The fix is a currency that belongs to the organisation rather than to each
tariff. That only stays true if a tariff cannot disagree with it, which is why
the mismatch is refused at save time instead of reconciled when a report is
run - see device-classification.md §3.12.
"""

from __future__ import annotations

from apps.ems.models import Tariff
from apps.ems.rollup import currency_by_site, currency_for
from tests import factories
from tests.test_api import API, ApiTestCase


class DefaultCurrencyTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.priced = factories.site(self.org, "priced")
        self.unpriced = factories.site(self.org, "unpriced")

        self.tariff = Tariff.objects.create(
            organization=self.org, name="Flat", currency="TWD"
        )
        factories.storage_plan(self.org, self.priced, tariff=self.tariff)
        self.token = self.login(self.admin.email)

    def test_a_site_without_a_tariff_falls_back_to_the_organization(self):
        currencies = currency_by_site(
            [self.priced.pk, self.unpriced.pk], default="TWD"
        )
        self.assertEqual(currencies[self.priced.pk], "TWD")
        self.assertEqual(currencies[self.unpriced.pk], "TWD")

    def test_every_requested_site_gets_an_entry(self):
        """A missing key is what made one row render as money and the next not."""
        currencies = currency_by_site([self.unpriced.pk], default="USD")
        self.assertIn(self.unpriced.pk, currencies)

    def test_sites_that_genuinely_disagree_still_return_nothing(self):
        """Not a display gap to paper over: adding two currencies together
        produces a number that means nothing."""
        other = factories.site(self.org, "other")
        factories.storage_plan(
            self.org,
            other,
            tariff=Tariff.objects.create(
                organization=self.org, name="Euro", currency="EUR"
            ),
        )
        self.assertEqual(
            currency_for([self.priced.pk, other.pk], default="TWD"), ""
        )

    def test_the_cost_overview_labels_every_site(self):
        body = self.get(f"{API}/ems/cost-overview", self.token).json()
        rows = {row["site_name"]: row["currency"] for row in body["sites"]}
        self.assertTrue(rows, "expected at least one site")
        self.assertEqual(
            [name for name, code in rows.items() if not code],
            [],
            f"sites with no currency: {rows}",
        )

    def test_the_live_overview_labels_every_site(self):
        body = self.get(f"{API}/ems/live", self.token).json()
        blanks = [row["site_name"] for row in body["sites"] if not row["currency"]]
        self.assertEqual(blanks, [], f"sites with no currency: {blanks}")

    def test_the_organization_reports_its_currency(self):
        body = self.get(f"{API}/auth/me", self.token).json()
        self.assertEqual(body["organization"]["reporting_currency"], "TWD")


class CurrencyMismatchTests(ApiTestCase):
    """A tariff that disagrees would make the reporting currency a third
    source of truth, quietly contradicting the other two."""

    def setUp(self) -> None:
        super().setUp()
        self.token = self.login(self.admin.email)

    def test_a_tariff_in_another_currency_is_refused(self):
        response = self.post(
            f"{API}/ems/tariffs",
            self.token,
            {"name": "Dollars", "currency": "USD", "default_import_price": 1.0},
        )
        self.assertEqual(response.status_code, 422, response.content)
        error = response.json()["error"]
        self.assertEqual(error["code"], "currency_mismatch")
        self.assertEqual(error["details"]["reporting_currency"], "TWD")

    def test_a_matching_tariff_is_accepted(self):
        response = self.post(
            f"{API}/ems/tariffs",
            self.token,
            {"name": "Local", "currency": "TWD", "default_import_price": 1.0},
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_the_comparison_ignores_case(self):
        response = self.post(
            f"{API}/ems/tariffs",
            self.token,
            {"name": "Lowercase", "currency": "twd", "default_import_price": 1.0},
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_editing_onto_a_mismatched_currency_is_refused(self):
        tariff = Tariff.objects.create(
            organization=self.org, name="Editable", currency="TWD"
        )
        response = self.client.put(
            f"{API}/ems/tariffs/{tariff.id}",
            data=b'{"name": "Editable", "currency": "JPY"}',
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(response.json()["error"]["code"], "currency_mismatch")

    def test_an_organization_with_no_currency_set_accepts_anything(self):
        """Blank means "not decided yet", which must not block configuration."""
        self.org.reporting_currency = ""
        self.org.save(update_fields=["reporting_currency"])

        response = self.post(
            f"{API}/ems/tariffs",
            self.token,
            {"name": "Anything", "currency": "USD", "default_import_price": 1.0},
        )
        self.assertEqual(response.status_code, 201, response.content)
