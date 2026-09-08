import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Copy, Download, Edit3, ExternalLink, FileInput, Plus, Star, Trash2 } from 'lucide-react'

import { CodeField } from '@/components/editor/CodeField'
import { Page } from '@/components/layout/AppShell'
import { IconButton, Badge, Button, Card, CardBody, CardHeader, Checkbox, EmptyRow, ErrorState, LoadingState, Modal, PageHeader, TBody, THead, Table, Td, TextInput, Th, Tr } from '@/components/ui'
import { api } from '@/lib/api'
import { DEFAULT_DASHBOARD_LAYOUT } from '@/lib/dashboard'
import { errorMessage } from '@/lib/errors'
import { useConfirm } from '@/lib/useConfirm'
import { useDashboard, useDashboardMutations, useDashboards } from '@/lib/queries'
import type { Dashboard, DashboardLayout } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

function pretty(layout: DashboardLayout): string {
  return JSON.stringify(layout, null, 2)
}

function cloneDefault(): DashboardLayout {
  return JSON.parse(JSON.stringify(DEFAULT_DASHBOARD_LAYOUT)) as DashboardLayout
}

function downloadJson(name: string, layout: DashboardLayout) {
  const blob = new Blob([pretty(layout)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name || 'dashboard'}.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function DashboardEditor({ id, open, onClose }: { id: number | null; open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const q = useDashboard(open ? id : null)
  const mutations = useDashboardMutations()
  const inputRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [layoutText, setLayoutText] = useState('')
  const [layoutError, setLayoutError] = useState('')

  useEffect(() => {
    if (!q.data) return
    setName(q.data.name)
    setIsDefault(q.data.is_default)
    setLayoutText(pretty(q.data.layout))
    setLayoutError('')
  }, [q.data])

  const initial = q.data ? `${q.data.name}\n${q.data.is_default}\n${pretty(q.data.layout)}` : ''
  const current = `${name}\n${isDefault}\n${layoutText}`
  const dirty = Boolean(q.data && initial !== current)

  const save = async () => {
    if (!q.data) return
    let layout: DashboardLayout
    try {
      layout = JSON.parse(layoutText) as DashboardLayout
    } catch {
      setLayoutError(t('dashboardRun.invalidJson'))
      return
    }
    setLayoutError('')
    try {
      const saved = await mutations.update.mutateAsync({ id: q.data.id, name, is_default: isDefault, layout })
      toast.success(t('dashboardRun.saved'))
      setLayoutText(pretty(saved.layout))
      onClose()
    } catch (error) {
      setLayoutError(errorMessage(error))
    }
  }

  const importFile = async (file: File | undefined) => {
    if (!file) return
    setLayoutText(await file.text())
    setLayoutError('')
  }

  const exportCurrent = () => {
    if (!q.data) return
    try {
      downloadJson(q.data.name, JSON.parse(layoutText) as DashboardLayout)
      setLayoutError('')
    } catch {
      setLayoutError(t('dashboardRun.invalidJson'))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      dirty={dirty}
      size="xl"
      title={t('dashboardRun.editorTitle')}
      description={t('dashboardRun.layoutHint')}
      footer={
        <>
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={mutations.update.isPending} onClick={() => void save()}>{t('dashboardRun.save')}</Button>
        </>
      }
    >
      {q.isPending ? <LoadingState /> : q.isError ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
            <TextInput label={t('dashboardRun.name')} value={name} onChange={(e) => setName(e.target.value)} />
            <div className="flex items-end pb-2">
              <Checkbox label={t('dashboardRun.isDefault')} checked={isDefault} onChange={setIsDefault} />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setLayoutText(pretty(cloneDefault()))}>{t('dashboardRun.loadDefault')}</Button>
            <Button size="sm" icon={<Download className="size-4" />} onClick={exportCurrent}>{t('dashboardRun.exportJson')}</Button>
            <Button size="sm" icon={<FileInput className="size-4" />} onClick={() => inputRef.current?.click()}>{t('dashboardRun.importJson')}</Button>
            <input ref={inputRef} type="file" accept="application/json,.json" hidden onChange={(e) => void importFile(e.currentTarget.files?.[0])} />
          </div>
          <CodeField label={t('dashboardRun.layoutJson')} hint={t('dashboardRun.layoutHint')} value={layoutText} onChange={setLayoutText} language="json" />
          {layoutError ? <p className="text-xs text-critical">{layoutError}</p> : null}
        </div>
      )}
    </Modal>
  )
}

export function DashboardsPage() {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const { confirm, dialog } = useConfirm()
  const [params, setParams] = useSearchParams()
  const dashboards = useDashboards()
  const mutations = useDashboardMutations()
  const [newName, setNewName] = useState('')
  const editId = params.get('edit') ? Number(params.get('edit')) : null
  const canEdit = auth.can('flows.edit')

  const items = dashboards.data?.items ?? []
  const ordered = useMemo(() => [...items].sort((a, b) => Number(b.is_default) - Number(a.is_default) || a.name.localeCompare(b.name)), [items])

  const create = async () => {
    const name = newName.trim()
    if (!name) return
    const created = await mutations.create.mutateAsync({ name, layout: cloneDefault(), is_default: items.length === 0 })
    setNewName('')
    toast.success(t('dashboardRun.saved'))
    setParams({ edit: String(created.id) })
  }

  const duplicate = async (summary: { id: number; name: string }) => {
    const source = await api.get<Dashboard>(`/vision/dashboards/${summary.id}`)
    await mutations.create.mutateAsync({ name: `${summary.name} copy`, layout: source.layout, is_default: false })
    toast.success(t('dashboardRun.copied'))
  }

  const remove = async (summary: { id: number; name: string }) => {
    const ok = await confirm(t('dashboardRun.removeMessage', { name: summary.name }), { title: t('dashboardRun.removeTitle'), confirmLabel: t('dashboardRun.remove'), danger: true })
    if (!ok) return
    await mutations.remove.mutateAsync(summary.id)
    toast.success(t('dashboardRun.removed'))
  }

  return (
    <Page>
      <PageHeader
        title={t('dashboardRun.titleList')}
        description={t('dashboardRun.subtitle')}
        actions={canEdit ? (
          <div className="flex flex-wrap items-center gap-2">
            <TextInput value={newName} placeholder={t('dashboardRun.createName')} onChange={(e) => setNewName(e.target.value)} />
            <Button variant="primary" icon={<Plus className="size-4" />} loading={mutations.create.isPending} disabled={!newName.trim()} onClick={() => void create()}>{t('dashboardRun.create')}</Button>
          </div>
        ) : null}
      />
      <Card>
        <CardHeader title={t('dashboardRun.list')} />
        <CardBody className="p-0">
          {dashboards.isPending ? <LoadingState /> : dashboards.isError ? <ErrorState error={dashboards.error} onRetry={() => void dashboards.refetch()} /> : (
            <Table>
              <THead>
                <Th>{t('dashboardRun.name')}</Th>
                <Th>{t('dashboardRun.isDefault')}</Th>
                <Th align="right">{t('dashboardRun.widgets')}</Th>
                <Th>{t('dashboardRun.updated')}</Th>
                <Th align="right">{t('common.actions')}</Th>
              </THead>
              <TBody>
                {ordered.length ? ordered.map((item) => (
                  <Tr key={item.id}>
                    <Td>
                      <div className="font-medium text-content">{item.name}</div>
                      {item.owner_name ? <div className="text-xs text-muted">{item.owner_name}</div> : null}
                    </Td>
                    <Td>{item.is_default ? <Badge tone="ok">{t('dashboardRun.isDefault')}</Badge> : <span className="text-muted">-</span>}</Td>
                    <Td align="right">{item.widget_count}</Td>
                    <Td>{item.updated_at ? new Date(item.updated_at).toLocaleString() : '-'}</Td>
                    <Td align="right">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        <Link to={`/dashboard/${item.id}`} className="btn h-8 px-2.5 text-xs"><ExternalLink className="size-4" />{t('dashboardRun.open')}</Link>
                        {canEdit ? (
                          <>
                            <Button size="sm" variant="ghost" icon={<Edit3 className="size-4" />} onClick={() => setParams({ edit: String(item.id) })}>{t('dashboardRun.editLayout')}</Button>
                            <Button size="sm" variant="ghost" icon={<Star className="size-4" />} disabled={item.is_default} onClick={() => mutations.update.mutate({ id: item.id, is_default: true })}>{t('dashboardRun.setDefault')}</Button>
                            <Button size="sm" variant="ghost" icon={<Copy className="size-4" />} onClick={() => void duplicate(item)}>{t('dashboardRun.copy')}</Button>
                            <span className="mx-1 h-6 w-px self-center bg-line" aria-hidden />
                            <IconButton label={t('dashboardRun.remove')} disabled={ordered.length <= 1} onClick={() => void remove(item)} className="hover:!bg-critical-soft hover:!text-critical"><Trash2 size={15} /></IconButton>
                          </>
                        ) : null}
                      </div>
                    </Td>
                  </Tr>
                )) : <EmptyRow colSpan={5} message={t('dashboardRun.noDashboards')} />}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
      <DashboardEditor id={editId} open={canEdit && editId !== null} onClose={() => setParams({})} />
      {dialog}
    </Page>
  )
}
