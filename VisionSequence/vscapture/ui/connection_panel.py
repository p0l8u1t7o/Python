"""「連線」面板：伺服端位址、名稱、金鑰、本機模式；狀態、RTT、已送影格與速率。"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from vscapture.config import LOCAL_MODES, ConnectionConfig
from vscapture.ui.widgets import CONN_STATE_COLORS, CONN_STATE_LABELS, LOCAL_MODE_LABELS, StatusDot, fmt_bytes, fmt_ms, hline, muted


class ConnectionPanel(QGroupBox):
    connect_clicked = Signal()
    disconnect_clicked = Signal()
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("連線", parent)
        self._connected = False
        self._last_bytes = 0
        self._last_t = time.perf_counter()
        self._rate = 0.0

        self.host = QLineEdit()
        self.host.setPlaceholderText("伺服端主機名稱或 IP")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.name = QLineEdit()
        self.name.setMaxLength(64)
        self.name.setPlaceholderText("在網頁上顯示的擷取端名稱")
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("伺服端有設定金鑰時才需要")
        self.auto_connect = QCheckBox("啟動時自動連線")
        self.local_mode = QComboBox()
        for key in LOCAL_MODES:
            self.local_mode.addItem(LOCAL_MODE_LABELS[key], key)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("伺服端", self.host)
        form.addRow("埠", self.port)
        form.addRow("名稱", self.name)
        form.addRow("金鑰", self.api_key)
        form.addRow("本機模式", self.local_mode)
        form.addRow("", self.auto_connect)

        self.button = QPushButton("連線")
        self.button.setDefault(True)
        self.button.clicked.connect(self._on_button)

        self.dot = StatusDot()
        self.state_label = QLabel(CONN_STATE_LABELS["disconnected"])
        self.state_label.setStyleSheet("font-weight:600;")
        row = QHBoxLayout()
        row.addWidget(self.dot)
        row.addWidget(self.state_label)
        row.addStretch(1)
        row.addWidget(self.button)
        self.detail = muted("")
        self.rtt = QLabel("—")
        self.sent = QLabel("—")
        self.rate = QLabel("—")
        self.local = QLabel("—")
        stats = QFormLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.addRow("往返延遲", self.rtt)
        stats.addRow("已送影格", self.sent)
        stats.addRow("速率", self.rate)
        stats.addRow("傳送方式", self.local)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hline())
        lay.addLayout(row)
        lay.addWidget(self.detail)
        lay.addLayout(stats)

        for w in (self.host, self.name, self.api_key):
            w.textEdited.connect(lambda _t: self.changed.emit())
        self.port.valueChanged.connect(lambda _v: self.changed.emit())
        self.auto_connect.toggled.connect(lambda _v: self.changed.emit())
        self.local_mode.currentIndexChanged.connect(lambda _i: self.changed.emit())

    # ---- 設定 ⇄ 欄位 ----
    def load_from(self, cfg: ConnectionConfig) -> None:
        self.host.setText(cfg.host)
        self.port.setValue(cfg.port)
        self.name.setText(cfg.client_name)
        self.api_key.setText(cfg.api_key)
        self.auto_connect.setChecked(cfg.auto_connect)
        idx = self.local_mode.findData(cfg.local_mode)
        self.local_mode.setCurrentIndex(max(0, idx))

    def apply_to(self, cfg: ConnectionConfig) -> None:
        cfg.host = self.host.text().strip() or "127.0.0.1"
        cfg.port = int(self.port.value())
        cfg.client_name = (self.name.text().strip() or cfg.client_name)[:64]
        cfg.api_key = self.api_key.text()
        cfg.auto_connect = self.auto_connect.isChecked()
        cfg.local_mode = str(self.local_mode.currentData() or "auto")

    # ---- 狀態 ----
    def _on_button(self) -> None:
        if self._connected:
            self.disconnect_clicked.emit()
        else:
            self.connect_clicked.emit()

    @Slot(object)
    def on_connection(self, data: dict[str, Any]) -> None:
        state = str(data.get("state") or "disconnected")
        self._connected = state in ("connected", "connecting", "reconnecting")
        self.dot.set_color(CONN_STATE_COLORS.get(state, "#9ca3af"))
        self.state_label.setText(CONN_STATE_LABELS.get(state, state))
        self.detail.setText(str(data.get("detail") or ""))
        self.button.setText("中斷" if self._connected else "連線")
        for w in (self.host, self.port, self.name, self.api_key, self.local_mode):
            w.setEnabled(not self._connected)
        if not self._connected:
            self.rtt.setText("—")
            self.local.setText("—")

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
        self.sent.setText(f"{frames} 張（{fmt_bytes(total)}）")
        self.rate.setText(f"{fmt_bytes(self._rate)}/s")
        self.local.setText("共享記憶體（同一台電腦）" if stats.get("local") else "TCP")
