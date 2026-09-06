"""連線：設定表單（選單 → 連線設定）與狀態卡（主視窗常駐）。

拆成兩個元件的理由：位址／金鑰這種東西設定完就不會再看，但連線狀態、RTT 與已送影格是現場一直要盯的。
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from vscapture.config import AUTO_UPDATE_MODES, LOCAL_MODES, ConnectionConfig
from vscapture.i18n import tr
from vscapture.ui.widgets import StatusDot, conn_state_label, detail_text, fmt_bytes, fmt_ms, hline, muted, shrinkable, state_color


class ConnectionForm(QWidget):
    """設定表單：伺服端位址、名稱、金鑰、本機模式、自動更新、閒置停止（在彈出視窗裡）。"""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self.setMinimumWidth(0)
        self.host = QLineEdit()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.name = QLineEdit()
        self.name.setMaxLength(64)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.auto_connect = QCheckBox()
        self.local_mode = shrinkable(QComboBox())
        self.auto_update = shrinkable(QComboBox())
        self.idle_stop = QSpinBox()
        self.idle_stop.setRange(0, 3600)
        self.idle_stop.setSpecialValueText("—")
        self.idle_stop.setKeyboardTracking(False)
        for _ in LOCAL_MODES:
            self.local_mode.addItem("")
        for _ in AUTO_UPDATE_MODES:
            self.auto_update.addItem("")

        self.form = QFormLayout()
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(7)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.field_labels: list[QLabel] = []
        for widget in (self.host, self.port, self.name, self.api_key, self.local_mode, self.auto_update, self.idle_stop):
            lab = QLabel()
            lab.setProperty("role", "muted")
            self.field_labels.append(lab)
            self.form.addRow(lab, widget)
        self.form.addRow("", self.auto_connect)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.form)
        lay.addStretch(1)

        for w in (self.host, self.name, self.api_key):
            w.textEdited.connect(lambda _t: self.changed.emit())
        self.port.valueChanged.connect(lambda _v: self.changed.emit())
        self.auto_connect.toggled.connect(lambda _v: self.changed.emit())
        self.local_mode.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.auto_update.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.idle_stop.valueChanged.connect(lambda _v: self.changed.emit())
        self.retranslate()

    def retranslate(self) -> None:
        for lab, key in zip(self.field_labels, ("connection.server", "connection.port", "connection.name", "connection.key", "connection.localMode", "update.auto", "connection.idleStop")):
            lab.setText(tr(key))
        self.idle_stop.setSuffix(tr("connection.idleSuffix"))
        self.idle_stop.setToolTip(tr("connection.idleStopHint"))
        self.field_labels[-1].setToolTip(tr("connection.idleStopHint"))
        self.host.setPlaceholderText(tr("connection.serverHint"))
        self.name.setPlaceholderText(tr("connection.nameHint"))
        self.api_key.setPlaceholderText(tr("connection.keyHint"))
        self.auto_connect.setText(tr("connection.autoConnect"))
        for i, key in enumerate(LOCAL_MODES):
            self.local_mode.setItemText(i, tr(f"localMode.{key}"))
            self.local_mode.setItemData(i, key)
        for i, key in enumerate(AUTO_UPDATE_MODES):
            self.auto_update.setItemText(i, tr(f"autoUpdate.{key}"))
            self.auto_update.setItemData(i, key)

    def load_from(self, cfg: ConnectionConfig) -> None:
        self.host.setText(cfg.host)
        self.port.setValue(cfg.port)
        self.name.setText(cfg.client_name)
        self.api_key.setText(cfg.api_key)
        self.auto_connect.setChecked(cfg.auto_connect)
        self.local_mode.setCurrentIndex(max(0, self.local_mode.findData(cfg.local_mode)))
        self.auto_update.setCurrentIndex(max(0, self.auto_update.findData(cfg.auto_update)))
        self.idle_stop.setValue(int(cfg.idle_stop_s))

    def apply_to(self, cfg: ConnectionConfig) -> None:
        cfg.host = self.host.text().strip() or "127.0.0.1"
        cfg.port = int(self.port.value())
        cfg.client_name = (self.name.text().strip() or cfg.client_name)[:64]
        cfg.api_key = self.api_key.text()
        cfg.auto_connect = self.auto_connect.isChecked()
        cfg.local_mode = str(self.local_mode.currentData() or "auto")
        cfg.auto_update = str(self.auto_update.currentData() or "notify")
        cfg.idle_stop_s = float(self.idle_stop.value())

    def set_connected(self, connected: bool) -> None:
        """連線中不讓人改位址／金鑰（改了也不會生效，先斷線再改）。"""
        self._connected = connected
        for w in (self.host, self.port, self.name, self.api_key, self.local_mode):
            w.setEnabled(not connected)


class ConnectionStatus(QGroupBox):
    """狀態卡：連線狀態、原因、連線／斷線鈕與 RTT／已送／速率／通道（主視窗常駐）。"""

    connect_clicked = Signal()
    disconnect_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self._state = "disconnected"
        self._detail = ""
        self._theme = "dark"
        self._last_bytes = 0
        self._last_t = time.perf_counter()
        self._rate = 0.0
        self.setMinimumWidth(0)

        self.button = QPushButton()
        self.button.setDefault(True)
        self.button.clicked.connect(self._on_button)
        self.settings_btn = QPushButton()
        self.settings_btn.clicked.connect(lambda: self.settings_clicked.emit())
        self.dot = StatusDot()
        self.state_label = QLabel()
        self.state_label.setProperty("role", "strong")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.dot)
        row.addWidget(self.state_label)
        row.addStretch(1)
        row.addWidget(self.settings_btn)
        row.addWidget(self.button)

        self.detail = muted("")
        self.server_label = muted("")
        self.rtt = QLabel("—")
        self.sent = QLabel("—")
        self.rate = QLabel("—")
        self.via = QLabel("—")
        self.stats = QFormLayout()
        self.stats.setContentsMargins(0, 0, 0, 0)
        self.stats.setSpacing(4)
        self.stat_labels: list[QLabel] = []
        for widget in (self.rtt, self.sent, self.rate, self.via):
            widget.setProperty("role", "muted")
            lab = QLabel()
            lab.setProperty("role", "subtle")
            self.stat_labels.append(lab)
            self.stats.addRow(lab, widget)

        lay = QVBoxLayout(self)
        lay.setSpacing(9)
        lay.addLayout(row)
        lay.addWidget(self.detail)
        lay.addWidget(hline())
        lay.addLayout(self.stats)
        lay.addWidget(self.server_label)
        self.retranslate()

    # ---- 語言／主題 ----
    def retranslate(self) -> None:
        self.setTitle(tr("connection.title"))
        self.settings_btn.setText(tr("connection.settings"))
        for lab, key in zip(self.stat_labels, ("connection.rtt", "connection.sent", "connection.rate", "connection.transport")):
            lab.setText(tr(key))
        self.button.setText(tr("connection.disconnect") if self._connected else tr("connection.connect"))
        self.state_label.setText(conn_state_label(self._state))
        self.detail.setText(detail_text(self._detail))

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.dot.set_color(state_color(theme, self._state))

    def show_target(self, cfg: ConnectionConfig) -> None:
        """狀態卡上顯示現在要連的是誰（設定搬到彈出視窗後，主畫面還是要看得到位址與名稱）。"""
        self.server_label.setText(tr("connection.target", server=f"{cfg.host}:{cfg.port}", name=cfg.client_name))

    # ---- 狀態 ----
    def _on_button(self) -> None:
        (self.disconnect_clicked if self._connected else self.connect_clicked).emit()

    @Slot(object)
    def on_connection(self, data: dict[str, Any]) -> None:
        self._state = str(data.get("state") or "disconnected")
        self._connected = self._state in ("connected", "connecting", "reconnecting")
        self.dot.set_color(state_color(self._theme, self._state))
        self.state_label.setText(conn_state_label(self._state))
        self._detail = str(data.get("detail") or "")
        self.detail.setText(detail_text(self._detail))
        self.button.setText(tr("connection.disconnect") if self._connected else tr("connection.connect"))
        if not self._connected:
            self.rtt.setText("—")
            self.via.setText("—")

    def update_stats(self, stats: dict[str, Any]) -> None:
        if stats.get("state") != "connected":
            return
        self.rtt.setText(fmt_ms(stats.get("rtt_ms")))
        frames = int(stats.get("frames_sent") or 0)
        total = int(stats.get("bytes_sent") or 0)
        now = time.perf_counter()
        dt = now - self._last_t
        if dt >= 0.5:
            self._rate = max(0.0, (total - self._last_bytes) / dt)
            self._last_bytes, self._last_t = total, now
        self.sent.setText(tr("connection.sentValue", frames=frames, bytes=fmt_bytes(total)))
        self.rate.setText(f"{fmt_bytes(self._rate)}/s")
        self.via.setText(tr("connection.viaShm") if stats.get("local") else tr("connection.viaTcp"))
