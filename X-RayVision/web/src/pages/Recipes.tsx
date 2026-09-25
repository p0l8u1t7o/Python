import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, send, upload } from "../api/client";
import type { ModelRow, ModuleValidation, RecipeRow, RecipeSummary } from "../api/types";
import { useApp } from "../app/context";
import { Layout } from "../components/Layout";
import { ReleaseDialog } from "../components/RecipeRelease";
import { Card, Empty, ErrorBox, Modal, fmt, fmtTime, useLoad } from "../components/ui";

export function Recipes() {
  const { t, label, modules, can } = useApp();
  const edit = can("recipe_edit");
  const nav = useNavigate();
  const [showRetired, setShowRetired] = useState(false);
  const [list, error, reload] = useLoad(() => get<RecipeSummary[]>("/api/recipes", { include_retired: showRetired ? "true" : "" }), [showRetired]);
  const [actionError, setActionError] = useState<unknown>(null);
  const [confirm, setConfirm] = useState<{ pk: number; what: "retire" | "delete"; name: string } | null>(null);
  const [release, setRelease] = useState<{ pk: number; name: string } | null>(null);
  const [newModule, setNewModule] = useState<boolean>(false);

  const act = async () => {
    if (!confirm) return;
    try {
      if (confirm.what === "delete") await send("DELETE", `/api/recipes/${confirm.pk}`);
      else await send("POST", `/api/recipes/${confirm.pk}/${confirm.what}`);
      setActionError(null);
      reload();
    } catch (e) {
      setActionError(e);
    } finally {
      setConfirm(null);
    }
  };

  // 修改：以該版本內容建立下一版草稿 (已有草稿時開啟該草稿)
  const revise = async (pk: number) => {
    try {
      const row = await send<RecipeRow>("POST", `/api/recipes/${pk}/revise`);
      nav(`/recipes/${row.id}`);
    } catch (e) {
      setActionError(e);
    }
  };

  return (
    <Layout title={t("ui.nav.recipes")}
      actions={<>
        <label className="check"><input type="checkbox" checked={showRetired} onChange={(e) => setShowRetired(e.target.checked)} />{t("ui.recipe.show_retired")}</label>
        {edit && <button className="btn primary" onClick={() => setNewModule(true)}>{t("ui.recipe.new")}</button>}
      </>}>
      <div className="stack">
        <ErrorBox error={error || actionError} />
        {list && list.length === 0 && <Card><Empty>{t("ui.recipe.none")}</Empty></Card>}
        {list?.map((r) => (
          <Card key={r.recipe_id} title={<h2>{label(r.name, r.recipe_id)} <span className="muted mono" style={{ fontWeight: 400 }}>{r.recipe_id}</span></h2>} bodyClass="">
            <table className="table">
              <thead><tr><th>{t("ui.version")}</th><th>{t("ui.status")}</th><th>{t("ui.created")}</th><th>{t("ui.released_at")}</th><th></th></tr></thead>
              <tbody>
                {[...r.versions].reverse().map((v) => (
                  <tr key={v.id}>
                    <td>v{v.version}{r.latest_released === v.version && <span className="badge q-pass" style={{ marginLeft: 8 }}>{t("ui.recipe.in_use")}</span>}</td>
                    <td>{t(`recipe.${v.status}`)}</td>
                    <td>{fmtTime(v.created_at)}</td>
                    <td>{fmtTime(v.released_at)}</td>
                    <td><div className="row" style={{ justifyContent: "flex-end" }}>
                      <button className="btn small" onClick={() => nav(`/recipes/${v.id}`)}>{v.status === "draft" && edit ? t("ui.edit") : t("ui.view")}</button>
                      {edit && v.status === "draft" && <>
                        <button className="btn small primary" onClick={() => setRelease({ pk: v.id, name: `${r.recipe_id} v${v.version}` })}>{t("ui.recipe.release")}</button>
                        <button className="btn small danger" onClick={() => setConfirm({ pk: v.id, what: "delete", name: `${r.recipe_id} v${v.version}` })}>{t("ui.delete")}</button>
                      </>}
                      {edit && v.status !== "draft" && <button className="btn small" onClick={() => revise(v.id)}>{t("ui.recipe.revise")}</button>}
                      {edit && v.status === "released" && <button className="btn small" onClick={() => setConfirm({ pk: v.id, what: "retire", name: `${r.recipe_id} v${v.version}` })}>{t("ui.recipe.retire")}</button>}
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ))}
      </div>
      <div style={{ marginTop: "var(--sp-4)" }}><ModuleValidationCard /></div>
      <div style={{ marginTop: "var(--sp-4)" }}><ModelsCard /></div>
      {confirm && (
        <Modal title={t(`ui.recipe.confirm_${confirm.what}`)} onClose={() => setConfirm(null)}
          footer={<><button className="btn" onClick={() => setConfirm(null)}>{t("ui.cancel")}</button>
            <button className={`btn ${confirm.what === "delete" ? "danger" : "primary"}`} onClick={act}>{t("ui.confirm")}</button></>}>
          <p>{confirm.name}</p>
          <p className="muted">{t(`ui.recipe.confirm_${confirm.what}_hint`)}</p>
        </Modal>
      )}
      {release && <ReleaseDialog pk={release.pk} name={release.name} onClose={() => setRelease(null)} onReleased={() => reload()} />}
      {newModule && (
        <Modal title={t("ui.recipe.new")} onClose={() => setNewModule(false)}>
          <div className="stack">
            {Object.values(modules).map((m) => (
              <button key={m.module_id} className="btn" onClick={() => nav(`/recipes/new/${m.module_id}`)}>{label(m.names, m.module_id)}</button>
            ))}
          </div>
        </Modal>
      )}
    </Layout>
  );
}


// 檢測模組驗證狀態 (規劃書 PLAN-002 第 3.6 節)：未驗證模組的判定最多為需複判
function ModuleValidationCard() {
  const { t, label, can } = useApp();
  const edit = can("recipe_edit");
  const [list, error, reload] = useLoad(() => get<ModuleValidation[]>("/api/modules/validation"), []);
  const [dialog, setDialog] = useState<{ m: ModuleValidation; status: "validated" | "revoked" } | null>(null);
  const [note, setNote] = useState("");
  const [report, setReport] = useState("");
  const [actionError, setActionError] = useState<unknown>(null);

  const submit = async () => {
    if (!dialog) return;
    try {
      await send("POST", `/api/modules/${dialog.m.module_id}/validation`, { status: dialog.status, note, report_name: report });
      setDialog(null);
      setActionError(null);
      reload();
    } catch (e) {
      setActionError(e);
    }
  };

  return (
    <Card title={<h2>{t("ui.modval.title")}</h2>} bodyClass="">
      <div className="muted" style={{ padding: "var(--sp-2) var(--sp-4)" }}>{t("ui.modval.hint")}</div>
      <ErrorBox error={error} />
      <table className="table">
        <thead><tr><th>{t("ui.modval.module")}</th><th>{t("ui.version")}</th><th>{t("ui.status")}</th><th>{t("ui.modval.approved")}</th><th>{t("ui.modval.note")}</th><th></th></tr></thead>
        <tbody>
          {list?.map((m) => (
            <tr key={m.module_id}>
              <td>{label(m.names, m.module_id)}</td>
              <td className="mono">{m.version}</td>
              <td>{m.status === "validated"
                ? <span className="badge q-pass">{t("ui.modval.validated")}</span>
                : <span className="badge q-warn">{t("ui.modval.unvalidated")}</span>}</td>
              <td>{m.status === "validated" ? `${m.approved_by}　${fmtTime(m.approved_at)}` : "–"}</td>
              <td>{m.status === "validated" ? t(m.note, m.note) : ""}</td>
              <td>{edit && (
                <div className="row" style={{ justifyContent: "flex-end" }}>
                  {m.status === "validated"
                    ? <button className="btn small" onClick={() => { setNote(""); setReport(""); setDialog({ m, status: "revoked" }); }}>{t("ui.modval.revoke")}</button>
                    : <button className="btn small primary" onClick={() => { setNote(""); setReport(""); setDialog({ m, status: "validated" }); }}>{t("ui.modval.approve")}</button>}
                </div>
              )}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {dialog && (
        <Modal title={t(dialog.status === "validated" ? "ui.modval.approve" : "ui.modval.revoke")} onClose={() => setDialog(null)}
          footer={<><button className="btn" onClick={() => setDialog(null)}>{t("ui.cancel")}</button>
            <button className={`btn ${dialog.status === "validated" ? "primary" : "danger"}`} onClick={submit}
              disabled={dialog.status === "validated" && !note.trim()}>{t("ui.confirm")}</button></>}>
          <div className="stack">
            <p>{label(dialog.m.names, dialog.m.module_id)} {dialog.m.series}</p>
            <p className="muted">{t(dialog.status === "validated" ? "ui.modval.approve_hint" : "ui.modval.revoke_hint")}</p>
            <label className="field"><span>{t("ui.modval.note")}</span>
              <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("ui.modval.note_hint")} /></label>
            {dialog.status === "validated" && (
              <label className="field"><span>{t("ui.modval.report")}</span>
                <input value={report} onChange={(e) => setReport(e.target.value)} placeholder={t("ui.modval.report_hint")} /></label>
            )}
            <ErrorBox error={actionError} />
          </div>
        </Modal>
      )}
    </Card>
  );
}

// 深度學習模型：原廠簽署的 .xrvmodel 匯入、停用 (停用後不能用於新發布的配方)
function ModelsCard() {
  const { t, label, can, modules } = useApp();
  const edit = can("recipe_edit");
  const [list, error, reload] = useLoad(() => get<ModelRow[]>("/api/models"), []);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const doImport = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f, f.name);
    setBusy(true);
    try {
      await upload("/api/models/import", fd);
      setErr(null);
      reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  };
  const setStatus = async (m: ModelRow, status: "active" | "retired") => {
    try {
      await send("POST", `/api/models/${m.id}/status`, { status });
      reload();
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <Card title={<h2>{t("ui.model.title")}</h2>} bodyClass=""
      actions={edit ? <>
        <input ref={file} type="file" accept=".xrvmodel" hidden onChange={(e) => e.target.files?.[0] && doImport(e.target.files[0])} />
        <button className="btn" disabled={busy} onClick={() => file.current?.click()}>{t("ui.model.import")}</button>
      </> : undefined}>
      <div className="muted" style={{ padding: "var(--sp-2) var(--sp-4)" }}>{t("ui.model.hint")}</div>
      <ErrorBox error={error || err} />
      {list && list.length === 0 && <Empty>{t("ui.model.empty")}</Empty>}
      {list && list.length > 0 && (
        <table className="table">
          <thead><tr><th>{t("ui.model.ref")}</th><th>{t("ui.modval.module")}</th><th>{t("ui.model.metrics")}</th>
            <th>{t("ui.model.imported")}</th><th>{t("ui.status")}</th><th></th></tr></thead>
          <tbody>
            {list.map((m) => (
              <tr key={m.id}>
                <td><span className="mono">{m.ref}</span>{m.meta.names && <div className="muted">{label(m.meta.names, "")}</div>}</td>
                <td>{label(modules[m.module_id]?.names, m.module_id)}</td>
                <td className="muted" style={{ fontSize: "var(--fs-xs)" }}>
                  {m.meta.metrics ? Object.entries(m.meta.metrics).filter(([, v]) => typeof v === "number")
                    .map(([k, v]) => `${t(`ui.model.metric.${k}`, k)} ${fmt(v, Number.isInteger(v) ? 0 : 3)}`).join("，") : "–"}
                </td>
                <td>{m.imported_by}　{fmtTime(m.imported_at)}</td>
                <td>{m.status === "active" ? <span className="badge q-pass">{t("ui.model.active")}</span>
                  : <span className="badge q-warn">{t("ui.model.retired")}</span>}</td>
                <td>{edit && (
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    {m.status === "active"
                      ? <button className="btn small" onClick={() => setStatus(m, "retired")}>{t("ui.model.retire")}</button>
                      : <button className="btn small" onClick={() => setStatus(m, "active")}>{t("ui.model.activate")}</button>}
                  </div>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
