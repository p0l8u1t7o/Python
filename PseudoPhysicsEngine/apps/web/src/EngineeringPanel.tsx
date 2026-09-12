import { type FormEvent, useEffect, useState } from 'react'
import {
  api,
  type MotionSpec,
  type ProcessAnalysis,
  type ProcessSpec,
  type Project,
  type ReleaseManifest,
  type ValidationReport,
} from './api'

interface EngineeringPanelProps {
  project: Project
  defaultSceneNodeId: string | null
  onReleased: (manifest: ReleaseManifest) => void
  onMotionChanged: (motion: MotionSpec) => void
}

const APPROVER_KEY = 'ppe.localApproverId'

function localApproverId() {
  const existing = localStorage.getItem(APPROVER_KEY)
  if (existing) return existing
  const created = crypto.randomUUID()
  localStorage.setItem(APPROVER_KEY, created)
  return created
}

export function EngineeringPanel({
  project,
  defaultSceneNodeId,
  onReleased,
  onMotionChanged,
}: EngineeringPanelProps) {
  const revisionId = project.current_revision.id
  const [processId, setProcessId] = useState<string>(() => crypto.randomUUID())
  const [stepId, setStepId] = useState<string>(() => crypto.randomUUID())
  const [motionId, setMotionId] = useState<string>(() => crypto.randomUUID())
  const [trackId, setTrackId] = useState<string>(() => crypto.randomUUID())
  const [sceneNodeId, setSceneNodeId] = useState<string>(() => crypto.randomUUID())
  const [stepName, setStepName] = useState('Transfer part')
  const [targetSeconds, setTargetSeconds] = useState(10)
  const [durationSeconds, setDurationSeconds] = useState(5)
  const [motionSeconds, setMotionSeconds] = useState(5)
  const [analysis, setAnalysis] = useState<ProcessAnalysis | null>(null)
  const [validation, setValidation] = useState<ValidationReport | null>(null)
  const [release, setRelease] = useState<ReleaseManifest | null>(null)
  const [busy, setBusy] = useState<'save' | 'validate' | 'release' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.allSettled([
      api.getProcessSpec(revisionId),
      api.getMotionSpec(revisionId),
      api.getValidation(revisionId),
      api.getRelease(revisionId),
    ]).then(([processResult, motionResult, validationResult, releaseResult]) => {
      if (cancelled) return
      if (processResult.status === 'fulfilled') {
        const spec = processResult.value
        const first = spec.steps[0]
        setProcessId(spec.id)
        setTargetSeconds(spec.target_cycle_time_seconds)
        if (first) {
          setStepId(first.id)
          setStepName(first.name)
          setDurationSeconds(first.estimated_duration_seconds)
        }
        api.analyzeProcess(revisionId).then(setAnalysis).catch(() => undefined)
      }
      if (motionResult.status === 'fulfilled') {
        const spec = motionResult.value
        onMotionChanged(spec)
        const first = spec.tracks[0]
        setMotionId(spec.id)
        if (first) {
          setTrackId(first.id)
          setSceneNodeId(first.scene_node_id)
          setMotionSeconds(first.keyframes.at(-1)?.time_seconds ?? 0)
        }
      }
      if (validationResult.status === 'fulfilled') setValidation(validationResult.value)
      if (releaseResult.status === 'fulfilled') setRelease(releaseResult.value)
    })
    return () => {
      cancelled = true
    }
  }, [onMotionChanged, revisionId])

  async function saveSpecs(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy('save')
    setMessage(null)
    const processSpec: ProcessSpec = {
      schema_name: 'ProcessSpec',
      schema_version: '1.0.0',
      id: processId,
      project_id: project.id,
      revision_id: revisionId,
      target_cycle_time_seconds: targetSeconds,
      assumptions: [],
      unresolved_questions: [],
      steps: [
        {
          id: stepId,
          name: stepName,
          predecessor_ids: [],
          input_conditions: [],
          output_conditions: [],
          equipment_requirements: [],
          estimated_duration_seconds: durationSeconds,
        },
      ],
    }
    const motionSpec: MotionSpec = {
      schema_name: 'MotionSpec',
      schema_version: '1.0.0',
      id: motionId,
      project_id: project.id,
      revision_id: revisionId,
      tracks: [
        {
          id: trackId,
          scene_node_id: defaultSceneNodeId ?? sceneNodeId,
          joint_name: 'primary_axis',
          position_unit: 'mm',
          keyframes: [
            { time_seconds: 0, position: 0 },
            { time_seconds: motionSeconds, position: 1000 },
          ],
        },
      ],
    }
    try {
      const [, savedMotion] = await Promise.all([
        api.saveProcessSpec(revisionId, processSpec),
        api.saveMotionSpec(revisionId, motionSpec),
      ])
      onMotionChanged(savedMotion)
      setAnalysis(await api.analyzeProcess(revisionId))
      setValidation(null)
      setMessage('Engineering specifications saved. Run validation to refresh the release gate.')
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Could not save engineering specs')
    } finally {
      setBusy(null)
    }
  }

  async function validate() {
    setBusy('validate')
    setMessage(null)
    try {
      const report = await api.validateRevision(revisionId)
      setValidation(report)
      setMessage(report.status === 'PASSED' ? 'Validation passed.' : 'Validation found blockers.')
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Validation failed')
    } finally {
      setBusy(null)
    }
  }

  async function publish() {
    setBusy('release')
    setMessage(null)
    try {
      const manifest = await api.releaseRevision(revisionId, localApproverId())
      setRelease(manifest)
      onReleased(manifest)
      setMessage('Revision released and locked.')
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Release failed')
    } finally {
      setBusy(null)
    }
  }

  const immutable = project.current_revision.status === 'RELEASED' || release !== null
  return (
    <section className="engineering-panel" aria-labelledby="engineering-heading">
      <div className="section-label">
        <h2 id="engineering-heading">Engineering gate</h2>
        <span>{release ? 'RELEASED' : validation?.status ?? 'NOT VALIDATED'}</span>
      </div>
      <form onSubmit={saveSpecs}>
        <label>Process step<input value={stepName} onChange={(event) => setStepName(event.target.value)} required /></label>
        <div className="engineering-grid">
          <label>Target (s)<input type="number" min="0.001" step="0.001" value={targetSeconds} onChange={(event) => setTargetSeconds(event.target.valueAsNumber)} required /></label>
          <label>Step (s)<input type="number" min="0" step="0.001" value={durationSeconds} onChange={(event) => setDurationSeconds(event.target.valueAsNumber)} required /></label>
          <label>Motion (s)<input type="number" min="0.001" step="0.001" value={motionSeconds} onChange={(event) => setMotionSeconds(event.target.valueAsNumber)} required /></label>
        </div>
        <button className="secondary-action" disabled={busy !== null || immutable}>{busy === 'save' ? 'Saving…' : 'Save Process + Motion'}</button>
      </form>
      {analysis && (
        <div className={`analysis-strip ${analysis.within_target ? 'pass' : 'fail'}`}>
          <span>Critical path</span><strong>{analysis.cycle_time_seconds.toFixed(3)} s</strong>
        </div>
      )}
      <button className="secondary-action" type="button" onClick={validate} disabled={busy !== null || immutable}>{busy === 'validate' ? 'Validating…' : 'Run validation'}</button>
      {validation && (validation.issues?.length ?? 0) > 0 && (
        <ul className="validation-list">
          {validation.issues?.map((issue) => <li key={issue.code} className={issue.blocks_release ? 'blocker' : ''}><strong>{issue.code}</strong><span>{issue.message}</span></li>)}
        </ul>
      )}
      <button className="primary-action" type="button" onClick={publish} disabled={busy !== null || immutable || validation?.status !== 'PASSED'}>{busy === 'release' ? 'Releasing…' : release ? 'Released' : 'Release revision'}</button>
      {release && <p className="manifest-id">Manifest {release.id}</p>}
      {message && <p className="engineering-message" role="status">{message}</p>}
    </section>
  )
}
