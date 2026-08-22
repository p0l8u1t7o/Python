import type { LucideIcon } from 'lucide-react'
import { useId } from 'react'

export interface Tab<T extends string> {
  value: T
  label: string
  icon?: LucideIcon
  /** Shown under the bar when this tab is selected. */
  description?: string
  /** A prerequisite worth stating before the operator commits to it. */
  note?: string
}

interface Props<T extends string> {
  tabs: Tab<T>[]
  value: T
  onChange: (value: T) => void
  children?: React.ReactNode
  className?: string
}

/**
 * A tab bar that also acts as the choice.
 *
 * Used where the tabs *are* the setting, not just a view: picking the peak
 * shaving tab selects peak shaving and reveals only the fields peak shaving
 * uses. A form that shows every strategy's parameters at once asks the
 * operator to work out which ones apply to them, and the answer is not
 * guessable from the field names.
 *
 * Real tab semantics (`tablist` / `tab` / `aria-selected`) so arrow keys and
 * screen readers behave as expected; the panel is rendered by the caller.
 */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  children,
  className = '',
}: Props<T>) {
  const id = useId()
  const active = tabs.find((tab) => tab.value === value)

  function onKeyDown(event: React.KeyboardEvent) {
    const index = tabs.findIndex((tab) => tab.value === value)
    if (index === -1) return
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (step === 0) return
    event.preventDefault()
    onChange(tabs[(index + step + tabs.length) % tabs.length].value)
  }

  return (
    <div className={className}>
      <div
        role="tablist"
        aria-label={active?.label}
        onKeyDown={onKeyDown}
        className="flex flex-wrap gap-1 border-b border-line"
      >
        {tabs.map((tab) => {
          const Icon = tab.icon
          const selected = tab.value === value
          return (
            <button
              key={tab.value}
              id={`${id}-${tab.value}`}
              role="tab"
              type="button"
              aria-selected={selected}
              aria-controls={`${id}-panel`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(tab.value)}
              className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                selected
                  ? 'border-accent text-accent'
                  : 'border-transparent text-muted hover:text-content'
              }`}
            >
              {Icon ? <Icon size={15} aria-hidden /> : null}
              {tab.label}
            </button>
          )
        })}
      </div>

      <div
        id={`${id}-panel`}
        role="tabpanel"
        aria-labelledby={`${id}-${value}`}
        className="pt-3"
      >
        {active?.description ? (
          <p className="mb-3 text-sm text-muted">{active.description}</p>
        ) : null}
        {active?.note ? (
          <p className="mb-3 text-xs text-warning">{active.note}</p>
        ) : null}
        {children}
      </div>
    </div>
  )
}
