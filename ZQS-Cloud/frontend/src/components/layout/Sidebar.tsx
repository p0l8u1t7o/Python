import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Activity,
  BatteryCharging,
  Bell,
  Building2,
  CircleHelp,
  ClipboardList,
  Cpu,
  LayoutDashboard,
  Map as MapIcon,
  Plug,
  Receipt,
  ScrollText,
  Settings,
  SlidersHorizontal,
  Workflow,
  X,
} from 'lucide-react'

import { useAlertSummary } from '@/lib/queries'
import { IconButton } from '@/components/ui'

interface NavItem {
  to: string
  labelKey: string
  icon: typeof Activity
  badge?: number
}

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const { data: summary } = useAlertSummary()

  const groups: { titleKey: string; items: NavItem[] }[] = [
    {
      titleKey: 'nav.monitoring',
      items: [
        { to: '/', labelKey: 'nav.dashboard', icon: LayoutDashboard },
        { to: '/devices', labelKey: 'nav.devices', icon: Cpu },
        { to: '/map', labelKey: 'nav.map', icon: MapIcon },
        { to: '/alerts', labelKey: 'nav.alerts', icon: Bell, badge: summary?.total_open },
        { to: '/storage', labelKey: 'nav.storage', icon: BatteryCharging },
        { to: '/telemetry', labelKey: 'nav.telemetry', icon: Activity },
        { to: '/events', labelKey: 'nav.events', icon: ScrollText },
      ],
    },
    {
      titleKey: 'nav.configuration',
      items: [
        { to: '/sites', labelKey: 'nav.sites', icon: Building2 },
        { to: '/recording', labelKey: 'nav.policies', icon: SlidersHorizontal },
        { to: '/rules', labelKey: 'nav.rules', icon: Bell },
        { to: '/storage-plans', labelKey: 'nav.storagePlans', icon: BatteryCharging },
        { to: '/tariffs', labelKey: 'nav.tariffs', icon: Receipt },
        { to: '/workflows', labelKey: 'nav.workflows', icon: Workflow },
      ],
    },
    {
      titleKey: 'nav.administration',
      items: [
        { to: '/audit', labelKey: 'nav.audit', icon: ClipboardList },
        { to: '/settings', labelKey: 'nav.settings', icon: Settings },
        { to: '/integration', labelKey: 'nav.integration', icon: Plug },
        { to: '/help', labelKey: 'nav.help', icon: CircleHelp },
      ],
    },
  ]

  return (
    <>
      {/* Scrim only exists on small screens, where the sidebar overlays. */}
      {open ? (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={onClose}
          aria-hidden
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-line
          bg-surface transition-transform lg:static lg:translate-x-0
          ${open ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <div className="flex h-14 items-center justify-between gap-2 border-b border-line px-4">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand text-on-brand"
              aria-hidden
            >
              <BatteryCharging className="size-4" />
            </span>
            <span className="truncate text-sm font-semibold tracking-tight">ZQS Cloud</span>
          </div>
          <IconButton label={t('common.close')} className="lg:hidden" onClick={onClose}>
            <X className="size-4" />
          </IconButton>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {groups.map((group) => (
            <div key={group.titleKey} className="mb-4">
              <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-subtle">
                {t(group.titleKey)}
              </p>
              <ul className="space-y-0.5">
                {group.items.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.to === '/'}
                      onClick={onClose}
                      className={({ isActive }) =>
                        `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                          isActive
                            ? 'bg-brand-soft font-medium text-brand'
                            : 'text-muted hover:bg-surface-muted hover:text-content'
                        }`
                      }
                    >
                      <item.icon className="size-4 shrink-0" aria-hidden />
                      <span className="flex-1 truncate">{t(item.labelKey)}</span>
                      {item.badge ? (
                        <span className="rounded-full bg-critical px-1.5 py-0.5 text-[10px] font-semibold text-white tnum">
                          {item.badge > 99 ? '99+' : item.badge}
                        </span>
                      ) : null}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </aside>
    </>
  )
}
