/**
 * 面板（Gentelella x_panel）：白底、細邊框、頂部標題列（x_title）＋右側動作圖示，可摺疊。
 * Card = 面板外框；CardHeader = 標題列（給 collapsible 就有摺疊鈕，內容摺疊由 Panel 統一處理）。
 */
import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

export function Card({ className = '', children, testId }: { className?: string; children: ReactNode; testId?: string }) {
  return <section className={`card ${className}`} data-testid={testId}>{children}</section>
}

export function CardHeader({ title, description, actions, className = '', collapsed, onToggle }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string; collapsed?: boolean; onToggle?: () => void }) {
  return (
    <header className={`panel-title ${className}`}>
      <div className="min-w-0 flex-1 basis-32">
        <h2 className="truncate">{title}</h2>
        {description ? <p className="mt-0.5 text-xs text-muted">{description}</p> : null}
      </div>
      {actions || onToggle ? (
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {actions}
          {onToggle ? (
            <button type="button" className="btn-icon" onClick={onToggle} aria-expanded={!collapsed} aria-label={collapsed ? 'expand' : 'collapse'} data-testid="panel-toggle">
              {collapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
            </button>
          ) : null}
        </div>
      ) : null}
    </header>
  )
}

export function CardBody({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`p-4 ${className}`}>{children}</div>
}

/** 可摺疊面板：標題列＋內容，一行搞定。 */
export function Panel({ title, description, actions, children, className = '', bodyClassName = '', defaultCollapsed = false, collapsible = true, testId }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string; defaultCollapsed?: boolean; collapsible?: boolean; testId?: string }) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  return (
    <Card className={className} testId={testId}>
      <CardHeader title={title} description={description} actions={actions} collapsed={collapsed} onToggle={collapsible ? () => setCollapsed((v) => !v) : undefined} />
      {collapsed ? null : <div className={bodyClassName} data-testid={testId ? `${testId}-body` : undefined}>{children}</div>}
    </Card>
  )
}

/** 統計 tile_count：大數字＋小標。 */
export function Tile({ label, value, unit, tone = '', className = '' }: { label: ReactNode; value: ReactNode; unit?: ReactNode; tone?: string; className?: string }) {
  return (
    <div className={`tile-count ${className}`}>
      <p className="tile-label">{label}</p>
      <p className={`tile-value ${tone}`}>
        {value}
        {unit ? <span className="tile-unit">{unit}</span> : null}
      </p>
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
      {/* basis-60：標題至少 240px 才跟動作同列，否則動作換到下一列（避免標題被擠成一字一行） */}
      <div className="min-w-0 flex-1 basis-60">
        <h1 className="text-[22px] font-normal leading-tight text-heading">{title}</h1>
        {description ? <p className="mt-1 text-[13px] text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function DetailRow({ label, children, mono = false }: { label: ReactNode; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <dt className="shrink-0 text-xs text-muted">{label}</dt>
      <dd className={`min-w-0 break-all text-right text-sm text-content ${mono ? 'font-mono text-xs' : ''}`}>{children}</dd>
    </div>
  )
}
