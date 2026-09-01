"""用 Google 圖片（Custom Search JSON API）抓元件與知識卡的照片。

存檔位置與檔名（前端就是照這個路徑讀）：
  設備元件 Component  → media/components/<設備 slug>/<元件 slug>.<ext>
  元件知識卡 KnowledgeCard → media/knowledge/<料號>.<ext>          例：knowledge/MEC-01.jpg

搜尋關鍵字取自 backend/catalog/seed/image_queries.json，要調整抓圖結果就改那個檔。

用法：
  python manage.py fetch_google_photos --dry-run          # 先看會抓什麼、用掉幾次查詢
  python manage.py fetch_google_photos                    # 只補沒有照片的
  python manage.py fetch_google_photos --target cards     # 只抓知識卡
  python manage.py fetch_google_photos --equipment aoi    # 只抓某台設備的元件
  python manage.py fetch_google_photos --code MEC-01 --force
  python manage.py fetch_google_photos --rights cc_publicdomain,cc_attribute,cc_sharealike

注意：Google 圖片搜到的多半是**有版權的第三方圖片**。本指令會把來源頁與網站寫進
photo_credit / photo_source_url 以便日後追溯或撤換；要不要用請自行判斷授權。
只想要可自由使用的圖就加 --rights。
"""

import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catalog import googleimages as gi
from catalog.models import Component

QUERIES = Path(__file__).resolve().parents[2] / "seed" / "image_queries.json"


class Command(BaseCommand):
    help = "用 Google 圖片搜尋抓取元件／知識卡照片"

    def add_arguments(self, parser):
        parser.add_argument(
            "--target", choices=["components", "cards", "all"], default="all",
            help="要抓設備元件、元件知識卡，還是兩者都抓（預設 all）",
        )
        parser.add_argument("--equipment", help="只處理指定設備 slug（僅對 components 有效）")
        parser.add_argument("--slug", help="只處理指定元件 slug")
        parser.add_argument("--category", help="只處理指定知識卡分類（mech/elec/…）")
        parser.add_argument("--code", help="只處理指定知識卡料號，如 MEC-01")
        parser.add_argument("--force", action="store_true", help="已有照片也重抓")
        parser.add_argument("--dry-run", action="store_true", help="只列出計畫，不查詢也不下載")
        parser.add_argument("--limit", type=int, default=0, help="最多處理幾筆（省 API 配額）")
        parser.add_argument("--candidates", type=int, default=5, help="每筆取幾個候選依序嘗試下載")
        parser.add_argument("--rights", default="", help="授權篩選，如 cc_publicdomain,cc_attribute")
        parser.add_argument("--delay", type=float, default=0.5, help="每筆之間的間隔秒數")
        parser.add_argument(
            "--queries", default=str(QUERIES),
            help=f"搜尋關鍵字對照檔（預設 {QUERIES.name}），可指向自己的覆寫檔",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        from training.models import KnowledgeCard  # 延後匯入，避免 app 載入順序問題

        path = Path(opts["queries"])
        try:
            queries = json.loads(path.read_text(encoding="utf-8"))
        except OSError as e:
            raise CommandError(f"讀不到搜尋關鍵字對照檔 {path}：{e}") from e

        jobs: list[tuple] = []
        if opts["target"] in ("components", "all"):
            jobs += self.component_jobs(queries.get("components", {}), opts)
        if opts["target"] in ("cards", "all"):
            jobs += self.card_jobs(KnowledgeCard, queries.get("cards", {}), opts)

        if opts["limit"]:
            jobs = jobs[: opts["limit"]]
        if not jobs:
            self.stdout.write("沒有要處理的項目（已有照片的預設會跳過，需要重抓請加 --force）。")
            return

        if opts["dry_run"]:
            for _obj, label, rel, query in jobs:
                self.stdout.write(f"  {label:<46} {rel:<44} q={query}")
            self.stdout.write(self.style.SUCCESS(
                f"共 {len(jobs)} 筆，會用掉 {len(jobs)} 次 Custom Search 查詢"
                "（免費層每天 100 次）。確認無誤後拿掉 --dry-run。"
            ))
            return

        try:
            gi.credentials()
        except gi.ConfigError as e:
            raise CommandError(str(e)) from e

        ok = failed = 0
        for i, (obj, label, rel, query) in enumerate(jobs, 1):
            try:
                hit, raw, ext = gi.best(query, count=opts["candidates"], rights=opts["rights"])
            except gi.QuotaError as e:
                self.stderr.write(self.style.ERROR(str(e)))
                self.stdout.write(f"已完成 {ok} 筆後停止，明天再跑會從沒照片的接著抓。")
                break
            except Exception as e:  # noqa: BLE001
                self.stderr.write(f"  [失敗] {label}: {e}")
                failed += 1
                continue

            rel = rel.rsplit(".", 1)[0] + ext
            dest = Path(settings.MEDIA_ROOT) / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)

            obj.photo = rel
            obj.photo_credit = f"圖片來源：{hit.site}（Google 圖片搜尋，版權屬原網站）"
            obj.photo_source_url = hit.page_url or hit.image_url
            obj.save(update_fields=["photo", "photo_credit", "photo_source_url"])
            ok += 1
            self.stdout.write(f"  [{i}/{len(jobs)}] {label:<40} <- {hit}")
            time.sleep(opts["delay"])

        self.stdout.write(self.style.SUCCESS(f"完成：{ok} 張下載，{failed} 筆失敗"))

    # ------------------------------------------------------------------
    def component_jobs(self, qmap: dict, opts) -> list[tuple]:
        qs = Component.objects.select_related("module__equipment")
        if opts["equipment"]:
            qs = qs.filter(module__equipment__slug=opts["equipment"])
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
        if not opts["force"]:
            qs = qs.filter(photo="")
        jobs = []
        for c in qs.order_by("module__equipment__slug", "order"):
            query = qmap.get(c.slug)
            if not query:
                self.stderr.write(f"  [略過] 元件 {c.slug} 沒有搜尋關鍵字（請補進 image_queries.json）")
                continue
            eq = c.module.equipment.slug
            jobs.append((c, f"{eq}/{c.name}", f"components/{eq}/{c.slug}.jpg", query))
        return jobs

    def card_jobs(self, model, qmap: dict, opts) -> list[tuple]:
        qs = model.objects.all()
        if opts["category"]:
            qs = qs.filter(category=opts["category"])
        if opts["code"]:
            qs = qs.filter(code=opts["code"])
        if not opts["force"]:
            qs = qs.filter(photo="")
        jobs = []
        for card in qs.order_by("code"):
            query = qmap.get(card.code)
            if not query:
                self.stderr.write(f"  [略過] 知識卡 {card.code} 沒有搜尋關鍵字")
                continue
            jobs.append((card, f"{card.code} {card.name}", f"knowledge/{card.code}.jpg", query))
        return jobs
