/**
 * 流程編輯器（FlowEditorPage）：頂列（EditorToolbar）＋ 工具箱／步驟清單 ＋ 影像視窗（ImageViewer）＋ 畫布（FlowCanvas）＋ 側欄（Inspector／ResultsPanel）。
 *
 * 幾個刻意的做法（見 docs/workflow-design.html 第 7/10 節）：
 * - payloads ref 是編輯器自己那份真相，React Flow 的 data 只是投影。
 * - 圖只在 flow.version 變時重載；存檔後自己標記已載入，避免畫布被重設。
 * - isEdit 只認 resizing=true 的 dimensions change。
 * - 鍵盤監聽用 ref 讀最新 nodes/edges；undo 歷史放 ref；deleteKeyCode={null}。
 * - 執行結果由 SSE（useFlowStream）與試執行回應餵進來，步驟狀態用 useMemo 派生。
 * - 未儲存的圖、暫存影像、最近試跑結果放在 lib/flowDraft.ts 的工作階段 store：離開頁面時寫入草稿，
 *   回來（或從工具頁回來）時若伺服器版本沒變就用草稿，所以編輯器 ⇄ 工具頁之間的變更不會丟。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useBlocker, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type FinalConnectionState,
  type Node,
  type NodeChange,
} from '@xyflow/react'
import { Camera, Check, ChevronDown, ChevronUp, Columns2, FileText, Layers, LayoutGrid, RotateCcw } from 'lucide-react'

import { EditorToolbar } from '@/components/editor/EditorToolbar'
import { FlowCanvas, readInteractionMode, storeInteractionMode, type InteractionMode } from '@/components/editor/FlowCanvas'
import { Inspector } from '@/components/editor/Inspector'
import { NodeContextMenu, type NodeMenuState } from '@/components/editor/NodeContextMenu'
import { NodeList } from '@/components/editor/NodeList'
import { FavoriteTools, ToolPicker, readFavorites, writeFavorites } from '@/components/editor/ToolPalette'
import { NodeResult, RecentRunsTable, RunErrorBlock, RunWarnings, SpanTimingCard } from '@/components/editor/ResultsPanel'
import { DRAG_MIME, HISTORY_LIMIT, autoConnectOnInsert, computeLayout, edgeProps, graphFrom, isTypingTarget, nextNodeId, nodeDataFrom, toFlowEdges, toFlowNode, toFlowNodes, type ToolNodeData } from '@/components/editor/graphMapping'
import { useResizer } from '@/components/editor/useResizer'
import { FlowSettingsDialogs } from '@/components/flow/FlowSettingsDialogs'
import { useSaveConflictDialog } from '@/components/flow/SaveConflictDialog'
import { RecipeDrawer } from '@/components/recipes/RecipeDrawer'
import { SaveTemplateModal, TemplateGallery } from '@/components/templates/TemplateGallery'
import { Button, Checkbox, ConfirmDialog, ErrorState, LoadingState, Modal, Select, StatusBadge, Tabs, TextInput } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { api, downloadFile, imageUrl } from '@/lib/api'
import { useConfirm } from '@/lib/useConfirm'
import { selectVisibleRun } from '@/lib/clearResults'
import { errorMessage } from '@/lib/errors'
import { createHistory, pushHistory as pushEditHistory, redoHistory, undoHistory } from '@/lib/flowHistory'
import { getSession, setDraft, updateSession, useFlowSession } from '@/lib/flowDraft'
import { flowGraphSignature, shouldSaveDraftVersion } from '@/lib/flowAutoVersion'
import { searchNodes } from '@/lib/nodeSearch'
import { readEditorCollapsedTasks, readEditorGridView, readFlowDescriptionPanelCollapsed, readFlowDraftAutoVersion, writeEditorCollapsedTasks, writeEditorGridView, writeFlowDescriptionPanelCollapsed } from '@/lib/localState'
import { collapseView, expandOnDrop, groupsOf, taskIdFromGroupNodeId, taskKindLabel, type NodeGroup } from '@/lib/nodeGroups'
import { GRID_COUNTS, bindGridCell, gridCellImage, gridPlacement, normalizeGridLayout, setGridCount, type GridBinding, type GridCount, type GridLayout } from '@/lib/gridView'
import { countFolderPreviewFiles, countPreviewSequenceResult, createPreviewSequenceState, findPreviewSequenceSource, graphForPreviewSequenceItem, isPreviewSequenceDone, nextPreviewSequenceIndex, previewSequenceStatusLabel, type PreviewSequenceSource, type PreviewSequenceState } from '@/lib/previewSequence'
import { describeReport, useRegisterAssistantContext } from '@/lib/assistantContext'
import { useFlowStream, type StreamEvent } from '@/lib/flowStream'
import { DECORATION_TYPES, checkConnection, graphProblems } from '@/lib/graphValidation'
import { useAssetMutations, useClearRecent, useContinuous, useFlow, useFlowMutations, usePreviewFlow, useRecentRuns, useRecipes, useScratchImage, useSources, useToolTypes, type FlowPatch } from '@/lib/queries'
import { isImageRef, type FlowGraph, type GraphEdge, type GraphNode, type NodeReport, type Overlay, type Region, type RunReport, type ToolTypeDef } from '@/lib/types'
import { isLockHolder, useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const LAYOUT_KEY = 'vs.editorLayout'
const FOCUS_OPTIONS = { duration: 300, maxZoom: 1.2 }
const SEQUENCE_DEFAULT_INTERVAL_MS = 1000
const AUTO_VERSION_INTERVAL_MS = 5 * 60 * 1000

interface LayoutState {
  left: number
  right: number
  /** 畫布高度佔中欄比例 */
  canvas: number
}

interface SequenceRun extends PreviewSequenceState {
  source: PreviewSequenceSource
  running: boolean
  paused: boolean
  baseSignature: string
  lastStatus?: string
}

function readLayout(): LayoutState {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY)
    if (raw) return { left: 190, right: 290, canvas: 0.42, ...(JSON.parse(raw) as Partial<LayoutState>) }
  } catch {
    /* ignore */
  }
  return { left: 190, right: 290, canvas: 0.42 }
}

function isEdit(change: NodeChange | EdgeChange): boolean {
  if (change.type === 'select') return false
  if (change.type === 'dimensions') return change.resizing === true
  return true
}

/** 影像視窗要顯示什麼：由「選取步驟 + 顯示模式 + 目前 run」派生。 */
export interface ViewTarget {
  ref: string | null
  width: number
  height: number
  overlays: Overlay[]
  nodeId: string | null
  hasInput: boolean
  hasOutput: boolean
}

function TaskGroupInspector({ flowId, group, nodes, defs, onExpand, onFocus }: { flowId: number; group: NodeGroup; nodes: GraphNode[]; defs: Map<string, ToolTypeDef>; onExpand: (taskId: string) => void; onFocus: (nodeId: string) => void }) {
  const { t } = useTranslation()
  const byId = new Map(nodes.map((node) => [node.id, node]))
  return (
    <div className="space-y-3 p-3" data-testid="group-inspector">
      <div>
        <p className="text-sm font-semibold text-heading">{group.label}</p>
        <p className="mt-0.5 text-xs text-muted">{taskKindLabel(group.kind, (key, fallback) => t(key, { defaultValue: fallback }))}</p>
      </div>
      <Button size="sm" variant="primary" className="w-full" onClick={() => onExpand(group.task_id)} data-testid="group-inspector-expand">
        {t('editor.groups.expand')}
      </Button>
      <Link to={`/flows/${flowId}/inspect?task=${encodeURIComponent(group.task_id)}`} className="block text-xs text-brand hover:underline" data-testid="group-open-inspect">
        {t('editor.groups.openInspect')}
      </Link>
      <div className="border-t border-line pt-3">
        <p className="mb-2 text-xs font-semibold text-heading">{t('editor.groups.nodeList')}</p>
        <div className="space-y-1">
          {group.node_ids.map((id) => {
            const node = byId.get(id)
            const def = node ? defs.get(node.type) : undefined
            return (
              <button key={id} type="button" className="flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-xs hover:bg-surface-muted" onClick={() => { onExpand(group.task_id); window.setTimeout(() => onFocus(id), 30) }}>
                <span className="min-w-0 truncate">{node?.label || def?.label || id}</span>
                <span className="shrink-0 font-mono text-[10px] text-subtle">{id}</span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export function firstImageOutput(report: NodeReport | undefined): { ref: string | null; width: number; height: number } | null {
  if (!report) return null
  for (const [key, value] of Object.entries(report.outputs ?? {})) {
    if (key === '_image') continue // 隱含直通埠＝原影像，不是「執行後」結果（否則 overlay 會消失、前後看起來相反）
    if (isImageRef(value)) return { ref: value.ref, width: value.width, height: value.height }
  }
  return null
}

export function inputImage(run: RunReport, nodeId: string, report: NodeReport, edges: GraphEdge[], defs: Map<string, ToolTypeDef>, payloads: Map<string, GraphNode>): { ref: string | null; width: number; height: number } | null {
  const def = defs.get(payloads.get(nodeId)?.type ?? '')
  const port = report.overlay_on ?? def?.inputs.find((p) => p.type === 'image')?.key
  if (!port) return null
  // 找上游：那條邊的來源步驟輸出。
  const edge = edges.find((e) => e.target === nodeId && (e.target_handle || def?.inputs[0]?.key) === port)
  let upstream: { ref: string | null; width: number; height: number } | null = null
  if (edge) {
    const value = run.nodes[edge.source]?.outputs?.[edge.source_handle || '']
    if (isImageRef(value)) upstream = { ref: value.ref, width: value.width, height: value.height }
  }
  // preview 模式：detail._input_ref 一定保留（上游影像可能已被快取淘汰）。
  const previewRef = report.detail?._input_ref
  if (typeof previewRef === 'string' && previewRef) {
    return { ref: previewRef, width: upstream?.width ?? 0, height: upstream?.height ?? 0 }
  }
  return upstream
}

export function resolveView(run: RunReport | null, selectedId: string | null, mode: 'input' | 'output', allOverlays: boolean, edges: GraphEdge[], defs: Map<string, ToolTypeDef>, payloads: Map<string, GraphNode>, order: string[]): ViewTarget {
  const empty: ViewTarget = { ref: null, width: 0, height: 0, overlays: [], nodeId: null, hasInput: false, hasOutput: false }
  if (!run) return empty
  let nodeId = selectedId && run.nodes[selectedId] ? selectedId : null
  if (!nodeId) {
    // 沒選取：最後一個有影像輸出的步驟。
    for (let i = order.length - 1; i >= 0; i -= 1) {
      if (firstImageOutput(run.nodes[order[i]])) {
        nodeId = order[i]
        break
      }
    }
    if (!nodeId) return empty
  }
  const report = run.nodes[nodeId]
  const input = inputImage(run, nodeId, report, edges, defs, payloads)
  const output = firstImageOutput(report)
  const useInput = mode === 'input' && input !== null ? true : output === null && input !== null
  const chosen = useInput ? input : output
  if (!chosen) return { ...empty, nodeId, hasInput: false, hasOutput: false }
  // 「執行前」（明確選 input）一律乾淨——標記是檢測「結果」，只該出現在執行後；
  // 無影像輸出的工具（找圓/blob…）在 output 模式 fallback 到輸入圖，那才疊標記。
  let overlays: Overlay[] = mode === 'input' && input !== null ? [] : useInput || !input ? report.overlays ?? [] : []
  if (allOverlays) {
    overlays = order.flatMap((id) => run.nodes[id]?.overlays ?? [])
  }
  return { ref: chosen.ref, width: chosen.width, height: chosen.height, overlays, nodeId, hasInput: input !== null, hasOutput: output !== null }
}

/** image_source 步驟的輸出 ref（給「用上次影像重新試執行」）。 */
export function sourceRefOf(run: RunReport | null, payloads: Map<string, GraphNode>): string | null {
  if (!run) return null
  for (const [id, report] of Object.entries(run.nodes)) {
    if (payloads.get(id)?.type !== 'image_source') continue
    const value = report?.outputs?.image
    if (isImageRef(value) && value.ref) return value.ref
  }
  return null
}

/** 拓樸順序（Kahn）。 */
export function topoOrder(graphNodes: GraphNode[], graphEdges: GraphEdge[]): string[] {
  const ids = graphNodes.filter((n) => !DECORATION_TYPES.has(n.type)).map((n) => n.id)
  const indeg = new Map(ids.map((id) => [id, 0]))
  for (const e of graphEdges) if (indeg.has(e.target) && indeg.has(e.source)) indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)
  const queue = ids.filter((id) => indeg.get(id) === 0)
  const out: string[] = []
  while (queue.length) {
    const id = queue.shift() as string
    out.push(id)
    for (const e of graphEdges) {
      if (e.source !== id || !indeg.has(e.target)) continue
      const d = (indeg.get(e.target) ?? 1) - 1
      indeg.set(e.target, d)
      if (d === 0) queue.push(e.target)
    }
  }
  return out
}

function EditorInner({ flowId }: { flowId: number }) {
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const focusedFromUrl = useRef('')
  const toast = useToast()
  const auth = useAuth()
  const { screenToFlowPosition, fitView, setCenter, getZoom } = useReactFlow()

  const catalogue = useToolTypes()
  const flow = useFlow(flowId)
  const recent = useRecentRuns(flowId)
  const { patch } = useFlowMutations()
  const preview = usePreviewFlow()
  const continuous = useContinuous()
  const scratchUpload = useScratchImage()
  const clearRecent = useClearRecent()
  const { fromImage } = useAssetMutations()
  const session = useFlowSession(flowId)
  const recipes = useRecipes(flowId)
  const [recipesOpen, setRecipesOpen] = useState(false)
  const { showConflict, dialog: saveConflictDialog } = useSaveConflictDialog()

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [meta, setMeta] = useState({ name: '', description: '' })
  const [dirty, setDirty] = useState(false)
  const [layout, setLayout] = useState<LayoutState>(readLayout)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [favorites, setFavorites] = useState<string[]>(readFavorites)
  const toggleFavorite = useCallback((key: string) => {
    setFavorites((old) => {
      const next = old.includes(key) ? old.filter((k) => k !== key) : [...old, key]
      writeFavorites(next)
      return next
    })
  }, [])
  const [rightTab, setRightTab] = useState<'inspector' | 'results'>('inspector')
  const [viewMode, setViewMode] = useState<'input' | 'output'>('input')
  const [split, setSplit] = useState(true) // 進編輯器預設就看「執行前／後」並排
  const [gridMode, setGridMode] = useState(false)
  const [gridLayout, setGridLayout] = useState<GridLayout>(() => normalizeGridLayout(readEditorGridView(flowId)))
  const [descriptionCollapsed, setDescriptionCollapsed] = useState(readFlowDescriptionPanelCollapsed)
  const [allOverlays, setAllOverlays] = useState(false)
  const [pinnedRunId, setPinnedRunId] = useState<string | null>(null)
  const [clearedRunId, setClearedRunId] = useState<string | null>(null)
  const [roiEditingKey, setRoiEditingKey] = useState<string | null>(null)
  const [templateKey, setTemplateKey] = useState<string | null>(null)
  const [templateRegion, setTemplateRegion] = useState<Region | null>(null)
  const [proposals, setProposals] = useState<Region[]>([])
  const [templateName, setTemplateName] = useState('')
  const [askTemplateName, setAskTemplateName] = useState(false)
  const [askReset, setAskReset] = useState(false)
  const [interaction, setInteraction] = useState<InteractionMode>(readInteractionMode)
  const [galleryOpen, setGalleryOpen] = useState(false)
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false)
  const [nodeMenu, setNodeMenu] = useState<NodeMenuState | null>(null)
  const [paramsClipboard, setParamsClipboard] = useState<{ type: string; params: Record<string, unknown> } | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchActive, setSearchActive] = useState(0)
  const [collapsedTasks, setCollapsedTasks] = useState<Set<string>>(() => new Set(readEditorCollapsedTasks(flowId)))
  const [groupPositions, setGroupPositions] = useState<Map<string, { x: number; y: number }>>(new Map())
  const groupDragStart = useRef<{ id: string; taskId: string; position: { x: number; y: number } } | null>(null)
  const [sequenceIntervalMs, setSequenceIntervalMs] = useState(SEQUENCE_DEFAULT_INTERVAL_MS)
  const [sequenceRun, setSequenceRun] = useState<SequenceRun | null>(null)
  const searchInput = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const previewRun = session.previewRun
  const setPreviewRun = useCallback((run: RunReport | null) => updateSession(flowId, { previewRun: run }), [flowId])
  const reuseImage = session.reuseImage
  const scratch = session.scratch

  useEffect(() => {
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout))
    } catch {
      /* ignore */
    }
  }, [layout])

  useEffect(() => {
    setGridLayout(normalizeGridLayout(readEditorGridView(flowId)))
    setCollapsedTasks(new Set(readEditorCollapsedTasks(flowId)))
    setGroupPositions(new Map())
  }, [flowId])

  useEffect(() => {
    writeEditorGridView(flowId, gridLayout)
  }, [flowId, gridLayout])
  useEffect(() => {
    writeFlowDescriptionPanelCollapsed(descriptionCollapsed)
  }, [descriptionCollapsed])

  const defs = useMemo(() => {
    const map = new Map<string, ToolTypeDef>()
    for (const def of catalogue.data?.items ?? []) map.set(def.key, def)
    return map
  }, [catalogue.data])

  const payloads = useRef<Map<string, GraphNode>>(new Map())
  const nodesRef = useRef<Node[]>([])
  const edgesRef = useRef<Edge[]>([])
  nodesRef.current = nodes
  edgesRef.current = edges
  const history = useRef(createHistory<FlowGraph>(HISTORY_LIMIT))
  const clipboard = useRef<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null)
  const loadedFor = useRef('')
  const saveBaseline = useRef<string | null>(null)
  const lastAutoVersionSignature = useRef<string | null>(null)
  const sequenceTimer = useRef<number | undefined>(undefined)
  const sequenceAbort = useRef<AbortController | null>(null)
  const sequenceRef = useRef<SequenceRun | null>(null)
  const runSequenceStepRef = useRef<() => void>(() => {})

  const currentGraph = useCallback(() => graphFrom(nodesRef.current, edgesRef.current, payloads.current), [])
  sequenceRef.current = sequenceRun

  // ---- 載入（只在 version 變時；草稿版本相符就用草稿） ----
  useEffect(() => {
    const data = flow.data
    if (!data || defs.size === 0) return
    const key = `${data.id}:${data.version}`
    if (loadedFor.current === key) return
    loadedFor.current = key
    saveBaseline.current = data.updated_at
    const draft = getSession(flowId).draft
    const source = draft && draft.baseVersion === data.version ? draft : null
    const graph = source ? source.graph : data.graph
    payloads.current = new Map((graph.nodes ?? []).map((n) => [n.id, n]))
    setNodes(toFlowNodes(graph, defs))
    setEdges(toFlowEdges(graph, defs))
    setMeta(source ? { name: source.name, description: source.description } : { name: data.name, description: data.description })
    setDirty(source ? source.dirty : false)
    lastAutoVersionSignature.current = flowGraphSignature(data.graph)
    history.current = createHistory<FlowGraph>(HISTORY_LIMIT)
  }, [flow.data, defs, setNodes, setEdges, flowId])

  const loadServerConflict = useCallback(
    (details: { version: number; updated_at: string; graph: FlowGraph }) => {
      saveBaseline.current = details.updated_at
      loadedFor.current = `${flowId}:${details.version}`
      payloads.current = new Map((details.graph.nodes ?? []).map((n) => [n.id, n]))
      setNodes(toFlowNodes(details.graph, defs))
      setEdges(toFlowEdges(details.graph, defs))
      setDirty(false)
      lastAutoVersionSignature.current = flowGraphSignature(details.graph)
      setDraft(flowId, { baseVersion: details.version, graph: details.graph, name: meta.name, description: meta.description, dirty: false })
      void flow.refetch()
    },
    [defs, flow, flowId, meta.description, meta.name, setEdges, setNodes],
  )

  const markSaved = useCallback((saved: { id: number; version: number; updated_at: string }) => {
    loadedFor.current = `${saved.id}:${saved.version}`
    saveBaseline.current = saved.updated_at
  }, [])

  // ---- 離開頁面時把目前的圖寫成草稿（工具頁會讀；回來時 version 相符就沿用） ----
  const latest = useRef({ meta, dirty, version: flow.data?.version ?? 0, loaded: false })
  latest.current = { meta, dirty, version: flow.data?.version ?? 0, loaded: loadedFor.current !== '' }
  useEffect(
    () => () => {
      const l = latest.current
      if (!l.loaded) return
      setDraft(flowId, { baseVersion: l.version, graph: currentGraph(), name: l.meta.name, description: l.meta.description, dirty: l.dirty })
    },
    [flowId, currentGraph],
  )

  // ---- 權限 ----
  /** 引擎被鎖：整合方與鎖的持有者仍可執行，其他人（含管理員）只能編輯。 */
  const execLocked = auth.lock.locked && auth.me?.kind !== 'integrator' && !isLockHolder(auth.me, auth.lock)
  /** 共用（或別人的）流程一般使用者不能改，只能複製。 */
  const readOnly = !auth.isEngineer  // 流程屬於產線：工程師都能改，操作員只能在參數卡頁調現場參數
  const lockHint = execLocked ? t('lock.execDisabled', { holder: auth.lock.holder === 'integrator' ? t('lock.integrator') : auth.lock.holder }) : undefined

  const latestAutoVersion = useRef({ meta, dirty, readOnly })
  latestAutoVersion.current = { meta, dirty, readOnly }
  const autoVersionSaving = useRef(false)
  useEffect(() => {
    const saveDraftVersion = async () => {
      const l = latestAutoVersion.current
      if (l.readOnly || autoVersionSaving.current) return
      const graph = currentGraph()
      const signature = flowGraphSignature(graph)
      if (!shouldSaveDraftVersion({ enabled: readFlowDraftAutoVersion(), dirty: l.dirty, currentSignature: signature, lastSavedSignature: lastAutoVersionSignature.current })) return
      autoVersionSaving.current = true
      try {
        const saved = await patch.mutateAsync(
          { id: flowId, name: l.meta.name.trim() || t('editor.untitled'), description: l.meta.description, graph, expected_updated_at: saveBaseline.current },
          { onSuccess: markSaved },
        )
        lastAutoVersionSignature.current = signature
        if (flowGraphSignature(currentGraph()) === signature) {
          setDirty(false)
          setDraft(flowId, { baseVersion: saved.version, graph, name: l.meta.name, description: l.meta.description, dirty: false })
        }
        toast.success(t('editor.toast.autoVersionSaved', { version: saved.version }))
      } catch (error) {
        if (!showConflict(error, {
          flowId,
          graph,
          loadServer: loadServerConflict,
          overwrite: async (updatedAt) => {
            const saved = await patch.mutateAsync({ id: flowId, name: l.meta.name.trim() || t('editor.untitled'), description: l.meta.description, graph, expected_updated_at: updatedAt }, { onSuccess: markSaved })
            lastAutoVersionSignature.current = signature
            if (flowGraphSignature(currentGraph()) === signature) {
              setDirty(false)
              setDraft(flowId, { baseVersion: saved.version, graph, name: l.meta.name, description: l.meta.description, dirty: false })
            }
            toast.success(t('editor.toast.autoVersionSaved', { version: saved.version }))
          },
        })) toast.error(errorMessage(error))
      } finally {
        autoVersionSaving.current = false
      }
    }
    const timer = window.setInterval(() => void saveDraftVersion(), AUTO_VERSION_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [currentGraph, flowId, patch, t, toast, markSaved, showConflict, loadServerConflict])

  // ---- SSE ----
  const onStreamEvent = useCallback(
    (event: StreamEvent) => {
      if (event.type === 'cleared') {
        setPreviewRun(null)
        setPinnedRunId(null)
      }
    },
    [setPreviewRun],
  )
  const stream = useFlowStream(flowId, true, onStreamEvent)
  const running = preview.isPending || stream.runningIds.size > 0

  // ---- 目前顯示的 run ----
  const recentRuns = useMemo(() => recent.data?.items ?? [], [recent.data])
  const activeRun = useMemo<RunReport | null>(() => selectVisibleRun({ pinnedRunId, previewRun, recentRuns, clearedRunId }), [pinnedRunId, previewRun, recentRuns, clearedRunId])

  const graphNodes = useMemo(() => nodes.map((n) => payloads.current.get(n.id)).filter((p): p is GraphNode => Boolean(p)), [nodes])
  const graphEdges = useMemo<GraphEdge[]>(() => edges.map((e) => ({ id: e.id, source: e.source, target: e.target, source_handle: e.sourceHandle ?? '', target_handle: e.targetHandle ?? '' })), [edges])
  //: 沒選影像來源又沒暫存影像 → 試執行一定失敗；橫幅直接讓人選來源（不用先找到取像步驟再進工具頁）
  const missingSourceNode = useMemo(() => graphNodes.find((n) => n.type === 'image_source' && !n.params?.source_id) ?? null, [graphNodes])
  const sourceList = useSources()
  const sequenceSource = useMemo(() => findPreviewSequenceSource({ nodes: graphNodes, edges: graphEdges }, sourceList.data?.items ?? []), [graphNodes, graphEdges, sourceList.data])
  const nodeOrder = useMemo(() => topoOrder(graphNodes, graphEdges), [graphNodes, graphEdges])
  const selectedCount = useMemo(() => nodes.filter((n) => n.selected).length, [nodes])
  const searchResults = useMemo(() => searchNodes(graphNodes, defs, searchQuery), [graphNodes, defs, searchQuery])
  const taskGroups = useMemo(
    () => groupsOf({ nodes: graphNodes, edges: graphEdges }, defs, (key, fallback) => t(key, { defaultValue: fallback })),
    [graphNodes, graphEdges, defs, t],
  )
  const taskGroupById = useMemo(() => new Map(taskGroups.map((group) => [group.task_id, group])), [taskGroups])
  const taskByNodeId = useMemo(() => {
    const map = new Map<string, string>()
    for (const group of taskGroups) for (const id of group.node_ids) map.set(id, group.task_id)
    return map
  }, [taskGroups])
  const storeCollapsedTasks = useCallback(
    (tasks: Set<string>) => {
      const valid = new Set(Array.from(tasks).filter((taskId) => taskGroupById.has(taskId)))
      setCollapsedTasks(valid)
      writeEditorCollapsedTasks(flowId, Array.from(valid))
      setGroupPositions(new Map())
    },
    [flowId, taskGroupById],
  )
  useEffect(() => {
    if (searchActive !== 0 && searchActive >= searchResults.length) setSearchActive(0)
  }, [searchActive, searchResults.length])
  useEffect(() => {
    const valid = new Set(Array.from(collapsedTasks).filter((taskId) => taskGroupById.has(taskId)))
    if (valid.size !== collapsedTasks.size) storeCollapsedTasks(valid)
  }, [collapsedTasks, taskGroupById, storeCollapsedTasks])

  const problemMap = useMemo(() => graphProblems(graphNodes, graphEdges, defs), [graphNodes, graphEdges, defs])
  const boardOutputNames = useMemo(() => Array.from(new Set(graphNodes.filter((n) => n.type === 'output' || n.type === 'format_text').map((n) => String(n.params?.name ?? '')).filter(Boolean))), [graphNodes])
  const boardImageNodes = useMemo(
    () => graphNodes.filter((n) => defs.get(n.type)?.outputs.some((p) => p.type === 'image' && !p.implicit)).map((n) => ({ id: n.id, label: n.label || defs.get(n.type)?.label || n.id })),
    [graphNodes, defs],
  )

  // ---- 步驟裝飾：只在有變的步驟回新物件 ----
  const slowestMs = useMemo(() => (activeRun ? Math.max(0, ...Object.values(activeRun.nodes).map((r) => (r.status === 'skipped' ? 0 : r.duration_ms))) : 0), [activeRun])
  const decoratedNodes = useMemo(
    () =>
      nodes.map((node) => {
        const data = node.data as ToolNodeData
        const report = activeRun?.nodes[node.id]
        const problems = problemMap.get(node.id)
        const problem = problems?.length ? t(`editor.validation.${problems[0].code}`, problems[0].values) : undefined
        const isRunning = running && data.enabled && node.type === 'tool'
        const heat = report && slowestMs > 0 && report.status !== 'skipped' ? report.duration_ms / slowestMs : 0
        if (data.report === report && data.problem === problem && Boolean(data.running) === isRunning && data.heat === heat) return node
        return { ...node, data: { ...data, report, problem, running: isRunning, heat } }
      }),
    [nodes, activeRun, problemMap, running, slowestMs, t],
  )
  const decoratedEdges = useMemo(
    () =>
      edges.map((edge) => {
        const src = activeRun?.nodes[edge.source]
        const dst = activeRun?.nodes[edge.target]
        const flowing = Boolean(src && src.status === 'ok' && dst && dst.status !== 'skipped')
        if (Boolean((edge.data as { flowing?: boolean } | undefined)?.flowing) === flowing) return edge
        return { ...edge, data: { ...(edge.data ?? {}), flowing } }
      }),
    [edges, activeRun],
  )
  const expandTask = useCallback(
    (taskId: string) => {
      const next = new Set(collapsedTasks)
      next.delete(taskId)
      storeCollapsedTasks(next)
      setSelectedId(null)
    },
    [collapsedTasks, storeCollapsedTasks],
  )
  const collapseTask = useCallback(
    (taskId: string) => {
      if (!taskGroupById.has(taskId)) return
      const next = new Set(collapsedTasks)
      next.add(taskId)
      storeCollapsedTasks(next)
      setSelectedId(`group:${taskId}`)
    },
    [collapsedTasks, storeCollapsedTasks, taskGroupById],
  )
  const expandTaskForNode = useCallback(
    (nodeId: string) => {
      const taskId = taskByNodeId.get(nodeId)
      if (!taskId || !collapsedTasks.has(taskId)) return
      const next = new Set(collapsedTasks)
      next.delete(taskId)
      storeCollapsedTasks(next)
    },
    [collapsedTasks, storeCollapsedTasks, taskByNodeId],
  )
  const displayView = useMemo(() => {
    const view = collapseView(decoratedNodes, decoratedEdges, collapsedTasks, { nodes: graphNodes, edges: graphEdges }, defs, activeRun?.nodes ?? null, expandTask)
    return {
      ...view,
      nodes: view.nodes.map((node) => {
        const position = groupPositions.get(node.id)
        const selected = node.type === 'group' ? node.id === selectedId : node.selected
        return position || selected !== node.selected ? { ...node, ...(position ? { position } : {}), selected } : node
      }),
    }
  }, [activeRun, collapsedTasks, decoratedEdges, decoratedNodes, defs, expandTask, graphEdges, graphNodes, groupPositions, selectedId])

  // ---- 離開攔截（到工具頁／參數卡不算離開：草稿會帶過去；其他路由如流程列表、別的流程都要問） ----
  const toolPagePrefix = `/flows/${flowId}/tools/`
  const teachPath = `/flows/${flowId}/teach`
  const { confirm, dialog: confirmDialog } = useConfirm()
  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }: { currentLocation: { pathname: string }; nextLocation: { pathname: string } }) =>
        dirty && currentLocation.pathname !== nextLocation.pathname && !nextLocation.pathname.startsWith(toolPagePrefix) && nextLocation.pathname !== teachPath,
      [dirty, toolPagePrefix, teachPath],
    ),
  )
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    void confirm(t('editor.leaveUnsaved'), { title: t('editor.leaveTitle'), confirmLabel: t('editor.leaveAnyway') }).then((ok) => (ok ? blocker.proceed() : blocker.reset()))
  }, [blocker, t, confirm])
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  // ---- 編輯操作 ----
  const pushHistory = useCallback(() => {
    history.current = pushEditHistory(history.current, currentGraph())
  }, [currentGraph])

  const restoreGraph = useCallback(
    (graph: FlowGraph) => {
      payloads.current = new Map(graph.nodes.map((n) => [n.id, n]))
      setNodes(toFlowNodes(graph, defs))
      setEdges(toFlowEdges(graph, defs))
      setSelectedId(null)
      setDirty(true)
    },
    [defs, setNodes, setEdges],
  )

  const undo = useCallback(() => {
    const previous = undoHistory(history.current, currentGraph())
    history.current = previous.state
    if (previous.value) restoreGraph(previous.value)
  }, [currentGraph, restoreGraph])

  const redo = useCallback(() => {
    const next = redoHistory(history.current, currentGraph())
    history.current = next.state
    if (next.value) restoreGraph(next.value)
  }, [currentGraph, restoreGraph])

  const onConnect = useCallback(
    (connection: Connection) => {
      const rejection = checkConnection(connection, payloads.current, graphFrom(nodesRef.current, edgesRef.current, payloads.current).edges, defs)
      if (rejection) {
        toast.warning(t(`editor.validation.${rejection.code}`, rejection.values))
        return
      }
      const source = payloads.current.get(connection.source)
      const def = source ? defs.get(source.type) : undefined
      const handle = connection.sourceHandle || def?.outputs[0]?.key || ''
      const sourceType = def?.outputs.find((p) => p.key === handle)?.type ?? 'any'
      pushHistory()
      setEdges((current) => addEdge({ ...connection, sourceHandle: handle, ...edgeProps(sourceType, source?.type === 'note') }, current))
      setDirty(true)
    },
    [defs, pushHistory, setEdges, t, toast],
  )

  const isValidConnection = useCallback(
    (conn: Connection | Edge) => checkConnection({ source: conn.source, sourceHandle: conn.sourceHandle ?? null, target: conn.target, targetHandle: conn.targetHandle ?? null }, payloads.current, graphFrom(nodesRef.current, edgesRef.current, payloads.current).edges, defs) === null,
    [defs],
  )
  // React Flow 對 isValidConnection 回 false 的連線不會呼叫 onConnect，所以被拒的原因要在 onConnectEnd 說出來。
  const onConnectEnd = useCallback(
    (_e: MouseEvent | TouchEvent, state: FinalConnectionState) => {
      if (!state.toHandle || !state.toNode || state.isValid !== false) return
      const from = { node: state.fromNode.id, handle: state.fromHandle.id ?? null, type: state.fromHandle.type }
      const to = { node: state.toNode.id, handle: state.toHandle.id ?? null, type: state.toHandle.type }
      const [src, dst] = from.type === 'source' ? [from, to] : [to, from]
      const rejection = checkConnection({ source: src.node, sourceHandle: src.handle, target: dst.node, targetHandle: dst.handle }, payloads.current, graphFrom(nodesRef.current, edgesRef.current, payloads.current).edges, defs)
      if (rejection) toast.warning(t(`editor.validation.${rejection.code}`, rejection.values))
    },
    [defs, toast, t],
  )

  const insertNode = useCallback(
    (def: ToolTypeDef, position: { x: number; y: number }) => {
      pushHistory()
      const id = nextNodeId(new Set(payloads.current.keys()), def.key)
      const payload: GraphNode = {
        id,
        type: def.key,
        label: '',
        description: '',
        enabled: true,
        continue_on_error: false,
        params: Object.fromEntries(def.params.filter((p) => p.default !== null && p.default !== undefined).map((p) => [p.key, p.default])),
        position,
      }
      const graphBefore = graphFrom(nodesRef.current, edgesRef.current, payloads.current)
      const autoEdge = autoConnectOnInsert({ nodes: [...graphBefore.nodes, payload], edges: graphBefore.edges }, id, selectedId, defs)
      payloads.current.set(id, payload)
      setNodes((current) => [...current.map((n) => ({ ...n, selected: false })), { ...toFlowNode(payload, def), selected: true }])
      if (autoEdge) {
        const source = payloads.current.get(autoEdge.source)
        const sourceDef = source ? defs.get(source.type) : undefined
        const sourceType = sourceDef?.outputs.find((p) => p.key === autoEdge.source_handle)?.type ?? (autoEdge.source_handle === '_image' ? 'image' : 'any')
        setEdges((current) => [...current, { id: autoEdge.id ?? `e-auto-${autoEdge.source}-${autoEdge.target}`, source: autoEdge.source, target: autoEdge.target, sourceHandle: autoEdge.source_handle ?? null, targetHandle: autoEdge.target_handle ?? null, ...edgeProps(sourceType, source?.type === 'note') }])
      }
      setSelectedId(id)
      setRightTab('inspector')
      setDirty(true)
    },
    [defs, pushHistory, selectedId, setEdges, setNodes],
  )

  const onDragOver = useCallback((e: React.DragEvent) => {
    if (e.dataTransfer.types.includes(DRAG_MIME)) {
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    }
  }, [])
  const insertAtCenter = useCallback(
    (def: ToolTypeDef) => {
      const jitter = () => Math.round((Math.random() - 0.5) * 60)
      const p = screenToFlowPosition({ x: window.innerWidth * 0.55 + jitter(), y: window.innerHeight * 0.55 + jitter() })
      insertNode(def, { x: Math.round(p.x), y: Math.round(p.y) })
      setPickerOpen(false)
    },
    [insertNode, screenToFlowPosition],
  )

  const insertNoteAtCenter = useCallback(() => {
    pushHistory()
    const jitter = () => Math.round((Math.random() - 0.5) * 60)
    const p = screenToFlowPosition({ x: window.innerWidth * 0.55 + jitter(), y: window.innerHeight * 0.55 + jitter() })
    const id = nextNodeId(new Set(payloads.current.keys()), 'note')
    const payload: GraphNode = {
      id, type: 'note', label: t('palette.noteDefaultLabel'), description: '', enabled: true, params: {},
      position: { x: Math.round(p.x), y: Math.round(p.y) }, width: 260, height: 100,
    }
    payloads.current.set(id, payload)
    setNodes((current) => [...current.map((n) => ({ ...n, selected: false })), { ...toFlowNode(payload, undefined), selected: true }])
    setSelectedId(id)
    setRightTab('inspector')
    setDirty(true)
  }, [pushHistory, screenToFlowPosition, setNodes, t])

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      const key = e.dataTransfer.getData(DRAG_MIME)
      const def = key ? defs.get(key) : undefined
      if (!def) return
      e.preventDefault()
      const p = screenToFlowPosition({ x: e.clientX, y: e.clientY })
      insertNode(def, { x: Math.round(p.x), y: Math.round(p.y) })
    },
    [defs, insertNode, screenToFlowPosition],
  )

  const patchNode = useCallback(
    (id: string, patchData: Partial<GraphNode>) => {
      const current = payloads.current.get(id)
      if (!current) return
      const updated = { ...current, ...patchData }
      payloads.current.set(id, updated)
      setNodes((list) => list.map((n) => (n.id === id ? { ...n, data: { ...(n.data as ToolNodeData), ...nodeDataFrom(updated, defs.get(updated.type)) } } : n)))
      setDirty(true)
    },
    [defs, setNodes],
  )

  const applyGraphChange = useCallback(
    (graph: FlowGraph): string | null => {
      const nodeMap = new Map(graph.nodes.map((node) => [node.id, node]))
      for (let index = 0; index < graph.edges.length; index += 1) {
        const edge = graph.edges[index]
        const rejection = checkConnection(
          { source: edge.source, sourceHandle: edge.source_handle ?? null, target: edge.target, targetHandle: edge.target_handle ?? null },
          nodeMap,
          graph.edges.filter((_item, i) => i !== index),
          defs,
        )
        if (rejection) return t(`editor.validation.${rejection.code}`, rejection.values)
      }
      pushHistory()
      const selectedIds = new Set(nodesRef.current.filter((node) => node.selected).map((node) => node.id))
      payloads.current = new Map(graph.nodes.map((node) => [node.id, node]))
      setNodes(toFlowNodes(graph, defs).map((node) => ({ ...node, selected: selectedIds.has(node.id) })))
      setEdges(toFlowEdges(graph, defs))
      setDirty(true)
      return null
    },
    [defs, pushHistory, setEdges, setNodes, t],
  )

  const deleteNodes = useCallback(
    async (ids: string[]) => {
      if (!ids.length) return
      const gone = new Set(ids)
      const usages = graphFrom(nodesRef.current, edgesRef.current, payloads.current).edges
        .filter((edge) => gone.has(edge.source) && !gone.has(edge.target))
        .map((edge) => {
          const target = payloads.current.get(edge.target)
          const def = target ? defs.get(target.type) : undefined
          const port = def?.inputs.find((item) => item.key === (edge.target_handle ?? ''))
          return `${target?.label || def?.label || edge.target} · ${port?.label || edge.target_handle || ''}`
        })
      if (usages.length) {
        const ok = await confirm(
          <div className="space-y-2">
            <p>{t('editor.deleteUsers.message')}</p>
            <ul className="max-h-40 list-disc space-y-1 overflow-y-auto pl-5 text-left text-xs">
              {usages.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
            </ul>
          </div>,
          { title: t('editor.deleteUsers.title'), confirmLabel: t('common.delete'), danger: true },
        )
        if (!ok) return
      }
      pushHistory()
      for (const id of ids) payloads.current.delete(id)
      setNodes((list) => list.filter((n) => !gone.has(n.id)))
      setEdges((list) => list.filter((e) => !gone.has(e.source) && !gone.has(e.target)))
      setSelectedId((cur) => (cur && gone.has(cur) ? null : cur))
      setDirty(true)
    },
    [confirm, defs, pushHistory, setNodes, setEdges, t],
  )

  const copySelection = useCallback(() => {
    const chosen = nodesRef.current.filter((n) => n.selected)
    if (!chosen.length) return
    const ids = new Set(chosen.map((n) => n.id))
    clipboard.current = {
      nodes: chosen.map((n) => ({ ...(payloads.current.get(n.id) ?? { id: n.id, type: 'note' }), position: { x: n.position.x, y: n.position.y } })),
      edges: edgesRef.current.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({ source: e.source, target: e.target, source_handle: e.sourceHandle ?? '', target_handle: e.targetHandle ?? '' })),
    }
  }, [])

  const paste = useCallback(() => {
    const copied = clipboard.current
    if (!copied?.nodes.length) return
    pushHistory()
    const existing = new Set(payloads.current.keys())
    const rename = new Map<string, string>()
    const fresh: Node[] = []
    for (const source of copied.nodes) {
      const id = nextNodeId(existing, source.type)
      existing.add(id)
      rename.set(source.id, id)
      const payload: GraphNode = { ...source, id, position: { x: (source.position?.x ?? 100) + 40, y: (source.position?.y ?? 100) + 40 } }
      payloads.current.set(id, payload)
      fresh.push({ ...toFlowNode(payload, defs.get(payload.type)), selected: true })
    }
    setNodes((cur) => [...cur.map((n) => ({ ...n, selected: false })), ...fresh])
    setEdges((cur) => [
      ...cur,
      ...copied.edges.map((e, i) => {
        const source = rename.get(e.source) ?? e.source
        const src = payloads.current.get(source)
        const def = src ? defs.get(src.type) : undefined
        const type = def?.outputs.find((p) => p.key === e.source_handle)?.type ?? 'any'
        return { id: `e-paste-${Date.now()}-${i}`, source, target: rename.get(e.target) ?? e.target, sourceHandle: e.source_handle || null, targetHandle: e.target_handle || null, ...edgeProps(type, src?.type === 'note') }
      }),
    ])
    setDirty(true)
  }, [defs, pushHistory, setNodes, setEdges])

  const autoLayout = useCallback(() => {
    pushHistory()
    const positions = computeLayout(currentGraph())
    if (!positions.size) return
    for (const [id, position] of positions) {
      const p = payloads.current.get(id)
      if (p) payloads.current.set(id, { ...p, position })
    }
    setNodes((list) => list.map((n) => (positions.get(n.id) ? { ...n, position: positions.get(n.id)! } : n)))
    setDirty(true)
    window.setTimeout(() => void fitView({ padding: 0.15, duration: 300 }), 50)
  }, [pushHistory, currentGraph, setNodes, fitView])

  /** 選取一個步驟並把畫布帶到它（步驟清單、錯誤區塊「前往該步驟」）。 */
  const focusNode = useCallback(
    (id: string) => {
      expandTaskForNode(id)
      setSelectedId(id)
      setNodes((list) => list.map((n) => ({ ...n, selected: n.id === id })))
      window.setTimeout(() => void fitView({ nodes: [{ id }], ...FOCUS_OPTIONS }), 30)
    },
    [expandTaskForNode, setNodes, fitView],
  )

  // 等草稿節點載入後才聚焦；同一個網址只處理一次，避免重繪搶走選取。
  useEffect(() => {
    const id = searchParams.get('focus')
    if (!id) { focusedFromUrl.current = ''; return }
    const key = `${flowId}:${id}`
    if (focusedFromUrl.current === key || !graphNodes.some((node) => node.id === id)) return
    focusedFromUrl.current = key
    setRightTab('inspector')
    focusNode(id)
  }, [flowId, searchParams, graphNodes, focusNode])

  const centerSearchNode = useCallback(
    (id: string) => {
      const node = nodesRef.current.find((item) => item.id === id)
      if (!node) return
      expandTaskForNode(id)
      setSelectedId(id)
      setRightTab('inspector')
      setNodes((list) => list.map((item) => ({ ...item, selected: item.id === id })))
      const width = node.width ?? 180
      const height = node.height ?? 72
      void setCenter(node.position.x + width / 2, node.position.y + height / 2, { duration: 300, zoom: Math.min(Math.max(getZoom(), 0.8), 1.2) })
    },
    [expandTaskForNode, getZoom, setCenter, setNodes],
  )

  // ---- 存檔／執行 ----
  const save = useCallback(async (): Promise<boolean> => {
    if (readOnly) {
      toast.warning(t('flows.readOnlyHint'))
      return false
    }
    if (problemMap.size > 0) toast.warning(t('editor.toast.validationWarning', { count: problemMap.size }))
    try {
      const graph = currentGraph()
      const saveBody = { id: flowId, name: meta.name.trim() || t('editor.untitled'), description: meta.description, graph }
      await patch.mutateAsync(
        { ...saveBody, expected_updated_at: saveBaseline.current },
        // 回應的新 version 會觸發「重載圖」effect；先標記為已載入，畫布才不會被重設。
        { onSuccess: markSaved },
      )
      lastAutoVersionSignature.current = flowGraphSignature(graph)
      setDirty(false)
      toast.success(t('editor.toast.saved'))
      return true
    } catch (error) {
      const graph = currentGraph()
      if (showConflict(error, {
        flowId,
        graph,
        loadServer: loadServerConflict,
        overwrite: async (updatedAt) => {
          const saved = await patch.mutateAsync({ id: flowId, name: meta.name.trim() || t('editor.untitled'), description: meta.description, graph, expected_updated_at: updatedAt }, { onSuccess: markSaved })
          lastAutoVersionSignature.current = flowGraphSignature(graph)
          setDirty(false)
          setDraft(flowId, { baseVersion: saved.version, graph, name: meta.name, description: meta.description, dirty: false })
          toast.success(t('editor.toast.saved'))
        },
      })) return false
      toast.error(errorMessage(error))
      return false
    }
  }, [readOnly, problemMap.size, patch, flowId, meta, currentGraph, toast, t, markSaved, showConflict, loadServerConflict])

  const patchFlowSettings = useCallback(
    async (body: FlowPatch, onSaved?: () => void) => {
      const graph = currentGraph()
      try {
        const saved = await patch.mutateAsync({ id: flowId, ...body, expected_updated_at: saveBaseline.current })
        markSaved(saved)
        onSaved?.()
      } catch (error) {
        if (!showConflict(error, {
          flowId,
          graph,
          loadServer: loadServerConflict,
          overwrite: async (updatedAt) => {
            const saved = await patch.mutateAsync({ id: flowId, ...body, expected_updated_at: updatedAt })
            markSaved(saved)
            onSaved?.()
          },
        })) toast.error(errorMessage(error))
      }
    },
    [currentGraph, flowId, loadServerConflict, markSaved, patch, showConflict, toast],
  )

  const lastSourceRef = useMemo(() => sourceRefOf(activeRun, payloads.current), [activeRun])
  //: 全域 AI 助手：在編輯器內可直接請助手修改目前畫布（套用走復原堆疊）
  //: 頁面現況給助手：用 ref 存最新值，describe() 讀時才取，不必把每個狀態都放進 deps
  const snapshotRef = useRef<() => Record<string, unknown>>(() => ({}))
  snapshotRef.current = () => {
    const g = currentGraph()
    const sel = selectedId ? g.nodes.find((n) => n.id === selectedId) : undefined
    const types = new Map(g.nodes.map((n) => [n.id, n.type]))
    return {
      selected: sel ? { id: sel.id, type: sel.type, ...(sel.label ? { label: sel.label } : {}) } : null,
      dirty, nodes: g.nodes.length, continuous: Boolean(flow.data?.continuous), locked: execLocked,
      last_run: describeReport(activeRun, types),
    }
  }
  useRegisterAssistantContext({
    kind: 'flow_editor', flowId, flowName: meta.name, imageRef: lastSourceRef, execLocked, getGraph: currentGraph,
    applyGraph: (g, why) => { pushHistory(); restoreGraph(g); toast.success(why ? `${t('agent.applied')}: ${why}` : t('agent.applied')) },
    describe: () => snapshotRef.current(), focusNode: (id) => setSelectedId(id),
    showProposals: setProposals,
  }, [flowId, meta.name, lastSourceRef, execLocked])
  /** 固定的來源影像：暫存影像優先，其次「用上次影像重跑」。 */
  const pinnedRef = scratch?.ref ?? (reuseImage ? lastSourceRef : null)

  const doPreview = useCallback(async (untilNode?: string) => {
    try {
      // untilNode：只跑到那一步（含它的上游），下游全部略過——調某一步時不必等整張圖跑完
      const report = await preview.mutateAsync({ flowId, graph: currentGraph(), reuse_image_ref: pinnedRef, until_node: untilNode ?? null })
      setPreviewRun(report)
      setPinnedRunId(null)
      setClearedRunId(null)
      if (untilNode) setSelectedId(untilNode)
      toast.push(t(untilNode ? 'editor.toast.runToDone' : 'editor.toast.previewDone', { status: t(`status.${report.status}`), ms: Math.round(report.duration_ms) }), report.status === 'ok' ? 'success' : report.status === 'ng' ? 'warning' : 'error', 1500)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }, [preview, flowId, currentGraph, pinnedRef, setPreviewRun, toast, t])

  const clearSequenceTimer = useCallback(() => {
    if (sequenceTimer.current === undefined) return
    window.clearTimeout(sequenceTimer.current)
    sequenceTimer.current = undefined
  }, [])

  const stopSequencePreview = useCallback((announce = false) => {
    clearSequenceTimer()
    sequenceAbort.current?.abort()
    sequenceAbort.current = null
    const state = sequenceRef.current
    if (!state) return
    const next = { ...state, running: false, paused: false }
    setSequenceRun(next)
    sequenceRef.current = next
    if (announce) toast.push(t('editor.sequenceStopped', { ok: state.ok, ng: state.ng }), 'info', 1600)
  }, [clearSequenceTimer, toast, t])

  const resolveSequenceTotal = useCallback(async (source: PreviewSequenceSource) => {
    if (source.total > 0) return source.total
    if (source.kind !== 'folder' || !source.folderPath) return 0
    const listing = await api.get<{ files: string[] }>('/vision/fs', { path: source.folderPath })
    return countFolderPreviewFiles(listing.files ?? [], source.pattern)
  }, [])

  const runSequenceStep = useCallback(async () => {
    const state = sequenceRef.current
    if (!state || !state.running || state.paused) return
    const nextIndex = nextPreviewSequenceIndex(state)
    if (nextIndex === null) {
      const next = { ...state, running: false, paused: false }
      setSequenceRun(next)
      sequenceRef.current = next
      toast.push(t('editor.sequenceDone', { ok: state.ok, ng: state.ng }), state.ng ? 'warning' : 'success', 2200)
      return
    }
    clearSequenceTimer()
    const controller = new AbortController()
    sequenceAbort.current = controller
    setSelectedId(state.source.nodeId)
    setRightTab('results')
    try {
      const graph = graphForPreviewSequenceItem(currentGraph(), state.source, nextIndex)
      const report = await preview.mutateAsync({ flowId, graph, reuse_image_ref: null, until_node: null, signal: controller.signal })
      if (controller.signal.aborted) return
      setPreviewRun(report)
      setPinnedRunId(null)
      setClearedRunId(null)
      const updated = countPreviewSequenceResult(state, report.status)
      const nextState: SequenceRun = { ...state, ...updated, lastStatus: report.status, running: !isPreviewSequenceDone(updated), paused: false }
      setSequenceRun(nextState)
      sequenceRef.current = nextState
      if (isPreviewSequenceDone(updated)) {
        toast.push(t('editor.sequenceDone', { ok: updated.ok, ng: updated.ng }), updated.ng ? 'warning' : 'success', 2200)
      } else {
        sequenceTimer.current = window.setTimeout(() => runSequenceStepRef.current(), sequenceIntervalMs)
      }
    } catch (error) {
      if (controller.signal.aborted) return
      const updated = countPreviewSequenceResult(state, 'failed')
      const nextState: SequenceRun = { ...state, ...updated, lastStatus: 'failed', running: !isPreviewSequenceDone(updated), paused: false }
      setSequenceRun(nextState)
      sequenceRef.current = nextState
      toast.error(errorMessage(error))
      if (!isPreviewSequenceDone(updated)) sequenceTimer.current = window.setTimeout(() => runSequenceStepRef.current(), sequenceIntervalMs)
    } finally {
      if (sequenceAbort.current === controller) sequenceAbort.current = null
    }
  }, [clearSequenceTimer, currentGraph, flowId, preview, sequenceIntervalMs, setPreviewRun, t, toast])
  runSequenceStepRef.current = runSequenceStep

  const startSequencePreview = useCallback(async () => {
    const source = sequenceSource
    if (!source || execLocked) return
    try {
      const total = await resolveSequenceTotal(source)
      if (total <= 0) {
        toast.warning(t('editor.sequenceNoImages'))
        return
      }
      const graph = currentGraph()
      const state: SequenceRun = { ...createPreviewSequenceState(total), source: { ...source, total }, running: true, paused: false, baseSignature: flowGraphSignature(graph) }
      setSequenceRun(state)
      sequenceRef.current = state
      clearSequenceTimer()
      sequenceTimer.current = window.setTimeout(() => runSequenceStepRef.current(), 0)
      toast.push(t('editor.sequenceStarted'), 'info', 1400)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }, [clearSequenceTimer, currentGraph, execLocked, resolveSequenceTotal, sequenceSource, t, toast])

  const pauseSequencePreview = useCallback(() => {
    clearSequenceTimer()
    sequenceAbort.current?.abort()
    sequenceAbort.current = null
    const state = sequenceRef.current
    if (!state) return
    const next = { ...state, paused: true }
    setSequenceRun(next)
    sequenceRef.current = next
  }, [clearSequenceTimer])

  const resumeSequencePreview = useCallback(() => {
    const state = sequenceRef.current
    if (!state) return
    const next = { ...state, running: true, paused: false }
    setSequenceRun(next)
    sequenceRef.current = next
    clearSequenceTimer()
    sequenceTimer.current = window.setTimeout(() => runSequenceStepRef.current(), 0)
  }, [clearSequenceTimer])

  const graphSignature = useMemo(() => flowGraphSignature({ nodes: graphNodes, edges: graphEdges }), [graphNodes, graphEdges])
  useEffect(() => {
    const state = sequenceRef.current
    if (state?.running && state.baseSignature !== graphSignature) stopSequencePreview(true)
  }, [graphSignature, stopSequencePreview])
  useEffect(
    () => () => {
      clearSequenceTimer()
      sequenceAbort.current?.abort()
      sequenceAbort.current = null
    },
    [clearSequenceTimer],
  )

  const clearResults = useCallback(() => {
    setClearedRunId(activeRun?.id ?? null)
    setPreviewRun(null)
    setPinnedRunId(null)
    setAllOverlays(false)
  }, [activeRun, setPreviewRun])

  const exportFlow = useCallback(async () => {
    try {
      await downloadFile(`/vision/flows/${flowId}/export`, `${meta.name || 'flow'}.flow.json`)
      toast.success(t('flows.exported', { name: meta.name }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }, [flowId, meta.name, toast, t])

  const toggleContinuous = useCallback(async () => {
    const next = !flow.data?.continuous
    if (next && dirty && !(await save())) return
    try {
      await continuous.mutateAsync({ flowId, running: next })
      toast.success(next ? t('editor.toast.continuousStarted') : t('editor.toast.continuousStopped'))
      if (next) setPinnedRunId(null)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }, [flow.data?.continuous, dirty, save, continuous, flowId, toast, t])

  const uploadScratch = useCallback(
    async (file: File) => {
      try {
        const info = await scratchUpload.mutateAsync({ flowId, file })
        updateSession(flowId, { scratch: info })
        toast.success(t('editor.toast.scratchUploaded', { name: info.name, w: info.width, h: info.height }))
      } catch (error) {
        toast.error(errorMessage(error))
      }
    },
    [scratchUpload, flowId, toast, t],
  )

  const doReset = useCallback(async () => {
    setAskReset(false)
    try {
      await clearRecent.mutateAsync(flowId)
      setPreviewRun(null)
      setPinnedRunId(null)
      setClearedRunId(null)
      toast.success(t('editor.toast.resetDone'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }, [clearRecent, flowId, setPreviewRun, toast, t])

  // ---- 範本：載入（取代畫布）／存為範本 ----
  const loadTemplate = useCallback(
    async ({ graph, name, missingSource }: { graph: FlowGraph; name: string; missingSource: boolean }) => {
      if (dirty && !(await confirm(t('templates.loadConfirm'), { confirmLabel: t('templates.loadAnyway') }))) return false
      pushHistory()
      restoreGraph(graph)
      setGalleryOpen(false)
      toast.success(t('templates.loaded', { name }))
      if (missingSource) toast.warning(t('templates.missingSource'))
      window.setTimeout(() => void fitView({ padding: 0.15, duration: 300 }), 50)
      return true
    },
    [dirty, pushHistory, restoreGraph, toast, t, fitView],
  )
  /** 載入範本時的節點 id 前綴：t1_、t2_…避免撞名。 */
  const templatePrefix = useMemo(() => {
    let n = 1
    while ([...payloads.current.keys()].some((id) => id.startsWith(`t${n}_`))) n += 1
    return `t${n}_`
  }, [nodes]) // eslint-disable-line react-hooks/exhaustive-deps


  // ---- 步驟右鍵選單 ----
  const duplicateNode = useCallback(
    (node: GraphNode) => {
      setNodes((list) => list.map((n) => ({ ...n, selected: n.id === node.id })))
      clipboard.current = { nodes: [{ ...node, position: { x: node.position?.x ?? 100, y: node.position?.y ?? 100 } }], edges: [] }
      paste()
    },
    [paste, setNodes],
  )
  const copyParams = useCallback(
    (node: GraphNode) => {
      setParamsClipboard({ type: node.type, params: JSON.parse(JSON.stringify(node.params ?? {})) as Record<string, unknown> })
      toast.success(t('nodeMenu.paramsCopied', { name: node.label || defs.get(node.type)?.label || node.id }))
    },
    [defs, toast, t],
  )
  const pasteParams = useCallback(
    (node: GraphNode) => {
      if (!paramsClipboard || paramsClipboard.type !== node.type) return
      pushHistory()
      patchNode(node.id, { params: { ...(node.params ?? {}), ...paramsClipboard.params } })
      toast.success(t('nodeMenu.paramsPasted'))
    },
    [paramsClipboard, pushHistory, patchNode, toast, t],
  )

  // ---- 鍵盤 ----
  const saveRef = useRef(save)
  saveRef.current = save
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const ctrl = event.ctrlKey || event.metaKey
      if (ctrl && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void saveRef.current()
        return
      }
      if (ctrl && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        setSearchOpen(true)
        window.setTimeout(() => searchInput.current?.focus(), 0)
        return
      }
      if (isTypingTarget(event.target)) return
      if (event.key === 'Escape') {
        if (searchOpen) setSearchOpen(false)
        else if (roiEditingKey) setRoiEditingKey(null)
        else if (templateKey) {
          setTemplateKey(null)
          setTemplateRegion(null)
        } else {
          setSelectedId(null)
          setNodes((list) => list.map((n) => (n.selected ? { ...n, selected: false } : n)))
        }
        return
      }
      if (ctrl && event.key.toLowerCase() === 'c') copySelection()
      else if (ctrl && event.key.toLowerCase() === 'v') {
        event.preventDefault()
        paste()
      } else if (ctrl && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) redo()
        else undo()
      } else if (ctrl && event.key.toLowerCase() === 'y') {
        event.preventDefault()
        redo()
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        const chosen = nodesRef.current.filter((n) => n.selected)
        if (chosen.length) {
          event.preventDefault()
          void deleteNodes(chosen.map((n) => n.id))
        } else {
          const chosenEdges = edgesRef.current.filter((e) => e.selected)
          if (chosenEdges.length) {
            event.preventDefault()
            pushHistory()
            const gone = new Set(chosenEdges.map((e) => e.id))
            setEdges((list) => list.filter((e) => !gone.has(e.id)))
            setDirty(true)
          }
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [copySelection, paste, undo, redo, deleteNodes, pushHistory, setEdges, setNodes, roiEditingKey, templateKey, searchOpen])

  // ---- 影像視窗 ----
  const selected = selectedId ? payloads.current.get(selectedId) : undefined
  const selectedTaskId = selectedId ? taskIdFromGroupNodeId(selectedId) : null
  const selectedGroup = selectedTaskId ? taskGroupById.get(selectedTaskId) ?? null : null
  const selectedDef = selected ? defs.get(selected.type) : undefined
  // ROI 編輯／範本框選一律在「輸入影像」上（ROI 座標系）。
  const effectiveMode = roiEditingKey || templateKey ? 'input' : viewMode
  const view = useMemo(
    () => resolveView(activeRun, selectedId, effectiveMode, allOverlays, graphEdges, defs, payloads.current, nodeOrder),
    [activeRun, selectedId, effectiveMode, allOverlays, graphEdges, defs, nodeOrder],
  )
  const outputView = useMemo(
    () => (split ? resolveView(activeRun, selectedId, 'output', false, graphEdges, defs, payloads.current, nodeOrder) : null),
    [split, activeRun, selectedId, graphEdges, defs, nodeOrder],
  )
  const compareView = useMemo(() => {
    if (roiEditingKey || templateKey) return null
    const otherMode = effectiveMode === 'input' ? 'output' : 'input'
    const other = resolveView(activeRun, selectedId, otherMode, false, graphEdges, defs, payloads.current, nodeOrder)
    return other.ref && other.ref !== view.ref ? other : null
  }, [activeRun, selectedId, effectiveMode, graphEdges, defs, nodeOrder, roiEditingKey, templateKey, view.ref])
  const gridPlace = useMemo(() => gridPlacement(gridLayout.count), [gridLayout.count])
  const imageNodeIds = useMemo(() => new Set(graphNodes.map((node) => node.id)), [graphNodes])
  const imagePortOptions = useMemo(() => {
    const out = new Map<string, { value: string; label: string }[]>()
    for (const node of graphNodes) {
      const ports = new Map<string, string>()
      for (const port of defs.get(node.type)?.outputs ?? []) {
        if (port.type === 'image') ports.set(port.key, port.label || port.key)
      }
      const report = activeRun?.nodes[node.id]
      for (const [key, value] of Object.entries(report?.outputs ?? {})) {
        if (isImageRef(value)) ports.set(key, ports.get(key) ?? key)
      }
      if (ports.size) out.set(node.id, Array.from(ports.entries()).map(([value, label]) => ({ value, label })))
    }
    return out
  }, [activeRun, defs, graphNodes])
  const gridNodeOptions = useMemo(
    () => graphNodes.filter((node) => imagePortOptions.has(node.id)).map((node) => ({ value: node.id, label: node.label || defs.get(node.type)?.label || node.id })),
    [defs, graphNodes, imagePortOptions],
  )
  const gridImages = useMemo(
    () => gridLayout.bindings.map((binding) => gridCellImage(activeRun, binding, imageNodeIds)),
    [activeRun, gridLayout.bindings, imageNodeIds],
  )
  const setGridBinding = useCallback((index: number, binding: GridBinding | null) => {
    setGridLayout((layout) => bindGridCell(layout, index, binding))
  }, [])
  const roiParam = roiEditingKey ? selectedDef?.params.find((p) => p.key === roiEditingKey) : undefined
  const roiValue = roiParam && selected ? (selected.params?.[roiParam.key] as Region | null | undefined) ?? null : null
  const badge = activeRun
    ? { text: `${t(`status.${activeRun.status}`)} · ${Math.round(activeRun.duration_ms)} ms${view.nodeId ? ` · ${payloads.current.get(view.nodeId)?.label || view.nodeId}` : ''}`, tone: (activeRun.status === 'ok' ? 'ok' : activeRun.status === 'ng' ? 'ng' : 'neutral') as 'ok' | 'ng' | 'neutral' }
    : null

  // 換步驟就結束 ROI 編輯（ROI 是那個步驟的參數）。
  useEffect(() => {
    setRoiEditingKey(null)
    setTemplateKey(null)
    setTemplateRegion(null)
  }, [selectedId])

  async function createTemplate() {
    if (!templateKey || !templateRegion || !view.ref || !selected) return
    try {
      const asset = await fromImage.mutateAsync({ ref: view.ref, region: templateRegion, name: templateName.trim() || undefined })
      patchNode(selected.id, { params: { ...(selected.params ?? {}), [templateKey]: asset.id } })
      toast.success(t('editor.toast.templateCreated', { name: asset.name }))
      setAskTemplateName(false)
      setTemplateKey(null)
      setTemplateRegion(null)
      setTemplateName('')
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  // ---- 版面拖曳 ----
  const onLeftResize = useResizer('x', (d) => setLayout((l) => ({ ...l, left: Math.min(420, Math.max(160, l.left + d)) })))
  const onRightResize = useResizer('x', (d) => setLayout((l) => ({ ...l, right: Math.min(560, Math.max(240, l.right - d)) })))
  const centerRef = useRef<HTMLDivElement>(null)
  const onCanvasResize = useResizer('y', (d) => {
    const h = centerRef.current?.clientHeight || 800
    setLayout((l) => ({ ...l, canvas: Math.min(0.8, Math.max(0.15, l.canvas - d / h)) }))
  })

  // ---- fps ----
  const fps = useMemo(() => {
    if (recentRuns.length < 2) return null
    const newest = recentRuns[0].finished_at ?? recentRuns[0].started_at
    const oldest = recentRuns[recentRuns.length - 1].finished_at ?? recentRuns[recentRuns.length - 1].started_at
    const span = newest - oldest
    return span > 0 ? (recentRuns.length - 1) / span : null
  }, [recentRuns])

  const nodeStatuses = useMemo(() => new Map(Object.entries(activeRun?.nodes ?? {}).map(([id, r]) => [id, r.status])), [activeRun])
  const onDisplayNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const ordinary: NodeChange[] = []
      const groupChanges: NodeChange[] = []
      for (const change of changes) {
        if ('id' in change && taskIdFromGroupNodeId(change.id)) groupChanges.push(change)
        else ordinary.push(change)
      }
      if (groupChanges.length) {
        setGroupPositions((current) => {
          const next = new Map(current)
          for (const change of groupChanges) {
            if (change.type === 'position' && change.position) next.set(change.id, { x: Math.round(change.position.x), y: Math.round(change.position.y) })
          }
          return next
        })
      }
      if (ordinary.length) {
        onNodesChange(ordinary)
        if (ordinary.some(isEdit)) setDirty(true)
      }
    },
    [onNodesChange],
  )
  const onDisplayEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const ordinary = changes.filter((change) => {
        if (!('id' in change)) return true
        const edge = displayView.edges.find((item) => item.id === change.id)
        return edge ? !taskIdFromGroupNodeId(edge.source) && !taskIdFromGroupNodeId(edge.target) : true
      })
      if (!ordinary.length) return
      onEdgesChange(ordinary)
      if (ordinary.some(isEdit)) setDirty(true)
    },
    [displayView.edges, onEdgesChange],
  )
  const onDisplayNodeDragStart = useCallback(
    (_event: MouseEvent | TouchEvent, node: Node) => {
      pushHistory()
      const taskId = taskIdFromGroupNodeId(node.id)
      groupDragStart.current = taskId ? { id: node.id, taskId, position: { x: node.position.x, y: node.position.y } } : null
    },
    [pushHistory],
  )
  const onDisplayNodeDragStop = useCallback(
    (_event: MouseEvent | TouchEvent, node: Node) => {
      const taskId = taskIdFromGroupNodeId(node.id)
      const start = groupDragStart.current
      groupDragStart.current = null
      if (!taskId || !start || start.id !== node.id) return
      setGroupPositions((current) => {
        const next = new Map(current)
        next.delete(node.id)
        return next
      })
      const delta = { x: Math.round(node.position.x - start.position.x), y: Math.round(node.position.y - start.position.y) }
      if (delta.x === 0 && delta.y === 0) return
      const graph = expandOnDrop(currentGraph(), taskId, delta)
      payloads.current = new Map(graph.nodes.map((item) => [item.id, item]))
      setNodes(toFlowNodes(graph, defs))
      setEdges(toFlowEdges(graph, defs))
      setSelectedId(`group:${taskId}`)
      setDirty(true)
    },
    [currentGraph, defs, setEdges, setNodes],
  )

  if (catalogue.isPending || flow.isPending) return <LoadingState />
  if (catalogue.isError || flow.isError) return <ErrorState error={flow.error ?? catalogue.error} onRetry={() => void flow.refetch()} />

  const isContinuous = Boolean(flow.data?.continuous)
  const viewerRoiProps = roiParam && selected
    ? { roi: roiValue, roiShapes: roiParam.shapes.length ? roiParam.shapes : undefined, onRoiChange: (region: Region) => patchNode(selected.id, { params: { ...(selected.params ?? {}), [roiParam.key]: region } }) }
    : templateKey
      ? { roi: templateRegion, roiShapes: ['rect' as const], onRoiChange: setTemplateRegion }
      : {}
  const optionBtn = (on: boolean) => `rounded px-1.5 py-0.5 ${on ? 'bg-brand-soft text-brand' : 'text-muted hover:text-content'}`

  return (
    <div className="flex h-full flex-col">
      <EditorToolbar
        flowId={flowId}
        onVersionRestored={() => { setDraft(flowId, null); void flow.refetch() }}
        name={meta.name}
        onNameChange={(name) => {
          setMeta({ ...meta, name })
          setDirty(true)
        }}
        dirty={dirty}
        readOnly={readOnly}
        saving={patch.isPending}
        onSave={() => void save()}
        problemCount={problemMap.size}
        execLocked={execLocked}
        lockHint={lockHint}
        flowDisabled={flow.data?.is_enabled === false}
        previewing={preview.isPending}
        onPreview={() => void doPreview()}
        sequenceAvailable={Boolean(sequenceSource)}
        sequenceRunning={Boolean(sequenceRun?.running)}
        sequencePaused={Boolean(sequenceRun?.paused)}
        sequenceLabel={sequenceRun ? t('editor.sequenceStatus', { current: previewSequenceStatusLabel(sequenceRun), ok: sequenceRun.ok, ng: sequenceRun.ng }) : t('editor.sequenceIdle')}
        sequenceIntervalMs={sequenceIntervalMs}
        onSequenceStart={() => void startSequencePreview()}
        onSequencePause={pauseSequencePreview}
        onSequenceResume={resumeSequencePreview}
        onSequenceStop={() => stopSequencePreview(true)}
        onSequenceIntervalChange={setSequenceIntervalMs}
        reuseImage={reuseImage}
        canReuse={Boolean(lastSourceRef)}
        onReuseChange={(value) => updateSession(flowId, { reuseImage: value })}
        scratch={scratch}
        uploadingScratch={scratchUpload.isPending}
        onUploadScratch={(file) => void uploadScratch(file)}
        onClearScratch={() => updateSession(flowId, { scratch: null })}
        isContinuous={isContinuous}
        continuousPending={continuous.isPending}
        onToggleContinuous={() => void toggleContinuous()}
        fpsLabel={isContinuous ? `${fps !== null ? t('editor.fps', { fps: fps.toFixed(1) }) : ''} ${flow.data?.stats.last_ms ? `· ${Math.round(flow.data.stats.last_ms)} ms` : ''}`.trim() : undefined}
        connected={stream.connected}
        onUndo={undo}
        onRedo={redo}
        onAutoLayout={autoLayout}
        taskGroupCount={taskGroups.length}
        collapsedTaskCount={collapsedTasks.size}
        onToggleTaskGroups={() => {
          storeCollapsedTasks(collapsedTasks.size ? new Set() : new Set(taskGroups.map((group) => group.task_id)))
          setSelectedId(null)
        }}
        resetting={clearRecent.isPending}
        onReset={() => setAskReset(true)}
        onClearResults={clearResults}
        onLoadTemplate={() => setGalleryOpen(true)}
        onSaveTemplate={() => setSaveTemplateOpen(true)}
        recipes={recipes.data?.items ?? []}
        onManageRecipes={() => setRecipesOpen(true)}
        notCommissioned={flow.data?.commissioned === false}
        onExport={() => void exportFlow()}
      />

      {missingSourceNode && !scratch ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-warning/40 bg-warning-soft px-3 py-1.5 text-xs text-warning" role="status" data-testid="no-source-banner">
          <span className="font-medium">{t('editor.noSourceBanner')}</span>
          <Select className="!h-7 !w-56 !py-0 text-xs" value="" aria-label={t('editor.noSourcePick')} placeholder={t('editor.noSourcePick')}
            options={(sourceList.data?.items ?? []).map((src) => ({ value: String(src.id), label: src.name }))}
            onChange={(e) => {
              const id = Number(e.target.value)
              if (!id) return
              pushHistory()
              patchNode(missingSourceNode.id, { params: { ...(missingSourceNode.params ?? {}), source_id: id } })
              toast.success(t('editor.sourcePicked'))
            }} data-testid="no-source-select" />
          <label className="cursor-pointer rounded-md border border-warning/40 px-2 py-0.5 hover:bg-warning/10">
            {t('editor.scratchUpload')}
            <input type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadScratch(f); e.target.value = '' }} />
          </label>
          <Link to="/sources" className="underline">{t('editor.manageSources')}</Link>
        </div>
      ) : null}

      {/* 三欄 */}
      <div className="flex min-h-0 flex-1">
        {/* 左：工具箱 + 步驟清單 */}
        <aside className="hidden shrink-0 flex-col border-r border-line bg-surface md:flex" style={{ width: layout.left }}>
          <div className="min-h-0 flex-[2]">
            <FavoriteTools catalogue={catalogue.data} favorites={favorites} onOpenPicker={() => setPickerOpen(true)} onInsert={insertAtCenter} onAddNote={insertNoteAtCenter} onToggleFavorite={toggleFavorite} />
          </div>
          <p className="border-y border-line px-3 py-1.5 text-xs font-semibold text-muted">{t('editor.nodeList')} <span className="tnum font-normal">({graphNodes.length})</span></p>
          <div className="min-h-0 flex-[3] overflow-hidden">
            <NodeList nodes={graphNodes} defs={defs} selectedId={selectedId} statuses={nodeStatuses} onSelect={focusNode} />
          </div>
        </aside>
        <div className="vs-resizer vs-resizer-x hidden md:block" onMouseDown={onLeftResize} />

        {/* 中：影像視窗（上）＋ 畫布（下） */}
        <div ref={centerRef} className="flex min-w-0 flex-1 flex-col">
          <div className="relative flex min-h-0 flex-1">
            {gridMode ? (
              <div
                className="grid min-h-0 min-w-0 flex-1 gap-1 bg-viewer p-1 pb-10"
                style={{ gridTemplateColumns: `repeat(${gridPlace.cols}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${gridPlace.rows}, minmax(0, 1fr))` }}
                data-testid="editor-grid-view"
              >
                {Array.from({ length: gridLayout.count }, (_, index) => {
                  const binding = gridLayout.bindings[index] ?? null
                  const ports = binding?.nodeId ? imagePortOptions.get(binding.nodeId) ?? [] : []
                  const image = gridImages[index]
                  return (
                    <div key={index} className="relative min-h-0 min-w-0 overflow-hidden rounded-md border border-line bg-viewer" data-testid="editor-grid-cell">
                      <ImageViewer proposals={proposals}
                        src={image?.ref ? imageUrl(image.ref, 1200) : null}
                        imageWidth={image?.width ?? 0}
                        imageHeight={image?.height ?? 0}
                        overlays={[]}
                        toolbar
                        className="h-full w-full"
                        stateKey={`flow:${flowId}:grid:${index}`}
                      />
                      <div className="absolute inset-x-1 bottom-1 z-20 grid grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)] gap-1 rounded-md bg-surface/90 p-1 backdrop-blur">
                        <Select
                          className="!h-7 !py-0 text-xs"
                          aria-label={t('editor.viewer.gridNode')}
                          value={binding?.nodeId ?? ''}
                          placeholder={t('editor.viewer.gridEmpty')}
                          options={gridNodeOptions}
                          onChange={(event) => {
                            const nodeId = event.target.value
                            const port = imagePortOptions.get(nodeId)?.[0]?.value ?? ''
                            setGridBinding(index, nodeId && port ? { nodeId, port } : null)
                          }}
                        />
                        <Select
                          className="!h-7 !py-0 text-xs"
                          aria-label={t('editor.viewer.gridPort')}
                          value={binding?.port ?? ''}
                          placeholder={t('editor.viewer.gridPort')}
                          disabled={!binding?.nodeId}
                          options={ports}
                          onChange={(event) => {
                            if (!binding?.nodeId) return
                            setGridBinding(index, event.target.value ? { nodeId: binding.nodeId, port: event.target.value } : null)
                          }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <>
                <div className="relative min-w-0 flex-1" data-testid="viewer-main">
                  <ImageViewer proposals={proposals}
                    src={view.ref ? imageUrl(view.ref, 1600) : null}
                    imageWidth={view.width}
                    imageHeight={view.height}
                    overlays={roiEditingKey || templateKey ? [] : view.overlays}
                    compareSrc={compareView?.ref ? imageUrl(compareView.ref, 1600) : null}
                    compareWidth={compareView?.width ?? 0}
                    compareHeight={compareView?.height ?? 0}
                    stateKey={`flow:${flowId}:main`}
                    badge={badge}
                    toolbar
                    className="h-full w-full"
                    {...viewerRoiProps}
                  />
                  {split ? <span className="pointer-events-none absolute left-2 top-16 rounded bg-black/50 px-1.5 py-0.5 text-[11px] text-white/90">{t('editor.viewer.before')}</span> : null}
                </div>
                {split && outputView ? (
                  <div className="relative min-w-0 flex-1 border-l border-line" data-testid="viewer-after">
                    {/* 沒有影像輸出的步驟（blob／比較…）：與工具頁一致，右邊顯示「標記疊在輸入影像上」而不是空白 */}
                    <ImageViewer proposals={proposals}
                      src={outputView.ref ? imageUrl(outputView.ref, 1600) : null}
                      imageWidth={outputView.width}
                      imageHeight={outputView.height}
                      overlays={outputView.hasOutput ? [] : outputView.overlays}
                      toolbar
                      stateKey={`flow:${flowId}:after`}
                      className="h-full w-full"
                    />
                    <span className="pointer-events-none absolute left-2 top-16 rounded bg-black/50 px-1.5 py-0.5 text-[11px] text-white/90">{t('editor.viewer.after')}{outputView.hasOutput || !outputView.ref ? '' : ` · ${t('tool.overlaysOnInput')}`}</span>
                  </div>
                ) : null}
              </>
            )}
            {/* 影像視窗的顯示選項：要壓在宮格每格底部的節點選單（z-20）之上，否則切到宮格後就按不到「執行前後」與退出宮格 */}
            <div className="absolute bottom-2 left-2 z-30 flex items-center gap-1 rounded-lg border border-line bg-surface/90 px-1.5 py-1 text-[11px] backdrop-blur" data-testid="viewer-options">
              <Camera size={12} className="text-muted" />
              <button type="button" className={optionBtn(effectiveMode === 'input' && !split && !gridMode)} disabled={!view.hasInput || split || gridMode} onClick={() => setViewMode('input')}>
                {t('editor.viewer.showInput')}
              </button>
              <button type="button" className={optionBtn(effectiveMode === 'output' && !split && !gridMode)} disabled={!view.hasOutput || split || gridMode} onClick={() => setViewMode('output')}>
                {t('editor.viewer.showOutput')}
              </button>
              <button type="button" className={`flex items-center gap-1 ${optionBtn(split && !gridMode)}`} disabled={gridMode} onClick={() => setSplit((v) => !v)} title={t('editor.viewer.splitHint')} data-testid="btn-split">
                <Columns2 size={12} /> {t('editor.viewer.split')}
              </button>
              <button type="button" className={`flex items-center gap-1 ${optionBtn(gridMode)}`} onClick={() => setGridMode((value) => !value)} title={t('editor.viewer.gridHint')} data-testid="btn-grid-view">
                <LayoutGrid size={12} /> {t('editor.viewer.gridView')}
              </button>
              {gridMode ? GRID_COUNTS.map((count) => (
                <button key={count} type="button" className={optionBtn(gridLayout.count === count)} onClick={() => setGridLayout((layout) => setGridCount(layout, count as GridCount))}>
                  {count}
                </button>
              )) : null}
              <span className="mx-0.5 h-3.5 w-px bg-line" />
              <button type="button" className={`flex items-center gap-1 ${optionBtn(allOverlays && !gridMode)}`} disabled={gridMode} onClick={() => setAllOverlays((v) => !v)} title={t('editor.viewer.allOverlays')}>
                <Layers size={12} /> {t('editor.viewer.allOverlays')}
              </button>
              {pinnedRunId ? (
                <>
                  <span className="mx-0.5 h-3.5 w-px bg-line" />
                  <button type="button" className="flex items-center gap-1 rounded px-1.5 py-0.5 text-muted hover:text-content" onClick={() => setPinnedRunId(null)} title={t('editor.viewer.viewingRun', { id: pinnedRunId.slice(0, 8) })}>
                    <RotateCcw size={12} /> {t('editor.viewer.latest')}
                  </button>
                </>
              ) : null}
              {!view.ref && !activeRun ? <span className="ml-1 text-subtle">{t('editor.viewer.empty')}</span> : null}
            </div>
            {templateKey ? (
              <div className="absolute right-2 bottom-2 flex items-center gap-1.5 rounded-lg border border-brand bg-surface/95 px-2 py-1 text-[11px]">
                <span className="text-brand">{t('editor.viewer.templateHint')}</span>
                <Button size="xs" variant="primary" icon={<Check size={12} />} disabled={!templateRegion} onClick={() => setAskTemplateName(true)}>
                  {t('editor.viewer.templateCreate')}
                </Button>
              </div>
            ) : null}
            {roiEditingKey ? (
              <div className="absolute right-2 bottom-2 flex items-center gap-1.5 rounded-lg border border-brand bg-surface/95 px-2 py-1 text-[11px]">
                <span className="text-brand">{t('editor.viewer.roiEditing')}</span>
                <Button size="xs" variant="primary" icon={<Check size={12} />} onClick={() => setRoiEditingKey(null)}>{t('editor.viewer.done')}</Button>
              </div>
            ) : null}
          </div>
          <div className="vs-resizer vs-resizer-y" onMouseDown={onCanvasResize} />
          <div className="relative min-h-60" style={{ height: `${layout.canvas * 100}%` }}>
            {searchOpen ? (
              <div className="absolute left-2 top-2 z-20 w-72 rounded-lg border border-line bg-surface p-2 shadow-lg" data-testid="node-search">
                <input
                  ref={searchInput}
                  className="input !py-1.5 text-sm"
                  value={searchQuery}
                  placeholder={t('editor.search.placeholder')}
                  aria-label={t('editor.search.label')}
                  onChange={(event) => { setSearchQuery(event.target.value); setSearchActive(0) }}
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                      event.preventDefault()
                      setSearchOpen(false)
                    } else if (event.key === 'Enter' && searchResults.length) {
                      event.preventDefault()
                      const index = searchActive % searchResults.length
                      centerSearchNode(searchResults[index].node.id)
                      setSearchActive((index + 1) % searchResults.length)
                    }
                  }}
                  data-testid="node-search-input"
                />
                <div className="mt-1 max-h-48 overflow-y-auto text-xs" data-testid="node-search-results">
                  {searchQuery.trim() && searchResults.length === 0 ? <p className="px-2 py-1.5 text-subtle">{t('editor.search.empty')}</p> : null}
                  {searchResults.map((result, index) => (
                    <button
                      key={result.node.id}
                      type="button"
                      className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left hover:bg-surface-muted ${index === searchActive ? 'bg-brand-soft text-brand' : ''}`}
                      onMouseEnter={() => setSearchActive(index)}
                      onClick={() => { setSearchActive(index); centerSearchNode(result.node.id) }}
                      data-testid="node-search-result"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{result.title}</span>
                        <span className="block truncate text-[11px] text-muted">{result.node.id} · {result.tool}</span>
                      </span>
                      {result.matches[0] ? <span className="max-w-24 truncate text-[11px] text-subtle">{result.matches[0]}</span> : null}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <FlowCanvas
              interaction={interaction}
              onInteractionChange={(mode) => { setInteraction(mode); storeInteractionMode(mode) }}
              onAutoLayout={autoLayout}
              nodes={displayView.nodes}
              edges={displayView.edges}
              onNodesChange={onDisplayNodesChange}
              onEdgesChange={onDisplayEdgesChange}
              onConnect={onConnect}
              onConnectEnd={onConnectEnd}
              isValidConnection={isValidConnection}
              onNodeClick={(_e, node) => {
                setSelectedId(node.id)
                setRightTab((tab) => (tab === 'results' && activeRun?.nodes[node.id] ? 'results' : 'inspector'))
              }}
              onNodeDoubleClick={(_e, node) => {
                // 雙擊步驟卡片直接開工具頁（與右鍵「開啟工具頁」同一路徑：離開時 cleanup 會把草稿寫進 store）
                setSelectedId(node.id)
                if (node.type === 'tool' && payloads.current.has(node.id)) navigate(`/flows/${flowId}/tools/${encodeURIComponent(node.id)}`)
                else if (node.type === 'group') expandTask(taskIdFromGroupNodeId(node.id) ?? '')
                else setRightTab('results')
              }}
              onNodeDragStart={onDisplayNodeDragStart}
              onNodeDragStop={onDisplayNodeDragStop}
              onNodeContextMenu={(e, node) => {
                e.preventDefault()
                const payload = payloads.current.get(node.id)
                if (!payload) return
                setSelectedId(node.id)
                setNodes((list) => list.map((n) => ({ ...n, selected: n.id === node.id })))
                setNodeMenu({ x: e.clientX, y: e.clientY, node: payload })
              }}
              onPaneClick={() => { setSelectedId(null); setNodeMenu(null) }}
              onDragOver={onDragOver}
              onDrop={onDrop}
            />
            {meta.description.trim() ? (
              <div className="absolute right-2 top-2 z-20 max-w-sm rounded-lg border border-line bg-surface/95 text-xs shadow-lg backdrop-blur" data-testid="flow-description-panel">
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-heading"
                  onClick={() => setDescriptionCollapsed((value) => !value)}
                  aria-expanded={!descriptionCollapsed}
                >
                  <FileText size={14} className="shrink-0 text-muted" />
                  <span className="min-w-0 flex-1 truncate font-semibold">{t('editor.descriptionPanel.title')}</span>
                  {descriptionCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </button>
                {descriptionCollapsed ? null : (
                  <p className="max-h-40 overflow-y-auto whitespace-pre-wrap px-2.5 pb-2 text-muted">{meta.description}</p>
                )}
              </div>
            ) : null}
          </div>
        </div>
        <div className="vs-resizer vs-resizer-x hidden lg:block" onMouseDown={onRightResize} />

        {/* 右：側欄（設定 / 結果） */}
        <aside className="hidden shrink-0 flex-col border-l border-line bg-surface lg:flex" style={{ width: layout.right }} data-testid="inspector-pane">
          <Tabs
            size="sm"
            value={rightTab}
            onChange={setRightTab}
            tabs={[
              { value: 'inspector', label: t('editor.inspector') },
              { value: 'results', label: t('editor.results'), badge: activeRun ? <StatusBadge status={activeRun.status} className="ml-1 !px-1.5 !py-0 !text-[10px]" /> : undefined },
            ]}
          />
          <div className="min-h-0 flex-1 overflow-y-auto">
            {rightTab === 'inspector' ? (
              selectedCount > 1 ? (
                <div className="space-y-3 p-3" data-testid="multi-select">
                  <p className="text-sm font-medium">{t('editor.multiSelected', { count: selectedCount })}</p>
                  <p className="text-xs text-muted">{t('editor.multiSelectedHint')}</p>
                  <Button size="sm" variant="danger" onClick={() => void deleteNodes(nodesRef.current.filter((n) => n.selected).map((n) => n.id))}>
                    {t('editor.deleteSelected', { count: selectedCount })}
                  </Button>
                </div>
              ) : selectedGroup ? (
                <TaskGroupInspector flowId={flowId} group={selectedGroup} nodes={graphNodes} defs={defs} onExpand={expandTask} onFocus={focusNode} />
              ) : selected ? (
                <Inspector flowId={flowId} node={selected} definition={selectedDef} edges={graphEdges} graph={{ nodes: graphNodes, edges: graphEdges }} defs={defs} onChange={(p) => patchNode(selected.id, p)} onGraphChange={applyGraphChange} onDelete={() => void deleteNodes([selected.id])} />
              ) : (
                <div className="space-y-3 p-3">
                  <p className="text-xs text-muted">{t('editor.selectNodeHint')}</p>
                  <div className="space-y-3">
                    <p className="text-xs font-semibold text-heading">{t('editor.flowSettings')}</p>
                    <TextInput
                      label={t('common.description')}
                      value={meta.description}
                      onChange={(e) => {
                        setMeta({ ...meta, description: e.target.value })
                        setDirty(true)
                      }}
                    />
                    <div className="grid grid-cols-2 gap-2">
                      <TextInput
                        label={t('flows.continuousInterval')}
                        type="number"
                        min={0}
                        value={String(flow.data?.continuous_interval_ms ?? 0)}
                        disabled={readOnly}
                        onChange={(e) => void patchFlowSettings({ continuous_interval_ms: Number(e.target.value) || 0 })}
                      />
                      <TextInput
                        label={t('flow.timeoutS')}
                        type="number"
                        min={0}
                        value={String(flow.data?.timeout_s ?? 0)}
                        disabled={readOnly}
                        onChange={(e) => void patchFlowSettings({ timeout_s: Number(e.target.value) || 0 })}
                      />
                      <TextInput
                        label={t('flow.concurrency')}
                        type="number"
                        min={1}
                        step={1}
                        value={String(flow.data?.concurrency ?? 1)}
                        disabled={readOnly}
                        onChange={(e) => void patchFlowSettings({ concurrency: Math.max(1, Number(e.target.value) || 1) })}
                      />
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1">
                      {/* 複製出來的流程預設停用；不用回列表就能在這裡開啟 */}
                      <Checkbox
                        label={t('flows.enabledToggle')}
                        hint={flow.data?.is_enabled === false ? t('editor.flowDisabledHint') : undefined}
                        checked={flow.data?.is_enabled !== false}
                        disabled={readOnly}
                        onChange={(v) => void patchFlowSettings({ is_enabled: v })}
                      />
                      <Checkbox
                        label={t('flow.stopOnNg')}
                        checked={flow.data?.stop_on_ng === true}
                        disabled={readOnly}
                        onChange={(v) => void patchFlowSettings({ stop_on_ng: v })}
                      />
                    </div>
                  </div>
                  <div className="space-y-3 border-t border-line pt-3">
                    <p className="text-xs font-semibold text-heading">{t('editor.moreSettings')}</p>
                    <FlowSettingsDialogs
                      flowId={flowId}
                      flow={flow.data}
                      boardOutputNames={boardOutputNames}
                      boardImageNodes={boardImageNodes}
                      readOnly={readOnly}
                      saving={patch.isPending}
                      onSaveBoard={(cfg) => void patchFlowSettings({ board: cfg }, () => toast.success(t('board.settings.saved')))}
                      onSaveComm={(rules) => void patchFlowSettings({ comm: rules }, () => toast.success(t('comm.saved')))}
                    />
                  </div>
                </div>
              )
            ) : (
              <div>
                <RunErrorBlock run={activeRun} order={nodeOrder} payloads={payloads.current} onGoto={focusNode} />
                <RunWarnings run={activeRun} />
                <p className="border-b border-line px-3 py-1.5 text-xs font-semibold text-muted">{t('editor.result.recentRuns')}</p>
                <RecentRunsTable
                  runs={previewRun && !recentRuns.some((r) => r.id === previewRun.id) ? [previewRun, ...recentRuns].slice(0, 8) : recentRuns}
                  selectedId={activeRun?.id ?? null}
                  onSelect={(run) => { setClearedRunId(null); setPinnedRunId(run.id) }}
                />
                <SpanTimingCard run={activeRun} nodes={graphNodes} edges={graphEdges} />
                <p className="border-y border-line px-3 py-1.5 text-xs font-semibold text-muted">
                  {selected ? selected.label || selectedDef?.label || selected.id : t('editor.results')}
                </p>
                <NodeResult report={selected ? activeRun?.nodes[selected.id] : undefined} run={activeRun} />
              </div>
            )}
          </div>
        </aside>
      </div>

      <Modal
        open={askTemplateName}
        onClose={() => setAskTemplateName(false)}
        title={t('editor.viewer.templateCreate')}
        size="sm"
        footer={
          <>
            <Button onClick={() => setAskTemplateName(false)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={fromImage.isPending} onClick={() => void createTemplate()}>{t('common.create')}</Button>
          </>
        }
      >
        <TextInput label={t('editor.viewer.templateName')} autoFocus value={templateName} onChange={(e) => setTemplateName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void createTemplate()} />
      </Modal>
      {confirmDialog}
      {saveConflictDialog}
      <ConfirmDialog open={askReset} onClose={() => setAskReset(false)} onConfirm={() => void doReset()} title={t('editor.reset')} message={t('editor.resetConfirm')} confirmLabel={t('editor.reset')} danger loading={clearRecent.isPending} />
      <ToolPicker open={pickerOpen} onClose={() => setPickerOpen(false)} catalogue={catalogue.data}
        favorites={favorites} onToggleFavorite={toggleFavorite} onPick={insertAtCenter} />
      <TemplateGallery open={galleryOpen} onClose={() => setGalleryOpen(false)} mode="load" prefix={templatePrefix} onPick={loadTemplate} />
      <RecipeDrawer open={recipesOpen} onClose={() => setRecipesOpen(false)} flowId={flowId} readOnly={readOnly} />
      <SaveTemplateModal open={saveTemplateOpen} onClose={() => setSaveTemplateOpen(false)} graph={currentGraph} defaultName={meta.name} />
      <NodeContextMenu
        menu={nodeMenu}
        onClose={() => setNodeMenu(null)}
        onOpenTool={(node) => navigate(`/flows/${flowId}/tools/${encodeURIComponent(node.id)}`)}
        onRunTo={execLocked ? undefined : (node) => void doPreview(node.id)}
        onDuplicate={duplicateNode}
        onCollapseTask={(node) => collapseTask(node.meta?.inspect?.task_id ?? '')}
        onToggleEnabled={(node) => patchNode(node.id, { enabled: node.enabled === false })}
        onDelete={(node) => void deleteNodes([node.id])}
        onCopyParams={copyParams}
        paramsClipboardType={paramsClipboard?.type ?? null}
        onPasteParams={pasteParams}
      />
    </div>
  )
}

export function FlowEditorPage() {
  const { flowId } = useParams<{ flowId: string }>()
  const id = Number(flowId)
  if (!flowId || Number.isNaN(id)) return null
  return (
    <ReactFlowProvider>
      <EditorInner key={id} flowId={id} />
    </ReactFlowProvider>
  )
}
