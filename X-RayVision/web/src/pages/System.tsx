import { useRef, useState } from "react";
import { get, send, upload } from "../api/client";
import { useApp, usePolling } from "../app/context";
import { Layout } from "../components/Layout";
import { Card, ErrorBox, Modal, fmt, fmtTime, useLoad } from "../components/ui";

interface Settings {
  retention_days: number | null;
  disk_warn_gb: number;
  archive_originals: boolean;
  data_dir: string;
  workers: number;
  gpu_inference: boolean;
  inference: { installed: boolean; providers: string[]; version: string | null };
}

interface LicenseStatus {
  state: string;
  analysis_allowed: boolean;
  machine_code: string;
  install_id: string;
  license_id?: string;
  customer?: string;
  starts?: string;
  expires?: string;
  grace_days?: number;
  days_left?: number;
  modules?: string[];
  warn?: boolean;
  enforced: boolean;
}

interface UpdateOverview {
  current: string;
  running: string;
  supported: boolean;
  installed: { version: string; released_at?: string; notes?: Record<string, string>; staged_at?: string }[];
  rollback_to: { version: string; snapshot_at: string }[];
  status: { state: string; action: string; version: string; from_version?: string; step?: string; reason?: string; updated_at?: string } | null;
  history: { action: string; from_version: string; to_version: string; result: string; actor?: string; at: string; reason?: string }[];
}

interface Archive {
  name: string;
  created_at: string;
  from_version: string;
  counts: Record<string, number>;
  imported: boolean;
}

export function SystemPage() {
  const { t, system } = useApp();
  return (
    <Layout title={t("ui.nav.system")}>
      <div className="stack">
        <DiskAndRetention />
        <InferenceCard />
        <LicenseCard />
        <UpdatesCard />
        <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>
          {t("ui.software_version")} {system?.version} · {t("ui.system.schema")} {system?.schema_version}
        </div>
      </div>
    </Layout>
  );
}

// ---------------------------------------------------------------------------
function DiskAndRetention() {
  const { t, system } = useApp();
  const [s, error, reload] = useLoad(() => get<Settings>("/api/settings"), []);
  const [draft, setDraft] = useState<{ retention: string; warn: string } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [msg, setMsg] = useState("");
  const d = system?.disk;
  if (!s) return <Card title={t("ui.system.storage")}><ErrorBox error={error} /></Card>;
  const cur = draft ?? { retention: s.retention_days ? String(s.retention_days) : "", warn: String(s.disk_warn_gb) };
  const save = async () => {
    try {
      await send("PUT", "/api/settings", { retention_days: cur.retention ? Number(cur.retention) : null, disk_warn_gb: Number(cur.warn) });
      setDraft(null);
      setErr(null);
      setMsg(t("ui.saved"));
      reload();
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <Card title={t("ui.system.storage")}>
      <div className="stack">
        {d && (
          <div>
            <div className="row">
              <span>{t("ui.system.disk_free")} <b>{fmt(d.free_gb, 1)} GB</b> / {fmt(d.total_gb, 1)} GB</span>
              {d.low && <span className="badge q-fail">{t("ui.system.disk_low")}</span>}
            </div>
            <div style={{ height: 8, background: "var(--surface-3)", borderRadius: 4, marginTop: 6 }}>
              <div style={{ width: `${d.used_ratio * 100}%`, height: 8, borderRadius: 4, background: d.low ? "var(--j-fail)" : "var(--accent)" }} />
            </div>
          </div>
        )}
        <dl className="kv">
          <dt>{t("ui.system.data_dir")}</dt><dd className="mono">{s.data_dir}</dd>
          <dt>{t("ui.system.archive_originals")}</dt><dd>{s.archive_originals ? t("ui.enabled") : t("ui.disabled")}</dd>
          <dt>{t("ui.system.workers")}</dt><dd>{s.workers}</dd>
        </dl>
        <div className="form-grid">
          <label className="field">{t("ui.system.retention_days")}
            <input type="number" min={1} value={cur.retention} placeholder={t("ui.system.retention_keep")}
              onChange={(e) => setDraft({ ...cur, retention: e.target.value })} />
            <span className="hint">{t("ui.system.retention_hint")}</span>
          </label>
          <label className="field">{t("ui.system.disk_warn")} (GB)
            <input type="number" min={0} value={cur.warn} onChange={(e) => setDraft({ ...cur, warn: e.target.value })} />
          </label>
        </div>
        <div className="row">
          <span className="spacer" />
          {msg && <span className="muted">{msg}</span>}
          <button className="btn primary" disabled={!draft} onClick={save}>{t("ui.save")}</button>
        </div>
        <ErrorBox error={err} />
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// 深度學習推論：GPU 預設關閉 (設備可能用 GPU 做 3D 重建)
function InferenceCard() {
  const { t } = useApp();
  const [s, error, reload] = useLoad(() => get<Settings>("/api/settings"), []);
  const [err, setErr] = useState<unknown>(null);
  if (!s) return <Card title={t("ui.inference.title")}><ErrorBox error={error} /></Card>;
  const gpuAvail = s.inference.providers.includes("DmlExecutionProvider");
  const toggle = async (v: boolean) => {
    try {
      await send("PUT", "/api/settings", { gpu_inference: v });
      setErr(null);
      reload();
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <Card title={t("ui.inference.title")}>
      <div className="stack">
        <div className="muted">{t("ui.inference.hint")}</div>
        <dl className="kv">
          <dt>{t("ui.inference.runtime")}</dt>
          <dd>{s.inference.installed ? `ONNX Runtime ${s.inference.version}` : t("ui.inference.not_installed")}</dd>
          <dt>{t("ui.inference.gpu_available")}</dt><dd>{gpuAvail ? t("ui.yes") : t("ui.no")}</dd>
        </dl>
        <label className="check">
          <input type="checkbox" checked={s.gpu_inference} disabled={!gpuAvail} onChange={(e) => toggle(e.target.checked)} />
          {t("ui.inference.use_gpu")}
        </label>
        <ErrorBox error={err} />
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
function LicenseCard() {
  const { t, refreshAuth } = useApp();
  const [st, error, reload] = useLoad(() => get<LicenseStatus>("/api/license"), []);
  const [err, setErr] = useState<unknown>(null);
  const [confirmDeact, setConfirmDeact] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const doImport = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f, f.name);
    try {
      await upload("/api/license/import", fd);
      setErr(null);
      reload();
      refreshAuth();
    } catch (e) {
      setErr(e);
    }
  };
  const deactivate = async () => {
    setConfirmDeact(false);
    try {
      const res = await fetch("/api/license/deactivate", { method: "POST" });
      if (!res.ok) throw new Error(String(res.status));
      downloadBlob(await res.blob(), "license_deactivation.xrvdeact");
      reload();
      refreshAuth();
    } catch (e) {
      setErr(e);
    }
  };
  const cls = !st ? "" : st.state === "valid" ? "q-pass" : st.state === "grace" ? "q-warn" : "q-fail";
  return (
    <Card title={t("ui.license.title")}>
      <div className="stack">
        <ErrorBox error={error || err} />
        {st && (
          <>
            <div className="row">
              <span className={`badge ${cls}`}>{t(`license.${st.state}`)}</span>
              {!st.enforced && <span className="muted">{t("ui.license.not_enforced")}</span>}
              {st.days_left !== undefined && st.state === "valid" && <span className="muted">{t("ui.license.days_left").replace("{n}", String(st.days_left))}</span>}
            </div>
            <dl className="kv">
              <dt>{t("ui.license.machine_code")}</dt><dd className="mono">{st.machine_code}</dd>
              {st.customer && <><dt>{t("ui.license.customer")}</dt><dd>{st.customer}</dd></>}
              {st.license_id && <><dt>{t("ui.license.id")}</dt><dd className="mono">{st.license_id}</dd></>}
              {st.expires && <><dt>{t("ui.license.period")}</dt><dd>{fmtTime(st.starts)} ~ {fmtTime(st.expires)}</dd></>}
              {st.grace_days !== undefined && st.license_id && <><dt>{t("ui.license.grace")}</dt><dd>{st.grace_days}</dd></>}
              {st.modules && st.license_id && <><dt>{t("ui.license.modules")}</dt><dd>{st.modules.map((m) => m === "*" ? t("ui.license.all_modules") : t(`module.${m}`, m)).join("、")}</dd></>}
            </dl>
            <div className="alert info">{t("ui.license.steps")}</div>
            <div className="row">
              <a className="btn" href="/api/license/request">{t("ui.license.download_request")}</a>
              <button className="btn primary" onClick={() => file.current?.click()}>{t("ui.license.import")}</button>
              <input ref={file} type="file" accept=".xrvlic,.json" hidden onChange={(e) => e.target.files?.[0] && doImport(e.target.files[0])} />
              <span className="spacer" />
              {st.license_id && st.state !== "deactivated" && <button className="btn danger" onClick={() => setConfirmDeact(true)}>{t("ui.license.deactivate")}</button>}
            </div>
          </>
        )}
      </div>
      {confirmDeact && (
        <Modal title={t("ui.license.deactivate")} onClose={() => setConfirmDeact(false)}
          footer={<><button className="btn" onClick={() => setConfirmDeact(false)}>{t("ui.cancel")}</button>
            <button className="btn danger" onClick={deactivate}>{t("ui.confirm")}</button></>}>
          <p>{t("ui.license.deactivate_hint")}</p>
        </Modal>
      )}
    </Card>
  );
}

function downloadBlob(blob: Blob, name: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------------------------------------------------------------------------
function UpdatesCard() {
  const { t, locale } = useApp();
  const [ov, setOv] = useState<UpdateOverview | null>(null);
  const [arch, setArch] = useState<Archive[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const [staged, setStaged] = useState<{ version: string; notes: Record<string, string>; released_at?: string } | null>(null);
  const [confirm, setConfirm] = useState<{ action: "apply" | "rollback"; version: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  usePolling(() => {
    get<UpdateOverview>("/api/updates").then(setOv).catch(() => undefined);
    get<Archive[]>("/api/rollback-archives").then(setArch).catch(() => undefined);
  }, 5000);

  const doUpload = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f, f.name);
    setBusy(true);
    try {
      setStaged(await upload("/api/updates/upload", fd));
      setErr(null);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const run = async () => {
    if (!confirm) return;
    try {
      await send("POST", confirm.action === "apply" ? "/api/updates/apply" : "/api/updates/rollback", { version: confirm.version });
      setErr(null);
    } catch (e) {
      setErr(e);
    } finally {
      setConfirm(null);
    }
  };
  const running = ov?.status?.state === "running";
  return (
    <Card title={t("ui.update.title")}>
      <div className="stack">
        <ErrorBox error={err} />
        {ov && (
          <>
            <dl className="kv">
              <dt>{t("ui.update.current")}</dt><dd><b>{ov.current}</b></dd>
              <dt>{t("ui.update.installed")}</dt><dd>{ov.installed.map((v) => v.version).join("、") || "–"}</dd>
            </dl>
            {!ov.supported && <div className="alert info">{t("ui.update.unsupported")}</div>}
            {ov.status && (
              <div className={`alert ${ov.status.state === "failed" ? "error" : "info"}`}>
                {t(`ui.update.action.${ov.status.action}`)} {ov.status.version}：{t(`ui.update.state.${ov.status.state}`)}
                {ov.status.step && ov.status.state === "running" && `（${t(`ui.update.step.${ov.status.step}`)}）`}
                {ov.status.reason && ` — ${ov.status.reason}`}
              </div>
            )}
            {ov.supported && (
              <div className="row">
                <button className="btn primary" disabled={busy || running} onClick={() => file.current?.click()}>{busy ? t("ui.working") : t("ui.update.upload")}</button>
                <input ref={file} type="file" accept=".xrvupd" hidden onChange={(e) => e.target.files?.[0] && doUpload(e.target.files[0])} />
                {ov.rollback_to.map((r) => (
                  <button key={r.version} className="btn" disabled={running} onClick={() => setConfirm({ action: "rollback", version: r.version })}>
                    {t("ui.update.rollback_to").replace("{v}", r.version)}
                  </button>
                ))}
              </div>
            )}
            {staged && (
              <div className="card card-b stack">
                <h3>{t("ui.update.staged")} {staged.version}</h3>
                <div style={{ whiteSpace: "pre-wrap" }}>{staged.notes[locale] || staged.notes["zh-TW"] || "–"}</div>
                <div className="row"><span className="spacer" />
                  <button className="btn primary" disabled={running} onClick={() => setConfirm({ action: "apply", version: staged.version })}>{t("ui.update.apply")}</button></div>
              </div>
            )}
            <h3>{t("ui.update.history")}</h3>
            <table className="table">
              <thead><tr><th>{t("ui.time")}</th><th>{t("ui.update.action_col")}</th><th>{t("ui.version")}</th><th>{t("ui.status")}</th><th>{t("ui.operator")}</th></tr></thead>
              <tbody>
                {ov.history.map((h, i) => (
                  <tr key={i}><td>{fmtTime(h.at)}</td><td>{t(`ui.update.action.${h.action}`)}</td><td>{h.from_version} → {h.to_version}</td>
                    <td>{t(`ui.update.result.${h.result}`, h.result)}</td><td>{h.actor || "–"}</td></tr>
                ))}
                {!ov.history.length && <tr><td colSpan={5} className="muted" style={{ textAlign: "center" }}>{t("ui.empty")}</td></tr>}
              </tbody>
            </table>
            {arch.length > 0 && (
              <>
                <h3>{t("ui.update.archives")}</h3>
                <div className="muted">{t("ui.update.archives_hint")}</div>
                <table className="table">
                  <tbody>
                    {arch.map((a) => (
                      <tr key={a.name}>
                        <td className="mono">{a.name}</td><td>{fmtTime(a.created_at)}</td>
                        <td>{t("ui.update.archive_runs").replace("{n}", String(a.counts.runs || 0))}</td>
                        <td>{a.imported ? t("ui.update.imported") :
                          <button className="btn small" onClick={() => send("POST", `/api/rollback-archives/${encodeURIComponent(a.name)}/import`)
                            .then(() => get<Archive[]>("/api/rollback-archives").then(setArch)).catch(setErr)}>{t("ui.update.import_archive")}</button>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </div>
      {confirm && (
        <Modal title={t(confirm.action === "apply" ? "ui.update.confirm_apply" : "ui.update.confirm_rollback").replace("{v}", confirm.version)}
          onClose={() => setConfirm(null)}
          footer={<><button className="btn" onClick={() => setConfirm(null)}>{t("ui.cancel")}</button>
            <button className="btn primary" onClick={run}>{t("ui.confirm")}</button></>}>
          <p>{t(confirm.action === "apply" ? "ui.update.apply_hint" : "ui.update.rollback_hint")}</p>
        </Modal>
      )}
    </Card>
  );
}
