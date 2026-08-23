"""Seed the customer showcase: a multi-site tenant with a coherent fleet.

What it builds, and why each piece is there:

* **Sites** - a science-park campus with two buildings (factory + office)
  under it, plus a standalone industrial plant and the head office. The tree
  exists to show plan inheritance: the campus carries a plan, building A
  inherits it, building B overrides with its own.
* **Gateways and devices** - one Sparkplug edge node per site, fronting a
  battery, a grid meter, a PV unit, a load monitor and an EMS controller.
  The ``sim:<kind>`` site tag tells the simulation console which load shape the
  site follows.
* **Energy assets** - the bindings with real ratings; the simulation console
  sizes its physics from them, and ``generate_history`` uses them to build
  the intervals and costs the savings figures come from.
* **Tariffs and plans** - Taipower presets and one plan per strategy, so the
  benefit of each strategy is visible side by side.

Run on a clean database (``scripts/reset-demo.ps1`` does the whole chain).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Membership, Organization, Role, User
from apps.alerts.models import (
    AlertRule,
    ChannelType,
    NotificationChannel,
    RuleScope,
    Severity,
)
from apps.devices.models import (
    Device,
    DeviceType,
    EdgeNode,
    EdgeNodeCredential,
    Site,
    SiteKind,
)
from apps.ems.models import (
    AssetRole,
    DispatchStrategy,
    EnergyAsset,
    StoragePlan,
    Tariff,
)
from apps.ems.taipower import presets
from apps.telemetry.models import RecordingPolicy

PASSWORD = "ChangeMe-2026!"

# (code, parent code, kind, name, address, city, lat, lon, sim kind, description)
SITES = [
    ("hsinchu", None, SiteKind.SITE, "新竹科學園區", "新竹市東區園區二路", "新竹市",
     24.7805, 121.0063, "campus", "園區總表；下轄生產廠房與研發大樓，儲能方案由園區統一設定。"),
    ("hsinchu-a", "hsinchu", SiteKind.AREA, "A棟 生產廠房", "新竹市東區園區二路 A棟", "新竹市",
     24.7812, 121.0071, "factory", "三班制生產，日間尖峰負載高，契約容量管理效益最明顯。"),
    ("hsinchu-b", "hsinchu", SiteKind.AREA, "B棟 研發大樓", "新竹市東區園區二路 B棟", "新竹市",
     24.7798, 121.0055, "office", "辦公負載，屋頂光電充足，改採光儲自發自用（覆寫園區方案）。"),
    ("taichung", None, SiteKind.SITE, "台中工業區廠房", "台中市西屯區工業區一路", "台中市",
     24.1659, 120.6101, "factory", "低壓電力二段式電價，離峰充電、尖峰放電套利。"),
    ("taipei-hq", None, SiteKind.SITE, "台北總部大樓", "台北市信義區信義路五段7號", "台北市",
     25.0339, 121.5645, "office", "總部辦公大樓，契約容量管理。"),
]

# Per-site plant sizing: peak load kW, PV kW, battery kW, battery kWh, contract kW.
SIZING = {
# Contracts sit just under each site's natural afternoon peak on purpose: the
# battery has something to shave, so the demand-cap strategy visibly acts.
    "hsinchu-a": (900.0, 400.0, 500.0, 1000.0, 680.0),
    "hsinchu-b": (320.0, 400.0, 250.0, 500.0, 300.0),
    "taichung": (1200.0, 300.0, 1000.0, 2000.0, 1100.0),
    "taipei-hq": (300.0, 80.0, 200.0, 500.0, 210.0),
}

# Plans: name -> (strategy, bound site codes, tariff preset, overrides)
PLANS = [
    ("園區契約容量管理", DispatchStrategy.DEMAND_CAP, ["hsinchu"], "taipower-lv-power-2tier",
     {"contract_capacity_kw": 680.0, "demand_cap_target_kw": 650.0,
      "usable_capacity_kwh": 1000.0, "max_charge_kw": 500.0, "max_discharge_kw": 500.0,
      "outage_voltage_min_v": 180.0,
      "notes": "園區統一方案：15 分鐘需量壓在契約容量以下，離峰回充。A 棟直接繼承。"}),
    ("研發大樓光儲自發自用", DispatchStrategy.SELF_CONSUMPTION, ["hsinchu-b"], "taipower-residential-3tier",
     {"usable_capacity_kwh": 500.0, "max_charge_kw": 250.0, "max_discharge_kw": 250.0,
      "export_limit_kw": 0.0,
      "notes": "覆寫園區方案：屋頂與車棚光電 400 kWp，中午餘電先充電，傍晚放電供自用。"}),
    ("工業區時間電價套利", DispatchStrategy.TOU_ARBITRAGE, ["taichung"], "taipower-lv-power-2tier",
     {"contract_capacity_kw": 1100.0, "usable_capacity_kwh": 2000.0,
      "max_charge_kw": 1000.0, "max_discharge_kw": 1000.0, "min_price_spread": 1.5,
      "outage_voltage_min_v": 180.0,
      "notes": "離峰 2.36 元充電、尖峰 5.85 元放電；價差低於門檻時不動作。"}),
    ("總部契約容量管理", DispatchStrategy.DEMAND_CAP, ["taipei-hq"], "taipower-lv-power-2tier",
     {"contract_capacity_kw": 210.0, "demand_cap_target_kw": 200.0,
      "usable_capacity_kwh": 500.0, "max_charge_kw": 200.0, "max_discharge_kw": 200.0,
      "outage_voltage_min_v": 180.0,
      "notes": "總部以小型儲能削減午後需量尖峰。"}),
]


class Command(BaseCommand):
    help = "Seed the multi-site customer showcase tenant."

    def add_arguments(self, parser):
        parser.add_argument("--org-slug", default="zqs-demo")
        parser.add_argument("--org-name", default="ZQS 示範能源股份有限公司")
        parser.add_argument("--email", default="admin@example.com")
        parser.add_argument("--password", default=PASSWORD)

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
        accounts = [
            (options["email"], "系統管理員", Role.OWNER),
            ("operator@example.com", "值班工程師", Role.OPERATOR),
            ("viewer@example.com", "管理階層檢視", Role.VIEWER),
        ]
        for email, full_name, role in accounts:
            user = self._user(email, options["password"], full_name)
            Membership.objects.update_or_create(
                organization=organization, user=user, defaults={"role": role}
            )

        policy = self._policy(organization)
        tariffs = self._tariffs(organization)
        sites = self._sites(organization)
        blueprints = {b.key: b for b in DeviceType.objects.filter(organization__isnull=True)}

        all_devices: dict[str, dict[str, Device]] = {}
        for code, (peak, pv, kw, kwh, _contract) in SIZING.items():
            site = sites[code]
            devices = self._devices(organization, site, policy, blueprints, kw, kwh, pv)
            self._assets(organization, site, devices, peak, pv, kw, kwh)
            all_devices[code] = devices

        self._plans(organization, sites, tariffs)
        self._alert_rules(organization, sites)
        self._channel(organization)
        self._workflows(organization, sites, all_devices)

        self.stdout.write(self.style.SUCCESS("Showcase tenant ready."))
        self.stdout.write(f"  organization : {organization.name} ({organization.slug})")
        for email, _name, role in accounts:
            self.stdout.write(f"  {role:<9}: {email} / {options['password']}")
        self.stdout.write(f"  sites        : {', '.join(sites)}")
        self.stdout.write(
            "  devices      : "
            + str(sum(len(d) for d in all_devices.values()))
            + " across "
            + str(len(all_devices))
            + " gateways"
        )

    # ---- pieces ----------------------------------------------------------
    def _user(self, email: str, password: str, full_name: str) -> User:
        user = User.objects.filter(email=email.lower()).first()
        if user is None:
            user = User.objects.create_user(
                email=email, password=password, full_name=full_name,
                language="zh-hant", timezone_name="Asia/Taipei",
            )
        return user

    def _policy(self, organization: Organization) -> RecordingPolicy:
        policy, _ = RecordingPolicy.objects.update_or_create(
            organization=organization,
            name="標準記錄策略",
            defaults={
                "description": "功率訊號全記錄，緩變訊號以死區稀疏化，每小時強制保存心跳樣本。",
                "is_default": True,
                "record_unlisted_metrics": True,
                "default_retention_days": 365,
                "default_min_interval_seconds": 0,
                "default_max_interval_seconds": 3600,
            },
        )
        return policy

    def _tariffs(self, organization: Organization) -> dict[str, Tariff]:
        out = {}
        for preset in presets():
            tariff, _ = Tariff.objects.update_or_create(
                organization=organization, name=preset["name"],
                defaults={**preset["tariff"], "is_active": True},
            )
            out[preset["key"]] = tariff
        return out

    def _sites(self, organization: Organization) -> dict[str, Site]:
        sites: dict[str, Site] = {}
        for code, parent, kind, name, address, city, lat, lon, sim, desc in SITES:
            site, _ = Site.objects.update_or_create(
                organization=organization, code=code,
                defaults={
                    "parent": sites.get(parent) if parent else None,
                    "kind": kind, "name": name, "address": address, "city": city,
                    "country": "TW", "latitude": lat, "longitude": lon,
                    "timezone_name": "Asia/Taipei", "description": desc,
                    "tags": [f"sim:{sim}", "showcase"],
                },
            )
            sites[code] = site
        return sites

    def _devices(self, organization, site, policy, blueprints, kw, kwh, pv) -> dict[str, Device]:
        tag = site.code.upper().replace("-", "")
        node, _ = EdgeNode.objects.get_or_create(
            group_id=organization.slug, node_id=f"GW-{tag}", deleted_at__isnull=True,
            defaults={
                "organization": organization, "site": site,
                "name": f"{site.name} 閘道器",
                "description": "場域 EMS 閘道器；後端設備以 Modbus 連接，對雲端以 Sparkplug B 上傳。",
                "is_implicit": False,
            },
        )
        if not hasattr(node, "credential"):
            EdgeNodeCredential.issue(node)

        spec = [
            (f"{tag}-BESS-01", f"儲能系統 {kw:.0f} kW / {kwh:.0f} kWh", "bess-pcs",
             (kwh * 9_000.0, 15.0, kwh * 120.0)),
            (f"{tag}-METER-01", "市電關口電表", "smart-meter", (45_000.0, 10.0, 0.0)),
            (f"{tag}-PV-01", f"屋頂光電 {pv:.0f} kWp", "power-generation-unit",
             (pv * 45_000.0, 20.0, pv * 600.0)),
            (f"{tag}-LOAD-01", "廠內負載監測", "load-monitor", (25_000.0, 10.0, 0.0)),
            (f"{tag}-EMS-01", "場域 EMS 控制器", "ems-controller", (180_000.0, 10.0, 12_000.0)),
        ]
        devices: dict[str, Device] = {}
        for device_id, name, key, (capital, life, upkeep) in spec:
            device, _ = Device.objects.update_or_create(
                organization=organization, device_id=device_id,
                defaults={
                    "edge_node": node, "site": site, "device_type": blueprints.get(key),
                    "recording_policy": policy, "name": name, "serial_number": device_id,
                    "is_enabled": True, "capital_cost": capital, "cost_currency": "TWD",
                    "expected_life_years": life, "annual_maintenance_cost": upkeep,
                },
            )
            if device.commissioned_on is None:
                device.commissioned_on = device.created_at.date()
                device.save(update_fields=["commissioned_on"])
            devices[key] = device
        return devices

    def _assets(self, organization, site, devices, peak, pv, kw, kwh) -> None:
        bindings = [
            (devices["smart-meter"], AssetRole.GRID_METER, {
                "power_metric": "grid_power_w",
                "voltage_metric": "grid_voltage_v",
                "energy_import_metric": "grid_import_energy_kwh",
                "energy_export_metric": "grid_export_energy_kwh",
                "rated_power_kw": peak,
            }),
            (devices["load-monitor"], AssetRole.LOAD_METER, {
                "power_metric": "load_power_w",
                "energy_import_metric": "load_energy_kwh",
                "rated_power_kw": peak,
            }),
            (devices["power-generation-unit"], AssetRole.PV, {
                "power_metric": "pv_power_w",
                "energy_import_metric": "pv_energy_kwh",
                "rated_power_kw": pv,
            }),
            (devices["bess-pcs"], AssetRole.BATTERY, {
                "power_metric": "battery_power_w",
                "soc_metric": "battery_soc",
                "soh_metric": "battery_soh",
                "energy_import_metric": "battery_charge_energy_kwh",
                "energy_export_metric": "battery_discharge_energy_kwh",
                "rated_power_kw": kw,
                "rated_energy_kwh": kwh,
                "session_tracking_enabled": True,
                "cost_model": "battery_cycle",
                "cost_parameters": {"cycle_cost_per_kwh": 1.8},
            }),
        ]
        for device, role, extra in bindings:
            EnergyAsset.objects.update_or_create(
                site=site, device=device, role=role,
                defaults={
                    "organization": organization, "name": device.name,
                    "power_scale": 0.001, "is_active": True, **extra,
                },
            )

    def _plans(self, organization, sites, tariffs) -> None:
        for name, strategy, codes, tariff_key, overrides in PLANS:
            plan, _ = StoragePlan.objects.update_or_create(
                organization=organization, name=name,
                defaults={
                    "strategy": strategy, "is_enabled": True,
                    "tariff": tariffs.get(tariff_key),
                    "min_soc_percent": 10.0, "max_soc_percent": 95.0,
                    "backup_reserve_percent": 15.0, "round_trip_efficiency": 0.9,
                    "offpeak_recharge": True,
                    "temperature_max_c": 45.0, "temperature_metric": "battery_temperature_c",
                    **overrides,
                },
            )
            for code in codes:
                site = sites[code]
                site.storage_plan = plan
                site.save(update_fields=["storage_plan"])

    def _alert_rules(self, organization, sites) -> None:
        org_rules = [
            {"name": "電池電量過低", "metric_key": "battery_soc", "operator": "lt",
             "threshold": 12.0, "hysteresis": 3.0, "severity": Severity.CRITICAL,
             "for_duration_seconds": 60,
             "message_template": "{device}：SOC 降至 {value}%（下限 {threshold}%）"},
            {"name": "電池溫度過高", "metric_key": "battery_temperature_c", "operator": "gt",
             "threshold": 45.0, "hysteresis": 3.0, "severity": Severity.MAJOR,
             "for_duration_seconds": 30,
             "message_template": "{device}：電池溫度 {value} °C"},
            {"name": "PCS 溫度過高", "metric_key": "pcs_temperature_c", "operator": "gt",
             "threshold": 60.0, "hysteresis": 5.0, "severity": Severity.MAJOR,
             "for_duration_seconds": 30},
            {"name": "市電電壓異常", "metric_key": "grid_voltage_v", "operator": "outside",
             "threshold": 198.0, "threshold_upper": 242.0, "hysteresis": 2.0,
             "severity": Severity.WARNING, "for_duration_seconds": 20},
        ]
        for rule in org_rules:
            AlertRule.objects.update_or_create(
                organization=organization, name=rule.pop("name"),
                defaults={"scope": RuleScope.ORGANIZATION, "site": None, "is_enabled": True,
                          "cooldown_seconds": 300, "auto_resolve": True, **rule},
            )
        for code, (_peak, _pv, _kw, _kwh, contract) in SIZING.items():
            site = sites[code]
            AlertRule.objects.update_or_create(
                organization=organization, name=f"{site.name} 超過契約容量",
                defaults={
                    "scope": RuleScope.SITE, "site": site, "is_enabled": True,
                    "metric_key": "grid_power_w", "operator": "gt",
                    "threshold": contract * 1000.0, "hysteresis": contract * 20.0,
                    "severity": Severity.MAJOR, "for_duration_seconds": 120,
                    "cooldown_seconds": 600, "auto_resolve": True,
                    "message_template": "{device}：市電取用 {value} W，超過契約容量",
                },
            )

    def _channel(self, organization) -> None:
        NotificationChannel.objects.update_or_create(
            organization=organization, name="值班群組 Webhook（範例）",
            defaults={
                "channel_type": ChannelType.WEBHOOK, "is_enabled": False,
                "config": {"url": "https://example.com/hooks/zqs-oncall"},
                "min_severity": Severity.MAJOR, "notify_alerts": True,
                "notify_events": True, "min_event_level": "error",
            },
        )

    def _workflows(self, organization, sites, all_devices) -> None:
        """Six annotated, runnable control flows - see ``showcase_workflows``.

        Created in order so the orchestrator can reference the drill it
        starts; placeholders resolve against the workflow's own site.
        """
        from apps.core.showcase_workflows import SHOWCASE_WORKFLOWS, render
        from apps.workflows.graph import validate_graph
        from apps.workflows.models import Workflow

        keys = {
            "BESS": "bess-pcs", "METER": "smart-meter", "PV": "power-generation-unit",
            "LOAD": "load-monitor", "EMS": "ems-controller",
        }
        created: dict[str, str] = {}
        for name, description, site_code, build in SHOWCASE_WORKFLOWS:
            devices = {k: str(all_devices[site_code][v].id) for k, v in keys.items()}
            graph = render(build(), devices, created)
            validate_graph(graph)
            workflow, _ = Workflow.objects.update_or_create(
                organization=organization, name=name,
                defaults={
                    "site": sites[site_code], "description": description,
                    "graph": graph, "is_enabled": True,
                },
            )
            created[name] = str(workflow.id)
