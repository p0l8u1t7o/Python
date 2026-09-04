"""更新橫幅：伺服端建置了新版就顯示在視窗最上方，可直接下載安裝（下載中顯示進度）。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from vscapture.engine import CaptureEngine
from vscapture.i18n import tr
from vscapture.ui.widgets import fmt_bytes


class UpdateBanner(QWidget):
    """`engine.update_status()` 的視覺化；「下載並更新」呼叫 `engine.start_update()`。"""

    install_requested = Signal()

    def __init__(self, engine: CaptureEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setProperty("role", "banner")
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(160)
        self.bar.hide()
        self.install_btn = QPushButton()
        self.install_btn.setProperty("accent", "true")
        self.install_btn.clicked.connect(self.install_requested.emit)
        self.cancel_btn = QPushButton()
        self.cancel_btn.clicked.connect(self.engine.cancel_update)
        self.cancel_btn.hide()
        self.later_btn = QPushButton()
        self.later_btn.clicked.connect(self.hide)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.bar)
        lay.addWidget(self.install_btn)
        lay.addWidget(self.cancel_btn)
        lay.addWidget(self.later_btn)
        self.retranslate()
        self.hide()

    def retranslate(self) -> None:
        self.install_btn.setText(tr("update.install"))
        self.cancel_btn.setText(tr("update.cancel"))
        self.later_btn.setText(tr("update.later"))
        self.refresh()

    @Slot(object)
    def on_update(self, _data: dict[str, Any] | None = None) -> None:
        self.refresh()

    def refresh(self) -> None:
        st = self.engine.update_status()
        phase, info = st["phase"], self.engine.update_info
        if not info.available and phase in ("idle", ""):
            self.hide()
            return
        busy = phase in ("downloading", "staging", "applying")
        self.bar.setVisible(phase == "downloading")
        self.install_btn.setVisible(phase in ("idle", "error"))
        self.cancel_btn.setVisible(phase == "downloading")
        self.later_btn.setVisible(not busy)
        self.install_btn.setEnabled(st["can_install"] or phase == "error")
        if phase == "downloading":
            total = max(1, int(st["total"] or info.size or 1))
            got = int(st["received"])
            self.bar.setRange(0, total)
            self.bar.setValue(min(got, total))
            self.text.setText(tr("update.downloading", percent=int(got * 100 / total), got=fmt_bytes(got), total=fmt_bytes(total)))
        elif phase == "staging":
            self.text.setText(tr("update.staging"))
        elif phase == "applying":
            self.text.setText(tr("update.applying"))
        elif phase == "ready":
            self.text.setText(tr("update.ready", path=st["staged"] or ""))
        elif phase == "error":
            self.text.setText(tr("update.error", error=st["error"]))
        else:
            hint = "" if st["can_install"] else "  " + tr("update.sourceMode")
            self.text.setText(tr("update.found", version=info.version, size=fmt_bytes(info.size)) + hint)
        self.show()
