"""設定用的彈出視窗：把既有的設定面板原樣裝進對話框。

連線、相機通道、傳送設定改從上方選單開啟——主視窗只留「現在怎麼樣」（連線狀態、通道狀態、預覽），
設定則是需要時才打開。對話框只是容器：面板本身改了什麼就直接寫進設定（跟以前一樣），
關閉時通知主視窗（存檔仍走「檔案 → 儲存設定」）。
"""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vscapture.config import RECORD_CODECS, RECORD_SCALES, RecordingConfig
from vscapture.engine import CaptureEngine
from vscapture.i18n import tr
from vscapture.recorder import default_recording_dir
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.widgets import fmt_bytes, muted
from vscapture.ui.widgets import shrinkable


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


class RecordingPanel(QWidget):
    """錄影設定表單；只更新組態，不啟動錄影執行緒。"""

    changed = Signal()

    def __init__(self, engine: CaptureEngine, bridge: EngineBridge) -> None:
        super().__init__()
        self.engine = engine
        self.bridge = bridge
        self._loading = False
        self._upload_cancel: Event | None = None
        self._upload_progress: tuple[int, int] | None = None
        self.folder = QLineEdit()
        self.codec = QComboBox()
        shrinkable(self.codec, 8)
        for codec in RECORD_CODECS:
            self.codec.addItem(codec, codec)
        self.fps_divisor = QSpinBox()
        self.fps_divisor.setRange(1, 60)
        self.scale = QComboBox()
        shrinkable(self.scale, 7)
        for scale in RECORD_SCALES:
            self.scale.addItem(str(scale), scale)
        self.max_minutes = QDoubleSpinBox()
        self.max_minutes.setRange(0.0, 1440.0)
        self.max_minutes.setDecimals(1)
        self.max_minutes.setSingleStep(1.0)
        self.server_folder = QLineEdit()
        # 資料夾用檔案總管挑，不必手打路徑（打錯一個字元錄影就落到別處）
        self.folder_browse = QPushButton()
        self.server_folder_browse = QPushButton()
        self.auto_upload = QCheckBox()
        self.folder_label = QLabel()
        self.codec_label = QLabel()
        self.fps_divisor_label = QLabel()
        self.scale_label = QLabel()
        self.max_minutes_label = QLabel()
        self.server_folder_label = QLabel()
        self.auto_upload_label = QLabel()

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(150)
        self.refresh_files_btn = QPushButton()
        self.upload_file_btn = QPushButton()
        self.cancel_upload_btn = QPushButton()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.upload_state = muted("")
        file_buttons = QHBoxLayout()
        file_buttons.setSpacing(6)
        file_buttons.addWidget(self.refresh_files_btn)
        file_buttons.addWidget(self.upload_file_btn)
        file_buttons.addWidget(self.cancel_upload_btn)
        file_buttons.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.form = QFormLayout()
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(8)
        self.form.addRow(self.folder_label, self._folder_row(self.folder, self.folder_browse))
        self.form.addRow(self.codec_label, self.codec)
        self.form.addRow(self.fps_divisor_label, self.fps_divisor)
        self.form.addRow(self.scale_label, self.scale)
        self.form.addRow(self.max_minutes_label, self.max_minutes)
        self.form.addRow(self.server_folder_label, self._folder_row(self.server_folder, self.server_folder_browse))
        self.form.addRow(self.auto_upload_label, self.auto_upload)
        root.addLayout(self.form)
        root.addWidget(self.file_list)
        root.addLayout(file_buttons)
        root.addWidget(self.progress)
        root.addWidget(self.upload_state)

        for widget in (self.folder, self.server_folder):
            widget.textChanged.connect(self._apply)
        self.folder_browse.clicked.connect(lambda: self._browse(self.folder, "recording.chooseFolder"))
        self.server_folder_browse.clicked.connect(lambda: self._browse(self.server_folder, "recording.chooseServerFolder"))
        for widget in (self.codec, self.scale):
            widget.currentIndexChanged.connect(self._apply)
        self.fps_divisor.valueChanged.connect(self._apply)
        self.max_minutes.valueChanged.connect(self._apply)
        self.auto_upload.toggled.connect(self._apply)
        self.refresh_files_btn.clicked.connect(self.refresh_files)
        self.upload_file_btn.clicked.connect(self.upload_selected)
        self.cancel_upload_btn.clicked.connect(self.cancel_upload)
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(250)
        self._progress_timer.timeout.connect(self._refresh_upload_progress)
        self.load_from(engine.cfg.recording)
        self.retranslate()
        self.refresh_files()

    def load_from(self, cfg: RecordingConfig) -> None:
        self._loading = True
        try:
            self.folder.setText(cfg.folder)
            self.codec.setCurrentIndex(max(0, self.codec.findData(cfg.codec)))
            self.fps_divisor.setValue(cfg.fps_divisor)
            self.scale.setCurrentIndex(max(0, self.scale.findData(cfg.scale)))
            self.max_minutes.setValue(float(cfg.max_minutes))
            self.server_folder.setText(cfg.server_folder)
            self.auto_upload.setChecked(cfg.auto_upload)
        finally:
            self._loading = False

    def _apply(self) -> None:
        if self._loading:
            return
        cfg = self.engine.cfg.recording
        cfg.folder = self.folder.text().strip()
        cfg.codec = str(self.codec.currentData() or "MJPG")
        cfg.fps_divisor = int(self.fps_divisor.value())
        cfg.scale = float(self.scale.currentData() or 1.0)
        cfg.max_minutes = float(self.max_minutes.value())
        cfg.server_folder = self.server_folder.text().strip()
        cfg.auto_upload = self.auto_upload.isChecked()
        self.refresh_files()
        self.changed.emit()

    @staticmethod
    def _folder_row(edit: QLineEdit, button: QPushButton) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(edit, 1)
        lay.addWidget(button)
        return row

    def _browse(self, edit: QLineEdit, title_key: str) -> None:
        """開檔案總管選資料夾；起始位置＝欄位目前的值（空的就用預設錄影資料夾）。"""
        start = edit.text().strip() or str(default_recording_dir())
        chosen = QFileDialog.getExistingDirectory(self, tr(title_key), start, QFileDialog.Option.ShowDirsOnly)
        if chosen:
            edit.setText(str(Path(chosen)))

    def _folder_path(self) -> Path:
        cfg = self.engine.cfg.recording
        return Path(cfg.server_folder or cfg.folder or default_recording_dir())

    def refresh_files(self) -> None:
        folder = self._folder_path()
        current = self.file_list.currentItem().data(Qt.ItemDataRole.UserRole) if self.file_list.currentItem() else ""
        self.file_list.clear()
        try:
            files = sorted(
                [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".avi", ".mp4"}],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError as exc:
            self.upload_state.setText(str(exc))
            return
        for path in files:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            item = QListWidgetItem(f"{path.name} · {fmt_bytes(size)}")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.file_list.addItem(item)
            if str(path) == current:
                self.file_list.setCurrentItem(item)
        self.upload_file_btn.setEnabled(self.file_list.count() > 0 and self._upload_cancel is None)
        self.cancel_upload_btn.setEnabled(self._upload_cancel is not None)

    def upload_selected(self) -> None:
        item = self.file_list.currentItem()
        if item is None:
            self.upload_state.setText(tr("recording.noFile"))
            return
        path = Path(str(item.data(Qt.ItemDataRole.UserRole)))
        self._upload_cancel = Event()
        self._upload_progress = (0, max(1, path.stat().st_size if path.exists() else 1))
        self.progress.setValue(0)
        self.upload_file_btn.setEnabled(False)
        self.cancel_upload_btn.setEnabled(True)
        self.upload_state.setText(tr("recording.uploading"))
        self._progress_timer.start()

        def progress(got: int, total: int) -> None:
            self._upload_progress = (int(got), int(total or 1))

        self.bridge.run_async(
            self.engine.transport.upload_file,
            path,
            cancel=self._upload_cancel,
            on_progress=progress,
            on_done=self._upload_done,
            on_error=self._upload_failed,
        )

    def cancel_upload(self) -> None:
        if self._upload_cancel is not None:
            self._upload_cancel.set()
            self.upload_state.setText(tr("recording.cancelling"))

    def _upload_done(self, result: dict[str, Any]) -> None:
        self._progress_timer.stop()
        self.progress.setValue(0 if result.get("cancelled") else 100)
        self.upload_state.setText(tr("recording.cancelled") if result.get("cancelled") else tr("recording.uploaded"))
        self._upload_cancel = None
        self._upload_progress = None
        self.refresh_files()

    def _upload_failed(self, message: str) -> None:
        self._progress_timer.stop()
        self.progress.setValue(0)
        self.upload_state.setText(message)
        self._upload_cancel = None
        self._upload_progress = None
        self.refresh_files()

    def _refresh_upload_progress(self) -> None:
        if self._upload_progress is None:
            return
        got, total = self._upload_progress
        pct = min(100, max(0, int(got * 100 / max(1, total))))
        self.progress.setValue(pct)
        self.upload_state.setText(tr("recording.uploadProgress", got=fmt_bytes(got), total=fmt_bytes(total)))

    def retranslate(self) -> None:
        self.folder_label.setText(tr("recording.folder"))
        self.codec_label.setText(tr("recording.codec"))
        self.fps_divisor_label.setText(tr("recording.fpsDivisor"))
        self.scale_label.setText(tr("recording.scale"))
        self.max_minutes_label.setText(tr("recording.maxMinutes"))
        self.server_folder_label.setText(tr("recording.serverFolder"))
        self.auto_upload_label.setText(tr("recording.autoUpload"))
        self.refresh_files_btn.setText(tr("recording.refreshFiles"))
        self.upload_file_btn.setText(tr("recording.uploadSelected"))
        self.cancel_upload_btn.setText(tr("recording.cancelUpload"))
        self.folder_browse.setText(tr("recording.browse"))
        self.server_folder_browse.setText(tr("recording.browse"))
        self.folder_browse.setToolTip(tr("recording.chooseFolder"))
        self.server_folder_browse.setToolTip(tr("recording.chooseServerFolder"))
        self.folder.setToolTip(tr("recording.folderHint"))
        self.server_folder.setToolTip(tr("recording.serverFolderHint"))
