import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useToast } from '@/providers/ToastProvider'
import { useAllDevices, useCostModels, useDevice, useEmsMutations } from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import { useFormDirty } from '@/lib/useFormDirty'
import type { AssetRole, EnergyAsset } from '@/lib/types'
import { Button, Checkbox, Modal, Select, TextInput } from '@/components/ui'

const ROLES: AssetRole[] = ['grid_meter', 'load_meter', 'pv', 'battery', 'ev_charger', 'generator']

/** Which metric bindings each role uses; the rest are hidden rather than ignored. */
const BINDINGS: Record<AssetRole, ('power' | 'import' | 'export' | 'soc' | 'soh' | 'voltage')[]> = {
  grid_meter: ['power', 'import', 'export', 'voltage'],
  load_meter: ['power', 'import'],
  pv: ['power', 'import'],
  battery: ['power', 'import', 'export', 'soc', 'soh'],
  ev_charger: ['power', 'import'],
  generator: ['power', 'import'],
}

/** Sensible defaults by role: what a device of that kind usually reports. */
const DEFAULT_METRICS: Record<AssetRole, Partial<Record<'power' | 'import' | 'export' | 'soc' | 'soh' | 'voltage', string>>> = {
  grid_meter: { power: 'grid_power_w', import: 'grid_import_energy_kwh', export: 'grid_export_energy_kwh', voltage: 'grid_voltage_v' },
  load_meter: { power: 'load_power_w', import: 'load_energy_kwh' },
  pv: { power: 'pv_power_w', import: 'pv_energy_kwh' },
  battery: {
    power: 'battery_power_w', soc: 'battery_soc', soh: 'battery_soh',
    import: 'battery_charge_energy_kwh', export: 'battery_discharge_energy_kwh',
  },
  ev_charger: { power: 'charger_power_w', import: 'charger_energy_kwh' },
  generator: { power: 'generator_power_w', import: 'generator_energy_kwh' },
}

const EMPTY = {
  device_id: '',
  role: 'battery' as AssetRole,
  name: '',
  power_metric: '',
  energy_import_metric: '',
  energy_export_metric: '',
  soc_metric: '',
  soh_metric: '',
  voltage_metric: '',
  power_scale: '0.001',
  energy_scale: '1',
  invert_sign: false,
  include_in_balance: true,
  rated_power_kw: '',
  rated_energy_kwh: '',
  is_active: true,
  session_tracking_enabled: false,
  session_enter_kw: '',
  session_exit_kw: '',
  session_min_duration_s: '60',
  session_gap_s: '300',
  cost_model: '',
  cycle_cost_per_kwh: '',
  fuel_price_per_litre: '',
  litres_per_kwh: '',
}
type Form = typeof EMPTY

/**
 * Bind a device and its metric keys to an energy role at one site.
 *
 * This is the form the whole storage page depends on: without a binding the
 * aggregator has nothing to integrate, and every cost and savings figure
 * stays at zero. The metric pickers list what the device has actually
 * reported, with the usual key for the role pre-filled, so the common case is
 * "pick the device, confirm, save".
 */
export function AssetEditor({
  open,
  siteId,
  asset,
  onClose,
}: {
  open: boolean
  siteId: string
  asset: EnergyAsset | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const { createAsset, updateAsset } = useEmsMutations()
  const devices = useAllDevices({ enabled: open })
  const costModels = useCostModels()
  const [form, setForm] = useState<Form>(EMPTY)
  const dirty = useFormDirty(open, form)
  const device = useDevice(form.device_id || undefined)

  useEffect(() => {
    if (!open) return
    if (asset) {
      const params = asset.cost_parameters ?? {}
      setForm({
        device_id: asset.device_id,
        role: asset.role,
        name: asset.name,
        power_metric: asset.power_metric,
        energy_import_metric: asset.energy_import_metric,
        energy_export_metric: asset.energy_export_metric,
        soc_metric: asset.soc_metric,
        soh_metric: asset.soh_metric,
        voltage_metric: asset.voltage_metric ?? '',
        power_scale: String(asset.power_scale),
        energy_scale: String(asset.energy_scale),
        invert_sign: asset.invert_sign,
        include_in_balance: asset.include_in_balance ?? true,
        rated_power_kw: asset.rated_power_kw === null ? '' : String(asset.rated_power_kw),
        rated_energy_kwh: asset.rated_energy_kwh === null ? '' : String(asset.rated_energy_kwh),
        is_active: asset.is_active,
        session_tracking_enabled: asset.session_tracking_enabled,
        session_enter_kw: asset.session_enter_kw === null ? '' : String(asset.session_enter_kw),
        session_exit_kw: asset.session_exit_kw === null ? '' : String(asset.session_exit_kw),
        session_min_duration_s: String(asset.session_min_duration_s),
        session_gap_s: String(asset.session_gap_s),
        cost_model: asset.cost_model ?? '',
        cycle_cost_per_kwh: params.cycle_cost_per_kwh === undefined ? '' : String(params.cycle_cost_per_kwh),
        fuel_price_per_litre: params.fuel_price_per_litre === undefined ? '' : String(params.fuel_price_per_litre),
        litres_per_kwh: params.litres_per_kwh === undefined ? '' : String(params.litres_per_kwh),
      })
    } else {
      setForm(EMPTY)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, asset?.id])

  // Devices at this site first; the rest after a divider, in case the asset
  // is metered by equipment registered elsewhere.
  const deviceOptions = useMemo(() => {
    const list = devices.data?.items ?? []
    const here = list.filter((d) => d.site_id === siteId)
    const elsewhere = list.filter((d) => d.site_id !== siteId)
    return [
      ...here.map((d) => ({ value: d.id, label: `${d.name} (${d.device_id})` })),
      ...elsewhere.map((d) => ({ value: d.id, label: `${d.name} (${d.device_id}) — ${d.site_name ?? '—'}` })),
    ]
  }, [devices.data, siteId])

  // What the chosen device has actually reported, so a binding can be picked
  // rather than typed - a typo here is a silent zero on every chart.
  const reported = useMemo(() => {
    const keys = (device.data?.latest ?? []).map((m) => m.metric_key)
    return Array.from(new Set(keys)).sort()
  }, [device.data])

  function metricOptions(current: string) {
    const options = reported.map((key) => ({ value: key, label: key }))
    if (current && !reported.includes(current)) options.unshift({ value: current, label: `${current} *` })
    return options
  }

  function setRole(role: AssetRole) {
    const defaults = DEFAULT_METRICS[role]
    setForm((f) => ({
      ...f,
      role,
      power_metric: f.power_metric || defaults.power || '',
      energy_import_metric: f.energy_import_metric || defaults.import || '',
      energy_export_metric: f.energy_export_metric || defaults.export || '',
      soc_metric: f.soc_metric || defaults.soc || '',
      soh_metric: f.soh_metric || defaults.soh || '',
      voltage_metric: f.voltage_metric || defaults.voltage || '',
    }))
  }

  const bindings = BINDINGS[form.role]
  const num = (value: string) => (value.trim() === '' ? null : Number(value))
  const problems: Partial<Record<keyof Form, string>> = {}
  if (!form.device_id) problems.device_id = t('assets.problems.device')
  if (!form.power_metric && form.role !== 'load_meter') problems.power_metric = t('assets.problems.powerMetric')
  if (form.role === 'battery' && !form.soc_metric) problems.soc_metric = t('assets.problems.socMetric')
  if (!(Number(form.power_scale) !== 0 && Number.isFinite(Number(form.power_scale)))) problems.power_scale = t('assets.problems.scale')
  for (const key of ['rated_power_kw', 'rated_energy_kwh', 'session_enter_kw', 'session_exit_kw'] as const) {
    const value = num(form[key])
    if (value !== null && !(value > 0)) problems[key] = t('assets.problems.positive')
  }
  const enter = num(form.session_enter_kw)
  const exit = num(form.session_exit_kw)
  if (enter !== null && exit !== null && exit > enter) problems.session_exit_kw = t('assets.problems.exitAboveEnter')
  const problemCount = Object.keys(problems).length

  async function submit() {
    const cost_parameters: Record<string, unknown> = { ...(asset?.cost_parameters ?? {}) }
    for (const key of ['cycle_cost_per_kwh', 'fuel_price_per_litre', 'litres_per_kwh'] as const) {
      const value = num(form[key])
      if (value === null) delete cost_parameters[key]
      else cost_parameters[key] = value
    }
    const body = {
      site_id: siteId,
      device_id: form.device_id,
      role: form.role,
      name: form.name.trim(),
      power_metric: bindings.includes('power') ? form.power_metric : '',
      energy_import_metric: bindings.includes('import') ? form.energy_import_metric : '',
      energy_export_metric: bindings.includes('export') ? form.energy_export_metric : '',
      soc_metric: bindings.includes('soc') ? form.soc_metric : '',
      soh_metric: bindings.includes('soh') ? form.soh_metric : '',
      voltage_metric: bindings.includes('voltage') ? form.voltage_metric : '',
      power_scale: Number(form.power_scale),
      energy_scale: Number(form.energy_scale || 1),
      invert_sign: form.invert_sign,
      include_in_balance: form.include_in_balance,
      rated_power_kw: num(form.rated_power_kw),
      rated_energy_kwh: num(form.rated_energy_kwh),
      is_active: form.is_active,
      session_tracking_enabled: form.session_tracking_enabled,
      session_enter_kw: num(form.session_enter_kw),
      session_exit_kw: num(form.session_exit_kw),
      session_min_duration_s: Number(form.session_min_duration_s || 60),
      session_gap_s: Number(form.session_gap_s || 300),
      cost_model: form.cost_model,
      cost_parameters,
    }
    try {
      if (asset) await updateAsset.mutateAsync({ id: asset.id, ...body })
      else await createAsset.mutateAsync(body)
      toast.success(t('common.saved'))
      onClose()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const metricField = (
    key: 'power_metric' | 'energy_import_metric' | 'energy_export_metric' | 'soc_metric' | 'soh_metric' | 'voltage_metric',
    label: string,
    required: boolean,
  ) => (
    <Select
      label={label}
      required={required}
      value={form[key]}
      placeholder={t('common.none')}
      options={metricOptions(form[key])}
      error={problems[key]}
      hint={form.device_id && reported.length === 0 ? t('assets.noReadingsYet') : undefined}
      onChange={(event) => setForm({ ...form, [key]: event.target.value })}
    />
  )

  return (
    <Modal
      open={open}
      onClose={onClose}
      dirty={dirty}
      size="lg"
      title={asset ? t('assets.edit') : t('assets.create')}
      description={t('assets.hint')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            disabled={problemCount > 0}
            loading={createAsset.isPending || updateAsset.isPending}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label={t('assets.device')}
            required
            value={form.device_id}
            placeholder={t('assets.pickDevice')}
            options={deviceOptions}
            error={problems.device_id}
            onChange={(event) => setForm({ ...form, device_id: event.target.value })}
          />
          <Select
            label={t('storage.role')}
            required
            value={form.role}
            options={ROLES.map((role) => ({ value: role, label: t(`storage.roles.${role}`) }))}
            onChange={(event) => setRole(event.target.value as AssetRole)}
          />
        </div>
        <TextInput
          label={t('common.name')}
          value={form.name}
          placeholder={device.data?.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />

        <div className="space-y-3 rounded-lg border border-line p-3">
          <p className="text-xs font-medium">{t('assets.bindings')}</p>
          <p className="text-xs text-muted">{t('assets.bindingsHint')}</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {bindings.includes('power') ? metricField('power_metric', t('storage.powerMetric'), form.role !== 'load_meter') : null}
            {bindings.includes('soc') ? metricField('soc_metric', t('storage.socMetric'), true) : null}
            {bindings.includes('soh') ? metricField('soh_metric', t('assets.sohMetric'), false) : null}
            {bindings.includes('voltage') ? metricField('voltage_metric', t('assets.voltageMetric'), false) : null}
            {bindings.includes('import') ? metricField('energy_import_metric', t('assets.importMetric'), false) : null}
            {bindings.includes('export') ? metricField('energy_export_metric', t('assets.exportMetric'), false) : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <TextInput
              label={t('assets.powerScale')}
              value={form.power_scale}
              error={problems.power_scale}
              hint={t('assets.powerScaleHint')}
              onChange={(event) => setForm({ ...form, power_scale: event.target.value })}
            />
            <TextInput
              label={t('assets.energyScale')}
              value={form.energy_scale}
              onChange={(event) => setForm({ ...form, energy_scale: event.target.value })}
            />
            <div className="space-y-2 pt-5">
              <Checkbox
                label={t('assets.invertSign')}
                hint={t('assets.invertSignHint')}
                checked={form.invert_sign}
                onChange={(invert_sign) => setForm({ ...form, invert_sign })}
              />
            </div>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <TextInput
            label={t('assets.ratedPower')}
            type="number"
            suffix="kW"
            value={form.rated_power_kw}
            error={problems.rated_power_kw}
            onChange={(event) => setForm({ ...form, rated_power_kw: event.target.value })}
          />
          {form.role === 'battery' ? (
            <TextInput
              label={t('assets.ratedEnergy')}
              type="number"
              suffix="kWh"
              value={form.rated_energy_kwh}
              error={problems.rated_energy_kwh}
              onChange={(event) => setForm({ ...form, rated_energy_kwh: event.target.value })}
            />
          ) : null}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Checkbox
            label={t('assets.includeInBalance')}
            hint={t('assets.includeInBalanceHint')}
            checked={form.include_in_balance}
            onChange={(include_in_balance) => setForm({ ...form, include_in_balance })}
          />
          <Checkbox
            label={t('common.enabled')}
            checked={form.is_active}
            onChange={(is_active) => setForm({ ...form, is_active })}
          />
        </div>

        <div className="space-y-3 rounded-lg border border-line p-3">
          <Checkbox
            label={t('assets.sessionTracking')}
            hint={t('assets.sessionTrackingHint')}
            checked={form.session_tracking_enabled}
            onChange={(session_tracking_enabled) => setForm({ ...form, session_tracking_enabled })}
          />
          {form.session_tracking_enabled ? (
            <div className="grid gap-3 sm:grid-cols-4">
              <TextInput
                label={t('assets.sessionEnter')}
                type="number"
                suffix="kW"
                value={form.session_enter_kw}
                error={problems.session_enter_kw}
                hint={t('assets.sessionEnterHint')}
                onChange={(event) => setForm({ ...form, session_enter_kw: event.target.value })}
              />
              <TextInput
                label={t('assets.sessionExit')}
                type="number"
                suffix="kW"
                value={form.session_exit_kw}
                error={problems.session_exit_kw}
                hint={t('assets.sessionExitHint')}
                onChange={(event) => setForm({ ...form, session_exit_kw: event.target.value })}
              />
              <TextInput
                label={t('assets.sessionMin')}
                type="number"
                suffix="s"
                value={form.session_min_duration_s}
                onChange={(event) => setForm({ ...form, session_min_duration_s: event.target.value })}
              />
              <TextInput
                label={t('assets.sessionGap')}
                type="number"
                suffix="s"
                value={form.session_gap_s}
                onChange={(event) => setForm({ ...form, session_gap_s: event.target.value })}
              />
            </div>
          ) : null}
        </div>

        <div className="space-y-3 rounded-lg border border-line p-3">
          <Select
            label={t('assets.costModel')}
            value={form.cost_model}
            placeholder={t('assets.costModelDefault')}
            hint={t('assets.costModelHint')}
            options={(costModels.data ?? []).map((model) => ({
              value: model.key,
              label: t(`assets.costModels.${model.key}`, { defaultValue: model.key }),
            }))}
            onChange={(event) => setForm({ ...form, cost_model: event.target.value })}
          />
          {(form.cost_model || (form.role === 'battery' ? 'battery_cycle' : '')) === 'battery_cycle' ? (
            <TextInput
              label={t('assets.cycleCost')}
              type="number"
              step="0.01"
              value={form.cycle_cost_per_kwh}
              hint={t('assets.cycleCostHint')}
              onChange={(event) => setForm({ ...form, cycle_cost_per_kwh: event.target.value })}
            />
          ) : null}
          {(form.cost_model || (form.role === 'generator' ? 'diesel_fuel' : '')) === 'diesel_fuel' ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <TextInput
                label={t('assets.fuelPrice')}
                type="number"
                step="0.01"
                value={form.fuel_price_per_litre}
                onChange={(event) => setForm({ ...form, fuel_price_per_litre: event.target.value })}
              />
              <TextInput
                label={t('assets.litresPerKwh')}
                type="number"
                step="0.001"
                value={form.litres_per_kwh}
                onChange={(event) => setForm({ ...form, litres_per_kwh: event.target.value })}
              />
            </div>
          ) : null}
        </div>
      </div>
    </Modal>
  )
}
