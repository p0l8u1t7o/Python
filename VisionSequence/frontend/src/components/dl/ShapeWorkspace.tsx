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
import { Check, ChevronLeft, ChevronRight, Keyboard, MousePointer, Pentagon, Save, Sparkles, Square, Trash2, Undo2 } from 'lucide-react'

import { ImageViewer } from '@/components/viewer/ImageViewer'
import { Button, IconButton, Modal } from '@/components/ui'
import { dlSampleUrl } from '@/lib/api'
import type { DlProject, DlSample, DlShape, DlSuggestion, Overlay, Region } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'
import { buildGradientMap, optimizePolygon, type GradientMap } from './optimize'

import { classColor as color } from '@/lib/colors'

type Mode = 'select' | 'polygon' | 'bbox'

function isTyping(): boolean {
  const el = document.activeElement
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || (el as HTMLElement).isContentEditable)
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
  const buttonRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (selected) buttonRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selected])
  // 影像只依 sample.id 載一次快取在 ref；shapes 變動（拖曳標記中每 frame）只重畫，不重新下載。
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
      drawRef.current() // 用最新的 draw（載入期間 shapes 可能已變）
    }
    img.onerror = () => {
      if (imgRef.current.id !== sample.id) return
      imgRef.current.failed = true
      drawRef.current()
    }
    img.src = dlSampleUrl(sample.id, 192)
  }, [sample.id, draw])
  return (
    <button ref={buttonRef} type="button" onClick={onClick}
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
export function ShapeWorkspace({ project, samples, suggestions, onSave, onAcceptSuggestion, onEditClasses, hotkeysDisabled = false }: {
  project: DlProject
  samples: DlSample[]
  suggestions: Map<string, DlSuggestion>
  onSave: (sampleId: string, shapes: DlShape[]) => Promise<void>
  onAcceptSuggestion: (sampleId: string, shapes: DlShape[]) => Promise<void>
  onEditClasses?: () => void
  /** 上層 Modal 開啟時停用快捷鍵，避免 Delete／←→ 打到背後的工作區 */
  hotkeysDisabled?: boolean
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
  const [showKeys, setShowKeys] = useState(false)
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
  // classes prop 變動（編輯類別後）：activeClass 重設、本地 shapes 過濾掉已刪類別（與後端
  // patch_project 的清理一致，否則殘留形狀會讓之後每次儲存被驗證拒絕）、清空時退回選取模式。
  useEffect(() => {
    if (activeClass && !classes.includes(activeClass)) setActiveClass(classes[0] ?? '')
    else if (!activeClass && classes.length) setActiveClass(classes[0])
    if (!classes.length) setMode('select')
    setShapes((old) => {
      if (old.every((s) => classes.includes(s.label))) return old
      setSelectedIndex(null)
      setHistory([])
      return old.filter((s) => classes.includes(s.label))
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(classes)])

  // 數字鍵指定類別：掛 capture 階段，先於 ImageViewer 容器的 keydown（它的 '1' 是 1:1 縮放，
  // 會 preventDefault 把類別鍵吃掉）；1:1 仍可用工具列按鈕。
  useEffect(() => {
    function onDigit(e: KeyboardEvent) {
      if (hotkeysDisabled || showKeys || isTyping()) return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (!/^[0-9]$/.test(e.key)) return
      const label = classes[Number(e.key)]
      if (!label) return
      assignClass(label)
      e.preventDefault()
      e.stopPropagation()
    }
    window.addEventListener('keydown', onDigit, true)
    return () => window.removeEventListener('keydown', onDigit, true)
  })

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (hotkeysDisabled || showKeys || isTyping()) return
      // ImageViewer 容器聚焦時自己處理 f/+/-/拖曳中Esc/頂點Delete（有 preventDefault），這裡讓路避免雙重觸發
      if (e.defaultPrevented) return
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
      else if (key === 'n' && classes.length) setMode('polygon')
      else if (key === 'b' && classes.length) setMode('bbox')
      else if (key === 'o') void optimizeSelected()
      else if (key === 'delete') removeSelected()
      else if (key === 'escape') {
        setMode('select')
        setSelectedIndex(null)
      } else if (key === 'arrowleft' || key === 'a') step(-1)
      else if (key === 'arrowright' || key === 'd') step(1)
      else return
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
      const c = color(classes, shape.label, 0.6)
      if (shape.kind === 'bbox') {
        const [[x0, y0], [x1, y1]] = [shape.points[0], shape.points[1] ?? shape.points[0]]
        out.push({ kind: 'rect', x: x0 * w, y: y0 * h, w: (x1 - x0) * w, h: (y1 - y0) * h, color: c, label: `${shape.label}?`, width: 1 } as Overlay)
      } else {
        out.push({ kind: 'polygon', points: shape.points.map(([x, y]) => [x * w, y * h]), color: c, label: `${shape.label}?`, width: 1 } as Overlay)
      }
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
  const index = samples.findIndex((s) => s.id === sample.id)
  const tools: { key: string; icon: React.ReactNode; label: string; kbd: string; active?: boolean; disabled?: boolean; onClick: () => void }[] = [
    { key: 'select', icon: <MousePointer size={22} />, label: t('dl.modeSelect'), kbd: 'V', active: mode === 'select', onClick: () => setMode('select') },
    { key: 'polygon', icon: <Pentagon size={22} />, label: t('dl.modePolygon'), kbd: 'N', active: mode === 'polygon', disabled: !classes.length, onClick: () => setMode('polygon') },
    { key: 'bbox', icon: <Square size={22} />, label: t('dl.modeBbox'), kbd: 'B', active: mode === 'bbox', disabled: !classes.length, onClick: () => setMode('bbox') },
    { key: 'sep1', icon: null, label: '', kbd: '', onClick: () => {} },
    { key: 'optimize', icon: <Sparkles size={22} />, label: t('dl.optimize'), kbd: 'O', disabled: selectedIndex === null, onClick: () => void optimizeSelected() },
    { key: 'delete', icon: <Trash2 size={22} />, label: t('dl.deleteShape'), kbd: 'Del', disabled: selectedIndex === null, onClick: removeSelected },
    { key: 'undo', icon: <Undo2 size={22} />, label: t('dl.undo'), kbd: '^Z', disabled: !history.length, onClick: undo },
  ]
  return (
    <div className="grid gap-3 lg:h-[calc(100vh-320px)] lg:min-h-[460px] lg:grid-cols-[180px_minmax(0,1fr)]">
      {/* 縮圖牆（與畫布同高，自行捲動） */}
      <div className="max-h-[50vh] space-y-1.5 overflow-y-auto pr-1 lg:max-h-none lg:h-full" data-testid="dl-thumb-wall">
        {samples.map((s) => (
          <Thumb key={s.id} sample={s.id === sample.id ? { ...s, shapes } : s} classes={classes} selected={s.id === sample.id} hasSuggestion={suggestions.has(s.id)} onClick={() => switchSample(s.id)} />
        ))}
      </div>

      <div className="flex min-h-0 min-w-0 flex-col gap-2">
        {/* 狀態列：導覽＋樣本資訊＋建議／儲存（固定位置不跳動） */}
        <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-2 gap-y-1">
          <IconButton label={t('dl.prevSample')} size="md" variant="secondary" onClick={() => step(-1)}><ChevronLeft size={16} /></IconButton>
          <IconButton label={t('dl.nextSample')} size="md" variant="secondary" onClick={() => step(1)}><ChevronRight size={16} /></IconButton>
          <span className="tnum text-xs text-muted">{index + 1} / {samples.length}</span>
          <span className="text-xs text-subtle">{sample.width}×{sample.height} · {shapes.length} {t('dl.shapesUnit')}</span>
          {dirty ? <span className="flex items-center gap-1 text-xs font-medium text-warning"><span className="size-1.5 rounded-full bg-warning" />{t('dl.unsaved')}</span> : null}
          <span className="ml-auto" />
          <IconButton label={t('dl.shortcuts')} size="md" onClick={() => setShowKeys(true)}><Keyboard size={16} /></IconButton>
          {suggestion?.shapes?.length ? (
            <Button size="md" variant="primary" onClick={() => void onAcceptSuggestion(sample.id, suggestion.shapes!).then(() => loadedIdRef.current = null)}>
              <Check size={15} /> {t('dl.acceptSuggestion', { count: suggestion.shapes.length })}
            </Button>
          ) : null}
          <Button size="md" variant="primary" loading={saving} onClick={() => void save()} title="Ctrl+S" data-testid="dl-save-shapes">
            <Save size={15} /> {t('common.save')}
          </Button>
        </div>

        {/* 類別列：大顆可點（數字鍵對應），畫新形狀用目前類別 */}
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {!classes.length ? (
            <button type="button" className="flex h-10 items-center gap-2 rounded-md border border-dashed border-warning px-3 text-sm text-warning hover:bg-warning-soft" onClick={onEditClasses}>
              {t('dl.classesFirstShort')}
            </button>
          ) : null}
          {classes.map((c, i) => {
            const active = activeClass === c
            return (
              <button key={c} type="button" onClick={() => assignClass(c)} title={t('dl.classButtonTitle', { n: i })}
                className={`flex h-11 items-center gap-2 rounded-md border px-3 text-sm font-medium transition-colors ${active ? 'border-transparent text-white shadow-sm' : 'border-line text-content hover:bg-surface-muted'}`}
                style={active ? { background: color(classes, c) } : undefined} data-testid={`dl-shape-class-${c}`}>
                <span className="size-3 shrink-0 rounded-full border border-black/10" style={{ background: active ? '#fff' : color(classes, c) }} />
                <span className="min-w-0 max-w-32 truncate">{c}</span>
                {i <= 9 ? <kbd className={`rounded border px-1 text-[10px] leading-4 ${active ? 'border-white/40 text-white/85' : 'border-line text-subtle'}`}>{i}</kbd> : null}
              </button>
            )
          })}
        </div>

        {/* 工具欄（大圖示）＋畫布 */}
        <div className="flex h-[55vh] min-h-[380px] gap-2 lg:h-auto lg:min-h-0 lg:flex-1">
          <div className="flex w-14 shrink-0 flex-col items-center gap-1 self-stretch overflow-y-auto rounded-md border border-line bg-surface p-1.5" data-testid="dl-tool-rail">
            {tools.map((tool) =>
              tool.icon === null ? (
                <span key={tool.key} className="my-1 h-px w-8 shrink-0 bg-line" />
              ) : (
                <button key={tool.key} type="button" onClick={tool.onClick} disabled={tool.disabled}
                  title={`${tool.label}（${tool.kbd}）`} aria-label={tool.label} aria-pressed={tool.active}
                  className={`flex size-11 shrink-0 flex-col items-center justify-center gap-0.5 rounded-md transition-colors disabled:cursor-not-allowed disabled:opacity-40
                    ${tool.active ? 'bg-brand-soft text-brand ring-1 ring-brand' : 'text-muted hover:bg-surface-muted hover:text-content'}`}
                  data-testid={`dl-tool-${tool.key}`}>
                  {tool.icon}
                  <kbd className="text-[9px] leading-none text-subtle">{tool.kbd}</kbd>
                </button>
              ),
            )}
          </div>
          <div className="min-h-0 min-w-0 flex-1">
            <ImageViewer
              className="h-full w-full"
              src={dlSampleUrl(sample.id, 1600)}
              imageWidth={sample.width}
              imageHeight={sample.height}
              overlays={overlays}
              roi={mode === 'select' ? editingRegion : null}
              roiShapes={
                // 編輯中：把手工具列只開放該形狀自己的種類，避免 bbox↔polygon／circle 等互轉毀掉標記資料
                mode === 'polygon' ? ['polygon']
                  : mode === 'bbox' ? ['rect']
                    : selectedIndex !== null ? (shapes[selectedIndex]?.kind === 'bbox' ? ['rect'] : ['polygon'])
                      : undefined
              }
              onRoiChange={mode === 'select' && selectedIndex === null ? undefined : onRoiChange}
              onPick={onPick}
              badge={dirty ? { text: t('dl.unsaved'), tone: 'neutral' } : null}
            />
          </div>
        </div>
      </div>

      <Modal open={showKeys} onClose={() => setShowKeys(false)} title={t('dl.shortcuts')} size="sm">
        <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          {([
            ['V / N / B', t('dl.keyModes')],
            ['0～9', t('dl.keyClasses')],
            ['O', t('dl.keyOptimize')],
            ['Delete', t('dl.keyDelete')],
            [t('dl.kbdAltVertex'), t('dl.keyDeleteVertex')],
            [t('dl.kbdDblEdge'), t('dl.keyInsertVertex')],
            ['Ctrl+Z / Ctrl+S', t('dl.keyUndoSave')],
            ['← → / A D', t('dl.keyNav')],
            [t('dl.kbdView'), t('dl.keyView')],
          ] as [string, string][]).map(([k, desc]) => (
            <span key={k} className="contents">
              <kbd className="rounded border border-line bg-surface-muted px-1.5 py-0.5 text-center text-xs">{k}</kbd>
              <span className="text-muted">{desc}</span>
            </span>
          ))}
        </div>
      </Modal>
    </div>
  )
}
