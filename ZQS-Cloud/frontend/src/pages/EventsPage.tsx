import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useEventCodes, useEvents, useSites } from '@/lib/queries'
import { formatDateTime } from '@/lib/format'
import { useTimeRange } from '@/lib/useTimeRange'
import type { DeviceEvent } from '@/lib/types'
import {
  Badge,
  Card,
  EmptyRow,
  ErrorState,
  EventLevelBadge,
  Modal,
  PageHeader,
  Pagination,
  Select,
  SiteTreeSelect,
  TBody,
  THead,
  Table,
  Td,
  Th,
  TextInput,
  TimeRangePicker,
  Tr,
} from '@/components/ui'

const PAGE_SIZE = 30

/**
 * Everything the fleet reported, in one place.
 *
 * The device detail page already answers "what happened to this unit". It
 * cannot answer the question an operator actually starts with - "something
 * went wrong around four o'clock, where?" - because that needs every device at
 * once. Hence a page rather than another tab.
 *
 * Distinct from the audit log next to it: that records what *people* did
 * through the console, this records what *equipment* reported. Mixing them
 * would make both harder to read, because they are searched for different
 * reasons.
 */
export function EventsPage() {
  const { t } = useTranslation()
  const range = useTimeRange('24h')
  const sites = useSites()

  const [offset, setOffset] = useState(0)
  const [level, setLevel] = useState('')
  const [code, setCode] = useState('')
  const [siteId, setSiteId] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<DeviceEvent | null>(null)

  // Codes come from what actually arrived in the window, not from a fixed
  // list: they are the device vendor's codes, so any list shipped here would
  // be wrong for somebody.
  const codes = useEventCodes({ start: range.start, end: range.end })

  const events = useEvents({
    start: range.start,
    end: range.end,
    level: level || undefined,
    code: code || undefined,
    site_id: siteId || undefined,
    include_descendants: siteId ? true : undefined,
    search: search.trim() || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  function reset<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value)
      setOffset(0)
    }
  }

  return (
    <>
      <PageHeader
        title={t('events.title')}
        description={t('events.subtitle')}
        actions={<TimeRangePicker range={range} />}
      />

      <Card>
        <div className="grid gap-3 border-b border-line p-3 sm:grid-cols-2 lg:grid-cols-4">
          <SiteTreeSelect
            label={t('events.site')}
            sites={sites.data?.items ?? []}
            value={siteId}
            placeholder={t('common.all')}
            onChange={reset(setSiteId)}
          />
          <Select
            label={t('events.level')}
            value={level}
            placeholder={t('common.all')}
            onChange={(event) => reset(setLevel)(event.target.value)}
            options={['info', 'notice', 'warning', 'error', 'critical'].map((value) => ({
              value,
              label: t(`events.levels.${value}`),
            }))}
          />
          <Select
            label={t('events.code')}
            value={code}
            placeholder={t('common.all')}
            onChange={(event) => reset(setCode)(event.target.value)}
            options={(codes.data ?? []).map((item) => ({
              value: item.code,
              label: `${item.code} (${item.count})`,
            }))}
          />
          <TextInput
            label={t('events.search')}
            value={search}
            placeholder={t('events.searchPlaceholder')}
            onChange={(event) => reset(setSearch)(event.target.value)}
          />
        </div>

        {events.isError ? (
          <ErrorState error={events.error} onRetry={() => void events.refetch()} />
        ) : (
          <>
            <Table>
              <THead>
                <Th>{t('events.level')}</Th>
                <Th>{t('events.device')}</Th>
                <Th>{t('events.code')}</Th>
                <Th>{t('events.message')}</Th>
                <Th align="right">{t('common.time')}</Th>
              </THead>
              <TBody>
                {events.isPending ? (
                  <EmptyRow colSpan={5} message={`${t('common.loading')}…`} />
                ) : events.data && events.data.items.length > 0 ? (
                  events.data.items.map((event) => (
                    <Tr
                      key={event.id}
                      onClick={() => setSelected(event)}
                      className="cursor-pointer"
                    >
                      <Td>
                        <span className="flex items-center gap-1">
                          <EventLevelBadge level={event.level} />
                          {event.payload?.alarm_state === 'active' ? (
                            <Badge tone="critical">{t('events.alarmRaised')}</Badge>
                          ) : event.payload?.alarm_state === 'cleared' ? (
                            <Badge tone="ok">{t('events.alarmCleared')}</Badge>
                          ) : null}
                        </span>
                      </Td>
                      <Td>
                        <Link
                          to={`/devices/${event.device_id}`}
                          className="link"
                          onClick={(clicked) => clicked.stopPropagation()}
                        >
                          {event.device_name || event.device_external_id}
                        </Link>
                        {event.site_name ? (
                          <span className="ml-2 text-xs text-muted">{event.site_name}</span>
                        ) : null}
                      </Td>
                      <Td className="font-mono text-xs">{event.code || '—'}</Td>
                      <Td className="max-w-md truncate">{event.message || '—'}</Td>
                      <Td align="right" className="whitespace-nowrap text-muted">
                        {formatDateTime(event.ts)}
                      </Td>
                    </Tr>
                  ))
                ) : (
                  <EmptyRow colSpan={5} message={t('events.empty')} />
                )}
              </TBody>
            </Table>
            <Pagination
              total={events.data?.total ?? 0}
              limit={PAGE_SIZE}
              offset={offset}
              onChange={setOffset}
            />
          </>
        )}
      </Card>

      <Modal
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected?.code || t('events.title')}
      >
        {selected ? (
          <div className="space-y-3 text-sm">
            <p>{selected.message}</p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
              <dt className="text-muted">{t('events.device')}</dt>
              <dd className="font-mono">{selected.device_external_id}</dd>
              <dt className="text-muted">{t('events.site')}</dt>
              <dd>{selected.site_name ?? '—'}</dd>
              <dt className="text-muted">{t('common.time')}</dt>
              <dd>{formatDateTime(selected.ts)}</dd>
              <dt className="text-muted">{t('events.received')}</dt>
              <dd>{formatDateTime(selected.received_at)}</dd>
            </dl>
            {/* The payload is the device vendor's own structure, so it is
                shown raw rather than interpreted. Guessing at field names
                would be wrong for every vendor but one. */}
            {Object.keys(selected.payload ?? {}).length > 0 ? (
              <pre className="max-h-64 overflow-auto rounded bg-subtle p-3 text-xs">
                {JSON.stringify(selected.payload, null, 2)}
              </pre>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </>
  )
}
