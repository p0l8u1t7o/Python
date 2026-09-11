/**
 * 「封裝成工具」（PRODUCT-DIRECTION v2 §3-4 主路徑）：框選節點 → 命名／分類／圖示 → 建立複合工具 →
 * 畫布上那些節點換成一個工具節點（跨邊界的線重接到對外埠、原本的具名輸出名稱搬到實例上）。
 * 對外參數之後在工具庫進入編輯再勾。
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Modal, Select, TextArea, TextInput } from '@/components/ui'
import { COMPOSITE_KEY_PATTERN, encapsulateSelection, slugKey } from '@/lib/composite'
import { errorMessage } from '@/lib/errors'
import { useCompositeToolMutations } from '@/lib/queries'
import type { FlowGraph, ToolCatalogue, ToolTypeDef } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

interface Props {
  open: boolean
  onClose: () => void
  graph: FlowGraph
  selectedIds: string[]
  defs: Map<string, ToolTypeDef>
  categories: ToolCatalogue['categories']
  /** 封裝完成：呼叫端把畫布換成新的圖 */
  onApplied: (graph: FlowGraph, toolLabel: string) => void
}

export function EncapsulateDialog({ open, onClose, graph, selectedIds, defs, categories, onApplied }: Props) {
  const { t } = useTranslation()
  const toast = useToast()
  const { create } = useCompositeToolMutations()
  const [label, setLabel] = useState('')
  const [key, setKey] = useState('')
  const [keyTouched, setKeyTouched] = useState(false)
  const [category, setCategory] = useState('logic')
  const [icon, setIcon] = useState('Boxes')
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (!open) return
    setLabel('')
    setKey('')
    setKeyTouched(false)
    setCategory('logic')
    setIcon('Boxes')
    setDescription('')
  }, [open])

  const preview = useMemo(() => (open ? encapsulateSelection(graph, selectedIds, defs, key || 'tool', label || 'Tool') : null), [open, graph, selectedIds, defs, key, label])
  const keyValid = COMPOSITE_KEY_PATTERN.test(key)
  const canSubmit = Boolean(label.trim()) && keyValid && Boolean(preview) && !create.isPending

  const submit = async () => {
    if (!preview || !canSubmit) return
    try {
      const made = await create.mutateAsync({ key, label: label.trim(), description, category, icon, graph: preview.toolGraph, interface: preview.interface })
      const applied = encapsulateSelection(graph, selectedIds, defs, made.key, made.label)
      if (applied) onApplied(applied.graph, made.label)
      onClose()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('editor.composite.encapsulateTitle')}
      description={t('editor.composite.encapsulateHint', { count: selectedIds.length })}
      dirty={Boolean(label || description)}
      footer={(close) => (
        <>
          <Button onClick={() => close()}>{t('common.cancel')}</Button>
          <Button variant="primary" disabled={!canSubmit} loading={create.isPending} onClick={() => void submit()} data-testid="encapsulate-confirm">{t('editor.composite.encapsulateConfirm')}</Button>
        </>
      )}
    >
      <div className="space-y-3" data-testid="encapsulate-dialog">
        <TextInput
          label={t('common.name')}
          value={label}
          required
          autoFocus
          onChange={(event) => {
            setLabel(event.target.value)
            if (!keyTouched) setKey(slugKey(event.target.value))
          }}
          data-testid="encapsulate-label"
        />
        <TextInput
          label={t('editor.composite.key')}
          hint={t('editor.composite.keyHint')}
          className="font-mono"
          value={key}
          required
          error={key && !keyValid ? t('editor.composite.keyInvalid') : undefined}
          onChange={(event) => {
            setKeyTouched(true)
            setKey(event.target.value.toLowerCase())
          }}
          data-testid="encapsulate-key"
        />
        <div className="grid grid-cols-2 gap-2">
          <Select label={t('editor.composite.category')} value={category} options={categories.map((item) => ({ value: item.key, label: item.label }))} onChange={(event) => setCategory(event.target.value)} data-testid="encapsulate-category" />
          <TextInput label={t('editor.composite.icon')} hint={t('editor.composite.iconHint')} value={icon} onChange={(event) => setIcon(event.target.value)} />
        </div>
        <TextArea label={t('common.description')} rows={2} value={description} onChange={(event) => setDescription(event.target.value)} />
        {preview ? (
          <p className="text-[11px] text-muted" data-testid="encapsulate-preview">
            {t('editor.composite.encapsulatePreview', { nodes: preview.toolGraph.nodes.length, inputs: preview.interface.inputs?.length ?? 0, outputs: preview.interface.outputs?.length ?? 0 })}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}
