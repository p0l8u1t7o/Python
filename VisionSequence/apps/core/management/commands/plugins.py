"""外掛清單（不用伺服器在跑）：現場工程師裝完外掛先看它有沒有掛得起來。

    manage.py plugins --list           表格：檔名、狀態、掛了什麼、錯誤
    manage.py plugins --list --json    給 vsctl 用
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core import plugins


class Command(BaseCommand):
    help = "List the folder plugins and whether each one mounts (the same view as the Plugins page)."

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="Scan the plugin folder and list every file")
        parser.add_argument("--json", action="store_true", help="Machine-readable output")
        parser.add_argument("--dir", default="", help="Scan another folder instead of VISION_PLUGIN_DIR")

    def handle(self, *args, **options):
        folder = Path(options["dir"]) if options["dir"] else plugins.plugin_dir()
        plugins.load_folder_plugins(folder, force=True)
        items = [it for it in plugins.inventory() if Path(it["path"]).resolve().parent == folder.resolve()]
        if options["json"]:
            self.stdout.write(json.dumps({"dir": str(folder), "items": items}, indent=2, default=str))
            return
        self.stdout.write(f"Plugin folder: {folder}" + ("" if folder.is_dir() else "  (missing)"))
        if not items:
            self.stdout.write("No plugin files.")
            return
        width = max(len(it["name"]) for it in items)
        for it in items:
            mark = {"ok": self.style.SUCCESS("  ok  "), "disabled": self.style.WARNING(" off  "), "empty": self.style.WARNING("empty "), "error": self.style.ERROR(" FAIL ")}[it["status"]]
            what = ", ".join(it["mounted"]) or it["error"] or "-"
            self.stdout.write(f"[{mark}] {it['name'].ljust(width)}  {what}")
