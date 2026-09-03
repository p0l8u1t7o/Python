/**
 * 程式碼參數（Param.kind = code）：等寬字、行號、Tab 縮排兩格、隨內容長高（外層參數欄捲動，行號與內容不用同步捲）。
 * 沒有管理員權限時唯讀（Python 腳本只有管理員能編輯）。
 */
import { useId } from 'react'

import { Field } from '@/components/ui'

export function CodeField({ label, hint, value, onChange, readOnly = false, readOnlyHint, language = 'python' }: {
  label: string
  hint?: string
  value: string
  onChange: (value: string) => void
  readOnly?: boolean
  readOnlyHint?: string
  language?: string
}) {
  const id = useId()
  const lines = Math.max(1, value.split('\n').length)
  const rows = Math.max(14, lines + 1)
  return (
    <Field label={<label htmlFor={id}>{label}</label>} hint={readOnly ? readOnlyHint ?? hint : hint}>
      <div className={`flex overflow-hidden rounded-md border bg-surface font-mono text-xs ${readOnly ? 'border-line opacity-90' : 'border-line focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20'}`} data-testid="code-field" data-language={language}>
        <pre aria-hidden className="tnum m-0 select-none border-r border-line bg-surface-muted/60 px-2 py-2 text-right leading-5 text-subtle">
          {Array.from({ length: rows }, (_, i) => i + 1).join('\n')}
        </pre>
        <textarea
          id={id}
          value={value}
          rows={rows}
          readOnly={readOnly}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          wrap="off"
          className="min-w-0 flex-1 resize-none bg-transparent px-3 py-2 leading-5 text-content outline-none"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== 'Tab' || readOnly) return
            e.preventDefault()
            const el = e.currentTarget
            const start = el.selectionStart
            const end = el.selectionEnd
            onChange(`${value.slice(0, start)}  ${value.slice(end)}`)
            requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = start + 2 })
          }}
        />
      </div>
    </Field>
  )
}
