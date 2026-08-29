import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { useId } from 'react'

export function Field({ label, hint, error, required, children, className = '' }: { label?: ReactNode; hint?: ReactNode; error?: string; required?: boolean; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      {label ? (
        <span className="label">
          {label}
          {required ? <span className="text-critical"> *</span> : null}
        </span>
      ) : null}
      {children}
      {error ? <p className="mt-1 text-xs text-critical">{error}</p> : hint ? <p className="hint">{hint}</p> : null}
    </div>
  )
}

interface TextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode
  hint?: ReactNode
  error?: string
  suffix?: ReactNode
}

export function TextInput({ label, hint, error, required, suffix, className = '', ...rest }: TextInputProps) {
  const id = useId()
  return (
    <Field label={label ? <label htmlFor={id}>{label}</label> : undefined} hint={hint} error={error} required={required}>
      <div className="relative">
        <input id={id} aria-invalid={error ? true : undefined} className={`input ${error ? 'border-critical' : ''} ${suffix ? 'pr-12' : ''} ${className}`} {...rest} />
        {suffix ? <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-subtle">{suffix}</span> : null}
      </div>
    </Field>
  )
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode
  hint?: ReactNode
  error?: string
  options: { value: string; label: string; disabled?: boolean }[]
  placeholder?: string
}

export function Select({ label, hint, error, required, options, placeholder, className = '', ...rest }: SelectProps) {
  const id = useId()
  return (
    <Field label={label ? <label htmlFor={id}>{label}</label> : undefined} hint={hint} error={error} required={required}>
      <select id={id} aria-invalid={error ? true : undefined} className={`input appearance-none pr-8 ${error ? 'border-critical' : ''} ${className}`} {...rest}>
        {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  )
}

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode
  hint?: ReactNode
  error?: string
}

export function TextArea({ label, hint, error, className = '', ...rest }: TextAreaProps) {
  const id = useId()
  return (
    <Field label={label ? <label htmlFor={id}>{label}</label> : undefined} hint={hint} error={error}>
      <textarea id={id} rows={3} className={`input resize-y ${error ? 'border-critical' : ''} ${className}`} {...rest} />
    </Field>
  )
}

export function Checkbox({ label, hint, checked, onChange, disabled }: { label: ReactNode; hint?: ReactNode; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  const id = useId()
  return (
    <div>
      <div className="flex items-start gap-2">
        <input id={id} type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 size-4 shrink-0 rounded border-line accent-[var(--brand)]" />
        <label htmlFor={id} className="select-none text-sm text-content">
          {label}
        </label>
      </div>
      {hint ? <p className="hint ml-6">{hint}</p> : null}
    </div>
  )
}

/** 小型開關（列表列的啟用切換） */
export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (value: boolean) => void; label?: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${checked ? 'bg-brand' : 'bg-line-strong'}`}
    >
      <span className={`inline-block size-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : 'translate-x-0.5'}`} />
    </button>
  )
}

export function SegmentedControl<T extends string>({ value, options, onChange, size = 'md', className = '' }: { value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (value: T) => void; size?: 'sm' | 'md'; className?: string }) {
  const padding = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm'
  return (
    <div role="group" className={`inline-flex rounded-md border border-line bg-surface p-0.5 ${className}`}>
      {options.map((option) => {
        const active = option.value === value
        return (
          <button key={option.value} type="button" title={option.title} aria-pressed={active} onClick={() => onChange(option.value)} className={`rounded-md font-medium transition-colors ${padding} ${active ? 'bg-brand-soft text-brand' : 'text-muted hover:bg-surface-muted hover:text-content'}`}>
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
