"""「傳送設定」分頁：編碼、JPEG 品質、單色、縮小、模式、串流 fps 上限、每張大小估算與「測試傳送」。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from vscapture import protocol as P
from vscapture.channel import Channel
from vscapture.config import ENCODINGS, MODES
from vscapture.engine import CaptureEngine
from vscapture.i18n import tr
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.widgets import fmt_bytes, muted, shrinkable

DOWNSCALES = (1, 2, 4)


class DeliveryPanel(QWidget):
    dirty = Signal()

    def __init__(self, engine: CaptureEngine, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.bridge = bridge
        self.channel: Channel | None = None
        self._loading = False

        self.encoding = shrinkable(QComboBox())
        for key in ENCODINGS:
            self.encoding.addItem("", key)
        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(1, 100)
        self.jpeg_quality.setKeyboardTracking(False)
        self.mono = QCheckBox()
        self.downscale = shrinkable(QComboBox(), 6)
        for d in DOWNSCALES:
            self.downscale.addItem("", d)
        self.mode = shrinkable(QComboBox())
        for key in MODES:
            self.mode.addItem("", key)
        self.stream_fps = QDoubleSpinBox()
        self.stream_fps.setRange(0.5, 240.0)
        self.stream_fps.setDecimals(1)
        self.stream_fps.setSuffix(" fps")
        self.stream_fps.setKeyboardTracking(False)

        self.form = QFormLayout()
        self.form.setSpacing(7)
        self.field_labels = [QLabel() for _ in range(5)]
        for lab in self.field_labels:
            lab.setProperty("role", "muted")
        self.form.addRow(self.field_labels[0], self.encoding)
        self.form.addRow(self.field_labels[1], self.jpeg_quality)
        self.form.addRow("", self.mono)
        self.form.addRow(self.field_labels[2], self.downscale)
        self.form.addRow(self.field_labels[3], self.mode)
        self.form.addRow(self.field_labels[4], self.stream_fps)
        self.box = QGroupBox()
        self.box.setLayout(self.form)

        self.estimate = muted("")
        self.test_btn = QPushButton()
        self.test_btn.clicked.connect(self.test_send)
        self.test_result = QLabel("—")
        self.test_result.setProperty("role", "muted")
        self.test_result.setWordWrap(True)
        test_row = QHBoxLayout()
        test_row.setSpacing(8)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        self.test_box = QGroupBox()
        QVBoxLayout(self.test_box).addLayout(test_row)

        lay = QVBoxLayout(self)
        lay.setSpacing(9)
        lay.addWidget(self.box)
        lay.addWidget(self.estimate)
        lay.addWidget(self.test_box)
        lay.addStretch(1)

        self.encoding.currentIndexChanged.connect(lambda _i: self._changed())
        self.jpeg_quality.valueChanged.connect(lambda _v: self._changed())
        self.mono.toggled.connect(lambda _v: self._changed())
        self.downscale.currentIndexChanged.connect(lambda _i: self._changed())
        self.mode.currentIndexChanged.connect(lambda _i: self._changed())
        self.stream_fps.valueChanged.connect(lambda _v: self._changed())
        self.retranslate()
        self.set_channel(None)

    def retranslate(self) -> None:
        self.box.setTitle(tr("delivery.group"))
        self.test_box.setTitle(tr("delivery.testGroup"))
        for lab, key in zip(self.field_labels, ("delivery.encoding", "delivery.jpegQuality", "delivery.downscale", "delivery.mode", "delivery.streamFps")):
            lab.setText(tr(key))
        self.encoding.setToolTip(tr("delivery.encodingTip"))
        self.mode.setToolTip(tr("delivery.modeTip"))
        self.mono.setText(tr("delivery.mono"))
        self.test_btn.setText(tr("delivery.test"))
        self.test_btn.setToolTip(tr("delivery.testTip"))
        self._loading = True
        for i, key in enumerate(ENCODINGS):
            missing = key == "lz4" and not P.lz4_available()
            self.encoding.setItemText(i, tr(f"encoding.{key}") + (tr("encoding.lz4Missing") if missing else ""))
            self.encoding.setItemData(i, key)
            if missing:
                model = self.encoding.model()
                item = model.item(i) if hasattr(model, "item") else None
                if item is not None:
                    item.setEnabled(False)
        for i, d in enumerate(DOWNSCALES):
            self.downscale.setItemText(i, tr("delivery.noDownscale") if d == 1 else f"1/{d}")
            self.downscale.setItemData(i, d)
        for i, key in enumerate(MODES):
            self.mode.setItemText(i, tr(f"mode.{key}"))
            self.mode.setItemData(i, key)
        self._loading = False
        self._refresh_estimate()

    def set_channel(self, ch: Channel | None) -> None:
        self.channel = ch
        self.setEnabled(ch is not None)
        if ch is None:
            self.estimate.setText(tr("params.pickChannel"))
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
            note = tr("delivery.noteJpeg", lo=fmt_bytes(raw / 10), hi=fmt_bytes(raw / 4))
        elif d.encoding == "lz4":
            note = tr("delivery.noteLz4", lo=fmt_bytes(raw / 3), hi=fmt_bytes(raw / 1.5))
        else:
            note = tr("delivery.noteRaw")
        per = tr("delivery.perSecond", fps=f"{d.stream_fps:g}", rate=fmt_bytes(raw * d.stream_fps)) if d.mode == "stream" else ""
        self.estimate.setText(tr("delivery.estimate", w=spec["width"], h=spec["height"], c=spec["channels"], size=fmt_bytes(raw), note=note, per=per))

    def test_send(self) -> None:
        ch = self.channel
        if ch is None:
            return
        self.test_btn.setEnabled(False)
        self.test_result.setText(tr("delivery.testing"))

        def run() -> dict[str, Any]:
            return self.engine.transport.test_send(ch.id).result(5.0)

        def done(r: dict[str, Any]) -> None:
            self.test_btn.setEnabled(True)
            text = tr("delivery.testResult", rtt=f"{r['rtt_ms']:.1f}", bytes=fmt_bytes(r["bytes"]), encode=f"{r['encode_ms']:.1f}")
            decode = r.get("decode_ms")
            self.test_result.setText(text + (tr("delivery.testDecode", decode=f"{decode:.1f}") if decode is not None else ""))

        def failed(message: str) -> None:
            self.test_btn.setEnabled(True)
            self.test_result.setText(tr("delivery.testFailed", error=message or "timeout"))

        self.bridge.run_async(run, on_done=done, on_error=failed)
