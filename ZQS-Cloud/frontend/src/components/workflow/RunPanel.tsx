import { useTranslation } from 'react-i18next'

import { formatDateTime } from '@/lib/format'
import type { WorkflowRun, WorkflowRunLog } from '@/lib/workflowTypes'
import { Badge, Card, CardBody, CardHeader } from '@/components/ui'

const LEVEL_TONE: Record<WorkflowRunLog['level'], 'neutral' | 'warning' | 'critical'> = {
  debug: 'neutral',
  info: 'neutral',
  warning: 'warning',
  error: 'critical',
}

export const STATUS_TONE: Record<string, 'ok' | 'warning' | 'critical' | 'neutral'> = {
  pending: 'neutral',
  running: 'ok',
  waiting: 'warning',
  paused: 'warning',
  succeeded: 'ok',
  failed: 'critical',
  cancelled: 'neutral',
}

/**
 * The run's story: status, what went wrong, and the step-by-step log.
 *
 * Display only - the controls (run, pause, step, stop) live in the toolbar
 * above the canvas, next to the drawing they act on. This panel is what the
 * operator reads while the canvas moves.
 */
export function RunPanel({
  run,
  logs,
  dirty,
}: {
  run: WorkflowRun | undefined
  logs: WorkflowRunLog[]
  dirty: boolean
}) {
  const { t } = useTranslation()

  return (
    <Card>
      <CardHeader title={t('workflows.runTitle')} description={t('workflows.runHint')} />
      <CardBody className="space-y-3">
        {dirty ? (
          <p className="text-xs text-warning">{t('workflows.unsavedWarning')}</p>
        ) : null}

        {run ? (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge tone={STATUS_TONE[run.status] ?? 'neutral'}>
                {t(`workflows.status.${run.status}`)}
              </Badge>
              {run.dry_run ? <Badge tone="warning">{t('workflows.dryRun')}</Badge> : null}
              <span className="text-muted">
                {t('workflows.steps', { count: run.steps_taken })}
              </span>
              {run.step_delay_seconds > 0 ? (
                <span className="text-muted">
                  {t('workflows.delayBadge', { seconds: run.step_delay_seconds })}
                </span>
              ) : null}
            </div>

            {run.error ? <p className="text-xs text-critical">{run.error}</p> : null}

            <div className="max-h-72 space-y-1 overflow-y-auto rounded border border-line p-2">
              {logs.length === 0 ? (
                <p className="text-xs text-muted">{t('workflows.noLogs')}</p>
              ) : (
                logs.map((entry) => (
                  <div key={entry.id} className="text-[11px] leading-snug">
                    <span className="text-muted">{formatDateTime(entry.ts)}</span>{' '}
                    {entry.node_label ? (
                      <span className="font-medium">{entry.node_label}</span>
                    ) : null}{' '}
                    <span
                      className={
                        LEVEL_TONE[entry.level] === 'critical'
                          ? 'text-critical'
                          : LEVEL_TONE[entry.level] === 'warning'
                            ? 'text-warning'
                            : ''
                      }
                    >
                      {entry.message}
                    </span>
                    {entry.branch ? (
                      <span className="ml-1 text-muted">→ {entry.branch}</span>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </>
        ) : (
          <p className="text-xs text-muted">{t('workflows.noRuns')}</p>
        )}
      </CardBody>
    </Card>
  )
}
