/** 群組管理 Modal（影像來源庫／資產庫共用）：群組清單（含項目數）、新增、改名、刪除。
 *  刪除時提示是否連同群組下的資源一併刪；不連刪則所屬資源變為未分組。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react'

import { Button, Modal, TextInput } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useGroupMutations, useGroups, type ResourceGroup } from '@/lib/queries'
import { useToast } from '@/providers/ToastProvider'

export function GroupManager({ kind, open, onClose }: { kind: 'source' | 'asset'; open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const groups = useGroups(kind, open)
  const { createGroup, renameGroup, removeGroup } = useGroupMutations(kind)
  const [name, setName] = useState('')
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null)
  const [deleting, setDeleting] = useState<ResourceGroup | null>(null)

  async function run(action: Promise<unknown>, done?: () => void) {
    try {
      await action
      done?.()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <>
      <Modal open={open} onClose={onClose} title={t('groups.manage')} description={t('groups.manageHint')}>
        <div className="space-y-2">
          {(groups.data ?? []).map((g) => (
            <div key={g.id} className="flex items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-sm" data-testid={`group-row-${g.name}`}>
              {renaming?.id === g.id ? (
                <>
                  <TextInput autoFocus value={renaming.name} onChange={(e) => setRenaming({ ...renaming, name: e.target.value })}
                    onKeyDown={(e) => { if (e.key === 'Enter') void run(renameGroup.mutateAsync({ id: g.id, name: renaming.name.trim() }), () => setRenaming(null)) }} />
                  <Button size="xs" variant="primary" loading={renameGroup.isPending} disabled={!renaming.name.trim()}
                    onClick={() => void run(renameGroup.mutateAsync({ id: g.id, name: renaming.name.trim() }), () => setRenaming(null))}><Check size={13} /></Button>
                  <Button size="xs" onClick={() => setRenaming(null)}><X size={13} /></Button>
                </>
              ) : (
                <>
                  <span className="min-w-0 flex-1 truncate font-medium">{g.name}</span>
                  <span className="tnum shrink-0 text-xs text-muted">{t('groups.itemCount', { count: g.count })}</span>
                  <button type="button" className="btn-icon" title={t('groups.rename')} onClick={() => setRenaming({ id: g.id, name: g.name })}><Pencil size={14} /></button>
                  <button type="button" className="btn-icon" title={t('common.delete')} onClick={() => setDeleting(g)}><Trash2 size={14} className="text-critical" /></button>
                </>
              )}
            </div>
          ))}
          {groups.data && !groups.data.length ? <p className="text-xs text-subtle">{t('groups.empty')}</p> : null}
          <div className="flex items-end gap-2 pt-1">
            <TextInput label={t('groups.newName')} value={name} onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) void run(createGroup.mutateAsync(name.trim()), () => setName('')) }} data-testid="group-new" />
            <Button variant="primary" loading={createGroup.isPending} disabled={!name.trim()}
              onClick={() => void run(createGroup.mutateAsync(name.trim()), () => setName(''))}><Plus size={14} /> {t('common.create')}</Button>
          </div>
        </div>
      </Modal>

      {/* 刪除：三個選擇——取消／保留資源（變未分組）／連同資源一併刪除 */}
      <Modal open={deleting !== null} onClose={() => setDeleting(null)} title={t('groups.deleteTitle', { name: deleting?.name ?? '' })}
        footer={
          <>
            <Button onClick={() => setDeleting(null)}>{t('common.cancel')}</Button>
            <Button loading={removeGroup.isPending}
              onClick={() => { if (deleting) void run(removeGroup.mutateAsync({ id: deleting.id, deleteItems: false }), () => setDeleting(null)) }}
              data-testid="group-del-keep">{t('groups.deleteKeep')}</Button>
            <Button variant="danger" loading={removeGroup.isPending}
              onClick={() => { if (deleting) void run(removeGroup.mutateAsync({ id: deleting.id, deleteItems: true }), () => setDeleting(null)) }}
              data-testid="group-del-all">{t('groups.deleteWithItems', { count: deleting?.count ?? 0 })}</Button>
          </>
        }>
        <p className="text-sm text-muted">{t('groups.deleteMessage', { count: deleting?.count ?? 0 })}</p>
      </Modal>
    </>
  )
}
