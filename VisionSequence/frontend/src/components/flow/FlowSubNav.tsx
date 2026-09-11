/**
 * 同一條流程的四個工作頁共用的子導覽（Suggest5 第 6 點）：檢測任務／畫布／參數卡／統計。
 * 放在檢測任務頁、編輯器工具列、參數卡頁與統計頁的頂列同一個位置；沒有現場教導功能的角色看不到參數卡。
 */
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router-dom'

import { useAuth } from '@/providers/AuthProvider'

export function FlowSubNav({ flowId, className = '' }: { flowId: number; className?: string }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const items: { key: string; to: string; label: string; hint: string; end?: boolean }[] = [
    { key: 'inspect', to: `/flows/${flowId}/inspect`, label: t('flowNav.inspect'), hint: t('flowNav.inspectHint') },
    { key: 'canvas', to: `/flows/${flowId}`, label: t('flowNav.canvas'), hint: t('flowNav.canvasHint'), end: true },
    ...(auth.can('flows.teach') ? [{ key: 'teach', to: `/flows/${flowId}/teach`, label: t('flowNav.teach'), hint: t('flowNav.teachHint') }] : []),
    { key: 'stats', to: `/flows/${flowId}/stats`, label: t('flowNav.stats'), hint: t('flowNav.statsHint') },
  ]
  return (
    <nav aria-label={t('flowNav.label')} className={`inline-flex shrink-0 items-center gap-0.5 rounded-md border border-line bg-surface-muted p-0.5 ${className}`} data-testid="flow-subnav">
      {items.map((item) => (
        <NavLink
          key={item.key}
          to={item.to}
          end={item.end}
          className={({ isActive }) => `whitespace-nowrap rounded px-2 py-1 text-xs transition-colors ${isActive ? 'bg-surface font-medium text-content shadow-xs' : 'text-muted hover:text-content'}`}
          title={item.hint}
          data-testid={`flow-nav-${item.key}`}
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}
