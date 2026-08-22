"""Rename the ``pv_inverter`` category to ``generation``.

The category is named for what the equipment does, not for how it does it.
Fuel cells, wind and CHP are all generation, and filing them under "PV
inverter" would attach history to a label that does not describe them.

``generator`` deliberately stays separate: it burns fuel, so it has a running
cost per kWh and its own cost model. That is a behavioural difference, not a
naming one.
"""

from django.db import migrations, models


def to_generation(apps, schema_editor):
    apps.get_model("devices", "DeviceType").objects.filter(
        category="pv_inverter"
    ).update(category="generation")


def to_pv_inverter(apps, schema_editor):
    apps.get_model("devices", "DeviceType").objects.filter(
        category="generation"
    ).update(category="pv_inverter")


class Migration(migrations.Migration):
    dependencies = [("devices", "0009_sparkplug")]

    operations = [
        migrations.AlterField(
            model_name="devicetype",
            name="category",
            field=models.CharField(
                choices=[
                    ("battery", "Battery / BESS"),
                    ("pcs", "Power conversion system"),
                    ("generation", "Generation unit"),
                    ("meter", "Energy meter"),
                    ("load", "Electrical load"),
                    ("generator", "Backup generator"),
                    ("ev_charger", "EV charger"),
                    ("controller", "EMS controller"),
                    ("sensor", "Sensor"),
                    ("gateway", "Gateway"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=20,
            ),
        ),
        migrations.RunPython(to_generation, to_pv_inverter),
    ]
