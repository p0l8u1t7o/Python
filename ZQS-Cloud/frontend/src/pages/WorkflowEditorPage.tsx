import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useBlocker, useParams } from 'react-router-dom'
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react'
import * as icons from 'lucide-react'
import '@xyflow/react/dist/style.css'

import { NodeInspector } from '@/components/workflow/NodeInspector'
import {
  ArrowNode,
  NoteNode,
  WorkflowNode,
  type WorkflowNodeData,
} from '@/components/workflow/WorkflowNode'
import { AnimatedFlowEdge } from '@/components/workflow/FlowEdge'
import { ZoomSlider } from '@/components/workflow/ZoomSlider'
import { RunPanel, STATUS_TONE } from '@/components/workflow/RunPanel'
import {
  useNodeTypes,
  useRunLogs,
  useWorkflow,
  useWorkflowCapacity,
  useWorkflowMutations,
  useWorkflowRun,
  useWorkflowRunMutations,
  useWorkflowRuns,
} from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import { useToast } from '@/providers/ToastProvider'
import type {
  GraphEdge,
  GraphNode,
  NodeTypeDef,
  WorkflowGraph,
} from '@/lib/workflowTypes'
import { isRunActive } from '@/lib/workflowTypes'
import { useRunStream } from '@/lib/runStream'
import { graphProblems } from '@/lib/workflowValidation'
import {
  Badge,
  Button,
  Card,
  ErrorState,
  LoadingState,
  PageHeader,
  Select,
  TextInput,
} from '@/components/ui'

const NODE_TYPES = { workflow: WorkflowNode, note: NoteNode, arrow: ArrowNode }
const EDGE_TYPES = { flow: AnimatedFlowEdge }
const DECORATION_TYPES = new Set(['note', 'arrow'])
const DRAG_MIME = 'application/x-zqs-node-type'
const HISTORY_LIMIT = 50

/** Column and row pitch for the one-click layout. */
const LAYOUT_X = 280
const LAYOUT_Y = 200

/** Stable-ish id that reads in a jump target field. */
function nextNodeId(existing: Set<string>, type: string): string {
  for (let index = 1; index < 1000; index += 1) {
    const candidate = `${type}-${index}`
    if (!existing.has(candidate)) return candidate
  }
  return `${type}-${Date.now()}`
}

/** True when the keystroke belongs to a form field, not to the canvas. */
function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return (
    tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
  )
}

function toFlowNodes(graph: WorkflowGraph, definitions: Map<string, NodeTypeDef>): Node[] {
  return (graph.nodes ?? []).map((node, index) => ({
    id: node.id,
    type: DECORATION_TYPES.has(node.type) ? node.type : 'workflow',
    position: node.position ?? { x: 80 + (index % 4) * 260, y: 80 + Math.floor(index / 4) * 190 },
    // Decoration is resizable; a saved size comes back exactly as it was left.
    ...(DECORATION_TYPES.has(node.type) && node.width ? { width: node.width } : {}),
    ...(DECORATION_TYPES.has(node.type) && node.height ? { height: node.height } : {}),
    data: {
      definition: definitions.get(node.type),
      label: node.label ?? '',
      description: node.description ?? '',
      enabled: node.enabled !== false,
      breakpoint: node.breakpoint === true,
      color: node.color ?? '',
      params: node.params ?? {},
    } satisfies WorkflowNodeData,
  }))
}

/** Visual properties for one edge; annotation arrows read as annotations. */
function edgeProps(sourceIsNote: boolean): Partial<Edge> {
  if (sourceIsNote) {
    return {
      animated: false,
      style: { strokeDasharray: '6 4' },
      markerEnd: { type: MarkerType.ArrowClosed },
    }
  }
  return { type: 'flow', animated: true, markerEnd: { type: MarkerType.ArrowClosed } }
}

function toFlowEdges(graph: WorkflowGraph): Edge[] {
  const notes = new Set(
    (graph.nodes ?? []).filter((node) => node.type === 'note').map((node) => node.id),
  )
  return (graph.edges ?? []).map((edge, index) => ({
    id: edge.id ?? `e-${edge.source}-${edge.source_handle ?? ''}-${edge.target}-${index}`,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.source_handle || null,
    ...edgeProps(notes.has(edge.source)),
  }))
}

/**
 * Which canvas changes count as an edit. React Flow reports the initial
 * measurement of every node as a `dimensions` change on mount - treating that
 * as an edit is why a freshly opened page used to warn about unsaved changes.
 * Only a resize the operator performs (`resizing: true`) counts.
 */
function isEdit(change: NodeChange | EdgeChange): boolean {
  if (change.type === 'select') return false
  if (change.type === 'dimensions') return change.resizing === true
  return true
}

/**
 * One-click layout: rank each executable node by its longest path from an
 * entry, then order each rank by where its parents sit. Notes stay where the
 * author put them - a layout pass that relocates somebody's annotations would
 * tidy the flow and scramble its documentation.
 */
function computeLayout(graph: WorkflowGraph): Map<string, { x: number; y: number }> {
  const executable = (graph.nodes ?? []).filter((node) => node.type !== 'note')
  const ids = executable.map((node) => node.id)
  const idSet = new Set(ids)
  const edges = (graph.edges ?? []).filter(
    (edge) => idSet.has(edge.source) && idSet.has(edge.target),
  )

  const incoming = new Map<string, string[]>()
  for (const edge of edges) {
    const list = incoming.get(edge.target)
    if (list) list.push(edge.source)
    else incoming.set(edge.target, [edge.source])
  }

  // Longest path from an entry, by relaxation. Bounded by |V| passes and a
  // rank cap, so a jump-loop drawn as a cycle cannot spin this forever.
  const rank = new Map<string, number>(ids.map((id) => [id, 0]))
  for (let pass = 0; pass < ids.length; pass += 1) {
    let moved = false
    for (const edge of edges) {
      const proposed = Math.min((rank.get(edge.source) ?? 0) + 1, ids.length)
      if (proposed > (rank.get(edge.target) ?? 0)) {
        rank.set(edge.target, proposed)
        moved = true
      }
    }
    if (!moved) break
  }

  const rows = new Map<number, string[]>()
  for (const id of ids) {
    const row = rank.get(id) ?? 0
    const list = rows.get(row)
    if (list) list.push(id)
    else rows.set(row, [id])
  }

  // Order each row under the average column of its parents, so edges run
  // downward rather than weaving. Single pass - good enough to be readable,
  // which is all a tidy-up button promises.
  const column = new Map<string, number>()
  const positions = new Map<string, { x: number; y: number }>()
  for (const row of [...rows.keys()].sort((a, b) => a - b)) {
    const members = rows.get(row) ?? []
    const keyed = members.map((id) => {
      const parents = (incoming.get(id) ?? []).map((parent) => column.get(parent))
      const known = parents.filter((value): value is number => value !== undefined)
      const barycenter = known.length
        ? known.reduce((sum, value) => sum + value, 0) / known.length
        : Number.MAX_SAFE_INTEGER
      return { id, barycenter }
    })
    keyed.sort((a, b) => a.barycenter - b.barycenter || a.id.localeCompare(b.id))
    keyed.forEach((entry, index) => {
      column.set(entry.id, index)
      positions.set(entry.id, { x: 60 + index * LAYOUT_X, y: 60 + row * LAYOUT_Y })
    })
  }
  return positions
}

function EditorInner({ workflowId }: { workflowId: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { screenToFlowPosition, fitView } = useReactFlow()

  const catalogue = useNodeTypes()
  const workflow = useWorkflow(workflowId)
  const capacity = useWorkflowCapacity()
  const { save } = useWorkflowMutations()

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [meta, setMeta] = useState({ name: '', description: '' })
  const [dirty, setDirty] = useState(false)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [stepDelay, setStepDelay] = useState(0)

  // ---- run state ---------------------------------------------------------
  // While a run is alive an SSE stream feeds the cache and polling stands
  // down; the moment the stream is not connected, polling takes back over.
  const runsQuery = useWorkflowRuns({ workflow_id: workflowId, limit: 5 })
  const streamWanted = Boolean(activeRunId)
  const streaming = useRunStream(activeRunId, streamWanted)
  const run = useWorkflowRun(activeRunId ?? undefined, { streaming })
  const { start, runNode, stop, pause, resume } = useWorkflowRunMutations()

  // Follow the newest run when nothing is pinned, so pressing Run in one tab
  // and watching in another still shows something.
  useEffect(() => {
    if (activeRunId) return
    const newest = runsQuery.data?.items?.[0]
    if (newest) setActiveRunId(newest.id)
  }, [runsQuery.data, activeRunId])

  const currentRun = run.data
  const runActive = currentRun ? isRunActive(currentRun.status) : false
  const runPaused = currentRun?.status === 'paused'
  // Logs arrive over the stream when it is up; otherwise they poll at
  // watching pace while the run moves - the canvas highlight and the log
  // lines have to track nodes that take only a couple of seconds.
  const logs = useRunLogs(
    activeRunId ?? undefined,
    { limit: 200 },
    { live: runActive, streaming },
  )
  const logItems = useMemo(() => logs.data?.items ?? [], [logs.data])

  const activeNodes = useMemo(
    () => new Set(currentRun?.active_nodes ?? []),
    [currentRun?.active_nodes],
  )

  // Where a failed run died: the last error the engine logged with a node
  // attached. Drawn in red on the canvas until the next run replaces it.
  const erroredNodeId = useMemo(() => {
    if (currentRun?.status !== 'failed') return null
    for (let index = logItems.length - 1; index >= 0; index -= 1) {
      const entry = logItems[index]
      if (entry.level === 'error' && entry.node_id) return entry.node_id
    }
    return null
  }, [currentRun?.status, logItems])

  // The graph is loaded once per workflow version, not on every refetch.
  // Reloading the canvas underneath someone dragging a node is the same class
  // of bug as resetting a form field they are typing into.
  const loadedFor = useRef<string>('')

  const definitions = useMemo(() => {
    const map = new Map<string, NodeTypeDef>()
    for (const definition of catalogue.data ?? []) map.set(definition.key, definition)
    return map
  }, [catalogue.data])

  /** The editor's own copy of the node payloads, keyed by id. */
  const payloads = useRef<Map<string, GraphNode>>(new Map())

  // Mirrors of the latest canvas state, for handlers that outlive a render
  // (the document-level keyboard listener would otherwise close over stale
  // state and undo to the wrong place).
  const nodesRef = useRef<Node[]>([])
  const edgesRef = useRef<Edge[]>([])
  nodesRef.current = nodes
  edgesRef.current = edges

  /** Snapshots for Ctrl+Z. Taken *before* each mutation, capped, in a ref -
   *  undo history is not render state and must not cause renders. */
  const history = useRef<WorkflowGraph[]>([])
  /** Copied nodes and the edges between them, for Ctrl+C / Ctrl+V. */
  const clipboard = useRef<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null)

  function graphFrom(flowNodes: Node[], flowEdges: Edge[]): WorkflowGraph {
    const graphNodes: GraphNode[] = flowNodes.map((node) => {
      const payload = payloads.current.get(node.id)
      const width = node.width ?? payload?.width
      const height = node.height ?? payload?.height
      return {
        ...(payload ?? { id: node.id, type: 'node' }),
        id: node.id,
        position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
        // A resized note keeps its size across save and reload.
        ...(width ? { width: Math.round(width) } : {}),
        ...(height ? { height: Math.round(height) } : {}),
      }
    })
    const graphEdges: GraphEdge[] = flowEdges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      source_handle: edge.sourceHandle ?? '',
    }))
    return { nodes: graphNodes, edges: graphEdges }
  }

  const currentGraph = () => graphFrom(nodesRef.current, edgesRef.current)

  function restoreGraph(graph: WorkflowGraph) {
    payloads.current = new Map(graph.nodes.map((node) => [node.id, node]))
    setNodes(toFlowNodes(graph, definitions))
    setEdges(toFlowEdges(graph))
    setSelectedId(null)
    setDirty(true)
  }

  const pushHistory = useCallback(() => {
    history.current.push(currentGraph())
    if (history.current.length > HISTORY_LIMIT) history.current.shift()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function undo() {
    const previous = history.current.pop()
    if (!previous) return
    restoreGraph(previous)
  }

  useEffect(() => {
    const data = workflow.data
    if (!data || definitions.size === 0) return
    const key = `${data.id}:${data.version}`
    if (loadedFor.current === key) return
    loadedFor.current = key

    payloads.current = new Map((data.graph.nodes ?? []).map((node) => [node.id, node]))
    setNodes(toFlowNodes(data.graph, definitions))
    setEdges(toFlowEdges(data.graph))
    setMeta({ name: data.name, description: data.description })
    setDirty(false)
    history.current = []
  }, [workflow.data, definitions, setNodes, setEdges])

  // ---- validation --------------------------------------------------------
  const problemMap = useMemo(() => {
    const graphNodes = nodes
      .map((node) => payloads.current.get(node.id))
      .filter((payload): payload is GraphNode => Boolean(payload))
    return graphProblems(graphNodes, definitions)
  }, [nodes, definitions])

  // Decoration - selection ring, live-branch light, validation mark, failure
  // mark - is layered onto the canvas nodes in one place, derived, so none of
  // it can drift out of step with the state it reports.
  const decoratedNodes = useMemo(
    () =>
      nodes.map((node) => {
        const data = node.data as WorkflowNodeData
        const problems = problemMap.get(node.id)
        const problem = problems?.length
          ? t(`workflows.validation.${problems[0].code}`, problems[0].values)
          : undefined
        const active = activeNodes.has(node.id)
        const errored = node.id === erroredNodeId
        if (
          data.problem === problem &&
          Boolean(data.active) === active &&
          Boolean(data.errored) === errored
        ) {
          return node
        }
        return { ...node, data: { ...data, problem, active, errored } }
      }),
    [nodes, problemMap, activeNodes, erroredNodeId, t],
  )

  // The taken path moves: an edge whose target holds a live branch carries a
  // travelling dot (Animated SVG Edge), so "the token went this way" is
  // visible rather than inferred.
  const decoratedEdges = useMemo(
    () =>
      edges.map((edge) => {
        const flowing = runActive && activeNodes.has(edge.target)
        if (Boolean((edge.data as { flowing?: boolean } | undefined)?.flowing) === flowing) {
          return edge
        }
        return { ...edge, data: { ...(edge.data ?? {}), flowing } }
      }),
    [edges, activeNodes, runActive],
  )

  // ---- leaving with unsaved changes (3-10) -------------------------------
  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }: {
        currentLocation: { pathname: string }
        nextLocation: { pathname: string }
      }) => dirty && currentLocation.pathname !== nextLocation.pathname,
      [dirty],
    ),
  )
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (window.confirm(t('workflows.leaveUnsaved'))) blocker.proceed()
    else blocker.reset()
  }, [blocker, t])

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      // Browsers show their own wording; the property just has to be set.
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const selected = selectedId ? payloads.current.get(selectedId) : undefined

  const onConnect = useCallback(
    (connection: Connection) => {
      pushHistory()
      const sourceIsNote = payloads.current.get(connection.source)?.type === 'note'
      setEdges((current) => addEdge({ ...connection, ...edgeProps(sourceIsNote) }, current))
      setDirty(true)
    },
    [setEdges, pushHistory],
  )

  /** Insert one node of `definition` at a canvas position. */
  const insertNode = useCallback(
    (definition: NodeTypeDef, position: { x: number; y: number }) => {
      pushHistory()
      const ids = new Set(payloads.current.keys())
      const id = nextNodeId(ids, definition.key)
      const payload: GraphNode = {
        id,
        type: definition.key,
        label: '',
        description: '',
        enabled: true,
        params: Object.fromEntries(
          definition.params
            .filter((param) => param.default !== null && param.default !== undefined)
            .map((param) => [param.key, param.default]),
        ),
        position,
      }
      payloads.current.set(id, payload)
      setNodes((current) => [
        // Selection follows insertion on the canvas as well as in the
        // inspector: the freshly placed node is what Delete and Ctrl+C are
        // about to be aimed at, and those read the canvas selection.
        ...current.map((node) => ({ ...node, selected: false })),
        {
          id,
          type: DECORATION_TYPES.has(definition.key) ? definition.key : 'workflow',
          position,
          selected: true,
          data: {
            definition,
            label: '',
            description: '',
            enabled: true,
            breakpoint: false,
            color: '',
            params: payload.params ?? {},
          } satisfies WorkflowNodeData,
        },
      ])
      setSelectedId(id)
      setDirty(true)
    },
    [setNodes, pushHistory],
  )

  function addNodeByClick(definition: NodeTypeDef) {
    const count = payloads.current.size
    insertNode(definition, { x: 120 + count * 40, y: 120 + count * 30 })
  }

  // ---- drag from the palette onto the canvas ----------------------------
  const onDragOver = useCallback((event: React.DragEvent) => {
    if (event.dataTransfer.types.includes(DRAG_MIME)) {
      event.preventDefault()
      event.dataTransfer.dropEffect = 'copy'
    }
  }, [])

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      const key = event.dataTransfer.getData(DRAG_MIME)
      const definition = key ? definitions.get(key) : undefined
      if (!definition) return
      event.preventDefault()
      // The drop point, in canvas coordinates - the node lands under the
      // cursor rather than wherever the auto-placement cursor happens to be.
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY })
      insertNode(definition, { x: Math.round(position.x), y: Math.round(position.y) })
    },
    [definitions, insertNode, screenToFlowPosition],
  )

  function patchNode(id: string, patch: Partial<GraphNode>) {
    const current = payloads.current.get(id)
    if (!current) return
    const updated = { ...current, ...patch }
    payloads.current.set(id, updated)
    setNodes((list) =>
      list.map((node) =>
        node.id === id
          ? {
              ...node,
              data: {
                ...(node.data as WorkflowNodeData),
                label: updated.label ?? '',
                description: updated.description ?? '',
                enabled: updated.enabled !== false,
                breakpoint: updated.breakpoint === true,
                color: updated.color ?? '',
                params: updated.params ?? {},
              },
            }
          : node,
      ),
    )
    setDirty(true)
  }

  const deleteNodes = useCallback(
    (ids: string[]) => {
      if (ids.length === 0) return
      pushHistory()
      const gone = new Set(ids)
      for (const id of ids) payloads.current.delete(id)
      setNodes((list) => list.filter((node) => !gone.has(node.id)))
      setEdges((list) =>
        list.filter((edge) => !gone.has(edge.source) && !gone.has(edge.target)),
      )
      setSelectedId((current) => (current && gone.has(current) ? null : current))
      setDirty(true)
    },
    [setNodes, setEdges, pushHistory],
  )

  // ---- clipboard ---------------------------------------------------------
  const copySelection = useCallback(() => {
    const chosen = nodesRef.current.filter((node) => node.selected)
    if (chosen.length === 0) return
    const ids = new Set(chosen.map((node) => node.id))
    clipboard.current = {
      nodes: chosen.map((node) => ({
        ...(payloads.current.get(node.id) ?? { id: node.id, type: 'node' }),
        position: { x: node.position.x, y: node.position.y },
      })),
      // Only the edges *between* copied nodes travel: an edge into the rest
      // of the graph would paste as a duplicate connection nobody drew.
      edges: edgesRef.current
        .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
        .map((edge) => ({
          source: edge.source,
          target: edge.target,
          source_handle: edge.sourceHandle ?? '',
        })),
    }
  }, [])

  const paste = useCallback(() => {
    const copied = clipboard.current
    if (!copied || copied.nodes.length === 0) return
    pushHistory()

    const existing = new Set(payloads.current.keys())
    const rename = new Map<string, string>()
    const newNodes: Node[] = []

    for (const source of copied.nodes) {
      const id = nextNodeId(existing, source.type)
      existing.add(id)
      rename.set(source.id, id)
      const position = {
        x: (source.position?.x ?? 100) + 40,
        y: (source.position?.y ?? 100) + 40,
      }
      const payload: GraphNode = { ...source, id, position }
      // A pasted jump that pointed inside the copied set follows its copy; one
      // that pointed outside keeps its target, which is what "duplicate this
      // fragment" means.
      if (payload.type === 'jump') {
        const target = String(payload.params?.target ?? '')
        if (rename.has(target) || copied.nodes.some((n) => n.id === target)) {
          payload.params = { ...payload.params, target: rename.get(target) ?? target }
        }
      }
      payloads.current.set(id, payload)
      newNodes.push({
        id,
        type: DECORATION_TYPES.has(payload.type) ? payload.type : 'workflow',
        position,
        selected: true,
        data: {
          definition: definitions.get(payload.type),
          label: payload.label ?? '',
          description: payload.description ?? '',
          enabled: payload.enabled !== false,
          breakpoint: payload.breakpoint === true,
          color: payload.color ?? '',
          params: payload.params ?? {},
        } satisfies WorkflowNodeData,
      })
    }

    setNodes((current) => [
      ...current.map((node) => ({ ...node, selected: false })),
      ...newNodes,
    ])
    setEdges((current) => [
      ...current,
      ...copied.edges.map((edge, index) => {
        const source = rename.get(edge.source) ?? edge.source
        return {
          id: `e-paste-${Date.now()}-${index}`,
          source,
          target: rename.get(edge.target) ?? edge.target,
          sourceHandle: edge.source_handle || null,
          ...edgeProps(payloads.current.get(source)?.type === 'note'),
        }
      }),
    ])
    setDirty(true)
  }, [definitions, setNodes, setEdges, pushHistory])

  // ---- keyboard ----------------------------------------------------------
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      // Never while typing: Ctrl+C in the name field means "copy text", and
      // Delete means "delete a character", exactly as everywhere else.
      if (isTypingTarget(event.target)) return

      const ctrl = event.ctrlKey || event.metaKey
      if (ctrl && event.key.toLowerCase() === 'c') {
        copySelection()
      } else if (ctrl && event.key.toLowerCase() === 'v') {
        event.preventDefault()
        paste()
      } else if (ctrl && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        undo()
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        const chosen = nodesRef.current.filter((node) => node.selected)
        if (chosen.length > 0) {
          event.preventDefault()
          deleteNodes(chosen.map((node) => node.id))
        } else {
          const selectedEdges = edgesRef.current.filter((edge) => edge.selected)
          if (selectedEdges.length > 0) {
            event.preventDefault()
            pushHistory()
            const gone = new Set(selectedEdges.map((edge) => edge.id))
            setEdges((list) => list.filter((edge) => !gone.has(edge.id)))
            setDirty(true)
          }
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [copySelection, paste, deleteNodes])

  // ---- layout (3-11) -----------------------------------------------------
  const autoLayout = useCallback(() => {
    pushHistory()
    const positions = computeLayout(currentGraph())
    if (positions.size === 0) return
    for (const [id, position] of positions) {
      const payload = payloads.current.get(id)
      if (payload) payloads.current.set(id, { ...payload, position })
    }
    setNodes((list) =>
      list.map((node) => {
        const position = positions.get(node.id)
        return position ? { ...node, position } : node
      }),
    )
    setDirty(true)
    // The nodes just moved; chase them.
    window.setTimeout(() => void fitView({ padding: 0.15, duration: 300 }), 50)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setNodes, pushHistory, fitView])

  // ---- saving and running ------------------------------------------------
  async function onSave() {
    if (problemMap.size > 0) {
      toast.error(t('workflows.validationWarning', { count: problemMap.size }))
    }
    try {
      await save.mutateAsync({
        id: workflowId,
        name: meta.name.trim(),
        description: meta.description,
        graph: currentGraph(),
      })
      setDirty(false)
      toast.success(t('common.saved'))
    } catch (error) {
      // The server validates the drawing - a jump to nowhere, an edge to a
      // deleted node - so its message is the useful one.
      toast.error(errorMessage(error))
    }
  }

  async function launch(dryRun: boolean) {
    if (problemMap.size > 0) {
      toast.error(t('workflows.validationWarning', { count: problemMap.size }))
      return
    }
    try {
      const created = await start.mutateAsync({
        workflowId,
        dry_run: dryRun,
        step_delay_seconds: stepDelay,
      })
      setActiveRunId(created.id)
      toast.success(dryRun ? t('workflows.testStarted') : t('workflows.runStarted'))
    } catch (error) {
      // The concurrency refusal arrives here, and its message already names
      // the limit and how many are going.
      toast.error(errorMessage(error))
    }
  }

  function runControl(action: 'stop' | 'pause' | 'resume') {
    if (!currentRun) return
    const mutation = { stop, pause, resume }[action]
    void mutation
      .mutateAsync(currentRun.id)
      .catch((error) => toast.error(errorMessage(error)))
  }

  /** Run only the selected node, once, and finish - no edges followed. */
  async function runSelectedNode() {
    if (!selectedId) return
    try {
      const created = await runNode.mutateAsync({
        workflowId,
        node_id: selectedId,
        dry_run: false,
      })
      setActiveRunId(created.id)
      toast.success(t('workflows.nodeRunFinished'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  if (catalogue.isPending || workflow.isPending) return <LoadingState />
  if (catalogue.isError || workflow.isError) {
    return (
      <ErrorState
        error={workflow.error ?? catalogue.error}
        onRetry={() => void workflow.refetch()}
      />
    )
  }

  const grouped = new Map<string, NodeTypeDef[]>()
  for (const definition of catalogue.data ?? []) {
    const bucket = grouped.get(definition.category)
    if (bucket) bucket.push(definition)
    else grouped.set(definition.category, [definition])
  }

  return (
    <>
      <PageHeader
        title={workflow.data?.name ?? t('workflows.editor')}
        description={t('workflows.editorHint')}
        actions={
          <div className="flex items-center gap-2">
            {capacity.data ? (
              <span
                className="cursor-help text-xs text-muted"
                title={
                  capacity.data.runs.length > 0
                    ? capacity.data.runs
                        .map(
                          (holder) =>
                            holder.workflow_name +
                            ': ' +
                            t('workflows.status.' + holder.status) +
                            ' \u00d7' +
                            holder.branches,
                        )
                        .join('\n')
                    : t('workflows.capacityIdle')
                }
              >
                {t('workflows.capacity', {
                  active: capacity.data.active,
                  limit: capacity.data.limit,
                })}
              </span>
            ) : null}
            <Button variant="primary" loading={save.isPending} onClick={() => void onSave()}>
              {dirty ? t('workflows.saveChanges') : t('common.saved')}
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[200px_1fr_290px]">
        {/* Palette. Built from the server's catalogue, so a node type
            registered on the backend appears here with no frontend change.
            Entries both click-to-add and drag onto the canvas. */}
        <Card className="h-fit p-3">
          <p className="mb-2 text-xs font-medium text-muted">{t('workflows.palette')}</p>
          <p className="mb-2 text-[11px] text-muted">{t('workflows.paletteHint')}</p>
          <div className="space-y-3">
            {[...grouped.entries()].map(([category, defs]) => (
              <div key={category}>
                <p className="mb-1 text-[11px] uppercase tracking-wide text-muted">
                  {t(`workflows.categories.${category}`, { defaultValue: category })}
                </p>
                <div className="space-y-1">
                  {defs.map((definition) => {
                    const Icon =
                      (icons as unknown as Record<string, icons.LucideIcon>)[definition.icon] ??
                      icons.Box
                    return (
                      <button
                        key={definition.key}
                        type="button"
                        title={t(`workflows.nodeTypes.${definition.key}.description`, {
                          defaultValue: definition.description,
                        })}
                        draggable
                        onDragStart={(event) => {
                          event.dataTransfer.setData(DRAG_MIME, definition.key)
                          event.dataTransfer.effectAllowed = 'copy'
                        }}
                        onClick={() => addNodeByClick(definition)}
                        className="flex w-full cursor-grab items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-subtle active:cursor-grabbing"
                      >
                        <Icon size={14} aria-hidden className="shrink-0 text-brand" />
                        <span className="truncate">
                          {t(`workflows.nodeTypes.${definition.key}.label`, {
                            defaultValue: definition.label,
                          })}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <div className="flex min-w-0 flex-col gap-2">
          {/* Run controls sit above the canvas they act on (3-2). */}
          <Card className="flex flex-wrap items-center gap-1.5 p-2">
            <Button onClick={() => void launch(true)} loading={start.isPending}>
              <icons.TestTube className="size-3.5" aria-hidden />
              {t('workflows.test')}
            </Button>
            <Button
              variant="primary"
              onClick={() => void launch(false)}
              loading={start.isPending}
            >
              <icons.Play className="size-3.5" aria-hidden />
              {t('workflows.run')}
            </Button>

            <span className="mx-1 h-5 w-px bg-line" aria-hidden />

            <Button
              onClick={() => runControl('pause')}
              disabled={!runActive || runPaused}
              loading={pause.isPending}
            >
              <icons.Pause className="size-3.5" aria-hidden />
              {t('workflows.pause')}
            </Button>
            <Button
              onClick={() => runControl('resume')}
              disabled={!runPaused}
              loading={resume.isPending}
            >
              <icons.Play className="size-3.5" aria-hidden />
              {t('workflows.resume')}
            </Button>
            <Button
              onClick={() => void runSelectedNode()}
              disabled={!selected || selected.type === 'note'}
              loading={runNode.isPending}
              title={t('workflows.stepOnceHint')}
            >
              <icons.StepForward className="size-3.5" aria-hidden />
              {t('workflows.stepOnce')}
            </Button>
            <Button
              onClick={() => runControl('stop')}
              disabled={!runActive}
              loading={stop.isPending}
            >
              <icons.Square className="size-3.5" aria-hidden />
              {t('workflows.stop')}
            </Button>

            <span className="mx-1 h-5 w-px bg-line" aria-hidden />

            <label className="flex items-center gap-1 text-[11px] text-muted">
              {t('workflows.stepDelay')}
              <Select
                value={String(stepDelay)}
                onChange={(event) => setStepDelay(Number(event.target.value))}
                options={[0, 0.5, 1, 2, 5, 10].map((seconds) => ({
                  value: String(seconds),
                  label: seconds === 0 ? t('workflows.delayOff') : `${seconds}s`,
                }))}
              />
            </label>

            <span className="ml-auto flex items-center gap-2">
              {currentRun ? (
                <Badge tone={STATUS_TONE[currentRun.status] ?? 'neutral'}>
                  {t(`workflows.status.${currentRun.status}`)}
                </Badge>
              ) : null}
              {problemMap.size > 0 ? (
                <span
                  className="flex items-center gap-1 text-[11px] text-critical"
                  title={t('workflows.validationWarning', { count: problemMap.size })}
                >
                  <icons.TriangleAlert className="size-3.5" aria-hidden />
                  {problemMap.size}
                </span>
              ) : null}
              <Button onClick={autoLayout} title={t('workflows.autoLayoutHint')}>
                <icons.Network className="size-3.5" aria-hidden />
                {t('workflows.autoLayout')}
              </Button>
            </span>
          </Card>

          {/* The canvas gets the room the drawing needs (3-1). */}
          <Card className="h-[calc(100vh-290px)] min-h-[520px] overflow-hidden p-0">
            <ReactFlow
              nodes={decoratedNodes}
              edges={decoratedEdges}
              nodeTypes={NODE_TYPES}
              edgeTypes={EDGE_TYPES}
              onNodesChange={(changes) => {
                onNodesChange(changes)
                if (changes.some(isEdit)) setDirty(true)
              }}
              onEdgesChange={(changes) => {
                onEdgesChange(changes)
                if (changes.some(isEdit)) setDirty(true)
              }}
              onConnect={onConnect}
              onNodeClick={(_event, node) => setSelectedId(node.id)}
              onNodeDragStart={() => pushHistory()}
              onPaneClick={() => setSelectedId(null)}
              onDragOver={onDragOver}
              onDrop={onDrop}
              // Deletion is handled by the document-level handler above, where
              // the payload map and history are kept in step. Letting React
              // Flow delete as well would remove the canvas node while the
              // payload survived - a ghost that reappears on the next restore.
              deleteKeyCode={null}
              fitView
              proOptions={{ hideAttribution: false }}
            >
              <Background />
              <Controls showZoom={false} />
              <MiniMap pannable zoomable />
              <ZoomSlider onAutoLayout={autoLayout} />
            </ReactFlow>
          </Card>
        </div>

        <div className="space-y-4">
          <Card className="p-3">
            {selected ? (
              <NodeInspector
                node={selected}
                definition={definitions.get(selected.type)}
                onChange={(patch) => patchNode(selected.id, patch)}
                onDelete={() => deleteNodes([selected.id])}
              />
            ) : (
              <div className="space-y-3">
                <p className="text-xs text-muted">{t('workflows.selectNodeHint')}</p>
                <TextInput
                  label={t('common.name')}
                  value={meta.name}
                  onChange={(event) => {
                    setMeta({ ...meta, name: event.target.value })
                    setDirty(true)
                  }}
                />
                <TextInput
                  label={t('common.description')}
                  value={meta.description}
                  onChange={(event) => {
                    setMeta({ ...meta, description: event.target.value })
                    setDirty(true)
                  }}
                />
              </div>
            )}
          </Card>

          <RunPanel run={currentRun} logs={logItems} dirty={dirty} />
        </div>
      </div>
    </>
  )
}

/**
 * Draw a control flow, then watch it run.
 *
 * The editor and the run view share one canvas on purpose: the question people
 * actually have while testing is "which branch did it take", and answering it
 * on the same picture they drew is the whole point of drawing it.
 *
 * Editing follows the habits hands already have: drag from the palette to
 * place a node, Delete removes the selection, Ctrl+C / Ctrl+V duplicate it,
 * Ctrl+Z walks back. None of the shortcuts fire while a form field has focus.
 */
export function WorkflowEditorPage() {
  const { workflowId } = useParams<{ workflowId: string }>()
  if (!workflowId) return null
  return (
    <ReactFlowProvider>
      <EditorInner workflowId={workflowId} />
    </ReactFlowProvider>
  )
}
