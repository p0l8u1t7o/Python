"""擷取端程式入口：`python -m vscapture`（桌面 UI）或 `--headless`（背景服務）。"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from vscapture import __version__, config as configmod
from vscapture.config import AppConfig, ChannelConfig, ConfigError, DeliveryConfig
from vscapture.logs import setup_logging

log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="vscapture", description="VisionSequence 擷取端：驅動相機並把影像送到伺服端")
    p.add_argument("--config", help="設定檔路徑（預設 %APPDATA%/VisionSequenceCapture/config.json）")
    p.add_argument("--headless", action="store_true", help="不開介面，只連線並服務伺服端")
    p.add_argument("--connect", action="store_true", help="啟動就連線（忽略設定檔的自動連線）")
    p.add_argument("--minimized", action="store_true", help="啟動時縮到系統匣")
    p.add_argument("--server", help="伺服端位址 host:port（覆寫設定檔）")
    p.add_argument("--name", help="擷取端名稱（覆寫設定檔）")
    p.add_argument("--api-key", help="登錄金鑰（覆寫設定檔）")
    p.add_argument("--fake", type=int, default=0, metavar="N", help="加入 N 個模擬相機通道（示範／測試）")
    p.add_argument("--list-cameras", action="store_true", help="列出各種相機並結束")
    p.add_argument("--log-level", default=None)
    p.add_argument("--version", action="version", version=f"VisionSequenceCapture {__version__}")
    return p.parse_args(argv)


def build_config(args: argparse.Namespace) -> tuple[AppConfig, Path | None, str]:
    """載入設定並套用命令列覆寫；回 (設定, 路徑, 錯誤訊息)。設定檔壞掉時用預設值並回傳錯誤（UI 顯示、不覆蓋檔案）。"""
    path = Path(args.config) if args.config else None
    error = ""
    try:
        cfg = configmod.load(path)
    except ConfigError as exc:
        cfg, error = AppConfig(), str(exc)
    if args.server:
        host, _, port = args.server.rpartition(":")
        cfg.connection.host = host or args.server
        if port.isdigit():
            cfg.connection.port = int(port)
    if args.name:
        cfg.connection.client_name = args.name[:64]
    if args.api_key is not None:
        cfg.connection.api_key = args.api_key
    if args.log_level:
        cfg.log_level = args.log_level.upper()
    for i in range(int(args.fake or 0)):
        cid = configmod.new_channel_id(c.id for c in cfg.channels)
        cfg.channels.append(ChannelConfig(id=cid, name=f"模擬相機 {i}", backend="fake", device_id=f"fake:{i % 2}", delivery=DeliveryConfig(encoding="raw")))
    return cfg, path, error


def build_engine(args: argparse.Namespace):
    from vscapture.engine import CaptureEngine

    cfg, path, error = build_config(args)
    engine = CaptureEngine(cfg, config_path=path)
    engine.config_error = error  # type: ignore[attr-defined]
    return engine


def list_cameras() -> int:
    from vscapture import cameras

    for info in cameras.describe_backends():
        print(f"[{info['label']}] {'可用' if info['available'] else '不可用：' + info['reason']}")
        if info["available"]:
            try:
                devices = cameras.backend_class(info["backend"]).enumerate()
            except Exception as exc:  # noqa: BLE001
                print(f"  列舉失敗：{exc}")
                continue
            for d in devices or []:
                print(f"  {d.device_id}\t{d.label}" + (f"\t{d.model} {d.serial}".rstrip() if d.model or d.serial else ""))
            if not devices:
                print("  （沒有找到裝置）")
    return 0


def run_headless(engine) -> int:
    stop = {"flag": False}

    def handler(signum, frame):  # noqa: ARG001
        stop["flag"] = True

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
    engine.start(connect=True)
    log.info("擷取端 headless 執行中（Ctrl+C 結束）；通道 %d 個", len(engine.channels))
    try:
        while not stop["flag"]:
            time.sleep(0.5)
    finally:
        engine.stop()
    return 0


def run_gui(engine, args: argparse.Namespace) -> int:
    from vscapture.ui.main_window import run_app

    return run_app(engine, minimized=bool(args.minimized or engine.cfg.ui.start_minimized), connect=bool(args.connect))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_cameras:
        setup_logging("WARNING", to_file=False)
        return list_cameras()
    engine = build_engine(args)
    setup_logging(engine.cfg.log_level, to_file=True)
    if getattr(engine, "config_error", ""):
        log.error("設定檔有誤，改用預設值：%s", engine.config_error)
    if args.headless:
        return run_headless(engine)
    return run_gui(engine, args)


if __name__ == "__main__":
    sys.exit(main())
