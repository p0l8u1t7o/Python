import type { DashboardLayout, DashboardSourceKind, DashboardWidget, DashboardWidgetType } from '@/lib/types'

export type DashboardPropKind =
  | 'any'
  | 'bool'
  | 'int'
  | 'number'
  | 'flow_id'
  | 'choice'
  | 'color'
  | 'text'
  | 'children'
  | 'columns'
  | 'tabs'
  | 'rules'
  | 'image_items'

export interface DashboardPropSpec {
  kind: DashboardPropKind
  defaultValue?: unknown
  required?: boolean
  choices?: readonly string[]
  range?: readonly [number, number]
}

export interface DashboardWidgetSchema {
  props: Record<string, DashboardPropSpec>
  sourceKinds: readonly DashboardSourceKind[]
}

export interface DashboardSchemaError {
  path: string
  message: string
  widgetId?: string
}

export const DASHBOARD_SOURCE_KINDS = ['output', 'variable', 'image', 'status', 'counts', 'spc', 'device'] as const satisfies readonly DashboardSourceKind[]
export const DASHBOARD_ACTIONS = ['run_once', 'continuous_start', 'continuous_stop', 'activate_recipe', 'set_variable', 'navigate', 'lock', 'unlock'] as const
export const DASHBOARD_OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between'] as const
export const DASHBOARD_SCOPES = ['flow', 'station'] as const

const FLOW_SOURCES = ['output', 'variable', 'status', 'counts', 'spc'] as const satisfies readonly DashboardSourceKind[]
const IMAGE_SOURCES = ['image'] as const satisfies readonly DashboardSourceKind[]
const DEVICE_SOURCES = ['device'] as const satisfies readonly DashboardSourceKind[]

export const WIDGET_SCHEMA = {
  image: { props: { node: { kind: 'text', defaultValue: null }, port: { kind: 'text', defaultValue: null }, overlays: { kind: 'bool', defaultValue: true }, crosshair: { kind: 'bool', defaultValue: false }, history: { kind: 'int', defaultValue: 1, range: [1, 50] } }, sourceKinds: IMAGE_SOURCES },
  images: { props: { items: { kind: 'image_items', defaultValue: [] }, columns: { kind: 'int', defaultValue: 2, range: [1, 8] }, overlays: { kind: 'bool', defaultValue: true }, history: { kind: 'int', defaultValue: 1, range: [1, 50] } }, sourceKinds: IMAGE_SOURCES },
  run_control: { props: { flow_id: { kind: 'flow_id', defaultValue: null } }, sourceKinds: ['status'] },
  run_status: { props: {}, sourceKinds: ['status'] },
  verdict: { props: {}, sourceKinds: ['status'] },
  text: { props: { template: { kind: 'text', required: true } }, sourceKinds: FLOW_SOURCES },
  button: { props: { action: { kind: 'choice', required: true, choices: DASHBOARD_ACTIONS }, flow_id: { kind: 'flow_id', defaultValue: null }, recipe: { kind: 'text', defaultValue: null }, variable: { kind: 'text', defaultValue: null }, value: { kind: 'any', defaultValue: null }, url: { kind: 'text', defaultValue: null } }, sourceKinds: ['status', 'variable', 'device'] },
  switch: { props: { variable: { kind: 'text', required: true }, scope: { kind: 'choice', defaultValue: 'flow', choices: DASHBOARD_SCOPES } }, sourceKinds: ['variable'] },
  param: { props: { node: { kind: 'text', required: true }, param: { kind: 'text', required: true } }, sourceKinds: ['output'] },
  variable: { props: { variable: { kind: 'text', required: true }, scope: { kind: 'choice', defaultValue: 'flow', choices: DASHBOARD_SCOPES }, editable: { kind: 'bool', defaultValue: false } }, sourceKinds: ['variable'] },
  traffic_light: { props: {}, sourceKinds: ['status'] },
  conditional_light: { props: { key: { kind: 'text', required: true }, op: { kind: 'choice', required: true, choices: DASHBOARD_OPS }, value: { kind: 'any', required: true }, value2: { kind: 'any', defaultValue: null }, color_true: { kind: 'color', defaultValue: '#22c55e' }, color_false: { kind: 'color', defaultValue: '#ef4444' } }, sourceKinds: FLOW_SOURCES },
  group: { props: { title: { kind: 'text', defaultValue: '' }, children: { kind: 'children', defaultValue: [] } }, sourceKinds: [] },
  tabs: { props: { tabs: { kind: 'tabs', defaultValue: [] } }, sourceKinds: [] },
  table: { props: { columns: { kind: 'columns', required: true }, rows: { kind: 'int', defaultValue: 10, range: [1, 200] }, rules: { kind: 'rules', defaultValue: [] } }, sourceKinds: FLOW_SOURCES },
  line_chart: { props: { key: { kind: 'text', required: true }, points: { kind: 'int', defaultValue: 100, range: [2, 5000] }, lower: { kind: 'number', defaultValue: null }, upper: { kind: 'number', defaultValue: null } }, sourceKinds: ['spc', 'output'] },
  stats: { props: {}, sourceKinds: ['counts'] },
  pie: { props: {}, sourceKinds: ['counts'] },
  image_static: { props: { fixed_image_id: { kind: 'text', required: true } }, sourceKinds: [] },
  clock: { props: { timezone: { kind: 'text', defaultValue: '' }, format: { kind: 'text', defaultValue: 'HH:mm:ss' } }, sourceKinds: DEVICE_SOURCES },
  log: { props: { rows: { kind: 'int', defaultValue: 20, range: [1, 200] } }, sourceKinds: ['status'] },
  device_status: { props: {}, sourceKinds: DEVICE_SOURCES },
} as const satisfies Record<DashboardWidgetType, DashboardWidgetSchema>

export const DASHBOARD_WIDGET_TYPES = Object.keys(WIDGET_SCHEMA) as DashboardWidgetType[]

export function defaultProps(type: DashboardWidgetType): Record<string, unknown> {
  const props: Record<string, unknown> = {}
  for (const [key, spec] of Object.entries(WIDGET_SCHEMA[type].props)) {
    if (spec.required) continue
    if (spec.kind === 'text' && spec.defaultValue === '') continue
    props[key] = clone(spec.defaultValue)
  }
  return props
}

export function requiredDefaults(type: DashboardWidgetType): Record<string, unknown> {
  const props = defaultProps(type)
  for (const [key, spec] of Object.entries(WIDGET_SCHEMA[type].props)) {
    if (!spec.required) continue
    props[key] = requiredValue(spec)
  }
  return props
}

export function validateDashboardLayout(layout: DashboardLayout): DashboardSchemaError[] {
  const errors: DashboardSchemaError[] = []
  const rows = checkInt(layout.rows, 'rows', [1, 10], errors)
  const cols = checkInt(layout.cols, 'cols', [1, 10], errors)
  if (!layout.bars || typeof layout.bars !== 'object' || Array.isArray(layout.bars)) errors.push({ path: 'bars', message: 'bars must be an object' })
  for (const key of ['top', 'bottom', 'left', 'right'] as const) {
    const value = layout.bars?.[key]
    if (value !== undefined && typeof value !== 'boolean') errors.push({ path: `bars.${key}`, message: `bars.${key} must be a boolean` })
  }
  if (layout.default_flow_id !== undefined && layout.default_flow_id !== null && !positiveInt(layout.default_flow_id)) errors.push({ path: 'default_flow_id', message: 'default_flow_id must be a positive integer or null' })
  if (layout.theme !== undefined && (!layout.theme || typeof layout.theme !== 'object' || Array.isArray(layout.theme))) errors.push({ path: 'theme', message: 'theme must be an object' })
  if (!Array.isArray(layout.cells)) errors.push({ path: 'cells', message: 'cells must be a list' })
  if (!Array.isArray(layout.widgets)) errors.push({ path: 'widgets', message: 'widgets must be a list' })

  const cellIds = new Set<string>()
  const occupied = new Map<string, string>()
  if (Array.isArray(layout.cells)) {
    layout.cells.forEach((cell, index) => {
      const prefix = `cell[${index}]`
      if (!cell || typeof cell !== 'object') {
        errors.push({ path: prefix, message: `${prefix} must be an object` })
        return
      }
      if (!text(cell.id)) errors.push({ path: `${prefix}.id`, message: `${prefix}.id must be a string` })
      else if (cellIds.has(cell.id)) errors.push({ path: `${prefix}.id`, message: `Duplicate cell id '${cell.id}'` })
      else cellIds.add(cell.id)
      checkInt(cell.row, `${prefix}.row`, [1, rows], errors)
      checkInt(cell.col, `${prefix}.col`, [1, cols], errors)
      checkInt(cell.row_span, `${prefix}.row_span`, [1, rows], errors)
      checkInt(cell.col_span, `${prefix}.col_span`, [1, cols], errors)
      if (positiveInt(cell.row) && positiveInt(cell.col) && positiveInt(cell.row_span) && positiveInt(cell.col_span)) {
        if (cell.row + cell.row_span - 1 > rows || cell.col + cell.col_span - 1 > cols) errors.push({ path: prefix, message: `Cell '${cell.id}' exceeds the grid` })
        for (let r = cell.row; r < cell.row + cell.row_span; r += 1) for (let c = cell.col; c < cell.col + cell.col_span; c += 1) {
          const key = `${r}:${c}`
          const other = occupied.get(key)
          if (other) errors.push({ path: prefix, message: `Cell '${cell.id}' overlaps cell '${other}'` })
          else occupied.set(key, cell.id)
        }
      }
    })
  }

  const widgetIds = new Set<string>()
  if (Array.isArray(layout.widgets)) {
    layout.widgets.forEach((widget, index) => {
      const prefix = `widget[${index}]`
      if (!widget || typeof widget !== 'object') {
        errors.push({ path: prefix, message: `${prefix} must be an object` })
        return
      }
      const widgetId = text(widget.id) ? widget.id : undefined
      if (!widgetId) errors.push({ path: `${prefix}.id`, message: `${prefix}.id must be a string` })
      else if (widgetIds.has(widgetId)) errors.push({ path: `${prefix}.id`, message: `Duplicate widget id '${widgetId}'`, widgetId })
      else widgetIds.add(widgetId)
      if (!(widget.type in WIDGET_SCHEMA)) {
        errors.push({ path: `${prefix}.type`, message: `Widget '${widget.id}' has unknown type '${widget.type}'`, widgetId })
        return
      }
      if (!widget.cell || !cellIds.has(widget.cell)) errors.push({ path: `${prefix}.cell`, message: `Widget '${widget.id}' references unknown cell '${widget.cell}'`, widgetId })
      validateProps(widget, prefix, errors)
      validateSource(widget, prefix, errors)
    })
  }
  return errors
}

function validateProps(widget: DashboardWidget, prefix: string, errors: DashboardSchemaError[]) {
  const spec = WIDGET_SCHEMA[widget.type]
  const raw = widget.props ?? {}
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    errors.push({ path: `${prefix}.props`, message: `Widget '${widget.id}' props must be an object`, widgetId: widget.id })
    return
  }
  for (const key of Object.keys(raw)) if (!(key in spec.props)) errors.push({ path: `${prefix}.props.${key}`, message: `Widget '${widget.id}' has unknown props.${key}`, widgetId: widget.id })
  for (const [key, prop] of Object.entries(spec.props)) {
    const value = raw[key]
    if (value === undefined || (value === null && !prop.required)) {
      if (prop.required) errors.push({ path: `${prefix}.props.${key}`, message: `Widget '${widget.id}' missing props.${key}`, widgetId: widget.id })
      continue
    }
    checkValue(value, `${prefix}.props.${key}`, `Widget '${widget.id}' props.${key}`, prop, errors, widget.id)
  }
}

function validateSource(widget: DashboardWidget, prefix: string, errors: DashboardSchemaError[]) {
  const source = widget.source
  if (source === undefined) return
  if (!source || typeof source !== 'object' || Array.isArray(source)) {
    errors.push({ path: `${prefix}.source`, message: `Widget '${widget.id}' source must be an object`, widgetId: widget.id })
    return
  }
  if (source.flow_id !== undefined && source.flow_id !== null && !positiveInt(source.flow_id)) errors.push({ path: `${prefix}.source.flow_id`, message: `Widget '${widget.id}' source.flow_id must be a positive integer`, widgetId: widget.id })
  if (source.kind !== undefined) {
    if (!DASHBOARD_SOURCE_KINDS.includes(source.kind)) errors.push({ path: `${prefix}.source.kind`, message: `Widget '${widget.id}' source.kind must be one of ${DASHBOARD_SOURCE_KINDS.join(', ')}`, widgetId: widget.id })
    else {
      const sourceKinds = WIDGET_SCHEMA[widget.type].sourceKinds as readonly DashboardSourceKind[]
      if (!sourceKinds.includes(source.kind) && sourceKinds.length) errors.push({ path: `${prefix}.source.kind`, message: `Widget '${widget.id}' source.kind is not available for ${widget.type}`, widgetId: widget.id })
    }
  }
  if (source.key !== undefined && source.key !== null && !text(source.key)) errors.push({ path: `${prefix}.source.key`, message: `Widget '${widget.id}' source.key must be a string`, widgetId: widget.id })
}

function checkValue(value: unknown, path: string, field: string, spec: DashboardPropSpec, errors: DashboardSchemaError[], widgetId?: string) {
  if (spec.kind === 'any') return
  if (spec.kind === 'bool' && typeof value !== 'boolean') errors.push({ path, message: `${field} must be a boolean`, widgetId })
  if (spec.kind === 'int') checkInt(value, path, spec.range ?? [Number.MIN_SAFE_INTEGER, Number.MAX_SAFE_INTEGER], errors, widgetId, field)
  if (spec.kind === 'number' && value !== null && ((typeof value !== 'number' && typeof value !== 'string') || !Number.isFinite(Number(value)))) errors.push({ path, message: `${field} must be a number`, widgetId })
  if (spec.kind === 'flow_id' && value !== null && !positiveInt(value)) errors.push({ path, message: `${field} must be a positive integer`, widgetId })
  if (spec.kind === 'choice' && !spec.choices?.includes(String(value))) errors.push({ path, message: `${field} must be one of ${(spec.choices ?? []).join(', ')}`, widgetId })
  if (spec.kind === 'color' && (typeof value !== 'string' || !/^#[0-9A-Fa-f]{6}$/.test(value))) errors.push({ path, message: `${field} must be a #rrggbb color`, widgetId })
  // 選填的文字屬性（時鐘時區、群組標題）允許空字串：後端存檔時本來就會把它補成空字串，
  // 讀回來再存回去不該被自己的驗證擋下來（設計端會顯示「must be a string」而不送出）。
  if (spec.kind === 'text' && (spec.required ? !text(value) : typeof value !== 'string')) errors.push({ path, message: `${field} must be a string`, widgetId })
  if (spec.kind === 'children') checkStringList(value, path, field, errors, widgetId, false)
  if (spec.kind === 'columns') checkStringList(value, path, field, errors, widgetId, true)
  if (spec.kind === 'tabs') checkTabs(value, path, field, errors, widgetId)
  if (spec.kind === 'rules') checkRules(value, path, field, errors, widgetId)
  if (spec.kind === 'image_items') checkImageItems(value, path, field, errors, widgetId)
}

function checkInt(value: unknown, path: string, range: readonly [number, number], errors: DashboardSchemaError[], widgetId?: string, label = path): number {
  if (!Number.isInteger(value) || typeof value !== 'number') {
    errors.push({ path, message: `${label} must be an integer`, widgetId })
    return range[0]
  }
  if (value < range[0] || value > range[1]) errors.push({ path, message: `${label} must be between ${range[0]} and ${range[1]}`, widgetId })
  return Math.max(range[0], Math.min(range[1], value))
}

function checkStringList(value: unknown, path: string, field: string, errors: DashboardSchemaError[], widgetId: string | undefined, nonEmpty: boolean) {
  if (!Array.isArray(value)) {
    errors.push({ path, message: `${field} must be a list`, widgetId })
    return
  }
  if (nonEmpty && value.length === 0) errors.push({ path, message: `${field} must contain at least one key`, widgetId })
  value.forEach((item, index) => {
    if (!text(item)) errors.push({ path: `${path}[${index}]`, message: `${field}[${index}] must be a non-empty string`, widgetId })
  })
}

function checkTabs(value: unknown, path: string, field: string, errors: DashboardSchemaError[], widgetId?: string) {
  if (!Array.isArray(value)) {
    errors.push({ path, message: `${field} must be a list`, widgetId })
    return
  }
  value.forEach((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) errors.push({ path: `${path}[${index}]`, message: `${field}[${index}] must be an object`, widgetId })
    else {
      if (!text((item as { title?: unknown }).title)) errors.push({ path: `${path}[${index}].title`, message: `${field}[${index}].title is required`, widgetId })
      checkStringList((item as { children?: unknown }).children ?? [], `${path}[${index}].children`, `${field}[${index}].children`, errors, widgetId, false)
    }
  })
}

function checkRules(value: unknown, path: string, field: string, errors: DashboardSchemaError[], widgetId?: string) {
  if (!Array.isArray(value)) {
    errors.push({ path, message: `${field} must be a list`, widgetId })
    return
  }
  value.forEach((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) errors.push({ path: `${path}[${index}]`, message: `${field}[${index}] must be an object`, widgetId })
    else {
      const row = item as Record<string, unknown>
      if (!text(row.key)) errors.push({ path: `${path}[${index}].key`, message: `${field}[${index}].key is required`, widgetId })
      if (!DASHBOARD_OPS.includes(row.op as never)) errors.push({ path: `${path}[${index}].op`, message: `${field}[${index}].op must be one of ${DASHBOARD_OPS.join(', ')}`, widgetId })
      if (row.color !== undefined && row.color !== null && (typeof row.color !== 'string' || !/^#[0-9A-Fa-f]{6}$/.test(row.color))) errors.push({ path: `${path}[${index}].color`, message: `${field}[${index}].color must be a #rrggbb color`, widgetId })
    }
  })
}

function checkImageItems(value: unknown, path: string, field: string, errors: DashboardSchemaError[], widgetId?: string) {
  if (!Array.isArray(value)) {
    errors.push({ path, message: `${field} must be a list`, widgetId })
    return
  }
  value.forEach((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) errors.push({ path: `${path}[${index}]`, message: `${field}[${index}] must be an object`, widgetId })
    else {
      const row = item as Record<string, unknown>
      if (row.flow_id !== undefined && row.flow_id !== null && !positiveInt(row.flow_id)) errors.push({ path: `${path}[${index}].flow_id`, message: `${field}[${index}].flow_id must be a positive integer`, widgetId })
      for (const key of ['node', 'port', 'title']) if (row[key] !== undefined && row[key] !== null && !text(row[key])) errors.push({ path: `${path}[${index}].${key}`, message: `${field}[${index}].${key} must be a string`, widgetId })
    }
  })
}

function requiredValue(spec: DashboardPropSpec): unknown {
  if (spec.kind === 'choice') return spec.choices?.[0] ?? ''
  if (spec.kind === 'columns') return ['width']
  if (spec.kind === 'any') return ''
  if (spec.kind === 'color') return '#22c55e'
  return ''
}

function positiveInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

function text(value: unknown): value is string {
  return typeof value === 'string' && value.trim() !== ''
}

function clone<T>(value: T): T {
  return value === undefined ? value : JSON.parse(JSON.stringify(value)) as T
}
