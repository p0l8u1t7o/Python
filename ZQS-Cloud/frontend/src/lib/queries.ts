/**
 * Query and mutation hooks.
 *
 * Keys are namespaced by resource so a mutation can invalidate exactly the
 * lists it affects. Refetch intervals differ by how fast the data actually
 * moves: live values every few seconds, registry data only on demand.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from '@tanstack/react-query'

import { api } from './api'
import type {
  Alert,
  AlertDetail,
  AlertRule,
  AlertSummary,
  ApiKey,
  ApiKeyCreated,
  AuditLog,
  Blueprint,
  Capabilities,
  Command,
  Device,
  DeviceCreated,
  DeviceCredential,
  DeviceDetail,
  DeviceEvent,
  DeviceMapPoint,
  DeviceStatusEvent,
  EnergyAsset,
  EnergyInterval,
  EnergyTotals,
  FleetStats,
  Health,
  LatestValue,
  Member,
  Metric,
  NotificationChannel,
  Organization,
  Page,
  RecordingPolicy,
  SeriesResponse,
  Site,
  SiteOverview,
  SiteSummary,
  StoragePlan,
  Tariff,
} from './types'

/** Values that change on their own; everything else refetches on demand. */
export const LIVE_REFETCH_MS = 15_000
export const FAST_REFETCH_MS = 5_000

export const keys = {
  capabilities: ['capabilities'] as const,
  health: ['health'] as const,
  fleet: ['fleet'] as const,
  sites: ['sites'] as const,
  site: (id: string) => ['sites', id] as const,
  blueprints: ['blueprints'] as const,
  devices: (params: unknown) => ['devices', params] as const,
  device: (id: string) => ['devices', 'detail', id] as const,
  deviceMap: (siteId?: string) => ['devices', 'map', siteId ?? 'all'] as const,
  deviceCommands: (id: string, params: unknown) => ['devices', id, 'commands', params] as const,
  deviceEvents: (id: string, params: unknown) => ['devices', id, 'events', params] as const,
  deviceStatusHistory: (id: string, params: unknown) => ['devices', id, 'status', params] as const,
  commands: (params: unknown) => ['commands', params] as const,
  metrics: ['metrics'] as const,
  policies: ['policies'] as const,
  series: (body: unknown) => ['series', body] as const,
  latest: (deviceIds: string[]) => ['latest', deviceIds] as const,
  deviceMetrics: (id: string) => ['deviceMetrics', id] as const,
  rules: ['rules'] as const,
  channels: ['channels'] as const,
  alerts: (params: unknown) => ['alerts', params] as const,
  alert: (id: string) => ['alerts', 'detail', id] as const,
  alertSummary: ['alerts', 'summary'] as const,
  audit: (params: unknown) => ['audit', params] as const,
  auditActions: ['audit', 'actions'] as const,
  members: ['members'] as const,
  apiKeys: ['apiKeys'] as const,
  organizations: ['organizations'] as const,
  emsAssets: (siteId?: string) => ['ems', 'assets', siteId ?? 'all'] as const,
  emsPlan: (siteId: string) => ['ems', 'plan', siteId] as const,
  emsTariffs: ['ems', 'tariffs'] as const,
  emsOverview: (siteId: string) => ['ems', 'overview', siteId] as const,
  emsIntervals: (siteId: string, params: unknown) => ['ems', 'intervals', siteId, params] as const,
  emsSummary: (siteId: string, params: unknown) => ['ems', 'summary', siteId, params] as const,
}

type Options<T> = Omit<UseQueryOptions<T, Error, T>, 'queryKey' | 'queryFn'>

// ---------------------------------------------------------------------------
// System
// ---------------------------------------------------------------------------
export function useCapabilities() {
  return useQuery({
    queryKey: keys.capabilities,
    queryFn: () => api.get<Capabilities>('/system/capabilities'),
    staleTime: 60 * 60 * 1000,
  })
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => api.get<Health>('/system/health'),
    refetchInterval: 30_000,
  })
}

export function useFleetStats() {
  return useQuery({
    queryKey: keys.fleet,
    queryFn: () => api.get<FleetStats>('/system/fleet'),
    refetchInterval: LIVE_REFETCH_MS,
  })
}

// ---------------------------------------------------------------------------
// Sites
// ---------------------------------------------------------------------------
export function useSites(options?: Options<Page<SiteSummary>>) {
  return useQuery({
    queryKey: keys.sites,
    queryFn: () => api.get<Page<SiteSummary>>('/sites', { limit: 200 }),
    ...options,
  })
}

export function useSiteMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: keys.sites })

  return {
    create: useMutation({
      mutationFn: (body: Partial<Site>) => api.post<Site>('/sites', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Partial<Site> & { id: string }) =>
        api.patch<Site>(`/sites/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/sites/${id}`),
      onSuccess: invalidate,
    }),
  }
}

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------
export interface DeviceListParams {
  q?: string
  status?: string
  site_id?: string
  device_type_id?: string
  limit?: number
  offset?: number
}

export function useDevices(params: DeviceListParams) {
  return useQuery({
    queryKey: keys.devices(params),
    queryFn: () => api.get<Page<Device>>('/devices', { limit: 50, offset: 0, ...params }),
    refetchInterval: LIVE_REFETCH_MS,
  })
}

/** Unpaginated list for pickers; the registry is small enough to hold. */
export function useAllDevices(options?: Options<Page<Device>>) {
  return useQuery({
    queryKey: keys.devices({ all: true }),
    queryFn: () => api.get<Page<Device>>('/devices', { limit: 500 }),
    ...options,
  })
}

export function useDevice(id: string | undefined) {
  return useQuery({
    queryKey: keys.device(id ?? ''),
    queryFn: () => api.get<DeviceDetail>(`/devices/${id}`),
    enabled: Boolean(id),
    refetchInterval: FAST_REFETCH_MS,
  })
}

export function useDeviceMap(siteId?: string) {
  return useQuery({
    queryKey: keys.deviceMap(siteId),
    queryFn: () => api.get<DeviceMapPoint[]>('/devices/map', siteId ? { site_id: siteId } : {}),
    refetchInterval: LIVE_REFETCH_MS,
  })
}

export function useBlueprints() {
  return useQuery({
    queryKey: keys.blueprints,
    queryFn: () => api.get<Blueprint[]>('/blueprints'),
    staleTime: 10 * 60 * 1000,
  })
}

export function useDeviceMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['devices'] })
    void queryClient.invalidateQueries({ queryKey: keys.fleet })
  }

  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<DeviceCreated>('/devices', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Record<string, unknown> & { id: string }) =>
        api.patch<Device>(`/devices/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/devices/${id}`),
      onSuccess: invalidate,
    }),
    rotateCredential: useMutation({
      mutationFn: (id: string) => api.post<DeviceCredential>(`/devices/${id}/credential`),
    }),
  }
}

export function useDeviceCommands(deviceId: string | undefined, params: { limit: number; offset: number }) {
  return useQuery({
    queryKey: keys.deviceCommands(deviceId ?? '', params),
    queryFn: () => api.get<Page<Command>>(`/devices/${deviceId}/commands`, params),
    enabled: Boolean(deviceId),
    refetchInterval: FAST_REFETCH_MS,
  })
}

export function useDeviceEvents(
  deviceId: string | undefined,
  params: { limit: number; offset: number; start?: string; end?: string; level?: string },
) {
  return useQuery({
    queryKey: keys.deviceEvents(deviceId ?? '', params),
    queryFn: () => api.get<Page<DeviceEvent>>(`/devices/${deviceId}/events`, params),
    enabled: Boolean(deviceId),
  })
}

export function useDeviceStatusHistory(
  deviceId: string | undefined,
  params: { limit: number; offset: number; start?: string; end?: string },
) {
  return useQuery({
    queryKey: keys.deviceStatusHistory(deviceId ?? '', params),
    queryFn: () => api.get<Page<DeviceStatusEvent>>(`/devices/${deviceId}/status-history`, params),
    enabled: Boolean(deviceId),
  })
}

export function useSendCommand(deviceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; params: Record<string, unknown> }) =>
      api.post<Command>(`/devices/${deviceId}/commands`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['devices', deviceId, 'commands'] })
      void queryClient.invalidateQueries({ queryKey: ['commands'] })
    },
  })
}

export function useCancelCommand() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<Command>(`/commands/${id}/cancel`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['commands'] })
      void queryClient.invalidateQueries({ queryKey: ['devices'] })
    },
  })
}

// ---------------------------------------------------------------------------
// Telemetry
// ---------------------------------------------------------------------------
export function useMetrics() {
  return useQuery({
    queryKey: keys.metrics,
    queryFn: () => api.get<Metric[]>('/metrics'),
    staleTime: 5 * 60 * 1000,
  })
}

export function usePolicies() {
  return useQuery({
    queryKey: keys.policies,
    queryFn: () => api.get<RecordingPolicy[]>('/recording-policies'),
  })
}

export function usePolicyMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: keys.policies })

  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api.post<RecordingPolicy>('/recording-policies', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Record<string, unknown> & { id: string }) =>
        api.put<RecordingPolicy>(`/recording-policies/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/recording-policies/${id}`),
      onSuccess: invalidate,
    }),
  }
}

export interface SeriesRequest {
  device_ids: string[]
  metrics: string[]
  start?: string
  end?: string
  interval_seconds?: number
  max_points?: number
}

export function useSeries(body: SeriesRequest, enabled = true) {
  return useQuery({
    queryKey: keys.series(body),
    queryFn: () => api.post<SeriesResponse>('/telemetry/series', body),
    enabled: enabled && body.device_ids.length > 0 && body.metrics.length > 0,
    // Charts should follow live data without hammering the aggregation query.
    refetchInterval: LIVE_REFETCH_MS,
  })
}

export function useLatestValues(deviceIds: string[], enabled = true) {
  return useQuery({
    queryKey: keys.latest(deviceIds),
    queryFn: () =>
      api.get<LatestValue[]>('/telemetry/latest', deviceIds.length ? { device_ids: deviceIds } : {}),
    enabled,
    refetchInterval: FAST_REFETCH_MS,
  })
}

export function useDeviceMetricKeys(deviceId: string | undefined) {
  return useQuery({
    queryKey: keys.deviceMetrics(deviceId ?? ''),
    queryFn: () => api.get<string[]>(`/telemetry/devices/${deviceId}/metrics`),
    enabled: Boolean(deviceId),
  })
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------
export interface AlertListParams {
  status?: string
  severity?: string
  device_pk?: string
  site_id?: string
  open_only?: boolean
  start?: string
  end?: string
  limit?: number
  offset?: number
}

export function useAlerts(params: AlertListParams) {
  return useQuery({
    queryKey: keys.alerts(params),
    queryFn: () => api.get<Page<Alert>>('/alerts', { limit: 50, offset: 0, ...params }),
    refetchInterval: LIVE_REFETCH_MS,
  })
}

export function useAlert(id: string | undefined) {
  return useQuery({
    queryKey: keys.alert(id ?? ''),
    queryFn: () => api.get<AlertDetail>(`/alerts/${id}`),
    enabled: Boolean(id),
  })
}

export function useAlertSummary() {
  return useQuery({
    queryKey: keys.alertSummary,
    queryFn: () => api.get<AlertSummary>('/alerts/summary'),
    refetchInterval: LIVE_REFETCH_MS,
  })
}

export function useAlertActions() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['alerts'] })
    void queryClient.invalidateQueries({ queryKey: keys.fleet })
  }

  return {
    acknowledge: useMutation({
      mutationFn: ({ id, note }: { id: string; note: string }) =>
        api.post<Alert>(`/alerts/${id}/acknowledge`, { note }),
      onSuccess: invalidate,
    }),
    resolve: useMutation({
      mutationFn: ({ id, note }: { id: string; note: string }) =>
        api.post<Alert>(`/alerts/${id}/resolve`, { note }),
      onSuccess: invalidate,
    }),
    bulkAcknowledge: useMutation({
      mutationFn: ({ alertIds, note }: { alertIds: string[]; note: string }) =>
        api.post('/alerts/bulk/acknowledge', { alert_ids: alertIds, note }),
      onSuccess: invalidate,
    }),
  }
}

export function useAlertRules() {
  return useQuery({
    queryKey: keys.rules,
    queryFn: () => api.get<AlertRule[]>('/alert-rules'),
  })
}

export function useAlertRuleMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: keys.rules })

  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<AlertRule>('/alert-rules', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Record<string, unknown> & { id: string }) =>
        api.put<AlertRule>(`/alert-rules/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/alert-rules/${id}`),
      onSuccess: invalidate,
    }),
  }
}

export function useNotificationChannels(enabled = true) {
  return useQuery({
    queryKey: keys.channels,
    queryFn: () => api.get<NotificationChannel[]>('/notification-channels'),
    enabled,
    // Only admins may read channels; a 403 is a permission fact, not a blip.
    retry: false,
  })
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------
export function useAuditLogs(params: Record<string, unknown>) {
  return useQuery({
    queryKey: keys.audit(params),
    queryFn: () => api.get<Page<AuditLog>>('/audit', { limit: 50, offset: 0, ...params }),
  })
}

export function useAuditActions() {
  return useQuery({
    queryKey: keys.auditActions,
    queryFn: () => api.get<{ value: string; label: string }[]>('/audit/actions'),
    staleTime: 60 * 60 * 1000,
  })
}

// ---------------------------------------------------------------------------
// Members and API keys
// ---------------------------------------------------------------------------
export function useMembers(enabled = true) {
  return useQuery({
    queryKey: keys.members,
    queryFn: () => api.get<Page<Member>>('/members', { limit: 200 }),
    enabled,
  })
}

export function useMemberMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: keys.members })

  return {
    add: useMutation({
      mutationFn: (body: { email: string; role: string }) => api.post<Member>('/members', body),
      onSuccess: invalidate,
    }),
    createUser: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post('/members/users', body),
      onSuccess: invalidate,
    }),
    setRole: useMutation({
      mutationFn: ({ userId, role }: { userId: string; role: string }) =>
        api.patch<Member>(`/members/${userId}`, { role }),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (userId: string) => api.delete(`/members/${userId}`),
      onSuccess: invalidate,
    }),
  }
}

export function useApiKeys(enabled = true) {
  return useQuery({
    queryKey: keys.apiKeys,
    queryFn: () => api.get<Page<ApiKey>>('/api-keys', { limit: 100 }),
    enabled,
    retry: false,
  })
}

export function useApiKeyMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: keys.apiKeys })

  return {
    create: useMutation({
      mutationFn: (body: { name: string; role: string; expires_in_days?: number | null }) =>
        api.post<ApiKeyCreated>('/api-keys', body),
      onSuccess: invalidate,
    }),
    revoke: useMutation({
      mutationFn: (id: string) => api.delete(`/api-keys/${id}`),
      onSuccess: invalidate,
    }),
  }
}

export function useOrganizations() {
  return useQuery({
    queryKey: keys.organizations,
    queryFn: () => api.get<{ organization: Organization; role: string }[]>('/organizations'),
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api.post('/auth/me/password', body),
  })
}

export function useUpdateProfile() {
  return useMutation({
    mutationFn: (body: { full_name?: string; phone?: string }) =>
      api.patch('/auth/me/profile', body),
  })
}

// ---------------------------------------------------------------------------
// EMS
// ---------------------------------------------------------------------------
export function useEnergyAssets(siteId?: string) {
  return useQuery({
    queryKey: keys.emsAssets(siteId),
    queryFn: () => api.get<EnergyAsset[]>('/ems/assets', siteId ? { site_id: siteId } : {}),
  })
}

export function useStoragePlan(siteId: string | undefined) {
  return useQuery({
    queryKey: keys.emsPlan(siteId ?? ''),
    queryFn: () => api.get<StoragePlan>(`/ems/sites/${siteId}/plan`),
    enabled: Boolean(siteId),
    // A site with no plan yet returns 404; that is a state, not a failure.
    retry: false,
  })
}

export function useTariffs() {
  return useQuery({
    queryKey: keys.emsTariffs,
    queryFn: () => api.get<Tariff[]>('/ems/tariffs'),
  })
}

export function useSiteOverview(siteId: string | undefined) {
  return useQuery({
    queryKey: keys.emsOverview(siteId ?? ''),
    queryFn: () => api.get<SiteOverview>(`/ems/sites/${siteId}/overview`),
    enabled: Boolean(siteId),
    refetchInterval: FAST_REFETCH_MS,
  })
}

export function useEnergyIntervals(
  siteId: string | undefined,
  params: { start?: string; end?: string },
) {
  return useQuery({
    queryKey: keys.emsIntervals(siteId ?? '', params),
    queryFn: () => api.get<EnergyInterval[]>(`/ems/sites/${siteId}/intervals`, params),
    enabled: Boolean(siteId),
    refetchInterval: 60_000,
  })
}

export function useEnergySummary(
  siteId: string | undefined,
  params: { start?: string; end?: string },
) {
  return useQuery({
    queryKey: keys.emsSummary(siteId ?? '', params),
    queryFn: () => api.get<EnergyTotals>(`/ems/sites/${siteId}/summary`, params),
    enabled: Boolean(siteId),
    refetchInterval: 60_000,
  })
}

export function useEmsMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['ems'] })

  return {
    savePlan: useMutation({
      mutationFn: ({ siteId, ...body }: Record<string, unknown> & { siteId: string }) =>
        api.put<StoragePlan>(`/ems/sites/${siteId}/plan`, body),
      onSuccess: invalidate,
    }),
    createAsset: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<EnergyAsset>('/ems/assets', body),
      onSuccess: invalidate,
    }),
    updateAsset: useMutation({
      mutationFn: ({ id, ...body }: Record<string, unknown> & { id: string }) =>
        api.put<EnergyAsset>(`/ems/assets/${id}`, body),
      onSuccess: invalidate,
    }),
    removeAsset: useMutation({
      mutationFn: (id: string) => api.delete(`/ems/assets/${id}`),
      onSuccess: invalidate,
    }),
    rebuildIntervals: useMutation({
      mutationFn: ({ siteId, start, end }: { siteId: string; start: string; end: string }) =>
        api.post(`/ems/sites/${siteId}/rebuild-intervals`, {}, { start, end }),
      onSuccess: invalidate,
    }),
  }
}
