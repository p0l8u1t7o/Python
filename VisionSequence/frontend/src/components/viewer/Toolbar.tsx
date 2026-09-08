/**
 * 檢視器頂部工具列：半透明深底、小而不佔位。
 * 比例 % 與游標座標／像素值用 DOM ref 由檢視器直接寫入（不走 React state），
 * 這樣拖曳、滾輪、移動游標時不會觸發 re-render。
 */
import type { RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { Crosshair, Spline, Egg,
  Circle,
  CircleDot,
  Grid3x3,
  Layers,
  Maximize,
  Minus,
  Pentagon,
  Plus,
  RectangleHorizontal,
  RotateCw,
  Shrink,
  Slash,
} from 'lucide-react'
import type { RoiShape } from '@/lib/types'

export interface ToolbarProps {
  onFit: () => void
  onOneToOne: () => void
  onZoomIn: () => void
  onZoomOut: () => void
  scaleRef: RefObject<HTMLSpanElement | null>
  pixelRef: RefObject<HTMLSpanElement | null>
  grid: boolean
  onToggleGrid: () => void
  crosshair: boolean
  onToggleCrosshair: () => void
  hasOverlays: boolean
  showOverlays: boolean
  onToggleOverlays: () => void
  hasCompare: boolean
  compareOpacity: number
  onCompareOpacityChange: (value: number) => void
  /** ROI 編輯／繪製模式才顯示形狀按鈕 */
  roiMode: boolean
  shapes: RoiShape[]
  activeShape: RoiShape | null
  onShape: (s: RoiShape) => void
  /** 有現成 ROI 才能夾在影像內 */
  canClamp: boolean
  onClampRoi: () => void
}

const SHAPE_ICON: Record<RoiShape, typeof Circle> = {
  rect: RectangleHorizontal,
  rotated_rect: RotateCw,
  circle: Circle,
  ellipse: Egg,
  annulus: CircleDot,
  polygon: Pentagon,
  polyline: Spline,
  line: Slash,
  point: Crosshair,
}

const btn =
  'inline-flex h-6 min-w-6 items-center justify-center rounded px-1 text-white/80 transition hover:bg-white/15 hover:text-white'
const btnOn = 'bg-sky-500/40 text-white'

export function Toolbar(p: ToolbarProps) {
  const { t } = useTranslation()
  return (
    <div
      className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center gap-0.5 px-1.5 py-1 text-xs select-none"
      onDoubleClick={(e) => e.stopPropagation()}
    >
      <div className="pointer-events-auto flex items-center gap-0.5 rounded-md bg-black/45 px-1 py-0.5 opacity-80 backdrop-blur-sm transition hover:opacity-100">
        <button type="button" className={btn} title={t('viewer.fit')} onClick={p.onFit}>
          <Shrink size={14} />
        </button>
        <button type="button" className={btn} title={t('viewer.oneToOne')} onClick={p.onOneToOne}>
          <Maximize size={14} />
        </button>
        <button type="button" className={btn} title={t('viewer.zoomOut')} onClick={p.onZoomOut}>
          <Minus size={14} />
        </button>
        <span ref={p.scaleRef} className="tnum min-w-11 text-center font-mono text-white/90">
          100%
        </span>
        <button type="button" className={btn} title={t('viewer.zoomIn')} onClick={p.onZoomIn}>
          <Plus size={14} />
        </button>
        <span className="mx-0.5 h-4 w-px bg-white/20" />
        <button
          type="button"
          className={`${btn} ${p.grid ? btnOn : ''}`}
          title={t('viewer.grid')}
          onClick={p.onToggleGrid}
        >
          <Grid3x3 size={14} />
        </button>
        <button
          type="button"
          className={`${btn} ${p.crosshair ? btnOn : ''}`}
          title={t('viewer.crosshair')}
          onClick={p.onToggleCrosshair}
        >
          <Crosshair size={14} />
        </button>
        {p.hasOverlays && (
          <button
            type="button"
            className={`${btn} ${p.showOverlays ? btnOn : ''}`}
            title={t('viewer.overlays')}
            onClick={p.onToggleOverlays}
          >
            <Layers size={14} />
          </button>
        )}
        {p.hasCompare && (
          <>
            <span className="mx-0.5 h-4 w-px bg-white/20" />
            <label className="flex items-center gap-1 px-1 text-[11px] text-white/85" title={t('viewer.compareOpacity')}>
              <Layers size={13} />
              <input
                type="range"
                min={0}
                max={100}
                value={p.compareOpacity}
                aria-label={t('viewer.compareOpacity')}
                className="h-1 w-20 accent-sky-400"
                onChange={(event) => p.onCompareOpacityChange(Number(event.target.value))}
              />
              <span className="tnum w-8 text-right">{p.compareOpacity}%</span>
            </label>
          </>
        )}
        {p.roiMode && p.shapes.length > 0 && (
          <>
            <span className="mx-0.5 h-4 w-px bg-white/20" />
            {p.shapes.map((s) => {
              const Icon = SHAPE_ICON[s]
              return (
                <button
                  key={s}
                  type="button"
                  className={`${btn} ${p.activeShape === s ? btnOn : ''}`}
                  title={t(`viewer.shapes.${s}`)}
                  onClick={() => p.onShape(s)}
                >
                  <Icon size={14} />
                </button>
              )
            })}
            {p.canClamp && (
              <button
                type="button"
                className={`${btn} px-1.5 text-[11px]`}
                title={t('viewer.clampHint')}
                onClick={p.onClampRoi}
              >
                {t('viewer.clamp')}
              </button>
            )}
          </>
        )}
      </div>
      <div className="flex-1" />
      <span
        ref={p.pixelRef}
        className="tnum pointer-events-none rounded-md bg-black/45 px-1.5 py-0.5 font-mono text-[11px] whitespace-pre text-white/85 empty:hidden"
      />
    </div>
  )
}
