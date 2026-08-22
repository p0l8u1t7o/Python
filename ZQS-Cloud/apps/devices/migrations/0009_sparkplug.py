"""Move the device registry onto the Sparkplug B address model.

The user authorised dropping the database and rebuilding it. This does not do
that: provisioning an implicit edge node per existing device and carrying the
credential across is about thirty extra lines, and it means the change does not
depend on the deployment being empty. A destructive migration is a decision
every future operator inherits, not just this one.

Credentials keep their existing ``mqtt_username``. The format for newly issued
ones changes from ``dev-<org>-<device>`` to ``node-<group>-<node>``, but a
migration cannot re-issue a password it never held in plaintext, and forcing a
rotation on every site to tidy up a prefix would be a poor trade.
"""

import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def provision_edge_nodes(apps, schema_editor):
    """One implicit node per existing device, carrying its credential."""
    Device = apps.get_model("devices", "Device")
    EdgeNode = apps.get_model("devices", "EdgeNode")
    DeviceCredential = apps.get_model("devices", "DeviceCredential")
    EdgeNodeCredential = apps.get_model("devices", "EdgeNodeCredential")

    for device in Device.objects.select_related("organization").all():
        node, _created = EdgeNode.objects.get_or_create(
            group_id=device.organization.slug,
            node_id=device.device_id,
            defaults={
                "organization_id": device.organization_id,
                "site_id": device.site_id,
                "name": device.name or device.device_id,
                "is_implicit": True,
                "is_enabled": device.is_enabled,
                "status": device.status,
                "status_changed_at": device.status_changed_at,
                "last_seen_at": device.last_seen_at,
                "firmware_version": device.firmware_version,
                "hardware_version": device.hardware_version,
                "ip_address": device.ip_address,
                "rssi": device.rssi,
            },
        )
        Device.objects.filter(pk=device.pk).update(edge_node=node)

        old = DeviceCredential.objects.filter(device_id=device.pk).first()
        if old is not None:
            EdgeNodeCredential.objects.update_or_create(
                edge_node=node,
                defaults={
                    "mqtt_username": old.mqtt_username,
                    "hashed_password": old.hashed_password,
                    "allowed_client_id": old.allowed_client_id,
                    "is_active": old.is_active,
                    "rotated_at": old.rotated_at,
                    "last_auth_at": old.last_auth_at,
                },
            )


def unprovision(apps, schema_editor):
    """Reverse: nothing to restore, the device rows still carry everything."""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_organization_reporting_currency"),
        ("devices", "0008_device_annual_maintenance_cost_device_capital_cost_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="EdgeNode",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "node_id",
                    models.CharField(
                        db_index=True,
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                message=(
                                    "Edge node ID must be 3-64 characters of letters, "
                                    "digits, '.', '_' or '-' and must not contain MQTT "
                                    "wildcards."
                                ),
                                regex="^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$",
                            )
                        ],
                    ),
                ),
                ("group_id", models.CharField(db_index=True, max_length=80)),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("is_implicit", models.BooleanField(default=False)),
                ("is_enabled", models.BooleanField(default=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("online", "Online"), ("offline", "Offline"), ("unknown", "Unknown")],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                ("status_changed_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("birth_at", models.DateTimeField(blank=True, null=True)),
                ("bd_seq", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("last_seq", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("rebirth_requested_at", models.DateTimeField(blank=True, null=True)),
                ("firmware_version", models.CharField(blank=True, max_length=64)),
                ("hardware_version", models.CharField(blank=True, max_length=64)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("rssi", models.IntegerField(blank=True, null=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="edge_nodes",
                        to="accounts.organization",
                    ),
                ),
                (
                    "site",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="edge_nodes",
                        to="devices.site",
                    ),
                ),
            ],
            options={"db_table": "devices_edge_node", "ordering": ("name",)},
        ),
        migrations.AddConstraint(
            model_name="edgenode",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("group_id", "node_id"),
                name="uniq_edge_node_per_group",
            ),
        ),
        migrations.CreateModel(
            name="EdgeNodeCredential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mqtt_username", models.CharField(db_index=True, max_length=128, unique=True)),
                ("hashed_password", models.CharField(max_length=256)),
                ("allowed_client_id", models.CharField(blank=True, max_length=128)),
                ("is_active", models.BooleanField(default=True)),
                ("rotated_at", models.DateTimeField(blank=True, null=True)),
                ("last_auth_at", models.DateTimeField(blank=True, null=True)),
                (
                    "edge_node",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credential",
                        to="devices.edgenode",
                    ),
                ),
            ],
            options={"db_table": "devices_edge_node_credential"},
        ),
        migrations.AddField(
            model_name="device",
            name="edge_node",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="devices",
                to="devices.edgenode",
            ),
        ),
        migrations.RunPython(provision_edge_nodes, unprovision),
        migrations.AlterField(
            model_name="device",
            name="edge_node",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="devices",
                to="devices.edgenode",
            ),
        ),
        migrations.AlterField(
            model_name="device",
            name="device_id",
            field=models.CharField(
                db_index=True,
                max_length=64,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "Device ID must be 3-64 characters of letters, digits, "
                            "'.', '_' or '-' and must not contain MQTT wildcards."
                        ),
                        regex="^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$",
                    )
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="device",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("edge_node", "device_id"),
                name="uniq_device_per_edge_node",
            ),
        ),
        migrations.AddIndex(
            model_name="device",
            index=models.Index(fields=["edge_node", "device_id"], name="devices_dev_edge_no_7e4094_idx"),
        ),
        migrations.CreateModel(
            name="MetricAlias",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alias", models.PositiveBigIntegerField()),
                ("name", models.CharField(max_length=200)),
                ("datatype", models.PositiveSmallIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "device",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metric_aliases",
                        to="devices.device",
                    ),
                ),
                (
                    "edge_node",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metric_aliases",
                        to="devices.edgenode",
                    ),
                ),
            ],
            options={"db_table": "devices_metric_alias"},
        ),
        migrations.AddConstraint(
            model_name="metricalias",
            constraint=models.UniqueConstraint(
                condition=models.Q(("device__isnull", False)),
                fields=("edge_node", "device", "alias"),
                name="uniq_alias_per_device",
            ),
        ),
        migrations.AddConstraint(
            model_name="metricalias",
            constraint=models.UniqueConstraint(
                condition=models.Q(("device__isnull", True)),
                fields=("edge_node", "alias"),
                name="uniq_alias_per_node",
            ),
        ),
        migrations.DeleteModel(name="DeviceCredential"),
    ]
