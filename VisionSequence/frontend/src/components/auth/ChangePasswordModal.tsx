/** 修改自己的密碼（AppShell 底部與設定頁共用）。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Modal, TextInput } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useChangePassword } from '@/lib/queries'
import { useToast } from '@/providers/ToastProvider'

export function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const change = useChangePassword()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')

  function reset() {
    setOldPassword('')
    setNewPassword('')
    setConfirm('')
    setError('')
  }

  async function submit() {
    if (!oldPassword || !newPassword) return setError(t('auth.required'))
    if (newPassword.length < 6) return setError(t('auth.weakPassword'))
    if (newPassword !== confirm) return setError(t('auth.passwordMismatch'))
    try {
      await change.mutateAsync({ old_password: oldPassword, new_password: newPassword })
      toast.success(t('auth.passwordChanged'))
      reset()
      onClose()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        reset()
        onClose()
      }}
      title={t('auth.changePassword')}
      size="sm"
      dirty={Boolean(oldPassword || newPassword)}
      footer={(close) => (
        <>
          <Button onClick={close}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={change.isPending} onClick={() => void submit()}>{t('common.save')}</Button>
        </>
      )}
    >
      <div className="space-y-3">
        <TextInput label={t('auth.oldPassword')} type="password" autoFocus autoComplete="current-password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} />
        <TextInput label={t('auth.newPassword')} type="password" autoComplete="new-password" hint={t('auth.passwordHint')} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
        <TextInput label={t('auth.confirmPassword')} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void submit()} />
        {error ? <p className="text-xs text-critical" role="alert">{error}</p> : null}
      </div>
    </Modal>
  )
}
