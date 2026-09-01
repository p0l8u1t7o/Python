/**
 * ImageViewer — 機器視覺平台的影像檢視器（類 VisionMaster / Cognex 影像視窗）。
 *
 * 用法（README）：
 *   <ImageViewer src={imageUrl(ref, 1024)} imageWidth={4096} imageHeight={3000}
 *                overlays={report.nodes[id].overlays}
 *                roi={region} roiShapes={['rect','circle']} onRoiChange={setRegion}
 *                badge={{ text: 'OK', tone: 'ok' }} />
 *
 *   - src 可以是縮圖：所有 overlay / ROI 座標一律以 imageWidth × imageHeight 為準，
 *     繪圖時把載入影像拉伸到該尺寸。
 *   - roi 非 null → 編輯模式；roi 為 null 但 roiShapes 有值且有 onRoiChange → 繪製模式（拖曳畫出第一個 ROI）。
 *   - 非 ROI 模式下點擊影像回 onPick(x, y)（影像像素座標）。
 *   - 互動：滾輪縮放（以游標為中心）、左鍵／中鍵拖曳平移、雙擊 fit、F / 1 / + / − 快捷鍵。
 *   - 同步視角（工具頁「前／後」並排）：傳 `viewport` + `onViewportChange`；檢視器每次改視角都回呼，
 *     收到不同的 `viewport` prop 就套用（不回呼，避免兩個檢視器互相彈跳）。兩個 prop 都不給時行為不變。
 *
 * 設計重點：
 *   1. 兩層 canvas：影像層（影像＋邊框＋像素格）、overlay 層（overlays＋ROI＋把手）。
 *      兩層皆依 devicePixelRatio 放大 backing store，線條才不會糊。
 *   2. 視角、拖曳狀態、hover 全放在 ref，透過 requestAnimationFrame 合併重繪，
 *      拖曳期間完全不觸發 React state 更新；工具列上的比例 % 與座標由 DOM ref 直接寫。
 *   3. 座標轉換見 useViewport.ts：screen = image * scale + t。
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type JSX } from 'react'
import { useTranslation } from 'react-i18next'
import type { Overlay, Region, RoiShape } from '@/lib/types'
import { drawOverlays, type DrawEnv } from './drawOverlays'
import {
  clampRegion,
  convertRegion,
  regionFromDrag,
  regionsEqual,
  roundRegion,
} from './geometry'
import {
  applyHandleDrag,
  applyMove,
  drawRoi,
  getHandles,
  hitBody,
  hitHandle,
  hitPolygonEdge,
  type Handle,
} from './roiEditor'
import { Toolbar } from './Toolbar'
import {
  fitViewport,
  recenterOnResize,
  scaleCenteredOnImage,
  toImage,
  useViewport,
  zoomAt,
  type Viewport,
} from './useViewport'

export interface ImageViewerProps {
  src: string | null
  imageWidth: number
  imageHeight: number
  overlays?: Overlay[]
  roi?: Region | null
  roiShapes?: RoiShape[]
  onRoiChange?: (region: Region) => void
  toolbar?: boolean
  className?: string
  badge?: { text: string; tone: 'ok' | 'ng' | 'neutral' } | null
  onPick?: (x: number, y: number) => void
  /** 雙擊影像（影像像素座標）；有傳時雙擊不再觸發 fit（逐點繪製用雙擊收尾）。 */
  onDoublePick?: (x: number, y: number) => void
  /** 游標在影像上的位置（影像像素座標；離開畫布時為 null）。以 rAF 節流，只在有傳時才回報。 */
  onHover?: (point: [number, number] | null) => void
  /** 受控視角（可選）：與另一個檢視器同步用 */
  viewport?: Viewport | null
  onViewportChange?: (vp: Viewport) => void
}

const ALL_SHAPES: RoiShape[] = ['rect', 'rotated_rect', 'circle', 'annulus', 'polygon', 'line']
const GRID_MIN_SCALE = 8

type Drag =
  | { kind: 'pan'; sx0: number; sy0: number; vp0: Viewport; moved: boolean; pick: boolean }
  | { kind: 'handle'; handle: Handle; region0: Region }
  | { kind: 'move'; region0: Region; ix0: number; iy0: number }
  | { kind: 'draw'; shape: RoiShape; ix0: number; iy0: number }

interface Sampler {
  ctx: CanvasRenderingContext2D
  w: number
  h: number
  approx: boolean
}

export function ImageViewer(props: ImageViewerProps): JSX.Element {
  const { t } = useTranslation()
  const {
    src,
    imageWidth,
    imageHeight,
    overlays,
    roi,
    roiShapes,
    onRoiChange,
    toolbar = true,
    className,
    badge,
    onPick,
    onDoublePick,
    onHover,
    viewport,
    onViewportChange,
  } = props
  const onViewportChangeRef = useRef(onViewportChange)
  onViewportChangeRef.current = onViewportChange

  const containerRef = useRef<HTMLDivElement>(null)
  const imgCanvasRef = useRef<HTMLCanvasElement>(null)
  const ovCanvasRef = useRef<HTMLCanvasElement>(null)
  const scaleRef = useRef<HTMLSpanElement>(null)
  const pixelRef = useRef<HTMLSpanElement>(null)

  const vpRef = useViewport()
  const imgRef = useRef<HTMLImageElement | null>(null)
  const samplerRef = useRef<Sampler | null>(null)
  const sizeRef = useRef({ w: 0, h: 0, dpr: 1 })
  const fittedRef = useRef(false)
  const dragRef = useRef<Drag | null>(null)
  const hoverRef = useRef<Handle | null>(null)
  /** 拖曳中的 ROI（未取整），優先於 props.roi 繪製，避免等待父層 state 回流 */
  const liveRoiRef = useRef<Region | null>(null)
  const pendingRoiRef = useRef<Region | null>(null)
  const selectedVertexRef = useRef<number | null>(null)
  const rafRef = useRef<{ id: number; image: boolean; overlay: boolean }>({ id: 0, image: false, overlay: false })
  /** onHover 的 rAF 節流（高更新率滑鼠一秒可觸發上千次 pointermove） */
  const hoverEmitRef = useRef<{ id: number; point: [number, number] | null }>({ id: 0, point: null })

  const [grid, setGrid] = useState(true)
  const [showOverlays, setShowOverlays] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [drawShape, setDrawShape] = useState<RoiShape | null>(null)

  const allowedShapes = roiShapes ?? ALL_SHAPES
  const editMode = !!roi && !!onRoiChange
  const drawMode = !roi && !!onRoiChange && !!roiShapes && roiShapes.length > 0
  const roiMode = editMode || drawMode
  const activeDrawShape: RoiShape =
    drawShape && allowedShapes.includes(drawShape)
      ? drawShape
      : allowedShapes.includes('rect')
        ? 'rect'
        : allowedShapes[0]

  // 讓原生事件處理器讀到最新 props / state，而不用每次都重新綁定監聽
  const latest = useRef({
    overlays,
    roi,
    onRoiChange,
    onPick,
    onDoublePick,
    onHover,
    editMode,
    drawMode,
    activeDrawShape,
    showOverlays,
    grid,
    imageWidth,
    imageHeight,
  })
  latest.current = {
    overlays,
    roi,
    onRoiChange,
    onPick,
    onDoublePick,
    onHover,
    editMode,
    drawMode,
    activeDrawShape,
    showOverlays,
    grid,
    imageWidth,
    imageHeight,
  }

  /** 有效影像座標系尺寸：props 優先，否則用載入影像本身 */
  const dims = useCallback((): [number, number] => {
    const { imageWidth: w, imageHeight: h } = latest.current
    const img = imgRef.current
    return [w || img?.naturalWidth || 0, h || img?.naturalHeight || 0]
  }, [])

  const env = useCallback((): DrawEnv => {
    const vp = vpRef.current
    return { scale: vp.scale, dpr: sizeRef.current.dpr, tx: vp.tx, ty: vp.ty }
  }, [vpRef])

  // ---------------- 繪製 ----------------

  const drawImageLayer = useCallback(() => {
    const canvas = imgCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const { w, h, dpr } = sizeRef.current
    const vp = vpRef.current
    const [W, H] = dims()
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    const img = imgRef.current
    if (img && W > 0 && H > 0) {
      // 放大超過 2x 關掉平滑，看得到像素格
      ctx.imageSmoothingEnabled = vp.scale <= 2
      ctx.imageSmoothingQuality = 'high'
      ctx.drawImage(img, 0, 0, img.naturalWidth, img.naturalHeight, vp.tx, vp.ty, W * vp.scale, H * vp.scale)
    }
    if (W > 0 && H > 0) {
      // 影像邊界 1px 邊框（對齊半像素避免糊）
      ctx.strokeStyle = 'rgba(255,255,255,0.35)'
      ctx.lineWidth = 1
      ctx.strokeRect(Math.round(vp.tx) + 0.5, Math.round(vp.ty) + 0.5, Math.round(W * vp.scale), Math.round(H * vp.scale))
    }
    if (latest.current.grid && vp.scale >= GRID_MIN_SCALE && W > 0 && H > 0) {
      // 只畫可見範圍內的像素格線
      const x0 = Math.max(0, Math.floor((0 - vp.tx) / vp.scale))
      const x1 = Math.min(W, Math.ceil((w - vp.tx) / vp.scale))
      const y0 = Math.max(0, Math.floor((0 - vp.ty) / vp.scale))
      const y1 = Math.min(H, Math.ceil((h - vp.ty) / vp.scale))
      // 用 difference 疊色：在白色（二值化亮區）與黑色像素上都看得到格線；固定白色在亮圖上等於沒畫
      ctx.save()
      ctx.globalCompositeOperation = 'difference'
      ctx.strokeStyle = 'rgba(255,255,255,0.28)'
      ctx.beginPath()
      for (let x = x0; x <= x1; x++) {
        const sx = Math.round(x * vp.scale + vp.tx) + 0.5
        ctx.moveTo(sx, Math.max(0, y0 * vp.scale + vp.ty))
        ctx.lineTo(sx, Math.min(h, y1 * vp.scale + vp.ty))
      }
      for (let y = y0; y <= y1; y++) {
        const sy = Math.round(y * vp.scale + vp.ty) + 0.5
        ctx.moveTo(Math.max(0, x0 * vp.scale + vp.tx), sy)
        ctx.lineTo(Math.min(w, x1 * vp.scale + vp.tx), sy)
      }
      ctx.stroke()
      ctx.restore()
    }
  }, [dims, vpRef])

  const drawOverlayLayer = useCallback(() => {
    const canvas = ovCanvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const { w, h, dpr } = sizeRef.current
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    const e = env()
    const L = latest.current
    if (L.showOverlays && L.overlays && L.overlays.length > 0) drawOverlays(ctx, e, L.overlays)
    const region = liveRoiRef.current ?? L.roi ?? null
    if (region) {
      const drag = dragRef.current
      const active = drag?.kind === 'handle' ? drag.handle : hoverRef.current
      drawRoi(ctx, e, region, {
        handles: L.editMode || drag?.kind === 'draw',
        active,
        selectedVertex: selectedVertexRef.current,
      })
    }
  }, [env])

  const schedule = useCallback(
    (image: boolean, overlay: boolean) => {
      const r = rafRef.current
      r.image ||= image
      r.overlay ||= overlay
      if (r.id) return
      r.id = requestAnimationFrame(() => {
        const doImage = r.image
        const doOverlay = r.overlay
        r.id = 0
        r.image = false
        r.overlay = false
        if (doImage) drawImageLayer()
        if (doOverlay) drawOverlayLayer()
      })
    },
    [drawImageLayer, drawOverlayLayer],
  )

  const updateScaleLabel = useCallback(() => {
    const el = scaleRef.current
    if (el) el.textContent = `${Math.round(vpRef.current.scale * 100)}%`
  }, [vpRef])

  const setViewport = useCallback(
    (vp: Viewport) => {
      vpRef.current = vp
      updateScaleLabel()
      schedule(true, true)
      onViewportChangeRef.current?.(vp)
    },
    [schedule, updateScaleLabel, vpRef],
  )

  // 受控視角：外面給的視角跟目前不同才套用（不回呼）。
  useEffect(() => {
    if (!viewport) return
    const cur = vpRef.current
    if (cur.scale === viewport.scale && cur.tx === viewport.tx && cur.ty === viewport.ty) return
    vpRef.current = viewport
    updateScaleLabel()
    schedule(true, true)
  }, [viewport, schedule, updateScaleLabel, vpRef])

  const fit = useCallback(() => {
    const [W, H] = dims()
    const { w, h } = sizeRef.current
    // w/h <= 1：容器尚未排版（resize 會把 0 clamp 成 1）。此時不 fit 也不標記 fitted，
    // 等 ResizeObserver 拿到真實尺寸再走 !fittedRef → fit()，否則視角會鎖死在退化縮放。
    if (W <= 0 || H <= 0 || w <= 1 || h <= 1) return
    fittedRef.current = true
    setViewport(fitViewport(w, h, W, H))
  }, [dims, setViewport])

  const zoomBy = useCallback(
    (factor: number) => {
      const { w, h } = sizeRef.current
      setViewport(zoomAt(vpRef.current, w / 2, h / 2, factor))
    },
    [setViewport, vpRef],
  )

  /** 1:1（100%）：比例設為 1 並把影像置中。不保留舊平移量，避免縮放／改視窗後影像跑到畫面外。 */
  const oneToOne = useCallback(() => {
    const [W, H] = dims()
    const { w, h } = sizeRef.current
    if (W <= 0 || H <= 0 || w <= 1 || h <= 1) return
    fittedRef.current = true
    setViewport(scaleCenteredOnImage(w, h, W, H, 1))
  }, [dims, setViewport])

  // ---------------- ROI 回報（每 frame 最多一次） ----------------

  const flushRoi = useCallback(() => {
    const pending = pendingRoiRef.current
    if (!pending) return
    pendingRoiRef.current = null
    const rounded = roundRegion(pending)
    if (!regionsEqual(rounded, latest.current.roi)) latest.current.onRoiChange?.(rounded)
  }, [])

  const emitRoi = useCallback(
    (region: Region, immediate = false) => {
      liveRoiRef.current = region
      pendingRoiRef.current = region
      schedule(false, true)
      if (immediate) flushRoi()
      else requestAnimationFrame(flushRoi)
    },
    [flushRoi, schedule],
  )

  const changeShape = useCallback(
    (shape: RoiShape) => {
      setDrawShape(shape)
      const cur = latest.current.roi
      if (cur && latest.current.onRoiChange) {
        selectedVertexRef.current = null
        emitRoi(convertRegion(cur, shape), true)
      }
    },
    [emitRoi],
  )

  const clampRoi = useCallback(() => {
    const cur = latest.current.roi
    const [W, H] = dims()
    if (cur && W > 0 && H > 0) emitRoi(clampRegion(cur, W, H), true)
  }, [dims, emitRoi])

  // ---------------- 尺寸 ----------------

  useLayoutEffect(() => {
    const el = containerRef.current
    if (!el) return
    const resize = () => {
      const rect = el.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      const w = Math.max(1, Math.round(rect.width))
      const h = Math.max(1, Math.round(rect.height))
      const prev = sizeRef.current
      sizeRef.current = { w, h, dpr }
      // 容器尺寸變了（視窗縮放、面板展開）：平移量跟著補一半差值，
      // 讓畫面中心看的內容不變；否則影像會往左上偏，看起來像跑位。
      if (fittedRef.current && (prev.w !== w || prev.h !== h)) {
        vpRef.current = recenterOnResize(vpRef.current, prev.w, prev.h, w, h)
      }
      for (const c of [imgCanvasRef.current, ovCanvasRef.current]) {
        if (!c) continue
        c.width = Math.round(w * dpr)
        c.height = Math.round(h * dpr)
        c.style.width = `${w}px`
        c.style.height = `${h}px`
      }
      if (!fittedRef.current) fit()
      else schedule(true, true)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el)
    return () => ro.disconnect()
  }, [fit, schedule])

  // ---------------- 影像載入 ----------------

  useEffect(() => {
    setLoadError(false)
    if (!src) {
      imgRef.current = null
      samplerRef.current = null
      setLoaded(false)
      schedule(true, true)
      return
    }
    let cancelled = false
    const img = new Image()
    img.onload = () => {
      if (cancelled) return
      const prev = imgRef.current
      imgRef.current = img
      // 像素取樣用離屏 canvas：跨域圖片會污染 canvas，取不到值就標示不可用
      try {
        const c = document.createElement('canvas')
        c.width = img.naturalWidth
        c.height = img.naturalHeight
        const ctx = c.getContext('2d', { willReadFrequently: true })
        if (ctx) {
          ctx.drawImage(img, 0, 0)
          ctx.getImageData(0, 0, 1, 1)
          const [W, H] = dims()
          samplerRef.current = {
            ctx,
            w: img.naturalWidth,
            h: img.naturalHeight,
            approx: img.naturalWidth !== W || img.naturalHeight !== H,
          }
        }
      } catch {
        samplerRef.current = null
      }
      setLoaded(true)
      // 首次載入或座標系尺寸未知（imageWidth=0 時用影像本身）→ fit；否則保留視角
      const sameDims =
        prev && prev.naturalWidth === img.naturalWidth && prev.naturalHeight === img.naturalHeight
      if (!fittedRef.current || (!latest.current.imageWidth && !sameDims)) fit()
      else schedule(true, true)
    }
    img.onerror = () => {
      if (cancelled) return
      // 清掉殘影（切換樣本失敗時不該顯示上一張），並顯示載入失敗提示。
      imgRef.current = null
      samplerRef.current = null
      setLoaded(false)
      setLoadError(true)
      schedule(true, true)
    }
    img.src = src
    return () => {
      cancelled = true
    }
  }, [src, dims, fit, schedule])

  // 座標系尺寸改變（換了不同影像）→ 重新 fit
  const prevDimsRef = useRef({ w: imageWidth, h: imageHeight })
  useEffect(() => {
    const p = prevDimsRef.current
    if (p.w !== imageWidth || p.h !== imageHeight) {
      prevDimsRef.current = { w: imageWidth, h: imageHeight }
      const s = samplerRef.current
      if (s) s.approx = s.w !== imageWidth || s.h !== imageHeight
      fittedRef.current = false
      fit()
    }
  }, [imageWidth, imageHeight, fit])

  // props 變動 → 重繪對應層
  useEffect(() => {
    schedule(true, false)
  }, [grid, schedule])
  useEffect(() => {
    // 父層回流新的 roi 後，放掉本地暫存
    if (!dragRef.current) liveRoiRef.current = null
    schedule(false, true)
  }, [overlays, roi, showOverlays, editMode, schedule])

  // ---------------- 互動 ----------------

  useEffect(() => {
    const el = containerRef.current
    const ov = ovCanvasRef.current
    if (!el || !ov) return

    const localPoint = (ev: PointerEvent | MouseEvent | WheelEvent): [number, number] => {
      const rect = ov.getBoundingClientRect()
      return [ev.clientX - rect.left, ev.clientY - rect.top]
    }

    const setCursor = (c: string) => {
      if (ov.style.cursor !== c) ov.style.cursor = c
    }

    const emitHover = (sx: number, sy: number) => {
      if (!latest.current.onHover) return
      const [ix, iy] = toImage(vpRef.current, sx, sy)
      hoverEmitRef.current.point = [ix, iy]
      if (hoverEmitRef.current.id) return
      hoverEmitRef.current.id = requestAnimationFrame(() => {
        hoverEmitRef.current.id = 0
        latest.current.onHover?.(hoverEmitRef.current.point)
      })
    }

    const updatePixelLabel = (sx: number, sy: number) => {
      const elp = pixelRef.current
      if (!elp) return
      const [ix, iy] = toImage(vpRef.current, sx, sy)
      const [W, H] = dims()
      if (W <= 0 || H <= 0 || ix < 0 || iy < 0 || ix >= W || iy >= H) {
        elp.textContent = ''
        return
      }
      const px = Math.floor(ix)
      const py = Math.floor(iy)
      let text = `${px}, ${py}`
      const s = samplerRef.current
      if (s) {
        const qx = Math.min(s.w - 1, Math.floor((px * s.w) / W))
        const qy = Math.min(s.h - 1, Math.floor((py * s.h) / H))
        const d = s.ctx.getImageData(qx, qy, 1, 1).data
        const val = d[0] === d[1] && d[1] === d[2] ? `G ${d[0]}` : `RGB ${d[0]},${d[1]},${d[2]}`
        text += `  ${s.approx ? '≈' : ''}${val}`
      }
      elp.textContent = text
    }

    const hoverCursor = (ix: number, iy: number) => {
      const L = latest.current
      if (L.editMode && L.roi) {
        const hs = getHandles(L.roi, env())
        const h = hitHandle(hs, ix, iy, vpRef.current.scale)
        if (h !== hoverRef.current) {
          hoverRef.current = h
          schedule(false, true)
        }
        if (h) return setCursor(h.cursor)
        if (hitBody(L.roi, ix, iy, vpRef.current.scale)) return setCursor('move')
        return setCursor('grab')
      }
      if (hoverRef.current) {
        hoverRef.current = null
        schedule(false, true)
      }
      if (L.drawMode) return setCursor('crosshair')
      setCursor(L.onPick ? 'crosshair' : 'grab')
    }

    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault()
      const [sx, sy] = localPoint(ev)
      const delta = ev.deltaMode === 1 ? ev.deltaY * 16 : ev.deltaY
      const factor = Math.exp(-delta * 0.0018)
      setViewport(zoomAt(vpRef.current, sx, sy, factor))
      updatePixelLabel(sx, sy)
      emitHover(sx, sy)
    }

    const onPointerDown = (ev: PointerEvent) => {
      if (ev.button !== 0 && ev.button !== 1 && ev.button !== 2) return
      el.focus({ preventScroll: true })
      const [sx, sy] = localPoint(ev)
      const [ix, iy] = toImage(vpRef.current, sx, sy)
      const L = latest.current
      const startPan = (pick: boolean) => {
        dragRef.current = { kind: 'pan', sx0: sx, sy0: sy, vp0: { ...vpRef.current }, moved: false, pick }
        setCursor('grabbing')
      }
      if (ev.button === 1) {
        ev.preventDefault()
        startPan(false)
        ov.setPointerCapture(ev.pointerId)
        return
      }
      if (L.editMode && L.roi) {
        const hs = getHandles(L.roi, env())
        const h = hitHandle(hs, ix, iy, vpRef.current.scale)
        if (ev.button === 2) {
          // 右鍵刪除多邊形頂點
          if (h?.kind === 'vertex' && L.roi.shape === 'polygon' && L.roi.points.length > 3) {
            const points = L.roi.points.filter((_, i) => i !== h.index)
            selectedVertexRef.current = null
            emitRoi({ shape: 'polygon', points }, true)
          }
          return
        }
        if (h) {
          selectedVertexRef.current = h.kind === 'vertex' ? (h.index ?? null) : null
          dragRef.current = { kind: 'handle', handle: h, region0: L.roi }
          setCursor(h.kind === 'rotate' ? 'grabbing' : h.cursor)
        } else if (hitBody(L.roi, ix, iy, vpRef.current.scale)) {
          selectedVertexRef.current = null
          dragRef.current = { kind: 'move', region0: L.roi, ix0: ix, iy0: iy }
          setCursor('move')
        } else {
          selectedVertexRef.current = null
          // 編輯模式點在形狀外：仍允許「點一下」回 onPick（呼叫端用來改選其他形狀／取消選取）。
          startPan(!!L.onPick)
        }
        schedule(false, true)
        ov.setPointerCapture(ev.pointerId)
        return
      }
      if (ev.button === 2) return
      if (L.drawMode) {
        const [W, H] = dims()
        if (ix >= 0 && iy >= 0 && ix <= W && iy <= H) {
          dragRef.current = { kind: 'draw', shape: L.activeDrawShape, ix0: ix, iy0: iy }
          setCursor('crosshair')
        } else startPan(false)
        ov.setPointerCapture(ev.pointerId)
        return
      }
      startPan(!!L.onPick)
      ov.setPointerCapture(ev.pointerId)
    }

    const onPointerMove = (ev: PointerEvent) => {
      const [sx, sy] = localPoint(ev)
      const drag = dragRef.current
      if (!drag) {
        const [ix, iy] = toImage(vpRef.current, sx, sy)
        hoverCursor(ix, iy)
        updatePixelLabel(sx, sy)
        emitHover(sx, sy)
        return
      }
      switch (drag.kind) {
        case 'pan': {
          const dx = sx - drag.sx0
          const dy = sy - drag.sy0
          if (!drag.moved && Math.hypot(dx, dy) < 3) return
          drag.moved = true
          vpRef.current = { scale: drag.vp0.scale, tx: drag.vp0.tx + dx, ty: drag.vp0.ty + dy }
          schedule(true, true)
          onViewportChangeRef.current?.(vpRef.current)
          break
        }
        case 'handle': {
          const [ix, iy] = toImage(vpRef.current, sx, sy)
          emitRoi(applyHandleDrag(drag.region0, drag.handle, ix, iy, ev.shiftKey))
          break
        }
        case 'move': {
          const [ix, iy] = toImage(vpRef.current, sx, sy)
          emitRoi(applyMove(drag.region0, ix - drag.ix0, iy - drag.iy0))
          break
        }
        case 'draw': {
          const [ix, iy] = toImage(vpRef.current, sx, sy)
          let x1 = ix
          let y1 = iy
          if (ev.shiftKey && (drag.shape === 'rect' || drag.shape === 'rotated_rect' || drag.shape === 'polygon')) {
            // Shift：正方形
            const d = Math.max(Math.abs(ix - drag.ix0), Math.abs(iy - drag.iy0))
            x1 = drag.ix0 + Math.sign(ix - drag.ix0 || 1) * d
            y1 = drag.iy0 + Math.sign(iy - drag.iy0 || 1) * d
          }
          liveRoiRef.current = regionFromDrag(drag.shape, drag.ix0, drag.iy0, x1, y1)
          schedule(false, true)
          break
        }
      }
      updatePixelLabel(sx, sy)
      emitHover(sx, sy)
    }

    const onPointerUp = (ev: PointerEvent) => {
      const drag = dragRef.current
      if (!drag) return
      dragRef.current = null
      if (ov.hasPointerCapture(ev.pointerId)) ov.releasePointerCapture(ev.pointerId)
      const [sx, sy] = localPoint(ev)
      const [ix, iy] = toImage(vpRef.current, sx, sy)
      switch (drag.kind) {
        case 'pan':
          if (!drag.moved && drag.pick && ev.button === 0) {
            const [W, H] = dims()
            if (ix >= 0 && iy >= 0 && ix < W && iy < H)
              latest.current.onPick?.(Math.floor(ix), Math.floor(iy))
          }
          break
        case 'handle':
        case 'move':
          // 最後一次回報後放掉本地暫存；React 會在下一個 rAF 前完成 re-render，不會閃
          flushRoi()
          liveRoiRef.current = null
          break
        case 'draw': {
          const region = liveRoiRef.current
          liveRoiRef.current = null
          if (region) {
            const rounded = roundRegion(region)
            // 太小視為誤觸
            const b = drag.shape === 'circle' || drag.shape === 'annulus' ? 3 : 2
            const size =
              rounded.shape === 'rect' ? Math.min(rounded.w, rounded.h)
              : rounded.shape === 'rotated_rect' ? Math.min(rounded.w, rounded.h)
              : rounded.shape === 'circle' ? rounded.r
              : rounded.shape === 'annulus' ? rounded.r_outer
              : rounded.shape === 'line' ? Math.hypot(rounded.x2 - rounded.x1, rounded.y2 - rounded.y1)
              : Math.hypot(ix - drag.ix0, iy - drag.iy0)
            if (size >= b) latest.current.onRoiChange?.(rounded)
          }
          schedule(false, true)
          break
        }
      }
      hoverCursor(ix, iy)
      schedule(false, true)
    }

    const onDblClick = (ev: MouseEvent) => {
      const [sx, sy] = localPoint(ev)
      const [ix, iy] = toImage(vpRef.current, sx, sy)
      const L = latest.current
      if (L.editMode && L.roi?.shape === 'polygon') {
        const hs = getHandles(L.roi, env())
        if (hitHandle(hs, ix, iy, vpRef.current.scale)) return
        const edge = hitPolygonEdge(L.roi, ix, iy, vpRef.current.scale)
        if (edge !== null) {
          const points = [...L.roi.points]
          points.splice(edge + 1, 0, [ix, iy])
          selectedVertexRef.current = edge + 1
          emitRoi({ shape: 'polygon', points }, true)
          return
        }
      }
      if (L.onDoublePick) {
        // 逐點繪製的雙擊收尾：交給呼叫端處理，不觸發 fit（避免畫到一半視角跳掉）
        L.onDoublePick(Math.floor(ix), Math.floor(iy))
        return
      }
      fit()
    }

    const onContextMenu = (ev: MouseEvent) => ev.preventDefault()

    const onPointerLeave = () => {
      if (pixelRef.current) pixelRef.current.textContent = ''
      if (latest.current.onHover) {
        hoverEmitRef.current.point = null
        latest.current.onHover(null)
      }
      if (hoverRef.current && !dragRef.current) {
        hoverRef.current = null
        schedule(false, true)
      }
    }

    const onKeyDown = (ev: KeyboardEvent) => {
      if (ev.ctrlKey || ev.metaKey || ev.altKey) return
      const L = latest.current
      switch (ev.key) {
        case 'f':
        case 'F':
          fit()
          break
        case '1':
          oneToOne()
          break
        case '+':
        case '=':
          zoomBy(1.25)
          break
        case '-':
        case '_':
          zoomBy(0.8)
          break
        case 'Escape':
          if (dragRef.current) {
            dragRef.current = null
            liveRoiRef.current = null
            pendingRoiRef.current = null
            schedule(true, true)
            break
          }
          return // 沒在拖曳就放行給上層（DL 工作區用 Esc 取消選取）
        case 'Backspace':
        case 'Delete': {
          const i = selectedVertexRef.current
          if (L.editMode && L.roi?.shape === 'polygon' && i !== null && L.roi.points.length > 3) {
            const points = L.roi.points.filter((_, k) => k !== i)
            selectedVertexRef.current = null
            emitRoi({ shape: 'polygon', points }, true)
            break
          }
          // 沒有頂點可刪就放行（不 preventDefault），讓上層（例如 DL 標記工作區的「刪形狀」）處理
          return
        }
        default:
          return
      }
      ev.preventDefault()
    }

    ov.addEventListener('wheel', onWheel, { passive: false })
    ov.addEventListener('pointerdown', onPointerDown)
    ov.addEventListener('pointermove', onPointerMove)
    ov.addEventListener('pointerup', onPointerUp)
    ov.addEventListener('pointercancel', onPointerUp)
    ov.addEventListener('pointerleave', onPointerLeave)
    ov.addEventListener('dblclick', onDblClick)
    ov.addEventListener('contextmenu', onContextMenu)
    el.addEventListener('keydown', onKeyDown)
    // 重新掛載（StrictMode / 依賴變動）後補畫一次，避免依賴前一次被取消的排程。
    schedule(true, true)
    return () => {
      ov.removeEventListener('wheel', onWheel)
      ov.removeEventListener('pointerdown', onPointerDown)
      ov.removeEventListener('pointermove', onPointerMove)
      ov.removeEventListener('pointerup', onPointerUp)
      ov.removeEventListener('pointercancel', onPointerUp)
      ov.removeEventListener('pointerleave', onPointerLeave)
      ov.removeEventListener('dblclick', onDblClick)
      ov.removeEventListener('contextmenu', onContextMenu)
      el.removeEventListener('keydown', onKeyDown)
      // 取消排程後一定要把 id 歸零，否則 schedule() 會以為還有 rAF 在排隊而永遠不再重繪
      //（StrictMode 的 mount→cleanup→mount 就會踩到：畫面全黑但互動正常）。
      // 保留 image/overlay 旗標，讓下一次 schedule 把漏掉的重繪補上。
      if (rafRef.current.id) {
        cancelAnimationFrame(rafRef.current.id)
        rafRef.current.id = 0
      }
      if (hoverEmitRef.current.id) {
        cancelAnimationFrame(hoverEmitRef.current.id)
        hoverEmitRef.current.id = 0
      }
    }
  }, [dims, emitRoi, env, fit, flushRoi, oneToOne, schedule, setViewport, vpRef, zoomBy])

  // ---------------- 渲染 ----------------

  const badgeClass =
    badge?.tone === 'ok'
      ? 'bg-green-600 text-white'
      : badge?.tone === 'ng'
        ? 'bg-red-600 text-white'
        : 'bg-neutral-600 text-white'

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      className={`relative overflow-hidden bg-viewer outline-none select-none ${className ?? ''}`}
    >
      <canvas ref={imgCanvasRef} className="absolute inset-0 block" />
      <canvas ref={ovCanvasRef} className="absolute inset-0 block touch-none" />
      {toolbar && (
        <Toolbar
          onFit={fit}
          onOneToOne={oneToOne}
          onZoomIn={() => zoomBy(1.25)}
          onZoomOut={() => zoomBy(0.8)}
          scaleRef={scaleRef}
          pixelRef={pixelRef}
          grid={grid}
          onToggleGrid={() => setGrid((g) => !g)}
          hasOverlays={!!overlays && overlays.length > 0}
          showOverlays={showOverlays}
          onToggleOverlays={() => setShowOverlays((v) => !v)}
          roiMode={roiMode}
          shapes={allowedShapes}
          activeShape={roi ? roi.shape : drawMode ? activeDrawShape : null}
          onShape={changeShape}
          canClamp={!!roi}
          onClampRoi={clampRoi}
        />
      )}
      {badge && (
        <div
          className={`pointer-events-none absolute top-8 right-2 z-10 rounded-md px-3 py-1 text-xl font-bold tracking-wide shadow ${badgeClass}`}
        >
          {badge.text}
        </div>
      )}
      {drawMode && loaded && (
        <div className="pointer-events-none absolute bottom-2 left-1/2 z-10 -translate-x-1/2 rounded-md bg-black/50 px-2 py-0.5 text-[11px] text-white/85">
          {t('viewer.drawHint')}
        </div>
      )}
      {!src && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-subtle">
          {t('viewer.noImage')}
        </div>
      )}
      {src && loadError && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-critical">
          {t('viewer.loadFailed')}
        </div>
      )}
    </div>
  )
}

export default ImageViewer
