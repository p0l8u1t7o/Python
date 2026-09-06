/**
 * 流程變數卡：這條流程與整站目前存的值（累計、上一片、料號），有 flows.teach 的人可以直接改或清掉。
 * 值會即時落地（API 是 write-through），所以換線改料號按下去就生效。
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, RefreshCw, Trash2 } from 'lucide-react'
import { Button, IconButton, TextInput } from '@/components/ui'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useFlowVariables } from '@/lib/queries'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

type Scope = 'flow' | 'station'

function show(value: unknown): string {
  if (value && typeof value === 'object' && (value as { image?: boolean }).image) {
    const v = value as { width: number; height: number }
    return `image ${v.width}x${v.height}`
  }
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

/** 輸入框裡打的字：數字就是數字、true/false 是布林、JSON 物件照 JSON，其餘是字串（跟 TCP SET 同一套規則）。 */
function parse(text: string): unknown {
  const s = text.trim()
  if (s === '') return ''
  if (/^-?\d+$/.test(s)) return Number(s)
  if (/^-?\d*\.\d+$/.test(s) || /^-?\d+\.\d*$/.test(s)) return Number(s)
  if (s === 'true' || s === 'false') return s === 'true'
  if ((s.startsWith('{') && s.endsWith('}')) || (s.startsWith('[') && s.endsWith(']'))) {
    try {
      return JSON.parse(s)
    } catch {
      return s
    }
  }
  return s
}

export function VariablesCard({ flowId }: { flowId: number }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const vars = useFlowVariables(flowId)
  const canEdit = auth.can('flows.teach')
  const [scope, setScope] = useState<Scope>('flow')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [newName, setNewName] = useState('')
  const [newValue, setNewValue] = useState('')
  const [busy, setBusy] = useState(false)

  const items = (scope === 'flow' ? vars.data?.items : vars.data?.station) ?? {}
  const base = scope === 'flow' ? `/vision/flows/${flowId}/variables` : '/vision/variables'

  async function save(name: string, text: string) {
    setBusy(true)
    try {
      await api.put(base, { values: { [name]: parse(text) } })
      setDrafts((d) => {
        const next = { ...d }
        delete next[name]
        return next
      })
      await vars.refetch()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(name: string) {
    setBusy(true)
    try {
      await api.delete(`${base}/${encodeURIComponent(name)}`)
      await vars.refetch()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2" data-testid="variables-card">
      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-1 rounded-md border border-line p-0.5 text-xs">
          {(['flow', 'station'] as Scope[]).map((s) => (
            <button key={s} type="button" className={`rounded px-2 py-0.5 ${scope === s ? 'bg-brand text-on-brand' : 'text-muted hover:text-content'}`} onClick={() => setScope(s)} data-testid={`variables-scope-${s}`}>
              {t(`variables.scope.${s}`)}
            </button>
          ))}
        </div>
        <IconButton label={t('common.refresh')} size="sm" onClick={() => void vars.refetch()}><RefreshCw size={13} /></IconButton>
      </div>
      <p className="text-[11px] text-subtle">{t('variables.hint')}</p>
      {Object.keys(items).length === 0 ? (
        <p className="text-xs text-subtle" data-testid="variables-empty">{t('variables.empty')}</p>
      ) : (
        <table className="w-full text-xs">
          <tbody>
            {Object.entries(items).map(([name, value]) => {
              const draft = drafts[name]
              const isImage = Boolean(value && typeof value === 'object' && (value as { image?: boolean }).image)
              return (
                <tr key={name} className="border-t border-line" data-testid={`variable-${name}`}>
                  <td className="py-1 pr-2 font-mono">{name}</td>
                  <td className="py-1">
                    {canEdit && !isImage ? (
                      <TextInput
                        value={draft ?? show(value)}
                        onChange={(e) => setDrafts((d) => ({ ...d, [name]: e.target.value }))}
                        onBlur={() => { if (draft !== undefined && draft !== show(value)) void save(name, draft) }}
                        onKeyDown={(e) => { if (e.key === 'Enter' && draft !== undefined) void save(name, draft) }}
                        data-testid={`variable-value-${name}`}
                      />
                    ) : (
                      <span className="tnum" title={show(value)}>{show(value)}</span>
                    )}
                  </td>
                  <td className="py-1 pl-1 text-right">
                    {canEdit ? <IconButton label={t('common.delete')} size="sm" onClick={() => void remove(name)}><Trash2 size={12} /></IconButton> : null}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {canEdit ? (
        <div className="flex items-end gap-1.5">
          <TextInput label={t('variables.name')} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="lot" data-testid="variable-new-name" />
          <TextInput label={t('variables.value')} value={newValue} onChange={(e) => setNewValue(e.target.value)} placeholder="A17" data-testid="variable-new-value" />
          <Button size="sm" icon={<Plus size={13} />} loading={busy} disabled={!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(newName)} onClick={() => { void save(newName, newValue); setNewName(''); setNewValue('') }} data-testid="variable-add">
            {t('variables.add')}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
