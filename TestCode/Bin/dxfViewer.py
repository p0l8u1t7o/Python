"""
DXF Fixture Nail 座標擷取工具
================================

功能：
  1. 開啟 DXF 檔案，於畫面上以 OpenGL 加速繪製所有幾何線段（LINE / LWPOLYLINE /
     POLYLINE / CIRCLE / ARC / SPLINE，並會嘗試展開 INSERT 區塊）。
  2. 選擇 DXF 中代表 Fixture Nails 的圖層（POINT / CIRCLE / INSERT 皆可視為
     Nail 候選點，取其座標），載入後以醒目顏色的點標示在畫面上。
  3. 使用滑鼠左鍵拖曳框選（Shift 加選 / Alt 減選）要輸出的 Fixture Nails。
  4. 將選取到的 Nail 座標 (X, Y) 匯出成 CSV 檔案。

安裝方式：
    pip install -r requirements.txt

執行方式：
    python dxf_fixture_nail_selector.py

滑鼠操作：
    左鍵拖曳   -> 框選 Fixture Nails（Shift 加選、Alt 減選）
    右鍵/中鍵拖曳 -> 平移畫面
    滾輪       -> 以游標位置為中心縮放（不卡頓，全部以 OpenGL 繪製）
"""

import sys
import os
import csv
import math
from dataclasses import dataclass, field
from typing import List, Optional, Set

import numpy as np

try:
    import ezdxf
except ImportError:
    print("請先安裝 ezdxf: pip install ezdxf")
    raise

from PyQt5 import QtGui
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QOpenGLWidget, QToolBar, QAction,
    QFileDialog, QDockWidget, QTableWidget, QTableWidgetItem,
    QComboBox, QLabel, QWidget, QVBoxLayout,
    QMessageBox, QStatusBar, QHeaderView
)

from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_LINE_SMOOTH, GL_POINT_SMOOTH, GL_BLEND,
    GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_LINE_SMOOTH_HINT, GL_NICEST,
    GL_PROJECTION, GL_MODELVIEW, GL_VERTEX_ARRAY, GL_LINES, GL_POINTS,
    GL_FLOAT, GL_LINE_LOOP, GL_QUADS,
    glClearColor, glEnable, glBlendFunc, glHint, glViewport, glClear,
    glMatrixMode, glLoadIdentity, glOrtho, glColor4f, glLineWidth,
    glPointSize, glEnableClientState, glDisableClientState,
    glVertexPointer, glDrawArrays, glPushMatrix, glPopMatrix,
    glBegin, glEnd, glVertex2f,
)


# ----------------------------------------------------------------------------
# 資料結構
# ----------------------------------------------------------------------------

@dataclass
class NailPoint:
    x: float
    y: float
    layer: str
    handle: str
    source: str  # 來源實體類型: POINT / CIRCLE / INSERT


@dataclass
class DXFSceneData:
    lines: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), dtype=np.float32))
    layers: List[str] = field(default_factory=list)
    entities_by_layer: dict = field(default_factory=dict)  # layer -> 該圖層原始實體清單


# ----------------------------------------------------------------------------
# DXF 讀取與幾何攤平（將弧線/圓/雲形線攤平成線段，方便 OpenGL 直接繪製）
# ----------------------------------------------------------------------------

def tessellate_arc(cx, cy, r, start_deg, end_deg, segs=32):
    pts = []
    if end_deg < start_deg:
        end_deg += 360.0
    for i in range(segs + 1):
        a = math.radians(start_deg + (end_deg - start_deg) * i / segs)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def polyline_to_segments(points, closed=False):
    segs = []
    n = len(points)
    if n < 2:
        return segs
    for i in range(n - 1):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[i + 1][0], points[i + 1][1]
        segs.append((x1, y1, x2, y2))
    if closed:
        x1, y1 = points[-1][0], points[-1][1]
        x2, y2 = points[0][0], points[0][1]
        segs.append((x1, y1, x2, y2))
    return segs


def load_dxf(path: str) -> DXFSceneData:
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    all_segments = []
    layers = sorted({l.dxf.name for l in doc.layers})
    entities_by_layer = {}

    def add_entity(e):
        layer = e.dxf.layer
        entities_by_layer.setdefault(layer, []).append(e)

    def explode_insert(e, depth):
        if depth > 4:
            return
        try:
            for sub in e.virtual_entities():
                handle_entity(sub, depth + 1)
        except Exception:
            pass

    def handle_entity(e, depth=0):
        etype = e.dxftype()
        add_entity(e)

        try:
            if etype == "LINE":
                p1 = e.dxf.start
                p2 = e.dxf.end
                all_segments.append((p1.x, p1.y, p2.x, p2.y))

            elif etype == "LWPOLYLINE":
                pts = list(e.get_points('xy'))
                all_segments.extend(polyline_to_segments(pts, closed=e.closed))

            elif etype == "POLYLINE":
                pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
                all_segments.extend(polyline_to_segments(pts, closed=e.is_closed))

            elif etype == "CIRCLE":
                c = e.dxf.center
                r = e.dxf.radius
                pts = tessellate_arc(c.x, c.y, r, 0, 360, segs=48)
                all_segments.extend(polyline_to_segments(pts, closed=True))

            elif etype == "ARC":
                c = e.dxf.center
                r = e.dxf.radius
                pts = tessellate_arc(c.x, c.y, r, e.dxf.start_angle, e.dxf.end_angle, segs=32)
                all_segments.extend(polyline_to_segments(pts, closed=False))

            elif etype == "SPLINE":
                try:
                    pts = [(p.x, p.y) for p in e.flattening(0.2)]
                    all_segments.extend(polyline_to_segments(pts, closed=False))
                except Exception:
                    pass

            elif etype == "INSERT":
                explode_insert(e, depth)

            elif etype == "POINT":
                pass  # 不畫成線段，改為 Nail 候選點處理

        except Exception:
            pass

    for e in msp:
        handle_entity(e)

    if all_segments:
        lines_arr = np.array(all_segments, dtype=np.float32)
    else:
        lines_arr = np.zeros((0, 4), dtype=np.float32)

    return DXFSceneData(lines=lines_arr, layers=layers, entities_by_layer=entities_by_layer)


def extract_nails_from_layer(scene: DXFSceneData, layer_name: str) -> List[NailPoint]:
    """從指定圖層擷取 Fixture Nail 候選點座標。
    支援 POINT（插入點）、CIRCLE（圓心）、INSERT（區塊插入點）。
    """
    nails = []
    for e in scene.entities_by_layer.get(layer_name, []):
        etype = e.dxftype()
        try:
            if etype == "POINT":
                p = e.dxf.location
                nails.append(NailPoint(p.x, p.y, layer_name, e.dxf.handle, "POINT"))
            elif etype == "CIRCLE":
                c = e.dxf.center
                nails.append(NailPoint(c.x, c.y, layer_name, e.dxf.handle, "CIRCLE"))
            elif etype == "INSERT":
                p = e.dxf.insert
                nails.append(NailPoint(p.x, p.y, layer_name, e.dxf.handle, "INSERT"))
        except Exception:
            continue
    return nails


# ----------------------------------------------------------------------------
# OpenGL 加速的繪圖視窗
# ----------------------------------------------------------------------------

class GLViewport(QOpenGLWidget):
    selectionChanged = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setFocusPolicy(Qt.StrongFocus)

        self.lines = np.zeros((0, 4), dtype=np.float32)
        self.nails: List[NailPoint] = []
        self.selected: Set[int] = set()

        self.view_cx, self.view_cy = 0.0, 0.0
        self.scale = 1.0  # 每世界單位對應的像素數

        self._panning = False
        self._pan_last = None

        self._selecting = False
        self._select_start = None
        self._select_end = None

    # ---------------- OpenGL 生命週期 ----------------

    def initializeGL(self):
        glClearColor(0.10, 0.10, 0.12, 1.0)
        glEnable(GL_LINE_SMOOTH)
        glEnable(GL_POINT_SMOOTH)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)

    def resizeGL(self, w, h):
        glViewport(0, 0, max(w, 1), max(h, 1))

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT)
        w, h = max(self.width(), 1), max(self.height(), 1)

        left = self.view_cx - w / (2 * self.scale)
        right = self.view_cx + w / (2 * self.scale)
        bottom = self.view_cy - h / (2 * self.scale)
        top = self.view_cy + h / (2 * self.scale)

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(left, right, bottom, top, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        # 背景 DXF 幾何線段（單一 glDrawArrays 呼叫，速度快、不卡頓）
        if len(self.lines) > 0:
            glColor4f(0.55, 0.65, 0.75, 0.9)
            glLineWidth(1.0)
            glEnableClientState(GL_VERTEX_ARRAY)
            flat = self.lines.reshape(-1, 2)
            glVertexPointer(2, GL_FLOAT, 0, flat)
            glDrawArrays(GL_LINES, 0, len(flat))
            glDisableClientState(GL_VERTEX_ARRAY)

        # Fixture Nails
        if self.nails:
            unsel_pts, sel_pts = [], []
            for i, n in enumerate(self.nails):
                (sel_pts if i in self.selected else unsel_pts).append((n.x, n.y))

            if unsel_pts:
                glColor4f(1.0, 0.85, 0.2, 0.95)
                glPointSize(7.0)
                self._draw_points(unsel_pts)

            if sel_pts:
                glColor4f(1.0, 0.2, 0.2, 1.0)
                glPointSize(10.0)
                self._draw_points(sel_pts)

        if self._selecting and self._select_start and self._select_end:
            self._draw_rubber_band(w, h)

    def _draw_points(self, pts):
        arr = np.array(pts, dtype=np.float32)
        glEnableClientState(GL_VERTEX_ARRAY)
        glVertexPointer(2, GL_FLOAT, 0, arr)
        glDrawArrays(GL_POINTS, 0, len(arr))
        glDisableClientState(GL_VERTEX_ARRAY)

    def _draw_rubber_band(self, w, h):
        # 用獨立的像素座標系疊加畫出框選矩形
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, w, h, 0, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()

        x1, y1 = self._select_start
        x2, y2 = self._select_end

        glColor4f(0.2, 0.7, 1.0, 0.85)
        glLineWidth(1.5)
        glBegin(GL_LINE_LOOP)
        glVertex2f(x1, y1)
        glVertex2f(x2, y1)
        glVertex2f(x2, y2)
        glVertex2f(x1, y2)
        glEnd()

        glColor4f(0.2, 0.7, 1.0, 0.15)
        glBegin(GL_QUADS)
        glVertex2f(x1, y1)
        glVertex2f(x2, y1)
        glVertex2f(x2, y2)
        glVertex2f(x1, y2)
        glEnd()

        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()

    # ---------------- 座標轉換 ----------------

    def screen_to_world(self, sx, sy):
        w, h = max(self.width(), 1), max(self.height(), 1)
        wx = self.view_cx + (sx - w / 2) / self.scale
        wy = self.view_cy - (sy - h / 2) / self.scale
        return wx, wy

    # ---------------- 資料設定 ----------------

    def set_scene(self, lines: np.ndarray):
        self.lines = lines
        self.update()

    def set_nails(self, nails: List[NailPoint]):
        self.nails = nails
        self.selected = set()
        self.update()
        self.selectionChanged.emit([])

    def fit_view(self):
        xs, ys = [], []
        if len(self.lines) > 0:
            xs.extend(self.lines[:, 0].tolist())
            xs.extend(self.lines[:, 2].tolist())
            ys.extend(self.lines[:, 1].tolist())
            ys.extend(self.lines[:, 3].tolist())
        for n in self.nails:
            xs.append(n.x)
            ys.append(n.y)

        if not xs or not ys:
            self.view_cx, self.view_cy, self.scale = 0.0, 0.0, 1.0
            self.update()
            return

        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        bw = max(maxx - minx, 1e-6)
        bh = max(maxy - miny, 1e-6)

        w, h = max(self.width(), 1), max(self.height(), 1)
        self.scale = 0.9 * min(w / bw, h / bh)
        self.view_cx = (minx + maxx) / 2
        self.view_cy = (miny + maxy) / 2
        self.update()

    # ---------------- 滑鼠事件 ----------------

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._selecting = True
            self._select_start = (ev.x(), ev.y())
            self._select_end = (ev.x(), ev.y())
        elif ev.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = True
            self._pan_last = (ev.x(), ev.y())
        self.update()

    def mouseMoveEvent(self, ev):
        if self._selecting:
            self._select_end = (ev.x(), ev.y())
            self.update()
        elif self._panning and self._pan_last:
            dx = ev.x() - self._pan_last[0]
            dy = ev.y() - self._pan_last[1]
            self.view_cx -= dx / self.scale
            self.view_cy += dy / self.scale
            self._pan_last = (ev.x(), ev.y())
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            self._select_end = (ev.x(), ev.y())
            self._apply_box_select(ev.modifiers())
            self.update()
        elif ev.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = False
            self._pan_last = None

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15

        mx, my = ev.x(), ev.y()
        wx_before, wy_before = self.screen_to_world(mx, my)

        self.scale *= factor
        self.scale = max(min(self.scale, 1e7), 1e-6)

        wx_after, wy_after = self.screen_to_world(mx, my)
        self.view_cx += (wx_before - wx_after)
        self.view_cy += (wy_before - wy_after)
        self.update()

    def _apply_box_select(self, modifiers):
        if not self._select_start or not self._select_end:
            return
        sx1, sy1 = self._select_start
        sx2, sy2 = self._select_end

        if abs(sx2 - sx1) < 3 and abs(sy2 - sy1) < 3:
            return  # 視為點擊，不算框選

        wx1, wy1 = self.screen_to_world(sx1, sy1)
        wx2, wy2 = self.screen_to_world(sx2, sy2)
        xmin, xmax = min(wx1, wx2), max(wx1, wx2)
        ymin, ymax = min(wy1, wy2), max(wy1, wy2)

        newly = set()
        for i, n in enumerate(self.nails):
            if xmin <= n.x <= xmax and ymin <= n.y <= ymax:
                newly.add(i)

        additive = bool(modifiers & Qt.ShiftModifier)
        subtractive = bool(modifiers & Qt.AltModifier)

        if subtractive:
            self.selected -= newly
        elif additive:
            self.selected |= newly
        else:
            self.selected = newly

        self.selectionChanged.emit([self.nails[i] for i in sorted(self.selected)])


# ----------------------------------------------------------------------------
# 主視窗
# ----------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DXF Fixture Nail 座標擷取工具")
        self.resize(1280, 800)

        self.scene: Optional[DXFSceneData] = None
        self.current_path = None

        self.viewport = GLViewport(self)
        self.setCentralWidget(self.viewport)
        self.viewport.selectionChanged.connect(self.on_selection_changed)

        self._build_toolbar()
        self._build_side_panel()
        self._build_statusbar()

    def _build_toolbar(self):
        tb = QToolBar("主工具列")
        tb.setMovable(False)
        self.addToolBar(tb)

        act_open = QAction("開啟 DXF...", self)
        act_open.triggered.connect(self.open_dxf)
        tb.addAction(act_open)

        act_fit = QAction("縮放至全圖", self)
        act_fit.triggered.connect(self.viewport.fit_view)
        tb.addAction(act_fit)

        tb.addSeparator()

        tb.addWidget(QLabel(" Fixture Nail 圖層： "))
        self.layer_combo = QComboBox()
        self.layer_combo.setMinimumWidth(220)
        tb.addWidget(self.layer_combo)

        act_load_nails = QAction("載入此圖層的 Nails", self)
        act_load_nails.triggered.connect(self.load_nails_from_layer)
        tb.addAction(act_load_nails)

        tb.addSeparator()

        act_clear_sel = QAction("清除選取", self)
        act_clear_sel.triggered.connect(self.clear_selection)
        tb.addAction(act_clear_sel)

        act_export = QAction("匯出選取座標 (CSV)...", self)
        act_export.triggered.connect(self.export_selected_csv)
        tb.addAction(act_export)

    def _build_side_panel(self):
        dock = QDockWidget("已選取 Fixture Nails", self)
        dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)

        container = QWidget()
        layout = QVBoxLayout(container)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["#", "X", "Y"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        hint = QLabel(
            "操作說明：\n"
            "左鍵拖曳＝框選 Nails（Shift 加選、Alt 減選）\n"
            "右鍵/中鍵拖曳＝平移畫面\n"
            "滾輪＝以游標為中心縮放"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        dock.setWidget(container)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_statusbar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("請開啟 DXF 檔案")

    # ---------------- 動作 ----------------

    def open_dxf(self):
        path, _ = QFileDialog.getOpenFileName(self, "開啟 DXF 檔案", "", "DXF Files (*.dxf)")
        if not path:
            return
        try:
            scene = load_dxf(path)
        except Exception as ex:
            QMessageBox.critical(self, "讀取失敗", f"無法讀取 DXF 檔案：\n{ex}")
            return

        self.scene = scene
        self.current_path = path
        self.viewport.set_scene(scene.lines)
        self.viewport.set_nails([])
        self.table.setRowCount(0)

        self.layer_combo.clear()
        self.layer_combo.addItems(scene.layers)

        # 嘗試自動選取名稱包含 nail / fixture / pin 的圖層
        for i, name in enumerate(scene.layers):
            low = name.lower()
            if "nail" in low or "fixture" in low or "pin" in low:
                self.layer_combo.setCurrentIndex(i)
                break

        self.viewport.fit_view()
        self.status.showMessage(f"已載入：{os.path.basename(path)}（共 {len(scene.layers)} 個圖層）")

    def load_nails_from_layer(self):
        if not self.scene:
            QMessageBox.warning(self, "尚未載入檔案", "請先開啟 DXF 檔案")
            return
        layer = self.layer_combo.currentText()
        if not layer:
            return
        nails = extract_nails_from_layer(self.scene, layer)
        self.viewport.set_nails(nails)
        self.table.setRowCount(0)
        self.status.showMessage(f"圖層「{layer}」共找到 {len(nails)} 個 Fixture Nail 候選點")

    def clear_selection(self):
        self.viewport.selected = set()
        self.viewport.update()
        self.table.setRowCount(0)
        self.viewport.selectionChanged.emit([])

    def on_selection_changed(self, nails: List[NailPoint]):
        self.table.setRowCount(len(nails))
        for row, n in enumerate(nails):
            self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(f"{n.x:.4f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{n.y:.4f}"))
        self.status.showMessage(f"目前選取 {len(nails)} 個 Fixture Nail")

    def export_selected_csv(self):
        nails = [self.viewport.nails[i] for i in sorted(self.viewport.selected)]
        if not nails:
            QMessageBox.information(self, "沒有選取項目", "請先框選要輸出的 Fixture Nails")
            return
        path, _ = QFileDialog.getSaveFileName(self, "匯出座標 CSV", "fixture_nails.csv", "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Index", "X", "Y", "Layer", "Handle", "Source"])
                for i, n in enumerate(nails, start=1):
                    writer.writerow([i, f"{n.x:.6f}", f"{n.y:.6f}", n.layer, n.handle, n.source])
            QMessageBox.information(self, "匯出完成", f"已匯出 {len(nails)} 筆座標至：\n{path}")
        except Exception as ex:
            QMessageBox.critical(self, "匯出失敗", str(ex))


def main():
    fmt = QtGui.QSurfaceFormat()
    fmt.setSamples(4)          # 多重採樣抗鋸齒
    fmt.setSwapInterval(1)     # 開啟垂直同步，避免撕裂
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()