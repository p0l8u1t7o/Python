/** 群組篩選 chips（影像來源庫／資產庫共用）：全部｜各群組（含數量）｜未分組。
 *  群組是自由文字（items 的 group 欄位），這裡只負責彙整與篩選，不管理群組清單本身。 */
import { useTranslation } from 'react-i18next'

export const GROUP_ALL = '__all__'
export const GROUP_NONE = '__none__'

export function groupNames(items: { group: string }[]): string[] {
  return [...new Set(items.map((i) => i.group).filter(Boolean))].sort((a, b) => a.localeCompare(b))
}

export function matchGroup(item: { group: string }, filter: string): boolean {
  if (filter === GROUP_ALL) return true
  if (filter === GROUP_NONE) return !item.group
  return item.group === filter
}

export function GroupChips({ items, value, onChange }: {
  items: { group: string }[]
  value: string
  onChange: (value: string) => void
}) {
  const { t } = useTranslation()
  const names = groupNames(items)
  if (!names.length) return null // 還沒有任何群組：不顯示篩選列
  const ungrouped = items.filter((i) => !i.group).length
  const chip = (key: string, label: string, count: number) => (
    <button key={key} type="button" onClick={() => onChange(key)} aria-pressed={value === key}
      className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors
        ${value === key ? 'border-transparent bg-brand text-on-brand' : 'border-line text-content hover:bg-surface-muted'}`}>
      {label}
      <span className={`tnum ${value === key ? 'opacity-80' : 'text-muted'}`}>{count}</span>
    </button>
  )
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5" data-testid="group-chips">
      {chip(GROUP_ALL, t('common.groupAll'), items.length)}
      {names.map((name) => chip(name, name, items.filter((i) => i.group === name).length))}
      {ungrouped ? chip(GROUP_NONE, t('common.ungrouped'), ungrouped) : null}
    </div>
  )
}

/** 群組輸入框＋既有群組建議（datalist）。 */
export function GroupInput({ value, onChange, suggestions, label }: {
  value: string
  onChange: (value: string) => void
  suggestions: string[]
  label: string
}) {
  const listId = `group-suggest-${label.replace(/\W/g, '')}`
  return (
    <div>
      <label className="label">{label}</label>
      <input className="input" list={listId} value={value} onChange={(e) => onChange(e.target.value)} maxLength={60} />
      <datalist id={listId}>
        {suggestions.map((name) => <option key={name} value={name} />)}
      </datalist>
    </div>
  )
}

/** 群組下拉（項目編輯用）：從已建立的群組選（含「未分組」）；群組本身在 GroupManager 管理。 */
export function GroupSelect({ value, onChange, groups, label }: {
  value: string
  onChange: (value: string) => void
  groups: { name: string }[]
  label: string
}) {
  const { t } = useTranslation()
  const names = groups.map((g) => g.name)
  const options = [
    { value: '', label: t('common.ungrouped') },
    // 值不在清單裡（舊資料）也要顯示，不然 select 會靜默落到第一項
    ...(value && !names.includes(value) ? [{ value, label: value }] : []),
    ...names.map((name) => ({ value: name, label: name })),
  ]
  return (
    <div>
      <label className="label">{label}</label>
      <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}
