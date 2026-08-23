"""Platform side of the device simulator: describe the registered fleet.

The simulator itself (``simulator/``) is a standalone MQTT client and knows
nothing about this database. What it needs is a description of the
gateways and devices it should impersonate, and that is what this module
produces from the registry - the same information a vendor would be handed
when commissioning a site. ``manage.py export_fleet_config`` writes it to
``simulator/fleet.json``.

``build_fleet`` keeps the old in-process convenience for tests and scripts:
export, then instantiate runners against this deployment's broker.
"""

from __future__ import annotations

from django.conf import settings

from simulator.config import BrokerConfig, DeviceConfig, FleetConfig, GatewayConfig
from simulator.physics import LOAD_SHAPES, METRIC_UNITS, SimDevice, SitePhysics

__all__ = [
    "LOAD_SHAPES",
    "METRIC_UNITS",
    "SimDevice",
    "SitePhysics",
    "build_fleet",
    "export_fleet_config",
]


def export_fleet_config(organization, *, only_sites: set[str] | None = None,
                        broker: BrokerConfig | None = None) -> FleetConfig:
    """Describe every registered gateway of ``organization`` for the simulator.

    Physics are sized from the energy-asset ratings; the load shape comes
    from the site's ``sim:<kind>`` tag. Gateways with no energy assets are
    still included (their devices publish as plain controllers) so that
    "every registered device comes online" means all of them.
    """
    from apps.devices.models import Device, EdgeNode
    from apps.ems.models import AssetRole, EnergyAsset
    from apps.ems.plans import effective_plan

    mqtt = settings.MQTT
    broker = broker or BrokerConfig(
        host=mqtt["HOST"], port=int(mqtt["PORT"]),
        username=mqtt.get("USERNAME") or "", password=mqtt.get("PASSWORD") or "",
        # Always 3.1.1: the bundled dev broker speaks only that, EMQX takes
        # both, and a vendor's firmware is far more likely to have it.
        protocol="311",
    )
    config = FleetConfig(broker=broker, group_id=organization.slug)

    assets = (
        EnergyAsset.objects.filter(organization=organization, is_active=True)
        .select_related("site", "device", "device__edge_node")
    )
    by_node: dict = {}
    for asset in assets:
        device = asset.device
        node = device.edge_node
        if device.deleted_at is not None or node is None or node.deleted_at is not None:
            continue
        site = asset.site
        if only_sites and site.code not in only_sites:
            continue
        spec = by_node.get(node.pk)
        if spec is None:
            kind = next((t.split(":", 1)[1] for t in (site.tags or []) if t.startswith("sim:")), "factory")
            spec = GatewayConfig(node_id=node.node_id, site_name=site.name, kind=kind,
                                 timezone=site.timezone_name or "Asia/Taipei")
            by_node[node.pk] = spec
        if asset.role == AssetRole.BATTERY:
            spec.battery_kw = asset.rated_power_kw or spec.battery_kw
            spec.battery_kwh = asset.rated_energy_kwh or spec.battery_kwh
            # W6：邊緣 fail-safe 參數抄自方案，模擬器與平台講同一套。
            plan, _source = effective_plan(site)
            if plan is not None:
                spec.watchdog_seconds = float(plan.heartbeat_interval_seconds * plan.heartbeat_miss_limit)
                spec.offline_policy = plan.offline_policy
                spec.reserve_soc = float(max(plan.backup_reserve_percent, plan.min_soc_percent))
        elif asset.role == AssetRole.PV:
            spec.pv_peak_kw = asset.rated_power_kw or spec.pv_peak_kw
        elif asset.role == AssetRole.LOAD_METER:
            spec.peak_load_kw = asset.rated_power_kw or spec.peak_load_kw
        elif asset.role == AssetRole.GRID_METER and asset.rated_power_kw:
            spec.peak_load_kw = max(spec.peak_load_kw, asset.rated_power_kw)
        if not any(d.device_id == device.device_id for d in spec.devices):
            spec.devices.append(DeviceConfig(device.device_id, str(asset.role), asset.power_metric, device.name))

    nodes = EdgeNode.objects.filter(
        organization=organization, deleted_at__isnull=True, is_enabled=True
    ).select_related("site")
    for node in nodes:
        if only_sites and (node.site is None or node.site.code not in only_sites):
            continue
        spec = by_node.get(node.pk)
        devices = list(Device.objects.filter(edge_node=node, deleted_at__isnull=True).order_by("device_id"))
        if spec is None:
            if not devices:
                continue
            spec = GatewayConfig(
                node_id=node.node_id, site_name=node.site.name if node.site else "",
                timezone=(node.site.timezone_name if node.site else "") or "Asia/Taipei",
            )
            by_node[node.pk] = spec
        credential = getattr(node, "credential", None)
        if credential is not None:
            spec.username = credential.mqtt_username
        known = {d.device_id for d in spec.devices}
        for device in devices:
            if device.device_id not in known:
                spec.devices.append(DeviceConfig(device.device_id, "controller", "", device.name))

    config.gateways = sorted(by_node.values(), key=lambda g: g.node_id)
    return config


def build_fleet(organization, *, interval: float, faults: bool, autonomous: bool, report=print,
                only_sites: set[str] | None = None):
    """Runners for every registered gateway, against this deployment's broker."""
    from simulator.gateway import GatewayRunner

    config = export_fleet_config(organization, only_sites=only_sites)
    return [
        GatewayRunner(config.broker, config.group_id, spec, interval=interval, faults=faults,
                      autonomous=autonomous, report=report)
        for spec in config.gateways
    ]
