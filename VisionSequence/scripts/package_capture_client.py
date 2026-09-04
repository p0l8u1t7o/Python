"""把 PyInstaller 產出的擷取端資料夾打成 zip，放到 data/downloads/ 並寫 manifest.json（網頁「下載擷取端」讀它）。

    python scripts/package_capture_client.py --dist build/capture/dist/VisionSequenceCapture --out data/downloads [--version 0.1.0] [--sdks pypylon,ids_peak] [--keep-old]

由 scripts/build_capture_client.ps1 呼叫；`package()` 也給測試用。zip 頂層是 `VisionSequenceCapture-<版本>/`，內含 README.txt。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIP_PREFIX = "VisionSequenceCapture-"
SDK_LABELS = {"pypylon": "Basler（pylon）", "ids_peak": "IDS peak", "pyueye": "IDS uEye（舊款）", "pygrabber": "網路攝影機名稱列舉"}


def readme_text(version: str, sdks: list[str]) -> str:
    bundled = "、".join(SDK_LABELS.get(s, s) for s in sdks) if sdks else "無（只有網路攝影機／USB 相機與模擬相機）"
    return f"""VisionSequence 擷取端 {version}
==========================================

用途：在相機所在的電腦直接驅動相機（網路攝影機／USB 相機、Basler、IDS），把影像送到 VisionSequence 伺服端；
同一台電腦以共享記憶體傳送，不同電腦以單一 TCP 連線無損傳送。

安裝
  1. 解壓縮到任意資料夾（避免過長的路徑；不需要管理員權限）。
  2. 執行 VisionSequenceCapture.exe（視窗版）。第一次執行若 Windows SmartScreen 提示「未知的發行者」，
     請選「其他資訊」→「仍要執行」。
  3. 在「連線」填入伺服端位址（預設埠 9100）與擷取端名稱，點選「連線」。
  4. 在「通道」新增相機、開啟並開始取像；回到網頁「影像來源」新增「擷取端相機」，選這台擷取端與通道。

主控台版（無介面）
  VisionSequenceCapture-console.exe --headless --connect          連線並常駐（Ctrl+C 結束），適合 Task Scheduler／NSSM
  VisionSequenceCapture-console.exe --list-cameras                列出各種相機
  其他參數：--server host:port、--name 名稱、--api-key 金鑰、--config 設定檔、--log-level DEBUG

設定檔：%APPDATA%\\VisionSequenceCapture\\config.json
記錄檔：%APPDATA%\\VisionSequenceCapture\\logs\\

本版本內含的相機支援：{bundled}
  - Basler：客戶端電腦請安裝 pylon Camera Software Suite（含 USB3／GigE 驅動）。
  - IDS：客戶端電腦請安裝 IDS peak（新款）或 uEye 驅動（舊款）。
  - 網路攝影機／USB 相機：Windows 內建，不需另裝。

說明文件：伺服端網頁 → 說明 → 擷取端（docs/capture-client.html）。
"""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def package(dist: Path, out: Path, version: str, *, sdks: list[str] | None = None, keep_old: bool = False) -> dict:
    """把 dist 資料夾壓成 out/VisionSequenceCapture-<version>-win64.zip 並寫 manifest.json；回 manifest 內容。"""
    dist = Path(dist)
    out = Path(out)
    if not dist.is_dir():
        raise FileNotFoundError(f"找不到建置產物資料夾：{dist}")
    sdks = [s for s in (sdks or []) if s]
    out.mkdir(parents=True, exist_ok=True)
    filename = f"{ZIP_PREFIX}{version}-win64.zip"
    top = f"{ZIP_PREFIX}{version}"
    target = out / filename
    tmp = out / (filename + ".tmp")
    count = 0
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(f"{top}/README.txt", readme_text(version, sdks).replace("\n", "\r\n"))
        for path in sorted(dist.rglob("*")):
            if path.is_dir():
                continue
            zf.write(path, f"{top}/{path.relative_to(dist).as_posix()}")
            count += 1
    os.replace(tmp, target)
    manifest = {
        "version": version,
        "filename": filename,
        "size": target.stat().st_size,
        "sha256": _sha256(target),
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "files": count,
        "sdks": sdks,
        "python": ".".join(str(p) for p in sys.version_info[:3]),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not keep_old:
        for old in out.glob(f"{ZIP_PREFIX}*.zip"):
            if old.name != filename:
                old.unlink()
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="打包擷取端 zip 與 manifest.json")
    p.add_argument("--dist", required=True, help="PyInstaller 產出的資料夾（含 VisionSequenceCapture.exe）")
    p.add_argument("--out", default=str(ROOT / "data" / "downloads"), help="輸出資料夾（預設 data/downloads）")
    p.add_argument("--version", default=None, help="版本（預設讀 vscapture.__version__）")
    p.add_argument("--sdks", nargs="?", const="", default="", help="打進去的相機 SDK 模組名，逗號分隔（寫進 README 與 manifest）")
    p.add_argument("--keep-old", action="store_true", help="保留舊版 zip（預設只留這一版）")
    args = p.parse_args(argv)
    version = args.version
    if not version:
        sys.path.insert(0, str(ROOT))
        import vscapture

        version = vscapture.__version__
    manifest = package(Path(args.dist), Path(args.out), version, sdks=[s.strip() for s in args.sdks.split(",") if s.strip()], keep_old=args.keep_old)
    print(f"{manifest['filename']}  {manifest['size']} 位元組  sha256 {manifest['sha256'][:16]}…  檔案 {manifest['files']} 個")
    return 0


if __name__ == "__main__":
    sys.exit(main())
