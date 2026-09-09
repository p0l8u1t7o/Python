"""通道面板：同一個元件兩種用法——主視窗只顯示清單與開關相機的操作，
選單開的「相機通道」彈出視窗才有新增／移除與名稱／種類／裝置的編輯。

沒有用到的元件照樣建立（`_load_form`／`_update_state` 不必分兩套），只是不放進版面，所以不會顯示。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from vscapture import cameras
from vscapture.channel import Channel
from vscapture.config import ChannelConfig, new_channel_id
from vscapture.engine import CaptureEngine
from vscapture.i18n import tr
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.widgets import channel_state_label, confirm, dot_icon, fmt_bytes, hline, muted, shrinkable, state_color, warn


class ChannelsPanel(QGroupBox):
    selected = Signal(str)  # cid（空字串＝沒有選取）
    dirty = Signal()

    def __init__(self, engine: CaptureEngine, bridge: EngineBridge, parent: QWidget | None = None, *, edit: bool = True, ops: bool = True) -> None:
        super().__init__(parent)
        self.engine = engine
        self.bridge = bridge
        self.edit_enabled = edit
        self.ops_enabled = ops
        self._loading = False
        self._theme = "dark"
        self._backends: list[dict[str, Any]] = []

        self.list = QListWidget()
        self.list.setMaximumHeight(132)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.add_btn = QPushButton()
        self.remove_btn = QPushButton()
        self.add_btn.clicked.connect(self.add_channel)
        self.remove_btn.clicked.connect(self.remove_channel)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        btns.addWidget(self.add_btn)
        btns.addWidget(self.remove_btn)
        btns.addStretch(1)

        self.name = QLineEdit()
        self.name.editingFinished.connect(self._on_name)
        self.backend = shrinkable(QComboBox())
        self.backend.currentIndexChanged.connect(self._on_backend)
        self.device = shrinkable(QComboBox(), 10)
        self.device.setEditable(True)
        self.device.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.device.activated.connect(self._on_device_picked)
        self.device.lineEdit().editingFinished.connect(self._on_device_edited)
        self.scan_btn = QPushButton()
        self.scan_btn.clicked.connect(self.scan_devices)
        dev_row = QHBoxLayout()
        dev_row.setSpacing(6)
        dev_row.addWidget(self.device, 1)
        dev_row.addWidget(self.scan_btn)
        self.enabled = QCheckBox()
        self.enabled.toggled.connect(self._on_enabled)
        self.preview = QCheckBox()
        self.preview.toggled.connect(self._on_preview)

        self.form = QFormLayout()
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(7)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.field_labels = [QLabel(), QLabel(), QLabel()]
        for lab in self.field_labels:
            lab.setProperty("role", "muted")
        self.form.addRow(self.field_labels[0], self.name)
        self.form.addRow(self.field_labels[1], self.backend)
        self.form.addRow(self.field_labels[2], dev_row)
        self.form.addRow("", self.enabled)
        self.form.addRow("", self.preview)

        self.open_btn = QPushButton()
        self.close_btn = QPushButton()
        self.start_btn = QPushButton()
        self.stop_btn = QPushButton()
        self.record_btn = QPushButton()
        self.upload_btn = QPushButton()
        self.open_btn.clicked.connect(lambda: self._camera_op("open"))
        self.close_btn.clicked.connect(lambda: self._camera_op("close"))
        self.start_btn.clicked.connect(lambda: self._camera_op("start"))
        self.stop_btn.clicked.connect(lambda: self._camera_op("stop"))
        self.record_btn.clicked.connect(self.toggle_recording)
        self.upload_btn.clicked.connect(self.upload_recording)
        ops_grid = QGridLayout()
        ops_grid.setSpacing(6)
        for i, b in enumerate((self.open_btn, self.close_btn, self.start_btn, self.stop_btn, self.record_btn, self.upload_btn)):
            ops_grid.addWidget(b, i // 2, i % 2)
        self.state_label = QLabel("—")
        self.state_label.setProperty("role", "strong")
        self.record_label = muted("")
        self.error_label = muted("")
        self.error_label.setProperty("role", "error")

        lay = QVBoxLayout(self)
        lay.setSpacing(9)
        lay.addWidget(self.list)
        if edit:
            lay.addLayout(btns)
            lay.addWidget(hline())
            lay.addLayout(self.form)
        if ops:
            if edit:
                lay.addWidget(hline())
            lay.addLayout(ops_grid)
            lay.addWidget(self.state_label)
            lay.addWidget(self.record_label)
            lay.addWidget(self.error_label)
        lay.addStretch(1)
        self._set_form_enabled(False)
        self.retranslate()
        self.bridge.run_async(cameras.describe_backends, on_done=self.set_backends)

    # ---- 語言／主題 ----
    def retranslate(self) -> None:
        self.setTitle(tr("channels.title") if self.ops_enabled else tr("channels.editTitle"))
        self.add_btn.setText(tr("channels.add"))
        self.remove_btn.setText(tr("channels.remove"))
        self.scan_btn.setText(tr("channels.scan"))
        self.enabled.setText(tr("channels.enabled"))
        self.preview.setText(tr("channels.preview"))
        for lab, key in zip(self.field_labels, ("channels.name", "channels.backend", "channels.device")):
            lab.setText(tr(key))
        self.open_btn.setText(tr("channels.open"))
        self.close_btn.setText(tr("channels.closeCam"))
        self.start_btn.setText(tr("channels.start"))
        self.stop_btn.setText(tr("channels.stop"))
        self.record_btn.setText(tr("channels.recordStart"))
        self.upload_btn.setText(tr("channels.uploadRecording"))
        self.set_backends(self._backends)
        self.refresh_list()

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.refresh_list()
        ch = self.current_channel()
        if ch is not None:
            self._update_state(ch)

    # ---- 相機種類 ----
    def set_backends(self, items: list[dict[str, Any]]) -> None:
        self._backends = items or []
        cfg = self.current_cfg()
        current = cfg.backend if cfg else None
        self._loading = True
        self.backend.clear()
        model = self.backend.model()
        for i, info in enumerate(self._backends):
            self.backend.addItem(info["label"] + ("" if info["available"] else tr("channels.sdkMissing")), info["backend"])
            if not info["available"] and isinstance(model, QStandardItemModel):
                item = model.item(i)
                item.setEnabled(False)
                item.setToolTip(tr("channels.sdkTip", reason=info["reason"]))
        if current is not None:
            self.backend.setCurrentIndex(max(0, self.backend.findData(current)))
        self._loading = False

    # ---- 清單 ----
    def refresh_list(self, select: str | None = None) -> None:
        current = select if select is not None else self.current_id()
        self._loading = True
        self.list.clear()
        for cfg in self.engine.cfg.channels:
            ch = self.engine.channels.get(cfg.id)
            item = QListWidgetItem(self._item_text(cfg, ch))
            item.setData(Qt.ItemDataRole.UserRole, cfg.id)
            item.setIcon(dot_icon(state_color(self._theme, ch.state.value if ch else "closed")))
            self.list.addItem(item)
            if cfg.id == current:
                self.list.setCurrentItem(item)
        self._loading = False
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        elif self.list.currentItem() is None:
            self._load_form(None)
            self.selected.emit("")
        else:
            self._load_form(self.current_channel())
            self.selected.emit(self.current_id())

    @staticmethod
    def _item_text(cfg: ChannelConfig, ch: Channel | None) -> str:
        state = channel_state_label(ch.state.value) if ch else ""
        if ch is not None and ch.idle_paused:
            state += tr("channels.idlePaused")
        suffix = "" if cfg.enabled else tr("channels.disabledSuffix")
        return f"{cfg.name or cfg.id}{suffix} · {state}"

    def current_id(self) -> str:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def current_channel(self) -> Channel | None:
        return self.engine.channels.get(self.current_id())

    def current_cfg(self) -> ChannelConfig | None:
        ch = self.current_channel()
        return ch.cfg if ch else None

    def _on_current_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self._loading:
            return
        ch = self.engine.channels.get(str(current.data(Qt.ItemDataRole.UserRole))) if current else None
        self._load_form(ch)
        self.selected.emit(ch.id if ch else "")

    def _set_form_enabled(self, enabled: bool) -> None:
        for w in (self.name, self.backend, self.device, self.scan_btn, self.enabled, self.preview, self.open_btn, self.close_btn, self.start_btn, self.stop_btn, self.record_btn, self.upload_btn, self.remove_btn):
            w.setEnabled(enabled)

    def _load_form(self, ch: Channel | None) -> None:
        self._loading = True
        try:
            if ch is None:
                self._set_form_enabled(False)
                self.name.clear()
                self.device.clear()
                self.state_label.setText("—")
                self.record_label.clear()
                self.error_label.clear()
                return
            self._set_form_enabled(True)
            cfg = ch.cfg
            self.name.setText(cfg.name)
            self.backend.setCurrentIndex(max(0, self.backend.findData(cfg.backend)))
            self.device.clear()
            if cfg.device_id:
                self.device.addItem(cfg.device_id, cfg.device_id)
            self.device.setCurrentText(cfg.device_id)
            self.enabled.setChecked(cfg.enabled)
            self.preview.setChecked(cfg.preview)
            self._update_state(ch)
        finally:
            self._loading = False

    def _update_state(self, ch: Channel) -> None:
        state = ch.state.value
        label = channel_state_label(state) + (tr("channels.idlePaused") if ch.idle_paused else "")
        self.state_label.setText(tr("channels.state", state=label))
        self.state_label.setToolTip(tr("channels.idleHint") if ch.idle_paused else "")
        self.state_label.setStyleSheet(f"font-weight:700; color:{state_color(self._theme, 'opening' if ch.idle_paused else state)};")
        self.error_label.setText(ch.last_error)
        is_open = state in ("open", "running")
        self.open_btn.setEnabled(not is_open and bool(ch.cfg.device_id))
        self.close_btn.setEnabled(is_open)
        self.start_btn.setEnabled(state == "open")
        self.stop_btn.setEnabled(state == "running")
        self._update_recording(ch)

    def _update_recording(self, ch: Channel) -> None:
        rec = self.engine.recording_status()["items"].get(ch.id) or {}
        active = bool(rec.get("active"))
        self.record_btn.setText(tr("channels.recordStop") if active else tr("channels.recordStart"))
        state = ch.state.value
        self.record_btn.setEnabled(ch.cfg.enabled and state in ("open", "running"))
        path = str(rec.get("path") or "")
        self.upload_btn.setEnabled(bool(path) and not active and self.engine.transport.state.value == "connected")
        if active or rec.get("path"):
            self.record_label.setText(tr(
                "channels.recordingStatus",
                duration=rec.get("duration_s", 0),
                size=fmt_bytes(rec.get("bytes", 0)),
                fps=rec.get("actual_fps", 0),
                dropped=rec.get("dropped", 0),
            ))
            self.record_label.setToolTip(str(rec.get("fallback_reason") or rec.get("path") or ""))
        else:
            self.record_label.setText(tr("channels.recordingIdle"))
            self.record_label.setToolTip("")

    def upload_recording(self) -> None:
        ch = self.current_channel()
        if ch is None:
            return
        rec = self.engine.recording_status()["items"].get(ch.id) or {}
        path = str(rec.get("path") or "")
        if not path:
            return
        self.upload_btn.setEnabled(False)
        self.upload_btn.setText(tr("channels.uploading"))

        def done(_result: object) -> None:
            self.upload_btn.setText(tr("channels.uploadRecording"))
            self.refresh_recording()

        def failed(message: str) -> None:
            self.upload_btn.setText(tr("channels.uploadRecording"))
            self.refresh_recording()
            warn(self, tr("channels.uploadRecording"), message)

        self.bridge.run_async(self.engine.transport.upload_file, Path(path), on_done=done, on_error=failed)

    def refresh_recording(self) -> None:
        ch = self.current_channel()
        if ch is not None:
            self._update_recording(ch)

    @Slot(object)
    def on_channel_event(self, data: dict[str, Any]) -> None:
        cid = str(data.get("id") or "")
        ch = self.engine.channels.get(cid)
        if ch is None:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == cid:
                item.setText(self._item_text(ch.cfg, ch))
                item.setIcon(dot_icon(state_color(self._theme, ch.state.value)))
        if cid == self.current_id():
            self._update_state(ch)

    # ---- 編輯 ----
    def add_channel(self) -> None:
        cid = new_channel_id(c.id for c in self.engine.cfg.channels)
        n = len(self.engine.cfg.channels) + 1
        backend = next((b["backend"] for b in self._backends if b["available"] and b["backend"] != "fake"), "webcam")
        cfg = ChannelConfig(id=cid, name=tr("channels.newName", n=n), backend=backend, enabled=True)
        self.engine.add_channel(cfg)
        self.refresh_list(select=cid)
        self.dirty.emit()
        self.scan_devices()

    def remove_channel(self) -> None:
        ch = self.current_channel()
        if ch is None:
            return
        if not confirm(self, tr("channels.removeTitle"), tr("channels.removeBody", name=ch.cfg.name or ch.id), ok=tr("channels.remove")):
            return
        self.engine.remove_channel(ch.id)
        self.refresh_list()
        self.dirty.emit()

    def _on_name(self) -> None:
        ch = self.current_channel()
        if ch is None or self._loading:
            return
        ch.cfg.name = self.name.text().strip() or ch.id
        self.engine.update_channel(ch.id, ch.cfg)
        item = self.list.currentItem()
        if item:
            item.setText(self._item_text(ch.cfg, ch))
        self.dirty.emit()

    def _on_backend(self, _index: int) -> None:
        ch = self.current_channel()
        if ch is None or self._loading:
            return
        backend = str(self.backend.currentData() or "webcam")
        if backend == ch.cfg.backend:
            return
        ch.cfg.backend = backend
        ch.cfg.device_id = ""
        self._loading = True
        self.device.clear()
        self._loading = False
        self.bridge.run_async(self.engine.update_channel, ch.id, ch.cfg, reopen=True, on_done=lambda _r: self._update_state(ch))
        self.dirty.emit()
        self.scan_devices()

    def scan_devices(self) -> None:
        ch = self.current_channel()
        if ch is None:
            return
        backend = ch.cfg.backend
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText(tr("channels.scanning"))

        def done(devices: list) -> None:
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText(tr("channels.scan"))
            if self.current_channel() is not ch:
                return
            self._loading = True
            self.device.clear()
            for d in devices:
                self.device.addItem(f"{d.label}  [{d.device_id}]", d.device_id)
            idx = self.device.findData(ch.cfg.device_id)
            if idx >= 0:
                self.device.setCurrentIndex(idx)
            else:
                self.device.setCurrentText(ch.cfg.device_id)
            self._loading = False
            if not devices:
                self.error_label.setText(tr("channels.noDevices"))

        def failed(message: str) -> None:
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText(tr("channels.scan"))
            self.error_label.setText(tr("channels.scanFailed", error=message))

        self.bridge.run_async(lambda: cameras.backend_class(backend).enumerate() if cameras.backend_class(backend).available()[0] else [], on_done=done, on_error=failed)

    def _on_device_picked(self, index: int) -> None:
        if self._loading:
            return
        self._set_device(str(self.device.itemData(index) or self.device.itemText(index)))

    def _on_device_edited(self) -> None:
        if self._loading:
            return
        text = self.device.currentText().strip()
        idx = self.device.findText(text)
        self._set_device(str(self.device.itemData(idx)) if idx >= 0 else text)

    def _set_device(self, device_id: str) -> None:
        ch = self.current_channel()
        if ch is None or device_id == ch.cfg.device_id:
            return
        ch.cfg.device_id = device_id
        self.error_label.clear()
        self.bridge.run_async(self.engine.update_channel, ch.id, ch.cfg, reopen=True, on_done=lambda _r: self._update_state(ch), on_error=self.error_label.setText)
        self.dirty.emit()

    def _on_enabled(self, checked: bool) -> None:
        ch = self.current_channel()
        if ch is None or self._loading:
            return
        ch.cfg.enabled = checked
        self.bridge.run_async(self.engine.update_channel, ch.id, ch.cfg, reopen=True, on_done=lambda _r: self.refresh_list())
        self.dirty.emit()

    def _on_preview(self, checked: bool) -> None:
        ch = self.current_channel()
        if ch is None or self._loading:
            return
        ch.cfg.preview = checked
        self.engine.update_channel(ch.id, ch.cfg)
        self.dirty.emit()

    def _camera_op(self, op: str) -> None:
        ch = self.current_channel()
        if ch is None:
            return
        fn = {"open": ch.open, "close": ch.close, "start": ch.start, "stop": ch.stop}[op]
        self.error_label.clear()
        for b in (self.open_btn, self.close_btn, self.start_btn, self.stop_btn):
            b.setEnabled(False)
        self.bridge.run_async(fn, on_done=lambda _r: self._update_state(ch), on_error=lambda m: (self.error_label.setText(m), self._update_state(ch)))

    def toggle_recording(self) -> None:
        ch = self.current_channel()
        if ch is None:
            return
        active = bool((self.engine.recording_status()["items"].get(ch.id) or {}).get("active"))
        fn = self.engine.stop_recording if active else self.engine.start_recording
        self.record_btn.setEnabled(False)
        self.bridge.run_async(lambda: fn([ch.id]), on_done=lambda _r: self._update_state(ch), on_error=lambda m: (self.error_label.setText(m), self._update_state(ch)))
