"""設定用的彈出視窗：把既有的設定面板原樣裝進對話框。

連線、相機通道、傳送設定改從上方選單開啟——主視窗只留「現在怎麼樣」（連線狀態、通道狀態、預覽），
設定則是需要時才打開。對話框只是容器：面板本身改了什麼就直接寫進設定（跟以前一樣），
關閉時通知主視窗（存檔仍走「檔案 → 儲存設定」）。
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from vscapture.i18n import tr


class SettingsDialog(QDialog):
    """一個設定面板 ＋ 一顆關閉鈕；記住自己的大小（同一個工作階段內）。"""

    closed = Signal()

    def __init__(self, parent: QWidget | None, body: QWidget, title_key: str, *, min_size: tuple[int, int] = (420, 320)) -> None:
        super().__init__(parent)
        self._title_key = title_key
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(*min_size)
        self.body = body
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)
        lay.addWidget(body, 1)
        lay.addWidget(self.buttons)
        self._geometry: QByteArray | None = None
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr(self._title_key))
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("common.close"))
        body_retranslate = getattr(self.body, "retranslate", None)
        if callable(body_retranslate):
            body_retranslate()

    def set_theme(self, theme: str) -> None:
        body_theme = getattr(self.body, "set_theme", None)
        if callable(body_theme):
            body_theme(theme)

    def open_dialog(self) -> None:
        """打開（已經開著就帶到前面）——同一個實例重複使用，面板的狀態才不會每次重來。"""
        self.retranslate()
        if self._geometry is not None:
            self.restoreGeometry(self._geometry)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._geometry = self.saveGeometry()
        self.closed.emit()
        super().closeEvent(event)
