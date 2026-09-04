/** 整合 ▸ Modbus 輸出：位址格式、對映表與主站／從站說明。 */
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Cable, Plug } from 'lucide-react'

import { CodeBlock } from './shared'
import { TraceLog } from '@/components/integration/TraceLog'
import { Card, CardBody, CardHeader } from '@/components/ui'

function ModbusSection() {
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
  return (
    <div className="grid items-start gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title={<span className="flex items-center gap-2"><Cable size={16} className="text-brand" />{t('integration.modbus.title')}</span>} actions={<Link to="/connections" className="btn-secondary !h-8 !px-2.5 !text-xs" data-testid="modbus-go-connections"><Plug size={13} /> {t('integration.modbus.goConnections')}</Link>} />
        <CardBody className="space-y-3 text-sm leading-relaxed">
          <p>{t('integration.modbus.intro')}</p>
          <div>
            <p className="label">{t('integration.modbus.srcTitle')}</p>
            <ul className="list-disc space-y-1 pl-5 text-xs">{(Array.isArray(lines('integration.modbus.srcLines')) ? lines('integration.modbus.srcLines') : []).map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
          <div>
            <p className="label">{t('integration.modbus.addressTitle')}</p>
            <ul className="list-disc space-y-1 pl-5 text-xs">{(Array.isArray(lines('integration.modbus.addressLines')) ? lines('integration.modbus.addressLines') : []).map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
          <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">{t('integration.modbus.degrade')}</p>
          <p className="text-xs text-muted">{t('integration.modbus.docs')}</p>
        </CardBody>
      </Card>
      <div className="space-y-4">
        <Card>
          <CardHeader title={t('integration.modbus.rolesTitle')} description={t('integration.modbus.rolesHint')} />
          <CardBody className="space-y-3 text-sm leading-relaxed">
            <div className="rounded-lg border border-line p-3">
              <p className="mb-1 font-medium">{t('integration.modbus.clientTitle')}</p>
              <p className="text-xs text-muted">{t('integration.modbus.clientHint')}</p>
            </div>
            <div className="rounded-lg border border-line p-3">
              <p className="mb-1 font-medium">{t('integration.modbus.serverTitle')}</p>
              <p className="text-xs text-muted">{t('integration.modbus.serverHint')}</p>
            </div>
            <div>
              <p className="label">{t('integration.modbus.toolsTitle')}</p>
              <ul className="list-disc space-y-1 pl-5 text-xs">
                {(Array.isArray(lines('integration.modbus.toolLines')) ? lines('integration.modbus.toolLines') : []).map((l, i) => <li key={i}>{l}</li>)}
              </ul>
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


export function ModbusPage() {
  return (
    <div className="space-y-4">
      <ModbusSection />
      <TraceLog channel="modbus" />
    </div>
  )
}
