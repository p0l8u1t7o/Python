/**
 * DL 樣本縮圖（標記工作區的縮圖牆共用）。
 * - 影像只依 sample.id 載一次快取在 ref；shapes／標記變動只重畫 canvas，不重新下載。
 * - shapes 模式把標記輪廓直接畫在縮圖上（快速巡檢哪幾張標壞了）。
 * - classes 模式用 labelText／labelColor 顯示類別色條。
 */
import { memo, useCallback, useEffect, useRef } from 'react'

import { dlSampleUrl } from '@/lib/api'
import { classColor } from '@/lib/colors'
import type { DlSample } from '@/lib/types'

export interface ThumbProps {
  sample: DlSample
  classes: string[]
  selected: boolean
  /** 有自動標記建議（尚未接受） */
  hasSuggestion?: boolean
  /** classes 模式：縮圖上顯示的類別名稱（空 = 未標記） */
  labelText?: string
  onClick: () => void
}

function ThumbImpl({ sample, classes, selected, hasSuggestion = false, labelText, onClick }: ThumbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (selected) buttonRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selected])
  const imgRef = useRef<{ id: string; img: HTMLImageElement | null; failed: boolean }>({ id: '', img: null, failed: false })
  const drawRef = useRef<() => void>(() => {})

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const w = 168
    const h = Math.max(24, Math.round((sample.height / Math.max(1, sample.width)) * w))
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const entry = imgRef.current
    if (entry.failed) {
      ctx.fillStyle = '#e2e8f0'
      ctx.fillRect(0, 0, w, h)
      ctx.fillStyle = '#94a3b8'
      ctx.font = '11px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('!', w / 2, h / 2)
      return
    }
    if (!entry.img) {
      ctx.fillStyle = '#f1f5f9'
      ctx.fillRect(0, 0, w, h)
      return
    }
    ctx.drawImage(entry.img, 0, 0, w, h)
    for (const shape of sample.shapes ?? []) {
      ctx.strokeStyle = classColor(classes, shape.label)
      ctx.lineWidth = 1.5
      ctx.beginPath()
      if (shape.kind === 'bbox') {
        const [[x0, y0], [x1, y1]] = [shape.points[0], shape.points[1] ?? shape.points[0]]
        ctx.strokeRect(x0 * w, y0 * h, (x1 - x0) * w, (y1 - y0) * h)
      } else {
        shape.points.forEach(([x, y], i) => (i ? ctx.lineTo(x * w, y * h) : ctx.moveTo(x * w, y * h)))
        ctx.closePath()
        ctx.stroke()
      }
    }
  }, [sample.shapes, sample.width, sample.height, classes])

  drawRef.current = draw
  useEffect(() => {
    if (imgRef.current.id === sample.id) {
      draw()
      return
    }
    imgRef.current = { id: sample.id, img: null, failed: false }
    draw()
    const img = new Image()
    img.onload = () => {
      if (imgRef.current.id !== sample.id) return
      imgRef.current.img = img
      drawRef.current() // 用最新的 draw（載入期間標記可能已變）
    }
    img.onerror = () => {
      if (imgRef.current.id !== sample.id) return
      imgRef.current.failed = true
      drawRef.current()
    }
    img.src = dlSampleUrl(sample.id, 192)
  }, [sample.id, draw])

  const shapeCount = (sample.shapes ?? []).length
  return (
    <button ref={buttonRef} type="button" onClick={onClick}
      className={`relative w-full overflow-hidden rounded-md border text-left ${selected ? 'border-brand ring-2 ring-brand/40' : 'border-line hover:border-brand/50'}`}>
      <canvas ref={canvasRef} className="block w-full" />
      {labelText !== undefined ? (
        <span className="absolute inset-x-0 bottom-0 truncate px-1.5 py-0.5 text-[11px] font-medium text-white"
          style={{ background: labelText ? classColor(classes, labelText, 0.85) : 'rgb(0 0 0 / 0.45)' }}>
          {labelText || '—'}
          {sample.labeled_by === 'auto' ? ` ~${Math.round(sample.score * 100)}%` : ''}
        </span>
      ) : (
        <span className="absolute left-1 top-1 rounded bg-black/50 px-1 text-[10px] text-white">
          {shapeCount || (hasSuggestion ? '?' : '—')}
          {sample.labeled_by === 'auto' ? ' auto' : ''}
        </span>
      )}
    </button>
  )
}

/** 縮圖牆可能上百顆，而逐點繪製的 hover／draft 每次滑鼠移動都讓工作區重繪——
 *  memo 擋掉無關縮圖的重繪。onClick 刻意不比（每次 render 都是新 closure，但行為只依 sample.id）。 */
export const Thumb = memo(ThumbImpl, (a, b) =>
  a.sample === b.sample && a.classes === b.classes && a.selected === b.selected &&
  a.hasSuggestion === b.hasSuggestion && a.labelText === b.labelText)
