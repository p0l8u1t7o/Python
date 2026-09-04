/**
 * 頂列（EditorToolbar）：兩列，按鈕都是圖示＋短文字，寬度不足時換行（flex-wrap）。
 *  - 第一列：流程名稱、儲存狀態、儲存、範本下拉、配方鈕、綁定配方下拉、（唯讀／問題／鎖定／停用／未教導標籤）；
 *            右側：即時 badge、容量、復原、自動排列、參數卡／Golden Set／匯出／統計圖示。
 *  - 第二列：試跑、用上次影像重跑、上傳暫存影像、批次測試、連續執行、重置；右側：fps 標籤、說明下拉。
 * 選取／平移切換在畫布右上角（FlowCanvas 的 CanvasModePanel），不在頂列。
 * 全部是受控 props，狀態與動作都在 FlowEditorPage。
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { BarChart3, BookOpen, ChevronDown, Download, Eraser, FlaskConical, Gem, HelpCircle, ImageUp, Images, Keyboard, LayoutTemplate, Lock, Network, Plug, PowerOff, Radio, Save, SlidersHorizontal, Square, TriangleAlert, Undo2, X } from 'lucide-react'
import { Link } from 'react-router-dom'

import { CapacityPill } from '@/components/layout/AppShell'
import { VersionButton } from '@/components/flow/VersionPanel'
import { BoundRecipeSelect } from '@/components/recipes/BoundRecipeSelect'
import { Badge, Button, IconButton } from '@/components/ui'
import type { FlowRecipe, ScratchImage } from '@/lib/types'

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
  problemCount: number
  execLocked: boolean
  lockHint?: string
  /** 流程已停用（is_enabled=false）：後端會拒絕連續執行／外部觸發，試跑不受影響 */
  flowDisabled?: boolean
  previewing: boolean
  onPreview: () => void
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
  onAutoLayout: () => void
  resetting: boolean
  onReset: () => void
  onBatchTest: () => void
  onLoadTemplate: () => void
  onSaveTemplate: () => void
  /** 綁定配方：有配方時顯示「綁定」下拉（is_default）；連續執行／外部觸發都用綁定的配方 */
  recipes?: FlowRecipe[]
  onManageRecipes?: () => void
  /** 未教導（commissioned=false） */
  notCommissioned?: boolean
  onExport?: () => void
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

/** 小型下拉選單（範本、說明）。 */
export function Dropdown({ trigger, children, testId, align = 'left' }: { trigger: (open: boolean) => ReactNode; children: ReactNode; testId?: string; align?: 'left' | 'right' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  return (
    <div ref={ref} className="relative" data-testid={testId}>
      <span onClick={() => setOpen((v) => !v)}>{trigger(open)}</span>
      {open ? (
        <div role="menu" className={`absolute top-full z-40 mt-1 w-52 rounded-xl border border-line bg-surface p-1 text-sm shadow-lg ${align === 'right' ? 'right-0' : 'left-0'}`} onClick={() => setOpen(false)}>
          {children}
        </div>
      ) : null}
    </div>
  )
}

export function MenuItem({ icon, children, onClick, to, disabled, testId }: { icon?: ReactNode; children: ReactNode; onClick?: () => void; to?: string; disabled?: boolean; testId?: string }) {
  const cls = 'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-surface-muted disabled:opacity-40'
  if (to) return <Link to={to} role="menuitem" className={cls} data-testid={testId}>{icon} {children}</Link>
  return <button type="button" role="menuitem" className={cls} onClick={onClick} disabled={disabled} data-testid={testId}>{icon} {children}</button>
}

export function EditorToolbar(p: EditorToolbarProps) {
  const { t } = useTranslation()
  const scratchInput = useRef<HTMLInputElement>(null)
  return (
    <header className="flex flex-col gap-1 border-b border-line bg-surface px-3 py-1.5" data-testid="editor-toolbar">
      {/* 第一列：名稱、儲存、範本、配方、綁定 */}
      <div className="flex flex-nowrap items-center gap-1.5 overflow-x-auto md:flex-wrap md:overflow-visible" data-testid="toolbar-row-1">
        <input className="input !w-48 min-w-32 !py-1 font-medium" value={p.name} onChange={(e) => p.onNameChange(e.target.value)} placeholder={t('editor.untitled')} aria-label={t('common.name')} />
        {p.dirty ? <span className="whitespace-nowrap text-[11px] text-warning">{t('editor.unsaved')}</span> : null}
        <span title={p.readOnly ? t('flows.readOnlyHint') : t('editor.saveShortcut')}>
          <Button size="sm" variant={p.dirty ? 'primary' : 'secondary'} icon={<Save size={14} />} loading={p.saving} disabled={p.readOnly} onClick={p.onSave}>
            {p.dirty ? t('editor.save') : t('editor.savedState')}
          </Button>
        </span>
        <Dropdown testId="menu-templates" trigger={(open) => <Button size="sm" icon={<LayoutTemplate size={14} />} active={open} data-testid="btn-templates">{t('templates.menu')} <ChevronDown size={12} /></Button>}>
          <MenuItem icon={<LayoutTemplate size={13} />} onClick={p.onLoadTemplate} testId="menu-load-template">{t('templates.load')}</MenuItem>
          <MenuItem icon={<Save size={13} />} onClick={p.onSaveTemplate} testId="menu-save-template">{t('templates.saveAs')}</MenuItem>
        </Dropdown>
        {p.onManageRecipes ? (
          <Button size="sm" icon={<BookOpen size={14} />} onClick={p.onManageRecipes} title={t('recipes.manage')} data-testid="btn-recipes">{t('recipes.drawerTitle')}</Button>
        ) : null}
        <VersionButton flowId={p.flowId} onRestored={p.onVersionRestored} />
        {p.recipes && p.recipes.length > 0 ? <BoundRecipeSelect flowId={p.flowId} recipes={p.recipes} disabled={p.readOnly} testId="editor-recipe" /> : null}
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
        {p.flowDisabled ? (
          <span className="flex items-center gap-1 whitespace-nowrap text-[11px] text-muted" title={t('editor.flowDisabledHint')} data-testid="flow-disabled-badge">
            <PowerOff size={12} /> {t('editor.flowDisabled')}
          </span>
        ) : null}
        {p.notCommissioned ? (
          <Link to={`/flows/${p.flowId}/teach`} className="flex items-center gap-1 whitespace-nowrap rounded-md border border-warning/40 bg-warning-soft px-1.5 py-0.5 text-[11px] text-warning hover:underline" title={t('flows.notCommissionedHint')} data-testid="not-commissioned-badge">
            <SlidersHorizontal size={11} /> {t('flows.notCommissioned')}
          </Link>
        ) : null}
        <span className="ml-auto flex flex-nowrap items-center gap-1 md:flex-wrap">
          <Badge tone={p.connected ? 'ok' : 'neutral'}>{p.connected ? t('dashboard.live') : t('dashboard.offline')}</Badge>
          <CapacityPill />
          <IconButton label={t('editor.undo')} onClick={p.onUndo} size="sm"><Undo2 size={15} /></IconButton>
          <IconButton label={t('editor.autoLayoutHint')} onClick={p.onAutoLayout} size="sm"><Network size={15} /></IconButton>
          <Link to={`/flows/${p.flowId}/teach`} className="btn-icon" title={t('editor.teach')} aria-label={t('editor.teach')} data-testid="btn-teach"><SlidersHorizontal size={15} /></Link>
          <Link to={`/flows/${p.flowId}/golden`} className="btn-icon" title={t('editor.golden')} aria-label={t('editor.golden')} data-testid="btn-golden"><Gem size={15} /></Link>
          {p.onExport ? <IconButton label={t('editor.export')} title={t('flows.exportHint')} onClick={p.onExport} size="sm" data-testid="btn-export"><Download size={15} /></IconButton> : null}
          <Link to={`/flows/${p.flowId}/stats`} className="btn-icon" title={t('stats.open')} aria-label={t('stats.open')} data-testid="btn-stats"><BarChart3 size={15} /></Link>
        </span>
      </div>

      {/* 第二列：執行相關 */}
      <div className="flex flex-nowrap items-center gap-1.5 overflow-x-auto md:flex-wrap md:overflow-visible" data-testid="toolbar-row-2">
        <span title={p.lockHint ?? t('editor.previewHint')}>
          <Button size="sm" variant="primary" icon={<FlaskConical size={14} />} loading={p.previewing} disabled={p.execLocked} onClick={p.onPreview} data-testid="btn-preview">
            {t('editor.preview')}
          </Button>
        </span>
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
        <span title={p.lockHint ?? t('batch.hint')}>
          <Button size="sm" icon={<Images size={14} />} disabled={p.execLocked} onClick={p.onBatchTest} data-testid="btn-batch">
            {t('batch.title')}
          </Button>
        </span>
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        <span title={p.lockHint ?? (p.flowDisabled && !p.isContinuous ? t('editor.flowDisabledHint') : p.isContinuous ? t('editor.continuousOff') : t('editor.continuous'))}>
          <Button size="sm" icon={p.isContinuous ? <Square size={14} /> : <Radio size={14} />} active={p.isContinuous} loading={p.continuousPending} disabled={(p.execLocked || p.flowDisabled) && !p.isContinuous} onClick={p.onToggleContinuous} data-testid="btn-continuous">
            {p.isContinuous ? t('editor.continuousOn') : t('editor.continuous')}
          </Button>
        </span>
        {p.fpsLabel ? <span className="tnum whitespace-nowrap text-[11px] text-muted">{p.fpsLabel}</span> : null}
        <span title={t('editor.resetHint')}>
          <Button size="sm" icon={<Eraser size={14} />} loading={p.resetting} disabled={p.readOnly} onClick={p.onReset} data-testid="btn-reset">
            {t('editor.reset')}
          </Button>
        </span>
        <span className="ml-auto flex items-center gap-1">
          <Dropdown testId="menu-help" align="right" trigger={() => <button type="button" className="btn-icon" title={t('nav.help')} aria-label={t('nav.help')}><HelpCircle size={15} /></button>}>
            <MenuItem icon={<HelpCircle size={13} />} to="/help">{t('helpMenu.help')}</MenuItem>
            <MenuItem icon={<Keyboard size={13} />} to="/help?tab=shortcuts">{t('helpMenu.shortcuts')}</MenuItem>
            <MenuItem icon={<Plug size={13} />} to="/integration">{t('helpMenu.integration')}</MenuItem>
          </Dropdown>
        </span>
      </div>
    </header>
  )
}
