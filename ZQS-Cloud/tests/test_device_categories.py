"""Categories name what equipment *does*, not how it does it.

``generation`` covers PV, fuel cells, wind and anything else that produces
energy for the site. A category called "PV inverter" would force every later
technology to be filed under a name that does not describe it, and by the time
that becomes obvious there is history attached to the wrong label.

``generator`` stays separate on purpose: it burns fuel, so it has a running
cost per kWh and its own cost model. That is a behavioural difference rather
than a naming one.
"""

from __future__ import annotations

from django.core.management import call_command
from django.test import TestCase

from apps.devices.models import (
    CATEGORY_CAPABILITIES,
    DeviceCategory,
    DeviceType,
    is_metering_only,
)
from tests import factories


class GenerationCategoryTests(TestCase):
    def test_the_category_is_named_for_what_it_does(self):
        self.assertEqual(DeviceCategory.GENERATION, "generation")
        self.assertFalse(hasattr(DeviceCategory, "PV_INVERTER"))

    def test_generation_can_export_but_never_charges(self):
        charge, discharge, export, dispatchable = CATEGORY_CAPABILITIES[
            DeviceCategory.GENERATION
        ]
        self.assertFalse(charge)
        self.assertTrue(discharge)
        self.assertTrue(export)
        self.assertTrue(dispatchable)

    def test_a_fuel_burning_generator_is_still_its_own_category(self):
        """It has a running cost per kWh; generation does not."""
        self.assertIn(DeviceCategory.GENERATOR, CATEGORY_CAPABILITIES)
        self.assertNotEqual(DeviceCategory.GENERATOR, DeviceCategory.GENERATION)


class LoadCategoryTests(TestCase):
    def test_a_load_is_not_metering_only(self):
        """All four capability flags are false for a passive load, and it is
        still a load rather than a meter: the flags answer "can it be
        commanded", not "what is it"."""
        self.assertFalse(is_metering_only(DeviceCategory.LOAD))
        self.assertTrue(is_metering_only(DeviceCategory.METER))

    def test_a_load_takes_no_commands(self):
        charge, discharge, export, dispatchable = CATEGORY_CAPABILITIES[
            DeviceCategory.LOAD
        ]
        self.assertEqual((charge, discharge, export, dispatchable), (False,) * 4)


class BuiltInBlueprintTests(TestCase):
    """``bootstrap`` ships the blueprints an operator picks from."""

    @classmethod
    def setUpTestData(cls) -> None:
        call_command("bootstrap", verbosity=0)

    def blueprint(self, key: str) -> DeviceType:
        return DeviceType.objects.get(organization__isnull=True, key=key)

    def test_a_monitored_load_blueprint_exists(self):
        """Registering equipment purely to watch its consumption is a normal
        thing to want, and it needed a blueprint of its own."""
        blueprint = self.blueprint("load-monitor")
        self.assertEqual(blueprint.category, DeviceCategory.LOAD)

    def test_a_monitored_load_offers_no_commands(self):
        """It reports and is never commanded, so an empty command list is the
        honest answer rather than an oversight."""
        self.assertEqual(self.blueprint("load-monitor").command_definitions, [])

    def test_generation_is_one_blueprint_not_one_per_technology(self):
        """Solar and a fuel cell obey identical rules here - they generate,
        they can export, they never charge. What differs is fuel cost, and
        that lives on the cost model."""
        generation = DeviceType.objects.filter(
            organization__isnull=True, category=DeviceCategory.GENERATION
        )
        self.assertEqual(
            list(generation.values_list("key", flat=True)), ["power-generation-unit"]
        )

    def test_the_generation_blueprint_can_limit_and_disable_output(self):
        commands = {
            entry["name"] for entry in self.blueprint("power-generation-unit").command_definitions
        }
        self.assertEqual(commands, {"set_export_limit", "set_output_enabled"})

    def test_generation_blueprints_are_translated(self):
        for key in ("power-generation-unit", "load-monitor"):
            translations = self.blueprint(key).translations
            self.assertIn("zh-hant", translations, key)
            self.assertIn("zh-hans", translations, key)

    def test_capability_defaults_are_applied_from_the_category(self):
        generation = self.blueprint("power-generation-unit")
        self.assertFalse(generation.can_charge)
        self.assertTrue(generation.can_export)


class CategoryApiTests(TestCase):
    def test_a_device_reports_its_category_to_the_console(self):
        org = factories.organization()
        blueprint = factories.blueprint(
            "gen-1", org, category=DeviceCategory.GENERATION
        )
        device = factories.device(org, "GEN-1", device_type=blueprint)
        self.assertEqual(device.device_type.category, "generation")
        self.assertFalse(device.is_metering_only)
