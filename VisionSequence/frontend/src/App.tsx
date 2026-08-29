/** data router（createBrowserRouter）：編輯器的 useBlocker 需要它。RequireAuth 未登入時導到 /login。 */
import { Navigate, Outlet, RouterProvider, createBrowserRouter, useLocation } from 'react-router-dom'

import { AppShell } from '@/components/layout/AppShell'
import { LoadingState } from '@/components/ui'
import { AssetsPage } from '@/pages/AssetsPage'
import { ConnectionsPage } from '@/pages/ConnectionsPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { FlowEditorPage } from '@/pages/FlowEditorPage'
import { FlowsPage } from '@/pages/FlowsPage'
import { GoldenPage } from '@/pages/GoldenPage'
import { HelpPage } from '@/pages/HelpPage'
import { IntegrationPage } from '@/pages/IntegrationPage'
import { LoginPage } from '@/pages/LoginPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { SourcesPage } from '@/pages/SourcesPage'
import { StatsPage } from '@/pages/StatsPage'
import { TeachPage } from '@/pages/TeachPage'
import { ToolPage } from '@/pages/ToolPage'
import { UsersPage } from '@/pages/UsersPage'
import { AuthProvider, useAuth } from '@/providers/AuthProvider'

function RequireAuth() {
  const auth = useAuth()
  const location = useLocation()
  if (auth.loading) return <LoadingState />
  if (!auth.authenticated) return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />
  return <Outlet />
}

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
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
          { path: 'connections', element: <ConnectionsPage /> },
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
