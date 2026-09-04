"""Self-check for support: the first question on any call is "what does doctor say?".

    manage.py doctor

Prints the version, disk headroom, database and archive size, listening ports, connection and
capture-client health, and the optional deep-learning stack — everything you would otherwise ask a
customer to look up one at a time. Exit code is 1 when something needs attention.
"""

from __future__ import annotations

import shutil
import socket
import sys
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

        from apps.vision.models import FlowRun, FlowRunHourly

        add("history", OK, f"{FlowRun.objects.count()} run rows (kept {cfg.get('KEEP_RUN_DAYS')}d), {FlowRunHourly.objects.count()} hourly rows (kept forever)")

        for label, port in (("API", cfg.get("TCP_PORT")), ("capture", cfg.get("CAPTURE_PORT"))):
            listening = _listening(int(port))
            add(f"{label} port {port}", OK if listening else WARN, "listening" if listening else "not listening (is manage.py serve running?)")

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
