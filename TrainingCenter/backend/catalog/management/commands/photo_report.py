"""產生照片縮圖對照表，用來一次檢查哪些圖抓錯了。

不管照片是 Commons、Google 還是自己拍的都會列進來，並標出還沒有照片的項目。

用法：
  python manage.py photo_report                     # 全部，輸出到 Docs/photo-report.html
  python manage.py photo_report --target cards      # 只看知識卡
  python manage.py photo_report --missing           # 只列還沒有照片的
  python manage.py photo_report --out D:\tmp\r.html
"""

import html
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from catalog.models import Component

CSS = """<style>
:root{color-scheme:dark}
body{margin:0;padding:22px 26px;background:#14171b;color:#e6e9ee;
 font:14px/1.6 "Segoe UI","Microsoft JhengHei",system-ui,sans-serif}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:26px 0 10px;padding-bottom:6px;
 border-bottom:1px solid #2c323a;color:#7ecbff}
.intro{color:#9aa4b2;max-width:900px;margin:0 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(215px,1fr));gap:12px}
figure{margin:0;background:#1b1f25;border:1px solid #2c323a;border-radius:6px;overflow:hidden}
figure img{display:block;width:100%;height:150px;object-fit:contain;background:#0e1114}
.none{display:grid;place-items:center;height:150px;background:#0e1114;color:#6b7481;font-size:12px}
figcaption{padding:7px 9px;font-size:11.5px;color:#8d97a5;word-break:break-word}
figcaption b{display:block;color:#dfe4ea;font-size:12.5px;margin-bottom:2px}
.code{font-family:Consolas,monospace;font-size:10.5px;color:#7ecbff}
a{color:#7ecbff;text-decoration:none}a:hover{text-decoration:underline}
.miss{border-color:#4d2020}
</style>"""


class Command(BaseCommand):
    help = "產生照片縮圖對照表 HTML"

    def add_arguments(self, parser):
        parser.add_argument("--target", choices=["components", "cards", "all"], default="all")
        parser.add_argument("--missing", action="store_true", help="只列還沒有照片的")
        parser.add_argument(
            "--out",
            default=str(Path(settings.BASE_DIR).parent / "Docs" / "photo-report.html"),
        )

    def handle(self, *args, **opts):
        from training.models import KnowledgeCard

        out = Path(opts["out"])
        media = Path(settings.MEDIA_ROOT)

        def rel(photo_name: str) -> str:
            """從報表所在目錄指到 media 檔案的相對路徑，直接用瀏覽器開就看得到。"""
            try:
                return os.path.relpath(media / photo_name, out.parent).replace("\\", "/")
            except ValueError:  # 跨磁碟機
                return (media / photo_name).as_uri()

        groups: list[tuple[str, list[dict]]] = []
        if opts["target"] in ("components", "all"):
            by_eq: dict[str, list] = {}
            for c in Component.objects.select_related("module__equipment").order_by(
                "module__equipment__slug", "module__order", "order"
            ):
                by_eq.setdefault(c.module.equipment.name, []).append(
                    {
                        "code": f"{c.module.equipment.slug} / {c.slug}",
                        "name": c.name,
                        "photo": c.photo.name if c.photo else "",
                        "credit": c.photo_credit,
                        "source": c.photo_source_url,
                    }
                )
            groups += [(f"設備元件：{k}", v) for k, v in by_eq.items()]

        if opts["target"] in ("cards", "all"):
            by_cat: dict[str, list] = {}
            for card in KnowledgeCard.objects.order_by("code"):
                by_cat.setdefault(card.get_category_display(), []).append(
                    {
                        "code": card.code,
                        "name": card.name,
                        "photo": card.photo.name if card.photo else "",
                        "credit": card.photo_credit,
                        "source": card.photo_source_url,
                    }
                )
            groups += [(f"元件知識卡：{k}", v) for k, v in by_cat.items()]

        if opts["missing"]:
            groups = [(t, [r for r in rows if not r["photo"]]) for t, rows in groups]

        total = sum(len(rows) for _, rows in groups)
        have = sum(1 for _, rows in groups for r in rows if r["photo"])

        h = [
            '<!doctype html><meta charset="utf-8"><title>元件照片對照表</title>',
            CSS,
            "<h1>元件照片對照表</h1>",
            f'<p class="intro">共 {total} 項，已有照片 <b>{have}</b> 項、還沒有 <b>{total - have}</b> 項。'
            "抓錯的請記下料號，改 <code>backend/catalog/seed/image_queries.json</code> 的關鍵字後，"
            "用 <code>fetch_google_photos --code &lt;料號&gt; --force</code> 單獨重抓。</p>",
        ]
        for title, rows in groups:
            if not rows:
                continue
            n_have = sum(1 for r in rows if r["photo"])
            h.append(f"<h2>{html.escape(title)}（{n_have}/{len(rows)}）</h2><div class='grid'>")
            for r in rows:
                cap = (
                    f'<figcaption><b>{html.escape(r["name"])}</b>'
                    f'<span class="code">{html.escape(r["code"])}</span>'
                )
                if r["credit"]:
                    cap += f'<br>{html.escape(r["credit"][:70])}'
                if r["source"]:
                    cap += (
                        f'<br><a href="{html.escape(r["source"])}" target="_blank" '
                        'rel="noopener">來源頁</a>'
                    )
                cap += "</figcaption>"
                img = (
                    f'<img src="{html.escape(rel(r["photo"]))}" loading="lazy" '
                    f'alt="{html.escape(r["name"])}">'
                    if r["photo"]
                    else '<div class="none">尚無照片</div>'
                )
                h.append(f"<figure{'' if r['photo'] else ' class=miss'}>{img}{cap}</figure>")
            h.append("</div>")

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(h), encoding="utf-8")
        self.stdout.write(
            self.style.SUCCESS(f"已產生 {out}（{have}/{total} 有照片）— 用瀏覽器開啟檢查")
        )
