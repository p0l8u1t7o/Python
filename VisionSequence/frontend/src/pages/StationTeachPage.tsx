import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowDown, ArrowUp, FolderPlus, ListFilter, Save, Star, Trash2, X } from 'lucide-react'

import type { InspectorActions } from '@/components/editor/ParamField'
import { ParamField } from '@/components/editor/ParamField'
import { formatValue } from '@/components/editor/ResultsPanel'
import { Badge, Button, EmptyState, ErrorState, IconButton, LoadingState, PageHeader, TextInput } from '@/components/ui'
import { Page } from '@/components/layout/AppShell'
import { errorMessage } from '@/lib/errors'
import {
  buildStationTeachPatches,
  filterStationTeachItems,
  invalidGroupItems,
  saveStationTeachPatches,
  sameStationTeachValue,
  stationTeachKey,
  stationTeachRef,
} from '@/lib/stationTeach'
import { useFlowMutations, useFlows, useStationTeachGroupMutations, useStationTeachGroups, useStationTeachParams } from '@/lib/queries'
import type { StationTeachGroup, StationTeachParamItem, StationTeachRef } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const NO_ACTIONS: InspectorActions = { roiEditingKey: null, setRoiEditing: () => undefined, templateFromImage: () => undefined, templateKey: null, hasImage: false }

function refEquals(a: StationTeachRef, b: StationTeachRef): boolean {
  return a.flow_id === b.flow_id && a.node_id === b.node_id && a.param === b.param
}

function groupRefs(group: StationTeachGroup): StationTeachRef[] {
  return group.items.map((item) => ({ flow_id: item.flow_id, node_id: item.node_id, param: item.param }))
}

function rowsByFlow(rows: StationTeachParamItem[]): { flowId: number; flowName: string; rows: StationTeachParamItem[] }[] {
  const groups = new Map<number, { flowId: number; flowName: string; rows: StationTeachParamItem[] }>()
  for (const row of rows) {
    const bucket = groups.get(row.flow_id) ?? { flowId: row.flow_id, flowName: row.flow_name, rows: [] }
    bucket.rows.push(row)
    groups.set(row.flow_id, bucket)
  }
  return [...groups.values()]
}

export function StationTeachPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const params = useStationTeachParams()
  const groups = useStationTeachGroups()
  const flows = useFlows()
  const flowMut = useFlowMutations()
  const groupMut = useStationTeachGroupMutations()
  const [flowId, setFlowId] = useState<number | ''>('')
  const [toolType, setToolType] = useState('')
  const [q, setQ] = useState('')
  const [activeGroupId, setActiveGroupId] = useState<string>('')
  const [newGroupName, setNewGroupName] = useState('')
  const [rename, setRename] = useState('')
  const [changes, setChanges] = useState<Record<string, unknown>>({})
  const [saving, setSaving] = useState(false)
  const [saveResults, setSaveResults] = useState<Awaited<ReturnType<typeof saveStationTeachPatches>>>([])

  const rows = params.data?.items ?? []
  const groupList = groups.data?.items ?? []
  const activeGroup = groupList.find((group) => group.id === activeGroupId) ?? groupList[0] ?? null
  const shownRows = useMemo(() => {
    const base = activeGroup
      ? activeGroup.items.map((item) => item.resolved).filter((item): item is StationTeachParamItem => Boolean(item))
      : rows
    return filterStationTeachItems(base, { flowId, toolType, q })
  }, [activeGroup, flowId, q, rows, toolType])
  const flowOptions = useMemo(() => [...new Map(rows.map((row) => [row.flow_id, row.flow_name])).entries()], [rows])
  const toolOptions = useMemo(() => [...new Map(rows.map((row) => [row.tool_type, row.tool_label])).entries()], [rows])
  const dirtyCount = Object.entries(changes).filter(([key, value]) => {
    const row = rows.find((item) => stationTeachKey(stationTeachRef(item)) === key)
    return row && !sameStationTeachValue(row.value, value)
  }).length
  const readOnly = !auth.can('flows.teach')
  const busy = params.isPending || groups.isPending || flows.isPending
  const error = params.error ?? groups.error ?? flows.error

  async function createGroup() {
    const name = newGroupName.trim()
    if (!name) return toast.error(t('stationTeach.groupNameRequired'))
    try {
      const group = await groupMut.create.mutateAsync({ name })
      setActiveGroupId(group.id)
      setNewGroupName('')
      toast.success(t('stationTeach.groupCreated', { name }))
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  async function renameGroup() {
    if (!activeGroup) return
    const name = rename.trim() || activeGroup.name
    try {
      await groupMut.patch.mutateAsync({ id: activeGroup.id, name })
      setRename('')
      toast.success(t('stationTeach.groupRenamed', { name }))
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  async function removeGroup(group: StationTeachGroup) {
    try {
      await groupMut.remove.mutateAsync(group.id)
      if (activeGroupId === group.id) setActiveGroupId('')
      toast.success(t('stationTeach.groupDeleted'))
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  async function moveGroup(group: StationTeachGroup, direction: -1 | 1) {
    const index = groupList.findIndex((item) => item.id === group.id)
    const nextIndex = index + direction
    if (index < 0 || nextIndex < 0 || nextIndex >= groupList.length) return
    const ids = groupList.map((item) => item.id)
    ;[ids[index], ids[nextIndex]] = [ids[nextIndex], ids[index]]
    try {
      await groupMut.reorder.mutateAsync(ids)
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  async function addToGroup(row: StationTeachParamItem) {
    if (!activeGroup) return toast.warning(t('stationTeach.pickGroupFirst'))
    const ref = stationTeachRef(row)
    const items = groupRefs(activeGroup)
    if (items.some((item) => refEquals(item, ref))) return
    try {
      await groupMut.patch.mutateAsync({ id: activeGroup.id, items: [...items, ref] })
      toast.success(t('stationTeach.groupItemAdded'))
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  async function removeFromGroup(ref: StationTeachRef) {
    if (!activeGroup) return
    try {
      await groupMut.patch.mutateAsync({ id: activeGroup.id, items: groupRefs(activeGroup).filter((item) => !refEquals(item, ref)) })
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  async function save() {
    const patches = buildStationTeachPatches(flows.data?.items ?? [], rows, changes)
    if (!patches.length) return
    setSaving(true)
    const results = await saveStationTeachPatches(patches, (patch) => flowMut.patch.mutateAsync({ id: patch.flow.id, graph: patch.graph }))
    setSaveResults(results)
    setSaving(false)
    const okFlowIds = new Set(results.filter((result) => result.ok).map((result) => result.flow_id))
    setChanges((old) => Object.fromEntries(Object.entries(old).filter(([key]) => {
      const row = rows.find((item) => stationTeachKey(stationTeachRef(item)) === key)
      return row && !okFlowIds.has(row.flow_id)
    })))
    const ok = results.filter((result) => result.ok).length
    const failed = results.length - ok
    if (failed) toast.error(t('stationTeach.savedPartial', { ok, failed }))
    else toast.success(t('stationTeach.savedAll', { count: ok }))
    void params.refetch()
    void flows.refetch()
  }

  if (busy) return <LoadingState />
  if (error) return <ErrorState error={error} onRetry={() => { void params.refetch(); void groups.refetch(); void flows.refetch() }} />

  return (
    <Page wide>
      <div data-testid="station-teach-page">
        <PageHeader
          title={t('stationTeach.title')}
          description={t('stationTeach.subtitle')}
          actions={<Button variant={dirtyCount ? 'primary' : 'secondary'} icon={<Save size={15} />} loading={saving} disabled={readOnly || dirtyCount === 0} onClick={() => void save()} data-testid="station-teach-save">{t('stationTeach.saveAll', { count: dirtyCount })}</Button>}
        />

        {readOnly ? <div className="mb-3 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning">{t('teach.readOnlyHint')}</div> : null}

        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <aside className="space-y-4">
            <section className="rounded-md border border-line bg-surface p-3">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-heading"><ListFilter size={15} /> {t('stationTeach.filters')}</div>
              <label className="label" htmlFor="station-teach-flow">{t('stationTeach.flow')}</label>
              <select id="station-teach-flow" className="input mb-2 h-8 py-0 text-sm" value={flowId} onChange={(event) => setFlowId(event.target.value ? Number(event.target.value) : '')} data-testid="station-teach-flow">
                <option value="">{t('stationTeach.allFlows')}</option>
                {flowOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
              </select>
              <label className="label" htmlFor="station-teach-tool">{t('stationTeach.tool')}</label>
              <select id="station-teach-tool" className="input mb-2 h-8 py-0 text-sm" value={toolType} onChange={(event) => setToolType(event.target.value)} data-testid="station-teach-tool">
                <option value="">{t('stationTeach.allTools')}</option>
                {toolOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
              <TextInput label={t('common.search')} value={q} onChange={(event) => setQ(event.target.value)} placeholder={t('stationTeach.searchPlaceholder')} data-testid="station-teach-search" />
            </section>

            <section className="rounded-md border border-line bg-surface p-3" data-testid="station-teach-groups">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-heading">{t('stationTeach.groups')}</p>
                <Badge>{`${groupList.length}/${groups.data?.limit ?? 32}`}</Badge>
              </div>
              <div className="mb-2 flex gap-1.5">
                <TextInput value={newGroupName} onChange={(event) => setNewGroupName(event.target.value)} placeholder={t('stationTeach.newGroup')} onKeyDown={(event) => event.key === 'Enter' && void createGroup()} data-testid="station-teach-new-group" />
                <IconButton label={t('common.create')} disabled={readOnly} onClick={() => void createGroup()}><FolderPlus size={15} /></IconButton>
              </div>
              <div className="space-y-1">
                <button type="button" className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm ${!activeGroup ? 'bg-brand-soft text-brand' : 'hover:bg-surface-muted'}`} onClick={() => setActiveGroupId('')}>
                  <span>{t('stationTeach.allParams')}</span>
                  <span className="tnum text-xs text-muted">{rows.length}</span>
                </button>
                {groupList.map((group) => (
                  <button key={group.id} type="button" className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm ${activeGroup?.id === group.id ? 'bg-brand-soft text-brand' : 'hover:bg-surface-muted'}`} onClick={() => { setActiveGroupId(group.id); setRename(group.name) }} data-testid="station-teach-group">
                    <span className="truncate">{group.name}</span>
                    <span className="tnum text-xs text-muted">{group.count}</span>
                  </button>
                ))}
              </div>
              {activeGroup ? (
                <div className="mt-3 border-t border-line pt-3">
                  <TextInput label={t('stationTeach.renameGroup')} value={rename || activeGroup.name} onChange={(event) => setRename(event.target.value)} data-testid="station-teach-rename" />
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <Button size="xs" disabled={readOnly} onClick={() => void renameGroup()}>{t('common.save')}</Button>
                    <IconButton size="xs" label={t('stationTeach.moveUp')} disabled={readOnly} onClick={() => void moveGroup(activeGroup, -1)}><ArrowUp size={13} /></IconButton>
                    <IconButton size="xs" label={t('stationTeach.moveDown')} disabled={readOnly} onClick={() => void moveGroup(activeGroup, 1)}><ArrowDown size={13} /></IconButton>
                    <IconButton size="xs" label={t('common.delete')} variant="danger" disabled={readOnly} onClick={() => void removeGroup(activeGroup)}><Trash2 size={13} /></IconButton>
                  </div>
                  {invalidGroupItems(activeGroup).length ? <p className="mt-2 text-xs text-warning">{t('stationTeach.invalidCount', { count: invalidGroupItems(activeGroup).length })}</p> : null}
                </div>
              ) : null}
            </section>
          </aside>

          <main className="space-y-4">
            {saveResults.length ? (
              <section className="rounded-md border border-line bg-surface p-3" data-testid="station-teach-save-results">
                <p className="mb-2 text-sm font-semibold text-heading">{t('stationTeach.saveResults')}</p>
                <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                  {saveResults.map((result) => (
                    <div key={result.flow_id} className={`rounded-md border px-2.5 py-2 text-sm ${result.ok ? 'border-ok/30 bg-ok-soft text-ok' : 'border-critical/30 bg-critical-soft text-critical'}`}>
                      <p className="font-medium">{result.flow_name}</p>
                      <p className="text-xs">{result.ok ? t('stationTeach.saveOk', { count: result.count }) : t('stationTeach.saveFailed', { message: errorMessage(result.error) })}</p>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {activeGroup?.items.filter((item) => !item.valid).map((item) => (
              <div key={`${item.flow_id}:${item.node_id}:${item.param}`} className="flex items-center gap-2 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning" data-testid="station-teach-invalid">
                <span className="min-w-0 flex-1 truncate">{t('stationTeach.invalidItem', { flow: item.flow_id, node: item.node_id, param: item.param })}</span>
                <IconButton label={t('stationTeach.removeInvalid')} disabled={readOnly} onClick={() => void removeFromGroup(item)}><X size={14} /></IconButton>
              </div>
            ))}

            {shownRows.length === 0 ? (
              <EmptyState title={t('stationTeach.empty')} description={t('stationTeach.emptyHint')} />
            ) : rowsByFlow(shownRows).map((bucket) => (
              <section key={bucket.flowId} className="rounded-md border border-line bg-surface" data-testid="station-teach-flow-group">
                <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
                  <div className="min-w-0">
                    <h2 className="truncate text-sm font-semibold text-heading">{bucket.flowName}</h2>
                    <p className="text-xs text-muted">{t('stationTeach.paramRows', { count: bucket.rows.length })}</p>
                  </div>
                </header>
                <div className="divide-y divide-line">
                  {bucket.rows.map((row) => {
                    const key = stationTeachKey(stationTeachRef(row))
                    const value = Object.prototype.hasOwnProperty.call(changes, key) ? changes[key] : row.value
                    const dirty = !sameStationTeachValue(row.value, value)
                    return (
                      <div key={key} className="grid gap-3 px-4 py-3 xl:grid-cols-[260px_1fr_44px]" data-testid="station-teach-row">
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <Badge tone={dirty ? 'warning' : 'neutral'}>{dirty ? t('stationTeach.changed') : t('stationTeach.current')}</Badge>
                            <span className="truncate text-sm font-medium text-heading">{row.node_label}</span>
                          </div>
                          <p className="mt-1 truncate font-mono text-[11px] text-muted">{row.node_id} / {row.tool_label} / {row.param.key}</p>
                          <p className="mt-1 truncate text-xs text-muted">{t('stationTeach.savedValue', { value: formatValue(row.value) })}</p>
                        </div>
                        <ParamField param={row.param} value={value} actions={NO_ACTIONS} onChange={(next) => setChanges((old) => ({ ...old, [key]: next }))} />
                        <div className="flex items-start justify-end">
                          <IconButton label={t('stationTeach.addToGroup')} disabled={readOnly || !activeGroup} onClick={() => void addToGroup(row)}><Star size={15} /></IconButton>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>
            ))}
          </main>
        </div>
      </div>
    </Page>
  )
}
