/** 案例評分的失敗原因；適用條件與驗收依據由既有案例保留。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useToast } from '@/providers/ToastProvider'

export const FAILURE_REASONS = ['glare', 'wrong_edge', 'locate_offset', 'low_contrast', 'missing_calibration', 'tolerance_unclear', 'tool_error', 'other'] as const

export function LessonRating({ sessionId }: { sessionId: number }) {
  const { t } = useTranslation()
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  async function save(value: string) {
    if (!value) return
    setBusy(true)
    try {
      const row = await api.get<{ lessons?: Record<string, unknown> }>(`/vision/agent/sessions/${sessionId}`)
      await api.patch(`/vision/agent/sessions/${sessionId}`, { rating: -1, lessons: { ...row.lessons, outcome: 'failure', failure_reasons: [value] } })
      setReason(value)
      toast.success(t('agent.rated'))
    } catch (error) { toast.error(errorMessage(error)) } finally { setBusy(false) }
  }
  return <select className="input !w-auto !text-xs" value={reason} disabled={busy} aria-label={t('evidence.failureReason')} data-testid="agent-failure-reason" onChange={(e) => void save(e.target.value)}>
    <option value="">{t('evidence.failureReason')}</option>
    {FAILURE_REASONS.map((key) => <option key={key} value={key}>{t(`evidence.reasons.${key}`)}</option>)}
  </select>
}
