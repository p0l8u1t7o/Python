/**
 * 整合頁的外框（`/integration/*`）：標題、整合資訊列，內容由子路由決定——
 * 每一種整合方式都是自己的頁面（pages/integration/*），側欄的樹狀選單直接連過去。
 * 舊網址 `/integration?tab=modbus` 會轉到 `/integration/modbus`。
 */
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Plug } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { PageHeader } from '@/components/ui'
import { useIntegrationInfo } from '@/lib/queries'
import { InfoBar } from '@/pages/integration/shared'
import { DEFAULT_SECTION, SECTIONS, SECTION_IDS, sectionOf } from '@/pages/integration/sections'

export function IntegrationLayout() {
  const { t } = useTranslation()
  const info = useIntegrationInfo()
  const location = useLocation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const section = sectionOf(location.pathname)
  //: 標題的 i18n key 是 sections.ts 的 key（modbusServer），不是路由片段（modbus-server）
  const sectionKey = SECTIONS.find((x) => x.id === section)?.key ?? section

  // 舊網址相容：/integration?tab=modbus → /integration/modbus
  useEffect(() => {
    const tab = params.get('tab')
    if (tab && SECTION_IDS.includes(tab)) navigate(`/integration/${tab}`, { replace: true })
  }, [params, navigate])

  return (
    <Page wide>
      <PageHeader
        title={<span className="flex items-center gap-2"><Plug size={20} className="text-brand" />{t('integration.title')} · {t(`integration.tabs.${sectionKey}`)}</span>}
        description={t(`integration.desc.${section}`, { defaultValue: t('integration.subtitle') })}
      />
      {info.data ? <InfoBar info={info.data} /> : null}
      <div data-testid={`integration-${section}`}>
        <Outlet context={info.data} />
      </div>
    </Page>
  )
}

/** `/integration` 本身沒有內容，導到第一個整合方式。 */
export function IntegrationIndex() {
  return <Navigate to={`/integration/${DEFAULT_SECTION}`} replace />
}
