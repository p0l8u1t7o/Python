"""共用小元件與文案對照：狀態燈、卡片標題、確認對話框、數量格式。文字一律走 `i18n.tr`。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QMessageBox, QWidget

from vscapture.i18n import tr
from vscapture.ui.theme import palette

CHANNEL_STATES = ("closed", "opening", "open", "running", "error")
CONN_STATES = ("disconnected", "connecting", "connected", "reconnecting", "auth_failed")
ENCODINGS = ("raw", "lz4", "jpeg")
MODES = ("on_demand", "stream")
LOCAL_MODES = ("auto", "force", "off")
TRIGGERS = ("freerun", "software", "hardware")


def channel_state_label(state: str) -> str:
    return tr(f"chstate.{state}") if state in CHANNEL_STATES else state


def conn_state_label(state: str) -> str:
    return tr(f"state.{state}") if state in CONN_STATES else state


def detail_text(detail: str) -> str:
    """連線狀態細節：`local`／`attempt:N` 是代碼（要翻譯），其餘是例外訊息，原樣顯示。"""
    if detail == "local":
        return tr("detail.local")
    if detail.startswith("attempt:"):
        return tr("detail.attempt", n=detail.split(":", 1)[1])
    return detail


def state_color(theme: str, state: str) -> str:
    c = palette(theme)
    return {
        "closed": c["subtle"], "opening": c["warn"], "open": c["accent"], "running": c["ok"], "error": c["bad"],
        "disconnected": c["subtle"], "connecting": c["warn"], "connected": c["ok"], "reconnecting": c["warn"], "auth_failed": c["bad"],
    }.get(state, c["subtle"])


def dot_icon(color: str, size: int = 10) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.end()
    return QIcon(pix)


class StatusDot(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.set_color("#6b7280")

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"background:{color}; border-radius:5px;")


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setProperty("role", "sep")
    f.setFixedHeight(1)
    return f


def label(text: str = "", role: str = "") -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    lab.setWordWrap(True)
    return lab


def muted(text: str = "") -> QLabel:
    return label(text, "muted")


def confirm(parent: QWidget | None, title: str, text: str, *, ok: str = "", cancel: str = "") -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton(ok or tr("common.ok"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(cancel or tr("common.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is yes


def warn(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def fmt_bytes(n: float | int | None) -> str:
    if not n:
        return "0 B"
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GB"


def fmt_ms(v: float | None) -> str:
    return tr("common.none") if v is None else f"{v:.1f} ms"
