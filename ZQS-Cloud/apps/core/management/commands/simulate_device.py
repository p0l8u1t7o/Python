"""Publish synthetic telemetry over MQTT.

Lets the whole chain - broker, ingestor, queue, worker, API - be exercised
before the LabVIEW device code exists, and doubles as a reference for the wire
format described in ``docs/device-protocol.md``.

Example::

    python manage.py simulate_device --device ZQS-BESS-0001 --profile battery \\
        --interval 5 --duration 600
"""

from __future__ import annotations

import math
import random
import signal
import time

import orjson
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.devices.models import Device
from services.mqtt import topics
from services.mqtt.client import MqttClient

PROFILES = ("battery", "meter", "pv", "controller")


class Command(BaseCommand):
    help = "Publish synthetic device telemetry to the MQTT broker."

    def add_arguments(self, parser):
        parser.add_argument("--device", required=True, help="device_id to publish as.")
        parser.add_argument("--profile", default="battery", choices=PROFILES)
        parser.add_argument("--interval", type=float, default=5.0, help="Seconds.")
        parser.add_argument(
            "--duration", type=float, default=0.0, help="Seconds; 0 runs until Ctrl-C."
        )
        parser.add_argument(
            "--seed", type=int, default=0, help="Fix the RNG for reproducible runs."
        )
        parser.add_argument(
            "--skip-registry-check",
            action="store_true",
            help="Publish even if the device is not registered.",
        )

    def handle(self, *args, **options):
        device_id = options["device"]
        if not options["skip_registry_check"]:
            if not Device.objects.filter(device_id=device_id).exists():
                raise CommandError(
                    f"Device '{device_id}' is not registered. Register it first, or "
                    "pass --skip-registry-check to publish anyway."
                )

        if options["seed"]:
            random.seed(options["seed"])

        client = MqttClient(client_suffix=f"sim-{device_id}", clean_session=True)
        # Announce the last will so an abrupt exit shows up as a real outage.
        client.set_last_will(
            topics.device_topic(device_id, topics.STATUS),
            orjson.dumps({"status": "offline", "reason": "lwt"}),
        )
        client.connect()

        client.publish(
            topics.device_topic(device_id, topics.STATUS),
            orjson.dumps(
                {
                    "status": "online",
                    "ts": int(time.time() * 1000),
                    "firmware": "sim-1.0.0",
                    "hardware": "simulator",
                }
            ),
            retain=True,
        )

        stopping = {"value": False}

        def stop(*_args):
            stopping["value"] = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

        state = _State()
        started = time.monotonic()
        published = 0

        self.stdout.write(
            f"publishing {options['profile']} telemetry as {device_id} "
            f"every {options['interval']}s (Ctrl-C to stop)"
        )

        try:
            while not stopping["value"]:
                metrics = _sample(options["profile"], state)
                client.publish(
                    topics.device_topic(device_id, topics.TELEMETRY),
                    orjson.dumps(
                        {
                            "ts": int(time.time() * 1000),
                            "seq": published,
                            "metrics": metrics,
                        }
                    ),
                )
                published += 1

                if options["duration"] and (time.monotonic() - started) >= options["duration"]:
                    break
                time.sleep(options["interval"])
        finally:
            client.publish(
                topics.device_topic(device_id, topics.STATUS),
                orjson.dumps({"status": "offline", "reason": "shutdown"}),
                retain=True,
            )
            client.disconnect()

        self.stdout.write(self.style.SUCCESS(f"published {published} message(s)"))


class _State:
    """Carries values between samples so the series looks continuous."""

    def __init__(self) -> None:
        self.soc = 55.0
        self.charge_kwh = 0.0
        self.discharge_kwh = 0.0
        self.import_kwh = 0.0
        self.export_kwh = 0.0
        self.pv_kwh = 0.0
        self.last = time.monotonic()

    def elapsed_hours(self) -> float:
        current = time.monotonic()
        hours = (current - self.last) / 3600.0
        self.last = current
        return hours


def _solar_factor() -> float:
    """Bell curve peaking at local solar noon, zero at night."""
    hour = timezone.localtime().hour + timezone.localtime().minute / 60.0
    if hour < 6 or hour > 18:
        return 0.0
    return max(0.0, math.sin(math.pi * (hour - 6) / 12))


def _load_kw() -> float:
    hour = timezone.localtime().hour
    base = 300.0 if 8 <= hour < 18 else 120.0
    return base * random.uniform(0.85, 1.15)


def _sample(profile: str, state: _State) -> dict:
    hours = state.elapsed_hours()
    pv_kw = 400.0 * _solar_factor() * random.uniform(0.9, 1.0)
    load_kw = _load_kw()

    # Simple peak-shaving behaviour: discharge above 250 kW net, charge on surplus.
    net_kw = load_kw - pv_kw
    if net_kw > 250 and state.soc > 15:
        battery_kw = min(net_kw - 250, 500.0)
    elif net_kw < 0 and state.soc < 95:
        battery_kw = max(net_kw, -500.0)
    else:
        battery_kw = 0.0

    if battery_kw > 0:
        state.discharge_kwh += battery_kw * hours
        state.soc = max(10.0, state.soc - battery_kw * hours / 10.0)
    elif battery_kw < 0:
        state.charge_kwh += -battery_kw * hours
        state.soc = min(98.0, state.soc + -battery_kw * hours / 10.0)

    grid_kw = load_kw - pv_kw - battery_kw
    if grid_kw > 0:
        state.import_kwh += grid_kw * hours
    else:
        state.export_kwh += -grid_kw * hours
    state.pv_kwh += pv_kw * hours

    if profile == "battery":
        return {
            "battery_power_w": round(battery_kw * 1000, 1),
            "battery_soc": round(state.soc, 2),
            "battery_soh": 98.4,
            "battery_voltage_v": round(random.uniform(780, 820), 1),
            "battery_current_a": round(battery_kw * 1000 / 800, 1),
            "battery_temperature_c": round(random.uniform(26, 34), 1),
            "battery_charge_energy_kwh": round(state.charge_kwh, 4),
            "battery_discharge_energy_kwh": round(state.discharge_kwh, 4),
            "pcs_state": "discharge" if battery_kw > 0 else ("charge" if battery_kw < 0 else "idle"),
            "pcs_temperature_c": round(random.uniform(35, 48), 1),
        }

    if profile == "meter":
        return {
            "grid_power_w": round(grid_kw * 1000, 1),
            "grid_voltage_v": round(random.uniform(215, 228), 1),
            "grid_current_a": round(abs(grid_kw) * 1000 / 380, 1),
            "grid_frequency_hz": round(random.uniform(59.95, 60.05), 3),
            "grid_power_factor": round(random.uniform(0.93, 0.99), 3),
            "grid_import_energy_kwh": round(state.import_kwh, 4),
            "grid_export_energy_kwh": round(state.export_kwh, 4),
            "load_power_w": round(load_kw * 1000, 1),
        }

    if profile == "pv":
        return {
            "pv_power_w": round(pv_kw * 1000, 1),
            "pv_energy_kwh": round(state.pv_kwh, 4),
            "pv_irradiance_wm2": round(1000 * _solar_factor(), 1),
            "ambient_temperature_c": round(random.uniform(24, 36), 1),
        }

    return {
        "uptime_s": int(time.monotonic()),
        "signal_rssi_dbm": random.randint(-85, -55),
        "ambient_temperature_c": round(random.uniform(22, 30), 1),
        "humidity_percent": round(random.uniform(45, 70), 1),
    }
