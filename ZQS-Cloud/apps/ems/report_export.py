"""把 :func:`apps.ems.reports.build_report` 的結果寫成 PDF 或 Word。

風格：專業、簡約——白底、一種強調色、細線表格、數字靠右、圖表只用直條與長條。
兩種格式的章節順序完全相同（摘要 → 分析結論 → 能源 → 需量與電費 → 警報），
所以拿 Word 改完再看 PDF 不會找不到對應段落。

中文字型：reportlab 內建字型不含 CJK。依序嘗試 ``REPORT_FONT_PATH``、Windows 的
微軟正黑體／Noto、Linux 的 Noto CJK；都沒有就退回 Helvetica（中文會變方框，
但檔案仍能產生）。Word 不需要嵌字型，交給開啟的電腦處理。
"""

from __future__ import annotations

import datetime as dt
import io
import os
import zoneinfo
from pathlib import Path

from apps.core.logging import get_logger

logger = get_logger("reports.export")

ACCENT = "#0f766e"
INK = "#1f2937"
MUTED = "#6b7280"
RULE = "#d1d5db"
SEVERITY_COLORS = {"critical": "#b91c1c", "major": "#c2410c", "warning": "#b45309", "info": "#2563eb"}
SEVERITY_LABELS = {"critical": "嚴重", "major": "重大", "warning": "警告", "info": "資訊"}
LEVEL_LABELS = {"critical": "注意", "warning": "建議", "ok": "良好", "info": "說明"}
WEEKDAY_LABELS = {"mon": "週一", "tue": "週二", "wed": "週三", "thu": "週四", "fri": "週五", "sat": "週六", "sun": "週日"}

_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/msjh.ttc", 0),
    ("C:/Windows/Fonts/NotoSansTC-VF.ttf", None),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/truetype/noto/NotoSansTC-Regular.ttf", None),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 2),
    ("/System/Library/Fonts/PingFang.ttc", 0),
]
_FONT_BOLD_CANDIDATES = [
    ("C:/Windows/Fonts/msjhbd.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
]


# ---------------------------------------------------------------------------
# 共用格式
# ---------------------------------------------------------------------------
def _local(value: dt.datetime, zone_name: str) -> str:
    try:
        zone = zoneinfo.ZoneInfo(zone_name or "UTC")
    except Exception:  # noqa: BLE001
        zone = dt.timezone.utc
    return value.astimezone(zone).strftime("%Y-%m-%d %H:%M")


def _num(value, digits: int = 0, unit: str = "") -> str:
    if value is None:
        return "—"
    text = f"{value:,.{digits}f}"
    return f"{text} {unit}".strip()


def _money(value, currency: str) -> str:
    if value is None:
        return "—"
    return f"{currency} {value:,.0f}".strip() if currency else f"{value:,.0f}"


def _pct(value) -> str:
    return "—" if value is None else f"{value:.0f}%"


def _minutes(value) -> str:
    if value is None:
        return "—"
    return f"{value / 60:.1f} 小時" if value >= 120 else f"{value:.0f} 分鐘"


def _tree_name(name: str, depth: int) -> str:
    """場域樹在表格裡的樣子：子場域縮排並加 └ 連接符，和 console 一致。"""
    return name if depth <= 0 else "　" * (depth - 1) + "└ " + name


def _title(report: dict) -> str:
    scope = report["scope_name"] or "全部場域"
    return f"能源管理報表 — {scope}"


def _period(report: dict) -> str:
    return f"{_local(report['start'], report['timezone_name'])} 至 {_local(report['end'], report['timezone_name'])}（{report['timezone_name']}）"


def _summary_rows(report: dict) -> list[tuple[str, str]]:
    t = report["totals"]
    c = report["currency"]
    return [
        ("總用電", _num(t["load_kwh"], 0, "kWh")),
        ("自發電", _num(t["pv_kwh"], 0, "kWh")),
        ("購電", _num(t["grid_import_kwh"], 0, "kWh")),
        ("售電", _num(t["grid_export_kwh"], 0, "kWh")),
        ("電池放電", _num(t["battery_discharge_kwh"], 0, "kWh")),
        ("自給率", _pct(t["self_sufficiency_ratio"])),
        ("自發自用率", _pct(t["self_consumption_ratio"])),
        ("最高負載", _num(t["peak_load_kw"], 0, "kW")),
        ("電費支出", _money(t["energy_cost"], c)),
        ("售電收入", _money(t["export_revenue"], c)),
        ("調度節省（電量）", _money(t["estimated_savings"], c)),
        ("需量費受益", _money(t["demand_savings"], c)),
        ("警報總數", f"{report['alerts']['total']} 則（未結案 {report['alerts']['open']}）"),
        ("結案中位時間", _minutes(report["alerts"]["median_minutes_to_resolve"])),
    ]


def _site_table(report: dict) -> tuple[list[str], list[list[str]]]:
    c = report["currency"]
    unit = f" {c}" if c else ""
    head = ["場域", "用電 kWh", "自發電 kWh", "購電 kWh", "自給率", "最高需量 kW", "契約 kW", f"電費{unit}", f"節省{unit}"]
    body = []
    for row in report["sites"]:
        # 幣別與總表不同的場域才在數字後標幣別，其餘放表頭，避免欄位換行。
        own = row["currency"] if row["currency"] and row["currency"] != c else ""
        body.append([
            _tree_name(row["site_name"], row.get("depth", 0)),
            _num(row["load_kwh"]),
            _num(row["pv_kwh"]),
            _num(row["grid_import_kwh"]),
            _pct(row["self_sufficiency_ratio"]),
            (_num(row["peak_demand_kw"]) + (" ▲" if row["over_contract"] else "")),
            _num(row["contract_capacity_kw"]),
            _num(row["energy_cost"]) + (f" {own}" if own else ""),
            _num(row["estimated_savings"] + row["demand_savings"]) + (f" {own}" if own else ""),
        ])
    return head, body


def _alert_site_table(report: dict) -> tuple[list[str], list[list[str]]]:
    head = ["場域", "總數", "嚴重", "重大", "警告", "資訊", "未結案"]
    body = [
        [_tree_name(r["site_name"], r.get("depth", 0)), str(r["total"]), str(r["critical"]), str(r["major"]), str(r["warning"]), str(r["info"]), str(r["open"])]
        for r in report["alerts"]["by_site"]
    ]
    return head, body


def _alert_top_table(report: dict) -> tuple[list[str], list[list[str]]]:
    head = ["警報", "嚴重度", "次數", "累計觸發"]
    body = [
        [f"{r['title']}" + (f"（{r['code']}）" if r["code"] else ""), SEVERITY_LABELS.get(r["severity"], r["severity"]), str(r["count"]), str(r["occurrences"])]
        for r in report["alerts"]["top_titles"]
    ]
    return head, body


def _alert_time_text(report: dict) -> str:
    a = report["alerts"]
    if a["total"] == 0:
        return "期間內沒有警報。"
    parts = [f"每日平均 {a['per_day']:.1f} 則。"]
    if a["peak_hour"] is not None:
        parts.append(f"最常發生在 {a['peak_hour']:02d}:00–{a['peak_hour']:02d}:59（佔 {a['peak_hour_share']:.0f}%）")
    if a["peak_weekday"]:
        parts.append(f"以{WEEKDAY_LABELS.get(a['peak_weekday'], a['peak_weekday'])}最多")
    if a["mean_minutes_to_acknowledge"] is not None:
        parts.append(f"平均 {_minutes(a['mean_minutes_to_acknowledge'])} 內確認")
    if a["median_minutes_to_resolve"] is not None:
        parts.append(f"結案中位數 {_minutes(a['median_minutes_to_resolve'])}")
    return "；".join(parts) + "。"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _register_fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    def try_register(name: str, candidates) -> str | None:
        for path, index in candidates:
            if not Path(path).exists():
                continue
            try:
                if index is None:
                    pdfmetrics.registerFont(TTFont(name, path))
                else:
                    pdfmetrics.registerFont(TTFont(name, path, subfontIndex=index))
                return name
            except Exception:  # noqa: BLE001 - try the next one
                logger.debug("font %s unusable", path, exc_info=True)
        return None

    custom = os.environ.get("REPORT_FONT_PATH", "")
    candidates = ([(custom, None)] if custom else []) + _FONT_CANDIDATES
    regular = try_register("ZQS-CJK", candidates) or "Helvetica"
    bold = try_register("ZQS-CJK-Bold", _FONT_BOLD_CANDIDATES) or (regular if regular != "Helvetica" else "Helvetica-Bold")
    return regular, bold


def render_pdf(report: dict) -> bytes:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    regular, bold = _register_fonts()
    accent = colors.HexColor(ACCENT)
    ink = colors.HexColor(INK)
    muted = colors.HexColor(MUTED)
    rule = colors.HexColor(RULE)

    h1 = ParagraphStyle("h1", fontName=bold, fontSize=20, leading=26, textColor=ink, spaceAfter=2)
    sub = ParagraphStyle("sub", fontName=regular, fontSize=9.5, leading=13, textColor=muted)
    h2 = ParagraphStyle("h2", fontName=bold, fontSize=13, leading=18, textColor=accent, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("body", fontName=regular, fontSize=9.5, leading=14, textColor=ink)
    small = ParagraphStyle("small", fontName=regular, fontSize=8, leading=11, textColor=muted)
    cell = ParagraphStyle("cell", fontName=regular, fontSize=8.5, leading=11, textColor=ink)
    cell_r = ParagraphStyle("cellr", parent=cell, alignment=TA_RIGHT)
    head_style = ParagraphStyle("head", fontName=bold, fontSize=8.5, leading=11, textColor=muted)
    head_r = ParagraphStyle("headr", parent=head_style, alignment=TA_RIGHT)

    def table(head, rows, widths=None, numeric_from=1):
        data = [[Paragraph(h, head_r if i >= numeric_from else head_style) for i, h in enumerate(head)]]
        for row in rows:
            data.append([Paragraph(str(v), cell_r if i >= numeric_from else cell) for i, v in enumerate(row)])
        t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, accent),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, rule),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]))
        return t

    def bar_chart(categories, values, *, width=170 * mm, height=55 * mm, color=ACCENT, label_every=1, fmt="{:,.0f}"):
        drawing = Drawing(width, height)
        chart = VerticalBarChart()
        chart.x, chart.y = 28, 18
        chart.width, chart.height = width - 40, height - 26
        chart.data = [values or [0]]
        chart.categoryAxis.categoryNames = [c if i % label_every == 0 else "" for i, c in enumerate(categories)]
        chart.categoryAxis.labels.fontName = regular
        chart.categoryAxis.labels.fontSize = 7
        chart.categoryAxis.labels.dy = -4
        chart.categoryAxis.strokeColor = rule
        chart.valueAxis.labels.fontName = regular
        chart.valueAxis.labels.fontSize = 7
        chart.valueAxis.strokeColor = rule
        chart.valueAxis.gridStrokeColor = colors.HexColor("#eef0f3")
        chart.valueAxis.visibleGrid = True
        chart.valueAxis.valueMin = 0
        chart.valueAxis.labelTextFormat = lambda v: fmt.format(v)
        chart.bars[0].fillColor = colors.HexColor(color)
        chart.bars[0].strokeColor = None
        chart.barWidth = 6
        chart.groupSpacing = 4
        drawing.add(chart)
        return drawing

    story = []
    story.append(Paragraph(_title(report), h1))
    story.append(Paragraph(f"{report['organization_name']} · {_period(report)}", sub))
    story.append(Paragraph(f"涵蓋 {report['site_count']} 個場域、{report['device_count']} 台設備 · 產生於 {_local(report['generated_at'], report['timezone_name'])}", sub))
    story.append(Spacer(1, 8))

    # 摘要：兩欄 KPI
    story.append(Paragraph("摘要", h2))
    kpis = _summary_rows(report)
    half = (len(kpis) + 1) // 2
    grid = []
    for i in range(half):
        left = kpis[i]
        right = kpis[i + half] if i + half < len(kpis) else ("", "")
        grid.append([Paragraph(left[0], small), Paragraph(left[1], cell_r), Paragraph(right[0], small), Paragraph(right[1], cell_r)])
    kpi_table = Table(grid, colWidths=[38 * mm, 47 * mm, 38 * mm, 47 * mm], hAlign="LEFT")
    kpi_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, rule),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(kpi_table)
    if report["mixed_currency"]:
        story.append(Paragraph("※ 場域幣別不一致，總計金額未標示幣別。", small))

    # 結論
    story.append(Paragraph("分析結論", h2))
    for item in report["insights"]:
        tag = LEVEL_LABELS.get(item["level"], "")
        color = {"critical": "#b91c1c", "warning": "#b45309", "ok": "#15803d"}.get(item["level"], MUTED)
        story.append(Paragraph(f'<font color="{color}"><b>{tag}</b></font>　{item["text"]}', body))
        story.append(Spacer(1, 2))

    # 能源
    story.append(Paragraph("能源使用", h2))
    if report["daily"]:
        days = [d["day"][5:] for d in report["daily"]]
        every = 1 if len(days) <= 14 else (2 if len(days) <= 31 else 7)
        story.append(Paragraph("每日用電（kWh）", small))
        story.append(bar_chart(days, [d["load_kwh"] for d in report["daily"]], label_every=every))
        story.append(Paragraph("每日購電（kWh）", small))
        story.append(bar_chart(days, [d["grid_import_kwh"] for d in report["daily"]], color="#1d4ed8", label_every=every, height=40 * mm))
    if report["hourly_load"] and any(h["avg_load_kw"] for h in report["hourly_load"]):
        story.append(Paragraph("一日負載曲線：各小時平均負載（kW）", small))
        story.append(bar_chart([f"{h['hour']:02d}" for h in report["hourly_load"]], [h["avg_load_kw"] for h in report["hourly_load"]], color="#7c3aed", height=40 * mm, label_every=2))
    head, rows = _site_table(report)
    story.append(Spacer(1, 4))
    story.append(table(head, rows, widths=[34 * mm, 18 * mm, 18 * mm, 18 * mm, 14 * mm, 20 * mm, 16 * mm, 20 * mm, 20 * mm]))
    story.append(Paragraph("▲ = 最高需量超過契約容量。節省 = 電量面調度節省 + 需量費受益。", small))

    # 警報
    story.append(PageBreak())
    story.append(Paragraph("警報統計", h2))
    a = report["alerts"]
    sev = a["by_severity"]
    story.append(Paragraph(
        f"共 {a['total']} 則：嚴重 {sev.get('critical', 0)}、重大 {sev.get('major', 0)}、警告 {sev.get('warning', 0)}、資訊 {sev.get('info', 0)}；已結案 {a['resolved']}、未結案 {a['open']}。",
        body,
    ))
    story.append(Paragraph(_alert_time_text(report), body))
    if a["total"]:
        story.append(Spacer(1, 4))
        story.append(Paragraph("發生時段分佈（各小時警報數）", small))
        story.append(bar_chart([f"{h:02d}" for h in range(24)], a["by_hour"], color="#b45309", height=40 * mm, label_every=2))
        story.append(Paragraph("星期分佈", small))
        story.append(bar_chart(["一", "二", "三", "四", "五", "六", "日"], a["by_weekday"], color="#b45309", height=32 * mm, width=90 * mm))
        head, rows = _alert_site_table(report)
        story.append(KeepTogether([Paragraph("各場域", small), table(head, rows, widths=[50 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm, 20 * mm])]))
        story.append(Spacer(1, 6))
        head, rows = _alert_top_table(report)
        story.append(KeepTogether([Paragraph("最常見的警報", small), table(head, rows, widths=[90 * mm, 22 * mm, 20 * mm, 24 * mm])]))

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(18 * mm, 10 * mm, f"{report['organization_name']} · {_title(report)}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 頁")
        canvas.setStrokeColor(accent)
        canvas.setLineWidth(1.2)
        canvas.line(18 * mm, A4[1] - 12 * mm, A4[0] - 18 * mm, A4[1] - 12 * mm)
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=_title(report), author=report["organization_name"],
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Word
# ---------------------------------------------------------------------------
def _chart_png(categories, values, color: str, width=1400, height=420, label_every=1) -> bytes | None:
    """簡單的直條圖 PNG（Pillow），給 Word 用。Pillow 缺席時不畫圖、只留表格。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(_FONT_CANDIDATES[0][0], 22)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    left, right, top, bottom = 90, 20, 20, 60
    plot_w, plot_h = width - left - right, height - top - bottom
    peak = max(values) if values and max(values) > 0 else 1
    n = max(1, len(values))
    slot = plot_w / n
    bar_w = max(4, slot * 0.6)
    for i in range(5):
        y = top + plot_h - plot_h * i / 4
        draw.line([(left, y), (width - right, y)], fill="#eef0f3", width=1)
        draw.text((8, y - 12), f"{peak * i / 4:,.0f}", fill=MUTED, font=font)
    for i, value in enumerate(values):
        x0 = left + i * slot + (slot - bar_w) / 2
        h = plot_h * (value / peak)
        draw.rounded_rectangle([x0, top + plot_h - h, x0 + bar_w, top + plot_h], radius=3, fill=color)
        if i % label_every == 0:
            draw.text((x0 + bar_w / 2 - 12, top + plot_h + 8), str(categories[i]), fill=MUTED, font=font)
    draw.line([(left, top + plot_h), (width - right, top + plot_h)], fill=RULE, width=2)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def render_docx(report: dict) -> bytes:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    for section in doc.sections:
        section.left_margin = section.right_margin = Cm(2)
        section.top_margin = section.bottom_margin = Cm(2)
    style = doc.styles["Normal"]
    style.font.name = "Microsoft JhengHei"
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft JhengHei")
    style.font.size = Pt(10)
    accent = RGBColor(0x0F, 0x76, 0x6E)
    muted = RGBColor(0x6B, 0x72, 0x80)

    def heading(text: str):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = True
        run.font.size = Pt(13)
        run.font.color.rgb = accent
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(4)
        # 標題下方一條細線
        pPr = p._p.get_or_add_pPr()
        border = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for key, value in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "0F766E")):
            bottom.set(qn(key), value)
        border.append(bottom)
        pPr.append(border)

    def note(text: str):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.font.size = Pt(8.5)
        run.font.color.rgb = muted

    def table(head, rows, numeric_from=1):
        t = doc.add_table(rows=1, cols=len(head))
        t.style = "Light List Accent 1" if "Light List Accent 1" in [s.name for s in doc.styles] else "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.LEFT
        for i, h in enumerate(head):
            cell = t.rows[0].cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(h)
            run.bold = True
            run.font.size = Pt(8.5)
            if i >= numeric_from:
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for row in rows:
            cells = t.add_row().cells
            for i, value in enumerate(row):
                cells[i].text = ""
                run = cells[i].paragraphs[0].add_run(str(value))
                run.font.size = Pt(8.5)
                if i >= numeric_from:
                    cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        return t

    def picture(png: bytes | None, caption: str):
        if not png:
            return
        note(caption)
        doc.add_picture(io.BytesIO(png), width=Cm(17))

    title = doc.add_paragraph()
    run = title.add_run(_title(report))
    run.bold = True
    run.font.size = Pt(20)
    note(f"{report['organization_name']} · {_period(report)}")
    note(f"涵蓋 {report['site_count']} 個場域、{report['device_count']} 台設備 · 產生於 {_local(report['generated_at'], report['timezone_name'])}")

    heading("摘要")
    kpis = _summary_rows(report)
    half = (len(kpis) + 1) // 2
    t = doc.add_table(rows=half, cols=4)
    for i in range(half):
        left = kpis[i]
        right = kpis[i + half] if i + half < len(kpis) else ("", "")
        for col, (text, is_value) in enumerate(((left[0], False), (left[1], True), (right[0], False), (right[1], True))):
            cell = t.rows[i].cells[col]
            cell.text = ""
            run = cell.paragraphs[0].add_run(text)
            run.font.size = Pt(9)
            if is_value:
                run.bold = True
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            else:
                run.font.color.rgb = muted
    if report["mixed_currency"]:
        note("※ 場域幣別不一致，總計金額未標示幣別。")

    heading("分析結論")
    for item in report["insights"]:
        p = doc.add_paragraph(style="List Bullet")
        tag = p.add_run(f"{LEVEL_LABELS.get(item['level'], '')}　")
        tag.bold = True
        tag.font.color.rgb = {
            "critical": RGBColor(0xB9, 0x1C, 0x1C), "warning": RGBColor(0xB4, 0x53, 0x09), "ok": RGBColor(0x15, 0x80, 0x3D),
        }.get(item["level"], muted)
        p.add_run(item["text"])

    heading("能源使用")
    if report["daily"]:
        days = [d["day"][5:] for d in report["daily"]]
        every = 1 if len(days) <= 14 else (2 if len(days) <= 31 else 7)
        picture(_chart_png(days, [d["load_kwh"] for d in report["daily"]], ACCENT, label_every=every), "每日用電（kWh）")
        picture(_chart_png(days, [d["grid_import_kwh"] for d in report["daily"]], "#1d4ed8", label_every=every), "每日購電（kWh）")
    if report["hourly_load"] and any(h["avg_load_kw"] for h in report["hourly_load"]):
        picture(_chart_png([f"{h['hour']:02d}" for h in report["hourly_load"]], [h["avg_load_kw"] for h in report["hourly_load"]], "#7c3aed", label_every=2), "一日負載曲線：各小時平均負載（kW）")
    head, rows = _site_table(report)
    table(head, rows)
    note("▲ = 最高需量超過契約容量。節省 = 電量面調度節省 + 需量費受益。")

    doc.add_page_break()
    heading("警報統計")
    a = report["alerts"]
    sev = a["by_severity"]
    doc.add_paragraph(
        f"共 {a['total']} 則：嚴重 {sev.get('critical', 0)}、重大 {sev.get('major', 0)}、警告 {sev.get('warning', 0)}、資訊 {sev.get('info', 0)}；已結案 {a['resolved']}、未結案 {a['open']}。"
    )
    doc.add_paragraph(_alert_time_text(report))
    if a["total"]:
        picture(_chart_png([f"{h:02d}" for h in range(24)], a["by_hour"], "#b45309", label_every=2), "發生時段分佈（各小時警報數）")
        picture(_chart_png(["一", "二", "三", "四", "五", "六", "日"], a["by_weekday"], "#b45309", width=800), "星期分佈")
        note("各場域")
        head, rows = _alert_site_table(report)
        table(head, rows)
        doc.add_paragraph()
        note("最常見的警報")
        head, rows = _alert_top_table(report)
        table(head, rows)

    footer = doc.sections[0].footer.paragraphs[0]
    footer.text = f"{report['organization_name']} · {_title(report)}"
    footer.runs[0].font.size = Pt(7.5)
    footer.runs[0].font.color.rgb = muted

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def filename(report: dict, ext: str) -> str:
    scope = (report["scope_name"] or "all-sites").replace(" ", "_")
    start = report["start"].strftime("%Y%m%d")
    end = report["end"].strftime("%Y%m%d")
    return f"energy-report_{scope}_{start}-{end}.{ext}"
