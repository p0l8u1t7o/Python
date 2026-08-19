import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { Activity, Bell, Building2, CheckCircle2, Cpu, WifiOff } from 'lucide-react'

import { useAlerts, useAlertSummary, useFleetStats, useHealth, useSites } from '@/lib/queries'
import { formatRelative } from '@/lib/format'
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
  Th,
  THead,
  Tr,
} from '@/components/ui'

export function DashboardPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const fleet = useFleetStats()
  const summary = useAlertSummary()
  const sites = useSites()
  const health = useHealth()
  const recentAlerts = useAlerts({ open_only: true, limit: 8 })

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
            ) : sites.data && sites.data.items.length > 0 ? (
              <ul className="divide-y divide-line">
                {sites.data.items.slice(0, 6).map((site) => (
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
                        {site.open_alert_count > 0 ? (
                          <Badge tone="critical">{site.open_alert_count}</Badge>
                        ) : null}
                        <Badge tone={site.online_count === site.device_count ? 'ok' : 'neutral'}>
                          {site.online_count}/{site.device_count}
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
                      {component.name.replace('_', ' ')}
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
