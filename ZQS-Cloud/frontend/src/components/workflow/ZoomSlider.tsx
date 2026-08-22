import { Panel, useReactFlow, useViewport } from '@xyflow/react'
import { Maximize, Minus, Network, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const MIN_ZOOM = 0.2
const MAX_ZOOM = 2

/**
 * The Zoom-Slider pattern: a slider with the current percentage, plus
 * fit-view and one-click tidy-up, living on the canvas itself where the
 * hands already are.
 */
export function ZoomSlider({ onAutoLayout }: { onAutoLayout: () => void }) {
  const { t } = useTranslation()
  const { zoom } = useViewport()
  const { zoomTo, fitView } = useReactFlow()

  const set = (value: number) =>
    void zoomTo(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value)), { duration: 120 })

  return (
    <Panel
      position="bottom-center"
      className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2 py-1 shadow-sm"
    >
      <button
        type="button"
        className="rounded p-1 text-muted hover:bg-surface-muted hover:text-content"
        onClick={() => set(zoom / 1.2)}
        aria-label={t('workflows.zoomOut')}
      >
        <Minus size={13} aria-hidden />
      </button>
      <input
        type="range"
        min={MIN_ZOOM}
        max={MAX_ZOOM}
        step={0.05}
        value={zoom}
        onChange={(event) => set(Number(event.target.value))}
        className="h-1 w-28 cursor-pointer accent-[var(--brand)]"
        aria-label={t('workflows.zoom')}
      />
      <button
        type="button"
        className="rounded p-1 text-muted hover:bg-surface-muted hover:text-content"
        onClick={() => set(zoom * 1.2)}
        aria-label={t('workflows.zoomIn')}
      >
        <Plus size={13} aria-hidden />
      </button>
      <span className="w-10 text-center text-[11px] tabular-nums text-muted">
        {Math.round(zoom * 100)}%
      </span>
      <span className="h-4 w-px bg-line" aria-hidden />
      <button
        type="button"
        className="rounded p-1 text-muted hover:bg-surface-muted hover:text-content"
        onClick={() => void fitView({ padding: 0.15, duration: 250 })}
        title={t('workflows.fitView')}
      >
        <Maximize size={13} aria-hidden />
      </button>
      <button
        type="button"
        className="rounded p-1 text-muted hover:bg-surface-muted hover:text-content"
        onClick={onAutoLayout}
        title={t('workflows.autoLayoutHint')}
      >
        <Network size={13} aria-hidden />
      </button>
    </Panel>
  )
}
