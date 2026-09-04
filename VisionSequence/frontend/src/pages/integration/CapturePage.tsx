/** 整合 ▸ 擷取端：程式下載、已連線的擷取端與通道；命令與結果在自己的分頁。 */
import { useTranslation } from 'react-i18next'
import { Activity, Monitor } from 'lucide-react'

import { SectionTabs } from './shared'
import { CaptureSection } from '@/components/capture/CaptureSection'
import { TraceLog } from '@/components/integration/TraceLog'

export function IntegrationCapturePage() {
  const { t } = useTranslation()
  return (
    <SectionTabs section="capture" tabs={[
      { key: 'clients', label: t('integration.sections.clients'), icon: Monitor, content: <CaptureSection /> },
      { key: 'trace', label: t('integration.trace.title'), icon: Activity, content: <TraceLog channel="capture" /> },
    ]} />
  )
}
