import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowLeftRight,
  BatteryCharging,
  MinusCircle,
  SunMedium,
  Zap,
  Gauge,
  Home,
  Plus,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  TrendingDown,
  Workflow as WorkflowIcon,
} from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import {
  useEmsMutations,
  useMetrics,
  useSites,
  useStoragePlanMutations,
  useStoragePlans,
  useTariffs,
  useWorkflowList,
} from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import type { DispatchStrategy, StoragePlan } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ChoiceCards,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Select,
  Tabs,
  Term,
  TextInput,
} from '@/components/ui'

const STRATEGY_ICON: Record<DispatchStrategy, LucideIcon> = {
  manual: SlidersHorizontal,
  self_consumption: Home,
  peak_shaving: TrendingDown,
  demand_cap: Gauge,
  tou_arbitrage: ArrowLeftRight,
  backup_only: ShieldCheck,
  workflow: WorkflowIcon,
}

const STRATEGIES: DispatchStrategy[] = [
  'manual',
  'self_consumption',
  'demand_cap',
  'peak_shaving',
  'tou_arbitrage',
  'backup_only',
  'workflow',
]

const BASELINES: StoragePlan['savings_baseline'][] = ['no_storage', 'grid_only', 'none']

const BASELINE_ICON: Record<StoragePlan['savings_baseline'], LucideIcon> = {
  grid_only: Zap,
  no_storage: SunMedium,
  none: MinusCircle,
}

type PlanForm = typeof EMPTY_FORM

/**
 * Field-level sanity checks, run while the operator is still looking at the
 * form. The server validates again; these exist so a plan that can never
 * act (a demand cap with no ceiling, a time-of-use plan with no tariff, a
 * SOC floor above its ceiling) is pointed out before Save rather than after.
 */
function planProblems(form: PlanForm, t: (key: string, options?: Record<string, unknown>) => string) {
  const problems: Partial<Record<keyof PlanForm, string>> = {}
  const num = (value: string | number) => (value === '' || value === null ? null : Number(value))
  const positive = (key: keyof PlanForm) => {
    const value = num(form[key] as string | number)
    if (value !== null && (!Number.isFinite(value) || value <= 0)) problems[key] = t('plans.problems.positive')
  }
  for (const key of ['contract_capacity_kw', 'peak_shaving_target_kw', 'usable_capacity_kwh',
    'max_charge_kw', 'max_discharge_kw', 'demand_cap_target_kw', 'max_cycles_per_day'] as const) {
    positive(key)
  }
  const minSoc = Number(form.min_soc_percent)
  const maxSoc = Number(form.max_soc_percent)
  const reserve = Number(form.backup_reserve_percent)
  if (!(minSoc >= 0 && minSoc <= 100)) problems.min_soc_percent = t('plans.problems.percent')
  if (!(maxSoc >= 0 && maxSoc <= 100)) problems.max_soc_percent = t('plans.problems.percent')
  if (!problems.min_soc_percent && !problems.max_soc_percent && minSoc >= maxSoc) {
    problems.min_soc_percent = t('plans.problems.socOrder')
  }
  if (!(reserve >= 0 && reserve <= 100)) problems.backup_reserve_percent = t('plans.problems.percent')
  else if (!problems.max_soc_percent && reserve > maxSoc) {
    problems.backup_reserve_percent = t('plans.problems.reserveAboveMax')
  }
  const rte = Number(form.round_trip_efficiency)
  if (!(rte > 0 && rte <= 1)) problems.round_trip_efficiency = t('plans.problems.efficiency')
  const spread = Number(form.min_price_spread)
  if (!(spread >= 0)) problems.min_price_spread = t('plans.problems.nonNegative')
  const tempMax = num(form.temperature_max_c)
  if (tempMax !== null && !Number.isFinite(tempMax)) problems.temperature_max_c = t('plans.problems.number')
  if (tempMax !== null && !form.temperature_metric) problems.temperature_metric = t('plans.problems.tempMetric')

  const contract = num(form.contract_capacity_kw)
  const target = num(form.demand_cap_target_kw)
  if (form.strategy === 'demand_cap') {
    if (contract === null && target === null) problems.contract_capacity_kw = t('plans.problems.demandCeiling')
    if (contract !== null && target !== null && target > contract) {
      problems.demand_cap_target_kw = t('plans.problems.targetAboveContract')
    }
  }
  if (form.strategy === 'peak_shaving' && num(form.peak_shaving_target_kw) === null) {
    problems.peak_shaving_target_kw = t('plans.problems.required')
  }
  if (form.strategy === 'tou_arbitrage' && !form.tariff_id) problems.tariff_id = t('plans.problems.tariff')
  if (form.strategy === 'workflow' && !form.workflow_id) problems.workflow_id = t('plans.problems.workflow')
  return problems
}

/** Strategies that compute a setpoint and can be stacked under a primary (W5). */
const STACKABLE: DispatchStrategy[] = ['demand_cap', 'tou_arbitrage', 'self_consumption', 'backup_only']

const EMPTY_FORM = {
  name: '',
  strategy: 'manual' as DispatchStrategy,
  strategies: [] as DispatchStrategy[],
  is_enabled: true,
  contract_capacity_kw: '' as string | number,
  peak_shaving_target_kw: '' as string | number,
  usable_capacity_kwh: '' as string | number,
  max_charge_kw: '' as string | number,
  max_discharge_kw: '' as string | number,
  min_soc_percent: 10,
  max_soc_percent: 95,
  backup_reserve_percent: 20,
  round_trip_efficiency: 0.9,
  tariff_id: '',
  workflow_id: '',
  savings_baseline: 'no_storage' as StoragePlan['savings_baseline'],
  enforce_limits: true,
  demand_cap_target_kw: '' as string | number,
  offpeak_recharge: true,
  min_price_spread: 1.0,
  max_cycles_per_day: '' as string | number,
  temperature_max_c: '' as string | number,
  temperature_metric: '',
}

/**
 * Storage plans as a catalogue of named strategy profiles.
 *
 * Grew out of a modal that had become a wall of fields. A full page gives the
 * strategy tabs, the envelope, the health constraints and the site bindings
 * the room they need - and making plans *named templates* means one profile
 * drives a whole fleet of similar sites, the same shape tariffs already have.
 */
export function StoragePlansPage() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  const plans = useStoragePlans()
  const selectedId = searchParams.get('plan') ?? ''
  const selected = (plans.data ?? []).find((plan) => plan.id === selectedId) ?? null
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<StoragePlan | null>(null)
  const { remove } = useStoragePlanMutations()
  const toast = useToast()

  function select(id: string | null) {
    const next = new URLSearchParams(searchParams)
    if (id) next.set('plan', id)
    else next.delete('plan')
    setSearchParams(next, { replace: true })
    setCreating(false)
  }

  if (plans.isPending) return <LoadingState />
  if (plans.error) {
    return <ErrorState error={plans.error} onRetry={() => void plans.refetch()} />
  }

  const editable = can('ems:write')

  return (
    <>
      <PageHeader
        title={<Term id="ems">{t('plans.title')}</Term>}
        description={t('plans.subtitle')}
        actions={
          editable ? (
            <Button
              variant="primary"
              icon={<Plus className="size-4" />}
              onClick={() => {
                select(null)
                setCreating(true)
              }}
            >
              {t('plans.create')}
            </Button>
          ) : null
        }
      />

      {(plans.data ?? []).length === 0 && !creating ? (
        <Card>
          <EmptyState
            icon={<BatteryCharging className="size-6" />}
            title={t('plans.empty')}
            description={t('plans.emptyHint')}
          />
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(plans.data ?? []).map((plan) => {
            const Icon = STRATEGY_ICON[plan.strategy] ?? SlidersHorizontal
            const active = plan.id === selectedId
            return (
              <button
                key={plan.id}
                type="button"
                onClick={() => select(active ? null : plan.id)}
                className={`rounded-lg border p-3.5 text-left transition ${
                  active
                    ? 'border-brand ring-2 ring-brand/30'
                    : 'border-line bg-surface hover:border-line-strong'
                }`}
              >
                <div className="flex items-start gap-2.5">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-brand-soft text-brand">
                    <Icon size={16} aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{plan.name}</p>
                    <p className="truncate text-xs text-muted">
                      {t(`storage.strategies.${plan.strategy}`)}
                      {(plan.strategies ?? []).filter((key) => key !== plan.strategy).map((key) => (
                        <span key={key} className="ml-1 rounded bg-brand-soft px-1 text-[10px] text-brand">
                          + {t(`storage.strategies.${key}`)}
                        </span>
                      ))}
                    </p>
                  </div>
                  {!plan.is_enabled ? (
                    <Badge tone="neutral">{t('common.disabled')}</Badge>
                  ) : null}
                </div>
                <p className="mt-2 text-[11px] text-muted">
                  {plan.sites.length > 0
                    ? t('plans.boundSites', {
                        names: plan.sites.map((site) => site.name).join('、'),
                      })
                    : t('plans.noSites')}
                </p>
              </button>
            )
          })}
        </div>
      )}

      {creating || selected ? (
        <PlanEditor
          key={selected?.id ?? 'new'}
          plan={creating ? null : selected}
          editable={editable}
          onDelete={selected ? () => setDeleting(selected) : undefined}
          onSaved={(id) => select(id)}
        />
      ) : null}

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        danger
        loading={remove.isPending}
        title={t('common.delete')}
        confirmLabel={t('common.delete')}
        message={t('plans.deleteConfirm', {
          name: deleting?.name ?? '',
          count: deleting?.sites.length ?? 0,
        })}
        onConfirm={async () => {
          if (!deleting) return
          try {
            await remove.mutateAsync(deleting.id)
            setDeleting(null)
            select(null)
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />
    </>
  )
}

function PlanEditor({
  plan,
  editable,
  onDelete,
  onSaved,
}: {
  plan: StoragePlan | null
  editable: boolean
  onDelete?: () => void
  onSaved: (id: string) => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const tariffs = useTariffs()
  const metrics = useMetrics()
  const workflows = useWorkflowList({ enabled: true })
  const sites = useSites()
  const { create, update } = useStoragePlanMutations()
  const { bindPlan } = useEmsMutations()

  const [form, setForm] = useState(EMPTY_FORM)

  useEffect(() => {
    if (plan) {
      setForm({
        name: plan.name,
        strategy: plan.strategy,
        strategies: (plan.strategies ?? []).filter((key) => key !== plan.strategy),
        is_enabled: plan.is_enabled,
        contract_capacity_kw: plan.contract_capacity_kw ?? '',
        peak_shaving_target_kw: plan.peak_shaving_target_kw ?? '',
        usable_capacity_kwh: plan.usable_capacity_kwh ?? '',
        max_charge_kw: plan.max_charge_kw ?? '',
        max_discharge_kw: plan.max_discharge_kw ?? '',
        min_soc_percent: plan.min_soc_percent,
        max_soc_percent: plan.max_soc_percent,
        backup_reserve_percent: plan.backup_reserve_percent,
        round_trip_efficiency: plan.round_trip_efficiency,
        tariff_id: plan.tariff_id ?? '',
        workflow_id: plan.workflow_id ?? '',
        savings_baseline: plan.savings_baseline ?? 'no_storage',
        enforce_limits: plan.enforce_limits ?? true,
        demand_cap_target_kw: plan.demand_cap_target_kw ?? '',
        offpeak_recharge: plan.offpeak_recharge ?? true,
        min_price_spread: plan.min_price_spread ?? 1.0,
        max_cycles_per_day: plan.max_cycles_per_day ?? '',
        temperature_max_c: plan.temperature_max_c ?? '',
        temperature_metric: plan.temperature_metric ?? '',
      })
    } else {
      setForm(EMPTY_FORM)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan?.id])

  const boundIds = useMemo(
    () => new Set((plan?.sites ?? []).map((site) => site.id)),
    [plan?.sites],
  )

  const number = (value: string | number) =>
    value === '' || value === null ? null : Number(value)
  const problems = useMemo(() => planProblems(form, t), [form, t])
  const problemCount = Object.keys(problems).length

  async function submit() {
    const body = {
      name: form.name.trim(),
      strategy: form.strategy,
      strategies: STACKABLE.includes(form.strategy)
        ? [form.strategy, ...form.strategies.filter((key) => key !== form.strategy)]
        : [form.strategy],
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
      workflow_id: form.strategy === 'workflow' ? form.workflow_id || null : null,
      savings_baseline: form.savings_baseline,
      enforce_limits: form.enforce_limits,
      demand_cap_target_kw: number(form.demand_cap_target_kw),
      offpeak_recharge: form.offpeak_recharge,
      min_price_spread: Number(form.min_price_spread),
      max_cycles_per_day: number(form.max_cycles_per_day),
      temperature_max_c: number(form.temperature_max_c),
      temperature_metric: form.temperature_metric,
    }
    try {
      if (plan) {
        await update.mutateAsync({ id: plan.id, ...body })
        onSaved(plan.id)
      } else {
        const created = await create.mutateAsync(body)
        onSaved(created.id)
      }
      toast.success(t('common.saved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function toggleSite(siteId: string, bound: boolean) {
    if (!plan) return
    try {
      await bindPlan.mutateAsync({ siteId, planId: bound ? plan.id : null })
      toast.success(bound ? t('plans.siteBound') : t('plans.siteUnbound'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Card className="mt-5 p-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          {plan ? t('plans.edit', { name: plan.name }) : t('plans.create')}
        </h2>
        {editable ? (
          <div className="flex gap-2">
            {onDelete ? (
              <Button icon={<Trash2 className="size-3.5" />} onClick={onDelete}>
                {t('common.delete')}
              </Button>
            ) : null}
            <Button
              variant="primary"
              loading={create.isPending || update.isPending}
              disabled={!form.name.trim() || problemCount > 0}
              title={problemCount > 0 ? t('plans.problems.summary', { count: problemCount }) : undefined}
              onClick={() => void submit()}
            >
              {t('common.save')}
            </Button>
          </div>
        ) : null}
      </div>

      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-3">
          <TextInput
            label={t('common.name')}
            required
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            hint={t('plans.nameHint')}
          />
          <Checkbox
            label={t('common.enabled')}
            hint={t('plans.enabledHint')}
            checked={form.is_enabled}
            onChange={(is_enabled) => setForm({ ...form, is_enabled })}
          />
          <Checkbox
            label={t('storage.enforceLimits', { defaultValue: 'Enforce limits' })}
            hint={t('plans.enforceHint')}
            checked={form.enforce_limits}
            onChange={(enforce_limits) => setForm({ ...form, enforce_limits })}
          />
        </div>

        <div>
          <h3 className="mb-2 text-sm font-medium">
            <Term id="ems">{t('storage.strategy')}</Term>
          </h3>
          <Tabs<DispatchStrategy>
            tabs={STRATEGIES.map((value) => ({
              value,
              label: t(`storage.strategies.${value}`),
              icon: STRATEGY_ICON[value],
              description: t(`storage.strategyDetails.${value}`),
              note: t(`storage.strategyNeeds.${value}`, { defaultValue: '' }) || undefined,
            }))}
            value={form.strategy}
            onChange={(strategy) => setForm({ ...form, strategy })}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              {form.strategy === 'peak_shaving' || form.strategy === 'demand_cap' ? (
                <>
                  <TextInput
                    label={<Term id="contractCapacity">{t('storage.contractCapacity')}</Term>}
                    type="number"
                    suffix="kW"
                    value={String(form.contract_capacity_kw)}
                    error={problems.contract_capacity_kw}
                    onChange={(event) =>
                      setForm({ ...form, contract_capacity_kw: event.target.value })
                    }
                    hint={t('storage.contractCapacityHint')}
                  />
                  <TextInput
                    label={
                      form.strategy === 'demand_cap'
                        ? t('storage.demandCapTarget')
                        : t('storage.peakDemand')
                    }
                    type="number"
                    suffix="kW"
                    value={String(
                      form.strategy === 'demand_cap'
                        ? form.demand_cap_target_kw
                        : form.peak_shaving_target_kw,
                    )}
                    error={
                      form.strategy === 'demand_cap'
                        ? problems.demand_cap_target_kw
                        : problems.peak_shaving_target_kw
                    }
                    onChange={(event) =>
                      setForm(
                        form.strategy === 'demand_cap'
                          ? { ...form, demand_cap_target_kw: event.target.value }
                          : { ...form, peak_shaving_target_kw: event.target.value },
                      )
                    }
                    hint={
                      form.strategy === 'demand_cap'
                        ? t('storage.demandCapTargetHint')
                        : t('storage.peakDemandHint')
                    }
                  />
                </>
              ) : null}

              {form.strategy === 'demand_cap' ? (
                <>
                  <Select
                    label={<Term id="tariff" />}
                    value={form.tariff_id}
                    error={problems.tariff_id}
                    placeholder={t('common.none')}
                    onChange={(event) => setForm({ ...form, tariff_id: event.target.value })}
                    options={(tariffs.data ?? []).map((tariff) => ({
                      value: tariff.id,
                      label: tariff.name,
                    }))}
                    hint={t('storage.demandCapTariffHint')}
                  />
                  <Checkbox
                    label={t('storage.offpeakRecharge')}
                    hint={t('storage.offpeakRechargeHint')}
                    checked={form.offpeak_recharge}
                    onChange={(offpeak_recharge) => setForm({ ...form, offpeak_recharge })}
                  />
                </>
              ) : null}

              {form.strategy === 'tou_arbitrage' ? (
                <>
                  <Select
                    label={<Term id="tariff" />}
                    value={form.tariff_id}
                    error={problems.tariff_id}
                    placeholder={t('common.none')}
                    onChange={(event) => setForm({ ...form, tariff_id: event.target.value })}
                    options={(tariffs.data ?? []).map((tariff) => ({
                      value: tariff.id,
                      label: tariff.name,
                    }))}
                    hint={t('storage.tariffHint')}
                  />
                  <TextInput
                    label={t('storage.minPriceSpread')}
                    type="number"
                    step="0.1"
                    min={0}
                    value={String(form.min_price_spread)}
                    error={problems.min_price_spread}
                    onChange={(event) =>
                      setForm({ ...form, min_price_spread: Number(event.target.value) })
                    }
                    hint={t('storage.minPriceSpreadHint')}
                  />
                </>
              ) : null}

              {form.strategy === 'workflow' ? (
                <Select
                  label={t('storage.workflowPick')}
                  value={form.workflow_id}
                  error={problems.workflow_id}
                  placeholder={t('common.none')}
                  onChange={(event) => setForm({ ...form, workflow_id: event.target.value })}
                  options={(workflows.data?.items ?? []).map((workflow) => ({
                    value: workflow.id,
                    label: workflow.name,
                  }))}
                  hint={t('storage.workflowPickHint')}
                  className="sm:col-span-2"
                />
              ) : null}

              {form.strategy === 'backup_only' ? (
                <TextInput
                  label={t('storage.backupReserve')}
                  type="number"
                  suffix="%"
                  min={0}
                  max={100}
                  value={String(form.backup_reserve_percent)}
                  error={problems.backup_reserve_percent}
                  onChange={(event) =>
                    setForm({ ...form, backup_reserve_percent: Number(event.target.value) })
                  }
                  hint={t('storage.backupReserveHint')}
                />
              ) : null}

              {form.strategy === 'manual' || form.strategy === 'self_consumption' ? (
                <p className="text-xs text-muted sm:col-span-2">
                  {t('storage.noExtraParameters')}
                </p>
              ) : null}
            </div>
          </Tabs>
        </div>

        {STACKABLE.includes(form.strategy) ? (
          <section className="space-y-2 rounded-lg border border-line p-3" data-testid="plan-stacking">
            <h3 className="text-sm font-medium">{t('storage.stacking')}</h3>
            <p className="text-xs text-muted">{t('storage.stackingHint')}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {STACKABLE.filter((key) => key !== form.strategy).map((key) => (
                <Checkbox
                  key={key}
                  label={t(`storage.strategies.${key}`)}
                  hint={t(`storage.strategyDetails.${key}`)}
                  checked={form.strategies.includes(key)}
                  onChange={(checked) =>
                    setForm({
                      ...form,
                      strategies: checked
                        ? [...form.strategies, key]
                        : form.strategies.filter((item) => item !== key),
                    })
                  }
                />
              ))}
            </div>
          </section>
        ) : null}

        <section className="space-y-3 rounded-lg border border-line p-3">
          <h3 className="text-sm font-medium">{t('storage.envelope')}</h3>
          <p className="text-xs text-muted">{t('storage.envelopeHint')}</p>
          <div className="grid gap-4 sm:grid-cols-3">
            <TextInput
              label={<Term id="usableCapacity">{t('storage.usableCapacity')}</Term>}
              type="number"
              suffix="kWh"
              value={String(form.usable_capacity_kwh)}
              error={problems.usable_capacity_kwh}
              onChange={(event) =>
                setForm({ ...form, usable_capacity_kwh: event.target.value })
              }
            />
            <TextInput
              label={<Term id="roundTrip">{t('storage.roundTrip')}</Term>}
              type="number"
              step="0.01"
              min={0.1}
              max={1}
              value={String(form.round_trip_efficiency)}
              error={problems.round_trip_efficiency}
              onChange={(event) =>
                setForm({ ...form, round_trip_efficiency: Number(event.target.value) })
              }
            />
            <TextInput
              label={<Term id="pcs">{t('storage.maxCharge')}</Term>}
              type="number"
              suffix="kW"
              value={String(form.max_charge_kw)}
              error={problems.max_charge_kw}
              onChange={(event) => setForm({ ...form, max_charge_kw: event.target.value })}
            />
            <TextInput
              label={t('storage.maxDischarge')}
              type="number"
              suffix="kW"
              value={String(form.max_discharge_kw)}
              error={problems.max_discharge_kw}
              onChange={(event) =>
                setForm({ ...form, max_discharge_kw: event.target.value })
              }
            />
            <TextInput
              label={<Term id="soc">{t('storage.minSoc')}</Term>}
              type="number"
              suffix="%"
              min={0}
              max={100}
              value={String(form.min_soc_percent)}
              error={problems.min_soc_percent}
              onChange={(event) =>
                setForm({ ...form, min_soc_percent: Number(event.target.value) })
              }
            />
            <TextInput
              label={<Term id="soc">{t('storage.maxSoc')}</Term>}
              type="number"
              suffix="%"
              min={0}
              max={100}
              value={String(form.max_soc_percent)}
              error={problems.max_soc_percent}
              onChange={(event) =>
                setForm({ ...form, max_soc_percent: Number(event.target.value) })
              }
            />
            {form.strategy !== 'backup_only' ? (
              <TextInput
                label={t('storage.backupReserve')}
                type="number"
                suffix="%"
                min={0}
                max={100}
                value={String(form.backup_reserve_percent)}
                error={problems.backup_reserve_percent}
                onChange={(event) =>
                  setForm({ ...form, backup_reserve_percent: Number(event.target.value) })
                }
                hint={t('storage.backupReserveHint')}
              />
            ) : null}
          </div>
        </section>

        <section className="space-y-3 rounded-lg border border-line p-3">
          <h3 className="text-sm font-medium">{t('storage.health')}</h3>
          <p className="text-xs text-muted">{t('storage.healthHint')}</p>
          <div className="grid gap-4 sm:grid-cols-3">
            <TextInput
              label={t('storage.maxCycles')}
              type="number"
              step="0.1"
              min={0}
              value={String(form.max_cycles_per_day)}
              error={problems.max_cycles_per_day}
              onChange={(event) =>
                setForm({ ...form, max_cycles_per_day: event.target.value })
              }
              hint={t('storage.maxCyclesHint')}
            />
            <TextInput
              label={t('storage.tempMax')}
              type="number"
              suffix="°C"
              value={String(form.temperature_max_c)}
              error={problems.temperature_max_c}
              onChange={(event) =>
                setForm({ ...form, temperature_max_c: event.target.value })
              }
              hint={t('storage.tempMaxHint')}
            />
            <Select
              label={t('storage.tempMetric')}
              value={form.temperature_metric}
              error={problems.temperature_metric}
              placeholder={t('common.none')}
              onChange={(event) =>
                setForm({ ...form, temperature_metric: event.target.value })
              }
              options={(metrics.data ?? []).map((metric) => ({
                value: metric.key,
                label: metric.unit ? `${metric.key} (${metric.unit})` : metric.key,
              }))}
              hint={t('storage.tempMetricHint')}
            />
          </div>
        </section>

        <section className="space-y-3 rounded-lg border border-line p-3">
          <h3 className="text-sm font-medium">{t('storage.savingsBaseline', { defaultValue: 'Savings baseline' })}</h3>
          <ChoiceCards<StoragePlan['savings_baseline']>
            columns={2}
            value={form.savings_baseline}
            onChange={(savings_baseline) => setForm({ ...form, savings_baseline })}
            choices={BASELINES.map((value) => ({
              value,
              label: t(`storage.savingsBaselines.${value}`, { defaultValue: value }),
              description: t(`storage.savingsBaselineDetails.${value}`),
              icon: BASELINE_ICON[value],
            }))}
          />
        </section>

        {plan ? (
          <section className="space-y-3 rounded-lg border border-line p-3">
            <h3 className="text-sm font-medium">{t('plans.bindings')}</h3>
            <p className="text-xs text-muted">{t('plans.bindingsHint')}</p>
            <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
              {(sites.data?.items ?? []).map((site) => (
                <div key={site.id} style={{ paddingLeft: site.depth * 16 }}>
                  <Checkbox
                    label={site.name}
                    checked={boundIds.has(site.id)}
                    onChange={(checked) => void toggleSite(site.id, checked)}
                  />
                </div>
              ))}
            </div>
          </section>
        ) : (
          <p className="text-xs text-muted">{t('plans.saveFirst')}</p>
        )}
      </div>
    </Card>
  )
}
