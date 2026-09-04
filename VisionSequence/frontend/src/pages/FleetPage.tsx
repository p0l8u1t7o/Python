/**
 * Fleet board `/fleet`: every station's yield on one screen.
 *
 * Read-only by design — this instance polls the others and shows numbers, it never pushes flows or
 * commands. A station that cannot be reached keeps its last figures but is clearly marked offline
 * with their age: on a shop floor a stale number that looks live is worse than no number.
 */
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ExternalLink, Lock, MonitorPlay, RefreshCw } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'

import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, CardBody, EmptyRow, ErrorState, LoadingState, PageHeader, TBody, THead, Table, Td, Th, Tile, Tr } from '@/components/ui'
import { api } from '@/lib/api'
import { useAuth } from '@/providers/AuthProvider'

interface FleetFlow {
  id: number
  name: string
  total: number
  ok: number
  ng: number
  failed: number
  yield: number | null
  last_status: string
  continuous: boolean
}

interface FleetStation {
  id: number
  name: string
  base_url: string
  note: string
  online: boolean
  error: string
  age_s: number | null
  stale: boolean
  station_id: string
  version: string
  locked: boolean
  totals: { total?: number; ok?: number; ng?: number; failed?: number; yield?: number | null }
  flows: FleetFlow[]
}

interface Board {
  items: FleetStation[]
  totals: { total: number; ok: number; ng: number; failed: number; stations: number; online: number; yield: number | null }
  interval_s: number
}

function age(seconds: number | null, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (seconds === null) return '—'
  if (seconds < 90) return t('fleet.agoSeconds', { count: Math.round(seconds) })
  if (seconds < 5400) return t('fleet.agoMinutes', { count: Math.round(seconds / 60) })
  return t('fleet.agoHours', { count: Math.round(seconds / 3600) })
}

export function FleetPage() {
  const { t } = useTranslation()
  const auth = useAuth()
  const board = useQuery({
    queryKey: ['fleet'],
    queryFn: () => api.get<Board>('/vision/fleet'),
    refetchInterval: 10_000,
  })

  const totals = board.data?.totals
  return (
    <Page>
      <PageHeader title={t('fleet.title')} description={t('fleet.subtitle')}
        actions={
          <div className="flex gap-2">
            <Button size="sm" icon={<RefreshCw size={14} />} loading={board.isFetching} onClick={() => void board.refetch()}>{t('common.refresh')}</Button>
            {auth.isAdmin ? <Link to="/integration/stations" className="btn btn-sm">{t('fleet.manage')}</Link> : null}
          </div>
        } />
      {board.isPending ? (
        <LoadingState />
      ) : board.isError ? (
        <ErrorState error={board.error} onRetry={() => void board.refetch()} />
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
            <Tile label={t('fleet.stations')} value={`${totals?.online ?? 0} / ${totals?.stations ?? 0}`} />
            <Tile label={t('fleet.total')} value={totals?.total ?? 0} />
            <Tile label={t('fleet.ng')} value={(totals?.ng ?? 0) + (totals?.failed ?? 0)} tone={totals?.ng ? 'warning' : ''} />
            <Tile label={t('fleet.yield')} value={totals?.yield === null || totals?.yield === undefined ? '—' : `${totals.yield}%`} tone="ok" />
            <Tile label={t('fleet.interval')} value={`${board.data.interval_s}s`} />
          </div>

          {board.data.items.length === 0 ? (
            <Card><CardBody className="text-sm text-muted">
              {t('fleet.empty')} {auth.isAdmin ? <Link to="/integration/stations" className="underline">{t('fleet.manage')}</Link> : null}
            </CardBody></Card>
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {board.data.items.map((station) => (
                <Card key={station.id} testId={`fleet-station-${station.id}`}>
                  <CardBody>
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <MonitorPlay size={16} className={station.online ? 'text-ok' : 'text-critical'} aria-hidden />
                      <span className="font-medium">{station.name}</span>
                      {station.station_id ? <code className="font-mono text-[11px] text-muted">{station.station_id}</code> : null}
                      {station.locked ? <Badge tone="info"><Lock size={10} /> {t('fleet.locked')}</Badge> : null}
                      {station.online ? null : <Badge tone="critical">{t('fleet.offline')}</Badge>}
                      {station.stale ? <span className="text-xs text-warning">{t('fleet.lastSeen', { when: age(station.age_s, t) })}</span> : null}
                      <a href={station.base_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs text-muted hover:underline">
                        {t('fleet.open')} <ExternalLink size={12} />
                      </a>
                    </div>
                    {station.error ? <p className="mb-2 text-xs text-critical">{station.error}</p> : null}
                    <div className="mb-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
                      <span><span className="text-muted">{t('fleet.total')} </span><span className="tnum font-medium">{station.totals.total ?? 0}</span></span>
                      <span><span className="text-muted">{t('fleet.ng')} </span><span className="tnum font-medium text-warning">{(station.totals.ng ?? 0) + (station.totals.failed ?? 0)}</span></span>
                      <span><span className="text-muted">{t('fleet.yield')} </span><span className="tnum font-medium text-ok">{station.totals.yield === null || station.totals.yield === undefined ? '—' : `${station.totals.yield}%`}</span></span>
                      {station.version ? <span className="text-xs text-muted">v{station.version}</span> : null}
                    </div>
                    <Table>
                      <THead>
                        <Th>{t('fleet.cols.flow')}</Th>
                        <Th align="right">{t('fleet.cols.total')}</Th>
                        <Th align="right">{t('fleet.cols.ng')}</Th>
                        <Th align="right">{t('fleet.cols.yield')}</Th>
                      </THead>
                      <TBody>
                        {station.flows.length === 0 ? (
                          <EmptyRow colSpan={4} message={t('fleet.noFlows')} />
                        ) : (
                          station.flows.slice(0, 6).map((flow) => (
                            <Tr key={flow.id}>
                              <Td className="max-w-[220px] truncate text-xs">
                                {flow.continuous ? <span className="mr-1 inline-block size-1.5 rounded-full bg-ok" aria-hidden /> : null}
                                {flow.name}
                              </Td>
                              <Td align="right" className="tnum text-xs">{flow.total}</Td>
                              <Td align="right" className="tnum text-xs text-warning">{flow.ng + flow.failed}</Td>
                              <Td align="right" className="tnum text-xs">{flow.yield === null ? '—' : `${flow.yield}%`}</Td>
                            </Tr>
                          ))
                        )}
                      </TBody>
                    </Table>
                  </CardBody>
                </Card>
              ))}
            </div>
          )}
          <p className="mt-3 text-xs text-muted">{t('fleet.footnote')}</p>
        </>
      )}
    </Page>
  )
}
