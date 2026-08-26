import { lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from '@/providers/AuthProvider'
import { AppShell } from '@/components/layout/AppShell'
import { Card, EmptyState, LoadingState } from '@/components/ui'
import { LoginPage } from '@/pages/LoginPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { DevicesPage } from '@/pages/DevicesPage'
import { DeviceDetailPage } from '@/pages/DeviceDetailPage'
import { AlertsPage } from '@/pages/AlertsPage'
import { SitesPage } from '@/pages/SitesPage'
import { RecordingPage } from '@/pages/RecordingPage'
import { RulesPage } from '@/pages/RulesPage'
import { TariffsPage } from '@/pages/TariffsPage'
import { StoragePlansPage } from '@/pages/StoragePlansPage'
import { HelpPage } from '@/pages/HelpPage'
import { AuditPage } from '@/pages/AuditPage'
import { EventsPage } from '@/pages/EventsPage'
import { GatewaysPage } from '@/pages/GatewaysPage'
import { WorkflowEditorPage } from '@/pages/WorkflowEditorPage'
import { WorkflowsPage } from '@/pages/WorkflowsPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { NotFoundPage } from '@/pages/NotFoundPage'

// Leaflet and Recharts are the two heavy dependencies; loading them only when
// their route is visited keeps the initial bundle small.
const MapPage = lazy(() => import('@/pages/MapPage'))
const StoragePage = lazy(() => import('@/pages/StoragePage'))
const TelemetryPage = lazy(() => import('@/pages/TelemetryPage'))

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, ready } = useAuth()
  const location = useLocation()
  const { t } = useTranslation()

  if (!ready) return <LoadingState />
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />

  // Authenticated but with no tenant: the API cannot scope anything, so say so
  // rather than letting every page fail with the same 403.
  if (!me.organization) {
    return (
      <Card className="mx-auto mt-16 max-w-md">
        <EmptyState title={t('auth.noOrganization')} />
      </Card>
    )
  }
  return <>{children}</>
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="devices" element={<DevicesPage />} />
        <Route path="devices/:deviceId" element={<DeviceDetailPage />} />
        <Route path="gateways" element={<GatewaysPage />} />
        <Route path="map" element={<MapPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="storage" element={<StoragePage />} />
        <Route path="storage-plans" element={<StoragePlansPage />} />
        <Route path="telemetry" element={<TelemetryPage />} />
        <Route path="sites" element={<SitesPage />} />
        <Route path="recording" element={<RecordingPage />} />
        <Route path="rules" element={<RulesPage />} />
        <Route path="tariffs" element={<TariffsPage />} />
        <Route path="workflows" element={<WorkflowsPage />} />
        <Route path="workflows/:workflowId" element={<WorkflowEditorPage />} />
        <Route path="events" element={<EventsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="help" element={<HelpPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
