/** 步驟的完整參數表單：依 def.params 產生（基本／進階分組、visible_when、前端驗證訊息）。工具頁左欄用。 */
import { useMemo, useState } from 'react'
import { exposedParamKeys, withParamExposed } from '@/lib/nodeInterface'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Link2 } from 'lucide-react'
import { PARAM_PREFIX } from '@/lib/types'
import { bindableParams } from '@/components/editor/graphMapping'

import { nodeProblems, paramVisible } from '@/lib/graphValidation'
import type { GraphEdge, GraphNode, ToolTypeDef } from '@/lib/types'
import { ParamField, type InspectorActions } from './ParamField'

export function ParamForm({ node, definition, edges, onChange, actions }: { node: GraphNode; definition: ToolTypeDef | undefined; edges: GraphEdge[]; onChange: (patch: Partial<GraphNode>) => void; actions: InspectorActions }) {
  const { t } = useTranslation()
  const params = node.params ?? {}
  const [showAdvanced, setShowAdvanced] = useState(false)
  const problems = useMemo(() => nodeProblems(node, definition, edges), [node, definition, edges])
  const problemByKey = new Map(problems.map((p) => [p.key, p]))

  // 參數訂閱：外露成埠的參數在畫布上多一個把手，接上上游就改吃那個值（後端 apps/vision/tools/base.py）
  const exposed = new Set(exposedParamKeys(node))
  const boundFrom = new Map(
    edges
      .filter((e) => e.target === node.id && (e.target_handle ?? '').startsWith(PARAM_PREFIX))
      .map((e) => [(e.target_handle ?? '').slice(PARAM_PREFIX.length), e.source] as const),
  )
  const bindable = new Set(bindableParams(definition).map((p) => p.key))
  const toggleExpose = (key: string) => onChange(withParamExposed(node, key, !exposed.has(key)))

  const visibleParams = (definition?.params ?? []).filter((p) => paramVisible(p, params))
  const basic = visibleParams.filter((p) => !p.group)
  const advanced = visibleParams.filter((p) => p.group)

  const renderParam = (param: (typeof visibleParams)[number]) => {
    const problem = problemByKey.get(param.key)
    const source = boundFrom.get(param.key)
    const on = exposed.has(param.key)
    return (
      <div key={param.key} data-param={param.key} className="group relative">
        {bindable.has(param.key) ? (
          <button
            type="button"
            className={`btn-icon absolute right-0 top-0 z-10 ${on ? 'text-brand' : 'text-subtle opacity-0 transition group-hover:opacity-100'}`}
            title={t(on ? 'editor.param.unbind' : 'editor.param.bind')}
            onClick={() => toggleExpose(param.key)}
            data-testid={`param-bind-${param.key}`}
          >
            <Link2 size={13} />
          </button>
        ) : null}
        <ParamField param={param} value={params[param.key] ?? param.default} actions={actions} onChange={(value) => onChange({ params: { ...params, [param.key]: value } })} />
        {source ? <p className="mt-1 text-[11px] text-muted">{t('editor.param.boundTo', { node: source })}</p> : on ? <p className="mt-1 text-[11px] text-subtle">{t('editor.param.exposed')}</p> : null}
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
            {t('common.advanced')} ({advanced.length})
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
