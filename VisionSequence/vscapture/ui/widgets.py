"""共用小元件與文案：狀態燈、確認對話框、數量格式。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QMessageBox, QWidget

CHANNEL_STATE_LABELS = {"closed": "已關閉", "opening": "開啟中", "open": "已開啟", "running": "取像中", "error": "錯誤"}
CHANNEL_STATE_COLORS = {"closed": "#9ca3af", "opening": "#f59e0b", "open": "#3b82f6", "running": "#22c55e", "error": "#ef4444"}
CONN_STATE_LABELS = {"disconnected": "未連線", "connecting": "連線中", "connected": "已連線", "reconnecting": "重新連線中", "auth_failed": "驗證失敗"}
CONN_STATE_COLORS = {"disconnected": "#9ca3af", "connecting": "#f59e0b", "connected": "#22c55e", "reconnecting": "#f59e0b", "auth_failed": "#ef4444"}
ENCODING_LABELS = {"raw": "不壓縮（raw）", "lz4": "無損壓縮（LZ4）", "jpeg": "有損壓縮（JPEG）"}
MODE_LABELS = {"on_demand": "依需求取像", "stream": "連續串流"}
LOCAL_MODE_LABELS = {"auto": "自動（同一台電腦用共享記憶體）", "force": "強制共享記憶體", "off": "一律走 TCP"}
TRIGGER_LABELS = {"freerun": "自由取像", "software": "軟體觸發", "hardware": "硬體觸發"}


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
        self.setFixedSize(12, 12)
        self.set_color("#9ca3af")

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"background:{color}; border-radius:6px;")


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def muted(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet("color:#6b7280;")
    lab.setWordWrap(True)
    return lab


def confirm(parent: QWidget | None, title: str, text: str, *, ok: str = "確定", cancel: str = "取消") -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton(ok, QMessageBox.ButtonRole.AcceptRole)
    box.addButton(cancel, QMessageBox.ButtonRole.RejectRole)
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
    return "—" if v is None else f"{v:.1f} ms"
