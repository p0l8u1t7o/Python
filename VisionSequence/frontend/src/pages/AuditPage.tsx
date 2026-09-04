/**
 * Audit trail `/audit` (administrators only): who changed what, when.
 * Filter by action, actor or free text; expand a row for the parameter-level detail; export CSV so
 * quality can keep the record outside the machine.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate } from 'react-router-dom'
import { Download } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'

import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, CardBody, EmptyRow, ErrorState, LoadingState, PageHeader, Select, TBody, THead, Table, Td, TextInput, Th, Tr } from '@/components/ui'
import { api, downloadFile } from '@/lib/api'
import { formatDateTime, formatDateTimeFull } from '@/lib/format'
import { useAuth } from '@/providers/AuthProvider'

interface AuditRow {
  id: number
  at: string
  actor: string
  actor_kind: string
  action: string
  target_type: string
  target_id: string
  target_name: string
  summary: string
  detail: Record<string, unknown>
  ip: string
}

const PAGE_SIZE = 50

/** flow.update → warning (it changes what the line accepts); deletions → critical. */
function tone(action: string): 'ok' | 'warning' | 'critical' | 'info' {
  if (action.endsWith('.delete')) return 'critical'
  if (action.startsWith('flow.') || action.startsWith('recipe.')) return 'warning'
  if (action.startsWith('lock.')) return 'info'
  return 'ok'
}

export function AuditPage() {
  const { t } = useTranslation()
  const auth = useAuth()
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [openRow, setOpenRow] = useState<number | null>(null)

  const params = { action, actor, q, limit: PAGE_SIZE, offset }
  const list = useQuery({
    queryKey: ['audit', params],
    queryFn: () => api.get<{ items: AuditRow[]; total: number; actions: string[]; actors: string[] }>('/vision/audit', params),
    enabled: auth.isAdmin,
  })

  if (!auth.isAdmin) return <Navigate to="/" replace />

  return (
    <Page>
      <PageHeader title={t('audit.title')} description={t('audit.subtitle')}
        actions={
          <Button size="sm" icon={<Download size={14} />}
            onClick={() => void downloadFile(`/vision/audit.csv${action ? `?action=${encodeURIComponent(action)}` : ''}`, 'audit.csv')}
            data-testid="audit-export">{t('audit.export')}</Button>
        } />
      <Card>
        <CardBody className="!pb-2">
          <div className="flex flex-wrap items-end gap-2">
            <Select label={t('audit.action')} value={action} className="!w-52" onChange={(e) => { setAction(e.target.value); setOffset(0) }}
              options={[{ value: '', label: t('common.all') }, ...(list.data?.actions ?? []).map((a) => ({ value: a, label: a }))]} data-testid="audit-action" />
            <Select label={t('audit.actor')} value={actor} className="!w-44" onChange={(e) => { setActor(e.target.value); setOffset(0) }}
              options={[{ value: '', label: t('common.all') }, ...(list.data?.actors ?? []).map((a) => ({ value: a, label: a }))]} />
            <TextInput label={t('common.search')} value={q} className="!w-56"
              onChange={(e) => { setQ(e.target.value); setOffset(0) }} data-testid="audit-search" />
          </div>
        </CardBody>
      </Card>
      <Card className="mt-4">
        <CardBody className="!p-0">
          {list.isPending ? (
            <LoadingState />
          ) : list.isError ? (
            <ErrorState error={list.error} onRetry={() => void list.refetch()} />
          ) : (
            <>
              <Table>
                <THead>
                  <Th>{t('audit.cols.at')}</Th>
                  <Th>{t('audit.cols.actor')}</Th>
                  <Th>{t('audit.cols.action')}</Th>
                  <Th>{t('audit.cols.target')}</Th>
                  <Th>{t('audit.cols.summary')}</Th>
                  <Th className="max-lg:hidden">{t('audit.cols.ip')}</Th>
                </THead>
                <TBody>
                  {list.data.items.length === 0 ? (
                    <EmptyRow colSpan={6} message={t('audit.empty')} />
                  ) : (
                    list.data.items.map((row) => (
                      <Tr key={row.id} className="cursor-pointer" onClick={() => setOpenRow(openRow === row.id ? null : row.id)} data-testid={`audit-row-${row.id}`}>
                        <Td className="tnum whitespace-nowrap text-xs text-muted"><span title={formatDateTimeFull(row.at)}>{formatDateTime(row.at)}</span></Td>
                        <Td className="whitespace-nowrap text-xs">{row.actor}{row.actor_kind !== 'user' ? <span className="text-muted"> ({row.actor_kind})</span> : null}</Td>
                        <Td><Badge tone={tone(row.action)}>{row.action}</Badge></Td>
                        <Td className="max-w-[220px] truncate text-xs"><span title={`${row.target_type} #${row.target_id}`}>{row.target_name || row.target_type || '—'}</span></Td>
                        <Td className="text-xs">
                          <div className="max-w-[420px] truncate">{row.summary || '—'}</div>
                          {openRow === row.id && Object.keys(row.detail ?? {}).length ? (
                            <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-all rounded bg-surface-muted p-2 font-mono text-[11px]">{JSON.stringify(row.detail, null, 2)}</pre>
                          ) : null}
                        </Td>
                        <Td className="max-lg:hidden font-mono text-[11px] text-muted">{row.ip || '—'}</Td>
                      </Tr>
                    ))
                  )}
                </TBody>
              </Table>
              <div className="flex items-center justify-between px-4 py-2 text-xs text-muted">
                <span className="tnum">{t('common.showing', { from: list.data.total ? offset + 1 : 0, to: Math.min(offset + PAGE_SIZE, list.data.total), total: list.data.total })}</span>
                <div className="flex gap-2">
                  <Button size="xs" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>{t('common.prev')}</Button>
                  <Button size="xs" disabled={offset + PAGE_SIZE >= list.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>{t('common.next')}</Button>
                </div>
              </div>
            </>
          )}
        </CardBody>
      </Card>
      <p className="mt-3 text-xs text-muted">{t('audit.footnote')}</p>
    </Page>
  )
}
