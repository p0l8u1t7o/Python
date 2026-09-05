/**
 * 整合 ▸ 外掛：plugins/ 底下每個檔案的載入結果（掛了什麼、停用、錯在哪）、重新掃描，
 * 以及外掛提供的連線種類的連線管理（外掛沒宣告 section 就歸這一頁）。
 */
import { useTranslation } from 'react-i18next'
import { ExternalLink, Plug, Puzzle, RefreshCw } from 'lucide-react'

import { SectionTabs } from './shared'
import { ConnectionsSection } from '@/components/integration/ConnectionsSection'
import { Badge, Button, Card, CardBody, CardHeader, EmptyRow, ErrorState, LoadingState, TBody, THead, Table, Td, Th, Tr } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { usePlugins, useRescanPlugins } from '@/lib/queries'
import type { PluginInfo } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const TONE: Record<PluginInfo['status'], 'ok' | 'neutral' | 'critical' | 'warning'> = { ok: 'ok', disabled: 'neutral', error: 'critical', empty: 'warning' }

function PluginInventory() {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const plugins = usePlugins()
  const rescan = useRescanPlugins()

  async function onRescan() {
    try {
      const res = await rescan.mutateAsync()
      toast.success(res.mounted?.length ? t('integration.plugins.rescanned', { list: res.mounted.join(', ') }) : t('integration.plugins.nothingNew'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const lines = t('integration.plugins.howtoLines', { returnObjects: true }) as unknown as string[]
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={<span className="flex items-center gap-2"><Puzzle size={16} className="text-brand" />{t('integration.plugins.title')}</span>}
          description={t('integration.plugins.subtitle')}
          actions={
            <span className="flex items-center gap-2">
              <a href={plugins.data?.docs_url ?? '/docs/plugins.html'} target="_blank" rel="noreferrer" className="btn-secondary !h-8 !px-2.5 !text-xs"><ExternalLink size={13} /> {t('integration.plugins.docs')}</a>
              <Button size="sm" icon={<RefreshCw size={14} />} disabled={!auth.isAdmin} title={auth.isAdmin ? undefined : t('integration.plugins.adminOnly')} loading={rescan.isPending} onClick={() => void onRescan()} data-testid="plugins-rescan">{t('integration.plugins.rescan')}</Button>
            </span>
          }
        />
        <CardBody className="space-y-3">
          <p className="text-xs text-muted">{t('integration.plugins.dir')}: <code className="font-mono">{plugins.data?.dir ?? '…'}</code></p>
          <ol className="list-decimal space-y-1 pl-5 text-xs text-muted">{(Array.isArray(lines) ? lines : []).map((l, i) => <li key={i}>{l}</li>)}</ol>
        </CardBody>
      </Card>
      <Card className="overflow-hidden">
        {plugins.isPending ? (
          <LoadingState />
        ) : plugins.isError ? (
          <ErrorState error={plugins.error} onRetry={() => void plugins.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('integration.plugins.cols.file')}</Th>
              <Th>{t('integration.plugins.cols.status')}</Th>
              <Th>{t('integration.plugins.cols.mounted')}</Th>
              <Th className="max-lg:hidden">{t('integration.plugins.cols.detail')}</Th>
            </THead>
            <TBody>
              {plugins.data.items.length === 0 ? (
                <EmptyRow colSpan={4} message={t('integration.plugins.empty')} />
              ) : (
                plugins.data.items.map((p) => (
                  <Tr key={p.name} testId={`plugin-${p.name}`}>
                    <Td>
                      <span className="font-mono text-xs">{p.name}</span>
                      {p.kind === 'package' ? <Badge className="ml-2" tone="neutral">{t('integration.plugins.package')}</Badge> : null}
                    </Td>
                    <Td><Badge tone={TONE[p.status]}>{t(`integration.plugins.status.${p.status}`)}</Badge></Td>
                    <Td>
                      {p.mounted.length ? (
                        <span className="flex flex-wrap gap-1">{p.mounted.map((m) => <code key={m} className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[11px]">{m}</code>)}</span>
                      ) : <span className="text-xs text-subtle">—</span>}
                    </Td>
                    <Td className="max-lg:hidden max-w-md text-xs">
                      {p.error ? <span className="text-critical">{p.error}</span> : p.requirements ? <span className="text-muted">{t('integration.plugins.hasRequirements')}</span> : null}
                    </Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  )
}

export function PluginsPage() {
  const { t } = useTranslation()
  return (
    <SectionTabs section="plugins" tabs={[
      { key: 'inventory', label: t('integration.sections.inventory'), icon: Puzzle, content: <PluginInventory /> },
      { key: 'connections', label: t('integration.sections.connections'), icon: Plug, content: <ConnectionsSection section="plugins" /> },
    ]} />
  )
}
