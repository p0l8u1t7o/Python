import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export interface Tab<T extends string> {
  value: T
  label: string
  icon?: LucideIcon
  badge?: ReactNode
}

/** 簡單的分頁列；面板由呼叫端渲染（本專案分頁內容差異大，不用統一 panel）。 */
export function Tabs<T extends string>({ tabs, value, onChange, className = '', size = 'md' }: { tabs: Tab<T>[]; value: T; onChange: (value: T) => void; className?: string; size?: 'sm' | 'md' }) {
  const pad = size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-3 py-2 text-sm'
  return (
    <div role="tablist" className={`flex gap-1 overflow-x-auto border-b border-line ${className}`}>
      {tabs.map((tab) => {
        const Icon = tab.icon
        const selected = tab.value === value
        return (
          <button key={tab.value} role="tab" type="button" aria-selected={selected} onClick={() => onChange(tab.value)} className={`-mb-px flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 font-medium transition-colors ${pad} ${selected ? 'border-brand text-brand' : 'border-transparent text-muted hover:text-content'}`}>
            {Icon ? <Icon size={14} aria-hidden /> : null}
            {tab.label}
            {tab.badge}
          </button>
        )
      })}
    </div>
  )
}
