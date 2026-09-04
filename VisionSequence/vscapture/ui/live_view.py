"""即時預覽與 ROI 圈選：`LiveView` 畫影像＋ROI（拖曳建立、8 個把手縮放、拖移），`LivePanel` 加上數值欄與套用鈕。"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from vscapture.channel import Channel, ChannelState
from vscapture.config import Roi
from vscapture.engine import CaptureEngine
from vscapture.frames import to_display
from vscapture.ui.bridge import EngineBridge
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
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#0b0f14;")
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
        self.message = "請選擇通道"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.set_preview_fps(15)

    def set_preview_fps(self, fps: int) -> None:
        self.timer.start(max(16, int(1000 / max(1, fps))))

    def set_channel(self, ch: Channel | None) -> None:
        self.channel = ch
        self._img = None
        self._seq = -1
        self.roi = Roi(ch.cfg.roi.x, ch.cfg.roi.y, ch.cfg.roi.w, ch.cfg.roi.h) if ch else Roi()
        self.hw_roi_active = bool(ch.hw_roi_active) if ch else False
        self.message = "請選擇通道" if ch is None else "尚無影像"
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
            if self._img is not None or self.message != "預覽已關閉":
                self._img, self.message = None, "預覽已關閉"
                self.update()
            return
        latest = ch.slot.latest()
        if latest is None:
            if self._img is not None:
                self._img = None
                self.message = "尚無影像（相機尚未開始取像）" if ch.state != ChannelState.RUNNING else "等待影格…"
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
        p.fillRect(self.rect(), QColor("#0b0f14"))
        if self._img is None:
            p.setPen(QColor("#6b7280"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            p.end()
            return
        target = self._fit()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(target, self._img)
        r = self._roi_rect_disp()
        if r is not None:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor("#22d3ee"), 2))
            p.setBrush(QColor(34, 211, 238, 30))
            p.drawRect(r)
            p.setBrush(QColor("#22d3ee"))
            p.setPen(QPen(QColor("#0b0f14"), 1))
            for hp in self._handles(r):
                p.drawRect(QRectF(hp.x() - HANDLE / 2, hp.y() - HANDLE / 2, HANDLE, HANDLE))
            p.setPen(QColor("#22d3ee"))
            p.drawText(QPointF(r.left() + 4, max(r.top() - 6, 14)), f"ROI {self.roi.x},{self.roi.y}  {self.roi.w}×{self.roi.h}")
        # HUD
        font = QFont("Consolas")
        font.setPointSize(9)
        p.setFont(font)
        w, h = self._img_size
        parts = [f"#{self._seq}", f"{self._fps:.1f} fps", f"{w}×{h}"]
        if self.hw_roi_active:
            parts.append(f"硬體 ROI @ {self.origin[0]},{self.origin[1]}")
        text = "  ·  ".join(parts)
        p.setPen(QColor(0, 0, 0, 160))
        p.drawText(QPointF(target.left() + 9, target.top() + 17), text)
        p.setPen(QColor("#e5e7eb"))
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
        self.view = LiveView()
        self.view.roi_changed.connect(self._on_view_roi)
        self.view.roi_dragging.connect(self._show_roi)

        self.spins: dict[str, QSpinBox] = {}
        row = QHBoxLayout()
        row.addWidget(QLabel("ROI"))
        for key, label in (("x", "X"), ("y", "Y"), ("w", "寬"), ("h", "高")):
            sp = QSpinBox()
            sp.setRange(0, 100000)
            sp.setKeyboardTracking(False)
            sp.setPrefix(f"{label} ")
            sp.valueChanged.connect(self._on_spin)
            self.spins[key] = sp
            row.addWidget(sp)
        self.clear_btn = QPushButton("清除 ROI")
        self.clear_btn.clicked.connect(self.clear_roi)
        self.hw_check = QCheckBox("使用相機硬體 ROI")
        self.hw_check.setToolTip("相機支援時只讀出 ROI 範圍（更高的影格率）；不支援時以軟體裁切後傳送。")
        self.apply_btn = QPushButton("套用 ROI")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.apply_roi)
        self.snap_btn = QPushButton("拍攝一張")
        self.snap_btn.setToolTip("軟體觸發模式：觸發相機拍一張")
        self.snap_btn.clicked.connect(self.snap)
        row.addWidget(self.clear_btn)
        row.addWidget(self.hw_check)
        row.addWidget(self.apply_btn)
        row.addStretch(1)
        row.addWidget(self.snap_btn)
        self.status = muted("在影像上拖曳圈選 ROI；只有 ROI 範圍會傳給伺服端。")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view, 1)
        lay.addLayout(row)
        lay.addWidget(self.status)
        self.set_channel(None)

    def set_preview_fps(self, fps: int) -> None:
        self.view.set_preview_fps(fps)

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
        software = bool(ch and ch.camera is not None and ch.camera.trigger_mode == "software" and ch.state == ChannelState.RUNNING)
        self.snap_btn.setVisible(software)

    def _show_roi(self, roi: Roi) -> None:
        self._loading = True
        for key in ("x", "y", "w", "h"):
            self.spins[key].setValue(int(getattr(roi, key)))
        self._loading = False

    def _on_view_roi(self, roi: Roi) -> None:
        self._show_roi(roi)
        self.status.setText("ROI 已更新，點選「套用 ROI」才會生效。" if not roi.is_full() else "ROI 已清除（全幅），點選「套用 ROI」生效。")

    def _on_spin(self, _v: int) -> None:
        if self._loading:
            return
        roi = Roi(*(self.spins[k].value() for k in ("x", "y", "w", "h")))
        self.view.set_roi(roi)
        self.status.setText("ROI 已更新，點選「套用 ROI」才會生效。")

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
        self.status.setText("套用中…")

        def done(result: tuple[bool, Roi]) -> None:
            self.apply_btn.setEnabled(True)
            is_hw, effective = result
            self.view.hw_roi_active = is_hw
            self.view.set_roi(effective if is_hw else roi)
            self._show_roi(self.view.roi)
            self.engine.transport.send_channels()
            self.dirty.emit()
            if roi.is_full():
                self.status.setText("已恢復全幅。")
            elif is_hw:
                self.status.setText(f"硬體 ROI 已生效：{effective.w}×{effective.h} @ {effective.x},{effective.y}（依相機對齊）。預覽即 ROI 範圍。")
            else:
                self.status.setText(f"ROI 已套用（軟體裁切）：{roi.w}×{roi.h} @ {roi.x},{roi.y}。" + ("此相機不支援硬體 ROI。" if hardware else ""))

        def failed(message: str) -> None:
            self.apply_btn.setEnabled(True)
            self.status.setText(f"套用失敗：{message}")

        self.bridge.run_async(ch.apply_roi, roi, hardware, on_done=done, on_error=failed)

    def snap(self) -> None:
        ch = self.channel
        if ch is None:
            return
        self.snap_btn.setEnabled(False)
        self.bridge.run_async(ch.acquire, 0, 2.0, after_request=True, on_done=lambda f: (self.snap_btn.setEnabled(True), self.status.setText("已拍攝一張。" if f is not None else "拍攝逾時。")),
                              on_error=lambda m: (self.snap_btn.setEnabled(True), self.status.setText(f"拍攝失敗：{m}")))
