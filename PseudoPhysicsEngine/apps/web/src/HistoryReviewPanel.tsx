import { type FormEvent, useCallback, useEffect, useState } from 'react'
import {
  api,
  type AuditEvent,
  type Job,
  type Project,
  type ProjectRevision,
  type ReviewComment,
  type RevisionDiff,
} from './api'

const REVIEWER_KEY = 'ppe.localReviewerId'

function reviewerId() {
  const existing = localStorage.getItem(REVIEWER_KEY)
  if (existing) return existing
  const created = crypto.randomUUID()
  localStorage.setItem(REVIEWER_KEY, created)
  return created
}

interface HistoryReviewPanelProps {
  project: Project
}

export function HistoryReviewPanel({ project }: HistoryReviewPanelProps) {
  const revision = project.current_revision
  const [revisions, setRevisions] = useState<ProjectRevision[]>([])
  const [diff, setDiff] = useState<RevisionDiff | null>(null)
  const [comments, setComments] = useState<ReviewComment[]>([])
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [commentBody, setCommentBody] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState<'comment' | 'job' | string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const [history, reviewComments, auditEvents] = await Promise.all([
      api.listRevisions(project.id),
      api.listComments(revision.id),
      api.listAuditEvents(project.id, revision.id),
    ])
    setRevisions(history)
    setComments(reviewComments)
    setEvents(auditEvents)
    if (revision.parent_revision_id) {
      setDiff(await api.compareRevisions(project.id, revision.parent_revision_id, revision.id))
    }
  }, [project.id, revision.id, revision.parent_revision_id])

  useEffect(() => {
    const loadTimer = window.setTimeout(() => {
      refresh().catch((caught) =>
        setError(caught instanceof Error ? caught.message : '無法載入歷程'),
      )
    }, 0)
    return () => window.clearTimeout(loadTimer)
  }, [refresh])

  async function addComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy('comment')
    setError(null)
    try {
      await api.createComment(revision.id, reviewerId(), commentBody)
      setCommentBody('')
      await refresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '無法新增留言')
    } finally {
      setBusy(null)
    }
  }

  async function resolve(comment: ReviewComment) {
    setBusy(comment.id)
    try {
      await api.resolveComment(comment.id, reviewerId())
      await refresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '無法解決留言')
    } finally {
      setBusy(null)
    }
  }

  async function runWorkerValidation() {
    setBusy('job')
    setError(null)
    try {
      let current = await api.submitRulesValidation(project.id, revision.id)
      setJob(current)
      for (let attempt = 0; attempt < 20 && ['PENDING', 'RUNNING'].includes(current.status); attempt += 1) {
        await new Promise((resolveDelay) => window.setTimeout(resolveDelay, 250))
        current = await api.getJob(current.id)
        setJob(current)
      }
      await refresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '背景驗證失敗')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="history-review-panel" aria-labelledby="history-heading">
      <div className="section-label"><h2 id="history-heading">版本與審查</h2><span>{revisions.length} REVISIONS</span></div>
      <div className="revision-line">
        {revisions.map((item) => <span key={item.id} className={item.id === revision.id ? 'current' : ''}>#{item.sequence} {item.status}</span>)}
      </div>
      {diff && (
        <details>
          <summary>與上一版差異（{diff.entries?.length ?? 0}）</summary>
          <ul className="compact-list">
            {diff.entries?.map((entry) => <li key={`${entry.object_type}:${entry.object_key}`}><strong>{entry.change_kind}</strong> {entry.object_type} <code>{entry.object_key.slice(0, 12)}</code></li>)}
          </ul>
        </details>
      )}
      <form className="comment-form" onSubmit={addComment}>
        <input value={commentBody} onChange={(event) => setCommentBody(event.target.value)} placeholder="新增 revision 審查留言" maxLength={4000} required />
        <button className="secondary-action" disabled={busy !== null}>{busy === 'comment' ? '送出中…' : '新增留言'}</button>
      </form>
      <ul className="comment-list">
        {comments.map((comment) => (
          <li key={comment.id} className={comment.resolved_at ? 'resolved' : ''}>
            <span>{comment.body}</span>
            {comment.resolved_at ? <small>已解決</small> : <button type="button" onClick={() => resolve(comment)} disabled={busy !== null}>標記解決</button>}
          </li>
        ))}
      </ul>
      <button className="secondary-action" type="button" onClick={runWorkerValidation} disabled={busy !== null}>{busy === 'job' ? 'Worker 執行中…' : '排入背景規則驗證'}</button>
      {job && <p className={`job-state ${job.status.toLowerCase()}`}>Job {job.id.slice(0, 8)} · {job.status}</p>}
      <details>
        <summary>Audit trail（{events.length}）</summary>
        <ul className="compact-list audit-list">{events.map((event) => <li key={event.id}><strong>{event.event_type}</strong><small>{new Date(event.created_at).toLocaleString()}</small></li>)}</ul>
      </details>
      {error && <p className="engineering-message error-message">{error}</p>}
    </section>
  )
}
