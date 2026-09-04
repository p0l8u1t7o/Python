"""「相機參數」分頁：以樹狀圖分組展開後設定；改動 250 ms 去抖動後套用並回填實際值。

工業相機（Basler／IDS）的參數動輒上百項且分屬多層類別，所以用樹狀圖：`ParamSpec.group` 以「/」分層，
沒有 group 的標準參數歸「基本」、其餘歸「進階」。展開狀態與搜尋字串在重新讀取後保留。
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vscapture.cameras.base import ParamSpec
from vscapture.channel import Channel, ChannelState
from vscapture.engine import CaptureEngine
from vscapture.i18n import tr
from vscapture.params import NEEDS_STOP, group_path, matches, param_label, sort_key
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.widgets import TRIGGERS, confirm, muted

log = logging.getLogger(__name__)


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
        self._items: dict[str, QTreeWidgetItem] = {}
        self._pending: dict[str, Any] = {}
        self._collapsed: set[str] = set()  # 使用者收起來的群組（重新讀取後保持）
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._flush)

        self.reload_btn = QPushButton()
        self.reload_btn.clicked.connect(self.reload)
        self.save_btn = QPushButton()
        self.save_btn.clicked.connect(self.save_requested.emit)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(self.reload_btn)
        bar.addWidget(self.save_btn)
        bar.addStretch(1)

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setStretchLastSection(False)
        self.tree.setColumnWidth(1, 170)
        self.tree.setMinimumHeight(120)
        self.tree.itemExpanded.connect(self._remember_expanded)
        self.tree.itemCollapsed.connect(self._remember_expanded)
        self.status = muted("")

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.addLayout(bar)
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.status)
        self.retranslate()

    def retranslate(self) -> None:
        self.reload_btn.setText(tr("params.reload"))
        self.save_btn.setText(tr("params.save"))
        self.save_btn.setToolTip(tr("params.saveTip"))
        self.search.setPlaceholderText(tr("params.search"))
        self.tree.setHeaderLabels([tr("params.colName"), tr("params.colValue")])
        if self.channel is None:
            self.status.setText(tr("params.pickChannel"))
        elif self.channel.camera is None:
            self.status.setText(tr("params.notOpen"))
        else:
            self.reload()

    # ---- 通道 ----
    def set_channel(self, ch: Channel | None) -> None:
        self.channel = ch
        self._pending.clear()
        self._clear()
        if ch is None:
            self.status.setText(tr("params.pickChannel"))
        elif ch.camera is None:
            self.status.setText(tr("params.notOpen"))
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
            self.status.setText(tr("params.closed") if state == "closed" else data.get("error") or tr("chstate.error"))

    def reload(self) -> None:
        ch = self.channel
        if ch is None or ch.camera is None:
            return
        self.status.setText(tr("params.loading"))
        self.bridge.run_async(ch.params, on_done=lambda specs: self._build(ch, specs), on_error=lambda m: self.status.setText(tr("params.loadFailed", error=m)))

    def _clear(self) -> None:
        self._widgets.clear()
        self._specs.clear()
        self._items.clear()
        self.tree.clear()

    # ---- 樹狀圖 ----
    def _remember_expanded(self, item: QTreeWidgetItem) -> None:
        if self._loading:
            return
        key = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if not key:
            return
        if item.isExpanded():
            self._collapsed.discard(key)
        else:
            self._collapsed.add(key)

    def _group_item(self, path: tuple[str, ...], cache: dict[tuple[str, ...], QTreeWidgetItem]) -> QTreeWidgetItem:
        if path in cache:
            return cache[path]
        parent = self._group_item(path[:-1], cache) if len(path) > 1 else None
        item = QTreeWidgetItem(parent or self.tree, [path[-1], ""])
        item.setData(0, Qt.ItemDataRole.UserRole, "/".join(path))
        item.setFirstColumnSpanned(True)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setExpanded("/".join(path) not in self._collapsed)
        cache[path] = item
        return item

    def _build(self, ch: Channel, specs: dict[str, ParamSpec]) -> None:
        if ch is not self.channel:
            return
        self._clear()
        self._specs = dict(specs)
        self._loading = True
        cache: dict[tuple[str, ...], QTreeWidgetItem] = {}
        for spec in sorted(specs.values(), key=sort_key):  # 「基本」排最前面
            parent = self._group_item(group_path(spec), cache)
            item = QTreeWidgetItem(parent, [param_label(spec), ""])
            item.setToolTip(0, spec.name + (f"  {tr('params.range', min=spec.min, max=spec.max)}" if spec.min is not None or spec.max is not None else ""))
            widget = self._make_widget(spec)
            self._widgets[spec.name] = widget
            self._items[spec.name] = item
            self.tree.setItemWidget(item, 1, widget)
        self._loading = False
        self._apply_filter(self.search.text())
        self.status.setText(tr("params.count", n=len(specs)) if specs else tr("params.none"))

    def _apply_filter(self, text: str) -> None:
        """搜尋：比對顯示名稱與 SDK 原名；沒有符合項目的群組整組隱藏。"""
        needle = (text or "").strip()
        for name, item in self._items.items():
            spec = self._specs.get(name)
            item.setHidden(spec is not None and not matches(spec, needle))
        for i in range(self.tree.topLevelItemCount()):
            self._filter_group(self.tree.topLevelItem(i), bool(needle))

    def _filter_group(self, item: QTreeWidgetItem, searching: bool) -> bool:
        visible = False
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole):
                visible = self._filter_group(child, searching) or visible
            elif not child.isHidden():
                visible = True
        item.setHidden(searching and not visible)
        if searching:
            item.setExpanded(visible)
        else:
            item.setExpanded(str(item.data(0, Qt.ItemDataRole.UserRole) or "") not in self._collapsed)
        return visible

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
                combo.addItem(tr(f"trigger.{choice}") if key == "trigger_mode" and choice in TRIGGERS else str(choice), choice)
            combo.setCurrentIndex(max(0, combo.findData(spec.value)))
            combo.currentIndexChanged.connect(lambda i, k=key, c=combo: self._queue(k, c.itemData(i)))
            w = combo
        elif spec.kind == "command":
            btn = QPushButton(spec.label or spec.name)
            btn.clicked.connect(lambda _c=False, k=key: self._queue(k, True))
            w = btn
        else:
            le = QLineEdit(str(spec.value if spec.value is not None else ""))
            le.editingFinished.connect(lambda k=key, e=le: self._queue(k, e.text()))
            w = le
        w.setEnabled(bool(spec.writable))
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
        if restart and not confirm(self, tr("params.restartTitle"), tr("params.restartBody"), ok=tr("params.apply")):
            self._set_values({k: self._specs[k].value for k in pending if k in self._specs})
            return
        self.status.setText(tr("params.applying"))

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
            self.status.setText(tr("params.applied", items="、".join(f"{param_label(self._specs[k])}={v}" for k, v in applied.items() if k in self._specs)) if applied else tr("params.noChange"))
            self.dirty.emit()
            if "trigger_mode" in applied or restart:
                self.reload()

        def failed(message: str) -> None:
            self.status.setText(tr("params.applyFailed", error=message))
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
