/** 設定：三個分頁依作用範圍分——這台瀏覽器（API 金鑰、顯示）、我的帳號（語言、主題、顯示名稱、密碼）、整站（執行策略、資料保留）；
 * 每張卡片標「作用範圍 · 生效方式」（D8）。整合方（API 金鑰身分）沒有帳號，主題與語言就落在這台瀏覽器。
 * 引擎鎖定由 HTTP／TCP 下指令，狀態顯示在上方橫幅；自動化接口說明在「外部整合」各頁。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Check, KeyRound } from 'lucide-react'

import { ChangePasswordModal } from '@/components/auth/ChangePasswordModal'
import { Page } from '@/components/layout/AppShell'
import { ExecutionPolicyCard } from '@/components/settings/ExecutionPolicyCard'
import { RetentionCard } from '@/components/settings/RetentionCard'
import { ScopeBadge } from '@/components/settings/ScopeBadge'
import { Button, Card, CardBody, CardHeader, DetailRow, PageHeader, Panel, SegmentedControl, Switch, Tabs, TextInput } from '@/components/ui'
import { setLanguage, storedLanguage, type Language } from '@/i18n'
import { api, apiKey, setApiKey } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { readFlowDraftAutoVersion, writeFlowDraftAutoVersion } from '@/lib/localState'
import { normalizeOverlayLimit, readOverlayLimit, writeOverlayLimit } from '@/lib/overlayLimit'
import { useUpdateProfile } from '@/lib/queries'
import { useAuth } from '@/providers/AuthProvider'
import { useTheme, type ThemePreference } from '@/providers/ThemeProvider'
import { useToast } from '@/providers/ToastProvider'

type SettingsTab = 'browser' | 'account' | 'station'
const TABS: SettingsTab[] = ['browser', 'account', 'station']

export function SettingsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const tabParam = params.get('tab')
  const tab: SettingsTab = TABS.includes(tabParam as SettingsTab) ? (tabParam as SettingsTab) : 'browser'
  const selectTab = (next: SettingsTab) => setParams(next === 'browser' ? {} : { tab: next }, { replace: true })
  const toast = useToast()
  const theme = useTheme()
  const client = useQueryClient()
  const auth = useAuth()
  const [key, setKey] = useState(apiKey())
  const [language, setLang] = useState<Language>(storedLanguage())
  const [changing, setChanging] = useState(false)
  const [overlayLimit, setOverlayLimit] = useState(readOverlayLimit)
  const [draftAutoVersion, setDraftAutoVersion] = useState(readFlowDraftAutoVersion)
  const profile = useUpdateProfile()
  const [displayName, setDisplayName] = useState(auth.me?.user?.display_name ?? '')
  const nameDirty = auth.me?.user ? displayName.trim() !== (auth.me.user.display_name ?? '') : false

  async function saveDisplayName() {
    try {
      await profile.mutateAsync({ display_name: displayName.trim() })
      await auth.refresh()
      toast.success(t('settings.displayNameSaved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  function saveKey() {
    setApiKey(key.trim())
    void client.invalidateQueries()
    toast.success(t('settings.saved'))
  }

  // 已登入：主題與語言存在帳號（換裝置跟著走）；整合方只有這台瀏覽器
  const accountScoped = auth.me?.kind === 'user'
  const themeCard = (
        <Panel title={t('settings.theme')} description={<ScopeBadge scope={accountScoped ? 'account' : 'browser'} mode="immediate" />} bodyClassName="space-y-4 p-4" testId="panel-theme">
            {/* 主題風格卡：迷你預覽（底色＋面板＋主色點）；已登入者的選擇會存進使用者設定 */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="theme-picker">
              {([
                { value: 'light', label: t('settings.themeLight'), canvas: '#f7f7f7', surface: '#ffffff', brand: '#1abb9c', text: '#2a3f54' },
                { value: 'dark', label: t('settings.themeDark'), canvas: '#111820', surface: '#1a2431', brand: '#1abb9c', text: '#e4ebf3' },
                { value: 'cyber', label: t('settings.themeCyber'), canvas: '#0a0a0f', surface: '#12121a', brand: '#00ff88', text: '#e0e0e0' },
                { value: 'system', label: t('settings.themeSystem'), canvas: '', surface: '', brand: '', text: '' },
              ] as { value: ThemePreference; label: string; canvas: string; surface: string; brand: string; text: string }[]).map((o) => {
                const active = theme.preference === o.value
                return (
                  <button key={o.value} type="button" onClick={() => theme.setPreference(o.value)} aria-pressed={active}
                    className={`overflow-hidden rounded-lg border text-left transition-all ${active ? 'border-brand ring-2 ring-brand/40' : 'border-line hover:border-brand/50'}`}
                    data-testid={`theme-${o.value}`}>
                    {o.value === 'system' ? (
                      <span className="flex h-14 w-full">
                        <span className="h-full w-1/2 bg-[#f7f7f7] p-1.5"><span className="block h-full rounded border border-black/10 bg-white" /></span>
                        <span className="h-full w-1/2 bg-[#111820] p-1.5"><span className="block h-full rounded border border-white/10 bg-[#1a2431]" /></span>
                      </span>
                    ) : (
                      <span className="block h-14 w-full p-1.5" style={{ background: o.canvas }}>
                        <span className="flex h-full flex-col justify-between rounded border border-black/10 p-1" style={{ background: o.surface }}>
                          <span className="block h-1.5 w-2/3 rounded-full" style={{ background: o.text, opacity: 0.55 }} />
                          <span className="flex items-center gap-1">
                            <span className="size-2.5 rounded-full" style={{ background: o.brand, boxShadow: o.value === 'cyber' ? `0 0 6px ${o.brand}` : undefined }} />
                            <span className="block h-1 w-1/3 rounded-full" style={{ background: o.brand, opacity: 0.7 }} />
                          </span>
                        </span>
                      </span>
                    )}
                    <span className={`block px-2 py-1.5 text-xs font-medium ${active ? 'text-brand' : 'text-content'}`}>{o.label}</span>
                  </button>
                )
              })}
            </div>
            {auth.me?.kind === 'user' ? <p className="text-xs text-subtle">{t('settings.themeSaved')}</p> : null}
            <div>
              <p className="label">{t('settings.language')}</p>
              <SegmentedControl<Language>
                value={language}
                onChange={(v) => {
                  setLang(v)
                  setLanguage(v)
                  // 登入者：存進帳號偏好，換一台電腦登入就是同一種語言（失敗不擋，本機已生效）
                  if (auth.me?.kind === 'user') void api.patch('/auth/prefs', { language: v }).catch(() => {})
                }}
                options={[
                  { value: 'zh-Hant', label: '繁體中文' },
                  { value: 'zh-Hans', label: '简体中文' },
                  { value: 'en', label: 'English' },
                ]}
              />
              {auth.me?.kind === 'user' ? <p className="mt-1 text-xs text-subtle">{t('settings.languageSaved')}</p> : null}
            </div>
        </Panel>
  )

  return (
    <Page>
      <PageHeader title={t('settings.title')} description={t('settings.tabsHint')} />
      <Tabs tabs={TABS.map((value) => ({ value, label: t(`settings.tabs.${value}`) }))} value={tab} onChange={selectTab} className="mb-4" />
      {tab === 'browser' ? (
      <div className="grid gap-4 lg:grid-cols-2" data-testid="settings-tab-browser">
        <Panel title={t('settings.apiKey')} description={<><ScopeBadge scope="browser" mode="save" /><span className="block">{t('settings.apiKeyHint')}</span></>} bodyClassName="flex items-end gap-2 p-4">
            <TextInput className="font-mono" type="password" aria-label="API key" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" />
            <Button variant="primary" onClick={saveKey}>{t('common.save')}</Button>
        </Panel>
        <Panel title={t('settings.display')} description={<><ScopeBadge scope="browser" mode="immediate" /><span className="block">{t('settings.displayHint')}</span></>} bodyClassName="space-y-3 p-4" testId="panel-display">
          <TextInput
            label={t('settings.overlayLimit')}
            hint={t('settings.overlayLimitHint')}
            type="number"
            min={1}
            step={100}
            value={String(overlayLimit)}
            onChange={(e) => setOverlayLimit(writeOverlayLimit(normalizeOverlayLimit(e.target.value)))}
            data-testid="settings-overlay-limit"
          />
          <label className="flex items-center gap-2 text-xs text-muted" title={t('settings.draftAutoVersionHint')} data-testid="settings-draft-auto-version">
            <Switch
              checked={draftAutoVersion}
              onChange={(value) => {
                setDraftAutoVersion(value)
                writeFlowDraftAutoVersion(value)
              }}
              label={t('settings.draftAutoVersion')}
            />
            <span>{t('settings.draftAutoVersion')}</span>
          </label>
        </Panel>
        {accountScoped ? null : themeCard}
      </div>
      ) : null}
      {tab === 'account' ? (
      <div className="grid gap-4 lg:grid-cols-2" data-testid="settings-tab-account">
        {accountScoped ? themeCard : null}
        <Card testId="panel-account">
          <CardHeader title={t('auth.account')} description={<ScopeBadge scope="account" mode="save" />} />
          <CardBody className="space-y-3">
            {auth.me?.user ? (
              <dl>
                <DetailRow label={t('auth.username')}>{auth.me.user.username}</DetailRow>
                <DetailRow label={t('auth.role')}>{t(`auth.roles.${auth.role}`)}</DetailRow>
              </dl>
            ) : null}
            {auth.me?.user ? (
              // 顯示名稱是自己的事，直接在這裡改；帳號名稱與角色仍由管理員在使用者頁管理
              <div className="flex flex-wrap items-end gap-2">
                <TextInput label={t('auth.displayName')} className="w-56" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && nameDirty && void saveDisplayName()} placeholder={auth.me.user.username} data-testid="profile-display-name" />
                <Button variant="primary" icon={<Check size={14} />} disabled={!nameDirty} loading={profile.isPending} onClick={() => void saveDisplayName()} data-testid="profile-save">{t('common.save')}</Button>
              </div>
            ) : (
              <p className="text-xs text-muted">{t('auth.integrator')}</p>
            )}
            {auth.me?.user ? <Button icon={<KeyRound size={14} />} onClick={() => setChanging(true)}>{t('auth.changePassword')}</Button> : null}
            <ChangePasswordModal open={changing} onClose={() => setChanging(false)} />
          </CardBody>
        </Card>
      </div>
      ) : null}
      {tab === 'station' ? (
      <div className="grid gap-4 lg:grid-cols-2" data-testid="settings-tab-station">
        <ExecutionPolicyCard />
        {auth.isAdmin ? <RetentionCard /> : null}
      </div>
      ) : null}
    </Page>
  )
}
