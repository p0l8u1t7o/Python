/**
 * 頂列（EditorToolbar）：兩列，寬度不足時換行（flex-wrap）。常駐的只有高頻動作（Suggest5 第 5 點），其餘收進「更多」。
 *  - 第一列：流程名稱、儲存狀態、儲存、（窄螢幕的工具／設定／結果抽屜入口）、目前配方、（唯讀／問題／鎖定／停用／未教導標籤）；
 *            右側：即時 badge、容量、復原／重做、流程子導覽（檢測任務／畫布／參數卡／統計）、「更多」選單
 *            （範本、配方管理、版本、自動排版、摺疊任務、Golden Set、匯出、清空結果、清除執行紀錄）。
 *  - 第二列：試執行、影像序列試執行、用上次影像重跑、上傳暫存影像、連續執行；右側：fps 標籤、說明選單。
 * 選取／平移切換在畫布右上角（FlowCanvas 的 CanvasModePanel），不在頂列。
 * 全部是受控 props，狀態與動作都在 FlowEditorPage。
 */
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Boxes, BookOpen, Download, Eraser, FlaskConical, Gem, HelpCircle, History, ImageUp, Keyboard, Layers2, LayoutTemplate, ListChecks, Lock, MoreHorizontal, Network, PanelLeft, Pause, Play, Plug, PowerOff, Radio, Redo2, Save, SlidersHorizontal, Square, Trash2, TriangleAlert, Undo2, X } from 'lucide-react'
import { Link } from 'react-router-dom'

import { CapacityPill } from '@/components/layout/AppShell'
import { FlowSubNav } from '@/components/flow/FlowSubNav'
import { VersionPanel } from '@/components/flow/VersionPanel'
import { BoundRecipeSelect } from '@/components/recipes/BoundRecipeSelect'
import { ActionMenu, ActionMenuItem, ActionMenuSeparator, Badge, Button, IconButton } from '@/components/ui'
import type { FlowRecipe, ScratchImage } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'

export interface EditorToolbarProps {
  flowId: number
  /** 還原舊版之後要重新載入畫布 */
  onVersionRestored?: () => void
  name: string
  onNameChange: (name: string) => void
  dirty: boolean
  readOnly: boolean
  saving: boolean
  onSave: () => void
  /** 窄螢幕：把左側工具區／右側設定／結果面板以抽屜開啟（面板本身在 < md／< lg 時不顯示） */
  onOpenDrawer?: (which: 'tools' | 'settings' | 'results') => void
  problemCount: number
  execLocked: boolean
  lockHint?: string
  /** 流程已停用（is_enabled=false）：後端會拒絕連續執行／外部觸發，試執行不受影響 */
  flowDisabled?: boolean
  previewing: boolean
  onPreview: () => void
  sequenceAvailable: boolean
  sequenceRunning: boolean
  sequencePaused: boolean
  sequenceLabel: string
  sequenceIntervalMs: number
  onSequenceStart: () => void
  onSequencePause: () => void
  onSequenceResume: () => void
  onSequenceStop: () => void
  onSequenceIntervalChange: (value: number) => void
  reuseImage: boolean
  canReuse: boolean
  onReuseChange: (value: boolean) => void
  scratch: ScratchImage | null
  uploadingScratch: boolean
  onUploadScratch: (file: File) => void
  onClearScratch: () => void
  isContinuous: boolean
  continuousPending: boolean
  onToggleContinuous: () => void
  fpsLabel?: string
  connected: boolean
  onUndo: () => void
  onRedo: () => void
  onAutoLayout: () => void
  taskGroupCount?: number
  collapsedTaskCount?: number
  onToggleTaskGroups?: () => void
  resetting: boolean
  /** 清除執行紀錄（記憶體內的執行紀錄與統計；呼叫端會先列出影響再確認） */
  onReset: () => void
  onClearResults: () => void
  onLoadTemplate: () => void
  onSaveTemplate: () => void
  /** 綁定配方：有配方時顯示「綁定」下拉（is_default）；連續執行／外部觸發都用綁定的配方 */
  recipes?: FlowRecipe[]
  onManageRecipes?: () => void
  /** 未教導（commissioned=false） */
  notCommissioned?: boolean
  onExport?: () => void
  /** tool＝複合工具的畫布：沒有配方／子導覽／連續執行／Golden Set，匯出的是 .tool.json */
  mode?: 'flow' | 'tool'
}

/** 暫存影像標籤：檔名＋尺寸＋清除。編輯器與工具頁共用。 */
export function ScratchBadge({ scratch, onClear }: { scratch: ScratchImage; onClear: () => void }) {
  const { t } = useTranslation()
  return (
    <span className="flex items-center gap-1 rounded-md border border-brand/40 bg-brand-soft px-1.5 py-0.5 text-[11px] text-brand" title={t('editor.scratchHint')} data-testid="scratch-badge">
      <ImageUp size={11} />
      <span className="max-w-32 truncate">{scratch.name}</span>
      <span className="tnum opacity-75">{scratch.width}×{scratch.height}</span>
      <button type="button" className="rounded p-0.5 hover:bg-brand/15" onClick={onClear} aria-label={t('editor.scratchClear')} title={t('editor.scratchClear')} data-testid="scratch-clear">
        <X size={11} />
      </button>
    </span>
  )
}

export function EditorToolbar(p: EditorToolbarProps) {
  const { t } = useTranslation()
  const canTeach = useAuth().can('flows.teach')  // 沒有現場教導功能的角色不給參數卡入口
  const scratchInput = useRef<HTMLInputElement>(null)
  const [versionsOpen, setVersionsOpen] = useState(false)
  return (
    <header className="flex flex-col gap-1 border-b border-line bg-surface px-3 py-1.5" data-testid="editor-toolbar">
      {/* 第一列：名稱、儲存、目前配方、標籤；右側子導覽與「更多」 */}
      <div className="flex flex-nowrap items-center gap-1.5 overflow-x-auto md:flex-wrap md:overflow-visible" data-testid="toolbar-row-1">
        <input className="input !w-48 min-w-32 !py-1 font-medium" value={p.name} onChange={(e) => p.onNameChange(e.target.value)} placeholder={t('editor.untitled')} aria-label={t('common.name')} />
        {p.dirty ? <span className="whitespace-nowrap text-[11px] text-warning">{t('editor.unsaved')}</span> : null}
        <span title={p.readOnly ? t('flows.readOnlyHint') : t('editor.saveShortcut')}>
          <Button size="sm" variant={p.dirty ? 'primary' : 'secondary'} icon={<Save size={14} />} loading={p.saving} disabled={p.readOnly} onClick={p.onSave} data-testid="btn-save">
            {p.dirty ? t('editor.save') : t('editor.savedState')}
          </Button>
        </span>
        {p.onOpenDrawer ? (
          <span className="flex items-center gap-1 lg:hidden" data-testid="editor-drawer-buttons">
            <Button size="sm" className="md:hidden" icon={<PanelLeft size={14} />} onClick={() => p.onOpenDrawer?.('tools')} data-testid="editor-drawer-tools">{t('editor.drawerTools')}</Button>
            <Button size="sm" icon={<SlidersHorizontal size={14} />} onClick={() => p.onOpenDrawer?.('settings')} data-testid="editor-drawer-settings">{t('editor.drawerSettings')}</Button>
            <Button size="sm" icon={<ListChecks size={14} />} onClick={() => p.onOpenDrawer?.('results')} data-testid="editor-drawer-results">{t('editor.drawerResults')}</Button>
          </span>
        ) : null}
        {p.mode === 'tool' ? (
          <Link to="/tools" className="flex items-center gap-1 whitespace-nowrap rounded-md border border-brand/40 bg-brand-soft px-1.5 py-0.5 text-[11px] text-brand hover:underline" title={t('editor.composite.toolModeHint')} data-testid="tool-mode-badge">
            <Boxes size={11} /> {t('editor.composite.toolMode')}
          </Link>
        ) : null}
        {p.mode !== 'tool' && p.recipes && p.recipes.length > 0 ? <BoundRecipeSelect flowId={p.flowId} recipes={p.recipes} disabled={p.readOnly} testId="editor-recipe" /> : null}
        {p.readOnly ? (
          <span className="flex items-center gap-1 whitespace-nowrap text-[11px] text-muted" title={t('flows.readOnlyHint')} data-testid="readonly-badge">
            <Lock size={12} /> {t('flows.readOnly')}
          </span>
        ) : null}
        {p.problemCount > 0 ? (
          <span className="flex items-center gap-1 whitespace-nowrap text-[11px] text-critical" title={t('editor.toast.validationWarning', { count: p.problemCount })}>
            <TriangleAlert size={13} /> {t('editor.problems', { count: p.problemCount })}
          </span>
        ) : null}
        {p.execLocked ? (
          <span className="flex items-center gap-1 whitespace-nowrap text-[11px] text-warning" title={p.lockHint} data-testid="exec-locked-badge">
            <Lock size={12} /> {t('lock.short')}
          </span>
        ) : null}
        {p.flowDisabled && p.mode !== 'tool' ? (
          <span className="flex items-center gap-1 whitespace-nowrap text-[11px] text-muted" title={t('editor.flowDisabledHint')} data-testid="flow-disabled-badge">
            <PowerOff size={12} /> {t('editor.flowDisabled')}
          </span>
        ) : null}
        {p.notCommissioned && p.mode !== 'tool' ? (
          canTeach ? (
            <Link to={`/flows/${p.flowId}/teach`} className="flex items-center gap-1 whitespace-nowrap rounded-md border border-warning/40 bg-warning-soft px-1.5 py-0.5 text-[11px] text-warning hover:underline" title={t('flows.notCommissionedHint')} data-testid="not-commissioned-badge">
              <SlidersHorizontal size={11} /> {t('flows.notCommissioned')}
            </Link>
          ) : (
            <span className="flex items-center gap-1 whitespace-nowrap rounded-md border border-warning/40 bg-warning-soft px-1.5 py-0.5 text-[11px] text-warning" title={t('flows.notCommissionedHint')} data-testid="not-commissioned-badge">
              <SlidersHorizontal size={11} /> {t('flows.notCommissioned')}
            </span>
          )
        ) : null}
        <span className="ml-auto flex flex-nowrap items-center gap-1 md:flex-wrap">
          <Badge tone={p.connected ? 'ok' : 'neutral'}>{p.connected ? t('dashboard.live') : t('dashboard.offline')}</Badge>
          <CapacityPill />
          <IconButton label={t('editor.undo')} onClick={p.onUndo} size="sm"><Undo2 size={15} /></IconButton>
          <IconButton label={t('editor.redo')} onClick={p.onRedo} size="sm"><Redo2 size={15} /></IconButton>
          {p.mode !== 'tool' ? <FlowSubNav flowId={p.flowId} /> : null}
          <ActionMenu testId="editor-more" label={t('common.more')} trigger={(open, props) => (
            <Button size="sm" icon={<MoreHorizontal size={14} />} active={open} title={t('common.more')} {...props}>{t('common.more')}</Button>
          )}>
            {p.mode !== 'tool' ? <ActionMenuItem icon={<LayoutTemplate size={13} />} onClick={p.onLoadTemplate} testId="menu-load-template">{t('templates.load')}</ActionMenuItem> : null}
            {p.mode !== 'tool' ? <ActionMenuItem icon={<Save size={13} />} onClick={p.onSaveTemplate} testId="menu-save-template">{t('templates.saveAs')}</ActionMenuItem> : null}
            {p.onManageRecipes && p.mode !== 'tool' ? <ActionMenuItem icon={<BookOpen size={13} />} onClick={p.onManageRecipes} title={t('recipes.manage')} testId="menu-recipes">{t('recipes.drawerTitle')}</ActionMenuItem> : null}
            <ActionMenuItem icon={<History size={13} />} onClick={() => setVersionsOpen(true)} testId="menu-versions">{t('versions.open')}</ActionMenuItem>
            <ActionMenuSeparator />
            <ActionMenuItem icon={<Network size={13} />} onClick={p.onAutoLayout} title={t('editor.autoLayoutHint')} testId="menu-auto-layout">{t('editor.autoLayout')}</ActionMenuItem>
            {p.onToggleTaskGroups && p.mode !== 'tool' ? (
              <ActionMenuItem icon={<Layers2 size={13} />} disabled={!p.taskGroupCount} onClick={p.onToggleTaskGroups} title={t('editor.groups.toggleHint')} testId="btn-toggle-groups">
                {p.collapsedTaskCount ? t('editor.groups.expandAll') : t('editor.groups.collapseTasks')}
              </ActionMenuItem>
            ) : null}
            <ActionMenuSeparator />
            {p.mode !== 'tool' ? <ActionMenuItem icon={<Gem size={13} />} to={`/flows/${p.flowId}/golden`} testId="btn-golden">{t('editor.golden')}</ActionMenuItem> : null}
            {p.onExport ? <ActionMenuItem icon={<Download size={13} />} onClick={p.onExport} title={t('flows.exportHint')} testId="btn-export">{t('editor.export')}</ActionMenuItem> : null}
            <ActionMenuSeparator />
            <ActionMenuItem icon={<Eraser size={13} />} onClick={p.onClearResults} title={t('editor.clearResultsHint')} testId="editor-clear-results">{t('editor.clearResults')}</ActionMenuItem>
            {p.mode !== 'tool' ? <ActionMenuItem icon={<Trash2 size={13} />} danger disabled={p.readOnly || p.resetting} onClick={p.onReset} title={t('editor.clearHistoryHint')} testId="btn-reset">{t('editor.clearHistory')}</ActionMenuItem> : null}
          </ActionMenu>
          <VersionPanel flowId={p.flowId} open={versionsOpen} onClose={() => setVersionsOpen(false)} onRestored={p.onVersionRestored} />
        </span>
      </div>

      {/* 第二列：執行相關 */}
      <div className="flex flex-nowrap items-center gap-1.5 overflow-x-auto md:flex-wrap md:overflow-visible" data-testid="toolbar-row-2">
        <span title={p.lockHint ?? t('editor.previewHint')}>
          <Button size="sm" variant="primary" icon={<FlaskConical size={14} />} loading={p.previewing} disabled={p.execLocked} onClick={p.onPreview} data-testid="btn-preview">
            {t('editor.preview')}
          </Button>
        </span>
        {p.sequenceAvailable && p.mode !== 'tool' ? (
          <span className="flex items-center gap-1.5 rounded-md border border-line px-1.5 py-0.5" title={t('editor.sequenceHint')} data-testid="sequence-preview-controls">
            {p.sequenceRunning && !p.sequencePaused ? (
              <Button size="sm" icon={<Pause size={14} />} disabled={p.execLocked} onClick={p.onSequencePause} data-testid="btn-sequence-preview">
                {t('editor.sequencePause')}
              </Button>
            ) : (
              <Button size="sm" icon={<Play size={14} />} disabled={p.execLocked} onClick={p.sequencePaused ? p.onSequenceResume : p.onSequenceStart} data-testid="btn-sequence-preview">
                {p.sequencePaused ? t('editor.sequenceResume') : t('editor.sequencePreview')}
              </Button>
            )}
            {p.sequenceRunning || p.sequencePaused ? (
              <Button size="sm" icon={<Square size={14} />} onClick={p.onSequenceStop} data-testid="btn-sequence-stop">
                {t('editor.sequenceStop')}
              </Button>
            ) : null}
            <label className="flex items-center gap-1 text-[11px] text-muted" title={t('editor.sequenceIntervalHint')}>
              {t('editor.sequenceInterval')}
              <input
                className="input !h-7 !w-20 !py-0 text-xs"
                type="number"
                min={100}
                step={100}
                value={p.sequenceIntervalMs}
                onChange={(e) => p.onSequenceIntervalChange(Math.max(100, Number(e.target.value) || 100))}
                data-testid="sequence-preview-interval"
              />
            </label>
            <span className="tnum whitespace-nowrap text-[11px] text-muted" data-testid="sequence-preview-status">{p.sequenceLabel}</span>
          </span>
        ) : null}
        <label className="flex items-center gap-1 whitespace-nowrap text-[11px] text-muted" title={t('editor.reuseImageHint')}>
          <input type="checkbox" className="accent-[var(--brand)]" checked={p.reuseImage} disabled={!p.canReuse || Boolean(p.scratch)} onChange={(e) => p.onReuseChange(e.target.checked)} data-testid="reuse-image" />
          {t('editor.reuseImage')}
        </label>
        {p.scratch ? (
          <ScratchBadge scratch={p.scratch} onClear={p.onClearScratch} />
        ) : (
          <span title={t('editor.scratchHint')}>
            <Button size="sm" icon={<ImageUp size={14} />} loading={p.uploadingScratch} onClick={() => scratchInput.current?.click()} data-testid="btn-scratch">
              {t('editor.scratchUpload')}
            </Button>
          </span>
        )}
        <input
          ref={scratchInput}
          type="file"
          accept="image/*"
          className="hidden"
          data-testid="scratch-input"
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) p.onUploadScratch(file)
          }}
        />
        {p.mode === 'tool' ? <span className="whitespace-nowrap text-[11px] text-muted" title={t('editor.composite.previewHint')} data-testid="tool-mode-preview-hint">{t('editor.composite.previewHint')}</span> : null}
        {p.mode !== 'tool' ? <span className="mx-1 h-5 w-px bg-line" aria-hidden /> : null}
        {p.mode !== 'tool' ? <span title={p.lockHint ?? (p.flowDisabled && !p.isContinuous ? t('editor.flowDisabledHint') : p.isContinuous ? t('editor.continuousOff') : t('editor.continuous'))}>
          <Button size="sm" icon={p.isContinuous ? <Square size={14} /> : <Radio size={14} />} active={p.isContinuous} loading={p.continuousPending} disabled={(p.execLocked || p.flowDisabled) && !p.isContinuous} onClick={p.onToggleContinuous} data-testid="btn-continuous">
            {p.isContinuous ? t('editor.continuousOn') : t('editor.continuous')}
          </Button>
        </span> : null}
        {p.fpsLabel ? <span className="tnum whitespace-nowrap text-[11px] text-muted">{p.fpsLabel}</span> : null}
        <span className="ml-auto flex items-center gap-1">
          <ActionMenu testId="menu-help" label={t('nav.help')} trigger={(_open, props) => <button type="button" className="btn-icon" title={t('nav.help')} aria-label={t('nav.help')} {...props}><HelpCircle size={15} /></button>}>
            <ActionMenuItem icon={<HelpCircle size={13} />} to="/help">{t('helpMenu.help')}</ActionMenuItem>
            <ActionMenuItem icon={<Keyboard size={13} />} to="/help?tab=shortcuts">{t('helpMenu.shortcuts')}</ActionMenuItem>
            <ActionMenuItem icon={<Plug size={13} />} to="/integration">{t('helpMenu.integration')}</ActionMenuItem>
          </ActionMenu>
        </span>
      </div>
    </header>
  )
}
