import { Fragment, useState } from "react";
import { get, send } from "../api/client";
import type { AuditEntry, DiagnosticExport, RecipeSummary, WatchFolder } from "../api/types";
import { useApp, usePolling } from "../app/context";
import { Layout } from "../components/Layout";
import { Card, Empty, ErrorBox, fmtTime, useLoad } from "../components/ui";

// ---------------------------------------------------------------------------
// 資料夾監看
// ---------------------------------------------------------------------------
export function WatchFolders() {
  const { t, can } = useApp();
  const manage = can("watch_manage");
  const [rows, setRows] = useState<WatchFolder[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [recipes] = useLoad(() => get<RecipeSummary[]>("/api/recipes"), []);
  const [form, setForm] = useState({ path: "", recipe_id: "", recursive: true, name_rule: "", import_existing: false });
  const refresh = () => get<WatchFolder[]>("/api/watch-folders").then(setRows).catch(setError);
  usePolling(refresh, 5000);

  const add = async () => {
    try {
      await send("POST", "/api/watch-folders", form);
      setForm({ ...form, path: "", name_rule: "" });
      setError(null);
      refresh();
    } catch (e) {
      setError(e);
    }
  };
  const patch = async (id: number, body: Record<string, unknown>) => {
    try {
      await send("PATCH", `/api/watch-folders/${id}`, body);
      refresh();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <Layout title={t("ui.nav.watch")}
      actions={manage && <button className="btn" onClick={() => send("POST", "/api/watch-folders/scan").then(refresh).catch(setError)}>{t("ui.watch.scan_now")}</button>}>
      <div className="stack">
        <ErrorBox error={error} />
        {manage && <Card title={t("ui.watch.add")}>
          <div className="stack">
            <div className="form-grid">
              <label className="field">{t("ui.watch.path")}
                <input type="text" value={form.path} placeholder="D:\XRay\Output" onChange={(e) => setForm({ ...form, path: e.target.value })} />
              </label>
              <label className="field">{t("ui.recipe")}
                <select value={form.recipe_id} onChange={(e) => setForm({ ...form, recipe_id: e.target.value })}>
                  <option value="">{t("ui.select")}</option>
                  {recipes?.filter((r) => r.latest_released).map((r) => <option key={r.recipe_id} value={r.recipe_id}>{r.recipe_id}</option>)}
                </select>
              </label>
              <label className="field">{t("ui.watch.name_rule")}
                <input type="text" className="mono" value={form.name_rule} placeholder="(?P<lot>[^/]+)/(?P<sample>[^/]+)\.tiff?$"
                  onChange={(e) => setForm({ ...form, name_rule: e.target.value })} />
                <span className="hint">{t("ui.watch.name_rule_hint")}</span>
              </label>
            </div>
            <div className="row">
              <label className="check"><input type="checkbox" checked={form.recursive} onChange={(e) => setForm({ ...form, recursive: e.target.checked })} />{t("ui.watch.recursive")}</label>
              <label className="check"><input type="checkbox" checked={form.import_existing} onChange={(e) => setForm({ ...form, import_existing: e.target.checked })} />{t("ui.watch.import_existing")}</label>
              <span className="spacer" />
              <button className="btn primary" disabled={!form.path || !form.recipe_id} onClick={add}>{t("ui.add")}</button>
            </div>
          </div>
        </Card>}
        <Card title={t("ui.watch.list")} bodyClass="">
          {rows.length === 0 ? <Empty>{t("ui.watch.none")}</Empty> : (
            <table className="table">
              <thead><tr><th>{t("ui.watch.path")}</th><th>{t("ui.recipe")}</th><th>{t("ui.watch.name_rule")}</th>
                <th className="num">{t("ui.watch.imported")}</th><th className="num">{t("ui.watch.pending")}</th>
                <th className="num">{t("ui.watch.failed")}</th><th>{t("ui.watch.last_scan")}</th><th>{t("ui.status")}</th></tr></thead>
              <tbody>
                {rows.map((w) => (
                  <tr key={w.id}>
                    <td className="mono">{w.path}</td><td>{w.recipe_id}</td><td className="mono">{w.name_rule || t("ui.watch.default_rule")}</td>
                    <td className="num">{w.counts.imported || 0}</td><td className="num">{w.counts.pending || 0}</td>
                    <td className="num">{w.counts.failed || 0}</td><td>{fmtTime(w.last_scan_at)}</td>
                    <td><label className="check"><input type="checkbox" disabled={!manage} checked={!!w.enabled} onChange={(e) => patch(w.id, { enabled: e.target.checked })} />
                      {w.enabled ? t("ui.enabled") : t("ui.disabled")}</label></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </Layout>
  );
}

// ---------------------------------------------------------------------------
// 問題回報包 (匯出紀錄)
// ---------------------------------------------------------------------------
export function Diagnostics() {
  const { t } = useApp();
  const [rows, error] = useLoad(() => get<DiagnosticExport[]>("/api/diagnostics"), []);
  return (
    <Layout title={t("ui.nav.diagnostics")}>
      <div className="stack">
        <div className="alert info">{t("ui.diag.page_hint")}</div>
        <ErrorBox error={error} />
        <Card bodyClass="">
          {!rows?.length ? <Empty /> : (
            <table className="table">
              <thead><tr><th>{t("ui.time")}</th><th>{t("ui.operator")}</th><th>{t("ui.file")}</th><th>{t("ui.diag.runs")}</th><th>{t("ui.diag.options")}</th></tr></thead>
              <tbody>
                {rows.map((r) => {
                  const o = JSON.parse(r.options_json) as Record<string, boolean>;
                  const n = (JSON.parse(r.run_ids_json) as number[]).length;
                  return (
                    <tr key={r.id}>
                      <td>{fmtTime(r.created_at)}</td><td>{r.actor}</td>
                      <td><a className="mono" href={`/api/diagnostics/files/${encodeURIComponent(r.file_name)}`}>{r.file_name}</a></td>
                      <td className="num">{n}</td>
                      <td>{Object.entries(o).filter(([, v]) => v).map(([k]) => t(`ui.diag.opt.${k}`)).join("、") || "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </Layout>
  );
}

// ---------------------------------------------------------------------------
// 稽核紀錄
// ---------------------------------------------------------------------------
export function Audit() {
  const { t } = useApp();
  const [action, setAction] = useState("");
  const [rows, error] = useLoad(() => get<AuditEntry[]>("/api/audit", { action, limit: 500 }), [action]);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Layout title={t("ui.nav.audit")}
      actions={<select value={action} onChange={(e) => setAction(e.target.value)}>
        <option value="">{t("ui.all")}</option>
        {["recipe", "module", "model", "annotation", "image", "run", "job", "watch", "diagnostics", "auth", "user", "license", "settings", "update", "system"].map((a) => <option key={a} value={a}>{t(`ui.audit.cat.${a}`)}</option>)}
      </select>}>
      <div className="stack">
        <div className="alert info">{t("ui.audit.hint")}</div>
        <ErrorBox error={error} />
        <Card bodyClass="">
          {!rows?.length ? <Empty /> : (
            <table className="table">
              <thead><tr><th>{t("ui.time")}</th><th>{t("ui.operator")}</th><th>{t("ui.audit.action")}</th><th>{t("ui.audit.target")}</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.id}>
                    <tr className="clickable" onClick={() => setOpen(open === r.id ? null : r.id)}>
                      <td>{fmtTime(r.ts)}</td><td>{r.actor}</td><td>{t(`audit.${r.action}`, r.action)}</td>
                      <td className="mono">{r.target_type} {r.target_id}</td>
                    </tr>
                    {open === r.id && (
                      <tr><td colSpan={4}><pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                        {JSON.stringify(JSON.parse(r.detail_json), null, 2)}</pre></td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </Layout>
  );
}
