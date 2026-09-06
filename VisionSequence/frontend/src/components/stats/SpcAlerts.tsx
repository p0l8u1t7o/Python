/** 總覽頁的量測值告警（WP-14）：哪條流程的哪個量測輸出「現在」觸發 Nelson 法則或超出規格；GET /spc/alerts（伺服端快取 30 秒）。 */
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { TrendingUp } from 'lucide-react'

import { useSpcAlerts } from '@/lib/queries'

export function SpcAlerts() {
  const { t } = useTranslation()
  const q = useSpcAlerts()
  const items = q.data?.items ?? []
  if (!items.length) return null
  return (
    <div className="mb-4 rounded-md border border-warning/40 bg-warning/10 px-4 py-3 text-sm" role="status" data-testid="spc-alerts">
      <div className="mb-1 flex items-center gap-2 font-medium"><TrendingUp size={16} className="text-warning" />{t('spc.alertsTitle', { count: items.length })}</div>
      <ul className="space-y-0.5 text-xs">
        {items.map((it) => (
          <li key={`${it.flow_id}-${it.output}`}>
            <Link to={`/flows/${it.flow_id}/stats`} className="font-medium underline-offset-2 hover:underline">{it.flow_name}</Link>
            <span className="mx-1 font-mono">{it.output}</span>
            <span className="text-muted">{it.alerts.map((a) => (a.rule === 0 ? a.text : t(`spc.rules.${a.rule}`))).join('; ')}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
