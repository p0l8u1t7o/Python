import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import type { AssistantWorkState, EngineeringNote } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

export function DecisionNotes({ decisions, flowId }: { decisions: AssistantWorkState['decisions']; flowId: number | null }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const client = useQueryClient()
  const [pending, setPending] = useState(false)
  const [saved, setSaved] = useState<Record<string, number>>({})
  if (!decisions?.length || !auth.can('flows.edit')) return null
  async function save(item: NonNullable<AssistantWorkState['decisions']>[number], key: string) {
    setPending(true)
    try {
      const row = await api.post<EngineeringNote>('/vision/notes', { title: item.text.slice(0, 200), body: item.text, kind: 'decision', flow: flowId })
      setSaved((old) => ({ ...old, [key]: row.id }))
      await client.invalidateQueries({ queryKey: ['engineering-notes'] })
      toast.success(t('notes.saved'))
    } catch (error) { toast.error(errorMessage(error)) } finally { setPending(false) }
  }
  return <details className="rounded border border-line p-2"><summary className="cursor-pointer">{t('notes.decisions')}</summary><ul className="mt-2 space-y-2">{decisions.map((item, i) => {
    const key = `${flowId}:${item.at}:${item.text}:${i}`
    return <li key={key} className="space-y-1"><p className="whitespace-pre-wrap break-words">{item.text}</p>{saved[key] ? <Link className="text-brand underline" to={`/notes?note=${saved[key]}`}>{t('notes.open')}</Link> : <Button size="sm" disabled={pending} onClick={() => void save(item, key)}>{t('notes.saveDecision')}</Button>}</li>
  })}</ul></details>
}
