"""主視窗：頂列（品牌、語言、外觀）＋更新橫幅、左「連線」「通道」、中央預覽與 ROI、右「相機參數」「傳送設定」、底部「記錄」；系統匣。"""

from __future__ import annotations

import base64
import logging
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import QApplication, QComboBox, QDockWidget, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QSplitter, QTabWidget, QVBoxLayout, QWidget

from vscapture import __version__, config as configmod
from vscapture.engine import CaptureEngine
from vscapture.i18n import LANGUAGES, set_language, tr
from vscapture.logs import log_dir
from vscapture.ui.bridge import EngineBridge
from vscapture.ui.channels_panel import ChannelsPanel
from vscapture.ui.connection_panel import ConnectionPanel
from vscapture.ui.delivery_panel import DeliveryPanel
from vscapture.ui.live_view import LivePanel
from vscapture.ui.log_panel import LogPanel
from vscapture.ui.params_panel import ParamsPanel
from vscapture.ui.theme import THEMES, apply_theme, palette
from vscapture.ui.tray import Tray
from vscapture.ui.update_banner import UpdateBanner
from vscapture.ui.widgets import conn_state_label, confirm, detail_text

log = logging.getLogger(__name__)


def resources_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "resources"


def app_icon() -> QIcon:
    path = resources_dir() / "icon.ico"
    return QIcon(str(path)) if path.is_file() else QIcon()


class MainWindow(QMainWindow):
    def __init__(self, engine: CaptureEngine, bridge: EngineBridge) -> None:
        super().__init__()
        self.engine = engine
        self.bridge = bridge
        self.theme = engine.cfg.ui.theme
        self._dirty = False
        self._quitting = False
        self._tray_hint_shown = False
        self.setWindowIcon(app_icon())
        self.resize(1320, 840)

        # 頂列：品牌 ＋ 語言／外觀
        self.brand = QLabel()
        self.brand.setProperty("role", "heading")
        icon_path = resources_dir() / "icon.ico"
        self.logo = QLabel()
        if icon_path.is_file():
            self.logo.setPixmap(QPixmap(str(icon_path)).scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.version_label = QLabel(f"v{__version__}")
        self.version_label.setProperty("role", "subtle")
        self.language_label = QLabel()
        self.language_label.setProperty("role", "muted")
        self.language = QComboBox()
        for code, name in LANGUAGES:
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(engine.cfg.ui.language)))
        self.language.currentIndexChanged.connect(self._on_language)
        self.theme_label = QLabel()
        self.theme_label.setProperty("role", "muted")
        self.theme_box = QComboBox()
        for key in THEMES:
            self.theme_box.addItem("", key)
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(self.theme)))
        self.theme_box.currentIndexChanged.connect(self._on_theme)
        top = QHBoxLayout()
        top.setContentsMargins(12, 8, 12, 0)
        top.setSpacing(8)
        top.addWidget(self.logo)
        top.addWidget(self.brand)
        top.addWidget(self.version_label)
        top.addStretch(1)
        top.addWidget(self.language_label)
        top.addWidget(self.language)
        top.addSpacing(8)
        top.addWidget(self.theme_label)
        top.addWidget(self.theme_box)

        self.banner = UpdateBanner(engine)
        self.banner.install_requested.connect(self.start_update)

        self.connection = ConnectionPanel()
        self.channels = ChannelsPanel(engine, bridge)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        ll.addWidget(self.connection)
        ll.addWidget(self.channels)
        ll.addStretch(1)
        left.setMinimumWidth(340)

        self.live = LivePanel(engine, bridge)
        self.params = ParamsPanel(engine, bridge)
        self.delivery = DeliveryPanel(engine, bridge)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.params, "")
        self.tabs.addTab(self.delivery, "")
        self.tabs.setMinimumWidth(340)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.live)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 640, 380])
        splitter.setChildrenCollapsible(False)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        cl.addLayout(top)
        wrap = QVBoxLayout()
        wrap.setContentsMargins(12, 0, 12, 12)
        wrap.setSpacing(8)
        wrap.addWidget(self.banner)
        wrap.addWidget(splitter, 1)
        cl.addLayout(wrap, 1)
        self.setCentralWidget(central)

        self.log_panel = LogPanel()
        self.log_dock = QDockWidget("", self)
        self.log_dock.setObjectName("logDock")
        self.log_dock.setWidget(self.log_panel)
        self.log_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)

        self._build_menu()
        self.status_bar = self.statusBar()

        self.tray: Tray | None = None
        if Tray.isSystemTrayAvailable():
            self.tray = Tray(self.windowIcon(), self)
            self.tray.show_requested.connect(self.show_window)
            self.tray.connect_requested.connect(self.connect_now)
            self.tray.disconnect_requested.connect(self.disconnect_now)
            self.tray.quit_requested.connect(self.quit)
            self.tray.show()

        bridge.connection.connect(self._on_connection)
        bridge.channel.connect(self.channels.on_channel_event)
        bridge.channel.connect(self.params.on_channel_event)
        bridge.channel.connect(lambda _d: self.live.refresh_buttons())
        bridge.stream.connect(self._on_stream)
        bridge.update.connect(self._on_update)
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
        self.apply_theme(self.theme)
        self.retranslate()
        self._restore_geometry()
        self.channels.refresh_list()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_stats)
        self._timer.start(1000)

    # ---- 語言與外觀 ----
    def retranslate(self) -> None:
        self.setWindowTitle(tr("app.title") + (" *" if self._dirty else ""))
        self.brand.setText(tr("app.title"))
        self.language_label.setText(tr("common.language"))
        self.theme_label.setText(tr("common.theme"))
        for i, key in enumerate(THEMES):
            self.theme_box.setItemText(i, tr("common.themeDark") if key == "dark" else tr("common.themeLight"))
        self.tabs.setTabText(0, tr("params.tab"))
        self.tabs.setTabText(1, tr("delivery.tab"))
        self.log_dock.setWindowTitle(tr("log.title"))
        self.file_menu.setTitle(tr("menu.file"))
        self.view_menu.setTitle(tr("menu.view"))
        self.help_menu.setTitle(tr("menu.help"))
        self.save_action.setText(tr("menu.save"))
        self.reload_action.setText(tr("menu.reload"))
        self.open_dir_action.setText(tr("menu.openFolder"))
        self.quit_action.setText(tr("menu.quit"))
        self.log_action.setText(tr("menu.log"))
        self.update_action.setText(tr("menu.checkUpdate"))
        self.about_action.setText(tr("menu.about"))
        for panel in (self.connection, self.channels, self.live, self.params, self.delivery, self.log_panel, self.banner):
            panel.retranslate()
        if self.tray is not None:
            self.tray.retranslate()
        self._on_connection({"state": self.engine.transport.state.value, "detail": self.engine.transport.state_detail})

    def apply_theme(self, theme: str) -> None:
        app = QApplication.instance()
        self.theme = apply_theme(app, theme) if app is not None else theme
        self.engine.cfg.ui.theme = self.theme
        for panel in (self.connection, self.channels, self.live, self.log_panel):
            panel.set_theme(self.theme)
        c = palette(self.theme)
        self.version_label.setStyleSheet(f"color:{c['subtle']};")

    def _on_language(self, index: int) -> None:
        code = str(self.language.itemData(index) or "zh-Hant")
        if code == self.engine.cfg.ui.language:
            return
        self.engine.cfg.ui.language = set_language(code)
        self.retranslate()
        self.mark_dirty()

    def _on_theme(self, index: int) -> None:
        theme = str(self.theme_box.itemData(index) or "dark")
        if theme == self.theme:
            return
        self.apply_theme(theme)
        self.mark_dirty()

    # ---- 選單 ----
    def _build_menu(self) -> None:
        bar = self.menuBar()
        self.file_menu = bar.addMenu("")
        self.save_action = QAction("", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_config)
        self.reload_action = QAction("", self)
        self.reload_action.triggered.connect(self.reload_config)
        self.open_dir_action = QAction("", self)
        self.open_dir_action.triggered.connect(self.open_app_dir)
        self.quit_action = QAction("", self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.quit)
        for action in (self.save_action, self.reload_action, self.open_dir_action):
            self.file_menu.addAction(action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.quit_action)
        self.view_menu = bar.addMenu("")
        self.log_action = QAction("", self)
        self.log_action.setCheckable(True)
        self.log_action.setChecked(True)
        self.log_action.toggled.connect(lambda on: self.log_dock.setVisible(on))
        self.view_menu.addAction(self.log_action)
        self.help_menu = bar.addMenu("")
        self.update_action = QAction("", self)
        self.update_action.triggered.connect(self.check_update)
        self.about_action = QAction("", self)
        self.about_action.triggered.connect(self.about)
        self.help_menu.addAction(self.update_action)
        self.help_menu.addAction(self.about_action)

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
        self.setWindowTitle(tr("app.title") + " *")

    @Slot()
    def start_update(self) -> None:
        if not self.engine.start_update(install=True):
            self.banner.refresh()

    @Slot()
    def check_update(self) -> None:
        info = self.engine.update_info
        if self.engine.transport.state.value != "connected":
            self.status_bar.showMessage(tr("update.noServer"), 4000)
        elif info.available:
            self.banner.refresh()
            self.banner.show()
        else:
            self.status_bar.showMessage(tr("update.upToDate", version=__version__), 4000)

    @Slot()
    def save_config(self) -> None:
        self.connection.apply_to(self.engine.cfg.connection)
        self.engine.cfg.ui.window_geometry = base64.b64encode(bytes(self.saveGeometry().data())).decode("ascii")
        try:
            path = self.engine.save_config()
        except OSError as exc:
            QMessageBox.warning(self, tr("dialog.saveTitle"), tr("dialog.saveFailed", error=exc))
            return
        self._dirty = False
        self.setWindowTitle(tr("app.title"))
        self.status_bar.showMessage(tr("dialog.saved", path=path), 4000)

    @Slot()
    def reload_config(self) -> None:
        if not confirm(self, tr("dialog.reloadTitle"), tr("dialog.reloadBody"), ok=tr("dialog.reload")):
            return
        try:
            cfg = configmod.load(self.engine.config_path)
        except configmod.ConfigError as exc:
            QMessageBox.warning(self, tr("dialog.reloadTitle"), tr("dialog.badConfig", error=exc))
            return
        self._on_channel_selected("")

        def done(_r: Any) -> None:
            self.connection.load_from(self.engine.cfg.connection)
            self.language.setCurrentIndex(max(0, self.language.findData(self.engine.cfg.ui.language)))
            self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(self.engine.cfg.ui.theme)))
            self.channels.refresh_list()
            self._dirty = False
            self.setWindowTitle(tr("app.title"))
            self.status_bar.showMessage(tr("dialog.reloaded"), 4000)

        self.bridge.run_async(self.engine.reload, cfg, on_done=done, on_error=lambda m: QMessageBox.warning(self, tr("dialog.reloadTitle"), m))

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
        QMessageBox.about(self, tr("menu.about"), f"<b>{tr('app.title')}</b> {__version__}<br>{tr('about.body')}<br><br>{tr('about.config')}：{path}<br>{tr('about.logs')}：{log_dir()}<br>Python {sys.version.split()[0]}")

    @Slot()
    def quit(self) -> None:
        self._quitting = True
        self.close()

    # ---- 事件 ----
    @Slot(object)
    def _on_connection(self, data: dict[str, Any]) -> None:
        self.connection.on_connection(data)
        state = str(data.get("state") or "disconnected")
        label = conn_state_label(state)
        detail = detail_text(str(data.get("detail") or ""))
        self.status_bar.showMessage(f"{label} — {detail}" if detail else label)
        if self.tray:
            self.tray.set_state(label, connected=state == "connected")

    @Slot(object)
    def _on_stream(self, data: dict[str, Any]) -> None:
        key = "status.streamOn" if data.get("enabled") else "status.streamOff"
        self.status_bar.showMessage(tr(key, id=data.get("id")), 3000)

    @Slot(object)
    def _on_update(self, _data: dict[str, Any]) -> None:
        self.banner.refresh()
        if self.engine.exit_requested.is_set():
            QTimer.singleShot(400, self.quit)

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
                self.tray.showMessage(tr("app.title"), tr("tray.tip"), self.windowIcon(), 3000)
            return
        if self._dirty:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(tr("dialog.quitTitle"))
            box.setText(tr("dialog.quitBody"))
            save_btn = box.addButton(tr("dialog.saveQuit"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("dialog.discardQuit"), QMessageBox.ButtonRole.DestructiveRole)
            cancel = box.addButton(tr("common.cancel"), QMessageBox.ButtonRole.RejectRole)
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
    set_language(engine.cfg.ui.language)
    # 不設 ApplicationDisplayName：Qt 會把它接在每個視窗標題後面，變成重複的名稱
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
        QTimer.singleShot(0, lambda: QMessageBox.warning(win, tr("dialog.badConfigTitle"), tr("dialog.badConfigBody", error=error)))
    # 相機開啟可能要幾秒，不擋住視窗
    bridge.run_async(engine.start, connect=connect or None, on_done=lambda _r: win.channels.refresh_list(), on_error=lambda m: log.error("啟動失敗：%s", m))
    app.aboutToQuit.connect(lambda: (engine.stop(), bridge.close()))
    return int(app.exec())
