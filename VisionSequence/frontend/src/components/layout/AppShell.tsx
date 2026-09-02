/**
 * 外框（Gentelella 風）：左側深色側欄（可摺疊成只顯示圖示，狀態存 localStorage `vs.sidebar`）＋
 * 頂部白色導覽列（摺疊鈕、麵包屑、容量、主題切換、使用者選單）＋內容區。
 * 引擎鎖定時內容區最上方出現黃色橫幅。
 */
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Activity, Brain, Camera, ChevronRight, HelpCircle, Images, KeyRound, LayoutDashboard, LogOut, Menu, Plug, Settings, ShieldCheck, UserRound, Users, Workflow } from 'lucide-react'

import { ChangePasswordModal } from '@/components/auth/ChangePasswordModal'
import { LockBanner } from '@/components/auth/LockBanner'
import { GlobalSearch } from '@/components/layout/GlobalSearch'
import { useLockEvents } from '@/lib/flowStream'
import { useCapacity, useFlow } from '@/lib/queries'
import { useAuth } from '@/providers/AuthProvider'

const NAV = [
  { to: '/', key: 'dashboard', icon: LayoutDashboard, end: true, admin: false },
  { to: '/flows', key: 'flows', icon: Workflow, end: false, admin: false },
  { to: '/sources', key: 'sources', icon: Camera, end: false, admin: false },
  { to: '/assets', key: 'assets', icon: Images, end: false, admin: false },
  { to: '/dl', key: 'dl', icon: Brain, end: false, admin: false },
  { to: '/integration', key: 'integration', icon: Plug, end: false, admin: false },
  { to: '/users', key: 'users', icon: Users, end: false, admin: true },
  { to: '/settings', key: 'settings', icon: Settings, end: false, admin: false },
  { to: '/help', key: 'help', icon: HelpCircle, end: false, admin: false },
] as const

export const SIDEBAR_KEY = 'vs.sidebar'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === 'collapsed'
  } catch {
    return false
  }
}

export function CapacityPill({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  const capacity = useCapacity()
  const data = capacity.data
  if (!data) return null
  const ratio = data.max_workers ? data.active / data.max_workers : 0
  const tone = ratio >= 1 ? 'text-critical' : ratio >= 0.7 ? 'text-warning' : 'text-ok'
  const title = data.flows.length ? data.flows.map((f) => `${f.flow_name || f.flow_id}${f.continuous ? ' (連續)' : ''}`).join('\n') : t('capacity.idle')
  return (
    <div className={`tnum ${compact ? 'text-[10px]' : 'text-xs'} ${tone}`} title={title}>
      {t('capacity.label', { active: data.active, max: data.max_workers })}
    </div>
  )
}

/** 頂列容量：icon＋執行數角標，點開才列出執行中的流程（頂列按鍵先 icon、點擊出清單）。 */
function CapacityMenu() {
  const { t } = useTranslation()
  const capacity = useCapacity()
  const [open, setOpen] = useState(false)
  const data = capacity.data
  if (!data) return null
  const ratio = data.max_workers ? data.active / data.max_workers : 0
  const tone = ratio >= 1 ? 'text-critical' : ratio >= 0.7 ? 'text-warning' : data.active ? 'text-ok' : 'text-muted'
  return (
    <div className="relative">
      <button type="button" className="btn-icon relative" onClick={() => setOpen((v) => !v)}
        title={t('capacity.label', { active: data.active, max: data.max_workers })}
        aria-label={t('capacity.label', { active: data.active, max: data.max_workers })} data-testid="capacity-menu">
        <Activity size={16} className={tone} />
        {data.active ? (
          <span className="tnum absolute -right-0.5 -top-0.5 flex min-w-3.5 items-center justify-center rounded-full bg-brand px-0.5 text-[9px] font-semibold leading-3.5 text-on-brand">
            {data.active}
          </span>
        ) : null}
      </button>
      {open ? (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute right-0 top-full z-40 mt-1 w-60 rounded-md border border-line bg-surface p-1.5 text-sm shadow-lg" role="menu" data-testid="capacity-list">
            <p className="tnum px-2 py-1.5 text-xs font-medium text-muted">{t('capacity.label', { active: data.active, max: data.max_workers })}</p>
            {data.flows.length ? (
              data.flows.map((f) => (
                <div key={f.flow_id} className="flex items-center gap-2 rounded-md px-2 py-1.5">
                  <Workflow size={14} className="shrink-0 text-muted" aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{f.flow_name || `#${f.flow_id}`}</span>
                  {f.continuous ? <span className="shrink-0 rounded bg-info-soft px-1.5 py-0.5 text-[10px] text-info">{t('capacity.continuous')}</span> : null}
                </div>
              ))
            ) : (
              <p className="px-2 py-1.5 text-xs text-subtle">{t('capacity.idle')}</p>
            )}
          </div>
        </>
      ) : null}
    </div>
  )
}

/** 頂部導覽列右側：目前使用者、修改密碼、登出。 */
function UserMenu() {
  const { t } = useTranslation()
  const auth = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [changing, setChanging] = useState(false)
  const user = auth.me?.user
  const name = user ? user.display_name || user.username : t('auth.integrator')

  async function logout() {
    setOpen(false)
    await auth.logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="btn-icon"
        title={`${name}${auth.isAdmin ? `（${t('auth.admin')}）` : ''}`}
        aria-label={t('auth.currentUser')}
        data-testid="user-menu"
      >
        <span className="relative flex size-7 items-center justify-center rounded-full bg-surface-muted text-muted">
          <UserRound size={16} aria-hidden />
          {auth.isAdmin ? <ShieldCheck size={10} className="absolute -right-1 -bottom-0.5 text-brand" aria-hidden /> : null}
        </span>
      </button>
      {open ? (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute right-0 top-full z-40 mt-1 w-52 rounded-md border border-line bg-surface p-1.5 text-sm shadow-lg" role="menu">
            <div className="px-2 py-1.5">
              <p className="truncate font-medium">{name}</p>
              <p className="truncate text-xs text-muted">
                {user ? `@${user.username}` : ''}
                {auth.isAdmin ? ` · ${t('auth.admin')}` : ''}
              </p>
            </div>
            {user ? (
              <button type="button" role="menuitem" className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-surface-muted" onClick={() => { setOpen(false); setChanging(true) }}>
                <KeyRound size={14} /> {t('auth.changePassword')}
              </button>
            ) : null}
            <button type="button" role="menuitem" className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-critical hover:bg-surface-muted" onClick={() => void logout()}>
              <LogOut size={14} /> {t('auth.logout')}
            </button>
          </div>
        </>
      ) : null}
      <ChangePasswordModal open={changing} onClose={() => setChanging(false)} />
    </div>
  )
}

/** 麵包屑：由路徑推導（流程子頁會顯示流程名稱）。 */
function Breadcrumb() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const parts = pathname.split('/').filter(Boolean)
  const flowMatch = /^\/flows\/(\d+)(?:\/(teach|tools|stats|golden))?/.exec(pathname)
  const flowId = flowMatch ? Number(flowMatch[1]) : null
  const flow = useFlow(flowId)
  const crumbs: { label: string; to?: string }[] = [{ label: t('nav.dashboard'), to: '/' }]
  if (parts.length) {
    const nav = NAV.find((n) => n.to === `/${parts[0]}`)
    if (nav) crumbs.push({ label: t(`nav.${nav.key}`), to: parts.length > 1 ? nav.to : undefined })
    if (flowId !== null) {
      crumbs.push({ label: flow.data?.name ?? `#${flowId}`, to: flowMatch?.[2] ? `/flows/${flowId}` : undefined })
      const sub = flowMatch?.[2]
      if (sub) crumbs.push({ label: t(`breadcrumb.${sub}`) })
    }
  }
  return (
    <nav className="flex min-w-0 items-center gap-1 text-[13px] text-muted" aria-label="breadcrumb" data-testid="breadcrumb">
      {crumbs.map((c, i) => (
        <span key={i} className="flex min-w-0 items-center gap-1">
          {i > 0 ? <ChevronRight size={13} className="shrink-0 text-subtle" aria-hidden /> : null}
          {c.to ? <NavLink to={c.to} className="truncate hover:text-brand">{c.label}</NavLink> : <span className="truncate font-medium text-heading">{c.label}</span>}
        </span>
      ))}
    </nav>
  )
}

export function AppShell() {
  const { t } = useTranslation()
  const auth = useAuth()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  // 鎖定事件：流程串流會濾掉沒有 flow_id 的事件，所以這裡另開一條只聽 lock 的全域串流。
  useLockEvents(auth.authenticated)
  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_KEY, collapsed ? 'collapsed' : 'expanded')
    } catch {
      /* ignore */
    }
  }, [collapsed])
  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <nav className={`flex shrink-0 flex-col bg-sidebar text-sidebar-text transition-[width] duration-150 ${collapsed ? 'w-[60px]' : 'w-[220px]'}`} data-testid="sidebar" data-collapsed={collapsed ? 'true' : 'false'}>
        <div className="flex h-12 items-center gap-2.5 border-b border-[var(--sidebar-line)] px-3.5" title={t('app.name')}>
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[var(--sidebar-brand)] text-sm font-bold text-white">VS</span>
          {!collapsed ? <span className="truncate text-[15px] font-semibold text-white">{t('app.name')}</span> : null}
        </div>
        {!collapsed ? <p className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-sidebar-muted">{t('nav.section')}</p> : <div className="pt-2" />}
        {/* 摺疊時 tooltip 要伸出側欄：overflow-y-auto 會把 overflow-x 也變成 auto 而裁掉 tooltip，所以摺疊時改 overflow-visible（9 項一定塞得下） */}
        <div className={`flex-1 ${collapsed ? 'overflow-visible' : 'overflow-y-auto'}`}>
          {NAV.filter((item) => !item.admin || auth.isAdmin).map(({ to, key, icon: Icon, end }) => (
            <NavLink key={key} to={to} end={end} title={collapsed ? undefined : t(`nav.${key}`)} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''} ${collapsed ? 'justify-center !px-0' : ''}`} data-testid={`nav-${key}`}>
              <Icon size={17} aria-hidden className="shrink-0" />
              {collapsed ? <span className="nav-tip" role="tooltip">{t(`nav.${key}`)}</span> : <span className="truncate">{t(`nav.${key}`)}</span>}
            </NavLink>
          ))}
        </div>
        <button type="button" onClick={() => setCollapsed((v) => !v)} className={`flex h-11 items-center gap-3 border-t border-[var(--sidebar-line)] text-[12px] text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-text ${collapsed ? 'justify-center' : 'px-4'}`} title={collapsed ? t('nav.expand') : t('nav.collapse')} aria-label={collapsed ? t('nav.expand') : t('nav.collapse')} data-testid="sidebar-toggle">
          <Menu size={16} aria-hidden />
          {!collapsed ? <span className="whitespace-nowrap">{t('nav.collapse')}</span> : null}
        </button>
      </nav>
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-3" data-testid="topbar">
          <button type="button" className="btn-icon" onClick={() => setCollapsed((v) => !v)} title={collapsed ? t('nav.expand') : t('nav.collapse')} aria-label={collapsed ? t('nav.expand') : t('nav.collapse')} data-testid="topbar-toggle">
            <Menu size={18} />
          </button>
          <Breadcrumb />
          <span className="ml-auto flex items-center gap-1">
            <GlobalSearch />
            <CapacityMenu />
            <UserMenu />
          </span>
        </header>
        <LockBanner />
        <div className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

/** 一般頁面的可捲動容器（編輯器不用，它自己管版面）。 */
export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className={`mx-auto px-5 py-5 ${wide ? '' : 'max-w-6xl'}`}>{children}</div>
    </div>
  )
}
