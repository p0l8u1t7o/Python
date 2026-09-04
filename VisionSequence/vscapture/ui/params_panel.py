"""「相機參數」分頁：依相機回報的 ParamSpec 自動組表單，改動 250 ms 去抖動後套用並回填實際值。"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from vscapture.cameras.base import ParamSpec
from vscapture.channel import Channel, ChannelState
from vscapture.engine import CaptureEngine
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.widgets import TRIGGER_LABELS, confirm, muted

log = logging.getLogger(__name__)
NEEDS_STOP = {"width", "height", "offset_x", "offset_y", "pixel_format"}


class ParamsPanel(QWidget):
    dirty = Signal()
    save_requested = Signal()

    def __init__(self, engine: CaptureEngine, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.bridge = bridge
        self.channel: Channel | None = None
        self._widgets: dict[str, QWidget] = {}
        self._specs: dict[str, ParamSpec] = {}
        self._pending: dict[str, Any] = {}
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._flush)

        bar = QHBoxLayout()
        self.reload_btn = QPushButton("重新讀取")
        self.reload_btn.clicked.connect(self.reload)
        self.save_btn = QPushButton("儲存到設定檔")
        self.save_btn.setToolTip("把目前的相機參數、ROI 與傳送設定寫進設定檔，下次啟動自動套用")
        self.save_btn.clicked.connect(self.save_requested.emit)
        bar.addWidget(self.reload_btn)
        bar.addWidget(self.save_btn)
        bar.addStretch(1)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.status = muted("請選擇通道")

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(scroll, 1)
        lay.addWidget(self.status)

    # ---- 通道 ----
    def set_channel(self, ch: Channel | None) -> None:
        self.channel = ch
        self._pending.clear()
        self._clear()
        if ch is None:
            self.status.setText("請選擇通道")
        elif ch.camera is None:
            self.status.setText("相機尚未開啟（先在「通道」開啟相機）")
        else:
            self.reload()

    @Slot(object)
    def on_channel_event(self, data: dict[str, Any]) -> None:
        ch = self.channel
        if ch is None or data.get("id") != ch.id:
            return
        state = str(data.get("state") or "")
        if state in ("open", "running") and not self._widgets:
            self.reload()
        elif state in ("closed", "error", "opening") and self._widgets:
            self._clear()
            self.status.setText("相機已關閉" if state == "closed" else data.get("error") or "相機錯誤")

    def reload(self) -> None:
        ch = self.channel
        if ch is None or ch.camera is None:
            return
        self.status.setText("讀取中…")
        self.bridge.run_async(ch.params, on_done=lambda specs: self._build(ch, specs), on_error=lambda m: self.status.setText(f"讀取失敗：{m}"))

    def _clear(self) -> None:
        self._widgets.clear()
        self._specs.clear()
        while self.body_layout.count() > 1:
            item = self.body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _build(self, ch: Channel, specs: dict[str, ParamSpec]) -> None:
        if ch is not self.channel:
            return
        self._clear()
        self._specs = dict(specs)
        groups: dict[str, list[ParamSpec]] = {}
        for spec in specs.values():
            groups.setdefault(spec.group or ("基本" if spec.standard else "進階"), []).append(spec)
        order = sorted(groups, key=lambda g: (g != "基本", g))
        self._loading = True
        for gname in order:
            box = QGroupBox(gname)
            form = QFormLayout(box)
            for spec in groups[gname]:
                w = self._make_widget(spec)
                self._widgets[spec.name] = w
                label = spec.label or spec.name
                if spec.unit and not isinstance(w, (QSpinBox, QDoubleSpinBox)):
                    label = f"{label}（{spec.unit}）"
                lab = QLabel(label)
                lab.setToolTip(spec.name)
                form.addRow(lab, w)
            self.body_layout.insertWidget(self.body_layout.count() - 1, box)
        self._loading = False
        self.status.setText(f"{len(specs)} 個參數；改動後自動套用" if specs else "此相機沒有可設定的參數")

    def _make_widget(self, spec: ParamSpec) -> QWidget:
        key = spec.name
        w: QWidget
        if spec.kind == "int":
            sb = QSpinBox()
            sb.setRange(int(spec.min) if spec.min is not None else -1_000_000_000, int(spec.max) if spec.max is not None else 1_000_000_000)
            sb.setSingleStep(max(1, int(spec.step or 1)))
            sb.setValue(int(spec.value or 0))
            sb.setKeyboardTracking(False)
            if spec.unit:
                sb.setSuffix(f" {spec.unit}")
            sb.valueChanged.connect(lambda v, k=key: self._queue(k, int(v)))
            w = sb
        elif spec.kind == "float":
            db = QDoubleSpinBox()
            step = float(spec.step or 0.1)
            db.setDecimals(0 if step >= 1 else 2 if step >= 0.01 else 4)
            db.setRange(float(spec.min) if spec.min is not None else -1e12, float(spec.max) if spec.max is not None else 1e12)
            db.setSingleStep(step)
            db.setValue(float(spec.value or 0.0))
            db.setKeyboardTracking(False)
            if spec.unit:
                db.setSuffix(f" {spec.unit}")
            db.valueChanged.connect(lambda v, k=key: self._queue(k, float(v)))
            w = db
        elif spec.kind == "bool":
            cb = QCheckBox()
            cb.setChecked(bool(spec.value))
            cb.toggled.connect(lambda v, k=key: self._queue(k, bool(v)))
            w = cb
        elif spec.kind == "enum":
            combo = QComboBox()
            for choice in spec.choices or ([str(spec.value)] if spec.value is not None else []):
                combo.addItem(TRIGGER_LABELS.get(choice, choice) if key == "trigger_mode" else str(choice), choice)
            idx = combo.findData(spec.value)
            combo.setCurrentIndex(max(0, idx))
            combo.currentIndexChanged.connect(lambda i, k=key, c=combo: self._queue(k, c.itemData(i)))
            w = combo
        elif spec.kind == "command":
            btn = QPushButton(spec.label or "執行")
            btn.clicked.connect(lambda _c=False, k=key: self._queue(k, True))
            w = btn
        else:
            le = QLineEdit(str(spec.value if spec.value is not None else ""))
            le.editingFinished.connect(lambda k=key, e=le: self._queue(k, e.text()))
            w = le
        w.setEnabled(bool(spec.writable))
        tip = spec.name
        if spec.min is not None or spec.max is not None:
            tip += f"  範圍 {spec.min}～{spec.max}"
        w.setToolTip(tip)
        return w

    # ---- 套用 ----
    def _queue(self, key: str, value: Any) -> None:
        if self._loading:
            return
        self._pending[key] = value
        self._timer.start()

    def _flush(self) -> None:
        ch = self.channel
        pending, self._pending = self._pending, {}
        if ch is None or ch.camera is None or not pending:
            return
        restart = bool(NEEDS_STOP & set(pending)) and ch.state == ChannelState.RUNNING
        if restart and not confirm(self, "套用參數", "此參數需要暫停取像才能套用，套用後會自動恢復取像。要繼續嗎？", ok="套用"):
            self._set_values({k: self._specs[k].value for k in pending if k in self._specs})
            return
        self.status.setText("套用中…")

        def apply() -> dict[str, Any]:
            if restart:
                ch.stop()
            try:
                return ch.set_params(pending)
            finally:
                if restart:
                    ch.start()

        def done(applied: dict[str, Any]) -> None:
            self._set_values(applied)
            for k, v in applied.items():
                if k in self._specs:
                    self._specs[k].value = v
            self.status.setText("已套用：" + "、".join(f"{self._specs[k].label or k}={v}" for k, v in applied.items()) if applied else "沒有變更")
            self.dirty.emit()
            if "trigger_mode" in applied or restart:
                self.reload()

        def failed(message: str) -> None:
            self.status.setText(f"套用失敗：{message}")
            self.reload()

        self.bridge.run_async(apply, on_done=done, on_error=failed)

    def _set_values(self, values: dict[str, Any]) -> None:
        self._loading = True
        try:
            for key, value in values.items():
                w = self._widgets.get(key)
                if w is None:
                    continue
                w.blockSignals(True)
                if isinstance(w, QSpinBox):
                    w.setValue(int(value))
                elif isinstance(w, QDoubleSpinBox):
                    w.setValue(float(value))
                elif isinstance(w, QCheckBox):
                    w.setChecked(bool(value))
                elif isinstance(w, QComboBox):
                    idx = w.findData(value)
                    if idx < 0:
                        w.addItem(str(value), value)
                        idx = w.count() - 1
                    w.setCurrentIndex(idx)
                elif isinstance(w, QLineEdit):
                    w.setText(str(value))
                w.blockSignals(False)
        finally:
            self._loading = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
