import { useRef, useState } from "react";
import { get, send, upload } from "../api/client";
import type { ImportResult, Job, RecipeSummary } from "../api/types";
import { useApp, usePolling } from "../app/context";
import { Layout } from "../components/Layout";
import { Card, Empty, ErrorBox, fmtTime, useLoad } from "../components/ui";

export function Imports() {
  const { t } = useApp();
  const [recipes] = useLoad(() => get<RecipeSummary[]>("/api/recipes"), []);
  const released = (recipes || []).flatMap((r) =>
    r.versions.filter((v) => v.status === "released").map((v) => ({ ...v, recipe_id: r.recipe_id })));
  const [recipePk, setRecipePk] = useState<number | null>(null);
  const [lot, setLot] = useState("");
  const [acq, setAcq] = useState("");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<ImportResult[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [status, setStatus] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const refreshJobs = () => get<Job[]>("/api/jobs", { status, limit: 200 }).then(setJobs).catch(setError);
  usePolling(refreshJobs, 3000, [status]);

  const doUpload = async (files: FileList | File[]) => {
    if (!recipePk || !files.length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f, f.name));
    fd.append("recipe_pk", String(recipePk));
    fd.append("lot_no", lot);
    fd.append("acquisition", acq);
    setBusy(true);
    setError(null);
    try {
      setResults(await upload<ImportResult[]>("/api/imports", fd));
      refreshJobs();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const action = async (id: number, what: "cancel" | "retry") => {
    try {
      await send("POST", `/api/jobs/${id}/${what}`);
      refreshJobs();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <Layout title={t("ui.nav.imports")}>
      <div className="stack">
        <Card title={t("ui.import.title")}>
          <div className="stack">
            <div className="form-grid">
              <label className="field">{t("ui.recipe")}
                <select value={recipePk ?? ""} onChange={(e) => setRecipePk(Number(e.target.value) || null)}>
                  <option value="">{t("ui.select")}</option>
                  {released.map((v) => <option key={v.id} value={v.id}>{v.recipe_id} v{v.version}</option>)}
                </select>
              </label>
              <label className="field">{t("ui.lot")}<input type="text" value={lot} onChange={(e) => setLot(e.target.value)} /></label>
              <label className="field">{t("ui.import.acquisition")}
                <input type="text" value={acq} placeholder="kv=90, power_w=5, frames=8" onChange={(e) => setAcq(e.target.value)} />
                <span className="hint">{t("ui.import.acquisition_hint")}</span>
              </label>
            </div>
            <div className={`dropzone ${over ? "over" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); doUpload(e.dataTransfer.files); }}>
              <div>{recipePk ? t("ui.import.drop") : t("ui.import.select_recipe_first")}</div>
              <div style={{ marginTop: 12 }}>
                <button className="btn primary" disabled={!recipePk || busy} onClick={() => input.current?.click()}>
                  {busy ? t("ui.working") : t("ui.import.choose")}
                </button>
                <input ref={input} type="file" multiple accept=".tif,.tiff,.png,.bmp,.jpg,.jpeg" hidden
                  onChange={(e) => e.target.files && doUpload(e.target.files)} />
              </div>
            </div>
            <ErrorBox error={error} />
            {results.length > 0 && (
              <table className="table">
                <tbody>
                  {results.map((r, i) => (
                    <tr key={i}><td className="mono">{r.file}</td>
                      <td>{r.error ? <span className="badge q-fail">{t(`error.${r.error}`)}</span> : <span className="badge q-pass">{t("ui.import.queued")}</span>}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
        <Card title={t("ui.jobs")} bodyClass=""
          actions={<select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("ui.all")}</option>
            {["queued", "running", "done", "failed", "cancelled"].map((s) => <option key={s} value={s}>{t(`job.${s}`)}</option>)}
          </select>}>
          {jobs.length === 0 ? <Empty /> : (
            <div className="table-wrap" style={{ maxHeight: 520 }}>
              <table className="table">
                <thead><tr><th>#</th><th>{t("ui.file")}</th><th>{t("ui.status")}</th><th>{t("ui.source")}</th>
                  <th>{t("ui.created")}</th><th>{t("ui.finished")}</th><th>{t("ui.error")}</th><th></th></tr></thead>
                <tbody>
                  {jobs.map((j) => (
                    <tr key={j.id}>
                      <td>{j.id}</td><td className="mono">{j.file_name}</td><td>{t(`job.${j.status}`)}</td>
                      <td>{t(`ui.source.${j.source}`, j.source)}</td><td>{fmtTime(j.created_at)}</td><td>{fmtTime(j.finished_at)}</td>
                      <td className="muted">{j.error ? t(`error.${j.error.split(":")[0]}`, j.error) : ""}</td>
                      <td>
                        {j.status === "queued" && <button className="btn small" onClick={() => action(j.id, "cancel")}>{t("ui.cancel")}</button>}
                        {(j.status === "failed" || j.status === "cancelled") && <button className="btn small" onClick={() => action(j.id, "retry")}>{t("ui.retry")}</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </Layout>
  );
}
