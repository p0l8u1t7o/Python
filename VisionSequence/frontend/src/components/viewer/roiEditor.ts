/**
 * ROI 編輯：把手、命中判定、拖曳套用、繪製。
 *
 * 所有幾何以影像座標計算；把手大小與命中容差以螢幕像素給定，透過 scale 換算。
 * 拖曳套用是純函式 applyHandleDrag(region0, handle, 起點, 目前點, shift) → 新 region，
 * 起點／region0 在 pointerdown 時固定，避免累積誤差。
 */
import type { Region } from '@/lib/types'
import {
  DEG,
  distToSegment,
  normalizeAngle,
  pointInPolygon,
  regionBounds,
  rotatedRectCorners,
  translateRegion,
} from './geometry'
import { applyImageTransform, drawLabel, type DrawEnv } from './drawOverlays'

export const ROI_COLOR = '#38bdf8'
export const HANDLE_SIZE = 8 // 螢幕 px
export const HIT_TOLERANCE = 8 // 螢幕 px
const ROTATE_HANDLE_OFFSET = 28 // 旋轉把手離頂邊的螢幕 px

export type HandleKind =
  | 'resize' // rect / rotated_rect 8 個
  | 'rotate'
  | 'radius' // circle
  | 'inner' // annulus
  | 'outer'
  | 'vertex' // polygon
  | 'endpoint' // line

export interface Handle {
  kind: HandleKind
  /** 影像座標 */
  x: number
  y: number
  /** resize：-1/0/1 表示左右／上下方向；vertex/endpoint：索引 */
  sx?: number
  sy?: number
  index?: number
  cursor: string
  /** 圓形把手（旋轉、半徑）或方形 */
  round?: boolean
}

/** resize 把手的游標：依旋轉角度挑最接近的方向 */
function resizeCursor(sx: number, sy: number, angleDeg: number): string {
  // 把手方向角（螢幕，順時針，0 = 右）
  let a = (Math.atan2(sy, sx) / DEG + angleDeg) % 360
  if (a < 0) a += 360
  // 每 45° 一段
  const seg = Math.round(a / 45) % 8
  const cursors = ['ew-resize', 'nwse-resize', 'ns-resize', 'nesw-resize']
  return cursors[seg % 4]
}

export function getHandles(r: Region, env: DrawEnv): Handle[] {
  const hs: Handle[] = []
  switch (r.shape) {
    case 'rect':
    case 'rotated_rect': {
      const angle = r.shape === 'rotated_rect' ? r.angle : 0
      const cx = r.shape === 'rect' ? r.x + r.w / 2 : r.cx
      const cy = r.shape === 'rect' ? r.y + r.h / 2 : r.cy
      const c = Math.cos(angle * DEG)
      const s = Math.sin(angle * DEG)
      const toWorld = (lx: number, ly: number): [number, number] => [
        cx + lx * c - ly * s,
        cy + lx * s + ly * c,
      ]
      for (const sy of [-1, 0, 1])
        for (const sx of [-1, 0, 1]) {
          if (sx === 0 && sy === 0) continue
          const [x, y] = toWorld((sx * r.w) / 2, (sy * r.h) / 2)
          hs.push({ kind: 'resize', x, y, sx, sy, cursor: resizeCursor(sx, sy, angle) })
        }
      if (r.shape === 'rotated_rect') {
        const [x, y] = toWorld(0, -r.h / 2 - ROTATE_HANDLE_OFFSET / env.scale)
        hs.push({ kind: 'rotate', x, y, cursor: 'grab', round: true })
      }
      break
    }
    case 'circle':
      for (const [dx, dy] of [
        [1, 0],
        [0, 1],
        [-1, 0],
        [0, -1],
      ])
        hs.push({
          kind: 'radius',
          x: r.cx + dx * r.r,
          y: r.cy + dy * r.r,
          cursor: dx ? 'ew-resize' : 'ns-resize',
          round: true,
        })
      break
    case 'annulus':
      for (const [dx, dy] of [
        [1, 0],
        [0, 1],
        [-1, 0],
        [0, -1],
      ]) {
        hs.push({
          kind: 'outer',
          x: r.cx + dx * r.r_outer,
          y: r.cy + dy * r.r_outer,
          cursor: dx ? 'ew-resize' : 'ns-resize',
          round: true,
        })
        hs.push({
          kind: 'inner',
          x: r.cx + dx * r.r_inner,
          y: r.cy + dy * r.r_inner,
          cursor: dx ? 'ew-resize' : 'ns-resize',
          round: true,
        })
      }
      break
    case 'polygon':
      r.points.forEach(([x, y], i) => hs.push({ kind: 'vertex', x, y, index: i, cursor: 'move' }))
      break
    case 'line':
      hs.push({ kind: 'endpoint', x: r.x1, y: r.y1, index: 0, cursor: 'move' })
      hs.push({ kind: 'endpoint', x: r.x2, y: r.y2, index: 1, cursor: 'move' })
      break
  }
  return hs
}

/** 命中把手（ix, iy 為影像座標） */
export function hitHandle(handles: Handle[], ix: number, iy: number, scale: number): Handle | null {
  const tol = HIT_TOLERANCE / scale
  let best: Handle | null = null
  let bestD = Infinity
  for (const h of handles) {
    const d = Math.hypot(h.x - ix, h.y - iy)
    if (d <= tol && d < bestD) {
      best = h
      bestD = d
    }
  }
  return best
}

/** 命中形狀本體（用來拖曳移動） */
export function hitBody(r: Region, ix: number, iy: number, scale: number): boolean {
  const tol = HIT_TOLERANCE / scale
  switch (r.shape) {
    case 'rect':
      return ix >= r.x && ix <= r.x + r.w && iy >= r.y && iy <= r.y + r.h
    case 'rotated_rect': {
      const c = Math.cos(-r.angle * DEG)
      const s = Math.sin(-r.angle * DEG)
      const dx = ix - r.cx
      const dy = iy - r.cy
      const lx = dx * c - dy * s
      const ly = dx * s + dy * c
      return Math.abs(lx) <= r.w / 2 && Math.abs(ly) <= r.h / 2
    }
    case 'circle':
      return Math.hypot(ix - r.cx, iy - r.cy) <= r.r
    case 'annulus': {
      const d = Math.hypot(ix - r.cx, iy - r.cy)
      return d <= r.r_outer && d >= r.r_inner
    }
    case 'polygon':
      return pointInPolygon(ix, iy, r.points)
    case 'line':
      return distToSegment(ix, iy, r.x1, r.y1, r.x2, r.y2) <= tol
  }
}

/** polygon：找最近的邊（雙擊新增頂點用），回傳插入位置（在該索引之後） */
export function hitPolygonEdge(
  r: Extract<Region, { shape: 'polygon' }>,
  ix: number,
  iy: number,
  scale: number,
): number | null {
  const tol = HIT_TOLERANCE / scale
  let best: number | null = null
  let bestD = tol
  const n = r.points.length
  for (let i = 0; i < n; i++) {
    const [x1, y1] = r.points[i]
    const [x2, y2] = r.points[(i + 1) % n]
    const d = distToSegment(ix, iy, x1, y1, x2, y2)
    if (d <= bestD) {
      bestD = d
      best = i
    }
  }
  return best
}

function snapAngle(deg: number, step = 15): number {
  return Math.round(deg / step) * step
}

/** 套用把手拖曳 */
export function applyHandleDrag(
  r0: Region,
  h: Handle,
  ix: number,
  iy: number,
  shift: boolean,
): Region {
  switch (r0.shape) {
    case 'rect':
    case 'rotated_rect': {
      const angle = r0.shape === 'rotated_rect' ? r0.angle : 0
      const cx = r0.shape === 'rect' ? r0.x + r0.w / 2 : r0.cx
      const cy = r0.shape === 'rect' ? r0.y + r0.h / 2 : r0.cy
      if (h.kind === 'rotate' && r0.shape === 'rotated_rect') {
        // 把手在頂邊上方，所以指標方向 + 90° 即為矩形角度
        let a = Math.atan2(iy - cy, ix - cx) / DEG + 90
        if (shift) a = snapAngle(a)
        return { ...r0, angle: normalizeAngle(a) }
      }
      if (h.kind !== 'resize') return r0
      // 指標轉到矩形的局部座標（未旋轉）
      const c = Math.cos(-angle * DEG)
      const s = Math.sin(-angle * DEG)
      const dx = ix - cx
      const dy = iy - cy
      const lx = dx * c - dy * s
      const ly = dx * s + dy * c
      let left = -r0.w / 2
      let right = r0.w / 2
      let top = -r0.h / 2
      let bottom = r0.h / 2
      const sx = h.sx ?? 0
      const sy = h.sy ?? 0
      if (sx === 1) right = Math.max(lx, left + 1)
      if (sx === -1) left = Math.min(lx, right - 1)
      if (sy === 1) bottom = Math.max(ly, top + 1)
      if (sy === -1) top = Math.min(ly, bottom - 1)
      if (shift && sx !== 0 && sy !== 0) {
        // 等比例：以原比例，取較大的變化量
        const ratio = r0.w / Math.max(r0.h, 1)
        const w = right - left
        const hgt = bottom - top
        if (w / ratio > hgt) {
          const nh = w / ratio
          if (sy === 1) bottom = top + nh
          else top = bottom - nh
        } else {
          const nw = hgt * ratio
          if (sx === 1) right = left + nw
          else left = right - nw
        }
      }
      const w = right - left
      const hgt = bottom - top
      const lcx = (left + right) / 2
      const lcy = (top + bottom) / 2
      // 局部中心轉回世界
      const cw = Math.cos(angle * DEG)
      const sw = Math.sin(angle * DEG)
      const ncx = cx + lcx * cw - lcy * sw
      const ncy = cy + lcx * sw + lcy * cw
      if (r0.shape === 'rect') return { shape: 'rect', x: ncx - w / 2, y: ncy - hgt / 2, w, h: hgt }
      return { ...r0, cx: ncx, cy: ncy, w, h: hgt }
    }
    case 'circle':
      return { ...r0, r: Math.max(1, Math.hypot(ix - r0.cx, iy - r0.cy)) }
    case 'annulus': {
      const d = Math.hypot(ix - r0.cx, iy - r0.cy)
      if (h.kind === 'inner') return { ...r0, r_inner: Math.max(0, Math.min(d, r0.r_outer - 1)) }
      return { ...r0, r_outer: Math.max(d, r0.r_inner + 1, 1) }
    }
    case 'polygon': {
      const i = h.index ?? 0
      const points = r0.points.map((p, k) => (k === i ? ([ix, iy] as [number, number]) : p))
      return { ...r0, points }
    }
    case 'line': {
      let x = ix
      let y = iy
      const ox = h.index === 0 ? r0.x2 : r0.x1
      const oy = h.index === 0 ? r0.y2 : r0.y1
      if (shift) {
        // 角度吸附 15°
        const len = Math.hypot(ix - ox, iy - oy)
        const a = snapAngle(Math.atan2(iy - oy, ix - ox) / DEG) * DEG
        x = ox + Math.cos(a) * len
        y = oy + Math.sin(a) * len
      }
      return h.index === 0 ? { ...r0, x1: x, y1: y } : { ...r0, x2: x, y2: y }
    }
  }
}

export function applyMove(r0: Region, dx: number, dy: number): Region {
  return translateRegion(r0, dx, dy)
}

// ---------------- 繪製 ----------------

export interface RoiDrawOptions {
  /** 顯示把手（編輯模式） */
  handles: boolean
  /** 目前被抓住／hover 的把手（畫成填白） */
  active?: Handle | null
  /** polygon 選中的頂點索引 */
  selectedVertex?: number | null
}

export function drawRoi(ctx: CanvasRenderingContext2D, env: DrawEnv, r: Region, opts: RoiDrawOptions) {
  const { scale } = env
  const px = (n: number) => n / scale
  ctx.save()
  applyImageTransform(ctx, env)
  ctx.strokeStyle = ROI_COLOR
  ctx.fillStyle = 'rgba(56,189,248,0.12)'
  ctx.lineWidth = px(1.5)
  ctx.setLineDash([])
  ctx.lineJoin = 'round'

  switch (r.shape) {
    case 'rect':
      ctx.fillRect(r.x, r.y, r.w, r.h)
      ctx.strokeRect(r.x, r.y, r.w, r.h)
      break
    case 'rotated_rect': {
      const pts = rotatedRectCorners(r)
      ctx.beginPath()
      ctx.moveTo(pts[0][0], pts[0][1])
      for (let i = 1; i < 4; i++) ctx.lineTo(pts[i][0], pts[i][1])
      ctx.closePath()
      ctx.fill()
      ctx.stroke()
      // 中心十字與到旋轉把手的連線
      const a = px(6)
      ctx.beginPath()
      ctx.moveTo(r.cx - a, r.cy)
      ctx.lineTo(r.cx + a, r.cy)
      ctx.moveTo(r.cx, r.cy - a)
      ctx.lineTo(r.cx, r.cy + a)
      ctx.stroke()
      if (opts.handles) {
        const c = Math.cos(r.angle * DEG)
        const s = Math.sin(r.angle * DEG)
        const topX = r.cx + (r.h / 2) * s
        const topY = r.cy - (r.h / 2) * c
        const off = ROTATE_HANDLE_OFFSET / scale
        ctx.setLineDash([px(3), px(3)])
        ctx.beginPath()
        ctx.moveTo(topX, topY)
        ctx.lineTo(topX + off * s, topY - off * c)
        ctx.stroke()
        ctx.setLineDash([])
      }
      break
    }
    case 'circle':
      ctx.beginPath()
      ctx.arc(r.cx, r.cy, Math.max(r.r, 0), 0, Math.PI * 2)
      ctx.fill()
      ctx.stroke()
      drawCross(ctx, r.cx, r.cy, px(5))
      break
    case 'annulus':
      ctx.beginPath()
      ctx.arc(r.cx, r.cy, Math.max(r.r_outer, 0), 0, Math.PI * 2)
      ctx.moveTo(r.cx + r.r_inner, r.cy)
      ctx.arc(r.cx, r.cy, Math.max(r.r_inner, 0), 0, Math.PI * 2, true)
      ctx.fill('evenodd')
      ctx.stroke()
      drawCross(ctx, r.cx, r.cy, px(5))
      break
    case 'polygon':
      if (r.points.length >= 2) {
        ctx.beginPath()
        ctx.moveTo(r.points[0][0], r.points[0][1])
        for (let i = 1; i < r.points.length; i++) ctx.lineTo(r.points[i][0], r.points[i][1])
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
      }
      break
    case 'line':
      ctx.beginPath()
      ctx.moveTo(r.x1, r.y1)
      ctx.lineTo(r.x2, r.y2)
      ctx.stroke()
      break
  }

  if (opts.handles) {
    const hs = getHandles(r, env)
    const half = px(HANDLE_SIZE / 2)
    ctx.lineWidth = px(1.5)
    for (const h of hs) {
      const isActive =
        (opts.active && opts.active.kind === h.kind && opts.active.index === h.index &&
          opts.active.sx === h.sx && opts.active.sy === h.sy) ||
        (h.kind === 'vertex' && opts.selectedVertex === h.index)
      ctx.fillStyle = isActive ? '#ffffff' : ROI_COLOR
      ctx.strokeStyle = isActive ? ROI_COLOR : '#ffffff'
      ctx.beginPath()
      if (h.round) ctx.arc(h.x, h.y, half, 0, Math.PI * 2)
      else ctx.rect(h.x - half, h.y - half, half * 2, half * 2)
      ctx.fill()
      ctx.stroke()
    }
  }
  ctx.restore()

  // 說明文字（螢幕座標）：尺寸／角度
  const b = regionBounds(r)
  const info = describeRegion(r)
  const sx = b.x * scale + env.tx
  const sy = b.y * scale + env.ty
  drawLabel(ctx, env, sx, sy, info, ROI_COLOR)
}

function drawCross(ctx: CanvasRenderingContext2D, x: number, y: number, a: number) {
  ctx.beginPath()
  ctx.moveTo(x - a, y)
  ctx.lineTo(x + a, y)
  ctx.moveTo(x, y - a)
  ctx.lineTo(x, y + a)
  ctx.stroke()
}

export function describeRegion(r: Region): string {
  const R = Math.round
  switch (r.shape) {
    case 'rect':
      return `rect ${R(r.w)}×${R(r.h)} @ ${R(r.x)},${R(r.y)}`
    case 'rotated_rect':
      return `rect ${R(r.w)}×${R(r.h)} ∠${r.angle.toFixed(1)}° @ ${R(r.cx)},${R(r.cy)}`
    case 'circle':
      return `circle r=${R(r.r)} @ ${R(r.cx)},${R(r.cy)}`
    case 'annulus':
      return `annulus r=${R(r.r_inner)}~${R(r.r_outer)} @ ${R(r.cx)},${R(r.cy)}`
    case 'polygon':
      return `polygon ${r.points.length} pts`
    case 'line':
      return `line ${R(Math.hypot(r.x2 - r.x1, r.y2 - r.y1))}px ∠${(Math.atan2(r.y2 - r.y1, r.x2 - r.x1) / DEG).toFixed(1)}°`
  }
}
