"""Backfill realistic historical telemetry, then aggregate it.

``simulate_device`` publishes live data going forward, which leaves every chart
empty until it has been running for hours. This writes straight to the database
instead, so a fresh install has something to look at immediately - and it needs
no MQTT broker or queue.

    python manage.py generate_history --days 3

The generated series obey the same sign conventions as real hardware
(``grid_power_w`` positive on import, ``battery_power_w`` positive on
discharge), so the energy aggregator produces the same numbers it would from a
real site.
"""

from __future__ import annotations

import datetime as dt
import math
import random
import zoneinfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.timeutils import now
from apps.devices.models import ConnectionStatus, Device, DeviceEvent, DeviceStatusEvent
from apps.devices.registry import DeviceRef
from apps.alerts.engine import AlertEngine, RuleCache
from apps.alerts.models import Alert
from apps.ems.aggregator import SiteAggregator
from apps.ems.models import AssetRole, EnergyAsset, EnergyInterval
from apps.telemetry.models import LatestSample, TelemetrySample
from apps.telemetry.repository import SampleRow, insert_samples, upsert_latest

class Command(BaseCommand):
    help = "Generate historical telemetry for the configured energy assets."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=float, default=3.0, help="How far back to generate.")
        parser.add_argument(
            "--interval", type=int, default=60, help="Seconds between samples."
        )
        parser.add_argument("--site", default="", help="Site code; default is every site.")
        parser.add_argument(
            "--organization", default="", help="Organization slug; default is every one."
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing samples in the window first, so re-running is clean.",
        )
        parser.add_argument(
            "--seed", type=int, default=20260819, help="Fix the RNG for reproducible data."
        )
        parser.add_argument(
            "--no-aggregate",
            action="store_true",
            help="Skip building energy intervals afterwards.",
        )
        parser.add_argument(
            "--with-faults",
            action="store_true",
            help=(
                "Inject occasional excursions and device log entries, so the "
                "alert rules have something to catch and the log pages are not "
                "empty. Off by default: generated data is clean unless asked."
            ),
        )
        parser.add_argument(
            "--no-alerts",
            action="store_true",
            help="Skip running the alert rules over the generated readings.",
        )

    def handle(self, *args, **options):
        if options["interval"] < 5:
            raise CommandError("--interval below 5 seconds generates an unhelpful amount of data")

        random.seed(options["seed"])

        end = now().replace(second=0, microsecond=0)
        start = end - dt.timedelta(days=options["days"])

        assets = EnergyAsset.objects.filter(is_active=True).select_related(
            "site", "device", "site__organization"
        )
        if options["site"]:
            assets = assets.filter(site__code=options["site"])
        if options["organization"]:
            assets = assets.filter(organization__slug=options["organization"])

        by_site: dict[str, list[EnergyAsset]] = {}
        for asset in assets:
            by_site.setdefault(str(asset.site_id), []).append(asset)

        if not by_site:
            applied = ", ".join(
                filter(
                    None,
                    [
                        f"site={options['site']}" if options["site"] else "",
                        f"organization={options['organization']}"
                        if options["organization"]
                        else "",
                    ],
                )
            )
            scope = f" matching {applied}" if applied else ""
            raise CommandError(
                f"No energy assets found{scope}. Run `manage.py seed_demo` first, "
                "or bind devices to energy roles under /api/ems/assets."
            )

        total_rows = 0
        total_intervals = 0
        total_alerts = 0
        total_events = 0

        for site_assets in by_site.values():
            site = site_assets[0].site
            self.stdout.write(f"generating {site.name} ({site.code})…")

            if options["clear"]:
                device_ids = [asset.device_id for asset in site_assets]
                deleted, _ = TelemetrySample.objects.filter(
                    device_id__in=device_ids, ts__gte=start, ts__lt=end
                ).delete()
                EnergyInterval.objects.filter(
                    site=site, interval_start__gte=start, interval_start__lt=end
                ).delete()
                LatestSample.objects.filter(device_id__in=device_ids).delete()
                # Also the derived records, or re-running piles up duplicate
                # log entries and leaves alerts from a window that no longer
                # has any data behind it.
                DeviceEvent.objects.filter(
                    device_id__in=device_ids, ts__gte=start, ts__lt=end
                ).delete()
                DeviceStatusEvent.objects.filter(
                    device_id__in=device_ids, ts__gte=start, ts__lt=end
                ).delete()
                Alert.objects.filter(
                    device_id__in=device_ids, started_at__gte=start, started_at__lt=end
                ).delete()
                if deleted:
                    self.stdout.write(f"  cleared {deleted} existing sample(s)")

            rows = self._generate_site(
                site, site_assets, start, end, options["interval"], options["with_faults"]
            )
            written = self._write(rows)
            total_rows += written
            self.stdout.write(f"  wrote {written} sample(s)")

            # The worker normally does these two things. Backfilling writes
            # straight to the tables, so without them every device would look
            # offline and no rule would ever have been evaluated.
            self._mark_devices_seen(site_assets, end)
            if not options["no_alerts"]:
                fired = self._evaluate_alerts(site_assets, rows)
                total_alerts += fired
                if fired:
                    self.stdout.write(f"  raised {fired} alert(s)")

            if options["with_faults"]:
                events = self._write_device_events(site_assets, start, end)
                total_events += events
                self.stdout.write(f"  wrote {events} device log entr(ies)")

            if not options["no_aggregate"]:
                count = SiteAggregator(site).run(start, end)
                total_intervals += count
                self.stdout.write(f"  built {count} energy interval(s)")

        self.stdout.write(
            self.style.SUCCESS(
                f"done: {total_rows} sample(s), {total_intervals} interval(s), "
                f"{total_alerts} alert(s), {total_events} event(s), "
                f"{start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC"
            )
        )

    # ---- generation ------------------------------------------------------
    def _generate_site(
        self,
        site,
        assets: list[EnergyAsset],
        start: dt.datetime,
        end: dt.datetime,
        interval: int,
        with_faults: bool = False,
    ) -> list[SampleRow]:
        try:
            zone = zoneinfo.ZoneInfo(site.timezone_name or "UTC")
        except Exception:  # noqa: BLE001 - a misconfigured site should still generate
            zone = dt.timezone.utc

        from apps.ems.plans import effective_plan

        plan = effective_plan(site)[0]
        by_role = {asset.role: asset for asset in assets}
        battery = by_role.get(AssetRole.BATTERY)
        meter = by_role.get(AssetRole.GRID_METER)
        pv = by_role.get(AssetRole.PV)

        capacity_kwh = (battery.rated_energy_kwh if battery else None) or (
            plan.usable_capacity_kwh if plan else None
        ) or 1000.0
        max_power_kw = (battery.rated_power_kw if battery else None) or (
            plan.max_discharge_kw if plan else None
        ) or 500.0
        shave_target_kw = (
            plan.peak_shaving_target_kw if plan and plan.peak_shaving_target_kw else 250.0
        )
        contract_kw = (plan.contract_capacity_kw if plan else None) or shave_target_kw * 1.8
        max_charge_kw = (plan.max_charge_kw if plan else None) or max_power_kw
        min_soc = plan.min_soc_percent if plan else 10.0
        max_soc = plan.max_soc_percent if plan else 95.0

        pv_peak_kw = (pv.rated_power_kw if pv else None) or 400.0

        rows: list[SampleRow] = []
        soc = 55.0
        cumulative = {
            "grid_import": 0.0,
            "grid_export": 0.0,
            "pv": 0.0,
            "charge": 0.0,
            "discharge": 0.0,
        }
        hours = interval / 3600.0

        # Long enough to outlast the rule's for_duration_seconds (60s) with room
        # to spare, short enough to read as a live excursion rather than a fault
        # the site has been ignoring for hours.
        fault_tail_start = end - dt.timedelta(minutes=25)

        cursor = start
        while cursor < end:
            local = cursor.astimezone(zone)

            pv_kw = _solar_kw(local, pv_peak_kw)
            load_kw = _load_kw(local)
            net_kw = load_kw - pv_kw

            # Peak shaving, PV-surplus charging, and an off-peak top-up.
            # Without the last one the battery would drain to its floor on day
            # one and sit there, which is neither realistic nor interesting.
            off_peak = local.hour >= 23 or local.hour < 7
            if net_kw > shave_target_kw and soc > min_soc:
                battery_kw = min(net_kw - shave_target_kw, max_power_kw)
            elif net_kw < 0 and soc < max_soc:
                battery_kw = max(net_kw, -max_power_kw)
            elif off_peak and soc < max_soc:
                # Charge into the headroom the contract leaves, keeping a 5%
                # margin so the top-up does not itself set a new demand peak.
                headroom = max(0.0, contract_kw * 0.95 - net_kw)
                battery_kw = -min(max_charge_kw, headroom)
            else:
                battery_kw = 0.0

            # SOC integrates the actual energy moved, then clamps the power if
            # the limit was hit mid-step - so the series stays self-consistent.
            delta_soc = -(battery_kw * hours) / capacity_kwh * 100.0
            new_soc = soc + delta_soc
            if new_soc < min_soc:
                battery_kw *= (soc - min_soc) / max(soc - new_soc, 1e-9)
                new_soc = min_soc
            elif new_soc > max_soc:
                battery_kw *= (max_soc - soc) / max(new_soc - soc, 1e-9)
                new_soc = max_soc
            soc = new_soc

            grid_kw = load_kw - pv_kw - battery_kw

            cumulative["pv"] += pv_kw * hours
            if grid_kw >= 0:
                cumulative["grid_import"] += grid_kw * hours
            else:
                cumulative["grid_export"] += -grid_kw * hours
            if battery_kw >= 0:
                cumulative["discharge"] += battery_kw * hours
            else:
                cumulative["charge"] += -battery_kw * hours

            # A deterministic excursion window each day, so demos exercise the
            # alert rules instead of showing a permanently empty alerts page.
            # The tail window runs right up to "now" so one alert is still
            # firing when the console opens - past alerts all auto-resolve, and
            # an alerts page filtered to "open" would otherwise look empty.
            if not with_faults:
                fault = None
            elif cursor >= fault_tail_start:
                fault = "battery_temp"
            else:
                fault = _in_fault_window(local)

            if meter:
                _add(rows, meter, "grid_power_w", cursor, grid_kw * 1000)
                _add(rows, meter, "load_power_w", cursor, load_kw * 1000)
                _add(
                    rows,
                    meter,
                    "grid_voltage_v",
                    cursor,
                    random.uniform(188, 194) if fault == "voltage_sag" else random.uniform(216, 226),
                )
                _add(rows, meter, "grid_frequency_hz", cursor, random.uniform(59.96, 60.04))
                _add(
                    rows, meter, "grid_import_energy_kwh", cursor, cumulative["grid_import"]
                )
                _add(
                    rows, meter, "grid_export_energy_kwh", cursor, cumulative["grid_export"]
                )
            if pv:
                _add(rows, pv, "pv_power_w", cursor, pv_kw * 1000)
                _add(rows, pv, "pv_energy_kwh", cursor, cumulative["pv"])
                _add(rows, pv, "pv_irradiance_wm2", cursor, pv_kw / pv_peak_kw * 1000)
            if battery:
                _add(rows, battery, "battery_power_w", cursor, battery_kw * 1000)
                _add(rows, battery, "battery_soc", cursor, soc)
                _add(rows, battery, "battery_soh", cursor, 98.4 - cursor.timestamp() % 3 * 0.01)
                _add(rows, battery, "battery_voltage_v", cursor, random.uniform(780, 820))
                _add(
                    rows,
                    battery,
                    "battery_current_a",
                    cursor,
                    battery_kw * 1000 / 800 if battery_kw else 0.0,
                )
                _add(
                    rows,
                    battery,
                    "battery_temperature_c",
                    cursor,
                    (52.0 if fault == "battery_temp" else 26.0)
                    + abs(battery_kw) / max_power_kw * 8
                    + random.uniform(-0.5, 0.5),
                )
                _add(
                    rows,
                    battery,
                    "battery_charge_energy_kwh",
                    cursor,
                    cumulative["charge"],
                )
                _add(
                    rows,
                    battery,
                    "battery_discharge_energy_kwh",
                    cursor,
                    cumulative["discharge"],
                )

            cursor += dt.timedelta(seconds=interval)

        return rows

    def _write(self, rows: list[SampleRow]) -> int:
        written = 0
        # Chunked so SQLite never holds one enormous transaction open.
        for index in range(0, len(rows), 5000):
            chunk = rows[index : index + 5000]
            with transaction.atomic():
                written += insert_samples(chunk)
        if rows:
            upsert_latest(rows)
        return written


    # ---- worker-equivalent side effects ----------------------------------
    def _mark_devices_seen(self, assets: list[EnergyAsset], end: dt.datetime) -> None:
        """Reflect that these devices reported right up to the window's end."""
        device_ids = {asset.device_id for asset in assets}
        Device.objects.filter(id__in=device_ids).update(
            last_seen_at=end,
            last_telemetry_at=end,
            status=ConnectionStatus.ONLINE,
            status_changed_at=end,
        )
        # Give the connection-history tab something real to show.
        DeviceStatusEvent.objects.bulk_create(
            [
                DeviceStatusEvent(
                    device_id=device_id,
                    status=ConnectionStatus.ONLINE,
                    reason="backfill",
                    ts=end,
                )
                for device_id in device_ids
            ]
        )

    def _evaluate_alerts(self, assets: list[EnergyAsset], rows: list[SampleRow]) -> int:
        """Replay the rule engine over the generated readings, in order."""
        refs: dict[object, DeviceRef] = {}
        for asset in assets:
            device = asset.device
            refs[device.id] = DeviceRef(
                pk=device.id,
                device_id=device.device_id,
                edge_node_id=device.edge_node_id,
                organization_id=device.organization_id,
                site_id=device.site_id,
                device_type_id=device.device_type_id,
                recording_policy_id=device.recording_policy_id,
                is_enabled=device.is_enabled,
            )

        engine = AlertEngine(rule_cache=RuleCache(ttl_seconds=3600))
        engine.rules.refresh(force=True)

        fired = 0
        for row in rows:
            if row.value is None:
                continue
            ref = refs.get(row.device_id)
            if ref is None:
                continue
            if not engine.rules.for_metric(ref.organization_id, row.metric_key):
                continue
            fired += len(
                engine.evaluate(ref, row.metric_key, row.value, row.ts, device_name=ref.device_id)
            )
        return fired

    def _write_device_events(
        self, assets: list[EnergyAsset], start: dt.datetime, end: dt.datetime
    ) -> int:
        """A handful of plausible operation-log entries per device."""
        templates = [
            ("info", "", "Scheduled self-test completed"),
            ("notice", "N0102", "Firmware configuration reloaded"),
            ("warning", "E0231", "Cooling fan speed below threshold"),
            ("info", "", "Clock synchronised with NTP"),
            ("error", "E0500", "Insulation resistance below limit"),
        ]
        span = (end - start).total_seconds()
        events = []
        for index, asset in enumerate(assets):
            for offset, (level, code, message) in enumerate(templates):
                ts = start + dt.timedelta(
                    seconds=span * ((offset + 1) / (len(templates) + 1))
                    + index * 900
                )
                if ts >= end:
                    continue
                events.append(
                    DeviceEvent(
                        organization_id=asset.organization_id,
                        device_id=asset.device_id,
                        ts=ts,
                        level=level,
                        code=code,
                        message=message,
                    )
                )
        DeviceEvent.objects.bulk_create(events)
        return len(events)


def _add(rows: list[SampleRow], asset: EnergyAsset, metric: str, ts: dt.datetime, value: float):
    rows.append(
        SampleRow(
            organization_id=asset.organization_id,
            device_id=asset.device_id,
            metric_key=metric,
            ts=ts,
            value=round(value, 3),
        )
    )


def _in_fault_window(local: dt.datetime) -> str | None:
    """Deterministic daily excursion windows, keyed off the calendar day."""
    day = local.toordinal()
    if day % 2 == 0 and 13 <= local.hour < 14:
        return "battery_temp"
    if day % 3 == 0 and 19 <= local.hour < 20 and local.minute < 20:
        return "voltage_sag"
    return None


def _solar_kw(local: dt.datetime, peak_kw: float) -> float:
    """Bell curve between 06:00 and 18:00, dulled by a per-day weather factor."""
    hour = local.hour + local.minute / 60.0
    if hour < 6 or hour > 18:
        return 0.0
    shape = math.sin(math.pi * (hour - 6) / 12)
    # Deterministic per-day cloudiness so a day looks coherent, not noisy.
    weather = 0.55 + 0.45 * abs(math.sin(local.toordinal() * 1.7))
    return max(0.0, peak_kw * shape * weather * random.uniform(0.96, 1.0))


def _load_kw(local: dt.datetime) -> float:
    """Office-style profile: a working-hours plateau with a weekend dip."""
    hour = local.hour + local.minute / 60.0
    weekend = local.weekday() >= 5

    if 8 <= hour < 18:
        base = 180.0 if weekend else 420.0
    elif 6 <= hour < 8 or 18 <= hour < 21:
        base = 150.0 if weekend else 260.0
    else:
        base = 110.0 if weekend else 140.0

    # A midday bump for cooling, plus small random variation.
    if 12 <= hour < 15 and not weekend:
        base *= 1.15
    return base * random.uniform(0.93, 1.07)
