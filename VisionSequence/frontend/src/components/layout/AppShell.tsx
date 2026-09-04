/**
 * 外框（Gentelella 風）：左側深色側欄（可摺疊成只顯示圖示，狀態存 localStorage `vs.sidebar`）＋
 * 頂部白色導覽列（摺疊鈕、麵包屑、容量、主題切換、使用者選單）＋內容區。
 * 引擎鎖定時內容區最上方出現黃色橫幅。
 */
import { Suspense, useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Activity, Brain, Camera, ChevronDown, ChevronRight, FlaskConical, HelpCircle, History, Images, KeyRound, LayoutDashboard, LogOut, Menu, Plug, Settings, ShieldCheck, Sparkles, UserRound, Users, Workflow } from 'lucide-react'

import { AssistantDock } from '@/components/assistant/AssistantDock'
import { ChangePasswordModal } from '@/components/auth/ChangePasswordModal'
import { BrandMark, LoadingState } from '@/components/ui'
import { LockBanner } from '@/components/auth/LockBanner'
import { GlobalSearch } from '@/components/layout/GlobalSearch'
import { useLockEvents } from '@/lib/flowStream'
import { MOBILE_QUERY, NARROW_QUERY, useMediaQuery } from '@/lib/useMediaQuery'
import { useCapacity, useFlow, useIntegrationInfo } from '@/lib/queries'
import type { LucideIcon } from 'lucide-react'

import { SECTIONS } from '@/pages/integration/sections'
import { useAuth } from '@/providers/AuthProvider'

const NAV: { to: string; key: string; icon: LucideIcon; end: boolean; admin: boolean; engineer?: boolean; tree?: boolean }[] = [
  { to: '/', key: 'dashboard', icon: LayoutDashboard, end: true, admin: false },
  { to: '/flows', key: 'flows', icon: Workflow, end: false, admin: false },
  { to: '/batch', key: 'batch', icon: FlaskConical, end: false, admin: false, engineer: true },
  { to: '/sources', key: 'sources', icon: Camera, end: false, admin: false, engineer: true },
  { to: '/assets', key: 'assets', icon: Images, end: false, admin: false, engineer: true },
  { to: '/dl', key: 'dl', icon: Brain, end: false, admin: false, engineer: true },
  { to: '/agent', key: 'agent', icon: Sparkles, end: false, admin: false, engineer: true },
  { to: '/integration', key: 'integration', icon: Plug, end: false, admin: false, engineer: true, tree: true },
  { to: '/users', key: 'users', icon: Users, end: false, admin: true },
  { to: '/audit', key: 'audit', icon: History, end: false, admin: true },
  { to: '/settings', key: 'settings', icon: Settings, end: false, admin: false },
  { to: '/help', key: 'help', icon: HelpCircle, end: false, admin: false },
]

export const SIDEBAR_KEY = 'vs.sidebar'
const NAV_OPEN_KEY = 'vs.navOpen'

function readOpenGroups(): string[] {
  try {
    return JSON.parse(localStorage.getItem(NAV_OPEN_KEY) || '[]') as string[]
  } catch {
    return []
  }
}

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
  const narrow = useMediaQuery(NARROW_QUERY)
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
  // 窄螢幕只留最後兩層（否則每層被擠成 1～6px 寬的省略號，點不到也看不懂）
  const shown = narrow ? crumbs.slice(-2) : crumbs
  return (
    <nav className="flex min-w-0 items-center gap-1 text-[13px] text-muted" aria-label="breadcrumb" data-testid="breadcrumb">
      {shown.map((c, i) => (
        <span key={i} className="flex min-w-0 items-center gap-1">
          {i > 0 ? <ChevronRight size={13} className="shrink-0 text-subtle" aria-hidden /> : null}
          {c.to ? <NavLink to={c.to} className="min-w-8 truncate py-1 hover:text-brand">{c.label}</NavLink> : <span className="truncate py-1 font-medium text-heading">{c.label}</span>}
        </span>
      ))}
    </nav>
  )
}

export function AppShell() {
  const { t } = useTranslation()
  const auth = useAuth()
  const info = useIntegrationInfo()  // 版本號顯示在側欄底部
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [openGroups, setOpenGroups] = useState<string[]>(readOpenGroups)
  const toggleGroup = (key: string) =>
    setOpenGroups((prev) => {
      const next = prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
      try {
        localStorage.setItem(NAV_OPEN_KEY, JSON.stringify(next))
      } catch {
        /* 隱私模式沒有 localStorage 也要能用 */
      }
      return next
    })
  // 手機（< 768px）：側欄改成抽屜（預設收起、☰ 開啟、點選項目或換頁自動關），不再佔掉 220px 內容寬
  const mobile = useMediaQuery(MOBILE_QUERY)
  const [mobileOpen, setMobileOpen] = useState(false)
  const { pathname } = useLocation()
  useEffect(() => { setMobileOpen(false) }, [pathname])
  const narrow = collapsed && !mobile
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
      {mobile && mobileOpen ? <div className="fixed inset-0 z-30 bg-black/50" onClick={() => setMobileOpen(false)} aria-hidden data-testid="sidebar-backdrop" /> : null}
      <nav
        className={mobile
          ? `fixed inset-y-0 left-0 z-40 flex w-[220px] flex-col bg-sidebar text-sidebar-text shadow-2xl transition-transform duration-150 ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}`
          : `flex shrink-0 flex-col bg-sidebar text-sidebar-text transition-[width] duration-150 ${narrow ? 'w-[60px]' : 'w-[220px]'}`}
        data-testid="sidebar" data-collapsed={narrow ? 'true' : 'false'} data-mobile={mobile ? 'true' : 'false'} aria-hidden={mobile && !mobileOpen ? true : undefined}>
        <div className="flex h-12 items-center gap-2.5 border-b border-[var(--sidebar-line)] px-3.5" title={t('app.name')}>
          <BrandMark size={30} />
          {!narrow ? <span className="truncate text-[15px] font-semibold tracking-tight text-white">{t('app.name')}</span> : null}
        </div>
        {!narrow ? <p className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-sidebar-muted">{t('nav.section')}</p> : <div className="pt-2" />}
        {/* 摺疊時 tooltip 要伸出側欄：overflow-y-auto 會把 overflow-x 也變成 auto 而裁掉 tooltip，所以摺疊時改 overflow-visible（10 項一定塞得下） */}
        <div className={`flex-1 ${narrow ? 'overflow-visible' : 'overflow-y-auto'}`}>
          {NAV.filter((item) => (!item.admin || auth.isAdmin) && (!item.engineer || auth.isEngineer)).map(({ to, key, icon: Icon, end, tree }) => (
            <div key={key}>
              <div className="relative flex items-center">
                <NavLink to={to} end={end} onClick={() => setMobileOpen(false)} title={narrow ? undefined : t(`nav.${key}`)} className={({ isActive }) => `nav-item flex-1 ${isActive ? 'active' : ''} ${narrow ? 'justify-center !px-0' : ''}`} data-testid={`nav-${key}`}>
                  <Icon size={17} aria-hidden className="shrink-0" />
                  {narrow ? <span className="nav-tip" role="tooltip">{t(`nav.${key}`)}</span> : <span className="truncate">{t(`nav.${key}`)}</span>}
                </NavLink>
                {tree && !narrow ? (
                  <button type="button" onClick={() => toggleGroup(key)} aria-expanded={openGroups.includes(key)} aria-label={t(openGroups.includes(key) ? 'nav.collapseGroup' : 'nav.expandGroup')}
                    className="absolute right-1 flex size-6 items-center justify-center rounded text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-text" data-testid={`nav-${key}-toggle`}>
                    {openGroups.includes(key) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                ) : null}
              </div>
              {tree && !narrow && openGroups.includes(key) ? (
                <div className="mb-1" data-testid={`nav-${key}-children`}>
                  {SECTIONS.map((section) => (
                    <NavLink key={section.id} to={`/integration/${section.id}`} onClick={() => setMobileOpen(false)}
                      className={({ isActive }) => `nav-item !py-1.5 !pl-9 text-[13px] ${isActive ? 'active' : ''}`} data-testid={`nav-integration-${section.id}`}>
                      <section.icon size={14} aria-hidden className="shrink-0" />
                      <span className="truncate">{t(`integration.tabs.${section.key}`)}</span>
                    </NavLink>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
        <button type="button" onClick={() => setCollapsed((v) => !v)} className={`${mobile ? 'hidden' : 'flex'} h-11 items-center gap-3 border-t border-[var(--sidebar-line)] text-[12px] text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-text ${narrow ? 'justify-center' : 'px-4'}`} title={narrow ? t('nav.expand') : t('nav.collapse')} aria-label={narrow ? t('nav.expand') : t('nav.collapse')} data-testid="sidebar-toggle">
          <Menu size={16} aria-hidden />
          {!narrow ? <span className="whitespace-nowrap">{t('nav.collapse')}</span> : null}
          {/* 版本號：客戶回報問題時的第一個問題 */}
          {!narrow && info.data?.version ? <span className="ml-auto pr-1 font-mono text-[10px] text-sidebar-muted" data-testid="app-version">v{info.data.version}</span> : null}
        </button>
      </nav>
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-3" data-testid="topbar">
          <button type="button" className="btn-icon" onClick={() => (mobile ? setMobileOpen((v) => !v) : setCollapsed((v) => !v))} aria-expanded={mobile ? mobileOpen : !collapsed} title={mobile ? t('nav.menu') : collapsed ? t('nav.expand') : t('nav.collapse')} aria-label={mobile ? t('nav.menu') : collapsed ? t('nav.expand') : t('nav.collapse')} data-testid="topbar-toggle">
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
        <AssistantDock />
        <div className="min-h-0 flex-1 overflow-hidden">
          <Suspense fallback={<LoadingState />}><Outlet /></Suspense>
        </div>
      </main>
    </div>
  )
}

/** 一般頁面的可捲動容器（編輯器不用，它自己管版面）。 */
export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className={`mx-auto px-5 pt-5 pb-24 ${wide ? '' : 'max-w-6xl'}`}>{children}</div>
    </div>
  )
}
