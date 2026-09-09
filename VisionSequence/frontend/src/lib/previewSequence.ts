import type { FlowGraph, GraphNode, ImageSource } from './types'

export type PreviewSequenceKind = 'fixed_image' | 'folder'

export interface PreviewSequenceSource {
  kind: PreviewSequenceKind
  nodeId: string
  total: number
  label: string
  sourceId?: number
  folderPath?: string
  pattern?: string
}

export interface PreviewSequenceState {
  index: number
  total: number
  ok: number
  ng: number
}

export function createPreviewSequenceState(total: number): PreviewSequenceState {
  return { index: 0, total: Math.max(0, Math.floor(total)), ok: 0, ng: 0 }
}

export function isPreviewSequenceDone(state: PreviewSequenceState): boolean {
  return state.total <= 0 || state.index >= state.total
}

export function nextPreviewSequenceIndex(state: PreviewSequenceState): number | null {
  return isPreviewSequenceDone(state) ? null : state.index + 1
}

export function countPreviewSequenceResult(state: PreviewSequenceState, status: string): PreviewSequenceState {
  const ok = status === 'ok' ? state.ok + 1 : state.ok
  const ng = status === 'ok' ? state.ng : state.ng + 1
  return { ...state, ok, ng, index: Math.min(state.total, state.index + 1) }
}

function fixedImages(node: GraphNode): unknown[] {
  const images = node.params?.images
  return Array.isArray(images) ? images : []
}

function sourceStatusCount(source: ImageSource | undefined): number {
  const count = source?.status?.count
  return typeof count === 'number' && Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0
}

export function findPreviewSequenceSource(graph: FlowGraph, sources: ImageSource[]): PreviewSequenceSource | null {
  const fixed = graph.nodes.find((node) => node.type === 'fixed_image' && node.params?.role !== 'reference' && fixedImages(node).length > 0)
  if (fixed) {
    return {
      kind: 'fixed_image',
      nodeId: fixed.id,
      total: fixedImages(fixed).length,
      label: fixed.label || 'Fixed image',
    }
  }
  for (const node of graph.nodes) {
    if (node.type !== 'image_source') continue
    const sourceId = Number(node.params?.source_id)
    if (!Number.isFinite(sourceId) || sourceId <= 0) continue
    const source = sources.find((item) => item.id === sourceId)
    if (source?.kind !== 'folder') continue
    return {
      kind: 'folder',
      nodeId: node.id,
      sourceId,
      total: sourceStatusCount(source),
      label: source.name,
      folderPath: typeof source.config?.path === 'string' ? source.config.path : undefined,
      pattern: typeof source.config?.pattern === 'string' ? source.config.pattern : undefined,
    }
  }
  return null
}

export function graphForPreviewSequenceItem(graph: FlowGraph, source: PreviewSequenceSource, index: number): FlowGraph {
  if (source.kind !== 'fixed_image') return graph
  return {
    nodes: graph.nodes.map((node) => {
      if (node.id !== source.nodeId) return node
      return { ...node, params: { ...(node.params ?? {}), mode: 'fixed', index } }
    }),
    edges: graph.edges,
  }
}

export function previewSequenceStatusLabel(state: PreviewSequenceState): string {
  if (state.total <= 0) return '0 / 0'
  const current = Math.min(state.total, Math.max(1, state.index))
  return `${current} / ${state.total}`
}

export function countFolderPreviewFiles(files: string[], pattern?: string): number {
  const cleaned = pattern?.trim()
  if (!cleaned) return files.length
  const basenamePattern = cleaned.split(/[\\/]/).pop() || cleaned
  const escaped = basenamePattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')
  const re = new RegExp(`^${escaped}$`, 'i')
  return files.filter((file) => re.test(file.split(/[\\/]/).pop() || file)).length
}
