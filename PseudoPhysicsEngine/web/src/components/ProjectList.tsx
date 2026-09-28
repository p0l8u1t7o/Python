import { useState } from "react";
import { api } from "../api";
import type { ProjectSummary, TrashItem } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";

type Pending =
  | { kind: "delete"; project: ProjectSummary }
  | { kind: "purge"; item: TrashItem }
  | undefined;

export function ProjectList({
  projects,
  trash,
  onNew,
  onOpen,
  onChanged,
}: {
  projects: ProjectSummary[];
  trash: TrashItem[];
  onNew: () => void;
  onOpen: (id: string) => void;
  onChanged: () => Promise<void>;
}) {
  const [pending, setPending] = useState<Pending>();
  const [showTrash, setShowTrash] = useState(false);
  const [notice, setNotice] = useState<string>();

  const restore = async (item: TrashItem) => {
    try {
      const result = await api<{ id: string; renamed: boolean }>(
        `/trash/${encodeURIComponent(item.trash_id)}/restore`,
        { method: "POST" },
      );
      setNotice(
        result.renamed
          ? `已還原「${item.name}」；原 id 已被使用，改為 ${result.id}`
          : `已還原「${item.name}」`,
      );
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : String(reason));
    }
    await onChanged();
  };

  return (
    <main className="landing">
      <header className="brand-row">
        <div>
          <span className="logo-mark">CF</span>
          <strong>CellForge</strong>
        </div>
        <div className="brand-actions">
          <button className={showTrash ? "active" : ""} onClick={() => setShowTrash(!showTrash)}>
            回收區（{trash.length}）
          </button>
          <button className="primary" onClick={onNew}>
            ＋ 新建案子
          </button>
        </div>
      </header>
      <section className="hero">
        <p className="eyebrow">AUTOMATION FEASIBILITY STUDIO</p>
        <h1>
          把零散需求，鍛造成
          <br />
          能看、能驗證的產線。
        </h1>
        <p>本機工程工作區 · 所有狀態皆存於案子 repo</p>
      </section>
      {notice && (
        <p className="list-notice" role="status">
          {notice}
          <button className="ghost" onClick={() => setNotice(undefined)} aria-label="關閉訊息">
            ×
          </button>
        </p>
      )}
      {showTrash && (
        <section className="trash-panel" aria-label="回收區">
          <h2>回收區</h2>
          <p className="lead">
            刪除的案子保留在這裡，含所有版本與匯出檔；還原後回到案子列表，永久刪除則無法復原。
          </p>
          {trash.length === 0 ? (
            <p className="lead">回收區是空的。</p>
          ) : (
            trash.map((item) => (
              <article className="trash-row" key={item.trash_id}>
                <div>
                  <b>{item.name}</b>
                  <small>
                    {item.customer || "未填客戶"} · {item.versions} 個版本 · 刪除於{" "}
                    {new Date(item.deleted_at).toLocaleString("zh-TW")}
                  </small>
                </div>
                <div>
                  <button onClick={() => void restore(item)}>還原</button>
                  <button className="danger" onClick={() => setPending({ kind: "purge", item })}>
                    永久刪除
                  </button>
                </div>
              </article>
            ))
          )}
        </section>
      )}
      {projects.length === 0 && <p className="lead">目前沒有案子；可以新建，或從回收區還原。</p>}
      <section className="project-grid">
        {projects.map((project) => (
          <article className="project-card" key={project.id} onClick={() => onOpen(project.id)}>
            <div className="card-top">
              <span className="status-dot" />
              <span>{project.latest_version ?? "尚未建置"}</span>
              <button
                className="card-delete"
                title="刪除案子（移到回收區）"
                aria-label={`刪除案子 ${project.name}`}
                onClick={(event) => {
                  event.stopPropagation();
                  setPending({ kind: "delete", project });
                }}
              >
                刪除
              </button>
            </div>
            <h2>{project.name}</h2>
            <p>
              {project.customer || "未填客戶"} · {project.product || "未填產品"}
            </p>
            <div className="check-pills">
              <span className="red">{project.checks.red}</span>
              <span className="yellow">{project.checks.yellow}</span>
              <span className="green">{project.checks.green}</span>
            </div>
            <footer>
              <span>{new Date(project.modified).toLocaleString("zh-TW")}</span>
              <b>開啟 →</b>
            </footer>
          </article>
        ))}
      </section>
      {pending?.kind === "delete" && (
        <ConfirmDialog
          title="刪除案子"
          message={`確定刪除「${pending.project.name}」？案子會移到回收區，之後可以還原。`}
          confirmLabel="刪除"
          danger
          onCancel={() => setPending(undefined)}
          onConfirm={async () => {
            await api(`/projects/${encodeURIComponent(pending.project.id)}`, {
              method: "DELETE",
            });
            setPending(undefined);
            setNotice(`已將「${pending.project.name}」移到回收區`);
            await onChanged();
          }}
        />
      )}
      {pending?.kind === "purge" && (
        <ConfirmDialog
          title="永久刪除"
          message={`確定永久刪除「${pending.item.name}」？所有版本、匯出與日誌都會刪除，無法復原。`}
          confirmLabel="永久刪除"
          danger
          onCancel={() => setPending(undefined)}
          onConfirm={async () => {
            await api(`/trash/${encodeURIComponent(pending.item.trash_id)}`, {
              method: "DELETE",
            });
            setPending(undefined);
            setNotice(`已永久刪除「${pending.item.name}」`);
            await onChanged();
          }}
        />
      )}
    </main>
  );
}
