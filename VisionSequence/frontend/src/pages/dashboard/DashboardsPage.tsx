import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Copy, Edit3, ExternalLink, Plus, Star, Trash2 } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { IconButton, Badge, Button, Card, CardBody, CardHeader, EmptyRow, ErrorState, LoadingState, PageHeader, Select, TBody, THead, Table, Td, TextInput, Th, Tr } from '@/components/ui'
import { api } from '@/lib/api'
import { cloneDashboardTemplate, DASHBOARD_CREATE_TEMPLATES } from '@/lib/dashboardTemplates'
import { useConfirm } from '@/lib/useConfirm'
import { useDashboardMutations, useDashboards } from '@/lib/queries'
import type { Dashboard } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

export function DashboardsPage() {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const { confirm, dialog } = useConfirm()
  const navigate = useNavigate()
  const dashboards = useDashboards()
  const mutations = useDashboardMutations()
  const [newName, setNewName] = useState('')
  const [templateKey, setTemplateKey] = useState('default')
  const canEdit = auth.can('flows.edit')

  const items = dashboards.data?.items ?? []
  const ordered = useMemo(() => [...items].sort((a, b) => Number(b.is_default) - Number(a.is_default) || a.name.localeCompare(b.name)), [items])

  const create = async () => {
    const name = newName.trim()
    if (!name) return
    const created = await mutations.create.mutateAsync({ name, layout: cloneDashboardTemplate(templateKey), is_default: items.length === 0 })
    setNewName('')
    toast.success(t('dashboardRun.saved'))
    navigate(`/dashboards/${created.id}/design`)
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
            <Select value={templateKey} options={DASHBOARD_CREATE_TEMPLATES.map((item) => ({ value: item.key, label: t(item.titleKey) }))} onChange={(e) => setTemplateKey(e.target.value)} aria-label={t('dashboardDesign.templateMenu')} />
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
                            <Link to={`/dashboards/${item.id}/design`} className="btn h-8 px-2.5 text-xs"><Edit3 className="size-4" />{t('dashboardRun.editLayout')}</Link>
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
      {dialog}
    </Page>
  )
}
