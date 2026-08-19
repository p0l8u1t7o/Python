"""Seed the built-in metric catalogue and device blueprints.

Idempotent: safe to run on every deploy. Built-ins are global (``organization``
is null) so every tenant inherits them and can still override any key with its
own definition.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.devices.models import DeviceCategory, DeviceType
from apps.telemetry.models import Aggregation, Metric, MetricKind, ValueType

# key, display, unit, value_type, kind, aggregation, min, max, category, zh-hant, zh-hans
BUILTIN_METRICS: list[tuple] = [
    # ---- Grid / point of common coupling ----
    ("grid_power_w", "Grid power", "W", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, -5e7, 5e7, "power", "市電功率", "市电功率"),
    ("grid_voltage_v", "Grid voltage", "V", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 0, 1000, "electrical", "市電電壓", "市电电压"),
    ("grid_current_a", "Grid current", "A", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, -10000, 10000, "electrical", "市電電流", "市电电流"),
    ("grid_frequency_hz", "Grid frequency", "Hz", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 40, 70, "electrical", "市電頻率", "市电频率"),
    ("grid_import_energy_kwh", "Cumulative grid import", "kWh", ValueType.FLOAT, MetricKind.COUNTER, Aggregation.COUNTER, 0, None, "energy", "累計市電購電量", "累计市电购电量"),
    ("grid_export_energy_kwh", "Cumulative grid export", "kWh", ValueType.FLOAT, MetricKind.COUNTER, Aggregation.COUNTER, 0, None, "energy", "累計躉售電量", "累计上网电量"),
    ("grid_power_factor", "Power factor", "", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, -1, 1, "electrical", "功率因數", "功率因数"),
    # ---- Load ----
    ("load_power_w", "Site load", "W", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 0, 5e7, "power", "場域負載", "场域负载"),
    ("load_energy_kwh", "Cumulative load energy", "kWh", ValueType.FLOAT, MetricKind.COUNTER, Aggregation.COUNTER, 0, None, "energy", "累計用電量", "累计用电量"),
    # ---- PV ----
    ("pv_power_w", "PV power", "W", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 0, 5e7, "power", "太陽能發電功率", "光伏发电功率"),
    ("pv_energy_kwh", "Cumulative PV energy", "kWh", ValueType.FLOAT, MetricKind.COUNTER, Aggregation.COUNTER, 0, None, "energy", "累計發電量", "累计发电量"),
    ("pv_irradiance_wm2", "Irradiance", "W/m2", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 0, 2000, "environment", "日照強度", "辐照强度"),
    # ---- Battery / BESS ----
    ("battery_power_w", "Battery power", "W", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, -5e7, 5e7, "power", "電池功率", "电池功率"),
    ("battery_soc", "State of charge", "%", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 0, 100, "battery", "電池電量", "电池电量"),
    ("battery_soh", "State of health", "%", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 0, 100, "battery", "電池健康度", "电池健康度"),
    ("battery_voltage_v", "Battery voltage", "V", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 0, 2000, "battery", "電池電壓", "电池电压"),
    ("battery_current_a", "Battery current", "A", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, -10000, 10000, "battery", "電池電流", "电池电流"),
    ("battery_temperature_c", "Battery temperature", "degC", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, -40, 120, "battery", "電池溫度", "电池温度"),
    ("battery_cell_voltage_max_v", "Max cell voltage", "V", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.MAX, 0, 10, "battery", "最高單體電壓", "最高单体电压"),
    ("battery_cell_voltage_min_v", "Min cell voltage", "V", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.MIN, 0, 10, "battery", "最低單體電壓", "最低单体电压"),
    ("battery_charge_energy_kwh", "Cumulative charge energy", "kWh", ValueType.FLOAT, MetricKind.COUNTER, Aggregation.COUNTER, 0, None, "energy", "累計充電量", "累计充电量"),
    ("battery_discharge_energy_kwh", "Cumulative discharge energy", "kWh", ValueType.FLOAT, MetricKind.COUNTER, Aggregation.COUNTER, 0, None, "energy", "累計放電量", "累计放电量"),
    ("battery_cycle_count", "Cycle count", "", ValueType.INTEGER, MetricKind.COUNTER, Aggregation.LAST, 0, None, "battery", "循環次數", "循环次数"),
    # ---- PCS / inverter ----
    ("pcs_state", "PCS state", "", ValueType.STRING, MetricKind.STATE, Aggregation.LAST, None, None, "status", "PCS 狀態", "PCS 状态"),
    ("pcs_temperature_c", "PCS temperature", "degC", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, -40, 150, "status", "PCS 溫度", "PCS 温度"),
    ("pcs_fault_code", "PCS fault code", "", ValueType.STRING, MetricKind.STATE, Aggregation.LAST, None, None, "status", "PCS 故障碼", "PCS 故障码"),
    # ---- EV charging ----
    ("ev_charger_power_w", "EV charger power", "W", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 0, 1e6, "power", "充電樁功率", "充电桩功率"),
    ("ev_session_energy_kwh", "EV session energy", "kWh", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.LAST, 0, None, "energy", "本次充電量", "本次充电量"),
    # ---- Environment / diagnostics ----
    ("ambient_temperature_c", "Ambient temperature", "degC", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, -50, 80, "environment", "環境溫度", "环境温度"),
    ("humidity_percent", "Humidity", "%", ValueType.FLOAT, MetricKind.GAUGE, Aggregation.AVG, 0, 100, "environment", "相對濕度", "相对湿度"),
    ("signal_rssi_dbm", "Signal strength", "dBm", ValueType.INTEGER, MetricKind.GAUGE, Aggregation.AVG, -120, 0, "diagnostics", "訊號強度", "信号强度"),
    ("uptime_s", "Uptime", "s", ValueType.INTEGER, MetricKind.COUNTER, Aggregation.LAST, 0, None, "diagnostics", "運行時間", "运行时间"),
]


def _command(name: str, label_en: str, label_tw: str, label_cn: str, params: dict, min_role="operator", confirm=False) -> dict:
    return {
        "name": name,
        "label": {"en": label_en, "zh-hant": label_tw, "zh-hans": label_cn},
        "params": params,
        "min_role": min_role,
        "confirm": confirm,
    }


_NUMBER = lambda minimum, maximum, unit: {  # noqa: E731 - concise schema literal
    "type": "number",
    "minimum": minimum,
    "maximum": maximum,
    "unit": unit,
}

BUILTIN_DEVICE_TYPES: list[dict] = [
    {
        "key": "bess-pcs",
        "name": "Battery energy storage system (PCS)",
        "category": DeviceCategory.BATTERY,
        "description": "Behind-the-meter battery with an integrated power conversion system.",
        "command_definitions": [
            _command(
                "set_power_limit",
                "Set power limit",
                "設定功率上限",
                "设定功率上限",
                {
                    "type": "object",
                    "required": ["limit_w"],
                    "properties": {"limit_w": _NUMBER(0, 5_000_000, "W")},
                },
            ),
            _command(
                "set_power_setpoint",
                "Set active power setpoint",
                "設定有效功率設定值",
                "设定有功功率设定值",
                {
                    "type": "object",
                    "required": ["power_w"],
                    "properties": {
                        "power_w": _NUMBER(-5_000_000, 5_000_000, "W"),
                        "ramp_s": _NUMBER(0, 3600, "s"),
                    },
                },
            ),
            _command(
                "set_mode",
                "Set operating mode",
                "設定運轉模式",
                "设定运行模式",
                {
                    "type": "object",
                    "required": ["mode"],
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["idle", "charge", "discharge", "auto", "standby"],
                        }
                    },
                },
            ),
            _command(
                "set_soc_limits",
                "Set SOC limits",
                "設定 SOC 上下限",
                "设定 SOC 上下限",
                {
                    "type": "object",
                    "properties": {
                        "min_soc": _NUMBER(0, 100, "%"),
                        "max_soc": _NUMBER(0, 100, "%"),
                    },
                },
            ),
            _command(
                "emergency_stop",
                "Emergency stop",
                "緊急停機",
                "紧急停机",
                {"type": "object", "properties": {}},
                min_role="operator",
                confirm=True,
            ),
            _command(
                "reboot",
                "Reboot controller",
                "重新啟動控制器",
                "重新启动控制器",
                {"type": "object", "properties": {}},
                min_role="admin",
                confirm=True,
            ),
        ],
    },
    {
        "key": "smart-meter",
        "name": "Smart energy meter",
        "category": DeviceCategory.METER,
        "description": "Revenue-grade or sub-meter reporting power and cumulative energy.",
        "command_definitions": [
            _command(
                "set_report_interval",
                "Set reporting interval",
                "設定回報週期",
                "设定回报周期",
                {
                    "type": "object",
                    "required": ["interval_s"],
                    "properties": {"interval_s": _NUMBER(1, 3600, "s")},
                },
                min_role="admin",
            ),
        ],
    },
    {
        "key": "pv-inverter",
        "name": "PV inverter",
        "category": DeviceCategory.PV_INVERTER,
        "description": "Grid-tied solar inverter.",
        "command_definitions": [
            _command(
                "set_export_limit",
                "Set export limit",
                "設定饋線輸出上限",
                "设定馈线输出上限",
                {
                    "type": "object",
                    "required": ["limit_w"],
                    "properties": {"limit_w": _NUMBER(0, 5_000_000, "W")},
                },
            ),
            _command(
                "set_output_enabled",
                "Enable / disable output",
                "啟用或停用輸出",
                "启用或停用输出",
                {
                    "type": "object",
                    "required": ["enabled"],
                    "properties": {"enabled": {"type": "boolean"}},
                },
                confirm=True,
            ),
        ],
    },
    {
        "key": "ems-controller",
        "name": "EMS site controller",
        "category": DeviceCategory.CONTROLLER,
        "description": "Site-level controller coordinating local assets.",
        "command_definitions": [
            _command(
                "set_strategy",
                "Set dispatch strategy",
                "設定調度策略",
                "设定调度策略",
                {
                    "type": "object",
                    "required": ["strategy"],
                    "properties": {
                        "strategy": {
                            "type": "string",
                            "enum": [
                                "manual",
                                "self_consumption",
                                "peak_shaving",
                                "tou_arbitrage",
                                "backup_only",
                            ],
                        },
                        "target_kw": _NUMBER(0, 5_000_000, "kW"),
                    },
                },
                min_role="admin",
            ),
            _command(
                "sync_time",
                "Synchronise clock",
                "校時",
                "校时",
                {
                    "type": "object",
                    "properties": {"epoch_ms": {"type": "integer"}},
                },
            ),
        ],
    },
    {
        "key": "ev-charger",
        "name": "EV charger",
        "category": DeviceCategory.EV_CHARGER,
        "description": "AC or DC electric vehicle supply equipment.",
        "command_definitions": [
            _command(
                "set_current_limit",
                "Set charging current limit",
                "設定充電電流上限",
                "设定充电电流上限",
                {
                    "type": "object",
                    "required": ["limit_a"],
                    "properties": {"limit_a": _NUMBER(0, 500, "A")},
                },
            ),
            _command(
                "stop_session",
                "Stop charging session",
                "停止充電",
                "停止充电",
                {"type": "object", "properties": {}},
                confirm=True,
            ),
        ],
    },
]


class Command(BaseCommand):
    help = "Create or update the built-in metric catalogue and device blueprints."

    def add_arguments(self, parser):
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Overwrite built-ins that already exist (default: only create missing).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        update = options["update_existing"]
        created_metrics = updated_metrics = 0

        for row in BUILTIN_METRICS:
            (
                key,
                display,
                unit,
                value_type,
                kind,
                aggregation,
                minimum,
                maximum,
                category,
                zh_hant,
                zh_hans,
            ) = row
            defaults = {
                "display_name": display,
                "unit": unit,
                "value_type": value_type,
                "kind": kind,
                "aggregation": aggregation,
                "min_value": minimum,
                "max_value": maximum,
                "category": category,
                "translations": {"en": display, "zh-hant": zh_hant, "zh-hans": zh_hans},
            }
            if update:
                _, created = Metric.objects.update_or_create(
                    organization=None, key=key, defaults=defaults
                )
                created_metrics += int(created)
                updated_metrics += int(not created)
            else:
                _, created = Metric.objects.get_or_create(
                    organization=None, key=key, defaults=defaults
                )
                created_metrics += int(created)

        created_types = updated_types = 0
        for blueprint in BUILTIN_DEVICE_TYPES:
            key = blueprint.pop("key")
            if update:
                _, created = DeviceType.objects.update_or_create(
                    organization=None, key=key, defaults=blueprint
                )
                created_types += int(created)
                updated_types += int(not created)
            else:
                _, created = DeviceType.objects.get_or_create(
                    organization=None, key=key, defaults=blueprint
                )
                created_types += int(created)

        self.stdout.write(
            self.style.SUCCESS(
                f"metrics: {created_metrics} created, {updated_metrics} updated; "
                f"blueprints: {created_types} created, {updated_types} updated"
            )
        )
