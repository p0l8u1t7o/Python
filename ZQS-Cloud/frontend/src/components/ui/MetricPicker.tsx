import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, GripVertical, Plus, RotateCcw, Search, X } from 'lucide-react'

import type { MetricValue } from '@/lib/types'
import { Button } from './Button'
import { Modal } from './Modal'

/**
 * Choose which readings a device shows, and in what order.
 *
 * The device decides what it publishes; a battery can report forty values and
 * nobody wants forty tiles. So the list is the *operator's*, drawn from
 * whatever has actually arrived rather than from a fixed catalogue - a metric
 * this particular unit has never sent is not offered, because a tile that can
 * only ever read "—" is worse than no tile.
 *
 * Reordering uses the browser's own drag-and-drop rather than a library. It
 * is one list of at most a few dozen rows; a drag-and-drop dependency would
 * be larger than the feature.
 */
export function MetricPicker({
  open,
  onClose,
  available,
  selected,
  onSave,
  onReset,
  saving = false,
}: {
  open: boolean
  onClose: () => void
  /** Everything this device has reported, newest values included. */
  available: MetricValue[]
  /** Metric keys currently shown, in display order. */
  selected: string[]
  onSave: (keys: string[]) => void
  onReset: () => void
  saving?: boolean
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<string[]>(selected)
  const [query, setQuery] = useState('')
  const dragged = useRef<number | null>(null)
  const [dragOver, setDragOver] = useState<number | null>(null)

  // Reset the draft whenever the dialog is opened, so a cancelled edit does
  // not leak into the next one.
  const openedWith = useRef(open)
  if (open && !openedWith.current) {
    openedWith.current = true
    setDraft(selected)
    setQuery('')
  } else if (!open && openedWith.current) {
    openedWith.current = false
  }

  const byKey = useMemo(
    () => new Map(available.map((metric) => [metric.metric_key, metric])),
    [available],
  )

  const unselected = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return available
      .filter((metric) => !draft.includes(metric.metric_key))
      .filter(
        (metric) =>
          !needle ||
          metric.metric_key.toLowerCase().includes(needle) ||
          metric.label.toLowerCase().includes(needle),
      )
  }, [available, draft, query])

  function move(from: number, to: number) {
    if (from === to) return
    setDraft((current) => {
      const next = [...current]
      const [item] = next.splice(from, 1)
      next.splice(to, 0, item)
      return next
    })
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={t('devices.customiseValues')}
      description={t('devices.customiseValuesHint')}
      footer={
        <>
          <Button icon={<RotateCcw className="size-3.5" />} onClick={onReset}>
            {t('devices.resetToDefault')}
          </Button>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={saving} onClick={() => onSave(draft)}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 sm:grid-cols-2">
        {/* ---- Shown, in order ------------------------------------------ */}
        <div>
          <p className="label">{t('devices.shownValues', { count: draft.length })}</p>
          {draft.length === 0 ? (
            <p className="rounded-lg border border-dashed border-line p-3 text-xs text-muted">
              {t('devices.noneSelected')}
            </p>
          ) : (
            <ul className="space-y-1">
              {draft.map((key, index) => {
                const metric = byKey.get(key)
                return (
                  <li
                    key={key}
                    draggable
                    onDragStart={() => {
                      dragged.current = index
                    }}
                    onDragEnter={() => setDragOver(index)}
                    onDragOver={(event) => event.preventDefault()}
                    onDragEnd={() => {
                      dragged.current = null
                      setDragOver(null)
                    }}
                    onDrop={(event) => {
                      event.preventDefault()
                      if (dragged.current !== null) move(dragged.current, index)
                      dragged.current = null
                      setDragOver(null)
                    }}
                    className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 ${
                      dragOver === index ? 'border-brand bg-brand-soft' : 'border-line'
                    }`}
                  >
                    <GripVertical
                      className="size-3.5 shrink-0 cursor-grab text-subtle"
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">
                        {metric?.label ?? key}
                      </span>
                      <span className="block truncate font-mono text-[11px] text-subtle">
                        {key}
                        {metric?.unit ? ` · ${metric.unit}` : ''}
                      </span>
                    </span>
                    {/* Keyboard users cannot drag, so the same reordering is
                        reachable by button - dragging is the shortcut, not
                        the only route. */}
                    <span className="flex shrink-0 flex-col">
                      <button
                        type="button"
                        disabled={index === 0}
                        onClick={() => move(index, index - 1)}
                        aria-label={t('devices.moveUp')}
                        className="px-1 text-[10px] leading-3 text-subtle hover:text-content disabled:opacity-30"
                      >
                        ▲
                      </button>
                      <button
                        type="button"
                        disabled={index === draft.length - 1}
                        onClick={() => move(index, index + 1)}
                        aria-label={t('devices.moveDown')}
                        className="px-1 text-[10px] leading-3 text-subtle hover:text-content disabled:opacity-30"
                      >
                        ▼
                      </button>
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setDraft((current) => current.filter((item) => item !== key))
                      }
                      aria-label={t('common.remove')}
                      className="shrink-0 text-subtle hover:text-critical"
                    >
                      <X className="size-3.5" />
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        {/* ---- Available ------------------------------------------------- */}
        <div>
          <p className="label">{t('devices.availableValues')}</p>
          <div className="mb-2 flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5">
            <Search className="size-3.5 shrink-0 text-subtle" aria-hidden />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('common.search')}
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-subtle"
            />
          </div>

          {available.length === 0 ? (
            <p className="rounded-lg border border-dashed border-line p-3 text-xs text-muted">
              {t('devices.noReportedMetrics')}
            </p>
          ) : unselected.length === 0 ? (
            <p className="flex items-center gap-1.5 rounded-lg bg-surface-muted p-3 text-xs text-muted">
              <Check className="size-3.5" aria-hidden />
              {t('devices.allValuesShown')}
            </p>
          ) : (
            <ul className="max-h-72 space-y-1 overflow-y-auto pr-1">
              {unselected.map((metric) => (
                <li key={metric.metric_key}>
                  <button
                    type="button"
                    onClick={() => setDraft((current) => [...current, metric.metric_key])}
                    className="flex w-full items-center gap-2 rounded-lg border border-line px-2 py-1.5 text-left hover:bg-surface-muted"
                  >
                    <Plus className="size-3.5 shrink-0 text-subtle" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{metric.label}</span>
                      <span className="block truncate font-mono text-[11px] text-subtle">
                        {metric.metric_key}
                        {metric.unit ? ` · ${metric.unit}` : ''}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Modal>
  )
}
