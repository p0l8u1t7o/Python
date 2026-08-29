/** 設定：API 金鑰、主題、語言、引擎鎖定（管理員）、修改密碼、容量資訊、自動化接口說明。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { KeyRound, Lock, Unlock } from 'lucide-react'

import { ChangePasswordModal } from '@/components/auth/ChangePasswordModal'
import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, CardBody, CardHeader, DetailRow, PageHeader, Panel, SegmentedControl, TextInput } from '@/components/ui'
import { setLanguage, storedLanguage, type Language } from '@/i18n'
import { apiKey, setApiKey } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useCapacity, useLockMutations } from '@/lib/queries'
import { isLockHolder, useAuth } from '@/providers/AuthProvider'
import { useTheme, type ThemePreference } from '@/providers/ThemeProvider'
import { useToast } from '@/providers/ToastProvider'

/** 引擎鎖定卡片：狀態＋（管理員）鎖定／解鎖。 */
function EngineLockCard() {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const { acquire, release } = useLockMutations()
  const [reason, setReason] = useState('')
  const [ttl, setTtl] = useState('')
  const lock = auth.lock
  const canUnlock = auth.isAdmin || isLockHolder(auth.me, lock)
  const holder = lock.holder === 'integrator' ? t('lock.integrator') : lock.holder

  async function doLock() {
    try {
      await acquire.mutateAsync({ reason: reason.trim(), ttl_s: ttl.trim() ? Number(ttl) : null })
      toast.success(t('lock.acquired'))
      setReason('')
      setTtl('')
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  async function doUnlock() {
    try {
      await release.mutateAsync()
      toast.success(t('lock.released'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Card>
      <CardHeader title={t('lock.title')} description={t('lock.settingsHint')} />
      <CardBody className="space-y-3">
        <div className="flex items-center gap-2 text-sm" data-testid="lock-status">
          {lock.locked ? <Lock size={15} className="text-warning" /> : <Unlock size={15} className="text-ok" />}
          <Badge tone={lock.locked ? 'warning' : 'ok'}>{lock.locked ? t('lock.locked') : t('lock.unlocked')}</Badge>
          {lock.locked ? (
            <span className="text-xs text-muted">
              {t('lock.holder')}：{holder}
              {lock.reason ? ` · ${lock.reason}` : ''}
              {lock.expires_at ? ` · ${t('lock.expiresAt', { time: new Date(lock.expires_at).toLocaleString() })}` : ''}
            </span>
          ) : null}
        </div>
        {lock.locked ? (
          canUnlock ? (
            <Button variant="primary" icon={<Unlock size={14} />} loading={release.isPending} onClick={() => void doUnlock()}>{t('lock.unlock')}</Button>
          ) : (
            <p className="text-xs text-muted">{t('lock.bannerHint')}</p>
          )
        ) : auth.isAdmin ? (
          <div className="flex flex-wrap items-end gap-2">
            <TextInput label={t('lock.reason')} className="w-56" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t('lock.reasonPlaceholder')} />
            <TextInput label={t('lock.ttl')} type="number" min={0} className="w-28" value={ttl} onChange={(e) => setTtl(e.target.value)} placeholder="∞" />
            <Button variant="primary" icon={<Lock size={14} />} loading={acquire.isPending} onClick={() => void doLock()} data-testid="btn-lock">{t('lock.lock')}</Button>
          </div>
        ) : (
          <p className="text-xs text-muted">{t('lock.adminOnly')}</p>
        )}
      </CardBody>
    </Card>
  )
}

export function SettingsPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const theme = useTheme()
  const client = useQueryClient()
  const capacity = useCapacity()
  const auth = useAuth()
  const [key, setKey] = useState(apiKey())
  const [language, setLang] = useState<Language>(storedLanguage())
  const [changing, setChanging] = useState(false)

  function saveKey() {
    setApiKey(key.trim())
    void client.invalidateQueries()
    toast.success(t('settings.saved'))
  }

  return (
    <Page>
      <PageHeader title={t('settings.title')} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('settings.apiKey')} description={t('settings.apiKeyHint')} />
          <CardBody className="flex items-end gap-2">
            <TextInput className="font-mono" type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" />
            <Button variant="primary" onClick={saveKey}>{t('common.save')}</Button>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('settings.theme')} />
          <CardBody className="space-y-4">
            <SegmentedControl<ThemePreference>
              value={theme.preference}
              onChange={theme.setPreference}
              options={[
                { value: 'light', label: t('settings.themeLight') },
                { value: 'dark', label: t('settings.themeDark') },
                { value: 'system', label: t('settings.themeSystem') },
              ]}
            />
            <div>
              <p className="label">{t('settings.language')}</p>
              <SegmentedControl<Language>
                value={language}
                onChange={(v) => {
                  setLang(v)
                  setLanguage(v)
                }}
                options={[
                  { value: 'zh-Hant', label: '繁體中文' },
                  { value: 'en', label: 'English' },
                ]}
              />
            </div>
          </CardBody>
        </Card>
        <EngineLockCard />
        <Card>
          <CardHeader title={t('auth.account')} />
          <CardBody className="space-y-3">
            {auth.me?.user ? (
              <dl>
                <DetailRow label={t('auth.username')}>{auth.me.user.username}</DetailRow>
                <DetailRow label={t('auth.displayName')}>{auth.me.user.display_name || '—'}</DetailRow>
                <DetailRow label={t('auth.role')}>{auth.isAdmin ? t('auth.admin') : t('auth.user')}</DetailRow>
              </dl>
            ) : (
              <p className="text-xs text-muted">{t('auth.integrator')}</p>
            )}
            {auth.me?.user ? <Button icon={<KeyRound size={14} />} onClick={() => setChanging(true)}>{t('auth.changePassword')}</Button> : null}
            <ChangePasswordModal open={changing} onClose={() => setChanging(false)} />
          </CardBody>
        </Card>
        <Panel title={t('settings.capacity')} description={t('settings.capacityHint')} bodyClassName="p-4" testId="panel-capacity">
          <div>
            {capacity.data ? (
              <dl>
                <DetailRow label="max_workers">{capacity.data.max_workers}</DetailRow>
                <DetailRow label="active">{capacity.data.active}</DetailRow>
                <DetailRow label="images">{capacity.data.images.images} / {Math.round(capacity.data.images.bytes / 1048576)} MB / {capacity.data.images.runs} runs</DetailRow>
                {capacity.data.flows.map((f) => (
                  <DetailRow key={f.flow_id} label={f.flow_name || `#${f.flow_id}`}>
                    {f.running ? t('status.running') : t('status.idle')} · queued {f.queued}{f.continuous ? ` · ${t('dashboard.continuous')}` : ''}
                  </DetailRow>
                ))}
              </dl>
            ) : null}
          </div>
        </Panel>
        <Panel title={t('settings.help')} bodyClassName="p-4" testId="panel-help">
          <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-muted" data-testid="settings-help-text">{t('settings.helpText')}</pre>
        </Panel>
      </div>
    </Page>
  )
}
