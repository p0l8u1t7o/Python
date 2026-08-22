"""Publish synthetic telemetry as a Sparkplug B edge node.

Lets the whole chain - broker, ingestor, queue, worker, API - be exercised
before the device firmware exists, and doubles as a reference implementation of
the wire format described in ``docs/device-protocol.md``.

It performs the full sequence a real node must: register NDEATH as the will,
NBIRTH, DBIRTH with the alias table, DDATA by alias, answer DCMD, and publish
its own death on a planned exit.

Example::

    python manage.py simulate_device --device ZQS-BESS-0001 --profile battery \\
        --interval 5 --duration 600
"""

from __future__ import annotations

import math
import random
import signal
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.devices.models import Device
from services.mqtt.client import MqttClient
from services.sparkplug import payload as sp
from services.sparkplug import profile as sp_profile
from services.sparkplug import topics
from services.sparkplug.datatypes import DataType
from services.sparkplug.node import EdgeNodeClient, MetricSpec

PROFILES = ("battery", "meter", "pv", "fuelcell", "controller")

#: Units published alongside each reading in the birth. This is what makes the
#: platform's plug-and-play registration work: a metric nobody has configured
#: arrives with enough to build a catalogue entry, so its chart comes up with
#: an axis label instead of a bare key.
METRIC_UNITS = {
    "battery_power_w": "W",
    "battery_soc": "%",
    "battery_soh": "%",
    "battery_voltage_v": "V",
    "battery_current_a": "A",
    "battery_temperature_c": "degC",
    "battery_charge_energy_kwh": "kWh",
    "battery_discharge_energy_kwh": "kWh",
    "pcs_temperature_c": "degC",
    "grid_power_w": "W",
    "grid_voltage_v": "V",
    "grid_current_a": "A",
    "grid_frequency_hz": "Hz",
    "grid_import_energy_kwh": "kWh",
    "grid_export_energy_kwh": "kWh",
    "load_power_w": "W",
    "pv_power_w": "W",
    "pv_energy_kwh": "kWh",
    "pv_irradiance_wm2": "W/m2",
    "ambient_temperature_c": "degC",
    "humidity_percent": "%",
    "uptime_s": "s",
    "signal_rssi_dbm": "dBm",
    # Deliberately not in the built-in catalogue. The fuel cell profile exists
    # partly to exercise plug-and-play registration: these arrive with a unit
    # and a datatype and nothing else, and the console has to end up with
    # labelled charts anyway.
    "stack_power_w": "W",
    "stack_voltage_v": "V",
    "stack_current_a": "A",
    "stack_temperature_c": "degC",
    "stack_energy_kwh": "kWh",
    "hydrogen_flow_slpm": "slpm",
    "hydrogen_pressure_bar": "bar",
}


#: What each profile declares about itself in its DBIRTH. Under Sparkplug the
#: birth *is* the declaration - there is no separate attributes object, because
#: a birth is already defined as everything the device offers.
DECLARATIONS = {
    "battery": {
        "Properties/Category": "battery",
        "Properties/Manufacturer": "ZQS Simulator",
        "Properties/Model": "SIM-BESS-500",
        "Capabilities/Can Charge": True,
        "Capabilities/Can Discharge": True,
        "Capabilities/Is Dispatchable": True,
        "Ratings/Rated Power kW": 500.0,
        "Ratings/Rated Energy kWh": 1000.0,
        "Ratings/Min SOC Percent": 10.0,
        "Ratings/Max SOC Percent": 98.0,
    },
    "meter": {
        "Properties/Category": "meter",
        "Properties/Manufacturer": "ZQS Simulator",
        "Properties/Model": "SIM-METER-3P",
    },
    "pv": {
        "Properties/Category": "generation",
        "Properties/Manufacturer": "ZQS Simulator",
        "Properties/Model": "SIM-PV-400",
        "Capabilities/Can Export": True,
        "Ratings/Rated Power kW": 400.0,
    },
    "fuelcell": {
        "Properties/Category": "generation",
        "Properties/Manufacturer": "ZQS Simulator",
        "Properties/Model": "SIM-FC-100",
        "Capabilities/Can Export": True,
        "Ratings/Rated Power kW": 100.0,
    },
    "controller": {
        "Properties/Category": "controller",
        "Properties/Manufacturer": "ZQS Simulator",
        "Properties/Model": "SIM-EMS",
    },
}


def _birth_metrics(profile_name: str, sample: dict) -> list[MetricSpec]:
    """Every metric this device offers, which is what a DBIRTH must list.

    Values are the current ones: a birth is a full snapshot, not a schema, so a
    host that has just connected already has something to show.
    """
    specs = [
        MetricSpec("Properties/Firmware", "sim-2.0.0", DataType.String),
        MetricSpec("Properties/Hardware", "simulator", DataType.String),
        MetricSpec("Properties/Schema Version", sp_profile.PROFILE_VERSION, DataType.Int32),
    ]
    for name, value in DECLARATIONS.get(profile_name, {}).items():
        specs.append(MetricSpec(name, value))
    for key, value in sample.items():
        unit = METRIC_UNITS.get(key, "")
        specs.append(
            MetricSpec(
                key,
                value,
                DataType.String if isinstance(value, str) else DataType.Double,
                properties={"unit": unit} if unit else None,
            )
        )
    return specs


class Command(BaseCommand):
    help = "Publish synthetic device telemetry to the MQTT broker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--device",
            required=True,
            action="append",
            help=(
                "device_id to publish as, optionally 'id=profile'. Repeat to "
                "serve several devices from one edge node, which is what a "
                "real gateway does - one connection, one seq counter."
            ),
        )
        parser.add_argument(
            "--profile",
            default="battery",
            choices=PROFILES,
            help="Default profile for devices given without '=profile'.",
        )
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
        parser.add_argument(
            "--group",
            default="",
            help="Sparkplug group_id. Defaults to the registered device's.",
        )
        parser.add_argument(
            "--node",
            default="",
            help="Sparkplug edge_node_id. Defaults to the registered device's.",
        )

    def handle(self, *args, **options):
        wanted = _parse_devices(options["device"], options["profile"])
        registered = {
            device.device_id: device
            for device in Device.objects.select_related("edge_node").filter(
                device_id__in=list(wanted), deleted_at__isnull=True
            )
        }
        missing = [d for d in wanted if d not in registered]
        if missing and not options["skip_registry_check"]:
            raise CommandError(
                f"Not registered: {', '.join(missing)}. Register them first, or "
                "pass --skip-registry-check to publish anyway."
            )

        nodes = {
            device.edge_node.group_id + "/" + device.edge_node.node_id
            for device in registered.values()
        }
        if len(nodes) > 1 and not (options["group"] and options["node"]):
            # One process is one MQTT session is one edge node. Publishing for
            # two nodes down one connection would give them a shared seq
            # counter, and the host would see permanent gaps on both.
            raise CommandError(
                "These devices report through different edge nodes "
                f"({', '.join(sorted(nodes))}). Run one simulator per node."
            )

        sample_device = next(iter(registered.values()), None)
        group_id = options["group"] or (
            sample_device.edge_node.group_id if sample_device else ""
        )
        node_id = options["node"] or (
            sample_device.edge_node.node_id if sample_device else next(iter(wanted))
        )
        if not group_id:
            raise CommandError(
                "Cannot determine the Sparkplug group. Register the device, or "
                "pass --group explicitly."
            )

        if options["seed"]:
            random.seed(options["seed"])

        states = {device_id: _State() for device_id in wanted}

        client = MqttClient(client_suffix=f"sim-{node_id}", clean_session=True)
        node = EdgeNodeClient(client, group_id, node_id)
        node.next_bd_seq()

        # Registered before connecting: a will set afterwards is a will the
        # broker never received, and then an abrupt exit leaves this node
        # showing as online until the host's timeout sweep catches it.
        will_qos, will_retain = topics.publish_options(topics.MessageType.NDEATH)
        client.set_last_will(
            topics.build(group_id, topics.MessageType.NDEATH, node_id),
            node.death_payload(),
            qos=will_qos,
            retain=will_retain,
        )

        stopping = {"value": False}

        def stop(*_args):
            stopping["value"] = True

        def on_command(topic: str, raw: bytes, qos: int, retain: bool) -> None:
            self._handle_command(node, wanted, topic, raw)

        client.on_message_callback = on_command
        client.subscriptions = node.command_subscriptions()
        client.connect()

        def announce() -> None:
            node.publish_nbirth()
            for device_id, profile_name in wanted.items():
                node.publish_dbirth(
                    device_id,
                    _birth_metrics(profile_name, _sample(profile_name, states[device_id])),
                )

        announce()
        self._announce = announce

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

        started = time.monotonic()
        published = 0

        listing = ", ".join(f"{d} ({p})" for d, p in wanted.items())
        self.stdout.write(
            f"publishing as {group_id}/{node_id} -> {listing} "
            f"every {options['interval']}s (Ctrl-C to stop)"
        )

        try:
            while not stopping["value"]:
                for device_id, profile_name in wanted.items():
                    node.publish_ddata(
                        device_id, _sample(profile_name, states[device_id])
                    )
                    published += 1

                if options["duration"] and (time.monotonic() - started) >= options["duration"]:
                    break
                time.sleep(options["interval"])
        finally:
            for device_id in wanted:
                node.publish_ddeath(device_id)
            node.publish_ndeath()
            client.disconnect()

        self.stdout.write(self.style.SUCCESS(f"published {published} message(s)"))

    def _handle_command(self, node: EdgeNodeClient, devices: dict, topic: str, raw: bytes):
        """Answer NCMD and DCMD the way a real device must.

        Two obligations: honour a rebirth request, and acknowledge a command.
        Ignoring either leaves the host asking again forever.
        """
        parsed = topics.parse(topic)
        if parsed is None:
            return
        try:
            view = sp.decode(raw)
        except sp.PayloadError:
            return

        names = {metric.name: metric.value for metric in view.metrics}

        if names.get(sp.NODE_REBIRTH_METRIC) or names.get(sp.DEVICE_REBIRTH_METRIC):
            self.stdout.write("rebirth requested; re-announcing")
            announce = getattr(self, "_announce", None)
            if announce is not None:
                announce()
            return

        command_id = names.get(sp_profile.COMMAND_ID)
        if not command_id or parsed.device_id not in devices:
            return
        command_name = names.get(sp_profile.COMMAND_NAME, "")
        self.stdout.write(f"command {command_name} ({command_id})")
        node.ack(parsed.device_id, str(command_id), "accepted")
        node.ack(parsed.device_id, str(command_id), "succeeded", message="simulated")


def _parse_devices(entries: list[str], default_profile: str) -> dict[str, str]:
    """``["BESS-1=battery", "METER-1"]`` -> ``{"BESS-1": "battery", ...}``."""
    parsed: dict[str, str] = {}
    for entry in entries:
        device_id, _, profile_name = entry.partition("=")
        device_id = device_id.strip()
        profile_name = (profile_name or default_profile).strip()
        if profile_name not in PROFILES:
            raise CommandError(
                f"Unknown profile {profile_name!r} for {device_id}; "
                f"expected one of {', '.join(PROFILES)}"
            )
        parsed[device_id] = profile_name
    return parsed


class _State:
    """Carries values between samples so the series looks continuous."""

    def __init__(self) -> None:
        self.soc = 55.0
        self.charge_kwh = 0.0
        self.discharge_kwh = 0.0
        self.import_kwh = 0.0
        self.export_kwh = 0.0
        self.pv_kwh = 0.0
        self.fuelcell_kwh = 0.0
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

    if profile == "fuelcell":
        # Runs flat out whenever the site is importing, which is roughly how a
        # fuel cell is actually operated: it is a baseload machine, not a
        # follower.
        stack_kw = 100.0 if grid_kw > 0 else 20.0
        state.fuelcell_kwh += stack_kw * hours
        return {
            "stack_power_w": round(stack_kw * 1000, 1),
            "stack_voltage_v": round(random.uniform(380, 420), 1),
            "stack_current_a": round(stack_kw * 1000 / 400, 1),
            "stack_temperature_c": round(random.uniform(58, 72), 1),
            "stack_energy_kwh": round(state.fuelcell_kwh, 4),
            "hydrogen_flow_slpm": round(stack_kw * 0.72, 2),
            "hydrogen_pressure_bar": round(random.uniform(4.5, 6.5), 2),
        }

    return {
        "uptime_s": int(time.monotonic()),
        "signal_rssi_dbm": random.randint(-85, -55),
        "ambient_temperature_c": round(random.uniform(22, 30), 1),
        "humidity_percent": round(random.uniform(45, 70), 1),
    }
