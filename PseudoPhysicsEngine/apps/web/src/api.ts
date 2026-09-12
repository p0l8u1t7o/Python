import type {
  ArtifactContract,
  AuditEventContract,
  ChangeSetApplyResultContract,
  ChangeSetContract,
  ChangeSetPreviewContract,
  FrameTreeContract,
  JobContract,
  MotionSpecContract,
  ProcessAnalysisContract,
  ProcessSpecContract,
  ProjectContract,
  ReleaseManifestContract,
  ReviewCommentContract,
  RevisionDiffContract,
  SceneAssemblyContract,
  ValidationReportContract,
} from './generated/contracts'

export type RevisionStatus = ProjectContract.RevisionStatus
export type ProjectRevision = ProjectContract.ProjectRevision
export type Project = ProjectContract.ProjectRead
export type CoordinateFrame = FrameTreeContract.CoordinateFrame
export type FrameTree = FrameTreeContract.FrameTreeRead
export type ArtifactFormat = ArtifactContract.ArtifactFormat
export type Artifact = ArtifactContract.ArtifactRead
export type ProcessSpec = ProcessSpecContract.ProcessSpec
export type ProcessAnalysis = ProcessAnalysisContract.ProcessAnalysis
export type MotionSpec = MotionSpecContract.MotionSpec
export type ValidationReport = ValidationReportContract.ValidationReport
export type ReleaseManifest = ReleaseManifestContract.ReleaseManifest
export type RevisionDiff = RevisionDiffContract.RevisionDiff
export type ReviewComment = ReviewCommentContract.ReviewCommentRead
export type AuditEvent = AuditEventContract.AuditEventRead
export type ChangeSet = ChangeSetContract.ChangeSet
export type ChangeSetPreview = ChangeSetPreviewContract.ChangeSetPreview
export type ChangeSetApplyResult = ChangeSetApplyResultContract.ChangeSetApplyResult
export type Job = JobContract.JobRead
export type SceneAssembly = SceneAssemblyContract.SceneAssemblySpec

interface ApiErrorBody {
  code?: string
  message?: string
  detail?: unknown
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (!(init?.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  })

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody
    throw new Error(body.message ?? `API request failed (${response.status})`)
  }

  return (await response.json()) as T
}

export const api = {
  checkHealth: () => request<{ status: 'ok'; database: 'ok' }>('/health'),
  listProjects: () => request<Project[]>('/projects'),
  getProject: (projectId: string) => request<Project>(`/projects/${projectId}`),
  listRevisions: (projectId: string) =>
    request<ProjectRevision[]>(`/projects/${projectId}/revisions`),
  compareRevisions: (projectId: string, fromRevisionId: string, toRevisionId: string) =>
    request<RevisionDiff>(
      `/projects/${projectId}/revisions/diff?from_revision_id=${fromRevisionId}&to_revision_id=${toRevisionId}`,
    ),
  getFrameTree: (revisionId: string) => request<FrameTree>(`/revisions/${revisionId}/frames`),
  listArtifacts: (projectId: string, revisionId: string) =>
    request<Artifact[]>(`/projects/${projectId}/artifacts?revision_id=${revisionId}`),
  uploadArtifact: (projectId: string, revisionId: string, source: string, file: File) => {
    const body = new FormData()
    body.set('revision_id', revisionId)
    body.set('source', source)
    body.set('file', file)
    return request<Artifact>(`/projects/${projectId}/files`, { method: 'POST', body })
  },
  artifactContentUrl: (artifactId: string) => `${API_BASE_URL}/artifacts/${artifactId}/content`,
  createProject: (name: string, customerName: string) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify({ name, customer_name: customerName.trim() || null }),
    }),
  createPlantFrame: (revisionId: string) =>
    request<FrameTree>(`/revisions/${revisionId}/frames`, {
      method: 'POST',
      body: JSON.stringify({
        frame: { id: crypto.randomUUID(), revision_id: revisionId, name: 'Plant' },
      }),
    }),
  previewChangeSet: (revisionId: string, changeSet: ChangeSet) =>
    request<ChangeSetPreview>(`/revisions/${revisionId}/changesets/preview`, {
      method: 'POST',
      body: JSON.stringify(changeSet),
    }),
  applyChangeSet: (revisionId: string, changeSet: ChangeSet) =>
    request<ChangeSetApplyResult>(`/revisions/${revisionId}/changesets/apply`, {
      method: 'POST',
      body: JSON.stringify(changeSet),
    }),
  getProcessSpec: (revisionId: string) =>
    request<ProcessSpec>(`/revisions/${revisionId}/process-spec`),
  saveProcessSpec: (revisionId: string, spec: ProcessSpec) =>
    request<ProcessSpec>(`/revisions/${revisionId}/process-spec`, {
      method: 'PUT',
      body: JSON.stringify(spec),
    }),
  analyzeProcess: (revisionId: string) =>
    request<ProcessAnalysis>(`/revisions/${revisionId}/process-analysis`),
  getMotionSpec: (revisionId: string) =>
    request<MotionSpec>(`/revisions/${revisionId}/motion-spec`),
  saveMotionSpec: (revisionId: string, spec: MotionSpec) =>
    request<MotionSpec>(`/revisions/${revisionId}/motion-spec`, {
      method: 'PUT',
      body: JSON.stringify(spec),
    }),
  validateRevision: (revisionId: string) =>
    request<ValidationReport>(`/revisions/${revisionId}/validate`, { method: 'POST' }),
  getValidation: (revisionId: string) =>
    request<ValidationReport>(`/revisions/${revisionId}/validation`),
  releaseRevision: (revisionId: string, approvedBy: string) =>
    request<ReleaseManifest>(`/revisions/${revisionId}/release`, {
      method: 'POST',
      body: JSON.stringify({ approved_by: approvedBy }),
    }),
  getRelease: (revisionId: string) =>
    request<ReleaseManifest>(`/revisions/${revisionId}/release`),
  getSceneAssembly: (revisionId: string) =>
    request<SceneAssembly>(`/revisions/${revisionId}/scene`),
  saveSceneAssembly: (revisionId: string, scene: SceneAssembly) =>
    request<SceneAssembly>(`/revisions/${revisionId}/scene`, {
      method: 'PUT',
      body: JSON.stringify(scene),
    }),
  listComments: (revisionId: string) =>
    request<ReviewComment[]>(`/revisions/${revisionId}/comments`),
  createComment: (revisionId: string, authorId: string, body: string) =>
    request<ReviewComment>(`/revisions/${revisionId}/comments`, {
      method: 'POST',
      body: JSON.stringify({ author_id: authorId, body }),
    }),
  resolveComment: (commentId: string, resolvedBy: string) =>
    request<ReviewComment>(`/comments/${commentId}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ resolved_by: resolvedBy }),
    }),
  listAuditEvents: (projectId: string, revisionId?: string) =>
    request<AuditEvent[]>(
      `/projects/${projectId}/audit${revisionId ? `?revision_id=${revisionId}` : ''}`,
    ),
  submitRulesValidation: (projectId: string, revisionId: string) =>
    request<Job>('/jobs', {
      method: 'POST',
      body: JSON.stringify({
        project_id: projectId,
        revision_id: revisionId,
        kind: 'SIMULATE',
        idempotency_key: crypto.randomUUID(),
        tool_name: 'ppe-rules',
        tool_version: '0.1.0',
      }),
    }),
  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),
}
