import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Info, Pencil, Plus, SlidersHorizontal, Trash2, X } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { useBlueprints, useMetrics, usePolicies, usePolicyMutations } from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import type { RecordingPolicy, RecordingRule } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  IconButton,
  LoadingState,
  Modal,
  PageHeader,
  Select,
  Table,
  TBody,
  Td,
  Term,
  TextInput,
  Th,
  THead,
  Tr,
} from '@/components/ui'

export function RecordingPage() {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const policies = usePolicies()
  const { remove } = usePolicyMutations()

  const [editing, setEditing] = useState<RecordingPolicy | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<RecordingPolicy | null>(null)

  return (
    <>
      <PageHeader
        title={t('policies.title')}
        description={t('policies.subtitle')}
        actions={
          can('telemetry:policy:write') ? (
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
              {t('policies.create')}
            </Button>
          ) : null
        }
      />

      <p className="mb-4 flex items-start gap-2 rounded-lg bg-info-soft px-3 py-2 text-sm text-info">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <Term id="worker">{t('policies.alertNote')}</Term>
      </p>

      {policies.isPending ? (
        <LoadingState />
      ) : policies.error ? (
        <ErrorState error={policies.error} onRetry={() => void policies.refetch()} />
      ) : (policies.data?.length ?? 0) === 0 ? (
        <Card>
          <EmptyState
            icon={<SlidersHorizontal className="size-6" />}
            title={t('policies.noPolicies')}
          />
        </Card>
      ) : (
        <div className="space-y-4">
          {policies.data?.map((policy) => (
            <Card key={policy.id}>
              <CardHeader
                title={
                  <span className="flex flex-wrap items-center gap-2">
                    {policy.name}
                    {policy.is_default ? (
                      <Badge tone="brand">{t('policies.isDefault')}</Badge>
                    ) : null}
                    <Badge tone="neutral">
                      {t('policies.devices', { count: policy.device_count })}
                    </Badge>
                  </span>
                }
                description={policy.description || undefined}
                actions={
                  can('telemetry:policy:write') ? (
                    <>
                      <IconButton label={t('common.edit')} onClick={() => setEditing(policy)}>
                        <Pencil className="size-3.5" />
                      </IconButton>
                      <IconButton label={t('common.delete')} onClick={() => setDeleting(policy)}>
                        <Trash2 className="size-3.5" />
                      </IconButton>
                    </>
                  ) : null
                }
              />
              <CardBody className="pb-0">
                <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
                  <span>
                    {t('policies.recordUnlisted')}:{' '}
                    <strong className="text-content">
                      {policy.record_unlisted_metrics ? t('common.yes') : t('common.no')}
                    </strong>
                  </span>
                  <span>
                    {t('policies.retention')}:{' '}
                    <strong className="text-content tnum">
                      {policy.default_retention_days || '∞'} {t('policies.days')}
                    </strong>
                  </span>
                  <span>
                    {t('policies.maxInterval')}:{' '}
                    <strong className="text-content tnum">
                      {policy.default_max_interval_seconds}s
                    </strong>
                  </span>
                </div>
              </CardBody>
              {policy.rules.length > 0 ? (
                <Table>
                  <THead>
                    <Th>{t('policies.metric')}</Th>
                    <Th align="right">{t('policies.minInterval')}</Th>
                    <Th align="right">{t('policies.maxInterval')}</Th>
                    <Th align="right">
                      <Term id="deadband">{t('policies.deadbandAbsolute')}</Term>
                    </Th>
                    <Th align="right">{t('policies.deadbandPercent')}</Th>
                    <Th align="right">{t('policies.retention')}</Th>
                  </THead>
                  <TBody>
                    {policy.rules.map((rule) => (
                      <Tr key={rule.metric_key}>
                        <Td className="font-mono text-xs">
                          {rule.metric_key}
                          {!rule.enabled ? (
                            <Badge tone="neutral" className="ml-2">
                              {t('common.disabled')}
                            </Badge>
                          ) : null}
                        </Td>
                        <Td align="right" className="tnum text-muted">
                          {rule.min_interval_seconds}s
                        </Td>
                        <Td align="right" className="tnum text-muted">
                          {rule.max_interval_seconds ? `${rule.max_interval_seconds}s` : '—'}
                        </Td>
                        <Td align="right" className="tnum text-muted">
                          {rule.deadband_absolute ?? '—'}
                        </Td>
                        <Td align="right" className="tnum text-muted">
                          {rule.deadband_percent !== null ? `${rule.deadband_percent}%` : '—'}
                        </Td>
                        <Td align="right" className="tnum text-muted">
                          {rule.retention_days === null
                            ? '—'
                            : rule.retention_days === 0
                              ? '∞'
                              : `${rule.retention_days}d`}
                        </Td>
                      </Tr>
                    ))}
                  </TBody>
                </Table>
              ) : (
                <CardBody className="pt-0">
                  <p className="text-sm text-muted">{t('common.none')}</p>
                </CardBody>
              )}
            </Card>
          ))}
        </div>
      )}

      <PolicyModal
        open={creating || editing !== null}
        policy={editing}
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
        message={t('policies.deleteConfirm', { name: deleting?.name ?? '' })}
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

const NEW_RULE: RecordingRule = {
  metric_key: '',
  enabled: true,
  min_interval_seconds: 0,
  max_interval_seconds: 3600,
  deadband_absolute: null,
  deadband_percent: null,
  retention_days: null,
  keep_rollups: true,
}

function PolicyModal({
  open,
  policy,
  onClose,
}: {
  open: boolean
  policy: RecordingPolicy | null
  onClose: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const metrics = useMetrics()
  const blueprints = useBlueprints()
  const { create, update } = usePolicyMutations()

  const [form, setForm] = useState({
    name: '',
    description: '',
    is_default: false,
    device_type_id: '',
    record_unlisted_metrics: true,
    default_retention_days: 365,
    default_min_interval_seconds: 0,
    default_max_interval_seconds: 3600,
  })
  const [rules, setRules] = useState<RecordingRule[]>([])

  useEffect(() => {
    if (!open) return
    if (policy) {
      setForm({
        name: policy.name,
        description: policy.description,
        is_default: policy.is_default,
        device_type_id: policy.device_type_id ?? '',
        record_unlisted_metrics: policy.record_unlisted_metrics,
        default_retention_days: policy.default_retention_days,
        default_min_interval_seconds: policy.default_min_interval_seconds,
        default_max_interval_seconds: policy.default_max_interval_seconds,
      })
      setRules(policy.rules.map((rule) => ({ ...rule })))
    } else {
      setForm({
        name: '',
        description: '',
        is_default: false,
        device_type_id: '',
        record_unlisted_metrics: true,
        default_retention_days: 365,
        default_min_interval_seconds: 0,
        default_max_interval_seconds: 3600,
      })
      setRules([])
    }
  }, [open, policy])

  function patchRule(index: number, patch: Partial<RecordingRule>) {
    setRules((current) =>
      current.map((rule, position) => (position === index ? { ...rule, ...patch } : rule)),
    )
  }

  async function submit() {
    const payload = {
      ...form,
      device_type_id: form.device_type_id || null,
      rules: rules
        .filter((rule) => rule.metric_key)
        .map(({ id: _id, ...rule }) => rule),
    }
    try {
      if (policy) await update.mutateAsync({ id: policy.id, ...payload })
      else await create.mutateAsync(payload)
      toast.success(t('common.saved'))
      onClose()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const metricOptions = (metrics.data ?? []).map((metric) => ({
    value: metric.key,
    label: `${metric.label} (${metric.key})`,
  }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={policy ? t('policies.edit') : t('policies.create')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            loading={create.isPending || update.isPending}
            disabled={!form.name}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput
            label={t('common.name')}
            required
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <Select
            label={t('policies.blueprint')}
            value={form.device_type_id}
            placeholder={t('common.none')}
            onChange={(event) => setForm({ ...form, device_type_id: event.target.value })}
            options={(blueprints.data ?? []).map((blueprint) => ({
              value: blueprint.id,
              label: blueprint.name,
            }))}
            hint={t('policies.appliesTo')}
          />
        </div>

        <div className="space-y-3 rounded-lg border border-line p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">
            {t('policies.defaults')}
          </p>
          <Checkbox
            label={t('policies.recordUnlisted')}
            hint={t('policies.recordUnlistedHint')}
            checked={form.record_unlisted_metrics}
            onChange={(value) => setForm({ ...form, record_unlisted_metrics: value })}
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <TextInput
              label={t('policies.minInterval')}
              type="number"
              min={0}
              suffix="s"
              value={String(form.default_min_interval_seconds)}
              onChange={(event) =>
                setForm({ ...form, default_min_interval_seconds: Number(event.target.value) })
              }
            />
            <TextInput
              label={t('policies.maxInterval')}
              type="number"
              min={0}
              suffix="s"
              value={String(form.default_max_interval_seconds)}
              onChange={(event) =>
                setForm({ ...form, default_max_interval_seconds: Number(event.target.value) })
              }
            />
            <TextInput
              label={t('policies.retention')}
              type="number"
              min={0}
              suffix={t('policies.days')}
              value={String(form.default_retention_days)}
              onChange={(event) =>
                setForm({ ...form, default_retention_days: Number(event.target.value) })
              }
              hint={t('policies.retentionHint')}
            />
          </div>
          <Checkbox
            label={t('policies.isDefault')}
            checked={form.is_default}
            onChange={(value) => setForm({ ...form, is_default: value })}
          />
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">
              {t('policies.rules')}
            </p>
            <Button
              size="sm"
              icon={<Plus className="size-3.5" />}
              onClick={() => setRules((current) => [...current, { ...NEW_RULE }])}
            >
              {t('policies.addRule')}
            </Button>
          </div>

          {rules.map((rule, index) => (
            <div key={index} className="rounded-lg border border-line p-3">
              <div className="mb-3 flex items-center gap-2">
                <Select
                  value={rule.metric_key}
                  placeholder={t('policies.metric')}
                  onChange={(event) => patchRule(index, { metric_key: event.target.value })}
                  options={metricOptions}
                  className="flex-1"
                />
                <IconButton
                  label={t('common.remove')}
                  onClick={() => setRules((current) => current.filter((_, i) => i !== index))}
                >
                  <X className="size-3.5" />
                </IconButton>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <TextInput
                  label={t('policies.minInterval')}
                  type="number"
                  min={0}
                  suffix="s"
                  value={String(rule.min_interval_seconds)}
                  onChange={(event) =>
                    patchRule(index, { min_interval_seconds: Number(event.target.value) })
                  }
                />
                <TextInput
                  label={t('policies.maxInterval')}
                  type="number"
                  min={0}
                  suffix="s"
                  value={String(rule.max_interval_seconds)}
                  onChange={(event) =>
                    patchRule(index, { max_interval_seconds: Number(event.target.value) })
                  }
                />
                <TextInput
                  label={<Term id="deadband">{t('policies.deadbandAbsolute')}</Term>}
                  type="number"
                  step="any"
                  min={0}
                  value={rule.deadband_absolute === null ? '' : String(rule.deadband_absolute)}
                  onChange={(event) =>
                    patchRule(index, {
                      deadband_absolute:
                        event.target.value === '' ? null : Number(event.target.value),
                    })
                  }
                />
                <TextInput
                  label={t('policies.retention')}
                  type="number"
                  min={0}
                  suffix={t('policies.days')}
                  value={rule.retention_days === null ? '' : String(rule.retention_days)}
                  onChange={(event) =>
                    patchRule(index, {
                      retention_days: event.target.value === '' ? null : Number(event.target.value),
                    })
                  }
                />
              </div>
            </div>
          ))}

          {rules.length > 0 ? <p className="hint">{t('policies.maxIntervalHint')}</p> : null}
        </div>
      </div>
    </Modal>
  )
}
