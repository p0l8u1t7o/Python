"""Fold ``pv-inverter`` and ``fuel-cell`` into one ``power-generation-unit``.

The platform treats every generation technology identically - it generates, it
can export, it never charges - so two blueprints were two names for one set of
rules. What actually differs between solar and a fuel cell is fuel cost, and
that lives on the cost model.

Devices are moved rather than dropped. The user offered to have the rows
deleted, but a device carries its history, its energy asset bindings and its
alert rules; repointing a foreign key is one statement and keeps all of it.
"""

from django.db import migrations

OLD_KEYS = ("pv-inverter", "fuel-cell")
NEW_KEY = "power-generation-unit"


def merge(apps, schema_editor):
    DeviceType = apps.get_model("devices", "DeviceType")
    Device = apps.get_model("devices", "Device")

    target = DeviceType.objects.filter(organization__isnull=True, key=NEW_KEY).first()
    if target is None:
        # ``bootstrap`` has not run against this database yet, so promote the
        # PV blueprint in place rather than leaving devices pointing at a
        # blueprint this migration is about to delete.
        target = DeviceType.objects.filter(
            organization__isnull=True, key="pv-inverter"
        ).first()
        if target is None:
            return
        target.key = NEW_KEY
        target.name = "Power generation unit"
        target.save(update_fields=["key", "name"])

    stale = DeviceType.objects.filter(
        organization__isnull=True, key__in=OLD_KEYS
    ).exclude(pk=target.pk)
    Device.objects.filter(device_type__in=stale).update(device_type=target)
    stale.delete()


def unmerge(apps, schema_editor):
    """Irreversible in any useful sense: which devices were fuel cells and
    which were PV is exactly the distinction this migration removes."""


class Migration(migrations.Migration):
    dependencies = [("devices", "0010_generation_category")]

    operations = [migrations.RunPython(merge, unmerge)]
