import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  BatteryCharging,
  Coins,
  History,
  Landmark,
  PiggyBank,
  PlayCircle,
  Radio,
  RefreshCw,
  Sun,
  Zap,
} from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import {
  useCostBreakdown,
  useDemandResponse,
  useDemandResponseMutations,
  useDispatchPreview,
  useEmsMutations,
  useEnergyAssets,
  useEnergyIntervals,
  useEnergySummary,
  useOperatingSessions,
  useSessionSummary,
  useSiteInvestment,
  useSiteOverview,
  useSites,
  useStoragePlan,
  useStoragePlans,
} from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import {
  formatCurrency,
  formatDateTime,
  formatDuration,
  formatMeasurement,
  formatNumber,
  formatPercent,
  formatTime,
} from '@/lib/format'
import { useTimeRange } from '@/lib/useTimeRange'
import { CostChart, EnergyBalanceChart, SocChart } from '@/components/charts/EnergyCharts'
import { CostSourceChart } from '@/components/charts/CostCharts'
import { PowerFlowDiagram } from '@/components/charts/PowerFlowDiagram'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  DetailRow,
  DeviceIcon,
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  PageHeader,
  Select,
  SiteTreeSelect,
  StatTile,
  TBody,
  THead,
  Table,
  Td,
  Term,
  TextInput,
  Th,
  TimeRangePicker,
  Tr,
} from '@/components/ui'

/**
 * One icon per strategy. Chosen so the shapes differ at a glance rather than
 * being literal: a flat-topped curve for peak shaving and a two-way arrow for
 * arbitrage are told apart instantly, where two battery variants would not be.
 */
export function StoragePage() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const range = useTimeRange('24h')

  const sites = useSites()
  const siteId = searchParams.get('site') ?? sites.data?.items[0]?.id ?? ''

  // Pin the first site into the URL so a reload and a shared link agree.
  useEffect(() => {
    if (!searchParams.get('site') && sites.data?.items[0]) {
      const next = new URLSearchParams(searchParams)
      next.set('site', sites.data.items[0].id)
      setSearchParams(next, { replace: true })
    }
  }, [sites.data, searchParams, setSearchParams])

  const overview = useSiteOverview(siteId || undefined)
  const assets = useEnergyAssets(siteId || undefined)
  const plan = useStoragePlan(siteId || undefined)
  const intervals = useEnergyIntervals(siteId || undefined, {
    start: range.start,
    end: range.end,
  })
  const summary = useEnergySummary(siteId || undefined, { start: range.start, end: range.end })
  const { rebuildIntervals } = useEmsMutations()
  const toast = useToast()

  if (sites.isPending) return <LoadingState />
  if (sites.error) return <ErrorState error={sites.error} onRetry={() => void sites.refetch()} />
  if (!sites.data || sites.data.items.length === 0) {
    return (
      <>
        <PageHeader title={t('storage.title')} description={t('storage.subtitle')} />
        <Card>
          <EmptyState icon={<BatteryCharging className="size-6" />} title={t('storage.noSites')} />
        </Card>
      </>
    )
  }

  const currency = summary.data?.currency || undefined
  const hasAssets = (assets.data?.length ?? 0) > 0

  return (
    <>
      <PageHeader
        title={<Term id="btm">{t('storage.title')}</Term>}
        description={t('storage.subtitle')}
        actions={
          <>
            <SiteTreeSelect
              sites={sites.data.items}
              value={siteId}
              onChange={(value) => {
                if (!value) return
                const next = new URLSearchParams(searchParams)
                next.set('site', value)
                setSearchParams(next, { replace: true })
              }}
              className="w-56"
            />
            <TimeRangePicker range={range} />
            {can('ems:write') ? <PlanBindPicker siteId={siteId} /> : null}
          </>
        }
      />

      {!hasAssets && !assets.isPending ? (
        <Card className="mb-5">
          <EmptyState
            icon={<Zap className="size-6" />}
            title={t('storage.notConfigured')}
            description={t('storage.notConfiguredHint')}
          />
        </Card>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title={t('storage.powerFlow')}
            description={
              overview.data?.flow.as_of
                ? t('storage.asOf', { time: formatTime(overview.data.flow.as_of) })
                : undefined
            }
            actions={
              overview.data?.flow.is_stale ? (
                <Badge tone="warning">{t('storage.stale')}</Badge>
              ) : null
            }
          />
          <CardBody>
            {overview.isPending ? (
              <LoadingState />
            ) : overview.error ? (
              <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
            ) : overview.data ? (
              <PowerFlowDiagram flow={overview.data.flow} />
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t('storage.today')} />
          <CardBody className="space-y-3">
            {overview.data ? (
              <dl className="divide-y divide-line">
                <DetailRow label={t('storage.gridImport')}>
                  {formatMeasurement(overview.data.today.grid_import_kwh, 'kWh', 1)}
                </DetailRow>
                <DetailRow label={t('storage.gridExport')}>
                  {formatMeasurement(overview.data.today.grid_export_kwh, 'kWh', 1)}
                </DetailRow>
                <DetailRow label={<Term id="pv">{t('storage.generation')}</Term>}>
                  {formatMeasurement(overview.data.today.pv_kwh, 'kWh', 1)}
                </DetailRow>
                <DetailRow label={t('storage.consumption')}>
                  {formatMeasurement(overview.data.today.load_kwh, 'kWh', 1)}
                </DetailRow>
                <DetailRow label={<Term id="dod">{t('storage.batteryDischarge')}</Term>}>
                  {formatMeasurement(overview.data.today.battery_discharge_kwh, 'kWh', 1)}
                </DetailRow>
                <DetailRow label={<Term id="peakDemand">{t('storage.peakDemand')}</Term>}>
                  {formatMeasurement(overview.data.today.peak_import_kw, 'kW', 1)}
                </DetailRow>
                <DetailRow label={<Term id="tariff">{t('storage.cost')}</Term>}>
                  {formatCurrency(overview.data.today.energy_cost, overview.data.today.currency)}
                </DetailRow>
                <DetailRow label={t('storage.savings')}>
                  <span className="text-ok">
                    {formatCurrency(
                      overview.data.today.estimated_savings,
                      overview.data.today.currency,
                    )}
                  </span>
                </DetailRow>
              </dl>
            ) : (
              <LoadingState />
            )}
          </CardBody>
        </Card>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label={<Term id="selfConsumption">{t('storage.selfConsumption')}</Term>}
          value={formatPercent(summary.data?.self_consumption_ratio)}
          hint={t('storage.selfConsumptionHint')}
          accent="warning"
          icon={<Sun className="size-4" />}
        />
        <StatTile
          label={<Term id="selfSufficiency">{t('storage.selfSufficiency')}</Term>}
          value={formatPercent(summary.data?.self_sufficiency_ratio)}
          hint={t('storage.selfSufficiencyHint')}
          accent="brand"
          icon={<BatteryCharging className="size-4" />}
        />
        <StatTile
          label={t('storage.cost')}
          value={formatCurrency(summary.data?.energy_cost, currency)}
          accent="neutral"
          icon={<Coins className="size-4" />}
        />
        <StatTile
          label={t('storage.savings')}
          value={formatCurrency(summary.data?.estimated_savings, currency)}
          hint={t('storage.savingsHint')}
          accent="ok"
          icon={<PiggyBank className="size-4" />}
        />
      </div>

      <Card className="mt-5">
        <CardHeader
          title={<Term id="kwVsKwh">{t('storage.intervalChart')}</Term>}
          description={
            summary.data
              ? `${formatMeasurement(summary.data.load_kwh, 'kWh', 1)} · ${t('storage.consumption')}`
              : undefined
          }
          actions={
            can('ems:write') ? (
              <Button
                size="sm"
                icon={<RefreshCw className="size-3.5" />}
                loading={rebuildIntervals.isPending}
                onClick={async () => {
                  try {
                    await rebuildIntervals.mutateAsync({
                      siteId,
                      start: range.start,
                      end: range.end,
                    })
                    toast.success(t('storage.rebuilt'))
                  } catch (error) {
                    toast.error(errorMessage(error))
                  }
                }}
              >
                {t('storage.rebuild')}
              </Button>
            ) : null
          }
        />
        <CardBody>
          {intervals.isPending ? (
            <LoadingState />
          ) : intervals.error ? (
            <ErrorState error={intervals.error} onRetry={() => void intervals.refetch()} />
          ) : (intervals.data?.length ?? 0) === 0 ? (
            <EmptyState title={t('storage.noIntervals')} />
          ) : (
            <EnergyBalanceChart intervals={intervals.data ?? []} spanSeconds={range.seconds} />
          )}
        </CardBody>
      </Card>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title={<Term id="soc">{t('storage.socChart')}</Term>} />
          <CardBody>
            <SocChart
              intervals={intervals.data ?? []}
              spanSeconds={range.seconds}
              minSoc={plan.data?.min_soc_percent ?? null}
              reserve={plan.data?.backup_reserve_percent ?? null}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t('storage.costChart')} />
          <CardBody>
            <CostChart
              intervals={intervals.data ?? []}
              spanSeconds={range.seconds}
              currency={currency}
            />
          </CardBody>
        </Card>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <CostBreakdownCard
          siteId={siteId}
          start={range.start}
          end={range.end}
          fallbackCurrency={currency}
        />
        <SessionsCard siteId={siteId} start={range.start} end={range.end} />
      </div>

      <InvestmentCard siteId={siteId} start={range.start} end={range.end} />

      <DispatchCard siteId={siteId} />

      <DemandResponseCard siteId={siteId} />

      <Card className="mt-5">
        <CardHeader
          title={<Term id="bess">{t('storage.assets')}</Term>}
          description={
            plan.data
              ? `${plan.data.name} — ${t(`storage.strategies.${plan.data.strategy}`)}` +
                (plan.data.inherited_from
                  ? `（${t('plans.inheritedBadge', { site: plan.data.inherited_from })}）`
                  : '')
              : t('plans.noneBound')
          }
        />
        <Table>
          <THead>
            <Th>{t('storage.role')}</Th>
            <Th>{t('storage.boundDevice')}</Th>
            <Th>{t('storage.powerMetric')}</Th>
            <Th>
              <Term id="soc">{t('storage.socMetric')}</Term>
            </Th>
            <Th align="right">{t('storage.scale')}</Th>
          </THead>
          <TBody>
            {(assets.data ?? []).map((asset) => (
              <Tr key={asset.id}>
                <Td>
                  <Badge tone="brand">{t(`storage.roles.${asset.role}`)}</Badge>
                </Td>
                <Td>
                  <span className="font-medium">{asset.device_name}</span>
                  <span className="ml-1.5 font-mono text-xs text-subtle">
                    {asset.device_external_id}
                  </span>
                </Td>
                <Td className="font-mono text-xs text-muted">{asset.power_metric || '—'}</Td>
                <Td className="font-mono text-xs text-muted">{asset.soc_metric || '—'}</Td>
                <Td align="right" className="tnum text-muted">
                  ×{formatNumber(asset.power_scale, { maximumFractionDigits: 4 })}
                  {asset.invert_sign ? <Badge tone="warning" className="ml-2">±</Badge> : null}
                </Td>
              </Tr>
            ))}
            {(assets.data?.length ?? 0) === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-muted">
                  {t('storage.notConfigured')}
                </td>
              </tr>
            ) : null}
          </TBody>
        </Table>
      </Card>

    </>
  )
}

/**
 * Demand response: commit the battery to a discharge, now.
 *
 * Deliberately not a strategy tab. A DR event is an *override* - while it is
 * live it outranks the strategy, the scheduled windows and even a workflow
 * takeover, because it is a commitment made to the grid operator. The plan
 * envelope and the health constraints still clamp it.
 */
function DemandResponseCard({ siteId }: { siteId: string }) {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const events = useDemandResponse(siteId)
  const { trigger, cancel } = useDemandResponseMutations(siteId)

  const [showTrigger, setShowTrigger] = useState(false)
  const [form, setForm] = useState({ target_power_kw: '', duration_minutes: 60, note: '' })

  const active = (events.data ?? []).find((event) => event.is_active)
  const recent = (events.data ?? []).slice(0, 5)

  async function submit() {
    try {
      await trigger.mutateAsync({
        target_power_kw: Number(form.target_power_kw),
        duration_minutes: Number(form.duration_minutes),
        note: form.note,
      })
      toast.success(t('storage.drStarted'))
      setShowTrigger(false)
      setForm({ target_power_kw: '', duration_minutes: 60, note: '' })
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Card className="mt-5">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Radio className="size-4 text-brand" aria-hidden />
            {t('storage.drTitle')}
          </span>
        }
        description={t('storage.drHint')}
        actions={
          can('ems:write') ? (
            <Button
              variant={active ? undefined : 'primary'}
              disabled={Boolean(active)}
              onClick={() => setShowTrigger(true)}
            >
              {t('storage.drTrigger')}
            </Button>
          ) : null
        }
      />
      <CardBody>
        {active ? (
          <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning-soft p-3">
            <Badge tone="warning">{t('storage.drActive')}</Badge>
            <span className="text-sm font-medium tnum">
              {formatNumber(active.target_power_kw)} kW
            </span>
            <span className="text-xs text-muted">
              {t('storage.drUntil', { time: formatTime(active.ends_at) })}
            </span>
            {active.note ? <span className="text-xs text-muted">{active.note}</span> : null}
            {can('ems:write') ? (
              <Button
                className="ml-auto"
                loading={cancel.isPending}
                onClick={() => {
                  void cancel
                    .mutateAsync(active.id)
                    .then(() => toast.success(t('storage.drCancelled')))
                    .catch((error) => toast.error(errorMessage(error)))
                }}
              >
                {t('common.cancel')}
              </Button>
            ) : null}
          </div>
        ) : null}

        {recent.length === 0 ? (
          <p className="text-xs text-muted">{t('storage.drEmpty')}</p>
        ) : (
          <dl className="divide-y divide-line">
            {recent.map((event) => (
              <DetailRow
                key={event.id}
                label={`${formatDateTime(event.starts_at)} → ${formatTime(event.ends_at)}`}
              >
                <span className="tnum">{formatNumber(event.target_power_kw)} kW</span>
                {event.cancelled_at ? (
                  <Badge tone="neutral" className="ml-2">
                    {t('storage.drCancelledBadge')}
                  </Badge>
                ) : event.is_active ? (
                  <Badge tone="warning" className="ml-2">
                    {t('storage.drActive')}
                  </Badge>
                ) : null}
              </DetailRow>
            ))}
          </dl>
        )}
      </CardBody>

      <Modal
        open={showTrigger}
        onClose={() => setShowTrigger(false)}
        title={t('storage.drTrigger')}
        description={t('storage.drTriggerHint')}
        footer={
          <>
            <Button onClick={() => setShowTrigger(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              loading={trigger.isPending}
              disabled={!form.target_power_kw || Number(form.target_power_kw) <= 0}
              onClick={() => void submit()}
            >
              {t('storage.drStart')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <TextInput
            label={t('storage.drPower')}
            type="number"
            suffix="kW"
            min={1}
            required
            value={form.target_power_kw}
            onChange={(event) => setForm({ ...form, target_power_kw: event.target.value })}
            hint={t('storage.drPowerHint')}
          />
          <Select
            label={t('storage.drDuration')}
            value={String(form.duration_minutes)}
            onChange={(event) =>
              setForm({ ...form, duration_minutes: Number(event.target.value) })
            }
            options={[15, 30, 60, 120, 240].map((minutes) => ({
              value: String(minutes),
              label: t('storage.drMinutes', { count: minutes }),
            }))}
          />
          <TextInput
            label={t('storage.drNote')}
            value={form.note}
            onChange={(event) => setForm({ ...form, note: event.target.value })}
            placeholder={t('storage.drNotePlaceholder')}
          />
        </div>
      </Modal>
    </Card>
  )
}

/**
 * Bind this site to a plan profile. The profiles themselves are edited on
 * the plans page - a site only *chooses* one here.
 */
function PlanBindPicker({ siteId }: { siteId: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const plans = useStoragePlans()
  const plan = useStoragePlan(siteId || undefined)
  const { bindPlan } = useEmsMutations()

  return (
    <span className="flex items-center gap-1.5">
      <Select
        value={plan.data && !plan.data.inherited_from ? plan.data.id : ''}
        placeholder={
          plan.data?.inherited_from
            ? t('plans.inheritedFrom', {
                plan: plan.data.name,
                site: plan.data.inherited_from,
              })
            : t('plans.noneBound')
        }
        onChange={(event) => {
          void bindPlan
            .mutateAsync({ siteId, planId: event.target.value || null })
            .then(() => toast.success(t('common.saved')))
            .catch((error) => toast.error(errorMessage(error)))
        }}
        options={(plans.data ?? []).map((entry) => ({
          value: entry.id,
          label: entry.name,
        }))}
        className="w-44"
      />
      <Button onClick={() => void navigate('/storage-plans')}>
        {t('plans.title')}
      </Button>
    </span>
  )
}

/**
 * Where this site's money actually went, by source.
 *
 * The headline cost figure has always meant *grid* cost, and still does - so a
 * generator running all afternoon leaves it unchanged while the site burns
 * diesel. This card is the layer that knows about the rest of the equipment.
 *
 * A modelled figure is labelled as one. A fuel cost built on an assumed
 * consumption curve is not the same kind of number as a metered import, and
 * conflating them is how a report acquires more authority than it earns.
 */
function CostBreakdownCard({
  siteId,
  start,
  end,
  fallbackCurrency,
}: {
  siteId: string
  start: string
  end: string
  fallbackCurrency?: string
}) {
  const { t } = useTranslation()
  const breakdown = useCostBreakdown(siteId || undefined, { start, end })
  const data = breakdown.data
  const currency = data?.currency || fallbackCurrency

  return (
    <Card>
      <CardHeader
        title={t('storage.costBreakdown')}
        description={t('storage.costBreakdownHint')}
      />
      <CardBody className="space-y-3">
        {breakdown.isPending ? (
          <LoadingState />
        ) : breakdown.error ? (
          <ErrorState error={breakdown.error} onRetry={() => void breakdown.refetch()} />
        ) : (data?.rows.length ?? 0) === 0 ? (
          <EmptyState title={t('storage.noCostData')} />
        ) : (
          <>
            <CostSourceChart rows={data?.rows ?? []} currency={currency} />
            <dl className="divide-y divide-line">
              {(data?.rows ?? []).map((row) => (
                <DetailRow
                  key={`${row.source}:${row.cost_model}`}
                  label={
                    <span className="flex items-center gap-1.5">
                      {t(`ems.costSources.${row.source}`, { defaultValue: row.source })}
                      {row.basis !== 'measured' ? (
                        <Badge tone="neutral">{t(`ems.costBasis.${row.basis}`)}</Badge>
                      ) : null}
                    </span>
                  }
                >
                  {formatCurrency(row.amount, currency)}
                  <span className="ml-1.5 text-xs text-subtle">
                    {formatMeasurement(row.energy_kwh, 'kWh', 0)}
                  </span>
                </DetailRow>
              ))}
              <DetailRow label={t('storage.totalCost')}>
                <span className="font-semibold">
                  {formatCurrency(data?.total_amount, currency)}
                </span>
              </DetailRow>
            </dl>
            {(data?.unknown_savings_intervals ?? 0) > 0 ? (
              <p className="rounded-lg bg-surface-muted px-3 py-2 text-xs text-muted">
                {t('storage.savingsUnknown', {
                  count: data?.unknown_savings_intervals ?? 0,
                })}
              </p>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  )
}

/**
 * How often the equipment here charged, discharged or ran.
 *
 * A session's edges come from what the equipment did, not from the settlement
 * grid, so this answers a question the interval chart cannot: how many times,
 * for how long, and how much each time.
 */
function SessionsCard({
  siteId,
  start,
  end,
}: {
  siteId: string
  start: string
  end: string
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const { can } = useAuth()
  const summary = useSessionSummary({ site_id: siteId || undefined, start, end })
  const sessions = useOperatingSessions({ site_id: siteId || undefined, limit: 6 })
  const { rebuildSessions } = useEmsMutations()

  const rows = (summary.data ?? []).filter((row) => row.count > 0)

  return (
    <Card>
      <CardHeader
        title={t('storage.sessions')}
        description={t('storage.sessionsHint')}
        actions={
          can('ems:write') ? (
            <Button
              size="sm"
              icon={<History className="size-3.5" />}
              loading={rebuildSessions.isPending}
              onClick={async () => {
                try {
                  await rebuildSessions.mutateAsync({ start, end })
                  toast.success(t('storage.sessionsRebuilt'))
                } catch (error) {
                  toast.error(errorMessage(error))
                }
              }}
            >
              {t('storage.rebuild')}
            </Button>
          ) : null
        }
      />
      <CardBody className="space-y-3">
        {summary.isPending ? (
          <LoadingState />
        ) : rows.length === 0 ? (
          <EmptyState title={t('storage.noSessions')} />
        ) : (
          <div className="grid gap-3 sm:grid-cols-3">
            {rows.map((row) => (
              <div key={row.kind} className="rounded-lg border border-line p-3">
                <p className="text-xs text-muted">
                  {t(`devices.sessionKinds.${row.kind}`)}
                </p>
                <p className="mt-1 tnum text-xl font-semibold">{row.count}</p>
                <p className="mt-0.5 text-[11px] text-subtle">
                  {formatMeasurement(row.total_energy_kwh, 'kWh', 0)}
                  {row.avg_duration_s
                    ? ` · ${t('storage.avgDuration', {
                        duration: formatDuration(row.avg_duration_s),
                      })}`
                    : ''}
                </p>
                {row.open_count > 0 ? (
                  <Badge tone="ok" className="mt-1.5">
                    {t('storage.openSessions', { count: row.open_count })}
                  </Badge>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </CardBody>

      {(sessions.data?.items.length ?? 0) > 0 ? (
        <Table>
          <THead>
            <Th>{t('devices.device')}</Th>
            <Th>{t('devices.sessionKind')}</Th>
            <Th>{t('devices.sessionStarted')}</Th>
            <Th align="right">{t('devices.sessionEnergy')}</Th>
          </THead>
          <TBody>
            {(sessions.data?.items ?? []).map((session) => (
              <Tr key={session.id}>
                <Td className="max-w-40 truncate">{session.device_name}</Td>
                <Td>
                  <Badge
                    tone={
                      session.kind === 'discharge'
                        ? 'brand'
                        : session.kind === 'charge'
                          ? 'info'
                          : 'neutral'
                    }
                  >
                    {t(`devices.sessionKinds.${session.kind}`)}
                  </Badge>
                </Td>
                <Td className="text-muted">{formatDateTime(session.started_at)}</Td>
                <Td align="right" className="tnum">
                  {formatMeasurement(session.energy_kwh, 'kWh', 1)}
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      ) : null}
    </Card>
  )
}

/**
 * What the automatic dispatch engine is about to do, and why.
 *
 * Shown before it happens rather than reconstructed afterwards from the
 * command log: "why is the battery idle" has an answer - no window, plan
 * disabled, clamped by the backup reserve - and that answer is worth far more
 * than the absence of a command.
 */
function DispatchCard({ siteId }: { siteId: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { can } = useAuth()
  const preview = useDispatchPreview()
  const { runDispatch } = useEmsMutations()

  const decisions = (preview.data ?? []).filter(
    (decision) => !siteId || decision.site_id === siteId,
  )
  if (preview.isPending || decisions.length === 0) return null

  return (
    <Card className="mt-5">
      <CardHeader
        title={t('storage.dispatch')}
        description={t('storage.dispatchHint')}
        actions={
          can('ems:dispatch') ? (
            <Button
              size="sm"
              icon={<PlayCircle className="size-3.5" />}
              loading={runDispatch.isPending}
              onClick={async () => {
                try {
                  const result = await runDispatch.mutateAsync({})
                  const sent = result.filter(
                    (decision) => decision.power_w !== null && !decision.skipped,
                  ).length
                  toast.success(t('storage.dispatchRan', { count: sent }))
                } catch (error) {
                  toast.error(errorMessage(error))
                }
              }}
            >
              {t('storage.runDispatch')}
            </Button>
          ) : null
        }
      />
      <Table>
        <THead>
          <Th>{t('storage.selectSite')}</Th>
          <Th align="right">{t('storage.dispatchTarget')}</Th>
          <Th>{t('storage.dispatchReason')}</Th>
        </THead>
        <TBody>
          {decisions.map((decision) => (
            <Tr key={decision.site_id}>
              <Td className="font-medium">{decision.site_name}</Td>
              <Td align="right" className="tnum">
                {decision.power_w === null ? (
                  <span className="text-muted">—</span>
                ) : (
                  <span
                    className={
                      decision.power_w < 0
                        ? 'text-info'
                        : decision.power_w > 0
                          ? 'text-brand'
                          : 'text-muted'
                    }
                  >
                    {formatMeasurement(decision.power_w, 'W', 1)}
                  </span>
                )}
                {decision.clamped_from_w !== null ? (
                  <Badge tone="warning" className="ml-2">
                    {t('storage.clamped')}
                  </Badge>
                ) : null}
              </Td>
              <Td className="text-muted">
                {decision.skipped
                  ? t(`storage.dispatchSkipped.${decision.skipped}`, {
                      defaultValue: decision.reason,
                    })
                  : decision.reason}
              </Td>
            </Tr>
          ))}
        </TBody>
      </Table>
    </Card>
  )
}

/**
 * What the equipment here cost, and what that works out to per year.
 *
 * Kept next to the energy cost rather than inside it. Capital is not a cost of
 * *moving energy*: folding an amortised purchase price into the interval costs
 * would make "what did this interval cost" mean two things at once, and it
 * would double count against the battery cycle charge, which already is the
 * purchase price expressed per kWh of throughput.
 *
 * Equipment with no recorded cost is counted and shown, not quietly treated as
 * free - a zero there flatters every payback figure on the page.
 */
function InvestmentCard({
  siteId,
  start,
  end,
}: {
  siteId: string
  start: string
  end: string
}) {
  const { t } = useTranslation()
  const investment = useSiteInvestment(siteId || undefined, { start, end })
  const data = investment.data

  if (investment.isPending) return null
  if (!data || (data.devices.length === 0 && data.devices_without_cost === 0)) return null

  const currency = data.currency || undefined

  return (
    <Card className="mt-5">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Landmark className="size-4 text-brand" aria-hidden />
            {t('storage.investment')}
          </span>
        }
        description={t('storage.investmentHint')}
      />
      <CardBody className="space-y-3">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
          <StatTile
            label={t('storage.capitalTotal')}
            value={formatCurrency(data.total_capital_cost, currency)}
          />
          <StatTile
            label={t('storage.annualTotal')}
            value={formatCurrency(data.total_annual_cost, currency)}
            hint={t('storage.annualTotalHint')}
          />
          <StatTile
            label={t('storage.windowShare')}
            value={formatCurrency(data.window_amortised_cost, currency)}
            hint={t('storage.windowShareHint')}
          />
        </div>

        {data.devices_without_cost > 0 ? (
          <p className="rounded-lg bg-surface-muted px-3 py-2 text-xs text-muted">
            {t('storage.missingCost', { count: data.devices_without_cost })}
          </p>
        ) : null}
      </CardBody>

      {data.devices.length > 0 ? (
        <Table>
          <THead>
            <Th>{t('devices.device')}</Th>
            <Th align="right">{t('devices.capitalCost')}</Th>
            <Th align="right">{t('devices.annualCost')}</Th>
            <Th align="right">{t('devices.commissionedOn')}</Th>
          </THead>
          <TBody>
            {data.devices.map((device) => (
              <Tr key={device.device_id}>
                <Td>
                  <span className="flex items-center gap-2">
                    <DeviceIcon category={device.category} />
                    <span className="font-medium">{device.device_name}</span>
                  </span>
                </Td>
                <Td align="right" className="tnum">
                  {formatCurrency(device.capital_cost, currency)}
                </Td>
                <Td align="right" className="tnum text-muted">
                  {formatCurrency(device.annual_cost, currency)}
                </Td>
                <Td align="right" className="text-muted">
                  {device.commissioned_on ?? '—'}
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      ) : null}
    </Card>
  )
}

export default StoragePage
