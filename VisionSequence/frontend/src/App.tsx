/** data router（createBrowserRouter）：編輯器的 useBlocker 需要它。RequireAuth 未登入時導到 /login。各頁 lazy 載入。 */
import { Suspense, lazy } from 'react'
import { Navigate, Outlet, RouterProvider, createBrowserRouter, useLocation } from 'react-router-dom'

import { AppShell } from '@/components/layout/AppShell'
import { LoadingState } from '@/components/ui'
import { AuthProvider, useAuth } from '@/providers/AuthProvider'

// 路由層級 code-splitting：每頁獨立 chunk，首屏只載 AppShell＋當前頁（主 bundle 由 1.6MB 降到數百 KB）。
const LoginPage = lazy(() => import('@/pages/LoginPage').then((m) => ({ default: m.LoginPage })))
const AgentPage = lazy(() => import('@/pages/AgentPage').then((m) => ({ default: m.AgentPage })))
const AssetsPage = lazy(() => import('@/pages/AssetsPage').then((m) => ({ default: m.AssetsPage })))
const DashboardPage = lazy(() => import('@/pages/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const FlowEditorPage = lazy(() => import('@/pages/FlowEditorPage').then((m) => ({ default: m.FlowEditorPage })))
const FlowsPage = lazy(() => import('@/pages/FlowsPage').then((m) => ({ default: m.FlowsPage })))
const GoldenPage = lazy(() => import('@/pages/GoldenPage').then((m) => ({ default: m.GoldenPage })))
const HelpPage = lazy(() => import('@/pages/HelpPage').then((m) => ({ default: m.HelpPage })))
const IntegrationPage = lazy(() => import('@/pages/IntegrationPage').then((m) => ({ default: m.IntegrationPage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const SourcesPage = lazy(() => import('@/pages/SourcesPage').then((m) => ({ default: m.SourcesPage })))
const StatsPage = lazy(() => import('@/pages/StatsPage').then((m) => ({ default: m.StatsPage })))
const TeachPage = lazy(() => import('@/pages/TeachPage').then((m) => ({ default: m.TeachPage })))
const DlPage = lazy(() => import('@/pages/DlPage').then((m) => ({ default: m.DlPage })))
const ToolPage = lazy(() => import('@/pages/ToolPage').then((m) => ({ default: m.ToolPage })))
const UsersPage = lazy(() => import('@/pages/UsersPage').then((m) => ({ default: m.UsersPage })))

function RequireAuth() {
  const auth = useAuth()
  const location = useLocation()
  if (auth.loading) return <LoadingState />
  if (!auth.authenticated) return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />
  return <Suspense fallback={<LoadingState />}><Outlet /></Suspense>
}

const router = createBrowserRouter([
  { path: '/login', element: <Suspense fallback={<LoadingState />}><LoginPage /></Suspense> },
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <AppShell />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: 'flows', element: <FlowsPage /> },
          { path: 'flows/:flowId', element: <FlowEditorPage /> },
          { path: 'flows/:flowId/tools/:nodeId', element: <ToolPage /> },
          { path: 'flows/:flowId/stats', element: <StatsPage /> },
          { path: 'flows/:flowId/teach', element: <TeachPage /> },
          { path: 'flows/:flowId/golden', element: <GoldenPage /> },
          { path: 'dl', element: <DlPage /> },
          { path: 'agent', element: <AgentPage /> },
          { path: 'connections', element: <Navigate to="/integration?tab=connections" replace /> },
          { path: 'integration', element: <IntegrationPage /> },
          { path: 'help', element: <HelpPage /> },
          { path: 'sources', element: <SourcesPage /> },
          { path: 'assets', element: <AssetsPage /> },
          { path: 'users', element: <UsersPage /> },
          { path: 'settings', element: <SettingsPage /> },
        ],
      },
    ],
  },
])

export function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  )
}
