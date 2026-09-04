/**
 * 角色權限（管理員）：勾選工程師與操作員各能用哪些功能。
 * 管理員那一欄是固定打勾且不可點——沒有人能把自己鎖在外面。
 * 真正的把關在伺服器（accounts/permissions.py＋require_feature），這裡只是設定畫面。
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ShieldCheck } from 'lucide-react'

import { Button, Card, CardBody, CardHeader, Checkbox, ErrorState, LoadingState } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useRolePermissionMutation, useRolePermissions } from '@/lib/queries'
import type { Feature } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

export function RolePermissionsCard() {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const query = useRolePermissions(auth.isAdmin)
  const save = useRolePermissionMutation()
  const [draft, setDraft] = useState<Record<string, Feature[]> | null>(null)

  const data = query.data
  useEffect(() => {
    if (data) setDraft(data.matrix)
  }, [data])

  const dirty = useMemo(() => {
    if (!data || !draft) return false
    return data.roles.some((role) => (data.matrix[role] ?? []).join() !== (draft[role] ?? []).join())
  }, [data, draft])

  function toggle(role: string, feature: Feature, on: boolean) {
    setDraft((prev) => {
      if (!prev) return prev
      const current = new Set(prev[role] ?? [])
      if (on) current.add(feature)
      else current.delete(feature)
      // 順序照後端的功能清單，比較 dirty 時才穩定
      const ordered = (data?.features ?? []).map((f) => f.key).filter((k) => current.has(k))
      return { ...prev, [role]: ordered }
    })
  }

  async function onSave() {
    if (!data || !draft) return
    try {
      for (const role of data.roles) {
        if ((data.matrix[role] ?? []).join() !== (draft[role] ?? []).join()) {
          await save.mutateAsync({ role, features: draft[role] ?? [] })
        }
      }
      await auth.refresh()  // 改到自己這個角色時，側欄要立刻跟著變
      toast.success(t('permissions.saved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  if (!auth.isAdmin) return null
  return (
    <Card className="mt-4" testId="role-permissions">
      <CardHeader
        title={<span className="flex items-center gap-2"><ShieldCheck size={16} className="text-brand" />{t('permissions.title')}</span>}
        description={t('permissions.subtitle')}
        actions={<Button variant="primary" size="sm" icon={<Check size={14} />} disabled={!dirty} loading={save.isPending} onClick={() => void onSave()} data-testid="permissions-save">{t('common.save')}</Button>}
      />
      <CardBody className="!p-0">
        {query.isPending ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : data && draft ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="table-header">{t('permissions.feature')}</th>
                  <th className="table-header text-center">{t('auth.roles.admin')}</th>
                  {data.roles.map((role) => <th key={role} className="table-header text-center">{t(`auth.roles.${role}`)}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.features.map((f) => (
                  <tr key={f.key} data-testid={`permission-${f.key}`}>
                    <td className="table-cell">
                      <span className="font-medium">{t(`permissions.features.${f.key}`)}</span>
                      <span className="ml-2 font-mono text-[11px] text-subtle">{f.key}</span>
                    </td>
                    <td className="table-cell text-center" title={t('permissions.adminAlways')}>
                      <Check size={15} className="mx-auto text-ok" aria-label={t('permissions.adminAlways')} />
                    </td>
                    {data.roles.map((role) => (
                      <td key={role} className="table-cell text-center">
                        <span className="inline-flex justify-center">
                          <Checkbox
                            label={<span className="sr-only">{`${t(`auth.roles.${role}`)} · ${t(`permissions.features.${f.key}`)}`}</span>}
                            checked={(draft[role] ?? []).includes(f.key)}
                            onChange={(v) => toggle(role, f.key, v)}
                          />
                        </span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="px-4 py-3 text-xs text-muted">{t('permissions.hint')}</p>
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}
