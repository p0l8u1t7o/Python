import { describe, expect, it } from 'vitest'

import { searchNodes, searchableFields } from './nodeSearch'
import type { GraphNode, ToolTypeDef } from './types'

const def: ToolTypeDef = {
  key: 'blob',
  label: 'Blob detector',
  description: '',
  category: 'detect',
  category_label: 'Detect',
  icon: 'Box',
  heavy: false,
  params: [],
  inputs: [],
  outputs: [],
}

const defs = new Map([[def.key, def]])
const nodes: GraphNode[] = [
  { id: 'camera', type: 'image_source', label: 'Top Camera', params: { source_id: 7 } },
  { id: 'blob_1', type: 'blob', label: 'Scratch finder', params: { min_area: 40, roi: { shape: 'rect', x: 1, y: 2, w: 3, h: 4 } } },
]

describe('nodeSearch', () => {
  it('builds searchable fields from id, title, type and filled params', () => {
    const fields = searchableFields(nodes[1], defs)
    expect(fields).toContain('blob_1')
    expect(fields).toContain('Scratch finder')
    expect(fields).toContain('Blob detector')
    expect(fields).toContain('min_area')
    expect(fields).toContain('40')
    expect(fields.some((field) => field.includes('"shape":"rect"'))).toBe(true)
  })

  it('matches every search term across node fields', () => {
    const result = searchNodes(nodes, defs, 'scratch 40')
    expect(result).toHaveLength(1)
    expect(result[0].node.id).toBe('blob_1')
  })

  it('returns no rows for empty queries', () => {
    expect(searchNodes(nodes, defs, '  ')).toEqual([])
  })
})
