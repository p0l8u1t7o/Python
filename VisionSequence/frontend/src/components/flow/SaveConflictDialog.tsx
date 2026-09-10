import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Modal } from '@/components/ui'
import { type FlowVersionConflictDetails, isFlowVersionConflict } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { diffFlow } from '@/lib/queries'
import type { FlowGraph } from '@/lib/types'

interface ConflictState {
  flowId: number
  graph: FlowGraph
  details: FlowVersionConflictDetails
  loadServer: (details: FlowVersionConflictDetails) => void
  overwrite: (updatedAt: string) => Promise<void>
}

export function conflictEditor(details: FlowVersionConflictDetails): string {
  return details.last_saved_by?.name || ''
}

export function conflictTime(details: FlowVersionConflictDetails): string {
  return details.last_saved_by?.at || details.updated_at
}

export function useSaveConflictDialog(): {
  showConflict: (
    error: unknown,
    args: {
      flowId: number
      graph: FlowGraph
      loadServer: (details: FlowVersionConflictDetails) => void
      overwrite: (updatedAt: string) => Promise<void>
    },
  ) => boolean
  dialog: ReactNode
} {
  const { t } = useTranslation()
  const [state, setState] = useState<ConflictState | null>(null)
  const [summary, setSummary] = useState('')
  const [diffLoading, setDiffLoading] = useState(false)
  const [action, setAction] = useState<'load' | 'overwrite' | null>(null)
  const [errorText, setErrorText] = useState('')

  const close = useCallback(() => {
    setState(null)
    setSummary('')
    setDiffLoading(false)
    setAction(null)
    setErrorText('')
  }, [])

  const showConflict = useCallback(
    (error: unknown, args: { flowId: number; graph: FlowGraph; loadServer: (details: FlowVersionConflictDetails) => void; overwrite: (updatedAt: string) => Promise<void> }) => {
      if (!isFlowVersionConflict(error)) return false
      const next = { flowId: args.flowId, graph: args.graph, details: error.details, loadServer: args.loadServer, overwrite: args.overwrite }
      setState(next)
      setSummary('')
      setErrorText('')
      setDiffLoading(true)
      void diffFlow(args.flowId, args.graph)
        .then((data) => setSummary(data.summary || t('saveConflict.noDiff')))
        .catch((err) => setErrorText(errorMessage(err)))
        .finally(() => setDiffLoading(false))
      return true
    },
    [t],
  )

  const editedBy = useMemo(() => (state ? conflictEditor(state.details) : ''), [state])
  const editedAt = useMemo(() => (state ? new Date(conflictTime(state.details)).toLocaleString() : ''), [state])

  const loadServer = async () => {
    if (!state) return
    setAction('load')
    try {
      state.loadServer(state.details)
      close()
    } finally {
      setAction(null)
    }
  }

  const overwrite = async () => {
    if (!state) return
    setAction('overwrite')
    setErrorText('')
    try {
      await state.overwrite(state.details.updated_at)
      close()
    } catch (err) {
      setErrorText(errorMessage(err))
    } finally {
      setAction(null)
    }
  }

  const dialog = (
    <Modal
      open={Boolean(state)}
      onClose={close}
      title={t('saveConflict.title')}
      description={t(editedBy ? 'saveConflict.descriptionWithUser' : 'saveConflict.description', { user: editedBy, time: editedAt })}
      size="md"
      footer={
        <>
          <Button onClick={() => void loadServer()} loading={action === 'load'} data-testid="save-conflict-load">
            {t('saveConflict.loadServer')}
          </Button>
          <Button variant="danger" onClick={() => void overwrite()} loading={action === 'overwrite'} data-testid="save-conflict-overwrite">
            {t('saveConflict.overwrite')}
          </Button>
          <Button variant="ghost" onClick={close} data-testid="save-conflict-cancel">
            {t('common.cancel')}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm" data-testid="save-conflict-dialog">
        <div>
          <p className="mb-1 font-medium text-heading">{t('saveConflict.diffTitle')}</p>
          <div className="rounded-md border border-line bg-surface-muted px-3 py-2 text-muted">
            {diffLoading ? t('common.loading') : (summary || t('saveConflict.noDiff'))}
          </div>
        </div>
        {errorText ? <p className="text-critical" role="alert">{errorText}</p> : null}
      </div>
    </Modal>
  )

  return { showConflict, dialog }
}
