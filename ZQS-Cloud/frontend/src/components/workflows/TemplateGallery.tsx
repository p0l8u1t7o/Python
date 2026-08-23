import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BookTemplate, Layers3, Trash2, User } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { useSites, useWorkflowTemplateMutations, useWorkflowTemplates } from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import type { WorkflowTemplate } from '@/lib/workflowTypes'
import { Badge, Button, ConfirmDialog, Modal, SiteTreeSelect, TextInput } from '@/components/ui'

/**
 * Pick a workflow template.
 *
 * Two jobs share the card list: the list page creates a new workflow from a
 * template (name + site), the editor loads a template into the canvas it is
 * already on (site comes from the workflow). Either way the backend resolves
 * the template's role placeholders - `{BESS}`, `{METER}` - against the site,
 * and anything it cannot resolve is reported so the operator picks the
 * device on the canvas instead of finding a wrong one wired in.
 */
export interface TemplateGalleryProps {
  open: boolean
  onClose: () => void
  mode: 'create' | 'load'
  /** Load mode: the site the canvas belongs to (placeholders resolve against it). */
  siteId?: string | null
  /** Create mode: called with what the user filled in plus the chosen template. */
  onCreate?: (template: WorkflowTemplate, name: string, siteId: string) => Promise<void> | void
  /** Load mode. */
  onLoad?: (template: WorkflowTemplate) => Promise<void> | void
  busy?: boolean
}

export function TemplateGallery({ open, onClose, mode, siteId, onCreate, onLoad, busy }: TemplateGalleryProps) {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const templates = useWorkflowTemplates(open)
  const sites = useSites()
  const { remove } = useWorkflowTemplateMutations()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [name, setName] = useState('')
  const [site, setSite] = useState(siteId ?? '')
  const [deleting, setDeleting] = useState<WorkflowTemplate | null>(null)

  const list = useMemo(() => {
    const q = query.trim().toLowerCase()
    const all = templates.data ?? []
    return q ? all.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(q)) : all
  }, [templates.data, query])
  const selected = list.find((item) => item.id === selectedId) ?? null

  function pick(template: WorkflowTemplate) {
    setSelectedId(template.id)
    if (!name) setName(template.name)
  }

  async function confirm() {
    if (!selected) return
    if (mode === 'create') await onCreate?.(selected, name.trim() || selected.name, site)
    else await onLoad?.(selected)
  }

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        size="lg"
        title={mode === 'create' ? t('workflows.templates.createFrom') : t('workflows.templates.loadInto')}
        footer={
          <>
            <Button onClick={onClose}>{t('common.cancel')}</Button>
            <Button variant="primary" disabled={!selected} loading={busy} onClick={() => void confirm()}>
              {mode === 'create' ? t('common.create') : t('workflows.templates.load')}
            </Button>
          </>
        }
      >
        <div className="space-y-3" data-testid="template-gallery">
          <TextInput
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('workflows.templates.search')}
          />
          <div className="grid max-h-[50vh] gap-2 overflow-y-auto sm:grid-cols-2">
            {list.map((template) => {
              const active = template.id === selectedId
              return (
                <div
                  key={template.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => pick(template)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      pick(template)
                    }
                  }}
                  data-testid={`template-card-${template.id}`}
                  className={`rounded-lg border p-3 text-left transition ${
                    active ? 'border-brand ring-2 ring-brand/30' : 'border-line bg-surface hover:border-line-strong'
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-brand-soft text-brand">
                      {template.source === 'builtin' ? <BookTemplate size={14} aria-hidden /> : <User size={14} aria-hidden />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{template.name}</p>
                      <p className="mt-0.5 line-clamp-2 text-xs text-muted">{template.description || '—'}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1">
                        <Badge tone={template.source === 'builtin' ? 'brand' : 'neutral'}>
                          {t(`workflows.templates.source.${template.source}`)}
                        </Badge>
                        <Badge tone="neutral">
                          <Layers3 size={10} className="mr-0.5 inline" aria-hidden />
                          {t('workflows.templates.nodes', { count: template.node_count })}
                        </Badge>
                        {template.placeholders.map((key) => (
                          <span key={key} className="rounded bg-surface-muted px-1 text-[10px] text-muted">
                            {template.placeholder_labels[key] ?? key}
                          </span>
                        ))}
                      </div>
                    </div>
                    {template.source === 'custom' && can('ems:write') ? (
                      <button
                        type="button"
                        aria-label={t('common.delete')}
                        className="rounded p-1 text-subtle hover:text-critical"
                        onClick={(event) => {
                          event.stopPropagation()
                          setDeleting(template)
                        }}
                      >
                        <Trash2 size={14} aria-hidden />
                      </button>
                    ) : null}
                  </div>
                </div>
              )
            })}
            {list.length === 0 ? (
              <p className="p-3 text-sm text-muted sm:col-span-2">{t('workflows.templates.empty')}</p>
            ) : null}
          </div>

          {mode === 'create' && selected ? (
            <div className="grid gap-3 border-t border-line pt-3 sm:grid-cols-2">
              <TextInput
                label={t('common.name')}
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
              <SiteTreeSelect
                label={t('workflows.site')}
                sites={sites.data?.items ?? []}
                value={site}
                placeholder={t('common.none')}
                allowClear
                hint={t('workflows.templates.siteHint')}
                onChange={setSite}
              />
            </div>
          ) : null}
          {mode === 'load' && selected ? (
            <p className="border-t border-line pt-3 text-xs text-muted">{t('workflows.templates.loadHint')}</p>
          ) : null}
        </div>
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        title={t('workflows.templates.deleteTitle')}
        message={deleting ? t('workflows.templates.deleteMessage', { name: deleting.name }) : ''}
        confirmLabel={t('common.delete')}
        danger
        loading={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={async () => {
          if (!deleting) return
          try {
            await remove.mutateAsync(deleting.id)
            if (selectedId === deleting.id) setSelectedId(null)
            setDeleting(null)
            toast.success(t('workflows.templates.deleted'))
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />
    </>
  )
}

export default TemplateGallery
