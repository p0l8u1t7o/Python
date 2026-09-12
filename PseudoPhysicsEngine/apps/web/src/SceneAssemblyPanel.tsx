import { type FormEvent, useEffect, useState } from 'react'
import {
  api,
  type Artifact,
  type FrameTree,
  type Project,
  type SceneAssembly,
} from './api'

interface SceneAssemblyPanelProps {
  project: Project
  frameTree: FrameTree | null
  artifacts: Artifact[]
  onSceneChanged: (scene: SceneAssembly) => void
}

export function SceneAssemblyPanel({ project, frameTree, artifacts, onSceneChanged }: SceneAssemblyPanelProps) {
  const revisionId = project.current_revision.id
  const [scene, setScene] = useState<SceneAssembly | null>(null)
  const [name, setName] = useState('Robot')
  const [artifactId, setArtifactId] = useState('')
  const [frameId, setFrameId] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.getSceneAssembly(revisionId).then((loaded) => {
        setScene(loaded)
        onSceneChanged(loaded)
      }).catch(() => undefined)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [onSceneChanged, revisionId])

  const availableArtifact = artifacts.find((artifact) => artifact.id === artifactId) ?? artifacts[0]
  const availableFrame = frameTree?.frames.find((frame) => frame.id === frameId) ?? frameTree?.frames[0]

  async function addNode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!availableArtifact || !availableFrame) return
    setBusy(true)
    setMessage(null)
    const next: SceneAssembly = {
      schema_name: 'SceneAssemblySpec', schema_version: '1.0.0',
      id: scene?.id ?? crypto.randomUUID(), project_id: project.id, revision_id: revisionId,
      nodes: [...(scene?.nodes ?? []), {
        id: crypto.randomUUID(), name, asset_version_id: availableArtifact.id,
        coordinate_frame_id: availableFrame.id, parent_node_id: null, visible: true,
      }],
    }
    try {
      const saved = await api.saveSceneAssembly(revisionId, next)
      setScene(saved)
      onSceneChanged(saved)
      setMessage('場景節點已保存。')
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : '無法保存場景節點')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="scene-assembly-panel" aria-labelledby="assembly-heading">
      <div className="section-label"><h2 id="assembly-heading">場景組裝</h2><span>{scene?.nodes?.length ?? 0} NODES</span></div>
      <form onSubmit={addNode}>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="節點名稱" required />
        <select value={availableArtifact?.id ?? ''} onChange={(event) => setArtifactId(event.target.value)} required>
          {artifacts.map((artifact) => <option key={artifact.id} value={artifact.id}>{artifact.original_filename}</option>)}
        </select>
        <select value={availableFrame?.id ?? ''} onChange={(event) => setFrameId(event.target.value)} required>
          {frameTree?.frames.map((frame) => <option key={frame.id} value={frame.id}>{frame.name}</option>)}
        </select>
        <button className="secondary-action" disabled={busy || project.current_revision.status === 'RELEASED' || !availableArtifact || !availableFrame}>{busy ? '保存中…' : '加入場景節點'}</button>
      </form>
      {scene?.nodes?.length ? <ul className="compact-list">{scene.nodes.map((node) => <li key={node.id}><strong>{node.name}</strong><code>{node.id.slice(0, 12)}</code></li>)}</ul> : <p className="engineering-message">需要至少一個 artifact 與 coordinate frame。</p>}
      {message && <p className="engineering-message">{message}</p>}
    </section>
  )
}
