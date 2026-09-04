"""介面外觀：深色／淺色兩套色票與 Qt 樣式表（與網頁同一個品牌色 #1abb9c）。

`apply_theme(app, "dark")` 會換掉整個應用程式的樣式表；面板只要用語意類別（`class="card"`、`role="muted"` 等）
就會跟著換色，不必各自寫顏色。影像預覽區固定深色（看影像用），與網頁的檢視器一致。
"""

from __future__ import annotations

from typing import Any

THEMES = ("dark", "light")
DEFAULT_THEME = "dark"

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#12141a", "panel": "#1a1d26", "panel2": "#20242f", "line": "#2b303c", "line2": "#3a4150",
        "ink": "#e6e9ef", "muted": "#98a1b3", "subtle": "#6b7280", "brand": "#1abb9c", "brandInk": "#04140f",
        "brandSoft": "rgba(26,187,156,0.14)", "accent": "#22d3ee", "ok": "#22c55e", "warn": "#f59e0b", "bad": "#ef4444",
        "input": "#161a22", "hover": "#242936", "viewer": "#0b0f14", "shadow": "rgba(0,0,0,0.45)",
    },
    "light": {
        "bg": "#f4f6f8", "panel": "#ffffff", "panel2": "#f8fafc", "line": "#dfe3ea", "line2": "#c8cfda",
        "ink": "#1f2430", "muted": "#5b6472", "subtle": "#8b93a1", "brand": "#0f9b82", "brandInk": "#ffffff",
        "brandSoft": "rgba(15,155,130,0.12)", "accent": "#0891b2", "ok": "#15803d", "warn": "#b45309", "bad": "#dc2626",
        "input": "#ffffff", "hover": "#eef1f5", "viewer": "#0b0f14", "shadow": "rgba(15,23,42,0.12)",
    },
}


def palette(theme: str) -> dict[str, str]:
    return PALETTES.get(theme, PALETTES[DEFAULT_THEME])


def stylesheet(theme: str) -> str:
    c = palette(theme)
    return f"""
* {{ font-family: "Microsoft JhengHei UI", "Microsoft JhengHei", "Segoe UI", "Noto Sans TC", sans-serif; font-size: 10pt; }}
QWidget {{ background: {c["bg"]}; color: {c["ink"]}; }}
QMainWindow::separator {{ background: {c["line"]}; width: 1px; height: 1px; }}
QToolTip {{ background: {c["panel2"]}; color: {c["ink"]}; border: 1px solid {c["line2"]}; padding: 4px 6px; }}

/* 卡片式群組 */
QGroupBox {{ background: {c["panel"]}; border: 1px solid {c["line"]}; border-radius: 8px; margin-top: 14px; padding: 12px 12px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 12px; top: 1px; padding: 0 6px; color: {c["muted"]}; font-size: 9pt; letter-spacing: 1px; }}

/* 輸入元件 */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QAbstractSpinBox {{
    background: {c["input"]}; color: {c["ink"]}; border: 1px solid {c["line"]}; border-radius: 6px; padding: 5px 6px 5px 8px; min-height: 18px; selection-background-color: {c["brand"]}; selection-color: {c["brandInk"]};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {c["brand"]}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c["subtle"]}; background: {c["panel2"]}; }}
QComboBox QAbstractItemView {{ background: {c["panel"]}; color: {c["ink"]}; border: 1px solid {c["line2"]}; selection-background-color: {c["brandSoft"]}; selection-color: {c["ink"]}; outline: none; }}

/* 按鈕 */
QPushButton {{ background: {c["panel2"]}; color: {c["ink"]}; border: 1px solid {c["line2"]}; border-radius: 6px; padding: 6px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {c["hover"]}; border-color: {c["brand"]}; }}
QPushButton:pressed {{ background: {c["brandSoft"]}; }}
QPushButton:disabled {{ color: {c["subtle"]}; border-color: {c["line"]}; background: transparent; }}
QPushButton:default, QPushButton[accent="true"] {{ background: {c["brand"]}; color: {c["brandInk"]}; border-color: {c["brand"]}; }}
QPushButton:default:hover, QPushButton[accent="true"]:hover {{ background: {c["accent"]}; border-color: {c["accent"]}; color: {c["brandInk"]}; }}

/* 清單、分頁、捲軸 */
QListWidget {{ background: {c["input"]}; border: 1px solid {c["line"]}; border-radius: 6px; padding: 3px; outline: none; }}
QListWidget::item {{ padding: 5px 7px; border-radius: 4px; }}
QListWidget::item:selected {{ background: {c["brandSoft"]}; color: {c["ink"]}; }}
QListWidget::item:hover {{ background: {c["hover"]}; }}
QTreeWidget {{ background: {c["input"]}; border: 1px solid {c["line"]}; border-radius: 6px; outline: none; alternate-background-color: {c["panel2"]}; }}
QTreeWidget::item {{ padding: 3px 2px; min-height: 26px; border-radius: 4px; }}
QTreeWidget::item:hover {{ background: {c["hover"]}; }}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView::section {{ background: {c["panel2"]}; color: {c["muted"]}; border: none; border-bottom: 1px solid {c["line"]}; padding: 5px 8px; font-size: 9pt; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid {c["line"]}; border-radius: 8px; background: {c["panel"]}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {c["muted"]}; padding: 7px 16px; border: 1px solid transparent; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {c["brand"]}; border-bottom-color: {c["brand"]}; font-weight: 700; }}
QTabBar::tab:hover {{ color: {c["ink"]}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {c["line2"]}; border-radius: 5px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {c["muted"]}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* 核取方塊 */
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c["line2"]}; border-radius: 4px; background: {c["input"]}; }}
QCheckBox::indicator:hover {{ border-color: {c["brand"]}; }}
QCheckBox::indicator:checked {{ background: {c["brand"]}; border-color: {c["brand"]}; }}
QCheckBox:disabled {{ color: {c["subtle"]}; }}

/* 選單列、狀態列、停靠面板 */
QMenuBar {{ background: {c["panel"]}; border-bottom: 1px solid {c["line"]}; }}
QMenuBar::item {{ padding: 6px 12px; background: transparent; }}
QMenuBar::item:selected {{ background: {c["brandSoft"]}; color: {c["brand"]}; }}
QMenu {{ background: {c["panel"]}; border: 1px solid {c["line2"]}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c["brandSoft"]}; color: {c["brand"]}; }}
QMenu::separator {{ height: 1px; background: {c["line"]}; margin: 4px 8px; }}
QStatusBar {{ background: {c["panel"]}; border-top: 1px solid {c["line"]}; color: {c["muted"]}; }}
QStatusBar::item {{ border: none; }}
QDockWidget {{ color: {c["muted"]}; titlebar-close-icon: none; titlebar-normal-icon: none; }}
QDockWidget::title {{ background: {c["panel"]}; padding: 6px 10px; border-top: 1px solid {c["line"]}; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {c["brandSoft"]}; }}
QProgressBar {{ background: {c["input"]}; border: 1px solid {c["line"]}; border-radius: 6px; height: 8px; text-align: center; color: {c["muted"]}; }}
QProgressBar::chunk {{ background: {c["brand"]}; border-radius: 5px; }}

/* 語意標籤 */
QLabel[role="muted"] {{ color: {c["muted"]}; }}
QLabel[role="subtle"] {{ color: {c["subtle"]}; font-size: 9pt; }}
QLabel[role="error"] {{ color: {c["bad"]}; }}
QLabel[role="strong"] {{ color: {c["ink"]}; font-weight: 700; }}
QLabel[role="heading"] {{ color: {c["ink"]}; font-size: 12pt; font-weight: 700; }}
QFrame[role="sep"] {{ background: {c["line"]}; max-height: 1px; border: none; }}
QWidget[role="banner"] {{ background: {c["brandSoft"]}; border: 1px solid {c["brand"]}; border-radius: 8px; }}
QWidget[role="viewer"] {{ background: {c["viewer"]}; border: 1px solid {c["line"]}; border-radius: 8px; }}
"""


def apply_theme(app: Any, theme: str) -> str:
    """套用到整個應用程式；回實際採用的主題名稱。"""
    name = theme if theme in THEMES else DEFAULT_THEME
    app.setStyleSheet(stylesheet(name))
    return name
