/**
 * 儲存範圍 Check List（RecipeCheckList）：`POST /recipes/check` 或 `import/check` 回來的 items 以清單呈現
 * 「步驟 › 參數：目前值 → 新值」＋狀態，使用者勾選要納入的項目。
 *  - ok：綠、預設勾；unchanged：灰、預設不勾但可勾；version_changed：黃、可勾；
 *  - node_missing／type_changed／param_missing／value_invalid：紅、不可勾。
 * CheckItemsTable 是純呈現＋勾選；RecipeCheckListModal 包成 Modal 給「新增／儲存配方」用，分兩區：
 *  - 上方「教導參數」：teach=true（或使用者明確改過／有問題的項目），ok 預設勾、unchanged 不勾；
 *  - 下方摺疊區「其他參數（N）」：teach=false 且與圖相同的項目（`include_all` 補列的），預設收合、不勾，展開後可勾。
 *  ROI 類值（kind=roi）顯示摘要，例如「rect 286×215 @ 373,277」。
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowRight, ChevronDown, ChevronRight } from 'lucide-react'

import { formatValue } from '@/components/editor/ResultsPanel'
import { Badge, Button, Modal, type Tone } from '@/components/ui'
import { RECIPE_ACCEPTABLE, type RecipeCheckItem, type RecipeCheckStatus } from '@/lib/types'

const STATUS_TONE: Record<RecipeCheckStatus, Tone> = {
  ok: 'ok',
  unchanged: 'neutral',
  version_changed: 'warning',
  node_missing: 'critical',
  type_changed: 'critical',
  param_missing: 'critical',
  value_invalid: 'critical',
}

export function acceptable(item: RecipeCheckItem): boolean {
  return RECIPE_ACCEPTABLE.has(item.status)
}

/** 預設勾選：ok（unchanged／version_changed 可勾但預設不勾）。 */
export function defaultSelection(items: RecipeCheckItem[]): Set<string> {
  return new Set(items.filter((it) => it.status === 'ok').map((it) => it.key))
}

/** 「其他參數」區：非教導參數且與圖相同（使用者明確改過或有問題的項目一律留在上方，不會被摺疊藏起來）。 */
export function isOtherParam(item: RecipeCheckItem): boolean {
  return item.teach === false && item.status === 'unchanged'
}

/** ROI 類值的摘要：rect 286×215 @ 373,277、circle r=40 @ 100,100、polygon 5 點… */
export function roiSummary(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null
  const v = value as Record<string, unknown>
  const n = (k: string) => Math.round(Number(v[k] ?? 0))
  switch (v.shape) {
    case 'rect':
      return `rect ${n('w')}×${n('h')} @ ${n('x')},${n('y')}`
    case 'rotated_rect':
      return `rotated_rect ${n('w')}×${n('h')} @ ${n('cx')},${n('cy')} ∠${n('angle')}°`
    case 'circle':
      return `circle r=${n('r')} @ ${n('cx')},${n('cy')}`
    case 'annulus':
      return `annulus r=${n('r_inner')}–${n('r_outer')} @ ${n('cx')},${n('cy')}`
    case 'polygon':
      return `polygon ${Array.isArray(v.points) ? v.points.length : 0} pts`
    case 'line':
      return `line ${n('x1')},${n('y1')} → ${n('x2')},${n('y2')}`
    default:
      return typeof v.shape === 'string' ? String(v.shape) : null
  }
}

export function checkValueText(item: RecipeCheckItem, value: unknown): string {
  if (value === undefined) return '—'
  if (item.kind === 'roi') return roiSummary(value) ?? formatValue(value)
  return formatValue(value)
}

export function CheckStatusBadge({ status }: { status: RecipeCheckStatus }) {
  const { t } = useTranslation()
  return <Badge tone={STATUS_TONE[status] ?? 'neutral'}>{t(`recipes.status.${status}`, { defaultValue: status })}</Badge>
}

export function CheckItemsTable({ items, selected, onChange, testId = 'check-list' }: { items: RecipeCheckItem[]; selected: Set<string>; onChange: (next: Set<string>) => void; testId?: string }) {
  const { t } = useTranslation()
  const toggle = (key: string) => {
    const next = new Set(selected)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    onChange(next)
  }
  const selectable = items.filter(acceptable)
  const allOn = selectable.length > 0 && selectable.every((it) => selected.has(it.key))
  if (items.length === 0) return <p className="rounded-md border border-dashed border-line px-3 py-4 text-center text-xs text-muted" data-testid={`${testId}-empty`}>{t('recipes.checkEmpty')}</p>
  return (
    <div className="overflow-x-auto rounded-md border border-line" data-testid={testId}>
      <table className="w-full text-xs">
        <thead className="border-b-2 border-line bg-surface">
          <tr>
            <th className="w-8 px-2 py-2">
              <input
                type="checkbox"
                className="accent-[var(--brand)]"
                checked={allOn}
                disabled={selectable.length === 0}
                onChange={() => {
                  // 只影響本表的項目，不動別區的勾選
                  const next = new Set(selected)
                  for (const it of selectable) if (allOn) next.delete(it.key)
                  else next.add(it.key)
                  onChange(next)
                }}
                aria-label={t('recipes.selectAll')}
                data-testid={`${testId}-all`}
              />
            </th>
            <th className="px-2 py-2 text-left font-semibold text-heading">{t('recipes.colItem')}</th>
            <th className="px-2 py-2 text-left font-semibold text-heading">{t('recipes.colChange')}</th>
            <th className="px-2 py-2 text-left font-semibold text-heading">{t('recipes.colStatus')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.map((it) => {
            const can = acceptable(it)
            const on = can && selected.has(it.key)
            return (
              <tr key={it.key} className={`${can ? 'cursor-pointer hover:bg-surface-muted/60' : 'opacity-80'} ${on ? 'bg-brand-soft/30' : ''}`} onClick={() => can && toggle(it.key)} data-testid="check-item" data-key={it.key} data-status={it.status} data-checked={on ? 'true' : 'false'} data-teach={it.teach === false ? 'false' : 'true'}>
                <td className="px-2 py-1.5 align-top">
                  <input type="checkbox" className="accent-[var(--brand)]" checked={on} disabled={!can} onChange={() => toggle(it.key)} onClick={(e) => e.stopPropagation()} aria-label={it.key} />
                </td>
                <td className="px-2 py-1.5 align-top">
                  <p className="font-medium text-content">{it.node_label || it.node_id} <span className="text-subtle">›</span> {it.param_label || it.param}</p>
                  <p className="font-mono text-[10px] text-subtle">{it.key}{it.tool_label ? <span className="ml-1 font-sans">· {it.tool_label}</span> : null}</p>
                </td>
                <td className="px-2 py-1.5 align-top font-mono">
                  <span className="text-muted">{checkValueText(it, it.current)}</span>
                  <ArrowRight size={11} className="mx-1 inline text-subtle" aria-hidden />
                  <span className="text-content">{checkValueText(it, it.value)}</span>
                </td>
                <td className="px-2 py-1.5 align-top">
                  <CheckStatusBadge status={it.status} />
                  {it.message ? <p className="mt-0.5 text-[10px] text-muted">{it.message}</p> : null}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function RecipeCheckListModal({ open, onClose, title, description, items, loading = false, submitting = false, confirmLabel, onConfirm, extra }: { open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; items: RecipeCheckItem[]; loading?: boolean; submitting?: boolean; confirmLabel: string; onConfirm: (keys: string[]) => void; extra?: ReactNode }) {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<Set<string>>(() => defaultSelection(items))
  const [othersOpen, setOthersOpen] = useState(false)
  useEffect(() => {
    if (open) {
      setSelected(defaultSelection(items))
      setOthersOpen(false)
    }
  }, [open, items])
  const teachItems = useMemo(() => items.filter((it) => !isOtherParam(it)), [items])
  const otherItems = useMemo(() => items.filter(isOtherParam), [items])
  const teachTotal = useMemo(() => teachItems.filter(acceptable).length, [teachItems])
  const teachSelected = useMemo(() => teachItems.filter((it) => selected.has(it.key)).length, [teachItems, selected])
  const otherSelected = selected.size - teachSelected
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={description ?? t('recipes.checkHint')}
      size="lg"
      footer={
        <>
          <span className="mr-auto tnum text-xs text-muted" data-testid="check-count">
            {t('recipes.selectedCount', { count: teachSelected, total: teachTotal })}
            {otherSelected > 0 ? t('recipes.selectedOther', { count: otherSelected }) : null}
          </span>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={submitting} disabled={loading} onClick={() => onConfirm([...selected])} data-testid="check-confirm">{confirmLabel}</Button>
        </>
      }
    >
      {extra}
      {loading ? (
        <p className="py-4 text-center text-xs text-muted">{t('common.loading')}…</p>
      ) : (
        <div className="space-y-3">
          <section data-testid="check-teach">
            <p className="label">{t('recipes.sectionTeach')}</p>
            <CheckItemsTable items={teachItems} selected={selected} onChange={setSelected} />
          </section>
          {otherItems.length > 0 ? (
            <section className="rounded-md border border-line" data-testid="check-others">
              <button type="button" className="flex w-full items-center gap-1 px-2 py-1.5 text-left text-xs font-semibold text-heading hover:bg-surface-muted" onClick={() => setOthersOpen((v) => !v)} aria-expanded={othersOpen} data-testid="check-others-toggle">
                {othersOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                {t('recipes.sectionOther', { count: otherItems.length })}
                <span className="ml-auto font-normal text-muted">{t('recipes.sectionOtherHint')}</span>
              </button>
              {othersOpen ? (
                <div className="border-t border-line p-2">
                  <CheckItemsTable items={otherItems} selected={selected} onChange={setSelected} testId="check-list-others" />
                </div>
              ) : null}
            </section>
          ) : null}
        </div>
      )}
    </Modal>
  )
}
