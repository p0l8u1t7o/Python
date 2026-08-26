import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Check, Copy } from 'lucide-react'

import { useCapabilities, useDevices } from '@/lib/queries'
import { formatDateTime, formatRelative } from '@/lib/format'
import { useAuth } from '@/providers/AuthProvider'
import type { BirthMetric, EdgeNode } from '@/lib/types'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConnectionBadge,
  DetailRow,
  EmptyRow,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
} from '@/components/ui'

/** Copy-to-clipboard that says whether it worked. */
function CodeBlock({ code, label }: { code: string; label?: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <div className="relative">
      {label ? <p className="mb-1 text-xs text-muted">{label}</p> : null}
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

function metricValue(metric: BirthMetric): string {
  if (metric.value === null || metric.value === undefined) return '—'
  if (typeof metric.value === 'object') return JSON.stringify(metric.value)
  return String(metric.value)
}

function propertiesSummary(properties: Record<string, unknown>): string {
  const entries = Object.entries(properties ?? {})
  if (entries.length === 0) return ''
  return entries.map(([key, value]) => `${key}=${String(value)}`).join('  ')
}

/**
 * Everything the platform knows about one gateway, in three layers: the
 * connection state it acts on, what the gateway itself declared in its
 * NBIRTH (shown verbatim, never interpreted), and the devices reporting
 * through it. The connection parameters live here too, because they are
 * only meaningful once filled in for a concrete gateway.
 */
export function GatewayDetail({ node }: { node: EdgeNode }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const capabilities = useCapabilities()
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

  return (
    <div className="space-y-4" data-testid="gateway-detail">
      <Card>
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
          description={node.description || node.site_name || undefined}
        />
        <CardBody>
          <h3 className="mb-2 text-sm font-medium">{t('gateways.connState')}</h3>
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
            <DetailRow label={t('gateways.lastSeen')}>
              {node.last_seen_at ? `${formatRelative(node.last_seen_at)} · ${formatDateTime(node.last_seen_at)}` : '—'}
            </DetailRow>
            <DetailRow label={t('gateways.statusChanged')}>
              {node.status_changed_at ? formatDateTime(node.status_changed_at) : '—'}
            </DetailRow>
            <DetailRow label={t('gateways.birthAt')}>
              {node.birth_at ? formatDateTime(node.birth_at) : '—'}
            </DetailRow>
            <DetailRow label={t('gateways.site')}>{node.site_name ?? '—'}</DetailRow>
            <DetailRow label={t('gateways.bdSeq')}>
              <span className="font-mono">{node.bd_seq ?? '—'}</span>
            </DetailRow>
            <DetailRow label={t('gateways.lastSeq')}>
              <span className="font-mono">{node.last_seq ?? '—'}</span>
            </DetailRow>
            <DetailRow label={t('gateways.ip')}>
              <span className="font-mono">{node.ip_address ?? '—'}</span>
            </DetailRow>
            <DetailRow label={t('gateways.rssi')}>
              <span className="font-mono">{node.rssi !== null ? `${node.rssi} dBm` : '—'}</span>
            </DetailRow>
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t('gateways.declared')} description={t('gateways.declaredHint')} />
        <CardBody className="space-y-3">
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
            <DetailRow label={t('gateways.firmware')}>{node.firmware_version || '—'}</DetailRow>
            <DetailRow label={t('gateways.hardware')}>{node.hardware_version || '—'}</DetailRow>
            <DetailRow label={t('gateways.bdSeq')}>
              <span className="font-mono">{node.bd_seq ?? '—'}</span>
            </DetailRow>
            <DetailRow label={t('gateways.birthAt')}>
              {node.birth_at ? formatDateTime(node.birth_at) : '—'}
            </DetailRow>
          </dl>
          {node.birth_metrics.length === 0 ? (
            <p className="text-sm text-muted">{t('gateways.noBirth')}</p>
          ) : (
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
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={`${t('gateways.managedDevices')} · ${items.length}`}
          description={t('gateways.managedHint')}
        />
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
      </Card>

      <Card>
        <CardHeader title={t('gateways.params')} description={t('gateways.paramsHint')} />
        <CardBody className="space-y-4">
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-xs text-muted">{t('gateways.namespace')}</dt>
              <dd className="font-mono text-sm">{namespace}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">{t('gateways.groupId')}</dt>
              <dd className="font-mono text-sm">{groupId}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">{t('gateways.hostId')}</dt>
              <dd className="font-mono text-sm">{hostId}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">{t('gateways.liveIngest')}</dt>
              <dd className="text-sm">
                <Badge tone={capabilities.data?.mqtt_enabled ? 'ok' : 'neutral'}>
                  {capabilities.data?.mqtt_enabled ? t('common.enabled') : t('common.disabled')}
                </Badge>
              </dd>
            </div>
          </dl>
          <CodeBlock
            code={`${t('gateways.clientId')}   zqs:${node.node_id}
${t('gateways.username')}  node-${groupId}-${node.node_id}
Password    ${t('gateways.passwordOnce')}
Clean session true    MQTT 3.1.1    Keepalive 45`}
          />
          <div className="space-y-1.5">
            <p className="text-xs text-muted">{t('gateways.topics')}</p>
            {topics.map(([kind, topic]) => (
              <div key={kind} className="flex items-baseline gap-2">
                <Badge>{kind}</Badge>
                <code className="min-w-0 flex-1 break-all font-mono text-xs">{topic}</code>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted">{t('gateways.docsHint')}</p>
        </CardBody>
      </Card>
    </div>
  )
}
