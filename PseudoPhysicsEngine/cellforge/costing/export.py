"""成本表匯出：XLSX 保留公式（參數格可改）並附程式計算值對照；CSV 為合併同料後的採購 BOM。"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="1F3A4D")
INPUT = Font(color="1F4FBF")
WARN_FILL = PatternFill("solid", fgColor="FCE8C8")

PURCHASE_COLUMNS = [
    ("item", "採購項"),
    ("name", "名稱"),
    ("kind_label", "種類"),
    ("subsystem", "子系統"),
    ("model", "型號"),
    ("spec", "規格"),
    ("supplier", "供應商"),
    ("unit", "單位"),
    ("quantity", "數量"),
    ("unit_price", "單價"),
    ("price_currency", "幣別"),
    ("exchange_rate", "匯率"),
    (None, "小計（公式）"),
    ("amount", "程式計算值"),
    ("missing", "缺價原因"),
    ("price_source", "價格來源"),
    ("quote_date", "報價日期"),
    ("valid_until", "有效期"),
    ("trust", "可信度"),
    ("grade", "等級"),
    ("range_pct", "±幅度"),
    ("applies_to", "適用"),
    (None, "設備來源"),
]
LABOR_COLUMNS = [
    ("id", "工時項目"),
    ("category_label", "分類"),
    ("name", "名稱"),
    ("quantity", "數量"),
    ("unit", "單位"),
    ("rate", "費率"),
    ("rate_currency", "幣別"),
    (None, "匯率"),
    (None, "小計（公式）"),
    ("amount", "程式計算值"),
    ("basis", "依據"),
]


def _number(value: str | None) -> float | str:
    # 顯示用數值；精確值保留在「程式計算值」與 costing.json 的十進位字串。
    return "" if value is None else float(Decimal(value))


def _header(sheet, titles: list[str]) -> None:
    sheet.append(titles)
    for cell in sheet[sheet.max_row]:
        cell.font = HEADER
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center")


def _widths(sheet, widths: dict[int, int]) -> None:
    for column, width in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = width


def _sources(line: dict[str, Any]) -> str:
    parts = []
    for source in line["sources"]:
        where = source.get("module") or "、".join(source.get("modules", [])) or "—"
        via = f"（經 {'→'.join(source['via'])}）" if source.get("via") else ""
        parts.append(f"{source['id']}:{where}×{source['quantity']}{via}")
    return "；".join(parts)


def write_costing_xlsx(costing: dict[str, Any], target: Path, version: dict[str, Any]) -> None:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "摘要"
    purchase = workbook.create_sheet("採購明細")
    labor = workbook.create_sheet("工時")
    mapping = workbook.create_sheet("設備對應")
    subsystems = workbook.create_sheet("子系統彙總")
    missing = workbook.create_sheet("缺價清單")
    issues = workbook.create_sheet("問題")
    version_sheet = workbook.create_sheet("版本")
    rounding = costing["policy"]["rounding"]
    line_decimals = int(rounding["line_decimals"])
    total_decimals = int(rounding["total_decimals"])

    _header(purchase, [title for _key, title in PURCHASE_COLUMNS])
    for row, line in enumerate(costing["purchase_lines"], start=2):
        values = []
        for key, _title in PURCHASE_COLUMNS:
            if key is None:
                values.append(None)
            elif key in {"quantity", "unit_price", "exchange_rate", "amount", "range_pct"}:
                values.append(_number(line.get(key)))
            else:
                values.append(line.get(key) or "")
        values[-1] = _sources(line)
        purchase.append(values)
        purchase.cell(
            row, 13
        ).value = f'=IF(OR(J{row}="",L{row}=""),"",ROUND(I{row}*J{row}*L{row},{line_decimals}))'
        for column in (9, 10):
            purchase.cell(row, column).font = INPUT
        if line["missing"]:
            for cell in purchase[row]:
                cell.fill = WARN_FILL
    _widths(purchase, {1: 14, 2: 26, 4: 18, 5: 22, 6: 36, 13: 16, 14: 16, 15: 16, 16: 30, 23: 40})

    _header(labor, [title for _key, title in LABOR_COLUMNS])
    for row, line in enumerate(costing["labor_lines"], start=2):
        exchange = line["exchange"]["rate"] if line.get("exchange") else "1"
        labor.append(
            [
                line["id"],
                line["category_label"],
                line["name"],
                _number(line["quantity"]),
                line["unit"],
                _number(line["rate"]),
                line["rate_currency"],
                _number(exchange),
                None,
                _number(line["amount"]),
                line["basis"],
            ]
        )
        labor.cell(row, 9).value = f"=ROUND(D{row}*F{row}*H{row},{line_decimals})"
        for column in (4, 6):
            labor.cell(row, column).font = INPUT
    _widths(labor, {1: 12, 3: 30, 11: 40})

    _header(mapping, ["來源", "類型", "模組", "採購項", "數量", "經由組件"])
    for line in costing["purchase_lines"]:
        for source in line["sources"]:
            mapping.append(
                [
                    source["id"],
                    "設備對應" if source["type"] == "equipment" else "BOM 列",
                    source.get("module") or "、".join(source.get("modules", [])),
                    line["item"],
                    _number(source["quantity"]),
                    "→".join(source.get("via", [])),
                ]
            )
    _widths(mapping, {1: 16, 3: 20, 4: 16, 6: 24})

    _header(subsystems, ["子系統", "已知小計（公式）", "程式計算值", "下限", "上限", "缺價列數"])
    for row, entry in enumerate(costing["by_subsystem"], start=2):
        subsystems.append(
            [
                entry["subsystem"],
                f"=SUMIF(採購明細!D:D,A{row},採購明細!M:M)",
                _number(entry["known"]),
                _number(entry["low"]),
                _number(entry["high"]),
                entry["missing"],
            ]
        )
    _widths(subsystems, {1: 22, 2: 18, 3: 16})

    _header(missing, ["類型", "項目", "名稱", "數量", "單位", "原因"])
    for entry in costing["missing"]:
        missing.append(
            [
                "採購" if entry["type"] == "purchase" else "工時",
                entry["id"],
                entry["name"],
                _number(entry["quantity"]),
                entry["unit"],
                entry["reason"],
            ]
        )
    if not costing["missing"]:
        missing.append(["—", "", "無缺價項目", "", "", ""])
    _widths(missing, {2: 14, 3: 28, 6: 30})

    _header(issues, ["嚴重度", "代碼", "說明"])
    for issue in costing["issues"]:
        issues.append([issue["severity"], issue["code"], issue["message"]])
    if not costing["issues"]:
        issues.append(["—", "", "無"])
    _widths(issues, {2: 22, 3: 90})

    policy = costing["policy"]
    pricing = policy.get("pricing")
    summary.append([f"成本估算｜{version.get('project_name', '')}｜{version['version']}"])
    summary["A1"].font = Font(bold=True, size=14)
    summary.append(
        [
            f"幣別 {costing['currency']}｜估算基準日 {costing['as_of']}｜"
            + (
                "已涵蓋全部項目"
                if costing["complete"]
                else "含缺價項目：以下為已知成本小計，不是完整總額"
            )
        ]
    )
    summary.append([])
    summary.append(["參數（藍字可改）", "值", "說明"])
    parameters = [
        ("管理費率", policy["overhead_rate"], "基底：設備成本＋專案開發成本"),
        ("預備費率", policy["contingency_rate"], "基底：設備成本＋專案開發成本＋管理費"),
        ("稅率", policy["tax_rate"], "預算稅額＝稅率 × 成本合計；報價稅額＝稅率 × 售價"),
    ]
    if pricing:
        label = "毛利率" if pricing["method"] == "margin" else "加價率"
        parameters.append((label, pricing["rate"], pricing.get("basis") or ""))
    first_parameter = summary.max_row + 1
    for label, value, note in parameters:
        summary.append([label, _number(value), note])
        summary.cell(summary.max_row, 2).font = INPUT
    cell = {
        label: f"B{first_parameter + index}" for index, (label, _v, _n) in enumerate(parameters)
    }
    summary.append([])
    summary.append(["項目", "金額（公式）", "程式計算值", "下限", "上限", "公式"])
    for header_cell in summary[summary.max_row]:
        header_cell.font = HEADER
        header_cell.fill = HEADER_FILL
    totals = costing["totals"]
    formulas = costing["formulas"]
    start = summary.max_row + 1
    rows = [
        ("設備成本", 'SUMIF(採購明細!C:C,"<>服務",採購明細!M:M)', "equipment", "equipment"),
        ("人工成本", "SUM(工時!I:I)", "labor", "labor"),
        ("服務", 'SUMIF(採購明細!C:C,"服務",採購明細!M:M)', "services", "development"),
        ("專案開發成本", "B{labor}+B{services}", "development", "development"),
        (
            "管理費",
            f"ROUND({cell['管理費率']}*(B{{equipment}}+B{{development}}),{total_decimals})",
            "overhead",
            "overhead",
        ),
        (
            "預備費",
            f"ROUND({cell['預備費率']}*(B{{equipment}}+B{{development}}+B{{overhead}}),"
            f"{total_decimals})",
            "contingency",
            "contingency",
        ),
        (
            "成本合計（未稅）",
            f"ROUND(B{{equipment}}+B{{development}}+B{{overhead}}+B{{contingency}},{total_decimals})",
            "cost",
            "cost",
        ),
        (
            "預算稅額",
            f"ROUND({cell['稅率']}*B{{cost}},{total_decimals})",
            "budget_tax",
            "budget_tax",
        ),
        ("含稅預算", "B{cost}+B{budget_tax}", "budget_with_tax", "budget_tax"),
    ]
    if pricing:
        rate_cell = cell["毛利率" if pricing["method"] == "margin" else "加價率"]
        price = (
            f"ROUND(B{{cost}}/(1-{rate_cell}),{total_decimals})"
            if pricing["method"] == "margin"
            else f"ROUND(B{{cost}}*(1+{rate_cell}),{total_decimals})"
        )
        rows += [
            ("售價（未稅）", price, "price", pricing["method"]),
            (
                "報價稅額",
                f"ROUND({cell['稅率']}*B{{price}},{total_decimals})",
                "quote_tax",
                "quote_tax",
            ),
            ("含稅報價", "B{price}+B{quote_tax}", "quote_with_tax", "quote_tax"),
        ]
    positions = {key: start + index for index, (_label, _f, key, _fk) in enumerate(rows)}
    for label, formula, key, formula_key in rows:
        total = totals[key]
        summary.append(
            [
                label,
                "=" + formula.format(**positions),
                _number(total["value"]),
                _number(total.get("low")),
                _number(total.get("high")),
                formulas.get(formula_key, ""),
            ]
        )
    summary.append([])
    coverage = costing["coverage"]
    summary.append(
        [
            "估算覆蓋率",
            f"{coverage['priced_lines']}/{coverage['total_lines']}",
            float(Decimal(coverage["ratio"])),
            "",
            "",
            "有單價的列數 ÷ 全部列數；缺價列見「缺價清單」",
        ]
    )
    summary.append(["上下限說明", "", "", "", "", formulas["range"]])
    for note in costing.get("notes", []):
        summary.append(["備註", note])
    _widths(summary, {1: 20, 2: 18, 3: 18, 4: 16, 5: 16, 6: 70})

    version_sheet.append(["項目", "值"])
    for key, value in version.items():
        version_sheet.append([key, str(value)])
    version_sheet.append([])
    version_sheet.append(["匯率", "值", "日期", "來源"])
    for rate in costing["exchange_rates"]:
        version_sheet.append(
            [f"{rate['from']}→{rate['to']}", rate["rate"], rate["date"], rate["source"]]
        )
    version_sheet.append([])
    version_sheet.append(
        [
            "捨入",
            f"明細小數 {line_decimals} 位；預備費、稅額、報價小數 {total_decimals} 位；"
            f"{rounding['mode']}",
        ]
    )
    _widths(version_sheet, {1: 26, 2: 70})
    workbook.save(target)


def write_purchase_csv(costing: dict[str, Any], target: Path) -> None:
    columns = [key for key, _title in PURCHASE_COLUMNS if key is not None]
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [title for key, title in PURCHASE_COLUMNS if key is not None] + ["設備來源"]
        )
        for line in costing["purchase_lines"]:
            writer.writerow([line.get(key) or "" for key in columns] + [_sources(line)])
