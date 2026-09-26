"""
產生 docs/cost-estimate.xlsx（快門葉片＋上蓋組裝站，預算級估價）並印出摘要數字給 cost-estimate.md。

    python tools/build_cost_estimate.py

藍字為可改的單價、數量、費率；數量 0 的選配不計入。金額為內部預算估計，非供應商報價。
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parents[1] / "docs" / "cost-estimate.xlsx"

ENG_RATE, TECH_RATE, CONTINGENCY, TAX = 8000, 5500, 0.15, 0.05
GRADES = {"A": (0.10, "型錄價或近期同級採購價"), "B": (0.20, "同級品預算價，需詢價"), "C": (0.30, "自製或規格未定，幅度較大")}

# (編號, 子系統, 項目, 規格要求, 建議選型, 選型理由, 數量, 單位, 單價, 等級)
ITEMS = [
    ("1-01", "1 手臂", "SCARA 手臂＋控制器", "動作範圍 ≥ 600 mm、Z 行程 200 mm、重複精度 ±0.01 mm 級", "DENSO HSR065＋RC8A＋教導器", "依選項對話指定 DENSO SCARA；HSR048 搆不到抽屜外側格", 1, "套", 950000, "B"),
    ("1-02", "1 手臂", "程式與通訊授權", "EtherNet/IP、WINCAPS 離線程式", "RC8A 通訊選配＋WINCAPS III", "與 PLC 交握、備份程式", 1, "式", 60000, "B"),
    ("2-01", "2 末端工具", "T1 葉片吸嘴", "多孔陶瓷吸盤 1.4 × 5 mm、XY 浮動 ±0.05 mm、白色背景板", "自製＋多孔陶瓷吸盤", "薄片不吸凹；浮動讓銷導正葉片孔", 1, "組", 45000, "C"),
    ("2-02", "2 末端工具", "T2 上蓋吸盤＋荷重元", "外框吸盤 17.8 × 16.8、50 N 荷重元＋放大器", "自製框＋50 N 小型荷重元", "壓合時量力對行程，判定卡勾", 1, "組", 85000, "B"),
    ("2-03", "2 末端工具", "T3 本體夾爪", "微型平行夾爪、ESD PEEK 夾指、夾持感測", "SMC MHF2 或同級", "夾本體側面自動對中", 1, "組", 60000, "B"),
    ("2-04", "2 末端工具", "氣動滑台與電磁閥", "12 mm 行程 ×3、真空產生器 ×2、真空開關", "SMC MXQ／ZK2 或同級", "只有使用中的工具伸出", 1, "組", 60000, "B"),
    ("2-05", "2 末端工具", "工具板與管線", "6061 陽極、線管、快換定位", "自製", "", 1, "式", 50000, "C"),
    ("3-01", "3 視覺", "上視相機組", "5MP GigE＋0.35× 遠心鏡頭＋同軸光", "IDS GigE 5MP＋遠心鏡頭", "無透視誤差，量孔位最準", 1, "組", 150000, "B"),
    ("3-02", "3 視覺", "下視相機組", "5MP GigE＋20 mm 鏡頭＋環形光", "IDS GigE 5MP", "定位銷、檢查葉片與成品", 1, "組", 80000, "B"),
    ("3-03", "3 視覺", "視覺主機與軟體", "工業電腦、GigE 網卡、視覺平台授權", "工業電腦＋自家視覺平台", "記錄偏移量、影像與壓合曲線", 1, "套", 180000, "B"),
    ("3-04", "3 視覺", "校正治具", "點陣標定片、J4 旋轉中心校正件", "玻璃標定片＋自製件", "手眼校正", 1, "式", 40000, "B"),
    ("4-01", "4 治具與供料", "組裝治具", "精密槽＋0.3、推塊氣缸 ×2、真空、有料感測；含備品 1 套", "自製（SKD11／陽極鋁）", "基準邊定位、導線槽、夾指避讓槽", 2, "套", 90000, "C"),
    ("4-02", "4 治具與供料", "雙抽屜", "全伸縮滑軌、電磁鎖、在位感測、狀態燈", "自製＋滑軌", "換盤不停機", 2, "組", 120000, "C"),
    ("4-03", "4 治具與供料", "吸塑盤開模", "本體／上蓋／小葉片／大葉片 4 款", "吸塑廠開模", "葉片改用吸塑盤排列（選項對話定案）", 4, "款", 50000, "B"),
    ("4-04", "4 治具與供料", "吸塑盤量產", "每款 60 片（周轉用）", "PET 防靜電", "", 240, "片", 150, "B"),
    ("4-05", "4 治具與供料", "離子風嘴與 NG 盒", "風嘴＋控制器、NG 盒與滿料感測", "Keyence SJ 系列或同級", "消除葉片靜電", 1, "式", 55000, "B"),
    ("5-01", "5 機台與控制", "機台與外罩", "底櫃、20 mm 台面、鋁擠外罩、前門互鎖", "自製", "", 1, "式", 380000, "C"),
    ("5-02", "5 機台與控制", "PLC 與安全", "KV-X＋I/O＋GC-1000 安全控制器", "Keyence", "與 MilitaryGradePC 相同平台", 1, "套", 230000, "A"),
    ("5-03", "5 機台與控制", "電控與氣動", "電控盤、配線、調壓、主電磁閥", "自製", "", 1, "式", 200000, "C"),
    ("5-04", "5 機台與控制", "HMI 與燈號", "觸控 HMI、三色燈、急停", "Keyence VT 或同級", "", 1, "式", 60000, "A"),
    ("6-01", "6 工程", "機構設計", "治具、工具、抽屜、機台", "—", "", 30, "人日", ENG_RATE, "B"),
    ("6-02", "6 工程", "電控設計", "電路、PLC 程式、安全回路", "—", "", 15, "人日", ENG_RATE, "B"),
    ("6-03", "6 工程", "手臂程式", "流程、補正、例外處理", "—", "", 20, "人日", ENG_RATE, "B"),
    ("6-04", "6 工程", "視覺開發", "定位、疊片判定、成品檢查、紀錄", "—", "", 25, "人日", ENG_RATE, "B"),
    ("6-05", "6 工程", "組立配線", "機構組立、配線、配管", "—", "", 25, "人日", TECH_RATE, "B"),
    ("6-06", "6 工程", "試機與驗收", "樣品 POC、節拍調整、驗收", "—", "", 20, "人日", ENG_RATE, "B"),
    ("7-01", "7 選配", "雙吸嘴同取兩片", "第二支 T1 吸嘴＋滑台", "自製", "約省 2.5 s／顆", 0, "組", 70000, "C"),
    ("7-02", "7 選配", "通電開關測試", "端子探針、驅動器、開關動作取像", "自製＋驅動板", "出貨前確認快門動作", 0, "式", 220000, "C"),
    ("7-03", "7 選配", "料盤堆疊供料", "取代抽屜，一次放 10 盤", "自製堆疊機", "換盤間隔拉長到約 1.5 小時", 0, "式", 480000, "C"),
    ("7-04", "7 選配", "柔性振動供料盤", "葉片若無法吸塑盤包裝時的備案（2 台）", "Asyril Asycube 或同級", "維持散料供料", 0, "台", 450000, "B"),
]

HEAD = ["編號", "子系統", "項目", "規格要求", "建議選型", "選型理由", "數量", "單位", "單價 NT$", "小計 NT$", "等級", "下限 NT$", "上限 NT$", "類別"]
BLUE = Font(color="1F4E9E")
BOLD = Font(bold=True)
THIN = Border(bottom=Side(style="thin", color="C9CED6"))
FILL = PatternFill("solid", fgColor="E8EEF6")
MONEY = '#,##0'


def main() -> None:
    wb = Workbook()
    # ---- 明細 ----
    ws = wb.active; ws.title = "明細"
    ws.append(HEAD)
    for c in ws[1]: c.font = BOLD; c.fill = FILL
    for i, it in enumerate(ITEMS, start=2):
        code, sub, name, spec, model, why, qty, unit, price, grade = it
        ws.append([code, sub, name, spec, model, why, qty, unit, price, f"=G{i}*I{i}", grade,
                   f"=J{i}*(1-VLOOKUP(K{i},摘要!$A$12:$B$14,2,FALSE))", f"=J{i}*(1+VLOOKUP(K{i},摘要!$A$12:$B$14,2,FALSE))", int(code.split("-")[0])])
        for col in "GI": ws[f"{col}{i}"].font = BLUE
        for col in "IJLM": ws[f"{col}{i}"].number_format = MONEY
    n = len(ITEMS) + 1
    widths = [7, 14, 20, 40, 26, 30, 7, 6, 12, 13, 6, 13, 13, 6]
    for k, w in enumerate(widths, start=1): ws.column_dimensions[get_column_letter(k)].width = w
    ws.freeze_panes = "A2"

    # ---- 摘要 ----
    s = wb.create_sheet("摘要", 0)
    rows = [
        ["快門葉片＋上蓋組裝站 預算級估價"],
        ["估算日 2026-09-26。單套全新設備、新台幣、未取得供應商報價。"],
        ["一站一套；DENSO HSR065 SCARA；三工具頭（葉片吸嘴／上蓋吸盤含荷重元／本體夾爪）；上視遠心＋下視相機；雙抽屜吸塑盤。"],
        ["參數（藍字可改）"],
        ["工程費率（NT$/人日）", ENG_RATE, "設計、程式、POC 與驗收"],
        ["技術費率（NT$/人日）", TECH_RATE, "組立配線"],
        ["預備費率", CONTINGENCY, "套用設備＋工程＋已選選配"],
        ["營業稅率（預算假設）", TAX, "含稅＝含預備費總額 × (1＋稅率)"],
        [],
        ["估價等級與幅度"],
        ["等級", "幅度", "定義"],
    ]
    for r in rows: s.append(r)
    for g, (rng, txt) in GRADES.items(): s.append([g, rng, txt])
    s.append([])
    s.append(["項目", "金額 NT$", "說明"])
    base = s.max_row
    s.append(["設備與材料（1～5 類）", f'=SUMIFS(明細!$J$2:$J${n},明細!$N$2:$N${n},"<6")', "不含工程人日與選配"])
    s.append(["工程人日（6 類）", f'=SUMIFS(明細!$J$2:$J${n},明細!$N$2:$N${n},6)', "設計、程式、組立與驗收"])
    s.append(["已選選配（7 類）", f'=SUMIFS(明細!$J$2:$J${n},明細!$N$2:$N${n},7)', "數量改為 1 才計入"])
    s.append(["小計（未稅）", f"=SUM(B{base+1}:B{base+3})", ""])
    s.append(["預備費", f"=B{base+4}*B7", ""])
    s.append(["含預備費，未稅", f"=B{base+4}+B{base+5}", "預算主數字"])
    s.append(["下限（含預備費，未稅）", f"=SUM(明細!L2:L{n})*(1+B7)", "逐列幅度加總，不是統計區間"])
    s.append(["上限（含預備費，未稅）", f"=SUM(明細!M2:M{n})*(1+B7)", ""])
    s.append(["含稅預算", f"=B{base+6}*(1+B8)", ""])
    for r in range(base + 1, base + 10): s[f"B{r}"].number_format = MONEY
    for cell in ("B5", "B6", "B7", "B8"): s[cell].font = BLUE
    s["B7"].number_format = s["B8"].number_format = "0%"
    for r in range(12, 15): s[f"B{r}"].number_format = "0%"
    s["A1"].font = Font(bold=True, size=14)
    for r in (4, 10, base): s[f"A{r}"].font = BOLD
    s.column_dimensions["A"].width = 26; s.column_dimensions["B"].width = 16; s.column_dimensions["C"].width = 60

    # ---- 選型計算 ----
    c = wb.create_sheet("選型計算")
    calc = [
        ["選型與數量核對"], [],
        ["項目", "數值", "單位", "依據"],
        ["手臂到最遠料格距離", 555, "mm", "抽屜本體盤外後角格 (−531, −460)，手臂座 (0, −300)"],
        ["HSR065 動作範圍", 650, "mm", "型錄值；HSR048 為 480 mm，不足"],
        ["規劃循環時間", 23.8, "s／顆", "3D 模擬（9 次取像、不含加速選項）"],
        ["人員作業時間（影片目測）", 30, "s／顆", "影片約 66 s 完成約 2 顆"],
        ["每抽屜產品數", 24, "顆", "本體盤 24 格＝葉片盤 48 格 × 2 盤／2"],
        ["換盤間隔", "=B6*B8/60", "分", "作業員約每 9.5 分鐘換一個抽屜"],
        ["每小時產能（稼動 85%）", "=3600/B6*0.85", "顆/h", ""],
        ["葉片孔單邊間隙（暫定）", 0.03, "mm", "孔 φ0.86（假設）− 銷 φ0.80，除以 2"],
        ["精度預算 RSS", "=SQRT(0.01^2+0.003^2+0.005^2+0.005^2+0.005^2+0.003^2)", "mm", "手臂、上視、下視、校正、吸嘴滑動、熱"],
        ["上蓋壓合力（示意）", 15, "N", "荷重元 50 N 量程；待量卡勾扣入力"],
    ]
    for r in calc: c.append(r)
    c["A1"].font = Font(bold=True, size=13)
    for cell in c[3]: cell.font = BOLD
    for w, col in zip([24, 14, 8, 50], "ABCD"): c.column_dimensions[col].width = w
    c["B9"].number_format = c["B10"].number_format = "0.0"; c["B12"].number_format = "0.000"

    # ---- 通訊架構 ----
    t = wb.create_sheet("通訊架構")
    for r in [["通訊與整合範圍"], [], ["裝置", "連接", "介面／協定", "交換內容", "待確認"],
              ["PLC", "DENSO RC8A", "EtherNet/IP", "流程交握、工具 I/O、例外", "RC8A 通訊選配"],
              ["視覺主機", "上視／下視相機", "GigE Vision＋硬體觸發", "影像、偏移量、判定", "取像觸發時序"],
              ["視覺主機", "RC8A", "TCP／EtherNet/IP", "補正量 Δx、Δz、θ", "座標系與手眼校正"],
              ["PLC", "荷重元放大器", "類比或 IO-Link", "壓合力對行程", "取樣頻率"],
              ["PLC", "抽屜、治具、NG 盒", "I/O", "在位、鎖定、夾緊、真空、滿料", ""],
              ["安全控制器", "RC8A、門互鎖、抽屜鎖", "安全 I/O", "急停、門開停機、抽屜區域互鎖", "獨立安全回路"]]:
        t.append(r)
    t["A1"].font = Font(bold=True, size=13)
    for cell in t[3]: cell.font = BOLD
    for w, col in zip([12, 22, 22, 30, 24], "ABCDE"): t.column_dimensions[col].width = w

    # ---- 假設與待確認 ----
    a = wb.create_sheet("假設與待確認")
    for r in [["估價假設與待確認"], [], ["項目", "內容"],
              ["估價基礎", "2026-09-26 內部預算估計，不是供應商報價；型號為建議，採購前需詢價與確認交期。"],
              ["範圍", "單站一套；含治具 2 套（1 套備品）、吸塑盤 4 款開模與周轉盤。"],
              ["不含", "產品零件、廠務（電、氣、網路）改造、MES 介面開發、年度保養合約、銷售毛利。"],
              ["吸塑盤", "葉片改用吸塑盤排列（選項對話定案）；需供應商配合包裝，否則改選配 7-04 柔性供料。"],
              ["節拍", "3D 模擬規劃值 23.8 s／顆，不是驗收承諾；需樣品 POC 確認。"],
              ["精度", "葉片孔徑、撥桿銷徑未提供；間隙與浮動量待葉片圖面確認。"],
              ["壓合力", "15 N 為示意值，待量上蓋卡勾扣入力。"],
              ["上下限", "逐列依等級幅度加總（A ±10%、B ±20%、C ±30%），不是統計信賴區間。"]]:
        a.append(r)
    a["A1"].font = Font(bold=True, size=13)
    for cell in a[3]: cell.font = BOLD
    a.column_dimensions["A"].width = 12; a.column_dimensions["B"].width = 90
    for row in a.iter_rows(min_row=4): row[1].alignment = Alignment(wrap_text=True, vertical="top")
    for sheet in wb:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.row > 1: cell.border = THIN
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)

    # ---- 同樣的算式，印出摘要數字 ----
    sub = lambda lo, hi: sum(q * p for code, *_, q, _u, p, _g in ITEMS if lo <= float(code.split('-')[0]) < hi)
    eq, eng, opt = sub(1, 6), sub(6, 7), sub(7, 8)
    subtotal = eq + eng + opt
    total = subtotal * (1 + CONTINGENCY)
    lo = sum(q * p * (1 - GRADES[g][0]) for *_, q, _u, p, g in ITEMS) * (1 + CONTINGENCY)
    hi = sum(q * p * (1 + GRADES[g][0]) for *_, q, _u, p, g in ITEMS) * (1 + CONTINGENCY)
    print(f"設備與材料 {eq:,.0f}\n工程人日 {eng:,.0f}\n選配 {opt:,.0f}\n小計 {subtotal:,.0f}\n含預備費未稅 {total:,.0f}\n下限 {lo:,.0f}\n上限 {hi:,.0f}\n含稅 {total * (1 + TAX):,.0f}\n項目數 {len(ITEMS)}")


if __name__ == "__main__":
    main()
