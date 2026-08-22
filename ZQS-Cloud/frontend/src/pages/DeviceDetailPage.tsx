import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  KeyRound,
  Pencil,
  Replace,
  Send,
  SlidersHorizontal,
  Trash2,
} from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import {
  useBlueprints,
  useCancelCommand,
  useDevice,
  useDeviceDeclaration,
  useDeviceEnergy,
  useLifecycleMutation,
  useReplaceDevice,
  useReviewDeclaration,
  useDeviceCommands,
  useDeviceEvents,
  useDeviceMetricKeys,
  useDeviceMutations,
  useDeviceStatusHistory,
  useOperatingSessions,
  useSendCommand,
  useSeries,
  useSites,
  useUiPreference,
} from '@/lib/queries'
import { currentLanguage } from '@/i18n'
import { errorMessage, fieldErrors } from '@/lib/errors'
import {
  formatDateTime,
  formatDuration,
  formatCurrency,
  formatMeasurement,
  formatPercent,
  formatRelative,
  secondsSince,
} from '@/lib/format'
import { useTimeRange } from '@/lib/useTimeRange'
import type { GlossaryId } from '@/lib/glossary'
import type {
  CommandDefinition,
  CommandParamSpec,
  Device,
  DeviceCredential,
  DeviceDetail,
  DeviceReplacement,
} from '@/lib/types'
import { TimeSeriesChart } from '@/components/charts/TimeSeriesChart'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  CommandStatusBadge,
  ConfirmDialog,
  ConnectionBadge,
  DetailRow,
  DeviceIcon,
  DeviceIconBadge,
  EmptyRow,
  ErrorState,
  EventLevelBadge,
  LoadingState,
  MetricPicker,
  Modal,
  PageHeader,
  Pagination,
  SegmentedControl,
  Select,
  SiteTreeSelect,
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
import { BlueprintPicker, CredentialPanel } from './DevicesPage'

type Tab = 'overview' | 'history' | 'commands' | 'events' | 'status'

export function DeviceDetailPage() {
  const { deviceId = '' } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { can } = useAuth()
  const toast = useToast()

  const [tab, setTab] = useState<Tab>('overview')
  const [editing, setEditing] = useState(false)
  const [replacing, setReplacing] = useState(false)
  const [showCommand, setShowCommand] = useState(false)
  const [showDelete, setShowDelete] = useState(false)
  const [credential, setCredential] = useState<DeviceCredential | null>(null)

  const device = useDevice(deviceId)
  const { remove, rotateCredential } = useDeviceMutations()

  if (device.isPending) return <LoadingState />
  if (device.error) return <ErrorState error={device.error} onRetry={() => void device.refetch()} />
  if (!device.data) return null

  const detail = device.data
  const staleSeconds = secondsSince(detail.last_seen_at)

  return (
    <>
      <Link
        to="/devices"
        className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-content"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t('devices.title')}
      </Link>

      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2.5">
            <DeviceIconBadge category={detail.device_category} />
            {detail.name}
            <ConnectionBadge status={detail.status} />
            {detail.commissioning_state !== 'active' ? (
              <Badge tone={LIFECYCLE_TONE[detail.commissioning_state]}>
                {t(`devices.lifecycleStates.${detail.commissioning_state}`)}
              </Badge>
            ) : null}
            {detail.identity_mismatch ? (
              <Badge tone="critical">{t('devices.identityMismatch')}</Badge>
            ) : null}
            {detail.open_alert_count > 0 ? (
              <Badge tone="critical">
                {t('devices.openAlerts', { count: detail.open_alert_count })}
              </Badge>
            ) : null}
          </span>
        }
        description={
          <span className="font-mono text-xs">{detail.device_id}</span>
        }
        actions={
          <>
            {can('device:command') ? (
              <Button
                variant="primary"
                icon={<Send className="size-4" />}
                onClick={() => setShowCommand(true)}
                disabled={detail.available_commands.length === 0}
              >
                {t('devices.sendCommand')}
              </Button>
            ) : null}
            {can('device:write') ? (
              <Button
                icon={<Pencil className="size-4" />}
                onClick={() => setEditing(true)}
              >
                {t('common.edit')}
              </Button>
            ) : null}
            {can('device:write') ? (
              <LifecycleActions device={detail} onReplace={() => setReplacing(true)} />
            ) : null}
            {can('device:write') ? (
              <>
                <Button
                  icon={<KeyRound className="size-4" />}
                  loading={rotateCredential.isPending}
                  onClick={async () => {
                    try {
                      setCredential(await rotateCredential.mutateAsync(detail.id))
                    } catch (error) {
                      toast.error(errorMessage(error))
                    }
                  }}
                >
                  {t('devices.rotateCredential')}
                </Button>
                <Button
                  variant="ghost"
                  icon={<Trash2 className="size-4" />}
                  onClick={() => setShowDelete(true)}
                  aria-label={t('common.delete')}
                />
              </>
            ) : null}
          </>
        }
      />

      <div className="mb-4">
        <SegmentedControl<Tab>
          value={tab}
          onChange={setTab}
          options={[
            { value: 'overview', label: t('devices.overview') },
            { value: 'history', label: t('devices.history') },
            { value: 'commands', label: t('devices.commands') },
            { value: 'events', label: t('devices.events') },
            { value: 'status', label: t('devices.statusHistory') },
          ]}
        />
      </div>

      {tab === 'overview' ? (
        <div className="grid gap-5 lg:grid-cols-3">
          <LatestValuesCard device={detail} />

          <Card>
            <CardHeader title={t('devices.overview')} />
            <CardBody>
              <dl className="divide-y divide-line">
                <DetailRow label={t('devices.deviceId')} mono>
                  {detail.device_id}
                </DetailRow>
                <DetailRow label={t('devices.site')}>{detail.site_name ?? '—'}</DetailRow>
                {/*
                  The gateway is only shown when it is a real one. An implicit
                  node exists purely so a directly-connected device has
                  somewhere to hold its MQTT session, and surfacing it would
                  just repeat the device's own name back at the operator.
                */}
                {!detail.edge_node_is_implicit && (
                  <DetailRow label={t('devices.edgeNode')}>
                    {detail.edge_node_name || '—'}
                  </DetailRow>
                )}
                <DetailRow label={t('devices.sparkplugAddress')} mono>
                  {detail.sparkplug_address || '—'}
                </DetailRow>
                <DetailRow label={t('devices.category')}>
                  {detail.device_category ? (
                    <span className="inline-flex items-center gap-1.5">
                      <DeviceIcon category={detail.device_category} />
                      {t(`devices.categories.${detail.device_category}`, {
                        defaultValue: detail.device_category,
                      })}
                    </span>
                  ) : (
                    '—'
                  )}
                </DetailRow>
                <DetailRow label={<Term id="blueprint">{t('devices.blueprint')}</Term>}>
                  {detail.device_type_name ?? '—'}
                </DetailRow>
                <DetailRow label={t('devices.serialNumber')}>
                  {detail.serial_number || '—'}
                </DetailRow>
                <DetailRow label={t('devices.firmware')}>
                  {detail.firmware_version || '—'}
                </DetailRow>
                <DetailRow label={t('devices.hardware')}>
                  {detail.hardware_version || '—'}
                </DetailRow>
                <DetailRow label={t('devices.ipAddress')} mono>
                  {detail.ip_address ?? '—'}
                </DetailRow>
                <DetailRow label={t('devices.signal')}>
                  {detail.rssi !== null ? `${detail.rssi} dBm` : '—'}
                </DetailRow>
                <DetailRow label={t('devices.lastSeen')}>
                  {detail.last_seen_at ? formatDateTime(detail.last_seen_at) : t('common.never')}
                </DetailRow>
                <DetailRow label={<Term id="telemetry">{t('devices.lastTelemetry')}</Term>}>
                  {detail.last_telemetry_at
                    ? formatDateTime(detail.last_telemetry_at)
                    : t('common.never')}
                </DetailRow>
                <DetailRow label={t('devices.location')}>
                  {detail.latitude !== null && detail.longitude !== null
                    ? `${detail.latitude.toFixed(5)}, ${detail.longitude.toFixed(5)}`
                    : '—'}
                </DetailRow>
                {detail.location_source ? (
                  <DetailRow label={t('devices.locationSource')}>
                    {detail.location_source}
                  </DetailRow>
                ) : null}
                <DetailRow label={<Term id="capabilities">{t('devices.capabilities')}</Term>}>
                  <CapabilityBadges device={detail} />
                </DetailRow>
                <DetailRow label={t('devices.capabilitySource')}>
                  {t(`devices.capabilitySources.${detail.capability_source}`)}
                </DetailRow>
                <DetailRow label={<Term id="lifecycle">{t('devices.lifecycle')}</Term>}>
                  <Badge tone={LIFECYCLE_TONE[detail.commissioning_state]}>
                    {/* The state itself is where "what does suspended mean?"
                        actually gets asked, so the value carries the term. */}
                    <Term id={LIFECYCLE_TERMS[detail.commissioning_state]}>
                      {t(`devices.lifecycleStates.${detail.commissioning_state}`)}
                    </Term>
                  </Badge>
                </DetailRow>
                {detail.retired_at ? (
                  <DetailRow label={t('devices.retiredAt')}>
                    {formatDateTime(detail.retired_at)}
                  </DetailRow>
                ) : null}
                {detail.capital_cost !== null ? (
                  <DetailRow label={t('devices.capitalCost')}>
                    {formatCurrency(detail.capital_cost, detail.cost_currency || undefined)}
                  </DetailRow>
                ) : null}
                {detail.annual_cost !== null ? (
                  <DetailRow label={t('devices.annualCost')}>
                    {formatCurrency(detail.annual_cost, detail.cost_currency || undefined)}
                  </DetailRow>
                ) : null}
              </dl>

              {detail.commissioning_state === 'pending' ? (
                <p className="mt-3 rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">
                  {t('devices.pendingCommissioning')}
                </p>
              ) : null}
              {detail.capabilities_unchecked ? (
                <p className="mt-3 rounded-lg bg-surface-muted px-3 py-2 text-xs text-muted">
                  {t('devices.noBlueprintWarning')}
                </p>
              ) : null}

              {staleSeconds !== null && staleSeconds > 300 ? (
                <p className="mt-3 rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">
                  {t('devices.stale', { duration: formatDuration(staleSeconds) })}
                </p>
              ) : null}
            </CardBody>
          </Card>
        </div>
      ) : null}

      {detail.identity_mismatch ? (
        <Card className="mt-5 border-critical">
          <CardBody className="space-y-2">
            <p className="text-sm font-medium text-critical">
              {t('devices.identityMismatchTitle')}
            </p>
            <p className="text-sm text-muted">{t('devices.identityMismatchHint')}</p>
            {can('device:write') ? (
              <Button variant="primary" onClick={() => setReplacing(true)}>
                {t('devices.replace')}
              </Button>
            ) : null}
          </CardBody>
        </Card>
      ) : null}

      {tab === 'overview' ? (
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <EnergyCard deviceId={detail.id} />
          <SessionsCard deviceId={detail.id} />
        </div>
      ) : null}

      {tab === 'overview' ? <DeclarationCard deviceId={detail.id} /> : null}

      <EditDeviceModal
        open={editing}
        device={detail}
        onClose={() => setEditing(false)}
      />

      <ReplaceModal
        open={replacing}
        device={detail}
        onClose={() => setReplacing(false)}
      />

      {tab === 'history' ? <HistoryTab deviceId={detail.id} /> : null}
      {tab === 'commands' ? <CommandsTab deviceId={detail.id} /> : null}
      {tab === 'events' ? <EventsTab deviceId={detail.id} /> : null}
      {tab === 'status' ? <StatusTab deviceId={detail.id} /> : null}

      <SendCommandModal
        open={showCommand}
        onClose={() => setShowCommand(false)}
        deviceId={detail.id}
        deviceName={detail.name}
        commands={detail.available_commands}
      />

      <Modal
        open={credential !== null}
        onClose={() => setCredential(null)}
        title={<Term id="mqtt">{t('devices.credentials')}</Term>}
        description={t('devices.rotateWarning')}
        footer={
          <Button variant="primary" onClick={() => setCredential(null)}>
            {t('common.close')}
          </Button>
        }
      >
        {credential ? <CredentialPanel credential={credential} /> : null}
      </Modal>

      <ConfirmDialog
        open={showDelete}
        onClose={() => setShowDelete(false)}
        danger
        loading={remove.isPending}
        title={t('common.delete')}
        message={t('devices.deleteConfirm', { name: detail.name })}
        confirmLabel={t('common.delete')}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(detail.id)
            navigate('/devices')
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
function HistoryTab({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation()
  const range = useTimeRange('24h')
  const metricKeys = useDeviceMetricKeys(deviceId)
  const [selected, setSelected] = useState<string[]>([])

  const active = selected.length > 0 ? selected : (metricKeys.data ?? []).slice(0, 3)

  const series = useSeries(
    {
      device_ids: [deviceId],
      metrics: active,
      start: range.start,
      end: range.end,
      max_points: 1200,
    },
    active.length > 0,
  )

  return (
    <Card>
      <CardHeader
        title={t('devices.history')}
        description={
          series.data
            ? series.data.downsampled
              ? t('telemetry.downsampled', {
                  interval: `${series.data.interval_seconds}s`,
                })
              : t('telemetry.raw')
            : undefined
        }
        actions={<TimeRangePicker range={range} />}
      />
      <CardBody>
        {metricKeys.data && metricKeys.data.length > 0 ? (
          <div className="mb-4 flex flex-wrap gap-1.5">
            {metricKeys.data.map((key) => {
              const isActive = active.includes(key)
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() =>
                    setSelected((current) => {
                      const base = current.length > 0 ? current : active
                      return base.includes(key)
                        ? base.filter((item) => item !== key)
                        : [...base, key]
                    })
                  }
                  className={`rounded-full border px-2.5 py-1 font-mono text-xs transition-colors ${
                    isActive
                      ? 'border-brand bg-brand-soft text-brand'
                      : 'border-line text-muted hover:text-content'
                  }`}
                >
                  {key}
                </button>
              )
            })}
          </div>
        ) : null}

        {active.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted">{t('telemetry.noSelection')}</p>
        ) : series.isPending ? (
          <LoadingState />
        ) : series.error ? (
          <ErrorState error={series.error} onRetry={() => void series.refetch()} />
        ) : (
          <TimeSeriesChart
            series={series.data?.series ?? []}
            spanSeconds={range.seconds}
            height={340}
          />
        )}
      </CardBody>
    </Card>
  )
}

function CommandsTab({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { can } = useAuth()
  const [offset, setOffset] = useState(0)
  const commands = useDeviceCommands(deviceId, { limit: 20, offset })
  const cancel = useCancelCommand()

  return (
    <Card>
      <CardHeader title={t('commands.title')} />
      <Table>
        <THead>
          <Th>{t('common.status')}</Th>
          <Th>{t('commands.command')}</Th>
          <Th>{t('commands.parameters')}</Th>
          <Th>{t('commands.issuedBy')}</Th>
          <Th align="right">{t('common.created')}</Th>
          <Th />
        </THead>
        <TBody>
          {commands.isPending ? (
            <EmptyRow colSpan={6} message={`${t('common.loading')}…`} />
          ) : commands.data && commands.data.items.length > 0 ? (
            commands.data.items.map((command) => {
              const terminal = ['succeeded', 'rejected', 'failed', 'expired', 'cancelled'].includes(
                command.status,
              )
              return (
                <Tr key={command.id}>
                  <Td>
                    <CommandStatusBadge status={command.status} />
                  </Td>
                  <Td className="font-medium">{command.name}</Td>
                  <Td className="max-w-xs truncate font-mono text-xs text-muted">
                    {Object.keys(command.params).length > 0
                      ? JSON.stringify(command.params)
                      : '—'}
                  </Td>
                  <Td className="text-muted">{command.issued_by_label || '—'}</Td>
                  <Td align="right" className="whitespace-nowrap text-muted">
                    {formatRelative(command.created_at)}
                  </Td>
                  <Td align="right">
                    {!terminal && can('device:command') ? (
                      <Button
                        size="sm"
                        loading={cancel.isPending}
                        onClick={() =>
                          cancel
                            .mutateAsync(command.id)
                            .catch((error) => toast.error(errorMessage(error)))
                        }
                      >
                        {t('common.cancel')}
                      </Button>
                    ) : command.error ? (
                      <span className="text-xs text-critical" title={command.error}>
                        {command.error.slice(0, 40)}
                      </span>
                    ) : null}
                  </Td>
                </Tr>
              )
            })
          ) : (
            <EmptyRow colSpan={6} message={t('commands.noCommands')} />
          )}
        </TBody>
      </Table>
      {commands.data ? (
        <Pagination total={commands.data.total} limit={20} offset={offset} onChange={setOffset} />
      ) : null}
    </Card>
  )
}

function EventsTab({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation()
  const range = useTimeRange('7d')
  const [offset, setOffset] = useState(0)
  const [level, setLevel] = useState('')

  const events = useDeviceEvents(deviceId, {
    limit: 30,
    offset,
    start: range.start,
    end: range.end,
    level: level || undefined,
  })

  return (
    <Card>
      <CardHeader
        title={<Term id="uplink">{t('devices.events')}</Term>}
        actions={
          <div className="flex items-center gap-2">
            <Select
              value={level}
              placeholder={t('common.all')}
              onChange={(event) => {
                setLevel(event.target.value)
                setOffset(0)
              }}
              options={['info', 'notice', 'warning', 'error', 'critical'].map((value) => ({
                value,
                label: t(`events.levels.${value}`),
              }))}
              className="w-32"
            />
            <TimeRangePicker range={range} />
          </div>
        }
      />
      <Table>
        <THead>
          <Th>{t('events.level')}</Th>
          <Th>{t('events.code')}</Th>
          <Th>{t('events.message')}</Th>
          <Th align="right">{t('common.time')}</Th>
        </THead>
        <TBody>
          {events.isPending ? (
            <EmptyRow colSpan={4} message={`${t('common.loading')}…`} />
          ) : events.data && events.data.items.length > 0 ? (
            events.data.items.map((event) => (
              <Tr key={event.id}>
                <Td>
                  <EventLevelBadge level={event.level} />
                </Td>
                <Td className="font-mono text-xs">{event.code || '—'}</Td>
                <Td>{event.message || '—'}</Td>
                <Td align="right" className="whitespace-nowrap text-muted">
                  {formatDateTime(event.ts)}
                </Td>
              </Tr>
            ))
          ) : (
            <EmptyRow colSpan={4} message={t('devices.noEvents')} />
          )}
        </TBody>
      </Table>
      {events.data ? (
        <Pagination total={events.data.total} limit={30} offset={offset} onChange={setOffset} />
      ) : null}
    </Card>
  )
}

function StatusTab({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation()
  const range = useTimeRange('7d')
  const [offset, setOffset] = useState(0)
  const history = useDeviceStatusHistory(deviceId, {
    limit: 30,
    offset,
    start: range.start,
    end: range.end,
  })

  return (
    <Card>
      <CardHeader
        title={<Term id="lwt">{t('devices.statusHistory')}</Term>}
        actions={
          <TimeRangePicker range={range} />
        }
      />
      <Table>
        <THead>
          <Th>{t('common.status')}</Th>
          <Th>{t('common.type')}</Th>
          <Th align="right">{t('common.time')}</Th>
        </THead>
        <TBody>
          {history.isPending ? (
            <EmptyRow colSpan={3} message={`${t('common.loading')}…`} />
          ) : history.data && history.data.items.length > 0 ? (
            history.data.items.map((event) => (
              <Tr key={event.id}>
                <Td>
                  <ConnectionBadge status={event.status} />
                </Td>
                <Td className="text-muted">{event.reason || '—'}</Td>
                <Td align="right" className="whitespace-nowrap text-muted">
                  {formatDateTime(event.ts)}
                </Td>
              </Tr>
            ))
          ) : (
            <EmptyRow colSpan={3} message={t('common.noData')} />
          )}
        </TBody>
      </Table>
      {history.data ? (
        <Pagination total={history.data.total} limit={30} offset={offset} onChange={setOffset} />
      ) : null}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Command dispatch
// ---------------------------------------------------------------------------
function commandLabel(definition: CommandDefinition): string {
  const language = currentLanguage()
  return definition.label?.[language] ?? definition.label?.en ?? definition.name
}

function SendCommandModal({
  open,
  onClose,
  deviceId,
  deviceName,
  commands,
}: {
  open: boolean
  onClose: () => void
  deviceId: string
  deviceName: string
  commands: CommandDefinition[]
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const send = useSendCommand(deviceId)

  const [name, setName] = useState(commands[0]?.name ?? '')
  const [values, setValues] = useState<Record<string, unknown>>({})

  const definition = useMemo(
    () => commands.find((command) => command.name === name),
    [commands, name],
  )
  const properties = definition?.params?.properties ?? {}
  const required = definition?.params?.required ?? []

  function updateValue(key: string, spec: CommandParamSpec, raw: string | boolean) {
    setValues((current) => {
      const next = { ...current }
      if (spec.type === 'boolean') {
        next[key] = Boolean(raw)
      } else if (spec.type === 'number' || spec.type === 'integer') {
        // Keep the field clearable: an empty string means "not supplied".
        next[key] = raw === '' ? undefined : Number(raw)
      } else {
        next[key] = raw === '' ? undefined : raw
      }
      return next
    })
  }

  const missing = required.filter(
    (key) => values[key] === undefined || values[key] === null || values[key] === '',
  )

  async function submit() {
    const params: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(values)) {
      if (value !== undefined && value !== '') params[key] = value
    }
    try {
      await send.mutateAsync({ name, params })
      toast.success(t('devices.commandSent'))
      setValues({})
      onClose()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  if (commands.length === 0) {
    return (
      <Modal open={open} onClose={onClose} title={t('devices.sendCommand')}>
        <p className="text-sm text-muted">{t('devices.noCommands')}</p>
      </Modal>
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('devices.sendCommand')}
      description={deviceName}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant={definition?.confirm ? 'danger' : 'primary'}
            loading={send.isPending}
            disabled={missing.length > 0}
            icon={<Send className="size-4" />}
            onClick={() => void submit()}
          >
            {t('devices.sendCommand')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Select
          label={t('commands.command')}
          value={name}
          onChange={(event) => {
            setName(event.target.value)
            setValues({})
          }}
          options={commands.map((command) => ({
            value: command.name,
            label: commandLabel(command),
          }))}
        />

        {Object.entries(properties).map(([key, spec]) => {
          const isRequired = required.includes(key)
          if (spec.type === 'boolean') {
            return (
              <Checkbox
                key={key}
                label={key}
                checked={Boolean(values[key])}
                onChange={(checked) => updateValue(key, spec, checked)}
              />
            )
          }
          if (spec.enum) {
            return (
              <Select
                key={key}
                label={key}
                required={isRequired}
                value={String(values[key] ?? '')}
                placeholder={isRequired ? undefined : t('common.none')}
                onChange={(event) => updateValue(key, spec, event.target.value)}
                options={spec.enum.map((option) => ({ value: option, label: option }))}
              />
            )
          }
          return (
            <TextInput
              key={key}
              label={key}
              required={isRequired}
              type={spec.type === 'number' || spec.type === 'integer' ? 'number' : 'text'}
              step={spec.type === 'integer' ? 1 : 'any'}
              min={spec.minimum}
              max={spec.maximum}
              suffix={spec.unit}
              value={String(values[key] ?? '')}
              onChange={(event) => updateValue(key, spec, event.target.value)}
              hint={
                spec.minimum !== undefined || spec.maximum !== undefined
                  ? `${spec.minimum ?? '−∞'} … ${spec.maximum ?? '∞'}`
                  : undefined
              }
            />
          )
        })}

        {definition?.confirm ? (
          <p className="rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">
            {t('commands.confirmBody', {
              command: commandLabel(definition),
              device: deviceName,
            })}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}


/** Effective capabilities - what the platform accepted, not what was claimed. */
function CapabilityBadges({ device }: { device: Device }) {
  const { t } = useTranslation()
  const entries: [keyof typeof device.capabilities, GlossaryId, string][] = [
    ['can_charge', 'canCharge', t('devices.canCharge')],
    ['can_discharge', 'canDischarge', t('devices.canDischarge')],
    ['can_export', 'canExport', t('devices.canExport')],
    ['is_dispatchable', 'isDispatchable', t('devices.isDispatchable')],
  ]
  return (
    <span className="flex flex-wrap gap-1">
      {entries.map(([key, term, label]) => (
        <Badge key={key} tone={device.capabilities[key] ? 'ok' : 'neutral'}>
          <Term id={term}>{label}</Term>
        </Badge>
      ))}
    </span>
  )
}

/**
 * What the device says about itself, and the accept/reject decision.
 *
 * Deliberately presented as a claim awaiting review rather than as fact:
 * accepting is the only path by which any of this reaches the fields that gate
 * commands, and it takes an administrator.
 */
function DeclarationCard({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const declaration = useDeviceDeclaration(deviceId)
  const review = useReviewDeclaration(deviceId)

  if (declaration.isPending || declaration.error || !declaration.data) return null
  const record = declaration.data
  const differences = Object.entries(record.diff_summary)

  async function decide(accept: boolean) {
    try {
      await review.mutateAsync({ accept })
      toast.success(t('common.saved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Card className="mt-5">
      <CardHeader
        title={<Term id="declaration">{t('devices.declaration')}</Term>}
        description={t('devices.declarationHint')}
        actions={<Badge tone={record.has_differences ? 'warning' : 'neutral'}>{
          t(`devices.declarationStates.${record.state}`)
        }</Badge>}
      />
      <CardBody className="space-y-3">
        {differences.length > 0 ? (
          <dl className="space-y-1 text-sm">
            {differences.map(([field, values]) => (
              <div key={field} className="flex items-baseline gap-2">
                <dt className="w-40 shrink-0 text-muted">{field}</dt>
                <dd className="flex gap-2">
                  <span className="text-warning">
                    {t('devices.declared')}: {String(values.declared)}
                  </span>
                  <span className="text-subtle">
                    {t('devices.effective')}: {String(values.effective)}
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-muted">{t('devices.declarationMatches')}</p>
        )}

        <pre className="max-h-48 overflow-auto rounded-lg bg-surface-muted p-3 text-xs">
          {JSON.stringify(record.payload, null, 2)}
        </pre>

        {can('device:write') && record.state === 'mismatched' ? (
          <div className="flex gap-2">
            <Button
              variant="primary"
              loading={review.isPending}
              onClick={() => void decide(true)}
            >
              {t('devices.acceptDeclaration')}
            </Button>
            <Button loading={review.isPending} onClick={() => void decide(false)}>
              {t('devices.rejectDeclaration')}
            </Button>
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}


/** How each lifecycle state should read at a glance. */
/** Each lifecycle state points at its own glossary entry. */
const LIFECYCLE_TERMS: Record<Device['commissioning_state'], GlossaryId> = {
  pending: 'lifecyclePending',
  active: 'lifecycleActive',
  suspended: 'lifecycleSuspended',
  retired: 'lifecycleRetired',
  rejected: 'lifecycleRejected',
}

const LIFECYCLE_TONE: Record<Device['commissioning_state'], 'ok' | 'warning' | 'critical' | 'neutral'> = {
  pending: 'warning',
  active: 'ok',
  suspended: 'warning',
  retired: 'neutral',
  rejected: 'critical',
}

/**
 * Suspend, retire, or bring a device back.
 *
 * Retiring never deletes: the row and its history stay, the device simply
 * stops connecting. Bringing one back is allowed - hardware does return from
 * repair - and the server refuses if whatever replaced it is still in service.
 */
function LifecycleActions({
  device,
  onReplace,
}: {
  device: Device
  onReplace: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const lifecycle = useLifecycleMutation(device.id)

  async function move(state: Device['commissioning_state']) {
    try {
      await lifecycle.mutateAsync({ state })
      toast.success(t('common.saved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  if (device.commissioning_state === 'retired') {
    return (
      <Button loading={lifecycle.isPending} onClick={() => void move('active')}>
        {t('devices.returnToService')}
      </Button>
    )
  }

  return (
    <>
      {device.commissioning_state === 'suspended' ? (
        <Button loading={lifecycle.isPending} onClick={() => void move('active')}>
          {t('devices.resume')}
        </Button>
      ) : (
        <Button loading={lifecycle.isPending} onClick={() => void move('suspended')}>
          {t('devices.suspend')}
        </Button>
      )}
      <Button icon={<Replace className="size-4" />} onClick={onReplace}>
        {t('devices.replace')}
      </Button>
    </>
  )
}

/**
 * The replacement wizard.
 *
 * A replacement is several steps that are only correct together - the asset
 * bindings especially, since one left on a silent device makes the site's
 * energy balance quietly incomplete. The server does all of it in a single
 * transaction; this form just collects the new identifier.
 */
function ReplaceModal({
  open,
  device,
  onClose,
}: {
  open: boolean
  device: Device
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const replace = useReplaceDevice(device.id)
  const [form, setForm] = useState({ device_id: '', name: '', serial_number: '', reason: '' })
  const [result, setResult] = useState<DeviceReplacement | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Keyed on the id, not the object: a refetch returns a new object even when
  // nothing changed, and re-seeding on that resets the fields while they are
  // being typed into.
  useEffect(() => {
    if (!open) return
    setResult(null)
    setErrors({})
    setForm({
      device_id: `${device.device_id}-R2`,
      name: device.name,
      serial_number: '',
      reason: '',
    })
  }, [open, device.id])

  async function submit() {
    setErrors({})
    try {
      setResult(await replace.mutateAsync(form))
      toast.success(t('common.saved'))
    } catch (error) {
      setErrors(fieldErrors(error))
      toast.error(errorMessage(error))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('devices.replaceTitle', { name: device.name })}
      footer={
        result ? (
          <Button variant="primary" onClick={onClose}>
            {t('common.close')}
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              loading={replace.isPending}
              disabled={!form.device_id || !form.name}
              onClick={() => void submit()}
            >
              {t('devices.replaceConfirm')}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="space-y-3 text-sm">
          <p>
            {t('devices.replaceDone', {
              assets: result.moved_asset_count,
              rules: result.moved_alert_rule_count,
            })}
          </p>
          {result.credential ? (
            <div className="rounded-lg bg-surface-muted p-3 font-mono text-xs">
              <div>{result.credential.mqtt_username}</div>
              <div>{result.credential.mqtt_password}</div>
              <p className="mt-2 font-sans text-muted">{t('devices.credentialOnce')}</p>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">{t('devices.replaceHint')}</p>
          <TextInput
            label={t('devices.newDeviceId')}
            required
            className="font-mono"
            value={form.device_id}
            error={errors.device_id}
            hint={t('devices.newDeviceIdHint')}
            onChange={(event) => setForm({ ...form, device_id: event.target.value })}
          />
          <TextInput
            label={t('common.name')}
            required
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <TextInput
            label={t('devices.serialNumber')}
            value={form.serial_number}
            onChange={(event) => setForm({ ...form, serial_number: event.target.value })}
          />
          <TextInput
            label={t('devices.replaceReason')}
            value={form.reason}
            onChange={(event) => setForm({ ...form, reason: event.target.value })}
          />
        </div>
      )}
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Editing, energy and sessions
// ---------------------------------------------------------------------------
/**
 * The device's current readings, in the order this person arranged them.
 *
 * A battery can publish forty values and nobody wants forty tiles. The
 * selection is per user and per device, saved server-side so it follows them
 * to another machine - a layout that lives in one browser's localStorage is a
 * layout you rebuild on every laptop.
 *
 * With nothing saved, everything the device reports is shown in the order the
 * API returns it. That is the honest default: the alternative - guessing a
 * "useful" subset - hides readings somebody installed the equipment to see.
 */
function LatestValuesCard({ device }: { device: DeviceDetail }) {
  const { t } = useTranslation()
  const toast = useToast()
  const [picking, setPicking] = useState(false)

  const layout = useUiPreference<{ keys: string[] }>(
    `device-metrics:${device.id}`,
    { keys: [] },
  )
  const chosen = layout.value.keys

  const byKey = new Map(device.latest.map((metric) => [metric.metric_key, metric]))
  const visible = chosen.length
    ? // A metric the device has stopped sending drops out rather than
      // rendering an empty tile; if it comes back, so does its position.
      chosen.map((key) => byKey.get(key)).filter((metric) => metric !== undefined)
    : device.latest

  return (
    <>
      <Card className="lg:col-span-2">
        <CardHeader
          title={t('devices.latestValues')}
          description={
            chosen.length ? t('devices.customisedValues') : t('devices.allValuesShownHint')
          }
          actions={
            <Button
              size="sm"
              icon={<SlidersHorizontal className="size-3.5" />}
              disabled={device.latest.length === 0}
              onClick={() => setPicking(true)}
            >
              {t('common.edit')}
            </Button>
          }
        />
        {visible.length === 0 ? (
          <CardBody>
            <p className="text-sm text-muted">
              {device.latest.length === 0
                ? t('common.noData')
                : t('devices.noneSelectedHint')}
            </p>
          </CardBody>
        ) : (
          <div className="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((metric) => (
              <div key={metric.metric_key} className="bg-surface p-3.5">
                <p className="truncate text-xs text-muted" title={metric.metric_key}>
                  {metric.label}
                </p>
                <p className="mt-1 text-lg font-semibold tnum">
                  {metric.value !== null
                    ? formatMeasurement(metric.value, metric.unit)
                    : (metric.value_text ?? '—')}
                </p>
                <p className="mt-0.5 text-[11px] text-subtle">
                  {formatRelative(metric.ts)}
                  {metric.quality !== 0 ? (
                    <Badge tone="warning" className="ml-1.5">
                      suspect
                    </Badge>
                  ) : null}
                </p>
              </div>
            ))}
          </div>
        )}
      </Card>

      <MetricPicker
        open={picking}
        onClose={() => setPicking(false)}
        available={device.latest}
        selected={chosen.length ? chosen : device.latest.map((m) => m.metric_key)}
        saving={layout.save.isPending}
        onSave={async (keys) => {
          try {
            await layout.save.mutateAsync({ keys })
            setPicking(false)
            toast.success(t('common.saved'))
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
        onReset={async () => {
          try {
            await layout.reset.mutateAsync()
            setPicking(false)
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />
    </>
  )
}


/**
 * Edit the registered details a person chose: the name, the site, the
 * blueprint.
 *
 * A device belongs to exactly one site, so this is a reassignment rather than
 * an addition - the previous site simply stops holding it, and its history
 * stays attached to the device either way.
 *
 * The device ID is deliberately absent. It is the MQTT topic segment and it is
 * unique platform-wide; changing it would orphan every stored sample from the
 * equipment that produced them. Replacement hardware gets a *new* device via
 * "Replace", which is the flow that keeps the history attributable.
 */
function EditDeviceModal({
  open,
  device,
  onClose,
}: {
  open: boolean
  device: Device
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const sites = useSites()
  const blueprints = useBlueprints()
  const { update } = useDeviceMutations()

  const shape = () => ({
    name: device.name,
    site_id: device.site_id ?? '',
    device_type_id: device.device_type_id ?? '',
    serial_number: device.serial_number,
    description: device.description,
    // Numbers are held as strings while being edited, so a half-typed
    // "12000" does not become NaN and blank the field under the cursor.
    capital_cost: device.capital_cost === null ? '' : String(device.capital_cost),
    cost_currency: device.cost_currency,
    commissioned_on: device.commissioned_on ?? '',
    expected_life_years:
      device.expected_life_years === null ? '' : String(device.expected_life_years),
    annual_maintenance_cost:
      device.annual_maintenance_cost === null
        ? ''
        : String(device.annual_maintenance_cost),
  })

  const [form, setForm] = useState(shape)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Reopening after a refetch should show what is stored, not what was
  // captured when this component first mounted.
  useEffect(() => {
    if (open) {
      setForm(shape())
      setErrors({})
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, device.id])

  const siteChanged = (device.site_id ?? '') !== form.site_id

  async function submit() {
    setErrors({})
    try {
      const optional = (value: string) => (value === '' ? null : Number(value))
      await update.mutateAsync({
        id: device.id,
        name: form.name.trim(),
        site_id: form.site_id || null,
        device_type_id: form.device_type_id || null,
        serial_number: form.serial_number.trim(),
        description: form.description,
        capital_cost: optional(form.capital_cost),
        cost_currency: form.cost_currency.trim().toUpperCase(),
        commissioned_on: form.commissioned_on || null,
        expected_life_years: optional(form.expected_life_years),
        annual_maintenance_cost: optional(form.annual_maintenance_cost),
      })
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
      title={t('devices.edit')}
      description={t('devices.editHint')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={update.isPending}
            disabled={!form.name.trim()}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextInput
          label={t('devices.registeredName')}
          required
          value={form.name}
          error={errors.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
        />
        <SiteTreeSelect
          label={t('devices.site')}
          sites={sites.data?.items ?? []}
          value={form.site_id}
          placeholder={t('common.none')}
          allowClear
          error={errors.site_id}
          hint={siteChanged ? t('devices.siteChangeHint') : t('devices.siteHint')}
          onChange={(value) => setForm({ ...form, site_id: value })}
        />
        <BlueprintPicker
          label={<Term id="blueprint">{t('devices.blueprint')}</Term>}
          blueprints={blueprints.data ?? []}
          value={form.device_type_id}
          error={errors.device_type_id}
          onChange={(value) => setForm({ ...form, device_type_id: value })}
        />
        <TextInput
          label={t('devices.serialNumber')}
          value={form.serial_number}
          error={errors.serial_number}
          hint={t('devices.serialHint')}
          onChange={(event) => setForm({ ...form, serial_number: event.target.value })}
        />
        <TextInput
          label={t('common.description')}
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
        />

        <div className="border-t border-line pt-4">
          <p className="label mb-0">{t('devices.costSection')}</p>
          <p className="hint mb-3">{t('devices.costSectionHint')}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextInput
              label={t('devices.capitalCost')}
              type="number"
              min={0}
              step="1000"
              value={form.capital_cost}
              error={errors.capital_cost}
              onChange={(event) => setForm({ ...form, capital_cost: event.target.value })}
            />
            <TextInput
              label={t('tariffs.currency')}
              value={form.cost_currency}
              className="uppercase"
              onChange={(event) => setForm({ ...form, cost_currency: event.target.value })}
            />
            <TextInput
              label={t('devices.commissionedOn')}
              type="date"
              value={form.commissioned_on}
              hint={t('devices.commissionedOnHint')}
              onChange={(event) =>
                setForm({ ...form, commissioned_on: event.target.value })
              }
            />
            <TextInput
              label={t('devices.expectedLife')}
              type="number"
              min={0}
              step="0.5"
              suffix={t('devices.years')}
              value={form.expected_life_years}
              onChange={(event) =>
                setForm({ ...form, expected_life_years: event.target.value })
              }
            />
            <TextInput
              label={t('devices.maintenanceCost')}
              type="number"
              min={0}
              step="1000"
              suffix={t('devices.perYear')}
              value={form.annual_maintenance_cost}
              onChange={(event) =>
                setForm({ ...form, annual_maintenance_cost: event.target.value })
              }
            />
            <div className="flex items-end">
              <p className="text-xs text-muted">
                {t('devices.annualCost')}:{' '}
                <span className="font-medium text-content tnum">
                  {formatCurrency(device.annual_cost, device.cost_currency || undefined)}
                </span>
              </p>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  )
}

/**
 * How much energy this one device moved.
 *
 * Reads the basis out loud rather than showing a bare number: a differenced
 * counter is exact, an integrated power gauge is an approximation whose error
 * grows as the reporting interval does. Coverage below 80% is called
 * incomplete instead of being quietly rounded into the total.
 */
function EnergyCard({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation()
  const range = useTimeRange('24h')
  const [metric, setMetric] = useState('')
  const energy = useDeviceEnergy(deviceId, {
    start: range.start,
    end: range.end,
    ...(metric ? { metric_key: metric } : {}),
  })

  const data = energy.data
  const incomplete = data ? data.basis === 'integrated' && data.coverage < 0.8 : false

  return (
    <Card>
      <CardHeader
        title={t('devices.energy')}
        description={t('devices.energyHint')}
        actions={<TimeRangePicker range={range} />}
      />
      <CardBody className="space-y-3">
        {energy.isPending ? (
          <LoadingState />
        ) : energy.error ? (
          <ErrorState error={energy.error} onRetry={() => void energy.refetch()} />
        ) : data ? (
          <>
            <div className="flex items-baseline gap-2">
              <span className="tnum text-2xl font-semibold">
                {data.kwh === null ? '—' : formatMeasurement(data.kwh, 'kWh', 1)}
              </span>
              <Badge tone={data.basis === 'counter' ? 'ok' : 'neutral'}>
                {t(`devices.energyBasis.${data.basis}`)}
              </Badge>
            </div>

            {data.kwh === null ? (
              <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">
                {data.counter_reset
                  ? t('devices.counterReset')
                  : t('devices.energyUnknown')}
              </p>
            ) : null}
            {incomplete ? (
              <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">
                {t('devices.energyIncomplete', {
                  percent: Math.round(data.coverage * 100),
                })}
              </p>
            ) : null}

            <dl className="divide-y divide-line">
              <DetailRow label={t('devices.energyMetric')} mono>
                {data.metric_key || '—'}
              </DetailRow>
              <DetailRow label={t('devices.energyCoverage')}>
                {data.basis === 'counter' ? '100%' : formatPercent(data.coverage)}
              </DetailRow>
              <DetailRow label={t('devices.energyAverage')}>
                {formatMeasurement(data.avg_kw, 'kW', 2)}
              </DetailRow>
              <DetailRow label={t('devices.energyPeak')}>
                {formatMeasurement(data.peak_kw, 'kW', 2)}
              </DetailRow>
            </dl>

            {data.available_metrics.length > 1 ? (
              <Select
                label={t('devices.energyMetric')}
                value={metric}
                placeholder={t('devices.energyAuto')}
                onChange={(event) => setMetric(event.target.value)}
                options={data.available_metrics.map((key) => ({ value: key, label: key }))}
              />
            ) : null}
          </>
        ) : null}
      </CardBody>
    </Card>
  )
}

/**
 * The last few times this device charged, discharged or ran.
 *
 * An open session is shown as open rather than filled in with "now": a machine
 * that has been running for 37 days is a real and useful answer, not a missing
 * end time.
 */
function SessionsCard({ deviceId }: { deviceId: string }) {
  const { t } = useTranslation()
  const sessions = useOperatingSessions({ device_pk: deviceId, limit: 8 })

  return (
    <Card>
      <CardHeader title={t('devices.sessions')} description={t('devices.sessionsHint')} />
      {sessions.isPending ? (
        <LoadingState />
      ) : sessions.error ? (
        <ErrorState error={sessions.error} onRetry={() => void sessions.refetch()} />
      ) : (
        <Table>
          <THead>
            <Th>{t('devices.sessionKind')}</Th>
            <Th>{t('devices.sessionStarted')}</Th>
            <Th align="right">{t('devices.sessionDuration')}</Th>
            <Th align="right">{t('devices.sessionEnergy')}</Th>
          </THead>
          <TBody>
            {(sessions.data?.items ?? []).map((session) => (
              <Tr key={session.id}>
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
                <Td align="right" className="tnum text-muted">
                  {session.ended_at === null ? (
                    <Badge tone="ok">{t('devices.sessionOpen')}</Badge>
                  ) : (
                    formatDuration(session.duration_s)
                  )}
                </Td>
                <Td align="right" className="tnum">
                  {formatMeasurement(session.energy_kwh, 'kWh', 2)}
                </Td>
              </Tr>
            ))}
            {(sessions.data?.items.length ?? 0) === 0 ? (
              <EmptyRow colSpan={4} message={t('devices.noSessions')} />
            ) : null}
          </TBody>
        </Table>
      )}
    </Card>
  )
}
