import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import {
  Activity,
  BatteryCharging,
  Bell,
  Building2,
  CheckCircle2,
  Coins,
  Cpu,
  PiggyBank,
  Plug,
  Sun,
  WifiOff,
  Zap,
} from 'lucide-react'

import {
  useAlerts,
  useAlertSummary,
  useCapabilities,
  useCostOverview,
  useDevices,
  useFleetLive,
  useFleetStats,
  useHealth,
  useSites,
  useUiPreference,
} from '@/lib/queries'
import {
  formatCurrency,
  formatMeasurement,
  formatPercent,
  formatRelative,
  formatTime,
} from '@/lib/format'
import { useTimeRange } from '@/lib/useTimeRange'
import type { FleetLive, PowerFlow, SiteLive } from '@/lib/types'
import type { GlossaryId } from '@/lib/glossary'
import { SiteCostChart } from '@/components/charts/CostCharts'
import { SocGauge } from '@/components/charts/PowerGauge'
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SegmentedControl,
  SeverityBadge,
  Skeleton,
  StatTile,
  Table,
  TBody,
  Td,
  Term,
  Th,
  THead,
  TimeRangePicker,
  Tr,
} from '@/components/ui'

type View = 'energy' | 'fleet'

/**
 * The overview answers two different questions and they want different
 * layouts: "what is the energy doing right now" and "is the equipment
 * healthy". Rather than stack both and make each half a page of scrolling,
 * the page switches - and remembers which one this person opens it for.
 */
export function DashboardPage() {
  const { t } = useTranslation()
  const preference = useUiPreference<{ view: View }>('dashboard-view', {
    view: 'energy',
  })
  const view = preference.value.view

  return (
    <>
      <PageHeader
        title={t('dashboard.title')}
        description={t('dashboard.subtitle')}
        actions={
          <SegmentedControl<View>
            value={view}
            onChange={(next) => preference.save.mutate({ view: next })}
            options={[
              {
                value: 'energy',
                label: (
                  <span className="flex items-center gap-1.5">
                    <Zap className="size-3.5" />
                    {t('dashboard.viewEnergy')}
                  </span>
                ),
              },
              {
                value: 'fleet',
                label: (
                  <span className="flex items-center gap-1.5">
                    <Cpu className="size-3.5" />
                    {t('dashboard.viewFleet')}
                  </span>
                ),
              },
            ]}
          />
        }
      />

      {view === 'energy' ? <EnergyView /> : <FleetView />}
    </>
  )
}

// ---------------------------------------------------------------------------
// Energy view
// ---------------------------------------------------------------------------
function EnergyView() {
  const { t } = useTranslation()
  const live = useFleetLive()
  const costRange = useTimeRange('24h')
  const costs = useCostOverview({ start: costRange.start, end: costRange.end })

  if (live.error) {
    return <ErrorState error={live.error} onRetry={() => void live.refetch()} />
  }

  const data = live.data
  const currency = data?.mixed_currency ? undefined : data?.currency || undefined

  return (
    <>
      <PowerRow live={data} loading={live.isPending} />

      <div className="mt-5 grid gap-5 xl:grid-cols-3">
        <Card>
          <CardHeader
            title={<Term id="soc">{t('storage.soc')}</Term>}
            description={t('dashboard.socHint')}
          />
          <CardBody className="flex flex-col items-center justify-center gap-3">
            {live.isPending ? (
              <Skeleton className="h-32 w-32 rounded-full" />
            ) : (
              <>
                <SocGauge
                  percent={data?.battery_soc_percent ?? null}
                  stale={data?.totals.is_stale ?? true}
                />
                <p className="text-center text-xs text-subtle">
                  {data?.battery_soc_percent === null || data === undefined
                    ? t('dashboard.noBattery')
                    : t('dashboard.socWeighted')}
                </p>
              </>
            )}
          </CardBody>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader
            title={t('dashboard.todayTitle')}
            description={t('dashboard.todayHint')}
          />
          <CardBody>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile
                label={t('storage.consumption')}
                value={
                  live.isPending ? '…' : formatMeasurement(data?.today_load_kwh, 'kWh', 0)
                }
                icon={<Plug className="size-4" />}
              />
              <StatTile
                label={<Term id="pv">{t('storage.generation')}</Term>}
                value={
                  live.isPending ? '…' : formatMeasurement(data?.today_pv_kwh, 'kWh', 0)
                }
                accent="warning"
                icon={<Sun className="size-4" />}
              />
              <StatTile
                label={<Term id="tariff">{t('storage.cost')}</Term>}
                value={
                  live.isPending
                    ? '…'
                    : formatCurrency(data?.today_energy_cost, currency)
                }
                icon={<Coins className="size-4" />}
              />
              <StatTile
                label={t('storage.savings')}
                value={
                  live.isPending
                    ? '…'
                    : formatCurrency(data?.today_estimated_savings, currency)
                }
                accent={(data?.today_estimated_savings ?? 0) < 0 ? 'critical' : 'ok'}
                hint={
                  (data?.today_estimated_savings ?? 0) < 0
                    ? t('dashboard.savingsNegative')
                    : undefined
                }
                icon={<PiggyBank className="size-4" />}
              />
            </div>
            {data?.mixed_currency ? (
              <p className="mt-3 rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">
                {t('dashboard.mixedCurrency')}
              </p>
            ) : null}
          </CardBody>
        </Card>
      </div>

      <SiteLiveTable live={data} loading={live.isPending} />

      <Card className="mt-5">
        <CardHeader
          title={t('dashboard.costTitle')}
          description={t('dashboard.costHint')}
          actions={<TimeRangePicker range={costRange} />}
        />
        <CardBody>
          {costs.isPending ? (
            <Skeleton className="h-64" />
          ) : costs.error ? (
            <ErrorState error={costs.error} onRetry={() => void costs.refetch()} />
          ) : (
            <SiteCostChart
              sites={costs.data?.sites ?? []}
              currency={costs.data?.mixed_currency ? undefined : costs.data?.currency}
            />
          )}
        </CardBody>
      </Card>
    </>
  )
}

/**
 * The four flows as they stand right now.
 *
 * Sign carries meaning and the label says which way, because "-42 kW" on its
 * own is ambiguous to anyone who has not memorised the convention: grid
 * positive is importing, battery positive is discharging.
 */
function PowerRow({ live, loading }: { live?: FleetLive; loading: boolean }) {
  const { t } = useTranslation()
  const flow = live?.totals
  const stale = flow?.is_stale ?? true

  const tiles: {
    key: keyof Pick<PowerFlow, 'grid_kw' | 'pv_kw' | 'battery_kw' | 'load_kw'>
    label: string
    term?: GlossaryId
    icon: typeof Zap
    accent: 'brand' | 'warning' | 'info' | 'neutral'
    direction?: (value: number) => string
  }[] = [
    {
      key: 'grid_kw',
      label: t('storage.grid'),
      icon: Zap,
      accent: 'info',
      direction: (value) =>
        value > 0 ? t('storage.importing') : value < 0 ? t('storage.exporting') : t('storage.idle'),
    },
    { key: 'pv_kw', label: t('storage.pv'), term: 'pv', icon: Sun, accent: 'warning' },
    {
      key: 'battery_kw',
      label: t('storage.battery'),
      term: 'bess',
      icon: BatteryCharging,
      accent: 'brand',
      direction: (value) =>
        value > 0
          ? t('storage.discharging')
          : value < 0
            ? t('storage.charging')
            : t('storage.idle'),
    },
    { key: 'load_kw', label: t('storage.load'), icon: Plug, accent: 'neutral' },
  ]

  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[92px]" />
        ))}
      </div>
    )
  }

  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((tile) => {
          const value = flow?.[tile.key] ?? null
          return (
            <StatTile
              key={tile.key}
              label={tile.term ? <Term id={tile.term}>{tile.label}</Term> : tile.label}
              // Magnitude in the number, direction in the hint: a bare minus
              // sign is only readable to someone who knows the convention.
              value={
                value === null ? '—' : formatMeasurement(Math.abs(value), 'kW', 1)
              }
              accent={tile.accent}
              icon={<tile.icon className="size-4" />}
              hint={
                value !== null && tile.direction ? tile.direction(value) : undefined
              }
            />
          )
        })}
      </div>

      <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-subtle">
        {stale ? (
          <Badge tone="warning">{t('storage.stale')}</Badge>
        ) : (
          <Badge tone="ok">{t('dashboard.liveNow')}</Badge>
        )}
        {live?.as_of ? t('storage.asOf', { time: formatTime(live.as_of) }) : null}
        {live ? (
          <span>
            {t('dashboard.reportingSites', {
              reporting: live.reporting_site_count,
              total: live.site_count,
            })}
          </span>
        ) : null}
        <MqttNotice />
      </p>
    </>
  )
}

/**
 * Says why the live figures are not moving, when the reason is "this
 * deployment has no broker".
 *
 * Without it, a demo install looks broken: every tile reads stale and nothing
 * on the page explains that live ingest was never switched on.
 */
function MqttNotice() {
  const { t } = useTranslation()
  const capabilities = useCapabilities()
  if (capabilities.data?.mqtt_enabled !== false) return null
  return <Badge tone="neutral">{t('dashboard.mqttDisabled')}</Badge>
}

function SiteLiveTable({ live, loading }: { live?: FleetLive; loading: boolean }) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <Card className="mt-5">
      <CardHeader title={t('dashboard.sitesLive')} description={t('dashboard.sitesLiveHint')} />
      <Table>
        <THead>
          <Th>{t('sites.site')}</Th>
          <Th align="right">{t('storage.grid')}</Th>
          <Th align="right">
            <Term id="pv">{t('storage.pv')}</Term>
          </Th>
          <Th align="right">{t('storage.battery')}</Th>
          <Th align="right">
            <Term id="soc">SOC</Term>
          </Th>
          <Th align="right">{t('dashboard.online')}</Th>
          <Th align="right">{t('dashboard.openAlerts')}</Th>
          <Th align="right">{t('dashboard.todayCost')}</Th>
        </THead>
        <TBody>
          {loading ? (
            <tr>
              <td colSpan={8} className="px-4 py-8 text-center text-sm text-muted">
                {t('common.loading')}…
              </td>
            </tr>
          ) : (live?.sites.length ?? 0) === 0 ? (
            <tr>
              <td colSpan={8} className="px-4 py-8 text-center text-sm text-muted">
                {t('sites.noSites')}
              </td>
            </tr>
          ) : (
            live?.sites.map((site) => (
              <SiteLiveRow
                key={site.site_id}
                site={site}
                onOpen={() => navigate(`/storage?site=${site.site_id}`)}
              />
            ))
          )}
        </TBody>
      </Table>
    </Card>
  )
}

function SiteLiveRow({ site, onOpen }: { site: SiteLive; onOpen: () => void }) {
  const { t } = useTranslation()
  const power = (value: number | null) =>
    value === null ? '—' : formatMeasurement(Math.abs(value), 'kW', 1)

  return (
    <Tr onClick={onOpen}>
      <Td>
        <span
          className="flex items-center gap-1.5"
          style={{ paddingLeft: `${site.depth * 12}px` }}
        >
          <Building2 className="size-3.5 shrink-0 text-subtle" aria-hidden />
          <span className="font-medium">{site.site_name}</span>
          {site.is_stale ? (
            <Badge tone="neutral">{t('storage.stale')}</Badge>
          ) : null}
        </span>
      </Td>
      <Td align="right" className="tnum">
        {power(site.flow.grid_kw)}
        {site.flow.grid_kw !== null && site.flow.grid_kw < 0 ? (
          <span className="ml-1 text-xs text-ok">↑</span>
        ) : null}
      </Td>
      <Td align="right" className="tnum text-muted">
        {power(site.flow.pv_kw)}
      </Td>
      <Td align="right" className="tnum text-muted">
        {power(site.flow.battery_kw)}
        {site.flow.battery_kw !== null && site.flow.battery_kw !== 0 ? (
          <span className="ml-1 text-xs text-subtle">
            {site.flow.battery_kw > 0 ? '↑' : '↓'}
          </span>
        ) : null}
      </Td>
      <Td align="right" className="tnum">
        {formatPercent(site.flow.battery_soc_percent, { alreadyPercent: true, decimals: 0 })}
      </Td>
      <Td align="right" className="tnum text-muted">
        <Badge tone={site.online_count === site.device_count ? 'ok' : 'neutral'}>
          {site.online_count}/{site.device_count}
        </Badge>
      </Td>
      <Td align="right">
        {site.open_alert_count > 0 ? (
          <Badge tone="critical">{site.open_alert_count}</Badge>
        ) : (
          <span className="text-subtle">—</span>
        )}
      </Td>
      <Td align="right" className="tnum">
        {formatCurrency(site.today_energy_cost, site.currency || undefined)}
      </Td>
    </Tr>
  )
}

// ---------------------------------------------------------------------------
// Fleet view
// ---------------------------------------------------------------------------
function FleetView() {
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
                    {/* "disabled" is deliberately neutral, not a warning: a
                        dependency this deployment does not use is not a
                        fault, and colouring it as one teaches people to
                        ignore the card that a real outage appears on. */}
                    <Badge
                      tone={
                        component.state === 'disabled'
                          ? 'neutral'
                          : component.ok
                            ? 'ok'
                            : 'critical'
                      }
                    >
                      {component.state === 'disabled'
                        ? t('dashboard.componentDisabled')
                        : component.ok
                          ? 'OK'
                          : component.detail || 'error'}
                    </Badge>
                  </div>
                ))
              ) : (
                <p className="text-sm text-muted">{t('common.noData')}</p>
              )}
              <p className="hint">{t('dashboard.healthHint')}</p>
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
