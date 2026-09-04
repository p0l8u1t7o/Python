/**
 * 連線（ConnectionsSection）：Modbus TCP／上位機的主動輸出連線（apps/comm）。
 * 「外部整合 ▸ 連線」頁（/integration/connections）的內容；本檔只輸出區塊，外框與命令追蹤在 pages/integration/ConnectionsPage.tsx。
 * kind 來自 GET /connections/kinds（含 fields）；config 表單依 kind 的 fields 產生：
 * modbus_tcp（主站，連到 PLC）／modbus_server（從站，本機開埠讓 PLC 來讀寫）: host/port/unit_id/timeout_s|size/word_order；tcp_client: host/port/timeout_s/template/newline/wait_reply；
 * dio_sim: channels；plugin: class。管理員才能新增／修改／測試／手動寫入；所有登入者可看列表與狀態。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Activity, Cable, Pencil, PenLine, Plug, Plus, Trash2 } from 'lucide-react'

import { Badge, Button, Card, Checkbox, ConfirmDialog, EmptyRow, ErrorState, IconButton, LoadingState, Modal, Select, Switch, TBody, THead, Table, Td, TextArea, TextInput, Th, Tr } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { fetchConnectionState, useConnectionKinds, useConnectionMutations, useConnections, type ConnectionBody } from '@/lib/queries'
import type { Connection, ConnectionOpResult } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const FIELD_TYPE: Record<string, 'text' | 'number' | 'boolean' | 'select' | 'multiline' | 'list'> = {
  host: 'text',
  port: 'number',
  unit_id: 'number',
  timeout_s: 'number',
  word_order: 'select',
  size: 'number',
  template: 'multiline',
  newline: 'text',
  wait_reply: 'boolean',
  channels: 'list',
  class: 'text',
  trigger_address: 'text',
  trigger_flow: 'text',
  trigger_interval_ms: 'number',
  trigger_mode: 'select',
  trigger_clear: 'boolean',
  trigger_done_address: 'text',
  trigger_recipe: 'text',
}
/** 觸發設定在表單裡自成一段（前面的欄位是連線本身，後面的是「誰來觸發檢測」）。 */
const TRIGGER_FIELDS = new Set(['trigger_address', 'trigger_flow', 'trigger_interval_ms', 'trigger_mode', 'trigger_clear', 'trigger_done_address', 'trigger_recipe'])
const FIELD_DEFAULT: Record<string, Record<string, unknown>> = {
  modbus_tcp: { host: '127.0.0.1', port: 502, unit_id: 1, timeout_s: 2, word_order: 'big', trigger_address: '', trigger_flow: '', trigger_interval_ms: 50, trigger_mode: 'rising', trigger_clear: true, trigger_done_address: '', trigger_recipe: '' },
  modbus_server: { host: '0.0.0.0', port: 5020, unit_id: 1, size: 512, word_order: 'big', trigger_address: '', trigger_flow: '', trigger_interval_ms: 50, trigger_mode: 'rising', trigger_clear: true, trigger_done_address: '', trigger_recipe: '' },
  tcp_client: { host: '127.0.0.1', port: 9000, timeout_s: 2, template: '', newline: '\n', wait_reply: false },
  dio_sim: { channels: ['DO0', 'DO1', 'OK', 'NG'] },
  plugin: { class: '' },
}

function ConfigField({ field, value, onChange }: { field: string; value: unknown; onChange: (v: unknown) => void }) {
  const { t } = useTranslation()
  const label = t(`connections.fields.${field}`, { defaultValue: field })
  const type = FIELD_TYPE[field] ?? 'text'
  if (type === 'boolean') return <Checkbox label={label} checked={Boolean(value)} onChange={onChange} />
  if (type === 'select' && field === 'word_order') {
    return <Select label={label} value={String(value ?? 'big')} onChange={(e) => onChange(e.target.value)} options={[{ value: 'big', label: t('connections.wordOrders.big') }, { value: 'little', label: t('connections.wordOrders.little') }]} />
  }
  if (type === 'select' && field === 'trigger_mode') {
    return <Select label={label} value={String(value ?? 'rising')} onChange={(e) => onChange(e.target.value)} options={[{ value: 'rising', label: t('connections.triggerModes.rising') }, { value: 'nonzero', label: t('connections.triggerModes.nonzero') }]} />
  }
  if (field === 'trigger_address' || field === 'trigger_flow') {
    return <TextInput label={label} hint={t(`connections.fields.${field}Hint`)} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
  }
  if (type === 'multiline') return <TextArea label={label} hint={t('connections.fields.templateHint')} rows={2} className="font-mono text-xs" value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
  if (type === 'list') {
    const text = Array.isArray(value) ? value.join(',') : typeof value === 'number' ? String(value) : String(value ?? '')
    return <TextInput label={label} hint={t('connections.fields.channelsHint')} value={text} onChange={(e) => onChange(e.target.value.split(',').map((s) => s.trim()).filter(Boolean))} />
  }
  if (type === 'number') return <TextInput label={label} type="number" step={field === 'timeout_s' ? 0.1 : 1} value={value === undefined || value === null ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
  if (field === 'newline') return <TextInput label={label} className="font-mono" value={JSON.stringify(String(value ?? '\n')).slice(1, -1)} onChange={(e) => onChange(e.target.value.replace(/\\n/g, '\n').replace(/\\r/g, '\r'))} />
  return <TextInput label={label} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
}

function ResultBox({ result }: { result: ConnectionOpResult | null }) {
  if (!result) return null
  return (
    <pre className={`max-h-56 overflow-auto rounded-lg p-3 font-mono text-[11px] leading-relaxed ${result.ok ? 'bg-surface-muted' : 'bg-critical-soft text-critical'}`} data-testid="connection-result">{JSON.stringify(result, null, 2)}</pre>
  )
}

export function ConnectionsSection() {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const connections = useConnections()
  const kinds = useConnectionKinds()
  const { create, patch, remove, test, write } = useConnectionMutations()
  const [editing, setEditing] = useState<{ id: number | null; body: ConnectionBody } | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Connection | null>(null)
  const [writing, setWriting] = useState<{ conn: Connection; values: string; result: ConnectionOpResult | null } | null>(null)
  const [stateView, setStateView] = useState<{ conn: Connection; addresses: string; result: ConnectionOpResult | null; loading: boolean } | null>(null)
  const isAdmin = auth.isAdmin

  const kindList = kinds.data ?? []
  const fieldsFor = useMemo(() => new Map(kindList.map((k) => [k.kind, k.fields])), [kindList])

  function defaultsFor(kind: string): Record<string, unknown> {
    const base = FIELD_DEFAULT[kind] ?? {}
    const out: Record<string, unknown> = {}
    for (const f of fieldsFor.get(kind) ?? []) if (f in base) out[f] = base[f]
    return out
  }
  function openCreate() {
    const kind = kindList.find((k) => k.kind === 'dio_sim')?.kind ?? kindList[0]?.kind ?? 'dio_sim'
    setEditing({ id: null, body: { name: '', kind, config: defaultsFor(kind), is_enabled: true } })
  }

  async function onSave() {
    if (!editing) return
    if (!editing.body.name.trim()) return toast.error(t('flows.nameRequired'))
    try {
      if (editing.id === null) {
        await create.mutateAsync(editing.body)
        toast.success(t('connections.created'))
      } else {
        await patch.mutateAsync({ id: editing.id, ...editing.body })
        toast.success(t('connections.updated'))
      }
      setEditing(null)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  async function onDelete() {
    if (!pendingDelete) return
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('connections.deleted'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setPendingDelete(null)
    }
  }
  async function onTest(conn: Connection) {
    try {
      const res = await test.mutateAsync(conn.id)
      if (res.ok) toast.success(t('connections.testOk'))
      else toast.error(t('connections.testFailed', { error: res.error ?? '' }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  async function onWrite() {
    if (!writing) return
    let values: unknown
    try {
      values = JSON.parse(writing.values)
    } catch {
      return toast.error(t('connections.writeInvalid'))
    }
    if (!values || typeof values !== 'object' || Array.isArray(values)) return toast.error(t('connections.writeInvalid'))
    try {
      const res = await write.mutateAsync({ id: writing.conn.id, values: values as Record<string, unknown> })
      setWriting({ ...writing, result: res })
      if (res.ok) toast.success(t('connections.writeOk', { count: Object.keys(values as object).length }))
      else toast.error(t('connections.writeFailed', { error: res.error ?? '' }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  async function readState(view: NonNullable<typeof stateView>) {
    setStateView({ ...view, loading: true })
    try {
      const res = await fetchConnectionState(view.conn.id, view.addresses)
      setStateView({ ...view, result: res, loading: false })
    } catch (error) {
      toast.error(errorMessage(error))
      setStateView({ ...view, loading: false })
    }
  }

  const body = editing?.body
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">{t('connections.subtitle')} · <Link to="/integration/modbus" className="text-brand hover:underline">{t('connections.goIntegration')}</Link></p>
        <span title={isAdmin ? undefined : t('connections.adminOnly')}><Button variant="primary" icon={<Plus size={15} />} disabled={!isAdmin} onClick={openCreate} data-testid="conn-create">{t('connections.create')}</Button></span>
      </div>
      <Card className="overflow-hidden">
        {connections.isPending ? (
          <LoadingState />
        ) : connections.isError ? (
          <ErrorState error={connections.error} onRetry={() => void connections.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('common.name')}</Th>
              <Th>{t('connections.kind')}</Th>
              <Th>{t('connections.config')}</Th>
              <Th>{t('connections.status')}</Th>
              <Th align="center">{t('common.enabled')}</Th>
              <Th align="right">{t('common.actions')}</Th>
            </THead>
            <TBody>
              {connections.data.items.length === 0 ? (
                <EmptyRow colSpan={6} message={<span className="inline-flex flex-col items-center gap-1"><Cable className="size-5" />{t('connections.empty')}</span>} />
              ) : (
                connections.data.items.map((c) => {
                  const st = c.status ?? {}
                  const connected = st.connected === true || st.open === true
                  return (
                    <Tr key={c.id}>
                      <Td className="font-medium">{c.name} <span className="text-xs text-muted">#{c.id}</span></Td>
                      <Td><Badge tone="info">{kindList.find((k) => k.kind === c.kind)?.label ?? c.kind}</Badge></Td>
                      <Td><code className="block max-w-xs truncate font-mono text-xs text-muted" title={JSON.stringify(c.config)}>{JSON.stringify(c.config)}</code></Td>
                      <Td>
                        <span className="flex items-center gap-1.5">
                          {'connected' in st || 'open' in st ? <Badge tone={connected ? 'ok' : 'neutral'}>{connected ? t('integration.events.connected') : t('integration.events.disconnected')}</Badge> : null}
                          <code className="block max-w-[200px] truncate font-mono text-[11px] text-muted" title={JSON.stringify(st)}>{JSON.stringify(st)}</code>
                        </span>
                      </Td>
                      <Td align="center"><Switch checked={c.is_enabled} disabled={!isAdmin} onChange={(v) => patch.mutate({ id: c.id, is_enabled: v }, { onError: (error) => toast.error(errorMessage(error)) })} /></Td>
                      <Td align="right">
                        <span className="inline-flex gap-1">
                          <IconButton label={t('connections.state')} onClick={() => void readState({ conn: c, addresses: '', result: null, loading: false })}><Activity size={15} /></IconButton>
                          <IconButton label={t('connections.test')} disabled={!isAdmin} onClick={() => void onTest(c)} data-testid="conn-test"><Plug size={15} /></IconButton>
                          <IconButton label={t('connections.write')} disabled={!isAdmin} onClick={() => setWriting({ conn: c, values: c.kind === 'dio_sim' ? JSON.stringify({ [(Array.isArray(c.config.channels) ? (c.config.channels as string[])[0] : 'DO0') ?? 'DO0']: 1 }) : '{"coil:0": 1}', result: null })} data-testid="conn-write"><PenLine size={15} /></IconButton>
                          <IconButton label={t('common.edit')} disabled={!isAdmin} onClick={() => setEditing({ id: c.id, body: { name: c.name, kind: c.kind, config: { ...c.config }, is_enabled: c.is_enabled } })}><Pencil size={15} /></IconButton>
                          <IconButton label={t('common.delete')} disabled={!isAdmin} onClick={() => setPendingDelete(c)}><Trash2 size={15} className="text-critical" /></IconButton>
                        </span>
                      </Td>
                    </Tr>
                  )
                })
              )}
            </TBody>
          </Table>
        )}
      </Card>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing?.id === null ? t('connections.create') : t('common.edit')}
        footer={
          <>
            <Button onClick={() => setEditing(null)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={create.isPending || patch.isPending} onClick={() => void onSave()} data-testid="conn-save">{t('common.save')}</Button>
          </>
        }
      >
        {body ? (
          <div className="space-y-3">
            <TextInput label={t('common.name')} required autoFocus value={body.name} onChange={(e) => setEditing({ ...editing!, body: { ...body, name: e.target.value } })} data-testid="conn-name-input" />
            <Select label={t('connections.kind')} value={body.kind} onChange={(e) => setEditing({ ...editing!, body: { ...body, kind: e.target.value, config: defaultsFor(e.target.value) } })} options={kindList.map((k) => ({ value: k.kind, label: k.label }))} data-testid="conn-kind" />
            {(fieldsFor.get(body.kind) ?? []).filter((f) => !TRIGGER_FIELDS.has(f)).map((field) => (
              <ConfigField key={field} field={field} value={body.config[field]} onChange={(v) => setEditing({ ...editing!, body: { ...body, config: { ...body.config, [field]: v } } })} />
            ))}
            {(fieldsFor.get(body.kind) ?? []).some((f) => TRIGGER_FIELDS.has(f)) ? (
              <details className="rounded border border-line" open={Boolean(body.config.trigger_address)} data-testid="conn-trigger">
                <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{t('connections.trigger.title')}</summary>
                <div className="space-y-3 border-t border-line p-3">
                  <p className="text-xs text-muted">{t('connections.trigger.hint')}</p>
                  {(fieldsFor.get(body.kind) ?? []).filter((f) => TRIGGER_FIELDS.has(f)).map((field) => (
                    <ConfigField key={field} field={field} value={body.config[field]} onChange={(v) => setEditing({ ...editing!, body: { ...body, config: { ...body.config, [field]: v } } })} />
                  ))}
                </div>
              </details>
            ) : null}
            <Checkbox label={t('common.enabled')} checked={body.is_enabled} onChange={(v) => setEditing({ ...editing!, body: { ...body, is_enabled: v } })} />
          </div>
        ) : null}
      </Modal>

      <Modal
        open={writing !== null}
        onClose={() => setWriting(null)}
        title={t('connections.writeTitle', { name: writing?.conn.name ?? '' })}
        footer={
          <>
            <Button onClick={() => setWriting(null)}>{t('common.close')}</Button>
            <Button variant="primary" icon={<PenLine size={14} />} loading={write.isPending} onClick={() => void onWrite()} data-testid="conn-write-send">{t('connections.write')}</Button>
          </>
        }
      >
        {writing ? (
          <div className="space-y-3">
            <TextArea label={t('connections.writeValues')} hint={t('connections.writeValuesHint')} rows={4} className="font-mono text-xs" value={writing.values} onChange={(e) => setWriting({ ...writing, values: e.target.value })} data-testid="conn-write-values" />
            <ResultBox result={writing.result} />
          </div>
        ) : null}
      </Modal>

      <Modal open={stateView !== null} onClose={() => setStateView(null)} title={t('connections.stateTitle', { name: stateView?.conn.name ?? '' })} footer={<Button onClick={() => setStateView(null)}>{t('common.close')}</Button>}>
        {stateView ? (
          <div className="space-y-3">
            <p className="text-xs text-muted">{t('connections.stateHint')}</p>
            {stateView.conn.kind !== 'dio_sim' ? (
              <div className="flex items-end gap-2">
                <TextInput label={t('connections.stateAddresses')} className="font-mono" value={stateView.addresses} onChange={(e) => setStateView({ ...stateView, addresses: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && void readState(stateView)} />
                <Button size="sm" loading={stateView.loading} onClick={() => void readState(stateView)}>{t('connections.read')}</Button>
              </div>
            ) : (
              <Button size="sm" loading={stateView.loading} onClick={() => void readState(stateView)}>{t('common.refresh')}</Button>
            )}
            {stateView.result?.ok && stateView.result.values && Object.keys(stateView.result.values).length ? (
              <table className="w-full text-xs" data-testid="conn-state-table">
                <tbody className="divide-y divide-line">
                  {Object.entries(stateView.result.values).map(([k, v]) => (
                    <tr key={k}><td className="py-1 pr-2 font-mono text-muted">{k}</td><td className="py-1 text-right font-mono">{JSON.stringify(v)}</td></tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <ResultBox result={stateView.result} />
          </div>
        ) : null}
      </Modal>

      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void onDelete()} title={t('connections.deleteTitle')} message={t('connections.deleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </>
  )
}
