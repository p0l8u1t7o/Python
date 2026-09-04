"""Restore an installation from a `manage.py backup` zip.

    manage.py restore backup.zip --yes

Overwrites the database and assets, so **stop the server first**. The existing database is kept
next to the new one as `<name>.before-restore` in case the backup turns out to be the wrong one.
"""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.vision import archive


def _safe_extract(zf: zipfile.ZipFile, member: str, target_root: Path, prefix: str) -> None:
    """Extract one member under `target_root`, refusing paths that escape it (zip slip)."""
    rel = member[len(prefix) + 1 :]
    dest = (target_root / rel).resolve()
    if not str(dest).startswith(str(target_root.resolve())):
        raise CommandError(f"Refusing to extract outside the target directory: {member}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member) as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)


class Command(BaseCommand):
    help = "Restore the database and assets from a backup zip. Stop the server first."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Backup .zip produced by manage.py backup")
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"No such file: {path}")
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "db.sqlite3" not in names:
                raise CommandError("This zip has no db.sqlite3 — is it a VisionSequence backup?")
            manifest = json.loads(zf.read("manifest.json")) if "manifest.json" in names else {}
            self.stdout.write(f"Backup created {manifest.get('created_at', '?')}, station {manifest.get('station_id', '?')}")
            if not options["yes"]:
                answer = input("This overwrites the current database and assets. Continue? [y/N] ").strip().lower()
                if answer not in ("y", "yes"):
                    self.stdout.write("Cancelled.")
                    return
            db = Path(settings.DATABASES["default"]["NAME"])
            if db.exists():
                keep = db.with_suffix(db.suffix + f".before-restore-{time.strftime('%Y%m%d-%H%M%S')}")
                shutil.copy2(db, keep)
                self.stdout.write(f"Previous database kept at {keep}")
            db.parent.mkdir(parents=True, exist_ok=True)
            with zf.open("db.sqlite3") as src, open(db, "wb") as out:
                shutil.copyfileobj(src, out)
            for prefix, root in (("assets", Path(settings.VISION["ASSET_DIR"])), ("archive", archive.root())):
                members = [n for n in names if n.startswith(f"{prefix}/") and not n.endswith("/")]
                for member in members:
                    _safe_extract(zf, member, root, prefix)
                if members:
                    self.stdout.write(f"Restored {len(members)} files into {root}")
        self.stdout.write(self.style.SUCCESS("Restore complete. Run manage.py migrate, then start the server."))
