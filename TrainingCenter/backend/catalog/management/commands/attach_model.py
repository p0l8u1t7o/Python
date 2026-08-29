"""把 glb 3D 模型掛到元件或設備（來源不限：text-to-cad skill、Zoo、SolidWorks 匯出…）。

用法：
  python manage.py attach_model component aoi/camera path/to/camera.glb
  python manage.py attach_model equipment aoi path/to/aoi.glb
  python manage.py attach_model component aoi/camera --clear     # 移除

檔案會複製到 media/models/…，並寫入 model_file。
"""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalog.models import Component, Equipment


class Command(BaseCommand):
    help = "把 glb 模型掛到元件或設備"

    def add_arguments(self, parser):
        parser.add_argument("kind", choices=["component", "equipment"])
        parser.add_argument("target", help="component: <設備slug>/<元件slug>；equipment: <設備slug>")
        parser.add_argument("glb", nargs="?", help="glb 檔路徑")
        parser.add_argument("--clear", action="store_true")
        parser.add_argument("--prompt", default="", help="順便記錄產生用的描述（model_prompt）")

    def handle(self, *args, **opts):
        media = Path(settings.MEDIA_ROOT)
        if opts["kind"] == "equipment":
            obj = Equipment.objects.get(slug=opts["target"])
            rel = f"models/{obj.slug}.glb"
        else:
            if "/" not in opts["target"]:
                raise CommandError("component 需要 <設備slug>/<元件slug>")
            eq_slug, c_slug = opts["target"].split("/", 1)
            obj = Component.objects.get(module__equipment__slug=eq_slug, slug=c_slug)
            rel = f"models/components/{eq_slug}/{c_slug}.glb"

        if opts["clear"]:
            obj.model_file = None
            obj.save(update_fields=["model_file"])
            self.stdout.write(f"已移除 {obj}")
            return

        src = Path(opts["glb"] or "")
        if not src.is_file():
            raise CommandError(f"找不到 glb：{src}")
        dest = media / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        obj.model_file = rel
        fields = ["model_file"]
        if opts["prompt"] and hasattr(obj, "model_prompt"):
            obj.model_prompt = opts["prompt"]
            fields.append("model_prompt")
        obj.save(update_fields=fields)
        self.stdout.write(self.style.SUCCESS(f"{obj} ← {rel}（{dest.stat().st_size // 1024} KB）"))
