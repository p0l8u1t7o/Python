import type { GraphNode, ToolTypeDef } from './types'

export interface NodeSearchResult {
  node: GraphNode
  title: string
  tool: string
  matches: string[]
}

function norm(value: unknown): string {
  return String(value ?? '').trim().toLowerCase()
}

function valueText(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value) ?? ''
  } catch {
    return String(value)
  }
}

function terms(query: string): string[] {
  return norm(query).split(/\s+/).filter(Boolean)
}

export function searchableFields(node: GraphNode, defs: Map<string, ToolTypeDef>): string[] {
  const def = defs.get(node.type)
  const fields = [node.id, node.label ?? '', def?.label ?? '', node.type, def?.category_label ?? '', def?.category ?? '']
  for (const [key, value] of Object.entries(node.params ?? {})) {
    const text = valueText(value)
    if (text) fields.push(key, text)
  }
  return fields
}

export function searchNodes(nodes: GraphNode[], defs: Map<string, ToolTypeDef>, query: string): NodeSearchResult[] {
  const needles = terms(query)
  if (needles.length === 0) return []
  const results: NodeSearchResult[] = []
  for (const node of nodes) {
    const fields = searchableFields(node, defs)
    const haystack = fields.map(norm)
    if (!needles.every((term) => haystack.some((field) => field.includes(term)))) continue
    const def = defs.get(node.type)
    results.push({
      node,
      title: node.label || def?.label || node.id,
      tool: def?.label || node.type,
      matches: fields.filter((field) => {
        const text = norm(field)
        return needles.some((term) => text.includes(term))
      }).slice(0, 4),
    })
  }
  return results
}
