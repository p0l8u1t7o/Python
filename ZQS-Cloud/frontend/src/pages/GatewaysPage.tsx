import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Cpu, Plug, Wifi, WifiOff } from 'lucide-react'

import { useEdgeNodes } from '@/lib/queries'
import { GatewayManager } from '@/components/devices/GatewayManager'
import { GatewayDetail } from '@/components/devices/GatewayDetail'
import { PageHeader } from '@/components/ui'

/**
 * Gateway management: the fleet of Sparkplug edge nodes on the left, the
 * selected one on the right in tabs (state and declaration, devices,
 * connection parameters, debugger). Side by side on wide screens so the
 * operator does not scroll past the list to see what they clicked. The
 * written protocol stays in docs/; this page only shows what is specific
 * to this deployment and this gateway.
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

  const stats = [
    { label: t('gateways.statTotal'), value: items.length, icon: Plug, tone: 'text-content' },
    { label: t('gateways.statOnline'), value: online, icon: Wifi, tone: 'text-ok' },
    {
      label: t('gateways.statOffline'),
      value: items.length - online,
      icon: WifiOff,
      tone: items.length - online > 0 ? 'text-warning' : 'text-content',
    },
    { label: t('gateways.statDevices'), value: managed, icon: Cpu, tone: 'text-content' },
  ]

  return (
    <>
      <PageHeader
        title={t('gateways.pageTitle')}
        description={t('gateways.pageHint')}
        actions={
          <div className="flex flex-wrap gap-2" data-testid="gateway-stats">
            {stats.map((stat) => (
              <div
                key={stat.label}
                className="flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5"
              >
                <stat.icon className="size-3.5 text-muted" aria-hidden />
                <span className="text-xs text-muted">{stat.label}</span>
                <span className={`text-sm font-semibold tnum ${stat.tone}`}>{stat.value}</span>
              </div>
            ))}
          </div>
        }
      />

      <div className="grid gap-4 xl:grid-cols-12">
        <div className="xl:col-span-5">
          <GatewayManager selectedId={selected?.id ?? null} onSelect={setSelectedId} compact />
        </div>
        <div className="xl:col-span-7">
          {selected ? <GatewayDetail node={selected} nodes={items} /> : null}
        </div>
      </div>
    </>
  )
}
