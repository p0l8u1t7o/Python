/** 說明頁的工具目錄：從 /tool-types 動態列出（已由目錄字典翻譯），依分類分卡片。 */
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { iconFor } from '@/components/editor/ToolNode'
import { Card, CardBody, CardHeader, LoadingState } from '@/components/ui'
import { PORT_HEX } from '@/lib/ports'
import { useToolTypes } from '@/lib/queries'

export function ToolsCatalogue() {
  const { t } = useTranslation()
  const catalogue = useToolTypes()
  const groups = useMemo(() => {
    const map = new Map<string, { label: string; items: NonNullable<typeof catalogue.data>['items'] }>()
    for (const def of catalogue.data?.items ?? []) {
      const g = map.get(def.category) ?? { label: def.category_label, items: [] }
      g.items.push(def)
      map.set(def.category, g)
    }
    return [...map.values()]
  }, [catalogue.data])
  if (catalogue.isPending) return <LoadingState compact />
  return (
    <div className="space-y-4" data-testid="help-tools">
      {groups.map((group) => (
        <Card key={group.label}>
          <CardHeader title={group.label} description={t('help.toolsCount', { count: group.items.length })} />
          <CardBody className="divide-y divide-line !p-0">
            {group.items.map((def) => {
              const Icon = iconFor(def.icon)
              return (
                <div key={def.key} className="px-4 py-3">
                  <p className="flex items-center gap-2 text-sm font-semibold">
                    <Icon size={15} className="text-brand" /> {def.label}
                    <span className="font-mono text-[11px] font-normal text-muted">{def.key}</span>
                    {def.heavy ? <span className="text-[11px] font-normal text-warning">{t('editor.heavy')}</span> : null}
                  </p>
                  {def.description ? <p className="mt-0.5 text-xs text-muted">{def.description}</p> : null}
                  <div className="mt-1.5 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
                    <p>
                      <span className="font-medium text-muted">{t('editor.inputs')}: </span>
                      {def.inputs.length ? def.inputs.map((p, i) => (
                        <span key={`${p.key}-${i}`} className="mr-2 inline-flex items-center gap-1">
                          <span className="inline-block size-2 rounded-full" style={{ background: PORT_HEX[p.type] }} />{p.label}<span className="text-subtle">({p.type}{p.required ? '' : '?'})</span>
                        </span>
                      )) : '—'}
                    </p>
                    <p>
                      <span className="font-medium text-muted">{t('editor.outputs')}: </span>
                      {def.outputs.filter((p) => !p.implicit).map((p, i) => (
                        <span key={`${p.key}-${i}`} className="mr-2 inline-flex items-center gap-1">
                          <span className={`inline-block size-2 ${p.type === 'flow' ? 'rotate-45' : 'rounded-full'}`} style={{ background: PORT_HEX[p.type] }} />{p.label}<span className="text-subtle">({p.type})</span>
                        </span>
                      ))}
                    </p>
                  </div>
                  {def.params.length ? (
                    <p className="mt-1 text-xs">
                      <span className="font-medium text-muted">{t('editor.parameters')}: </span>
                      {def.params.map((p) => `${p.label} (${p.kind}${p.unit ? `, ${p.unit}` : ''})`).join(', ')}
                    </p>
                  ) : null}
                </div>
              )
            })}
          </CardBody>
        </Card>
      ))}
    </div>
  )
}
