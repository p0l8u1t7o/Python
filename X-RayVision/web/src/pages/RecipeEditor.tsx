import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { get, send } from "../api/client";
import type { AnalysisResult, ModelRow, ParamDef, QualityRule, RecipeBody, RecipeDiff, RecipeRow, RunDetail, RunRow } from "../api/types";
import { reasonText, useApp } from "../app/context";
import { ImageViewer, buildShapes } from "../components/ImageViewer";
import { Layout } from "../components/Layout";
import { summaryEntries } from "../components/ModuleSummary";
import { RecipeDiffView, ReleaseDialog } from "../components/RecipeRelease";
import { RegionEditor } from "../components/RegionEditor";
import { loadRun } from "../components/RunPreview";
import { Card, ErrorBox, JudgmentBadge, QualityBadge, fmt, fmtSigned, fmtTime, useLoad } from "../components/ui";

const ACQ_KEYS = ["tube_voltage_kv", "tube_current_ua", "tube_power_w", "exposure_ms", "frames", "view_angle_deg"];
const PLATFORM_METRICS = ["image.snr", "image.saturation_ratio", "image.dark_ratio"];

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
      get<RecipeBody>(`/api/recipe-template/${moduleId}`).then(setBody).catch(setError);
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
  const allRules = body.modules.flatMap((m) => modules[m.module_id]?.quality_rules || []);
  const metrics = Array.from(new Set([...PLATFORM_METRICS, ...allRules.map((r) => r.metric)]));

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
            const setParam = (k: string, v: unknown) => {
              const mods = [...body.modules];
              mods[mi] = { ...m, params: { ...m.params, [k]: v } };
              upd({ modules: mods });
            };
            const setJudge = (k: string, v: unknown) => {
              const mods = [...body.modules];
              mods[mi] = { ...m, judgment: { ...(m.judgment || {}), [k]: v } };
              upd({ modules: mods });
            };
            return (
              <Card key={m.module_id} title={`${label(info.names, m.module_id)}（${t("ui.module_version")} ${m.module_version || info.version}）`}
                actions={<label className="check"><input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />{t("ui.recipe.show_advanced")}</label>}>
                <div className="stack">
                  <h3>{t("ui.recipe.judgment_spec")}</h3>
                  <div className="form-grid">
                    {info.judgment_params.filter((p) => advanced || readOnly || !p.advanced).map((p) => (
                      <ParamField key={p.key} p={p} value={(m.judgment || {})[p.key]} onChange={(v) => setJudge(p.key, v)} nullable />
                    ))}
                  </div>
                  <h3>{t("ui.recipe.params")}</h3>
                  <div className="form-grid">
                    {info.params.filter((p) => advanced || readOnly || !p.advanced).map((p) => (
                      <ParamField key={p.key} p={p} value={m.params[p.key] ?? p.default} onChange={(v) => setParam(p.key, v)}
                        moduleId={m.module_id} />
                    ))}
                  </div>
                </div>
              </Card>
            );
          })}

          <Card title={t("ui.region.title")}>
            <RegionEditor value={body.regions} readOnly={readOnly} onChange={(v) => upd({ regions: v })} />
          </Card>

          <Card title={t("ui.recipe.quality_rules")}>
            <div className="stack">
              <div className="muted">{t("ui.recipe.quality_hint")}</div>
              <table className="table">
                <thead><tr><th>{t("ui.metric")}</th><th>{t("ui.recipe.warn_below")}</th><th>{t("ui.recipe.warn_above")}</th>
                  <th>{t("ui.recipe.fail_below")}</th><th>{t("ui.recipe.fail_above")}</th><th></th></tr></thead>
                <tbody>
                  {body.quality_rules.map((q, i) => (
                    <tr key={i}>
                      <td>
                        <select value={q.metric} onChange={(e) => { const r = [...body.quality_rules]; r[i] = { ...q, metric: e.target.value }; upd({ quality_rules: r }); }}>
                          {metrics.map((k) => <option key={k} value={k}>{t(`metric.${k}`, k)}</option>)}
                        </select>
                      </td>
                      {(["warn_below", "warn_above", "fail_below", "fail_above"] as (keyof QualityRule)[]).map((f) => (
                        <td key={f}><input type="number" step="any" style={{ width: 100 }} value={(q[f] as number | null | undefined) ?? ""}
                          onChange={(e) => { const r = [...body.quality_rules]; r[i] = { ...q, [f]: e.target.value === "" ? null : Number(e.target.value) }; upd({ quality_rules: r }); }} /></td>
                      ))}
                      <td><button className="btn small danger" onClick={() => upd({ quality_rules: body.quality_rules.filter((_, j) => j !== i) })}>{t("ui.delete")}</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div><button className="btn small" onClick={() => {
                const def = allRules.find((r) => !body.quality_rules.some((q) => q.metric === r.metric)) || { metric: metrics[0] };
                upd({ quality_rules: [...body.quality_rules, { ...def }] });
              }}>{t("ui.recipe.add_rule")}</button></div>
            </div>
          </Card>

          <Card title={t("ui.recipe.acq_limits")}>
            <div className="stack">
              <div className="muted">{t("ui.recipe.acq_hint")}</div>
              <div className="form-grid">
                {ACQ_KEYS.map((k) => {
                  const v = body.acquisition_limits[k] || [null, null];
                  const set = (i: 0 | 1, x: string) => {
                    const nv: [number | null, number | null] = [...v] as [number | null, number | null];
                    nv[i] = x === "" ? null : Number(x);
                    const lim = { ...body.acquisition_limits };
                    if (nv[0] === null && nv[1] === null) delete lim[k];
                    else lim[k] = nv;
                    upd({ acquisition_limits: lim });
                  };
                  return (
                    <label key={k} className="field">{t(`acquisition.${k}`)}
                      <div className="row">
                        <input type="number" step="any" style={{ width: 90 }} placeholder={t("ui.min")} value={v[0] ?? ""} onChange={(e) => set(0, e.target.value)} />
                        <span>–</span>
                        <input type="number" step="any" style={{ width: 90 }} placeholder={t("ui.max")} value={v[1] ?? ""} onChange={(e) => set(1, e.target.value)} />
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
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

function ParamField({ p, value, onChange, nullable, moduleId }:
  { p: ParamDef; value: unknown; onChange: (v: unknown) => void; nullable?: boolean; moduleId?: string }) {
  const { label, t } = useApp();
  if (p.type === "model") return <ModelField p={p} value={String(value ?? "")} onChange={onChange} moduleId={moduleId || ""} />;
  const unit = p.unit && !["ratio", "sigma"].includes(p.unit) ? `（${p.unit === "um" ? "µm" : p.unit === "deg" ? "°" : p.unit}）` : "";
  const range = p.min !== null && p.max !== null ? `${p.min} – ${p.max}` : "";
  if (p.type === "bool") {
    return <label className="check"><input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />{label(p.label, p.key)}</label>;
  }
  if (p.type === "enum") {
    return (
      <label className="field">{label(p.label, p.key)}
        <select value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {p.choices.map((c) => <option key={c} value={c}>{t(`ui.choice.${p.key}.${c}`, c)}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label className="field">{label(p.label, p.key)}{unit}
      <input type="number" step={p.type === "int" ? 1 : "any"} value={value === null || value === undefined ? "" : String(value)}
        placeholder={nullable ? t("ui.not_set") : ""}
        onChange={(e) => onChange(e.target.value === "" ? (nullable ? null : p.default) : Number(e.target.value))} />
      {range && <span className="hint">{t("ui.range")} {range}</span>}
    </label>
  );
}

// 深度學習模型參數：列出適用於此模組、啟用中的模型 (已選但停用者仍顯示，發布時會被拒絕)
function ModelField({ p, value, onChange, moduleId }: { p: ParamDef; value: string; onChange: (v: unknown) => void; moduleId: string }) {
  const { label, t } = useApp();
  const [models, setModels] = useState<ModelRow[]>([]);
  useEffect(() => {
    get<ModelRow[]>("/api/models", { module_id: moduleId }).then(setModels).catch(() => setModels([]));
  }, [moduleId]);
  const usable = models.filter((m) => m.status === "active" && (!p.choices.length || p.choices.includes(m.task)));
  const known = models.some((m) => m.ref === value);
  return (
    <label className="field">{label(p.label, p.key)}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("ui.model.none")}</option>
        {usable.map((m) => <option key={m.ref} value={m.ref}>{m.ref}{m.meta.names ? `（${label(m.meta.names, m.ref)}）` : ""}</option>)}
        {value && !usable.some((m) => m.ref === value) && <option value={value}>{value}（{t(known ? "ui.model.retired" : "ui.model.missing")}）</option>}
      </select>
    </label>
  );
}
