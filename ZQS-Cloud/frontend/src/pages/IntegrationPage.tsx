import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Copy } from 'lucide-react'

import { useCapabilities, useEdgeNodes } from '@/lib/queries'
import { GatewayManager } from '@/components/devices/GatewayManager'
import { useAuth } from '@/providers/AuthProvider'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  PageHeader,
  Select,
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
          // Clipboard access fails on an insecure origin and when the user has
          // denied it. Falling back to "select it yourself" beats a button
          // that silently does nothing.
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

function Step({
  index,
  title,
  children,
}: {
  index: number
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">
        {index}
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <h3 className="text-sm font-medium">{title}</h3>
        <div className="space-y-2 text-sm text-muted">{children}</div>
      </div>
    </div>
  )
}

/**
 * How to get a device talking to this deployment.
 *
 * Aimed at the device vendor, not the operator, and it exists because the
 * written protocol cannot know *this* deployment's group id, host id or node
 * names. A vendor reading the spec still has to ask somebody for those four
 * strings; this page just shows them, filled into the topics they belong in.
 *
 * It is a starting point, not the contract. Every section points at
 * docs/device-protocol.md for the parts that must not be paraphrased.
 */
export function IntegrationPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const capabilities = useCapabilities()
  const nodes = useEdgeNodes({ include_implicit: true })

  const groupId = me?.organization.slug ?? 'your-group'
  const namespace = capabilities.data?.sparkplug_namespace ?? 'spBv1.0'
  const hostId = capabilities.data?.sparkplug_host_id ?? 'zqs-cloud'

  // Real gateways first. An implicit node exists only to hold one directly
  // connected device's session, so it is a valid integration target but a poor
  // default - the vendor almost always wants the gateway they were told about.
  const nodeOptions = useMemo(() => {
    const items = [...(nodes.data?.items ?? [])]
    items.sort((a, b) => Number(a.is_implicit) - Number(b.is_implicit))
    return items
  }, [nodes.data])

  const [nodeId, setNodeId] = useState('')
  const node = useMemo(
    () => nodeOptions.find((item) => item.node_id === nodeId) ?? nodeOptions[0],
    [nodeOptions, nodeId],
  )
  const exampleNode = node?.node_id ?? 'YOUR-GATEWAY'
  const exampleDevice = 'YOUR-DEVICE'

  const topics = [
    ['NBIRTH', `${namespace}/${groupId}/NBIRTH/${exampleNode}`, t('integration.topicNbirth')],
    ['NDEATH', `${namespace}/${groupId}/NDEATH/${exampleNode}`, t('integration.topicNdeath')],
    [
      'DBIRTH',
      `${namespace}/${groupId}/DBIRTH/${exampleNode}/${exampleDevice}`,
      t('integration.topicDbirth'),
    ],
    [
      'DDATA',
      `${namespace}/${groupId}/DDATA/${exampleNode}/${exampleDevice}`,
      t('integration.topicDdata'),
    ],
    ['NCMD', `${namespace}/${groupId}/NCMD/${exampleNode}`, t('integration.topicNcmd')],
    [
      'DCMD',
      `${namespace}/${groupId}/DCMD/${exampleNode}/${exampleDevice}`,
      t('integration.topicDcmd'),
    ],
  ] as const

  return (
    <>
      <PageHeader
        title={t('integration.title')}
        description={t('integration.subtitle')}
      />

      <div className="mb-5">
        <GatewayManager />
      </div>

      <div className="space-y-4">
        <Card>
          <CardHeader
            title={t('integration.thisDeployment')}
            description={t('integration.thisDeploymentHint')}
          />
          <CardBody>
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-xs text-muted">{t('integration.namespace')}</dt>
                <dd className="font-mono text-sm">{namespace}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t('integration.groupId')}</dt>
                <dd className="font-mono text-sm">{groupId}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t('integration.hostId')}</dt>
                <dd className="font-mono text-sm">{hostId}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t('integration.liveIngest')}</dt>
                <dd className="text-sm">
                  <Badge tone={capabilities.data?.mqtt_enabled ? 'ok' : 'neutral'}>
                    {capabilities.data?.mqtt_enabled
                      ? t('common.enabled')
                      : t('common.disabled')}
                  </Badge>
                </dd>
              </div>
            </dl>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title={t('integration.stepsTitle')}
            description={t('integration.stepsHint')}
            actions={
              nodeOptions.length > 0 ? (
                <Select
                  value={node?.node_id ?? ''}
                  onChange={(event) => setNodeId(event.target.value)}
                  options={nodeOptions.map((item) => ({
                    value: item.node_id,
                    label: item.name || item.node_id,
                  }))}
                  className="w-56"
                />
              ) : undefined
            }
          />
          <CardBody className="space-y-6">
            <Step index={1} title={t('integration.step1')}>
              <p>{t('integration.step1Body')}</p>
              <CodeBlock
                code={`Client ID     zqs:${exampleNode}
Username      node-${groupId}-${exampleNode}
Password      ${t('integration.passwordOnce')}
Clean session true
Keepalive     45`}
              />
            </Step>

            <Step index={2} title={t('integration.step2')}>
              <p>{t('integration.step2Body')}</p>
              <CodeBlock
                code={`topic   ${namespace}/${groupId}/NDEATH/${exampleNode}
qos     1
retain  false
payload  bdSeq = <${t('integration.thisConnection')}>`}
              />
            </Step>

            <Step index={3} title={t('integration.step3')}>
              <p>{t('integration.step3Body')}</p>
              <CodeBlock
                code={`${namespace}/${groupId}/NCMD/${exampleNode}
${namespace}/${groupId}/DCMD/${exampleNode}/+`}
              />
            </Step>

            <Step index={4} title={t('integration.step4')}>
              <p>{t('integration.step4Body')}</p>
              <CodeBlock
                code={`NBIRTH  seq=0
  bdSeq               Int64    <${t('integration.sameAsWill')}>
  Node Control/Rebirth Boolean false

DBIRTH  seq=1
  battery_soc     Double  alias=1  properties{ unit: "%" }
  battery_power_w Double  alias=2  properties{ unit: "W" }
  Properties/Category  String  "battery"`}
              />
              <p className="text-xs">{t('integration.step4Note')}</p>
            </Step>

            <Step index={5} title={t('integration.step5')}>
              <p>{t('integration.step5Body')}</p>
              <CodeBlock
                code={`DDATA  seq=2
  alias=1  78.5
  alias=2  -125000`}
              />
            </Step>

            <Step index={6} title={t('integration.step6')}>
              <p>{t('integration.step6Body')}</p>
              <CodeBlock
                code={`${t('integration.received')}  DCMD
  Command/ID       String  "0f9d7a1c-…"
  Command/Name     String  "set_power_limit"
  Command/limit_w  Int64   400000

${t('integration.reply')}  DDATA
  Command/ID      String  "0f9d7a1c-…"
  Command/Status  String  "succeeded"`}
              />
            </Step>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title={t('integration.topicsTitle')}
            description={t('integration.topicsHint')}
          />
          <CardBody className="space-y-2">
            {topics.map(([kind, topic, note]) => (
              <div key={kind} className="border-b border-line pb-2 last:border-0">
                <div className="flex items-baseline gap-2">
                  <Badge>{kind}</Badge>
                  <code className="min-w-0 flex-1 break-all font-mono text-xs">{topic}</code>
                </div>
                <p className="mt-1 text-xs text-muted">{note}</p>
              </div>
            ))}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title={t('integration.verifyTitle')}
            description={t('integration.verifyHint')}
          />
          <CardBody className="space-y-3">
            <CodeBlock
              label={t('integration.verifySelfTest')}
              code="python scripts/run_device_test.py self-test"
            />
            <CodeBlock
              label={t('integration.verifyDevice')}
              code={`python scripts/run_device_test.py device --device ${exampleDevice}`}
            />
            <p className="text-sm text-muted">{t('integration.verifyBody')}</p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t('integration.specTitle')} />
          <CardBody className="space-y-2 text-sm text-muted">
            <p>{t('integration.specBody')}</p>
            <ul className="list-inside list-disc space-y-1">
              <li>
                <code className="font-mono text-xs">docs/device-protocol.md</code> —{' '}
                {t('integration.specProtocol')}
              </li>
              <li>
                <code className="font-mono text-xs">docs/device-test-harness.md</code> —{' '}
                {t('integration.specHarness')}
              </li>
              <li>
                <code className="font-mono text-xs">
                  services/sparkplug/sparkplug_b.proto
                </code>{' '}
                — {t('integration.specProto')}
              </li>
            </ul>
          </CardBody>
        </Card>
      </div>
    </>
  )
}
