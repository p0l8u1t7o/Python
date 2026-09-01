/**
 * ShapeWorkspace — shapes 模式（分割／偵測）的標記工作區。
 * 左：縮圖牆（直接畫上標記輪廓，快速巡檢）；右：ImageViewer 編輯器。
 * 重用 ImageViewer 的 ROI 編輯（頂點拖曳、雙擊邊線插點、Alt+點刪點、繪製模式）：
 * 選中的形狀當作 roi 編輯，其他形狀畫成 overlays。座標存 0~1 正規化，只在畫布上換算像素。
 * 快捷鍵：V 選取、N 多邊形、B 框、O 自動優化、Delete 刪形狀、Ctrl+Z 還原、Ctrl+S 儲存、
 * ←/→ 上下張、Esc 取消、0~9 指定類別。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, MousePointer, Pentagon, Redo2, Save, Sparkles, Square, Trash2, Undo2 } from 'lucide-react'

import { ImageViewer } from '@/components/viewer/ImageViewer'
import { Button } from '@/components/ui'
import { dlSampleUrl } from '@/lib/api'
import type { DlProject, DlSample, DlShape, DlSuggestion, Overlay, Region } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'
import { buildGradientMap, optimizePolygon, type GradientMap } from './optimize'

const CLASS_COLORS = ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#db2777', '#65a30d']
const color = (classes: string[], label: string) => {
  const i = classes.indexOf(label)
  return i >= 0 ? CLASS_COLORS[i % CLASS_COLORS.length] : '#94a3b8'
}

type Mode = 'select' | 'polygon' | 'bbox'

function isTyping(): boolean {
  const el = document.activeElement
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || (el as HTMLElement).isContentEditable)
}

// ---- 正規化 shapes ↔ 影像像素 Region ----
function shapeToRegion(shape: DlShape, w: number, h: number): Region {
  if (shape.kind === 'bbox') {
    const [[x0, y0], [x1, y1]] = [shape.points[0], shape.points[1] ?? shape.points[0]]
    return { shape: 'rect', x: x0 * w, y: y0 * h, w: (x1 - x0) * w, h: (y1 - y0) * h }
  }
  return { shape: 'polygon', points: shape.points.map(([x, y]) => [x * w, y * h] as [number, number]) }
}

function regionToShape(region: Region, label: string, w: number, h: number): DlShape | null {
  const cl = (v: number) => Math.min(1, Math.max(0, v))
  if (region.shape === 'rect') {
    return { label, kind: 'bbox', points: [[cl(region.x / w), cl(region.y / h)], [cl((region.x + region.w) / w), cl((region.y + region.h) / h)]] }
  }
  if (region.shape === 'polygon') {
    return { label, kind: 'polygon', points: region.points.map(([x, y]) => [cl(x / w), cl(y / h)] as [number, number]) }
  }
  return null
}

function pointInShape(shape: DlShape, nx: number, ny: number): boolean {
  if (shape.kind === 'bbox') {
    const [[x0, y0], [x1, y1]] = [shape.points[0], shape.points[1] ?? shape.points[0]]
    return nx >= x0 && nx <= x1 && ny >= y0 && ny <= y1
  }
  let inside = false
  const pts = shape.points
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i]
    const [xj, yj] = pts[j]
    if (yi > ny !== yj > ny && nx < ((xj - xi) * (ny - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

// ---- 縮圖（把標記輪廓直接畫上去） ----
function Thumb({ sample, classes, selected, hasSuggestion, onClick }: { sample: DlSample; classes: string[]; selected: boolean; hasSuggestion: boolean; onClick: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const img = new Image()
    img.onload = () => {
      const w = 168
      const h = Math.max(24, Math.round((sample.height / Math.max(1, sample.width)) * w))
      canvas.width = w
      canvas.height = h
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.drawImage(img, 0, 0, w, h)
      for (const shape of sample.shapes ?? []) {
        ctx.strokeStyle = color(classes, shape.label)
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
    }
    img.src = dlSampleUrl(sample.id, 192)
  }, [sample.id, sample.shapes, sample.width, sample.height, classes])
  return (
    <button type="button" onClick={onClick}
      className={`relative w-full overflow-hidden rounded-md border text-left ${selected ? 'border-brand ring-2 ring-brand/40' : 'border-line hover:border-brand/50'}`}>
      <canvas ref={canvasRef} className="block w-full" />
      <span className="absolute left-1 top-1 rounded bg-black/50 px-1 text-[10px] text-white">
        {(sample.shapes ?? []).length || (hasSuggestion ? '?' : '—')}
        {sample.labeled_by === 'auto' ? ' auto' : ''}
      </span>
    </button>
  )
}

// ---------------------------------------------------------------------------
export function ShapeWorkspace({ project, samples, suggestions, onSave, onAcceptSuggestion }: {
  project: DlProject
  samples: DlSample[]
  suggestions: Map<string, DlSuggestion>
  onSave: (sampleId: string, shapes: DlShape[]) => Promise<void>
  onAcceptSuggestion: (sampleId: string, shapes: DlShape[]) => Promise<void>
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const classes = project.classes
  const [selectedId, setSelectedId] = useState<string | null>(samples[0]?.id ?? null)
  const sample = samples.find((s) => s.id === selectedId) ?? samples[0] ?? null
  const [shapes, setShapes] = useState<DlShape[]>([])
  const [history, setHistory] = useState<DlShape[][]>([])
  const [dirty, setDirty] = useState(false)
  const [mode, setMode] = useState<Mode>('select')
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [activeClass, setActiveClass] = useState(classes[0] ?? '')
  const [saving, setSaving] = useState(false)
  const gradientRef = useRef<{ id: string; map: GradientMap } | null>(null)

  const loadedIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (!sample || loadedIdRef.current === sample.id) return
    loadedIdRef.current = sample.id
    setShapes((sample.shapes ?? []).map((s) => ({ ...s, points: s.points.map((p) => [...p] as [number, number]) })))
    setHistory([])
    setDirty(false)
    setSelectedIndex(null)
    setMode('select')
  }, [sample])

  const pushHistory = useCallback(() => {
    setHistory((old) => [...old.slice(-40), shapes.map((s) => ({ ...s, points: s.points.map((p) => [...p] as [number, number]) }))])
  }, [shapes])

  function undo() {
    setHistory((old) => {
      if (!old.length) return old
      setShapes(old[old.length - 1])
      setDirty(true)
      setSelectedIndex(null)
      return old.slice(0, -1)
    })
  }

  async function save() {
    if (!sample) return
    setSaving(true)
    try {
      await onSave(sample.id, shapes)
      setDirty(false)
      toast.success(t('common.saved'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  function switchSample(id: string) {
    if (dirty && !window.confirm(t('dl.unsavedConfirm'))) return
    loadedIdRef.current = null
    setSelectedId(id)
  }

  function step(delta: number) {
    if (!sample) return
    const idx = samples.findIndex((s) => s.id === sample.id)
    const next = samples[idx + delta]
    if (next) switchSample(next.id)
  }

  function removeSelected() {
    if (selectedIndex === null) return
    pushHistory()
    setShapes((old) => old.filter((_, i) => i !== selectedIndex))
    setSelectedIndex(null)
    setDirty(true)
  }

  function assignClass(label: string) {
    setActiveClass(label)
    if (selectedIndex !== null) {
      pushHistory()
      setShapes((old) => old.map((s, i) => (i === selectedIndex ? { ...s, label } : s)))
      setDirty(true)
    }
  }

  async function optimizeSelected() {
    if (!sample || selectedIndex === null) return
    const shape = shapes[selectedIndex]
    if (!shape || shape.kind !== 'polygon') {
      toast.warning(t('dl.optimizePolygonOnly'))
      return
    }
    try {
      let entry = gradientRef.current
      if (!entry || entry.id !== sample.id) {
        const img = new Image()
        await new Promise<void>((resolve, reject) => {
          img.onload = () => resolve()
          img.onerror = () => reject(new Error('image load failed'))
          img.src = dlSampleUrl(sample.id, 1280)
        })
        entry = { id: sample.id, map: buildGradientMap(img, sample.width, sample.height) }
        gradientRef.current = entry
      }
      pushHistory()
      const px = shape.points.map(([x, y]) => [x * sample.width, y * sample.height] as [number, number])
      const optimized = optimizePolygon(px, entry.map)
      setShapes((old) => old.map((s, i) => (i === selectedIndex ? { ...s, points: optimized.map(([x, y]) => [Math.min(1, Math.max(0, x / sample.width)), Math.min(1, Math.max(0, y / sample.height))] as [number, number]) } : s)))
      setDirty(true)
      toast.push(t('dl.optimizedNotSaved'), 'info')
    } catch {
      toast.error(t('dl.optimizeFailed'))
    }
  }

  // 鍵盤快捷鍵
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (isTyping()) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        void save()
        return
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        undo()
        return
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const key = e.key.toLowerCase()
      if (key === 'v') setMode('select')
      else if (key === 'n') setMode('polygon')
      else if (key === 'b') setMode('bbox')
      else if (key === 'o') void optimizeSelected()
      else if (key === 'delete') removeSelected()
      else if (key === 'escape') {
        setMode('select')
        setSelectedIndex(null)
      } else if (key === 'arrowleft' || key === 'a') step(-1)
      else if (key === 'arrowright' || key === 'd') step(1)
      else if (/^[0-9]$/.test(key)) {
        const label = classes[Number(key)]
        if (label) assignClass(label)
      } else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // ---- ImageViewer 接線 ----
  const suggestion = sample ? suggestions.get(sample.id) : undefined
  const overlays = useMemo<Overlay[]>(() => {
    if (!sample) return []
    const w = sample.width
    const h = sample.height
    const out: Overlay[] = []
    shapes.forEach((shape, i) => {
      if (i === selectedIndex) return
      const c = color(classes, shape.label)
      if (shape.kind === 'bbox') {
        const [[x0, y0], [x1, y1]] = [shape.points[0], shape.points[1] ?? shape.points[0]]
        out.push({ kind: 'rect', x: x0 * w, y: y0 * h, w: (x1 - x0) * w, h: (y1 - y0) * h, color: c, label: shape.label, width: 2 } as Overlay)
      } else {
        out.push({ kind: 'polygon', points: shape.points.map(([x, y]) => [x * w, y * h]), color: c, label: shape.label, width: 2 } as Overlay)
      }
    })
    for (const shape of suggestion?.shapes ?? []) {
      const c = color(classes, shape.label)
      out.push({ kind: 'polygon', points: shape.points.map(([x, y]) => [x * w, y * h]), color: `${c}99`, label: `${shape.label}?`, width: 1 } as Overlay)
    }
    return out
  }, [sample, shapes, selectedIndex, suggestion, classes])

  const editingRegion = useMemo<Region | null>(() => {
    if (!sample || selectedIndex === null) return null
    const shape = shapes[selectedIndex]
    return shape ? shapeToRegion(shape, sample.width, sample.height) : null
  }, [sample, shapes, selectedIndex])

  const gestureRef = useRef(false)
  const onRoiChange = useCallback((region: Region) => {
    if (!sample) return
    if (mode === 'select' && selectedIndex !== null) {
      if (!gestureRef.current) {
        gestureRef.current = true
        pushHistory()
        window.setTimeout(() => (gestureRef.current = false), 800)
      }
      const shape = regionToShape(region, shapes[selectedIndex]?.label ?? activeClass, sample.width, sample.height)
      if (shape) {
        setShapes((old) => old.map((s, i) => (i === selectedIndex ? { ...shape, kind: s.kind } : s)))
        setDirty(true)
      }
      return
    }
    // 繪製模式：第一筆拖曳建立新形狀
    const label = activeClass || classes[0] || ''
    const shape = regionToShape(region, label, sample.width, sample.height)
    if (!shape) return
    pushHistory()
    setShapes((old) => {
      setSelectedIndex(old.length)
      return [...old, { ...shape, kind: mode === 'bbox' ? 'bbox' : 'polygon' }]
    })
    setDirty(true)
    setMode('select')
  }, [sample, mode, selectedIndex, shapes, activeClass, classes, pushHistory])

  const onPick = useCallback((x: number, y: number) => {
    if (!sample || mode !== 'select') return
    const nx = x / sample.width
    const ny = y / sample.height
    for (let i = shapes.length - 1; i >= 0; i--) {
      if (pointInShape(shapes[i], nx, ny)) {
        setSelectedIndex(i)
        return
      }
    }
    setSelectedIndex(null)
  }, [sample, mode, shapes])

  if (!sample) return null
  const counts = shapes.length
  return (
    <div className="grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)]">
      {/* 縮圖牆 */}
      <div className="max-h-[70vh] space-y-1.5 overflow-y-auto pr-1" data-testid="dl-thumb-wall">
        {samples.map((s) => (
          <Thumb key={s.id} sample={s.id === sample.id ? { ...s, shapes } : s} classes={classes} selected={s.id === sample.id} hasSuggestion={suggestions.has(s.id)} onClick={() => switchSample(s.id)} />
        ))}
      </div>

      <div className="min-w-0 space-y-2">
        {/* 工具列 */}
        <div className="flex flex-wrap items-center gap-1.5">
          <Button size="sm" active={mode === 'select'} onClick={() => setMode('select')} title="V"><MousePointer size={14} /> {t('dl.modeSelect')}</Button>
          <Button size="sm" active={mode === 'polygon'} onClick={() => setMode('polygon')} title="N"><Pentagon size={14} /> {t('dl.modePolygon')}</Button>
          <Button size="sm" active={mode === 'bbox'} onClick={() => setMode('bbox')} title="B"><Square size={14} /> {t('dl.modeBbox')}</Button>
          <span className="mx-1 h-5 w-px bg-line" />
          {classes.map((c, i) => (
            <button key={c} type="button" onClick={() => assignClass(c)} title={String(i)}
              className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${activeClass === c ? 'border-transparent text-white' : 'border-line hover:bg-surface-muted'}`}
              style={activeClass === c ? { background: color(classes, c) } : undefined}>
              <span className="size-2 rounded-full" style={{ background: activeClass === c ? '#fff' : color(classes, c) }} />{c}
            </button>
          ))}
          <span className="ml-auto" />
          <Button size="sm" onClick={() => void optimizeSelected()} disabled={selectedIndex === null} title="O"><Sparkles size={14} /> {t('dl.optimize')}</Button>
          <Button size="sm" onClick={removeSelected} disabled={selectedIndex === null} title="Delete"><Trash2 size={14} /></Button>
          <Button size="sm" onClick={undo} disabled={!history.length} title="Ctrl+Z"><Undo2 size={14} /></Button>
          {suggestion?.shapes?.length ? (
            <Button size="sm" variant="primary" onClick={() => void onAcceptSuggestion(sample.id, suggestion.shapes!).then(() => loadedIdRef.current = null)}>
              <Check size={14} /> {t('dl.acceptSuggestion', { count: suggestion.shapes.length })}
            </Button>
          ) : null}
          <Button size="sm" variant="primary" loading={saving} onClick={() => void save()} title="Ctrl+S" data-testid="dl-save-shapes">
            <Save size={14} /> {t('common.save')}{dirty ? ' *' : ''}
          </Button>
        </div>
        <p className="text-xs text-subtle">{t('dl.shapeHint', { count: counts })}</p>
        <div className="h-[62vh] min-h-[380px]">
          <ImageViewer
            src={dlSampleUrl(sample.id, 1600)}
            imageWidth={sample.width}
            imageHeight={sample.height}
            overlays={overlays}
            roi={mode === 'select' ? editingRegion : null}
            roiShapes={mode === 'polygon' ? ['polygon'] : mode === 'bbox' ? ['rect'] : undefined}
            onRoiChange={mode === 'select' && selectedIndex === null ? undefined : onRoiChange}
            onPick={onPick}
            badge={dirty ? { text: t('dl.unsaved'), tone: 'neutral' } : null}
          />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          <Button size="sm" onClick={() => step(-1)}>←</Button>
          <Button size="sm" onClick={() => step(1)}>→</Button>
          <span>{samples.findIndex((s) => s.id === sample.id) + 1} / {samples.length}</span>
          <Redo2 size={12} className="ml-2 opacity-0" aria-hidden />
        </div>
      </div>
    </div>
  )
}
