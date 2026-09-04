"""系統匣：顯示視窗、連線、中斷、結束。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from vscapture.i18n import tr


class Tray(QSystemTrayIcon):
    show_requested = Signal()
    connect_requested = Signal()
    disconnect_requested = Signal()
    quit_requested = Signal()

    def __init__(self, icon: QIcon, parent: QWidget | None = None) -> None:
        super().__init__(icon, parent)
        menu = QMenu(parent)
        self.show_action = QAction("", menu)
        self.connect_action = QAction("", menu)
        self.disconnect_action = QAction("", menu)
        self.quit_action = QAction("", menu)
        self.show_action.triggered.connect(self.show_requested.emit)
        self.connect_action.triggered.connect(self.connect_requested.emit)
        self.disconnect_action.triggered.connect(self.disconnect_requested.emit)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(self.show_action)
        menu.addSeparator()
        menu.addAction(self.connect_action)
        menu.addAction(self.disconnect_action)
        menu.addSeparator()
        menu.addAction(self.quit_action)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self._state = tr("state.disconnected")
        self.retranslate()

    def retranslate(self) -> None:
        self.show_action.setText(tr("tray.show"))
        self.connect_action.setText(tr("connection.connect"))
        self.disconnect_action.setText(tr("connection.disconnect"))
        self.quit_action.setText(tr("menu.quit"))
        self.set_state(self._state, self.disconnect_action.isEnabled())

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_requested.emit()

    def set_state(self, text: str, connected: bool = False) -> None:
        self._state = text
        self.setToolTip(tr("tray.state", state=text))
        self.connect_action.setEnabled(not connected)
        self.disconnect_action.setEnabled(connected)
