import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { DASHBOARD_WIDGET_TYPES, defaultProps, validateDashboardLayout, WIDGET_SCHEMA } from '@/lib/dashboardSchema'
import type { DashboardLayout } from '@/lib/types'

function readBackendContract() {
  const source = readFileSync(resolve(process.cwd(), '../apps/vision/dashboard.py'), 'utf8')
  const typesBlock = source.match(/WIDGET_TYPES\s*=\s*\(([\s\S]*?)\)/)?.[1] ?? ''
  const types = [...typesBlock.matchAll(/"([^"]+)"/g)].map((match) => match[1])
  const propsStart = source.indexOf('WIDGET_PROPS:')
  const propsOpen = source.indexOf('{', propsStart)
  let depth = 0
  let propsEnd = propsOpen
  for (let index = propsOpen; index < source.length; index += 1) {
    const char = source[index]
    if (char === '{') depth += 1
    if (char === '}') depth -= 1
    if (depth === 0) {
      propsEnd = index
      break
    }
  }
  const propsBlock = source.slice(propsOpen + 1, propsEnd)
  const props = new Map<string, string[]>()
  let cursor = 0
  while (cursor < propsBlock.length) {
    const match = /"([^"]+)"\s*:\s*\{/g.exec(propsBlock.slice(cursor))
    if (!match) break
    const widgetType = match[1]
    const open = cursor + match.index + match[0].lastIndexOf('{')
    let innerDepth = 0
    let close = open
    for (let index = open; index < propsBlock.length; index += 1) {
      const char = propsBlock[index]
      if (char === '{') innerDepth += 1
      if (char === '}') innerDepth -= 1
      if (innerDepth === 0) {
        close = index
        break
      }
    }
    const body = propsBlock.slice(open + 1, close)
    const names = [...body.matchAll(/"([^"]+)"\s*:/g)].map((item) => item[1])
    props.set(widgetType, names)
    cursor = close + 1
  }
  return { types, props }
}

describe('dashboard schema', () => {
  it('mirrors backend widget types and prop names', () => {
    const backend = readBackendContract()
    expect(DASHBOARD_WIDGET_TYPES).toEqual(backend.types)
    for (const type of backend.types) {
      expect(Object.keys(WIDGET_SCHEMA[type as keyof typeof WIDGET_SCHEMA].props)).toEqual(backend.props.get(type))
    }
  })

  it('reports local validation errors before save', () => {
    const layout: DashboardLayout = {
      rows: 2,
      cols: 2,
      cells: [{ id: 'main', row: 1, col: 1, row_span: 1, col_span: 1 }],
      widgets: [{ id: 'bad', type: 'line_chart', cell: 'main', props: { key: '', points: 1 }, source: { kind: 'spc' } }],
      bars: { top: true, bottom: true, left: false, right: false },
      default_flow_id: null,
      theme: {},
    }
    expect(validateDashboardLayout(layout).map((error) => error.message)).toEqual(expect.arrayContaining([
      "Widget 'bad' props.key must be a string",
      "Widget 'bad' props.points must be between 2 and 5000",
    ]))
  })
})

describe('optional text props', () => {
  const cell = { id: 'only', row: 1, col: 1, row_span: 1, col_span: 1 }

  function layoutWith(widget: Record<string, unknown>) {
    return { rows: 1, cols: 1, cells: [cell], bars: {}, widgets: [widget], theme: {} } as unknown as DashboardLayout
  }

  it('accepts an empty optional text but still demands a required one', () => {
    // 真實災情：時鐘存檔後讀回來時區是空字串，再存一次就被自己的驗證擋下來。
    const clock = layoutWith({ id: 'c', type: 'clock', cell: 'only', props: { timezone: '', format: 'HH:mm' } })
    expect(validateDashboardLayout(clock)).toEqual([])
    const group = layoutWith({ id: 'g', type: 'group', cell: 'only', props: { title: '', children: [] } })
    expect(validateDashboardLayout(group)).toEqual([])
    const text = layoutWith({ id: 't', type: 'text', cell: 'only', props: { template: '' } })
    expect(validateDashboardLayout(text).length).toBeGreaterThan(0)
  })

  it('keeps every widget type valid once its required props are filled in', () => {
    // requiredDefaults 給的是空白（設計端要求使用者填），這裡補上樣本值，
    // 驗的是「填好之後每一種 widget 都過得了自己的驗證」。
    const sample: Record<string, unknown> = {
      text: 'x', int: 1, number: 1, bool: true, any: 1, flow_id: 1, color: '#112233',
      children: [], tabs: [], columns: ['value'], rules: [], image_items: [],
    }
    for (const type of DASHBOARD_WIDGET_TYPES) {
      const props: Record<string, unknown> = { ...defaultProps(type) }
      for (const [key, spec] of Object.entries(WIDGET_SCHEMA[type].props)) {
        if (!spec.required) continue
        props[key] = spec.kind === 'choice' ? (spec.choices ?? [''])[0] : sample[spec.kind]
      }
      const errors = validateDashboardLayout(layoutWith({ id: 'w', type, cell: 'only', props }))
      expect(`${type}: ${JSON.stringify(errors)}`).toBe(`${type}: []`)
    }
  })
})
