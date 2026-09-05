/**
 * 說明頁（HelpPage）`/help`：快速上手、名詞定義（docs/glossary.html 的表）、埠型別與顏色圖例、
 * 工具目錄（從 /tool-types 動態列出）、快捷鍵、自動化接口摘要、帳號與鎖定。
 * 全部文字都走 i18n（help.content.*，三語系同構）；工具目錄從 /tool-types 動態列出（已由目錄字典翻譯）。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { Plug } from 'lucide-react'

import { iconFor } from '@/components/editor/ToolNode'
import { Page } from '@/components/layout/AppShell'
import { Button, Card, CardBody, CardHeader, LoadingState, PageHeader, Tabs } from '@/components/ui'
import { PORT_HEX } from '@/lib/ports'
import { useToolTypes } from '@/lib/queries'
import type { PortType } from '@/lib/types'

type HelpTab = 'quickstart' | 'glossary' | 'ports' | 'tools' | 'shortcuts' | 'automation' | 'accounts'
const TABS: HelpTab[] = ['quickstart', 'glossary', 'ports', 'tools', 'shortcuts', 'automation', 'accounts']

function Table({ head, rows }: { head: string[]; rows: (string | React.ReactNode)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>{head.map((h) => <th key={h} className="table-header">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row, i) => (
            <tr key={i}>{row.map((cell, j) => <td key={j} className={`table-cell ${j === 1 ? 'font-mono text-xs' : ''}`}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ToolsCatalogue() {
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

export function HelpPage() {
  const { t } = useTranslation()
  // 說明內容依語系整份取出（陣列），三語系的形狀由 i18n 測試鎖住
  const content = <T,>(key: string) => t(`help.content.${key}`, { returnObjects: true }) as unknown as T
  const QUICKSTART = content<{ title: string; body: string }[]>('quickstart')
  const GLOSSARY_PAGES = content<[string, string, string, string][]>('pages')
  const GLOSSARY_EDITOR = content<[string, string, string][]>('editor')
  const GLOSSARY_CORE = content<[string, string, string][]>('core')
  const GLOSSARY_STATUS = content<[string, string, string][]>('status')
  const PORT_ROWS = content<[PortType, string, string][]>('ports')
  const SHORTCUTS = content<[string, string][]>('shortcuts')
  const AUTOMATION = content<{ title: string; code: string }[]>('automation')
  const ACCOUNTS = content<string[]>('accounts')
  const [params, setParams] = useSearchParams()
  const initial = params.get('tab') as HelpTab | null
  const [tab, setTab] = useState<HelpTab>(initial && TABS.includes(initial) ? initial : 'quickstart')
  const change = (next: HelpTab) => {
    setTab(next)
    setParams({ tab: next }, { replace: true })
  }
  return (
    <Page>
      <PageHeader title={t('help.title')} description={t('help.subtitle')} />
      <Tabs value={tab} onChange={change} tabs={TABS.map((value) => ({ value, label: t(`help.tabs.${value}`) }))} className="mb-4 flex-wrap" />
      <div data-testid={`help-${tab}`}>
        {tab === 'quickstart' ? (
          <ol className="space-y-3">
            {QUICKSTART.map((step, i) => (
              <li key={step.title} className="card flex gap-3 p-4">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-sm font-bold text-brand">{i + 1}</span>
                <div>
                  <p className="text-sm font-semibold">{step.title}</p>
                  <p className="mt-0.5 text-sm leading-relaxed text-muted">{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}
        {tab === 'glossary' ? (
          <div className="space-y-4">
            <Card><CardHeader title={t('help.glossary.pages')} /><CardBody className="!p-0"><Table head={[t('help.cols.zh'), t('help.cols.route'), t('help.cols.code'), t('help.cols.desc')]} rows={GLOSSARY_PAGES} /></CardBody></Card>
            <Card><CardHeader title={t('help.glossary.editor')} /><CardBody className="!p-0"><Table head={[t('help.cols.zh'), t('help.cols.code'), t('help.cols.desc')]} rows={GLOSSARY_EDITOR} /></CardBody></Card>
            <Card><CardHeader title={t('help.glossary.core')} /><CardBody className="!p-0"><Table head={[t('help.cols.zh'), t('help.cols.en'), t('help.cols.def')]} rows={GLOSSARY_CORE} /></CardBody></Card>
            <Card><CardHeader title={t('help.glossary.status')} /><CardBody className="!p-0"><Table head={[t('help.cols.status'), t('help.cols.color'), t('help.cols.desc')]} rows={GLOSSARY_STATUS} /></CardBody></Card>
          </div>
        ) : null}
        {tab === 'ports' ? (
          <Card>
            <CardHeader title={t('help.tabs.ports')} description={t('help.portsHint')} />
            <CardBody className="!p-0">
              <Table
                head={[t('help.cols.type'), t('help.cols.color'), t('help.cols.usage')]}
                rows={PORT_ROWS.map(([type, color, usage]) => [
                  <span key="t" className="inline-flex items-center gap-2 font-mono text-xs">
                    <span className={`inline-block size-3 border-2 border-surface ${type === 'flow' ? 'rotate-45' : 'rounded-full'}`} style={{ background: PORT_HEX[type] }} />
                    {type}
                  </span>,
                  `${color} ${PORT_HEX[type]}`,
                  usage,
                ])}
              />
            </CardBody>
          </Card>
        ) : null}
        {tab === 'tools' ? <ToolsCatalogue /> : null}
        {tab === 'shortcuts' ? (
          <Card><CardBody className="!p-0"><Table head={[t('help.cols.key'), t('help.cols.action')]} rows={SHORTCUTS.map(([k, v]) => [<kbd key="k" className="rounded border border-line bg-surface-muted px-1.5 py-0.5 font-mono text-xs">{k}</kbd>, v])} /></CardBody></Card>
        ) : null}
        {tab === 'automation' ? (
          <div className="space-y-3">
            <Card>
              <CardBody className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted">{t('integration.subtitle')}</p>
                <Link to="/integration"><Button variant="primary" icon={<Plug size={14} />} data-testid="help-goto-integration">{t('integration.title')}</Button></Link>
              </CardBody>
            </Card>
            {AUTOMATION.map((item) => (
              <Card key={item.title}>
                <CardHeader title={item.title} />
                <CardBody><pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-surface-muted p-3 font-mono text-xs leading-relaxed">{item.code}</pre></CardBody>
              </Card>
            ))}
          </div>
        ) : null}
        {tab === 'accounts' ? (
          <Card>
            <CardHeader title={t('help.tabs.accounts')} />
            <CardBody>
              <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed">
                {ACCOUNTS.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </CardBody>
          </Card>
        ) : null}
      </div>
    </Page>
  )
}
