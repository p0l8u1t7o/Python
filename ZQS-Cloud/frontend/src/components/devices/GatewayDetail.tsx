import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Activity, Bug, Check, Copy, Cpu, KeyRound } from 'lucide-react'

import { useCapabilities, useDevices } from '@/lib/queries'
import { formatDateTime, formatRelative } from '@/lib/format'
import { useAuth } from '@/providers/AuthProvider'
import type { BirthMetric, EdgeNode } from '@/lib/types'
import { ConnectionDebugger } from '@/components/devices/ConnectionDebugger'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConnectionBadge,
  EmptyRow,
  Table,
  Tabs,
  TBody,
  Td,
  Th,
  THead,
  Tr,
} from '@/components/ui'

type DetailTab = 'status' | 'devices' | 'params' | 'debug'

/** Copy-to-clipboard that says whether it worked. */
function CodeBlock({ code }: { code: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-md border border-line bg-[#0b1220] p-3 pr-12 text-xs leading-relaxed text-[#7dd3fc] selection:bg-[#1e3a5f]">
        {code}
      </pre>
      <Button
        className="absolute right-2 top-2"
        onClick={() => {
          // Clipboard access fails on an insecure origin; a button that
          // silently does nothing is worse than one that shows no tick.
          void navigator.clipboard
            ?.writeText(code)
            .then(() => {
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            })
            .catch(() => setCopied(false))
        }}
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        <span className="sr-only">{t('common.copy')}</span>
      </Button>
    </div>
  )
}

/** Compact label/value cell for the dense state grid. */
function Fact({ label, children, mono = false }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted">{label}</dt>
      <dd className={`truncate text-sm ${mono ? 'font-mono text-xs' : ''}`}>{children}</dd>
    </div>
  )
}

function metricValue(metric: BirthMetric): string {
  if (metric.value === null || metric.value === undefined) return '—'
  if (typeof metric.value === 'object') return JSON.stringify(metric.value)
  return String(metric.value)
}

function propertiesSummary(properties: Record<string, unknown>): string {
  return Object.entries(properties ?? {})
    .map(([key, value]) => `${key}=${String(value)}`)
    .join('  ')
}

/**
 * Everything the platform knows about one gateway, in tabs so the page
 * stays one screen tall: the connection state it acts on together with
 * what the gateway itself declared in its NBIRTH (verbatim, never
 * interpreted), the devices reporting through it, the strings a device
 * needs to connect, and the debugger for when it will not.
 */
export function GatewayDetail({ node, nodes }: { node: EdgeNode; nodes: EdgeNode[] }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const capabilities = useCapabilities()
  const [tab, setTab] = useState<DetailTab>('status')
  const devices = useDevices({ edge_node_id: node.id, limit: 200 })

  const groupId = node.group_id || me?.organization.slug || 'your-group'
  const namespace = capabilities.data?.sparkplug_namespace ?? 'spBv1.0'
  const hostId = capabilities.data?.sparkplug_host_id ?? 'zqs-cloud'
  const topics = [
    ['NBIRTH', `${namespace}/${groupId}/NBIRTH/${node.node_id}`],
    ['NDEATH', `${namespace}/${groupId}/NDEATH/${node.node_id}`],
    ['DBIRTH', `${namespace}/${groupId}/DBIRTH/${node.node_id}/<device_id>`],
    ['DDATA', `${namespace}/${groupId}/DDATA/${node.node_id}/<device_id>`],
    ['NCMD', `${namespace}/${groupId}/NCMD/${node.node_id}`],
    ['DCMD', `${namespace}/${groupId}/DCMD/${node.node_id}/+`],
  ] as const
  const items = devices.data?.items ?? []

  const tabs = [
    { value: 'status' as const, label: t('gateways.tabStatus'), icon: Activity },
    { value: 'devices' as const, label: `${t('gateways.tabDevices')} · ${node.device_count}`, icon: Cpu },
    { value: 'params' as const, label: t('gateways.tabParams'), icon: KeyRound },
    { value: 'debug' as const, label: t('gateways.tabDebug'), icon: Bug },
  ]

  return (
    <Card>
      <div data-testid="gateway-detail">
        <CardHeader
          title={
            <span className="flex flex-wrap items-center gap-2">
              <span>{node.name || node.node_id}</span>
              <code className="font-mono text-xs text-muted">{node.node_id}</code>
              <ConnectionBadge status={node.status} />
              {!node.is_enabled ? <Badge tone="neutral">{t('common.disabled')}</Badge> : null}
              {node.rebirth_requested_at ? <Badge tone="warning">{t('gateways.rebirthPending')}</Badge> : null}
            </span>
          }
          description={[node.site_name, node.description].filter(Boolean).join(' · ') || undefined}
        />
        <Tabs tabs={tabs} value={tab} onChange={setTab} className="px-4" />

        {tab === 'status' ? (
          <CardBody className="space-y-4">
            <section>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">{t('gateways.connState')}</h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
                <Fact label={t('gateways.lastSeen')}>
                  {node.last_seen_at ? formatRelative(node.last_seen_at) : '—'}
                </Fact>
                <Fact label={t('gateways.statusChanged')}>
                  {node.status_changed_at ? formatDateTime(node.status_changed_at) : '—'}
                </Fact>
                <Fact label={t('gateways.birthAt')}>{node.birth_at ? formatDateTime(node.birth_at) : '—'}</Fact>
                <Fact label={t('gateways.site')}>{node.site_name ?? '—'}</Fact>
                <Fact label={t('gateways.bdSeq')} mono>{node.bd_seq ?? '—'}</Fact>
                <Fact label={t('gateways.lastSeq')} mono>{node.last_seq ?? '—'}</Fact>
                <Fact label={t('gateways.ip')} mono>{node.ip_address ?? '—'}</Fact>
                <Fact label={t('gateways.rssi')} mono>{node.rssi !== null ? `${node.rssi} dBm` : '—'}</Fact>
              </dl>
            </section>

            <section>
              <h3 className="mb-0.5 text-xs font-medium uppercase tracking-wide text-muted">{t('gateways.declared')}</h3>
              <p className="mb-2 text-xs text-muted">{t('gateways.declaredHint')}</p>
              <dl className="mb-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
                <Fact label={t('gateways.firmware')}>{node.firmware_version || '—'}</Fact>
                <Fact label={t('gateways.hardware')}>{node.hardware_version || '—'}</Fact>
                <Fact label={t('gateways.metric')} mono>{node.birth_metrics.length}</Fact>
              </dl>
              {node.birth_metrics.length === 0 ? (
                <p className="text-sm text-muted">{t('gateways.noBirth')}</p>
              ) : (
                <div className="max-h-72 overflow-y-auto rounded-md border border-line">
                  <Table>
                    <THead>
                      <Th>{t('gateways.metric')}</Th>
                      <Th align="right">{t('gateways.alias')}</Th>
                      <Th>{t('gateways.datatype')}</Th>
                      <Th>{t('gateways.value')}</Th>
                      <Th>{t('gateways.properties')}</Th>
                    </THead>
                    <TBody>
                      {node.birth_metrics.map((metric, index) => (
                        <Tr key={`${metric.name}-${index}`}>
                          <Td className="font-mono text-xs">{metric.name || '—'}</Td>
                          <Td align="right" className="font-mono text-xs tnum">{metric.alias ?? '—'}</Td>
                          <Td className="text-xs">{metric.datatype}</Td>
                          <Td className="font-mono text-xs">{metricValue(metric)}</Td>
                          <Td className="font-mono text-xs text-muted">{propertiesSummary(metric.properties)}</Td>
                        </Tr>
                      ))}
                    </TBody>
                  </Table>
                </div>
              )}
            </section>
          </CardBody>
        ) : null}

        {tab === 'devices' ? (
          <div>
            <p className="px-4 pt-3 text-xs text-muted">{t('gateways.managedHint')}</p>
            <Table>
              <THead>
                <Th>{t('gateways.deviceId')}</Th>
                <Th>{t('common.name')}</Th>
                <Th>{t('gateways.category')}</Th>
                <Th>{t('common.status')}</Th>
                <Th>{t('gateways.lastSeen')}</Th>
              </THead>
              <TBody>
                {items.length === 0 ? (
                  <EmptyRow colSpan={5} message={t('gateways.noDevices')} />
                ) : (
                  items.map((device) => (
                    <Tr key={device.id}>
                      <Td className="font-mono text-xs">
                        <Link to={`/devices/${device.id}`} className="text-brand hover:underline">
                          {device.device_id}
                        </Link>
                      </Td>
                      <Td className="font-medium">{device.name}</Td>
                      <Td className="text-muted">{device.device_category || '—'}</Td>
                      <Td><ConnectionBadge status={device.status} /></Td>
                      <Td className="text-muted">{device.last_seen_at ? formatRelative(device.last_seen_at) : '—'}</Td>
                    </Tr>
                  ))
                )}
              </TBody>
            </Table>
          </div>
        ) : null}

        {tab === 'params' ? (
          <CardBody className="space-y-3">
            <p className="text-xs text-muted">{t('gateways.paramsHint')}</p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
              <Fact label={t('gateways.namespace')} mono>{namespace}</Fact>
              <Fact label={t('gateways.groupId')} mono>{groupId}</Fact>
              <Fact label={t('gateways.hostId')} mono>{hostId}</Fact>
              <Fact label={t('gateways.liveIngest')}>
                <Badge tone={capabilities.data?.mqtt_enabled ? 'ok' : 'neutral'}>
                  {capabilities.data?.mqtt_enabled ? t('common.enabled') : t('common.disabled')}
                </Badge>
              </Fact>
            </dl>
            <CodeBlock
              code={`${t('gateways.clientId')}   zqs:${node.node_id}
${t('gateways.username')}  node-${groupId}-${node.node_id}
Password    ${t('gateways.passwordOnce')}
Clean session true    MQTT 3.1.1    Keepalive 45`}
            />
            <div className="space-y-1">
              <p className="text-[11px] text-muted">{t('gateways.topics')}</p>
              {topics.map(([kind, topic]) => (
                <div key={kind} className="flex items-baseline gap-2">
                  <Badge>{kind}</Badge>
                  <code className="min-w-0 flex-1 break-all font-mono text-xs">{topic}</code>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted">{t('gateways.docsHint')}</p>
          </CardBody>
        ) : null}

        {tab === 'debug' ? (
          <CardBody>
            <ConnectionDebugger nodes={nodes} initialNode={node.node_id} embedded />
          </CardBody>
        ) : null}
      </div>
    </Card>
  )
}
