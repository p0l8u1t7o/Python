"""把手動存下來的圖片匯入平台，放到正確的位置與檔名。

不需要任何 API 金鑰。適合用 `Docs/photo-candidates.html` 挑好圖、右鍵另存之後批次匯入。

檔名決定要掛到哪裡（副檔名可為 jpg/jpeg/png/webp，大小寫皆可）：

  MEC-01.jpg              → 元件知識卡 MEC-01
  aoi__belt-conveyor.jpg  → AOI 設備的 belt-conveyor 元件（雙底線分隔設備與元件）
  aoi/belt-conveyor.jpg   → 同上，用子資料夾表示設備
  belt-conveyor.jpg       → 所有設備裡 slug 為 belt-conveyor 的元件

用法：
  python manage.py import_photos D:\\photos --dry-run
  python manage.py import_photos D:\\photos --credit "翻攝自原廠型錄"
  python manage.py import_photos D:\\photos --move        # 匯入後刪掉來源檔
"""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from catalog.models import Component

EXTS = {".jpg", ".jpeg", ".png", ".webp"}
CANON = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MIN_PIXELS = 120


class Command(BaseCommand):
    help = "從資料夾匯入手動準備的元件／知識卡照片"

    def add_arguments(self, parser):
        parser.add_argument("folder", help="放圖片的資料夾（會遞迴掃描）")
        parser.add_argument("--credit", default="", help="寫進 photo_credit 的來源說明")
        parser.add_argument("--source-url", default="", help="寫進 photo_source_url 的來源頁")
        parser.add_argument("--dry-run", action="store_true", help="只列出對應關係，不寫檔")
        parser.add_argument("--move", action="store_true", help="匯入成功後刪除來源檔")
        parser.add_argument("--force", action="store_true", help="已有照片也覆蓋")

    def handle(self, *args, **opts):
        from training.models import KnowledgeCard

        folder = Path(opts["folder"])
        if not folder.is_dir():
            raise CommandError(f"找不到資料夾：{folder}")

        files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in EXTS)
        if not files:
            raise CommandError(f"{folder} 底下沒有 {'／'.join(sorted(EXTS))} 檔案")

        ok = skipped = failed = 0
        for src in files:
            try:
                targets = self.resolve(src, folder, KnowledgeCard)
            except LookupError as e:
                self.stderr.write(f"  [對不到] {src.name}: {e}")
                failed += 1
                continue

            if not opts["force"]:
                targets = [t for t in targets if not t[0].photo]
                if not targets:
                    skipped += 1
                    continue

            try:
                raw, ext = self.read_image(src)
            except Exception as e:  # noqa: BLE001
                self.stderr.write(f"  [壞檔] {src.name}: {e}")
                failed += 1
                continue

            for obj, rel_base, label in targets:
                rel = rel_base + ext
                if opts["dry_run"]:
                    self.stdout.write(f"  {src.name:<34} → {rel:<44} ({label})")
                    continue
                dest = Path(settings.MEDIA_ROOT) / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
                obj.photo = rel
                if opts["credit"]:
                    obj.photo_credit = opts["credit"]
                if opts["source_url"]:
                    obj.photo_source_url = opts["source_url"]
                obj.save(update_fields=["photo", "photo_credit", "photo_source_url"])
                self.stdout.write(f"  [OK] {label:<38} ← {src.name}")
                ok += 1

            if opts["move"] and not opts["dry_run"]:
                src.unlink(missing_ok=True)

        if opts["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"預覽 {len(files)} 個檔案；確認無誤後拿掉 --dry-run"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"完成：{ok} 張匯入，{skipped} 個已有照片跳過，{failed} 個失敗"
            ))

    # ------------------------------------------------------------------
    def read_image(self, path: Path) -> tuple[bytes, str]:
        """讀檔並確認真的是看得懂的圖片；副檔名以實際解碼格式為準。"""
        raw = path.read_bytes()
        with Image.open(path) as im:
            fmt, size = im.format, im.size
            im.verify()
        if fmt not in CANON:
            raise ValueError(f"不支援的格式 {fmt}")
        if min(size) < MIN_PIXELS:
            raise ValueError(f"解析度太低 {size[0]}x{size[1]}")
        return raw, CANON[fmt]

    def resolve(self, src: Path, root: Path, card_model) -> list[tuple]:
        """從檔名／子資料夾推出要掛到哪個物件，回傳 (物件, 相對路徑不含副檔名, 顯示名稱)。"""
        stem = src.stem
        # 子資料夾當作設備 slug（photos/aoi/belt-conveyor.jpg）
        parts = src.relative_to(root).parts
        eq_from_dir = parts[-2] if len(parts) >= 2 else ""

        card = card_model.objects.filter(code__iexact=stem).first()
        if card:
            return [(card, f"knowledge/{card.code}", f"{card.code} {card.name}")]

        eq_slug, _, comp_slug = stem.partition("__")
        if not comp_slug:
            comp_slug, eq_slug = stem, eq_from_dir

        qs = Component.objects.select_related("module__equipment").filter(slug__iexact=comp_slug)
        if eq_slug:
            qs = qs.filter(module__equipment__slug__iexact=eq_slug)
        comps = list(qs)
        if not comps:
            raise LookupError(
                f"沒有 code={stem} 的知識卡，也沒有 slug={comp_slug}"
                + (f"（設備 {eq_slug}）" if eq_slug else "") + " 的元件"
            )
        return [
            (c, f"components/{c.module.equipment.slug}/{c.slug}",
             f"{c.module.equipment.slug}/{c.name}")
            for c in comps
        ]
