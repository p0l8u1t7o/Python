"""Back the installation up into one zip: database, assets and a manifest.

    manage.py backup                       → data/backups/visionsequence-<stamp>.zip
    manage.py backup --out D:/x.zip --with-images

The database is copied through SQLite's own backup API so the file is consistent even while the
line is running. Archived inspection images are excluded by default — they are the bulky part and
are usually not what you need to move a station to a new PC.
"""

from __future__ import annotations

import json
import sqlite3
import time
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.vision import archive

MANIFEST = "manifest.json"


def _db_path() -> Path:
    return Path(settings.DATABASES["default"]["NAME"])


def _copy_db(target: Path) -> None:
    """SQLite 的線上備份：跑著的產線也能備，不會拿到寫到一半的檔案。"""
    src = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _add_tree(zf: zipfile.ZipFile, root: Path, prefix: str) -> int:
    count = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if path.is_file():
            zf.write(path, f"{prefix}/{path.relative_to(root).as_posix()}")
            count += 1
    return count


class Command(BaseCommand):
    help = "Back up the database, assets and settings manifest into a single zip file."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="", help="Target .zip (default: data/backups/visionsequence-<stamp>.zip)")
        parser.add_argument("--with-images", action="store_true", help="Include archived inspection images (can be very large)")

    def handle(self, *args, **options):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = Path(options["out"]) if options["out"] else Path(settings.DATA_DIR) / "backups" / f"visionsequence-{stamp}.zip"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_db = out.parent / f".{stamp}.sqlite3"
        try:
            _copy_db(tmp_db)
        except sqlite3.Error as exc:
            raise CommandError(f"Could not copy the database: {exc}") from exc
        try:
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(tmp_db, "db.sqlite3")
                assets = _add_tree(zf, Path(settings.VISION["ASSET_DIR"]), "assets")
                images = _add_tree(zf, archive.root(), "archive") if options["with_images"] else 0
                zf.writestr(MANIFEST, json.dumps({
                    "created_at": stamp,
                    "station_id": settings.VISION.get("STATION_ID", ""),
                    "asset_files": assets,
                    "archive_files": images,
                    "with_images": bool(options["with_images"]),
                }, indent=2))
        finally:
            tmp_db.unlink(missing_ok=True)
        size = out.stat().st_size
        self.stdout.write(self.style.SUCCESS(f"Backup written: {out} ({size / (1 << 20):.1f} MB)"))
        if not options["with_images"]:
            self.stdout.write("Archived inspection images were not included (use --with-images).")
