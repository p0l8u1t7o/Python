/**
 * 畫布（FlowCanvas）：React Flow 的薄包裝，統一 nodeTypes / edgeTypes、背景、小地圖、縮放滑桿與互動模式。
 * 節點／邊的狀態與所有編輯回呼由 FlowEditorPage 提供（payloads 是那邊的真相）。
 *
 * 互動模式（預設 pan，存 localStorage `vs.canvasMode`；切換鈕在畫布右上角 `CanvasModePanel`）：
 *   pan    = 左鍵拖曳平移、Shift+拖曳框選（預設）；
 *   select = 左鍵框選（部分重疊即選中）、中鍵／右鍵平移。
 */
import { Background, MiniMap, Panel, ReactFlow, SelectionMode, type ReactFlowProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { BoxSelect, Hand } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { SegmentedControl } from '@/components/ui'
import { useTheme } from '@/providers/ThemeProvider'
import { FlowEdge } from './FlowEdge'
import { GroupNode } from './GroupNode'
import { NoteNode, ToolNode } from './ToolNode'
import { ZoomSlider } from './ZoomSlider'

const NODE_TYPES = { tool: ToolNode, note: NoteNode, group: GroupNode }
const EDGE_TYPES = { flow: FlowEdge }

export type InteractionMode = 'select' | 'pan'
export const CANVAS_MODE_KEY = 'vs.canvasMode'

export function readInteractionMode(): InteractionMode {
  try {
    return localStorage.getItem(CANVAS_MODE_KEY) === 'select' ? 'select' : 'pan'
  } catch {
    return 'pan'
  }
}

export function storeInteractionMode(mode: InteractionMode) {
  try {
    localStorage.setItem(CANVAS_MODE_KEY, mode)
  } catch {
    /* ignore */
  }
}

/** 畫布右上角的選取／平移切換（與縮放滑桿同風格）。 */
export function CanvasModePanel({ interaction, onChange }: { interaction: InteractionMode; onChange: (mode: InteractionMode) => void }) {
  const { t } = useTranslation()
  return (
    <Panel position="top-right" className="rounded-lg border border-line bg-surface p-0.5 shadow-sm" data-testid="canvas-mode">
      <SegmentedControl
        size="sm"
        className="!border-0 !bg-transparent !p-0"
        value={interaction}
        onChange={onChange}
        options={[
          { value: 'select', label: <span className="flex items-center gap-1"><BoxSelect size={12} /> {t('editor.modeSelect')}</span>, title: t('editor.modeSelectHint') },
          { value: 'pan', label: <span className="flex items-center gap-1"><Hand size={12} /> {t('editor.modePan')}</span>, title: t('editor.modePanHint') },
        ]}
      />
    </Panel>
  )
}

export function FlowCanvas({ interaction, onInteractionChange, onAutoLayout, edgeValues, onEdgeValuesChange, children, ...rest }: ReactFlowProps & { interaction: InteractionMode; onInteractionChange: (mode: InteractionMode) => void; onAutoLayout: () => void; edgeValues?: boolean; onEdgeValuesChange?: (on: boolean) => void }) {
  // 小地圖／控制列跟著主題（深色主題下原本掛 light class，小地圖是白色方塊）
  const theme = useTheme()
  return (
    <ReactFlow
      nodeTypes={NODE_TYPES}
      edgeTypes={EDGE_TYPES}
      deleteKeyCode={null}
      fitView
      minZoom={0.2}
      maxZoom={2}
      selectionOnDrag={interaction === 'select'}
      panOnDrag={interaction === 'select' ? [1, 2] : true}
      selectionKeyCode="Shift"
      selectionMode={SelectionMode.Partial}
      selectNodesOnDrag={false}
      // 拉線時放開在把手 80px 內就自動接上（VM 的 ModuleConnectSpan）；預設 20px 要對得很準
      connectionRadius={80}
      colorMode={theme.resolved}
      {...rest}
    >
      <Background />
      {/* 手機寬度只留畫布與工具列（CLAUDE.md 的響應式規則）：小地圖會壓到縮放列與右下角的助手鈕 */}
      <MiniMap pannable zoomable className="!h-24 !w-36 max-md:hidden" />
      <ZoomSlider onAutoLayout={onAutoLayout} edgeValues={edgeValues} onEdgeValuesChange={onEdgeValuesChange} />
      <CanvasModePanel interaction={interaction} onChange={onInteractionChange} />
      {children}
    </ReactFlow>
  )
}
