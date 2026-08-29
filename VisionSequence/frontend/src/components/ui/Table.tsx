import type { ReactNode } from 'react'

const ALIGN = { left: 'text-left', right: 'text-right', center: 'text-center' } as const
type Align = keyof typeof ALIGN

export function Table({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`overflow-x-auto ${className}`}>
      <table className="w-full border-collapse">{children}</table>
    </div>
  )
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead className="border-b-2 border-line bg-surface">
      <tr>{children}</tr>
    </thead>
  )
}

export function Th({ children, align = 'left', className = '' }: { children?: ReactNode; align?: Align; className?: string }) {
  return <th scope="col" className={`table-header ${ALIGN[align]} ${className}`}>{children}</th>
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-line">{children}</tbody>
}

export function Tr({ children, onClick, className = '', selected = false }: { children: ReactNode; onClick?: () => void; className?: string; selected?: boolean }) {
  return (
    <tr onClick={onClick} className={`${onClick ? 'cursor-pointer hover:bg-surface-muted/70' : ''} ${selected ? 'bg-brand-soft/50' : ''} ${className}`}>
      {children}
    </tr>
  )
}

export function Td({ children, align = 'left', className = '', colSpan }: { children?: ReactNode; align?: Align; className?: string; colSpan?: number }) {
  return <td colSpan={colSpan} className={`table-cell ${ALIGN[align]} ${className}`}>{children}</td>
}

export function EmptyRow({ colSpan, message }: { colSpan: number; message: ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-8 text-center text-sm text-muted">{message}</td>
    </tr>
  )
}
