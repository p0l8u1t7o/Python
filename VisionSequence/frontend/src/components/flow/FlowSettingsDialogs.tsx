import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { BoardSettings } from '@/components/flow/BoardSettings'
import { CommSettings } from '@/components/flow/CommSettings'
import { VariablesCard } from '@/components/flow/VariablesCard'
import { Button, Modal } from '@/components/ui'
import type { BoardConfig } from '@/lib/board'
import type { CommRule, Flow } from '@/lib/types'

type DialogKind = 'variables' | 'board' | 'comm'

interface Props {
  flowId: number
  flow: Pick<Flow, 'board' | 'comm'> | undefined
  boardOutputNames: string[]
  boardImageNodes: { id: string; label: string }[]
  readOnly: boolean
  saving: boolean
  onSaveBoard: (config: BoardConfig) => void
  onSaveComm: (rules: CommRule[]) => void
}

export function FlowSettingsDialogs({ flowId, flow, boardOutputNames, boardImageNodes, readOnly, saving, onSaveBoard, onSaveComm }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState<DialogKind | null>(null)
  const close = () => setOpen(null)

  return (
    <>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => setOpen('variables')} data-testid="editor-open-variables">
          {t('editor.openVariables')}
        </Button>
        <Button size="sm" onClick={() => setOpen('board')} data-testid="editor-open-board">
          {t('editor.openBoard')}
        </Button>
        <Button size="sm" onClick={() => setOpen('comm')} data-testid="editor-open-comm">
          {t('editor.openComm')}
        </Button>
      </div>

      <Modal open={open === 'variables'} onClose={close} title={t('variables.title')} size="md">
        <div className="h-[min(70vh,520px)] min-h-0 overflow-hidden" data-testid="editor-variables-dialog">
          <div className="h-full overflow-y-auto pr-1">
            <VariablesCard flowId={flowId} />
          </div>
        </div>
      </Modal>

      <Modal open={open === 'board'} onClose={close} title={t('board.settings.title')} size="lg">
        <div className="h-[min(75vh,680px)] min-h-0 overflow-hidden" data-testid="editor-board-dialog">
          <div className="h-full overflow-y-auto pr-1">
            <BoardSettings
              flowId={flowId}
              config={flow?.board}
              outputNames={boardOutputNames}
              imageNodes={boardImageNodes}
              readOnly={readOnly}
              saving={saving}
              onSave={onSaveBoard}
            />
          </div>
        </div>
      </Modal>

      <Modal open={open === 'comm'} onClose={close} title={t('comm.title')} size="lg">
        <div className="h-[min(75vh,680px)] min-h-0 overflow-hidden" data-testid="editor-comm-dialog">
          <div className="h-full overflow-y-auto pr-1">
            <CommSettings
              config={flow?.comm}
              nodes={boardImageNodes}
              readOnly={readOnly}
              saving={saving}
              onSave={onSaveComm}
            />
          </div>
        </div>
      </Modal>
    </>
  )
}
