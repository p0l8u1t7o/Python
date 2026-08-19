import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { Button, Card, EmptyState } from '@/components/ui'

export function NotFoundPage() {
  const { t } = useTranslation()
  return (
    <Card className="mx-auto max-w-md">
      <EmptyState
        title="404"
        description={t('errors.not_found')}
        action={
          <Link to="/">
            <Button variant="primary">{t('nav.dashboard')}</Button>
          </Link>
        }
      />
    </Card>
  )
}
