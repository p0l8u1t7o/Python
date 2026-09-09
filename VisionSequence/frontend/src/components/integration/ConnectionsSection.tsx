/**
 * 連線：主動輸出的目的地（apps/comm）。**由各自的整合頁管理**——`kind` 固定這一頁只管一種
 * （Modbus 從站／主站頁，建立時不必選種類）；沒給 `kind` 時由 `section` 決定收哪些 kind（tcp／plugins 頁），
 * 後端 `comm.writers.kinds()` 是唯一事實來源，所以不會有連線找不到頁面而刪不掉。
 * kind 來自 GET /connections/kinds（含 fields）；config 表單依 kind 的 fields 產生：
 * modbus_tcp（主站，連到設備）／modbus_server（從站，本機開埠讓對方主站來讀寫）: host/port/unit_id/timeout_s|size/word_order；tcp_client: host/port/timeout_s/template/newline/wait_reply；tcp_image: host/port/timeout_s/encoding/quality；
 * plugin: class。有 connections 功能的人才能新增／修改／測試／手動寫入；所有登入者可看列表與狀態。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Activity, Cable, Download, Pencil, PenLine, Plug, Plus, Trash2, Upload } from 'lucide-react'

import { RuleTable } from '@/components/integration/RuleTable'
import { Badge, Button, Card, Checkbox, ConfirmDialog, EmptyRow, ErrorState, IconButton, LoadingState, Modal, Select, Switch, TBody, THead, Table, Td, TextArea, TextInput, Th, Tr } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { fetchConnectionState, fetchConnectionsExport, useConnectionKinds, useConnectionMutations, useConnections, useImportConnections, type ConnectionBody } from '@/lib/queries'
import type { Connection, ConnectionOpResult, ConnectionsExport, TriggerRule } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const FIELD_TYPE: Record<string, 'text' | 'number' | 'boolean' | 'select' | 'multiline' | 'list' | 'rules' | 'events'> = {
  host: 'text',
  port: 'number',
  baudrate: 'number',
  bytesize: 'number',
  parity: 'select',
  stopbits: 'number',
  bind_port: 'number',
  max_clients: 'number',
  end_char: 'select',
  end_custom: 'text',
  unit_id: 'number',
  timeout_s: 'number',
  word_order: 'select',
  size: 'number',
  template: 'multiline',
  newline: 'text',
  wait_reply: 'boolean',
  encoding: 'select',
  quality: 'number',
  channels: 'list',
  class: 'text',
  triggers: 'rules',
  trigger_interval_ms: 'number',
  events: 'events',
  event_template: 'text',
  heartbeat_ms: 'number',
  heartbeat_payload: 'text',
  heartbeat_address: 'text',
}
/** 站台事件（後端 apps/comm/events.py 的封閉集合）。 */
const EVENT_KINDS = ['server_ready', 'flow_busy', 'flow_idle', 'source_connected', 'source_lost', 'lock', 'unlock']
/** 觸發設定在表單裡自成一段（前面的欄位是連線本身，後面的是「誰來觸發檢測」）。 */
const TRIGGER_FIELDS = new Set(['triggers', 'trigger_interval_ms'])
/** 事件回報與心跳自成另一段（「這一站發生了什麼，要不要主動說一聲」）。 */
const EVENT_FIELDS = new Set(['events', 'event_template', 'heartbeat_ms', 'heartbeat_payload', 'heartbeat_address'])
const FIELD_DEFAULT: Record<string, Record<string, unknown>> = {
  modbus_tcp: { host: '127.0.0.1', port: 502, unit_id: 1, timeout_s: 2, word_order: 'big', triggers: [], trigger_interval_ms: 50, heartbeat_ms: 0, heartbeat_address: '' },
  modbus_server: { host: '0.0.0.0', port: 5020, unit_id: 1, size: 512, word_order: 'big', triggers: [], trigger_interval_ms: 50, heartbeat_ms: 0, heartbeat_address: '' },
  tcp_client: { host: '127.0.0.1', port: 9000, timeout_s: 2, template: '', newline: '\n', wait_reply: false, events: [], event_template: '', heartbeat_ms: 0, heartbeat_payload: '' },
  tcp_image: { host: '127.0.0.1', port: 9001, timeout_s: 2, encoding: 'jpeg', quality: 85 },
  serial: { port: 'COM3', baudrate: 9600, bytesize: 8, parity: 'N', stopbits: 1, timeout_s: 2, end_char: '\\n', end_custom: '', encoding: 'utf-8', triggers: [], trigger_interval_ms: 50, events: [], event_template: '', heartbeat_ms: 0, heartbeat_payload: '' },
  udp: { host: '127.0.0.1', port: 9002, bind_port: 0, timeout_s: 2, end_char: '\\n', end_custom: '', encoding: 'utf-8', triggers: [], trigger_interval_ms: 50, events: [], event_template: '', heartbeat_ms: 0, heartbeat_payload: '' },
  tcp_server_text: { host: '0.0.0.0', port: 9003, max_clients: 4, timeout_s: 2, end_char: '\\n', end_custom: '', encoding: 'utf-8', triggers: [], trigger_interval_ms: 50, events: [], event_template: '', heartbeat_ms: 0, heartbeat_payload: '' },
  plugin: { class: '' },
}

const STREAM_KINDS = new Set(['serial', 'udp', 'tcp_server_text'])

function ConfigField({ kind, field, value, onChange }: { kind: string; field: string; value: unknown; onChange: (v: unknown) => void }) {
  const { t } = useTranslation()
  const label = t(`connections.fields.${field}`, { defaultValue: field })
  const type = FIELD_TYPE[field] ?? 'text'
  if (type === 'boolean') return <Checkbox label={label} checked={Boolean(value)} onChange={onChange} />
  if (type === 'select' && field === 'parity') {
    return <Select label={label} value={String(value ?? 'N')} onChange={(e) => onChange(e.target.value)} options={['N', 'E', 'O'].map((v) => ({ value: v, label: t(`connections.parity.${v}`) }))} />
  }
  if (type === 'select' && field === 'end_char') {
    return <Select label={label} value={String(value ?? '\\n')} onChange={(e) => onChange(e.target.value)} options={['\\n', '\\r', '\\r\\n', 'custom'].map((v) => ({ value: v, label: t(`connections.endings.${v.replace(/\\/g, '') || 'custom'}`, { defaultValue: v }) }))} />
  }
  if (type === 'select' && field === 'word_order') {
    return <Select label={label} value={String(value ?? 'big')} onChange={(e) => onChange(e.target.value)} options={[{ value: 'big', label: t('connections.wordOrders.big') }, { value: 'little', label: t('connections.wordOrders.little') }]} />
  }
  if (type === 'select' && field === 'encoding') {
    const options = STREAM_KINDS.has(kind) ? ['utf-8', 'ascii', 'latin-1', 'hex'] : ['jpeg', 'png', 'raw']
    return <Select label={label} value={String(value ?? options[0])} onChange={(e) => onChange(e.target.value)} options={options.map((v) => ({ value: v, label: t(`connections.encodings.${v}`) }))} />
  }
  if (type === 'rules') {
    return <RuleTable rules={Array.isArray(value) ? (value as TriggerRule[]) : []} source="value" onChange={(rules) => onChange(rules)} />
  }
  if (type === 'events') {
    const chosen = new Set(Array.isArray(value) ? (value as string[]) : [])
    return (
      <fieldset>
        <legend className="mb-1 text-xs font-medium text-muted">{label}</legend>
        <div className="grid gap-1 sm:grid-cols-2">
          {EVENT_KINDS.map((kind) => (
            <Checkbox
              key={kind}
              label={t(`connections.eventKinds.${kind}`)}
              checked={chosen.has(kind)}
              onChange={(on) => onChange(EVENT_KINDS.filter((k) => (k === kind ? on : chosen.has(k))))}
            />
          ))}
        </div>
      </fieldset>
    )
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

export function ConnectionsSection({ section, kind }: { section: string; kind?: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const connections = useConnections()
  const kinds = useConnectionKinds()
  const { create, patch, remove, test, write } = useConnectionMutations()
  const importAll = useImportConnections()
  const [editing, setEditing] = useState<{ id: number | null; body: ConnectionBody } | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Connection | null>(null)
  const [writing, setWriting] = useState<{ conn: Connection; values: string; result: ConnectionOpResult | null } | null>(null)
  const [stateView, setStateView] = useState<{ conn: Connection; addresses: string; result: ConnectionOpResult | null; loading: boolean } | null>(null)
  // 「連線的增刪改」是一個可授權的功能（accounts/permissions.py 的 connections），預設只有管理員
  const canManage = auth.can('connections')

  // 這一頁只管自己的 kind；後端沒宣告 section 的外掛歸外掛頁，kind 完全不認得的舊連線也落到那裡，才不會有孤兒連線。
  const kindList = useMemo(() => (kinds.data ?? []).filter((k) => (kind ? k.kind === kind : (k.section || 'plugins') === section)), [kinds.data, section, kind])
  const ownKinds = useMemo(() => new Set(kindList.map((k) => k.kind)), [kindList])
  const rows = useMemo(() => (connections.data?.items ?? []).filter((c) => (kind ? c.kind === kind : ownKinds.has(c.kind) || (section === 'plugins' && !(kinds.data ?? []).some((k) => k.kind === c.kind)))), [connections.data, ownKinds, kinds.data, section, kind])
  const fieldsFor = useMemo(() => new Map(kindList.map((k) => [k.kind, k.fields])), [kindList])

  function defaultsFor(kind: string): Record<string, unknown> {
    const base = FIELD_DEFAULT[kind] ?? {}
    const out: Record<string, unknown> = {}
    for (const f of fieldsFor.get(kind) ?? []) if (f in base) out[f] = base[f]
    return out
  }
  function openCreate() {
    const first = kind ?? kindList[0]?.kind ?? ''
    setEditing({ id: null, body: { name: '', kind: first, config: defaultsFor(first), is_enabled: true } })
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
  /** 整份通訊設定：換一台工控機時匯出再匯入，不必一條一條重打（密碼欄位在伺服器就遮掉了）。 */
  async function onExport() {
    try {
      const data = await fetchConnectionsExport()
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `connections-${data.station_id || 'station'}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  async function onImport(file: File) {
    try {
      const data = JSON.parse(await file.text()) as ConnectionsExport
      if (!Array.isArray(data?.connections)) throw new Error(t('connections.importInvalid'))
      const result = await importAll.mutateAsync(data)
      const failed = result.failed.length
      if (failed) toast.error(t('connections.importFailed', { count: failed, name: result.failed[0]?.name ?? '' }))
      else toast.success(t('connections.imported', { created: result.created.length, updated: result.updated.length }))
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
        <p className="text-sm text-muted">{t('connections.subtitle')}</p>
        <span className="flex flex-wrap items-center gap-2" title={canManage ? undefined : t('connections.adminOnly')}>
          <Button icon={<Download size={15} />} disabled={!canManage} onClick={() => void onExport()} title={t('connections.exportAllHint')} data-testid="conn-export">{t('connections.export')}</Button>
          <label className={`btn-secondary cursor-pointer ${canManage ? '' : 'pointer-events-none opacity-50'}`} title={t('connections.importHint')}>
            <Upload size={15} />
            {t('connections.import')}
            <input
              type="file"
              accept="application/json,.json"
              className="hidden"
              disabled={!canManage}
              onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void onImport(file) }}
              data-testid="conn-import"
            />
          </label>
          <Button variant="primary" icon={<Plus size={15} />} disabled={!canManage} onClick={openCreate} data-testid="conn-create">{t('connections.create')}</Button>
        </span>
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
              {rows.length === 0 ? (
                <EmptyRow colSpan={6} message={<span className="inline-flex flex-col items-center gap-1"><Cable className="size-5" />{t('connections.empty')}</span>} />
              ) : (
                rows.map((c) => {
                  const st = c.status ?? {}
                  const connected = st.connected === true || st.open === true
                  return (
                    <Tr key={c.id}>
                      <Td className="font-medium">{c.name} <span className="text-xs text-muted">#{c.id}</span></Td>
                      <Td><Badge tone="info">{(kinds.data ?? []).find((k) => k.kind === c.kind)?.label ?? c.kind}</Badge></Td>
                      <Td><code className="block max-w-xs truncate font-mono text-xs text-muted" title={JSON.stringify(c.config)}>{JSON.stringify(c.config)}</code></Td>
                      <Td>
                        <span className="flex items-center gap-1.5">
                          {'connected' in st || 'open' in st ? <Badge tone={connected ? 'ok' : 'neutral'}>{connected ? t('integration.events.connected') : t('integration.events.disconnected')}</Badge> : null}
                          <code className="block max-w-[200px] truncate font-mono text-[11px] text-muted" title={JSON.stringify(st)}>{JSON.stringify(st)}</code>
                        </span>
                      </Td>
                      <Td align="center"><Switch label={t('common.enabled')} checked={c.is_enabled} disabled={!canManage} onChange={(v) => patch.mutate({ id: c.id, is_enabled: v }, { onError: (error) => toast.error(errorMessage(error)) })} /></Td>
                      <Td align="right">
                        <span className="inline-flex gap-1">
                          <IconButton label={t('connections.state')} onClick={() => void readState({ conn: c, addresses: '', result: null, loading: false })}><Activity size={15} /></IconButton>
                          <IconButton label={t('connections.test')} disabled={!canManage} onClick={() => void onTest(c)} data-testid="conn-test"><Plug size={15} /></IconButton>
                          <IconButton label={t('connections.write')} disabled={!canManage} onClick={() => setWriting({ conn: c, values: c.kind.startsWith('modbus') ? '{"coil:0": 1}' : '{"judge": "OK"}', result: null })} data-testid="conn-write"><PenLine size={15} /></IconButton>
                          <IconButton label={t('common.edit')} disabled={!canManage} onClick={() => setEditing({ id: c.id, body: { name: c.name, kind: c.kind, config: { ...c.config }, is_enabled: c.is_enabled } })}><Pencil size={15} /></IconButton>
                          <IconButton label={t('common.delete')} disabled={!canManage} onClick={() => setPendingDelete(c)}><Trash2 size={15} className="text-critical" /></IconButton>
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
            {kind ? null : <Select label={t('connections.kind')} value={body.kind} onChange={(e) => setEditing({ ...editing!, body: { ...body, kind: e.target.value, config: defaultsFor(e.target.value) } })} options={kindList.map((k) => ({ value: k.kind, label: k.label }))} data-testid="conn-kind" />}
            {(fieldsFor.get(body.kind) ?? []).filter((f) => !TRIGGER_FIELDS.has(f) && !EVENT_FIELDS.has(f)).map((field) => (
              <ConfigField key={field} kind={body.kind} field={field} value={body.config[field]} onChange={(v) => setEditing({ ...editing!, body: { ...body, config: { ...body.config, [field]: v } } })} />
            ))}
            {(fieldsFor.get(body.kind) ?? []).some((f) => TRIGGER_FIELDS.has(f)) ? (
              <details className="rounded border border-line" open={Array.isArray(body.config.triggers) && body.config.triggers.length > 0} data-testid="conn-trigger">
                <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{t('connections.trigger.title')}</summary>
                <div className="space-y-3 border-t border-line p-3">
                  <p className="text-xs text-muted">{t('connections.trigger.hint')}</p>
                  {(fieldsFor.get(body.kind) ?? []).filter((f) => TRIGGER_FIELDS.has(f)).map((field) => (
                    <ConfigField key={field} kind={body.kind} field={field} value={body.config[field]} onChange={(v) => setEditing({ ...editing!, body: { ...body, config: { ...body.config, [field]: v } } })} />
                  ))}
                </div>
              </details>
            ) : null}
            {(fieldsFor.get(body.kind) ?? []).some((f) => EVENT_FIELDS.has(f)) ? (
              <details className="rounded border border-line" open={Boolean((body.config.events as string[] | undefined)?.length) || Number(body.config.heartbeat_ms ?? 0) > 0} data-testid="conn-events">
                <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{t('connections.report.title')}</summary>
                <div className="space-y-3 border-t border-line p-3">
                  <p className="text-xs text-muted">{t('connections.report.hint')}</p>
                  {(fieldsFor.get(body.kind) ?? []).filter((f) => EVENT_FIELDS.has(f)).map((field) => (
                    <ConfigField key={field} kind={body.kind} field={field} value={body.config[field]} onChange={(v) => setEditing({ ...editing!, body: { ...body, config: { ...body.config, [field]: v } } })} />
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
            <div className="flex items-end gap-2">
              <TextInput label={t('connections.stateAddresses')} className="font-mono" value={stateView.addresses} onChange={(e) => setStateView({ ...stateView, addresses: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && void readState(stateView)} />
              <Button size="sm" loading={stateView.loading} onClick={() => void readState(stateView)}>{t('connections.read')}</Button>
            </div>
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
