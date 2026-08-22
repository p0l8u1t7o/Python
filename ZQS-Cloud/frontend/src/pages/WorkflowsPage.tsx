import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'

import {
  useSites,
  useWorkflowCapacity,
  useWorkflowList,
  useWorkflowMutations,
} from '@/lib/queries'
import { errorMessage, fieldErrors } from '@/lib/errors'
import { formatDateTime } from '@/lib/format'
import { useToast } from '@/providers/ToastProvider'
import { useAuth } from '@/providers/AuthProvider'
import type { Workflow } from '@/lib/workflowTypes'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyRow,
  IconButton,
  ErrorState,
  Modal,
  PageHeader,
  SiteTreeSelect,
  TBody,
  THead,
  Table,
  Td,
  Th,
  TextArea,
  TextInput,
  Tr,
} from '@/components/ui'

/**
 * Every control flow in this organisation.
 *
 * The concurrency figure is on this page rather than only in the editor,
 * because the limit is per organisation: the reason a run was refused may be a
 * workflow the operator is not looking at.
 */
export function WorkflowsPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()

  const workflows = useWorkflowList()
  const capacity = useWorkflowCapacity()
  const sites = useSites()
  const { create, remove } = useWorkflowMutations()
  const { can } = useAuth()

  const [open, setOpen] = useState(false)
  const [deleting, setDeleting] = useState<Workflow | null>(null)
  const [form, setForm] = useState({ name: '', description: '', site_id: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})

  async function submit() {
    setErrors({})
    try {
      const created = await create.mutateAsync({
        name: form.name.trim(),
        description: form.description,
        site_id: form.site_id || null,
        // A new workflow starts with one Start node so the canvas is not a
        // blank page with no obvious first move.
        graph: {
          nodes: [
            {
              id: 'start-1',
              type: 'start',
              label: '',
              enabled: true,
              params: {},
              position: { x: 240, y: 80 },
            },
          ],
          edges: [],
        },
      })
      setOpen(false)
      setForm({ name: '', description: '', site_id: '' })
      navigate(`/workflows/${created.id}`)
    } catch (error) {
      setErrors(fieldErrors(error))
      toast.error(errorMessage(error))
    }
  }

  return (
    <>
      <PageHeader
        title={t('workflows.title')}
        description={t('workflows.subtitle')}
        actions={
          <div className="flex items-center gap-3">
            {capacity.data ? (
              <span className="text-xs text-muted">
                {t('workflows.capacity', {
                  active: capacity.data.active,
                  limit: capacity.data.limit,
                })}
              </span>
            ) : null}
            <Button variant="primary" onClick={() => setOpen(true)}>
              <Plus className="size-4" aria-hidden />
              {t('workflows.create')}
            </Button>
          </div>
        }
      />

      <Card>
        {workflows.isError ? (
          <ErrorState
            error={workflows.error}
            onRetry={() => void workflows.refetch()}
          />
        ) : (
          <Table>
            <THead>
              <Th>{t('common.name')}</Th>
              <Th>{t('workflows.site')}</Th>
              <Th align="right">{t('workflows.nodes')}</Th>
              <Th align="right">{t('workflows.activeRuns')}</Th>
              <Th>{t('common.status')}</Th>
              <Th align="right">{t('common.updated')}</Th>
              <Th />
            </THead>
            <TBody>
              {workflows.isPending ? (
                <EmptyRow colSpan={7} message={`${t('common.loading')}…`} />
              ) : (workflows.data?.items ?? []).length > 0 ? (
                (workflows.data?.items ?? []).map((workflow) => (
                  <Tr key={workflow.id}>
                    <Td>
                      <Link to={`/workflows/${workflow.id}`} className="link">
                        {workflow.name}
                      </Link>
                      {workflow.description ? (
                        <p className="text-xs text-muted">{workflow.description}</p>
                      ) : null}
                    </Td>
                    <Td>{workflow.site_name ?? '—'}</Td>
                    <Td align="right">{workflow.node_count}</Td>
                    <Td align="right">
                      {workflow.active_run_count > 0 ? (
                        <Badge tone="ok">{workflow.active_run_count}</Badge>
                      ) : (
                        '—'
                      )}
                    </Td>
                    <Td>
                      <Badge tone={workflow.is_enabled ? 'ok' : 'neutral'}>
                        {workflow.is_enabled ? t('common.enabled') : t('common.disabled')}
                      </Badge>
                    </Td>
                    <Td align="right" className="whitespace-nowrap text-muted">
                      {formatDateTime(workflow.updated_at)}
                    </Td>
                    <Td align="right">
                      {can('ems:write') ? (
                        <IconButton
                          label={t('common.delete')}
                          onClick={() => setDeleting(workflow)}
                        >
                          <Trash2 className="size-3.5" />
                        </IconButton>
                      ) : null}
                    </Td>
                  </Tr>
                ))
              ) : (
                <EmptyRow colSpan={7} message={t('workflows.empty')} />
              )}
            </TBody>
          </Table>
        )}
      </Card>

      <ConfirmDialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        danger
        loading={remove.isPending}
        title={t('common.delete')}
        confirmLabel={t('common.delete')}
        message={t('workflows.deleteConfirm', { name: deleting?.name ?? '' })}
        onConfirm={async () => {
          if (!deleting) return
          try {
            await remove.mutateAsync(deleting.id)
            setDeleting(null)
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t('workflows.create')}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              loading={create.isPending}
              onClick={() => void submit()}
            >
              {t('common.create')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <TextInput
            label={t('common.name')}
            required
            value={form.name}
            error={errors.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <TextArea
            label={t('common.description')}
            rows={2}
            value={form.description}
            onChange={(event) => setForm({ ...form, description: event.target.value })}
          />
          <SiteTreeSelect
            label={t('workflows.site')}
            sites={sites.data?.items ?? []}
            value={form.site_id}
            placeholder={t('common.none')}
            allowClear
            hint={t('workflows.siteHint')}
            onChange={(site_id) => setForm({ ...form, site_id })}
          />
        </div>
      </Modal>
    </>
  )
}
