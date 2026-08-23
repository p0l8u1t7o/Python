import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Clock, Copy, Plus, Trash2 } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import {
  useSites,
  useStoragePlans,
  useTariffMutations,
  useTariffPresets,
  useTariffs,
} from '@/lib/queries'
import { errorMessage, fieldErrors } from '@/lib/errors'
import { formatNumber } from '@/lib/format'
import type { SiteSummary, StoragePlan, Tariff, TariffPreset } from '@/lib/types'
import { useFormDirty } from '@/lib/useFormDirty'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  EmptyRow,
  ErrorState,
  IconButton,
  Modal,
  PageHeader,
  Select,
  TBody,
  THead,
  Table,
  Td,
  Term,
  TextInput,
  Th,
  TimezoneSelect,
  Tr,
} from '@/components/ui'

/** Monday-first, matching `Tariff.periods[].weekdays` where Monday is 0. */
const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

/**
 * A time-of-use period as the form holds it.
 *
 * Prices are strings while being edited so a half-typed "8." does not become
 * `NaN` and blank the field under the user's cursor; they are converted once,
 * on submit.
 */
interface PeriodForm {
  name: string
  start: string
  end: string
  months: number[]
  weekdays: number[]
  import_price: string
  export_price: string
}

function toPeriodForm(raw: Record<string, unknown>): PeriodForm {
  return {
    name: String(raw.name ?? ''),
    start: String(raw.start ?? '00:00'),
    end: String(raw.end ?? '24:00'),
    months: Array.isArray(raw.months) ? (raw.months as number[]) : [],
    weekdays: Array.isArray(raw.weekdays) ? (raw.weekdays as number[]) : [],
    import_price: raw.import_price === undefined ? '' : String(raw.import_price),
    export_price: raw.export_price === undefined ? '' : String(raw.export_price),
  }
}

function fromPeriodForm(period: PeriodForm): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    name: period.name.trim(),
    start: period.start,
    end: period.end,
  }
  // An empty months/weekdays list means "every month" / "every day", and the
  // backend spells that as the key being absent. Sending [] would match
  // nothing and silently drop the period out of the tariff.
  if (period.months.length > 0) payload.months = period.months
  if (period.weekdays.length > 0) payload.weekdays = period.weekdays
  if (period.import_price !== '') payload.import_price = Number(period.import_price)
  if (period.export_price !== '') payload.export_price = Number(period.export_price)
  return payload
}

export function TariffsPage() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const tariffs = useTariffs()
  const [editing, setEditing] = useState<Tariff | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<Tariff | null>(null)

  const editable = can('ems:write')

  return (
    <>
      <PageHeader
        title={<Term id="tariff">{t('tariffs.title')}</Term>}
        description={t('tariffs.subtitle')}
        actions={
          editable ? (
            <Button
              variant="primary"
              icon={<Plus className="size-4" />}
              onClick={() => setCreating(true)}
            >
              {t('tariffs.create')}
            </Button>
          ) : null
        }
      />

      <Card>
        {tariffs.error ? (
          <ErrorState error={tariffs.error} onRetry={() => void tariffs.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('common.name')}</Th>
              <Th>{t('tariffs.kind')}</Th>
              <Th>{t('tariffs.currency')}</Th>
              <Th align="right">{t('tariffs.importPrice')}</Th>
              <Th align="right">{t('tariffs.exportPrice')}</Th>
              <Th align="right">
                <Term id="peakDemand">{t('tariffs.demandCharge')}</Term>
              </Th>
              <Th align="right">{t('tariffs.periods')}</Th>
              <Th align="right">{t('common.actions')}</Th>
            </THead>
            <TBody>
              {tariffs.isPending ? (
                <EmptyRow colSpan={8} message={`${t('common.loading')}…`} />
              ) : (tariffs.data?.length ?? 0) === 0 ? (
                <EmptyRow colSpan={8} message={t('tariffs.empty')} />
              ) : (
                (tariffs.data ?? []).map((tariff) => (
                  <Tr key={tariff.id}>
                    <Td>
                      <span className="font-medium">{tariff.name}</span>
                      {!tariff.is_active ? (
                        <Badge tone="neutral" className="ml-2">
                          {t('common.disabled')}
                        </Badge>
                      ) : null}
                    </Td>
                    <Td>
                      <Badge tone={tariff.kind === 'tou' ? 'brand' : 'neutral'}>
                        {t(`tariffs.kinds.${tariff.kind}`)}
                      </Badge>
                    </Td>
                    <Td className="text-muted">{tariff.currency}</Td>
                    <Td align="right" className="tnum">
                      {formatNumber(tariff.default_import_price, {
                        maximumFractionDigits: 4,
                      })}
                    </Td>
                    <Td align="right" className="tnum text-muted">
                      {formatNumber(tariff.default_export_price, {
                        maximumFractionDigits: 4,
                      })}
                    </Td>
                    <Td align="right" className="tnum text-muted">
                      {formatNumber(tariff.demand_charge_per_kw, {
                        maximumFractionDigits: 2,
                      })}
                    </Td>
                    <Td align="right" className="tnum text-muted">
                      {tariff.periods.length}
                    </Td>
                    <Td align="right">
                      {editable ? (
                        <span className="flex justify-end gap-1">
                          <Button size="sm" onClick={() => setEditing(tariff)}>
                            {t('common.edit')}
                          </Button>
                          <IconButton
                            label={t('tariffs.duplicate')}
                            onClick={() =>
                              setEditing({
                                ...tariff,
                                // A blank id makes the dialog create rather
                                // than update - copying a tariff to try a new
                                // price is the common way to edit one safely.
                                id: '',
                                name: `${tariff.name} (${t('tariffs.copySuffix')})`,
                              })
                            }
                          >
                            <Copy className="size-4" />
                          </IconButton>
                          <IconButton
                            label={t('common.delete')}
                            onClick={() => setDeleting(tariff)}
                          >
                            <Trash2 className="size-4" />
                          </IconButton>
                        </span>
                      ) : null}
                    </Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
        )}
      </Card>

      <TariffUsage />

      <TariffModal
        open={creating || editing !== null}
        tariff={editing}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
      />

      <DeleteTariffDialog tariff={deleting} onClose={() => setDeleting(null)} />
    </>
  )
}

/**
 * Which sites use which tariff - and *why*.
 *
 * A tariff reaches a site through its storage plan, and the plan may be bound
 * to an ancestor rather than the site itself. Showing only "site → tariff"
 * hid that chain, so an operator could not tell whether changing a child's
 * plan would change its tariff. The tree shows the site hierarchy with the
 * plan each site actually runs (own or inherited from whom) and the tariff
 * that plan carries, coloured per tariff so the coverage reads at a glance.
 */
const TARIFF_TONES = ['brand', 'info', 'warning', 'major', 'ok', 'critical'] as const

interface UsageRow {
  site: SiteSummary
  plan: StoragePlan | null
  /** Name of the ancestor the plan is bound to; null when bound directly. */
  inheritedFrom: string | null
  tariff: Tariff | null
}

function TariffUsage() {
  const { t } = useTranslation()
  const sites = useSites()
  const tariffs = useTariffs()
  const plans = useStoragePlans()

  const rows = useMemo<UsageRow[]>(() => {
    // Depth-first tree order: a parent row above its children, siblings by
    // name. The list endpoint sorts by name alone, which put "A棟" above the
    // park it belongs to.
    const all = sites.data?.items ?? []
    const byParent = new Map<string | null, SiteSummary[]>()
    for (const site of all) {
      const key = site.parent_id && all.some((s) => s.id === site.parent_id) ? site.parent_id : null
      byParent.set(key, [...(byParent.get(key) ?? []), site])
    }
    const items: SiteSummary[] = []
    const walk = (parent: string | null) => {
      for (const site of (byParent.get(parent) ?? []).sort((a, b) => a.name.localeCompare(b.name))) {
        items.push(site)
        walk(site.id)
      }
    }
    walk(null)
    const tariffById = new Map((tariffs.data ?? []).map((tariff) => [tariff.id, tariff]))
    const planBySite = new Map<string, StoragePlan>()
    for (const plan of plans.data ?? []) for (const site of plan.sites) planBySite.set(site.id, plan)
    const byId = new Map(items.map((site) => [site.id, site]))
    return items.map((site) => {
      let current: SiteSummary | undefined = site
      let plan: StoragePlan | null = null
      let inheritedFrom: string | null = null
      for (let hop = 0; hop < 20 && current; hop += 1) {
        const found = planBySite.get(current.id)
        if (found) {
          plan = found
          inheritedFrom = current.id === site.id ? null : current.name
          break
        }
        current = current.parent_id ? byId.get(current.parent_id) : undefined
      }
      const tariff = plan?.tariff_id ? tariffById.get(plan.tariff_id) ?? null : null
      return { site, plan, inheritedFrom, tariff }
    })
  }, [plans.data, tariffs.data, sites.data])

  const toneOf = useMemo(() => {
    const map = new Map<string, (typeof TARIFF_TONES)[number]>()
    ;(tariffs.data ?? []).forEach((tariff, index) => map.set(tariff.id, TARIFF_TONES[index % TARIFF_TONES.length]))
    return map
  }, [tariffs.data])

  const coverage = useMemo(() => {
    const counts = new Map<string, number>()
    for (const row of rows) if (row.tariff) counts.set(row.tariff.id, (counts.get(row.tariff.id) ?? 0) + 1)
    return counts
  }, [rows])

  if (rows.length === 0) return null
  const unassigned = rows.filter((row) => !row.tariff).length

  return (
    <Card className="mt-5">
      <CardHeader title={t('tariffs.usage')} description={t('tariffs.usageHint')} />
      <CardBody className="space-y-4">
       <div data-testid="tariff-usage" className="space-y-4">
        <div className="flex flex-wrap gap-2" data-testid="tariff-coverage">
          {(tariffs.data ?? []).map((tariff) => (
            <Badge key={tariff.id} tone={toneOf.get(tariff.id)}>
              {tariff.name} · {t('tariffs.siteCount', { count: coverage.get(tariff.id) ?? 0 })}
            </Badge>
          ))}
          {unassigned > 0 ? <Badge tone="neutral">{t('tariffs.noneAssigned')} · {t('tariffs.siteCount', { count: unassigned })}</Badge> : null}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-1.5 pr-3 font-medium">{t('sites.site')}</th>
                <th className="py-1.5 pr-3 font-medium">{t('tariffs.planColumn')}</th>
                <th className="py-1.5 pr-3 font-medium">{t('tariffs.tariffColumn')}</th>
                <th className="py-1.5 pr-3 text-right font-medium">{t('tariffs.demandChargeColumn')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((row) => {
                const depth = row.site.depth
                return (
                  <tr key={row.site.id} data-testid={`tariff-usage-${row.site.code}`}>
                    <td className="py-2 pr-3">
                      <span className="flex items-center" style={{ paddingLeft: depth * 18 }}>
                        {depth > 0 ? (
                          <span className="mr-1.5 inline-block h-4 w-3 shrink-0 border-b border-l border-line" aria-hidden />
                        ) : null}
                        <span className="font-medium">{row.site.name}</span>
                        <span className="ml-2 font-mono text-xs text-subtle">{row.site.code}</span>
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      {row.plan ? (
                        <span className="flex flex-wrap items-center gap-1.5">
                          <span>{row.plan.name}</span>
                          {row.inheritedFrom ? (
                            <Badge tone="neutral">{t('tariffs.inheritedFrom', { site: row.inheritedFrom })}</Badge>
                          ) : (
                            <Badge tone="brand">{t('tariffs.boundHere')}</Badge>
                          )}
                        </span>
                      ) : (
                        <span className="text-muted">{t('tariffs.noPlan')}</span>
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      {row.tariff ? (
                        <span className="flex flex-wrap items-center gap-1.5">
                          <Badge tone={toneOf.get(row.tariff.id)}>{row.tariff.name}</Badge>
                          <span className="text-xs text-muted">{t(`tariffs.kinds.${row.tariff.kind}`, { defaultValue: row.tariff.kind })}</span>
                        </span>
                      ) : (
                        <span className="text-muted">{t('tariffs.noneAssigned')}</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-xs">
                      {row.tariff ? `${formatNumber(row.tariff.demand_charge_per_kw)} ${row.tariff.currency}/kW` : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
       </div>
      </CardBody>
    </Card>
  )
}

function DeleteTariffDialog({
  tariff,
  onClose,
}: {
  tariff: Tariff | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const { remove } = useTariffMutations()

  return (
    <ConfirmDialog
      open={tariff !== null}
      onClose={onClose}
      danger
      loading={remove.isPending}
      title={t('common.delete')}
      // The API refuses while a storage plan still points at it, which is the
      // check that matters; this message just says so in advance.
      message={t('tariffs.deleteConfirm', { name: tariff?.name ?? '' })}
      confirmLabel={t('common.delete')}
      onConfirm={async () => {
        if (!tariff) return
        try {
          await remove.mutateAsync(tariff.id)
          toast.success(t('tariffs.deleted'))
          onClose()
        } catch (error) {
          toast.error(errorMessage(error))
        }
      }}
    />
  )
}

const EMPTY_FORM = {
  name: '',
  kind: 'tou' as Tariff['kind'],
  currency: 'TWD',
  timezone_name: 'Asia/Taipei',
  demand_charge_per_kw: '0',
  default_import_price: '0',
  default_export_price: '0',
  is_active: true,
}

function TariffModal({
  open,
  tariff,
  onClose,
}: {
  open: boolean
  tariff: Tariff | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const { create, update } = useTariffMutations()
  const presets = useTariffPresets()

  const [form, setForm] = useState(EMPTY_FORM)
  const [periods, setPeriods] = useState<PeriodForm[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const dirty = useFormDirty(open, { form, periods })

  /**
   * Per-period checks. The server validates the period list too, but it
   * reports "periods invalid" for the whole list; this names the row.
   */
  const periodProblems = useMemo(() => {
    const out = new Map<number, { start?: string; end?: string; import_price?: string; export_price?: string }>()
    if (form.kind === 'flat') return out
    periods.forEach((period, index) => {
      const row: { start?: string; end?: string; import_price?: string; export_price?: string } = {}
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(period.start)) row.start = t('tariffs.problems.time')
      if (!/^(([01]\d|2[0-3]):[0-5]\d|24:00)$/.test(period.end)) row.end = t('tariffs.problems.time')
      if (!row.start && !row.end && period.start === period.end) row.end = t('tariffs.problems.empty')
      if (period.import_price !== '' && !(Number(period.import_price) >= 0)) row.import_price = t('tariffs.problems.price')
      if (period.export_price !== '' && !(Number(period.export_price) >= 0)) row.export_price = t('tariffs.problems.price')
      if (period.months.length === 0) row.start = row.start ?? t('tariffs.problems.noMonths')
      if (Object.keys(row).length) out.set(index, row)
    })
    return out
  }, [form.kind, periods, t])
  const periodProblemCount = periodProblems.size

  /** Fill the form from a bundled Taipower table; everything stays editable. */
  function applyPreset(preset: TariffPreset) {
    setForm((current) => ({
      ...current,
      name: current.name.trim() || preset.name,
      kind: preset.tariff.kind,
      currency: preset.tariff.currency,
      timezone_name: preset.tariff.timezone_name,
      demand_charge_per_kw: String(preset.tariff.demand_charge_per_kw),
      default_import_price: String(preset.tariff.default_import_price),
      default_export_price: String(preset.tariff.default_export_price),
    }))
    setPeriods(
      preset.tariff.periods.map((period) => toPeriodForm(period as Record<string, unknown>)),
    )
    toast.success(t('tariffs.presetApplied', { year: preset.tariff_year }))
  }

  const isUpdate = Boolean(tariff?.id)

  useEffect(() => {
    if (!open) return
    setErrors({})
    if (tariff) {
      setForm({
        name: tariff.name,
        kind: tariff.kind,
        currency: tariff.currency,
        timezone_name: tariff.timezone_name,
        demand_charge_per_kw: String(tariff.demand_charge_per_kw),
        default_import_price: String(tariff.default_import_price),
        default_export_price: String(tariff.default_export_price),
        is_active: tariff.is_active,
      })
      setPeriods(tariff.periods.map(toPeriodForm))
    } else {
      setForm(EMPTY_FORM)
      setPeriods([])
    }
  }, [open, tariff?.id])

  function setPeriod(index: number, patch: Partial<PeriodForm>) {
    setPeriods((current) =>
      current.map((period, position) =>
        position === index ? { ...period, ...patch } : period,
      ),
    )
  }

  function toggleWeekday(index: number, day: number) {
    setPeriods((current) =>
      current.map((period, position) => {
        if (position !== index) return period
        const weekdays = period.weekdays.includes(day)
          ? period.weekdays.filter((value) => value !== day)
          : [...period.weekdays, day].sort((a, b) => a - b)
        return { ...period, weekdays }
      }),
    )
  }

  function toggleMonth(index: number, month: number) {
    setPeriods((current) =>
      current.map((period, position) => {
        if (position !== index) return period
        const months = period.months.includes(month)
          ? period.months.filter((value) => value !== month)
          : [...period.months, month].sort((a, b) => a - b)
        return { ...period, months }
      }),
    )
  }

  async function submit() {
    setErrors({})
    const body = {
      name: form.name.trim(),
      kind: form.kind,
      currency: form.currency.trim().toUpperCase(),
      timezone_name: form.timezone_name.trim(),
      demand_charge_per_kw: Number(form.demand_charge_per_kw || 0),
      default_import_price: Number(form.default_import_price || 0),
      default_export_price: Number(form.default_export_price || 0),
      // A flat tariff has no periods by definition; keeping stale ones around
      // would make it silently behave as time-of-use again if the kind were
      // switched back.
      periods: form.kind === 'flat' ? [] : periods.map(fromPeriodForm),
      is_active: form.is_active,
    }

    try {
      if (isUpdate && tariff) {
        await update.mutateAsync({ id: tariff.id, ...body })
      } else {
        await create.mutateAsync(body)
      }
      toast.success(t('common.saved'))
      onClose()
    } catch (error) {
      setErrors(fieldErrors(error))
      toast.error(errorMessage(error))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      dirty={dirty}
      size="lg"
      title={isUpdate ? t('tariffs.edit') : t('tariffs.create')}
      description={t('tariffs.hint')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={create.isPending || update.isPending}
            disabled={!form.name.trim() || periodProblemCount > 0 || (form.kind !== 'flat' && periods.length === 0)}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {(presets.data ?? []).length > 0 ? (
          <div className="rounded-lg border border-line bg-surface-muted p-3">
            <p className="mb-1 text-xs font-medium">{t('tariffs.presetTitle')}</p>
            <p className="mb-2 text-[11px] text-muted">{t('tariffs.presetHint')}</p>
            <div className="flex flex-wrap gap-2">
              {(presets.data ?? []).map((preset) => (
                <Button key={preset.key} title={preset.description} onClick={() => applyPreset(preset)}>
                  {preset.name}
                </Button>
              ))}
            </div>
          </div>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput
            label={t('common.name')}
            required
            value={form.name}
            error={errors.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <Select
            label={t('tariffs.kind')}
            value={form.kind}
            onChange={(event) =>
              setForm({ ...form, kind: event.target.value as Tariff['kind'] })
            }
            options={[
              { value: 'tou', label: t('tariffs.kinds.tou') },
              { value: 'flat', label: t('tariffs.kinds.flat') },
            ]}
            hint={t('tariffs.kindHint')}
          />
          <TextInput
            label={t('tariffs.currency')}
            value={form.currency}
            error={errors.currency}
            onChange={(event) => setForm({ ...form, currency: event.target.value })}
            className="uppercase"
            hint={t('tariffs.currencyHint')}
          />
          <TimezoneSelect
            label={t('tariffs.timezone')}
            value={form.timezone_name}
            error={errors.timezone_name}
            onChange={(zone) => setForm({ ...form, timezone_name: zone })}
            hint={t('tariffs.timezoneHint')}
          />
          <TextInput
            label={t('tariffs.importPrice')}
            type="number"
            step="0.0001"
            min={0}
            value={form.default_import_price}
            error={errors.default_import_price}
            onChange={(event) =>
              setForm({ ...form, default_import_price: event.target.value })
            }
            suffix={`/kWh`}
            hint={t('tariffs.defaultPriceHint')}
          />
          <TextInput
            label={t('tariffs.exportPrice')}
            type="number"
            step="0.0001"
            min={0}
            value={form.default_export_price}
            error={errors.default_export_price}
            onChange={(event) =>
              setForm({ ...form, default_export_price: event.target.value })
            }
            suffix={`/kWh`}
          />
          <TextInput
            label={<Term id="peakDemand">{t('tariffs.demandCharge')}</Term>}
            type="number"
            step="0.01"
            min={0}
            value={form.demand_charge_per_kw}
            error={errors.demand_charge_per_kw}
            onChange={(event) =>
              setForm({ ...form, demand_charge_per_kw: event.target.value })
            }
            suffix="/kW"
            hint={t('tariffs.demandChargeHint')}
          />
          <div className="flex items-end">
            <Checkbox
              label={t('common.enabled')}
              checked={form.is_active}
              onChange={(value) => setForm({ ...form, is_active: value })}
            />
          </div>
        </div>

        {form.kind === 'tou' ? (
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="label mb-0">{t('tariffs.periods')}</span>
              <Button
                size="sm"
                icon={<Plus className="size-3.5" />}
                onClick={() =>
                  setPeriods((current) => [
                    ...current,
                    {
                      name: '',
                      start: '00:00',
                      end: '24:00',
                      months: [],
                      weekdays: [],
                      import_price: '',
                      export_price: '',
                    },
                  ])
                }
              >
                {t('tariffs.addPeriod')}
              </Button>
            </div>

            <p className="hint mb-3">{t('tariffs.periodsHint')}</p>

            {periods.length === 0 ? (
              <CardBody className="rounded-lg border border-dashed border-line text-center">
                <p className="flex items-center justify-center gap-1.5 text-sm text-muted">
                  <Clock className="size-4" aria-hidden />
                  {t('tariffs.noPeriods')}
                </p>
              </CardBody>
            ) : (
              <div className="space-y-3">
                {periods.map((period, index) => (
                  <div
                    key={index}
                    className="rounded-lg border border-line p-3"
                  >
                    <div className="mb-3 flex items-center gap-2">
                      <span className="grid size-6 shrink-0 place-items-center rounded-md bg-surface-muted text-xs font-semibold tnum">
                        {index + 1}
                      </span>
                      <TextInput
                        value={period.name}
                        placeholder={t('tariffs.periodName')}
                        onChange={(event) =>
                          setPeriod(index, { name: event.target.value })
                        }
                        className="flex-1"
                      />
                      <IconButton
                        label={t('common.remove')}
                        onClick={() =>
                          setPeriods((current) =>
                            current.filter((_, position) => position !== index),
                          )
                        }
                      >
                        <Trash2 className="size-4" />
                      </IconButton>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-4">
                      <TextInput
                        label={t('range.from')}
                        type="time"
                        value={period.start}
                        error={periodProblems.get(index)?.start}
                        onChange={(event) =>
                          setPeriod(index, { start: event.target.value })
                        }
                      />
                      <TextInput
                        label={t('range.to')}
                        type="time"
                        value={period.end === '24:00' ? '' : period.end}
                        placeholder="24:00"
                        error={periodProblems.get(index)?.end}
                        onChange={(event) =>
                          setPeriod(index, { end: event.target.value || '24:00' })
                        }
                        hint={t('tariffs.midnightHint')}
                      />
                      <TextInput
                        label={t('tariffs.importPrice')}
                        type="number"
                        step="0.0001"
                        min={0}
                        value={period.import_price}
                        error={periodProblems.get(index)?.import_price}
                        placeholder={form.default_import_price}
                        onChange={(event) =>
                          setPeriod(index, { import_price: event.target.value })
                        }
                      />
                      <TextInput
                        label={t('tariffs.exportPrice')}
                        type="number"
                        step="0.0001"
                        min={0}
                        value={period.export_price}
                        error={periodProblems.get(index)?.export_price}
                        placeholder={form.default_export_price}
                        onChange={(event) =>
                          setPeriod(index, { export_price: event.target.value })
                        }
                      />
                    </div>

                    <div className="mt-3 space-y-2">
                      <div>
                        <span className="label">{t('tariffs.weekdays')}</span>
                        <div className="flex flex-wrap gap-1">
                          {WEEKDAY_KEYS.map((key, day) => (
                            <TogglePill
                              key={key}
                              active={period.weekdays.includes(day)}
                              onClick={() => toggleWeekday(index, day)}
                            >
                              {t(`tariffs.weekdayShort.${key}`)}
                            </TogglePill>
                          ))}
                        </div>
                      </div>
                      <div>
                        <span className="label">{t('tariffs.months')}</span>
                        <div className="flex flex-wrap gap-1">
                          {Array.from({ length: 12 }, (_, offset) => offset + 1).map(
                            (month) => (
                              <TogglePill
                                key={month}
                                active={period.months.includes(month)}
                                onClick={() => toggleMonth(index, month)}
                              >
                                {month}
                              </TogglePill>
                            ),
                          )}
                        </div>
                      </div>
                      <p className="hint">{t('tariffs.emptyMeansAll')}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

function TogglePill({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`min-w-8 rounded-md border px-2 py-1 text-xs font-medium transition-colors ${
        active
          ? 'border-brand bg-brand-soft text-brand'
          : 'border-line text-muted hover:bg-surface-muted'
      }`}
    >
      {children}
    </button>
  )
}

export default TariffsPage
