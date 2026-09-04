/** 整合 ▸ 擷取端：程式下載、已連線的擷取端與通道＋命令與結果。 */
import { CaptureSection } from '@/components/capture/CaptureSection'
import { TraceLog } from '@/components/integration/TraceLog'

export function IntegrationCapturePage() {
  return (
    <div className="space-y-4">
      <CaptureSection />
      <TraceLog channel="capture" />
    </div>
  )
}
