/**
 * ImageViewer 開發示範頁（不掛路由，需要時在 App 內臨時 render <ImageViewerDemo />）。
 * 用 canvas 產生一張測試影像（含漸層、格線與幾個圖形）當 src，示範 overlays、ROI 編輯與繪製模式。
 */
import { useMemo, useState } from 'react'
import type { Overlay, Region, RoiShape } from '@/lib/types'
import { ImageViewer } from './ImageViewer'

const IMG_W = 1600
const IMG_H = 1200

function makeTestImage(): string {
  const c = document.createElement('canvas')
  // 故意用一半解析度當「縮圖」，驗證座標系縮放
  c.width = IMG_W / 2
  c.height = IMG_H / 2
  const ctx = c.getContext('2d')!
  const g = ctx.createLinearGradient(0, 0, c.width, c.height)
  g.addColorStop(0, '#3b3b3b')
  g.addColorStop(1, '#a0a0a0')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, c.width, c.height)
  ctx.strokeStyle = 'rgba(255,255,255,0.15)'
  for (let x = 0; x < c.width; x += 50) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, c.height)
    ctx.stroke()
  }
  for (let y = 0; y < c.height; y += 50) {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(c.width, y)
    ctx.stroke()
  }
  ctx.fillStyle = '#222'
  ctx.beginPath()
  ctx.arc(300, 250, 80, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = '#eee'
  ctx.fillRect(500, 150, 160, 100)
  return c.toDataURL('image/png')
}

function makeOverlays(): Overlay[] {
  const pts: [number, number][] = []
  for (let i = 0; i < 2000; i++) pts.push([Math.random() * IMG_W, Math.random() * IMG_H])
  const contour: [number, number][] = []
  for (let a = 0; a < 360; a += 5) {
    const r = 160 + Math.sin((a * Math.PI) / 30) * 10
    contour.push([600 + Math.cos((a * Math.PI) / 180) * r, 500 + Math.sin((a * Math.PI) / 180) * r])
  }
  return [
    { kind: 'circle', cx: 600, cy: 500, r: 160, label: '孔 r=160', width: 2 },
    { kind: 'rect', x: 1000, y: 300, w: 320, h: 200, angle: 20, label: '定位 ∠20°', color: '#f59e0b', dash: true },
    { kind: 'rect', x: 100, y: 800, w: 300, h: 200, fill: true, color: '#ef4444', label: 'NG 區' },
    { kind: 'line', x1: 100, y1: 100, x2: 700, y2: 120, color: '#38bdf8' },
    { kind: 'point', x: 800, y: 900, label: '中心' },
    { kind: 'points', points: pts, color: '#a855f7' },
    { kind: 'contours', contours: [contour], color: '#22c55e' },
    { kind: 'polyline', points: [[1200, 900], [1300, 1000], [1400, 950], [1500, 1100]], color: '#f472b6' },
    { kind: 'annulus', cx: 1300, cy: 700, r_inner: 40, r_outer: 90, label: 'annulus' },
    { kind: 'text', x: 50, y: 40, text: 'Hello VisionSequence', color: '#fde68a' },
  ]
}

const SHAPES: RoiShape[] = ['rect', 'rotated_rect', 'circle', 'annulus', 'polygon', 'line']

export function ImageViewerDemo() {
  const src = useMemo(makeTestImage, [])
  const overlays = useMemo(makeOverlays, [])
  const [roi, setRoi] = useState<Region | null>({ shape: 'rect', x: 400, y: 300, w: 300, h: 200 })
  const [picked, setPicked] = useState<[number, number] | null>(null)
  const [mode, setMode] = useState<'edit' | 'pick'>('edit')

  return (
    <div className="flex h-screen flex-col gap-2 bg-canvas p-3">
      <div className="flex items-center gap-2 text-sm">
        <button type="button" className="btn-secondary" onClick={() => setMode('edit')}>
          ROI 模式
        </button>
        <button type="button" className="btn-secondary" onClick={() => setMode('pick')}>
          點選模式
        </button>
        <button type="button" className="btn-ghost" onClick={() => setRoi(null)}>
          清除 ROI（進入繪製模式）
        </button>
        <span className="font-mono text-xs text-muted">
          roi: {roi ? JSON.stringify(roi) : 'null'} {picked && `pick: ${picked.join(',')}`}
        </span>
      </div>
      <ImageViewer
        className="min-h-0 flex-1 rounded-lg border border-line"
        src={src}
        imageWidth={IMG_W}
        imageHeight={IMG_H}
        overlays={overlays}
        roi={mode === 'edit' ? roi : null}
        roiShapes={mode === 'edit' ? SHAPES : undefined}
        onRoiChange={mode === 'edit' ? setRoi : undefined}
        onPick={mode === 'pick' ? (x, y) => setPicked([x, y]) : undefined}
        badge={{ text: 'OK', tone: 'ok' }}
      />
    </div>
  )
}

export default ImageViewerDemo
