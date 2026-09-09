/**
 * 整合 ▸ 設備連線：串口、UDP 與本機 TCP 文字伺服器。頁面只放連線清單與通訊追蹤。
 */
import { ConnectionsSection } from '@/components/integration/ConnectionsSection'
import { TraceLog } from '@/components/integration/TraceLog'

export function DevicesPage() {
  return (
    <div className="space-y-4">
      <ConnectionsSection section="devices" />
      <TraceLog channel="modbus" />
    </div>
  )
}
