/**
 * 把工具回傳的 overlays 畫到 canvas。
 *
 * 作法：呼叫端已把 ctx 的 transform 設成「影像座標 → 裝置像素」
 * （setTransform(scale*dpr, 0, 0, scale*dpr, tx*dpr, ty*dpr)），所以這裡直接用影像座標畫圖；
 * 線寬、把手、點半徑要固定為螢幕像素，因此除以 scale。
 * 文字與標籤則暫時把 transform 重設為只剩 dpr，在螢幕座標畫，避免文字被縮放糊掉。
 *
 * 效能：points / contours / polyline 可能有數千個元素，各自累積成一個 Path2D 後一次 stroke。
 */
import type { Overlay } from '@/lib/types'
import { DEG } from './geometry'

export const OVERLAY_DEFAULT_COLOR = '#22c55e'

export interface DrawEnv {
  /** 影像 px → 螢幕 CSS px 的比例 */
  scale: number
  dpr: number
  tx: number
  ty: number
}

function hexToRgba(hex: string, alpha: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return hex
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`
}

/** 以影像座標系設定 transform */
export function applyImageTransform(ctx: CanvasRenderingContext2D, env: DrawEnv) {
  const k = env.scale * env.dpr
  ctx.setTransform(k, 0, 0, k, env.tx * env.dpr, env.ty * env.dpr)
}

/** 在螢幕座標（CSS px）畫帶底的標籤文字 */
export function drawLabel(
  ctx: CanvasRenderingContext2D,
  env: DrawEnv,
  sx: number,
  sy: number,
  text: string,
  color: string,
  opts: { above?: boolean; font?: string } = {},
) {
  ctx.save()
  ctx.setTransform(env.dpr, 0, 0, env.dpr, 0, 0)
  ctx.font = opts.font ?? '11px ui-monospace, Menlo, monospace'
  ctx.textBaseline = 'top'
  const padX = 4
  const padY = 2
  const w = ctx.measureText(text).width + padX * 2
  const h = 15
  const x = sx
  const y = opts.above === false ? sy : sy - h
  ctx.fillStyle = 'rgba(0,0,0,0.6)'
  ctx.fillRect(x, y, w, h)
  ctx.fillStyle = color
  ctx.fillText(text, x + padX, y + padY)
  ctx.restore()
}

function overlayAnchor(o: Overlay): [number, number] | null {
  switch (o.kind) {
    case 'rect':
      if (o.angle) {
        // 旋轉矩形：取四角最上方者的最小 x/y
        const c = Math.cos(o.angle * DEG)
        const s = Math.sin(o.angle * DEG)
        const cx = o.x + o.w / 2
        const cy = o.y + o.h / 2
        let minX = Infinity
        let minY = Infinity
        for (const [lx, ly] of [
          [-o.w / 2, -o.h / 2],
          [o.w / 2, -o.h / 2],
          [o.w / 2, o.h / 2],
          [-o.w / 2, o.h / 2],
        ]) {
          minX = Math.min(minX, cx + lx * c - ly * s)
          minY = Math.min(minY, cy + lx * s + ly * c)
        }
        return [minX, minY]
      }
      return [o.x, o.y]
    case 'circle':
      return [o.cx - o.r, o.cy - o.r]
    case 'annulus':
      return [o.cx - o.r_outer, o.cy - o.r_outer]
    case 'polygon':
    case 'polyline':
    case 'points': {
      if (o.points.length === 0) return null
      let minX = Infinity
      let minY = Infinity
      for (const [x, y] of o.points) {
        if (x < minX) minX = x
        if (y < minY) minY = y
      }
      return [minX, minY]
    }
    case 'line':
      return [Math.min(o.x1, o.x2), Math.min(o.y1, o.y2)]
    case 'point':
      return [o.x, o.y]
    case 'text':
      return null
    case 'contours': {
      let minX = Infinity
      let minY = Infinity
      for (const c of o.contours)
        for (const [x, y] of c) {
          if (x < minX) minX = x
          if (y < minY) minY = y
        }
      return Number.isFinite(minX) ? [minX, minY] : null
    }
  }
}

/** 畫一組 overlays。呼叫前 ctx 的 transform 不限，函式內自行設定。 */
export function drawOverlays(ctx: CanvasRenderingContext2D, env: DrawEnv, overlays: Overlay[]) {
  if (overlays.length === 0) return
  const { scale } = env
  const px = (n: number) => n / scale // 螢幕像素 → 影像單位
  const labels: { sx: number; sy: number; text: string; color: string }[] = []

  ctx.save()
  applyImageTransform(ctx, env)
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'

  for (const o of overlays) {
    const color = o.color || OVERLAY_DEFAULT_COLOR
    ctx.strokeStyle = color
    ctx.fillStyle = hexToRgba(color, 0.25)
    ctx.lineWidth = px(o.width ?? 1.5)
    ctx.setLineDash(o.dash ? [px(6), px(4)] : [])

    switch (o.kind) {
      case 'rect': {
        const p = new Path2D()
        if (o.angle) {
          ctx.save()
          ctx.translate(o.x + o.w / 2, o.y + o.h / 2)
          ctx.rotate(o.angle * DEG)
          p.rect(-o.w / 2, -o.h / 2, o.w, o.h)
          if (o.fill) ctx.fill(p)
          ctx.stroke(p)
          ctx.restore()
        } else {
          p.rect(o.x, o.y, o.w, o.h)
          if (o.fill) ctx.fill(p)
          ctx.stroke(p)
        }
        break
      }
      case 'circle': {
        const p = new Path2D()
        p.arc(o.cx, o.cy, Math.max(o.r, 0), 0, Math.PI * 2)
        if (o.fill) ctx.fill(p)
        ctx.stroke(p)
        break
      }
      case 'annulus': {
        const p = new Path2D()
        p.arc(o.cx, o.cy, Math.max(o.r_outer, 0), 0, Math.PI * 2)
        p.moveTo(o.cx + o.r_inner, o.cy)
        p.arc(o.cx, o.cy, Math.max(o.r_inner, 0), 0, Math.PI * 2, true)
        if (o.fill) ctx.fill(p, 'evenodd')
        ctx.stroke(p)
        break
      }
      case 'polygon':
      case 'polyline': {
        if (o.points.length < 2) break
        const p = new Path2D()
        p.moveTo(o.points[0][0], o.points[0][1])
        for (let i = 1; i < o.points.length; i++) p.lineTo(o.points[i][0], o.points[i][1])
        if (o.kind === 'polygon') {
          p.closePath()
          if (o.fill) ctx.fill(p)
        }
        ctx.stroke(p)
        break
      }
      case 'line': {
        ctx.beginPath()
        ctx.moveTo(o.x1, o.y1)
        ctx.lineTo(o.x2, o.y2)
        ctx.stroke()
        break
      }
      case 'point': {
        // 十字標記，固定 6px 臂長
        const a = px(6)
        ctx.beginPath()
        ctx.moveTo(o.x - a, o.y)
        ctx.lineTo(o.x + a, o.y)
        ctx.moveTo(o.x, o.y - a)
        ctx.lineTo(o.x, o.y + a)
        ctx.stroke()
        break
      }
      case 'points': {
        // 大量小圓：一個 Path2D 一次 stroke
        const r = px(2.5)
        const p = new Path2D()
        for (const [x, y] of o.points) {
          p.moveTo(x + r, y)
          p.arc(x, y, r, 0, Math.PI * 2)
        }
        if (o.fill) ctx.fill(p)
        ctx.stroke(p)
        break
      }
      case 'contours': {
        const p = new Path2D()
        for (const c of o.contours) {
          if (c.length < 2) continue
          p.moveTo(c[0][0], c[0][1])
          for (let i = 1; i < c.length; i++) p.lineTo(c[i][0], c[i][1])
          p.closePath()
        }
        if (o.fill) ctx.fill(p)
        ctx.stroke(p)
        break
      }
      case 'text': {
        labels.push({
          sx: o.x * scale + env.tx,
          sy: o.y * scale + env.ty,
          text: o.text,
          color,
        })
        break
      }
    }

    if (o.label && o.kind !== 'text') {
      const a = overlayAnchor(o)
      if (a) labels.push({ sx: a[0] * scale + env.tx, sy: a[1] * scale + env.ty, text: o.label, color })
    }
  }
  ctx.restore()

  // 標籤最後畫（在所有圖形之上），螢幕座標
  for (const l of labels) drawLabel(ctx, env, l.sx, l.sy, l.text, l.color)
}
