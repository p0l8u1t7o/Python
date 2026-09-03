/** 使用者管理（管理員）：列表、新增、改角色／啟用、重設密碼、刪除。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate } from 'react-router-dom'
import { KeyRound, Plus, Shield, Trash2, Users } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, Checkbox, ConfirmDialog, EmptyRow, ErrorState, IconButton, LoadingState, Modal, PageHeader, Switch, TBody, THead, Table, Td, TextInput, Th, Tr } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useUserMutations, useUsers, type UserPatch } from '@/lib/queries'
import type { AuthUser } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

const EMPTY_FORM = { username: '', password: '', display_name: '', is_staff: false }

export function UsersPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const users = useUsers(auth.isAdmin)
  const { create, patch, remove } = useUserMutations()
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [resetTarget, setResetTarget] = useState<AuthUser | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [pendingDelete, setPendingDelete] = useState<AuthUser | null>(null)
  const [pendingRole, setPendingRole] = useState<{ user: AuthUser; is_staff: boolean } | null>(null)
  const [pendingActive, setPendingActive] = useState<{ user: AuthUser; is_active: boolean } | null>(null)

  if (!auth.isAdmin) return <Navigate to="/" replace />
  const myId = auth.me?.user?.id

  async function onCreate() {
    if (!form.username.trim() || !form.password) return toast.error(t('auth.required'))
    if (form.password.length < 6) return toast.error(t('auth.weakPassword'))
    try {
      await create.mutateAsync({ ...form, username: form.username.trim() })
      toast.success(t('users.created'))
      setCreating(false)
      setForm(EMPTY_FORM)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function onPatch(id: number, body: UserPatch, done: string) {
    try {
      await patch.mutateAsync({ id, ...body })
      toast.success(done)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function onResetPassword() {
    if (!resetTarget) return
    if (resetPassword.length < 6) return toast.error(t('auth.weakPassword'))
    await onPatch(resetTarget.id, { password: resetPassword }, t('users.passwordReset'))
    setResetTarget(null)
    setResetPassword('')
  }

  async function onDelete() {
    if (!pendingDelete) return
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('users.deleted'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setPendingDelete(null)
    }
  }

  return (
    <Page>
      <PageHeader
        title={t('users.title')}
        description={t('users.subtitle')}
        actions={
          <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>
            {t('users.create')}
          </Button>
        }
      />
      <Card className="overflow-hidden">
        {users.isPending ? (
          <LoadingState />
        ) : users.isError ? (
          <ErrorState error={users.error} onRetry={() => void users.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('auth.username')}</Th>
              <Th className="max-sm:hidden">{t('auth.displayName')}</Th>
              <Th align="center">{t('users.admin')}</Th>
              <Th align="center">{t('common.enabled')}</Th>
              <Th className="max-md:hidden">{t('users.lastLogin')}</Th>
              <Th align="right">{t('common.actions')}</Th>
            </THead>
            <TBody>
              {users.data.items.length === 0 ? (
                <EmptyRow colSpan={6} message={<span className="inline-flex items-center gap-2"><Users className="size-5" />{t('users.empty')}</span>} />
              ) : (
                users.data.items.map((user) => {
                  const self = user.id === myId
                  return (
                    <Tr key={user.id}>
                      <Td>
                        <span className="font-medium">{user.username}</span>
                        {self ? <Badge tone="brand" className="ml-2">{t('users.you')}</Badge> : null}
                      </Td>
                      <Td className="max-sm:hidden text-muted">{user.display_name || '—'}</Td>
                      <Td align="center">
                        <Switch checked={user.is_staff} disabled={self} label={t('users.admin')} onChange={(v) => setPendingRole({ user, is_staff: v })} />
                      </Td>
                      <Td align="center">
                        <Switch checked={user.is_active} disabled={self} label={t('common.enabled')} onChange={(v) => setPendingActive({ user, is_active: v })} />
                      </Td>
                      <Td className="tnum max-md:hidden text-xs text-muted">{user.last_login ? new Date(user.last_login).toLocaleString() : '—'}</Td>
                      <Td align="right">
                        <span className="inline-flex max-w-32 flex-wrap justify-end gap-1 sm:max-w-none">
                          <IconButton label={t('users.resetPassword')} onClick={() => setResetTarget(user)}><KeyRound size={15} /></IconButton>
                          <IconButton label={t('common.delete')} disabled={self} onClick={() => setPendingDelete(user)}><Trash2 size={15} className="text-critical" /></IconButton>
                        </span>
                      </Td>
                    </Tr>
                  )
                })
              )}
            </TBody>
          </Table>
        )}
      </Card>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title={t('users.createTitle')}
        size="sm"
        dirty={Boolean(form.username || form.password)}
        footer={
          <>
            <Button onClick={() => setCreating(false)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={create.isPending} onClick={() => void onCreate()}>{t('common.create')}</Button>
          </>
        }
      >
        <div className="space-y-3">
          <TextInput label={t('auth.username')} required autoFocus autoComplete="off" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <TextInput label={t('auth.password')} required type="password" autoComplete="new-password" hint={t('auth.passwordHint')} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <TextInput label={t('auth.displayName')} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          <Checkbox label={<span className="inline-flex items-center gap-1"><Shield size={13} />{t('users.admin')}</span>} hint={t('users.adminHint')} checked={form.is_staff} onChange={(v) => setForm({ ...form, is_staff: v })} />
        </div>
      </Modal>

      <Modal
        open={resetTarget !== null}
        onClose={() => setResetTarget(null)}
        title={t('users.resetPasswordTitle', { name: resetTarget?.username ?? '' })}
        size="sm"
        footer={
          <>
            <Button onClick={() => setResetTarget(null)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={patch.isPending} onClick={() => void onResetPassword()}>{t('common.save')}</Button>
          </>
        }
      >
        <TextInput label={t('auth.newPassword')} type="password" autoFocus autoComplete="new-password" hint={t('users.resetPasswordHint')} value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void onResetPassword()} />
      </Modal>

      <ConfirmDialog
        open={pendingRole !== null}
        onClose={() => setPendingRole(null)}
        onConfirm={() => {
          if (!pendingRole) return
          void onPatch(pendingRole.user.id, { is_staff: pendingRole.is_staff }, t('users.updated'))
          setPendingRole(null)
        }}
        title={t('users.roleTitle')}
        message={t(pendingRole?.is_staff ? 'users.promoteMessage' : 'users.demoteMessage', { name: pendingRole?.user.username ?? '' })}
        confirmLabel={t('common.confirm')}
        loading={patch.isPending}
      />
      <ConfirmDialog
        open={pendingActive !== null}
        onClose={() => setPendingActive(null)}
        onConfirm={() => {
          if (!pendingActive) return
          void onPatch(pendingActive.user.id, { is_active: pendingActive.is_active }, t('users.updated'))
          setPendingActive(null)
        }}
        title={t('users.activeTitle')}
        message={t(pendingActive?.is_active ? 'users.enableMessage' : 'users.disableMessage', { name: pendingActive?.user.username ?? '' })}
        confirmLabel={t('common.confirm')}
        danger={pendingActive ? !pendingActive.is_active : false}
        loading={patch.isPending}
      />
      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void onDelete()} title={t('users.deleteTitle')} message={t('users.deleteMessage', { name: pendingDelete?.username ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </Page>
  )
}
