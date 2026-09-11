import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useEngineeringNotes } from '@/lib/queries'

export function FlowNotesLink({ flowId }: { flowId: number }) {
  const { t } = useTranslation()
  const notes = useEngineeringNotes({ flow: flowId })
  return <Link className="block p-3 text-sm text-brand underline" to={`/notes?flow=${flowId}`}>{t('notes.forFlow', { count: notes.data?.total ?? 0 })}</Link>
}
