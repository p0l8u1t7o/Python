import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CalendarClock, Plus, Trash2 } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { useDispatchWindowMutations, useDispatchWindows } from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import { formatDateTime, formatMeasurement } from '@/lib/format'
import { useFormDirty } from '@/lib/useFormDirty'
import type { DispatchWindow } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  EmptyRow,
  IconButton,
  Modal,
  Select,
  Table,
  TBody,
  Td,
  TextArea,
  TextInput,
  Th,
  THead,
  Tr,
} from '@/components/ui'

const MODES = ['charge', 'discharge', 'idle', 'auto'] as const

/** `datetime-local` wants local wall-clock without zone; ISO from the API is UTC. */
function toLocalInput(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function defaultStart(): string {
  const d = new Date(Date.now() + 5 * 60_000)
  d.setSeconds(0, 0)
  return toLocalInput(d.toISOString())
}

/**
 * Scheduled battery instructions for one site: "charge at 200 kW from 01:00
 * to 05:00 tonight". A window outranks the plan's strategy while it is in
 * force and is clamped by the plan's limits; the dispatch preview above
 * shows the result. One-shot only - the engine does not expand recurrences,
 * so the form does not offer them.
 */
export function DispatchWindowsCard({ siteId }: { siteId: string }) {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const windows = useDispatchWindows(siteId || undefined)
  const { create, remove } = useDispatchWindowMutations()
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<DispatchWindow | null>(null)

  const now = Date.now()
  const items = (windows.data ?? []).filter((w) => new Date(w.ends_at).getTime() > now - 24 * 3600_000)

  async function confirmDelete() {
    if (!deleting) return
    try {
      await remove.mutateAsync(deleting.id)
      toast.success(t('windows.deleted'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setDeleting(null)
    }
  }

  return (
    <Card className="mt-5">
      <CardHeader
        title={t('windows.title')}
        description={t('windows.hint')}
        actions={
          can('ems:dispatch') ? (
            <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setCreating(true)}>
              {t('windows.create')}
            </Button>
          ) : undefined
        }
      />
      <Table>
        <THead>
          <Th>{t('windows.mode')}</Th>
          <Th align="right">{t('windows.power')}</Th>
          <Th>{t('windows.from')}</Th>
          <Th>{t('windows.until')}</Th>
          <Th>{t('windows.notes')}</Th>
          {can('ems:dispatch') ? <Th /> : null}
        </THead>
        <TBody>
          {items.length === 0 ? (
            <EmptyRow colSpan={6} message={t('windows.empty')} />
          ) : (
            items.map((w) => {
              const active = new Date(w.starts_at).getTime() <= now && new Date(w.ends_at).getTime() > now
              const past = new Date(w.ends_at).getTime() <= now
              return (
                <Tr key={w.id}>
                  <Td>
                    <Badge tone={w.mode === 'charge' ? 'info' : w.mode === 'discharge' ? 'brand' : 'neutral'}>
                      {t(`windows.modes.${w.mode}`)}
                    </Badge>
                    {active && w.is_enabled ? <Badge tone="ok" className="ml-1">{t('windows.active')}</Badge> : null}
                    {past ? <Badge tone="neutral" className="ml-1">{t('windows.past')}</Badge> : null}
                    {!w.is_enabled ? <Badge tone="neutral" className="ml-1">{t('common.disabled')}</Badge> : null}
                  </Td>
                  <Td align="right" className="tnum">
                    {w.target_power_kw !== null ? formatMeasurement(w.target_power_kw, 'kW', 0) : '—'}
                  </Td>
                  <Td className="text-muted">{formatDateTime(w.starts_at)}</Td>
                  <Td className="text-muted">{formatDateTime(w.ends_at)}</Td>
                  <Td className="text-muted">{w.notes || '—'}</Td>
                  {can('ems:dispatch') ? (
                    <Td align="right">
                      <IconButton label={t('common.delete')} onClick={() => setDeleting(w)}>
                        <Trash2 className="size-3.5" />
                      </IconButton>
                    </Td>
                  ) : null}
                </Tr>
              )
            })
          )}
        </TBody>
      </Table>

      <CreateWindowModal open={creating} siteId={siteId} onClose={() => setCreating(false)} create={create} />
      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onConfirm={() => void confirmDelete()}
        title={t('common.delete')}
        danger
        loading={remove.isPending}
        message={t('windows.deleteConfirm')}
      />
    </Card>
  )
}

function CreateWindowModal({
  open,
  siteId,
  onClose,
  create,
}: {
  open: boolean
  siteId: string
  onClose: () => void
  create: ReturnType<typeof useDispatchWindowMutations>['create']
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const [form, setForm] = useState({
    mode: 'charge' as (typeof MODES)[number],
    target_power_kw: '',
    starts_at: defaultStart(),
    ends_at: '',
    priority: '0',
    is_enabled: true,
    notes: '',
  })
  const dirty = useFormDirty(open, form)

  const needsPower = form.mode === 'charge' || form.mode === 'discharge'
  const problems: Partial<Record<keyof typeof form, string>> = {}
  if (needsPower && !(Number(form.target_power_kw) > 0)) problems.target_power_kw = t('windows.problems.power')
  if (!form.starts_at) problems.starts_at = t('windows.problems.time')
  if (!form.ends_at) problems.ends_at = t('windows.problems.time')
  else if (form.starts_at && new Date(form.ends_at) <= new Date(form.starts_at)) problems.ends_at = t('windows.problems.order')
  const problemCount = Object.keys(problems).length

  async function submit() {
    try {
      await create.mutateAsync({
        site_id: siteId,
        mode: form.mode,
        target_power_kw: needsPower ? Number(form.target_power_kw) : null,
        starts_at: new Date(form.starts_at).toISOString(),
        ends_at: new Date(form.ends_at).toISOString(),
        priority: Number(form.priority || 0),
        is_enabled: form.is_enabled,
        notes: form.notes,
      })
      toast.success(t('common.saved'))
      setForm({ ...form, target_power_kw: '', ends_at: '', notes: '', starts_at: defaultStart() })
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
      title={t('windows.create')}
      description={t('windows.createHint')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            disabled={problemCount > 0}
            loading={create.isPending}
            icon={<CalendarClock className="size-4" />}
            onClick={() => void submit()}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select
            label={t('windows.mode')}
            value={form.mode}
            options={MODES.map((mode) => ({ value: mode, label: t(`windows.modes.${mode}`) }))}
            hint={t(`windows.modeHints.${form.mode}`)}
            onChange={(event) => setForm({ ...form, mode: event.target.value as (typeof MODES)[number] })}
          />
          {needsPower ? (
            <TextInput
              label={t('windows.power')}
              type="number"
              suffix="kW"
              required
              value={form.target_power_kw}
              error={problems.target_power_kw}
              hint={t('windows.powerHint')}
              onChange={(event) => setForm({ ...form, target_power_kw: event.target.value })}
            />
          ) : null}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <TextInput
            label={t('windows.from')}
            type="datetime-local"
            required
            value={form.starts_at}
            error={problems.starts_at}
            onChange={(event) => setForm({ ...form, starts_at: event.target.value })}
          />
          <TextInput
            label={t('windows.until')}
            type="datetime-local"
            required
            value={form.ends_at}
            error={problems.ends_at}
            onChange={(event) => setForm({ ...form, ends_at: event.target.value })}
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <TextInput
            label={t('windows.priority')}
            type="number"
            min={-100}
            max={100}
            value={form.priority}
            hint={t('windows.priorityHint')}
            onChange={(event) => setForm({ ...form, priority: event.target.value })}
          />
          <div className="pt-6">
            <Checkbox
              label={t('common.enabled')}
              checked={form.is_enabled}
              onChange={(is_enabled) => setForm({ ...form, is_enabled })}
            />
          </div>
        </div>
        <TextArea
          label={t('windows.notes')}
          rows={2}
          value={form.notes}
          onChange={(event) => setForm({ ...form, notes: event.target.value })}
        />
      </div>
    </Modal>
  )
}
