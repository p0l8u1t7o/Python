/**
 * 流程編輯器（FlowEditorPage）：頂列（EditorToolbar）＋ 工具箱／步驟清單 ＋ 影像視窗（ImageViewer）＋ 畫布（FlowCanvas）＋ 側欄（Inspector／ResultsPanel）。
 *
 * 幾個刻意的做法（見 docs/workflow-design.html 第 7/10 節）：
 * - payloads ref 是編輯器自己那份真相，React Flow 的 data 只是投影。
 * - 圖只在 flow.version 變時重載；存檔後自己標記已載入，避免畫布被重設。
 * - isEdit 只認 resizing=true 的 dimensions change。
 * - 鍵盤監聽用 ref 讀最新 nodes/edges；undo 歷史放 ref；deleteKeyCode={null}。
 * - 執行結果由 SSE（useFlowStream）與試跑回應餵進來，步驟狀態用 useMemo 派生。
 * - 未儲存的圖、暫存影像、最近試跑結果放在 lib/flowDraft.ts 的工作階段 store：離開頁面時寫入草稿，
 *   回來（或從工具頁回來）時若伺服器版本沒變就用草稿，所以編輯器 ⇄ 工具頁之間的變更不會丟。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useBlocker, useNavigate, useParams } from 'react-router-dom'
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
import { Camera, Check, Columns2, Layers, RotateCcw } from 'lucide-react'

import { EditorToolbar } from '@/components/editor/EditorToolbar'
import { FlowCanvas, readInteractionMode, storeInteractionMode, type InteractionMode } from '@/components/editor/FlowCanvas'
import { Inspector } from '@/components/editor/Inspector'
import { NodeContextMenu, type NodeMenuState } from '@/components/editor/NodeContextMenu'
import { NodeList } from '@/components/editor/NodeList'
import { FavoriteTools, ToolPicker, readFavorites, writeFavorites } from '@/components/editor/ToolPalette'
import { NodeResult, RecentRunsTable, RunErrorBlock, RunWarnings } from '@/components/editor/ResultsPanel'
import { DRAG_MIME, HISTORY_LIMIT, computeLayout, edgeProps, graphFrom, isTypingTarget, nextNodeId, nodeDataFrom, toFlowEdges, toFlowNode, toFlowNodes, type ToolNodeData } from '@/components/editor/graphMapping'
import { useResizer } from '@/components/editor/useResizer'
import { RecipeDrawer } from '@/components/recipes/RecipeDrawer'
import { SaveTemplateModal, TemplateGallery } from '@/components/templates/TemplateGallery'
import { Button, Checkbox, ConfirmDialog, ErrorState, LoadingState, Modal, Select, StatusBadge, Tabs, TextInput } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { downloadFile, imageUrl } from '@/lib/api'
import { useConfirm } from '@/lib/useConfirm'
import { errorMessage } from '@/lib/errors'
import { getSession, setDraft, updateSession, useFlowSession } from '@/lib/flowDraft'
import { useRegisterAssistantContext } from '@/lib/assistantContext'
import { useFlowStream, type StreamEvent } from '@/lib/flowStream'
import { DECORATION_TYPES, checkConnection, graphProblems } from '@/lib/graphValidation'
import { useAssetMutations, useClearRecent, useContinuous, useFlow, useFlowMutations, usePreviewFlow, useRecentRuns, useRecipes, useScratchImage, useSources, useToolTypes } from '@/lib/queries'
import { isImageRef, type FlowGraph, type GraphEdge, type GraphNode, type NodeReport, type Overlay, type Region, type RunReport, type ToolTypeDef } from '@/lib/types'
import { isLockHolder, useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const LAYOUT_KEY = 'vs.editorLayout'
const FOCUS_OPTIONS = { duration: 300, maxZoom: 1.2 }

interface LayoutState {
  left: number
  right: number
  /** 畫布高度佔中欄比例 */
  canvas: number
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

export function firstImageOutput(report: NodeReport | undefined): { ref: string | null; width: number; height: number } | null {
  if (!report) return null
  for (const [key, value] of Object.entries(report.outputs)) {
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
    const value = run.nodes[edge.source]?.outputs[edge.source_handle || '']
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
  let overlays: Overlay[] = mode === 'input' && input !== null ? [] : useInput || !input ? report.overlays : []
  if (allOverlays) {
    overlays = order.flatMap((id) => run.nodes[id]?.overlays ?? [])
  }
  return { ref: chosen.ref, width: chosen.width, height: chosen.height, overlays, nodeId, hasInput: input !== null, hasOutput: output !== null }
}

/** image_source 步驟的輸出 ref（給「用上次影像重跑」）。 */
export function sourceRefOf(run: RunReport | null, payloads: Map<string, GraphNode>): string | null {
  if (!run) return null
  for (const [id, report] of Object.entries(run.nodes)) {
    if (payloads.get(id)?.type !== 'image_source') continue
    const value = report.outputs.image
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
  const toast = useToast()
  const auth = useAuth()
  const { screenToFlowPosition, fitView } = useReactFlow()

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
  const [allOverlays, setAllOverlays] = useState(false)
  const [pinnedRunId, setPinnedRunId] = useState<string | null>(null)
  const [roiEditingKey, setRoiEditingKey] = useState<string | null>(null)
  const [templateKey, setTemplateKey] = useState<string | null>(null)
  const [templateRegion, setTemplateRegion] = useState<Region | null>(null)
  const [templateName, setTemplateName] = useState('')
  const [askTemplateName, setAskTemplateName] = useState(false)
  const [askReset, setAskReset] = useState(false)
  const [interaction, setInteraction] = useState<InteractionMode>(readInteractionMode)
  const [galleryOpen, setGalleryOpen] = useState(false)
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false)
  const [nodeMenu, setNodeMenu] = useState<NodeMenuState | null>(null)
  const [paramsClipboard, setParamsClipboard] = useState<{ type: string; params: Record<string, unknown> } | null>(null)
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
  const history = useRef<FlowGraph[]>([])
  const clipboard = useRef<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null)
  const loadedFor = useRef('')

  const currentGraph = useCallback(() => graphFrom(nodesRef.current, edgesRef.current, payloads.current), [])

  // ---- 載入（只在 version 變時；草稿版本相符就用草稿） ----
  useEffect(() => {
    const data = flow.data
    if (!data || defs.size === 0) return
    const key = `${data.id}:${data.version}`
    if (loadedFor.current === key) return
    loadedFor.current = key
    const draft = getSession(flowId).draft
    const source = draft && draft.baseVersion === data.version ? draft : null
    const graph = source ? source.graph : data.graph
    payloads.current = new Map((graph.nodes ?? []).map((n) => [n.id, n]))
    setNodes(toFlowNodes(graph, defs))
    setEdges(toFlowEdges(graph, defs))
    setMeta(source ? { name: source.name, description: source.description } : { name: data.name, description: data.description })
    setDirty(source ? source.dirty : false)
    history.current = []
  }, [flow.data, defs, setNodes, setEdges, flowId])

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
  const activeRun = useMemo<RunReport | null>(() => {
    if (pinnedRunId) {
      if (previewRun?.id === pinnedRunId) return previewRun
      return recentRuns.find((r) => r.id === pinnedRunId) ?? previewRun ?? recentRuns[0] ?? null
    }
    const latestRun = recentRuns[0] ?? null
    if (!previewRun) return latestRun
    if (!latestRun || previewRun.started_at >= latestRun.started_at) return previewRun
    return latestRun
  }, [pinnedRunId, previewRun, recentRuns])

  const graphNodes = useMemo(() => nodes.map((n) => payloads.current.get(n.id)).filter((p): p is GraphNode => Boolean(p)), [nodes])
  const graphEdges = useMemo<GraphEdge[]>(() => edges.map((e) => ({ id: e.id, source: e.source, target: e.target, source_handle: e.sourceHandle ?? '', target_handle: e.targetHandle ?? '' })), [edges])
  //: 沒選影像來源又沒暫存影像 → 試執行一定失敗；橫幅直接讓人選來源（不用先找到取像步驟再進工具頁）
  const missingSourceNode = useMemo(() => graphNodes.find((n) => n.type === 'image_source' && !n.params?.source_id) ?? null, [graphNodes])
  const sourceList = useSources()
  const nodeOrder = useMemo(() => topoOrder(graphNodes, graphEdges), [graphNodes, graphEdges])
  const selectedCount = useMemo(() => nodes.filter((n) => n.selected).length, [nodes])

  const problemMap = useMemo(() => graphProblems(graphNodes, graphEdges, defs), [graphNodes, graphEdges, defs])

  // ---- 步驟裝飾：只在有變的步驟回新物件 ----
  const decoratedNodes = useMemo(
    () =>
      nodes.map((node) => {
        const data = node.data as ToolNodeData
        const report = activeRun?.nodes[node.id]
        const problems = problemMap.get(node.id)
        const problem = problems?.length ? t(`editor.validation.${problems[0].code}`, problems[0].values) : undefined
        const isRunning = running && data.enabled && node.type === 'tool'
        if (data.report === report && data.problem === problem && Boolean(data.running) === isRunning) return node
        return { ...node, data: { ...data, report, problem, running: isRunning } }
      }),
    [nodes, activeRun, problemMap, running, t],
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
    history.current.push(currentGraph())
    if (history.current.length > HISTORY_LIMIT) history.current.shift()
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
    const previous = history.current.pop()
    if (previous) restoreGraph(previous)
  }, [restoreGraph])

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
      payloads.current.set(id, payload)
      setNodes((current) => [...current.map((n) => ({ ...n, selected: false })), { ...toFlowNode(payload, def), selected: true }])
      setSelectedId(id)
      setRightTab('inspector')
      setDirty(true)
    },
    [pushHistory, setNodes],
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

  const deleteNodes = useCallback(
    (ids: string[]) => {
      if (!ids.length) return
      pushHistory()
      const gone = new Set(ids)
      for (const id of ids) payloads.current.delete(id)
      setNodes((list) => list.filter((n) => !gone.has(n.id)))
      setEdges((list) => list.filter((e) => !gone.has(e.source) && !gone.has(e.target)))
      setSelectedId((cur) => (cur && gone.has(cur) ? null : cur))
      setDirty(true)
    },
    [pushHistory, setNodes, setEdges],
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
      setSelectedId(id)
      setNodes((list) => list.map((n) => ({ ...n, selected: n.id === id })))
      window.setTimeout(() => void fitView({ nodes: [{ id }], ...FOCUS_OPTIONS }), 30)
    },
    [setNodes, fitView],
  )

  // ---- 存檔／執行 ----
  const save = useCallback(async (): Promise<boolean> => {
    if (readOnly) {
      toast.warning(t('flows.readOnlyHint'))
      return false
    }
    if (problemMap.size > 0) toast.warning(t('editor.toast.validationWarning', { count: problemMap.size }))
    try {
      await patch.mutateAsync(
        { id: flowId, name: meta.name.trim() || t('editor.untitled'), description: meta.description, graph: currentGraph() },
        // 回應的新 version 會觸發「重載圖」effect；先標記為已載入，畫布才不會被重設。
        { onSuccess: (saved) => { loadedFor.current = `${saved.id}:${saved.version}` } },
      )
      setDirty(false)
      toast.success(t('editor.toast.saved'))
      return true
    } catch (error) {
      toast.error(errorMessage(error))
      return false
    }
  }, [readOnly, problemMap.size, patch, flowId, meta, currentGraph, toast, t])

  const lastSourceRef = useMemo(() => sourceRefOf(activeRun, payloads.current), [activeRun])
  //: 全域 AI 助手：在編輯器內可直接請助手修改目前畫布（套用走復原堆疊）
  useRegisterAssistantContext({
    kind: 'flow_editor', flowId, flowName: meta.name, imageRef: lastSourceRef, execLocked, getGraph: currentGraph,
    applyGraph: (g, why) => { pushHistory(); restoreGraph(g); toast.success(why ? `${t('agent.applied')}：${why}` : t('agent.applied')) },
  }, [flowId, meta.name, lastSourceRef, execLocked])
  /** 固定的來源影像：暫存影像優先，其次「用上次影像重跑」。 */
  const pinnedRef = scratch?.ref ?? (reuseImage ? lastSourceRef : null)

  const doPreview = useCallback(async () => {
    try {
      const report = await preview.mutateAsync({ flowId, graph: currentGraph(), reuse_image_ref: pinnedRef })
      setPreviewRun(report)
      setPinnedRunId(null)
      toast.push(t('editor.toast.previewDone', { status: t(`status.${report.status}`), ms: Math.round(report.duration_ms) }), report.status === 'ok' ? 'success' : report.status === 'ng' ? 'warning' : 'error', 1500)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }, [preview, flowId, currentGraph, pinnedRef, setPreviewRun, toast, t])

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
      if (isTypingTarget(event.target)) return
      if (event.key === 'Escape') {
        if (roiEditingKey) setRoiEditingKey(null)
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
        undo()
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        const chosen = nodesRef.current.filter((n) => n.selected)
        if (chosen.length) {
          event.preventDefault()
          deleteNodes(chosen.map((n) => n.id))
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
  }, [copySelection, paste, undo, deleteNodes, pushHistory, setEdges, setNodes, roiEditingKey, templateKey])

  // ---- 影像視窗 ----
  const selected = selectedId ? payloads.current.get(selectedId) : undefined
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
        onAutoLayout={autoLayout}
        resetting={clearRecent.isPending}
        onReset={() => setAskReset(true)}
        onBatchTest={() => navigate(`/batch?flow=${flowId}${dirty ? '&draft=1' : ''}`)}
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
            <div className="relative min-w-0 flex-1" data-testid="viewer-main">
              <ImageViewer
                src={view.ref ? imageUrl(view.ref, 1600) : null}
                imageWidth={view.width}
                imageHeight={view.height}
                overlays={roiEditingKey || templateKey ? [] : view.overlays}
                badge={badge}
                toolbar
                className="h-full w-full"
                {...viewerRoiProps}
              />
              {split ? <span className="pointer-events-none absolute left-2 top-8 rounded bg-black/50 px-1.5 py-0.5 text-[11px] text-white/90">{t('editor.viewer.before')}</span> : null}
            </div>
            {split && outputView ? (
              <div className="relative min-w-0 flex-1 border-l border-line" data-testid="viewer-after">
                {/* 沒有影像輸出的步驟（blob／比較…）：與工具頁一致，右邊顯示「標記疊在輸入影像上」而不是空白 */}
                <ImageViewer
                  src={outputView.ref ? imageUrl(outputView.ref, 1600) : null}
                  imageWidth={outputView.width}
                  imageHeight={outputView.height}
                  overlays={outputView.hasOutput ? [] : outputView.overlays}
                  toolbar
                  className="h-full w-full"
                />
                <span className="pointer-events-none absolute left-2 top-8 rounded bg-black/50 px-1.5 py-0.5 text-[11px] text-white/90">{t('editor.viewer.after')}{outputView.hasOutput || !outputView.ref ? '' : ` · ${t('tool.overlaysOnInput')}`}</span>
              </div>
            ) : null}
            {/* 影像視窗的顯示選項 */}
            <div className="absolute bottom-2 left-2 flex items-center gap-1 rounded-lg border border-line bg-surface/90 px-1.5 py-1 text-[11px] backdrop-blur">
              <Camera size={12} className="text-muted" />
              <button type="button" className={optionBtn(effectiveMode === 'input' && !split)} disabled={!view.hasInput || split} onClick={() => setViewMode('input')}>
                {t('editor.viewer.showInput')}
              </button>
              <button type="button" className={optionBtn(effectiveMode === 'output' && !split)} disabled={!view.hasOutput || split} onClick={() => setViewMode('output')}>
                {t('editor.viewer.showOutput')}
              </button>
              <button type="button" className={`flex items-center gap-1 ${optionBtn(split)}`} onClick={() => setSplit((v) => !v)} title={t('editor.viewer.splitHint')} data-testid="btn-split">
                <Columns2 size={12} /> {t('editor.viewer.split')}
              </button>
              <span className="mx-0.5 h-3.5 w-px bg-line" />
              <button type="button" className={`flex items-center gap-1 ${optionBtn(allOverlays)}`} onClick={() => setAllOverlays((v) => !v)} title={t('editor.viewer.allOverlays')}>
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
            <FlowCanvas
              interaction={interaction}
              onInteractionChange={(mode) => { setInteraction(mode); storeInteractionMode(mode) }}
              onAutoLayout={autoLayout}
              nodes={decoratedNodes}
              edges={decoratedEdges}
              onNodesChange={(changes) => {
                onNodesChange(changes)
                if (changes.some(isEdit)) setDirty(true)
              }}
              onEdgesChange={(changes) => {
                onEdgesChange(changes)
                if (changes.some(isEdit)) setDirty(true)
              }}
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
                else setRightTab('results')
              }}
              onNodeDragStart={() => pushHistory()}
              onNodeContextMenu={(e, node) => {
                e.preventDefault()
                const payload = payloads.current.get(node.id)
                if (!payload) return
                setSelectedId(node.id)
                setNodes((list) => list.map((n) => ({ ...n, selected: n.id === node.id })))
                setNodeMenu({ x: e.clientX, y: e.clientY, node: payload })
              }}
              onPaneClick={() => setSelectedId(null)}
              onDragOver={onDragOver}
              onDrop={onDrop}
            />
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
                  <Button size="sm" variant="danger" onClick={() => deleteNodes(nodesRef.current.filter((n) => n.selected).map((n) => n.id))}>
                    {t('editor.deleteSelected', { count: selectedCount })}
                  </Button>
                </div>
              ) : selected ? (
                <Inspector flowId={flowId} node={selected} definition={selectedDef} edges={graphEdges} onChange={(p) => patchNode(selected.id, p)} onDelete={() => deleteNodes([selected.id])} />
              ) : (
                <div className="space-y-3 p-3">
                  <p className="text-xs text-muted">{t('editor.selectNodeHint')}</p>
                  <TextInput
                    label={t('common.description')}
                    value={meta.description}
                    onChange={(e) => {
                      setMeta({ ...meta, description: e.target.value })
                      setDirty(true)
                    }}
                  />
                  <TextInput
                    label={t('flows.continuousInterval')}
                    type="number"
                    min={0}
                    value={String(flow.data?.continuous_interval_ms ?? 0)}
                    disabled={readOnly}
                    onChange={(e) => patch.mutate({ id: flowId, continuous_interval_ms: Number(e.target.value) || 0 }, { onSuccess: (saved) => { loadedFor.current = `${saved.id}:${saved.version}` } })}
                  />
                  {/* 複製出來的流程預設停用；不用回列表就能在這裡開啟 */}
                  <Checkbox
                    label={t('flows.enabledToggle')}
                    hint={flow.data?.is_enabled === false ? t('editor.flowDisabledHint') : undefined}
                    checked={flow.data?.is_enabled !== false}
                    disabled={readOnly}
                    onChange={(v) => patch.mutate({ id: flowId, is_enabled: v }, { onSuccess: (saved) => { loadedFor.current = `${saved.id}:${saved.version}` }, onError: (error) => toast.error(errorMessage(error)) })}
                  />
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
                  onSelect={(run) => setPinnedRunId(run.id)}
                />
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
        onDuplicate={duplicateNode}
        onToggleEnabled={(node) => patchNode(node.id, { enabled: node.enabled === false })}
        onDelete={(node) => deleteNodes([node.id])}
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
