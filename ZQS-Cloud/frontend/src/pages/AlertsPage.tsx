import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { CheckCircle2 } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { useAlert, useAlertActions, useAlerts, useAlertSummary, useSites } from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import { formatDateTime, formatNumber, formatRelative } from '@/lib/format'
import type { Severity } from '@/lib/types'
import {
  AlertStatusBadge,
  Badge,
  Button,
  Card,
  CardBody,
  DetailRow,
  EmptyRow,
  ErrorState,
  Modal,
  PageHeader,
  Pagination,
  SegmentedControl,
  Select,
  SiteTreeSelect,
  SeverityBadge,
  StatTile,
  TBody,
  THead,
  Table,
  Td,
  TextArea,
  Th,
  Tr,
} from '@/components/ui'

const PAGE_SIZE = 25
const SEVERITIES: Severity[] = ['critical', 'major', 'warning', 'info']

export function AlertsPage() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()

  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [openOnly, setOpenOnly] = useState(true)
  const [severity, setSeverity] = useState('')
  const [siteId, setSiteId] = useState('')

  const detailId = searchParams.get('alert')
  const sites = useSites()
  const summary = useAlertSummary()
  const alerts = useAlerts({
    open_only: openOnly || undefined,
    severity: severity || undefined,
    site_id: siteId || undefined,
    limit: PAGE_SIZE,
    offset,
  })
  const { bulkAcknowledge } = useAlertActions()

  const items = alerts.data?.items ?? []
  const selectable = items.filter((alert) => alert.status === 'firing').map((alert) => alert.id)
  const allSelected = selectable.length > 0 && selectable.every((id) => selected.includes(id))

  function openDetail(id: string) {
    const next = new URLSearchParams(searchParams)
    next.set('alert', id)
    setSearchParams(next, { replace: true })
  }

  function closeDetail() {
    const next = new URLSearchParams(searchParams)
    next.delete('alert')
    setSearchParams(next, { replace: true })
  }

  return (
    <>
      <PageHeader title={t('alerts.title')} description={t('alerts.subtitle')} />

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {SEVERITIES.map((level) => (
          <StatTile
            key={level}
            label={t(`severity.${level}`)}
            value={summary.data?.by_severity[level] ?? 0}
            accent={level === 'info' ? 'info' : level}
            onClick={() => {
              setSeverity(severity === level ? '' : level)
              setOffset(0)
            }}
          />
        ))}
      </div>

      <Card>
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line p-4">
          <div className="flex flex-wrap items-end gap-3">
            <SegmentedControl
              size="sm"
              value={openOnly ? 'open' : 'all'}
              onChange={(value) => {
                setOpenOnly(value === 'open')
                setOffset(0)
              }}
              options={[
                { value: 'open', label: t('alerts.onlyOpen') },
                { value: 'all', label: t('common.all') },
              ]}
            />
            <Select
              value={severity}
              placeholder={t('common.all')}
              onChange={(event) => {
                setSeverity(event.target.value)
                setOffset(0)
              }}
              options={SEVERITIES.map((level) => ({ value: level, label: t(`severity.${level}`) }))}
              className="w-36"
            />
            <SiteTreeSelect
              sites={sites.data?.items ?? []}
              value={siteId}
              placeholder={t('common.all')}
              allowClear
              onChange={(value) => {
                setSiteId(value)
                setOffset(0)
              }}
              className="w-52"
            />
          </div>

          {selected.length > 0 && can('alert:acknowledge') ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted">
                {t('alerts.selected', { count: selected.length })}
              </span>
              <Button
                variant="primary"
                size="sm"
                loading={bulkAcknowledge.isPending}
                onClick={async () => {
                  try {
                    await bulkAcknowledge.mutateAsync({ alertIds: selected, note: '' })
                    setSelected([])
                  } catch (error) {
                    toast.error(errorMessage(error))
                  }
                }}
              >
                {t('alerts.bulkAcknowledge')}
              </Button>
            </div>
          ) : null}
        </div>

        {alerts.error ? (
          <ErrorState error={alerts.error} onRetry={() => void alerts.refetch()} />
        ) : (
          <>
            <Table>
              <THead>
                <Th className="w-10">
                  {can('alert:acknowledge') ? (
                    <input
                      type="checkbox"
                      aria-label="select all"
                      checked={allSelected}
                      disabled={selectable.length === 0}
                      onChange={(event) =>
                        setSelected(event.target.checked ? selectable : [])
                      }
                      className="size-4 rounded border-line accent-[var(--brand)]"
                    />
                  ) : null}
                </Th>
                <Th>{t('severity.warning')}</Th>
                <Th>{t('common.status')}</Th>
                <Th>{t('devices.device')}</Th>
                <Th>{t('alerts.title')}</Th>
                <Th align="right">{t('alerts.lastTriggered')}</Th>
              </THead>
              <TBody>
                {alerts.isPending ? (
                  <EmptyRow colSpan={6} message={`${t('common.loading')}…`} />
                ) : items.length > 0 ? (
                  items.map((alert) => (
                    <Tr key={alert.id}>
                      <Td>
                        {can('alert:acknowledge') && alert.status === 'firing' ? (
                          <input
                            type="checkbox"
                            aria-label={alert.title}
                            checked={selected.includes(alert.id)}
                            onChange={(event) =>
                              setSelected((current) =>
                                event.target.checked
                                  ? [...current, alert.id]
                                  : current.filter((id) => id !== alert.id),
                              )
                            }
                            className="size-4 rounded border-line accent-[var(--brand)]"
                          />
                        ) : null}
                      </Td>
                      <Td onClick={() => openDetail(alert.id)} className="cursor-pointer">
                        <SeverityBadge severity={alert.severity} />
                      </Td>
                      <Td onClick={() => openDetail(alert.id)} className="cursor-pointer">
                        <AlertStatusBadge status={alert.status} />
                      </Td>
                      <Td onClick={() => openDetail(alert.id)} className="cursor-pointer">
                        <span className="font-medium">{alert.device_name || '—'}</span>
                        {alert.site_name ? (
                          <span className="ml-1.5 text-xs text-subtle">{alert.site_name}</span>
                        ) : null}
                      </Td>
                      <Td onClick={() => openDetail(alert.id)} className="max-w-md cursor-pointer">
                        <span className="block truncate">{alert.title}</span>
                        {alert.occurrence_count > 1 ? (
                          <Badge tone="neutral" className="mt-1">
                            ×{alert.occurrence_count}
                          </Badge>
                        ) : null}
                      </Td>
                      <Td
                        align="right"
                        onClick={() => openDetail(alert.id)}
                        className="cursor-pointer whitespace-nowrap text-muted"
                      >
                        {formatRelative(alert.last_triggered_at)}
                      </Td>
                    </Tr>
                  ))
                ) : (
                  <EmptyRow
                    colSpan={6}
                    message={
                      <span className="flex flex-col items-center gap-2">
                        <CheckCircle2 className="size-6 text-ok" aria-hidden />
                        {t('alerts.noAlerts')}
                      </span>
                    }
                  />
                )}
              </TBody>
            </Table>

            {alerts.data ? (
              <Pagination
                total={alerts.data.total}
                limit={PAGE_SIZE}
                offset={offset}
                onChange={setOffset}
              />
            ) : null}
          </>
        )}
      </Card>

      <AlertDetailModal alertId={detailId} onClose={closeDetail} />
    </>
  )
}

function AlertDetailModal({ alertId, onClose }: { alertId: string | null; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { can } = useAuth()
  const alert = useAlert(alertId ?? undefined)
  const { acknowledge, resolve } = useAlertActions()
  const [note, setNote] = useState('')

  const detail = alert.data

  return (
    <Modal
      open={Boolean(alertId)}
      onClose={onClose}
      size="lg"
      title={detail?.title ?? t('alerts.title')}
      description={
        detail ? (
          <span className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={detail.severity} />
            <AlertStatusBadge status={detail.status} />
            {detail.device_name ? (
              <Link
                to={`/devices/${detail.device_id}`}
                className="text-xs font-medium text-brand hover:underline"
              >
                {detail.device_name}
              </Link>
            ) : null}
          </span>
        ) : undefined
      }
      footer={
        detail && detail.status !== 'resolved' && can('alert:acknowledge') ? (
          <>
            {detail.status === 'firing' ? (
              <Button
                loading={acknowledge.isPending}
                onClick={async () => {
                  try {
                    await acknowledge.mutateAsync({ id: detail.id, note })
                    setNote('')
                  } catch (error) {
                    toast.error(errorMessage(error))
                  }
                }}
              >
                {t('alerts.acknowledge')}
              </Button>
            ) : null}
            <Button
              variant="primary"
              loading={resolve.isPending}
              onClick={async () => {
                try {
                  await resolve.mutateAsync({ id: detail.id, note })
                  setNote('')
                  onClose()
                } catch (error) {
                  toast.error(errorMessage(error))
                }
              }}
            >
              {t('alerts.resolve')}
            </Button>
          </>
        ) : null
      }
    >
      {alert.isPending ? (
        <p className="py-8 text-center text-sm text-muted">{t('common.loading')}…</p>
      ) : alert.error ? (
        <ErrorState error={alert.error} />
      ) : detail ? (
        <div className="space-y-5">
          {detail.message ? <p className="text-sm text-content">{detail.message}</p> : null}

          <Card>
            <CardBody>
              <dl className="divide-y divide-line">
                <DetailRow label={t('alerts.source')}>
                  {t(
                    detail.source === 'device'
                      ? 'alerts.sourceDevice'
                      : detail.source === 'system'
                        ? 'alerts.sourceSystem'
                        : 'alerts.sourceRule',
                  )}
                </DetailRow>
                {detail.rule_name ? (
                  <DetailRow label={t('alerts.rule')}>{detail.rule_name}</DetailRow>
                ) : null}
                {detail.metric_key ? (
                  <DetailRow label={t('rules.metric')} mono>
                    {detail.metric_key}
                  </DetailRow>
                ) : null}
                {detail.code ? (
                  <DetailRow label={t('events.code')} mono>
                    {detail.code}
                  </DetailRow>
                ) : null}
                {detail.trigger_value !== null ? (
                  <DetailRow label={t('alerts.triggerValue')}>
                    {formatNumber(detail.trigger_value)}
                  </DetailRow>
                ) : null}
                {detail.threshold !== null ? (
                  <DetailRow label={t('alerts.threshold')}>
                    {formatNumber(detail.threshold)}
                  </DetailRow>
                ) : null}
                <DetailRow label={t('alerts.triggered')}>
                  {formatDateTime(detail.started_at)}
                </DetailRow>
                <DetailRow label={t('alerts.lastTriggered')}>
                  {formatDateTime(detail.last_triggered_at)}
                </DetailRow>
                <DetailRow label={t('alerts.occurrences')}>{detail.occurrence_count}</DetailRow>
                {detail.acknowledged_by_label ? (
                  <DetailRow label={t('alerts.acknowledged')}>
                    {t('alerts.acknowledgedBy', { who: detail.acknowledged_by_label })}
                  </DetailRow>
                ) : null}
              </dl>
            </CardBody>
          </Card>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
              {t('alerts.timeline')}
            </h3>
            <ol className="space-y-2 border-l border-line pl-4">
              {detail.events.map((event) => (
                <li key={event.id} className="relative">
                  <span
                    className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-brand"
                    aria-hidden
                  />
                  <p className="text-sm text-content">
                    {event.event_type}
                    {event.message ? <span className="text-muted"> — {event.message}</span> : null}
                  </p>
                  <p className="text-xs text-subtle">
                    {formatDateTime(event.created_at)}
                    {event.actor_label ? ` · ${event.actor_label}` : ''}
                  </p>
                </li>
              ))}
            </ol>
          </div>

          {detail.status !== 'resolved' && can('alert:acknowledge') ? (
            <TextArea
              label={t('alerts.note')}
              placeholder={t('alerts.notePlaceholder')}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          ) : detail.resolve_note ? (
            <p className="rounded-lg bg-surface-muted px-3 py-2 text-sm text-muted">
              {detail.resolve_note}
            </p>
          ) : null}
        </div>
      ) : null}
    </Modal>
  )
}
