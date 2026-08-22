import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Building2, Check, ChevronDown, ChevronRight, Factory, Layers, Search, X } from 'lucide-react'

import type { SiteKind, SiteSummary } from '@/lib/types'
import { Field } from './Field'

const KIND_ICON: Record<SiteKind, typeof Building2> = {
  site: Building2,
  area: Factory,
  line: Layers,
  group: Layers,
}

/**
 * Sentinel for "devices belonging to no site at all".
 *
 * A real value rather than an empty string, because empty already means "no
 * filter" - and the two are genuinely different questions.
 */
export const UNASSIGNED = '__unassigned__'

interface TreeNode {
  site: SiteSummary
  children: TreeNode[]
}

/** Nest a flat site list, keeping anything whose parent is missing at the top. */
function buildTree(sites: SiteSummary[]): TreeNode[] {
  const nodes = new Map<string, TreeNode>()
  sites.forEach((site) => nodes.set(site.id, { site, children: [] }))

  const roots: TreeNode[] = []
  nodes.forEach((node) => {
    const parent = node.site.parent_id ? nodes.get(node.site.parent_id) : undefined
    if (parent) parent.children.push(node)
    else roots.push(node)
  })
  return roots
}

/** Every id on the path from a node up to its root, the node included. */
function ancestryOf(sites: SiteSummary[], id: string): string[] {
  const byId = new Map(sites.map((site) => [site.id, site]))
  const chain: string[] = []
  const seen = new Set<string>()
  let current = byId.get(id)
  while (current && !seen.has(current.id)) {
    chain.push(current.id)
    seen.add(current.id)
    current = current.parent_id ? byId.get(current.parent_id) : undefined
  }
  return chain
}

export interface SiteTreeSelectProps {
  sites: SiteSummary[]
  /** Selected site id, `UNASSIGNED`, or '' for none. */
  value: string
  onChange: (value: string) => void
  label?: ReactNode
  hint?: ReactNode
  error?: string
  required?: boolean
  /** Shown when nothing is selected. */
  placeholder?: string
  /** Offer an "unassigned" row. Filters want it; an assignment picker does not. */
  allowUnassigned?: boolean
  /** Offer a row that clears the selection. */
  allowClear?: boolean
  disabled?: boolean
  className?: string
}

/**
 * A site picker that keeps the tree visible.
 *
 * A flat `<select>` with indentation loses the shape the moment the list is
 * long enough to scroll, which is exactly when the shape matters: "Line 3"
 * means nothing without the plant above it. This renders the real hierarchy,
 * collapsible, with a filter that keeps a match's ancestors on screen so a
 * result is never shown floating without its context.
 *
 * The value is still a plain site id, so callers are unchanged apart from the
 * element they render.
 */
export function SiteTreeSelect({
  sites,
  value,
  onChange,
  label,
  hint,
  error,
  required,
  placeholder,
  allowUnassigned = false,
  allowClear = false,
  disabled = false,
  className = '',
}: SiteTreeSelectProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const container = useRef<HTMLDivElement>(null)

  const tree = useMemo(() => buildTree(sites), [sites])
  const selected = sites.find((site) => site.id === value)

  // Close on an outside click or Escape - a popover that traps the pointer is
  // worse than a plain select, not better.
  useEffect(() => {
    if (!open) return
    function onPointerDown(event: MouseEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  /**
   * Ids to render while filtering: each match plus its ancestors.
   *
   * Without the ancestors a match would appear at the top level, which is a
   * lie about where the equipment is.
   */
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return null

    const matched = sites.filter(
      (site) =>
        site.name.toLowerCase().includes(needle) ||
        site.code.toLowerCase().includes(needle),
    )
    const keep = new Set<string>()
    matched.forEach((site) => ancestryOf(sites, site.id).forEach((id) => keep.add(id)))
    return keep
  }, [query, sites])

  function toggle(id: string) {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function pick(next: string) {
    onChange(next)
    setOpen(false)
    setQuery('')
  }

  function renderNodes(nodes: TreeNode[], depth: number): ReactNode {
    return nodes.map((node) => {
      if (visible && !visible.has(node.site.id)) return null
      const Icon = KIND_ICON[node.site.kind] ?? Building2
      const hasChildren = node.children.length > 0
      // While filtering, everything on a matching path stays expanded -
      // collapsing a branch the user is actively searching would hide the hit.
      const isCollapsed = !visible && collapsed.has(node.site.id)
      const isSelected = node.site.id === value

      return (
        <li key={node.site.id}>
          <div
            className={`flex items-center gap-1 rounded-md pr-2 text-sm ${
              isSelected ? 'bg-brand-soft text-brand' : 'hover:bg-surface-muted'
            }`}
            style={{ paddingLeft: `${depth * 14 + 4}px` }}
          >
            {hasChildren ? (
              <button
                type="button"
                onClick={() => toggle(node.site.id)}
                className="shrink-0 rounded p-0.5 text-subtle hover:text-content"
                aria-label={isCollapsed ? t('common.expand') : t('common.collapse')}
              >
                {isCollapsed ? (
                  <ChevronRight className="size-3.5" />
                ) : (
                  <ChevronDown className="size-3.5" />
                )}
              </button>
            ) : (
              <span className="w-[1.375rem] shrink-0" aria-hidden />
            )}
            <button
              type="button"
              onClick={() => pick(node.site.id)}
              className="flex min-w-0 flex-1 items-center gap-1.5 py-1.5 text-left"
            >
              <Icon className="size-3.5 shrink-0 text-subtle" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{node.site.name}</span>
              {node.site.total_device_count > 0 ? (
                <span className="shrink-0 tnum text-[11px] text-subtle">
                  {node.site.total_device_count}
                </span>
              ) : null}
              {isSelected ? <Check className="size-3.5 shrink-0" aria-hidden /> : null}
            </button>
          </div>
          {hasChildren && !isCollapsed ? (
            <ul>{renderNodes(node.children, depth + 1)}</ul>
          ) : null}
        </li>
      )
    })
  }

  const buttonLabel =
    value === UNASSIGNED
      ? t('sites.unassigned')
      : selected
        ? selected.name
        : placeholder ?? t('common.all')

  return (
    <Field
      label={label}
      hint={hint}
      error={error}
      required={required}
      className={className}
    >
      <div className="relative" ref={container}>
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((current) => !current)}
          aria-haspopup="listbox"
          aria-expanded={open}
          className={`input flex items-center gap-2 text-left ${
            error ? 'border-critical' : ''
          } ${!selected && value !== UNASSIGNED ? 'text-muted' : ''}`}
        >
          <span className="min-w-0 flex-1 truncate">{buttonLabel}</span>
          <ChevronDown className="size-4 shrink-0 text-subtle" aria-hidden />
        </button>

        {open ? (
          <div className="absolute left-0 z-30 mt-1 max-h-80 w-full min-w-56 overflow-hidden rounded-lg border border-line bg-surface shadow-lg">
            <div className="flex items-center gap-1.5 border-b border-line px-2.5 py-2">
              <Search className="size-3.5 shrink-0 text-subtle" aria-hidden />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t('sites.searchPlaceholder')}
                className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-subtle"
              />
              {query ? (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  className="shrink-0 text-subtle hover:text-content"
                  aria-label={t('common.clear')}
                >
                  <X className="size-3.5" />
                </button>
              ) : null}
            </div>

            <div className="max-h-64 overflow-y-auto p-1">
              {allowClear ? (
                <button
                  type="button"
                  onClick={() => pick('')}
                  className="flex w-full items-center rounded-md px-2 py-1.5 text-left text-sm text-muted hover:bg-surface-muted"
                >
                  {placeholder ?? t('common.all')}
                </button>
              ) : null}
              {allowUnassigned ? (
                <button
                  type="button"
                  onClick={() => pick(UNASSIGNED)}
                  className={`flex w-full items-center rounded-md px-2 py-1.5 text-left text-sm italic ${
                    value === UNASSIGNED
                      ? 'bg-brand-soft text-brand'
                      : 'text-muted hover:bg-surface-muted'
                  }`}
                >
                  {t('sites.unassigned')}
                </button>
              ) : null}

              {sites.length === 0 ? (
                <p className="px-2 py-3 text-sm text-muted">{t('sites.noSites')}</p>
              ) : (
                <ul>{renderNodes(tree, 0)}</ul>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </Field>
  )
}
