/**
 * 結果回送（編輯器設定面板）：這條流程跑完要把結果送給誰、送什麼。存在 Flow.comm，
 * 後端 apps/vision/reporting.py 在每一片跑完時直接送出去（不經佇列，不會漏）。
 *
 * 只列得出「送得出文字」的連線（TCP 文字）；Modbus 是位址對位址的，那種需求在圖裡用
 * 「寫入 Modbus」把值對到位址。
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ListPlus, Save, Trash2 } from 'lucide-react'

import { Button, IconButton, Select, Switch, TextInput } from '@/components/ui'
import { useConnectionKinds, useConnections } from '@/lib/queries'
import type { CommRule } from '@/lib/types'

interface Props {
  config: CommRule[] | undefined
  /** 圖裡的節點（id 與顯示名），給「只在某一步…時送」用 */
  nodes: { id: string; label: string }[]
  readOnly: boolean
  saving: boolean
  onSave: (rules: CommRule[]) => void
}

const NODE_STATUSES = ['any', 'ok', 'ng', 'error', 'skipped'] as const

function emptyRule(connection: string): CommRule {
  return { id: '', name: '', enabled: true, connection, when: 'on_finish', interval_ms: 1000, node: '', node_status: 'any', ok: '{judge},{run_id}', ng: '', failed: '' }
}

export function CommSettings({ config, nodes, readOnly, saving, onSave }: Props) {
  const { t } = useTranslation()
  const connections = useConnections()
  const kinds = useConnectionKinds()
  const [draft, setDraft] = useState<CommRule[]>(config ?? [])
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    setDraft(config ?? [])
    setDirty(false)
  }, [config])

  // 送得出文字的連線種類（後端 Writer.texts）；目前是 TCP 文字與宣告了的外掛
  const textKinds = new Set((kinds.data ?? []).filter((k) => k.section === 'tcp' || k.section === 'plugins').map((k) => k.kind))
  const usable = (connections.data?.items ?? []).filter((c) => textKinds.has(c.kind) && c.kind !== 'tcp_image')
  const names = Array.from(new Set([...usable.map((c) => c.name), ...draft.map((r) => r.connection).filter(Boolean)]))

  const update = (index: number, patch: Partial<CommRule>) => {
    setDraft((rules) => rules.map((r, i) => (i === index ? { ...r, ...patch } : r)))
    setDirty(true)
  }
  const add = () => {
    setDraft((rules) => [...rules, emptyRule(names[0] ?? '')])
    setDirty(true)
  }
  const remove = (index: number) => {
    setDraft((rules) => rules.filter((_, i) => i !== index))
    setDirty(true)
  }

  return (
    <div className="space-y-3" data-testid="comm-settings">
      <p className="text-[11px] text-subtle">{t('comm.hint')}</p>
      {names.length === 0 ? <p className="text-[11px] text-subtle">{t('comm.noConnections')}</p> : null}
      {draft.map((rule, i) => (
        <div key={rule.id || i} className="space-y-2 rounded border border-line p-2" data-testid={`comm-rule-${i}`}>
          <div className="flex items-center gap-2">
            <Switch checked={rule.enabled} disabled={readOnly} onChange={(v) => update(i, { enabled: v })} />
            <Select
              className="flex-1"
              value={rule.connection}
              disabled={readOnly}
              onChange={(e) => update(i, { connection: e.target.value })}
              options={names.map((n) => ({ value: n, label: n }))}
            />
            <IconButton label={t('common.delete')} disabled={readOnly} onClick={() => remove(i)}><Trash2 size={14} className="text-critical" /></IconButton>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <Select
              label={t('comm.when')}
              value={rule.when}
              disabled={readOnly}
              onChange={(e) => update(i, { when: e.target.value as CommRule['when'] })}
              options={[{ value: 'on_finish', label: t('comm.whens.on_finish') }, { value: 'interval', label: t('comm.whens.interval') }]}
            />
            {rule.when === 'interval' ? (
              <TextInput label={t('comm.interval')} type="number" value={String(rule.interval_ms)} disabled={readOnly} onChange={(e) => update(i, { interval_ms: Number(e.target.value) })} />
            ) : null}
          </div>
          <TextInput label={t('comm.ok')} className="font-mono" value={rule.ok} disabled={readOnly} onChange={(e) => update(i, { ok: e.target.value })} data-testid={`comm-ok-${i}`} />
          <TextInput label={t('comm.ng')} className="font-mono" value={rule.ng} disabled={readOnly} onChange={(e) => update(i, { ng: e.target.value })} />
          <TextInput label={t('comm.failed')} hint={t('comm.failedHint')} className="font-mono" value={rule.failed} disabled={readOnly} onChange={(e) => update(i, { failed: e.target.value })} />
          <div className="grid gap-2 sm:grid-cols-2">
            <Select
              label={t('comm.node')}
              value={rule.node}
              disabled={readOnly}
              onChange={(e) => update(i, { node: e.target.value })}
              options={[{ value: '', label: t('comm.everyRun') }, ...nodes.map((n) => ({ value: n.id, label: n.label }))]}
            />
            {rule.node ? (
              <Select
                label={t('comm.nodeStatus')}
                value={rule.node_status}
                disabled={readOnly}
                onChange={(e) => update(i, { node_status: e.target.value as CommRule['node_status'] })}
                options={NODE_STATUSES.map((s) => ({ value: s, label: t(`comm.nodeStatuses.${s}`) }))}
              />
            ) : null}
          </div>
        </div>
      ))}
      <div className="flex items-center justify-between gap-2">
        <Button size="sm" icon={<ListPlus size={14} />} disabled={readOnly || names.length === 0} onClick={add} data-testid="comm-add">{t('comm.add')}</Button>
        <Button size="sm" variant="primary" icon={<Save size={14} />} loading={saving} disabled={readOnly || !dirty} onClick={() => onSave(draft)} data-testid="comm-save">{t('common.save')}</Button>
      </div>
    </div>
  )
}
