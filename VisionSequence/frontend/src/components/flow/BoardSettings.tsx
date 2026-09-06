/**
 * 看板設定（編輯器設定面板）：這條流程的看板要顯示哪幾個具名輸出（含標籤、單位、小數、公差）、哪個節點的影像、
 * 哪些變數、要不要判定與今日良率。存在 Flow.board；總覽頁與 /board/{id} 全螢幕看板都照它畫。
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ExternalLink, Save } from 'lucide-react'
import { Button, Checkbox, Select, TextInput } from '@/components/ui'
import type { BoardConfig, BoardValueConfig } from '@/lib/board'

interface Props {
  flowId: number
  config: BoardConfig | undefined
  /** 圖裡會產生具名輸出的名字（output／format_text 的 name） */
  outputNames: string[]
  /** 有影像輸出的節點（id 與顯示名） */
  imageNodes: { id: string; label: string }[]
  readOnly: boolean
  saving: boolean
  onSave: (config: BoardConfig) => void
}

function num(text: string): number | undefined {
  const s = text.trim()
  if (s === '') return undefined
  const n = Number(s)
  return Number.isFinite(n) ? n : undefined
}

export function BoardSettings({ flowId, config, outputNames, imageNodes, readOnly, saving, onSave }: Props) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<BoardConfig>(config ?? {})
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    setDraft(config ?? {})
    setDirty(false)
  }, [config])

  const values = draft.values ?? []
  const names = Array.from(new Set([...outputNames, ...values.map((v) => v.key)]))
  const update = (patch: Partial<BoardConfig>) => {
    setDraft((d) => ({ ...d, ...patch }))
    setDirty(true)
  }
  const toggle = (key: string, on: boolean) => {
    update({ values: on ? [...values.filter((v) => v.key !== key), { key }] : values.filter((v) => v.key !== key) })
  }
  const patchValue = (key: string, patch: Partial<BoardValueConfig>) => {
    update({ values: values.map((v) => (v.key === key ? { ...v, ...patch } : v)) })
  }

  return (
    <div className="space-y-3" data-testid="board-settings">
      <p className="text-[11px] text-subtle">{t('board.settings.hint')}</p>
      <TextInput label={t('board.settings.titleField')} value={draft.title ?? ''} placeholder={t('board.settings.titlePlaceholder')} disabled={readOnly} onChange={(e) => update({ title: e.target.value })} data-testid="board-title-input" />
      <Select
        label={t('board.settings.imageNode')}
        value={draft.image ?? ''}
        disabled={readOnly}
        onChange={(e) => update({ image: e.target.value })}
        options={[{ value: '', label: t('board.settings.imageAuto') }, ...imageNodes.map((n) => ({ value: n.id, label: n.label }))]}
        data-testid="board-image-node"
      />
      <div>
        <p className="mb-1 text-xs font-medium">{t('board.settings.values')}</p>
        <p className="mb-1.5 text-[11px] text-subtle">{t('board.settings.valuesHint')}</p>
        {names.length === 0 ? <p className="text-xs text-subtle">{t('board.settings.noOutputs')}</p> : null}
        <div className="space-y-1.5">
          {names.map((key) => {
            const item = values.find((v) => v.key === key)
            return (
              <div key={key} className="rounded-md border border-line px-2 py-1.5" data-testid={`board-value-${key}`}>
                <Checkbox label={<span className="font-mono text-xs">{key}</span>} checked={Boolean(item)} disabled={readOnly} onChange={(on) => toggle(key, on)} />
                {item ? (
                  <div className="mt-1.5 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
                    <TextInput label={t('board.settings.label')} value={item.label ?? ''} disabled={readOnly} onChange={(e) => patchValue(key, { label: e.target.value || undefined })} />
                    <TextInput label={t('board.settings.unit')} value={item.unit ?? ''} disabled={readOnly} onChange={(e) => patchValue(key, { unit: e.target.value || undefined })} />
                    <TextInput label={t('board.settings.decimals')} value={item.decimals === undefined ? '' : String(item.decimals)} inputMode="numeric" disabled={readOnly} onChange={(e) => patchValue(key, { decimals: num(e.target.value) })} />
                    <TextInput label={t('board.settings.low')} value={item.low === undefined ? '' : String(item.low)} inputMode="decimal" disabled={readOnly} onChange={(e) => patchValue(key, { low: num(e.target.value) })} />
                    <TextInput label={t('board.settings.high')} value={item.high === undefined ? '' : String(item.high)} inputMode="decimal" disabled={readOnly} onChange={(e) => patchValue(key, { high: num(e.target.value) })} />
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
      <TextInput
        label={t('board.settings.variables')}
        hint={t('board.settings.variablesHint')}
        value={(draft.variables ?? []).join(', ')}
        disabled={readOnly}
        onChange={(e) => update({ variables: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })}
        data-testid="board-variables-input"
      />
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <Checkbox label={t('board.settings.showVerdict')} checked={draft.show_verdict !== false} disabled={readOnly} onChange={(v) => update({ show_verdict: v })} />
        <Checkbox label={t('board.settings.showCounts')} checked={draft.show_counts !== false} disabled={readOnly} onChange={(v) => update({ show_counts: v })} />
        <Checkbox label={t('board.settings.overlays')} checked={draft.overlays !== false} disabled={readOnly} onChange={(v) => update({ overlays: v })} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" icon={<Save size={13} />} disabled={readOnly || !dirty} loading={saving} onClick={() => { onSave(draft); setDirty(false) }} data-testid="board-save">
          {t('board.settings.save')}
        </Button>
        <a className="inline-flex items-center gap-1 text-xs text-brand hover:underline" href={`/board/${flowId}`} target="_blank" rel="noreferrer" data-testid="board-open">
          <ExternalLink size={12} /> {t('board.settings.open')}
        </a>
      </div>
    </div>
  )
}
