/**
 * Version history for a flow: every save is a snapshot you can read, compare and bring back.
 * Restoring writes a new version rather than rewriting history, so the trail stays usable as
 * evidence. "Released" is a signature, not a gate — it never blocks a run.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { History, RotateCcw, Tag } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import { keys } from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import { formatDateTime } from '@/lib/format'
import { useConfirm } from '@/lib/useConfirm'
import { Badge, Button, EmptyRow, ErrorState, LoadingState, Modal, TBody, THead, Table, Td, Th, Tr } from '@/components/ui'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

interface VersionRow {
  version: number
  saved_at: string
  saved_by: string
  note: string
  is_released: boolean
  node_count: number
  changes: number
  summary: string
  is_current: boolean
}

export function VersionPanel({ flowId, open, onClose, onRestored }: { flowId: number; open: boolean; onClose: () => void; onRestored?: () => void }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const { confirm, dialog } = useConfirm()
  const [busy, setBusy] = useState(0)

  const list = useQuery({
    queryKey: ['flow-versions', flowId],
    queryFn: () => api.get<{ items: VersionRow[]; current: number; keep: number }>(`/vision/flows/${flowId}/versions`),
    enabled: open,
  })

  const restore = useMutation({
    mutationFn: (version: number) => api.post(`/vision/flows/${flowId}/versions/${version}/restore`, {}),
    onSuccess: async (_data, version) => {
      await qc.invalidateQueries({ queryKey: keys.flow(flowId) })
      await list.refetch()
      toast.success(t('versions.restored', { version }))
      onRestored?.()
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const release = useMutation({
    mutationFn: ({ version, released }: { version: number; released: boolean }) =>
      api.post(`/vision/flows/${flowId}/versions/${version}/release`, { released }),
    onSuccess: () => void list.refetch(),
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <Modal open={open} onClose={onClose} title={t('versions.title')} description={t('versions.subtitle')} size="lg"
      footer={<Button onClick={onClose}>{t('common.close')}</Button>}>
      {list.isPending ? (
        <LoadingState />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : (
        <div className="max-h-[60vh] overflow-auto">
          <Table>
            <THead>
              <Th>{t('versions.cols.version')}</Th>
              <Th>{t('versions.cols.when')}</Th>
              <Th className="max-md:hidden">{t('versions.cols.who')}</Th>
              <Th>{t('versions.cols.changes')}</Th>
              <Th align="right">{t('common.actions')}</Th>
            </THead>
            <TBody>
              {(list.data?.items ?? []).length === 0 ? (
                <EmptyRow colSpan={5} message={t('versions.empty')} />
              ) : (
                (list.data?.items ?? []).map((row) => (
                  <Tr key={row.version} data-testid={`version-${row.version}`}>
                    <Td className="whitespace-nowrap">
                      <span className="tnum font-mono text-xs">v{row.version}</span>
                      {row.is_current ? <Badge tone="ok" className="ml-1.5">{t('versions.current')}</Badge> : null}
                      {row.is_released ? <Badge tone="info" className="ml-1.5"><Tag size={10} /> {t('versions.released')}</Badge> : null}
                    </Td>
                    <Td className="tnum whitespace-nowrap text-xs text-muted">{formatDateTime(row.saved_at)}</Td>
                    <Td className="max-md:hidden text-xs text-muted">{row.saved_by || '—'}</Td>
                    <Td className="text-xs"><span className="text-muted">{row.note ? `${row.note} · ` : ''}</span>{row.summary || (row.changes ? t('versions.changeCount', { count: row.changes }) : '—')}</Td>
                    <Td align="right">
                      {auth.isEngineer ? (
                        <div className="flex justify-end gap-1">
                          <Button size="xs" variant="ghost" icon={<Tag size={13} />} loading={release.isPending && busy === row.version}
                            onClick={() => { setBusy(row.version); release.mutate({ version: row.version, released: !row.is_released }) }}
                            data-testid={`version-release-${row.version}`}>
                            {row.is_released ? t('versions.unrelease') : t('versions.release')}
                          </Button>
                          <Button size="xs" icon={<RotateCcw size={13} />} disabled={row.is_current} loading={restore.isPending && busy === row.version}
                            onClick={async () => {
                              if (!(await confirm(t('versions.restoreConfirm', { version: row.version }), { title: t('versions.restore') }))) return
                              setBusy(row.version)
                              restore.mutate(row.version)
                            }} data-testid={`version-restore-${row.version}`}>
                            {t('versions.restore')}
                          </Button>
                        </div>
                      ) : null}
                    </Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
          {list.data ? <p className="px-1 pt-3 text-xs text-muted">{t('versions.keepHint', { keep: list.data.keep })}</p> : null}
        </div>
      )}
      {dialog}
    </Modal>
  )
}

/** Header button that opens the panel. */
export function VersionButton({ flowId, onRestored }: { flowId: number; onRestored?: () => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size="sm" icon={<History size={14} />} onClick={() => setOpen(true)} data-testid="open-versions">{t('versions.open')}</Button>
      <VersionPanel flowId={flowId} open={open} onClose={() => setOpen(false)} onRestored={onRestored} />
    </>
  )
}
