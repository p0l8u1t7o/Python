"""Per-site plant physics for the device simulator.

Standalone: no Django, no database. A site is a load curve (factory, office
or campus shape scaled to its peak), a solar curve, and a battery whose SOC
integrates whatever setpoint the platform last sent. The grid meter is the
balance: ``grid = load - pv - battery``. That one identity is what makes a
command from the platform show up on the meter a second later, which is the
whole point of simulating a plant rather than replaying numbers.
"""

from __future__ import annotations

import datetime as dt
import math
import random
import threading
import time
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

LOAD_SHAPES: dict[str, list[float]] = {
    "factory": [0.35, 0.33, 0.32, 0.32, 0.33, 0.40, 0.62, 0.85, 0.95, 1.00, 1.00, 0.98,
                0.90, 0.97, 1.00, 0.98, 0.95, 0.90, 0.78, 0.62, 0.50, 0.42, 0.38, 0.36],
    "office":  [0.18, 0.17, 0.17, 0.17, 0.18, 0.22, 0.35, 0.60, 0.85, 0.95, 1.00, 0.98,
                0.90, 0.97, 1.00, 0.96, 0.88, 0.70, 0.45, 0.32, 0.26, 0.22, 0.20, 0.19],
    "campus":  [0.30, 0.28, 0.28, 0.28, 0.30, 0.36, 0.50, 0.70, 0.88, 0.96, 1.00, 0.98,
                0.92, 0.97, 1.00, 0.97, 0.92, 0.84, 0.72, 0.60, 0.50, 0.42, 0.36, 0.32],
}

METRIC_UNITS = {
    "battery_power_w": "W", "battery_soc": "%", "battery_soh": "%",
    "battery_voltage_v": "V", "battery_current_a": "A", "battery_temperature_c": "°C",
    "battery_charge_energy_kwh": "kWh", "battery_discharge_energy_kwh": "kWh",
    "pcs_temperature_c": "°C",
    "grid_power_w": "W", "grid_voltage_v": "V", "grid_current_a": "A",
    "grid_frequency_hz": "Hz", "grid_power_factor": "",
    "grid_import_energy_kwh": "kWh", "grid_export_energy_kwh": "kWh",
    "load_power_w": "W", "load_energy_kwh": "kWh",
    "pv_power_w": "W", "pv_energy_kwh": "kWh", "pv_irradiance_wm2": "W/m²",
    "ambient_temperature_c": "°C", "uptime_s": "s", "signal_rssi_dbm": "dBm",
    "humidity_percent": "%",
}


def _valid_until_monotonic(value) -> float | None:
    """ISO 8601 UTC → monotonic 秒。解析不了就當沒有期限，並不因此拒絕命令。"""
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        when = dt.datetime.fromisoformat(text)
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        remaining = (when - dt.datetime.now(dt.timezone.utc)).total_seconds()
        return time.monotonic() + remaining
    except (TypeError, ValueError):
        return None


@dataclass
class SitePhysics:
    """One site's energy balance, stepped in wall-clock time."""

    kind: str = "factory"
    #: The site's wall clock; the load shape and the sun follow it, not UTC.
    timezone_name: str = "Asia/Taipei"
    peak_load_kw: float = 500.0
    pv_peak_kw: float = 300.0
    battery_kw_rated: float = 250.0
    battery_kwh: float = 500.0
    min_soc: float = 10.0
    max_soc: float = 95.0
    soc: float = 55.0
    #: Commanded battery power in watts: negative charges, positive discharges.
    setpoint_w: float = 0.0
    emergency_stop: bool = False
    #: Optional fallback policy when no setpoint has been received yet.
    autonomous: bool = False

    # ---- edge fail-safe (W6) ---------------------------------------------
    #: 設定點有效期（monotonic 秒）與到期後的行為：idle 歸零、hold 維持、
    #: reserve 充到備援水位。None = 沒有期限（舊版平台的命令）。
    setpoint_valid_until: float | None = None
    on_expiry: str = "idle"
    #: 備援水位（%）；reserve 政策充到這裡就停。
    reserve_soc: float = 20.0
    #: 雲端心跳 watchdog：最近一次收到設定點的時間、允許的靜默秒數、斷線時的政策。
    #: 靜默超過 watchdog_seconds（或 MQTT 連線斷掉超過這個秒數）就進 offline_policy。
    last_setpoint_at: float | None = None
    watchdog_seconds: float = 180.0
    offline_policy: str = "reserve"
    link_down_since: float | None = None
    #: 市電停電：關口電壓 0、電表功率 0，電池自己轉成孤島供電（最多額定功率）。
    grid_outage: bool = False
    #: 最近一次 step 套用的模式，給主控台顯示：normal / expired / watchdog / island。
    mode: str = "normal"

    # running totals (kWh) - what the energy meters report
    import_kwh: float = 0.0
    export_kwh: float = 0.0
    pv_kwh: float = 0.0
    load_kwh: float = 0.0
    charge_kwh: float = 0.0
    discharge_kwh: float = 0.0

    # last computed instantaneous values (kW)
    load_kw: float = 0.0
    pv_kw: float = 0.0
    battery_kw: float = 0.0
    grid_kw: float = 0.0

    _last: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _seen_setpoint: bool = False

    def battery_kw_rating(self) -> float:
        return self.battery_kw_rated

    def command(self, name: str, params: dict) -> str:
        """Apply a platform command; returns a short result message."""
        with self._lock:
            if name == "set_power_setpoint":
                value = params.get("power_w")
                if not isinstance(value, (int, float)):
                    return "power_w missing"
                self.setpoint_w = float(value)
                self._seen_setpoint = True
                self.emergency_stop = False
                self.last_setpoint_at = time.monotonic()
                self.setpoint_valid_until = _valid_until_monotonic(params.get("valid_until"))
                policy = str(params.get("on_expiry") or "idle").lower()
                self.on_expiry = policy if policy in ("idle", "hold", "reserve") else "idle"
                note = ""
                if self.setpoint_valid_until is not None:
                    note = f", valid {self.setpoint_valid_until - time.monotonic():.0f}s then {self.on_expiry}"
                return f"setpoint {self.setpoint_w / 1000:.1f} kW{note}"
            if name == "emergency_stop":
                self.setpoint_w = 0.0
                self.emergency_stop = True
                return "stopped"
            if name in ("reboot", "reset", "clear_alarms"):
                return "ok"
            return "accepted"

    def _policy_kw(self, policy: str) -> float:
        """過期／斷線政策換算成功率（kW）。"""
        if policy == "hold":
            return self.setpoint_w / 1000.0
        if policy == "reserve":
            if self.soc < self.reserve_soc:
                return -min(self.battery_kw_rated, self.battery_kw_rated * 0.5)
            return 0.0
        return 0.0

    def _watchdog_tripped(self, now_mono: float) -> bool:
        if self.watchdog_seconds <= 0:
            return False
        if self.link_down_since is not None and now_mono - self.link_down_since > self.watchdog_seconds:
            return True
        if self.last_setpoint_at is not None and now_mono - self.last_setpoint_at > self.watchdog_seconds:
            return True
        return False

    def step(self) -> None:
        now_local = dt.datetime.now(ZoneInfo(self.timezone_name or "Asia/Taipei"))
        hour = now_local.hour + now_local.minute / 60.0
        elapsed_h = (time.monotonic() - self._last) / 3600.0
        self._last = time.monotonic()

        shape = LOAD_SHAPES.get(self.kind, LOAD_SHAPES["factory"])
        index = int(hour) % 24
        frac = hour - int(hour)
        base = shape[index] * (1 - frac) + shape[(index + 1) % 24] * frac
        load_kw = self.peak_load_kw * base * random.uniform(0.98, 1.02)

        solar = 0.0 if hour < 6 or hour > 18 else max(0.0, math.sin(math.pi * (hour - 6) / 12))
        pv_kw = self.pv_peak_kw * solar * random.uniform(0.92, 1.0)

        with self._lock:
            now_mono = time.monotonic()
            self.mode = "normal"
            if self.emergency_stop:
                wanted_kw = 0.0
            elif self.grid_outage:
                # 孤島：沒有市電，電池獨力供應負載（PV 先抵）；這個切換不需要雲端。
                self.mode = "island"
                wanted_kw = load_kw - pv_kw
            elif self._watchdog_tripped(now_mono):
                self.mode = "watchdog"
                wanted_kw = self._policy_kw(self.offline_policy)
            elif self.setpoint_valid_until is not None and now_mono > self.setpoint_valid_until:
                self.mode = "expired"
                wanted_kw = self._policy_kw(self.on_expiry)
            elif self._seen_setpoint or not self.autonomous:
                wanted_kw = self.setpoint_w / 1000.0
            else:
                # Built-in fallback until the platform sends a setpoint: shave
                # above 80% of peak, soak up PV surplus.
                net = load_kw - pv_kw
                if net > 0.8 * self.peak_load_kw:
                    wanted_kw = net - 0.8 * self.peak_load_kw
                elif net < 0:
                    wanted_kw = net
                else:
                    wanted_kw = 0.0

            battery_kw = max(-self.battery_kw_rated, min(self.battery_kw_rated, wanted_kw))
            # SOC limits: a battery at its floor cannot discharge, at its
            # ceiling cannot charge - the PCS would refuse, so the simulator
            # does too, and the platform sees the setpoint not being met.
            if battery_kw > 0 and self.soc <= self.min_soc:
                battery_kw = 0.0
            if battery_kw < 0 and self.soc >= self.max_soc:
                battery_kw = 0.0
            if self.battery_kwh > 0:
                delta = -(battery_kw * elapsed_h) / self.battery_kwh * 100.0
                self.soc = max(self.min_soc, min(self.max_soc, self.soc + delta))

            grid_kw = load_kw - pv_kw - battery_kw
            if self.grid_outage:
                # 孤島時電表看不到功率；電池供不上的部分就是甩掉的負載。
                grid_kw = 0.0

            self.load_kw, self.pv_kw, self.battery_kw, self.grid_kw = (
                load_kw, pv_kw, battery_kw, grid_kw,
            )
            self.load_kwh += load_kw * elapsed_h
            self.pv_kwh += pv_kw * elapsed_h
            if battery_kw > 0:
                self.discharge_kwh += battery_kw * elapsed_h
            else:
                self.charge_kwh += -battery_kw * elapsed_h
            if grid_kw > 0:
                self.import_kwh += grid_kw * elapsed_h
            else:
                self.export_kwh += -grid_kw * elapsed_h

    # ---- what each role reports --------------------------------------------
    def sample(self, role: str, power_metric: str = "") -> dict:
        """Readings for one device role; ``power_metric`` is the key the
        platform bound for this asset, so the balance adds up on its side."""
        if role == "battery":
            state = "discharge" if self.battery_kw > 0 else ("charge" if self.battery_kw < 0 else "idle")
            return {
                power_metric or "battery_power_w": round(self.battery_kw * 1000, 1),
                "battery_soc": round(self.soc, 2),
                "battery_soh": 98.4,
                "battery_voltage_v": round(random.uniform(780, 820), 1),
                "battery_current_a": round(self.battery_kw * 1000 / 800, 1),
                # Warms with throughput: idle ~28 C, full power ~36 C.
                "battery_temperature_c": round(
                    28 + 8 * abs(self.battery_kw) / max(self.battery_kw_rating(), 1) + random.uniform(-0.5, 0.5), 1
                ),
                "battery_charge_energy_kwh": round(self.charge_kwh, 4),
                "battery_discharge_energy_kwh": round(self.discharge_kwh, 4),
                "pcs_state": state,
                "pcs_temperature_c": round(random.uniform(35, 48), 1),
            }
        if role == "grid_meter":
            outage = self.grid_outage
            return {
                power_metric or "grid_power_w": round(self.grid_kw * 1000, 1),
                "grid_voltage_v": 0.0 if outage else round(random.uniform(215, 228), 1),
                "grid_current_a": round(abs(self.grid_kw) * 1000 / 380, 1),
                "grid_frequency_hz": 0.0 if outage else round(random.uniform(59.95, 60.05), 3),
                "grid_power_factor": round(random.uniform(0.93, 0.99), 3),
                "grid_import_energy_kwh": round(self.import_kwh, 4),
                "grid_export_energy_kwh": round(self.export_kwh, 4),
            }
        if role == "pv":
            return {
                power_metric or "pv_power_w": round(self.pv_kw * 1000, 1),
                "pv_energy_kwh": round(self.pv_kwh, 4),
                "pv_irradiance_wm2": round(1000 * (self.pv_kw / self.pv_peak_kw if self.pv_peak_kw else 0), 1),
                "ambient_temperature_c": round(random.uniform(24, 36), 1),
            }
        if role == "load_meter":
            return {
                power_metric or "load_power_w": round(self.load_kw * 1000, 1),
                "load_energy_kwh": round(self.load_kwh, 4),
            }
        return {
            "uptime_s": int(time.monotonic()),
            "signal_rssi_dbm": random.randint(-85, -55),
            "ambient_temperature_c": round(random.uniform(22, 30), 1),
            "humidity_percent": round(random.uniform(45, 70), 1),
        }


@dataclass
class SimDevice:
    device_id: str
    role: str
    power_metric: str = ""
