import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { get, send } from "../api/client";
import type { AnalysisResult, RecipeBody, RecipeDiff, RecipeRow, RunDetail, RunRow } from "../api/types";
import { reasonText, useApp } from "../app/context";
import { ImageViewer, buildShapes } from "../components/ImageViewer";
import { Layout } from "../components/Layout";
import { summaryEntries } from "../components/ModuleSummary";
import { RecipeDiffView, ReleaseDialog } from "../components/RecipeRelease";
import { AcqLimitsForm, ModuleParamsForm, QualityRulesForm, arraysSupported, loadTemplate } from "../components/RecipeForm";
import { RegionEditor } from "../components/RegionEditor";
import { loadRun } from "../components/RunPreview";
import { Card, ErrorBox, JudgmentBadge, QualityBadge, fmt, fmtSigned, fmtTime, useLoad } from "../components/ui";

// 配方編輯：參數畫面依檢測模組宣告的參數結構自動產生
export function RecipeEditor() {
  const { pk, moduleId } = useParams();
  const { t, label, modules, can } = useApp();
  const nav = useNavigate();
  const [row, setRow] = useState<RecipeRow | null>(null);
  const [body, setBody] = useState<RecipeBody | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [diff, setDiff] = useState<RecipeDiff | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const isNew = !pk;
  const edit = can("recipe_edit");
  const readOnly = (!!row && row.status !== "draft") || !edit;

  const loadDiff = (id: number) => get<RecipeDiff>(`/api/recipes/${id}/diff`).then(setDiff).catch(() => setDiff(null));
  useEffect(() => {
    setDirty(false);
    setDiff(null);
    if (pk) {
      get<RecipeRow>(`/api/recipes/${pk}`).then((r) => {
        setRow(r);
        setBody(r.body);
        if (r.status === "draft") loadDiff(r.id);
      }).catch(setError);
    } else if (moduleId) {
      loadTemplate(moduleId).then((r) => { setBody(r.body); setNotice(r.notice); }).catch(setError);
    }
  }, [pk, moduleId]);

  if (!body) return <Layout title={t("ui.nav.recipes")}><ErrorBox error={error} /></Layout>;
  const upd = (patch: Partial<RecipeBody>) => { setBody({ ...body, ...patch }); setSaved(false); setDirty(true); };

  const save = async (): Promise<RecipeRow | null> => {
    setError(null);
    const clean = { ...body, modules: body.modules.map(({ module_version: _v, ...m }) => m) };
    try {
      const r = isNew
        ? await send<RecipeRow>("POST", "/api/recipes", { body: clean })
        : await send<RecipeRow>("PUT", `/api/recipes/${row!.id}`, { body: clean });
      setSaved(true);
      setDirty(false);
      if (isNew) nav(`/recipes/${r.id}`, { replace: true });
      else { setRow(r); setBody(r.body); loadDiff(r.id); }
      return r;
    } catch (e) {
      setError(e);
      return null;
    }
  };

  // 發布前先儲存未儲存的變更
  const startRelease = async () => {
    if (dirty && !(await save())) return;
    setReleasing(true);
  };

  const revise = async () => {
    try {
      const r = await send<RecipeRow>("POST", `/api/recipes/${row!.id}/revise`);
      nav(`/recipes/${r.id}`);
    } catch (e) {
      setError(e);
    }
  };

  const title = isNew ? t("ui.recipe.new") : `${row?.recipe_id} v${row?.version}（${t(`recipe.${row?.status}`)}）`;

  return (
    <Layout title={title}
      actions={<>
        <button className="btn" onClick={() => nav("/recipes")}>{t("ui.back")}</button>
        {!readOnly && <button className="btn" onClick={save}>{t("ui.save_draft")}</button>}
        {!readOnly && !isNew && <button className="btn primary" onClick={startRelease}>{t("ui.recipe.release")}</button>}
        {edit && row && row.status !== "draft" && <button className="btn primary" onClick={revise}>{t("ui.recipe.revise")}</button>}
      </>}>
      <fieldset disabled={readOnly} style={{ border: 0, padding: 0, margin: 0 }}>
        <div className="stack">
          {readOnly && edit && <div className="alert info">{t("ui.recipe.readonly_hint")}</div>}
          {row?.status === "draft" && diff?.base && (
            <div className="alert info">
              <div className="row">
                <span>{t("ui.recipe.revised_from").replace("{v}", String(diff.base.version)).replace("{s}", t(`recipe.${diff.base.status}`))}
                  {dirty && `（${t("ui.recipe.unsaved")}）`}</span>
                <span className="spacer" />
                <button type="button" className="btn small" onClick={() => setShowDiff(!showDiff)}>
                  {t(showDiff ? "ui.diff.hide" : "ui.diff.show").replace("{n}", String(diff.changes.length))}</button>
              </div>
              {showDiff && <div style={{ marginTop: "var(--sp-2)" }}><RecipeDiffView diff={diff} /></div>}
            </div>
          )}
          {saved && <div className="alert info">{t("ui.saved")}</div>}
          {isNew && notice && <div className="alert info">{t(`notice.${notice}`, notice)}</div>}
          <ErrorBox error={error} />
          <Card title={t("ui.recipe.basic")}>
            <div className="form-grid">
              <label className="field">{t("ui.recipe.id")}
                <input type="text" value={body.recipe_id} disabled={!isNew} onChange={(e) => upd({ recipe_id: e.target.value })} />
              </label>
              <label className="field">{t("ui.recipe.name_zh")}
                <input type="text" value={body.name["zh-TW"] || ""} onChange={(e) => upd({ name: { ...body.name, "zh-TW": e.target.value } })} />
              </label>
              <label className="field">{t("ui.recipe.name_en")}
                <input type="text" value={body.name.en || ""} onChange={(e) => upd({ name: { ...body.name, en: e.target.value } })} />
              </label>
              <label className="field">{t("ui.pixel_size")} (µm/px)
                <input type="number" step="any" value={body.pixel_size_um ?? ""} placeholder={t("ui.recipe.pixel_auto")}
                  onChange={(e) => upd({ pixel_size_um: e.target.value === "" ? null : Number(e.target.value) })} />
              </label>
              <label className="field">{t("ui.calibration")}
                <input type="text" value={body.calibration_profile ?? ""} placeholder={t("ui.not_used")}
                  onChange={(e) => upd({ calibration_profile: e.target.value || null })} />
              </label>
            </div>
          </Card>

          {body.modules.map((m, mi) => {
            const info = modules[m.module_id];
            if (!info) return null;
            return (
              <Card key={m.module_id} title={`${label(info.names, m.module_id)}（${t("ui.module_version")} ${m.module_version || info.version}）`}
                actions={<label className="check"><input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />{t("ui.recipe.show_advanced")}</label>}>
                <ModuleParamsForm m={m} info={info} advanced={advanced} readOnly={readOnly}
                  onChange={(nm) => { const mods = [...body.modules]; mods[mi] = nm; upd({ modules: mods }); }} />
              </Card>
            );
          })}

          <Card title={t("ui.region.title")}>
            <RegionEditor value={body.regions} readOnly={readOnly} arraysSupported={arraysSupported(body, modules)} onChange={(v) => upd({ regions: v })} />
          </Card>

          <Card title={t("ui.recipe.quality_rules")}>
            <QualityRulesForm body={body} upd={upd} modules={modules} />
          </Card>

          <Card title={t("ui.recipe.acq_limits")}>
            <AcqLimitsForm body={body} upd={upd} />
          </Card>
        </div>
      </fieldset>
      {edit && <div style={{ marginTop: "var(--sp-4)" }}><TrialPanel body={body} /></div>}
      {releasing && row && (
        <ReleaseDialog pk={row.id} name={`${row.recipe_id} v${row.version}`} onClose={() => setReleasing(false)}
          onReleased={(r) => { setRow(r); setBody(r.body); setDiff(null); }} />
      )}
    </Layout>
  );
}

// 試跑 (PLAN-003 第 7 節)：以編輯中、尚未儲存的內容分析一張影像，與該影像目前結果並列比較；不產生紀錄
function TrialPanel({ body }: { body: RecipeBody }) {
  const { t, label, modules } = useApp();
  const [runs] = useLoad(() => get<{ items: RunRow[] }>("/api/runs", { limit: 200 }), []);
  const [filter, setFilter] = useState("");
  const [runId, setRunId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [trial, setTrial] = useState<{ runId: number; result: AnalysisResult; body: string } | null>(null);
  const [current, setCurrent] = useState<RunDetail | null>(null);
  const items = runs?.items || [];

  useEffect(() => {
    if (runId === null && items.length) setRunId((items.find((r) => r.recipe_id === body.recipe_id) || items[0]).id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs]);

  const shapes = useMemo(() => (trial ? buildShapes(trial.result, modules, 10, t("ui.group")) : []), [trial, modules, t]);
  const q = filter.trim().toLowerCase();
  const shown = items.filter((r) => !q || `${r.file_name} ${r.lot_no || ""} ${r.sample_no}`.toLowerCase().includes(q));
  const stale = !!trial && trial.body !== JSON.stringify(body);

  const run = async () => {
    if (!runId) return;
    setBusy(true);
    setError(null);
    try {
      const [r, d] = await Promise.all([
        send<{ result: AnalysisResult }>("POST", "/api/recipes/trial", { body, run_id: runId }),
        loadRun(runId),
      ]);
      setTrial({ runId, result: r.result, body: JSON.stringify(body) });
      setCurrent(d);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  // 比較表：判定、品質、各模組主要量測、判定原因
  const rows = (res: AnalysisResult | undefined): Map<string, string> => {
    const m = new Map<string, string>();
    if (!res) return m;
    for (const mr of res.modules) {
      const name = label(modules[mr.module_id]?.names, mr.module_id);
      m.set(`${name} › ${t("ui.judgment")}`, t(`judgment.${mr.judgment}`));
      const d = mr.summary?.die_shift;
      if (d) {
        m.set(`${name} › ${t("ui.die_shift")}`, `${fmtSigned(d.dx)}, ${fmtSigned(d.dy)} px`);
        m.set(`${name} › ${t("ui.std_error")}`, `± ${fmt(d.se, 3)} px`);
        m.set(`${name} › ${t("ui.sites_used")}`, fmt(mr.summary.sites_used as number, 0));
      } else {
        for (const [k, v] of summaryEntries(mr)) m.set(`${name} › ${t(`summary.${k}`, k)}`, fmt(v, Number.isInteger(v) ? 0 : 2));
      }
    }
    return m;
  };
  const a = rows(current?.run.id === trial?.runId ? current?.result : undefined);
  const b = rows(trial?.result);
  const keys = Array.from(new Set([...a.keys(), ...b.keys()]));

  return (
    <Card title={t("ui.trial.title")}>
      <div className="stack">
        <div className="muted">{t("ui.trial.hint")}</div>
        <div className="row">
          <input type="text" placeholder={t("ui.trial.search")} value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 200 }} />
          <select value={runId ?? ""} onChange={(e) => setRunId(Number(e.target.value) || null)} style={{ minWidth: 320 }}>
            {!items.length && <option value="">{t("ui.trial.no_images")}</option>}
            {shown.map((r) => <option key={r.id} value={r.id}>{r.file_name}（{r.lot_no || "–"}／{r.recipe_id} v{r.recipe_version}／{fmtTime(r.created_at)}）</option>)}
          </select>
          <button className="btn primary" disabled={!runId || busy} onClick={run}>{busy ? t("ui.trial.running") : t("ui.trial.run")}</button>
        </div>
        <ErrorBox error={error} />
        {stale && <div className="alert info">{t("ui.trial.stale")}</div>}
        {trial && (
          <div className="trial-layout">
            <div className="trial-viewer">
              <ImageViewer src={`/api/runs/${trial.runId}/image?max_size=2048`} width={trial.result.image.width} height={trial.result.image.height}
                shapes={shapes} hiddenLayers={new Set()} opacity={0.9} brightness={1} contrast={1} />
            </div>
            <div className="stack">
              <table className="table">
                <thead><tr><th></th><th>{t("ui.trial.current")}</th><th>{t("ui.trial.result")}</th></tr></thead>
                <tbody>
                  <tr><th>{t("ui.auto_judgment")}</th>
                    <td>{current && <JudgmentBadge value={current.run.auto_judgment} />}</td>
                    <td><JudgmentBadge value={trial.result.judgment} /></td></tr>
                  <tr><th>{t("ui.quality")}</th>
                    <td>{current && <QualityBadge value={current.run.quality_level} />}</td>
                    <td><QualityBadge value={trial.result.quality.level} /></td></tr>
                  {keys.map((k) => (
                    <tr key={k} className={a.get(k) !== b.get(k) ? "selected" : ""}><th>{k}</th><td>{a.get(k) ?? "–"}</td><td>{b.get(k) ?? "–"}</td></tr>
                  ))}
                </tbody>
              </table>
              {trial.result.judgment_reasons.length > 0 && (
                <div className="stack">
                  <h3>{t("ui.reasons")}（{t("ui.trial.result")}）</h3>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {trial.result.judgment_reasons.map((x) => <li key={x}>{reasonText(t, x)}</li>)}
                  </ul>
                </div>
              )}
              <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.trial.not_saved")}</div>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
