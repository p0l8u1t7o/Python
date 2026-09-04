/** 整合 ▸ 引擎鎖定：整合方鎖住硬體時，其他人只能編輯不能執行。 */
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { CodeBlock, useSectionInfo } from './shared'
import { Badge, Card, CardBody, CardHeader, DetailRow, LoadingState } from '@/components/ui'
import { useAuth } from '@/providers/AuthProvider'
import type { IntegrationInfo } from '@/lib/types'

function LockSection({ info }: { info: IntegrationInfo }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const lock = auth.lock
  const base = info.http_base
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader title={t('integration.lockTab.current')} description={t('integration.lockTab.hint')} />
        <CardBody className="space-y-3">
          <dl>
            <DetailRow label={t('lock.title')}><Badge tone={lock.locked ? 'warning' : 'ok'}>{lock.locked ? t('lock.locked') : t('lock.unlocked')}</Badge></DetailRow>
            {lock.locked ? (
              <>
                <DetailRow label={t('lock.holder')}>{lock.holder === 'integrator' ? t('lock.integrator') : lock.holder}</DetailRow>
                <DetailRow label={t('lock.reason')}>{lock.reason || t('lock.noReason')}</DetailRow>
                <DetailRow label={t('lock.ttl')}>{lock.expires_at ? new Date(lock.expires_at).toLocaleString() : '∞'}</DetailRow>
              </>
            ) : null}
          </dl>
          <Link to="/settings" className="text-xs text-brand hover:underline">{t('integration.lockTab.goSettings')}</Link>
        </CardBody>
      </Card>
      <Card>
        <CardBody className="space-y-3">
          <CodeBlock title={t('integration.lockTab.lockExample')} code={`curl -X POST "${base}/vision/lock" \\\n  -H "X-API-Key: <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '{"reason": "camera calibration", "ttl_s": 600}'`} />
          <CodeBlock title={t('integration.lockTab.unlockExample')} code={`curl -X DELETE "${base}/vision/lock" -H "X-API-Key: <YOUR_API_KEY>"`} />
          <CodeBlock title={t('integration.lockTab.statusExample')} code={`curl "${base}/vision/lock" -H "X-API-Key: <YOUR_API_KEY>"\n# → {"locked": true, "holder": "integrator", "reason": "...", "locked_at": "...", "expires_at": "..."}`} />
        </CardBody>
      </Card>
    </div>
  )
}


export function LockPage() {
  const info = useSectionInfo()
  if (!info) return <LoadingState />
  return (
    <div className="space-y-4">
      <LockSection info={info} />
      
    </div>
  )
}
