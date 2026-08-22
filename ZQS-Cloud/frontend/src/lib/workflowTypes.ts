/**
 * Types shared between the workflow editor, the run view and the API layer.
 *
 * The node *catalogue* is fetched rather than declared here. Registering a
 * node type on the server is meant to be all it takes for it to appear in the
 * editor with a working parameter form; a hard-coded copy in the frontend
 * would be a second list to keep in step, and it would be the one that fell
 * behind.
 */

export type NodeParamKind =
  | 'text'
  | 'number'
  | 'boolean'
  | 'select'
  | 'device'
  | 'metric'
  | 'command'
  | 'workflow'
  | 'duration'
  /** Another node in the same graph (jump targets). */
  | 'node'

export interface NodeParam {
  key: string
  label: string
  kind: NodeParamKind
  required: boolean
  default: unknown
  help_text: string
  options: { value: string; label: string }[]
  unit: string
  minimum: number | null
  maximum: number | null
}

export interface NodeHandle {
  key: string
  label: string
  /** Drawn in a colour that says what the branch means. */
  tone: 'neutral' | 'ok' | 'warn' | 'critical'
}

export interface NodeTypeDef {
  key: string
  label: string
  description: string
  category: string
  /** Lucide icon name; the editor maps it to a component. */
  icon: string
  params: NodeParam[]
  handles: NodeHandle[]
}

/** One node as it is stored in the graph. */
export interface GraphNode {
  id: string
  type: string
  /** The operator's own name for this step. */
  label?: string
  /** Their note on why it is there. */
  description?: string
  /** Off means the engine steps over it without executing it. */
  enabled?: boolean
  /** The engine pauses the run just before executing this node. */
  breakpoint?: boolean
  /** Custom card colour picked by the operator; text auto-contrasts. */
  color?: string
  params?: Record<string, unknown>
  position?: { x: number; y: number }
  /** Persisted size, for resizable nodes (notes). */
  width?: number
  height?: number
}

export interface GraphEdge {
  id?: string
  source: string
  target: string
  /** Which output the edge leaves by. Blank for a single-output node. */
  source_handle?: string
}

export interface WorkflowGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface Workflow {
  id: string
  name: string
  description: string
  site_id: string | null
  site_name: string | null
  is_enabled: boolean
  version: number
  graph: WorkflowGraph
  node_count: number
  active_run_count: number
  created_at: string
  updated_at: string
}

export type RunStatus =
  | 'pending'
  | 'running'
  | 'waiting'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface WorkflowRun {
  id: string
  workflow_id: string
  workflow_name: string
  status: RunStatus
  trigger: 'manual' | 'api' | 'workflow' | 'storage_plan'
  dry_run: boolean
  workflow_version: number
  steps_taken: number
  step_delay_seconds: number
  error: string
  context: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  wake_at: string | null
  created_at: string
  /** Where each branch currently sits, for lighting up the canvas. */
  active_nodes: string[]
}

export interface WorkflowRunLog {
  id: number
  ts: string
  node_id: string
  node_label: string
  level: 'debug' | 'info' | 'warning' | 'error'
  message: string
  branch: string
  detail: Record<string, unknown>
}

export interface WorkflowCapacity {
  limit: number
  /** Live branches (parallel tokens), not runs. */
  active: number
  /** Who is holding the slots - the answer to "I stopped everything". */
  runs: {
    run_id: string
    workflow_name: string
    status: string
    branches: number
  }[]
}

/** Statuses that still occupy one of the tenant's concurrent slots. */
export const ACTIVE_RUN_STATUSES: RunStatus[] = ['pending', 'running', 'waiting', 'paused']

export function isRunActive(status: RunStatus): boolean {
  return ACTIVE_RUN_STATUSES.includes(status)
}
