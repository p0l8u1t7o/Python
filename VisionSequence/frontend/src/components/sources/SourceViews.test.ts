import { describe, expect, it } from 'vitest'

import { buildSourceTree } from './SourceViews'
import type { ImageSource } from '@/lib/types'

function source(id: number, kind: string, group: string, name: string): ImageSource {
  return { id, name, group, kind, config: {}, is_enabled: true, status: {}, created_at: '', updated_at: '' }
}

describe('source tree', () => {
  it('groups by kind then group, cameras first', () => {
    const tree = buildSourceTree([
      source(1, 'synthetic', '', 'gen'),
      source(2, 'folder', '樣本', 'b'),
      source(3, 'capture', '產線', 'cam2'),
      source(4, 'folder', '', 'a'),
      source(5, 'capture', '產線', 'cam1'),
    ])
    expect(tree.map((n) => n.kind)).toEqual(['capture', 'folder', 'synthetic'])
    expect(tree[0].total).toBe(2)
    expect(tree[0].groups[0].items.map((s) => s.name)).toEqual(['cam1', 'cam2'])
    expect(tree[1].groups.map((g) => g.group)).toEqual(['樣本', ''])  // 未分組排最後
  })

  it('puts unknown kinds after the known ones and handles an empty library', () => {
    expect(buildSourceTree([])).toEqual([])
    const tree = buildSourceTree([source(1, 'plugin_cam', '', 'x'), source(2, 'capture', '', 'c')])
    expect(tree.map((n) => n.kind)).toEqual(['capture', 'plugin_cam'])
  })
})
