import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from './Button'

// Tailwind scans for literal class strings, so `text-${align}` would never
// emit the utility. Map to real class names instead.
const ALIGN = {
  left: 'text-left',
  right: 'text-right',
  center: 'text-center',
} as const

export function Table({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    // Wide tables scroll inside their own box rather than the page body.
    <div className={`overflow-x-auto ${className}`}>
      <table className="w-full border-collapse">{children}</table>
    </div>
  )
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead className="border-b border-line bg-surface-muted/60">
      <tr>{children}</tr>
    </thead>
  )
}

export function Th({
  children,
  align = 'left',
  className = '',
}: {
  children?: ReactNode
  align?: 'left' | 'right' | 'center'
  className?: string
}) {
  return (
    <th scope="col" className={`table-header ${ALIGN[align]} ${className}`}>
      {children}
    </th>
  )
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-line">{children}</tbody>
}

export function Tr({
  children,
  onClick,
  className = '',
}: {
  children: ReactNode
  onClick?: () => void
  className?: string
}) {
  return (
    <tr
      onClick={onClick}
      className={`${onClick ? 'cursor-pointer hover:bg-surface-muted/70' : ''} ${className}`}
    >
      {children}
    </tr>
  )
}

export function Td({
  children,
  align = 'left',
  className = '',
  colSpan,
  onClick,
}: {
  children?: ReactNode
  align?: 'left' | 'right' | 'center'
  className?: string
  colSpan?: number
  onClick?: () => void
}) {
  return (
    <td
      colSpan={colSpan}
      onClick={onClick}
      className={`table-cell ${ALIGN[align]} ${className}`}
    >
      {children}
    </td>
  )
}

export function EmptyRow({ colSpan, message }: { colSpan: number; message: ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-10 text-center text-sm text-muted">
        {message}
      </td>
    </tr>
  )
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
}) {
  const { t } = useTranslation()
  if (total <= limit) return null

  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + limit, total)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-2.5">
      <p className="text-xs text-muted tnum">{t('common.showing', { from, to, total })}</p>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          {t('common.previous')}
        </Button>
        <Button size="sm" disabled={to >= total} onClick={() => onChange(offset + limit)}>
          {t('common.next')}
        </Button>
      </div>
    </div>
  )
}
