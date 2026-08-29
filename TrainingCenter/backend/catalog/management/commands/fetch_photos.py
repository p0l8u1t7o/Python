"""從 Wikimedia Commons 依 photo_query 抓取元件照片。

photo_query 可用 "|" 分隔多組關鍵字（由具體到通用），依序嘗試。

用法：
  python manage.py fetch_photos            # 只補沒有照片的元件
  python manage.py fetch_photos --force    # 重抓全部
  python manage.py fetch_photos --equipment aoi

只接受 CC / Public domain 授權的點陣圖；照片存到 media/components/<設備>/<元件>.jpg，
並把「作者 · 授權 · Wikimedia Commons」寫入 photo_credit、檔案頁寫入 photo_source_url。
"""

import math
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
import json
import re

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import Component

API = "https://commons.wikimedia.org/w/api.php"
UA = "TrainingCenterBot/1.0 (https://github.com/example/trainingcenter; admin@example.com)"
# upload.wikimedia.org 對非瀏覽器 UA 回 403，改用 Commons 的 thumb.php 取縮圖
THUMB = "https://commons.wikimedia.org/w/thumb.php?f={name}&w=1024"
ALLOWED_LICENSE = re.compile(r"(cc|public domain|pd|gfdl)", re.I)
BLOCKED_TITLE = re.compile(
    r"(logo|icon|diagram|drawing|sketch|schematic|patent|scheme|chart|graph|\.svg|map|screenshot|"
    r"cover|book|page|text|document|poster|portrait|people|person|man |woman|group|team|meeting|"
    r"museum|exhibit|antique|vintage|historic|old|19[0-9]{2}|toy|lego|model kit)",
    re.I,
)


def _get(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as r:
        return r.read()


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def search_commons(query: str, limit: int = 8) -> list[dict]:
    """cat: → 只取該分類直接成員（incategory）；deep: → 含子分類（deepcategory，容易跑題，慎用）。"""
    if query.startswith(("cat:", "deep:")):
        op = "incategory" if query.startswith("cat:") else "deepcategory"
        cat = query.split(":", 1)[1].split("~", 1)[0].strip()
        q = quote(f'{op}:"{cat}" filetype:bitmap -intitle:diagram -intitle:drawing')
    else:
        q = quote(f"filetype:bitmap {query}")
    url = (
        f"{API}?action=query&generator=search&gsrsearch={q}&gsrnamespace=6&gsrlimit={limit}"
        "&prop=imageinfo&iiprop=url|extmetadata|mime&format=json"
    )
    data = json.loads(_get(url))
    pages = data.get("query", {}).get("pages", {})
    results = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
        title = p.get("title", "")
        results.append(
            {
                "title": title,
                "thumb": THUMB.format(name=quote(title.removeprefix("File:"))),
                "text": " ".join(
                    [
                        title,
                        _strip_html(meta.get("ImageDescription", {}).get("value", "")),
                        _strip_html(meta.get("Categories", {}).get("value", "")),
                        _strip_html(meta.get("ObjectName", {}).get("value", "")),
                    ]
                ).lower(),
                "mime": info.get("mime", ""),
                "license": lic,
                "author": _strip_html(meta.get("Artist", {}).get("value", "")),
                "page": info.get("descriptionurl", ""),
            }
        )
    return results


def pick(results: list[dict], query: str) -> dict | None:
    """挑最相關一張：點陣圖、非圖示／示意圖、授權允許、且與查詢詞相關。

    cat: 查詢已由分類保證相關性，不再做關鍵字過濾；文字查詢需全部詞命中（>3 詞時 2/3）。
    """
    is_cat = query.startswith(("cat:", "deep:"))
    # cat:分類 ~ 提示詞：提示詞用來在分類成員中排序（命中越多越優先），不強制
    hint = query.split("~", 1)[1] if is_cat and "~" in query else ("" if is_cat else query)
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9-]+", hint) if len(w) > 2]
    need = 0 if is_cat else (len(words) if len(words) <= 3 else math.ceil(len(words) * 2 / 3))
    best = None
    for r in results:
        if r["mime"] not in ("image/jpeg", "image/png"):
            continue
        if BLOCKED_TITLE.search(r["title"]) or BLOCKED_TITLE.search(r["text"][:300]):
            continue
        if not ALLOWED_LICENSE.search(r["license"]):
            continue
        hits = sum(1 for w in words if w in r["text"])
        if hits < need:
            continue
        if best is None or hits > best[0]:
            best = (hits, r)
            if is_cat and hits == len(words):
                break  # 提示詞全命中（或無提示詞）就取第一張
    return best[1] if best else None


class Command(BaseCommand):
    help = "從 Wikimedia Commons 抓取元件照片"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="已有照片也重抓")
        parser.add_argument("--equipment", help="只處理指定設備 slug")
        parser.add_argument("--delay", type=float, default=0.5, help="每次請求間隔秒數")

    def handle(self, *args, **opts):
        qs = Component.objects.select_related("module__equipment").exclude(photo_query="")
        if opts["equipment"]:
            qs = qs.filter(module__equipment__slug=opts["equipment"])
        if not opts["force"]:
            qs = qs.filter(photo="")
        ok = skipped = 0
        for c in qs:
            eq_slug = c.module.equipment.slug
            hit = None
            try:
                # photo_query 可用 "|" 列出多組關鍵字，由具體到通用依序嘗試
                for q in [x.strip() for x in c.photo_query.split("|") if x.strip()]:
                    hit = pick(search_commons(q, limit=20), q)
                    if hit:
                        break
                    time.sleep(opts["delay"])
            except Exception as e:  # noqa: BLE001
                self.stderr.write(f"  [ERR] {c.name}: 查詢失敗 {e}")
                continue
            if not hit:
                self.stdout.write(self.style.WARNING(f"  - {c.name}: 找不到合適授權的照片（{c.photo_query}）"))
                skipped += 1
                continue
            ext = ".png" if hit["mime"] == "image/png" else ".jpg"
            rel = f"components/{eq_slug}/{c.slug}{ext}"
            dest = Path(settings.MEDIA_ROOT) / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                dest.write_bytes(_get(hit["thumb"]))
            except Exception as e:  # noqa: BLE001
                self.stderr.write(f"  [ERR] {c.name}: 下載失敗 {e}")
                continue
            author = hit["author"][:80] or "未知作者"
            c.photo = rel
            c.photo_credit = f"照片：{author} · {hit['license']} · Wikimedia Commons"
            c.photo_source_url = hit["page"]
            c.save(update_fields=["photo", "photo_credit", "photo_source_url"])
            ok += 1
            self.stdout.write(f"  [OK] {c.name} ← {hit['title']} [{hit['license']}]")
            time.sleep(opts["delay"])
        self.stdout.write(self.style.SUCCESS(f"完成：{ok} 張下載，{skipped} 個找不到"))
