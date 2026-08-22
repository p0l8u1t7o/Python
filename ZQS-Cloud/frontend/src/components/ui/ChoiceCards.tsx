import type { LucideIcon } from 'lucide-react'
import { useId } from 'react'

import { Field } from './Field'

export interface Choice<T extends string> {
  value: T
  label: string
  /** One or two sentences on what picking this actually does. */
  description: string
  icon: LucideIcon
  /** Optional third line for a consequence worth spelling out. */
  note?: string
}

interface Props<T extends string> {
  label?: React.ReactNode
  value: T
  choices: Choice<T>[]
  onChange: (value: T) => void
  hint?: React.ReactNode
  columns?: 1 | 2
}

/**
 * A radio group that shows what each option means, instead of naming it.
 *
 * For settings where the name alone does not carry the decision. "Time-of-use
 * arbitrage" and "Maximise self-consumption" are both accurate and neither
 * tells an operator which one bills less at their site - so the description
 * belongs next to the option, at the moment of choosing, not in a manual.
 *
 * Built on real radio inputs rather than clickable divs: keyboard navigation,
 * form semantics and screen-reader grouping all come for free, and a settings
 * page that cannot be driven from the keyboard is a settings page somebody
 * eventually cannot use.
 */
export function ChoiceCards<T extends string>({
  label,
  value,
  choices,
  onChange,
  hint,
  columns = 1,
}: Props<T>) {
  const name = useId()
  return (
    <Field label={label} hint={hint}>
      <div
        role="radiogroup"
        aria-label={typeof label === 'string' ? label : undefined}
        className={`grid gap-2 ${columns === 2 ? 'sm:grid-cols-2' : ''}`}
      >
        {choices.map((choice) => {
          const Icon = choice.icon
          const selected = choice.value === value
          return (
            <label
              key={choice.value}
              className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition
                ${
                  selected
                    ? 'border-accent bg-accent/5 ring-1 ring-accent'
                    : 'border-line hover:border-muted hover:bg-subtle'
                }`}
            >
              <input
                type="radio"
                name={name}
                value={choice.value}
                checked={selected}
                onChange={() => onChange(choice.value)}
                className="sr-only"
              />
              <Icon
                size={18}
                aria-hidden
                className={`mt-0.5 shrink-0 ${selected ? 'text-accent' : 'text-muted'}`}
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{choice.label}</span>
                <span className="mt-0.5 block text-xs text-muted">
                  {choice.description}
                </span>
                {choice.note ? (
                  <span className="mt-1 block text-xs text-warning">{choice.note}</span>
                ) : null}
              </span>
            </label>
          )
        })}
      </div>
    </Field>
  )
}
