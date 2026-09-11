/** 設定卡片的「作用範圍 · 生效方式」標記（PM-REVIEW-R2 D8：一頁混三種範圍、四個各自的儲存鈕，看不出哪個立即生效）。 */
import { useTranslation } from 'react-i18next'

import { Badge } from '@/components/ui'

export type SettingsScope = 'browser' | 'account' | 'station'
export type ApplyMode = 'immediate' | 'save' | 'mixed'

export function ScopeBadge({ scope, mode }: { scope: SettingsScope; mode: ApplyMode }) {
  const { t } = useTranslation()
  return (
    <span className="mb-1 inline-flex flex-wrap items-center gap-1" data-testid="scope-badge" data-scope={scope} data-mode={mode}>
      <Badge tone="neutral">{t(`settings.scope.${scope}`)}</Badge>
      <Badge tone={mode === 'immediate' ? 'ok' : 'info'}>{t(`settings.applies.${mode}`)}</Badge>
    </span>
  )
}
