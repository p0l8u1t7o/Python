"""「通道」面板：通道清單、新增／移除、相機種類與裝置、開啟／關閉／開始／停止。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from vscapture import cameras
from vscapture.channel import Channel
from vscapture.config import ChannelConfig, new_channel_id
from vscapture.engine import CaptureEngine
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.widgets import CHANNEL_STATE_COLORS, CHANNEL_STATE_LABELS, confirm, dot_icon, hline, muted


class ChannelsPanel(QGroupBox):
    selected = Signal(str)  # cid（空字串＝沒有選取）
    dirty = Signal()

    def __init__(self, engine: CaptureEngine, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__("通道", parent)
        self.engine = engine
        self.bridge = bridge
        self._loading = False
        self._backends: list[dict[str, Any]] = []

        self.list = QListWidget()
        self.list.setMaximumHeight(140)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.add_btn = QPushButton("新增")
        self.remove_btn = QPushButton("移除")
        self.add_btn.clicked.connect(self.add_channel)
        self.remove_btn.clicked.connect(self.remove_channel)
        btns = QHBoxLayout()
        btns.addWidget(self.add_btn)
        btns.addWidget(self.remove_btn)
        btns.addStretch(1)

        self.name = QLineEdit()
        self.name.editingFinished.connect(self._on_name)
        self.backend = QComboBox()
        self.backend.currentIndexChanged.connect(self._on_backend)
        self.device = QComboBox()
        self.device.setEditable(True)
        self.device.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.device.activated.connect(self._on_device_picked)
        self.device.lineEdit().editingFinished.connect(self._on_device_edited)
        self.scan_btn = QPushButton("掃描")
        self.scan_btn.clicked.connect(self.scan_devices)
        dev_row = QHBoxLayout()
        dev_row.addWidget(self.device, 1)
        dev_row.addWidget(self.scan_btn)
        self.enabled = QCheckBox("啟用（伺服端可取像）")
        self.enabled.toggled.connect(self._on_enabled)
        self.preview = QCheckBox("即時預覽")
        self.preview.toggled.connect(self._on_preview)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("名稱", self.name)
        form.addRow("相機種類", self.backend)
        form.addRow("裝置", dev_row)
        form.addRow("", self.enabled)
        form.addRow("", self.preview)

        self.open_btn = QPushButton("開啟")
        self.close_btn = QPushButton("關閉")
        self.start_btn = QPushButton("開始取像")
        self.stop_btn = QPushButton("停止")
        self.open_btn.clicked.connect(lambda: self._camera_op("open"))
        self.close_btn.clicked.connect(lambda: self._camera_op("close"))
        self.start_btn.clicked.connect(lambda: self._camera_op("start"))
        self.stop_btn.clicked.connect(lambda: self._camera_op("stop"))
        ops = QHBoxLayout()
        for b in (self.open_btn, self.close_btn, self.start_btn, self.stop_btn):
            ops.addWidget(b)
        self.state_label = QLabel("—")
        self.state_label.setStyleSheet("font-weight:600;")
        self.error_label = muted("")
        self.error_label.setStyleSheet("color:#ef4444;")

        lay = QVBoxLayout(self)
        lay.addWidget(self.list)
        lay.addLayout(btns)
        lay.addWidget(hline())
        lay.addLayout(form)
        lay.addLayout(ops)
        lay.addWidget(self.state_label)
        lay.addWidget(self.error_label)
        self._set_form_enabled(False)
        self.bridge.run_async(cameras.describe_backends, on_done=self.set_backends)

    # ---- 相機種類 ----
    def set_backends(self, items: list[dict[str, Any]]) -> None:
        self._backends = items
        current = self.current_cfg().backend if self.current_cfg() else None
        self._loading = True
        self.backend.clear()
        model = self.backend.model()
        for i, info in enumerate(items):
            self.backend.addItem(info["label"], info["backend"])
            if not info["available"]:
                assert isinstance(model, QStandardItemModel)
                item = model.item(i)
                item.setEnabled(False)
                item.setToolTip(f"SDK 尚未安裝：{info['reason']}")
                self.backend.setItemText(i, f"{info['label']}（SDK 尚未安裝）")
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
            item.setIcon(dot_icon(CHANNEL_STATE_COLORS.get(ch.state.value if ch else "closed", "#9ca3af")))
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
        state = CHANNEL_STATE_LABELS.get(ch.state.value, "") if ch else ""
        suffix = "" if cfg.enabled else "（停用）"
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
        for w in (self.name, self.backend, self.device, self.scan_btn, self.enabled, self.preview, self.open_btn, self.close_btn, self.start_btn, self.stop_btn, self.remove_btn):
            w.setEnabled(enabled)

    def _load_form(self, ch: Channel | None) -> None:
        self._loading = True
        try:
            if ch is None:
                self._set_form_enabled(False)
                self.name.clear()
                self.device.clear()
                self.state_label.setText("—")
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
        self.state_label.setText(f"狀態：{CHANNEL_STATE_LABELS.get(state, state)}")
        self.state_label.setStyleSheet(f"font-weight:600; color:{CHANNEL_STATE_COLORS.get(state, '#111')};")
        self.error_label.setText(ch.last_error)
        is_open = state in ("open", "running")
        self.open_btn.setEnabled(not is_open and bool(ch.cfg.device_id))
        self.close_btn.setEnabled(is_open)
        self.start_btn.setEnabled(state == "open")
        self.stop_btn.setEnabled(state == "running")

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
                item.setIcon(dot_icon(CHANNEL_STATE_COLORS.get(ch.state.value, "#9ca3af")))
        if cid == self.current_id():
            self._update_state(ch)

    # ---- 編輯 ----
    def add_channel(self) -> None:
        cid = new_channel_id(c.id for c in self.engine.cfg.channels)
        n = len(self.engine.cfg.channels) + 1
        backend = next((b["backend"] for b in self._backends if b["available"] and b["backend"] != "fake"), "webcam")
        cfg = ChannelConfig(id=cid, name=f"相機 {n}", backend=backend, enabled=True)
        self.engine.add_channel(cfg)
        self.refresh_list(select=cid)
        self.dirty.emit()
        self.scan_devices()

    def remove_channel(self) -> None:
        ch = self.current_channel()
        if ch is None:
            return
        if not confirm(self, "移除通道", f"要移除通道「{ch.cfg.name or ch.id}」嗎？使用此通道的網頁影像來源將無法取像。", ok="移除"):
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
        self.scan_btn.setText("掃描中…")

        def done(devices: list) -> None:
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("掃描")
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
                self.error_label.setText("沒有找到裝置；可直接輸入裝置識別（例如網路攝影機的索引 0）。")

        def failed(message: str) -> None:
            self.scan_btn.setEnabled(True)
            self.scan_btn.setText("掃描")
            self.error_label.setText(f"掃描失敗：{message}")

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
