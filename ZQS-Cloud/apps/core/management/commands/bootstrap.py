"""Seed the built-in metric catalogue and device blueprints.

Idempotent: safe to run on every deploy. Built-ins are global (``organization``
is null) so every tenant inherits them and can still override any key with its
own definition.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.devices.models import (
    CAPABILITY_FIELDS,
    CATEGORY_CAPABILITIES,
    DeviceCategory,
    DeviceType,
)
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


def _command(name: str, label_en: str, label_tw: str, label_cn: str, params: dict, min_role="operator", confirm=False, kind="dispatch") -> dict:
    """One entry in a blueprint's command catalogue.

    ``kind`` separates energy dispatch from housekeeping. ``is_dispatchable``
    blocks the former, so a meter can still be told to change its reporting
    interval while refusing anything that moves power.
    """
    return {
        "name": name,
        "label": {"en": label_en, "zh-hant": label_tw, "zh-hans": label_cn},
        "params": params,
        "min_role": min_role,
        "confirm": confirm,
        "kind": kind,
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
        "description": (
            "Behind-the-meter battery with an integrated power conversion system. Charges from the grid or from surplus solar and discharges to shave peak demand or to arbitrage a time-of-use tariff. Pick this for the cabinet as a whole when the battery and its inverter are one unit."
        ),
        "translations": {
            "zh-hant": {"description": "表後儲能系統，電池與功率轉換系統整合成一台。可從市電或多餘的太陽能充電，放電用來削減尖峰需量或做時間電價套利。電池與變流器是同一台機櫃時選這個。"},
            "zh-hans": {"description": "表后储能系统，电池与功率转换系统整合成一台。可从市电或多余的太阳能充电，放电用来削减尖峰需量或做分时电价套利。电池与变流器是同一台机柜时选这个。"},
        },
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
                        # W6：有效期。邊緣在 valid_until 之後依 on_expiry 自行降級，
                        # 斷網時電池不會停在最後一個設定點。
                        "valid_until": {"type": "string", "description": "ISO 8601 UTC; setpoint expires after this"},
                        "on_expiry": {"type": "string", "enum": ["idle", "hold", "reserve"]},
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
        "description": (
            "Revenue-grade or sub-meter reporting power and cumulative energy. Measures only - it is never dispatched. Bind the one at the point of common coupling as the site's grid meter; bind any others as sub-meters with 'include in balance' off, or their energy is counted twice."
        ),
        "translations": {
            "zh-hant": {"description": "電錶，回報功率與累計電量，可以是計費用主錶或分錶。它只量測，永遠不會被下命令。接在總進線（PCC）的那一顆綁成場域的市電錶；其餘的綁成分錶並關掉「納入能源平衡」，否則同一度電會被算兩次。"},
            "zh-hans": {"description": "电表，回报功率与累计电量，可以是计费用主表或分表。它只量测，永远不会被下命令。接在总进线（PCC）的那一颗绑成场域的市电表；其余的绑成分表并关掉“纳入能源平衡”，否则同一度电会被算两次。"},
        },
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
                kind="config",
            ),
        ],
    },
    {
        "key": "power-generation-unit",
        "name": "Power generation unit",
        "category": DeviceCategory.GENERATION,
        "description": (
            "Anything that produces power for the site: solar, fuel cell, wind, CHP. One blueprint rather than one per technology, because the platform treats them identically - they generate, they can export, they never charge. What differs between them is fuel cost, and that belongs on the cost model, not on the blueprint."
        ),
        "translations": {
            "zh-hant": {"description": "為場域產生電力的設備：太陽能、燃料電池、風力、汽電共生。一個藍圖而不是每種技術各一個，因為平台對它們的處理完全相同——都是發電、可逆送、不充電。它們之間真正的差別是燃料成本，而那屬於成本模型，不屬於藍圖。"},
            "zh-hans": {"description": "为场域产生电力的设备：太阳能、燃料电池、风力、汽电共生。一个蓝图而不是每种技术各一个，因为平台对它们的处理完全相同——都是发电、可逆送、不充电。它们之间真正的差别是燃料成本，而那属于成本模型，不属于蓝图。"},
        },
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
        "key": "load-monitor",
        "name": "Monitored load",
        "category": DeviceCategory.LOAD,
        "description": (
            "A piece of equipment registered purely so its consumption is visible: a chiller, a compressor, a production line. It reports and is never commanded, which is why it carries no commands at all. Registering one does not change the site energy balance - see the note on double counting in docs/system-logic.html."
        ),
        "translations": {
            "zh-hant": {"description": "純粹為了看見耗電量而登記的設備：冰水主機、空壓機、產線。它只回報、不接受命令，所以沒有任何可用命令。登記它不會改變場域的能量平衡——重複計算的說明見 docs/system-logic.html。"},
            "zh-hans": {"description": "纯粹为了看见耗电量而登记的设备：冰水主机、空压机、产线。它只回报、不接受命令，所以没有任何可用命令。登记它不会改变场域的能量平衡——重复计算的说明见 docs/system-logic.html。"},
        },
        "command_definitions": [],
    },
    {
        "key": "ems-controller",
        "name": "EMS site controller",
        "category": DeviceCategory.CONTROLLER,
        "description": (
            "Site-level controller coordinating local assets. Carries no energy itself, so it takes no part in the energy balance; register it when the hardware that runs local control also reports its own status."
        ),
        "translations": {
            "zh-hant": {"description": "場域層級的控制器，協調現場各項資產。它本身不承載能量，因此不參與能源平衡；當負責現場控制的硬體也會回報自己的狀態時，才需要登記它。"},
            "zh-hans": {"description": "场域层级的控制器，协调现场各项资产。它本身不承载能量，因此不参与能源平衡；当负责现场控制的硬件也会回报自己的状态时，才需要登记它。"},
        },
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
                kind="config",
            ),
        ],
    },
    {
        "key": "ev-charger",
        "name": "EV charger",
        "category": DeviceCategory.EV_CHARGER,
        "description": (
            "AC or DC electric vehicle supply equipment. Draws power and never returns it, so it charges but does not discharge. Its consumption is already inside the site's load; bind it as a separate role only when you want its sessions and energy reported on their own."
        ),
        "translations": {
            "zh-hant": {"description": "交流或直流的電動車充電設備。只取電、不回送，因此只會充電不會放電。它的用電本來就已經包含在場域負載裡；只有在你想單獨看它的充電次數與用電量時，才另外綁成一個角色。"},
            "zh-hans": {"description": "交流或直流的电动车充电设备。只取电、不回送，因此只会充电不会放电。它的用电本来就已经包含在场域负载里；只有在你想单独看它的充电次数与用电量时，才另外绑成一个角色。"},
        },
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
        for builtin in BUILTIN_DEVICE_TYPES:
            # A copy: the table is module state, and popping the key out of
            # it made a second call in the same process (tests, a seed that
            # bootstraps first) fail with KeyError.
            blueprint = dict(builtin)
            key = blueprint.pop("key")
            # Capabilities follow from the category, so a new built-in
            # blueprint gets sensible defaults without anyone hand-filling four
            # booleans. Re-running with --update-existing is how already
            # installed deployments pick them up - no data migration needed.
            defaults = CATEGORY_CAPABILITIES.get(
                blueprint.get("category"), CATEGORY_CAPABILITIES[DeviceCategory.OTHER]
            )
            for field, value in zip(CAPABILITY_FIELDS, defaults):
                blueprint.setdefault(field, value)
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
