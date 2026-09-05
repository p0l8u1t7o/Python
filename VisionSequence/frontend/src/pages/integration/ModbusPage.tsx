/**
 * 整合 ▸ Modbus 從站／主站：各自一頁，各管自己那一種連線（建立時不必選種類），共用位址格式與對映表的說明。
 * 從站＝本平台開埠、對方主站來讀寫；主站＝本平台連出去讀寫任何 Modbus TCP 設備。
 */
import { useTranslation } from 'react-i18next'
import { Activity, BookOpen, Cable, Plug, Server } from 'lucide-react'

import { CodeBlock, SectionTabs } from './shared'
import { ConnectionsSection } from '@/components/integration/ConnectionsSection'
import { TraceLog } from '@/components/integration/TraceLog'
import { Card, CardBody, CardHeader } from '@/components/ui'

type Role = 'server' | 'client'

function ModbusGuide({ role }: { role: Role }) {
  const { t } = useTranslation()
  const lines = (key: string) => t(key, { returnObjects: true }) as unknown as string[]
  const example = `[
  {"src": "judge", "address": "coil:0", "dtype": "bool"},
  {"src": "count", "address": "holding:100", "dtype": "int"},
  {"src": "area", "address": "holding:102:float32", "scale": 0.01},
  {"src": "v0", "address": "holding:110", "dtype": "int", "offset": 1},
  {"value": 1, "address": "coil:7"}
]`
  const readExample = `[
  {"name": "recipe", "address": "holding:0"},
  {"name": "trigger", "address": "coil:1"},
  {"name": "temperature", "address": "holding:10:float32", "scale": 0.1}
]`
  const RoleIcon = role === 'server' ? Server : Cable
  return (
    <div className="grid items-start gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title={<span className="flex items-center gap-2"><RoleIcon size={16} className="text-brand" />{t(role === 'server' ? 'integration.modbus.serverTitle' : 'integration.modbus.clientTitle')}</span>} />
        <CardBody className="space-y-3 text-sm leading-relaxed">
          <p>{t(role === 'server' ? 'integration.modbus.serverHint' : 'integration.modbus.clientHint')}</p>
          <p className="text-xs text-muted">{t('integration.modbus.rolesHint')}</p>
          <p>{t('integration.modbus.intro')}</p>
          <div>
            <p className="label">{t('integration.modbus.toolsTitle')}</p>
            <ul className="list-disc space-y-1 pl-5 text-xs">
              {(Array.isArray(lines('integration.modbus.toolLines')) ? lines('integration.modbus.toolLines') : []).map((l, i) => <li key={i}>{l}</li>)}
            </ul>
          </div>
          <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">{t('integration.modbus.degrade')}</p>
          <p className="text-xs text-muted">{t('integration.modbus.docs')}</p>
        </CardBody>
      </Card>
      <div className="space-y-4">
        <Card>
          <CardHeader title={t('integration.modbus.addressTitle')} />
          <CardBody className="space-y-3 text-sm leading-relaxed">
            <div>
              <p className="label">{t('integration.modbus.srcTitle')}</p>
              <ul className="list-disc space-y-1 pl-5 text-xs">{(Array.isArray(lines('integration.modbus.srcLines')) ? lines('integration.modbus.srcLines') : []).map((l, i) => <li key={i}>{l}</li>)}</ul>
            </div>
            <div>
              <p className="label">{t('integration.modbus.addressTitle')}</p>
              <ul className="list-disc space-y-1 pl-5 text-xs">{(Array.isArray(lines('integration.modbus.addressLines')) ? lines('integration.modbus.addressLines') : []).map((l, i) => <li key={i}>{l}</li>)}</ul>
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('integration.modbus.mappingTitle')} description={t('integration.modbus.mappingHint')} />
          <CardBody className="space-y-3">
            <CodeBlock title={t('integration.modbus.example')} code={example} />
            <CodeBlock title={t('integration.modbus.readExample')} code={readExample} />
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

function ModbusRolePage({ role, kind, section }: { role: Role; kind: string; section: string }) {
  const { t } = useTranslation()
  return (
    <SectionTabs section={section} tabs={[
      { key: 'connections', label: t('integration.sections.connections'), icon: Plug, content: <ConnectionsSection section={section} kind={kind} /> },
      { key: 'guide', label: t('integration.sections.guide'), icon: BookOpen, content: <ModbusGuide role={role} /> },
      { key: 'trace', label: t('integration.trace.title'), icon: Activity, content: <TraceLog channel="modbus" /> },
    ]} />
  )
}

/** 從站：本平台開埠，對方（任何 Modbus TCP 主站）來讀寫。 */
export function ModbusServerPage() {
  return <ModbusRolePage role="server" kind="modbus_server" section="modbus-server" />
}

/** 主站：本平台連出去讀寫任何 Modbus TCP 設備。 */
export function ModbusClientPage() {
  return <ModbusRolePage role="client" kind="modbus_tcp" section="modbus-client" />
}
