/**
 * 觸發規則表：設備做了什麼 → 平台做什麼（後端 `apps/comm/rules.py`）。
 *
 * 兩個地方用同一張表：連線的規則（`source="value"`，讀位址，存在 `config.triggers`）與
 * 站台的接收規則（`source="text"`，TCP 指令埠收到不是指令的一行時比對，存在 /vision/integration/rules）。
 * 這個元件只管編輯與呈現；正規化（丟掉壞掉的列）由後端 `rules.sanitize` 負責。
 */
import { useTranslation } from 'react-i18next'
import { ListPlus, Trash2 } from 'lucide-react'

import { Button, Checkbox, EmptyState, IconButton, Select, Switch, TextInput } from '@/components/ui'
import { useFlows } from '@/lib/queries'
import type { RuleAction, RuleSource, RuleTextMatch, RuleValueMode, TriggerRule } from '@/lib/types'

const VALUE_MODES: RuleValueMode[] = ['rising', 'falling', 'change', 'nonzero', 'equal', 'not_equal', 'range']
const TEXT_MATCHES: RuleTextMatch[] = ['exact', 'contains', 'prefix', 'regex']
const ACTIONS: RuleAction[] = ['run_flow', 'activate_recipe', 'set_variable', 'lock', 'unlock']
/** 要填比較值的比對方式（其餘看的是變化，不需要數字）。 */
const NEEDS_VALUE: RuleValueMode[] = ['equal', 'not_equal', 'range']

export function emptyRule(source: RuleSource): TriggerRule {
  return {
    id: '', name: '', enabled: true, source,
    address: '', mode: 'rising', value: 0, value2: 0,
    match: 'contains', pattern: '', capture: '',
    action: 'run_flow', flow: '', recipe: '', variable: '', scope: 'flow', set_value: '', args: {},
    reason: '', ttl: 0, clear: source === 'value', done: '', reply: '',
  }
}

function FlowPicker({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const flows = useFlows()
  const names = (flows.data?.items ?? []).map((f) => f.name)
  const options = [{ value: '', label: '—' }, ...names.map((n) => ({ value: n, label: n }))]
  if (value && !names.includes(value)) options.push({ value, label: value })
  return <Select label={label} value={value} onChange={(e) => onChange(e.target.value)} options={options} />
}

function RuleRow({ rule, index, onChange, onRemove, readOnly }: {
  rule: TriggerRule
  index: number
  onChange: (rule: TriggerRule) => void
  onRemove: () => void
  readOnly: boolean
}) {
  const { t } = useTranslation()
  const set = (patch: Partial<TriggerRule>) => onChange({ ...rule, ...patch })
  const grid = 'grid gap-3 sm:grid-cols-2 lg:grid-cols-3'
  return (
    <div className="rounded-lg border border-line p-3" data-testid={`rule-${index}`}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Switch checked={rule.enabled} disabled={readOnly} onChange={(v) => set({ enabled: v })} />
        <TextInput className="flex-1 basis-48" placeholder={t('integration.rules.namePlaceholder')} value={rule.name} disabled={readOnly} onChange={(e) => set({ name: e.target.value })} />
        <IconButton label={t('common.delete')} disabled={readOnly} onClick={onRemove}><Trash2 size={15} className="text-critical" /></IconButton>
      </div>

      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">{t('integration.rules.when')}</p>
      <div className={grid}>
        {rule.source === 'value' ? (
          <>
            <TextInput label={t('integration.rules.address')} hint={t('integration.rules.addressHint')} className="font-mono" value={rule.address} disabled={readOnly} onChange={(e) => set({ address: e.target.value })} />
            <Select label={t('integration.rules.mode')} value={rule.mode} disabled={readOnly} onChange={(e) => set({ mode: e.target.value as RuleValueMode })} options={VALUE_MODES.map((m) => ({ value: m, label: t(`integration.rules.modes.${m}`) }))} />
            {NEEDS_VALUE.includes(rule.mode) ? (
              <div className="flex gap-2">
                <TextInput label={t('integration.rules.value')} type="number" value={String(rule.value)} disabled={readOnly} onChange={(e) => set({ value: Number(e.target.value) })} />
                {rule.mode === 'range' ? <TextInput label={t('integration.rules.value2')} type="number" value={String(rule.value2)} disabled={readOnly} onChange={(e) => set({ value2: Number(e.target.value) })} /> : null}
              </div>
            ) : null}
          </>
        ) : (
          <>
            <Select label={t('integration.rules.match')} value={rule.match} disabled={readOnly} onChange={(e) => set({ match: e.target.value as RuleTextMatch })} options={TEXT_MATCHES.map((m) => ({ value: m, label: t(`integration.rules.matches.${m}`) }))} />
            <TextInput label={t('integration.rules.pattern')} hint={t('integration.rules.patternHint')} className="font-mono" value={rule.pattern} disabled={readOnly} onChange={(e) => set({ pattern: e.target.value })} />
            <TextInput label={t('integration.rules.capture')} hint={t('integration.rules.captureHint')} className="font-mono" value={rule.capture} disabled={readOnly} onChange={(e) => set({ capture: e.target.value })} />
          </>
        )}
      </div>

      <p className="mb-2 mt-4 text-xs font-medium uppercase tracking-wide text-muted">{t('integration.rules.then')}</p>
      <div className={grid}>
        <Select label={t('integration.rules.action')} value={rule.action} disabled={readOnly} onChange={(e) => set({ action: e.target.value as RuleAction })} options={ACTIONS.map((a) => ({ value: a, label: t(`integration.rules.actions.${a}`) }))} />
        {rule.action === 'run_flow' || rule.action === 'activate_recipe' || (rule.action === 'set_variable' && rule.scope === 'flow') ? (
          <FlowPicker label={t('integration.rules.flow')} value={rule.flow} onChange={(v) => set({ flow: v })} />
        ) : null}
        {rule.action === 'activate_recipe' ? (
          <TextInput label={t('integration.rules.recipe')} hint={t('integration.rules.recipeHint')} value={rule.recipe} disabled={readOnly} onChange={(e) => set({ recipe: e.target.value })} />
        ) : null}
        {rule.action === 'set_variable' ? (
          <>
            <Select label={t('integration.rules.scope')} value={rule.scope} disabled={readOnly} onChange={(e) => set({ scope: e.target.value as 'flow' | 'station' })} options={[{ value: 'flow', label: t('variables.scope.flow') }, { value: 'station', label: t('variables.scope.station') }]} />
            <TextInput label={t('integration.rules.variable')} className="font-mono" value={rule.variable} disabled={readOnly} onChange={(e) => set({ variable: e.target.value })} />
            <TextInput label={t('integration.rules.setValue')} hint={t('integration.rules.setValueHint')} className="font-mono" value={rule.set_value} disabled={readOnly} onChange={(e) => set({ set_value: e.target.value })} />
          </>
        ) : null}
        {rule.action === 'lock' ? (
          <>
            <TextInput label={t('integration.rules.reason')} value={rule.reason} disabled={readOnly} onChange={(e) => set({ reason: e.target.value })} />
            <TextInput label={t('integration.rules.ttl')} hint={t('integration.rules.ttlHint')} type="number" value={String(rule.ttl)} disabled={readOnly} onChange={(e) => set({ ttl: Number(e.target.value) })} />
          </>
        ) : null}
        {rule.action === 'run_flow' ? (
          <TextInput label={t('integration.rules.ruleRecipe')} hint={t('integration.rules.ruleRecipeHint')} value={rule.recipe} disabled={readOnly} onChange={(e) => set({ recipe: e.target.value })} />
        ) : null}
      </div>

      {rule.source === 'value' ? (
        <div className={`${grid} mt-3 items-end`}>
          <Checkbox label={t('integration.rules.clear')} checked={rule.clear} disabled={readOnly} onChange={(v) => set({ clear: v })} />
          <TextInput label={t('integration.rules.done')} hint={t('integration.rules.doneHint')} className="font-mono" value={rule.done} disabled={readOnly} onChange={(e) => set({ done: e.target.value })} />
        </div>
      ) : (
        <div className="mt-3">
          <TextInput label={t('integration.rules.reply')} hint={t('integration.rules.replyHint')} className="font-mono" value={rule.reply} disabled={readOnly} onChange={(e) => set({ reply: e.target.value })} />
        </div>
      )}
    </div>
  )
}

export function RuleTable({ rules, source, onChange, readOnly = false }: {
  rules: TriggerRule[]
  source: RuleSource
  onChange: (rules: TriggerRule[]) => void
  readOnly?: boolean
}) {
  const { t } = useTranslation()
  const replace = (index: number, rule: TriggerRule) => onChange(rules.map((r, i) => (i === index ? rule : r)))
  return (
    <div className="space-y-3">
      {rules.length === 0 ? (
        <EmptyState icon={<ListPlus className="size-5" />} title={t('integration.rules.empty')} description={t(`integration.rules.emptyHint.${source}`)} />
      ) : (
        rules.map((rule, i) => (
          <RuleRow key={rule.id || i} rule={rule} index={i} readOnly={readOnly} onChange={(r) => replace(i, r)} onRemove={() => onChange(rules.filter((_, j) => j !== i))} />
        ))
      )}
      <Button icon={<ListPlus size={15} />} disabled={readOnly} onClick={() => onChange([...rules, emptyRule(source)])} data-testid="rule-add">{t('integration.rules.add')}</Button>
    </div>
  )
}
