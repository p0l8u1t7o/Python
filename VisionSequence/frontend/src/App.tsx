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
const DashboardsPage = lazy(() => import('@/pages/dashboard/DashboardsPage').then((m) => ({ default: m.DashboardsPage })))
const DashboardDesignerPage = lazy(() => import('@/pages/dashboard/DashboardDesignerPage').then((m) => ({ default: m.DashboardDesignerPage })))
const DashboardViewerPage = lazy(() => import('@/pages/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const FlowEditorPage = lazy(() => import('@/pages/FlowEditorPage').then((m) => ({ default: m.FlowEditorPage })))
const FlowsPage = lazy(() => import('@/pages/FlowsPage').then((m) => ({ default: m.FlowsPage })))
const GoldenPage = lazy(() => import('@/pages/GoldenPage').then((m) => ({ default: m.GoldenPage })))
const BatchPage = lazy(() => import('@/pages/BatchPage').then((m) => ({ default: m.BatchPage })))
const HelpPage = lazy(() => import('@/pages/HelpPage').then((m) => ({ default: m.HelpPage })))
const IntegrationLayout = lazy(() => import('@/pages/IntegrationPage').then((m) => ({ default: m.IntegrationLayout })))
const IntegrationIndex = lazy(() => import('@/pages/IntegrationPage').then((m) => ({ default: m.IntegrationIndex })))
const IntegrationHttpPage = lazy(() => import('@/pages/integration/HttpPage').then((m) => ({ default: m.HttpPage })))
const IntegrationTcpPage = lazy(() => import('@/pages/integration/TcpPage').then((m) => ({ default: m.TcpPage })))
const IntegrationDevicesPage = lazy(() => import('@/pages/integration/DevicesPage').then((m) => ({ default: m.DevicesPage })))
const IntegrationEventsPage = lazy(() => import('@/pages/integration/EventsPage').then((m) => ({ default: m.EventsPage })))
const IntegrationModbusServerPage = lazy(() => import('@/pages/integration/ModbusPage').then((m) => ({ default: m.ModbusServerPage })))
const IntegrationModbusClientPage = lazy(() => import('@/pages/integration/ModbusPage').then((m) => ({ default: m.ModbusClientPage })))
const IntegrationCapturePage = lazy(() => import('@/pages/integration/CapturePage').then((m) => ({ default: m.IntegrationCapturePage })))
const IntegrationPluginsPage = lazy(() => import('@/pages/integration/PluginsPage').then((m) => ({ default: m.PluginsPage })))
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const SourcesPage = lazy(() => import('@/pages/SourcesPage').then((m) => ({ default: m.SourcesPage })))
const CalibrationPage = lazy(() => import('@/pages/CalibrationPage').then((m) => ({ default: m.CalibrationPage })))
const BoardPage = lazy(() => import('@/pages/BoardPage').then((m) => ({ default: m.BoardPage })))
const StatsPage = lazy(() => import('@/pages/StatsPage').then((m) => ({ default: m.StatsPage })))
const TeachPage = lazy(() => import('@/pages/TeachPage').then((m) => ({ default: m.TeachPage })))
const InspectPage = lazy(() => import('@/pages/InspectPage').then((m) => ({ default: m.InspectPage })))
const StationTeachPage = lazy(() => import('@/pages/StationTeachPage').then((m) => ({ default: m.StationTeachPage })))
const DlPage = lazy(() => import('@/pages/DlPage').then((m) => ({ default: m.DlPage })))
const ToolPage = lazy(() => import('@/pages/ToolPage').then((m) => ({ default: m.ToolPage })))
const UsersPage = lazy(() => import('@/pages/UsersPage').then((m) => ({ default: m.UsersPage })))
const AuditPage = lazy(() => import('@/pages/AuditPage').then((m) => ({ default: m.AuditPage })))

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
      // 現場全螢幕看板：沒有側欄與頂列（kiosk 用），登入照常
      { path: '/board/:flowId', element: <Suspense fallback={<LoadingState />}><BoardPage /></Suspense> },
      { path: '/dashboard', element: <Suspense fallback={<LoadingState />}><DashboardViewerPage /></Suspense> },
      { path: '/dashboard/:id', element: <Suspense fallback={<LoadingState />}><DashboardViewerPage /></Suspense> },
      {
        path: '/',
        element: <AppShell />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: 'flows', element: <FlowsPage /> },
          { path: 'dashboards', element: <DashboardsPage /> },
          { path: 'dashboards/:id/design', element: <DashboardDesignerPage /> },
          { path: 'flows/:flowId', element: <FlowEditorPage /> },
          { path: 'flows/:flowId/tools/:nodeId', element: <ToolPage /> },
          { path: 'flows/:flowId/stats', element: <StatsPage /> },
          { path: 'flows/:flowId/teach', element: <TeachPage /> },
          { path: 'flows/:flowId/golden', element: <GoldenPage /> },
          { path: 'flows/:flowId/inspect', element: <InspectPage /> },
          { path: 'teach', element: <StationTeachPage /> },
          { path: 'batch', element: <BatchPage /> },
          { path: 'dl', element: <DlPage /> },
          { path: 'agent', element: <AgentPage /> },
          { path: 'connections', element: <Navigate to="/integration/modbus-server" replace /> },
          {
            path: 'integration',
            element: <IntegrationLayout />,
            children: [
              { index: true, element: <IntegrationIndex /> },
              { path: 'http', element: <IntegrationHttpPage /> },
              { path: 'tcp', element: <IntegrationTcpPage /> },
              { path: 'devices', element: <IntegrationDevicesPage /> },
              { path: 'events', element: <IntegrationEventsPage /> },
              { path: 'modbus-server', element: <IntegrationModbusServerPage /> },
              { path: 'modbus-client', element: <IntegrationModbusClientPage /> },
              { path: 'modbus', element: <Navigate to="/integration/modbus-server" replace /> },
              { path: 'capture', element: <IntegrationCapturePage /> },
              { path: 'plugins', element: <IntegrationPluginsPage /> },
              // 舊書籤（連線／引擎鎖定／回傳格式已併進各整合頁）不要落到 404
              { path: '*', element: <Navigate to="/integration/http" replace /> },
            ],
          },
          { path: 'help', element: <HelpPage /> },
          { path: 'help/:page', element: <HelpPage /> },
          { path: 'sources', element: <SourcesPage /> },
          { path: 'calibration', element: <CalibrationPage /> },
          { path: 'assets', element: <AssetsPage /> },
          { path: 'users', element: <UsersPage /> },
          { path: 'audit', element: <AuditPage /> },
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
