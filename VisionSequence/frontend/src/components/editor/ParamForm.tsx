/** 步驟的完整參數表單：依 def.params 產生（基本／進階分組、visible_when、前端驗證訊息）。工具頁左欄用。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { nodeProblems, paramVisible } from '@/lib/graphValidation'
import type { GraphEdge, GraphNode, ToolTypeDef } from '@/lib/types'
import { ParamField, type InspectorActions } from './ParamField'

export function ParamForm({ node, definition, edges, onChange, actions }: { node: GraphNode; definition: ToolTypeDef | undefined; edges: GraphEdge[]; onChange: (patch: Partial<GraphNode>) => void; actions: InspectorActions }) {
  const { t } = useTranslation()
  const params = node.params ?? {}
  const [showAdvanced, setShowAdvanced] = useState(false)
  const problems = useMemo(() => nodeProblems(node, definition, edges), [node, definition, edges])
  const problemByKey = new Map(problems.map((p) => [p.key, p]))

  const visibleParams = (definition?.params ?? []).filter((p) => paramVisible(p, params))
  const basic = visibleParams.filter((p) => !p.group)
  const advanced = visibleParams.filter((p) => p.group)

  const renderParam = (param: (typeof visibleParams)[number]) => {
    const problem = problemByKey.get(param.key)
    return (
      <div key={param.key} data-param={param.key}>
        <ParamField param={param} value={params[param.key] ?? param.default} actions={actions} onChange={(value) => onChange({ params: { ...params, [param.key]: value } })} />
        {problem ? <p className="mt-1 text-[11px] text-critical">{t(`editor.validation.${problem.code}`, problem.values)}</p> : null}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {visibleParams.length === 0 ? <p className="text-xs text-muted">{t('editor.noParameters')}</p> : basic.map(renderParam)}
      {advanced.length > 0 ? (
        <div>
          <button type="button" className="flex items-center gap-1 text-xs font-medium text-muted hover:text-content" onClick={() => setShowAdvanced((v) => !v)}>
            {showAdvanced ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {t('common.advanced')}（{advanced.length}）
          </button>
          {showAdvanced ? <div className="mt-2.5 space-y-4 border-l-2 border-line pl-3">{advanced.map(renderParam)}</div> : null}
        </div>
      ) : null}
      {problems.filter((p) => p.key.startsWith('in:') || p.key.startsWith('out:')).map((p) => (
        <p key={p.key} className={`rounded-lg px-3 py-2 text-xs ${p.severity === 'error' ? 'bg-critical-soft text-critical' : 'bg-warning-soft text-warning'}`}>
          {t(`editor.validation.${p.code}`, p.values)}
        </p>
      ))}
    </div>
  )
}
