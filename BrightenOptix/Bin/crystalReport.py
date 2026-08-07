import os
import subprocess
import tempfile
from xml.sax.saxutils import escape

from openpyxl import load_workbook

_HELPER_DIR = os.path.join(os.path.dirname(__file__), "CrystalPrintHelper")
_HELPER_EXE = os.path.join(_HELPER_DIR, "CrystalPrintHelper.exe")
_BUILD_SCRIPT = os.path.join(_HELPER_DIR, "build.ps1")


#============================================================================================================================================#
# 若 CrystalPrintHelper.exe 尚未建置，先用 build.ps1 編譯一份

def _ensure_helper_built() -> bool:
    if os.path.exists(_HELPER_EXE):
        return True

    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", _BUILD_SCRIPT],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"編譯 CrystalPrintHelper.exe 失敗：{result.stderr or result.stdout}")
        return False

    return os.path.exists(_HELPER_EXE)


#============================================================================================================================================#
# 讀取 Excel（第一列為欄位名稱、第二列為對應數值），組成 Crystal Reports 可讀取的
# ADO.NET DataSet XML（未夾帶 xs:schema，交由 DataSet.ReadXml 自動推斷欄位型別）

def _build_dataset_xml_from_excel(xlsx_path: str, table_name: str) -> str:
    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb.active

    headers = [cell.value for cell in ws[1]]
    values = [cell.value for cell in ws[2]]

    fields_xml = "".join(
        f"    <{header}>{escape(str(value))}</{header}>\n"
        for header, value in zip(headers, values)
        if header and value is not None
    )

    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<NewDataSet>\n"
        f"  <{table_name}>\n"
        f"{fields_xml}"
        f"  </{table_name}>\n"
        "</NewDataSet>\n"
    )

    fd, temp_path = tempfile.mkstemp(suffix=".xml", prefix="crystal_dataset_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(xml_content)

    return temp_path


#============================================================================================================================================#
# 開啟 .rpt 報表，套用 XML 資料來源，並送到印表機列印
#
# 實際的 Crystal Reports 呼叫是交給獨立編譯的 CrystalPrintHelper.exe 執行（見
# CrystalPrintHelper/Program.cs），因為部分 Crystal Reports 驅動元件是針對 CLR v2.0
# 編譯的混合模式組件，無法在 64 位元 Python 目前使用的 CLR v4 環境下以 in-process
# side-by-side 方式載入；獨立的 exe 則是以 CLR v2.0 啟動整個處理序，不受此限制。

def print_rpt_with_xml(
    rpt_path: str,
    xml_path: str,
    printer_name: str = "",
    ignore_missing_ufl: bool = False,
    rotation: int = 0,
    offset_x: int = 0,
    offset_y: int = 0,
) -> bool:
    if not rpt_path.strip() or not xml_path.strip():
        return False

    if not os.path.exists(rpt_path):
        print(f"找不到報表檔案：{rpt_path}")
        return False

    if not os.path.exists(xml_path):
        print(f"找不到報表資料檔案：{xml_path}")
        return False

    if rotation not in (0, 90, 180, 270):
        print(f"rotation 必須是 0、90、180 或 270，收到：{rotation}")
        return False

    if not _ensure_helper_built():
        return False

    args = [_HELPER_EXE, rpt_path, xml_path]
    if printer_name:
        args += ["--printer", printer_name]
    if ignore_missing_ufl:
        args.append("--ignore-missing-ufl")
    if rotation:
        args += ["--rotation", str(rotation)]
    if offset_x:
        args += ["--offset-x", str(offset_x)]
    if offset_y:
        args += ["--offset-y", str(offset_y)]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"列印報表時發生錯誤：{result.stderr or result.stdout}")
        return False

    return True


#============================================================================================================================================#
# 開啟 .rpt 報表，套用 Excel（第一列欄位名稱、第二列數值）作為資料來源，並送到印表機列印
#
# rotation：0、90、180 或 270 度。180/270 並非標準 Win32 印表機方向值（官方只定義了
#     0/90），能否生效視印表機驅動是否支援而定，需搭配實際印出的標籤確認。
# offset_x、offset_y：頁面邊界位移量，單位為百分之一英吋（0.01"），用來微調列印
#     內容在標籤紙上的位置。

def print_rpt_with_excel(
    rpt_path: str,
    xlsx_path: str,
    table_name: str,
    printer_name: str = "",
    ignore_missing_ufl: bool = False,
    rotation: int = 0,
    offset_x: int = 0,
    offset_y: int = 0,
) -> bool:
    if not rpt_path.strip() or not xlsx_path.strip():
        return False

    if not os.path.exists(rpt_path):
        print(f"找不到報表檔案：{rpt_path}")
        return False

    if not os.path.exists(xlsx_path):
        print(f"找不到報表資料檔案：{xlsx_path}")
        return False

    xml_path = _build_dataset_xml_from_excel(xlsx_path, table_name)
    try:
        return print_rpt_with_xml(
            rpt_path, xml_path, printer_name, ignore_missing_ufl,
            rotation, offset_x, offset_y,
        )
    finally:
        os.remove(xml_path)


#============================================================================================================================================#

if __name__ == "__main__":
    # ignore_missing_ufl=True 暫時繞過缺少 IDAutomation Data Matrix UFL 的問題
    # （條碼欄位會印成空白），待安裝好正式的 UFL 元件後應移除這個參數。
    #
    # rotation/offset_x/offset_y 用來調整列印位置與方向，請依實際列印出的標籤紙
    # 調整數值。
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    rpt_file = os.path.join(data_dir, "csfr010zd_0_std_2.rpt")
    xlsx_file = os.path.join(data_dir, "Print Database.xlsx")
    print_rpt_with_excel(
        rpt_file, xlsx_file, "csfr010zd", "Godex ZX1600i+",
        ignore_missing_ufl=False, rotation=0, offset_x=0, offset_y=0,
    )
