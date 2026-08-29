/**
 * 匯入配方（RecipeImportModal）：選檔 → `POST /recipes/import/check`（multipart）→ 顯示流程名稱／指紋是否相同、
 * 每個配方的檢查清單（可勾選 ok／unchanged／version_changed）→ `POST /recipes/import {doc, accept}` → 寫入幾項、略過幾項。
 */
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, TriangleAlert, Upload } from 'lucide-react'

import { Badge, Button, Modal } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useRecipeImport } from '@/lib/queries'
import type { RecipeImportCheck } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'
import { CheckItemsTable, defaultSelection } from './RecipeCheckList'

export function RecipeImportModal({ open, onClose, flowId }: { open: boolean; onClose: () => void; flowId: number }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { check, run } = useRecipeImport(flowId)
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null)
  const [result, setResult] = useState<RecipeImportCheck | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [setDefault, setSetDefault] = useState(false)

  function reset() {
    setFile(null)
    setDoc(null)
    setResult(null)
    setSelected(new Set())
    setSetDefault(false)
  }
  function close() {
    reset()
    onClose()
  }

  async function pick(f: File) {
    setFile(f)
    setResult(null)
    try {
      const text = await f.text()
      let parsed = JSON.parse(text) as Record<string, unknown>
      if (parsed && typeof parsed === 'object' && 'doc' in parsed && typeof parsed.doc === 'object') parsed = parsed.doc as Record<string, unknown>
      setDoc(parsed)
      const res = await check.mutateAsync(f)
      setResult(res)
      // 多個配方的 key 會重複（同 node.param）；用 "配方名|key" 區分勾選
      setSelected(new Set(res.recipes.flatMap((r) => [...defaultSelection(r.items)].map((k) => `${r.name}|${k}`))))
    } catch (error) {
      setDoc(null)
      toast.error(errorMessage(error))
    }
  }

  async function doImport() {
    if (!doc || !result) return
    // 後端 accept 是 key 清單（不分配方）：同 key 在任一配方被勾就接受。
    const accept = [...new Set([...selected].map((s) => s.slice(s.indexOf('|') + 1)))]
    try {
      const res = await run.mutateAsync({ doc, accept, is_default: setDefault })
      const accepted = res.items.reduce((n, r) => n + r.accepted, 0)
      toast.success(t('recipes.importResult', { accepted, skipped: res.skipped.length, count: res.items.length }))
      close()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const perRecipe = (name: string) => {
    const on = new Set([...selected].filter((s) => s.startsWith(`${name}|`)).map((s) => s.slice(name.length + 1)))
    return {
      selected: on,
      onChange: (next: Set<string>) => {
        const rest = [...selected].filter((s) => !s.startsWith(`${name}|`))
        setSelected(new Set([...rest, ...[...next].map((k) => `${name}|${k}`)]))
      },
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title={t('recipes.importTitle')}
      description={t('recipes.importHint')}
      size="lg"
      footer={
        <>
          {result ? <span className="mr-auto tnum text-xs text-muted" data-testid="import-count">{t('recipes.selectedCount', { count: selected.size, total: result.recipes.reduce((n, r) => n + (r.summary.acceptable ?? 0), 0) })}</span> : null}
          <Button onClick={close}>{t('common.cancel')}</Button>
          <Button variant="primary" icon={<Upload size={14} />} loading={run.isPending} disabled={!result || !doc} onClick={() => void doImport()} data-testid="import-run">{t('recipes.importRun')}</Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => input.current?.click()} loading={check.isPending} data-testid="import-pick">{t('recipes.importFile')}</Button>
          <input ref={input} type="file" accept=".json,application/json" className="hidden" data-testid="recipe-import-input" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void pick(f) }} />
          <span className="truncate text-xs text-muted">{file?.name ?? '—'}</span>
        </div>
        {result ? (
          <div className="space-y-3" data-testid="import-check">
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge tone={result.same_flow_name ? 'ok' : 'warning'}>
                {result.same_flow_name ? <CheckCircle2 size={11} /> : <TriangleAlert size={11} />}
                {result.same_flow_name ? t('recipes.sameFlowName') : t('recipes.diffFlowName', { name: result.flow_name ?? '?' })}
              </Badge>
              <Badge tone={result.fingerprint_match ? 'ok' : 'warning'}>
                {result.fingerprint_match ? <CheckCircle2 size={11} /> : <TriangleAlert size={11} />}
                {result.fingerprint_match ? t('recipes.fingerprintMatch') : t('recipes.fingerprintDiff')}
              </Badge>
            </div>
            {result.recipes.map((r) => {
              const sel = perRecipe(r.name)
              return (
                <section key={r.name} className="space-y-1.5" data-testid="import-recipe">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    {r.name || t('recipes.unnamed')}
                    {r.exists ? <Badge tone="warning">{t('recipes.exists')}</Badge> : <Badge tone="info">{t('recipes.willCreate')}</Badge>}
                    <span className="tnum text-[11px] font-normal text-muted">{t('recipes.summary', { acceptable: r.summary.acceptable ?? 0, total: r.summary.total ?? 0 })}</span>
                  </p>
                  <CheckItemsTable items={r.items} selected={sel.selected} onChange={sel.onChange} testId="import-items" />
                </section>
              )
            })}
            {result.recipes.length === 1 ? (
              <label className="flex items-center gap-2 text-xs text-muted">
                <input type="checkbox" className="accent-[var(--brand)]" checked={setDefault} onChange={(e) => setSetDefault(e.target.checked)} data-testid="import-bind" />
                {t('recipes.importBind')}
              </label>
            ) : null}
          </div>
        ) : null}
      </div>
    </Modal>
  )
}
