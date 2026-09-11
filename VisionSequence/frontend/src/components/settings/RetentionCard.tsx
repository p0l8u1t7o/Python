/** 資料保留（管理員）：保存時限、維護視窗、用量與上次整理；「立即整理」會馬上跑一次。
 * 伺服器只在引擎空檔刪除，所以這張卡片只負責設定與顯示。 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Brush, Save } from 'lucide-react'

import { ScopeBadge } from '@/components/settings/ScopeBadge'
import { Button, Card, CardBody, CardHeader, Checkbox, DetailRow, Select, TextInput } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { formatDateTime } from '@/lib/format'
import { useRetention, useSaveRetention, useSweepRetention } from '@/lib/queries'
import type { RetentionSettings } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

const DAY_FIELDS = ['run_days', 'audit_days', 'measurement_days', 'archive_days'] as const

function mb(bytes: number): string {
  if (!bytes) return '0 MB'
  return bytes >= (1 << 30) ? `${(bytes / (1 << 30)).toFixed(2)} GB` : `${Math.round(bytes / (1 << 20))} MB`
}

export function RetentionCard() {
  const { t } = useTranslation()
  const toast = useToast()
  const state = useRetention()
  const save = useSaveRetention()
  const sweep = useSweepRetention()
  const [form, setForm] = useState<RetentionSettings | null>(null)

  useEffect(() => {
    if (state.data && !form) setForm(state.data.settings)
  }, [state.data, form])

  const server = state.data?.settings
  const dirty = Boolean(form && server && (Object.keys(form) as (keyof RetentionSettings)[]).some((k) => form[k] !== server[k]))

  function set<K extends keyof RetentionSettings>(key: K, value: RetentionSettings[K]) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  async function submit() {
    if (!form) return
    try {
      const next = await save.mutateAsync(form)
      setForm(next.settings)
      toast.success(t('settings.retention.saved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function runNow() {
    try {
      const res = await sweep.mutateAsync()
      setForm(res.status.settings)
      toast.success(t('settings.retention.swept', {
        runs: res.result.runs, audit: res.result.audit, pictures: res.result.archive_files,
      }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const usage = state.data?.usage
  return (
    <Card testId="retention-card">
      <CardHeader title={t('settings.retention.title')} description={<><ScopeBadge scope="station" mode="save" /><span className="block">{t('settings.retention.hint')}</span></>} />
      <CardBody className="space-y-3">
        {form ? (
          <>
            <p className="hint">{t('settings.retention.daysHint')}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {DAY_FIELDS.map((key) => (
                <TextInput
                  key={key}
                  label={t(`settings.retention.${key}`)}
                  type="number"
                  min={0}
                  value={String(form[key])}
                  onChange={(e) => set(key, Number(e.target.value) as never)}
                  data-testid={`retention-${key}`}
                />
              ))}
              <TextInput label={t('settings.retention.archive_max_gb')} type="number" min={0} step="0.5"
                value={String(form.archive_max_gb)} onChange={(e) => set('archive_max_gb', Number(e.target.value))} />
              <TextInput label={t('settings.retention.backup_keep')} hint={t('settings.retention.backupHint')} type="number" min={0}
                value={String(form.backup_keep)} onChange={(e) => set('backup_keep', Number(e.target.value))} />
              <Select label={t('settings.retention.window_hour')} hint={t('settings.retention.windowHint')}
                value={String(form.window_hour)} onChange={(e) => set('window_hour', Number(e.target.value))}
                options={Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: `${String(h).padStart(2, '0')}:00` }))}
                data-testid="retention-window" />
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <Checkbox label={t('settings.retention.enabled')} checked={form.enabled} onChange={(v) => set('enabled', v)} data-testid="retention-enabled" />
              <Checkbox label={t('settings.retention.vacuum')} checked={form.vacuum} onChange={(v) => set('vacuum', v)} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" icon={<Save size={14} />} disabled={!dirty} loading={save.isPending} onClick={() => void submit()} data-testid="retention-save">
                {t('common.save')}
              </Button>
              <Button icon={<Brush size={14} />} loading={sweep.isPending} onClick={() => void runNow()} data-testid="retention-sweep">
                {t('settings.retention.sweepNow')}
              </Button>
            </div>
          </>
        ) : null}
        {usage ? (
          <dl className="border-t border-line pt-2">
            <DetailRow label={t('settings.retention.database')}>{mb(usage.db_bytes)}</DetailRow>
            <DetailRow label={t('settings.retention.rows')}>
              {t('settings.retention.rowsValue', { runs: usage.runs, audit: usage.audit, measurements: usage.measurements })}
            </DetailRow>
            <DetailRow label={t('settings.retention.pictures')}>{usage.archive_files} · {mb(usage.archive_bytes)}</DetailRow>
            <DetailRow label={t('settings.retention.backups')}>{usage.backup_files} · {mb(usage.backup_bytes)}</DetailRow>
            <DetailRow label={t('settings.retention.lastSweep')}>
              {state.data?.last_sweep_at ? formatDateTime(state.data.last_sweep_at) : t('settings.retention.never')}
            </DetailRow>
          </dl>
        ) : null}
      </CardBody>
    </Card>
  )
}
