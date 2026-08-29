import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle'
type Size = 'xs' | 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-brand text-on-brand hover:bg-brand-strong border border-transparent',
  secondary: 'bg-surface text-content border border-line hover:bg-surface-muted',
  ghost: 'bg-transparent text-muted hover:text-content hover:bg-surface-muted border border-transparent',
  danger: 'bg-critical text-white hover:opacity-90 border border-transparent',
  subtle: 'bg-surface-muted text-content border border-transparent hover:bg-line',
}

const SIZES: Record<Size, string> = {
  xs: 'h-7 px-2 text-xs gap-1',
  sm: 'h-8 px-2.5 text-xs gap-1.5',
  md: 'h-9 px-3.5 text-sm gap-2',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
  /** 切換型按鈕的按下狀態 */
  active?: boolean
}

export function Button({ variant = 'secondary', size = 'md', loading = false, icon, active, className = '', children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      aria-pressed={active}
      className={`inline-flex items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors
        disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]}
        ${active ? '!border-brand !bg-brand-soft !text-brand' : ''} ${className}`}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  )
}

/** 純圖示按鈕；label 同時是 title 與無障礙名稱。 */
export function IconButton({ label, variant = 'ghost', size = 'md', className = '', children, active, ...rest }: Omit<ButtonProps, 'children'> & { label: string; children: ReactNode }) {
  const dim = size === 'md' ? 'size-8' : 'size-7'
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={`inline-flex ${dim} items-center justify-center rounded-md transition-colors disabled:cursor-not-allowed disabled:opacity-50
        ${VARIANTS[variant]} ${active ? '!bg-brand-soft !text-brand' : ''} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}
