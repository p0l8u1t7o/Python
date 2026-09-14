import type { ProjectSummary } from "../types";

export function ProjectList({
  projects,
  onNew,
  onOpen,
}: {
  projects: ProjectSummary[];
  onNew: () => void;
  onOpen: (id: string) => void;
}) {
  return (
    <main className="landing">
      <header className="brand-row">
        <div>
          <span className="logo-mark">CF</span>
          <strong>CellForge</strong>
        </div>
        <button className="primary" onClick={onNew}>
          ＋ 新建案子
        </button>
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
      <section className="project-grid">
        {projects.map((project) => (
          <article className="project-card" key={project.id} onClick={() => onOpen(project.id)}>
            <div className="card-top">
              <span className="status-dot" />
              <span>{project.latest_version ?? "尚未建置"}</span>
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
    </main>
  );
}
