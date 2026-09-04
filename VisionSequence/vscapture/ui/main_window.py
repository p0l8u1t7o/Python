"""主視窗：左「連線」「通道」、中央預覽與 ROI、右「相機參數」「傳送設定」分頁、底部「記錄」；系統匣。"""

from __future__ import annotations

import base64
import logging
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow, QMessageBox, QSplitter, QTabWidget, QVBoxLayout, QWidget

from vscapture import __version__, config as configmod
from vscapture.engine import CaptureEngine
from vscapture.logs import log_dir
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.channels_panel import ChannelsPanel
from vscapture.ui.connection_panel import ConnectionPanel
from vscapture.ui.delivery_panel import DeliveryPanel
from vscapture.ui.live_view import LivePanel
from vscapture.ui.log_panel import LogPanel
from vscapture.ui.params_panel import ParamsPanel
from vscapture.ui.tray import Tray
from vscapture.ui.widgets import CONN_STATE_LABELS, confirm

log = logging.getLogger(__name__)
TITLE = "VisionSequence 擷取端"


def app_icon() -> QIcon:
    path = Path(__file__).resolve().parent.parent / "resources" / "icon.ico"
    return QIcon(str(path)) if path.is_file() else QIcon()


class MainWindow(QMainWindow):
    def __init__(self, engine: CaptureEngine, bridge: EngineBridge) -> None:
        super().__init__()
        self.engine = engine
        self.bridge = bridge
        self._dirty = False
        self._quitting = False
        self._tray_hint_shown = False
        self.setWindowTitle(TITLE)
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)

        self.connection = ConnectionPanel()
        self.channels = ChannelsPanel(engine, bridge)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 6, 6)
        ll.addWidget(self.connection)
        ll.addWidget(self.channels)
        ll.addStretch(1)
        left.setMinimumWidth(300)

        self.live = LivePanel(engine, bridge)
        self.params = ParamsPanel(engine, bridge)
        self.delivery = DeliveryPanel(engine, bridge)
        tabs = QTabWidget()
        tabs.addTab(self.params, "相機參數")
        tabs.addTab(self.delivery, "傳送設定")
        tabs.setMinimumWidth(320)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.live)
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([340, 640, 360])
        self.setCentralWidget(splitter)

        self.log_panel = LogPanel()
        dock = QDockWidget("記錄", self)
        dock.setObjectName("logDock")
        dock.setWidget(self.log_panel)
        dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.log_dock = dock

        self._build_menu()
        self.status_conn = self.statusBar()
        self.status_conn.showMessage("未連線")

        # 系統匣
        self.tray: Tray | None = None
        if Tray.isSystemTrayAvailable():
            self.tray = Tray(self.windowIcon(), self)
            self.tray.show_requested.connect(self.show_window)
            self.tray.connect_requested.connect(self.connect_now)
            self.tray.disconnect_requested.connect(self.disconnect_now)
            self.tray.quit_requested.connect(self.quit)
            self.tray.show()

        # 訊號
        bridge.connection.connect(self._on_connection)
        bridge.channel.connect(self.channels.on_channel_event)
        bridge.channel.connect(self.params.on_channel_event)
        bridge.channel.connect(lambda _d: self.live.refresh_buttons())
        bridge.stream.connect(self._on_stream)
        bridge.log.connect(self.log_panel.append)
        self.connection.connect_clicked.connect(self.connect_now)
        self.connection.disconnect_clicked.connect(self.disconnect_now)
        self.connection.changed.connect(self.mark_dirty)
        self.channels.selected.connect(self._on_channel_selected)
        self.channels.dirty.connect(self.mark_dirty)
        self.live.dirty.connect(self.mark_dirty)
        self.live.dirty.connect(self.params.reload)  # 硬體 ROI 生效後寬高／位移會變
        self.params.dirty.connect(self.mark_dirty)
        self.params.save_requested.connect(self.save_config)
        self.delivery.dirty.connect(self.mark_dirty)

        self.connection.load_from(engine.cfg.connection)
        self.live.set_preview_fps(engine.cfg.ui.preview_fps)
        self._restore_geometry()
        self.channels.refresh_list()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_stats)
        self._timer.start(1000)

    # ---- 選單 ----
    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("檔案")
        save = QAction("儲存設定", self)
        save.setShortcut(QKeySequence.StandardKey.Save)
        save.triggered.connect(self.save_config)
        reload = QAction("重新載入設定", self)
        reload.triggered.connect(self.reload_config)
        open_dir = QAction("開啟設定資料夾", self)
        open_dir.triggered.connect(self.open_app_dir)
        quit_action = QAction("結束", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.quit)
        file_menu.addAction(save)
        file_menu.addAction(reload)
        file_menu.addAction(open_dir)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)
        view_menu = bar.addMenu("檢視")
        self.log_action = QAction("記錄", self)
        self.log_action.setCheckable(True)
        self.log_action.setChecked(True)
        self.log_action.toggled.connect(lambda on: self.log_dock.setVisible(on))
        view_menu.addAction(self.log_action)
        help_menu = bar.addMenu("說明")
        about = QAction("關於", self)
        about.triggered.connect(self.about)
        help_menu.addAction(about)

    # ---- 動作 ----
    @Slot()
    def connect_now(self) -> None:
        self.connection.apply_to(self.engine.cfg.connection)
        self.engine.connect()

    @Slot()
    def disconnect_now(self) -> None:
        self.bridge.run_async(self.engine.disconnect)

    @Slot()
    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @Slot()
    def mark_dirty(self) -> None:
        self._dirty = True
        self.setWindowTitle(f"{TITLE} *")

    @Slot()
    def save_config(self) -> None:
        self.connection.apply_to(self.engine.cfg.connection)
        self.engine.cfg.ui.window_geometry = base64.b64encode(bytes(self.saveGeometry().data())).decode("ascii")
        try:
            path = self.engine.save_config()
        except OSError as exc:
            QMessageBox.warning(self, "儲存設定", f"無法寫入設定檔：{exc}")
            return
        self._dirty = False
        self.setWindowTitle(TITLE)
        self.status_conn.showMessage(f"設定已儲存：{path}", 4000)

    @Slot()
    def reload_config(self) -> None:
        if not confirm(self, "重新載入設定", "會關閉所有相機並依設定檔重新建立通道與連線。要繼續嗎？", ok="重新載入"):
            return
        try:
            cfg = configmod.load(self.engine.config_path)
        except configmod.ConfigError as exc:
            QMessageBox.warning(self, "重新載入設定", f"設定檔有誤：{exc}")
            return
        self._on_channel_selected("")

        def done(_r: Any) -> None:
            self.connection.load_from(self.engine.cfg.connection)
            self.channels.refresh_list()
            self._dirty = False
            self.setWindowTitle(TITLE)
            self.status_conn.showMessage("設定已重新載入", 4000)

        self.bridge.run_async(self.engine.reload, cfg, on_done=done, on_error=lambda m: QMessageBox.warning(self, "重新載入設定", m))

    @Slot()
    def open_app_dir(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        folder = self.engine.config_path.parent if self.engine.config_path else configmod.app_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    @Slot()
    def about(self) -> None:
        path = self.engine.config_path or configmod.default_config_path()
        QMessageBox.about(self, "關於", f"<b>{TITLE}</b> {__version__}<br>在相機所在的電腦直接驅動相機，把影像送到 VisionSequence 伺服端。<br><br>設定檔：{path}<br>記錄檔：{log_dir()}<br>Python {sys.version.split()[0]}")

    @Slot()
    def quit(self) -> None:
        self._quitting = True
        self.close()

    # ---- 事件 ----
    @Slot(object)
    def _on_connection(self, data: dict[str, Any]) -> None:
        self.connection.on_connection(data)
        state = str(data.get("state") or "disconnected")
        label = CONN_STATE_LABELS.get(state, state)
        detail = str(data.get("detail") or "")
        self.status_conn.showMessage(f"{label}" + (f" — {detail}" if detail else ""))
        if self.tray:
            self.tray.set_state(label, connected=state == "connected")

    @Slot(object)
    def _on_stream(self, data: dict[str, Any]) -> None:
        self.status_conn.showMessage(f"通道 {data.get('id')} 串流{'開啟' if data.get('enabled') else '關閉'}", 3000)

    @Slot(str)
    def _on_channel_selected(self, cid: str) -> None:
        ch = self.engine.channels.get(cid) if cid else None
        self.live.set_channel(ch)
        self.params.set_channel(ch)
        self.delivery.set_channel(ch)

    def _refresh_stats(self) -> None:
        self.connection.update_stats(self.engine.transport.stats())
        self.live.refresh_buttons()

    def _restore_geometry(self) -> None:
        raw = self.engine.cfg.ui.window_geometry
        if raw:
            try:
                self.restoreGeometry(QByteArray(base64.b64decode(raw)))
            except Exception:  # noqa: BLE001
                pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.tray is not None and not self._quitting:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(TITLE, "程式仍在系統匣執行；右鍵可連線、中斷或結束。", self.windowIcon(), 3000)
            return
        if self._dirty:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("結束")
            box.setText("設定尚未儲存，要儲存嗎？")
            save_btn = box.addButton("儲存並結束", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("不儲存", QMessageBox.ButtonRole.DestructiveRole)
            cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is cancel:
                self._quitting = False
                event.ignore()
                return
            if box.clickedButton() is save_btn:
                self.save_config()
        else:
            self.engine.cfg.ui.window_geometry = base64.b64encode(bytes(self.saveGeometry().data())).decode("ascii")
            try:
                self.engine.save_config()
            except OSError:
                pass
        if self.tray is not None:
            self.tray.hide()
        event.accept()


def run_app(engine: CaptureEngine, *, minimized: bool = False, connect: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("VisionSequenceCapture")
    app.setApplicationDisplayName(TITLE)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    bridge = EngineBridge(engine)
    win = MainWindow(engine, bridge)
    if minimized and win.tray is not None:
        win.hide()
    else:
        win.show()
    error = getattr(engine, "config_error", "")
    if error:
        QTimer.singleShot(0, lambda: QMessageBox.warning(win, "設定檔有誤", f"{error}\n\n已改用預設值；儲存設定會覆寫原檔。"))
    # 相機開啟可能要幾秒，不擋住視窗
    bridge.run_async(engine.start, connect=connect or None, on_done=lambda _r: win.channels.refresh_list(), on_error=lambda m: log.error("啟動失敗：%s", m))
    app.aboutToQuit.connect(lambda: (engine.stop(), bridge.close()))
    rc = app.exec()
    return int(rc)
