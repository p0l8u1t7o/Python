"""「記錄」面板：最近 2000 行，依等級過濾。"""

from __future__ import annotations

import html
import logging

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

COLORS = {logging.DEBUG: "#6b7280", logging.INFO: "#d1d5db", logging.WARNING: "#f59e0b", logging.ERROR: "#ef4444", logging.CRITICAL: "#ef4444"}


class LogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.level = logging.INFO
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(2000)
        self.text.setStyleSheet("background:#0b0f14; color:#d1d5db; font-family:Consolas, monospace; font-size:9pt;")
        self.filter = QComboBox()
        for label, level in (("全部", logging.DEBUG), ("一般", logging.INFO), ("警告", logging.WARNING), ("錯誤", logging.ERROR)):
            self.filter.addItem(label, level)
        self.filter.setCurrentIndex(1)
        self.filter.currentIndexChanged.connect(lambda i: setattr(self, "level", int(self.filter.itemData(i))))
        clear = QPushButton("清除")
        clear.clicked.connect(self.text.clear)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("等級"))
        bar.addWidget(self.filter)
        bar.addStretch(1)
        bar.addWidget(clear)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addLayout(bar)
        lay.addWidget(self.text, 1)

    @Slot(int, str)
    def append(self, level: int, line: str) -> None:
        if level < self.level:
            return
        color = COLORS.get(level, "#d1d5db")
        self.text.appendHtml(f'<span style="color:{color}">{html.escape(line)}</span>')
