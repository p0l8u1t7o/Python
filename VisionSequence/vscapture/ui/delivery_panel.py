"""「傳送設定」分頁：編碼、JPEG 品質、單色、縮小、模式、串流 fps 上限、每張大小估算與「測試傳送」。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from vscapture import protocol as P
from vscapture.channel import Channel
from vscapture.config import ENCODINGS, MODES
from vscapture.engine import CaptureEngine
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.widgets import ENCODING_LABELS, MODE_LABELS, fmt_bytes, muted


class DeliveryPanel(QWidget):
    dirty = Signal()

    def __init__(self, engine: CaptureEngine, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.bridge = bridge
        self.channel: Channel | None = None
        self._loading = False

        self.encoding = QComboBox()
        for key in ENCODINGS:
            self.encoding.addItem(ENCODING_LABELS[key], key)
        if not P.lz4_available():
            idx = self.encoding.findData("lz4")
            self.encoding.setItemText(idx, ENCODING_LABELS["lz4"] + "（此版本未內含）")
            self.encoding.model().item(idx).setEnabled(False)
        self.encoding.setToolTip("同一台電腦一律走共享記憶體（不壓縮）；跨電腦建議 LZ4（無損、約 1.5～3 倍）；JPEG 有損，只在頻寬很緊時使用。")
        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(1, 100)
        self.jpeg_quality.setKeyboardTracking(False)
        self.mono = QCheckBox("轉成單色後傳送（頻寬 ÷3）")
        self.downscale = QComboBox()
        for d in (1, 2, 4):
            self.downscale.addItem("不縮小" if d == 1 else f"1/{d}", d)
        self.mode = QComboBox()
        for key in MODES:
            self.mode.addItem(MODE_LABELS[key], key)
        self.mode.setToolTip("依需求取像：伺服端每次執行才向相機要一張新影格（延遲最低、頻寬最省）。連續串流：持續把最新影格推給伺服端，執行時直接取用。")
        self.stream_fps = QDoubleSpinBox()
        self.stream_fps.setRange(0.5, 240.0)
        self.stream_fps.setDecimals(1)
        self.stream_fps.setSuffix(" fps")
        self.stream_fps.setKeyboardTracking(False)

        form = QFormLayout()
        form.addRow("編碼", self.encoding)
        form.addRow("JPEG 品質", self.jpeg_quality)
        form.addRow("", self.mono)
        form.addRow("縮小", self.downscale)
        form.addRow("模式", self.mode)
        form.addRow("串流上限", self.stream_fps)
        box = QGroupBox("傳送")
        box.setLayout(form)

        self.estimate = muted("")
        self.test_btn = QPushButton("測試傳送")
        self.test_btn.setToolTip("把目前影格依上述設定送到伺服端一次，量往返時間與大小")
        self.test_btn.clicked.connect(self.test_send)
        self.test_result = QLabel("—")
        self.test_result.setWordWrap(True)
        test_row = QHBoxLayout()
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        test_box = QGroupBox("測試")
        tl = QVBoxLayout(test_box)
        tl.addLayout(test_row)

        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addWidget(self.estimate)
        lay.addWidget(test_box)
        lay.addStretch(1)

        self.encoding.currentIndexChanged.connect(lambda _i: self._changed())
        self.jpeg_quality.valueChanged.connect(lambda _v: self._changed())
        self.mono.toggled.connect(lambda _v: self._changed())
        self.downscale.currentIndexChanged.connect(lambda _i: self._changed())
        self.mode.currentIndexChanged.connect(lambda _i: self._changed())
        self.stream_fps.valueChanged.connect(lambda _v: self._changed())
        self.set_channel(None)

    def set_channel(self, ch: Channel | None) -> None:
        self.channel = ch
        self.setEnabled(ch is not None)
        if ch is None:
            self.estimate.setText("請選擇通道")
            return
        d = ch.cfg.delivery
        self._loading = True
        self.encoding.setCurrentIndex(max(0, self.encoding.findData(d.encoding)))
        self.jpeg_quality.setValue(d.jpeg_quality)
        self.mono.setChecked(d.mono)
        self.downscale.setCurrentIndex(max(0, self.downscale.findData(d.downscale)))
        self.mode.setCurrentIndex(max(0, self.mode.findData(d.mode)))
        self.stream_fps.setValue(d.stream_fps)
        self._loading = False
        self._refresh_estimate()
        self.test_result.setText("—")

    def _changed(self) -> None:
        ch = self.channel
        if ch is None or self._loading:
            return
        d = ch.cfg.delivery
        d.encoding = str(self.encoding.currentData() or "lz4")
        d.jpeg_quality = int(self.jpeg_quality.value())
        d.mono = self.mono.isChecked()
        d.downscale = int(self.downscale.currentData() or 1)
        d.mode = str(self.mode.currentData() or "on_demand")
        d.stream_fps = float(self.stream_fps.value())
        self.jpeg_quality.setEnabled(d.encoding == "jpeg")
        self.stream_fps.setEnabled(d.mode == "stream")
        self.engine.update_channel(ch.id, ch.cfg)
        self._refresh_estimate()
        self.dirty.emit()

    def _refresh_estimate(self) -> None:
        ch = self.channel
        if ch is None:
            return
        spec = ch.hello_dict()
        raw = int(spec["max_bytes"])
        d = ch.cfg.delivery
        self.jpeg_quality.setEnabled(d.encoding == "jpeg")
        self.stream_fps.setEnabled(d.mode == "stream")
        if d.encoding == "jpeg":
            note = f"JPEG 約 {fmt_bytes(raw / 10)}～{fmt_bytes(raw / 4)}（有損）"
        elif d.encoding == "lz4":
            note = f"LZ4 典型 {fmt_bytes(raw / 3)}～{fmt_bytes(raw / 1.5)}（無損；同一台電腦走共享記憶體時不壓縮）"
        else:
            note = "不壓縮"
        per_s = f"；連續串流 {d.stream_fps:g} fps 最多 {fmt_bytes(raw * d.stream_fps)}/s（未壓縮）" if d.mode == "stream" else ""
        self.estimate.setText(f"送出尺寸 {spec['width']}×{spec['height']}×{spec['channels']}，每張 {fmt_bytes(raw)}；{note}{per_s}")

    def test_send(self) -> None:
        ch = self.channel
        if ch is None:
            return
        self.test_btn.setEnabled(False)
        self.test_result.setText("傳送中…")

        def run() -> dict[str, Any]:
            return self.engine.transport.test_send(ch.id).result(5.0)

        def done(r: dict[str, Any]) -> None:
            self.test_btn.setEnabled(True)
            decode = r.get("decode_ms")
            self.test_result.setText(f"往返 {r['rtt_ms']:.1f} ms · {fmt_bytes(r['bytes'])} · 編碼 {r['encode_ms']:.1f} ms · 伺服端解碼 {decode:.1f} ms" if decode is not None else f"往返 {r['rtt_ms']:.1f} ms · {fmt_bytes(r['bytes'])} · 編碼 {r['encode_ms']:.1f} ms")

        def failed(message: str) -> None:
            self.test_btn.setEnabled(True)
            self.test_result.setText(f"失敗：{message or '逾時'}")

        self.bridge.run_async(run, on_done=done, on_error=failed)
