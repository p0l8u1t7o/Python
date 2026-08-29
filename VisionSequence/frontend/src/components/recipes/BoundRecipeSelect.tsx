/**
 * 綁定配方（BoundRecipeSelect）：選「目前綁定執行的配方」= `is_default`。
 * 選某配方 → PATCH is_default:true；選「不用配方（圖值）」→ 把目前預設的 is_default 設 false。
 * 執行一次／連續／外部觸發未指定 recipe 都用這個綁定。
 */
import { useTranslation } from 'react-i18next'
import { Link2 } from 'lucide-react'

import { errorMessage } from '@/lib/errors'
import { useRecipeMutations } from '@/lib/queries'
import type { FlowRecipe } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

export function boundRecipe(recipes: FlowRecipe[] | undefined): FlowRecipe | null {
  return recipes?.find((r) => r.is_default) ?? null
}

export function BoundRecipeSelect({ flowId, recipes, disabled = false, className = '', showLabel = true, testId = 'bound-recipe' }: { flowId: number; recipes: FlowRecipe[]; disabled?: boolean; className?: string; showLabel?: boolean; testId?: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { patch } = useRecipeMutations(flowId)
  const bound = boundRecipe(recipes)

  async function change(value: string) {
    try {
      if (value === '') {
        if (bound) await patch.mutateAsync({ id: bound.id, is_default: false })
        toast.success(t('recipes.boundCleared'))
      } else {
        const r = recipes.find((x) => String(x.id) === value)
        if (!r) return
        await patch.mutateAsync({ id: r.id, is_default: true })
        toast.success(t('recipes.boundSet', { name: r.name }))
      }
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <label className={`flex items-center gap-1 text-[11px] text-muted ${className}`} title={t('recipes.boundHint')} onClick={(e) => e.stopPropagation()}>
      {showLabel ? <span className="flex items-center gap-1 whitespace-nowrap"><Link2 size={12} className={bound ? 'text-brand' : 'text-subtle'} /> {t('recipes.bound')}</span> : null}
      <select className="input !h-8 !w-40 !py-0 text-xs" value={bound ? String(bound.id) : ''} disabled={disabled || patch.isPending} onChange={(e) => void change(e.target.value)} data-testid={testId}>
        <option value="">{t('recipes.boundNone')}</option>
        {recipes.map((r) => <option key={r.id} value={String(r.id)}>{r.name}</option>)}
      </select>
    </label>
  )
}

/** 「綁定：partA」文字標籤。 */
export function BoundBadge({ recipes, className = '' }: { recipes: FlowRecipe[] | undefined; className?: string }) {
  const { t } = useTranslation()
  const bound = boundRecipe(recipes)
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] ${bound ? 'border-brand/40 bg-brand-soft text-brand' : 'border-line text-muted'} ${className}`} title={t('recipes.boundHint')} data-testid="bound-badge">
      <Link2 size={11} /> {t('recipes.boundLabel', { name: bound ? bound.name : t('recipes.boundGraph') })}
    </span>
  )
}
