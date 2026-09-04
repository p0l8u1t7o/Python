/** Integration ▸ Stations: which other stations this instance polls for the fleet board. */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Pencil, Plus, Plug, Trash2 } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { Badge, Button, Card, CardBody, CardHeader, Checkbox, ConfirmDialog, EmptyRow, ErrorState, IconButton, LoadingState, Modal, TBody, THead, Table, Td, TextInput, Th, Tr } from '@/components/ui'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

interface StationRow {
  id: number
  name: string
  base_url: string
  note: string
  is_enabled: boolean
  api_key_hint: string
}

type Draft = { id: number | null; name: string; base_url: string; api_key: string; note: string; is_enabled: boolean }
const EMPTY: Draft = { id: null, name: '', base_url: '', api_key: '', note: '', is_enabled: true }

export function StationsPage() {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const [draft, setDraft] = useState<Draft | null>(null)
  const [pendingDelete, setPendingDelete] = useState<StationRow | null>(null)
  const [probe, setProbe] = useState<{ ok: boolean; error?: string; station_id?: string; version?: string; flows?: number } | null>(null)

  const list = useQuery({ queryKey: ['stations'], queryFn: () => api.get<{ items: StationRow[] }>('/vision/stations') })
  const invalidate = () => { void qc.invalidateQueries({ queryKey: ['stations'] }); void qc.invalidateQueries({ queryKey: ['fleet'] }) }

  const save = useMutation({
    mutationFn: (body: Draft) => body.id === null
      ? api.post('/vision/stations', { name: body.name, base_url: body.base_url, api_key: body.api_key, note: body.note, is_enabled: body.is_enabled })
      : api.patch(`/vision/stations/${body.id}`, { name: body.name, base_url: body.base_url, note: body.note, is_enabled: body.is_enabled, ...(body.api_key ? { api_key: body.api_key } : {}) }),
    onSuccess: () => { invalidate(); setDraft(null); setProbe(null); toast.success(t('common.saved')) },
    onError: (error) => toast.error(errorMessage(error)),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/vision/stations/${id}`),
    onSuccess: () => { invalidate(); setPendingDelete(null) },
    onError: (error) => toast.error(errorMessage(error)),
  })
  const test = useMutation({
    mutationFn: (body: Draft) => api.post<{ ok: boolean; error?: string; station_id?: string; version?: string; flows?: number }>('/vision/stations/test', { name: body.name || 'x', base_url: body.base_url, api_key: body.api_key }),
    onSuccess: (result) => setProbe(result),
    onError: (error) => setProbe({ ok: false, error: errorMessage(error) }),
  })

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={t('stations.title')} description={t('stations.subtitle')}
          actions={auth.isAdmin ? <Button size="sm" icon={<Plus size={14} />} onClick={() => { setDraft({ ...EMPTY }); setProbe(null) }} data-testid="station-add">{t('stations.add')}</Button> : undefined} />
        <CardBody className="!p-0">
          {list.isPending ? (
            <LoadingState />
          ) : list.isError ? (
            <ErrorState error={list.error} onRetry={() => void list.refetch()} />
          ) : (
            <Table>
              <THead>
                <Th>{t('common.name')}</Th>
                <Th>{t('stations.url')}</Th>
                <Th className="max-md:hidden">{t('stations.key')}</Th>
                <Th className="max-lg:hidden">{t('stations.note')}</Th>
                <Th align="center">{t('common.enabled')}</Th>
                <Th align="right">{t('common.actions')}</Th>
              </THead>
              <TBody>
                {list.data.items.length === 0 ? (
                  <EmptyRow colSpan={6} message={t('stations.empty')} />
                ) : (
                  list.data.items.map((row) => (
                    <Tr key={row.id} data-testid={`station-${row.id}`}>
                      <Td className="font-medium">{row.name}</Td>
                      <Td className="font-mono text-xs text-muted">{row.base_url}</Td>
                      <Td className="max-md:hidden font-mono text-xs text-muted">{row.api_key_hint || '—'}</Td>
                      <Td className="max-lg:hidden text-xs text-muted">{row.note || '—'}</Td>
                      <Td align="center">{row.is_enabled ? <Badge tone="ok">{t('common.enabled')}</Badge> : <Badge>{t('common.disabled')}</Badge>}</Td>
                      <Td align="right">
                        <div className="flex justify-end gap-1">
                          <IconButton label={t('common.edit')} disabled={!auth.isAdmin}
                            onClick={() => { setDraft({ id: row.id, name: row.name, base_url: row.base_url, api_key: '', note: row.note, is_enabled: row.is_enabled }); setProbe(null) }}><Pencil size={15} /></IconButton>
                          <IconButton label={t('common.delete')} disabled={!auth.isAdmin} onClick={() => setPendingDelete(row)}><Trash2 size={15} className="text-critical" /></IconButton>
                        </div>
                      </Td>
                    </Tr>
                  ))
                )}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
      <p className="text-xs text-muted">
        {t('stations.footnote')} <Link to="/fleet" className="underline">{t('fleet.title')}</Link>
      </p>

      <Modal open={draft !== null} onClose={() => setDraft(null)} title={draft?.id === null ? t('stations.add') : t('stations.edit')}
        footer={
          <>
            <Button onClick={() => setDraft(null)}>{t('common.cancel')}</Button>
            <Button icon={<Plug size={14} />} loading={test.isPending} disabled={!draft?.base_url} onClick={() => draft && test.mutate(draft)} data-testid="station-test">{t('stations.test')}</Button>
            <Button variant="primary" loading={save.isPending} disabled={!draft?.name || !draft?.base_url} onClick={() => draft && save.mutate(draft)} data-testid="station-save">{t('common.save')}</Button>
          </>
        }>
        {draft ? (
          <div className="space-y-3">
            <TextInput label={t('common.name')} required autoFocus value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} data-testid="station-name" />
            <TextInput label={t('stations.url')} required hint={t('stations.urlHint')} placeholder="http://192.168.1.31:8000" value={draft.base_url} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} data-testid="station-url" />
            <TextInput label={t('stations.key')} type="password" hint={draft.id === null ? t('stations.keyHint') : t('stations.keyKeep')} value={draft.api_key} onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} />
            <TextInput label={t('stations.note')} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
            <Checkbox label={t('common.enabled')} checked={draft.is_enabled} onChange={(v) => setDraft({ ...draft, is_enabled: v })} />
            {probe ? (
              <div className={`rounded border px-3 py-2 text-xs ${probe.ok ? 'border-ok/40 bg-ok/10' : 'border-critical/40 bg-critical/10'}`} data-testid="station-probe">
                {probe.ok ? t('stations.probeOk', { station: probe.station_id, version: probe.version, flows: probe.flows }) : probe.error}
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} danger
        title={t('common.delete')} message={t('stations.deleteMessage', { name: pendingDelete?.name ?? '' })}
        confirmLabel={t('common.delete')} onConfirm={() => pendingDelete && remove.mutate(pendingDelete.id)} />
    </div>
  )
}
