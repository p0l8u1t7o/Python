"""The trust boundary: what a device claims never becomes what it may do.

:class:`TrustBoundaryTests` is the load-bearing part of this file. Everything
else is convenience; that class is what fails the moment someone wires a
declared value into a decision, which is the exact mistake this design exists
to prevent.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase

from apps.audit.models import AuditAction, AuditLog
from apps.core.errors import ValidationError
from apps.core.timeutils import now
from apps.devices.models import (
    DECLARATION_SCHEMA_VERSION,
    CapabilitySource,
    LifecycleState,
    DeclarationState,
    DeviceCategory,
    DeviceDeclaration,
    DeviceEvent,
    declaration_diff,
)
from apps.devices.services import check_capabilities
from tests import factories
from tests.test_api import API, ApiTestCase


def declaration(category: str = DeviceCategory.BATTERY, **capabilities) -> dict:
    return {
        "schema_version": DECLARATION_SCHEMA_VERSION,
        "category": category,
        "model": "PCS-50K",
        "capabilities": {
            "can_charge": False,
            "can_discharge": True,
            "can_export": False,
            "is_dispatchable": True,
            **capabilities,
        },
        "ratings": {"rated_power_kw": 50.0, "min_soc_percent": 10.0},
        "cost_model_hint": "diesel_fuel",
    }


class TrustBoundaryTests(TestCase):
    """A device may claim anything; it may still only do what was confirmed."""

    def setUp(self) -> None:
        self.org = factories.organization()
        self.blueprint = factories.blueprint(
            "backup-pcs",
            self.org,
            category=DeviceCategory.BATTERY,
            can_charge=False,
            can_discharge=True,
            can_export=False,
            is_dispatchable=True,
            command_definitions=[{"name": "set_power_setpoint", "params": {}}],
        )
        self.device = factories.device(
            self.org, "BACKUP-1", device_type=self.blueprint, can_charge=False
        )

    def test_a_declared_capability_does_not_unlock_a_command(self):
        # The pin. A compromised unit says it can charge; the charge command
        # must still be refused, because the check reads the confirmed field.
        DeviceDeclaration.objects.create(
            device=self.device,
            payload=declaration(can_charge=True),
            schema_version=DECLARATION_SCHEMA_VERSION,
            received_at=now(),
            state=DeclarationState.MISMATCHED,
        )
        self.device.refresh_from_db()

        with self.assertRaises(ValidationError) as caught:
            check_capabilities(self.device, "set_power_setpoint", {"power_w": -50_000})
        self.assertEqual(caught.exception.code, "capability_not_supported")

    def test_the_declaration_does_not_change_the_effective_capabilities(self):
        DeviceDeclaration.objects.create(
            device=self.device,
            payload=declaration(can_charge=True, can_export=True),
            schema_version=DECLARATION_SCHEMA_VERSION,
            received_at=now(),
        )
        self.device.refresh_from_db()
        capabilities = self.device.effective_capabilities()
        self.assertFalse(capabilities["can_charge"])
        self.assertFalse(capabilities["can_export"])

    def test_a_cost_model_hint_is_stored_but_not_applied(self):
        # Costing must not be steerable from the wire either: a unit claiming
        # an implausible fuel curve would make a bad dispatch look cheap.
        record = DeviceDeclaration.objects.create(
            device=self.device,
            payload=declaration(),
            schema_version=DECLARATION_SCHEMA_VERSION,
            received_at=now(),
        )
        self.assertEqual(record.payload["cost_model_hint"], "diesel_fuel")
        # Nothing on the device or its assets picked it up.
        self.assertFalse(hasattr(self.device, "cost_model"))
        self.assertEqual(self.device.capability_source, CapabilitySource.BLUEPRINT)

    def test_the_diff_reports_the_disagreement(self):
        diff = declaration_diff(self.device, declaration(can_charge=True))
        self.assertEqual(diff["can_charge"], {"declared": True, "effective": False})
        self.assertNotIn("can_discharge", diff)

    def test_an_agreeing_declaration_produces_no_diff(self):
        self.assertEqual(declaration_diff(self.device, declaration()), {})


class DeclarationIngestTests(TestCase):
    """What the worker does with the identity metrics of a DBIRTH.

    Under Sparkplug the birth *is* the declaration - there is no separate
    ``attributes`` object, because a birth is already defined as the complete
    set of metrics a device offers. That makes the trust boundary easier to
    hold, not harder: the claim arrives as ordinary metrics and is stored as a
    claim, exactly as before.
    """

    def setUp(self) -> None:
        from apps.devices.registry import get_registry
        from services.worker.processors import Shared, SparkplugProcessor

        # The registry is a process-wide TTL cache; a device created after it
        # was last loaded is invisible until it is dropped.
        get_registry().invalidate()
        self.org = factories.organization()
        self.blueprint = factories.blueprint(
            "pcs-x", self.org, category=DeviceCategory.PCS, can_charge=True
        )
        self.device = factories.device(
            self.org, "DECL-1", device_type=self.blueprint
        )
        get_registry().invalidate()
        self.processor = SparkplugProcessor(Shared())

    @staticmethod
    def metrics_for(attributes: dict) -> list[dict]:
        """Turn a declaration dict into the DBIRTH metrics carrying it."""
        from services.sparkplug.datatypes import DataType

        metrics: list[dict] = []

        def add(name: str, value, datatype: DataType) -> None:
            metrics.append(
                {
                    "name": name,
                    "alias": None,
                    "datatype": int(datatype),
                    "value": value,
                    "ts": now().isoformat(),
                    "is_null": value is None,
                    "is_transient": False,
                    "is_historical": False,
                    "properties": {},
                }
            )

        for key, label, datatype in (
            ("schema_version", "Properties/Schema Version", DataType.Int32),
            ("category", "Properties/Category", DataType.String),
            ("model", "Properties/Model", DataType.String),
            ("manufacturer", "Properties/Manufacturer", DataType.String),
            ("serial_number", "Properties/Serial Number", DataType.String),
        ):
            if key in attributes:
                add(label, attributes[key], datatype)

        for key, value in (attributes.get("capabilities") or {}).items():
            add(f"Capabilities/{key}", value, DataType.Boolean)
        for key, value in (attributes.get("ratings") or {}).items():
            add(f"Ratings/{key}", value, DataType.Double)
        return metrics

    def envelope(self, attributes=None, kind: str = "DBIRTH") -> dict:
        node = self.device.edge_node
        return {
            "v": 2,
            "kind": kind,
            "group_id": node.group_id,
            "edge_node_id": node.node_id,
            "device_id": self.device.device_id,
            "data": {
                "timestamp": now().isoformat(),
                "seq": 1,
                "metrics": self.metrics_for(attributes or {}),
            },
        }

    def process(self, attributes=None) -> None:
        self.processor.process([self.envelope(attributes)])

    @staticmethod
    def pcs_declaration(**capabilities) -> dict:
        return declaration(category=DeviceCategory.PCS, **capabilities)

    def test_a_birth_without_identity_metrics_creates_nothing(self):
        """A device that only reports readings is not making a claim."""
        self.process()
        self.assertFalse(DeviceDeclaration.objects.exists())

    def test_a_declaration_is_stored_as_pending(self):
        self.process(self.pcs_declaration())
        record = DeviceDeclaration.objects.get()
        self.assertEqual(record.state, DeclarationState.MISMATCHED)
        self.assertEqual(record.payload["model"], "PCS-50K")

    def test_capabilities_are_untouched_by_ingest(self):
        self.process(self.pcs_declaration(can_charge=False))
        self.device.refresh_from_db()
        # The blueprint said True; the declaration says False; nothing changed.
        self.assertIsNone(self.device.can_charge)
        self.assertTrue(self.device.effective_capabilities()["can_charge"])

    def test_an_identical_redeclaration_does_not_queue_more_review(self):
        # Devices republish their birth on every reconnect, and Sparkplug makes
        # that more frequent, not less - so repeating the same claim must not
        # bury the review queue.
        self.process(self.pcs_declaration())
        self.process(self.pcs_declaration())
        self.assertEqual(DeviceDeclaration.objects.count(), 1)
        self.assertEqual(
            DeviceEvent.objects.filter(code="declaration.changed").count(), 1
        )

    def test_a_changed_declaration_replaces_the_previous_one(self):
        self.process(self.pcs_declaration())
        self.process(self.pcs_declaration(can_export=True))
        self.assertEqual(DeviceDeclaration.objects.count(), 1)
        self.assertTrue(
            DeviceDeclaration.objects.get().payload["capabilities"]["can_export"]
        )
        self.assertEqual(
            DeviceEvent.objects.filter(code="declaration.changed").count(), 2
        )

    def test_an_unsupported_schema_version_is_logged_and_ignored(self):
        self.process({"schema_version": 99, "capabilities": {"can_charge": True}})
        self.assertFalse(DeviceDeclaration.objects.exists())
        event = DeviceEvent.objects.get(code="declaration.unsupported_version")
        self.assertEqual(event.payload["schema_version"], 99)

    def test_a_malformed_declaration_does_not_break_ingest(self):
        self.processor.process([self.envelope({"schema_version": "nonsense"})])
        self.device.refresh_from_db()
        # The birth itself was still applied.
        self.assertIsNotNone(self.device.last_seen_at)

    def test_a_version_omitted_entirely_is_accepted(self):
        """The profile defines the metric names, so it also owns the version."""
        payload = self.pcs_declaration()
        payload.pop("schema_version")
        self.process(payload)
        self.assertTrue(DeviceDeclaration.objects.exists())


class DeclarationReviewApiTests(ApiTestCase):
    """Adoption is a commissioning step, not an ongoing approval queue."""

    def setUp(self) -> None:
        super().setUp()
        self.token = self.login("admin@acme-demo.com")
        self.viewer_token = self.login("view@acme-demo.com")
        self.blueprint = factories.blueprint(
            "review-pcs",
            self.org,
            category=DeviceCategory.BATTERY,
            can_charge=False,
            can_discharge=True,
        )
        self.device = factories.device(
            self.org,
            "REVIEW-1",
            device_type=self.blueprint,
            commissioning_state=LifecycleState.PENDING,
        )
        self.declaration = DeviceDeclaration.objects.create(
            device=self.device,
            payload=declaration(can_charge=True),
            schema_version=DECLARATION_SCHEMA_VERSION,
            received_at=now() - dt.timedelta(minutes=5),
            state=DeclarationState.MISMATCHED,
            diff_summary=declaration_diff(self.device, declaration(can_charge=True)),
        )

    def review(self, accept: bool, token: str | None = None):
        return self.post(
            f"{API}/devices/{self.device.id}/declaration/review",
            token or self.token,
            {"accept": accept},
        )

    def test_reading_a_declaration_shows_the_diff(self):
        response = self.get(f"{API}/devices/{self.device.id}/declaration", self.token)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["has_differences"])
        self.assertEqual(body["state"], "mismatched")

    def test_a_device_without_a_declaration_is_404(self):
        other = factories.device(self.org, "NODECL-1")
        response = self.get(f"{API}/devices/{other.id}/declaration", self.token)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "no_declaration")

    def test_adopting_during_commissioning_applies_the_capabilities(self):
        response = self.review(accept=True)
        self.assertEqual(response.status_code, 200, response.content)

        self.device.refresh_from_db()
        self.assertTrue(self.device.can_charge)
        self.assertEqual(self.device.capability_source, CapabilitySource.DEVICE)
        self.assertEqual(self.device.commissioning_state, LifecycleState.ACTIVE)
        self.assertTrue(self.device.is_enabled)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditAction.DEVICE_DECLARATION_ACCEPTED
            ).exists()
        )

    def test_adoption_is_refused_once_the_device_is_in_service(self):
        # The policy: a device's category never changes. A later disagreement
        # means the hardware was swapped, so the answer is a replacement, not
        # an edit.
        self.device.commissioning_state = LifecycleState.ACTIVE
        self.device.save(update_fields=["commissioning_state"])

        response = self.review(accept=True)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(
            response.json()["error"]["code"], "declaration_not_adoptable"
        )
        self.device.refresh_from_db()
        self.assertIsNone(self.device.can_charge)

    def test_acknowledging_changes_nothing_on_the_device(self):
        response = self.review(accept=False)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["state"], "acknowledged")

        self.device.refresh_from_db()
        self.assertIsNone(self.device.can_charge)
        self.assertEqual(self.device.capability_source, CapabilitySource.BLUEPRINT)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditAction.DEVICE_DECLARATION_REJECTED
            ).exists()
        )

    def test_acknowledging_does_not_lift_an_identity_freeze(self):
        # Seeing a problem is not the same as fixing it. The freeze exists
        # because we do not know what the hardware is.
        DeviceDeclaration.objects.filter(pk=self.declaration.pk).update(
            identity_mismatch=True
        )
        self.review(accept=False)
        self.declaration.refresh_from_db()
        self.assertTrue(self.declaration.identity_mismatch)

    def test_adopting_does_lift_the_freeze(self):
        DeviceDeclaration.objects.filter(pk=self.declaration.pk).update(
            identity_mismatch=True
        )
        self.review(accept=True)
        self.declaration.refresh_from_db()
        self.assertFalse(self.declaration.identity_mismatch)

    def test_a_viewer_cannot_adopt_a_declaration(self):
        response = self.review(accept=True, token=self.viewer_token)
        self.assertEqual(response.status_code, 403)

    def test_adopting_leaves_no_outstanding_difference(self):
        self.review(accept=True)
        self.declaration.refresh_from_db()
        self.assertEqual(self.declaration.state, DeclarationState.MATCHED)
        self.assertEqual(self.declaration.diff_summary, {})
        self.assertIsNotNone(self.declaration.reviewed_at)

    def test_another_tenants_device_is_not_reachable(self):
        stranger = factories.device(self.other_org, "THEIRS-1")
        response = self.get(f"{API}/devices/{stranger.id}/declaration", self.token)
        self.assertEqual(response.status_code, 404)
