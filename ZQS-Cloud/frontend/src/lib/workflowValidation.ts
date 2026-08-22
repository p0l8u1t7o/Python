/**
 * Client-side sanity checks on node parameters.
 *
 * The server remains the authority - it re-validates on save and on start -
 * but these run while the operator is still looking at the field, which is
 * when a mistake is cheapest to point out. Returned as i18n keys plus values
 * so the message follows the console language.
 */

import type { GraphEdge, GraphNode, NodeParam, NodeTypeDef } from '@/lib/workflowTypes'

export interface ParamProblem {
  paramKey: string
  /** i18n key under `workflows.validation.` */
  code:
    | 'required'
    | 'notANumber'
    | 'belowMinimum'
    | 'aboveMaximum'
    | 'badTime'
    | 'danglingTarget'
    | 'selfTarget'
  values: Record<string, unknown>
}

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || String(value).trim() === ''
}

function checkParam(param: NodeParam, value: unknown, nodeType: string): ParamProblem | null {
  const values = { label: param.label, min: param.minimum, max: param.maximum }

  if (isBlank(value)) {
    return param.required ? { paramKey: param.key, code: 'required', values } : null
  }

  if (param.kind === 'number' || param.kind === 'duration') {
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) {
      return { paramKey: param.key, code: 'notANumber', values }
    }
    if (param.minimum !== null && numeric < param.minimum) {
      return { paramKey: param.key, code: 'belowMinimum', values }
    }
    if (param.maximum !== null && numeric > param.maximum) {
      return { paramKey: param.key, code: 'aboveMaximum', values }
    }
  }

  // The time-window node writes wall-clock times as text; a typo here would
  // otherwise only surface as "took the false branch" at run time.
  if (nodeType === 'if_end_time' && param.key.endsWith('_time') && !HHMM.test(String(value))) {
    return { paramKey: param.key, code: 'badTime', values }
  }

  return null
}

/**
 * Every problem with one node's parameters. Empty means fit to run.
 *
 * `nodes` lets a node-picker parameter (a jump target) be checked against the
 * graph it lives in: a target that was deleted, or that is decoration, would
 * otherwise only surface as "jump target does not exist" at run time.
 */
export function nodeProblems(
  node: GraphNode,
  definition: NodeTypeDef | undefined,
  nodes: GraphNode[] = [],
): ParamProblem[] {
  if (!definition) return []
  const params = node.params ?? {}
  const problems: ParamProblem[] = []
  for (const param of definition.params) {
    const value = params[param.key] ?? param.default
    const problem = checkParam(param, value, definition.key)
    if (problem) {
      problems.push(problem)
      continue
    }
    if (param.kind === 'node' && !isBlank(value)) {
      const values = { label: param.label, target: String(value) }
      if (String(value) === node.id) {
        problems.push({ paramKey: param.key, code: 'selfTarget', values })
      } else if (
        nodes.length > 0 &&
        !nodes.some((other) => other.id === String(value) && !DECORATION.has(other.type))
      ) {
        problems.push({ paramKey: param.key, code: 'danglingTarget', values })
      }
    }
  }
  return problems
}

const DECORATION = new Set(['note', 'arrow'])

/**
 * Output handles nothing is connected to. Not an error - a branch that ends at
 * "failed" is a legitimate drawing - but worth saying out loud in the
 * inspector, because an unconnected `true` on a condition is the single most
 * common way a flow silently does nothing.
 */
export function unconnectedHandles(
  node: GraphNode,
  definition: NodeTypeDef | undefined,
  edges: GraphEdge[],
): string[] {
  if (!definition || DECORATION.has(node.type)) return []
  const used = new Set(
    edges.filter((edge) => edge.source === node.id).map((edge) => edge.source_handle || ''),
  )
  // A blank source_handle on an edge matches any handle (single-output nodes
  // write none), so one blank edge counts as connecting everything.
  if (used.has('')) return []
  return definition.handles.filter((handle) => !used.has(handle.key)).map((handle) => handle.key)
}

/** node id -> problems, for marking the canvas. */
export function graphProblems(
  nodes: GraphNode[],
  definitions: Map<string, NodeTypeDef>,
): Map<string, ParamProblem[]> {
  const result = new Map<string, ParamProblem[]>()
  for (const node of nodes) {
    if (node.enabled === false) continue // a disabled node never executes
    const problems = nodeProblems(node, definitions.get(node.type), nodes)
    if (problems.length > 0) result.set(node.id, problems)
  }
  return result
}
