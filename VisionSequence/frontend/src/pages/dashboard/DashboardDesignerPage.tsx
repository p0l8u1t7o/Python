import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { Link, Navigate, useBlocker, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ChevronDown, ChevronUp, Copy, Download, FileInput, Grid3X3, LayoutTemplate, PanelRight, Plus, Redo2, Save, Scissors, Trash2, Undo2 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'

import { WidgetRenderer } from '@/components/dashboard/WidgetRenderer'
import { CodeField } from '@/components/editor/CodeField'
import { Button, Checkbox, ErrorState, Field, IconButton, LoadingState, Select, Switch, Tabs, TextInput } from '@/components/ui'
import { cellById, nestedWidgetIds, resolveFlow } from '@/lib/dashboard'
import { downloadDashboardJson, parseDashboardLayout, prettyDashboardLayout, readDashboardJson } from '@/lib/dashboardIo'
import { validateDashboardLayout, WIDGET_SCHEMA, DASHBOARD_SOURCE_KINDS, DASHBOARD_WIDGET_TYPES, defaultProps, requiredDefaults, type DashboardPropSpec } from '@/lib/dashboardSchema'
import { cloneDashboardTemplate, DASHBOARD_TEMPLATES } from '@/lib/dashboardTemplates'
import { errorMessage } from '@/lib/errors'
import { api } from '@/lib/api'
import { useConfirm } from '@/lib/useConfirm'
import { useDashboard, useDashboardData, useDashboardMutations, useDashboards, useFlow, useFlows, useToolTypes } from '@/lib/queries'
import { graphOutputNames } from '@/lib/portLayout'
import type { DashboardCell, DashboardLayout, DashboardSourceKind, DashboardWidget, DashboardWidgetSource, DashboardWidgetType, Flow, ToolCatalogue } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

type PanelMode = 'catalog' | 'properties' | 'preview' | 'advanced'
type VariablesPayload = { items?: Record<string, unknown>; station?: Record<string, unknown> }
type FixedImagesPayload = { items?: { id: string; name?: string }[]; count?: number; bytes?: number; orphans?: string[] }

const ICONS: Partial<Record<DashboardWidgetType, ReactNode>> = {
  image: <Grid3X3 className="size-4" />,
  images: <Grid3X3 className="size-4" />,
  table: <Grid3X3 className="size-4" />,
  line_chart: <Grid3X3 className="size-4" />,
  stats: <Grid3X3 className="size-4" />,
  pie: <Grid3X3 className="size-4" />,
  image_static: <Grid3X3 className="size-4" />,
  child: <PanelRight className="size-4" />,
}

export function DashboardDesignerPage() {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const params = useParams()
  const dashboardId = params.id ? Number(params.id) : null
  const dashboard = useDashboard(dashboardId)
  const mutations = useDashboardMutations()
  const inputRef = useRef<HTMLInputElement>(null)
  const { confirm, dialog } = useConfirm()
  const [name, setName] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [layout, setLayout] = useState<DashboardLayout | null>(null)
  const [savedSnapshot, setSavedSnapshot] = useState('')
  const [selectedCell, setSelectedCell] = useState('')
  const [selectedWidget, setSelectedWidget] = useState('')
  const [pendingType, setPendingType] = useState<DashboardWidgetType | null>(null)
  const [panelMode, setPanelMode] = useState<PanelMode>('catalog')
  const [serverError, setServerError] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [layoutText, setLayoutText] = useState('')
  const [layoutError, setLayoutError] = useState('')
  const [past, setPast] = useState<DashboardLayout[]>([])
  const [future, setFuture] = useState<DashboardLayout[]>([])

  useEffect(() => {
    if (!dashboard.data) return
    const normalized = normalizeLayout(dashboard.data.layout)
    const snapshot = JSON.stringify({ name: dashboard.data.name, isDefault: dashboard.data.is_default, layout: normalized })
    setName(dashboard.data.name)
    setIsDefault(dashboard.data.is_default)
    setLayout(normalized)
    setLayoutText(prettyDashboardLayout(normalized))
    setSavedSnapshot(snapshot)
    setPast([])
    setFuture([])
    setSelectedCell(normalized.cells[0]?.id ?? '')
    setSelectedWidget('')
    setServerError('')
  }, [dashboard.data])

  const currentSnapshot = layout ? JSON.stringify({ name, isDefault, layout }) : ''
  const dirty = Boolean(layout && currentSnapshot !== savedSnapshot)
  const schemaErrors = useMemo(() => layout ? validateDashboardLayout(layout) : [], [layout])
  const badWidgets = useMemo(() => new Set(schemaErrors.map((error) => error.widgetId).filter((id): id is string => Boolean(id))), [schemaErrors])

  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }: { currentLocation: { pathname: string }; nextLocation: { pathname: string } }) => dirty && currentLocation.pathname !== nextLocation.pathname,
      [dirty],
    ),
  )

  useEffect(() => {
    if (blocker.state !== 'blocked') return
    void confirm(t('editor.leaveUnsaved'), { title: t('editor.leaveTitle'), confirmLabel: t('editor.leaveAnyway') }).then((ok) => (ok ? blocker.proceed() : blocker.reset()))
  }, [blocker, confirm, t])

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  useEffect(() => {
    if (layout) setLayoutText(prettyDashboardLayout(layout))
  }, [layout])

  if (!auth.loading && !auth.can('flows.edit')) return <Navigate to="/dashboards" replace />
  if (auth.loading || dashboard.isPending || !layout) return <div className="flex h-full items-center justify-center"><LoadingState /></div>
  if (dashboard.isError) return <div className="p-5"><ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} /></div>

  const selectedWidgetObj = layout.widgets.find((widget) => widget.id === selectedWidget) ?? null

  const pushLayout = (next: DashboardLayout) => {
    setLayout((current) => {
      if (current) setPast((items) => [...items.slice(-29), clone(current)])
      return next
    })
    setFuture([])
    setServerError('')
  }

  const updateLayout = (updater: (current: DashboardLayout) => DashboardLayout) => {
    pushLayout(updater(layout))
  }

  const undo = () => {
    const previous = past.at(-1)
    if (!previous) return
    setPast((items) => items.slice(0, -1))
    setFuture((items) => [clone(layout), ...items.slice(0, 29)])
    setLayout(clone(previous))
  }

  const redo = () => {
    const next = future[0]
    if (!next) return
    setFuture((items) => items.slice(1))
    setPast((items) => [...items.slice(-29), clone(layout)])
    setLayout(clone(next))
  }

  const save = async () => {
    const errors = validateDashboardLayout(layout)
    if (errors.length) {
      setServerError(errors[0].message)
      return
    }
    setServerError('')
    try {
      const saved = await mutations.update.mutateAsync({ id: dashboard.data.id, name, is_default: isDefault, layout })
      const normalized = normalizeLayout(saved.layout)
      const snapshot = JSON.stringify({ name: saved.name, isDefault: saved.is_default, layout: normalized })
      setName(saved.name)
      setIsDefault(saved.is_default)
      setLayout(normalized)
      setSavedSnapshot(snapshot)
      setPast([])
      setFuture([])
      toast.success(t('dashboardRun.saved'))
    } catch (error) {
      setServerError(errorMessage(error))
    }
  }

  const applyJson = () => {
    try {
      pushLayout(normalizeLayout(parseDashboardLayout(layoutText)))
      setLayoutError('')
      setAdvancedOpen(false)
    } catch {
      setLayoutError(t('dashboardRun.invalidJson'))
    }
  }

  const importFile = async (file: File | undefined) => {
    if (!file) return
    try {
      pushLayout(normalizeLayout(await readDashboardJson(file)))
      setLayoutError('')
      setAdvancedOpen(false)
    } catch {
      setLayoutError(t('dashboardRun.invalidJson'))
    }
  }

  const applyTemplate = async (key: string) => {
    if (!key) return
    const ok = await confirm(t('dashboardDesign.templateConfirm'), { title: t('dashboardDesign.templateMenu'), confirmLabel: t('dashboardDesign.applyTemplate'), danger: false })
    if (!ok) return
    const next = normalizeLayout(cloneDashboardTemplate(key))
    pushLayout(next)
    setSelectedCell(next.cells[0]?.id ?? '')
    setSelectedWidget('')
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-app">
      <header className="shrink-0 border-b border-line bg-surface px-4 py-3">
        <div className="flex flex-wrap items-end gap-3">
          <Link to="/dashboards" className="btn h-8 px-2.5 text-xs"><ArrowLeft className="size-4" />{t('dashboardRun.backToList')}</Link>
          <TextInput label={t('dashboardRun.name')} value={name} onChange={(event) => setName(event.target.value)} className="w-64" />
          <Checkbox label={t('dashboardRun.isDefault')} checked={isDefault} onChange={setIsDefault} />
          <div className="ml-auto flex flex-wrap items-end gap-2">
            <IconButton label={t('dashboardDesign.undo')} disabled={!past.length} onClick={undo}><Undo2 size={16} /></IconButton>
            <IconButton label={t('dashboardDesign.redo')} disabled={!future.length} onClick={redo}><Redo2 size={16} /></IconButton>
            <Select label={t('dashboardDesign.templateMenu')} value="" placeholder={t('dashboardDesign.applyTemplate')} options={DASHBOARD_TEMPLATES.map((item) => ({ value: item.key, label: t(item.titleKey) }))} onChange={(event) => void applyTemplate(event.target.value)} />
            <Button icon={<Download className="size-4" />} onClick={() => downloadDashboardJson(name, layout)}>{t('dashboardRun.exportJson')}</Button>
            <Button icon={<FileInput className="size-4" />} onClick={() => inputRef.current?.click()}>{t('dashboardRun.importJson')}</Button>
            <input ref={inputRef} type="file" accept="application/json,.json" hidden onChange={(event) => void importFile(event.currentTarget.files?.[0])} />
            <Button icon={<PanelRight className="size-4" />} onClick={() => setPanelMode('preview')}>{t('dashboardDesign.preview')}</Button>
            <Button variant="primary" icon={<Save className="size-4" />} loading={mutations.update.isPending} disabled={!dirty} onClick={() => void save()}>{t('dashboardRun.save')}</Button>
          </div>
        </div>
        {serverError ? <p className="mt-2 text-sm text-critical" data-testid="dash-design-error">{serverError}</p> : null}
        {schemaErrors.length ? <p className="mt-1 text-xs text-warning" data-testid="dash-design-schema">{schemaErrors[0].message}</p> : null}
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-[18rem_minmax(0,1fr)_24rem] overflow-hidden">
        <WidgetCatalog pendingType={pendingType} onPick={setPendingType} />
        <section className="min-h-0 min-w-0 border-x border-line">
          <CanvasHeader layout={layout} onChange={updateLayout} selectedCell={selectedCell} />
          <DashboardCanvas
            layout={layout}
            selectedCell={selectedCell}
            selectedWidget={selectedWidget}
            badWidgets={badWidgets}
            dashboardId={dashboard.data.id}
            pendingType={pendingType}
            onChange={updateLayout}
            onSelectCell={(id) => { setSelectedCell(id); setSelectedWidget('') }}
            onSelectWidget={(id) => { setSelectedWidget(id); setPanelMode('properties') }}
            onAdd={(widget) => { setSelectedWidget(widget.id); setPanelMode('properties'); setPendingType(null) }}
          />
        </section>
        <aside className="flex min-h-0 min-w-0 flex-col bg-surface">
          <Tabs
            size="sm"
            value={panelMode}
            onChange={setPanelMode}
            tabs={[
              { value: 'catalog', label: t('dashboardDesign.catalog') },
              { value: 'properties', label: t('dashboardDesign.properties') },
              { value: 'preview', label: t('dashboardDesign.preview') },
              { value: 'advanced', label: t('dashboardDesign.advanced') },
            ]}
          />
          <div className="min-h-0 flex-1 overflow-auto p-3">
            {panelMode === 'catalog' ? <WidgetCatalog compact pendingType={pendingType} onPick={setPendingType} /> : null}
            {panelMode === 'properties' ? (
              selectedWidgetObj ? (
                <PropertiesPanel
                  layout={layout}
                  widget={selectedWidgetObj}
                  onWidget={(widget) => updateLayout((current) => ({ ...current, widgets: current.widgets.map((item) => item.id === widget.id ? widget : item) }))}
                  onLayout={(patch) => updateLayout((current) => normalizeLayout({ ...current, ...patch }))}
                />
              ) : <EmptyPanel>{t('dashboardDesign.selectWidget')}</EmptyPanel>
            ) : null}
            {panelMode === 'preview' ? <PreviewPanel dashboardId={dashboard.data.id} layout={layout} /> : null}
            {panelMode === 'advanced' ? (
              <div className="space-y-3">
                <button type="button" className="flex w-full items-center justify-between text-sm font-semibold text-heading" onClick={() => setAdvancedOpen((value) => !value)}>
                  <span>{t('dashboardRun.layoutJson')}</span>
                  {advancedOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
                {advancedOpen ? (
                  <>
                    <CodeField label={t('dashboardRun.layoutJson')} hint={t('dashboardDesign.jsonHint')} value={layoutText} onChange={setLayoutText} language="json" />
                    {layoutError ? <p className="text-xs text-critical">{layoutError}</p> : null}
                    <Button variant="primary" onClick={applyJson}>{t('dashboardDesign.applyJson')}</Button>
                  </>
                ) : <p className="text-sm text-muted">{t('dashboardDesign.advancedClosed')}</p>}
              </div>
            ) : null}
          </div>
        </aside>
      </div>
      {dialog}
    </div>
  )
}

function WidgetCatalog({ compact = false, pendingType, onPick }: { compact?: boolean; pendingType: DashboardWidgetType | null; onPick: (type: DashboardWidgetType) => void }) {
  const { t } = useTranslation()
  return (
    <aside className={`${compact ? '' : 'min-h-0 overflow-auto border-r border-line bg-surface p-3'}`} data-testid={compact ? 'dash-design-catalog-compact' : 'dash-design-catalog'}>
      {!compact ? <h2 className="mb-3 text-sm font-semibold text-heading">{t('dashboardDesign.catalog')}</h2> : null}
      <div className="space-y-2">
        {DASHBOARD_WIDGET_TYPES.map((type) => (
          <button
            key={type}
            type="button"
            draggable
            data-testid={`dash-design-add-${type}`}
            onClick={() => onPick(type)}
            onDragStart={(event) => event.dataTransfer.setData('application/x-dashboard-type', type)}
            className={`flex w-full items-start gap-3 rounded-md border px-3 py-2 text-left transition-colors hover:border-brand/70 hover:bg-surface-muted ${pendingType === type ? 'border-brand bg-brand-soft' : 'border-line bg-surface'}`}
          >
            <span className="mt-0.5 shrink-0 text-muted">{ICONS[type] ?? <LayoutTemplate className="size-4" />}</span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-content">{t(`dashboardRun.widgetTypes.${type}`)}</span>
              <span className="mt-0.5 block text-xs leading-snug text-muted">{t(`dashboardDesign.widgetPurpose.${type}`)}</span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  )
}

function CanvasHeader({ layout, selectedCell, onChange }: { layout: DashboardLayout; selectedCell: string; onChange: (updater: (current: DashboardLayout) => DashboardLayout) => void }) {
  const { t } = useTranslation()
  const cell = cellById(layout, selectedCell)
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line bg-surface px-3 py-2">
      <div className="flex flex-wrap items-end gap-2">
        <TextInput label={t('dashboardDesign.rows')} type="number" min={1} max={10} value={layout.rows} onChange={(event) => onChange((current) => normalizeLayout({ ...current, rows: Number(event.target.value) }))} className="w-20" />
        <TextInput label={t('dashboardDesign.cols')} type="number" min={1} max={10} value={layout.cols} onChange={(event) => onChange((current) => normalizeLayout({ ...current, cols: Number(event.target.value) }))} className="w-20" />
        <Button size="sm" icon={<Scissors className="size-4" />} disabled={!cell || (cell.row_span === 1 && cell.col_span === 1)} onClick={() => onChange((current) => splitCell(current, selectedCell))}>{t('dashboardDesign.splitCell')}</Button>
      </div>
      <div className="flex flex-wrap gap-4">
        {(['top', 'bottom', 'left', 'right'] as const).map((bar) => <Checkbox key={bar} label={t(`dashboardDesign.bars.${bar}`)} checked={layout.bars?.[bar] === true} onChange={(value) => onChange((current) => ({ ...current, bars: { ...(current.bars ?? {}), [bar]: value } }))} />)}
      </div>
    </div>
  )
}

function DashboardCanvas({
  layout,
  selectedCell,
  selectedWidget,
  badWidgets,
  dashboardId,
  pendingType,
  onChange,
  onSelectCell,
  onSelectWidget,
  onAdd,
}: {
  layout: DashboardLayout
  selectedCell: string
  selectedWidget: string
  badWidgets: Set<string>
  dashboardId: number
  pendingType: DashboardWidgetType | null
  onChange: (updater: (current: DashboardLayout) => DashboardLayout) => void
  onSelectCell: (id: string) => void
  onSelectWidget: (id: string) => void
  onAdd: (widget: DashboardWidget) => void
}) {
  const { t } = useTranslation()
  const data = useDashboardData(dashboardId, { refetchInterval: false })
  const gridRef = useRef<HTMLDivElement>(null)
  const start = useRef<{ row: number; col: number } | null>(null)
  const addedByPointer = useRef(false)
  const [end, setEnd] = useState<{ row: number; col: number } | null>(null)
  const nested = useMemo(() => nestedWidgetIds(layout), [layout])

  const point = (event: { clientX: number; clientY: number }) => {
    const rect = gridRef.current?.getBoundingClientRect()
    if (!rect) return null
    return {
      row: Math.max(1, Math.min(layout.rows, Math.floor(((event.clientY - rect.top) / Math.max(1, rect.height)) * layout.rows) + 1)),
      col: Math.max(1, Math.min(layout.cols, Math.floor(((event.clientX - rect.left) / Math.max(1, rect.width)) * layout.cols) + 1)),
    }
  }

  const drop = (event: DragEvent, cell: DashboardCell) => {
    event.preventDefault()
    event.stopPropagation()
    const type = event.dataTransfer.getData('application/x-dashboard-type') as DashboardWidgetType
    const widgetId = event.dataTransfer.getData('application/x-dashboard-widget')
    if (type) {
      onChange((current) => {
        const result = addWidget(current, cell.id, type)
        onAdd(result.widget)
        return result.layout
      })
    } else if (widgetId) {
      onChange((current) => moveWidget(current, widgetId, cell.id))
      onSelectWidget(widgetId)
    }
  }

  const finishPointer = (target: { row: number; col: number } | null) => {
    const origin = start.current
    start.current = null
    setEnd(null)
    if (!origin || !target) return
    if (origin.row === target.row && origin.col === target.col) {
      const cell = cellAt(layout, target.row, target.col)
      if (cell && pendingType) {
        addedByPointer.current = true
        onChange((current) => {
          const result = addWidget(current, cell.id, pendingType)
          onAdd(result.widget)
          return result.layout
        })
      } else if (cell) onSelectCell(cell.id)
      return
    }
    onChange((current) => mergeRect(current, origin, target))
  }

  const selection = start.current && end ? {
    row: Math.min(start.current.row, end.row),
    col: Math.min(start.current.col, end.col),
    rowSpan: Math.abs(start.current.row - end.row) + 1,
    colSpan: Math.abs(start.current.col - end.col) + 1,
  } : null

  return (
    <div className="h-[calc(100%-4.25rem)] min-h-0 overflow-auto bg-surface-muted/30 p-4">
      <div
        ref={gridRef}
        className="relative grid min-h-[620px] min-w-[820px] gap-2 rounded-md border border-line bg-[linear-gradient(to_right,var(--line)_1px,transparent_1px),linear-gradient(to_bottom,var(--line)_1px,transparent_1px)] bg-surface p-2"
        style={{ gridTemplateRows: `repeat(${layout.rows}, minmax(0, 1fr))`, gridTemplateColumns: `repeat(${layout.cols}, minmax(0, 1fr))` }}
        data-testid="dash-design-grid"
        onPointerDown={(event) => {
          if ((event.target as HTMLElement).closest('[data-widget-card]')) return
          const p = point(event)
          start.current = p
          setEnd(p)
        }}
        onPointerMove={(event) => { if (start.current) setEnd(point(event)) }}
        onPointerUp={(event) => finishPointer(point(event))}
      >
        {layout.cells.map((cell) => {
          const widgets = layout.widgets.filter((widget) => widget.cell === cell.id && !nested.has(widget.id))
          return (
            <section
              key={cell.id}
              className={`min-h-28 min-w-0 overflow-hidden rounded-md border p-2 ${selectedCell === cell.id ? 'border-brand ring-2 ring-brand/20' : 'border-line'} bg-surface/95`}
              style={{ gridRow: `${cell.row} / span ${cell.row_span}`, gridColumn: `${cell.col} / span ${cell.col_span}` }}
              data-testid={`dash-design-cell-${cell.id}`}
              onClick={() => {
                if (addedByPointer.current) {
                  addedByPointer.current = false
                  return
                }
                if (pendingType) {
                  onChange((current) => {
                    const result = addWidget(current, cell.id, pendingType)
                    onAdd(result.widget)
                    return result.layout
                  })
                } else onSelectCell(cell.id)
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => drop(event, cell)}
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="truncate font-mono text-[11px] text-muted">{cell.id}</span>
                <span className="tnum text-[11px] text-subtle">{cell.row},{cell.col} / {cell.row_span}x{cell.col_span}</span>
              </div>
              <div className="grid h-[calc(100%-1.5rem)] min-h-0 gap-2">
                {widgets.length ? widgets.map((widget) => (
                  <div key={widget.id} className={badWidgets.has(widget.id) ? 'rounded-md ring-2 ring-critical' : selectedWidget === widget.id ? 'rounded-md ring-2 ring-brand' : ''}>
                    <div data-widget-card>
                      <WidgetStackItem
                        widget={widget}
                        onSelect={() => onSelectWidget(widget.id)}
                        onRemove={() => onChange((current) => removeWidget(current, widget.id))}
                        onDuplicate={() => onChange((current) => duplicateWidget(current, widget.id))}
                        onMove={(delta) => onChange((current) => reorderWidget(current, widget.id, delta))}
                      />
                    </div>
                    <div className="h-32 min-h-0">
                      <WidgetRenderer widget={widget} layout={layout} data={data.data} live={{}} design />
                    </div>
                  </div>
                )) : <div className="flex h-full min-h-24 items-center justify-center rounded border border-dashed border-line text-sm text-muted">{t('dashboardDesign.dropHere')}</div>}
              </div>
            </section>
          )
        })}
        {selection ? <div className="pointer-events-none rounded-md border-2 border-brand/70 bg-brand-soft/20" style={{ gridRow: `${selection.row} / span ${selection.rowSpan}`, gridColumn: `${selection.col} / span ${selection.colSpan}` }} /> : null}
      </div>
    </div>
  )
}

function WidgetStackItem({ widget, onSelect, onRemove, onDuplicate, onMove }: { widget: DashboardWidget; onSelect: () => void; onRemove: () => void; onDuplicate: () => void; onMove: (delta: number) => void }) {
  const { t } = useTranslation()
  return (
    <div
      role="button"
      tabIndex={0}
      draggable
      data-testid={`dash-design-widget-${widget.type}`}
      onClick={(event) => { event.stopPropagation(); onSelect() }}
      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onSelect() }}
      onDragStart={(event) => event.dataTransfer.setData('application/x-dashboard-widget', widget.id)}
      className="mb-1 rounded-md border border-line bg-surface-muted px-2 py-1.5"
    >
      <div className="flex items-center gap-1.5">
        <span className="min-w-0 flex-1 truncate text-xs font-medium">{t(`dashboardRun.widgetTypes.${widget.type}`)} <span className="font-mono text-subtle">{widget.id}</span></span>
        <IconButton label={t('dashboardDesign.moveUp')} size="xs" onClick={(event) => { event.stopPropagation(); onMove(-1) }}><ChevronUp size={13} /></IconButton>
        <IconButton label={t('dashboardDesign.moveDown')} size="xs" onClick={(event) => { event.stopPropagation(); onMove(1) }}><ChevronDown size={13} /></IconButton>
        <IconButton label={t('dashboardRun.copy')} size="xs" onClick={(event) => { event.stopPropagation(); onDuplicate() }}><Copy size={13} /></IconButton>
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        <IconButton label={t('dashboardRun.remove')} size="xs" onClick={(event) => { event.stopPropagation(); onRemove() }} className="hover:!bg-critical-soft hover:!text-critical"><Trash2 size={13} /></IconButton>
      </div>
    </div>
  )
}

function PropertiesPanel({ layout, widget, onWidget, onLayout }: { layout: DashboardLayout; widget: DashboardWidget; onWidget: (widget: DashboardWidget) => void; onLayout: (patch: Partial<DashboardLayout>) => void }) {
  const { t } = useTranslation()
  const flows = useFlows()
  const effectiveFlowId = resolveFlow(widget, layout)
  const selectedFlow = useFlow(effectiveFlowId)
  const catalogue = useToolTypes()
  const flowVariables = useVariables(effectiveFlowId)
  const stationVariables = useStationVariables()
  const fixedImages = useFixedImages()
  const dashboards = useDashboards()
  const flowOptions = (flows.data?.items ?? []).map((flow) => ({ value: String(flow.id), label: flow.name }))
  const dashboardOptions = (dashboards.data?.items ?? []).map((item) => ({ value: String(item.id), label: item.name }))
  const allowedSources = WIDGET_SCHEMA[widget.type].sourceKinds
  const sourceKind = widget.source?.kind ?? allowedSources[0] ?? 'output'
  const sourceOptions = allowedSources.length ? allowedSources : DASHBOARD_SOURCE_KINDS
  const keyOptions = sourceKeyOptions(sourceKind, selectedFlow.data, catalogue.data, flowVariables.data, stationVariables.data, fixedImages.data)
  const otherWidgets = layout.widgets.filter((item) => item.id !== widget.id)

  const patchProps = (name: string, value: unknown) => onWidget({ ...widget, props: { ...(widget.props ?? {}), [name]: value } })
  const patchSource = (patch: Partial<DashboardWidgetSource>) => onWidget({ ...widget, source: cleanSource({ ...(widget.source ?? {}), ...patch }) })

  return (
    <div className="space-y-5" data-testid="dash-design-properties">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-heading">{t('dashboardDesign.layout')}</h2>
        <Select label={t('dashboardDesign.defaultFlow')} value={layout.default_flow_id ? String(layout.default_flow_id) : ''} placeholder={t('dashboardDesign.noDefaultFlow')} options={flowOptions} onChange={(event) => onLayout({ default_flow_id: event.target.value ? Number(event.target.value) : null })} />
        <div className="grid grid-cols-2 gap-2">
          <TextInput label={t('dashboard.design.background')} value={String(layout.theme?.background ?? '')} onChange={(event) => onLayout({ theme: { ...(layout.theme ?? {}), background: event.target.value } })} />
          <TextInput label={t('dashboard.design.accent')} value={String(layout.theme?.accent ?? '')} onChange={(event) => onLayout({ theme: { ...(layout.theme ?? {}), accent: event.target.value } })} />
        </div>
      </section>
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-heading">{t('dashboardDesign.widget')}</h2>
        <TextInput label={t('dashboardDesign.widgetId')} value={widget.id} readOnly />
        <TextInput label={t('dashboardDesign.cell')} value={widget.cell ?? ''} readOnly />
      </section>
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-heading">{t('dashboardDesign.source')}</h2>
        <Select label={t('dashboardDesign.sourceFlow')} value={widget.source?.flow_id ? String(widget.source.flow_id) : ''} placeholder={t('dashboardDesign.useDefaultFlow')} options={flowOptions} onChange={(event) => patchSource({ flow_id: event.target.value ? Number(event.target.value) : null })} />
        {sourceOptions.length ? (
          <Select label={t('dashboardDesign.sourceKind')} value={sourceKind} options={sourceOptions.map((kind) => ({ value: kind, label: t(`dashboardDesign.sourceKinds.${kind}`) }))} onChange={(event) => patchSource({ kind: event.target.value as DashboardSourceKind, key: '' })} data-testid="dash-design-widget-mode" />
        ) : null}
        {keyOptions.length ? <Select label={t('dashboardDesign.sourceKey')} value={widget.source?.key ?? ''} placeholder={t('dashboardDesign.freeInput')} options={keyOptions} onChange={(event) => patchSource({ key: event.target.value })} /> : <TextInput label={t('dashboardDesign.sourceKey')} value={widget.source?.key ?? ''} onChange={(event) => patchSource({ key: event.target.value })} />}
      </section>
      <section className="space-y-3" data-testid="dash-design-props">
        <h2 className="text-sm font-semibold text-heading">{t('dashboardDesign.props')}</h2>
        {Object.entries(WIDGET_SCHEMA[widget.type].props).length ? Object.entries(WIDGET_SCHEMA[widget.type].props).map(([name, spec]) => (
          <PropField key={name} name={name} spec={spec} value={widget.props?.[name]} flowOptions={flowOptions} dashboardOptions={dashboardOptions} otherWidgets={otherWidgets} onChange={(value) => patchProps(name, value)} />
        )) : <p className="text-sm text-muted">{t('dashboardDesign.noProps')}</p>}
      </section>
    </div>
  )
}

function PropField({ name, spec, value, flowOptions, dashboardOptions, otherWidgets, onChange }: { name: string; spec: DashboardPropSpec; value: unknown; flowOptions: { value: string; label: string }[]; dashboardOptions: { value: string; label: string }[]; otherWidgets: DashboardWidget[]; onChange: (value: unknown) => void }) {
  const { t } = useTranslation()
  const label = t(`dashboardDesign.propsLabels.${name}`, { defaultValue: name })
  if (spec.kind === 'bool') return <Field label={label}><Switch checked={value === undefined ? Boolean(spec.defaultValue) : value === true} label={label} onChange={onChange} /></Field>
  if (spec.kind === 'int' || spec.kind === 'number') return <TextInput label={label} type="number" min={spec.range?.[0]} max={spec.range?.[1]} value={value == null ? '' : String(value)} onChange={(event) => onChange(event.target.value === '' ? null : spec.kind === 'int' ? Math.trunc(Number(event.target.value)) : Number(event.target.value))} />
  if (spec.kind === 'choice') return <Select label={label} value={String(value ?? spec.defaultValue ?? '')} options={(spec.choices ?? []).map((choice) => ({ value: choice, label: choice }))} onChange={(event) => onChange(event.target.value)} />
  if (spec.kind === 'color') return <div className="grid grid-cols-[3rem_minmax(0,1fr)] items-end gap-2"><input type="color" value={typeof value === 'string' ? value : String(spec.defaultValue ?? '#22c55e')} onChange={(event) => onChange(event.target.value)} className="h-9 w-12 rounded border border-line bg-surface" aria-label={label} /><TextInput label={label} value={typeof value === 'string' ? value : String(spec.defaultValue ?? '')} onChange={(event) => onChange(event.target.value)} /></div>
  if (spec.kind === 'flow_id') return <Select label={label} value={value ? String(value) : ''} placeholder={t('dashboardDesign.useDefaultFlow')} options={flowOptions} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)} />
  if (spec.kind === 'dashboard_id') return <Select label={label} value={value ? String(value) : ''} placeholder={t('dashboardDesign.pickDashboard')} options={dashboardOptions} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)} />
  if (spec.kind === 'children') return <ChildrenEditor label={label} value={Array.isArray(value) ? value : []} widgets={otherWidgets} onChange={onChange} />
  if (spec.kind === 'columns') return <StringListEditor label={label} value={Array.isArray(value) ? value : []} onChange={onChange} />
  if (spec.kind === 'tabs') return <TabsEditor value={Array.isArray(value) ? value : []} widgets={otherWidgets} onChange={onChange} />
  if (spec.kind === 'rules') return <RulesEditor value={Array.isArray(value) ? value : []} onChange={onChange} />
  if (spec.kind === 'image_items') return <ImageItemsEditor value={Array.isArray(value) ? value : []} flowOptions={flowOptions} onChange={onChange} />
  if (spec.kind === 'any') return <TextInput label={label} value={value == null ? '' : typeof value === 'string' ? value : JSON.stringify(value)} onChange={(event) => onChange(parseLoose(event.target.value))} />
  return <TextInput label={label} value={value == null ? '' : String(value)} onChange={(event) => onChange(event.target.value)} />
}

function ChildrenEditor({ label, value, widgets, onChange }: { label: string; value: unknown[]; widgets: DashboardWidget[]; onChange: (value: string[]) => void }) {
  const selected = new Set(value.filter((item): item is string => typeof item === 'string'))
  return <Field label={label}><div className="space-y-1 rounded-md border border-line p-2">{widgets.map((widget) => <Checkbox key={widget.id} label={`${widget.id} (${widget.type})`} checked={selected.has(widget.id)} onChange={(checked) => { const next = new Set(selected); if (checked) next.add(widget.id); else next.delete(widget.id); onChange([...next]) }} />)}</div></Field>
}

function StringListEditor({ label, value, onChange }: { label: string; value: unknown[]; onChange: (value: string[]) => void }) {
  const { t } = useTranslation()
  const rows = value.map((item) => String(item ?? ''))
  return <Field label={label}><div className="space-y-2">{rows.map((item, index) => <div key={index} className="flex gap-2"><TextInput value={item} onChange={(event) => onChange(rows.map((row, i) => i === index ? event.target.value : row).filter(Boolean))} /><IconButton label={t('dashboardDesign.remove')} onClick={() => onChange(rows.filter((_, i) => i !== index))} className="hover:!bg-critical-soft hover:!text-critical"><Trash2 size={14} /></IconButton></div>)}<Button size="sm" icon={<Plus className="size-4" />} onClick={() => onChange([...rows, ''])}>{t('dashboardDesign.add')}</Button></div></Field>
}

function TabsEditor({ value, widgets, onChange }: { value: unknown[]; widgets: DashboardWidget[]; onChange: (value: unknown[]) => void }) {
  const { t } = useTranslation()
  const rows = value.map((item) => typeof item === 'object' && item !== null ? item as { title?: string; children?: string[] } : { title: '', children: [] })
  const patch = (index: number, row: { title?: string; children?: string[] }) => onChange(rows.map((item, i) => i === index ? row : item))
  return <Field label={t('dashboardDesign.tabs')}><div className="space-y-2">{rows.map((row, index) => { const selected = new Set(row.children ?? []); return <div key={index} className="space-y-2 rounded-md border border-line p-2"><TextInput label={t('dashboardDesign.propsLabels.title')} value={row.title ?? ''} onChange={(event) => patch(index, { ...row, title: event.target.value })} />{widgets.map((widget) => <Checkbox key={widget.id} label={`${widget.id} (${widget.type})`} checked={selected.has(widget.id)} onChange={(checked) => { const next = new Set(selected); if (checked) next.add(widget.id); else next.delete(widget.id); patch(index, { ...row, children: [...next] }) }} />)}<Button size="sm" variant="ghost" onClick={() => onChange(rows.filter((_, i) => i !== index))}>{t('dashboardDesign.remove')}</Button></div> })}<Button size="sm" icon={<Plus className="size-4" />} onClick={() => onChange([...rows, { title: `Tab ${rows.length + 1}`, children: [] }])}>{t('dashboardDesign.add')}</Button></div></Field>
}

function RulesEditor({ value, onChange }: { value: unknown[]; onChange: (value: unknown[]) => void }) {
  const { t } = useTranslation()
  const rows = value.map((item) => typeof item === 'object' && item !== null ? item as Record<string, unknown> : {})
  const patch = (index: number, patchRow: Record<string, unknown>) => onChange(rows.map((row, i) => i === index ? { ...row, ...patchRow } : row))
  return <Field label={t('dashboardDesign.rules')}><div className="space-y-2">{rows.map((row, index) => <div key={index} className="grid grid-cols-2 gap-2 rounded-md border border-line p-2"><TextInput label={t('dashboardDesign.propsLabels.key')} value={String(row.key ?? '')} onChange={(event) => patch(index, { key: event.target.value })} /><Select label={t('dashboardDesign.propsLabels.op')} value={String(row.op ?? 'eq')} options={['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'between'].map((op) => ({ value: op, label: op }))} onChange={(event) => patch(index, { op: event.target.value })} /><TextInput label={t('dashboardDesign.propsLabels.value')} value={row.value == null ? '' : String(row.value)} onChange={(event) => patch(index, { value: parseLoose(event.target.value) })} /><TextInput label={t('dashboardDesign.propsLabels.color')} value={String(row.color ?? '#ef4444')} onChange={(event) => patch(index, { color: event.target.value })} /><Button size="sm" variant="ghost" onClick={() => onChange(rows.filter((_, i) => i !== index))}>{t('dashboardDesign.remove')}</Button></div>)}<Button size="sm" icon={<Plus className="size-4" />} onClick={() => onChange([...rows, { key: 'verdict', op: 'eq', value: 'NG', color: '#ef4444' }])}>{t('dashboardDesign.add')}</Button></div></Field>
}

function ImageItemsEditor({ value, flowOptions, onChange }: { value: unknown[]; flowOptions: { value: string; label: string }[]; onChange: (value: unknown[]) => void }) {
  const { t } = useTranslation()
  const rows = value.map((item) => typeof item === 'object' && item !== null ? item as Record<string, unknown> : {})
  const patch = (index: number, patchRow: Record<string, unknown>) => onChange(rows.map((row, i) => i === index ? { ...row, ...patchRow } : row))
  return <Field label={t('dashboardDesign.imageItems')}><div className="space-y-2">{rows.map((row, index) => <div key={index} className="grid grid-cols-2 gap-2 rounded-md border border-line p-2"><Select label={t('dashboardDesign.sourceFlow')} value={row.flow_id ? String(row.flow_id) : ''} placeholder={t('dashboardDesign.useDefaultFlow')} options={flowOptions} onChange={(event) => patch(index, { flow_id: event.target.value ? Number(event.target.value) : null })} /><TextInput label={t('dashboardDesign.propsLabels.title')} value={String(row.title ?? '')} onChange={(event) => patch(index, { title: event.target.value })} /><TextInput label={t('dashboardDesign.propsLabels.node')} value={String(row.node ?? '')} onChange={(event) => patch(index, { node: event.target.value })} /><TextInput label={t('dashboardDesign.propsLabels.port')} value={String(row.port ?? '')} onChange={(event) => patch(index, { port: event.target.value })} /><Button size="sm" variant="ghost" onClick={() => onChange(rows.filter((_, i) => i !== index))}>{t('dashboardDesign.remove')}</Button></div>)}<Button size="sm" icon={<Plus className="size-4" />} onClick={() => onChange([...rows, { title: '', node: '', port: '' }])}>{t('dashboardDesign.add')}</Button></div></Field>
}

function PreviewPanel({ dashboardId, layout }: { dashboardId: number; layout: DashboardLayout }) {
  const data = useDashboardData(dashboardId, { refetchInterval: 15000 })
  const nested = useMemo(() => nestedWidgetIds(layout), [layout])
  const widgets = layout.widgets.filter((widget) => !nested.has(widget.id))
  return (
    <div className="h-[560px] overflow-auto rounded-md border border-line bg-app p-2" data-testid="dash-design-preview">
      <div className="grid h-[720px] w-[980px] origin-top-left scale-[0.36] gap-2" style={{ gridTemplateRows: `repeat(${layout.rows}, minmax(0, 1fr))`, gridTemplateColumns: `repeat(${layout.cols}, minmax(0, 1fr))` }}>
        {layout.cells.map((cell) => {
          const assigned = widgets.filter((widget) => widget.cell === cell.id)
          return (
            <section key={cell.id} className="min-h-32 min-w-0 overflow-hidden" style={{ gridRow: `${cell.row} / span ${cell.row_span}`, gridColumn: `${cell.col} / span ${cell.col_span}` }}>
              <div className="grid h-full min-h-0 gap-2">
                {assigned.map((widget) => <WidgetRenderer key={widget.id} widget={widget} layout={layout} data={data.data} live={{}} design />)}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}

function EmptyPanel({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-dashed border-line p-6 text-center text-sm text-muted">{children}</div>
}

function useVariables(flowId: number | null) {
  return useQuery({ queryKey: ['flow-variables', flowId], queryFn: () => api.get<VariablesPayload>(`/vision/flows/${flowId}/variables`), enabled: flowId !== null })
}

function useStationVariables() {
  return useQuery({ queryKey: ['station-variables'], queryFn: () => api.get<VariablesPayload>('/vision/variables') })
}

function useFixedImages() {
  return useQuery({ queryKey: ['fixed-images'], queryFn: () => api.get<FixedImagesPayload>('/vision/fixed-images') })
}

function sourceKeyOptions(kind: DashboardSourceKind, flow?: Flow, catalogue?: ToolCatalogue, flowVars?: VariablesPayload, stationVars?: VariablesPayload, fixedImages?: FixedImagesPayload) {
  if (kind === 'output' || kind === 'spc') return namedOutputKeys(flow, catalogue).map((key) => ({ value: key, label: key }))
  if (kind === 'variable') return [
    ...Object.keys(flowVars?.items ?? {}).map((key) => ({ value: key, label: key })),
    ...Object.keys(flowVars?.station ?? {}).map((key) => ({ value: `station.${key}`, label: `station.${key}` })),
    ...Object.keys(stationVars?.items ?? {}).map((key) => ({ value: `station.${key}`, label: `station.${key}` })),
  ]
  if (kind === 'image') {
    const imageNodes = imageOutputs(flow, catalogue).map((item) => ({ value: item.node, label: item.port ? `${item.node}:${item.port}` : item.node }))
    const fixed = (fixedImages?.items ?? []).map((item) => ({ value: item.id, label: item.name ? `${item.name} (${item.id})` : item.id }))
    return [...imageNodes, ...fixed]
  }
  if (kind === 'status') return ['status', 'verdict', 'run_id', 'duration_ms'].map((key) => ({ value: key, label: key }))
  if (kind === 'counts') return ['total', 'ok', 'ng', 'failed', 'yield'].map((key) => ({ value: key, label: key }))
  if (kind === 'device') return ['station', 'version', 'lock', 'capacity', 'running'].map((key) => ({ value: key, label: key }))
  return []
}

function namedOutputKeys(flow?: Flow, catalogue?: ToolCatalogue): string[] {
  // 步驟依埠順序發布的名稱（alias）排前面，再補 output 步驟與判定鍵
  const found = new Set<string>(graphOutputNames(flow?.graph?.nodes ?? [], new Map((catalogue?.items ?? []).map((item) => [item.key, item]))))
  for (const node of flow?.graph?.nodes ?? []) {
    const params = node.params ?? {}
    if (node.type === 'output') {
      const name = params.name
      found.add(typeof name === 'string' && name.trim() ? name.trim() : node.label || node.id)
    }
    for (const key of ['judge', 'output_key', 'key']) {
      const value = params[key]
      if (typeof value === 'string' && value.trim()) found.add(value.trim())
    }
  }
  return [...found]
}

function imageOutputs(flow?: Flow, catalogue?: ToolCatalogue): { node: string; port: string }[] {
  const byType = new Map((catalogue?.items ?? []).map((item) => [item.key, item]))
  const out: { node: string; port: string }[] = []
  for (const node of flow?.graph?.nodes ?? []) {
    const def = byType.get(node.type)
    for (const port of def?.outputs ?? []) if (port.type === 'image') out.push({ node: node.id, port: port.key })
    if (!def && node.type !== 'output') out.push({ node: node.id, port: '' })
  }
  return out
}

function addWidget(layout: DashboardLayout, cellId: string, type: DashboardWidgetType): { layout: DashboardLayout; widget: DashboardWidget } {
  const base = type.replace(/[^a-z0-9_]/g, '_')
  const used = new Set(layout.widgets.map((widget) => widget.id))
  let id = base
  let index = 2
  while (used.has(id)) {
    id = `${base}_${index}`
    index += 1
  }
  const sourceKind = WIDGET_SCHEMA[type].sourceKinds[0]
  const widget: DashboardWidget = { id, type, cell: cellId, props: requiredDefaults(type), ...(sourceKind ? { source: { kind: sourceKind } } : {}) }
  return { layout: { ...layout, widgets: [...layout.widgets, widget] }, widget }
}

function moveWidget(layout: DashboardLayout, widgetId: string, cellId: string): DashboardLayout {
  return { ...layout, widgets: layout.widgets.map((widget) => widget.id === widgetId ? { ...widget, cell: cellId } : widget) }
}

function duplicateWidget(layout: DashboardLayout, widgetId: string): DashboardLayout {
  const source = layout.widgets.find((widget) => widget.id === widgetId)
  if (!source) return layout
  const used = new Set(layout.widgets.map((widget) => widget.id))
  let id = `${source.id}_copy`
  let index = 2
  while (used.has(id)) {
    id = `${source.id}_copy_${index}`
    index += 1
  }
  return { ...layout, widgets: [...layout.widgets, { ...clone(source), id }] }
}

function removeWidget(layout: DashboardLayout, widgetId: string): DashboardLayout {
  return { ...layout, widgets: layout.widgets.filter((widget) => widget.id !== widgetId).map((widget) => ({ ...widget, props: removeChildRef(widget.props ?? {}, widgetId) })) }
}

function reorderWidget(layout: DashboardLayout, widgetId: string, delta: number): DashboardLayout {
  const index = layout.widgets.findIndex((widget) => widget.id === widgetId)
  const target = index + delta
  if (index < 0 || target < 0 || target >= layout.widgets.length || layout.widgets[index].cell !== layout.widgets[target].cell) return layout
  const next = [...layout.widgets]
  const [item] = next.splice(index, 1)
  next.splice(target, 0, item)
  return { ...layout, widgets: next }
}

function removeChildRef(props: Record<string, unknown>, widgetId: string): Record<string, unknown> {
  const next = { ...props }
  if (Array.isArray(next.children)) next.children = next.children.filter((id) => id !== widgetId)
  if (Array.isArray(next.tabs)) next.tabs = next.tabs.map((tab) => typeof tab === 'object' && tab !== null ? { ...tab, children: Array.isArray((tab as { children?: unknown }).children) ? (tab as { children: unknown[] }).children.filter((id) => id !== widgetId) : [] } : tab)
  return next
}

function splitCell(layout: DashboardLayout, cellId: string): DashboardLayout {
  const cell = cellById(layout, cellId)
  if (!cell) return layout
  const units: DashboardCell[] = []
  for (let row = cell.row; row < cell.row + cell.row_span; row += 1) for (let col = cell.col; col < cell.col + cell.col_span; col += 1) units.push({ id: uniqueCellId(layout, `c_${row}_${col}`), row, col, row_span: 1, col_span: 1 })
  const first = units[0]
  return { ...layout, cells: [...layout.cells.filter((item) => item.id !== cellId), ...units], widgets: layout.widgets.map((widget) => widget.cell === cellId ? { ...widget, cell: first.id } : widget) }
}

function mergeRect(layout: DashboardLayout, start: { row: number; col: number }, end: { row: number; col: number }): DashboardLayout {
  const row = Math.min(start.row, end.row)
  const col = Math.min(start.col, end.col)
  const rowSpan = Math.abs(start.row - end.row) + 1
  const colSpan = Math.abs(start.col - end.col) + 1
  const cells = layout.cells.filter((cell) => cell.row < row || cell.row >= row + rowSpan || cell.col < col || cell.col >= col + colSpan)
  const covered = layout.cells.filter((cell) => !(cell.row < row || cell.row >= row + rowSpan || cell.col < col || cell.col >= col + colSpan))
  const id = covered[0]?.id ?? uniqueCellId(layout, `c_${row}_${col}`)
  const merged = { id, row, col, row_span: rowSpan, col_span: colSpan }
  const movedIds = new Set(covered.map((cell) => cell.id))
  return normalizeLayout({ ...layout, cells: [...cells, merged], widgets: layout.widgets.map((widget) => widget.cell && movedIds.has(widget.cell) ? { ...widget, cell: id } : widget) })
}

function cellAt(layout: DashboardLayout, row: number, col: number): DashboardCell | null {
  return layout.cells.find((cell) => row >= cell.row && row < cell.row + cell.row_span && col >= cell.col && col < cell.col + cell.col_span) ?? null
}

function normalizeLayout(layout: DashboardLayout): DashboardLayout {
  const rows = clampInt(layout.rows, 1, 10)
  const cols = clampInt(layout.cols, 1, 10)
  const cells = (Array.isArray(layout.cells) ? layout.cells : []).map((cell) => ({
    id: typeof cell.id === 'string' && cell.id ? cell.id : `c_${cell.row}_${cell.col}`,
    row: clampInt(cell.row, 1, rows),
    col: clampInt(cell.col, 1, cols),
    row_span: clampInt(cell.row_span, 1, rows),
    col_span: clampInt(cell.col_span, 1, cols),
  })).map((cell) => ({ ...cell, row_span: Math.min(cell.row_span, rows - cell.row + 1), col_span: Math.min(cell.col_span, cols - cell.col + 1) }))
  const out: DashboardCell[] = []
  const occupied = new Set<string>()
  for (const cell of cells) {
    let overlaps = false
    for (let r = cell.row; r < cell.row + cell.row_span; r += 1) for (let c = cell.col; c < cell.col + cell.col_span; c += 1) if (occupied.has(`${r}:${c}`)) overlaps = true
    if (overlaps) continue
    out.push(cell)
    for (let r = cell.row; r < cell.row + cell.row_span; r += 1) for (let c = cell.col; c < cell.col + cell.col_span; c += 1) occupied.add(`${r}:${c}`)
  }
  for (let r = 1; r <= rows; r += 1) for (let c = 1; c <= cols; c += 1) if (!occupied.has(`${r}:${c}`)) out.push({ id: uniqueCellId({ ...layout, cells: out }, `c_${r}_${c}`), row: r, col: c, row_span: 1, col_span: 1 })
  const cellIds = new Set(out.map((cell) => cell.id))
  return {
    rows,
    cols,
    cells: out.sort((a, b) => a.row - b.row || a.col - b.col),
    bars: { top: layout.bars?.top === true, bottom: layout.bars?.bottom === true, left: layout.bars?.left === true, right: layout.bars?.right === true },
    default_flow_id: typeof layout.default_flow_id === 'number' ? layout.default_flow_id : null,
    widgets: (Array.isArray(layout.widgets) ? layout.widgets : []).filter((widget) => widget.type in WIDGET_SCHEMA && widget.cell && cellIds.has(widget.cell)).map((widget) => ({ ...widget, props: { ...defaultProps(widget.type), ...(widget.props ?? {}) } })),
    theme: layout.theme && typeof layout.theme === 'object' && !Array.isArray(layout.theme) ? layout.theme : {},
  }
}

function uniqueCellId(layout: DashboardLayout, base: string): string {
  const used = new Set(layout.cells.map((cell) => cell.id))
  let id = base
  let index = 2
  while (used.has(id)) {
    id = `${base}_${index}`
    index += 1
  }
  return id
}

function cleanSource(source: DashboardWidgetSource): DashboardWidgetSource {
  const out: DashboardWidgetSource = {}
  if (source.flow_id) out.flow_id = source.flow_id
  if (source.kind) out.kind = source.kind
  if (source.key) out.key = source.key
  return out
}

function parseLoose(value: string): unknown {
  const text = value.trim()
  if (text === '') return ''
  if (text === 'true') return true
  if (text === 'false') return false
  if (Number.isFinite(Number(text))) return Number(text)
  try {
    return JSON.parse(text) as unknown
  } catch {
    return value
  }
}

function clampInt(value: unknown, min: number, max: number): number {
  const number = typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : min
  return Math.max(min, Math.min(max, number))
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}
