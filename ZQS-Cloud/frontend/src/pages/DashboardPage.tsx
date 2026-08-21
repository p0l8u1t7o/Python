import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { Activity, Bell, Building2, CheckCircle2, Cpu, WifiOff } from 'lucide-react'

import {
  useAlerts,
  useAlertSummary,
  useDevices,
  useFleetStats,
  useHealth,
  useSites,
} from '@/lib/queries'
import { formatRelative } from '@/lib/format'
import type { GlossaryId } from '@/lib/glossary'
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SeverityBadge,
  Skeleton,
  StatTile,
  Table,
  TBody,
  Td,
  Term,
  Th,
  THead,
  Tr,
} from '@/components/ui'

export function DashboardPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const fleet = useFleetStats()
  const summary = useAlertSummary()
  // Subtree totals, so a plant's card counts its workshops' devices too.
  const sites = useSites({ includeDescendants: true })
  const health = useHealth()
  const recentAlerts = useAlerts({ open_only: true, limit: 8 })
  const unassigned = useDevices({ unassigned_only: true, limit: 1 })

  const groups = (sites.data?.items ?? []).filter((site) => site.depth === 0)
  const unassignedCount = unassigned.data?.total ?? 0

  return (
    <>
      <PageHeader title={t('dashboard.title')} description={t('dashboard.subtitle')} />

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {fleet.isPending ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[92px]" />)
        ) : fleet.data ? (
          <>
            <StatTile
              label={t('dashboard.totalDevices')}
              value={fleet.data.total_devices}
              icon={<Cpu className="size-4" />}
              hint={t('dashboard.devicesOnline', {
                online: fleet.data.online,
                total: fleet.data.total_devices,
              })}
              onClick={() => navigate('/devices')}
            />
            <StatTile
              label={t('dashboard.online')}
              value={fleet.data.online}
              accent="ok"
              icon={<Activity className="size-4" />}
              onClick={() => navigate('/devices?status=online')}
            />
            <StatTile
              label={t('dashboard.offline')}
              value={fleet.data.offline}
              accent={fleet.data.offline > 0 ? 'critical' : 'neutral'}
              icon={<WifiOff className="size-4" />}
              onClick={() => navigate('/devices?status=offline')}
            />
            <StatTile
              label={t('dashboard.openAlerts')}
              value={summary.data?.total_open ?? fleet.data.open_alerts}
              accent={
                (summary.data?.by_severity.critical ?? 0) > 0
                  ? 'critical'
                  : (summary.data?.total_open ?? 0) > 0
                    ? 'warning'
                    : 'ok'
              }
              icon={<Bell className="size-4" />}
              onClick={() => navigate('/alerts')}
            />
          </>
        ) : (
          <div className="col-span-full">
            <ErrorState error={fleet.error} onRetry={() => void fleet.refetch()} />
          </div>
        )}
      </div>

      {groups.length > 0 || unassignedCount > 0 ? (
        <Card className="mb-5">
          <CardHeader
            title={t('dashboard.byGroup')}
            actions={
              <Link to="/sites" className="text-xs font-medium text-brand hover:underline">
                {t('dashboard.viewAll')}
              </Link>
            }
          />
          <CardBody>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {groups.map((site) => (
                <Link
                  key={site.id}
                  to={`/devices?site=${site.id}`}
                  className="rounded-lg border border-line p-3 transition-colors hover:bg-surface-muted/60"
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium">{site.name}</span>
                      <span className="block truncate text-xs text-subtle">
                        {site.child_count > 0
                          ? t('dashboard.groupChildren', { count: site.child_count })
                          : site.address || site.code}
                      </span>
                    </span>
                    {site.total_open_alert_count > 0 ? (
                      <Badge tone="critical">{site.total_open_alert_count}</Badge>
                    ) : null}
                  </span>
                  <span className="mt-2 flex items-baseline gap-1.5">
                    <span className="tnum text-xl font-semibold">{site.total_online_count}</span>
                    <span className="tnum text-sm text-subtle">/ {site.total_device_count}</span>
                    <span className="ml-auto text-xs text-subtle">{t('dashboard.online')}</span>
                  </span>
                </Link>
              ))}

              {unassignedCount > 0 ? (
                <Link
                  to="/devices?unassigned=1"
                  className="rounded-lg border border-dashed border-line p-3 transition-colors hover:bg-surface-muted/60"
                >
                  <span className="block truncate text-sm font-medium italic">
                    {t('sites.unassigned')}
                  </span>
                  <span className="block truncate text-xs text-subtle">
                    {t('sites.unassignedHint')}
                  </span>
                  <span className="mt-2 block tnum text-xl font-semibold">{unassignedCount}</span>
                </Link>
              ) : null}
            </div>
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title={t('dashboard.recentAlerts')}
            actions={
              <Link to="/alerts" className="text-xs font-medium text-brand hover:underline">
                {t('dashboard.viewAll')}
              </Link>
            }
          />
          {recentAlerts.isPending ? (
            <LoadingState />
          ) : recentAlerts.error ? (
            <ErrorState error={recentAlerts.error} onRetry={() => void recentAlerts.refetch()} />
          ) : recentAlerts.data && recentAlerts.data.items.length > 0 ? (
            <Table>
              <THead>
                <Th>{t('common.status')}</Th>
                <Th>{t('devices.device')}</Th>
                <Th>{t('alerts.title')}</Th>
                <Th align="right">{t('alerts.triggered')}</Th>
              </THead>
              <TBody>
                {recentAlerts.data.items.map((alert) => (
                  <Tr key={alert.id} onClick={() => navigate(`/alerts?alert=${alert.id}`)}>
                    <Td>
                      <SeverityBadge severity={alert.severity} />
                    </Td>
                    <Td>
                      <span className="font-medium">{alert.device_name || '—'}</span>
                      {alert.site_name ? (
                        <span className="ml-1.5 text-xs text-subtle">{alert.site_name}</span>
                      ) : null}
                    </Td>
                    <Td className="max-w-sm truncate">{alert.title}</Td>
                    <Td align="right" className="whitespace-nowrap text-muted">
                      {formatRelative(alert.started_at)}
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          ) : (
            <EmptyState
              icon={<CheckCircle2 className="size-6 text-ok" />}
              title={t('dashboard.noAlerts')}
            />
          )}
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader title={t('dashboard.sitesOverview')} />
            {sites.isPending ? (
              <LoadingState />
            ) : groups.length > 0 ? (
              <ul className="divide-y divide-line">
                {groups.slice(0, 6).map((site) => (
                  <li key={site.id}>
                    <Link
                      to={`/storage?site=${site.id}`}
                      className="flex items-center justify-between gap-3 px-4 py-3 transition-colors hover:bg-surface-muted/60"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">{site.name}</span>
                        <span className="block truncate text-xs text-subtle">
                          {site.address || site.code}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-1.5">
                        {site.total_open_alert_count > 0 ? (
                          <Badge tone="critical">{site.total_open_alert_count}</Badge>
                        ) : null}
                        <Badge
                          tone={
                            site.total_online_count === site.total_device_count ? 'ok' : 'neutral'
                          }
                        >
                          {site.total_online_count}/{site.total_device_count}
                        </Badge>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={<Building2 className="size-6" />}
                title={t('sites.noSites')}
                action={
                  <Link to="/sites" className="text-sm font-medium text-brand hover:underline">
                    {t('sites.create')}
                  </Link>
                }
              />
            )}
          </Card>

          <Card>
            <CardHeader title={t('dashboard.systemHealth')} />
            <CardBody className="space-y-2">
              {health.isPending ? (
                <Skeleton className="h-16" />
              ) : health.data ? (
                health.data.components.map((component) => (
                  <div
                    key={component.name}
                    className="flex items-center justify-between gap-3 text-sm"
                  >
                    <span className="capitalize text-muted">
                      {/* A component name only helps if you know what the
                          component is - which is exactly the question a red
                          badge next to "message bus" provokes. */}
                      <ComponentName name={component.name} />
                    </span>
                    <Badge tone={component.ok ? 'ok' : 'critical'}>
                      {component.ok ? 'OK' : component.detail || 'error'}
                    </Badge>
                  </div>
                ))
              ) : (
                <p className="text-sm text-muted">{t('common.noData')}</p>
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  )
}

/**
 * A health component's name, with a glossary bubble where we have one.
 *
 * Names come from the API, so anything unrecognised falls through to plain
 * text rather than crashing the card.
 */
const HEALTH_TERMS: Record<string, GlossaryId> = {
  mqtt: 'mqtt',
  message_bus: 'ingestor',
}

function ComponentName({ name }: { name: string }) {
  const label = name.replace('_', ' ')
  const term = HEALTH_TERMS[name]
  return term ? <Term id={term}>{label}</Term> : <>{label}</>
}
