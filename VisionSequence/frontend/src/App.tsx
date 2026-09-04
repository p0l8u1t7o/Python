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
const BatchPage = lazy(() => import('@/pages/BatchPage').then((m) => ({ default: m.BatchPage })))
const HelpPage = lazy(() => import('@/pages/HelpPage').then((m) => ({ default: m.HelpPage })))
const IntegrationLayout = lazy(() => import('@/pages/IntegrationPage').then((m) => ({ default: m.IntegrationLayout })))
const IntegrationIndex = lazy(() => import('@/pages/IntegrationPage').then((m) => ({ default: m.IntegrationIndex })))
const IntegrationHttpPage = lazy(() => import('@/pages/integration/HttpPage').then((m) => ({ default: m.HttpPage })))
const IntegrationTcpPage = lazy(() => import('@/pages/integration/TcpPage').then((m) => ({ default: m.TcpPage })))
const IntegrationEventsPage = lazy(() => import('@/pages/integration/EventsPage').then((m) => ({ default: m.EventsPage })))
const IntegrationLockPage = lazy(() => import('@/pages/integration/LockPage').then((m) => ({ default: m.LockPage })))
const IntegrationFormatPage = lazy(() => import('@/pages/integration/FormatPage').then((m) => ({ default: m.FormatPage })))
const IntegrationModbusPage = lazy(() => import('@/pages/integration/ModbusPage').then((m) => ({ default: m.ModbusPage })))
const IntegrationConnectionsPage = lazy(() => import('@/pages/integration/ConnectionsPage').then((m) => ({ default: m.IntegrationConnectionsPage })))
const IntegrationCapturePage = lazy(() => import('@/pages/integration/CapturePage').then((m) => ({ default: m.IntegrationCapturePage })))
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
          { path: 'batch', element: <BatchPage /> },
          { path: 'dl', element: <DlPage /> },
          { path: 'agent', element: <AgentPage /> },
          { path: 'connections', element: <Navigate to="/integration/connections" replace /> },
          {
            path: 'integration',
            element: <IntegrationLayout />,
            children: [
              { index: true, element: <IntegrationIndex /> },
              { path: 'http', element: <IntegrationHttpPage /> },
              { path: 'tcp', element: <IntegrationTcpPage /> },
              { path: 'events', element: <IntegrationEventsPage /> },
              { path: 'modbus', element: <IntegrationModbusPage /> },
              { path: 'connections', element: <IntegrationConnectionsPage /> },
              { path: 'capture', element: <IntegrationCapturePage /> },
              { path: 'lock', element: <IntegrationLockPage /> },
              { path: 'format', element: <IntegrationFormatPage /> },
            ],
          },
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
