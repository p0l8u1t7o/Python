/** 畫布上的縮放滑桿 + 符合視窗 + 自動排列 + 線上顯示數值。 */
import { Panel, useReactFlow, useViewport } from '@xyflow/react'
import { Maximize, Minus, Network, Plus, Tag } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const MIN_ZOOM = 0.2
const MAX_ZOOM = 2

export function ZoomSlider({ onAutoLayout, edgeValues, onEdgeValuesChange }: { onAutoLayout: () => void; edgeValues?: boolean; onEdgeValuesChange?: (on: boolean) => void }) {
  const { t } = useTranslation()
  const { zoom } = useViewport()
  const { zoomTo, fitView } = useReactFlow()
  const set = (value: number) => void zoomTo(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value)), { duration: 120 })
  return (
    <Panel position="bottom-center" className="flex items-center gap-1 rounded-lg border border-line bg-surface px-2 py-0.5 shadow-sm">
      <button type="button" className="btn-icon" onClick={() => set(zoom / 1.2)} aria-label={t('editor.zoomOut')}><Minus size={12} /></button>
      <input type="range" min={MIN_ZOOM} max={MAX_ZOOM} step={0.05} value={zoom} onChange={(e) => set(Number(e.target.value))} className="h-1 w-24 cursor-pointer accent-[var(--brand)]" aria-label={t('editor.zoom')} />
      <button type="button" className="btn-icon" onClick={() => set(zoom * 1.2)} aria-label={t('editor.zoomIn')}><Plus size={12} /></button>
      <span className="w-9 text-center text-[10px] tabular-nums text-muted">{Math.round(zoom * 100)}%</span>
      <span className="h-4 w-px bg-line" aria-hidden />
      <button type="button" className="btn-icon" onClick={() => void fitView({ padding: 0.15, duration: 250 })} title={t('editor.fitView')}><Maximize size={12} /></button>
      <button type="button" className="btn-icon" onClick={onAutoLayout} title={t('editor.autoLayoutHint')}><Network size={12} /></button>
      {onEdgeValuesChange ? (
        <button type="button" className={`btn-icon ${edgeValues ? 'text-brand' : ''}`} onClick={() => onEdgeValuesChange(!edgeValues)} title={t('editor.edgeValuesHint')} aria-pressed={edgeValues} data-testid="editor-edge-values"><Tag size={12} /></button>
      ) : null}
    </Panel>
  )
}
