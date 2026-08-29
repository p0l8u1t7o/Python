"""建立示範資料：合成影像來源＋兩個示範流程，讓沒有相機的機器也能完整體驗。"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.vision.demo import seed_demo


class Command(BaseCommand):
    help = "建立示範影像來源與示範流程（已存在則更新圖）"

    def handle(self, *args, **options):
        created = seed_demo()
        for name in created:
            self.stdout.write(f"  {name}")
        self.stdout.write(self.style.SUCCESS("示範資料已就緒"))
