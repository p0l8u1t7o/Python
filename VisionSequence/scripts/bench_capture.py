"""擷取端傳輸效能基準：把模擬相機的影像送進伺服端 hub，量伺服端實際收到的 fps 與每張耗時。

用法：
    .venv/Scripts/python.exe scripts/bench_capture.py                    # 20MP 彩色、共享記憶體與 TCP 各跑一輪
    .venv/Scripts/python.exe scripts/bench_capture.py --model 2 --secs 3 # 500 萬畫素
    .venv/Scripts/python.exe scripts/bench_capture.py --transport tcp --encoding lz4
    .venv/Scripts/python.exe scripts/bench_capture.py --channels 2 --mono

預設把擷取端跑成**另一個行程**（和實機一樣，兩邊不搶同一個 GIL），量兩種模式：
- 連續串流：擷取端持續推最新影格，伺服端每張複製一次 → 這是「伺服端 fps」的上限。
- 依需求取像：伺服端每張送一次 GRAB 等回覆（含往返），這是產線觸發式檢測的實際延遲。

輸出伺服端實收 fps、每張接收耗時（複製）與丟幀數。`--inproc` 改成同行程（除錯用，數字偏保守）。
數字會隨機器記憶體頻寬變動；docs/capture-client.html §7 記的是這台開發機的結果。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from apps.vision.capture.hub import CaptureHub  # noqa: E402
from vscapture.cameras.fake import FAKE_MODELS  # noqa: E402
from vscapture.config import AppConfig, CameraParams, ChannelConfig, ConnectionConfig, DeliveryConfig  # noqa: E402
from vscapture.engine import CaptureEngine  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_config(hub_port: int, args: argparse.Namespace, local: bool) -> AppConfig:
    cfg = AppConfig(connection=ConnectionConfig(host="127.0.0.1", port=hub_port, client_name="bench", auto_connect=False, local_mode="auto" if local else "off"))
    for i in range(args.channels):
        cfg.channels.append(ChannelConfig(
            id=f"cam{i + 1}", name=f"bench {i + 1}", backend="fake", device_id=f"fake:{args.model}",
            params=CameraParams(fps=float(args.fps)),
            delivery=DeliveryConfig(encoding=args.encoding, mono=args.mono, mode="on_demand", stream_fps=args.fps, jpeg_quality=args.jpeg_quality),
        ))
    return cfg


class Client:
    """擷取端：預設另起一個行程（實機情境），`--inproc` 則在本行程內跑。"""

    def __init__(self, cfg: AppConfig, inproc: bool) -> None:
        self.inproc = inproc
        self.engine: CaptureEngine | None = None
        self.proc: subprocess.Popen | None = None
        self.tmp = None
        if inproc:
            self.engine = CaptureEngine(cfg)
            self.engine.start(connect=True)
            return
        self.tmp = tempfile.TemporaryDirectory(prefix="vsbench-")
        path = os.path.join(self.tmp.name, "config.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(cfg), fh, ensure_ascii=False)
        env = {**os.environ, "VSCAPTURE_CONFIG": path, "PYTHONIOENCODING": "utf-8"}
        self.proc = subprocess.Popen([sys.executable, "-m", "vscapture", "--headless", "--connect", "--log-level", "WARNING"],
                                     cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self) -> None:
        if self.engine is not None:
            self.engine.stop()
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.tmp is not None:
            self.tmp.cleanup()


def wait_for(fn, timeout: float = 10.0) -> bool:
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if fn():
            return True
        time.sleep(0.02)
    return False


def report(label: str, spans: list[float], nbytes: int, extra: str = "") -> None:
    if not spans:
        print(f"{label:<26} —（沒有影格）")
        return
    spans.sort()
    med = statistics.median(spans)
    p95 = spans[min(len(spans) - 1, int(len(spans) * 0.95))]
    fps = 1000.0 / med if med else 0.0
    print(f"{label:<26} {len(spans):>4} 張  中位 {med:6.2f} ms  p95 {p95:6.2f} ms  → {fps:6.1f} fps  {nbytes * fps / 1e6:7.0f} MB/s  {extra}")


def run_stream(hub: CaptureHub, cid: str, secs: float, nbytes: int) -> None:
    """連續串流：擷取端一直推，量伺服端這段時間實際收到幾張（不派 Python 消費者，避免自己變成瓶頸）。"""
    hub.acquire_stream("bench", cid, "bench")
    time.sleep(0.5)  # 讓推送執行緒起來
    session = hub.get("bench")
    ch = session.channel(cid)
    seq0, t0 = ch.last_seq, time.perf_counter()
    time.sleep(secs)
    got, elapsed = ch.last_seq - seq0, time.perf_counter() - t0
    recv_ms, inst = ch.rate.recv_ms, ch.rate.fps
    hub.release_stream("bench", cid, "bench")
    fps = got / elapsed if elapsed else 0.0
    print(f"{'  連續串流':<24} {got:>4} 張 / {elapsed:.1f} 秒  → {fps:6.1f} fps  {nbytes * fps / 1e6:7.0f} MB/s  伺服端複製 {recv_ms:5.2f} ms（瞬時 {inst:.0f} fps）")


def run_on_demand(hub: CaptureHub, cid: str, secs: float, nbytes: int) -> None:
    session = hub.get("bench")
    spans: list[float] = []
    end = time.perf_counter() + secs
    errors = 0
    while time.perf_counter() < end:
        t0 = time.perf_counter()
        try:
            session.request_frame(cid, timeout=2.0, after_request=True)
        except Exception:  # noqa: BLE001
            errors += 1
            continue
        spans.append((time.perf_counter() - t0) * 1000)
    ch = session.channel(cid)
    report("  依需求取像（含往返）", spans, nbytes, f"伺服端複製 {ch.rate.recv_ms:5.2f} ms" + (f"  失敗 {errors}" if errors else ""))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="擷取端傳輸效能基準")
    p.add_argument("--model", type=int, default=3, help=f"模擬相機機種 0～{len(FAKE_MODELS) - 1}（預設 3＝5472×3648）")
    p.add_argument("--channels", type=int, default=1)
    p.add_argument("--secs", type=float, default=3.0, help="每種模式量測秒數")
    p.add_argument("--fps", type=float, default=120.0, help="相機影格率上限（模擬相機最高 120）")
    p.add_argument("--encoding", default="raw", choices=["raw", "lz4", "jpeg"])
    p.add_argument("--jpeg-quality", type=int, default=90)
    p.add_argument("--mono", action="store_true", help="擷取端轉單色後傳送")
    p.add_argument("--transport", default="both", choices=["shm", "tcp", "both"])
    p.add_argument("--inproc", action="store_true", help="擷取端跑在同一個行程（除錯用；兩邊搶同一個 GIL，數字偏保守）")
    args = p.parse_args(argv)

    w, h = FAKE_MODELS[args.model]
    channels = 1 if args.mono else 3
    nbytes = w * h * channels
    print(f"影格 {w}×{h}×{channels} = {nbytes / 1e6:.1f} MB／張；60 fps 需要 {nbytes * 60 / 1e9:.2f} GB/s，每張預算 16.7 ms")
    print(f"通道 {args.channels} 個、編碼 {args.encoding}、相機上限 {args.fps:g} fps、擷取端{'同行程' if args.inproc else '獨立行程'}\n")

    for local in ([True, False] if args.transport == "both" else [args.transport == "shm"]):
        port = free_port()
        hub = CaptureHub()
        hub.start("127.0.0.1", port)
        client = Client(make_config(port, args, local), args.inproc)
        try:
            if not wait_for(lambda: hub.get("bench") is not None and len(hub.get("bench").channels) >= args.channels, 20.0):
                print("擷取端沒有連上，跳過")
                continue
            if local and not wait_for(lambda: hub.get("bench").shm is not None, 5.0):
                print("共享記憶體協商失敗，跳過")
                continue
            session = hub.get("bench")
            print(f"[{'共享記憶體（同一台電腦）' if session.shm is not None else 'TCP（本機 loopback；跨電腦另受網路頻寬限制）'}]")
            for cid in [c["id"] for c in session.to_dict()["channels"][:1]]:
                run_stream(hub, cid, args.secs, nbytes)
                run_on_demand(hub, cid, args.secs, nbytes)
            print()
        finally:
            client.stop()
            hub.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
