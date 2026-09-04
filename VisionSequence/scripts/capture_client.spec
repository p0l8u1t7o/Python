# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：擷取端（VisionSequenceCapture）。

由 scripts/build_capture_client.ps1 呼叫；也可手動：
    .venv-capture\\Scripts\\python.exe -m PyInstaller --noconfirm scripts\\capture_client.spec
一次 Analysis 產兩個執行檔（視窗版 VisionSequenceCapture.exe、主控台版 VisionSequenceCapture-console.exe），
共用同一個資料夾（onedir，啟動快、防毒誤判少）。相機 SDK（pypylon／ids_peak／pyueye）只在建置機有裝時才會打進去。
"""

import sys
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 — SPECPATH 由 PyInstaller 注入
sys.path.insert(0, str(ROOT))
import vscapture  # noqa: E402

VERSION = vscapture.__version__
ICON = ROOT / "vscapture" / "resources" / "icon.ico"
ENTRY = ROOT / "vscapture" / "__main__.py"

hiddenimports = collect_submodules("vscapture")
datas: list = [(str(ICON), "vscapture/resources")] if ICON.is_file() else []
binaries: list = []
# 不需要的大模組與 Qt 子模組（介面只用 QtCore／QtGui／QtWidgets）
excludes = [
    "torch", "torchvision", "ultralytics", "tkinter", "matplotlib", "scipy", "pandas", "IPython", "jupyter", "PyQt5", "PyQt6", "django", "tests",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtLocation", "PySide6.QtPositioning", "PySide6.QtRemoteObjects",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtWebSockets", "PySide6.QtWebChannel",
    "PySide6.QtWebView", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvgWidgets", "PySide6.QtNetworkAuth",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtHttpServer", "PySide6.QtAxContainer",
    "PySide6.QtPrintSupport", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtAsyncio", "PySide6.QtExampleIcons",
]

# 選配相機 SDK：建置機有裝才收進來（pypylon 的 DLL 由 collect_dynamic_libs 抓；IDS peak 的 .pyd 與資料用 collect_all）
if find_spec("pypylon"):
    binaries += collect_dynamic_libs("pypylon")
    datas += collect_data_files("pypylon")
    hiddenimports += collect_submodules("pypylon")
for mod in ("ids_peak", "ids_peak_ipl", "pyueye", "pygrabber"):
    if find_spec(mod):
        d, b, h = collect_all(mod)
        datas += d
        binaries += b
        hiddenimports += h

a = Analysis(  # noqa: F821
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821


def _version_info():
    """exe 的檔案版本資訊（檔案總管「詳細資料」）；非 Windows 或缺模組時省略。"""
    try:
        from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo
    except Exception:  # noqa: BLE001
        return None
    parts = [int(p) if p.isdigit() else 0 for p in VERSION.split(".")][:4]
    nums = tuple(parts + [0] * (4 - len(parts)))
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040404B0", [
                StringStruct("CompanyName", "VisionSequence"),
                StringStruct("FileDescription", "VisionSequence 擷取端"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "VisionSequenceCapture"),
                StringStruct("OriginalFilename", "VisionSequenceCapture.exe"),
                StringStruct("ProductName", "VisionSequence Capture"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [1028, 1200])]),
        ],
    )


_common = dict(
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    icon=str(ICON) if ICON.is_file() else None,
    version=_version_info(),
    disable_windowed_traceback=False,
    target_arch=None,
)
exe_gui = EXE(pyz, a.scripts, [], name="VisionSequenceCapture", console=False, **_common)  # noqa: F821
exe_cli = EXE(pyz, a.scripts, [], name="VisionSequenceCapture-console", console=True, **_common)  # noqa: F821
coll = COLLECT(exe_gui, exe_cli, a.binaries, a.datas, strip=False, upx=False, name="VisionSequenceCapture")  # noqa: F821
