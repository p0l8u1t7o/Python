import type { ReactNode } from 'react'

export function Card({
  className = '',
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return <section className={`card ${className}`}>{children}</section>
}

export function CardHeader({
  title,
  description,
  actions,
  className = '',
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <header
      className={`flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3 ${className}`}
    >
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-content">{title}</h2>
        {description ? <p className="mt-0.5 text-xs text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  )
}

export function CardBody({
  className = '',
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return <div className={`p-4 ${className}`}>{children}</div>
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-content">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

/** Label/value row used throughout detail panels. */
export function DetailRow({
  label,
  children,
  mono = false,
}: {
  label: ReactNode
  children: ReactNode
  mono?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="shrink-0 text-xs text-muted">{label}</dt>
      <dd
        className={`min-w-0 truncate text-right text-sm text-content ${mono ? 'font-mono text-xs' : ''}`}
      >
        {children}
      </dd>
    </div>
  )
}
