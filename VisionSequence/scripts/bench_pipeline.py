"""Conveyor pick latency bench with the real runner and fake capture cameras.

Usage:
    .venv/Scripts/python.exe scripts/bench_pipeline.py
"""

from __future__ import annotations

import os
import logging
import socket
import sys
import tempfile
import threading
import time
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATA_DIR", os.path.join(tempfile.gettempdir(), "vs-codex-testdata"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
logging.getLogger().setLevel(logging.WARNING)

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402

from apps.comm import writers  # noqa: E402
from apps.comm.writers import TcpClientWriter  # noqa: E402
from apps.vision import sources, variables  # noqa: E402
from apps.vision.capture.hub import hub  # noqa: E402
from apps.vision.models import Flow, ImageSource  # noqa: E402
from apps.vision.runner import runner  # noqa: E402
from vscapture.config import AppConfig, CameraParams, ChannelConfig, ConnectionConfig, DeliveryConfig  # noqa: E402
from vscapture.engine import CaptureEngine  # noqa: E402
from vscapture.transport.client import ConnState  # noqa: E402

settings.VISION = {**getattr(settings, "VISION", {}), "KEEP_RUN_IMAGES": 1000, "PERSIST_RUNS": False}
logging.getLogger().setLevel(logging.WARNING)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(fn, timeout: float = 10.0) -> bool:
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if fn():
            return True
        time.sleep(0.02)
    return bool(fn())


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, int(round((len(values) - 1) * p)))
    return values[idx]


def line(label: str, values: list[float], unit: str = "ms") -> None:
    p50, p95 = pct(values, 0.50), pct(values, 0.95)
    if p50 is None or p95 is None:
        print(f"{label:<34} n=0")
    else:
        print(f"{label:<34} n={len(values):>4}  p50={p50:8.3f} {unit}  p95={p95:8.3f} {unit}")


class LineServer(threading.Thread):
    def __init__(self, port: int) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.ready = threading.Event()
        self.stop = threading.Event()
        self.received: dict[str, tuple[float, float, str]] = {}

    def run(self) -> None:
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", self.port))
        server.listen()
        server.settimeout(0.1)
        self.ready.set()
        try:
            while not self.stop.is_set():
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._client, args=(conn,), daemon=True).start()
        finally:
            server.close()

    def _client(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(0.1)
            buf = b""
            while not self.stop.is_set():
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    text = raw.decode("utf-8", errors="replace").strip()
                    run_id = text.split(",", 1)[0]
                    if run_id:
                        self.received[run_id] = (time.perf_counter(), time.time(), text)


class BenchTcpClientWriter(TcpClientWriter):
    def __init__(self, config: dict[str, Any], *, send_times: dict[str, float], **kw: Any) -> None:
        self.send_times = send_times
        super().__init__(config, **kw)

    def _write(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.sock is None:
            self._open()
        payload = self.render(values)
        run_id = str(values.get("line") or payload).split(",", 1)[0].strip()
        self.sock.settimeout(self.timeout)
        t0 = time.perf_counter()
        self.sock.sendall(payload.encode(self.encoding))
        if run_id:
            self.send_times[run_id] = t0
        self.last_payload = payload
        return {"written": len(values), "payload": payload}


def make_capture_config(port: int) -> AppConfig:
    cfg = AppConfig(
        connection=ConnectionConfig(host="127.0.0.1", port=port, client_name="bench-pipeline", auto_connect=False, local_mode="auto"),
        channels=[],
    )
    for cid in ("cam1", "cam2"):
        cfg.channels.append(ChannelConfig(
            id=cid,
            name=cid,
            backend="fake",
            device_id="fake:2",
            params=CameraParams(fps=60.0),
            delivery=DeliveryConfig(encoding="raw", mode="stream", stream_fps=60.0),
        ))
    return cfg


def make_flow(source: ImageSource, suffix: str) -> Flow:
    graph = {
        "nodes": [
            {"id": "src", "type": "image_source", "params": {"source_id": source.id}},
            {"id": "infer", "type": "blob", "params": {"threshold_method": "fixed", "threshold": 80, "polarity": "bright", "min_area": 400, "max_count": 20, "min_count": 0}},
            {"id": "edge", "type": "edge_filter", "params": {"margin_top": 2, "margin_bottom": 2, "margin_left": 2, "margin_right": 2}},
            {"id": "track", "type": "track_objects", "params": {"state_name": "bench_conveyor_b", "max_distance": 0, "max_missing": 0, "confirm_frames": 1}},
            {"id": "fmt", "type": "format_text", "params": {"name": "line", "each_template": "{run_id},{index},{centroid[0]:.2f},{centroid[1]:.2f},0.00", "join": "\\n"}},
            {"id": "tcp", "type": "write_modbus", "params": {"connection": "bench-robot", "mapping": [{"src": "line", "address": "line"}], "on_error": "warn"}},
        ],
        "edges": [
            {"source": "src", "target": "infer", "source_handle": "image", "target_handle": "image"},
            {"source": "infer", "target": "edge", "source_handle": "blobs", "target_handle": "matches"},
            {"source": "src", "target": "edge", "source_handle": "image", "target_handle": "image"},
            {"source": "edge", "target": "track", "source_handle": "matches", "target_handle": "matches"},
            {"source": "track", "target": "fmt", "source_handle": "new_confirmed", "target_handle": "items"},
            {"source": "fmt", "target": "tcp", "source_handle": "text", "target_handle": "values"},
        ],
    }
    return Flow.objects.create(name=f"bench conveyor latency {suffix}", graph=graph, continuous_interval_ms=0)


def collect_reports(flow_id: int) -> list[Any]:
    return [r for r in runner.runtime(flow_id).recent if r.trigger == "continuous"]


def main() -> int:
    call_command("migrate", interactive=False, run_syncdb=True, verbosity=0)
    variables.store.clear()
    writers.close_all()
    sources.close_all()

    hub_port = free_port()
    tcp_port = free_port()
    send_times: dict[str, float] = {}
    server = LineServer(tcp_port)
    server.start()
    if not server.ready.wait(2.0):
        print("TCP server did not start")
        return 2

    hub.start("127.0.0.1", hub_port)
    capture = CaptureEngine(make_capture_config(hub_port))
    capture.start(connect=False)
    writer = BenchTcpClientWriter(
        {"host": "127.0.0.1", "port": tcp_port, "timeout_s": 1.0, "template": "{line}", "newline": "\n", "queue": True, "queue_size": 256},
        name="bench-robot",
        send_times=send_times,
    )
    writers.register_writer("bench-robot", writer)

    flow: Flow | None = None
    source: ImageSource | None = None
    try:
        capture.connect()
        if not wait_for(lambda: capture.transport.state == ConnState.CONNECTED and hub.get("bench-pipeline") is not None, 10.0):
            print(f"capture did not connect: {capture.transport.state} {capture.transport.state_detail}")
            return 2
        if not wait_for(lambda: hub.get("bench-pipeline").shm is not None, 5.0):  # type: ignore[union-attr]
            print("shared memory was not negotiated")
            return 2

        suffix = str(int(time.time() * 1000))
        source = ImageSource.objects.create(
            name=f"bench-cam1-{suffix}",
            kind="capture",
            config={"client": "bench-pipeline", "channel": "cam1", "mode": "stream", "timeout_ms": 1000},
        )
        flow = make_flow(source, suffix)
        runner.forget(flow.id)

        print("Conveyor pipeline latency bench")
        print("capture: fake:2 2448x2048 colour, 2 cameras, 60 fps, shared memory")
        print("pipeline: image_source(stream) -> blob fallback -> edge_filter -> track_objects -> format_text -> tcp_client(queue)")
        print("ai_segment: not used (stock model/GPU not required in this environment); blob fallback is reported as inference")
        print("duration: 10.0 s")

        pair_dt: list[float] = []
        for _ in range(20):
            _left, _right, dt_ms = hub.request_pair("bench-pipeline", "cam1", "cam2", timeout=2.0)
            if dt_ms is not None:
                pair_dt.append(float(dt_ms))

        runner.start_continuous(flow)
        time.sleep(10.0)
        runner.stop_continuous(flow.id)
        reports = collect_reports(flow.id)
        wait_for(lambda: len(server.received) >= sum(1 for r in reports if r.outputs.get("line")), 2.0)

        grab = [float(r.timing.get("grab_ms") or 0.0) for r in reports]
        frame_age = [float(r.timing["frame_age_ms"]) for r in reports if r.timing.get("frame_age_ms") is not None]
        since_capture = [float(r.timing["since_capture_ms"]) for r in reports if r.timing.get("since_capture_ms") is not None]
        infer = [float((r.timing.get("nodes_ms") or {}).get("infer") or 0.0) for r in reports]
        other_nodes = [
            sum(float(v) for k, v in (r.timing.get("nodes_ms") or {}).items() if k not in ("src", "infer"))
            for r in reports
        ]
        record = [float(r.timing.get("record_ms") or 0.0) for r in reports]

        tcp_send_to_recv: list[float] = []
        capture_to_tcp: list[float] = []
        for r in reports:
            got = server.received.get(r.id)
            if got is None:
                continue
            recv_perf, recv_wall, _text = got
            sent_perf = send_times.get(r.id)
            if sent_perf is not None:
                tcp_send_to_recv.append(max(0.0, (recv_perf - sent_perf) * 1000.0))
            frames = r.timing.get("frames") or []
            captured_at = frames[0].get("captured_at") if frames and isinstance(frames[0], dict) else None
            if captured_at is not None:
                capture_to_tcp.append(max(0.0, (recv_wall - float(captured_at)) * 1000.0))

        seqs = [int((r.timing.get("frames") or [{}])[0].get("seq") or 0) for r in reports if r.timing.get("frames")]
        frames_seen = max(seqs) - min(seqs) + 1 if seqs else 0
        drop_rate = max(0.0, 1.0 - (len(reports) / frames_seen)) if frames_seen else 0.0

        print()
        print(f"runs={len(reports)} tcp_received={len(server.received)} source_frames_seen={frames_seen} drop_rate={drop_rate * 100:.2f}%")
        line("grab wait", grab)
        line("frame age", frame_age)
        line("since capture at runner", since_capture)
        line("inference/blob", infer)
        line("other nodes", other_nodes)
        line("record", record)
        line("tcp send to receive", tcp_send_to_recv)
        line("capture to tcp receive", capture_to_tcp)
        line("stereo pair dt", pair_dt)
        overhead = [o + rec for o, rec in zip(other_nodes, record)]
        line("platform overhead excl. infer/grab", overhead)
        overhead_p95 = pct(overhead, 0.95) or 0.0
        print(f"low_latency_mode_needed={'yes' if overhead_p95 > 3.0 else 'no'} (platform overhead p95 {overhead_p95:.3f} ms)")
        frame_age_p95 = pct(frame_age, 0.95) or 0.0
        print(f"push_continuous_needed={'yes' if frame_age_p95 > 3.0 else 'no'} (frame_age p95 {frame_age_p95:.3f} ms)")
        return 0
    finally:
        if flow is not None:
            runner.stop_continuous(flow.id)
            runner.forget(flow.id)
            flow.delete()
        if source is not None:
            source.delete()
        writer.close()
        writers.close_all()
        sources.close_all()
        capture.stop()
        hub.stop()
        server.stop.set()
        variables.store.clear()


if __name__ == "__main__":
    raise SystemExit(main())
