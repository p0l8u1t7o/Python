import { useCallback, useEffect, useMemo, useState } from "react";
import { api, waitForJob } from "../api";
import type { Assumption, InputEntry, Project, Question } from "../types";
import { Viewer, type Check } from "./Viewer";

const tabs = ["資料", "檢查", "問題", "假設", "變更", "任務", "對話", "流程"] as const;
type Tab = (typeof tabs)[number];
type Task = {
  id: string;
  owner: "engineering" | "astra";
  instruction: string;
  status: string;
  result?: unknown;
};
type Change = { id: string; text: string };
type Process = {
  stations: { id: string; name: string }[];
  steps: { id: string; station: string; actor: string; action: string; duration_s?: number }[];
  takt: { target_s: number };
};

export function MainWorkspace({ projectId, onBack }: { projectId: string; onBack: () => void }) {
  const [project, setProject] = useState<Project>();
  const [files, setFiles] = useState<InputEntry[]>([]);
  const [tab, setTab] = useState<Tab>("資料");
  const [version, setVersion] = useState<string>();
  const [overlayVersion, setOverlayVersion] = useState<string>();
  const [checks, setChecks] = useState<Check[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [changes, setChanges] = useState<Change[]>([]);
  const [process, setProcess] = useState<Process>();
  const [command, setCommand] = useState("");
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<string>();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const refresh = useCallback(async () => {
    const [projectData, fileData, taskData, changeData, processData] = await Promise.all([
      api<Project>(`/projects/${projectId}`),
      api<{ files: InputEntry[] }>(`/projects/${projectId}/files`),
      api<Task[]>(`/projects/${projectId}/tasks`),
      api<Change[]>(`/projects/${projectId}/changes`),
      api<Process>(`/projects/${projectId}/process`),
    ]);
    setProject(projectData);
    setFiles(fileData.files);
    setTasks(taskData);
    setChanges(changeData);
    setProcess(processData);
    setVersion((old) => old ?? projectData.versions.at(-1)?.id);
  }, [projectId]);
  useEffect(() => {
    void refresh().catch((reason) => setError(String(reason)));
  }, [refresh]);
  useEffect(() => {
    if (!version) {
      setChecks([]);
      return;
    }
    void api<{ items: Check[] }>(`/projects/${projectId}/versions/${version}/checks.json`)
      .then((data) => setChecks(data.items))
      .catch(() => setChecks([]));
  }, [projectId, version]);
  const latest = useMemo(
    () => project?.versions.find((item) => item.id === version),
    [project, version],
  );

  async function runJob(jobId: string, label: string) {
    setNotice(`${label} 已排程…`);
    setError(undefined);
    const finished = await waitForJob(jobId, (job) => setNotice(`${label}：${job.status}`));
    if (finished.status !== "done") throw new Error(finished.error ?? `${label} 失敗`);
    await refresh();
    setNotice(`${label} 完成`);
  }
  async function submitChange(text: string, object?: string, time?: number) {
    if (!text.trim()) return;
    try {
      const job = await api<{ id: string; change_id: string }>(`/projects/${projectId}/changes`, {
        method: "POST",
        body: JSON.stringify({ text, object, t: time }),
      });
      setCommand("");
      await runJob(job.id, job.change_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }
  async function runAstra() {
    try {
      const task = await api<Task>(`/projects/${projectId}/tasks`, {
        method: "POST",
        body: JSON.stringify({ owner: "astra", text: command.trim() || "請 Astra 美化" }),
      });
      const job = await api<{ id: string }>(`/projects/${projectId}/tasks/${task.id}/run`, {
        method: "POST",
      });
      setCommand("");
      await runJob(job.id, `Astra ${task.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }
  async function build() {
    try {
      const job = await api<{ id: string }>(`/projects/${projectId}/build`, { method: "POST" });
      await runJob(job.id, "L1 建置 + Astra");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }
  async function exportPack() {
    try {
      const job = await api<{ id: string }>(`/projects/${projectId}/export`, {
        method: "POST",
        body: JSON.stringify({ kinds: [] }),
      });
      await runJob(job.id, "完整交付包");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }
  async function supplement(list: FileList | null) {
    if (!list) return;
    for (const file of Array.from(list)) {
      const body = new FormData();
      body.append("file", file);
      body.append("kind", file.type.startsWith("image/") ? "product_photo" : "other");
      body.append("note", "補充資料");
      await api(`/projects/${projectId}/files`, { method: "POST", body });
    }
    await refresh();
    setNotice("資料已補充；請重新執行 intake 或建立變更。");
  }
  if (!project) return <div className="center-message">正在載入專案…</div>;
  return (
    <main className="workspace">
      <header className="topbar">
        <button className="menu" onClick={onBack}>
          ←
        </button>
        <div className="project-title">
          <b>{project.name}</b>
          <span>{project.customer || "未填客戶"}</span>
        </div>
        <select value={version ?? ""} onChange={(event) => setVersion(event.target.value)}>
          {project.versions.map((item) => (
            <option key={item.id}>{item.id}</option>
          ))}
        </select>
        <select
          aria-label="疊圖版本"
          value={overlayVersion ?? ""}
          onChange={(event) => setOverlayVersion(event.target.value || undefined)}
        >
          <option value="">不疊圖</option>
          {project.versions
            .filter((item) => item.id !== version)
            .map((item) => (
              <option key={item.id}>{item.id}</option>
            ))}
        </select>
        <button onClick={() => void build()}>建置 L1</button>
        <button onClick={() => void exportPack()}>匯出</button>
        <div className="agent-state">
          <span className="green-dot" />
          工程代理
        </div>
        <div className="agent-state">
          <span className="green-dot" />
          Astra
        </div>
        <button onClick={() => setSettingsOpen(true)}>設定</button>
      </header>
      <section className="work-grid">
        <Viewer
          projectId={projectId}
          version={version}
          overlayVersion={overlayVersion}
          checks={checks}
          onChangeRequest={(object, time, text) => void submitChange(text, object, time)}
        />
        <aside className="side-panel">
          <nav className="tabs">
            {tabs.map((item) => (
              <button
                className={tab === item ? "active" : ""}
                key={item}
                onClick={() => setTab(item)}
              >
                {item}
              </button>
            ))}
          </nav>
          <div className="panel-content">
            {error && (
              <div className="error-card">
                <b>操作失敗</b>
                <p>{error}</p>
                <button
                  onClick={() => {
                    setError(undefined);
                    void refresh();
                  }}
                >
                  重新整理狀態
                </button>
              </div>
            )}
            {notice && <div className="notice">{notice}</div>}
            {tab === "資料" && (
              <DataPanel projectId={projectId} files={files} onFiles={supplement} />
            )}
            {tab === "檢查" && <ChecksPanel checks={checks} summary={latest?.checks} />}
            {tab === "問題" && <QuestionPanel projectId={projectId} />}
            {tab === "假設" && <AssumptionPanel projectId={projectId} />}
            {tab === "變更" && (
              <div className="compact-list">
                {changes.map((item) => (
                  <article key={item.id}>
                    <b>{item.id}</b>
                    <pre>{item.text}</pre>
                  </article>
                ))}
              </div>
            )}
            {tab === "任務" && (
              <div className="compact-list">
                {tasks.map((item) => (
                  <article key={item.id}>
                    <b>
                      {item.id} · {item.owner}
                    </b>
                    <p>{item.instruction}</p>
                    <span className={`status ${item.status}`}>{item.status}</span>
                  </article>
                ))}
              </div>
            )}
            {tab === "對話" && (
              <div className="empty-panel">
                <span>訊</span>
                <h2>代理對話</h2>
                <p>下方輸入可送給工程代理或 Astra；所有執行都成為可追蹤任務。</p>
              </div>
            )}
            {tab === "流程" && <ProcessPanel process={process} />}
          </div>
          <div className="agent-command">
            <textarea
              placeholder="輸入工程修改或 Astra 美化指令"
              value={command}
              onChange={(event) => setCommand(event.target.value)}
            />
            <div>
              <button onClick={() => void submitChange(command)}>工程代理</button>
              <button onClick={() => void runAstra()}>Astra</button>
            </div>
          </div>
        </aside>
      </section>
      {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)} />}
    </main>
  );
}

function ChecksPanel({
  checks,
  summary,
}: {
  checks: Check[];
  summary?: { red: number; yellow: number; green: number };
}) {
  return (
    <div>
      <div className="check-pills">
        <span className="red">{summary?.red ?? 0}</span>
        <span className="yellow">{summary?.yellow ?? 0}</span>
        <span className="green">{summary?.green ?? 0}</span>
      </div>
      <div className="compact-list">
        {checks.map((item) => (
          <article key={item.id} className={`check-${item.severity}`}>
            <b>
              {item.id} · {item.type}
            </b>
            <p>{item.detail}</p>
            <small>{item.objects?.join(" ↔ ")}</small>
          </article>
        ))}
      </div>
    </div>
  );
}
function ProcessPanel({ process }: { process?: Process }) {
  return (
    <div className="compact-list">
      {process?.stations.map((station) => (
        <article key={station.id}>
          <b>
            {station.id} · {station.name}
          </b>
          {process.steps
            .filter((step) => step.station === station.id)
            .map((step) => (
              <p key={step.id}>
                {step.id} — {step.actor}.{step.action} ({step.duration_s ?? 0}s)
              </p>
            ))}
        </article>
      ))}
    </div>
  );
}
function DataPanel({
  projectId,
  files,
  onFiles,
}: {
  projectId: string;
  files: InputEntry[];
  onFiles: (files: FileList | null) => void;
}) {
  return (
    <>
      <label className="supplement">
        <input type="file" multiple onChange={(event) => void onFiles(event.target.files)} />＋
        補充資料
      </label>
      <div className="file-grid">
        {files.map((file) => (
          <article key={file.path}>
            {file.kind === "product_photo" ? (
              <img
                src={`/api/projects/${encodeURIComponent(projectId)}/files/content?path=${encodeURIComponent(file.path)}`}
                alt={file.note || file.path}
              />
            ) : (
              <div className="document-icon">{file.path.split(".").at(-1)?.toUpperCase()}</div>
            )}
            <b title={file.path}>{file.path.split("/").at(-1)}</b>
            <span>{file.kind}</span>
            <small>{file.note || "無備註"}</small>
          </article>
        ))}
      </div>
    </>
  );
}
function QuestionPanel({ projectId }: { projectId: string }) {
  const [questions, setQuestions] = useState<Question[]>([]);
  const refresh = useCallback(
    () =>
      api<{ questions: Question[] }>(`/projects/${projectId}/questions`).then((data) =>
        setQuestions(data.questions),
      ),
    [projectId],
  );
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const update = async (item: Question, skip: boolean) => {
    await api(`/projects/${projectId}/questions/${item.id}`, {
      method: "POST",
      body: JSON.stringify(skip ? { skip: true } : { answer: item.answer ?? "" }),
    });
    await refresh();
  };
  return (
    <div className="compact-list">
      {questions.map((item) => (
        <article key={item.id} className={item.status !== "open" ? "resolved" : ""}>
          <b>{item.id}</b>
          <h3>{item.text}</h3>
          <p>{item.why}</p>
          {item.status === "open" && (
            <div className="answer-row">
              <input
                value={item.answer ?? ""}
                onChange={(event) =>
                  setQuestions((old) =>
                    old.map((value) =>
                      value.id === item.id ? { ...value, answer: event.target.value } : value,
                    ),
                  )
                }
              />
              <button onClick={() => void update(item, true)}>跳過</button>
              <button onClick={() => void update(item, false)}>回答</button>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}
function AssumptionPanel({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Assumption[]>([]);
  useEffect(() => {
    void api<{ assumptions: Assumption[] }>(`/projects/${projectId}/assumptions`).then((data) =>
      setItems(data.assumptions),
    );
  }, [projectId]);
  return (
    <div className="assumption-table">
      {items.map((item) => (
        <button key={item.id} className={item.status}>
          <b>{item.id}</b>
          <span>{item.text}</span>
          <small>{item.basis}</small>
        </button>
      ))}
    </div>
  );
}
function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  useEffect(() => {
    void api<Record<string, unknown>>("/settings").then(setSettings);
  }, []);
  const save = async () => {
    await api("/settings", { method: "PUT", body: JSON.stringify(settings) });
    onClose();
  };
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h2>CellForge 設定</h2>
        <label>
          工程代理模式
          <input
            value={String(settings.engineering_agent_mode ?? "")}
            onChange={(event) =>
              setSettings({ ...settings, engineering_agent_mode: event.target.value })
            }
          />
        </label>
        <label>
          Astra 模式
          <input
            value={String(settings.astra_agent_mode ?? "")}
            onChange={(event) => setSettings({ ...settings, astra_agent_mode: event.target.value })}
          />
        </label>
        <label>
          Astra 模型
          <input
            value={String(settings.astra_agent_model ?? "")}
            onChange={(event) =>
              setSettings({ ...settings, astra_agent_model: event.target.value })
            }
          />
        </label>
        <div>
          <button onClick={onClose}>取消</button>
          <button className="primary" onClick={() => void save()}>
            儲存
          </button>
        </div>
      </div>
    </div>
  );
}
