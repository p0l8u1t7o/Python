import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bell, Pencil, Plus, Send, Trash2 } from 'lucide-react'

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
import { formatNumber, formatRelative } from '@/lib/format'
import { useFormDirty } from '@/lib/useFormDirty'
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
  const { can } = useAuth()
  const channels = useNotificationChannels(can('alert:rule:write'))
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
  const dirty = useFormDirty(open, form)

  /**
   * Checks that run while the form is open. A band whose upper bound sits
   * below its lower one, or a negative hysteresis, would be refused by the
   * server - but only after the click, and without pointing at the field.
   */
  const problems = useMemo(() => {
    const out: Partial<Record<'threshold' | 'threshold_upper' | 'hysteresis' | 'for_duration_seconds' | 'cooldown_seconds', string>> = {}
    const lower = Number(form.threshold)
    const upper = Number(form.threshold_upper)
    if (form.threshold !== '' && !Number.isFinite(lower)) out.threshold = t('rules.problems.number')
    if (needsUpper) {
      if (form.threshold_upper === '' || !Number.isFinite(upper)) out.threshold_upper = t('rules.problems.number')
      else if (Number.isFinite(lower) && upper <= lower) out.threshold_upper = t('rules.problems.bandOrder')
    }
    if (!(Number(form.hysteresis) >= 0)) out.hysteresis = t('rules.problems.nonNegative')
    else if (needsUpper && Number.isFinite(lower) && Number.isFinite(upper) && Number(form.hysteresis) * 2 >= upper - lower) {
      out.hysteresis = t('rules.problems.hysteresisTooWide')
    }
    if (!(Number(form.for_duration_seconds) >= 0)) out.for_duration_seconds = t('rules.problems.nonNegative')
    if (!(Number(form.cooldown_seconds) >= 0)) out.cooldown_seconds = t('rules.problems.nonNegative')
    return out
  }, [form, needsUpper, t])
  const problemCount = Object.keys(problems).length

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
      dirty={dirty}
      size="lg"
      title={rule ? t('rules.edit') : t('rules.create')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={create.isPending || update.isPending}
            disabled={!form.name || !form.metric_key || form.threshold === '' || problemCount > 0}
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
            error={problems.threshold}
            onChange={(event) => setForm({ ...form, threshold: event.target.value })}
          />
          {needsUpper ? (
            <TextInput
              label={t('rules.thresholdUpper')}
              type="number"
              step="any"
              required
              value={form.threshold_upper}
              error={problems.threshold_upper}
              onChange={(event) => setForm({ ...form, threshold_upper: event.target.value })}
            />
          ) : null}
          <TextInput
            label={t('rules.hysteresis')}
            type="number"
            step="any"
            min={0}
            value={String(form.hysteresis)}
            error={problems.hysteresis}
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
            error={problems.for_duration_seconds}
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
            error={problems.cooldown_seconds}
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
  const channels = useNotificationChannels(can('alert:rule:write'))
  const { remove } = useNotificationChannelMutations()

  const [editing, setEditing] = useState<NotificationChannel | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<NotificationChannel | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const { test } = useNotificationChannelMutations()
  async function testStored(channel: NotificationChannel) {
    setTesting(channel.id)
    try {
      const result = await test.mutateAsync({
        id: channel.id,
        name: channel.name,
        channel_type: channel.channel_type,
        config: channel.config ?? {},
      })
      if (result.ok) toast.success(t('channels.testOk', { detail: result.message }))
      else toast.error(t('channels.testFailed', { detail: result.message }))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setTesting(null)
    }
  }

  // Channels are admin-only; for anyone else the section simply is not
  // there - and the query above is never fired, so no 403 reaches the console.
  if (!can('alert:rule:write') || channels.isError) return null

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
                    <span className="flex flex-col gap-1">
                      {channel.is_enabled ? (
                        <Badge tone="ok">{t('common.enabled')}</Badge>
                      ) : (
                        <Badge tone="neutral">{t('common.disabled')}</Badge>
                      )}
                      {channel.last_delivery_status === 'failed' ? (
                        <span
                          className="text-xs text-critical"
                          title={channel.last_delivery_error}
                        >
                          {t('channels.lastFailed', {
                            when: channel.last_delivery_at ? formatRelative(channel.last_delivery_at) : '',
                          })}
                        </span>
                      ) : channel.last_delivery_status === 'sent' ? (
                        <span className="text-xs text-muted">
                          {t('channels.lastSent', {
                            when: channel.last_delivery_at ? formatRelative(channel.last_delivery_at) : '',
                          })}
                        </span>
                      ) : null}
                    </span>
                  </Td>
                  <Td align="right">
                    <span className="flex justify-end gap-1">
                      <IconButton
                        label={t('channels.test')}
                        onClick={() => void testStored(channel)}
                        disabled={testing === channel.id}
                      >
                        <Send className="size-3.5" />
                      </IconButton>
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
  const { create, update, test } = useNotificationChannelMutations()

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
    smtp_host: '',
    smtp_port: '',
    smtp_username: '',
    smtp_password: '',
    smtp_use_tls: true,
    smtp_use_ssl: false,
    from_email: '',
  })
  const channelDirty = useFormDirty(open, form)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  useEffect(() => {
    setTestResult(null)
  }, [open, form.channel_type])

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
        smtp_host: String(config.smtp_host ?? ''),
        smtp_port: config.smtp_port ? String(config.smtp_port) : '',
        smtp_username: String(config.smtp_username ?? ''),
        smtp_password: '',
        smtp_use_tls: config.smtp_use_tls !== false,
        smtp_use_ssl: Boolean(config.smtp_use_ssl),
        from_email: String(config.from_email ?? ''),
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
        smtp_host: '',
        smtp_port: '',
        smtp_username: '',
        smtp_password: '',
        smtp_use_tls: true,
        smtp_use_ssl: false,
        from_email: '',
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, channel?.id])

  /** The config the form describes. Blank secrets mean "keep the stored one". */
  function buildConfig(): Record<string, unknown> {
    const config: Record<string, unknown> = {}
    if (form.channel_type === 'webhook') config.url = form.url.trim()
    if (form.channel_type === 'email') {
      config.recipients = form.recipients
        .split(/[,;\s]+/)
        .map((entry) => entry.trim())
        .filter(Boolean)
      if (form.smtp_host.trim()) {
        config.smtp_host = form.smtp_host.trim()
        config.smtp_port = form.smtp_port.trim() ? Number(form.smtp_port) : 587
        config.smtp_username = form.smtp_username.trim()
        config.smtp_password = form.smtp_password
        config.smtp_use_tls = form.smtp_use_tls
        config.smtp_use_ssl = form.smtp_use_ssl
      }
      if (form.from_email.trim()) config.from_email = form.from_email.trim()
    }
    if (form.channel_type === 'line') {
      // Blank means "keep the stored token" on update; the server merges it.
      config.channel_access_token = form.line_token.trim()
      config.to = form.line_to.trim()
    }
    if (form.channel_type === 'mqtt') config.topic = form.topic.trim()
    return config
  }

  /** The LINE recipient shape the Messaging API accepts; anything else can never be pushed to. */
  const lineToProblem =
    form.channel_type === 'line' && form.line_to.trim() && !/^[UCR][0-9a-f]{32}$/.test(form.line_to.trim())
      ? t('channels.lineToInvalid')
      : undefined
  const smtpPortProblem =
    form.channel_type === 'email' && form.smtp_port.trim() && !/^\d{1,5}$/.test(form.smtp_port.trim())
      ? t('channels.smtpPortInvalid')
      : undefined
  const formProblem = Boolean(lineToProblem || smtpPortProblem)

  async function runTest() {
    setTestResult(null)
    try {
      const result = await test.mutateAsync({
        id: channel?.id,
        name: form.name.trim() || t('channels.test'),
        channel_type: form.channel_type,
        config: buildConfig(),
      })
      setTestResult(result)
    } catch (error) {
      setTestResult({ ok: false, message: errorMessage(error) })
    }
  }

  async function submit() {
    const config = buildConfig()

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
      dirty={channelDirty}
      title={channel ? t('channels.edit') : t('channels.create')}
      footer={
        <>
          <Button
            icon={<Send className="size-3.5" />}
            loading={test.isPending}
            disabled={formProblem}
            onClick={() => void runTest()}
            title={t('channels.testHint')}
          >
            {t('channels.test')}
          </Button>
          <span className="flex-1" />
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={create.isPending || update.isPending}
            disabled={formProblem}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {testResult ? (
          <p
            className={`rounded-lg px-3 py-2 text-sm ${
              testResult.ok ? 'bg-ok-soft text-ok' : 'bg-critical-soft text-critical'
            }`}
            role="status"
          >
            {testResult.ok ? t('channels.testOk', { detail: testResult.message }) : t('channels.testFailed', { detail: testResult.message })}
          </p>
        ) : null}
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
          <>
            <TextArea
              label={t('channels.recipients')}
              value={form.recipients}
              onChange={(event) => setForm({ ...form, recipients: event.target.value })}
              hint={t('channels.recipientsHint')}
              rows={2}
              required
            />
            <div className="space-y-3 rounded-lg border border-line p-3">
              <p className="text-xs font-medium">{t('channels.smtpTitle')}</p>
              <p className="text-xs text-muted">{t('channels.smtpHint')}</p>
              <div className="grid gap-3 sm:grid-cols-3">
                <TextInput
                  label={t('channels.smtpHost')}
                  value={form.smtp_host}
                  placeholder="smtp.gmail.com"
                  onChange={(event) => setForm({ ...form, smtp_host: event.target.value })}
                />
                <TextInput
                  label={t('channels.smtpPort')}
                  value={form.smtp_port}
                  placeholder="587"
                  error={smtpPortProblem}
                  onChange={(event) => setForm({ ...form, smtp_port: event.target.value })}
                />
                <TextInput
                  label={t('channels.fromEmail')}
                  value={form.from_email}
                  placeholder="alerts@example.com"
                  onChange={(event) => setForm({ ...form, from_email: event.target.value })}
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <TextInput
                  label={t('channels.smtpUsername')}
                  value={form.smtp_username}
                  autoComplete="off"
                  onChange={(event) => setForm({ ...form, smtp_username: event.target.value })}
                />
                <TextInput
                  label={t('channels.smtpPassword')}
                  type="password"
                  value={form.smtp_password}
                  autoComplete="new-password"
                  placeholder={channel?.config?.smtp_password ? t('channels.secretKept') : undefined}
                  hint={t('channels.smtpPasswordHint')}
                  onChange={(event) => setForm({ ...form, smtp_password: event.target.value })}
                />
              </div>
              <div className="flex flex-wrap gap-4">
                <Checkbox
                  label="STARTTLS (587)"
                  checked={form.smtp_use_tls && !form.smtp_use_ssl}
                  onChange={(smtp_use_tls) =>
                    setForm({ ...form, smtp_use_tls, smtp_use_ssl: smtp_use_tls ? false : form.smtp_use_ssl })
                  }
                />
                <Checkbox
                  label="SSL (465)"
                  checked={form.smtp_use_ssl}
                  onChange={(smtp_use_ssl) =>
                    setForm({ ...form, smtp_use_ssl, smtp_use_tls: smtp_use_ssl ? false : form.smtp_use_tls })
                  }
                />
              </div>
            </div>
          </>
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
              error={lineToProblem}
              placeholder="Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
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
