"""載入 catalog/seed/*.json 的設備／模組／元件資料。

用法：python manage.py load_seed
- 以 slug 為鍵 update_or_create，可重複執行。
- 若 media/components/<equipment>/<component-slug>.jpg 存在，會自動掛上照片。
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import Component, Equipment, Module

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")


class Command(BaseCommand):
    help = "載入種子資料（設備、模組、元件）"

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT)
        for path in sorted(SEED_DIR.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            # seed 目錄裡不是每個 json 都是設備定義（例如 image_queries.json 是抓圖關鍵字），
            # 沒有頂層 slug 的就跳過，並印出來避免無聲忽略。
            if not isinstance(data, dict) or "slug" not in data:
                self.stdout.write(f"  跳過 {path.name}（不是設備定義）")
                continue
            modules_data = data.pop("modules", [])
            equipment, _ = Equipment.objects.update_or_create(slug=data["slug"], defaults=data)
            for m_order, m in enumerate(modules_data):
                comps = m.pop("components", [])
                m["order"] = m_order
                module, _ = Module.objects.update_or_create(
                    equipment=equipment, slug=m["slug"], defaults=m
                )
                for c_order, c in enumerate(comps):
                    pos = c.pop("pos", [0, 0, 0])
                    c.update({"order": c_order, "pos_x": pos[0], "pos_y": pos[1], "pos_z": pos[2]})
                    comp, _ = Component.objects.update_or_create(
                        module=module, slug=c["slug"], defaults=c
                    )
                    if not comp.photo:
                        for ext in PHOTO_EXTS:
                            rel = f"components/{equipment.slug}/{comp.slug}{ext}"
                            if (media_root / rel).exists():
                                comp.photo = rel
                                comp.save(update_fields=["photo"])
                                break
            self.stdout.write(self.style.SUCCESS(f"載入 {equipment.name}：{len(modules_data)} 個模組"))
        self.stdout.write(
            f"合計 {Equipment.objects.count()} 台設備、{Module.objects.count()} 個模組、"
            f"{Component.objects.count()} 個元件"
        )
