"""A device that has never been configured describes itself into the console.

The DBIRTH already names every metric, states its datatype and carries its
unit, which is everything the catalogue needs. What this file pins is that the
convenience does not become a hole: registering a metric is registering a
*label*, and a device must not be able to relabel a series that alert rules
already depend on.
"""

from __future__ import annotations

from django.test import TestCase

from apps.core.timeutils import now
from apps.telemetry.models import Metric
from services.sparkplug.datatypes import DataType
from tests import factories


def metric(name: str, datatype: DataType, properties: dict | None = None) -> dict:
    """One metric in the envelope shape the bus carries."""
    return {
        "name": name,
        "alias": None,
        "datatype": int(datatype),
        "value": 0,
        "ts": now().isoformat(),
        "is_null": False,
        "is_transient": False,
        "is_historical": False,
        "properties": properties or {},
    }


class AutoRegistrationTests(TestCase):
    def setUp(self) -> None:
        from apps.devices.registry import get_registry
        from services.worker.processors import Shared, SparkplugProcessor

        get_registry().invalidate()
        self.org = factories.organization()
        self.device = factories.device(self.org, "PNP-1")
        get_registry().invalidate()
        self.processor = SparkplugProcessor(Shared())

    def birth(self, metrics: list[dict]) -> dict:
        node = self.device.edge_node
        return self.processor.process(
            [
                {
                    "v": 2,
                    "kind": "DBIRTH",
                    "group_id": node.group_id,
                    "edge_node_id": node.node_id,
                    "device_id": self.device.device_id,
                    "data": {
                        "timestamp": now().isoformat(),
                        "seq": 1,
                        "metrics": metrics,
                    },
                }
            ]
        )

    def definition(self, key: str) -> Metric:
        return Metric.objects.get(organization=self.org, key=key)

    # ---- the headline behaviour -----------------------------------------
    def test_an_unknown_metric_is_registered_from_the_birth(self):
        stats = self.birth(
            [metric("stack_voltage_v", DataType.Double, {"unit": "V"})]
        )
        self.assertEqual(stats.get("metrics_registered"), 1)

        definition = self.definition("stack_voltage_v")
        self.assertEqual(definition.unit, "V")
        self.assertEqual(definition.value_type, "float")
        self.assertEqual(definition.kind, "gauge")

    def test_a_hierarchical_name_lands_on_the_normalised_key(self):
        """``Battery/SOC`` and ``battery_soc`` must not fork one series."""
        self.birth([metric("Stack/Voltage V", DataType.Double, {"unit": "V"})])
        self.assertTrue(
            Metric.objects.filter(organization=self.org, key="stack_voltage_v").exists()
        )

    def test_the_datatype_decides_how_the_value_is_stored(self):
        self.birth(
            [
                metric("relay_closed", DataType.Boolean),
                metric("firmware_state", DataType.String),
                metric("cycle_count", DataType.Int64),
            ]
        )
        self.assertEqual(self.definition("relay_closed").value_type, "boolean")
        self.assertEqual(self.definition("firmware_state").value_type, "string")
        self.assertEqual(self.definition("cycle_count").value_type, "integer")

    def test_a_cumulative_unit_is_treated_as_a_counter(self):
        """Integrating a total instead of differencing it corrupts the energy
        figures, and the unit is the only clue a birth gives."""
        self.birth([metric("stack_energy_kwh", DataType.Double, {"unit": "kWh"})])
        definition = self.definition("stack_energy_kwh")
        self.assertEqual(definition.kind, "counter")
        self.assertEqual(definition.aggregation, "counter")

    def test_an_explicit_kind_beats_the_unit_guess(self):
        self.birth(
            [metric("odd_kwh", DataType.Double, {"unit": "kWh", "kind": "gauge"})]
        )
        self.assertEqual(self.definition("odd_kwh").kind, "gauge")

    def test_a_percentage_gets_a_plausibility_window(self):
        self.birth([metric("stack_health", DataType.Double, {"unit": "%"})])
        definition = self.definition("stack_health")
        self.assertEqual((definition.min_value, definition.max_value), (-5.0, 105.0))

    # ---- the limits ------------------------------------------------------
    def test_an_existing_definition_is_never_overwritten(self):
        """A firmware update must not be able to relabel a metric that alert
        rules and charts already depend on."""
        Metric.objects.create(
            organization=self.org,
            key="stack_voltage_v",
            display_name="Operator's own name",
            unit="V",
            min_value=0.0,
            max_value=1000.0,
        )
        self.birth(
            [
                metric(
                    "stack_voltage_v",
                    DataType.String,
                    {"unit": "nonsense", "display_name": "Device says so"},
                )
            ]
        )
        definition = self.definition("stack_voltage_v")
        self.assertEqual(definition.display_name, "Operator's own name")
        self.assertEqual(definition.unit, "V")

    def test_a_builtin_key_is_not_shadowed_by_a_tenant_copy(self):
        """Two definitions of ``battery_soc`` would fork a metric that charts
        and rules share across the whole platform."""
        Metric.objects.create(key="shared_metric", display_name="Built in", unit="W")
        self.birth([metric("shared_metric", DataType.Double, {"unit": "kW"})])
        self.assertFalse(
            Metric.objects.filter(organization=self.org, key="shared_metric").exists()
        )

    def test_protocol_metrics_are_not_registered(self):
        """``bdSeq`` and the control metrics are plumbing, not measurements."""
        self.birth(
            [
                metric("bdSeq", DataType.Int64),
                metric("Device Control/Rebirth", DataType.Boolean),
                metric("Properties/Model", DataType.String),
                metric("Capabilities/Can Charge", DataType.Boolean),
                metric("Alarm/E0500", DataType.Boolean),
                metric("Command/ID", DataType.String),
            ]
        )
        self.assertEqual(Metric.objects.filter(organization=self.org).count(), 0)

    def test_registration_grants_nothing(self):
        """The trust boundary is unchanged: a label is not a capability."""
        self.birth(
            [
                metric("Capabilities/Can Charge", DataType.Boolean, {}),
                metric("stack_voltage_v", DataType.Double, {"unit": "V"}),
            ]
        )
        self.device.refresh_from_db()
        self.assertIsNone(self.device.can_charge)

    def test_a_second_birth_registers_nothing_new(self):
        metrics = [metric("stack_voltage_v", DataType.Double, {"unit": "V"})]
        self.birth(metrics)
        stats = self.birth(metrics)
        self.assertFalse(stats.get("metrics_registered"))
