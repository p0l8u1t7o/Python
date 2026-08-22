import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bell, Pencil, Plus, Trash2 } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import {
  useAlertRuleMutations,
  useAlertRules,
  useAllDevices,
  useBlueprints,
  useMetrics,
  useNotificationChannelMutations,
  useNotificationChannels,
  useSites,
} from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import { formatNumber } from '@/lib/format'
import type {
  AlertRule,
  NotificationChannel,
  Operator,
  RuleScope,
  Severity,
} from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  EmptyRow,
  ErrorState,
  IconButton,
  Modal,
  PageHeader,
  Select,
  SiteTreeSelect,
  SeverityBadge,
  TBody,
  THead,
  Table,
  Td,
  TextArea,
  TextInput,
  Th,
  Tr,
} from '@/components/ui'

const OPERATORS: Operator[] = ['gt', 'gte', 'lt', 'lte', 'eq', 'neq', 'outside', 'inside']
const SCOPES: RuleScope[] = ['organization', 'site', 'device_type', 'device']
const SEVERITIES: Severity[] = ['info', 'warning', 'major', 'critical']

export function RulesPage() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const rules = useAlertRules()
  const { remove } = useAlertRuleMutations()

  const [editing, setEditing] = useState<AlertRule | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<AlertRule | null>(null)

  return (
    <>
      <PageHeader
        title={t('rules.title')}
        description={t('rules.subtitle')}
        actions={
          can('alert:rule:write') ? (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
              {t('rules.create')}
            </Button>
          ) : null
        }
      />

      <Card>
        {rules.error ? (
          <ErrorState error={rules.error} onRetry={() => void rules.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('common.status')}</Th>
              <Th>{t('rules.rule')}</Th>
              <Th>{t('rules.metric')}</Th>
              <Th>{t('rules.operator')}</Th>
              <Th>{t('rules.scope')}</Th>
              <Th align="right">{t('rules.duration')}</Th>
              <Th align="right">{t('dashboard.openAlerts')}</Th>
              <Th />
            </THead>
            <TBody>
              {rules.isPending ? (
                <EmptyRow colSpan={8} message={`${t('common.loading')}…`} />
              ) : rules.data && rules.data.length > 0 ? (
                rules.data.map((rule) => (
                  <Tr key={rule.id}>
                    <Td>
                      <SeverityBadge severity={rule.severity} />
                      {!rule.is_enabled ? (
                        <Badge tone="neutral" className="ml-1.5">
                          {t('common.disabled')}
                        </Badge>
                      ) : null}
                    </Td>
                    <Td className="font-medium">{rule.name}</Td>
                    <Td className="font-mono text-xs text-muted">{rule.metric_key}</Td>
                    <Td className="text-muted">
                      {t(`rules.operators.${rule.operator}`)}{' '}
                      <span className="tnum text-content">
                        {formatNumber(rule.threshold)}
                        {rule.threshold_upper !== null
                          ? ` … ${formatNumber(rule.threshold_upper)}`
                          : ''}
                      </span>
                      {rule.hysteresis > 0 ? (
                        <span className="ml-1.5 text-xs text-subtle">
                          ±{formatNumber(rule.hysteresis)}
                        </span>
                      ) : null}
                    </Td>
                    <Td className="text-muted">{t(`rules.scopes.${rule.scope}`)}</Td>
                    <Td align="right" className="tnum text-muted">
                      {rule.for_duration_seconds}s
                    </Td>
                    <Td align="right">
                      {rule.open_alert_count > 0 ? (
                        <Badge tone="critical">{rule.open_alert_count}</Badge>
                      ) : (
                        <span className="text-subtle">—</span>
                      )}
                    </Td>
                    <Td align="right">
                      {can('alert:rule:write') ? (
                        <span className="flex justify-end gap-1">
                          <IconButton label={t('common.edit')} onClick={() => setEditing(rule)}>
                            <Pencil className="size-3.5" />
                          </IconButton>
                          <IconButton label={t('common.delete')} onClick={() => setDeleting(rule)}>
                            <Trash2 className="size-3.5" />
                          </IconButton>
                        </span>
                      ) : null}
                    </Td>
                  </Tr>
                ))
              ) : (
                <EmptyRow
                  colSpan={8}
                  message={
                    <span className="flex flex-col items-center gap-2">
                      <Bell className="size-6 text-subtle" aria-hidden />
                      {t('rules.noRules')}
                    </span>
                  }
                />
              )}
            </TBody>
          </Table>
        )}
      </Card>

      <ChannelsCard />

      <RuleModal
        open={creating || editing !== null}
        rule={editing}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
      />

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        danger
        loading={remove.isPending}
        title={t('common.delete')}
        confirmLabel={t('common.delete')}
        message={t('rules.deleteConfirm', { name: deleting?.name ?? '' })}
        onConfirm={async () => {
          if (!deleting) return
          try {
            await remove.mutateAsync(deleting.id)
            setDeleting(null)
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />
    </>
  )
}

function RuleModal({
  open,
  rule,
  onClose,
}: {
  open: boolean
  rule: AlertRule | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const metrics = useMetrics()
  const sites = useSites()
  const blueprints = useBlueprints()
  const devices = useAllDevices()
  const channels = useNotificationChannels()
  const { create, update } = useAlertRuleMutations()

  const [form, setForm] = useState({
    name: '',
    description: '',
    is_enabled: true,
    severity: 'warning' as Severity,
    scope: 'organization' as RuleScope,
    site_id: '',
    device_type_id: '',
    device_ids: [] as string[],
    metric_key: '',
    operator: 'gt' as Operator,
    threshold: '',
    threshold_upper: '',
    hysteresis: 0,
    for_duration_seconds: 0,
    cooldown_seconds: 300,
    auto_resolve: true,
    message_template: '',
    channel_ids: [] as string[],
  })

  useEffect(() => {
    if (!open) return
    if (rule) {
      setForm({
        name: rule.name,
        description: rule.description,
        is_enabled: rule.is_enabled,
        severity: rule.severity,
        scope: rule.scope,
        site_id: rule.site_id ?? '',
        device_type_id: rule.device_type_id ?? '',
        device_ids: rule.device_ids,
        metric_key: rule.metric_key,
        operator: rule.operator,
        threshold: rule.threshold?.toString() ?? '',
        threshold_upper: rule.threshold_upper?.toString() ?? '',
        hysteresis: rule.hysteresis,
        for_duration_seconds: rule.for_duration_seconds,
        cooldown_seconds: rule.cooldown_seconds,
        auto_resolve: rule.auto_resolve,
        message_template: rule.message_template,
        channel_ids: rule.channel_ids ?? [],
      })
    } else {
      setForm({
        name: '',
        description: '',
        is_enabled: true,
        severity: 'warning',
        scope: 'organization',
        site_id: '',
        device_type_id: '',
        device_ids: [],
        metric_key: metrics.data?.[0]?.key ?? '',
        operator: 'gt',
        threshold: '',
        threshold_upper: '',
        hysteresis: 0,
        for_duration_seconds: 0,
        cooldown_seconds: 300,
        auto_resolve: true,
        message_template: '',
        channel_ids: [],
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, rule?.id])

  const needsUpper = form.operator === 'outside' || form.operator === 'inside'

  async function submit() {
    const payload = {
      name: form.name.trim(),
      description: form.description,
      is_enabled: form.is_enabled,
      severity: form.severity,
      scope: form.scope,
      site_id: form.scope === 'site' ? form.site_id || null : null,
      device_type_id: form.scope === 'device_type' ? form.device_type_id || null : null,
      device_ids: form.scope === 'device' ? form.device_ids : [],
      metric_key: form.metric_key,
      operator: form.operator,
      threshold: form.threshold === '' ? null : Number(form.threshold),
      threshold_upper: needsUpper && form.threshold_upper !== '' ? Number(form.threshold_upper) : null,
      hysteresis: Number(form.hysteresis),
      for_duration_seconds: Number(form.for_duration_seconds),
      cooldown_seconds: Number(form.cooldown_seconds),
      auto_resolve: form.auto_resolve,
      message_template: form.message_template,
      channel_ids: form.channel_ids,
    }
    try {
      if (rule) await update.mutateAsync({ id: rule.id, ...payload })
      else await create.mutateAsync(payload)
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
      size="lg"
      title={rule ? t('rules.edit') : t('rules.create')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={create.isPending || update.isPending}
            disabled={!form.name || !form.metric_key}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput
            label={t('common.name')}
            required
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <Select
            label={t('severity.warning')}
            value={form.severity}
            onChange={(event) => setForm({ ...form, severity: event.target.value as Severity })}
            options={SEVERITIES.map((value) => ({ value, label: t(`severity.${value}`) }))}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label={t('rules.metric')}
            required
            value={form.metric_key}
            onChange={(event) => setForm({ ...form, metric_key: event.target.value })}
            options={(metrics.data ?? []).map((metric) => ({
              value: metric.key,
              label: `${metric.label} (${metric.key})`,
            }))}
          />
          <Select
            label={t('rules.operator')}
            value={form.operator}
            onChange={(event) => setForm({ ...form, operator: event.target.value as Operator })}
            options={OPERATORS.map((value) => ({ value, label: t(`rules.operators.${value}`) }))}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <TextInput
            label={t('rules.threshold')}
            type="number"
            step="any"
            required
            value={form.threshold}
            onChange={(event) => setForm({ ...form, threshold: event.target.value })}
          />
          {needsUpper ? (
            <TextInput
              label={t('rules.thresholdUpper')}
              type="number"
              step="any"
              required
              value={form.threshold_upper}
              onChange={(event) => setForm({ ...form, threshold_upper: event.target.value })}
            />
          ) : null}
          <TextInput
            label={t('rules.hysteresis')}
            type="number"
            step="any"
            min={0}
            value={String(form.hysteresis)}
            onChange={(event) => setForm({ ...form, hysteresis: Number(event.target.value) })}
            hint={t('rules.hysteresisHint')}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput
            label={t('rules.duration')}
            type="number"
            min={0}
            suffix="s"
            value={String(form.for_duration_seconds)}
            onChange={(event) =>
              setForm({ ...form, for_duration_seconds: Number(event.target.value) })
            }
            hint={t('rules.durationHint')}
          />
          <TextInput
            label={t('rules.cooldown')}
            type="number"
            min={0}
            suffix="s"
            value={String(form.cooldown_seconds)}
            onChange={(event) => setForm({ ...form, cooldown_seconds: Number(event.target.value) })}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label={t('rules.scope')}
            value={form.scope}
            onChange={(event) => setForm({ ...form, scope: event.target.value as RuleScope })}
            options={SCOPES.map((value) => ({ value, label: t(`rules.scopes.${value}`) }))}
          />
          {form.scope === 'site' ? (
            <SiteTreeSelect
              label={t('sites.site')}
              required
              sites={sites.data?.items ?? []}
              value={form.site_id}
              placeholder={t('common.none')}
              onChange={(value) => setForm({ ...form, site_id: value })}
            />
          ) : null}
          {form.scope === 'device_type' ? (
            <Select
              label={t('devices.blueprint')}
              required
              value={form.device_type_id}
              placeholder={t('common.none')}
              onChange={(event) => setForm({ ...form, device_type_id: event.target.value })}
              options={(blueprints.data ?? []).map((blueprint) => ({
                value: blueprint.id,
                label: blueprint.name,
              }))}
            />
          ) : null}
        </div>

        {form.scope === 'device' ? (
          <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-line p-2">
            {(devices.data?.items ?? []).map((device) => (
              <Checkbox
                key={device.id}
                label={`${device.name} (${device.device_id})`}
                checked={form.device_ids.includes(device.id)}
                onChange={(checked) =>
                  setForm({
                    ...form,
                    device_ids: checked
                      ? [...form.device_ids, device.id]
                      : form.device_ids.filter((id) => id !== device.id),
                  })
                }
              />
            ))}
          </div>
        ) : null}

        <TextInput
          label={t('rules.messageTemplate')}
          value={form.message_template}
          onChange={(event) => setForm({ ...form, message_template: event.target.value })}
          placeholder="{device}: {metric} = {value} (limit {threshold})"
          hint={t('rules.messageTemplateHint')}
        />

        <TextArea
          label={t('common.description')}
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
        />

        {channels.data && channels.data.length > 0 ? (
          <div>
            <p className="mb-1 text-xs font-medium text-muted">
              {t('channels.notifyVia')}
            </p>
            <div className="flex flex-wrap gap-x-6 gap-y-1">
              {channels.data.map((channel) => (
                <Checkbox
                  key={channel.id}
                  label={`${channel.name} (${t(`channels.types.${channel.channel_type}`)})`}
                  checked={form.channel_ids.includes(channel.id)}
                  onChange={(checked) =>
                    setForm({
                      ...form,
                      channel_ids: checked
                        ? [...form.channel_ids, channel.id]
                        : form.channel_ids.filter((id) => id !== channel.id),
                    })
                  }
                />
              ))}
            </div>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-6">
          <Checkbox
            label={t('rules.autoResolve')}
            checked={form.auto_resolve}
            onChange={(value) => setForm({ ...form, auto_resolve: value })}
          />
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


const CHANNEL_TYPES: NotificationChannel['channel_type'][] = [
  'email',
  'line',
  'webhook',
  'mqtt',
]
const EVENT_LEVELS = ['info', 'notice', 'warning', 'error', 'critical']

/**
 * Where notifications go: email, a LINE bot, a webhook, MQTT.
 *
 * Lives on the rules page because a channel only matters through what is
 * wired to it - alert rules pick channels in their own form, and the
 * event subscription (device-reported events, by level) lives on the
 * channel itself.
 */
function ChannelsCard() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const channels = useNotificationChannels()
  const { remove } = useNotificationChannelMutations()

  const [editing, setEditing] = useState<NotificationChannel | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<NotificationChannel | null>(null)

  // The channels endpoint is admin-only; a 403 means this operator does not
  // manage notification targets, so the section simply is not there.
  if (channels.isError) return null

  return (
    <>
      <Card className="mt-4">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div>
            <p className="text-sm font-medium">{t('channels.title')}</p>
            <p className="text-xs text-muted">{t('channels.subtitle')}</p>
          </div>
          {can('alert:rule:write') ? (
            <Button icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
              {t('channels.create')}
            </Button>
          ) : null}
        </div>
        <Table>
          <THead>
            <Th>{t('common.name')}</Th>
            <Th>{t('channels.type')}</Th>
            <Th>{t('channels.alertsColumn')}</Th>
            <Th>{t('channels.eventsColumn')}</Th>
            <Th>{t('common.status')}</Th>
            <Th />
          </THead>
          <TBody>
            {(channels.data ?? []).length === 0 ? (
              <EmptyRow colSpan={6} message={t('channels.empty')} />
            ) : (
              (channels.data ?? []).map((channel) => (
                <Tr key={channel.id}>
                  <Td className="font-medium">{channel.name}</Td>
                  <Td className="text-muted">
                    {t(`channels.types.${channel.channel_type}`)}
                  </Td>
                  <Td>
                    {channel.notify_alerts ? (
                      <SeverityBadge severity={channel.min_severity} />
                    ) : (
                      <span className="text-subtle">—</span>
                    )}
                  </Td>
                  <Td>
                    {channel.notify_events ? (
                      <Badge tone="neutral">
                        {t(`events.levels.${channel.min_event_level}`)}+
                      </Badge>
                    ) : (
                      <span className="text-subtle">—</span>
                    )}
                  </Td>
                  <Td>
                    {channel.is_enabled ? (
                      <Badge tone="ok">{t('common.enabled')}</Badge>
                    ) : (
                      <Badge tone="neutral">{t('common.disabled')}</Badge>
                    )}
                  </Td>
                  <Td align="right">
                    <span className="flex justify-end gap-1">
                      <IconButton label={t('common.edit')} onClick={() => setEditing(channel)}>
                        <Pencil className="size-3.5" />
                      </IconButton>
                      <IconButton label={t('common.delete')} onClick={() => setDeleting(channel)}>
                        <Trash2 className="size-3.5" />
                      </IconButton>
                    </span>
                  </Td>
                </Tr>
              ))
            )}
          </TBody>
        </Table>
      </Card>

      <ChannelModal
        open={creating || editing !== null}
        channel={editing}
        onClose={() => {
          setCreating(false)
          setEditing(null)
        }}
      />

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        danger
        loading={remove.isPending}
        title={t('common.delete')}
        confirmLabel={t('common.delete')}
        message={t('channels.deleteConfirm', { name: deleting?.name ?? '' })}
        onConfirm={async () => {
          if (!deleting) return
          try {
            await remove.mutateAsync(deleting.id)
            setDeleting(null)
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />
    </>
  )
}

function ChannelModal({
  open,
  channel,
  onClose,
}: {
  open: boolean
  channel: NotificationChannel | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const { create, update } = useNotificationChannelMutations()

  const [form, setForm] = useState({
    name: '',
    channel_type: 'email' as NotificationChannel['channel_type'],
    is_enabled: true,
    min_severity: 'warning' as Severity,
    notify_alerts: true,
    notify_events: false,
    min_event_level: 'error',
    url: '',
    recipients: '',
    line_token: '',
    line_to: '',
    topic: '',
  })

  useEffect(() => {
    if (!open) return
    if (channel) {
      const config = channel.config ?? {}
      setForm({
        name: channel.name,
        channel_type: channel.channel_type,
        is_enabled: channel.is_enabled,
        min_severity: channel.min_severity,
        notify_alerts: channel.notify_alerts,
        notify_events: channel.notify_events,
        min_event_level: channel.min_event_level,
        url: String(config.url ?? ''),
        recipients: Array.isArray(config.recipients) ? config.recipients.join(', ') : '',
        // Secrets come back redacted; an untouched field keeps the stored one.
        line_token: '',
        line_to: String(config.to ?? ''),
        topic: String(config.topic ?? ''),
      })
    } else {
      setForm({
        name: '',
        channel_type: 'email',
        is_enabled: true,
        min_severity: 'warning',
        notify_alerts: true,
        notify_events: false,
        min_event_level: 'error',
        url: '',
        recipients: '',
        line_token: '',
        line_to: '',
        topic: '',
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, channel?.id])

  async function submit() {
    const config: Record<string, unknown> = {}
    if (form.channel_type === 'webhook') config.url = form.url.trim()
    if (form.channel_type === 'email') {
      config.recipients = form.recipients
        .split(/[,;\s]+/)
        .map((entry) => entry.trim())
        .filter(Boolean)
    }
    if (form.channel_type === 'line') {
      // Blank means "keep the stored token" on update; the server merges it.
      config.channel_access_token = form.line_token.trim()
      config.to = form.line_to.trim()
    }
    if (form.channel_type === 'mqtt') config.topic = form.topic.trim()

    const payload = {
      name: form.name.trim(),
      channel_type: form.channel_type,
      is_enabled: form.is_enabled,
      min_severity: form.min_severity,
      notify_alerts: form.notify_alerts,
      notify_events: form.notify_events,
      min_event_level: form.min_event_level,
      config,
    }
    try {
      if (channel) await update.mutateAsync({ id: channel.id, ...payload })
      else await create.mutateAsync(payload)
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
      title={channel ? t('channels.edit') : t('channels.create')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={create.isPending || update.isPending}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <TextInput
          label={t('common.name')}
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          required
        />

        <Select
          label={t('channels.type')}
          value={form.channel_type}
          onChange={(event) =>
            setForm({
              ...form,
              channel_type: event.target.value as NotificationChannel['channel_type'],
            })
          }
          options={CHANNEL_TYPES.map((type) => ({
            value: type,
            label: t(`channels.types.${type}`),
          }))}
        />

        {form.channel_type === 'webhook' ? (
          <TextInput
            label="URL"
            value={form.url}
            onChange={(event) => setForm({ ...form, url: event.target.value })}
            placeholder="https://example.com/hook"
            required
          />
        ) : null}

        {form.channel_type === 'email' ? (
          <TextArea
            label={t('channels.recipients')}
            value={form.recipients}
            onChange={(event) => setForm({ ...form, recipients: event.target.value })}
            hint={t('channels.recipientsHint')}
            rows={2}
            required
          />
        ) : null}

        {form.channel_type === 'line' ? (
          <>
            <TextInput
              label={t('channels.lineToken')}
              type="password"
              value={form.line_token}
              onChange={(event) => setForm({ ...form, line_token: event.target.value })}
              placeholder={channel ? t('channels.secretKept') : undefined}
              hint={t('channels.lineTokenHint')}
              required={!channel}
            />
            <TextInput
              label={t('channels.lineTo')}
              value={form.line_to}
              onChange={(event) => setForm({ ...form, line_to: event.target.value })}
              hint={t('channels.lineToHint')}
              required
            />
          </>
        ) : null}

        {form.channel_type === 'mqtt' ? (
          <TextInput
            label="Topic"
            value={form.topic}
            onChange={(event) => setForm({ ...form, topic: event.target.value })}
            required
          />
        ) : null}

        <div className="space-y-3 border-t border-line pt-3">
          <Checkbox
            label={t('channels.notifyAlerts')}
            hint={t('channels.notifyAlertsHint')}
            checked={form.notify_alerts}
            onChange={(notify_alerts) => setForm({ ...form, notify_alerts })}
          />
          {form.notify_alerts ? (
            <Select
              label={t('channels.minSeverity')}
              value={form.min_severity}
              onChange={(event) =>
                setForm({ ...form, min_severity: event.target.value as Severity })
              }
              options={SEVERITIES.map((severity) => ({
                value: severity,
                label: t(`severity.${severity}`),
              }))}
            />
          ) : null}

          <Checkbox
            label={t('channels.notifyEvents')}
            hint={t('channels.notifyEventsHint')}
            checked={form.notify_events}
            onChange={(notify_events) => setForm({ ...form, notify_events })}
          />
          {form.notify_events ? (
            <Select
              label={t('channels.minEventLevel')}
              value={form.min_event_level}
              onChange={(event) =>
                setForm({ ...form, min_event_level: event.target.value })
              }
              options={EVENT_LEVELS.map((level) => ({
                value: level,
                label: t(`events.levels.${level}`),
              }))}
            />
          ) : null}
        </div>

        <Checkbox
          label={t('common.enabled')}
          checked={form.is_enabled}
          onChange={(is_enabled) => setForm({ ...form, is_enabled })}
        />
      </div>
    </Modal>
  )
}
