import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  fixModule,
  getLibraryModules,
  getModuleCheck,
  getModuleDetail,
  getProjectModules,
  moduleRenderUrl,
  promoteModule,
  recheckModule,
  waitForJob,
} from "../api";
import type {
  Assumption,
  InputEntry,
  LibraryModuleSummary,
  ModuleDetail,
  ModuleSummary,
  PartCheckResult,
  Project,
  Question,
} from "../types";
import { Viewer, type Check } from "./Viewer";
import { ModulePreview } from "./ModulePreview";

const tabs = ["資料", "檢查", "問題", "假設", "變更", "任務", "對話", "流程", "模組"] as const;
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
  const [focusedCheck, setFocusedCheck] = useState<Check>();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [changes, setChanges] = useState<Change[]>([]);
  const [process, setProcess] = useState<Process>();
  const [command, setCommand] = useState("");
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<string>();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [moduleImage, setModuleImage] = useState<{ id: string; url: string }>();
  const [placeholderInstances, setPlaceholderInstances] = useState<string[]>([]);
  const [inferredModuleCount, setInferredModuleCount] = useState(0);
  const [placeholderFilterToken, setPlaceholderFilterToken] = useState(0);
  const [agentSummary, setAgentSummary] = useState<string>();
  const [locatedModule, setLocatedModule] = useState<{ instanceId: string; token: number }>();

  const refresh = useCallback(async () => {
    const [projectData, fileData, taskData, changeData, processData, moduleData] =
      await Promise.all([
        api<Project>(`/projects/${projectId}`),
        api<{ files: InputEntry[] }>(`/projects/${projectId}/files`),
        api<Task[]>(`/projects/${projectId}/tasks`),
        api<Change[]>(`/projects/${projectId}/changes`),
        api<Process>(`/projects/${projectId}/process`),
        getProjectModules(projectId),
      ]);
    setProject(projectData);
    if (projectData.first_build_summary) setAgentSummary(projectData.first_build_summary);
    setFiles(fileData.files);
    setTasks(taskData);
    setChanges(changeData);
    setProcess(processData);
    setPlaceholderInstances(
      moduleData.modules
        .filter((module) => module.placeholder)
        .flatMap((module) => module.usages.map((usage) => usage.instance_id)),
    );
    setInferredModuleCount(
      moduleData.modules
        .flatMap((module) => module.usages)
        .filter((usage) => usage.trust === "inferred").length,
    );
    setVersion((old) => old ?? projectData.versions.at(-1)?.id);
  }, [projectId]);
  useEffect(() => {
    void refresh().catch((reason) => setError(String(reason)));
  }, [refresh]);
  useEffect(() => {
    setFocusedCheck(undefined);
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
    return finished;
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
      const finished = await runJob(job.id, "L1 建置 + Astra");
      const summary = finished.result?.summary;
      if (typeof summary === "string") setAgentSummary(summary);
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
      setExportOpen(false);
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
        <button onClick={() => setExportOpen(true)}>匯出</button>
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
          focusedCheck={focusedCheck}
          locatedModule={locatedModule}
          onCheckSelect={setFocusedCheck}
          onChangeRequest={(object, time, text) => void submitChange(text, object, time)}
        />
        {moduleImage && (
          <div
            className="module-image-overlay"
            role="dialog"
            aria-label={`${moduleImage.id} 三視圖`}
          >
            <button onClick={() => setModuleImage(undefined)}>關閉</button>
            <img src={moduleImage.url} alt={`${moduleImage.id} 三視圖與等角視圖`} />
          </div>
        )}
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
            {tab === "檢查" && (
              <ChecksPanel
                checks={checks}
                summary={latest?.checks}
                placeholderInstances={placeholderInstances}
                onPlaceholder={() => {
                  setPlaceholderFilterToken((value) => value + 1);
                  setTab("模組");
                }}
                onSelect={setFocusedCheck}
              />
            )}
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
            {tab === "對話" && <ChatPanel summary={agentSummary} />}
            {tab === "流程" && <ProcessPanel process={process} />}
            {tab === "模組" && (
              <ModulePanel
                projectId={projectId}
                placeholderFilterToken={placeholderFilterToken}
                onEnlarge={(id, url) => setModuleImage({ id, url })}
                onLocate={(instanceId) =>
                  setLocatedModule((current) => ({
                    instanceId,
                    token: (current?.token ?? 0) + 1,
                  }))
                }
                onWorkspaceRefresh={refresh}
              />
            )}
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
      {exportOpen && (
        <ExportDialog
          projectId={projectId}
          inferredModuleCount={inferredModuleCount}
          placeholderCount={placeholderInstances.length}
          onClose={() => setExportOpen(false)}
          onConfirm={() => void exportPack()}
        />
      )}
    </main>
  );
}

const moduleCategories = [
  ["frame", "機架"],
  ["conveying", "輸送"],
  ["handling", "搬運"],
  ["fixturing", "治具"],
  ["vision", "視覺"],
  ["safety", "安全"],
  ["electrical", "電控"],
  ["material_handling", "物料處理"],
] as const;

const checkLabels: Record<string, string> = {
  "6.1": "尺寸依據",
  "6.2": "安裝介面",
  "6.3": "具名子零件",
  "6.4": "座標框架",
  "6.5": "運動軸",
  "6.6": "碰撞體膨脹",
  "6.7": "工程色",
  "6.8": "參數範圍",
  "6.9": "三角面數",
  "6.10": "最低點高度",
};

type ModuleBrowserRow = {
  id: string;
  source: "project" | "library";
  category: string;
  summary: string;
  status: "draft" | "production";
  usages: ModuleSummary["usages"];
  check: ModuleSummary["check"];
};

function emptyCheck(id: string): ModuleSummary["check"] {
  return { status: "not_checked", cache_key: `未檢查-${id}` };
}

function checkBadge(check: ModuleSummary["check"]): { text: string; tone: string } {
  const failures = check.counts?.fail ?? 0;
  const warnings = check.counts?.warn ?? 0;
  if (failures > 0) return { text: `✖ ${failures} 失敗`, tone: "fail" };
  if (warnings > 0) return { text: `⚠ ${warnings} 警告`, tone: "warn" };
  if (check.status === "passed") return { text: "✔ 通過", tone: "pass" };
  return { text: "— 未檢查", tone: "unchecked" };
}

function displayValue(value: unknown): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function ModulePanel({
  projectId,
  placeholderFilterToken,
  onEnlarge,
  onLocate,
  onWorkspaceRefresh,
}: {
  projectId: string;
  placeholderFilterToken: number;
  onEnlarge: (id: string, url: string) => void;
  onLocate: (instanceId: string) => void;
  onWorkspaceRefresh: () => Promise<void>;
}) {
  const [manifest, setManifest] = useState<LibraryModuleSummary[]>([]);
  const [projectModules, setProjectModules] = useState<ModuleSummary[]>([]);
  const [selected, setSelected] = useState<string>();
  const [detail, setDetail] = useState<ModuleDetail>();
  const [check, setCheck] = useState<PartCheckResult>();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [problemsOnly, setProblemsOnly] = useState(false);
  const [placeholdersOnly, setPlaceholdersOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [actionMessage, setActionMessage] = useState<string>();
  const [actionRunning, setActionRunning] = useState(false);
  const [assetRevision, setAssetRevision] = useState(0);

  const refreshModules = useCallback(async () => {
    setLoading(true);
    try {
      const [libraryData, projectData] = await Promise.all([
        getLibraryModules(),
        getProjectModules(projectId),
      ]);
      setManifest(libraryData.modules);
      setProjectModules(projectData.modules);
      setError(undefined);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void refreshModules().catch((reason) =>
      setError(reason instanceof Error ? reason.message : String(reason)),
    );
  }, [refreshModules]);

  useEffect(() => {
    if (placeholderFilterToken <= 0) return;
    setSelected(undefined);
    setSearch("");
    setCategory("all");
    setProblemsOnly(false);
    setPlaceholdersOnly(true);
  }, [placeholderFilterToken]);

  const refreshSelected = useCallback(
    async (moduleId: string) => {
      const [detailData, checkData] = await Promise.all([
        getModuleDetail(projectId, moduleId),
        getModuleCheck(projectId, moduleId),
      ]);
      setDetail(detailData);
      setCheck(checkData);
      setProjectModules((old) =>
        old.map((item) =>
          item.id === moduleId
            ? {
                ...item,
                check: {
                  status: checkData.passed ? "passed" : "failed",
                  passed: checkData.passed,
                  counts: {
                    fail: checkData.items.filter((entry) => entry.severity === "fail").length,
                    warn: checkData.items.filter((entry) => entry.severity === "warn").length,
                    info: checkData.items.filter((entry) => entry.severity === "info").length,
                  },
                  cache_key: checkData.cache.key,
                },
              }
            : item,
        ),
      );
      setError(undefined);
    },
    [projectId],
  );

  useEffect(() => {
    if (!selected) {
      setDetail(undefined);
      setCheck(undefined);
      setActionMessage(undefined);
      return;
    }
    setLoading(true);
    refreshSelected(selected)
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setLoading(false));
  }, [refreshSelected, selected]);

  async function runModuleAction(action: "fix" | "recheck" | "promote") {
    if (!selected) return;
    const labels = { fix: "代理修正", recheck: "重新檢查", promote: "收進模組庫" };
    const label = labels[action];
    setActionRunning(true);
    setActionMessage(`${label}已排程…`);
    setError(undefined);
    try {
      const job =
        action === "fix"
          ? await fixModule(projectId, selected)
          : action === "promote"
            ? await promoteModule(projectId, selected)
            : await recheckModule(projectId, selected);
      if ("change_id" in job && "task_id" in job)
        setActionMessage(`已建立 ${String(job.change_id)}／${String(job.task_id)}，工程代理執行中…`);
      await onWorkspaceRefresh();
      const finished = await waitForJob(job.id, (current) =>
        setActionMessage(`${label}：${current.status}`),
      );
      if (finished.status !== "done") throw new Error(finished.error ?? `${label}失敗`);
      await Promise.all([
        refreshModules(),
        refreshSelected(selected),
        onWorkspaceRefresh(),
      ]);
      setAssetRevision((value) => value + 1);
      setActionMessage(`${label}完成`);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      setActionMessage(`${label}失敗`);
    } finally {
      setActionRunning(false);
    }
  }

  const rows = useMemo(() => {
    const byId = new Map(projectModules.map((item) => [item.id, item]));
    const libraryRows: ModuleBrowserRow[] = manifest.map((item) => {
      const projectItem = byId.get(item.id);
      return {
        id: item.id,
        source: "library",
        category: item.category,
        summary: item.summary,
        status: item.status,
        usages: projectItem?.usages ?? [],
        check: projectItem?.check ?? emptyCheck(item.id),
      };
    });
    const localRows: ModuleBrowserRow[] = projectModules
      .filter((item) => item.source === "project")
      .map((item) => ({ ...item, status: "production" }));
    return [...localRows, ...libraryRows];
  }, [manifest, projectModules]);

  const placeholderCount = rows.filter((item) => item.status === "draft").length;
  const filtered = rows.filter((item) => {
    const term = search.trim().toLocaleLowerCase("zh-TW");
    const badge = checkBadge(item.check);
    return (
      (!term || `${item.id} ${item.summary}`.toLocaleLowerCase("zh-TW").includes(term)) &&
      (category === "all" || item.category === category) &&
      (!problemsOnly || badge.tone === "fail" || badge.tone === "warn") &&
      (!placeholdersOnly || item.status === "draft")
    );
  });

  if (selected && detail && check) {
    return (
      <ModuleDetailView
        detail={detail}
        check={check}
        projectId={projectId}
        assetRevision={assetRevision}
        actionMessage={actionMessage}
        actionRunning={actionRunning}
        onBack={() => setSelected(undefined)}
        onEnlarge={onEnlarge}
        onLocate={onLocate}
        onAction={runModuleAction}
      />
    );
  }

  return (
    <div className="module-panel">
      <div className="module-toolbar">
        <input
          aria-label="搜尋模組"
          placeholder="搜尋模組…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          aria-label="模組類別"
          value={category}
          onChange={(event) => setCategory(event.target.value)}
        >
          <option value="all">所有類別</option>
          <option value="project">本案自建</option>
          {moduleCategories.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <label className="problem-toggle">
          <input
            type="checkbox"
            checked={problemsOnly}
            onChange={(event) => setProblemsOnly(event.target.checked)}
          />
          只看有問題
        </label>
      </div>
      {error && <div className="module-load-error">載入失敗：{error}</div>}
      {loading && <div className="module-loading">正在載入模組…</div>}
      <ModuleGroup
        title="本案自建"
        rows={filtered.filter((item) => item.source === "project")}
        onSelect={setSelected}
      />
      {moduleCategories.map(([id, name]) => (
        <ModuleGroup
          key={id}
          title={name}
          rows={filtered.filter((item) => item.source === "library" && item.category === id)}
          onSelect={setSelected}
        />
      ))}
      <button
        className={`module-placeholder-count ${placeholderCount > 0 ? "has-placeholders" : ""}`}
        onClick={() => {
          setPlaceholdersOnly((old) => !old);
          setProblemsOnly(false);
          setCategory("all");
        }}
      >
        本版佔位模組：{placeholderCount}
      </button>
    </div>
  );
}

function ModuleGroup({
  title,
  rows,
  onSelect,
}: {
  title: string;
  rows: ModuleBrowserRow[];
  onSelect: (id: string) => void;
}) {
  return (
    <section className="module-group">
      <h3>
        {title}
        <span>{rows.length}</span>
      </h3>
      {rows.length === 0 && <p className="module-group-empty">目前沒有符合的模組</p>}
      {rows.map((item) => {
        const badge = checkBadge(item.check);
        const usage = item.status === "draft" ? "⬚" : item.usages.length > 0 ? "●" : "○";
        return (
          <button key={item.id} className="module-row" onClick={() => onSelect(item.id)}>
            <span className={`module-usage ${item.usages.length > 0 ? "used" : ""}`}>{usage}</span>
            <span>
              <b>{item.id}</b>
              <small>{item.summary}</small>
            </span>
            <em className={`module-badge ${badge.tone}`}>{badge.text}</em>
          </button>
        );
      })}
    </section>
  );
}

function ModuleDetailView({
  detail,
  check,
  projectId,
  assetRevision,
  actionMessage,
  actionRunning,
  onBack,
  onEnlarge,
  onLocate,
  onAction,
}: {
  detail: ModuleDetail;
  check: PartCheckResult;
  projectId: string;
  assetRevision: number;
  actionMessage?: string;
  actionRunning: boolean;
  onBack: () => void;
  onEnlarge: (id: string, url: string) => void;
  onLocate: (instanceId: string) => void;
  onAction: (action: "fix" | "recheck" | "promote") => Promise<void>;
}) {
  const renderUrl = `${moduleRenderUrl(projectId, detail.id)}?revision=${assetRevision}`;
  const findings = new Map(check.items.map((item) => [item.index, item]));
  const frameFinding = findings.get("6.4");
  const distances = (frameFinding?.values.surface_distance_mm ?? {}) as Record<string, number>;
  const warningDistance = Number(
    frameFinding?.values.surface_warning_mm ?? Number.POSITIVE_INFINITY,
  );
  const warnedFrames = new Set(
    frameFinding?.severity === "warn"
      ? Object.entries(distances)
          .filter(([, distance]) => distance > warningDistance)
          .map(([name]) => name)
      : [],
  );
  const properties = detail.params_schema.properties ?? {};
  const failures = check.items.filter((item) => item.severity === "fail").length;
  const actionable = check.items.some((item) => ["fail", "warn"].includes(item.severity));
  const locatedInstance = detail.usages[0]?.instance_id;
  return (
    <div className="module-detail">
      <header>
        <button onClick={onBack}>← 返回清單</button>
        <div>
          <h2>{detail.id}</h2>
          <span>{detail.source === "project" ? "本案自建" : "共用模組庫"}</span>
        </div>
      </header>
      <div className="module-actions" aria-label="模組動作列">
        <button
          disabled={actionRunning || !actionable}
          title={actionable ? "依檢查結果建立 CR 並派工程代理" : "目前沒有失敗或警告"}
          onClick={() => void onAction("fix")}
        >
          請代理修正
        </button>
        <button disabled={actionRunning} onClick={() => void onAction("recheck")}>
          重新檢查
        </button>
        <button
          disabled={actionRunning || !locatedInstance}
          title={locatedInstance ? `定位 ${locatedInstance}` : "本案尚未使用此模組"}
          onClick={() => locatedInstance && onLocate(locatedInstance)}
        >
          在場景中定位
        </button>
        {detail.source === "project" && (
          <button
            disabled={actionRunning || failures > 0}
            title={failures > 0 ? "仍有失敗項目，不可收進庫" : "通過失敗項檢查，可收進共用庫"}
            onClick={() => void onAction("promote")}
          >
            收進庫
          </button>
        )}
        {actionMessage && <span>{actionMessage}</span>}
      </div>
      <button
        className="module-render-card"
        onClick={() => onEnlarge(detail.id, renderUrl)}
        aria-label="放大三視圖"
      >
        <img src={renderUrl} alt={`${detail.id} 的三視圖與等角視圖`} />
        <span>點擊放大三視圖</span>
      </button>
      <ModulePreview
        projectId={projectId}
        moduleId={detail.id}
        axes={detail.axes}
        frames={detail.frames}
        assetRevision={assetRevision}
      />
      <DetailSection title="模組檢查">
        <div className="module-check-list">
          {Object.entries(checkLabels).map(([index, label]) => {
            const item = findings.get(index);
            const severity = index === "6.10" ? "info" : (item?.severity ?? "pass");
            return (
              <article key={index} className={`module-check-item ${severity}`}>
                <b>
                  {severity === "fail"
                    ? "✖"
                    : severity === "warn"
                      ? "⚠"
                      : severity === "info"
                        ? "●"
                        : "✔"}{" "}
                  {index} {label}
                </b>
                <p>{item?.message ?? "未發現問題"}</p>
              </article>
            );
          })}
        </div>
      </DetailSection>
      <DetailSection title="參數">
        <table>
          <thead>
            <tr>
              <th>名稱</th>
              <th>本案實際值</th>
              <th>允許範圍</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(properties).map(([name, schema]) => {
              const actual = detail.usages.length
                ? detail.usages.map(
                    (usage) =>
                      `${usage.instance_id}: ${displayValue(usage.params[name] ?? detail.params[name])}`,
                  )
                : [displayValue(detail.params[name] ?? schema.default)];
              const limits =
                schema.minimum === undefined && schema.maximum === undefined
                  ? (schema.type ?? "—")
                  : `${schema.minimum ?? "—"} ～ ${schema.maximum ?? "—"}`;
              return (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{actual.join("；")}</td>
                  <td>{limits}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </DetailSection>
      <DetailSection title="Frames">
        <table>
          <thead>
            <tr>
              <th>名稱</th>
              <th>XYZ</th>
              <th>連結</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(detail.frames).map(([name, frame]) => (
              <tr key={name} className={warnedFrames.has(name) ? "frame-warning" : ""}>
                <td>
                  {warnedFrames.has(name) ? "⚠ " : ""}
                  {name}
                </td>
                <td>{frame.xyz.join(", ")}</td>
                <td>{frame.link ?? "base"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </DetailSection>
      <DetailSection title="Axes">
        {detail.axes.length === 0 ? (
          <p className="module-none">無運動軸</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>id／型式</th>
                <th>父 → 子</th>
                <th>範圍</th>
              </tr>
            </thead>
            <tbody>
              {detail.axes.map((axis) => (
                <tr key={axis.id}>
                  <td>
                    {axis.id}
                    <small>{axis.type}</small>
                  </td>
                  <td>
                    {axis.parent} → {axis.child ?? axis.id}
                  </td>
                  <td>{(axis.range_deg ?? axis.range_mm)?.join(" ～ ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </DetailSection>
      <DetailSection title="尺寸依據">
        <p className="module-basis">{detail.meta.basis}</p>
      </DetailSection>
      <DetailSection title="本案使用">
        {detail.usages.length === 0 ? (
          <p className="module-none">本案尚未使用</p>
        ) : (
          <ul className="module-usages">
            {detail.usages.map((usage) => (
              <li key={usage.instance_id}>
                <b>{usage.instance_id}</b>
                <span>{usage.machine_id}</span>
              </li>
            ))}
          </ul>
        )}
      </DetailSection>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="module-detail-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function ChatPanel({ summary }: { summary?: string }) {
  return (
    <div className="chat-panel">
      <header>
        <span>訊</span>
        <div>
          <h2>代理對話</h2>
          <p>下方輸入可送給工程代理或 Astra；所有執行都成為可追蹤任務。</p>
        </div>
      </header>
      {summary ? (
        <section className="agent-summary">
          <b>首次建置摘要</b>
          <pre>{summary}</pre>
        </section>
      ) : (
        <p className="module-none">尚無首次建置摘要。</p>
      )}
    </div>
  );
}

function ExportDialog({
  projectId,
  inferredModuleCount,
  placeholderCount,
  onClose,
  onConfirm,
}: {
  projectId: string;
  inferredModuleCount: number;
  placeholderCount: number;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const [inferredCount, setInferredCount] = useState<number>();
  useEffect(() => {
    void api<{ assumptions: Assumption[] }>(`/projects/${projectId}/assumptions`)
      .then((data) =>
        setInferredCount(data.assumptions.filter((item) => item.status === "active").length),
      )
      .catch(() => setInferredCount(0));
  }, [projectId]);
  return (
    <div className="modal-backdrop">
      <div className="modal export-dialog" role="dialog" aria-label="匯出交付包">
        <h2>匯出完整交付包</h2>
        <p>將以目前版本建立工程交付檔案；請先確認尚未定案的內容。</p>
        <div className="export-readiness">
          <span>仍為推估的項目數</span>
          <b>{inferredCount === undefined ? "…" : inferredCount + inferredModuleCount}</b>
          <span>佔位模組數</span>
          <b className={placeholderCount > 0 ? "amber" : ""}>{placeholderCount}</b>
        </div>
        {placeholderCount > 0 && (
          <p className="export-warning">佔位幾何尚未替換，不應視為工程定案。</p>
        )}
        <div>
          <button onClick={onClose}>取消</button>
          <button className="primary" onClick={onConfirm}>
            仍要匯出
          </button>
        </div>
      </div>
    </div>
  );
}

function ChecksPanel({
  checks,
  summary,
  placeholderInstances,
  onPlaceholder,
  onSelect,
}: {
  checks: Check[];
  summary?: { red: number; yellow: number; green: number };
  placeholderInstances: string[];
  onPlaceholder: () => void;
  onSelect: (check: Check) => void;
}) {
  return (
    <div>
      <div className="check-pills">
        <span className="red">{summary?.red ?? 0}</span>
        <span className="yellow">{summary?.yellow ?? 0}</span>
        <span className="green">{summary?.green ?? 0}</span>
      </div>
      <div className="compact-list">
        {placeholderInstances.length > 0 && (
          <button className="check-row check-info" onClick={onPlaceholder}>
            <b>ⓘ 佔位模組仍在使用</b>
            <p>
              本案有 {placeholderInstances.length} 個佔位模組：
              {placeholderInstances.join("、")}。點此查看模組清單。
            </p>
          </button>
        )}
        {checks.map((item) => (
          <button
            key={item.id}
            className={`check-row check-${item.severity}`}
            onClick={() => onSelect(item)}
          >
            <b>
              {item.id} · {item.type}
            </b>
            <p>{item.detail}</p>
            <small>{item.objects?.join(" ↔ ")}</small>
          </button>
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
