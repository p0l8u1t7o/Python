import { DEFAULT_DASHBOARD_LAYOUT } from '@/lib/dashboard'
import type { DashboardLayout } from '@/lib/types'

export type DashboardTemplateKey = 'empty' | 'default' | 'singleFlowBench' | 'dualFlowCompare' | 'measurementBoard' | 'operatorPanel' | 'multiImageWall' | 'deviceStatus'

export interface DashboardTemplate {
  key: DashboardTemplateKey
  titleKey: string
  descriptionKey: string
  layout: DashboardLayout
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export const EMPTY_DASHBOARD_LAYOUT: DashboardLayout = {
  rows: 2,
  cols: 2,
  cells: [
    { id: 'c_1_1', row: 1, col: 1, row_span: 1, col_span: 1 },
    { id: 'c_1_2', row: 1, col: 2, row_span: 1, col_span: 1 },
    { id: 'c_2_1', row: 2, col: 1, row_span: 1, col_span: 1 },
    { id: 'c_2_2', row: 2, col: 2, row_span: 1, col_span: 1 },
  ],
  bars: { top: true, bottom: false, left: false, right: false },
  default_flow_id: null,
  widgets: [],
  theme: {},
}

const singleFlowBench: DashboardLayout = {
  rows: 3,
  cols: 4,
  cells: [
    { id: 'image', row: 1, col: 1, row_span: 3, col_span: 2 },
    { id: 'verdict', row: 1, col: 3, row_span: 1, col_span: 1 },
    { id: 'stats', row: 1, col: 4, row_span: 1, col_span: 1 },
    { id: 'table', row: 2, col: 3, row_span: 1, col_span: 2 },
    { id: 'control', row: 3, col: 3, row_span: 1, col_span: 2 },
  ],
  bars: { top: true, bottom: true, left: false, right: false },
  default_flow_id: null,
  widgets: [
    { id: 'latest_image', type: 'image', cell: 'image', props: { overlays: true, crosshair: false, history: 6 }, source: { kind: 'image' } },
    { id: 'verdict', type: 'verdict', cell: 'verdict', props: {}, source: { kind: 'status' } },
    { id: 'today', type: 'stats', cell: 'stats', props: {}, source: { kind: 'counts' } },
    { id: 'outputs', type: 'table', cell: 'table', props: { columns: ['verdict', 'width'], rows: 8, rules: [] }, source: { kind: 'output' } },
    { id: 'run_control', type: 'run_control', cell: 'control', props: { flow_id: null }, source: { kind: 'status' } },
  ],
  theme: {},
}

const dualFlowCompare: DashboardLayout = {
  rows: 3,
  cols: 4,
  cells: [
    { id: 'left_image', row: 1, col: 1, row_span: 2, col_span: 2 },
    { id: 'right_image', row: 1, col: 3, row_span: 2, col_span: 2 },
    { id: 'left_status', row: 3, col: 1, row_span: 1, col_span: 1 },
    { id: 'left_counts', row: 3, col: 2, row_span: 1, col_span: 1 },
    { id: 'right_status', row: 3, col: 3, row_span: 1, col_span: 1 },
    { id: 'right_counts', row: 3, col: 4, row_span: 1, col_span: 1 },
  ],
  bars: { top: true, bottom: false, left: false, right: false },
  default_flow_id: null,
  widgets: [
    { id: 'left_image', type: 'image', cell: 'left_image', props: { overlays: true, crosshair: false, history: 4 }, source: { kind: 'image' } },
    { id: 'right_image', type: 'image', cell: 'right_image', props: { overlays: true, crosshair: false, history: 4 }, source: { kind: 'image' } },
    { id: 'left_verdict', type: 'verdict', cell: 'left_status', props: {}, source: { kind: 'status' } },
    { id: 'left_stats', type: 'stats', cell: 'left_counts', props: {}, source: { kind: 'counts' } },
    { id: 'right_verdict', type: 'verdict', cell: 'right_status', props: {}, source: { kind: 'status' } },
    { id: 'right_stats', type: 'stats', cell: 'right_counts', props: {}, source: { kind: 'counts' } },
  ],
  theme: {},
}

const measurementBoard: DashboardLayout = {
  rows: 3,
  cols: 4,
  cells: [
    { id: 'stats', row: 1, col: 1, row_span: 1, col_span: 1 },
    { id: 'pie', row: 1, col: 2, row_span: 1, col_span: 1 },
    { id: 'chart', row: 1, col: 3, row_span: 2, col_span: 2 },
    { id: 'table', row: 2, col: 1, row_span: 2, col_span: 2 },
    { id: 'log', row: 3, col: 3, row_span: 1, col_span: 2 },
  ],
  bars: { top: true, bottom: true, left: false, right: false },
  default_flow_id: null,
  widgets: [
    { id: 'today', type: 'stats', cell: 'stats', props: {}, source: { kind: 'counts' } },
    { id: 'yield_mix', type: 'pie', cell: 'pie', props: {}, source: { kind: 'counts' } },
    { id: 'width_trend', type: 'line_chart', cell: 'chart', props: { key: 'width', points: 100, lower: null, upper: null }, source: { kind: 'spc', key: 'width' } },
    { id: 'measurements', type: 'table', cell: 'table', props: { columns: ['verdict', 'width', 'height'], rows: 20, rules: [] }, source: { kind: 'output' } },
    { id: 'recent_log', type: 'log', cell: 'log', props: { rows: 20 }, source: { kind: 'status' } },
  ],
  theme: {},
}

const operatorPanel: DashboardLayout = {
  rows: 3,
  cols: 4,
  cells: [
    { id: 'control', row: 1, col: 1, row_span: 1, col_span: 2 },
    { id: 'buttons', row: 1, col: 3, row_span: 1, col_span: 2 },
    { id: 'params', row: 2, col: 1, row_span: 1, col_span: 2 },
    { id: 'variables', row: 2, col: 3, row_span: 1, col_span: 2 },
    { id: 'lights', row: 3, col: 1, row_span: 1, col_span: 4 },
  ],
  bars: { top: true, bottom: true, left: true, right: false },
  default_flow_id: null,
  widgets: [
    { id: 'run_control', type: 'run_control', cell: 'control', props: { flow_id: null }, source: { kind: 'status' } },
    { id: 'start_button', type: 'button', cell: 'buttons', props: { action: 'run_once', flow_id: null, recipe: null, variable: null, value: null, url: null }, source: { kind: 'status' } },
    { id: 'exposure', type: 'param', cell: 'params', props: { node: 'camera', param: 'exposure_ms' }, source: { kind: 'output' } },
    { id: 'lot', type: 'variable', cell: 'variables', props: { variable: 'lot', scope: 'flow', editable: true }, source: { kind: 'variable', key: 'lot' } },
    { id: 'auto_mode', type: 'switch', cell: 'variables', props: { variable: 'auto_mode', scope: 'station' }, source: { kind: 'variable', key: 'auto_mode' } },
    { id: 'traffic', type: 'traffic_light', cell: 'lights', props: {}, source: { kind: 'status' } },
    { id: 'threshold_light', type: 'conditional_light', cell: 'lights', props: { key: 'width', op: 'between', value: 9.5, value2: 10.5, color_true: '#22c55e', color_false: '#ef4444' }, source: { kind: 'output', key: 'width' } },
  ],
  theme: {},
}

const multiImageWall: DashboardLayout = {
  rows: 3,
  cols: 4,
  cells: [
    { id: 'wall', row: 1, col: 1, row_span: 2, col_span: 4 },
    { id: 'verdict', row: 3, col: 1, row_span: 1, col_span: 1 },
    { id: 'stats', row: 3, col: 2, row_span: 1, col_span: 1 },
    { id: 'clock', row: 3, col: 3, row_span: 1, col_span: 1 },
    { id: 'device', row: 3, col: 4, row_span: 1, col_span: 1 },
  ],
  bars: { top: true, bottom: false, left: false, right: false },
  default_flow_id: null,
  widgets: [
    { id: 'images', type: 'images', cell: 'wall', props: { items: [{ title: 'Camera A', node: 'camera_a', port: 'image' }, { title: 'Camera B', node: 'camera_b', port: 'image' }, { title: 'Camera C', node: 'camera_c', port: 'image' }, { title: 'Camera D', node: 'camera_d', port: 'image' }], columns: 4, overlays: true, history: 1 }, source: { kind: 'image' } },
    { id: 'verdict', type: 'verdict', cell: 'verdict', props: {}, source: { kind: 'status' } },
    { id: 'today', type: 'stats', cell: 'stats', props: {}, source: { kind: 'counts' } },
    { id: 'clock', type: 'clock', cell: 'clock', props: { format: 'HH:mm:ss' }, source: { kind: 'device' } },
    { id: 'device', type: 'device_status', cell: 'device', props: {}, source: { kind: 'device' } },
  ],
  theme: {},
}

const deviceStatus: DashboardLayout = {
  rows: 3,
  cols: 4,
  cells: [
    { id: 'device', row: 1, col: 1, row_span: 2, col_span: 2 },
    { id: 'run', row: 1, col: 3, row_span: 1, col_span: 1 },
    { id: 'clock', row: 1, col: 4, row_span: 1, col_span: 1 },
    { id: 'counts', row: 2, col: 3, row_span: 1, col_span: 2 },
    { id: 'log', row: 3, col: 1, row_span: 1, col_span: 4 },
  ],
  bars: { top: true, bottom: true, left: false, right: true },
  default_flow_id: null,
  widgets: [
    { id: 'device', type: 'device_status', cell: 'device', props: {}, source: { kind: 'device' } },
    { id: 'run_status', type: 'run_status', cell: 'run', props: {}, source: { kind: 'status' } },
    { id: 'clock', type: 'clock', cell: 'clock', props: { format: 'HH:mm:ss' }, source: { kind: 'device' } },
    { id: 'counts', type: 'stats', cell: 'counts', props: {}, source: { kind: 'counts' } },
    { id: 'log', type: 'log', cell: 'log', props: { rows: 50 }, source: { kind: 'status' } },
  ],
  theme: {},
}

export const DASHBOARD_TEMPLATES: DashboardTemplate[] = [
  { key: 'singleFlowBench', titleKey: 'dashboardDesign.templates.singleFlowBench.title', descriptionKey: 'dashboardDesign.templates.singleFlowBench.description', layout: singleFlowBench },
  { key: 'dualFlowCompare', titleKey: 'dashboardDesign.templates.dualFlowCompare.title', descriptionKey: 'dashboardDesign.templates.dualFlowCompare.description', layout: dualFlowCompare },
  { key: 'measurementBoard', titleKey: 'dashboardDesign.templates.measurementBoard.title', descriptionKey: 'dashboardDesign.templates.measurementBoard.description', layout: measurementBoard },
  { key: 'operatorPanel', titleKey: 'dashboardDesign.templates.operatorPanel.title', descriptionKey: 'dashboardDesign.templates.operatorPanel.description', layout: operatorPanel },
  { key: 'multiImageWall', titleKey: 'dashboardDesign.templates.multiImageWall.title', descriptionKey: 'dashboardDesign.templates.multiImageWall.description', layout: multiImageWall },
  { key: 'deviceStatus', titleKey: 'dashboardDesign.templates.deviceStatus.title', descriptionKey: 'dashboardDesign.templates.deviceStatus.description', layout: deviceStatus },
]

export const DASHBOARD_CREATE_TEMPLATES: DashboardTemplate[] = [
  { key: 'empty', titleKey: 'dashboardDesign.templates.empty.title', descriptionKey: 'dashboardDesign.templates.empty.description', layout: EMPTY_DASHBOARD_LAYOUT },
  { key: 'default', titleKey: 'dashboardDesign.templates.default.title', descriptionKey: 'dashboardDesign.templates.default.description', layout: DEFAULT_DASHBOARD_LAYOUT },
  ...DASHBOARD_TEMPLATES,
]

export function cloneDashboardTemplate(keyOrLayout: DashboardTemplateKey | string | DashboardLayout): DashboardLayout {
  const layout = typeof keyOrLayout === 'string'
    ? (DASHBOARD_CREATE_TEMPLATES.find((template) => template.key === keyOrLayout)?.layout ?? EMPTY_DASHBOARD_LAYOUT)
    : keyOrLayout
  return clone(layout)
}
