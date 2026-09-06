"""Self-check for support: the first question on any call is "what does doctor say?".

    manage.py doctor

Prints the version, disk headroom, database and archive size, listening ports, connection and
capture-client health, and the optional deep-learning stack — everything you would otherwise ask a
customer to look up one at a time. Exit code is 1 when something needs attention.
"""

from __future__ import annotations

import json
import shutil
import socket
import sys
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

OK, WARN, BAD = "ok", "warn", "bad"


class Command(BaseCommand):
    help = "Check the installation and print a support-friendly summary."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Machine-readable output")

    def handle(self, *args, **options):
        checks: list[tuple[str, str, str]] = []

        def add(name: str, state: str, detail: str) -> None:
            checks.append((name, state, detail))

        cfg = settings.VISION
        from apps.vision import __version__ as version  # noqa: PLC0415 — 版本在套件層，避免載入順序問題

        add("version", OK, version)
        add("python", OK, f"{sys.version.split()[0]} at {sys.executable}")
        add("layout", OK, f"VS_HOME {settings.VS_HOME}; app {settings.BASE_DIR}")

        # 正式環境該改掉的預設值：安裝程式會產生，手動安裝的人常忘記
        add("settings: DEBUG", WARN if settings.DEBUG else OK, "DEBUG is on (set DEBUG=0 in .env for production)" if settings.DEBUG else "off")
        default_key = settings.SECRET_KEY in ("dev-only-secret-change-me", "change-me", "")
        add("settings: SECRET_KEY", BAD if default_key else OK, "default value (set a random SECRET_KEY in .env)" if default_key else "set")
        hosts = getattr(settings, "ALLOWED_HOSTS", [])
        add("settings: ALLOWED_HOSTS", WARN if "*" in hosts and not settings.DEBUG else OK, ", ".join(hosts) or "(empty)")
        add("settings: API key", OK if cfg.get("API_KEY") else WARN, "set" if cfg.get("API_KEY") else "empty (integrators and the capture client are not authenticated)")
        add("settings: TCP auth", OK if cfg.get("TCP_AUTH") else WARN, "set" if cfg.get("TCP_AUTH") else "empty (any host that can reach the TCP port can run and lock; rely on the firewall)")

        db = Path(settings.DATABASES["default"]["NAME"])
        db_mb = db.stat().st_size / (1 << 20) if db.exists() else 0
        add("database", OK if db.exists() else BAD, f"{db} ({db_mb:.1f} MB)")

        data_dir = Path(settings.DATA_DIR)
        try:
            usage = shutil.disk_usage(data_dir)
            free_gb = usage.free / (1 << 30)
            add("disk", OK if free_gb > 10 else WARN if free_gb > 2 else BAD, f"{free_gb:.1f} GB free on {data_dir.drive or data_dir}")
        except OSError as exc:
            add("disk", BAD, str(exc))

        from apps.vision import archive

        stats = archive.stats()
        cap_gb = float(cfg.get("ARCHIVE_MAX_GB", 20))
        used_gb = stats["bytes"] / (1 << 30)
        add("image archive", WARN if cap_gb and used_gb > cap_gb * 0.9 else OK,
            f"{stats['files']} files, {used_gb:.2f} / {cap_gb:g} GB in {stats['dir']}")

        from apps.vision.models import FlowRun, FlowRunHourly, MeasurementLog
        from apps.vision.tools import accel

        acc = accel.status()
        add("acceleration", OK, f"{acc['backend']}" + (f" ({acc['device']})" if acc['device'] else "") + f", VISION_ACCEL={acc['mode']}" + (f": {acc['reason']}" if acc['backend'] == 'cpu' and acc['mode'] != 'cpu' else ""))

        from apps.vision import retention

        keep = retention.effective()
        add("history", OK, f"{FlowRun.objects.count()} run rows (kept {keep['run_days']}d), {FlowRunHourly.objects.count()} hourly rows (kept forever)")
        add("measurements", OK, f"{MeasurementLog.objects.count()} SPC rows ({'on' if cfg.get('MEASUREMENT_LOG', True) else 'off'}, kept {keep['measurement_days']}d)")

        state = retention.status()
        last = state["last_sweep_at"] or "never"
        add("retention", OK if keep["enabled"] else WARN,
            f"runs {keep['run_days']}d, audit {keep['audit_days']}d, pictures {keep['archive_days']}d/{keep['archive_max_gb']:g} GB, "
            f"window {keep['window_hour']:02d}:00, last clean-up {last}" + ("" if keep["enabled"] else " (automatic clean-up is off)"))
        backups = state["usage"]
        add("backups", OK, f"{backups['backup_files']} files, {backups['backup_bytes'] / (1 << 20):.1f} MB (kept {keep['backup_keep']})")

        http_port = int(cfg.get("HTTP_PORT") or 8000)
        served = _healthz(http_port)
        if served is None:
            add(f"HTTP port {http_port}", WARN, "not answering /healthz (is manage.py serve running?)")
        elif served.get("version") != version:
            add(f"HTTP port {http_port}", WARN, f"answering with version {served.get('version')} (this install is {version}); restart the service")
        else:
            add(f"HTTP port {http_port}", OK, "answering /healthz")
        for label, port in (("TCP commands", cfg.get("TCP_PORT")), ("capture", cfg.get("CAPTURE_PORT"))):
            listening = _listening(int(port))
            add(f"{label} port {port}", OK if listening else WARN, "listening" if listening else "not listening (is manage.py serve running?)")

        dist = Path(settings.FRONTEND_DIST) / "index.html"
        add("web interface", OK if dist.exists() else BAD, str(dist) if dist.exists() else f"{dist} missing: build the front end (npm run build) or install a release package")

        from apps.core import plugins as folder_plugins

        pdir = folder_plugins.plugin_dir()
        broken_plugins = [it["name"] for it in folder_plugins.inventory() if it["status"] == "error"]
        add("plugins dir", BAD if not pdir.is_dir() else WARN if broken_plugins else OK,
            f"{pdir} missing" if not pdir.is_dir() else f"{pdir}; {len(folder_plugins.inventory())} files" + (f", failing: {', '.join(broken_plugins)}" if broken_plugins else ""))

        try:
            from apps.vision.capture import build as capture_build

            client = capture_build.info(fresh=True)
            add("capture client build", OK if client.get("available") else WARN,
                f"{client.get('version')} in {capture_build.download_dir()}" if client.get("available") else f"no package in {capture_build.download_dir()} (the download button is disabled)")
        except Exception as exc:  # noqa: BLE001
            add("capture client build", WARN, str(exc)[:120])

        try:
            from apps.comm.models import Connection
            from apps.comm.writers import connection_info

            broken = [c.name for c in Connection.objects.filter(is_enabled=True) if (connection_info(c) or {}).get("error")]
            add("connections", WARN if broken else OK, f"{len(broken)} with errors: {', '.join(broken)}" if broken else "no errors")
        except Exception as exc:  # noqa: BLE001
            add("connections", WARN, str(exc)[:120])

        try:
            from apps.vision.dl.devices import info as dl_info

            dl = dl_info()
            gpus = ", ".join(g.get("name", "?") for g in dl.get("gpus") or []) or "CPU only"
            add("deep learning", OK, f"{gpus}; providers {', '.join(dl.get('providers') or []) or 'none'}")
        except Exception:  # noqa: BLE001 — DL 是選配
            add("deep learning", OK, "not installed (optional)")

        from django.contrib.auth.models import User

        admins = User.objects.filter(is_staff=True, is_active=True).count()
        add("accounts", OK if admins else BAD, f"{User.objects.count()} users, {admins} administrators")

        if options["json"]:
            import json

            self.stdout.write(json.dumps([{"check": c, "state": s, "detail": d} for c, s, d in checks], indent=2))
        else:
            width = max(len(c) for c, _, _ in checks)
            for name, state, detail in checks:
                mark = {OK: "  ok  ", WARN: " warn ", BAD: " FAIL "}[state]
                style = {OK: self.style.SUCCESS, WARN: self.style.WARNING, BAD: self.style.ERROR}[state]
                self.stdout.write(f"[{style(mark)}] {name.ljust(width)}  {detail}")
        if any(s == BAD for _, s, _ in checks):
            sys.exit(1)


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _healthz(port: int) -> dict | None:
    """HTTP 埠有沒有在回 /healthz（回 JSON 才算；別的程式佔了埠也會被看出來）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as resp:  # noqa: S310 - 本機固定位址
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return body if isinstance(body, dict) else {}
    except Exception:  # noqa: BLE001
        return None
