"""Back the installation up into one zip: database, assets, settings (.env), folder plugins and a manifest.

    manage.py backup                       → data/backups/visionsequence-<stamp>.zip
    manage.py backup --out D:/x.zip --with-images --with-wheels --with-client
    manage.py backup --no-env              (for a shared NAS: keep the keys out of the archive)

The database is copied through SQLite's own backup API so the file is consistent even while the
line is running. Archived inspection images are excluded by default — they are the bulky part and
are usually not what you need to move a station to a new PC. The .env (station id, keys) and the
plugin folder are included because "install on new hardware, restore the backup" depends on them.
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


def _add_tree(zf: zipfile.ZipFile, root: Path, prefix: str, *, skip=lambda rel: False) -> int:
    count = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_file() and not skip(rel):
            zf.write(path, f"{prefix}/{rel.as_posix()}")
            count += 1
    return count


def _skip_plugin_file(rel: Path, with_wheels: bool) -> bool:
    parts = rel.parts
    if "__pycache__" in parts or rel.suffix in (".pyc", ".pyo"):
        return True
    return not with_wheels and any(p == "_wheels" or p == "wheels" for p in parts[:-1])


class Command(BaseCommand):
    help = "Back up the database, assets and settings manifest into a single zip file."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="", help="Target .zip (default: data/backups/visionsequence-<stamp>.zip)")
        parser.add_argument("--with-images", action="store_true", help="Include archived inspection images (can be very large)")
        parser.add_argument("--no-env", action="store_true", help="Leave the .env (station id, keys) out, e.g. for a shared backup share")
        parser.add_argument("--with-wheels", action="store_true", help="Include the plugins' offline wheel folders (wheels/, _wheels/)")
        parser.add_argument("--with-client", action="store_true", help="Include the capture client package zip, not just its manifest")

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
                env_path = Path(settings.VS_HOME) / ".env"
                env_included = bool(not options["no_env"] and env_path.exists())
                if env_included:
                    zf.write(env_path, "env/.env")
                plugin_files = _add_tree(zf, Path(settings.VISION["PLUGIN_DIR"]), "plugins", skip=lambda rel: _skip_plugin_file(rel, options["with_wheels"]))
                downloads = Path(settings.DATA_DIR) / "downloads"
                client_files = 0
                manifest_path = downloads / "manifest.json"
                if manifest_path.exists():
                    zf.write(manifest_path, "downloads/manifest.json")
                    client_files = 1
                    if options["with_client"]:
                        for zip_path in downloads.glob("*.zip"):
                            zf.write(zip_path, f"downloads/{zip_path.name}")
                            client_files += 1
                from apps.vision import __version__

                zf.writestr(MANIFEST, json.dumps({
                    "created_at": stamp,
                    "version": __version__,
                    "station_id": settings.VISION.get("STATION_ID", ""),
                    "asset_files": assets,
                    "archive_files": images,
                    "with_images": bool(options["with_images"]),
                    "env_included": env_included,
                    "plugin_files": plugin_files,
                    "capture_client_files": client_files,
                }, indent=2))
        finally:
            tmp_db.unlink(missing_ok=True)
        size = out.stat().st_size
        self.stdout.write(self.style.SUCCESS(f"Backup written: {out} ({size / (1 << 20):.1f} MB)"))
        if not options["with_images"]:
            self.stdout.write("Archived inspection images were not included (use --with-images).")
        if options["no_env"]:
            self.stdout.write("The .env (station id and keys) was not included (--no-env).")
