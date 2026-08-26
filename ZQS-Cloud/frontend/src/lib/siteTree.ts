/**
 * Order a flat list of parent-linked rows as a tree: parents first, each
 * followed by its subtree, siblings in the input's order.
 *
 * Every list of sites in the console is drawn this way (dashboard, report,
 * fleet card, pickers) so a workshop is always seen under its plant. Rows
 * whose parent is not in the list are treated as roots - a filtered list
 * still renders rather than losing the orphans.
 */
export interface TreeRow<T> {
  item: T
  parent: T | null
  depth: number
  hasChildren: boolean
  /** True for the last sibling; lets a renderer pick the closing connector. */
  last: boolean
  /** Rows under this one, however deep - what a collapse hides. */
  descendants: number
}

export function treeRows<T>(
  items: readonly T[],
  id: (item: T) => string,
  parentId: (item: T) => string | null | undefined,
): TreeRow<T>[] {
  const known = new Set(items.map(id))
  const childrenOf = new Map<string | null, T[]>()
  for (const item of items) {
    const parent = parentId(item)
    const key = parent && known.has(parent) ? parent : null
    childrenOf.set(key, [...(childrenOf.get(key) ?? []), item])
  }
  const out: TreeRow<T>[] = []
  const walk = (parent: T | null, depth: number) => {
    const kids = childrenOf.get(parent ? id(parent) : null) ?? []
    kids.forEach((item, index) => {
      const row: TreeRow<T> = {
        item,
        parent,
        depth,
        hasChildren: (childrenOf.get(id(item)) ?? []).length > 0,
        last: index === kids.length - 1,
        descendants: 0,
      }
      out.push(row)
      const before = out.length
      walk(item, depth + 1)
      row.descendants = out.length - before
    })
  }
  walk(null, 0)
  return out
}

/** Ids hidden by a set of collapsed rows: every descendant of any of them. */
export function hiddenByCollapse<T>(
  rows: TreeRow<T>[],
  id: (item: T) => string,
  collapsed: ReadonlySet<string>,
): Set<string> {
  const hidden = new Set<string>()
  const byId = new Map(rows.map((row) => [id(row.item), row]))
  for (const row of rows) {
    let cursor = row.parent
    while (cursor) {
      if (collapsed.has(id(cursor))) {
        hidden.add(id(row.item))
        break
      }
      cursor = byId.get(id(cursor))?.parent ?? null
    }
  }
  return hidden
}
