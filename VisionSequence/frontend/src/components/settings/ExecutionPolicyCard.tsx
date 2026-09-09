/** 執行策略與站台運維設定。畫面文字走 i18n；數值本身從 capacity API 讀。 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Activity, Save } from 'lucide-react'

import { Button, Card, CardBody, CardHeader, DetailRow, Select, Switch, TextInput } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useAutoSaveSettings, useCapacity, useExecutionSettings, useLogLevel, useSaveAutoSaveSettings, useSaveExecutionSettings, useSaveLogLevel } from '@/lib/queries'
import type { LogLevel } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const LOG_LEVELS: LogLevel[] = ['error', 'info', 'debug', 'trace']

export function ExecutionPolicyCard() {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const capacity = useCapacity()
  const execution = useExecutionSettings(auth.isAdmin)
  const saveExecution = useSaveExecutionSettings()
  const logLevel = useLogLevel(auth.isAdmin)
  const saveLogLevel = useSaveLogLevel()
  const autoSave = useAutoSaveSettings(auth.isAdmin)
  const saveAutoSave = useSaveAutoSaveSettings()
  const [autoSaveEnabled, setAutoSaveEnabled] = useState(false)
  const [autoSaveInterval, setAutoSaveInterval] = useState(15)

  useEffect(() => {
    const settings = autoSave.data?.settings
    if (!settings) return
    setAutoSaveEnabled(settings.auto_save_enabled)
    setAutoSaveInterval(settings.auto_save_interval_min)
  }, [autoSave.data])

  async function toggleStable(value: boolean) {
    try {
      await saveExecution.mutateAsync({ stable_cycle_mode: value })
      toast.success(t('settings.ops.saved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function changeLogLevel(value: LogLevel) {
    try {
      await saveLogLevel.mutateAsync(value)
      toast.success(t('settings.ops.logSaved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function submitAutoSave() {
    try {
      await saveAutoSave.mutateAsync({ auto_save_enabled: autoSaveEnabled, auto_save_interval_min: autoSaveInterval })
      toast.success(t('settings.ops.autoSaveSaved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const cap = capacity.data
  const stable = execution.data?.settings?.stable_cycle_mode ?? Boolean(cap?.stable_cycle_mode)
  const serverAutoSave = autoSave.data?.settings
  const autoSaveDirty = Boolean(serverAutoSave && (autoSaveEnabled !== serverAutoSave.auto_save_enabled || autoSaveInterval !== serverAutoSave.auto_save_interval_min))

  return (
    <Card testId="execution-policy-card">
      <CardHeader title={t('settings.ops.title')} description={t('settings.ops.hint')} />
      <CardBody className="space-y-4">
        {cap ? (
          <dl>
            <DetailRow label="MAX_WORKERS">{cap.configured_max_workers ?? cap.max_workers}</DetailRow>
            <p className="hint mb-1">{t('settings.ops.maxWorkersHint')}</p>
            <DetailRow label="CV_THREADS">{cap.cv_threads ?? '-'}</DetailRow>
            <p className="hint mb-1">{t('settings.ops.cvThreadsHint')}</p>
            <DetailRow label="SSE_MAX_STREAMS">{cap.sse_max_streams ?? '-'}</DetailRow>
            <p className="hint mb-1">{t('settings.ops.sseHint')}</p>
            <DetailRow label="MAX_QUEUE_PER_FLOW">{cap.max_queue_per_flow ?? '-'}</DetailRow>
            <p className="hint mb-1">{t('settings.ops.queueHint')}</p>
            <DetailRow label="RUN_TIMEOUT_S">{cap.run_timeout_s ?? '-'}</DetailRow>
            <p className="hint">{t('settings.ops.timeoutHint')}</p>
          </dl>
        ) : null}

        {auth.isAdmin ? (
          <div className="space-y-3 border-t border-line pt-3">
            <label className="flex items-center gap-2 text-sm text-content">
              <Switch checked={stable} disabled={saveExecution.isPending} onChange={(value) => void toggleStable(value)} label={t('settings.ops.stableMode')} />
              <span>{t('settings.ops.stableMode')}</span>
            </label>
            <p className="hint">{t('settings.ops.stableModeHint')}</p>

            <Select
              label={t('settings.ops.logLevel')}
              hint={t('settings.ops.traceHint')}
              value={logLevel.data?.level ?? 'info'}
              onChange={(event) => void changeLogLevel(event.target.value as LogLevel)}
              options={LOG_LEVELS.map((level) => ({ value: level, label: t(`settings.ops.levels.${level}`) }))}
            />

            <div className="grid gap-2 sm:grid-cols-[1fr_8rem_auto] sm:items-end">
              <label className="flex items-center gap-2 text-sm text-content">
                <Switch checked={autoSaveEnabled} onChange={setAutoSaveEnabled} label={t('settings.ops.autoSave')} />
                <span>{t('settings.ops.autoSave')}</span>
              </label>
              <TextInput
                label={t('settings.ops.autoSaveInterval')}
                type="number"
                min={1}
                max={1440}
                value={String(autoSaveInterval)}
                onChange={(event) => setAutoSaveInterval(Number(event.target.value))}
              />
              <Button variant="primary" icon={<Save size={14} />} disabled={!autoSaveDirty} loading={saveAutoSave.isPending} onClick={() => void submitAutoSave()}>
                {t('common.save')}
              </Button>
            </div>
            <p className="hint">{t('settings.ops.autoSaveHint')}</p>
            <p className="hint">{t('settings.ops.autoLoadHint')}</p>
          </div>
        ) : (
          <p className="hint">{t('settings.ops.adminOnly')}</p>
        )}
        <div className="border-t border-line pt-2 text-xs text-muted">
          <Activity className="mr-1 inline size-3.5" />
          {t('settings.ops.liveCapacity', { active: cap?.active ?? 0, max: cap?.max_workers ?? 0 })}
        </div>
      </CardBody>
    </Card>
  )
}
