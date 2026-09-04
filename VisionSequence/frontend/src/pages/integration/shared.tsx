/** 整合頁共用的小元件：複製按鈕、程式碼區塊、頂部資訊列。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useOutletContext } from 'react-router-dom'
import { Check, Copy } from 'lucide-react'

import { Badge, Button, Card } from '@/components/ui'
import { useIntegrationInfo } from '@/lib/queries'
import { useToast } from '@/providers/ToastProvider'
import type { IntegrationInfo } from '@/lib/types'

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* 退回下面的方式 */
  }
  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(area)
    return ok
  } catch {
    return false
  }
}

export function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const toast = useToast()
  const [done, setDone] = useState(false)
  return (
    <Button
      size="xs"
      icon={done ? <Check size={12} /> : <Copy size={12} />}
      onClick={() => {
        void copyText(text).then((ok) => {
          if (!ok) {
            toast.error(t('errors.generic'))
            return
          }
          setDone(true)
          window.setTimeout(() => setDone(false), 1200)
        })
      }}
    >
      {done ? t('common.copied') : t('common.copy')}
    </Button>
  )
}

export function CodeBlock({ code, title }: { code: string; title?: string }) {
  return (
    <div className="relative">
      {title ? <p className="mb-1 text-xs font-medium text-muted">{title}</p> : null}
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-muted p-3 pr-20 font-mono text-[11px] leading-relaxed">{code}</pre>
      <span className="absolute right-2 top-1"><CopyButton text={code} /></span>
    </div>
  )
}

/** 綁定位址（0.0.0.0＝所有介面）不是外部該填的東西；優先用伺服器算出來的可連位址。 */
export function connectHost(connect: string | undefined, bind: string | undefined, fallback: string): string {
  if (connect) return connect
  return bind && bind !== '0.0.0.0' && bind !== '::' ? bind : fallback
}

export function InfoBar({ info }: { info: IntegrationInfo }) {
  const { t } = useTranslation()
  return (
    <Card className="mb-4 px-4 py-2">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs" data-testid="integration-info">
        <span><span className="text-muted">{t('integration.info.httpBase')}: </span><code className="font-mono">{info.http_base}</code></span>
        <span className="flex items-center gap-1">
          <span className="text-muted">{t('integration.info.tcp')}: </span><code className="font-mono" title={t('integration.info.bound', { host: info.tcp_host })}>{connectHost(info.tcp_connect_host, info.tcp_host, info.host)}:{info.tcp_port}</code>
          <Badge tone={info.tcp_listening ? 'ok' : 'warning'}>{info.tcp_listening ? t('integration.info.listening') : t('integration.info.notListening')}</Badge>
        </span>
        {info.capture_port ? (
          <span className="flex items-center gap-1">
            <span className="text-muted">{t('integration.info.capture')}: </span><code className="font-mono" title={t('integration.info.bound', { host: info.capture_host ?? '' })}>{connectHost(info.capture_connect_host, info.capture_host, info.host)}:{info.capture_port}</code>
            <Badge tone={info.capture_listening ? 'ok' : 'warning'}>{info.capture_listening ? t('integration.info.listening') : t('integration.info.notListening')}</Badge>
          </span>
        ) : null}
        <span><span className="text-muted">{t('integration.info.apiKey')}: </span>{info.api_key_required ? t('integration.info.required') : t('integration.info.optional')}</span>
        <span><span className="text-muted">{t('integration.info.workers')}: </span>{info.max_workers}</span>
        <span><span className="text-muted">{t('integration.info.timeout')}: </span>{info.run_timeout_s}</span>
      </div>
    </Card>
  )
}



/** 整合資訊：在整合外框內由 Outlet 傳下來；單獨 render（測試、直接掛路由）時自己查一次。 */
export function useSectionInfo(): IntegrationInfo | undefined {
  const fromOutlet = useOutletContext<IntegrationInfo | undefined>()
  const query = useIntegrationInfo()
  return fromOutlet ?? query.data
}
