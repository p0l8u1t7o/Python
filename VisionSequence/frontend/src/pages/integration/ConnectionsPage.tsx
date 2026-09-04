/** 整合 ▸ 連線：主動輸出的目的地（Modbus 主站／從站、上位機 TCP、模擬 DIO、外掛）＋命令與結果。 */
import { TraceLog } from '@/components/integration/TraceLog'
import { ConnectionsSection } from '@/pages/ConnectionsPage'

export function IntegrationConnectionsPage() {
  return (
    <div className="space-y-4">
      <ConnectionsSection />
      <TraceLog channel="modbus" />
    </div>
  )
}
