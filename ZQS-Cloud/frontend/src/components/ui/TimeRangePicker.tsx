import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CalendarRange, X } from 'lucide-react'

import { formatDateTime } from '@/lib/format'
import { RANGE_KEYS, toLocalInputValue, type PresetKey, type TimeRange } from '@/lib/useTimeRange'
import { Button } from './Button'
import { SegmentedControl } from './Field'

/**
 * The rolling presets, plus a way to pin an exact interval.
 *
 * The presets answer "what is happening"; a fixed interval answers "what
 * happened at 03:40 last Tuesday", which a rolling window cannot - it moves
 * out from under you while you read it. Both are needed, so both are here, and
 * the control makes it obvious which one is active.
 */
export function TimeRangePicker({
  range,
  size = 'sm',
  className = '',
}: {
  range: TimeRange
  size?: 'sm' | 'md'
  className?: string
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [from, setFrom] = useState(() => toLocalInputValue(range.start))
  const [to, setTo] = useState(() => toLocalInputValue(range.end))
  const [problem, setProblem] = useState('')
  const container = useRef<HTMLDivElement>(null)

  // Opening the panel should offer the window currently on screen as the
  // starting point, not whatever was typed the last time it was open.
  useEffect(() => {
    if (open) {
      setFrom(toLocalInputValue(range.start))
      setTo(toLocalInputValue(range.end))
      setProblem('')
    }
  }, [open, range.start, range.end])

  useEffect(() => {
    if (!open) return
    function onPointerDown(event: MouseEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open])

  function apply() {
    const start = new Date(from)
    const end = new Date(to)
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
      setProblem(t('range.invalid'))
      return
    }
    if (start >= end) {
      setProblem(t('range.startAfterEnd'))
      return
    }
    range.setCustom(start.toISOString(), end.toISOString())
    setOpen(false)
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`} ref={container}>
      <SegmentedControl<PresetKey>
        size={size}
        value={(range.isCustom ? '' : range.key) as PresetKey}
        onChange={range.setKey}
        options={RANGE_KEYS.map((key) => ({ value: key, label: t(`range.${key}`) }))}
      />

      <div className="relative">
        <Button
          size={size}
          icon={<CalendarRange className="size-3.5" />}
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
          className={range.isCustom ? 'border-brand text-brand' : ''}
        >
          {range.isCustom
            ? `${formatDateTime(range.start)} – ${formatDateTime(range.end)}`
            : t('range.custom')}
        </Button>

        {open ? (
          <div className="absolute right-0 z-30 mt-1 w-72 rounded-lg border border-line bg-surface p-3 shadow-lg">
            <div className="space-y-3">
              <label className="block">
                <span className="label">{t('range.from')}</span>
                <input
                  type="datetime-local"
                  value={from}
                  max={to || undefined}
                  onChange={(event) => setFrom(event.target.value)}
                  className="input"
                />
              </label>
              <label className="block">
                <span className="label">{t('range.to')}</span>
                <input
                  type="datetime-local"
                  value={to}
                  min={from || undefined}
                  onChange={(event) => setTo(event.target.value)}
                  className="input"
                />
              </label>
              {problem ? <p className="text-xs text-critical">{problem}</p> : null}
              <p className="hint">{t('range.customHint')}</p>
              <div className="flex justify-end gap-2">
                {range.isCustom ? (
                  <Button
                    size="sm"
                    icon={<X className="size-3.5" />}
                    onClick={() => {
                      range.clearCustom()
                      setOpen(false)
                    }}
                  >
                    {t('common.clear')}
                  </Button>
                ) : null}
                <Button size="sm" variant="primary" onClick={apply}>
                  {t('common.apply')}
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
