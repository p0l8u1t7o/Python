import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { api, inferKind, waitForJob } from "../api";
import type { Job, Question } from "../types";

type Upload = { file: File; kind: string; note: string };
const steps = ["基本資料", "上傳資料", "限制與偏好", "代理解析", "回答問題", "產生初版"];

export function Wizard({
  onComplete,
  onCancel,
}: {
  onComplete: (id: string) => void;
  onCancel?: () => void;
}) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({
    name: "軍規筆電 QC 線",
    customer: "",
    product: "Getac V110 系列 rugged notebook",
    description: "依現有品管資料規劃自動化 QC 五站產線。",
    robot_brand: "DENSO",
    takt: "45",
    width: "8000",
    depth: "4000",
    stations: "6",
    safety: "不可撞刮產品；護蓋逐門開關",
    free_text: "",
  });
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [projectId, setProjectId] = useState<string>();
  const [job, setJob] = useState<Job>();
  const [logs, setLogs] = useState<string[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [intakeSummary, setIntakeSummary] = useState("");
  const [checklistMap, setChecklistMap] = useState("");
  const [error, setError] = useState<string>();

  const patch = (key: string, value: string) => setForm((old) => ({ ...old, [key]: value }));
  const addFiles = (files: FileList | File[]) =>
    setUploads((old) => [
      ...old,
      ...Array.from(files).map((file) => ({ file, kind: inferKind(file), note: "" })),
    ]);
  const updateUpload = (index: number, change: Partial<Upload>) =>
    setUploads((old) => old.map((item, i) => (i === index ? { ...item, ...change } : item)));

  async function startIntake() {
    setError(undefined);
    setLogs(["建立案子 repo…"]);
    try {
      let id = projectId;
      if (!id) {
        const created = await api<{ id: string }>("/projects", {
          method: "POST",
          body: JSON.stringify({
            name: form.name,
            customer: form.customer,
            product: form.product,
            description: form.description,
            seed_example: "getac_qc",
            constraints: {
              robot_brand: form.robot_brand || null,
              takt_target_s: form.takt ? Number(form.takt) : null,
              footprint_mm:
                form.width && form.depth ? [Number(form.width), Number(form.depth)] : null,
              stations_max: form.stations ? Number(form.stations) : null,
              safety_notes: form.safety,
              free_text: form.free_text,
            },
          }),
        });
        id = created.id;
        setProjectId(id);
        for (let i = 0; i < uploads.length; i += 1) {
          const upload = uploads[i];
          const data = new FormData();
          data.append("file", upload.file);
          data.append("kind", upload.kind);
          data.append("note", upload.note);
          setLogs((old) => [...old, `上傳 ${i + 1}/${uploads.length}：${upload.file.name}`]);
          await api(`/projects/${id}/files`, { method: "POST", body: data });
        }
      }
      setLogs((old) => [...old, "啟動工程代理解析…"]);
      const submitted = await api<Job>(`/projects/${id}/intake`, { method: "POST" });
      setJob(submitted);
      const finished = await waitForJob(submitted.id, setJob, appendJobEvent(setLogs));
      if (finished.status !== "done") throw new Error(finished.error ?? "解析工作失敗");
      const payload = await api<{ questions: Question[] }>(`/projects/${id}/questions`);
      const [summary, checklist] = await Promise.all([
        api<{ markdown: string }>(`/projects/${id}/analysis/intake`),
        api<{ markdown: string }>(`/projects/${id}/analysis/checklist_map`),
      ]);
      setQuestions(payload.questions);
      setIntakeSummary(summary.markdown);
      setChecklistMap(checklist.markdown);
      setLogs((old) => [...old, "真實資料解析與問題驗證完成。"]);
      setStep(4);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function respond(question: Question, skip: boolean) {
    if (!projectId) return;
    await api(`/projects/${projectId}/questions/${question.id}`, {
      method: "POST",
      body: JSON.stringify(skip ? { skip: true } : { answer: question.answer ?? "" }),
    });
    setQuestions((old) =>
      old.map((item) =>
        item.id === question.id ? { ...item, status: skip ? "skipped" : "answered" } : item,
      ),
    );
  }

  async function skipAll() {
    if (!projectId || questions.length === 0) return;
    await api(`/projects/${projectId}/questions/${questions[0].id}`, {
      method: "POST",
      body: JSON.stringify({ skip_all: true }),
    });
    setQuestions((old) => old.map((item) => ({ ...item, status: "skipped" })));
  }

  async function build() {
    if (!projectId) return;
    setError(undefined);
    setLogs(["驗證工程資料…"]);
    try {
      const submitted = await api<Job>(`/projects/${projectId}/build`, { method: "POST" });
      setJob(submitted);
      const finished = await waitForJob(submitted.id, setJob, appendJobEvent(setLogs));
      if (finished.status !== "done") throw new Error(finished.error ?? "建置失敗");
      setLogs((old) => [...old, "STEP OCP 重讀、GLB 與 timeline 均已完成。"]);
      onComplete(projectId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  return (
    <main className="wizard-shell">
      <header className="wizard-header">
        <div>
          <span className="logo-mark">CF</span>
          <strong>建立 CellForge 案子</strong>
        </div>
        {onCancel && (
          <button className="ghost" onClick={onCancel}>
            關閉
          </button>
        )}
      </header>
      <nav className="stepper">
        {steps.map((label, i) => (
          <div className={i === step ? "active" : i < step ? "done" : ""} key={label}>
            <span>{i + 1}</span>
            <small>{label}</small>
          </div>
        ))}
      </nav>
      <section className="wizard-panel">
        {step === 0 && (
          <>
            <p className="eyebrow">STEP 01</p>
            <h1>先替這條產線命名。</h1>
            <div className="form-grid">
              <label className="wide">
                案名 *<input value={form.name} onChange={(e) => patch("name", e.target.value)} />
              </label>
              <label>
                客戶
                <input value={form.customer} onChange={(e) => patch("customer", e.target.value)} />
              </label>
              <label>
                產品名稱
                <input value={form.product} onChange={(e) => patch("product", e.target.value)} />
              </label>
              <label className="wide">
                需求敘述
                <textarea
                  rows={5}
                  value={form.description}
                  onChange={(e) => patch("description", e.target.value)}
                />
              </label>
            </div>
          </>
        )}
        {step === 1 && (
          <>
            <p className="eyebrow">STEP 02</p>
            <h1>把現有資料全部放進來。</h1>
            <label
              className="drop-zone"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                addFiles(e.dataTransfer.files);
              }}
            >
              <input
                type="file"
                multiple
                onChange={(e) => e.target.files && addFiles(e.target.files)}
              />
              <b>拖放檔案，或點此選取</b>
              <span>照片、PDF、Check List、CAD、工程圖皆可；也可零檔案繼續</span>
            </label>
            <div className="upload-list">
              {uploads.map((upload, index) => (
                <div className="upload-row" key={`${upload.file.name}-${index}`}>
                  <span className="file-icon">
                    {upload.file.name.split(".").at(-1)?.toUpperCase()}
                  </span>
                  <div>
                    <b>{upload.file.name}</b>
                    <small>{(upload.file.size / 1024 / 1024).toFixed(1)} MB</small>
                  </div>
                  <select
                    value={upload.kind}
                    onChange={(e) => updateUpload(index, { kind: e.target.value })}
                  >
                    <option value="product_photo">產品照片</option>
                    <option value="inspection_spec">檢驗規範</option>
                    <option value="checklist">Check List</option>
                    <option value="layout">廠房佈局</option>
                    <option value="cad">CAD</option>
                    <option value="drawing">工程圖</option>
                    <option value="text">文字</option>
                    <option value="other">其他</option>
                  </select>
                  <input
                    placeholder="備註"
                    value={upload.note}
                    onChange={(e) => updateUpload(index, { note: e.target.value })}
                  />
                  <button
                    className="icon-button"
                    onClick={() => setUploads((old) => old.filter((_, i) => i !== index))}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <p className="count">已選擇 {uploads.length} 個檔案</p>
          </>
        )}
        {step === 2 && (
          <>
            <p className="eyebrow">STEP 03</p>
            <h1>框出設計邊界。</h1>
            <div className="form-grid">
              <label>
                手臂品牌
                <input
                  value={form.robot_brand}
                  onChange={(e) => patch("robot_brand", e.target.value)}
                />
              </label>
              <label>
                節拍目標（秒）
                <input
                  type="number"
                  value={form.takt}
                  onChange={(e) => patch("takt", e.target.value)}
                />
              </label>
              <label>
                佔地長度（mm）
                <input
                  type="number"
                  value={form.width}
                  onChange={(e) => patch("width", e.target.value)}
                />
              </label>
              <label>
                佔地寬度（mm）
                <input
                  type="number"
                  value={form.depth}
                  onChange={(e) => patch("depth", e.target.value)}
                />
              </label>
              <label>
                站別上限
                <input
                  type="number"
                  value={form.stations}
                  onChange={(e) => patch("stations", e.target.value)}
                />
              </label>
              <label className="wide">
                安全需求
                <textarea value={form.safety} onChange={(e) => patch("safety", e.target.value)} />
              </label>
              <label className="wide">
                其他
                <textarea
                  value={form.free_text}
                  onChange={(e) => patch("free_text", e.target.value)}
                />
              </label>
            </div>
          </>
        )}
        {step === 3 && (
          <>
            <p className="eyebrow">STEP 04</p>
            <h1>讓工程流程先盤點資料。</h1>
            <p className="lead">
              Claude Code 會逐頁讀取 PDF、Check List 與所有照片，建立對照表和關鍵問題。
            </p>
            <button
              className="primary big"
              disabled={job?.status === "running"}
              onClick={() => void startIntake()}
            >
              開始解析
            </button>
            <LogPanel logs={logs} job={job} />
            {intakeSummary && <MarkdownPreview title="解析摘要" text={intakeSummary} />}
            {checklistMap && <MarkdownPreview title="Check List 對照" text={checklistMap} />}
          </>
        )}
        {step === 4 && (
          <>
            <p className="eyebrow">STEP 05</p>
            <h1>回答關鍵缺口，或採用預設。</h1>
            {intakeSummary && <MarkdownPreview title="解析摘要" text={intakeSummary} />}
            {checklistMap && <MarkdownPreview title="Check List 對照" text={checklistMap} />}
            <div className="question-list">
              {questions.map((question) => (
                <article
                  className={question.status !== "open" ? "question resolved" : "question"}
                  key={question.id}
                >
                  <span>{question.id}</span>
                  <h3>{question.text}</h3>
                  <p>為什麼問：{question.why}</p>
                  <small>跳過時假設：{question.default_if_skipped}</small>
                  {question.status === "open" ? (
                    <div className="answer-row">
                      <input
                        placeholder="輸入回答"
                        value={question.answer ?? ""}
                        onChange={(e) =>
                          setQuestions((old) =>
                            old.map((item) =>
                              item.id === question.id ? { ...item, answer: e.target.value } : item,
                            ),
                          )
                        }
                      />
                      <button onClick={() => void respond(question, true)}>跳過</button>
                      <button className="primary" onClick={() => void respond(question, false)}>
                        送出
                      </button>
                    </div>
                  ) : (
                    <b className="resolved-label">
                      已{question.status === "skipped" ? "跳過" : "回答"}
                    </b>
                  )}
                </article>
              ))}
            </div>
            <button className="ghost" onClick={() => void skipAll()}>
              全部跳過
            </button>
          </>
        )}
        {step === 5 && (
          <>
            <p className="eyebrow">STEP 06</p>
            <h1>產生第一版五站動畫。</h1>
            <p className="lead">
              建立 CadQuery Assembly、以 OCP XCAF 驗證 STEP 裝配樹，並輸出 GLB 與 55 秒 timeline。
            </p>
            <button
              className="primary big"
              disabled={job?.status === "running"}
              onClick={() => void build()}
            >
              產生初版
            </button>
            <LogPanel logs={logs} job={job} />
          </>
        )}
        {error && <div className="error-card">{error}</div>}
      </section>
      <footer className="wizard-actions">
        <button
          className="ghost"
          disabled={step === 0 || step >= 3}
          onClick={() => setStep((value) => value - 1)}
        >
          上一步
        </button>
        <span>{step + 1} / 6</span>
        {step < 3 ? (
          <button
            className="primary"
            disabled={step === 0 && !form.name.trim()}
            onClick={() => setStep((value) => value + 1)}
          >
            下一步
          </button>
        ) : step === 4 ? (
          <button
            className="primary"
            disabled={questions.some((question) => question.status === "open")}
            onClick={() => setStep(5)}
          >
            下一步
          </button>
        ) : (
          <span />
        )}
      </footer>
    </main>
  );
}

function appendJobEvent(setLogs: Dispatch<SetStateAction<string[]>>) {
  return (event: Record<string, unknown>) => {
    const message = typeof event.message === "string" ? event.message : undefined;
    if (message) setLogs((old) => [...old, message]);
  };
}

function MarkdownPreview({ title, text }: { title: string; text: string }) {
  return (
    <section className="analysis-preview">
      <h3>{title}</h3>
      <pre>{text}</pre>
    </section>
  );
}

function LogPanel({ logs, job }: { logs: string[]; job?: Job }) {
  if (!logs.length && !job) return null;
  return (
    <div className="log-panel">
      <header>
        <span className={job?.status === "running" ? "pulse" : "status-dot"} />
        {job?.status ?? "準備中"}
      </header>
      {logs.map((line, i) => (
        <p key={`${line}-${i}`}>{line}</p>
      ))}
    </div>
  );
}
