#!/usr/bin/env python
"""一鍵啟動：啟動 HTTP 服務並開啟瀏覽器。

    python run.py                 # 預設 127.0.0.1:8848
    python run.py --port 9000
    python run.py --no-browser    # 不自動開瀏覽器（伺服器部署用）
    python run.py --seed-demo 20  # 啟動前先產生 20 批合成資料
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    ap = argparse.ArgumentParser(description="ExpAnalysis 製程分析平台")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--reload", action="store_true", help="開發模式：改檔自動重載")
    ap.add_argument("--seed-demo", type=int, metavar="N",
                    help="啟動前產生 N 批合成資料（會清空既有資料）")
    args = ap.parse_args()

    from expanalysis.config import SETTINGS
    from expanalysis.logging_setup import setup_logging

    setup_logging(SETTINGS.log_level, SETTINGS.log_dir)
    host = args.host or SETTINGS.host
    port = args.port or SETTINGS.port

    if args.seed_demo:
        from expanalysis.data.synthetic import SyntheticConfig, seed_database
        from expanalysis.service import get_service
        svc = get_service()
        seed_database(svc.repo, SyntheticConfig(n_batches=args.seed_demo))
        svc.invalidate()
        print(f"已產生 {args.seed_demo} 批合成資料。")

    url = f"http://{host}:{port}/"
    if not args.no_browser:
        def _open():
            time.sleep(1.5)
            try:
                webbrowser.open(url)
            except Exception:            # noqa: BLE001 - 開瀏覽器失敗不該擋住服務
                pass
        threading.Thread(target=_open, daemon=True).start()

    print(f"\n  ExpAnalysis 已啟動 → {url}")
    print(f"  API 文件           → {url}api/docs")
    print(f"  說明文件           → {url}docs/\n")

    import uvicorn
    uvicorn.run("expanalysis.api.app:app", host=host, port=port,
                reload=args.reload, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
