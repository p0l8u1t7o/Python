/**
 * TanStack Query hooks。query key 集中在 `keys`，SSE（flowStream.ts）直接寫同一組 key 的快取。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { logActivity } from '@/lib/activity'

import { ApiError, api, request } from './api'
import type { BoardConfig, BoardData } from './board'
import { localiseList, localiseTrainers } from './catalogueLocale'
import type { OpenApiDocument } from '@/pages/integration/openapi'
import { localiseCatalogue } from './toolLocale'
import type { Language } from '@/i18n'
import type {
  ArchivePolicy,
  Asset,
  AuthUser,
  Capacity,
  CaptureClients,
  CaptureDownloadInfo,
  CommRule,
  Connection,
  ConnectionKind,
  ConnectionOpResult,
  DlDatasetVersion,
  DlDevices,
  DlProject,
  DlSample,
  DlShape,
  DlSuggestion,
  DlTrainerDef,
  DlTrainJob,
  EngineLock,
  ExpectStatus,
  Feature,
  Flow,
  FlowGraph,
  FlowRecipe,
  FlowStatsDb,
  FlowTemplate,
  GoldenBaseline,
  GoldenCase,
  GoldenList,
  ImageSource,
  IntegrationInfo,
  Page,
  PluginInventory,
  PreviewReport,
  RecipeCheckResult,
  RecipeImportCheck,
  RecipeImportResult,
  RegressResult,
  RetentionSettings,
  RetentionStatus,
  RetentionSweepResult,
  Role,
  RolePermissions,
  RunReport,
  ScratchImage,
  SourceKind,
  SpcAlertsResult,
  SpcResult,
  TcpResult,
  TemplateInstance,
  ToolCatalogue,
  TriggerRule,
} from './types'

export const keys = {
  toolTypes: ['tool-types'] as const,
  capacity: ['capacity'] as const,
  flows: ['flows'] as const,
  flow: (id: number) => ['flow', id] as const,
  recent: (id: number) => ['recent', id] as const,
  history: (id: number, params: Record<string, unknown>) => ['history', id, params] as const,
  stats: (id: number, hours: number) => ['flow-stats', id, hours] as const,
  spc: (id: number, output: string, chart: string, subgroup: number, hours: number) => ['flow-spc', id, output, chart, subgroup, hours] as const,
  spcAlerts: ['spc-alerts'] as const,
  sources: ['sources'] as const,
  sourceKinds: ['source-kinds'] as const,
  assets: (kind: string) => ['assets', kind] as const,
  lock: ['engine-lock'] as const,
  users: ['users'] as const,
  permissions: ['role-permissions'] as const,
  templates: ['templates'] as const,
  integration: ['integration-info'] as const,
  captureClients: ['capture-clients'] as const,
  captureDownload: ['capture-download'] as const,
  run: (id: string) => ['run', id] as const,
  recipes: (flowId: number) => ['recipes', flowId] as const,
  golden: (flowId: number) => ['golden', flowId] as const,
  goldenBaseline: (flowId: number) => ['golden-baseline', flowId] as const,
  connections: ['connections'] as const,
  connectionKinds: ['connection-kinds'] as const,
}

export interface RecentRuns {
  items: RunReport[]
  stats: Flow['stats']
  continuous: boolean
}

// ---- 工具目錄 / 容量 ----
export function useToolTypes() {
  // 後端目錄是英文（唯一事實來源）；中文介面在這裡疊字典，其他頁面不必知道有這回事。
  const { i18n } = useTranslation()
  const language = i18n.language as Language
  return useQuery({
    queryKey: [...keys.toolTypes, language],
    queryFn: () => api.get<ToolCatalogue>('/vision/tool-types'),
    select: (data) => localiseCatalogue(data, language),
    staleTime: 5 * 60_000,
  })
}

/** 資料保留（管理員）：設定、用量與上次整理；存檔與「立即整理」後把新狀態寫回快取。 */
export function useRetention(enabled = true) {
  return useQuery({
    queryKey: ['retention'],
    queryFn: () => api.get<RetentionStatus>('/vision/retention'),
    enabled,
  })
}

export function useSaveRetention() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<RetentionSettings>) => api.patch<RetentionStatus>('/vision/retention', body),
    onSuccess: (data) => client.setQueryData(['retention'], data),
  })
}

export function useSweepRetention() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ result: RetentionSweepResult; status: RetentionStatus }>('/vision/retention/sweep', {}),
    onSuccess: (data) => {
      client.setQueryData(['retention'], data.status)
      void client.invalidateQueries({ queryKey: ['audit'] })
    },
  })
}

export function useCapacity(intervalMs = 5000) {
  return useQuery({
    queryKey: keys.capacity,
    queryFn: () => api.get<Capacity>('/vision/capacity'),
    refetchInterval: intervalMs,
    refetchOnWindowFocus: true,  // 多客戶端：切回來就看最新（隱藏時 TanStack 本來就會暫停輪詢）
  })
}

// ---- 流程 ----
export function useFlows(q = '', mine = false) {
  return useQuery({
    queryKey: [...keys.flows, q, mine],
    queryFn: () => api.get<Page<Flow>>('/vision/flows', { q, limit: 200, mine: mine ? 'true' : '' }),
    refetchOnWindowFocus: true,  // 別台電腦可能新增或改了流程
  })
}

export function useFlow(id: number | null) {
  return useQuery({
    queryKey: keys.flow(id ?? 0),
    queryFn: () => api.get<Flow>(`/vision/flows/${id}`),
    enabled: id !== null,
  })
}

export interface FlowPatch {
  name?: string
  description?: string
  graph?: FlowGraph
  is_enabled?: boolean
  continuous_interval_ms?: number
  /** 參數卡頁「標記為已教導」 */
  commissioned?: boolean
  /** 影像封存策略（工程師才能改） */
  archive_policy?: Partial<ArchivePolicy>
  /** 現場看板設定（工程師才能改） */
  board?: BoardConfig
  comm?: CommRule[]
}

export function useFlowMutations() {
  const client = useQueryClient()
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: keys.flows })
    void client.invalidateQueries({ queryKey: keys.capacity })
  }
  const create = useMutation({
    mutationFn: (body: { name: string; description?: string; graph?: FlowGraph }) =>
      api.post<Flow>('/vision/flows', body),
    onSuccess: invalidate,
  })
  const patch = useMutation({
    mutationFn: ({ id, ...body }: FlowPatch & { id: number }) =>
      api.patch<Flow>(`/vision/flows/${id}`, body),
    onSuccess: (flow) => {
      client.setQueryData(keys.flow(flow.id), flow)
      invalidate()
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/vision/flows/${id}`),
    onSuccess: invalidate,
  })
  const duplicate = useMutation({
    mutationFn: (id: number) => api.post<Flow>(`/vision/flows/${id}/duplicate`),
    onSuccess: invalidate,
  })
  return { create, patch, remove, duplicate }
}

export function useRecentRuns(flowId: number | null, limit = 8) {
  return useQuery({
    queryKey: keys.recent(flowId ?? 0),
    queryFn: () => api.get<RecentRuns>(`/vision/flows/${flowId}/recent`, { limit }),
    enabled: flowId !== null,
    // SSE 會即時更新；這裡只是初始載入與斷線保險。
    staleTime: 30_000,
  })
}

export function useRunHistory(flowId: number | null, params: { status?: string; limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: keys.history(flowId ?? 0, params),
    queryFn: () => api.get<Page<RunReport>>(`/vision/flows/${flowId}/runs`, params),
    enabled: flowId !== null,
  })
}

export function useFlowStats(flowId: number | null, hours = 24) {
  return useQuery({
    queryKey: keys.stats(flowId ?? 0, hours),
    queryFn: () => api.get<FlowStatsDb>(`/vision/flows/${flowId}/stats`, { hours }),
    enabled: flowId !== null,
  })
}

/** 量測值 SPC（WP-14）：具名輸出的時間序列＋管制界限／Cp、Cpk／Nelson 判異；output 空字串＝伺服端選第一個。 */
export function useFlowSpc(flowId: number | null, opts: { output: string; chart: 'imr' | 'xbar_r'; subgroup: number; hours: number }) {
  return useQuery({
    queryKey: keys.spc(flowId ?? 0, opts.output, opts.chart, opts.subgroup, opts.hours),
    queryFn: () => api.get<SpcResult>(`/vision/flows/${flowId}/spc`, { output: opts.output, chart: opts.chart, subgroup: opts.subgroup, hours: opts.hours, limit: 1000 }),
    enabled: flowId !== null,
    refetchInterval: 30_000,
  })
}

/** 總覽頁的量測值告警（伺服端快取 30 秒）。 */
export function useSpcAlerts() {
  return useQuery({ queryKey: keys.spcAlerts, queryFn: () => api.get<SpcAlertsResult>('/vision/spc/alerts'), refetchInterval: 60_000 })
}

// ---- 執行 ----
export interface RunFlowArgs {
  flowId: number
  /** 附影像檔 → multipart；沒有 → JSON */
  file?: File | null
  context?: Record<string, unknown>
  wait?: boolean
  /** 配方名稱或 id；空 = 預設配方 */
  recipe?: string | null
}

/** 執行結果的一行細節（錯誤或沒過的節點），給操作軌跡用。 */
function reportDetail(report: RunReport): string {
  if (report.error) return report.error
  return Object.entries(report.nodes ?? {}).filter(([, n]) => n.status !== 'ok').slice(0, 4).map(([id, n]) => `${id}: ${n.status}${n.message ? ` (${n.message})` : ''}`).join('; ')
}

export function useRunFlow() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ flowId, file, context, wait = true, recipe }: RunFlowArgs) => {
      const query = { wait: wait ? 1 : 0, include_images: 1, trigger: 'ui' }
      if (file) {
        const form = new FormData()
        form.append('image', file)
        if (context) form.append('context', JSON.stringify(context))
        if (recipe) form.append('recipe', recipe)
        return api.postForm<RunReport>(`/vision/flows/${flowId}/run`, form, query)
      }
      return api.post<RunReport>(`/vision/flows/${flowId}/run`, { context: context ?? null, wait, ...(recipe ? { recipe } : {}) }, query)
    },
    onSuccess: (report, args) => {
      logActivity('run', `run flow ${args.flowId}: ${report.status}`, reportDetail(report))
      void client.invalidateQueries({ queryKey: keys.capacity })
    },
  })
}

export interface PreviewArgs {
  flowId: number
  graph: FlowGraph
  context?: Record<string, unknown>
  reuse_image_ref?: string | null
  /** 只跑到該步驟與其祖先（工具頁） */
  until_node?: string | null
  /** 回傳直方圖／統計（工具頁） */
  analysis?: boolean
  /** 配方名稱或 id（伺服器端疊覆寫） */
  recipe?: string | null
  signal?: AbortSignal
}

export async function previewFlow({ flowId, graph, context, reuse_image_ref, until_node, analysis, recipe, signal }: PreviewArgs): Promise<PreviewReport> {
  const send = (ref: string | null) =>
    request<PreviewReport>(`/vision/flows/${flowId}/preview`, {
      method: 'POST',
      body: {
        graph,
        context: context ?? null,
        reuse_image_ref: ref,
        ...(until_node ? { until_node } : {}),
        ...(analysis ? { analysis: true } : {}),
        ...(recipe ? { recipe } : {}),
      },
      signal,
    })
  try {
    return await send(reuse_image_ref ?? null)
  } catch (error) {
    // 「用上次影像重跑」的影像已被快取淘汰（404 image_gone）：改用來源重新取像，不要卡在錯誤上
    if (reuse_image_ref && error instanceof ApiError && error.code === 'image_gone') return send(null)
    throw error
  }
}

export function usePreviewFlow() {
  return useMutation({ mutationFn: previewFlow, onSuccess: (report, args) => logActivity('run', `preview flow ${args.flowId}: ${report.status}`, reportDetail(report)) })
}

/** 暫存影像：只進快取不進影像來源庫；之後試跑帶 reuse_image_ref。 */
export function useScratchImage() {
  return useMutation({
    mutationFn: ({ flowId, file }: { flowId: number; file: File }) => {
      const form = new FormData()
      form.append('image', file)
      return api.postForm<ScratchImage>(`/vision/flows/${flowId}/scratch-image`, form)
    },
  })
}

/** 重置：清除記憶體內的執行紀錄與統計（SSE 會再收到 cleared）。 */
export function useClearRecent() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (flowId: number) => api.delete(`/vision/flows/${flowId}/recent`),
    onSuccess: (_data, flowId) => {
      client.setQueryData<RecentRuns>(keys.recent(flowId), (old) => ({ items: [], stats: emptyStats(), continuous: old?.continuous ?? false }))
      client.setQueryData<Flow>(keys.flow(flowId), (old) => (old ? { ...old, stats: emptyStats() } : old))
    },
  })
}

export function emptyStats(): Flow['stats'] {
  return { runs: 0, ok: 0, ng: 0, failed: 0, avg_ms: 0, max_ms: 0, last_ms: 0, last_status: '', last_run_id: '', last_finished_at: 0 }
}

export function useContinuous() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ flowId, running }: { flowId: number; running: boolean }) =>
      api.post<{ running: boolean }>(`/vision/flows/${flowId}/continuous`, { running }),
    onSuccess: (_data, { flowId }) => {
      void client.invalidateQueries({ queryKey: keys.flow(flowId) })
      void client.invalidateQueries({ queryKey: keys.flows })
      void client.invalidateQueries({ queryKey: keys.capacity })
    },
  })
}

// ---- 影像來源 ----
/** `live`：清單含擷取端相機時每 5 秒重抓（顯示 fps／最近影格／離線）。 */
export function useSources(live = false) {
  return useQuery({
    queryKey: keys.sources,
    queryFn: () => api.get<{ items: ImageSource[] }>('/vision/sources'),
    refetchInterval: (query) => (live && query.state.data?.items.some((s) => s.kind === 'capture') ? 5000 : false),
  })
}

export function useSourceKinds() {
  // 後端目錄是英文（唯一事實來源）；中文介面疊字典，存進資料庫的 kind 仍是英文。
  const { i18n } = useTranslation()
  const language = i18n.language as Language
  return useQuery({
    queryKey: [...keys.sourceKinds, language],
    queryFn: () => api.get<{ items: SourceKind[] } | SourceKind[]>('/vision/sources/kinds'),
    select: (data) => localiseList('sourceKinds', Array.isArray(data) ? data : data.items, (k) => k.kind, language),
    staleTime: Infinity,
  })
}

export interface SourceBody {
  name: string
  kind: string
  config: Record<string, unknown>
  is_enabled: boolean
  group?: string
}

export function useSourceMutations() {
  const client = useQueryClient()
  const invalidate = () => void client.invalidateQueries({ queryKey: keys.sources })
  const create = useMutation({
    mutationFn: (body: SourceBody) => api.post<ImageSource>('/vision/sources', body),
    onSuccess: invalidate,
  })
  const patch = useMutation({
    mutationFn: ({ id, ...body }: Partial<SourceBody> & { id: number }) =>
      api.patch<ImageSource>(`/vision/sources/${id}`, body),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/vision/sources/${id}`),
    onSuccess: invalidate,
  })
  const push = useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) => {
      const form = new FormData()
      form.append('image', file)
      return api.postForm<{ ok: boolean }>(`/vision/sources/${id}/push`, form)
    },
  })
  return { create, patch, remove, push }
}

// ---- 擷取端（apps/vision/capture/api.py） ----
export function useCaptureClients(enabled = true, intervalMs = 5000) {
  return useQuery({
    queryKey: keys.captureClients,
    queryFn: () => api.get<CaptureClients>('/vision/capture/clients'),
    enabled,
    refetchInterval: enabled ? intervalMs : false,
  })
}

export function useCaptureDownloadInfo() {
  return useQuery({
    queryKey: keys.captureDownload,
    queryFn: () => api.get<CaptureDownloadInfo>('/vision/capture/download/info'),
    staleTime: 60_000,
  })
}

export function useCaptureMutations() {
  const client = useQueryClient()
  const stream = useMutation({
    mutationFn: ({ client: name, channel, enabled, max_fps }: { client: string; channel: string; enabled: boolean; max_fps?: number }) =>
      api.post<{ ok: boolean; streaming: boolean }>(`/vision/capture/clients/${encodeURIComponent(name)}/channels/${encodeURIComponent(channel)}/stream`, { enabled, max_fps }),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.captureClients }),
  })
  return { stream }
}

// ---- 資源群組（影像來源庫／資產庫共用） ----
export interface ResourceGroup {
  id: number
  name: string
  count: number
}

export function useGroups(kind: 'source' | 'asset', enabled = true) {
  return useQuery({
    queryKey: ['groups', kind],
    queryFn: () => api.get<{ items: ResourceGroup[] }>('/vision/groups', { kind }),
    select: (data) => data.items,
    enabled,
  })
}

export function useGroupMutations(kind: 'source' | 'asset') {
  const client = useQueryClient()
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ['groups', kind] })
    // 改名／刪除會連動項目的 group 字串
    void client.invalidateQueries({ queryKey: kind === 'source' ? keys.sources : ['assets'] })
  }
  const createGroup = useMutation({
    mutationFn: (name: string) => api.post<ResourceGroup>('/vision/groups', { kind, name }),
    onSuccess: invalidate,
  })
  const renameGroup = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => api.patch<ResourceGroup>(`/vision/groups/${id}`, { name }),
    onSuccess: invalidate,
  })
  const removeGroup = useMutation({
    mutationFn: ({ id, deleteItems }: { id: number; deleteItems: boolean }) =>
      request<void>(`/vision/groups/${id}`, { method: 'DELETE', query: { delete_items: deleteItems ? '1' : '' } }),
    onSuccess: invalidate,
  })
  return { createGroup, renameGroup, removeGroup }
}

// ---- 資產 ----
export function useAssets(kind = '') {
  return useQuery({
    queryKey: keys.assets(kind),
    queryFn: () => api.get<{ items: Asset[] }>('/vision/assets', { kind }),
  })
}

export function useAssetMutations() {
  const client = useQueryClient()
  const invalidate = () => void client.invalidateQueries({ queryKey: ['assets'] })
  const uploadFile = useMutation({
    mutationFn: ({ file, kind, name, group }: { file: File; kind: Asset['kind']; name?: string; group?: string }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('kind', kind)
      form.append('name', name || file.name)
      form.append('group', group || '')
      return api.postForm<Asset>('/vision/assets', form)
    },
    onSuccess: invalidate,
  })
  const patch = useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; group?: string }) => api.patch<Asset>(`/vision/assets/${id}`, body),
    onSuccess: invalidate,
  })
  const fromImage = useMutation({
    mutationFn: (body: { ref: string; region?: unknown; name?: string }) =>
      api.post<Asset>('/vision/assets/from-image', body),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/vision/assets/${id}`),
    onSuccess: invalidate,
  })
  return { uploadFile, fromImage, patch, remove }
}

// ---- 引擎鎖定 ----
/** 鎖定狀態：AuthProvider 以 me.lock 預填、SSE lock 事件直接寫快取，這裡每 30 秒輪詢保險。 */
export function useEngineLock(enabled = true) {
  return useQuery({
    queryKey: keys.lock,
    queryFn: () => api.get<EngineLock>('/vision/lock'),
    // 不輪詢：初值來自 /auth/me，變動靠 SSE 的 lock 事件，斷線重連時登記表會讓它失效重抓
    refetchInterval: false,
    enabled,
  })
}

export function useLockMutations() {
  const client = useQueryClient()
  const apply = (lock: EngineLock) => client.setQueryData(keys.lock, lock)
  const acquire = useMutation({
    mutationFn: (body: { reason?: string; ttl_s?: number | null }) => api.post<EngineLock>('/vision/lock', body),
    onSuccess: apply,
  })
  const release = useMutation({
    mutationFn: () => api.delete<EngineLock>('/vision/lock'),
    onSuccess: apply,
  })
  return { acquire, release }
}

// ---- 使用者（管理員） ----
export function useUsers(enabled = true) {
  return useQuery({
    queryKey: keys.users,
    queryFn: () => api.get<{ items: AuthUser[] }>('/users'),
    enabled,
  })
}

export interface UserPatch {
  password?: string
  role?: Role
  is_staff?: boolean
  is_active?: boolean
  display_name?: string
}

export function useUserMutations() {
  const client = useQueryClient()
  const invalidate = () => void client.invalidateQueries({ queryKey: keys.users })
  const create = useMutation({
    mutationFn: (body: { username: string; password: string; role: Role; display_name: string }) => api.post<AuthUser>('/users', body),
    onSuccess: invalidate,
  })
  const patch = useMutation({
    mutationFn: ({ id, ...body }: UserPatch & { id: number }) => api.patch<AuthUser>(`/users/${id}`, body),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/users/${id}`),
    onSuccess: invalidate,
  })
  return { create, patch, remove }
}

// ---- 角色權限（管理員勾選工程師與操作員能用哪些功能） ----
export function useRolePermissions(enabled = true) {
  return useQuery({
    queryKey: keys.permissions,
    queryFn: () => api.get<RolePermissions>('/users/permissions'),
    enabled,
  })
}

export function useRolePermissionMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { role: string; features: Feature[] }) => api.patch<{ role: string; features: Feature[] }>('/users/permissions', body),
    // 改到自己這個角色時側欄也要跟著變，所以呼叫端會再 auth.refresh() 一次
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.permissions }),
  })
}

/** 改自己的顯示名稱（帳號名稱與角色是管理員的事）；呼叫端成功後 auth.refresh() 讓側欄與選單跟著變。 */
export function useUpdateProfile() {
  return useMutation({
    mutationFn: (body: { display_name: string }) => api.patch<AuthUser>('/auth/profile', body),
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { old_password: string; new_password: string }) => api.post<{ ok: boolean }>('/auth/password', body),
  })
}

// ---- 範本庫 ----
export function useTemplates(enabled = true) {
  const { i18n } = useTranslation()
  const language = i18n.language as Language
  return useQuery({
    queryKey: [...keys.templates, language],
    queryFn: () => api.get<{ items: FlowTemplate[]; can_manage: boolean }>('/vision/templates'),
    // 內建範本才有對照；自建範本是使用者自己取的名字，原樣顯示（id 是 builtin:<key>）
    select: (data) => ({ ...data, items: localiseList('templates', data.items, (t) => t.id.replace(/^builtin:/, ''), language) }),
    enabled,
  })
}

export function useTemplateMutations() {
  const client = useQueryClient()
  const invalidate = () => void client.invalidateQueries({ queryKey: keys.templates })
  const create = useMutation({
    mutationFn: (body: { name: string; description: string; category: string; graph: FlowGraph }) => api.post<FlowTemplate>('/vision/templates', body),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/vision/templates/${encodeURIComponent(id)}`),
    onSuccess: invalidate,
  })
  const instantiate = useMutation({
    mutationFn: ({ id, source_id, prefix, use_samples }: { id: string; source_id?: number | null; prefix?: string; use_samples?: boolean }) =>
      api.post<TemplateInstance>(`/vision/templates/${encodeURIComponent(id)}/instantiate`, { source_id: source_id ?? null, prefix: prefix ?? '', use_samples: use_samples ?? true }),
  })
  return { create, remove, instantiate }
}

/** 單一 run（記憶體 recent 內或資料庫）；不在了會 404 run_not_found。 */
export function fetchRun(runId: string): Promise<RunReport> {
  return api.get<RunReport>(`/vision/runs/${encodeURIComponent(runId)}`)
}

// ---- 整合頁 ----
export function useIntegrationInfo() {
  return useQuery({
    queryKey: keys.integration,
    queryFn: () => api.get<IntegrationInfo>('/vision/integration/info'),
    refetchInterval: 15_000,
  })
}

export function useTcpCommand() {
  return useMutation({
    mutationFn: ({ command, timeout_s }: { command: string; timeout_s?: number }) => api.post<TcpResult>('/vision/integration/tcp', { command, timeout_s: timeout_s ?? 10 }),
  })
}

// ---- 看板（設定＋最新 run＋今日良率一次拿齊；整合端自建 UI 也用同一個端點） ----
export function useBoard(flowId: number | null) {
  return useQuery({
    queryKey: ['board', flowId] as const,
    queryFn: () => api.get<BoardData>(`/vision/flows/${flowId}/board`),
    enabled: flowId !== null,
    refetchInterval: 15000,
  })
}

// ---- 流程變數（跨執行的狀態；記憶體為正本，API 是 write-through） ----
export interface FlowVariables {
  flow_id: number
  items: Record<string, unknown>
  station: Record<string, unknown>
}

export function useFlowVariables(flowId: number | null) {
  return useQuery({
    queryKey: ['flow-variables', flowId] as const,
    queryFn: () => api.get<FlowVariables>(`/vision/flows/${flowId}/variables`),
    enabled: flowId !== null,
    refetchInterval: 5000,
  })
}

// ---- 配方（FlowRecipe） ----
export function useRecipes(flowId: number | null) {
  return useQuery({
    queryKey: keys.recipes(flowId ?? 0),
    queryFn: () => api.get<{ items: FlowRecipe[] }>(`/vision/flows/${flowId}/recipes`),
    enabled: flowId !== null,
  })
}

export interface RecipeBody {
  name: string
  description?: string
  param_overrides?: Record<string, Record<string, unknown>>
  is_default?: boolean
}

export function useRecipeMutations(flowId: number) {
  const client = useQueryClient()
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: keys.recipes(flowId) })
    void client.invalidateQueries({ queryKey: keys.flows })
    void client.invalidateQueries({ queryKey: keys.flow(flowId) })
  }
  const create = useMutation({
    mutationFn: (body: RecipeBody) => api.post<FlowRecipe>(`/vision/flows/${flowId}/recipes`, body),
    onSuccess: invalidate,
  })
  const patch = useMutation({
    mutationFn: ({ id, ...body }: Partial<RecipeBody> & { id: number }) => api.patch<FlowRecipe>(`/vision/flows/${flowId}/recipes/${id}`, body),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/vision/flows/${flowId}/recipes/${id}`),
    onSuccess: invalidate,
  })
  return { create, patch, remove }
}

/** 儲存範圍 Check List：存檔前逐項檢查覆寫（不寫入）。include_all=true 時流程所有宣告參數也列出（覆寫沒提到的以圖值列為 unchanged，帶 teach／kind）。 */
export function checkRecipe(flowId: number, param_overrides: Record<string, Record<string, unknown>>, options: { include_all?: boolean; signal?: AbortSignal } = {}): Promise<RecipeCheckResult> {
  return request<RecipeCheckResult>(`/vision/flows/${flowId}/recipes/check`, { method: 'POST', body: { param_overrides, include_all: options.include_all ?? false }, signal: options.signal })
}

/** 匯入合理化檢查（multipart file）與匯入（只寫入 accept 的項目）。 */
export function useRecipeImport(flowId: number) {
  const client = useQueryClient()
  const check = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.postForm<RecipeImportCheck>(`/vision/flows/${flowId}/recipes/import/check`, form)
    },
  })
  const run = useMutation({
    mutationFn: (body: { doc: Record<string, unknown>; accept: string[]; name?: string; is_default?: boolean }) => api.post<RecipeImportResult>(`/vision/flows/${flowId}/recipes/import`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.recipes(flowId) })
      void client.invalidateQueries({ queryKey: keys.flows })
      void client.invalidateQueries({ queryKey: keys.flow(flowId) })
    },
  })
  return { check, run }
}

/** 把配方的覆寫疊到圖上（與後端 apply_recipe 相同語意；不動原圖）。 */
export function applyOverrides(graph: FlowGraph, overrides: Record<string, Record<string, unknown>> | null | undefined): FlowGraph {
  if (!overrides || Object.keys(overrides).length === 0) return graph
  return {
    ...graph,
    nodes: graph.nodes.map((n) => {
      const patch = overrides[n.id]
      return patch && typeof patch === 'object' ? { ...n, params: { ...(n.params ?? {}), ...patch } } : n
    }),
  }
}

// ---- Golden Set ----
export function useGolden(flowId: number | null) {
  return useQuery({
    queryKey: keys.golden(flowId ?? 0),
    queryFn: () => api.get<GoldenList>(`/vision/flows/${flowId}/golden`),
    enabled: flowId !== null,
  })
}

export function useGoldenBaseline(flowId: number | null) {
  return useQuery({
    queryKey: keys.goldenBaseline(flowId ?? 0),
    queryFn: () => api.get<{ baseline: GoldenBaseline | null; flow_version: number; case_count: number }>(`/vision/flows/${flowId}/golden/baseline`),
    enabled: flowId !== null,
  })
}

export interface GoldenFromBatchItem {
  image_ref: string
  name?: string
  expect_status?: ExpectStatus
  expect_outputs?: Record<string, unknown>
  note?: string
}

export function useGoldenMutations(flowId: number) {
  const client = useQueryClient()
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: keys.golden(flowId) })
    void client.invalidateQueries({ queryKey: keys.goldenBaseline(flowId) })
  }
  const upload = useMutation({
    mutationFn: ({ files, expect_status, note }: { files: File[]; expect_status: ExpectStatus; note?: string }) => {
      const form = new FormData()
      for (const f of files) form.append('images', f)
      form.append('expect_status', expect_status)
      if (note) form.append('note', note)
      return api.postForm<{ items: GoldenCase[]; created: number }>(`/vision/flows/${flowId}/golden`, form)
    },
    onSuccess: invalidate,
  })
  const fromBatch = useMutation({
    mutationFn: (items: GoldenFromBatchItem[]) => api.post<{ items: GoldenCase[]; created: number }>(`/vision/flows/${flowId}/golden`, { from_batch: items }),
    onSuccess: invalidate,
  })
  const patch = useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; expect_status?: ExpectStatus; expect_outputs?: Record<string, unknown>; note?: string }) =>
      api.patch<GoldenCase>(`/vision/flows/${flowId}/golden/${id}`, body),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/vision/flows/${flowId}/golden/${id}`),
    onSuccess: invalidate,
  })
  const regress = useMutation({
    mutationFn: (body: { graph?: FlowGraph | null; save_baseline?: boolean; fail_under?: number | null }) =>
      api.post<RegressResult>(`/vision/flows/${flowId}/regress`, { graph: body.graph ?? null, save_baseline: Boolean(body.save_baseline), fail_under: body.fail_under ?? null }),
    onSuccess: invalidate,
  })
  return { upload, fromBatch, patch, remove, regress }
}

// ---- 匯出／匯入 ----
export function useImportFlow() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ file, source_id }: { file: File; source_id?: number | null }) => {
      const form = new FormData()
      form.append('file', file)
      if (source_id) form.append('source_id', String(source_id))
      return api.postForm<{ flow: Flow; created: boolean }>('/vision/flows/import', form)
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.flows }),
  })
}

// ---- 連線（Modbus TCP／上位機） ----
export function useConnections(enabled = true) {
  return useQuery({
    queryKey: keys.connections,
    queryFn: () => api.get<{ items: Connection[] }>('/vision/connections'),
    enabled,
  })
}

/** 站台接收規則：TCP 指令埠收到「不是指令」的一行時比對這一張表。 */
export function useStationRules(enabled = true) {
  return useQuery({
    queryKey: ['station-rules'],
    queryFn: () => api.get<{ items: TriggerRule[] }>('/vision/integration/rules'),
    enabled,
  })
}

export function useSaveStationRules() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (rules: TriggerRule[]) => api.patch<{ items: TriggerRule[] }>('/vision/integration/rules', { rules }),
    onSuccess: (data) => client.setQueryData(['station-rules'], data),
  })
}


export function useConnectionKinds() {
  const { i18n } = useTranslation()
  const language = i18n.language as Language
  return useQuery({
    queryKey: [...keys.connectionKinds, language],
    queryFn: () => api.get<{ items: ConnectionKind[] }>('/vision/connections/kinds'),
    select: (data) => localiseList('connectionKinds', data.items, (k) => k.kind, language),
    staleTime: Infinity,
  })
}

export interface ConnectionBody {
  name: string
  kind: string
  config: Record<string, unknown>
  is_enabled: boolean
}

export function useConnectionMutations() {
  const client = useQueryClient()
  const invalidate = () => void client.invalidateQueries({ queryKey: keys.connections })
  const create = useMutation({
    mutationFn: (body: ConnectionBody) => api.post<Connection>('/vision/connections', body),
    onSuccess: invalidate,
  })
  const patch = useMutation({
    mutationFn: ({ id, ...body }: Partial<ConnectionBody> & { id: number }) => api.patch<Connection>(`/vision/connections/${id}`, body),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/vision/connections/${id}`),
    onSuccess: invalidate,
  })
  const test = useMutation({
    mutationFn: (id: number) => api.post<ConnectionOpResult>(`/vision/connections/${id}/test`),
    onSuccess: invalidate,
  })
  const write = useMutation({
    mutationFn: ({ id, values, timeout_s }: { id: number; values: Record<string, unknown>; timeout_s?: number | null }) =>
      api.post<ConnectionOpResult>(`/vision/connections/${id}/write`, { values, timeout_s: timeout_s ?? null }),
    onSuccess: invalidate,
  })
  return { create, patch, remove, test, write }
}

export function fetchConnectionState(id: number, addresses = ''): Promise<ConnectionOpResult> {
  return api.get<ConnectionOpResult>(`/vision/connections/${id}/state`, { addresses })
}

// ---- OpenAPI 描述（Swagger 風格的 API 總覽讀它） ----
export function useOpenApi() {
  return useQuery({
    queryKey: ['openapi'],
    queryFn: () => api.get<OpenApiDocument>('/openapi.json'),
    staleTime: 10 * 60_000,
  })
}

// ---- 資料夾外掛（/vision/plugins） ----
export function usePlugins(enabled = true) {
  return useQuery({
    queryKey: ['plugins'],
    queryFn: () => api.get<PluginInventory>('/vision/plugins'),
    enabled,
  })
}

export function useRescanPlugins() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<PluginInventory>('/vision/plugins/rescan', {}),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['plugins'] })
      // 新掛的工具／來源／連線種類要立刻出現在各自的目錄
      void client.invalidateQueries({ queryKey: keys.toolTypes })
      void client.invalidateQueries({ queryKey: keys.sourceKinds })
      void client.invalidateQueries({ queryKey: keys.connectionKinds })
      void client.invalidateQueries({ queryKey: ['dl', 'trainers'] })
    },
  })
}

// ---- 深度學習教導（/vision/dl） ----
export function useDlTrainers() {
  const { i18n } = useTranslation()
  const language = i18n.language as Language
  return useQuery({
    queryKey: ['dl', 'trainers', language],
    queryFn: () => api.get<{ items: DlTrainerDef[] }>('/vision/dl/trainers'),
    select: (data) => localiseTrainers(data.items, language),
    staleTime: 5 * 60_000,
  })
}

export function useDlDevices() {
  return useQuery({
    queryKey: ['dl', 'devices'],
    queryFn: () => api.get<DlDevices>('/vision/dl/devices'),
    staleTime: 30_000,
  })
}

export function useDlProjects() {
  return useQuery({
    queryKey: ['dl', 'projects'],
    queryFn: () => api.get<{ items: DlProject[] }>('/vision/dl/projects'),
    select: (data) => data.items,
  })
}

export function useDlProject(id: number | null) {
  return useQuery({
    queryKey: ['dl', 'project', id],
    queryFn: () => api.get<DlProject>(`/vision/dl/projects/${id}`),
    enabled: id !== null,
  })
}

export function useDlSamples(projectId: number | null) {
  return useQuery({
    queryKey: ['dl', 'samples', projectId],
    queryFn: () => api.get<{ items: DlSample[] }>(`/vision/dl/projects/${projectId}/samples`),
    select: (data) => data.items,
    enabled: projectId !== null,
  })
}

export function useDlVersions(projectId: number | null) {
  return useQuery({
    queryKey: ['dl', 'versions', projectId],
    queryFn: () => api.get<{ items: DlDatasetVersion[] }>(`/vision/dl/projects/${projectId}/versions`),
    select: (data) => data.items,
    enabled: projectId !== null,
  })
}

/** 訓練狀態輪詢：訓練中每 700ms、閒置放慢到 5 秒。 */
export function useDlTrainStatus(active = true) {
  return useQuery({
    queryKey: ['dl', 'train-status'],
    queryFn: () => api.get<{ job: DlTrainJob | null }>('/vision/dl/train/status'),
    select: (data) => data.job,
    refetchInterval: (query) => (active ? (query.state.data?.job?.status === 'running' ? 700 : 5000) : false),
  })
}

export function useDlMutations() {
  const client = useQueryClient()
  const invalidateProjects = () => void client.invalidateQueries({ queryKey: ['dl', 'projects'] })
  const invalidateProject = (id: number) => {
    void client.invalidateQueries({ queryKey: ['dl', 'project', id] })
    void client.invalidateQueries({ queryKey: ['dl', 'samples', id] })
    invalidateProjects()
  }
  const createProject = useMutation({
    mutationFn: (body: { name: string; trainer_kind: string; classes: string[]; description?: string }) =>
      api.post<DlProject>('/vision/dl/projects', body),
    onSuccess: invalidateProjects,
  })
  const patchProject = useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; classes?: string[]; params?: Record<string, unknown>; description?: string }) =>
      api.patch<DlProject>(`/vision/dl/projects/${id}`, body),
    onSuccess: (_, v) => invalidateProject(v.id),
  })
  const removeProject = useMutation({
    mutationFn: (id: number) => api.delete(`/vision/dl/projects/${id}`),
    onSuccess: invalidateProjects,
  })
  const uploadSamples = useMutation({
    mutationFn: ({ projectId, files, label }: { projectId: number; files: File[]; label?: string }) => {
      const form = new FormData()
      for (const f of files) form.append('files', f)
      form.append('label', label || '')
      return api.postForm<{ items: DlSample[]; skipped: number; duplicates: number }>(`/vision/dl/projects/${projectId}/samples`, form)
    },
    onSuccess: (_, v) => invalidateProject(v.projectId),
  })
  const fromSource = useMutation({
    mutationFn: ({ projectId, source_id, count, label }: { projectId: number; source_id: number; count: number; label?: string }) =>
      api.post<{ items: DlSample[]; duplicates: number }>(`/vision/dl/projects/${projectId}/samples/from-source`, { source_id, count, label: label || '' }),
    onSuccess: (_, v) => invalidateProject(v.projectId),
  })
  const setLabel = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string; projectId: number }) =>
      api.patch<DlSample>(`/vision/dl/samples/${id}`, { label }),
    onSuccess: (_, v) => invalidateProject(v.projectId),
  })
  const setShapes = useMutation({
    mutationFn: ({ id, shapes }: { id: string; shapes: DlShape[]; projectId: number }) =>
      api.patch<DlSample>(`/vision/dl/samples/${id}`, { shapes }),
    onSuccess: (_, v) => invalidateProject(v.projectId),
  })
  const removeSample = useMutation({
    mutationFn: ({ id }: { id: string; projectId: number }) => api.delete(`/vision/dl/samples/${id}`),
    onSuccess: (_, v) => invalidateProject(v.projectId),
  })
  const setSplit = useMutation({
    mutationFn: ({ id, split }: { id: string; split: DlSample['split']; projectId: number }) =>
      api.patch<DlSample>(`/vision/dl/samples/${id}`, { split }),
    onSuccess: (_, v) => invalidateProject(v.projectId),
  })
  const autoSplit = useMutation({
    mutationFn: ({ projectId, val, test }: { projectId: number; val: number; test: number }) =>
      api.post<{ train: number; val: number; test: number }>(`/vision/dl/projects/${projectId}/split`, { val, test }),
    onSuccess: (_, v) => invalidateProject(v.projectId),
  })
  const freezeVersion = useMutation({
    mutationFn: ({ projectId, name, note }: { projectId: number; name?: string; note?: string }) =>
      api.post<DlDatasetVersion>(`/vision/dl/projects/${projectId}/versions`, { name, note }),
    onSuccess: (_, v) => void client.invalidateQueries({ queryKey: ['dl', 'versions', v.projectId] }),
  })
  const removeVersion = useMutation({
    mutationFn: ({ id }: { id: number; projectId: number }) => api.delete(`/vision/dl/versions/${id}`),
    onSuccess: (_, v) => void client.invalidateQueries({ queryKey: ['dl', 'versions', v.projectId] }),
  })
  const datasetExport = useMutation({
    mutationFn: ({ projectId, dir, val_ratio }: { projectId: number; dir: string; val_ratio?: number }) =>
      api.post<{ dir: string; train: number; val: number; test: number }>(`/vision/dl/projects/${projectId}/dataset-export`, { dir, val_ratio }),
  })
  const datasetImport = useMutation({
    mutationFn: ({ projectId, dir }: { projectId: number; dir: string }) =>
      api.post<{ imported: number; skipped: number; duplicates: number; classes: string[] }>(`/vision/dl/projects/${projectId}/dataset-import`, { dir }),
    onSuccess: (_, v) => invalidateProject(v.projectId),
  })
  const samPoint = useMutation({
    mutationFn: ({ projectId, sampleId, points, boxes, labels, model }: { projectId: number; sampleId: string; points?: [number, number][]; boxes?: [number, number, number, number][]; labels?: number[]; model?: string }) =>
      api.post<{ shapes: DlShape[]; model: string }>(`/vision/dl/projects/${projectId}/sam-point`, { sample_id: sampleId, points, boxes, labels, model }),
  })
  const bulkLabels = useMutation({
    mutationFn: ({ projectId, items }: { projectId: number; items: { id: string; label?: string; shapes?: DlShape[]; score?: number; by?: string }[] }) =>
      api.post<{ updated: number }>(`/vision/dl/projects/${projectId}/labels`, { items }),
    onSuccess: (_, v) => invalidateProject(v.projectId),
  })
  const autoLabel = useMutation({
    mutationFn: ({ projectId, params, method, maxSamples }: { projectId: number; params?: Record<string, unknown>; method?: 'model' | 'sam'; maxSamples?: number }) =>
      api.post<{ items: DlSuggestion[]; remaining?: number; method?: string; model?: string }>(`/vision/dl/projects/${projectId}/auto-label`, { params, method, max_samples: maxSamples }),
  })
  const startTrain = useMutation({
    mutationFn: ({ projectId, params, device, asset_name }: { projectId: number; params: Record<string, unknown>; device: string; asset_name: string }) =>
      api.post<DlTrainJob>(`/vision/dl/projects/${projectId}/train`, { params, device, asset_name }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['dl', 'train-status'] }),
  })
  const cancelTrain = useMutation({
    mutationFn: () => api.post<{ cancelled: boolean }>('/vision/dl/train/cancel', {}),
  })
  // 訓練完不自動進資產庫：使用者命名後儲存，或整個放棄
  const saveModel = useMutation({
    mutationFn: (name: string) => api.post<DlTrainJob>('/vision/dl/train/save', { name }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['dl', 'train-status'] })
      void client.invalidateQueries({ queryKey: ['dl', 'projects'] })
      void client.invalidateQueries({ queryKey: ['assets'] })
    },
  })
  const discardModel = useMutation({
    mutationFn: () => api.post<{ discarded: boolean }>('/vision/dl/train/discard', {}),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['dl', 'train-status'] }),
  })
  const patchSettings = useMutation({
    mutationFn: (body: { providers?: string[]; train_device?: string }) => api.patch<DlDevices>('/vision/dl/settings', body),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['dl', 'devices'] }),
  })
  return { createProject, patchProject, removeProject, uploadSamples, fromSource, setLabel, setShapes, setSplit, autoSplit, freezeVersion, removeVersion, datasetExport, datasetImport, samPoint, removeSample, bulkLabels, autoLabel, startTrain, cancelTrain, saveModel, discardModel, patchSettings }
}
