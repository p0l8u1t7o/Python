import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { BatteryCharging, Coins, PiggyBank, RefreshCw, Sun, Zap } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import {
  useEmsMutations,
  useEnergyAssets,
  useEnergyIntervals,
  useEnergySummary,
  useSiteOverview,
  useSites,
  useStoragePlan,
  useTariffs,
} from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import { formatCurrency, formatMeasurement, formatNumber, formatPercent, formatTime } from '@/lib/format'
import { RANGE_KEYS, useTimeRange, type RangeKey } from '@/lib/useTimeRange'
import type { DispatchStrategy } from '@/lib/types'
import { CostChart, EnergyBalanceChart, SocChart } from '@/components/charts/EnergyCharts'
import { PowerFlowDiagram } from '@/components/charts/PowerFlowDiagram'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  DetailRow,
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  PageHeader,
  SegmentedControl,
  Select,
  StatTile,
  TBody,
  Term,
  THead,
  Table,
  Td,
  TextInput,
  Th,
  Tr,
} from '@/components/ui'

const STRATEGIES: DispatchStrategy[] = [
  'manual',
  'self_consumption',
  'peak_shaving',
  'tou_arbitrage',
  'backup_only',
]

export function StoragePage() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const range = useTimeRange('24h')

  const sites = useSites()
  const siteId = searchParams.get('site') ?? sites.data?.items[0]?.id ?? ''
  const [showPlan, setShowPlan] = useState(false)

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
            <Select
              value={siteId}
              onChange={(event) => {
                const next = new URLSearchParams(searchParams)
                next.set('site', event.target.value)
                setSearchParams(next, { replace: true })
              }}
              options={sites.data.items.map((site) => ({ value: site.id, label: site.name }))}
              className="w-52"
            />
            <SegmentedControl<RangeKey>
              size="sm"
              value={range.key}
              onChange={range.setKey}
              options={RANGE_KEYS.map((key) => ({ value: key, label: t(`range.${key}`) }))}
            />
            {can('ems:write') ? (
              <Button onClick={() => setShowPlan(true)}>{t('storage.plan')}</Button>
            ) : null}
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

      <Card className="mt-5">
        <CardHeader
          title={<Term id="bess">{t('storage.assets')}</Term>}
          description={
            plan.data
              ? `${t('storage.strategy')}: ${t(`storage.strategies.${plan.data.strategy}`)}`
              : undefined
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

      <PlanModal
        open={showPlan}
        onClose={() => setShowPlan(false)}
        siteId={siteId}
        existing={plan.data ?? null}
      />
    </>
  )
}

function PlanModal({
  open,
  onClose,
  siteId,
  existing,
}: {
  open: boolean
  onClose: () => void
  siteId: string
  existing: ReturnType<typeof useStoragePlan>['data'] | null
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const tariffs = useTariffs()
  const { savePlan } = useEmsMutations()

  const [form, setForm] = useState(() => ({
    strategy: existing?.strategy ?? ('manual' as DispatchStrategy),
    is_enabled: existing?.is_enabled ?? true,
    contract_capacity_kw: existing?.contract_capacity_kw ?? '',
    peak_shaving_target_kw: existing?.peak_shaving_target_kw ?? '',
    usable_capacity_kwh: existing?.usable_capacity_kwh ?? '',
    max_charge_kw: existing?.max_charge_kw ?? '',
    max_discharge_kw: existing?.max_discharge_kw ?? '',
    min_soc_percent: existing?.min_soc_percent ?? 10,
    max_soc_percent: existing?.max_soc_percent ?? 95,
    backup_reserve_percent: existing?.backup_reserve_percent ?? 20,
    round_trip_efficiency: existing?.round_trip_efficiency ?? 0.9,
    tariff_id: existing?.tariff_id ?? '',
  }))

  // Reopening after the plan loaded should show the stored values, not the
  // defaults captured when this component first mounted.
  useEffect(() => {
    if (open && existing) {
      setForm({
        strategy: existing.strategy,
        is_enabled: existing.is_enabled,
        contract_capacity_kw: existing.contract_capacity_kw ?? '',
        peak_shaving_target_kw: existing.peak_shaving_target_kw ?? '',
        usable_capacity_kwh: existing.usable_capacity_kwh ?? '',
        max_charge_kw: existing.max_charge_kw ?? '',
        max_discharge_kw: existing.max_discharge_kw ?? '',
        min_soc_percent: existing.min_soc_percent,
        max_soc_percent: existing.max_soc_percent,
        backup_reserve_percent: existing.backup_reserve_percent,
        round_trip_efficiency: existing.round_trip_efficiency,
        tariff_id: existing.tariff_id ?? '',
      })
    }
  }, [open, existing])

  const number = (value: string | number) =>
    value === '' || value === null ? null : Number(value)

  async function submit() {
    try {
      await savePlan.mutateAsync({
        siteId,
        strategy: form.strategy,
        is_enabled: form.is_enabled,
        contract_capacity_kw: number(form.contract_capacity_kw),
        peak_shaving_target_kw: number(form.peak_shaving_target_kw),
        usable_capacity_kwh: number(form.usable_capacity_kwh),
        max_charge_kw: number(form.max_charge_kw),
        max_discharge_kw: number(form.max_discharge_kw),
        min_soc_percent: Number(form.min_soc_percent),
        max_soc_percent: Number(form.max_soc_percent),
        backup_reserve_percent: Number(form.backup_reserve_percent),
        round_trip_efficiency: Number(form.round_trip_efficiency),
        tariff_id: form.tariff_id || null,
      })
      toast.success(t('common.saved'))
      onClose()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('storage.plan')}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={savePlan.isPending} onClick={() => void submit()}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          label={<Term id="ems">{t('storage.strategy')}</Term>}
          value={form.strategy}
          onChange={(event) =>
            setForm({ ...form, strategy: event.target.value as DispatchStrategy })
          }
          options={STRATEGIES.map((value) => ({
            value,
            label: t(`storage.strategies.${value}`),
          }))}
        />
        <Select
          label={<Term id="tariff" />}
          value={form.tariff_id}
          placeholder={t('common.none')}
          onChange={(event) => setForm({ ...form, tariff_id: event.target.value })}
          options={(tariffs.data ?? []).map((tariff) => ({
            value: tariff.id,
            label: tariff.name,
          }))}
        />
        <TextInput
          label={<Term id="contractCapacity">{t('storage.contractCapacity')}</Term>}
          type="number"
          suffix="kW"
          value={String(form.contract_capacity_kw)}
          onChange={(event) => setForm({ ...form, contract_capacity_kw: event.target.value })}
        />
        <TextInput
          label={<Term id="peakDemand">{t('storage.peakDemand')}</Term>}
          type="number"
          suffix="kW"
          value={String(form.peak_shaving_target_kw)}
          onChange={(event) => setForm({ ...form, peak_shaving_target_kw: event.target.value })}
        />
        <TextInput
          label={<Term id="usableCapacity">{t('storage.usableCapacity')}</Term>}
          type="number"
          suffix="kWh"
          value={String(form.usable_capacity_kwh)}
          onChange={(event) => setForm({ ...form, usable_capacity_kwh: event.target.value })}
        />
        <TextInput
          label={<Term id="roundTrip">{t('storage.roundTrip')}</Term>}
          type="number"
          step="0.01"
          min={0.1}
          max={1}
          value={String(form.round_trip_efficiency)}
          onChange={(event) => setForm({ ...form, round_trip_efficiency: Number(event.target.value) })}
        />
        <TextInput
          label={<Term id="pcs">Max charge</Term>}
          type="number"
          suffix="kW"
          value={String(form.max_charge_kw)}
          onChange={(event) => setForm({ ...form, max_charge_kw: event.target.value })}
        />
        <TextInput
          label="Max discharge"
          type="number"
          suffix="kW"
          value={String(form.max_discharge_kw)}
          onChange={(event) => setForm({ ...form, max_discharge_kw: event.target.value })}
        />
        <TextInput
          label={<Term id="soc">Min SOC</Term>}
          type="number"
          suffix="%"
          min={0}
          max={100}
          value={String(form.min_soc_percent)}
          onChange={(event) => setForm({ ...form, min_soc_percent: Number(event.target.value) })}
        />
        <TextInput
          label={<Term id="soc">Max SOC</Term>}
          type="number"
          suffix="%"
          min={0}
          max={100}
          value={String(form.max_soc_percent)}
          onChange={(event) => setForm({ ...form, max_soc_percent: Number(event.target.value) })}
        />
        <TextInput
          label="Backup reserve"
          type="number"
          suffix="%"
          min={0}
          max={100}
          value={String(form.backup_reserve_percent)}
          onChange={(event) =>
            setForm({ ...form, backup_reserve_percent: Number(event.target.value) })
          }
          hint="Never discharged for arbitrage."
        />
        <div className="flex items-end">
          <Checkbox
            label={t('common.enabled')}
            checked={form.is_enabled}
            onChange={(value) => setForm({ ...form, is_enabled: value })}
          />
        </div>
      </div>
    </Modal>
  )
}

export default StoragePage
