import { type FormEvent, useMemo, useState } from 'react'
import {
  api,
  type ChangeSet,
  type ChangeSetApplyResult,
  type ChangeSetPreview,
  type CoordinateFrame,
  type FrameTree,
  type Project,
} from './api'

interface ChangeSetPanelProps {
  project: Project
  frameTree: FrameTree | null
  onApplied: (result: ChangeSetApplyResult) => Promise<void>
}

const APPROVER_KEY = 'ppe.localApproverId'

function approverId() {
  const existing = localStorage.getItem(APPROVER_KEY)
  if (existing) return existing
  const created = crypto.randomUUID()
  localStorage.setItem(APPROVER_KEY, created)
  return created
}

function framePayload(frame: CoordinateFrame, frameTree: FrameTree) {
  const transform = frameTree.transforms.find((item) => item.child_frame_id === frame.id)
  return {
    name: frame.name,
    parent_frame_id: frame.parent_frame_id ?? null,
    transform_from_parent: transform
      ? {
          id: transform.id,
          matrix: transform.matrix,
          trust_status: transform.trust_status,
          source: transform.source,
        }
      : null,
  }
}

export function ChangeSetPanel({ project, frameTree, onApplied }: ChangeSetPanelProps) {
  const [frameId, setFrameId] = useState('')
  const [nextName, setNextName] = useState('')
  const [reason, setReason] = useState('Update coordinate-frame naming')
  const [candidate, setCandidate] = useState<ChangeSet | null>(null)
  const [preview, setPreview] = useState<ChangeSetPreview | null>(null)
  const [busy, setBusy] = useState<'preview' | 'apply' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const selectedFrame = useMemo(
    () => frameTree?.frames.find((frame) => frame.id === frameId) ?? frameTree?.frames[0],
    [frameId, frameTree],
  )

  async function previewChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!frameTree || !selectedFrame || !nextName.trim()) return
    setBusy('preview')
    setMessage(null)
    const before = framePayload(selectedFrame, frameTree)
    const changeSet: ChangeSet = {
      schema_name: 'ChangeSet',
      schema_version: '1.0.0',
      id: crypto.randomUUID(),
      project_id: project.id,
      base_revision_id: project.current_revision.id,
      reason,
      user_instruction: `Rename coordinate frame ${selectedFrame.name} to ${nextName.trim()}`,
      interpreted_intent: 'Rename one coordinate frame while preserving its hierarchy and transform.',
      operations: [
        {
          operation: 'UPDATE',
          object_type: 'CoordinateFrame',
          object_id: selectedFrame.id,
          before,
          after: { ...before, name: nextName.trim() },
        },
      ],
      requires_tessellation: false,
      requires_simulation: false,
      requires_render: false,
      approved_by: approverId(),
    }
    try {
      const result = await api.previewChangeSet(project.current_revision.id, changeSet)
      setCandidate(changeSet)
      setPreview(result)
      setMessage(result.valid ? 'Preview passed. Applying creates a new immutable-history revision.' : 'Preview found issues.')
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Could not preview ChangeSet')
    } finally {
      setBusy(null)
    }
  }

  async function applyChange() {
    if (!candidate || !preview?.valid) return
    setBusy('apply')
    setMessage(null)
    try {
      const result = await api.applyChangeSet(project.current_revision.id, candidate)
      await onApplied(result)
      setCandidate(null)
      setPreview(null)
      setNextName('')
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Could not apply ChangeSet')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="change-set-panel" aria-labelledby="change-set-heading">
      <div className="section-label"><h2 id="change-set-heading">ChangeSet</h2><span>NEW REVISION</span></div>
      <form onSubmit={previewChange}>
        <select value={selectedFrame?.id ?? ''} onChange={(event) => {
          setFrameId(event.target.value)
          setPreview(null)
          setCandidate(null)
        }} required>
          {frameTree?.frames.map((frame) => <option key={frame.id} value={frame.id}>{frame.name}</option>)}
        </select>
        <input value={nextName} onChange={(event) => {
          setNextName(event.target.value)
          setPreview(null)
          setCandidate(null)
        }} placeholder="New frame name" maxLength={200} required />
        <input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Reason" maxLength={1000} required />
        <button className="secondary-action" disabled={busy !== null || !selectedFrame}>{busy === 'preview' ? 'Previewing…' : 'Preview change'}</button>
      </form>
      {preview && (
        <div className={`change-preview ${preview.valid ? 'pass' : 'fail'}`}>
          <strong>{preview.valid ? 'VALID' : 'REJECTED'}</strong>
          <span>{preview.affected_object_ids.length} object affected</span>
          {preview.issues.map((issue) => <small key={`${issue.code}:${issue.operation_index}`}>{issue.code}: {issue.message}</small>)}
        </div>
      )}
      <button className="primary-action" type="button" onClick={applyChange} disabled={busy !== null || !candidate || !preview?.valid}>{busy === 'apply' ? 'Creating revision…' : 'Approve and create revision'}</button>
      {message && <p className="engineering-message">{message}</p>}
    </section>
  )
}
