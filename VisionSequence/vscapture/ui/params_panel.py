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

from vscapture.cameras.base import Camera, ParamSpec
from vscapture.channel import Channel, ChannelState
from vscapture.engine import CaptureEngine
from vscapture.i18n import tr
from vscapture.params import NEEDS_STOP, group_path, matches, param_label, sort_key
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.widgets import TRIGGERS, confirm, muted, shrinkable

log = logging.getLogger(__name__)
ROLE_GROUP = Qt.ItemDataRole.UserRole
ROLE_PARAM = Qt.ItemDataRole.UserRole + 1
USER_SET_NAMES = ("Default", "UserSet1", "UserSet2", "UserSet3")


class ParamsPanel(QWidget):
    dirty = Signal()
    save_requested = Signal()

    def __init__(self, engine: CaptureEngine, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.bridge = bridge
        self.channel: Channel | None = None
        self._widgets: dict[str, list[QWidget]] = {}
        self._specs: dict[str, ParamSpec] = {}
        self._items: dict[str, list[QTreeWidgetItem]] = {}
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
        self.user_set_combo = shrinkable(QComboBox(), 10)
        self.user_set_combo.setEditable(True)
        for name in USER_SET_NAMES:
            self.user_set_combo.addItem(name, name)
        self.load_user_set_btn = QPushButton()
        self.load_user_set_btn.clicked.connect(self._load_user_set)
        self.save_user_set_btn = QPushButton()
        self.save_user_set_btn.clicked.connect(self._save_user_set)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(self.reload_btn)
        bar.addWidget(self.save_btn)
        bar.addStretch(1)
        # user set 另起一列：與重新讀取／儲存擠同一列時，兩欄版面下按鈕文字會被截成看不懂的字
        user_bar = QHBoxLayout()
        user_bar.setSpacing(6)
        user_bar.addWidget(self.user_set_combo, 1)
        user_bar.addWidget(self.load_user_set_btn)
        user_bar.addWidget(self.save_user_set_btn)

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setStretchLastSection(False)
        self.tree.setColumnWidth(1, 28)  # 星號欄：不能放第 0 欄，那一欄的寬度會被縮排與展開箭頭吃掉
        self.tree.setColumnWidth(2, 170)
        self.tree.setMinimumHeight(120)
        self.tree.itemClicked.connect(self._toggle_favourite)
        self.tree.itemExpanded.connect(self._remember_expanded)
        self.tree.itemCollapsed.connect(self._remember_expanded)
        self.status = muted("")

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.addLayout(bar)
        lay.addLayout(user_bar)
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.status)
        self.retranslate()

    def retranslate(self) -> None:
        self.reload_btn.setText(tr("params.reload"))
        self.save_btn.setText(tr("params.save"))
        self.save_btn.setToolTip(tr("params.saveTip"))
        self.user_set_combo.setToolTip(tr("params.userSetName"))
        self.load_user_set_btn.setText(tr("params.loadUserSet"))
        self.save_user_set_btn.setText(tr("params.saveUserSet"))
        self.search.setPlaceholderText(tr("params.search"))
        self.tree.setHeaderLabels([tr("params.colName"), "", tr("params.colValue")])
        self.tree.headerItem().setToolTip(1, tr("params.colFavourite"))
        self._update_user_set_controls()
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
        self._update_user_set_controls()

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
        self._update_user_set_controls()

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

    # ---- user set ----
    def _user_set_supported(self) -> bool:
        ch = self.channel
        cam = ch.camera if ch is not None else None
        if cam is None:
            return False
        cls = cam.__class__
        return cls.load_user_set is not Camera.load_user_set and cls.save_user_set is not Camera.save_user_set

    def _update_user_set_controls(self) -> None:
        supported = self._user_set_supported()
        enabled = bool(self.channel and self.channel.camera)
        tip = tr("params.userSetTip") if supported else tr("params.userSetUnsupported")
        self.user_set_combo.setEnabled(enabled and supported)
        self.load_user_set_btn.setEnabled(enabled and supported)
        self.save_user_set_btn.setEnabled(enabled and supported)
        for w in (self.user_set_combo, self.load_user_set_btn, self.save_user_set_btn):
            w.setToolTip(tip)

    def _user_set_name(self) -> str:
        return self.user_set_combo.currentText().strip()

    def _remember_user_set_name(self, name: str) -> None:
        if self.user_set_combo.findText(name) < 0:
            self.user_set_combo.addItem(name, name)
        self.user_set_combo.setCurrentText(name)

    def _sync_config_values(self, values: dict[str, Any]) -> None:
        ch = self.channel
        if ch is None:
            return
        for key, value in values.items():
            if hasattr(ch.cfg.params, key):
                setattr(ch.cfg.params, key, value)
            else:
                ch.cfg.extras[key] = value

    def _load_user_set(self) -> None:
        ch = self.channel
        name = self._user_set_name()
        if ch is None or ch.camera is None:
            return
        if not name:
            self.status.setText(tr("params.userSetNoName"))
            return
        self.status.setText(tr("params.userSetLoading"))
        self.load_user_set_btn.setEnabled(False)
        self.save_user_set_btn.setEnabled(False)

        def load() -> dict[str, Any]:
            ch.load_user_set(name)
            return {key: spec.value for key, spec in ch.params().items() if spec.writable}

        def done(values: dict[str, Any]) -> None:
            self._sync_config_values(values)
            self._remember_user_set_name(name)
            log.info("%s", tr("params.userSetLoaded", name=name))
            self.status.setText(tr("params.userSetLoaded", name=name))
            self.dirty.emit()
            self.reload()
            self._update_user_set_controls()

        def failed(message: str) -> None:
            log.warning("%s", tr("params.userSetLoadFailed", error=message))
            self.status.setText(tr("params.userSetLoadFailed", error=message))
            self._update_user_set_controls()

        self.bridge.run_async(load, on_done=done, on_error=failed)

    def _save_user_set(self) -> None:
        ch = self.channel
        name = self._user_set_name()
        if ch is None or ch.camera is None:
            return
        if not name:
            self.status.setText(tr("params.userSetNoName"))
            return
        self.status.setText(tr("params.userSetSaving"))
        self.load_user_set_btn.setEnabled(False)
        self.save_user_set_btn.setEnabled(False)

        def done(_result: Any) -> None:
            self._remember_user_set_name(name)
            log.info("%s", tr("params.userSetSaved", name=name))
            self.status.setText(tr("params.userSetSaved", name=name))
            self._update_user_set_controls()

        def failed(message: str) -> None:
            log.warning("%s", tr("params.userSetSaveFailed", error=message))
            self.status.setText(tr("params.userSetSaveFailed", error=message))
            self._update_user_set_controls()

        self.bridge.run_async(ch.save_user_set, name, on_done=done, on_error=failed)

    # ---- 樹狀圖 ----
    def _remember_expanded(self, item: QTreeWidgetItem) -> None:
        if self._loading:
            return
        key = str(item.data(0, ROLE_GROUP) or "")
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
        item.setData(0, ROLE_GROUP, "/".join(path))
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
        favourites = set(ch.cfg.favourite_params)
        for spec in sorted((s for s in specs.values() if s.name in favourites), key=lambda s: sort_key(s, favourites)):
            parent = self._group_item(group_path(spec, favourites), cache)
            self._add_param_row(parent, spec)
        for spec in sorted(specs.values(), key=sort_key):  # 「基本」排最前面
            parent = self._group_item(group_path(spec), cache)
            self._add_param_row(parent, spec)
        self._loading = False
        self._apply_filter(self.search.text())
        self.status.setText(tr("params.count", n=len(specs)) if specs else tr("params.none"))

    def _add_param_row(self, parent: QTreeWidgetItem, spec: ParamSpec) -> None:
        favourite = spec.name in (self.channel.cfg.favourite_params if self.channel else [])
        item = QTreeWidgetItem(parent, [param_label(spec), "★" if favourite else "☆", ""])
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
        item.setData(0, ROLE_PARAM, spec.name)
        tip = spec.name + (f"  {tr('params.range', min=spec.min, max=spec.max)}" if spec.min is not None or spec.max is not None else "")
        item.setToolTip(1, tr("params.favouriteTip"))
        item.setToolTip(0, tip)
        widget = self._make_widget(spec)
        self._widgets.setdefault(spec.name, []).append(widget)
        self._items.setdefault(spec.name, []).append(item)
        self.tree.setItemWidget(item, 2, widget)

    def _toggle_favourite(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 1 or self.channel is None or self._loading:
            return
        key = str(item.data(0, ROLE_PARAM) or "")
        spec = self._specs.get(key)
        if spec is None:
            return
        names = list(self.channel.cfg.favourite_params)
        label = param_label(spec)
        if key in names:
            self.channel.cfg.favourite_params = [name for name in names if name != key]
            message = tr("params.favouriteOff", name=label)
        else:
            self.channel.cfg.favourite_params = [*names, key]
            message = tr("params.favouriteOn", name=label)
        self.dirty.emit()
        self._build(self.channel, self._specs)
        self.status.setText(message)

    def _apply_filter(self, text: str) -> None:
        """搜尋：比對顯示名稱與 SDK 原名；沒有符合項目的群組整組隱藏。"""
        needle = (text or "").strip()
        for name, items in self._items.items():
            spec = self._specs.get(name)
            hidden = spec is not None and not matches(spec, needle)
            for item in items:
                item.setHidden(hidden)
        for i in range(self.tree.topLevelItemCount()):
            self._filter_group(self.tree.topLevelItem(i), bool(needle))

    def _filter_group(self, item: QTreeWidgetItem, searching: bool) -> bool:
        visible = False
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, ROLE_GROUP):
                visible = self._filter_group(child, searching) or visible
            elif not child.isHidden():
                visible = True
        item.setHidden(searching and not visible)
        if searching:
            item.setExpanded(visible)
        else:
            item.setExpanded(str(item.data(0, ROLE_GROUP) or "") not in self._collapsed)
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
            combo = shrinkable(QComboBox())
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
                for w in self._widgets.get(key, []):
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
