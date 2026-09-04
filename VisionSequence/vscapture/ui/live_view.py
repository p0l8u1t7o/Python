"""即時預覽與 ROI 圈選：`LiveView` 畫影像＋ROI（拖曳建立、8 個把手縮放、拖移），`LivePanel` 加上數值欄與套用鈕。"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from vscapture.channel import Channel, ChannelState
from vscapture.config import Roi
from vscapture.engine import CaptureEngine
from vscapture.frames import to_display
from vscapture.ui.bridge import EngineBridge
from vscapture.i18n import tr
from vscapture.ui.theme import palette
from vscapture.ui.widgets import muted

log = logging.getLogger(__name__)
HANDLE = 7  # 把手半邊長（像素）
CURSORS = {0: Qt.CursorShape.SizeFDiagCursor, 1: Qt.CursorShape.SizeVerCursor, 2: Qt.CursorShape.SizeBDiagCursor, 3: Qt.CursorShape.SizeHorCursor,
           4: Qt.CursorShape.SizeFDiagCursor, 5: Qt.CursorShape.SizeVerCursor, 6: Qt.CursorShape.SizeBDiagCursor, 7: Qt.CursorShape.SizeHorCursor}


class LiveView(QWidget):
    """影像顯示＋ROI 互動。ROI 一律以全感測器座標保存（硬體 ROI 生效時影像有 origin 位移）。"""

    roi_changed = Signal(object)  # Roi（拖曳結束）
    roi_dragging = Signal(object)  # Roi（拖曳中）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 150)
        self.setMouseTracking(True)
        self.setProperty("role", "viewer")
        self.channel: Channel | None = None
        self.roi = Roi()
        self.hw_roi_active = False
        self._img: QImage | None = None
        self._img_size = (0, 0)  # 通道影像（可能已被硬體 ROI 裁切）
        self.origin = (0, 0)
        self.full = (0, 0)
        self._seq = -1
        self._fps = 0.0
        self._scale = 1.0
        self._off = (0.0, 0.0)
        self._drag: dict[str, Any] | None = None
        self.message = tr("live.pickChannel")
        self.theme = "dark"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._active = True
        self._interval = 66
        self.set_preview_fps(15)

    def set_preview_fps(self, fps: int) -> None:
        self._interval = max(16, int(1000 / max(1, fps)))
        if self._active:
            self.timer.start(self._interval)

    def set_active(self, active: bool) -> None:
        """視窗看不到時停掉預覽計時器（縮小、收到系統匣）——省下縮圖與轉檔的 CPU。"""
        self._active = active
        if active:
            self.timer.start(self._interval)
        else:
            self.timer.stop()

    def set_channel(self, ch: Channel | None) -> None:
        self.channel = ch
        self._img = None
        self._seq = -1
        self.roi = Roi(ch.cfg.roi.x, ch.cfg.roi.y, ch.cfg.roi.w, ch.cfg.roi.h) if ch else Roi()
        self.hw_roi_active = bool(ch.hw_roi_active) if ch else False
        self.message = tr("live.pickChannel") if ch is None else tr("live.noImage")
        self.update()

    def set_roi(self, roi: Roi) -> None:
        self.roi = roi
        self.update()

    # ---- 影像 ----
    def _tick(self) -> None:
        ch = self.channel
        if ch is None:
            return
        if not ch.cfg.preview:
            if self._img is not None or self.message != tr("live.previewOff"):
                self._img, self.message = None, tr("live.previewOff")
                self.update()
            return
        latest = ch.slot.latest()
        if latest is None:
            if self._img is not None:
                self._img = None
                self.message = tr("live.notRunning") if ch.state != ChannelState.RUNNING else tr("live.waiting")
                self.update()
            return
        if latest.seq == self._seq:
            return
        self._seq = latest.seq
        image = latest.image
        disp = to_display(image, max(1, self.width()), max(1, self.height()))
        h, w = disp.shape[:2]
        if disp.ndim == 2:
            fmt = QImage.Format.Format_Grayscale8
        elif disp.shape[2] == 3:
            fmt = QImage.Format.Format_BGR888
        else:
            fmt = QImage.Format.Format_ARGB32
        self._img = QImage(disp.data, w, h, disp.strides[0], fmt).copy()
        self._img_size = (int(image.shape[1]), int(image.shape[0]))
        self.origin = tuple(latest.origin) if latest.origin else (0, 0)
        self.full = tuple(latest.full) if latest.full and latest.full[0] else self._img_size
        self.hw_roi_active = bool(ch.hw_roi_active)
        self._fps = float(ch.stats().get("fps") or 0.0)
        self.update()

    # ---- 座標 ----
    def _fit(self) -> QRectF:
        w, h = self._img_size
        if w <= 0 or h <= 0:
            return QRectF()
        scale = min(self.width() / w, self.height() / h)
        dw, dh = w * scale, h * scale
        ox, oy = (self.width() - dw) / 2, (self.height() - dh) / 2
        self._scale, self._off = scale, (ox, oy)
        return QRectF(ox, oy, dw, dh)

    def _to_image(self, pos: QPointF) -> tuple[float, float]:
        w, h = self._img_size
        x = (pos.x() - self._off[0]) / self._scale
        y = (pos.y() - self._off[1]) / self._scale
        return max(0.0, min(float(w), x)), max(0.0, min(float(h), y))

    def _roi_rect_img(self) -> QRectF | None:
        """ROI 在通道影像座標（扣掉 origin）；全幅或不在畫面內回 None。"""
        if self.roi.is_full() or self._img_size[0] <= 0:
            return None
        return QRectF(self.roi.x - self.origin[0], self.roi.y - self.origin[1], self.roi.w, self.roi.h)

    def _roi_rect_disp(self) -> QRectF | None:
        r = self._roi_rect_img()
        if r is None:
            return None
        s, (ox, oy) = self._scale, self._off
        return QRectF(ox + r.x() * s, oy + r.y() * s, r.width() * s, r.height() * s)

    @staticmethod
    def _handles(r: QRectF) -> list[QPointF]:
        cx, cy = r.center().x(), r.center().y()
        return [r.topLeft(), QPointF(cx, r.top()), r.topRight(), QPointF(r.right(), cy), r.bottomRight(), QPointF(cx, r.bottom()), r.bottomLeft(), QPointF(r.left(), cy)]

    def _hit(self, pos: QPointF) -> tuple[str, int]:
        r = self._roi_rect_disp()
        if r is None:
            return "new", -1
        for i, hp in enumerate(self._handles(r)):
            if abs(pos.x() - hp.x()) <= HANDLE + 2 and abs(pos.y() - hp.y()) <= HANDLE + 2:
                return "resize", i
        if r.contains(pos):
            return "move", -1
        return "new", -1

    # ---- 繪製 ----
    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        c = palette(self.theme)
        p.fillRect(self.rect(), QColor(c["viewer"]))
        if self._img is None:
            p.setPen(QColor(c["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            p.end()
            return
        target = self._fit()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(target, self._img)
        r = self._roi_rect_disp()
        if r is not None:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(c["accent"]), 2))
            p.setBrush(QColor(c["accent"] + "22" if len(c["accent"]) == 7 else c["accent"]))
            p.drawRect(r)
            p.setBrush(QColor(c["accent"]))
            p.setPen(QPen(QColor(c["viewer"]), 1))
            for hp in self._handles(r):
                p.drawRect(QRectF(hp.x() - HANDLE / 2, hp.y() - HANDLE / 2, HANDLE, HANDLE))
            p.setPen(QColor(c["accent"]))
            p.drawText(QPointF(r.left() + 4, max(r.top() - 6, 14)), f"{tr('live.roi')} {self.roi.x},{self.roi.y}  {self.roi.w}×{self.roi.h}")
        # HUD
        font = QFont("Consolas")
        font.setPointSize(9)
        p.setFont(font)
        w, h = self._img_size
        parts = [f"#{self._seq}", f"{self._fps:.1f} fps", f"{w}×{h}"]
        if self.hw_roi_active:
            parts.append(tr("live.hwRoiBadge", x=self.origin[0], y=self.origin[1]))
        text = "  ·  ".join(parts)
        p.setPen(QColor(0, 0, 0, 160))
        p.drawText(QPointF(target.left() + 9, target.top() + 17), text)
        p.setPen(QColor("#e6e9ef"))
        p.drawText(QPointF(target.left() + 8, target.top() + 16), text)
        p.end()

    # ---- 滑鼠 ----
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._img is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        mode, handle = self._hit(pos)
        ix, iy = self._to_image(pos)
        self._drag = {"mode": mode, "handle": handle, "start": (ix, iy), "roi0": self._roi_rect_img() or QRectF(ix, iy, 0, 0)}
        if mode == "new":
            self.roi = Roi(int(ix) + self.origin[0], int(iy) + self.origin[1], 0, 0)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._img is None:
            return
        pos = event.position()
        if self._drag is None:
            mode, handle = self._hit(pos)
            self.setCursor(CURSORS[handle] if mode == "resize" else Qt.CursorShape.SizeAllCursor if mode == "move" else Qt.CursorShape.CrossCursor)
            return
        ix, iy = self._to_image(pos)
        d = self._drag
        r0: QRectF = d["roi0"]
        sx, sy = d["start"]
        w, h = self._img_size
        if d["mode"] == "new":
            x0, y0 = min(sx, ix), min(sy, iy)
            rect = QRectF(x0, y0, abs(ix - sx), abs(iy - sy))
        elif d["mode"] == "move":
            dx, dy = ix - sx, iy - sy
            nx = max(0.0, min(w - r0.width(), r0.x() + dx))
            ny = max(0.0, min(h - r0.height(), r0.y() + dy))
            rect = QRectF(nx, ny, r0.width(), r0.height())
        else:
            left, top, right, bottom = r0.left(), r0.top(), r0.right(), r0.bottom()
            hd = d["handle"]
            if hd in (0, 6, 7):
                left = min(ix, right - 1)
            if hd in (2, 3, 4):
                right = max(ix, left + 1)
            if hd in (0, 1, 2):
                top = min(iy, bottom - 1)
            if hd in (4, 5, 6):
                bottom = max(iy, top + 1)
            rect = QRectF(left, top, right - left, bottom - top)
        self.roi = Roi(int(round(rect.x())) + self.origin[0], int(round(rect.y())) + self.origin[1], int(round(rect.width())), int(round(rect.height())))
        self.roi_dragging.emit(self.roi)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag = None
        if self.roi.w < 2 or self.roi.h < 2:
            self.roi = Roi()
        self.roi_changed.emit(self.roi)
        self.update()


class LivePanel(QWidget):
    """預覽＋ROI 數值欄、清除、硬體 ROI、套用、拍攝一張。"""

    dirty = Signal()

    def __init__(self, engine: CaptureEngine, bridge: EngineBridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.bridge = bridge
        self.channel: Channel | None = None
        self._loading = False
        self._snap_visible = False
        self.view = LiveView()
        self.view.roi_changed.connect(self._on_view_roi)
        self.view.roi_dragging.connect(self._show_roi)

        self.spins: dict[str, QSpinBox] = {}
        self.roi_label = QLabel()
        for key in ("x", "y", "w", "h"):
            sp = QSpinBox()
            sp.setRange(0, 100000)
            sp.setKeyboardTracking(False)
            sp.setMaximumWidth(120)
            sp.setMinimumWidth(56)
            sp.valueChanged.connect(self._on_spin)
            self.spins[key] = sp
        self.clear_btn = QPushButton()
        self.clear_btn.clicked.connect(self.clear_roi)
        self.hw_check = QCheckBox()
        self.apply_btn = QPushButton()
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.apply_roi)
        self.snap_btn = QPushButton()
        self.snap_btn.clicked.connect(self.snap)
        # ROI 工具列：寬的時候一列，窄的時候拆成兩列（數值一列、動作一列）
        self.tools = QWidget()
        self.tools_grid = QGridLayout(self.tools)
        self.tools_grid.setContentsMargins(0, 0, 0, 0)
        self.tools_grid.setSpacing(6)
        self._tool_rows = -1
        self._reflow_tools(1)
        self.status = muted("")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.tools)
        lay.addWidget(self.status)
        self.retranslate()
        self.set_channel(None)

    def retranslate(self) -> None:
        self.roi_label.setText(tr("live.roi"))
        for key in ("x", "y", "w", "h"):
            self.spins[key].setPrefix(tr(f"live.roi{key.upper()}") + " ")
        self.clear_btn.setText(tr("live.clearRoi"))
        self.hw_check.setText(tr("live.hwRoi"))
        self.hw_check.setToolTip(tr("live.hwRoiTip"))
        self.apply_btn.setText(tr("live.applyRoi"))
        self.snap_btn.setText(tr("live.snap"))
        self.snap_btn.setToolTip(tr("live.snapTip"))
        self.status.setText(tr("live.hint"))
        self.view.message = tr("live.pickChannel") if self.channel is None else self.view.message
        self.view.update()

    def set_theme(self, theme: str) -> None:
        self.view.theme = theme
        self.view.update()

    def set_preview_fps(self, fps: int) -> None:
        self.view.set_preview_fps(fps)

    def set_active(self, active: bool) -> None:
        self.view.set_active(active)

    def _reflow_tools(self, rows: int) -> None:
        """ROI 工具列排成 1 或 2 列。"""
        if rows == self._tool_rows:
            return
        self._tool_rows = rows
        while self.tools_grid.count():
            item = self.tools_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        values = [self.roi_label, *self.spins.values()]
        actions = [self.clear_btn, self.hw_check, self.apply_btn, self.snap_btn]
        if rows == 1:
            for i, w in enumerate(values):
                self.tools_grid.addWidget(w, 0, i)
            for i, w in enumerate(actions):
                self.tools_grid.addWidget(w, 0, len(values) + i)
            self.tools_grid.setColumnStretch(len(values) + len(actions) - 1, 0)
        else:
            for i, w in enumerate(values):
                self.tools_grid.addWidget(w, 0, i)
            for i, w in enumerate(actions):
                self.tools_grid.addWidget(w, 1, i)
        for w in (*values, *actions):
            w.setVisible(True)
        self.snap_btn.setVisible(self._snap_visible)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reflow_tools(1 if self.width() >= 700 else 2)

    def set_channel(self, ch: Channel | None) -> None:
        self.channel = ch
        self.view.set_channel(ch)
        enabled = ch is not None
        for w in (*self.spins.values(), self.clear_btn, self.hw_check, self.apply_btn):
            w.setEnabled(enabled)
        self._loading = True
        self.hw_check.setChecked(bool(ch.cfg.hw_roi) if ch else False)
        self._loading = False
        self._show_roi(self.view.roi)
        self.refresh_buttons()

    def refresh_buttons(self) -> None:
        ch = self.channel
        self._snap_visible = bool(ch and ch.camera is not None and ch.camera.trigger_mode == "software" and ch.state == ChannelState.RUNNING)
        self.snap_btn.setVisible(self._snap_visible)

    def _show_roi(self, roi: Roi) -> None:
        self._loading = True
        for key in ("x", "y", "w", "h"):
            self.spins[key].setValue(int(getattr(roi, key)))
        self._loading = False

    def _on_view_roi(self, roi: Roi) -> None:
        self._show_roi(roi)
        self.status.setText(tr("live.roiChanged") if not roi.is_full() else tr("live.roiCleared"))

    def _on_spin(self, _v: int) -> None:
        if self._loading:
            return
        roi = Roi(*(self.spins[k].value() for k in ("x", "y", "w", "h")))
        self.view.set_roi(roi)
        self.status.setText(tr("live.roiChanged"))

    def clear_roi(self) -> None:
        self.view.set_roi(Roi())
        self._show_roi(Roi())
        self.apply_roi()

    def apply_roi(self) -> None:
        ch = self.channel
        if ch is None:
            return
        roi = Roi(*(self.spins[k].value() for k in ("x", "y", "w", "h")))
        hardware = self.hw_check.isChecked()
        self.apply_btn.setEnabled(False)
        self.status.setText(tr("live.applying"))

        def done(result: tuple[bool, Roi]) -> None:
            self.apply_btn.setEnabled(True)
            is_hw, effective = result
            self.view.hw_roi_active = is_hw
            self.view.set_roi(effective if is_hw else roi)
            self._show_roi(self.view.roi)
            self.engine.transport.send_channels()
            self.dirty.emit()
            if roi.is_full():
                self.status.setText(tr("live.fullRestored"))
            elif is_hw:
                self.status.setText(tr("live.hwApplied", w=effective.w, h=effective.h, x=effective.x, y=effective.y))
            else:
                self.status.setText(tr("live.swApplied", w=roi.w, h=roi.h, x=roi.x, y=roi.y) + (tr("live.noHwRoi") if hardware else ""))

        def failed(message: str) -> None:
            self.apply_btn.setEnabled(True)
            self.status.setText(tr("live.applyFailed", error=message))

        self.bridge.run_async(ch.apply_roi, roi, hardware, on_done=done, on_error=failed)

    def snap(self) -> None:
        ch = self.channel
        if ch is None:
            return
        self.snap_btn.setEnabled(False)
        self.bridge.run_async(ch.acquire, 0, 2.0, after_request=True, on_done=lambda f: (self.snap_btn.setEnabled(True), self.status.setText(tr("live.snapped") if f is not None else tr("live.snapTimeout"))),
                              on_error=lambda m: (self.snap_btn.setEnabled(True), self.status.setText(tr("live.snapFailed", error=m))))
