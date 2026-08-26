import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Cpu, Plug, Wifi, WifiOff } from 'lucide-react'

import { useEdgeNodes } from '@/lib/queries'
import { GatewayManager } from '@/components/devices/GatewayManager'
import { GatewayDetail } from '@/components/devices/GatewayDetail'
import { ConnectionDebugger } from '@/components/devices/ConnectionDebugger'
import { PageHeader, StatTile } from '@/components/ui'

/**
 * Gateway management: the fleet of Sparkplug edge nodes, one selected for a
 * closer look (state, declaration, devices, connection parameters), and the
 * connection debugger for the one that will not come up. The written
 * protocol stays in docs/; this page only shows what is specific to this
 * deployment and this gateway.
 */
export function GatewaysPage() {
  const { t } = useTranslation()
  const nodes = useEdgeNodes({ include_implicit: false })
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const items = useMemo(() => nodes.data?.items ?? [], [nodes.data])
  const selected = useMemo(
    () => items.find((node) => node.id === selectedId) ?? items[0],
    [items, selectedId],
  )
  const online = items.filter((node) => node.status === 'online').length
  const managed = items.reduce((sum, node) => sum + node.device_count, 0)

  return (
    <>
      <PageHeader title={t('gateways.pageTitle')} description={t('gateways.pageHint')} />

      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label={t('gateways.statTotal')} value={items.length} icon={<Plug className="size-4" />} />
        <StatTile label={t('gateways.statOnline')} value={online} accent="ok" icon={<Wifi className="size-4" />} />
        <StatTile
          label={t('gateways.statOffline')}
          value={items.length - online}
          accent={items.length - online > 0 ? 'warning' : 'neutral'}
          icon={<WifiOff className="size-4" />}
        />
        <StatTile label={t('gateways.statDevices')} value={managed} icon={<Cpu className="size-4" />} />
      </div>

      <div className="mb-5">
        <GatewayManager selectedId={selected?.id ?? null} onSelect={setSelectedId} />
      </div>

      {selected ? (
        <div className="mb-5">
          <GatewayDetail node={selected} />
        </div>
      ) : null}

      <ConnectionDebugger nodes={items} initialNode={selected?.node_id} />
    </>
  )
}
