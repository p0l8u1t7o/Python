import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { get, send } from "../api/client";
import type { ModelRow, ParamDef, QualityRule, RecipeBody, RecipeRow } from "../api/types";
import { useApp } from "../app/context";
import { Layout } from "../components/Layout";
import { RegionEditor } from "../components/RegionEditor";
import { Card, ErrorBox } from "../components/ui";

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
  const isNew = !pk;
  const readOnly = (!!row && row.status !== "draft") || !can("recipe_edit");

  useEffect(() => {
    if (pk) {
      get<RecipeRow>(`/api/recipes/${pk}`).then((r) => { setRow(r); setBody(r.body); }).catch(setError);
    } else if (moduleId) {
      get<RecipeBody>(`/api/recipe-template/${moduleId}`).then(setBody).catch(setError);
    }
  }, [pk, moduleId]);

  if (!body) return <Layout title={t("ui.nav.recipes")}><ErrorBox error={error} /></Layout>;
  const upd = (patch: Partial<RecipeBody>) => { setBody({ ...body, ...patch }); setSaved(false); };

  const save = async () => {
    setError(null);
    const clean = { ...body, modules: body.modules.map(({ module_version: _v, ...m }) => m) };
    try {
      const r = isNew
        ? await send<RecipeRow>("POST", "/api/recipes", { body: clean })
        : await send<RecipeRow>("PUT", `/api/recipes/${row!.id}`, { body: clean });
      setSaved(true);
      if (isNew) nav(`/recipes/${r.id}`, { replace: true });
      else { setRow(r); setBody(r.body); }
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
        {!readOnly && <button className="btn primary" onClick={save}>{t("ui.save_draft")}</button>}
      </>}>
      <fieldset disabled={readOnly} style={{ border: 0, padding: 0, margin: 0 }}>
        <div className="stack">
          {readOnly && can("recipe_edit") && <div className="alert info">{t("ui.recipe.readonly_hint")}</div>}
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
    </Layout>
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
