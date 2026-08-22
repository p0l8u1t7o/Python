"""Create a working demo tenant: users, a site, devices, policy, rules, EMS.

Intended for local development and for demonstrating the console before real
hardware exists. Idempotent - re-running updates rather than duplicating.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Membership, Organization, Role, User
from apps.alerts.models import AlertRule, RuleScope, Severity
from django.db.models import Count, Q
from django.utils import timezone

from apps.devices.models import Device, DeviceType, EdgeNode, EdgeNodeCredential, Site
from apps.ems.models import (
    AssetRole,
    DispatchStrategy,
    EnergyAsset,
    StoragePlan,
    Tariff,
)
from apps.telemetry.models import RecordingPolicy, RecordingRule

DEMO_PASSWORD = "ChangeMe-2026!"


class Command(BaseCommand):
    help = "Seed a demo organization with sites, devices, policies and rules."

    def add_arguments(self, parser):
        parser.add_argument("--org-slug", default="demo")
        parser.add_argument("--org-name", default="Demo Energy Co.")
        parser.add_argument("--email", default="admin@example.com")
        parser.add_argument("--password", default=DEMO_PASSWORD)

    @transaction.atomic
    def handle(self, *args, **options):
        organization, _ = Organization.objects.update_or_create(
            slug=options["org_slug"],
            defaults={
                "name": options["org_name"],
                "default_timezone": "Asia/Taipei",
                "reporting_currency": "TWD",
                "is_active": True,
            },
        )

        owner = self._user(options["email"], options["password"], "Demo Administrator")
        Membership.objects.update_or_create(
            organization=organization, user=owner, defaults={"role": Role.OWNER}
        )
        operator = self._user("operator@example.com", options["password"], "Demo Operator")
        Membership.objects.update_or_create(
            organization=organization, user=operator, defaults={"role": Role.OPERATOR}
        )
        viewer = self._user("viewer@example.com", options["password"], "Demo Viewer")
        Membership.objects.update_or_create(
            organization=organization, user=viewer, defaults={"role": Role.VIEWER}
        )

        site, _ = Site.objects.update_or_create(
            organization=organization,
            code="taipei-hq",
            defaults={
                "name": "Taipei Headquarters",
                "address": "No. 7, Section 5, Xinyi Road, Xinyi District, Taipei",
                "city": "Taipei",
                "country": "TW",
                "latitude": 25.0339,
                "longitude": 121.5645,
                "timezone_name": "Asia/Taipei",
                "description": "1 MWh behind-the-meter storage with rooftop PV.",
            },
        )

        policy = self._recording_policy(organization)
        devices = self._devices(organization, site, policy)
        self._energy(organization, site, devices)
        self._alert_rules(organization, site)
        self._workflow(organization, site, devices)

        self.stdout.write(self.style.SUCCESS("Demo tenant ready."))
        self.stdout.write(f"  organization : {organization.name} ({organization.slug})")
        self.stdout.write(f"  owner        : {owner.email} / {options['password']}")
        self.stdout.write(f"  operator     : {operator.email} / {options['password']}")
        self.stdout.write(f"  viewer       : {viewer.email} / {options['password']}")
        self.stdout.write("  devices      : " + ", ".join(d.device_id for d in devices.values()))

    # ---- helpers ---------------------------------------------------------
    def _user(self, email: str, password: str, full_name: str) -> User:
        user = User.objects.filter(email=email.lower()).first()
        if user is None:
            user = User.objects.create_user(
                email=email,
                password=password,
                full_name=full_name,
                language="zh-hant",
                timezone_name="Asia/Taipei",
            )
        return user

    def _recording_policy(self, organization: Organization) -> RecordingPolicy:
        policy, _ = RecordingPolicy.objects.update_or_create(
            organization=organization,
            name="Default 15s / 1h heartbeat",
            defaults={
                "description": (
                    "Keeps fast-moving power signals, thins out slow ones with a "
                    "deadband, and forces a heartbeat sample every hour."
                ),
                "is_default": True,
                "record_unlisted_metrics": True,
                "default_retention_days": 365,
                "default_min_interval_seconds": 0,
                "default_max_interval_seconds": 3600,
            },
        )
        policy.rules.all().delete()
        RecordingRule.objects.bulk_create(
            [
                RecordingRule(
                    policy=policy,
                    metric_key="grid_power_w",
                    min_interval_seconds=5,
                    deadband_absolute=50,
                    retention_days=730,
                ),
                RecordingRule(
                    policy=policy,
                    metric_key="pv_power_w",
                    min_interval_seconds=15,
                    deadband_absolute=50,
                    retention_days=730,
                ),
                RecordingRule(
                    policy=policy,
                    metric_key="battery_power_w",
                    min_interval_seconds=5,
                    deadband_absolute=50,
                    retention_days=730,
                ),
                RecordingRule(
                    policy=policy,
                    metric_key="battery_soc",
                    min_interval_seconds=30,
                    deadband_percent=0.5,
                    retention_days=1825,
                ),
                RecordingRule(
                    policy=policy,
                    metric_key="battery_temperature_c",
                    min_interval_seconds=60,
                    deadband_absolute=0.5,
                ),
                # Diagnostics are noisy and rarely charted - keep them coarse.
                RecordingRule(
                    policy=policy,
                    metric_key="signal_rssi_dbm",
                    min_interval_seconds=300,
                    retention_days=30,
                ),
            ]
        )
        return policy

    def _devices(
        self, organization: Organization, site: Site, policy: RecordingPolicy
    ) -> dict[str, Device]:
        blueprints = {
            blueprint.key: blueprint
            for blueprint in DeviceType.objects.filter(organization__isnull=True)
        }
        specification = [
            ("ZQS-BESS-0001", "BESS #1 (500 kW / 1 MWh)", "bess-pcs"),
            ("ZQS-METER-0001", "PCC grid meter", "smart-meter"),
            ("ZQS-PV-0001", "Rooftop PV inverter", "pv-inverter"),
            ("ZQS-EMS-0001", "Site EMS controller", "ems-controller"),
        ]

        # One gateway carrying all four devices, which is the shape a real
        # site takes: an EMS box on the LAN speaks MQTT, the equipment behind
        # it speaks Modbus. Seeding four independent nodes instead would model
        # the exception and hide the normal case.
        node, _created = EdgeNode.objects.get_or_create(
            group_id=organization.slug,
            node_id="ZQS-GW-0001",
            deleted_at__isnull=True,
            defaults={
                "organization": organization,
                "site": site,
                "name": "Taipei site gateway",
                "description": "Sparkplug edge node fronting the demo equipment",
                "is_implicit": False,
            },
        )
        if not hasattr(node, "credential"):
            EdgeNodeCredential.issue(node)

        devices: dict[str, Device] = {}
        for device_id, name, blueprint_key in specification:
            # Keyed on the organisation and the device id, not on the node.
            # Seeding a database whose devices already exist on their own
            # implicit nodes has to *move* them onto the gateway; keying on the
            # node would create a second copy and collide on the serial number.
            device, _created = Device.objects.update_or_create(
                organization=organization,
                device_id=device_id,
                defaults={
                    "edge_node": node,
                    "site": site,
                    "device_type": blueprints.get(blueprint_key),
                    "recording_policy": policy,
                    "name": name,
                    "serial_number": device_id,
                    "is_enabled": True,
                },
            )
            devices[blueprint_key] = device

        # A device moved onto the gateway leaves its implicit node behind, and
        # an implicit node with nothing on it is pure clutter: it exists only
        # to hold one device's connection, so without that device it has no
        # reason to be listed anywhere. Real gateways are never touched.
        # Counted then updated by primary key: an UPDATE cannot carry the join
        # the annotation needs, so doing it in one statement silently affects
        # nothing.
        orphan_ids = list(
            EdgeNode.objects.filter(
                organization=organization, is_implicit=True, deleted_at__isnull=True
            )
            .annotate(
                attached=Count("devices", filter=Q(devices__deleted_at__isnull=True))
            )
            .filter(attached=0)
            .values_list("pk", flat=True)
        )
        if orphan_ids:
            EdgeNode.objects.filter(pk__in=orphan_ids).update(
                deleted_at=timezone.now()
            )
            self.stdout.write(
                f"  removed {len(orphan_ids)} empty implicit edge node(s)"
            )

        return devices

    def _energy(
        self, organization: Organization, site: Site, devices: dict[str, Device]
    ) -> None:
        tariff, _ = Tariff.objects.update_or_create(
            organization=organization,
            name="Taipower high-voltage TOU (illustrative)",
            defaults={
                "currency": "TWD",
                "timezone_name": "Asia/Taipei",
                "demand_charge_per_kw": 236.2,
                "default_import_price": 2.11,
                "default_export_price": 1.05,
                "periods": [
                    {
                        "name": "summer_peak",
                        "months": [6, 7, 8, 9],
                        "weekdays": [0, 1, 2, 3, 4],
                        "start": "16:00",
                        "end": "22:00",
                        "import_price": 8.36,
                        "export_price": 1.05,
                    },
                    {
                        "name": "summer_mid",
                        "months": [6, 7, 8, 9],
                        "weekdays": [0, 1, 2, 3, 4],
                        "start": "09:00",
                        "end": "16:00",
                        "import_price": 5.02,
                        "export_price": 1.05,
                    },
                    {
                        "name": "off_peak",
                        "start": "23:00",
                        "end": "09:00",
                        "import_price": 1.96,
                        "export_price": 1.05,
                    },
                ],
            },
        )

        plan, _ = StoragePlan.objects.update_or_create(
            organization=organization,
            name="示範儲能方案",
            defaults={
                "strategy": DispatchStrategy.PEAK_SHAVING,
                "is_enabled": True,
                # Sized against the seeded load profile, which peaks near
                # 480 kW: a target above that would never trigger a discharge.
                "contract_capacity_kw": 450.0,
                "peak_shaving_target_kw": 250.0,
                "export_limit_kw": 0.0,
                "usable_capacity_kwh": 1000.0,
                "max_charge_kw": 500.0,
                "max_discharge_kw": 500.0,
                "min_soc_percent": 10.0,
                "max_soc_percent": 95.0,
                "backup_reserve_percent": 20.0,
                "round_trip_efficiency": 0.88,
                "tariff": tariff,
            },
        )
        if site.storage_plan_id != plan.pk:
            site.storage_plan = plan
            site.save(update_fields=["storage_plan"])

        bindings = [
            (
                devices["smart-meter"],
                AssetRole.GRID_METER,
                {
                    "power_metric": "grid_power_w",
                    "energy_import_metric": "grid_import_energy_kwh",
                    "energy_export_metric": "grid_export_energy_kwh",
                },
            ),
            (
                devices["pv-inverter"],
                AssetRole.PV,
                {"power_metric": "pv_power_w", "energy_import_metric": "pv_energy_kwh"},
            ),
            (
                devices["bess-pcs"],
                AssetRole.BATTERY,
                {
                    "power_metric": "battery_power_w",
                    "soc_metric": "battery_soc",
                    "soh_metric": "battery_soh",
                    "energy_import_metric": "battery_charge_energy_kwh",
                    "energy_export_metric": "battery_discharge_energy_kwh",
                    "rated_power_kw": 500.0,
                    "rated_energy_kwh": 1000.0,
                    # A battery's charge and discharge sessions are the whole
                    # point of session tracking, so the demo has them on.
                    "session_tracking_enabled": True,
                    "cost_model": "battery_cycle",
                    # 12M TWD pack over roughly 6,600 full-equivalent cycles
                    # of 1 MWh: about 1.8 TWD per kWh of throughput.
                    "cost_parameters": {"cycle_cost_per_kwh": 1.8},
                },
            ),
        ]
        # Purchase costs, so the investment card has something real in it.
        # Rough Taiwan list prices; the point is the shape of the answer, not
        # the precision of these particular numbers.
        costs = {
            "bess-pcs": (12_000_000.0, 15.0, 180_000.0),
            "pv-inverter": (2_400_000.0, 20.0, 40_000.0),
            "smart-meter": (45_000.0, 10.0, 0.0),
            "ems-controller": (180_000.0, 10.0, 12_000.0),
        }
        for key, (capital, life, upkeep) in costs.items():
            device = devices.get(key)
            if device is None:
                continue
            device.capital_cost = capital
            device.cost_currency = "TWD"
            device.expected_life_years = life
            device.annual_maintenance_cost = upkeep
            device.commissioned_on = device.created_at.date()
            device.save(
                update_fields=[
                    "capital_cost",
                    "cost_currency",
                    "expected_life_years",
                    "annual_maintenance_cost",
                    "commissioned_on",
                    "updated_at",
                ]
            )

        for device, role, extra in bindings:
            EnergyAsset.objects.update_or_create(
                site=site,
                device=device,
                role=role,
                defaults={
                    "organization": organization,
                    "name": device.name,
                    # Devices report watts; the EMS module works in kW.
                    "power_scale": 0.001,
                    "is_active": True,
                    **extra,
                },
            )

    def _alert_rules(self, organization: Organization, site: Site) -> None:
        rules = [
            {
                "name": "Battery SOC critically low",
                "metric_key": "battery_soc",
                "operator": "lt",
                "threshold": 10.0,
                "hysteresis": 3.0,
                "severity": Severity.CRITICAL,
                "for_duration_seconds": 120,
                "message_template": "{device}: SOC dropped to {value}% (limit {threshold}%)",
            },
            {
                "name": "Battery over-temperature",
                "metric_key": "battery_temperature_c",
                "operator": "gt",
                "threshold": 45.0,
                "hysteresis": 3.0,
                "severity": Severity.MAJOR,
                "for_duration_seconds": 60,
                "message_template": "{device}: battery at {value} degC",
            },
            {
                "name": "Grid voltage out of range",
                "metric_key": "grid_voltage_v",
                "operator": "outside",
                "threshold": 198.0,
                "threshold_upper": 242.0,
                "hysteresis": 2.0,
                "severity": Severity.WARNING,
                "for_duration_seconds": 30,
            },
            {
                "name": "Contract capacity exceeded",
                "metric_key": "grid_power_w",
                "operator": "gt",
                # Must track contract_capacity_kw on the storage plan, or the
                # rule silently never fires.
                "threshold": 450_000.0,
                "hysteresis": 10_000.0,
                "severity": Severity.MAJOR,
                "for_duration_seconds": 300,
                "message_template": "{device}: importing {value} W above the contract",
            },
        ]
        for rule in rules:
            AlertRule.objects.update_or_create(
                organization=organization,
                name=rule.pop("name"),
                defaults={
                    "scope": RuleScope.SITE,
                    "site": site,
                    "is_enabled": True,
                    "cooldown_seconds": 600,
                    "auto_resolve": True,
                    **rule,
                },
            )


    def _workflow(self, organization: Organization, site: Site, devices: dict) -> None:
        """One drawn control flow, so the editor opens on a real example.

        Two parallel branches: discharge while demand stays over the contract,
        and stop discharging when the battery runs low. The graph ships as a
        fixture with ``{DEVICE-ID}`` placeholders, resolved against the seeded
        devices here so the node parameters point at real rows.
        """
        import json
        from pathlib import Path

        from apps.workflows.models import Workflow

        fixture = Path(__file__).resolve().parents[2] / "fixtures" / "demo_workflow.json"
        graph_text = fixture.read_text(encoding="utf-8")
        for key, device in devices.items():
            graph_text = graph_text.replace("{" + device.device_id + "}", str(device.id))
        graph = json.loads(graph_text)

        Workflow.objects.update_or_create(
            organization=organization,
            name="削峰與低電量保護",
            defaults={
                "site": site,
                "description": "兩條並行分支：需量持續偏高就放電削峰；電量偏低就停止放電。",
                "graph": graph,
                "is_enabled": True,
            },
        )
