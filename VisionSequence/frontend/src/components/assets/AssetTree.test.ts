import { describe, expect, it } from 'vitest'

import { buildTree, formatSize } from './AssetTree'
import type { Asset } from '@/lib/types'

function asset(id: string, kind: Asset['kind'], group: string, name: string, size = 1024): Asset {
  return { id, name, group, kind, size, meta: {}, created_at: '2026-09-06T10:00:00Z' }
}

describe('asset tree', () => {
  it('groups by kind then group, in a stable order', () => {
    const tree = buildTree([
      asset('1', 'file', '', 'z-file'),
      asset('2', 'image', '樣本', 'b'),
      asset('3', 'image', '', 'a'),
      asset('4', 'image', '樣本', 'a', 2048),
      asset('5', 'model', 'DL', 'm'),
    ])
    expect(tree.map((n) => n.kind)).toEqual(['image', 'model', 'file'])  // KIND_ORDER，不是字母序
    const images = tree[0]
    expect(images.total).toBe(3)
    expect(images.bytes).toBe(1024 + 1024 + 2048)
    expect(images.groups.map((g) => g.group)).toEqual(['樣本', ''])  // 未分組排最後
    expect(images.groups[0].items.map((a) => a.name)).toEqual(['a', 'b'])
    expect(images.groups[0].bytes).toBe(3072)
  })

  it('handles an empty library and unknown kinds', () => {
    expect(buildTree([])).toEqual([])
    const tree = buildTree([asset('9', 'dataset' as Asset['kind'], '', 'd')])
    expect(tree[0].kind).toBe('dataset')
    expect(tree[0].total).toBe(1)
  })

  it('formats sizes', () => {
    expect(formatSize(512)).toBe('512 B')
    expect(formatSize(2048)).toBe('2.0 KB')
    expect(formatSize(3 * 1048576)).toBe('3.0 MB')
  })
})
