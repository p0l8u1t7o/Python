/**
 * 瀏覽器本機狀態的分層：使用者層（登出／工作階段過期就清——共用電腦下一個人不該看到上一個人的助手對話與 TCP 命令歷史）
 * 與裝置層（主題、登入前的語言、側欄與版面偏好——留在這台電腦）。新增 localStorage 鍵時決定它屬於哪一層。
 */
export const USER_SCOPED_KEYS = ['vs.token', 'vs.apiKey', 'vs.assistant.v1', 'vs.assistant.share', 'vs.tcpHistory'] as const
export const USER_SCOPED_SESSION_KEYS = ['vs.assistant.hints.dismissed'] as const
/** 說明用：這些故意保留 */
export const DEVICE_SCOPED_KEYS = ['vs.theme', 'vs.language', 'vs.sidebar', 'vs.navOpen', 'vs.favoriteTools', 'vs.editorLayout', 'vs.canvasMode', 'vs.overlayLimit', 'vs.viewerState.v1', 'vs.editorGridView.v1', 'vs.toolAutoPreview.v1', 'vs.flowDraftAutoVersion.v1', 'vs.flowDescriptionPanelCollapsed.v1', 'vs.editorCollapsed.v1', 'vs.inspectionRun.v1:'] as const

export interface ViewerLocalState {
  crosshair: boolean
  x: number | null
  y: number | null
  compareOpacity: number
}

export interface EditorGridLocalState {
  count: number
  bindings: ({ nodeId: string; port: string } | null)[]
}

const VIEWER_STATE_KEY = 'vs.viewerState.v1'
const EDITOR_GRID_VIEW_KEY = 'vs.editorGridView.v1'
const TOOL_AUTO_PREVIEW_KEY = 'vs.toolAutoPreview.v1'
const FLOW_DRAFT_AUTO_VERSION_KEY = 'vs.flowDraftAutoVersion.v1'
const FLOW_DESCRIPTION_PANEL_KEY = 'vs.flowDescriptionPanelCollapsed.v1'
const EDITOR_COLLAPSED_KEY = 'vs.editorCollapsed.v1'

function readRecord(key: string): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function writeRecord(key: string, value: Record<string, unknown>): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* private mode */
  }
}

function readBoolean(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    return raw === '1'
  } catch {
    return fallback
  }
}

function writeBoolean(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* private mode */
  }
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function readViewerState(scope: string): Partial<ViewerLocalState> {
  const item = readRecord(VIEWER_STATE_KEY)[scope]
  if (!item || typeof item !== 'object' || Array.isArray(item)) return {}
  const raw = item as Record<string, unknown>
  const opacity = finiteNumber(raw.compareOpacity)
  return {
    crosshair: raw.crosshair === true,
    x: finiteNumber(raw.x),
    y: finiteNumber(raw.y),
    compareOpacity: opacity === null ? undefined : Math.min(100, Math.max(0, Math.round(opacity))),
  }
}

export function writeViewerState(scope: string, state: Partial<ViewerLocalState>): void {
  const record = readRecord(VIEWER_STATE_KEY)
  record[scope] = { ...(record[scope] && typeof record[scope] === 'object' ? record[scope] as Record<string, unknown> : {}), ...state }
  writeRecord(VIEWER_STATE_KEY, record)
}

export function readEditorGridView(flowId: number): Partial<EditorGridLocalState> {
  const item = readRecord(EDITOR_GRID_VIEW_KEY)[String(flowId)]
  if (!item || typeof item !== 'object' || Array.isArray(item)) return {}
  const raw = item as Record<string, unknown>
  return {
    count: finiteNumber(raw.count) ?? undefined,
    bindings: Array.isArray(raw.bindings)
      ? raw.bindings.map((binding) => {
          if (!binding || typeof binding !== 'object' || Array.isArray(binding)) return null
          const b = binding as Record<string, unknown>
          return typeof b.nodeId === 'string' && typeof b.port === 'string' ? { nodeId: b.nodeId, port: b.port } : null
        })
      : undefined,
  }
}

export function writeEditorGridView(flowId: number, state: EditorGridLocalState): void {
  const record = readRecord(EDITOR_GRID_VIEW_KEY)
  record[String(flowId)] = state
  writeRecord(EDITOR_GRID_VIEW_KEY, record)
}

export function readToolAutoPreview(): boolean {
  return readBoolean(TOOL_AUTO_PREVIEW_KEY, false)
}

export function writeToolAutoPreview(value: boolean): void {
  writeBoolean(TOOL_AUTO_PREVIEW_KEY, value)
}

export function readFlowDraftAutoVersion(): boolean {
  return readBoolean(FLOW_DRAFT_AUTO_VERSION_KEY, true)
}

export function writeFlowDraftAutoVersion(value: boolean): void {
  writeBoolean(FLOW_DRAFT_AUTO_VERSION_KEY, value)
}

export function readFlowDescriptionPanelCollapsed(): boolean {
  return readBoolean(FLOW_DESCRIPTION_PANEL_KEY, false)
}

export function writeFlowDescriptionPanelCollapsed(value: boolean): void {
  writeBoolean(FLOW_DESCRIPTION_PANEL_KEY, value)
}

export function readEditorCollapsedTasks(flowId: number): string[] {
  const item = readRecord(EDITOR_COLLAPSED_KEY)[String(flowId)]
  return Array.isArray(item) ? item.filter((value): value is string => typeof value === 'string') : []
}

export function writeEditorCollapsedTasks(flowId: number, taskIds: string[]): void {
  const record = readRecord(EDITOR_COLLAPSED_KEY)
  record[String(flowId)] = Array.from(new Set(taskIds)).sort()
  writeRecord(EDITOR_COLLAPSED_KEY, record)
}

export function clearUserState(): void {
  for (const key of USER_SCOPED_KEYS) {
    try {
      localStorage.removeItem(key)
    } catch {
      /* 私密模式 */
    }
  }
  for (const key of USER_SCOPED_SESSION_KEYS) {
    try {
      sessionStorage.removeItem(key)
    } catch {
      /* 私密模式 */
    }
  }
}
