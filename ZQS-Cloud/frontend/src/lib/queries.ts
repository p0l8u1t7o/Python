/**
 * Query and mutation hooks.
 *
 * Keys are namespaced by resource so a mutation can invalidate exactly the
 * lists it affects. Refetch intervals differ by how fast the data actually
 * moves: live values every few seconds, registry data only on demand.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from '@tanstack/react-query'

import { api, requestBlob } from './api'
import type { EnergyReport, ReportParams } from '@/components/reports/reportTypes'
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
  CostBreakdown,
  CostModel,
  CostOverview,
  Device,
  DeviceEnergy,
  DeviceCreated,
  DeviceCredential,
  DeviceDeclaration,
  DeviceDetail,
  DeviceReplacement,
  LifecycleState,
  DeviceEvent,
  DeviceMapPoint,
  DeviceStatusEvent,
  EnergyAsset,
  EnergyInterval,
  EnergyTotals,
  FleetLive,
  FleetStats,
  Health,
  Member,
  Metric,
  DispatchDecision,
  DispatchWindow,
  DemandResponseEvent,
  NotificationChannel,
  TariffPreset,
  OperatingSession,
  Organization,
  Page,
  RecordingPolicy,
  SeriesResponse,
  SessionSummary,
  Site,
  SiteInvestment,
  SiteOverview,
  SiteSummary,
  StoragePlan,
  Tariff,
  UiPreference,
  EdgeNode,
  EventCode,
  GeocodeResponse,
  IngressDebugStatus,
  IngressDiagnosis,
  IngressTrace,
} from './types'
import type {
  NodeTypeDef,
  TemplateInstantiation,
  Workflow,
  WorkflowCapacity,
  WorkflowGraph,
  WorkflowRun,
  WorkflowRunLog,
  WorkflowTemplate,
} from './workflowTypes'

/** Values that change on their own; everything else refetches on demand. */
export const LIVE_REFETCH_MS = 15_000
export const FAST_REFETCH_MS = 5_000

export const keys = {
  capabilities: ['capabilities'] as const,
  timezones: ['system', 'timezones'] as const,
  events: (params: unknown) => ['events', params] as const,
  eventCodes: (params: unknown) => ['events', 'codes', params] as const,
  edgeNodes: (params: unknown) => ['edge-nodes', params] as const,
  nodeTypes: ['workflows', 'node-types'] as const,
  workflowCapacity: ['workflows', 'capacity'] as const,
  workflows: ['workflows', 'list'] as const,
  workflow: (id: string) => ['workflows', 'detail', id] as const,
  workflowRuns: (params: unknown) => ['workflow-runs', params] as const,
  workflowRun: (id: string) => ['workflow-runs', 'detail', id] as const,
  workflowRunLogs: (id: string, params: unknown) =>
    ['workflow-runs', 'logs', id, params] as const,
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
  emsCostOverview: (params: unknown) => ['ems', 'cost-overview', params] as const,
  emsCostBreakdown: (siteId: string, params: unknown) =>
    ['ems', 'cost-breakdown', siteId, params] as const,
  emsCostModels: ['ems', 'cost-models'] as const,
  emsSessions: (params: unknown) => ['ems', 'sessions', params] as const,
  emsSessionSummary: (params: unknown) => ['ems', 'sessions', 'summary', params] as const,
  emsDispatchPreview: ['ems', 'dispatch', 'preview'] as const,
  emsDispatchWindows: (siteId: string | undefined) => ['ems', 'dispatch', 'windows', siteId] as const,
  deviceEnergy: (id: string, params: unknown) => ['devices', id, 'energy', params] as const,
  emsLive: ['ems', 'live'] as const,
  emsInvestment: (siteId: string, params: unknown) =>
    ['ems', 'investment', siteId, params] as const,
  uiPreference: (key: string) => ['ui-preference', key] as const,
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

/**
 * IANA zone names the *server* accepts.
 *
 * Fetched rather than bundled: the value has to survive server-side
 * validation, so the only list worth offering is the one the server has.
 * Cached hard - tzdata changes a few times a year, not a few times an hour.
 */
export function useTimezones() {
  return useQuery({
    queryKey: keys.timezones,
    queryFn: () => api.get<string[]>('/system/timezones'),
    staleTime: 24 * 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  })
}

/**
 * Look up coordinates for an address.
 *
 * A mutation rather than a query on purpose: it runs when somebody presses a
 * button, not when a field changes. The upstream service allows one request
 * per second, and a query keyed on the address text would fire one per
 * keystroke and get the whole deployment rate-limited.
 */
export function useGeocode() {
  return useMutation({
    mutationFn: (address: string) =>
      api.get<GeocodeResponse>('/sites/geocode', { q: address }),
  })
}

/**
 * The fleet-wide operation log.
 *
 * Separate from `useDeviceEvents`, which is scoped to one device: the two
 * answer different questions and are filtered differently, so sharing a hook
 * would mean a params object where half the fields are always unused.
 */
export function useEvents(params: Record<string, unknown>) {
  return useQuery({
    queryKey: keys.events(params),
    queryFn: () => api.get<Page<DeviceEvent>>('/events', params),
    refetchInterval: LIVE_REFETCH_MS,
    placeholderData: (previous) => previous,
  })
}

export function useEventCodes(params: Record<string, unknown>) {
  return useQuery({
    queryKey: keys.eventCodes(params),
    queryFn: () => api.get<EventCode[]>('/events/codes', params),
    staleTime: 5 * 60 * 1000,
  })
}

export function useEdgeNodeMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['edge-nodes'] })
    void queryClient.invalidateQueries({ queryKey: ['devices'] })
  }
  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api.post<{ edge_node: EdgeNode; credential: DeviceCredential | null }>('/edge-nodes', body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/edge-nodes/${id}`),
      onSuccess: invalidate,
    }),
    rotate: useMutation({
      mutationFn: (id: string) => api.post<DeviceCredential>(`/edge-nodes/${id}/credential`),
    }),
    /** Ask the gateway to re-announce itself and everything behind it. */
    rebirth: useMutation({
      mutationFn: (id: string) => api.post(`/edge-nodes/${id}/rebirth`),
      onSuccess: invalidate,
    }),
  }
}

export function useEdgeNodes(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: keys.edgeNodes(params),
    queryFn: () => api.get<Page<EdgeNode>>('/edge-nodes', params),
    refetchInterval: LIVE_REFETCH_MS,
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
// Per-user console layout
// ---------------------------------------------------------------------------
/**
 * A layout choice that follows the person rather than the browser.
 *
 * Distinct from theme/language/timezone on the user record, which the API
 * itself reads. Nothing on the server reads these; they exist so that a
 * customised page is still customised on another machine.
 *
 * `fallback` is returned while the request is in flight and when nothing has
 * been saved, so callers never have to render a half-configured page - an
 * unset key is the normal first-visit case, not an error.
 */
export function useUiPreference<T extends Record<string, unknown>>(
  key: string,
  fallback: T,
) {
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: keys.uiPreference(key),
    queryFn: () => api.get<UiPreference>(`/auth/me/ui/${key}`),
    // Layouts change only when this user changes them, and they have just
    // been told the answer by their own mutation.
    staleTime: 10 * 60 * 1000,
  })

  const save = useMutation({
    mutationFn: (value: T) =>
      api.put<UiPreference>(`/auth/me/ui/${key}`, { value }),
    // Written straight into the cache rather than invalidated: the control
    // that triggered this is looking at the value, and a refetch round trip
    // would make it visibly lag the click.
    onSuccess: (result) => queryClient.setQueryData(keys.uiPreference(key), result),
  })

  const reset = useMutation({
    mutationFn: () => api.delete(`/auth/me/ui/${key}`),
    onSuccess: () =>
      queryClient.setQueryData(keys.uiPreference(key), { key, value: {} }),
  })

  const stored = query.data?.value as T | undefined
  const value = stored && Object.keys(stored).length > 0 ? { ...fallback, ...stored } : fallback

  return { value, isLoaded: !query.isPending, save, reset }
}

// ---------------------------------------------------------------------------
// Sites
// ---------------------------------------------------------------------------
/**
 * The whole site tree in one request. `include_descendants` fills the
 * `total_*` counts so a parent row can show both its own devices and its
 * subtree's without a second call; the plain counts stay the site's own.
 */
export function useSites(
  options?: Options<Page<SiteSummary>> & { includeDescendants?: boolean },
) {
  const { includeDescendants = false, ...queryOptions } = options ?? {}
  return useQuery({
    queryKey: [...keys.sites, { includeDescendants }],
    queryFn: () =>
      api.get<Page<SiteSummary>>('/sites', {
        limit: 200,
        ...(includeDescendants ? { include_descendants: true } : {}),
      }),
    ...queryOptions,
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
  /** Widen `site_id` to the whole subtree below that site. */
  include_descendants?: boolean
  /** Only devices with no site at all - the ones a tree cannot place. */
  unassigned_only?: boolean
  device_type_id?: string
  /** Only devices reporting through this gateway (edge node pk). */
  edge_node_id?: string
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

export function useDeviceDeclaration(deviceId: string | undefined) {
  return useQuery({
    queryKey: ['devices', 'detail', deviceId ?? '', 'declaration'],
    queryFn: () => api.get<DeviceDeclaration>(`/devices/${deviceId}/declaration`),
    enabled: Boolean(deviceId),
    // 404 simply means the device has never declared anything.
    retry: false,
  })
}

export function useReviewDeclaration(deviceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { accept: boolean; note?: string }) =>
      api.post<DeviceDeclaration>(`/devices/${deviceId}/declaration/review`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.device(deviceId) })
      queryClient.invalidateQueries({ queryKey: keys.devices({}) })
    },
  })
}

/** Suspend, retire, reject or return a device to service. */
export function useLifecycleMutation(deviceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { state: LifecycleState; reason?: string }) =>
      api.post<Device>(`/devices/${deviceId}/lifecycle`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.device(deviceId) })
      queryClient.invalidateQueries({ queryKey: ['devices'] })
    },
  })
}

/**
 * Register a successor and hand everything over to it in one transaction.
 *
 * The new `device_id` must be new: it is the MQTT topic segment and is unique
 * platform-wide, and a retired device keeps its own so its history stays
 * attributable to it.
 */
export function useReplaceDevice(deviceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      device_id: string
      name: string
      serial_number?: string
      reason?: string
    }) => api.post<DeviceReplacement>(`/devices/${deviceId}/replace`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['devices'] })
      queryClient.invalidateQueries({ queryKey: keys.sites })
    },
  })
}

/**
 * How much energy one device moved over a window.
 *
 * Distinct from the site figures under `/ems`: those are a site's balance on a
 * fixed 15-minute grid, and a single device is not a slice of them. Read
 * `basis` before quoting the number - `integrated` is an approximation and
 * `coverage` says how good an approximation.
 */
export function useDeviceEnergy(
  deviceId: string | undefined,
  params: { start?: string; end?: string; metric_key?: string } = {},
) {
  return useQuery({
    queryKey: keys.deviceEnergy(deviceId ?? '', params),
    queryFn: () => api.get<DeviceEnergy>(`/devices/${deviceId}/energy`, params),
    enabled: Boolean(deviceId),
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
  /**
   * Chart every device in these sites without listing them. The server
   * expands them, so the console needs no extra round trip.
   */
  site_ids?: string[]
  include_descendants?: boolean
  metrics: string[]
  start?: string
  end?: string
  interval_seconds?: number
  max_points?: number
}

export function useSeries(body: SeriesRequest, enabled = true) {
  const hasSelection = body.device_ids.length > 0 || (body.site_ids?.length ?? 0) > 0
  return useQuery({
    queryKey: keys.series(body),
    queryFn: () => api.post<SeriesResponse>('/telemetry/series', body),
    enabled: enabled && hasSelection && body.metrics.length > 0,
    // Charts should follow live data without hammering the aggregation query.
    refetchInterval: LIVE_REFETCH_MS,
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

export function useNotificationChannelMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: keys.channels })
  }

  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api.post<NotificationChannel>('/notification-channels', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
        api.put<NotificationChannel>(`/notification-channels/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/notification-channels/${id}`),
      onSuccess: invalidate,
    }),
    /** Send one test message through a configuration, saved or not. */
    test: useMutation({
      mutationFn: (body: {
        id?: string
        name: string
        channel_type: string
        config: Record<string, unknown>
      }) => api.post<{ ok: boolean; message: string }>('/notification-channels/test', body),
    }),
  }
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
      // site_ids is omitted unless the caller passes it: sending it on every
      // role change would silently wipe a member's site scope.
      mutationFn: ({ userId, ...body }: { userId: string; role: string; site_ids?: string[] }) =>
        api.patch<Member>(`/members/${userId}`, body),
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

export function useCurrentOrganization() {
  return useQuery({
    queryKey: keys.organizations,
    queryFn: () => api.get<Organization>('/organizations/current'),
  })
}

export function useUpdateOrganization() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name?: string; default_timezone?: string; reporting_currency?: string }) =>
      api.patch<Organization>('/organizations/current', body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.organizations })
    },
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

export function useStoragePlans() {
  return useQuery({
    queryKey: ['ems', 'plans'],
    queryFn: () => api.get<StoragePlan[]>('/ems/plans'),
  })
}

export function useStoragePlanMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['ems'] })
  }

  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api.post<StoragePlan>('/ems/plans', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
        api.put<StoragePlan>(`/ems/plans/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/ems/plans/${id}`),
      onSuccess: invalidate,
    }),
  }
}

export function useDemandResponse(siteId: string | undefined) {
  return useQuery({
    queryKey: ['ems', 'demand-response', siteId ?? ''],
    queryFn: () =>
      api.get<DemandResponseEvent[]>(`/ems/sites/${siteId}/demand-response`),
    enabled: Boolean(siteId),
    refetchInterval: FAST_REFETCH_MS,
  })
}

export function useDemandResponseMutations(siteId: string | undefined) {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['ems', 'demand-response'] })
  }

  return {
    trigger: useMutation({
      mutationFn: (body: {
        target_power_kw: number
        duration_minutes: number
        note?: string
      }) => api.post<DemandResponseEvent>(`/ems/sites/${siteId}/demand-response`, body),
      onSuccess: invalidate,
    }),
    cancel: useMutation({
      mutationFn: (eventId: string) =>
        api.post<DemandResponseEvent>(`/ems/demand-response/${eventId}/cancel`, {}),
      onSuccess: invalidate,
    }),
  }
}

export function useTariffs() {
  return useQuery({
    queryKey: keys.emsTariffs,
    queryFn: () => api.get<Tariff[]>('/ems/tariffs'),
  })
}

export function useTariffPresets() {
  return useQuery({
    queryKey: ['ems', 'tariff-presets'],
    queryFn: () => api.get<TariffPreset[]>('/ems/tariffs/presets'),
    // Bundled tables only change with a deploy.
    staleTime: 60 * 60 * 1000,
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

/**
 * Cost and savings for every site in one request.
 *
 * One call rather than one per site: the dashboard renders every site the user
 * can see, and asking individually is a round trip each.
 */
export function useCostOverview(params: { start?: string; end?: string } = {}) {
  return useQuery({
    queryKey: keys.emsCostOverview(params),
    queryFn: () => api.get<CostOverview>('/ems/cost-overview', params),
    refetchInterval: 60_000,
  })
}

/** Where one site's money went, by source. */
export function useCostBreakdown(
  siteId: string | undefined,
  params: { start?: string; end?: string } = {},
) {
  return useQuery({
    queryKey: keys.emsCostBreakdown(siteId ?? '', params),
    queryFn: () =>
      api.get<CostBreakdown>(`/ems/sites/${siteId}/cost-breakdown`, params),
    enabled: Boolean(siteId),
  })
}

/** The registered cost models, so the console never hard-codes the list. */
export function useCostModels() {
  return useQuery({
    queryKey: keys.emsCostModels,
    queryFn: () => api.get<CostModel[]>('/ems/cost-models'),
    staleTime: 60 * 60 * 1000,
  })
}

export interface SessionListParams {
  site_id?: string
  device_pk?: string
  kind?: string
  /** Ignores the window: "what is running right now", not "started today". */
  open_only?: boolean
  start?: string
  end?: string
  limit?: number
  offset?: number
}

export function useOperatingSessions(params: SessionListParams) {
  return useQuery({
    queryKey: keys.emsSessions(params),
    queryFn: () =>
      api.get<Page<OperatingSession>>('/ems/sessions', { limit: 25, ...params }),
  })
}

export function useSessionSummary(
  params: { site_id?: string; device_pk?: string; start?: string; end?: string } = {},
) {
  return useQuery({
    queryKey: keys.emsSessionSummary(params),
    queryFn: () => api.get<SessionSummary[]>('/ems/sessions/summary', params),
  })
}

/** What the dispatch engine would send right now, without sending it. */
export function useDispatchPreview(options?: Options<DispatchDecision[]>) {
  return useQuery({
    queryKey: keys.emsDispatchPreview,
    queryFn: () => api.get<DispatchDecision[]>('/ems/dispatch-windows/preview'),
    refetchInterval: LIVE_REFETCH_MS,
    ...options,
  })
}

/**
 * Current power at every site, plus today's totals, in one request.
 *
 * The overview needs a headline figure *and* a row per site; asking the
 * per-site endpoint once per site would be a round trip each.
 */
export function useFleetLive(options?: Options<FleetLive>) {
  return useQuery({
    queryKey: keys.emsLive,
    queryFn: () => api.get<FleetLive>('/ems/live'),
    refetchInterval: FAST_REFETCH_MS,
    ...options,
  })
}

/** What the equipment at a site cost, and its share of the window. */
export function useSiteInvestment(
  siteId: string | undefined,
  params: { start?: string; end?: string } = {},
) {
  return useQuery({
    queryKey: keys.emsInvestment(siteId ?? '', params),
    queryFn: () => api.get<SiteInvestment>(`/ems/sites/${siteId}/investment`, params),
    enabled: Boolean(siteId),
  })
}

export function useTariffMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: keys.emsTariffs })
    // A price change moves every cost figure, so the plans that reference it
    // and anything derived from them have to be considered stale too.
    void queryClient.invalidateQueries({ queryKey: ['ems'] })
  }

  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<Tariff>('/ems/tariffs', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Record<string, unknown> & { id: string }) =>
        api.put<Tariff>(`/ems/tariffs/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/ems/tariffs/${id}`),
      onSuccess: invalidate,
    }),
  }
}

export function useDispatchWindows(siteId: string | undefined) {
  return useQuery({
    queryKey: keys.emsDispatchWindows(siteId),
    queryFn: () => api.get<DispatchWindow[]>('/ems/dispatch-windows', siteId ? { site_id: siteId } : {}),
    refetchInterval: LIVE_REFETCH_MS,
  })
}

export function useDispatchWindowMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['ems', 'dispatch'] })
  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) => api.post<DispatchWindow>('/ems/dispatch-windows', body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/ems/dispatch-windows/${id}`),
      onSuccess: invalidate,
    }),
  }
}

export function useEmsMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['ems'] })

  return {
    bindPlan: useMutation({
      mutationFn: ({ siteId, planId }: { siteId: string; planId: string | null }) =>
        api.put(`/ems/sites/${siteId}/plan`, { plan_id: planId }),
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
    rebuildSessions: useMutation({
      mutationFn: (params: { start: string; end: string; device_pk?: string }) =>
        api.post('/ems/sessions/rebuild', {}, params),
      onSuccess: invalidate,
    }),
    /**
     * Run the dispatch engine now rather than waiting for the cycle.
     *
     * Idempotent in the way that matters: the engine only issues a command
     * when the target has moved, so pressing this twice sends one setpoint.
     */
    runDispatch: useMutation({
      mutationFn: (params: { dry_run?: boolean } = {}) =>
        api.post<DispatchDecision[]>('/ems/dispatch-windows/run', {}, params),
      onSuccess: () => {
        invalidate()
        void queryClient.invalidateQueries({ queryKey: ['commands'] })
      },
    }),
  }
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------
/**
 * The node palette and every node type's parameter form.
 *
 * Cached hard: the catalogue only changes when the server is redeployed, and
 * the editor asks for it on every mount.
 */
export function useNodeTypes() {
  return useQuery({
    queryKey: keys.nodeTypes,
    queryFn: () => api.get<NodeTypeDef[]>('/workflows/node-types'),
    staleTime: 60 * 60 * 1000,
  })
}

export function useWorkflowCapacity() {
  return useQuery({
    queryKey: keys.workflowCapacity,
    queryFn: () => api.get<WorkflowCapacity>('/workflows/capacity'),
    refetchInterval: LIVE_REFETCH_MS,
  })
}

export function useWorkflowList(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: keys.workflows,
    queryFn: () => api.get<Page<Workflow>>('/workflows', { limit: 100 }),
    refetchInterval: LIVE_REFETCH_MS,
    ...options,
  })
}

export function useWorkflow(id: string | undefined) {
  return useQuery({
    queryKey: keys.workflow(id ?? ''),
    queryFn: () => api.get<Workflow>(`/workflows/${id}`),
    enabled: Boolean(id),
  })
}

export function useWorkflowMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['workflows'] })
  }

  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api.post<Workflow>('/workflows', body),
      onSuccess: invalidate,
    }),
    save: useMutation({
      mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) =>
        api.patch<Workflow>(`/workflows/${id}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/workflows/${id}`),
      onSuccess: invalidate,
    }),
  }
}

export function useWorkflowTemplates(enabled = true) {
  return useQuery({
    queryKey: ['workflows', 'templates'] as const,
    queryFn: () => api.get<WorkflowTemplate[]>('/workflows/templates'),
    enabled,
  })
}

export function useWorkflowTemplateMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['workflows', 'templates'] })
  }
  return {
    save: useMutation({
      mutationFn: (body: { name: string; description: string; graph: WorkflowGraph }) =>
        api.post<WorkflowTemplate>('/workflows/templates', body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api.delete(`/workflows/templates/${id}`),
      onSuccess: invalidate,
    }),
    instantiate: useMutation({
      mutationFn: ({ id, ...body }: { id: string; site_id: string | null; fresh_ids?: boolean }) =>
        api.post<TemplateInstantiation>(`/workflows/templates/${id}/instantiate`, body),
    }),
  }
}

export function useWorkflowRuns(params: Record<string, unknown>) {
  return useQuery({
    queryKey: keys.workflowRuns(params),
    queryFn: () => api.get<Page<WorkflowRun>>('/workflow-runs', params),
    refetchInterval: FAST_REFETCH_MS,
  })
}

/**
 * One run, polled quickly.
 *
 * Fast because this is what drives the canvas highlight while a graph is
 * executing, and a token can move through several nodes in a second.
 */
/** Poll fast enough to watch a run walk the canvas while it is moving. */
const RUN_LIVE_REFETCH_MS = 1000

export function useWorkflowRun(id: string | undefined, options?: { streaming?: boolean }) {
  const streaming = options?.streaming ?? false
  return useQuery({
    queryKey: keys.workflowRun(id ?? ''),
    queryFn: () => api.get<WorkflowRun>(`/workflow-runs/${id}`),
    enabled: Boolean(id),
    // With SSE connected the cache is fed by the stream and polling would be
    // duplicate traffic. Without it, an alive run still has to track nodes
    // that take only a couple of seconds each - a 5s poll shows the token
    // teleporting.
    refetchInterval: (query) => {
      if (streaming) return false
      const status = query.state.data?.status
      return status && ['pending', 'running', 'waiting', 'paused'].includes(status)
        ? RUN_LIVE_REFETCH_MS
        : FAST_REFETCH_MS
    },
  })
}

export function useRunLogs(
  id: string | undefined,
  params: Record<string, unknown>,
  options?: { live?: boolean; streaming?: boolean },
) {
  return useQuery({
    queryKey: keys.workflowRunLogs(id ?? '', params),
    queryFn: () => api.get<Page<WorkflowRunLog>>(`/workflow-runs/${id}/logs`, params),
    enabled: Boolean(id),
    refetchInterval: options?.streaming
      ? false
      : options?.live
        ? RUN_LIVE_REFETCH_MS
        : FAST_REFETCH_MS,
  })
}

export function useWorkflowRunMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['workflow-runs'] })
    void queryClient.invalidateQueries({ queryKey: ['workflows'] })
  }

  return {
    start: useMutation({
      mutationFn: ({
        workflowId,
        ...body
      }: {
        workflowId: string
        dry_run: boolean
        step_delay_seconds?: number
        start_paused?: boolean
      }) => api.post<WorkflowRun>(`/workflows/${workflowId}/runs`, body),
      onSuccess: invalidate,
    }),
    runNode: useMutation({
      mutationFn: ({
        workflowId,
        ...body
      }: {
        workflowId: string
        node_id: string
        dry_run?: boolean
      }) => api.post<WorkflowRun>(`/workflows/${workflowId}/run-node`, body),
      onSuccess: invalidate,
    }),
    stop: useMutation({
      mutationFn: (runId: string) =>
        api.post<WorkflowRun>(`/workflow-runs/${runId}/stop`, {}),
      onSuccess: invalidate,
    }),
    pause: useMutation({
      mutationFn: (runId: string) =>
        api.post<WorkflowRun>(`/workflow-runs/${runId}/pause`, {}),
      onSuccess: invalidate,
    }),
    resume: useMutation({
      mutationFn: (runId: string) =>
        api.post<WorkflowRun>(`/workflow-runs/${runId}/resume`, {}),
      onSuccess: invalidate,
    }),
    step: useMutation({
      mutationFn: (runId: string) =>
        api.post<WorkflowRun>(`/workflow-runs/${runId}/step`, {}),
      onSuccess: invalidate,
    }),
  }
}

// ---- connection debugger (integration page) --------------------------------
export function useIngressDebugStatus() {
  return useQuery({
    queryKey: ['integration', 'debug', 'status'] as const,
    queryFn: () => api.get<IngressDebugStatus>('/integration/debug'),
    refetchInterval: 5000,
  })
}

export function useIngressTraces({ node, enabled }: { node: string; enabled: boolean }) {
  return useQuery({
    queryKey: ['integration', 'debug', 'traces', node] as const,
    queryFn: () => api.get<IngressTrace[]>('/integration/debug/traces', { node: node || undefined, limit: 300 }),
    // Two seconds while capturing: a vendor is watching a device connect.
    refetchInterval: enabled ? 2000 : false,
  })
}

export function useIngressDiagnosis(node: string, enabled: boolean) {
  return useQuery({
    queryKey: ['integration', 'debug', 'diagnose', node] as const,
    queryFn: () => api.get<IngressDiagnosis>(`/integration/debug/diagnose/${encodeURIComponent(node)}`),
    enabled: Boolean(node) && enabled,
    refetchInterval: enabled ? 4000 : false,
  })
}

export function useIngressDebugMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['integration', 'debug'] })
  }
  return {
    enable: useMutation({
      mutationFn: (body: { minutes: number; node_filter: string; capture_payload: boolean }) =>
        api.put<IngressDebugStatus>('/integration/debug', body),
      onSuccess: invalidate,
    }),
    disable: useMutation({
      mutationFn: () => api.delete('/integration/debug'),
      onSuccess: invalidate,
    }),
    clear: useMutation({
      mutationFn: () => api.delete('/integration/debug/traces'),
      onSuccess: invalidate,
    }),
  }
}

// ---- energy management report ---------------------------------------------
export function useEnergyReport(params: ReportParams | null) {
  return useQuery({
    queryKey: ['ems', 'report', params] as const,
    queryFn: () => api.get<EnergyReport>('/ems/reports/energy', { ...(params ?? {}) }),
    enabled: params !== null,
    staleTime: 60_000,
  })
}

/**
 * Download the same report as a file. Goes through `fetch` directly because
 * the JSON client parses bodies; this one has to stay a blob. The anchor
 * trick is what every browser accepts for a "save as" without a popup.
 */
export async function downloadEnergyReport(params: ReportParams, format: 'pdf' | 'docx'): Promise<void> {
  const blob = await requestBlob('/ems/reports/energy/export', { ...params, format })
  const url = URL.createObjectURL(blob.body)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = blob.filename ?? `energy-report.${format}`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
  }
}
