import { type FormEvent, lazy, Suspense, useCallback, useEffect, useState } from 'react'
import './App.css'
import {
  api,
  type Artifact,
  type ChangeSetApplyResult,
  type FrameTree,
  type MotionSpec,
  type Project,
  type SceneAssembly,
} from './api'
import { EngineeringPanel } from './EngineeringPanel'
import { HistoryReviewPanel } from './HistoryReviewPanel'
import { SceneAssemblyPanel } from './SceneAssemblyPanel'
import { ChangeSetPanel } from './ChangeSetPanel'
import { registerCreateProjectTool } from './webmcp'

type ApiState = 'checking' | 'online' | 'offline'
type BusyAction = 'project' | 'frame' | 'resume' | 'upload' | null
const LAST_PROJECT_KEY = 'ppe.lastProjectId'
const SceneViewer = lazy(() =>
  import('./SceneViewer').then((module) => ({ default: module.SceneViewer })),
)

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`
}

function errorMessage(caught: unknown, fallback: string) {
  return caught instanceof Error ? caught.message : fallback
}

function App() {
  const [apiState, setApiState] = useState<ApiState>('checking')
  const [projectName, setProjectName] = useState('機器人工作站')
  const [customerName, setCustomerName] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [project, setProject] = useState<Project | null>(null)
  const [frameTree, setFrameTree] = useState<FrameTree | null>(null)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [motion, setMotion] = useState<MotionSpec | null>(null)
  const [sceneAssembly, setSceneAssembly] = useState<SceneAssembly | null>(null)
  const [artifactSource, setArtifactSource] = useState('供應商匯出')
  const [artifactFile, setArtifactFile] = useState<File | null>(null)
  const [loadingProjects, setLoadingProjects] = useState(true)
  const [busyAction, setBusyAction] = useState<BusyAction>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .checkHealth()
      .then(() => setApiState('online'))
      .catch(() => {
        setApiState('offline')
        setLoadingProjects(false)
      })
  }, [])

  useEffect(() => {
    if (apiState !== 'online') return
    let cancelled = false
    api
      .listProjects()
      .then(async (loadedProjects) => {
        if (cancelled) return
        setProjects(loadedProjects)
        const lastProjectId = localStorage.getItem(LAST_PROJECT_KEY)
        const selected = loadedProjects.find((item) => item.id === lastProjectId)
        if (!selected) return
        setBusyAction('resume')
        const [tree, storedArtifacts] = await Promise.all([
          api.getFrameTree(selected.current_revision.id),
          api.listArtifacts(selected.id, selected.current_revision.id),
        ])
        if (!cancelled) {
          setProject(selected)
          setFrameTree(tree)
          setArtifacts(storedArtifacts)
        }
      })
      .catch((caught) => {
        if (!cancelled) setError(errorMessage(caught, '無法載入專案'))
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingProjects(false)
          setBusyAction(null)
        }
      })
    return () => {
      cancelled = true
    }
  }, [apiState])

  const showProject = useCallback((selected: Project) => {
    setProject(selected)
    setProjects((current) => [selected, ...current.filter((item) => item.id !== selected.id)])
    setFrameTree(null)
    setArtifacts([])
    setMotion(null)
    setSceneAssembly(null)
    setError(null)
    localStorage.setItem(LAST_PROJECT_KEY, selected.id)
  }, [])

  const handleMotionChanged = useCallback((loadedMotion: MotionSpec) => setMotion(loadedMotion), [])
  const handleSceneChanged = useCallback(
    (loadedScene: SceneAssembly) => setSceneAssembly(loadedScene),
    [],
  )

  useEffect(() => registerCreateProjectTool(showProject), [showProject])

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusyAction('project')
    setError(null)
    try {
      showProject(await api.createProject(projectName, customerName))
    } catch (caught) {
      setError(errorMessage(caught, '無法建立專案'))
    } finally {
      setBusyAction(null)
    }
  }

  async function handleCreatePlantFrame() {
    if (!project) return
    setBusyAction('frame')
    setError(null)
    try {
      setFrameTree(await api.createPlantFrame(project.current_revision.id))
    } catch (caught) {
      setError(errorMessage(caught, '無法建立 Plant 座標框架'))
    } finally {
      setBusyAction(null)
    }
  }

  async function handleResumeProject(selected: Project) {
    setBusyAction('resume')
    setError(null)
    try {
      const [tree, storedArtifacts] = await Promise.all([
        api.getFrameTree(selected.current_revision.id),
        api.listArtifacts(selected.id, selected.current_revision.id),
      ])
      setProject(selected)
      setFrameTree(tree)
      setArtifacts(storedArtifacts)
      setMotion(null)
      setSceneAssembly(null)
      localStorage.setItem(LAST_PROJECT_KEY, selected.id)
    } catch (caught) {
      setError(errorMessage(caught, '無法開啟專案'))
    } finally {
      setBusyAction(null)
    }
  }

  function handleSwitchProject() {
    setProject(null)
    setFrameTree(null)
    setArtifacts([])
    setMotion(null)
    setSceneAssembly(null)
    localStorage.removeItem(LAST_PROJECT_KEY)
  }

  async function handleUploadArtifact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!project || !artifactFile) return
    setBusyAction('upload')
    setError(null)
    try {
      const uploaded = await api.uploadArtifact(
        project.id,
        project.current_revision.id,
        artifactSource,
        artifactFile,
      )
      setArtifacts((current) => [uploaded, ...current])
      setArtifactFile(null)
      event.currentTarget.reset()
    } catch (caught) {
      setError(errorMessage(caught, '無法上傳工程檔案'))
    } finally {
      setBusyAction(null)
    }
  }

  function handleReleased() {
    setProject((current) =>
      current
        ? { ...current, current_revision: { ...current.current_revision, status: 'RELEASED' } }
        : current,
    )
    setProjects((current) =>
      current.map((item) =>
        item.id === project?.id
          ? { ...item, current_revision: { ...item.current_revision, status: 'RELEASED' } }
          : item,
      ),
    )
  }

  async function handleChangeSetApplied(result: ChangeSetApplyResult) {
    if (!project) return
    const nextProject = { ...project, current_revision: result.revision }
    const copiedArtifacts = await api.listArtifacts(project.id, result.revision.id)
    setProject(nextProject)
    setProjects((current) =>
      current.map((item) => (item.id === project.id ? nextProject : item)),
    )
    setFrameTree(result.frame_tree)
    setArtifacts(copiedArtifacts)
    setMotion(null)
    setSceneAssembly(null)
  }

  const plantFrame = frameTree?.frames.find((frame) => frame.parent_frame_id == null)
  const previewArtifact = artifacts.find((artifact) => artifact.format === 'GLB')
  const hasStep = artifacts.some((artifact) => artifact.format === 'STEP')
  const immutable = project?.current_revision.status === 'RELEASED'

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <span className="brand-mark" aria-hidden="true">PPE</span>
          <div><strong>Digital Thread Console</strong><span>自動化設備數位分身工程平台</span></div>
        </div>
        <div className={`system-state ${apiState}`} role="status">
          <span className="state-dot" aria-hidden="true" />
          API {apiState === 'online' ? '連線正常' : apiState === 'offline' ? '離線' : '檢查中'}
        </div>
      </header>

      <main className="workspace">
        <aside className="module-rail" aria-label="功能模組">
          <button type="button" className="module active"><span>01</span>專案</button>
          <button type="button" className="module" disabled><span>02</span>場景</button>
          <button type="button" className="module" disabled><span>03</span>模擬</button>
          <button type="button" className="module" disabled><span>04</span>發布</button>
          <div className="rail-footer">MVP<br />LOCAL WORKFLOW</div>
        </aside>

        <section className="control-panel" aria-labelledby="project-heading">
          <div className="panel-heading">
            <span className="eyebrow">PROJECT SETUP</span>
            <h1 id="project-heading">工程專案</h1>
            <p>建立不可變 revision，保存工程輸入並通過發布閘門。</p>
          </div>

          {!project ? (
            <>
              <section className="project-picker" aria-labelledby="existing-projects-heading">
                <div className="section-label"><h2 id="existing-projects-heading">既有專案</h2><span>{loadingProjects ? '載入中' : `${projects.length} PROJECTS`}</span></div>
                {projects.length ? (
                  <div className="project-list">
                    {projects.map((item) => (
                      <button type="button" className="project-option" key={item.id} disabled={busyAction !== null} onClick={() => handleResumeProject(item)}>
                        <span>{item.name}</span><small>REV #{item.current_revision.sequence} · {item.current_revision.status}</small>
                      </button>
                    ))}
                  </div>
                ) : <p className="empty-projects">{loadingProjects ? '正在讀取…' : '尚無專案'}</p>}
              </section>
              <form className="project-form" onSubmit={handleCreateProject}>
                <div className="section-label"><h2>建立新專案</h2></div>
                <label>專案名稱<input value={projectName} onChange={(event) => setProjectName(event.target.value)} minLength={1} maxLength={200} required /></label>
                <label>客戶名稱 <span>選填</span><input value={customerName} onChange={(event) => setCustomerName(event.target.value)} maxLength={200} placeholder="例如：示範工廠" /></label>
                <button className="primary-action" disabled={busyAction !== null || apiState !== 'online'}>{busyAction === 'project' ? '建立中…' : '建立專案'}</button>
              </form>
            </>
          ) : (
            <>
              <div className="project-record">
                <div className="record-title"><span className="status-chip">{project.current_revision.status}</span><h2>{project.name}</h2><p>{project.customer_name ?? '內部工程專案'}</p></div>
                <dl><div><dt>Project UUID</dt><dd>{project.id}</dd></div><div><dt>Revision</dt><dd>#{project.current_revision.sequence}</dd></div><div><dt>Revision UUID</dt><dd>{project.current_revision.id}</dd></div></dl>
                {!plantFrame && <button className="primary-action" onClick={handleCreatePlantFrame} disabled={busyAction !== null || immutable}>{busyAction === 'frame' ? '建立中…' : '建立 Plant 座標框架'}</button>}
                <button className="secondary-action" onClick={handleSwitchProject} disabled={busyAction !== null}>切換專案</button>
              </div>

              <section className="artifact-panel" aria-labelledby="artifact-heading">
                <div className="section-label"><h2 id="artifact-heading">工程檔案</h2><span>{artifacts.length} ARTIFACTS</span></div>
                <form className="artifact-form" onSubmit={handleUploadArtifact}>
                  <input aria-label="檔案來源" value={artifactSource} onChange={(event) => setArtifactSource(event.target.value)} maxLength={500} required />
                  <input aria-label="選擇工程檔案" type="file" accept=".step,.stp,.glb,.pdf" onChange={(event) => setArtifactFile(event.target.files?.[0] ?? null)} required />
                  <button className="primary-action" disabled={!artifactFile || busyAction !== null || immutable}>{busyAction === 'upload' ? '驗證並上傳中…' : '上傳 STEP / GLB / PDF'}</button>
                </form>
                <div className="artifact-list">
                  {artifacts.map((artifact) => (
                    <a key={artifact.id} className="artifact-row" href={api.artifactContentUrl(artifact.id)} target="_blank" rel="noreferrer">
                      <span><strong>{artifact.original_filename}</strong><small>{artifact.format} · {formatBytes(artifact.size_bytes)}</small></span><code>{artifact.sha256.slice(0, 12)}</code>
                    </a>
                  ))}
                </div>
              </section>
              <ChangeSetPanel
                key={`changeset-${project.current_revision.id}`}
                project={project}
                frameTree={frameTree}
                onApplied={handleChangeSetApplied}
              />
              <SceneAssemblyPanel
                key={`scene-${project.current_revision.id}`}
                project={project}
                frameTree={frameTree}
                artifacts={artifacts}
                onSceneChanged={handleSceneChanged}
              />
              <EngineeringPanel
                key={project.current_revision.id}
                project={project}
                defaultSceneNodeId={sceneAssembly?.nodes?.[0]?.id ?? null}
                onReleased={handleReleased}
                onMotionChanged={handleMotionChanged}
              />
              <HistoryReviewPanel key={`history-${project.current_revision.id}`} project={project} />
            </>
          )}
          {error && <p className="error-message" role="alert">{error}</p>}
        </section>

        <section className="scene-panel" aria-labelledby="scene-heading">
          <div className="scene-toolbar"><div><span className="eyebrow">COORDINATE WORKSPACE</span><h2 id="scene-heading">Plant / Z-up</h2></div><span className="unit-badge">UNIT · mm</span></div>
          <div className="coordinate-stage">
            {previewArtifact ? (
              <Suspense fallback={<div className="viewer-loading">載入 3D 檢視器…</div>}><SceneViewer modelUrl={api.artifactContentUrl(previewArtifact.id)} motion={motion} /></Suspense>
            ) : (
              <div className="stage-message"><span className={`stage-index ${plantFrame ? 'ready' : ''}`}>{plantFrame ? '01' : '00'}</span><strong>{plantFrame ? 'Plant frame 已建立' : '等待場景基準'}</strong><p>{plantFrame ? '上傳 GLB 即可預覽；保存 MotionSpec 後可播放動作。' : '先建立專案與 Plant root frame。'}</p></div>
            )}
          </div>
          <div className="scene-footer"><span>Viewer：{previewArtifact?.original_filename ?? '尚未載入 GLB'}</span><span>Transform：4×4 / column vector</span></div>
        </section>

        <aside className="integrity-panel" aria-labelledby="integrity-heading">
          <span className="eyebrow">INTEGRITY</span><h2 id="integrity-heading">資料完整性</h2>
          <ul className="check-list">
            <li className={project ? 'complete' : ''}><span />Project UUID</li>
            <li className={project ? 'complete' : ''}><span />不可變 Revision</li>
            <li className={plantFrame ? 'complete' : ''}><span />Plant root / Z-up / mm</li>
            <li className={hasStep ? 'complete' : ''}><span />STEP 來源檔</li>
            <li className={(sceneAssembly?.nodes?.length ?? 0) > 0 ? 'complete' : ''}><span />SceneAssembly</li>
            <li className={motion ? 'complete' : ''}><span />MotionSpec</li>
          </ul>
          <div className="trust-card"><span>發布狀態</span><strong>{immutable ? 'RELEASED' : 'DRAFT'}</strong><p>INFERRED 座標、缺少規格或週期超標都會阻擋發布。</p></div>
        </aside>
      </main>
    </div>
  )
}

export default App
