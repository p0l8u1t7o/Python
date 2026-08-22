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
import type { Tariff, TariffPreset } from '@/lib/types'
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
 * Which sites use which tariff.
 *
 * Shown because a tariff is not a standalone object: editing one moves every
 * cost and savings figure for every site whose storage plan points at it, and
 * that consequence should be visible from the page where the edit happens.
 */
function TariffUsage() {
  const { t } = useTranslation()
  const sites = useSites()
  const tariffs = useTariffs()
  const plans = useStoragePlans()

  const tariffNames = useMemo(
    () => new Map((tariffs.data ?? []).map((tariff) => [tariff.id, tariff.name])),
    [tariffs.data],
  )
  // site id -> tariff name, resolved through the *effective* plan: the
  // site's own binding, else the nearest bound ancestor - same rule the
  // dispatch engine applies.
  const bySite = useMemo(() => {
    const direct = new Map<string, string>()
    for (const plan of plans.data ?? []) {
      const name = plan.tariff_id ? tariffNames.get(plan.tariff_id) : undefined
      if (!name) continue
      for (const site of plan.sites) direct.set(site.id, name)
    }
    const parentOf = new Map(
      (sites.data?.items ?? []).map((site) => [site.id, site.parent_id]),
    )
    const map = new Map<string, string>()
    for (const site of sites.data?.items ?? []) {
      let current: string | null | undefined = site.id
      for (let hop = 0; hop < 20 && current; hop += 1) {
        const found = direct.get(current)
        if (found) {
          map.set(site.id, current === site.id ? found : `${found}`)
          break
        }
        current = parentOf.get(current)
      }
    }
    return map
  }, [plans.data, tariffNames, sites.data])

  // Every site, children included and indented - a tariff bound to a child
  // site is exactly as real as one bound to a root.
  const rows = sites.data?.items ?? []
  if (rows.length === 0) return null

  return (
    <Card className="mt-5">
      <CardHeader title={t('tariffs.usage')} description={t('tariffs.usageHint')} />
      <div className="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((site) => (
          <div key={site.id} className="bg-surface p-3.5">
            <p
              className="truncate text-sm font-medium"
              style={{ paddingLeft: site.depth * 12 }}
            >
              {site.depth > 0 ? '└ ' : ''}
              {site.name}
            </p>
            <p
              className="mt-0.5 truncate text-xs text-muted"
              style={{ paddingLeft: site.depth * 12 }}
            >
              {bySite.get(site.id) ?? t('tariffs.noneAssigned')}
            </p>
          </div>
        ))}
      </div>
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
      size="lg"
      title={isUpdate ? t('tariffs.edit') : t('tariffs.create')}
      description={t('tariffs.hint')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={create.isPending || update.isPending}
            disabled={!form.name.trim()}
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
                        onChange={(event) =>
                          setPeriod(index, { start: event.target.value })
                        }
                      />
                      <TextInput
                        label={t('range.to')}
                        type="time"
                        value={period.end === '24:00' ? '' : period.end}
                        placeholder="24:00"
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
