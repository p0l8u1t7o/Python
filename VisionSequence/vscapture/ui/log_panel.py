"""「記錄」面板：最近 2000 行，依等級過濾。"""

from __future__ import annotations

import html
import logging

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from vscapture.i18n import tr
from vscapture.ui.theme import palette

LEVELS = (("log.all", logging.DEBUG), ("log.info", logging.INFO), ("log.warning", logging.WARNING), ("log.error", logging.ERROR))


class LogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.level = logging.INFO
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(2000)
        self.filter = QComboBox()
        for _key, level in LEVELS:
            self.filter.addItem("", level)
        self.filter.setCurrentIndex(1)
        self.filter.currentIndexChanged.connect(lambda i: setattr(self, "level", int(self.filter.itemData(i))))
        self.clear_btn = QPushButton()
        self.clear_btn.clicked.connect(self.text.clear)
        self.level_label = QLabel()
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(self.level_label)
        bar.addWidget(self.filter)
        bar.addStretch(1)
        bar.addWidget(self.clear_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addLayout(bar)
        lay.addWidget(self.text, 1)
        self.colors: dict[int, str] = {}
        self.set_theme("dark")
        self.retranslate()

    def retranslate(self) -> None:
        self.level_label.setText(tr("log.level"))
        self.clear_btn.setText(tr("log.clear"))
        for i, (key, _level) in enumerate(LEVELS):
            self.filter.setItemText(i, tr(key))

    def set_theme(self, theme: str) -> None:
        c = palette(theme)
        self.colors = {logging.DEBUG: c["subtle"], logging.INFO: c["muted"], logging.WARNING: c["warn"], logging.ERROR: c["bad"], logging.CRITICAL: c["bad"]}
        self.text.setStyleSheet(f"background:{c['viewer']}; color:{c['ink']}; border:1px solid {c['line']}; border-radius:6px; font-family:Consolas, monospace; font-size:9pt;")

    @Slot(int, str)
    def append(self, level: int, line: str) -> None:
        if level < self.level:
            return
        color = self.colors.get(level, self.colors[logging.INFO])
        self.text.appendHtml(f'<span style="color:{color}">{html.escape(line)}</span>')
