/**
 * 工具庫（PRODUCT-DIRECTION v2 §3-8）：站台的複合工具清單——新建、進入編輯（工具的畫布）、匯出 .tool.json、匯入、
 * 另存為我的工具（內建工具唯讀）、刪除（仍被流程使用就擋下並列出）。改工具本體會直接影響所有用到它的流程（不鎖版本，P5 再做）。
 */
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { Boxes, Copy, Download, Pencil, Plus, Trash2, Upload } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, ConfirmDialog, EmptyRow, ErrorState, LoadingState, Modal, PageHeader, TBody, THead, Table, Td, Th, Tr, TextInput } from '@/components/ui'
import { downloadFile } from '@/lib/api'
import { COMPOSITE_KEY_PATTERN, slugKey } from '@/lib/composite'
import { errorMessage } from '@/lib/errors'
import { formatDateTime } from '@/lib/format'
import { useCompositeTool, useCompositeToolMutations, useCompositeTools } from '@/lib/queries'
import type { CompositeTool } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

export function ToolLibraryPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const auth = useAuth()
  const canEdit = auth.can('tools.edit')
  const tools = useCompositeTools()
  const { create, remove, duplicate, importFile } = useCompositeToolMutations()
  const [creating, setCreating] = useState(false)
  const [copying, setCopying] = useState<CompositeTool | null>(null)
  const [pendingDelete, setPendingDelete] = useState<CompositeTool | null>(null)
  const [form, setForm] = useState({ label: '', key: '', touched: false })
  const fileInput = useRef<HTMLInputElement>(null)

  const openForm = (tool: CompositeTool | null) => {
    setForm({ label: tool ? `${tool.label} (copy)` : '', key: tool ? `${tool.key}_copy` : '', touched: Boolean(tool) })
    if (tool) setCopying(tool)
    else setCreating(true)
  }
  const closeForm = () => {
    setCreating(false)
    setCopying(null)
  }
  const keyValid = COMPOSITE_KEY_PATTERN.test(form.key)

  const submit = async () => {
    if (!form.label.trim() || !keyValid) return
    try {
      const made = copying
        ? await duplicate.mutateAsync({ id: copying.id, key: form.key, label: form.label.trim() })
        : await create.mutateAsync({ key: form.key, label: form.label.trim(), graph: { nodes: [], edges: [] }, interface: {} })
      closeForm()
      toast.success(t('tools.created', { name: made.label }))
      navigate(`/flows/${made.flow_id}`)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const confirmDelete = async () => {
    if (!pendingDelete) return
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('tools.deleted', { name: pendingDelete.label }))
      setPendingDelete(null)
    } catch (error) {
      toast.error(errorMessage(error))
      setPendingDelete(null)
    }
  }

  const exportTool = async (tool: CompositeTool) => {
    try {
      await downloadFile(`/vision/composite-tools/${tool.id}/export`, `${tool.key}.tool.json`)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const importTool = async (file: File) => {
    try {
      const result = await importFile.mutateAsync({ file })
      toast.success(t(`tools.import.${result.action}`, { name: result.tool.label }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const items = tools.data?.items ?? []
  return (
    <Page>
      <PageHeader
        title={t('tools.title')}
        description={t('tools.subtitle')}
        actions={
          canEdit ? (
            <>
              <input ref={fileInput} type="file" accept=".json,application/json" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importTool(file); event.target.value = '' }} data-testid="tools-import-input" />
              <Button icon={<Upload size={15} />} loading={importFile.isPending} onClick={() => fileInput.current?.click()} data-testid="tools-import">{t('tools.import.button')}</Button>
              <Button variant="primary" icon={<Plus size={15} />} onClick={() => openForm(null)} data-testid="tools-create">{t('tools.create')}</Button>
            </>
          ) : undefined
        }
      />
      <p className="mb-3 rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning" data-testid="tools-direct-reference">{t('tools.directReference')}</p>
      {tools.isLoading ? <LoadingState /> : tools.error ? <ErrorState error={tools.error} onRetry={() => void tools.refetch()} /> : (
        <Card testId="tools-table">
          <div className="overflow-x-auto">
            <Table>
              <THead>
                <Th>{t('common.name')}</Th>
                <Th className="max-lg:hidden">{t('tools.key')}</Th>
                <Th className="max-lg:hidden">{t('tools.toolVersion')}</Th>
                <Th className="max-lg:hidden">{t('tools.category')}</Th>
                <Th align="right">{t('tools.usedBy')}</Th>
                <Th className="max-xl:hidden">{t('tools.updatedAt')}</Th>
                <Th align="right">{t('common.actions')}</Th>
              </THead>
              <TBody>
                {items.length === 0 ? <EmptyRow colSpan={6} message={t('tools.empty')} /> : null}
                {items.map((tool) => (
                  <Tr key={tool.id} testId={`tool-row-${tool.key}`}>
                    <Td>
                      <span className="flex items-center gap-2">
                        <Boxes size={14} className="shrink-0 text-brand" aria-hidden />
                        <span className="font-medium">{tool.label}</span>
                        {tool.builtin ? <Badge tone="info">{t('tools.builtin')}</Badge> : null}
                      </span>
                      {tool.description ? <p className="mt-0.5 max-w-md truncate text-xs text-muted">{tool.description}</p> : null}
                    </Td>
                    <Td className="max-lg:hidden"><span className="font-mono text-xs">{tool.key}</span></Td>
                    <Td className="max-lg:hidden"><span className="tabular-nums text-xs" data-testid="tool-version">v{tool.version}</span></Td>
                    <Td className="max-lg:hidden">{tool.category_label}</Td>
                    <Td align="right">
                      <span className="whitespace-nowrap tabular-nums" title={t('tools.usedByHint', { flows: tool.used_by_flows ?? 0, tools: tool.used_by_tools ?? 0 })}>
                        {(tool.used_by_flows ?? 0) + (tool.used_by_tools ?? 0)}
                      </span>
                    </Td>
                    <Td className="max-xl:hidden"><span className="whitespace-nowrap text-xs text-muted" title={tool.updated_at}>{formatDateTime(tool.updated_at)}</span></Td>
                    <Td align="right">
                      <span className="flex items-center justify-end gap-1">
                        <Button size="sm" icon={<Pencil size={13} />} onClick={() => navigate(`/flows/${tool.flow_id}`)} data-testid={`tool-open-${tool.key}`}>
                          {tool.builtin || !canEdit ? t('tools.view') : t('tools.edit')}
                        </Button>
                        <Button size="sm" icon={<Download size={13} />} onClick={() => void exportTool(tool)} title={t('tools.exportHint')} data-testid={`tool-export-${tool.key}`}>{t('tools.export')}</Button>
                        {canEdit ? <Button size="sm" icon={<Copy size={13} />} onClick={() => openForm(tool)} title={t('tools.copyHint')} data-testid={`tool-copy-${tool.key}`}>{t('tools.copy')}</Button> : null}
                        {canEdit && !tool.builtin ? (
                          <>
                            <span className="mx-1 h-4 w-px bg-line" aria-hidden />
                            <Button size="sm" variant="ghost" className="text-muted hover:text-critical" icon={<Trash2 size={13} />} onClick={() => setPendingDelete(tool)} title={t('common.delete')} aria-label={t('common.delete')} data-testid={`tool-delete-${tool.key}`} />
                          </>
                        ) : null}
                      </span>
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          </div>
        </Card>
      )}

      <Modal
        open={creating || Boolean(copying)}
        onClose={closeForm}
        title={copying ? t('tools.copyTitle', { name: copying.label }) : t('tools.createTitle')}
        description={copying ? t('tools.copyDescription') : t('tools.createDescription')}
        dirty={Boolean(form.label)}
        footer={(close) => (
          <>
            <Button onClick={() => close()}>{t('common.cancel')}</Button>
            <Button variant="primary" disabled={!form.label.trim() || !keyValid} loading={create.isPending || duplicate.isPending} onClick={() => void submit()} data-testid="tools-form-confirm">{copying ? t('tools.copy') : t('tools.create')}</Button>
          </>
        )}
      >
        <div className="space-y-3" data-testid="tools-form">
          <TextInput label={t('common.name')} value={form.label} required autoFocus onChange={(event) => setForm((current) => ({ ...current, label: event.target.value, key: current.touched ? current.key : slugKey(event.target.value) }))} data-testid="tools-form-label" />
          <TextInput label={t('tools.key')} hint={t('editor.composite.keyHint')} className="font-mono" value={form.key} required error={form.key && !keyValid ? t('editor.composite.keyInvalid') : undefined} onChange={(event) => setForm((current) => ({ ...current, key: event.target.value.toLowerCase(), touched: true }))} data-testid="tools-form-key" />
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => void confirmDelete()}
        title={t('tools.deleteTitle')}
        message={pendingDelete ? t('tools.deleteMessage', { name: pendingDelete.label }) : ''}
        confirmLabel={t('common.delete')}
        danger
        loading={remove.isPending}
      />
    </Page>
  )
}

/** `/tools/:toolId`：工具的畫布就是它的內部流程（kind=tool），直接導過去；麵包屑會顯示「工具庫 › 工具」。 */
export function ToolOpenPage() {
  const { toolId } = useParams<{ toolId: string }>()
  const id = Number(toolId)
  const tool = useCompositeTool(Number.isNaN(id) ? null : id)
  if (tool.isLoading) return <LoadingState />
  if (tool.error || !tool.data) return <ErrorState error={tool.error ?? new Error('Not found')} />
  return <Navigate to={`/flows/${tool.data.flow_id}`} replace />
}
