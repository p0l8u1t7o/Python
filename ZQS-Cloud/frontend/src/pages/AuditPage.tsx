import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useAuditActions, useAuditLogs } from '@/lib/queries'
import { formatDateTime } from '@/lib/format'
import { useTimeRange } from '@/lib/useTimeRange'
import type { AuditLog } from '@/lib/types'
import {
  Badge,
  Card,
  EmptyRow,
  ErrorState,
  Modal,
  PageHeader,
  Pagination,
  TimeRangePicker,
  Select,
  TBody,
  THead,
  Table,
  Td,
  Th,
  Tr,
} from '@/components/ui'

const PAGE_SIZE = 30

export function AuditPage() {
  const { t } = useTranslation()
  const range = useTimeRange('7d')
  const actions = useAuditActions()
  const [offset, setOffset] = useState(0)
  const [action, setAction] = useState('')
  const [selected, setSelected] = useState<AuditLog | null>(null)

  const logs = useAuditLogs({
    start: range.start,
    end: range.end,
    action: action || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  return (
    <>
      <PageHeader
        title={t('audit.title')}
        description={t('audit.subtitle')}
        actions={
          <>
            <Select
              value={action}
              placeholder={t('audit.filterAction')}
              onChange={(event) => {
                setAction(event.target.value)
                setOffset(0)
              }}
              options={(actions.data ?? []).map((item) => ({
                value: item.value,
                label: item.label,
              }))}
              className="w-56"
            />
            <TimeRangePicker range={range} />
          </>
        }
      />

      <Card>
        {logs.error ? (
          <ErrorState error={logs.error} onRetry={() => void logs.refetch()} />
        ) : (
          <>
            <Table>
              <THead>
                <Th>{t('audit.result')}</Th>
                <Th>{t('audit.action')}</Th>
                <Th>{t('audit.actor')}</Th>
                <Th>{t('audit.target')}</Th>
                <Th align="right">{t('common.time')}</Th>
              </THead>
              <TBody>
                {logs.isPending ? (
                  <EmptyRow colSpan={5} message={`${t('common.loading')}…`} />
                ) : logs.data && logs.data.items.length > 0 ? (
                  logs.data.items.map((entry) => (
                    <Tr key={entry.id} onClick={() => setSelected(entry)}>
                      <Td>
                        <Badge tone={entry.status === 'success' ? 'ok' : 'critical'}>
                          {t(`audit.${entry.status}`)}
                        </Badge>
                      </Td>
                      <Td className="font-medium">{entry.action_label || entry.action}</Td>
                      <Td className="text-muted">{entry.actor_label || '—'}</Td>
                      <Td className="max-w-xs truncate text-muted">
                        {entry.target_label || entry.target_type || '—'}
                      </Td>
                      <Td align="right" className="whitespace-nowrap text-muted">
                        {formatDateTime(entry.created_at)}
                      </Td>
                    </Tr>
                  ))
                ) : (
                  <EmptyRow colSpan={5} message={t('audit.noEntries')} />
                )}
              </TBody>
            </Table>

            {logs.data ? (
              <Pagination
                total={logs.data.total}
                limit={PAGE_SIZE}
                offset={offset}
                onChange={setOffset}
              />
            ) : null}
          </>
        )}
      </Card>

      <Modal
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected?.action_label ?? t('audit.title')}
        description={selected ? formatDateTime(selected.created_at) : undefined}
      >
        {selected ? (
          <div className="space-y-3 text-sm">
            <dl className="divide-y divide-line">
              <div className="flex justify-between gap-4 py-1.5">
                <dt className="text-xs text-muted">{t('audit.actor')}</dt>
                <dd className="text-right">{selected.actor_label || '—'}</dd>
              </div>
              <div className="flex justify-between gap-4 py-1.5">
                <dt className="text-xs text-muted">{t('audit.target')}</dt>
                <dd className="text-right">
                  {selected.target_label || '—'}
                  {selected.target_type ? (
                    <span className="ml-1.5 text-xs text-subtle">{selected.target_type}</span>
                  ) : null}
                </dd>
              </div>
              <div className="flex justify-between gap-4 py-1.5">
                <dt className="text-xs text-muted">{t('audit.ipAddress')}</dt>
                <dd className="text-right font-mono text-xs">{selected.ip_address || '—'}</dd>
              </div>
              <div className="flex justify-between gap-4 py-1.5">
                <dt className="text-xs text-muted">Request ID</dt>
                <dd className="text-right font-mono text-xs">{selected.request_id || '—'}</dd>
              </div>
            </dl>

            {selected.message ? (
              <p className="rounded-lg bg-surface-muted px-3 py-2 text-muted">{selected.message}</p>
            ) : null}

            {Object.keys(selected.payload).length > 0 ? (
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted">{t('audit.payload')}</p>
                <pre className="max-h-64 overflow-auto rounded-lg bg-surface-muted p-3 font-mono text-xs">
                  {JSON.stringify(selected.payload, null, 2)}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </>
  )
}
