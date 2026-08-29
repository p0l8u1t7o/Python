/**
 * ROI 幾何工具：外框、中心、形狀轉換、夾在影像內、取整。
 * 全部以「影像像素座標」計算，不涉及螢幕座標。
 * 角度慣例：度數、影像座標系（y 向下）順時針為正，與 canvas ctx.rotate 一致。
 */
import type { Region, RoiShape } from '@/lib/types'

export interface Bounds {
  x: number
  y: number
  w: number
  h: number
}

export const DEG = Math.PI / 180

/** rotated_rect 四個角（順序：左上、右上、右下、左下） */
export function rotatedRectCorners(r: {
  cx: number
  cy: number
  w: number
  h: number
  angle: number
}): [number, number][] {
  const c = Math.cos(r.angle * DEG)
  const s = Math.sin(r.angle * DEG)
  const hw = r.w / 2
  const hh = r.h / 2
  const local: [number, number][] = [
    [-hw, -hh],
    [hw, -hh],
    [hw, hh],
    [-hw, hh],
  ]
  return local.map(([lx, ly]) => [r.cx + lx * c - ly * s, r.cy + lx * s + ly * c])
}

function pointsBounds(points: [number, number][]): Bounds {
  if (points.length === 0) return { x: 0, y: 0, w: 0, h: 0 }
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const [x, y] of points) {
    if (x < minX) minX = x
    if (y < minY) minY = y
    if (x > maxX) maxX = x
    if (y > maxY) maxY = y
  }
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
}

/** 軸對齊外框 */
export function regionBounds(r: Region): Bounds {
  switch (r.shape) {
    case 'rect':
      return { x: r.x, y: r.y, w: r.w, h: r.h }
    case 'rotated_rect':
      return pointsBounds(rotatedRectCorners(r))
    case 'circle':
      return { x: r.cx - r.r, y: r.cy - r.r, w: r.r * 2, h: r.r * 2 }
    case 'annulus':
      return { x: r.cx - r.r_outer, y: r.cy - r.r_outer, w: r.r_outer * 2, h: r.r_outer * 2 }
    case 'polygon':
      return pointsBounds(r.points)
    case 'line':
      return pointsBounds([
        [r.x1, r.y1],
        [r.x2, r.y2],
      ])
  }
}

export function regionCenter(r: Region): [number, number] {
  const b = regionBounds(r)
  return [b.x + b.w / 2, b.y + b.h / 2]
}

/** 把目前 ROI 轉成另一種形狀（以中心／外框近似），切換形狀工具時用。 */
export function convertRegion(r: Region, shape: RoiShape): Region {
  if (r.shape === shape) return r
  const b = regionBounds(r)
  const w = Math.max(b.w, 2)
  const h = Math.max(b.h, 2)
  const cx = b.x + b.w / 2
  const cy = b.y + b.h / 2
  switch (shape) {
    case 'rect':
      return { shape: 'rect', x: b.x, y: b.y, w, h }
    case 'rotated_rect':
      return { shape: 'rotated_rect', cx, cy, w, h, angle: 0 }
    case 'circle':
      return { shape: 'circle', cx, cy, r: Math.max(Math.min(w, h) / 2, 1) }
    case 'annulus': {
      const outer = r.shape === 'circle' ? r.r : Math.max(Math.min(w, h) / 2, 2)
      return { shape: 'annulus', cx, cy, r_inner: outer / 2, r_outer: outer }
    }
    case 'polygon': {
      if (r.shape === 'rotated_rect') return { shape: 'polygon', points: rotatedRectCorners(r) }
      return {
        shape: 'polygon',
        points: [
          [b.x, b.y],
          [b.x + w, b.y],
          [b.x + w, b.y + h],
          [b.x, b.y + h],
        ],
      }
    }
    case 'line':
      return { shape: 'line', x1: b.x, y1: cy, x2: b.x + w, y2: cy }
  }
}

/** 在 (x, y) 附近建立預設 ROI（繪製模式起點／沒有現成 ROI 時） */
export function regionFromDrag(shape: RoiShape, x0: number, y0: number, x1: number, y1: number): Region {
  const x = Math.min(x0, x1)
  const y = Math.min(y0, y1)
  const w = Math.abs(x1 - x0)
  const h = Math.abs(y1 - y0)
  const d = Math.hypot(x1 - x0, y1 - y0)
  switch (shape) {
    case 'rect':
      return { shape: 'rect', x, y, w, h }
    case 'rotated_rect':
      return { shape: 'rotated_rect', cx: x + w / 2, cy: y + h / 2, w, h, angle: 0 }
    case 'circle':
      return { shape: 'circle', cx: x0, cy: y0, r: d }
    case 'annulus':
      return { shape: 'annulus', cx: x0, cy: y0, r_inner: d / 2, r_outer: d }
    case 'polygon':
      return {
        shape: 'polygon',
        points: [
          [x, y],
          [x + w, y],
          [x + w, y + h],
          [x, y + h],
        ],
      }
    case 'line':
      return { shape: 'line', x1: x0, y1: y0, x2: x1, y2: y1 }
  }
}

export function translateRegion(r: Region, dx: number, dy: number): Region {
  switch (r.shape) {
    case 'rect':
      return { ...r, x: r.x + dx, y: r.y + dy }
    case 'rotated_rect':
    case 'circle':
    case 'annulus':
      return { ...r, cx: r.cx + dx, cy: r.cy + dy }
    case 'polygon':
      return { ...r, points: r.points.map(([x, y]) => [x + dx, y + dy]) }
    case 'line':
      return { ...r, x1: r.x1 + dx, y1: r.y1 + dy, x2: r.x2 + dx, y2: r.y2 + dy }
  }
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)

/** 夾在影像範圍內 */
export function clampRegion(r: Region, W: number, H: number): Region {
  switch (r.shape) {
    case 'rect': {
      const w = Math.min(r.w, W)
      const h = Math.min(r.h, H)
      return { shape: 'rect', x: clamp(r.x, 0, W - w), y: clamp(r.y, 0, H - h), w, h }
    }
    case 'rotated_rect': {
      let rr = r
      const b0 = regionBounds(rr)
      // 外框比影像大：等比縮小
      const k = Math.min(1, W / Math.max(b0.w, 1), H / Math.max(b0.h, 1))
      if (k < 1) rr = { ...rr, w: rr.w * k, h: rr.h * k }
      const b = regionBounds(rr)
      const dx = clamp(b.x, 0, W - b.w) - b.x
      const dy = clamp(b.y, 0, H - b.h) - b.y
      return { ...rr, cx: rr.cx + dx, cy: rr.cy + dy }
    }
    case 'circle': {
      const rad = Math.min(r.r, W / 2, H / 2)
      return { shape: 'circle', cx: clamp(r.cx, rad, W - rad), cy: clamp(r.cy, rad, H - rad), r: rad }
    }
    case 'annulus': {
      const outer = Math.min(r.r_outer, W / 2, H / 2)
      return {
        shape: 'annulus',
        cx: clamp(r.cx, outer, W - outer),
        cy: clamp(r.cy, outer, H - outer),
        r_inner: Math.min(r.r_inner, outer - 1),
        r_outer: outer,
      }
    }
    case 'polygon':
      return { shape: 'polygon', points: r.points.map(([x, y]) => [clamp(x, 0, W), clamp(y, 0, H)]) }
    case 'line':
      return {
        shape: 'line',
        x1: clamp(r.x1, 0, W),
        y1: clamp(r.y1, 0, H),
        x2: clamp(r.x2, 0, W),
        y2: clamp(r.y2, 0, H),
      }
  }
}

/** 數值取整：座標／長度取整數，角度保留 1 位小數；尺寸至少 1。 */
export function roundRegion(r: Region): Region {
  const R = Math.round
  switch (r.shape) {
    case 'rect':
      return { shape: 'rect', x: R(r.x), y: R(r.y), w: Math.max(1, R(r.w)), h: Math.max(1, R(r.h)) }
    case 'rotated_rect':
      return {
        shape: 'rotated_rect',
        cx: R(r.cx),
        cy: R(r.cy),
        w: Math.max(1, R(r.w)),
        h: Math.max(1, R(r.h)),
        angle: Math.round(normalizeAngle(r.angle) * 10) / 10,
      }
    case 'circle':
      return { shape: 'circle', cx: R(r.cx), cy: R(r.cy), r: Math.max(1, R(r.r)) }
    case 'annulus': {
      const outer = Math.max(2, R(r.r_outer))
      return {
        shape: 'annulus',
        cx: R(r.cx),
        cy: R(r.cy),
        r_inner: clamp(R(r.r_inner), 0, outer - 1),
        r_outer: outer,
      }
    }
    case 'polygon':
      return { shape: 'polygon', points: r.points.map(([x, y]) => [R(x), R(y)]) }
    case 'line':
      return { shape: 'line', x1: R(r.x1), y1: R(r.y1), x2: R(r.x2), y2: R(r.y2) }
  }
}

/** 角度正規化到 (-180, 180] */
export function normalizeAngle(a: number): number {
  let v = a % 360
  if (v > 180) v -= 360
  if (v <= -180) v += 360
  return v
}

export function regionsEqual(a: Region | null | undefined, b: Region | null | undefined): boolean {
  if (a === b) return true
  if (!a || !b) return false
  return JSON.stringify(a) === JSON.stringify(b)
}

/** 點到線段距離 */
export function distToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const len2 = dx * dx + dy * dy
  let t = len2 === 0 ? 0 : ((px - x1) * dx + (py - y1) * dy) / len2
  t = clamp(t, 0, 1)
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

export function pointInPolygon(px: number, py: number, pts: [number, number][]): boolean {
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i]
    const [xj, yj] = pts[j]
    const intersect = yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi
    if (intersect) inside = !inside
  }
  return inside
}
