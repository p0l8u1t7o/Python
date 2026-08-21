import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, KeyRound, Monitor, Moon, Plus, Sun, Trash2 } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useTheme } from '@/providers/ThemeProvider'
import { useToast } from '@/providers/ToastProvider'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  EmptyRow,
  IconButton,
  Modal,
  PageHeader,
  SegmentedControl,
  Select,
  TBody,
  THead,
  Table,
  Td,
  Term,
  TextInput,
  Th,
  Tr,
} from '@/components/ui'
import {
  useApiKeyMutations,
  useApiKeys,
  useCapabilities,
  useChangePassword,
  useHealth,
  useMemberMutations,
  useMembers,
  useUpdateProfile,
} from '@/lib/queries'
import { errorMessage } from '@/lib/errors'
import { formatRelative } from '@/lib/format'
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES, applyLanguage, currentLanguage } from '@/i18n'
import type { SupportedLanguage } from '@/i18n'
import type { ApiKeyCreated, Role, ThemePreference } from '@/lib/types'

const ROLES: Role[] = ['viewer', 'operator', 'admin', 'owner']

export function SettingsPage() {
  const { t } = useTranslation()
  const { me, can } = useAuth()

  return (
    <>
      <PageHeader title={t('settings.title')} />

      <div className="grid gap-5 lg:grid-cols-2">
        <AppearanceCard />
        <ProfileCard />
        <PasswordCard />
        <PlatformCard />
        {can('member:manage') ? (
          <div className="lg:col-span-2">
            <MembersCard />
          </div>
        ) : null}
        {can('apikey:manage') ? (
          <div className="lg:col-span-2">
            <ApiKeysCard />
          </div>
        ) : null}
      </div>

      {me ? (
        <p className="mt-6 text-xs text-subtle">
          {t('settings.organization')}: {me.organization.name} ({me.organization.slug}) ·{' '}
          {t(`role.${me.role}`)}
        </p>
      ) : null}
    </>
  )
}

function AppearanceCard() {
  const { t } = useTranslation()
  const { preference, setPreference } = useTheme()
  const { savePreferences, me } = useAuth()
  const toast = useToast()
  const [timezone, setTimezone] = useState(me?.user.timezone_name ?? 'UTC')

  async function persist(patch: Parameters<typeof savePreferences>[0]) {
    try {
      await savePreferences(patch)
      toast.success(t('common.saved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Card>
      <CardHeader title={t('settings.appearance')} description={t('settings.appearanceHint')} />
      <CardBody className="space-y-4">
        <div>
          <span className="label">{t('theme.label')}</span>
          <SegmentedControl<ThemePreference>
            value={preference}
            onChange={(value) => {
              setPreference(value)
              void persist({ theme: value })
            }}
            options={[
              {
                value: 'system',
                label: (
                  <span className="flex items-center gap-1.5">
                    <Monitor className="size-3.5" />
                    {t('theme.system')}
                  </span>
                ),
              },
              {
                value: 'light',
                label: (
                  <span className="flex items-center gap-1.5">
                    <Sun className="size-3.5" />
                    {t('theme.light')}
                  </span>
                ),
              },
              {
                value: 'dark',
                label: (
                  <span className="flex items-center gap-1.5">
                    <Moon className="size-3.5" />
                    {t('theme.dark')}
                  </span>
                ),
              },
            ]}
          />
        </div>

        <div>
          <span className="label">{t('language.label')}</span>
          <SegmentedControl<SupportedLanguage>
            value={currentLanguage()}
            onChange={(value) => {
              applyLanguage(value)
              void persist({ language: value })
            }}
            options={SUPPORTED_LANGUAGES.map((code) => ({
              value: code,
              label: LANGUAGE_LABELS[code],
            }))}
          />
        </div>

        <div className="flex items-end gap-2">
          <TextInput
            label={t('settings.timezone')}
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
            placeholder="Asia/Taipei"
            className="flex-1"
          />
          <Button onClick={() => void persist({ timezone_name: timezone })}>
            {t('common.save')}
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

function ProfileCard() {
  const { t } = useTranslation()
  const { me, reload } = useAuth()
  const toast = useToast()
  const update = useUpdateProfile()
  const [form, setForm] = useState({ full_name: '', phone: '' })

  useEffect(() => {
    if (me) setForm({ full_name: me.user.full_name, phone: me.user.phone })
  }, [me])

  return (
    <Card>
      <CardHeader title={t('settings.profile')} description={me?.user.email} />
      <CardBody className="space-y-4">
        <TextInput
          label={t('settings.fullName')}
          value={form.full_name}
          onChange={(event) => setForm({ ...form, full_name: event.target.value })}
        />
        <TextInput
          label={t('settings.phone')}
          value={form.phone}
          onChange={(event) => setForm({ ...form, phone: event.target.value })}
        />
        <Button
          variant="primary"
          loading={update.isPending}
          onClick={async () => {
            try {
              await update.mutateAsync(form)
              await reload()
              toast.success(t('common.saved'))
            } catch (error) {
              toast.error(errorMessage(error))
            }
          }}
        >
          {t('common.save')}
        </Button>
      </CardBody>
    </Card>
  )
}

function PasswordCard() {
  const { t } = useTranslation()
  const toast = useToast()
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')

  return (
    <Card>
      <CardHeader title={t('settings.security')} />
      <CardBody className="space-y-4">
        <TextInput
          label={t('auth.currentPassword')}
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />
        <TextInput
          label={t('auth.newPassword')}
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
        <Button
          variant="primary"
          loading={change.isPending}
          disabled={!current || next.length < 10}
          onClick={async () => {
            try {
              await change.mutateAsync({ current_password: current, new_password: next })
              setCurrent('')
              setNext('')
              toast.success(t('auth.passwordChanged'))
            } catch (error) {
              toast.error(errorMessage(error))
            }
          }}
        >
          {t('auth.changePassword')}
        </Button>
      </CardBody>
    </Card>
  )
}

function PlatformCard() {
  const { t } = useTranslation()
  const capabilities = useCapabilities()
  const health = useHealth()

  return (
    <Card>
      <CardHeader title={t('settings.platform')} />
      <CardBody>
        <dl className="space-y-2 text-sm">
          {capabilities.data ? (
            <>
              <Row
                label={<Term id="mqtt">MQTT topic root</Term>}
                value={capabilities.data.mqtt_topic_root}
                mono
              />
              <Row label={<Term id="ingestor">Message bus</Term>} value={capabilities.data.bus_backend} />
              <Row label="Database" value={capabilities.data.database_engine} />
              <Row
                label="Offline grace"
                value={`${capabilities.data.device_offline_grace_seconds}s`}
              />
            </>
          ) : null}
          {health.data ? <Row label="API version" value={health.data.version} /> : null}
        </dl>
      </CardBody>
    </Card>
  )
}

function Row({
  label,
  value,
  mono = false,
}: {
  label: ReactNode
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`text-right ${mono ? 'font-mono text-xs' : ''}`}>{value}</dd>
    </div>
  )
}

function MembersCard() {
  const { t } = useTranslation()
  const toast = useToast()
  const { me } = useAuth()
  const members = useMembers()
  const { add, setRole, remove } = useMemberMutations()

  const [showAdd, setShowAdd] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setNewRole] = useState<Role>('viewer')
  const [removing, setRemoving] = useState<{ id: string; email: string } | null>(null)

  return (
    <Card>
      <CardHeader
        title={t('settings.members')}
        actions={
          <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setShowAdd(true)}>
            {t('settings.addMember')}
          </Button>
        }
      />
      <Table>
        <THead>
          <Th>{t('auth.email')}</Th>
          <Th>{t('settings.fullName')}</Th>
          <Th>{t('settings.memberRole')}</Th>
          <Th align="right">{t('settings.joined')}</Th>
          <Th />
        </THead>
        <TBody>
          {members.isPending ? (
            <EmptyRow colSpan={5} message={`${t('common.loading')}…`} />
          ) : (
            members.data?.items.map((member) => (
              <Tr key={member.user.id}>
                <Td className="font-medium">{member.user.email}</Td>
                <Td className="text-muted">{member.user.full_name || '—'}</Td>
                <Td>
                  <Select
                    value={member.role}
                    disabled={member.user.id === me?.user.id}
                    onChange={async (event) => {
                      try {
                        await setRole.mutateAsync({
                          userId: member.user.id,
                          role: event.target.value,
                        })
                        toast.success(t('common.saved'))
                      } catch (error) {
                        toast.error(errorMessage(error))
                      }
                    }}
                    options={ROLES.map((value) => ({ value, label: t(`role.${value}`) }))}
                    className="w-36"
                  />
                </Td>
                <Td align="right" className="text-muted">
                  {formatRelative(member.created_at)}
                </Td>
                <Td align="right">
                  {member.user.id !== me?.user.id ? (
                    <IconButton
                      label={t('common.remove')}
                      onClick={() => setRemoving({ id: member.user.id, email: member.user.email })}
                    >
                      <Trash2 className="size-3.5" />
                    </IconButton>
                  ) : null}
                </Td>
              </Tr>
            ))
          )}
        </TBody>
      </Table>

      <Modal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        title={t('settings.addMember')}
        description={t('settings.addMemberHint')}
        size="sm"
        footer={
          <>
            <Button onClick={() => setShowAdd(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              loading={add.isPending}
              disabled={!email}
              onClick={async () => {
                try {
                  await add.mutateAsync({ email: email.trim(), role })
                  setEmail('')
                  setShowAdd(false)
                } catch (error) {
                  toast.error(errorMessage(error))
                }
              }}
            >
              {t('common.add')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <TextInput
            label={t('auth.email')}
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <Select
            label={t('settings.memberRole')}
            value={role}
            onChange={(event) => setNewRole(event.target.value as Role)}
            options={ROLES.map((value) => ({ value, label: t(`role.${value}`) }))}
          />
        </div>
      </Modal>

      <ConfirmDialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        danger
        loading={remove.isPending}
        title={t('common.remove')}
        confirmLabel={t('common.remove')}
        message={t('settings.removeMemberConfirm', { email: removing?.email ?? '' })}
        onConfirm={async () => {
          if (!removing) return
          try {
            await remove.mutateAsync(removing.id)
            setRemoving(null)
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />
    </Card>
  )
}

function ApiKeysCard() {
  const { t } = useTranslation()
  const toast = useToast()
  const keys = useApiKeys()
  const { create, revoke } = useApiKeyMutations()

  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [role, setRole] = useState<Role>('viewer')
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [revoking, setRevoking] = useState<{ id: string; name: string } | null>(null)

  return (
    <Card>
      <CardHeader
        title={t('settings.apiKeys')}
        description={t('settings.apiKeysHint')}
        actions={
          <Button size="sm" icon={<KeyRound className="size-3.5" />} onClick={() => setShowCreate(true)}>
            {t('settings.createApiKey')}
          </Button>
        }
      />
      <Table>
        <THead>
          <Th>{t('common.name')}</Th>
          <Th>Prefix</Th>
          <Th>{t('settings.memberRole')}</Th>
          <Th>{t('common.status')}</Th>
          <Th align="right">{t('settings.lastUsed')}</Th>
          <Th />
        </THead>
        <TBody>
          {keys.isPending ? (
            <EmptyRow colSpan={6} message={`${t('common.loading')}…`} />
          ) : keys.data && keys.data.items.length > 0 ? (
            keys.data.items.map((key) => (
              <Tr key={key.id}>
                <Td className="font-medium">{key.name}</Td>
                <Td className="font-mono text-xs text-muted">{key.prefix}</Td>
                <Td className="text-muted">{t(`role.${key.role}`)}</Td>
                <Td>
                  <Badge tone={key.is_active ? 'ok' : 'neutral'}>
                    {key.is_active ? t('common.enabled') : t('common.disabled')}
                  </Badge>
                </Td>
                <Td align="right" className="text-muted">
                  {key.last_used_at ? formatRelative(key.last_used_at) : t('common.never')}
                </Td>
                <Td align="right">
                  {key.is_active ? (
                    <IconButton
                      label={t('settings.revokeApiKey')}
                      onClick={() => setRevoking({ id: key.id, name: key.name })}
                    >
                      <Trash2 className="size-3.5" />
                    </IconButton>
                  ) : null}
                </Td>
              </Tr>
            ))
          ) : (
            <EmptyRow colSpan={6} message={t('common.none')} />
          )}
        </TBody>
      </Table>

      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title={t('settings.createApiKey')}
        size="sm"
        footer={
          <>
            <Button onClick={() => setShowCreate(false)}>{t('common.cancel')}</Button>
            <Button
              variant="primary"
              loading={create.isPending}
              disabled={!name}
              onClick={async () => {
                try {
                  const result = await create.mutateAsync({ name: name.trim(), role })
                  setCreated(result)
                  setName('')
                  setShowCreate(false)
                } catch (error) {
                  toast.error(errorMessage(error))
                }
              }}
            >
              {t('common.create')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <TextInput
            label={t('common.name')}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="BI export"
          />
          <Select
            label={t('settings.memberRole')}
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
            options={ROLES.filter((value) => value !== 'owner').map((value) => ({
              value,
              label: t(`role.${value}`),
            }))}
          />
        </div>
      </Modal>

      <Modal
        open={created !== null}
        onClose={() => setCreated(null)}
        title={t('settings.apiKeyCreated')}
        description={t('settings.apiKeySecretWarning')}
        footer={
          <Button variant="primary" onClick={() => setCreated(null)}>
            {t('common.close')}
          </Button>
        }
      >
        {created ? (
          <div className="flex items-center gap-2 rounded-lg bg-surface-muted p-2.5">
            <code className="min-w-0 flex-1 break-all font-mono text-xs">{created.secret}</code>
            <Button
              size="sm"
              icon={<Copy className="size-3.5" />}
              onClick={async () => {
                await navigator.clipboard.writeText(created.secret)
                toast.success(t('common.copied'))
              }}
              aria-label={t('common.copy')}
            />
          </div>
        ) : null}
      </Modal>

      <ConfirmDialog
        open={revoking !== null}
        onClose={() => setRevoking(null)}
        danger
        loading={revoke.isPending}
        title={t('settings.revokeApiKey')}
        confirmLabel={t('settings.revokeApiKey')}
        message={t('settings.revokeConfirm', { name: revoking?.name ?? '' })}
        onConfirm={async () => {
          if (!revoking) return
          try {
            await revoke.mutateAsync(revoking.id)
            setRevoking(null)
          } catch (error) {
            toast.error(errorMessage(error))
          }
        }}
      />
    </Card>
  )
}
