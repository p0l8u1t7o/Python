import { useEffect, useState } from "react";
import { get } from "../api/client";
import type { ModelRow, ModuleInfo, ParamDef, QualityRule, RecipeBody, RecipeModule } from "../api/types";
import { useApp } from "../app/context";

// 配方內容表單 (配方編輯器與手動檢測共用)：參數畫面依檢測模組宣告的參數結構自動產生
export const ACQ_KEYS = ["tube_voltage_kv", "tube_current_ua", "tube_power_w", "exposure_ms", "frames", "view_angle_deg"];
export const PLATFORM_METRICS = ["image.snr", "image.saturation_ratio", "image.dark_ratio"];

// 模組的判定規格與參數；changed 為與來源不同的鍵 (「params.鍵」「judgment.鍵」，以 * 標示)
export function ModuleParamsForm({ m, info, onChange, advanced, readOnly, changed, compact }: {
  m: RecipeModule; info: ModuleInfo; onChange: (m: RecipeModule) => void; advanced: boolean; readOnly: boolean;
  changed?: Set<string>; compact?: boolean;
}) {
  const { t } = useApp();
  const setParam = (k: string, v: unknown) => onChange({ ...m, params: { ...m.params, [k]: v } });
  const setJudge = (k: string, v: unknown) => onChange({ ...m, judgment: { ...(m.judgment || {}), [k]: v } });
  const grid = compact ? "form-grid compact" : "form-grid";
  return (
    <div className="stack">
      <h3>{t("ui.recipe.judgment_spec")}</h3>
      <div className={grid}>
        {info.judgment_params.filter((p) => advanced || readOnly || !p.advanced).map((p) => (
          <ParamField key={p.key} p={p} value={(m.judgment || {})[p.key]} onChange={(v) => setJudge(p.key, v)} nullable
            changed={changed?.has(`judgment.${p.key}`)} />
        ))}
      </div>
      <h3>{t("ui.recipe.params")}</h3>
      <div className={grid}>
        {info.params.filter((p) => advanced || readOnly || !p.advanced).map((p) => (
          <ParamField key={p.key} p={p} value={m.params[p.key] ?? p.default} onChange={(v) => setParam(p.key, v)}
            moduleId={m.module_id} changed={changed?.has(`params.${p.key}`)} />
        ))}
      </div>
    </div>
  );
}

export function QualityRulesForm({ body, upd, modules }: { body: RecipeBody; upd: (p: Partial<RecipeBody>) => void; modules: Record<string, ModuleInfo> }) {
  const { t } = useApp();
  const allRules = body.modules.flatMap((m) => modules[m.module_id]?.quality_rules || []);
  const metrics = Array.from(new Set([...PLATFORM_METRICS, ...allRules.map((r) => r.metric)]));
  return (
    <div className="stack">
      <div className="muted">{t("ui.recipe.quality_hint")}</div>
      <div className="table-wrap">
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
                  <td key={f}><input type="number" step="any" style={{ width: 90 }} value={(q[f] as number | null | undefined) ?? ""}
                    onChange={(e) => { const r = [...body.quality_rules]; r[i] = { ...q, [f]: e.target.value === "" ? null : Number(e.target.value) }; upd({ quality_rules: r }); }} /></td>
                ))}
                <td><button type="button" className="btn small danger" onClick={() => upd({ quality_rules: body.quality_rules.filter((_, j) => j !== i) })}>{t("ui.delete")}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div><button type="button" className="btn small" onClick={() => {
        const def = allRules.find((r) => !body.quality_rules.some((q) => q.metric === r.metric)) || { metric: metrics[0] };
        upd({ quality_rules: [...body.quality_rules, { ...def }] });
      }}>{t("ui.recipe.add_rule")}</button></div>
    </div>
  );
}

export function AcqLimitsForm({ body, upd }: { body: RecipeBody; upd: (p: Partial<RecipeBody>) => void }) {
  const { t } = useApp();
  return (
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
  );
}

// 新增配方範本 (依模組宣告，可能預設使用深度學習模型)；notice 為提示代碼 (例如尚未匯入模型)
export async function loadTemplate(moduleId: string): Promise<{ body: RecipeBody; notice: string | null }> {
  const { _notice, ...body } = await get<RecipeBody & { _notice?: string | null }>(`/api/recipe-template/${moduleId}`);
  return { body, notice: _notice || null };
}

// 是否有啟用中的模組支援「視為一個陣列」
export function arraysSupported(body: RecipeBody, modules: Record<string, ModuleInfo>) {
  return body.modules.some((m) => m.enabled !== false && modules[m.module_id]?.supports_region_arrays);
}

export function ParamField({ p, value, onChange, nullable, moduleId, changed }:
  { p: ParamDef; value: unknown; onChange: (v: unknown) => void; nullable?: boolean; moduleId?: string; changed?: boolean }) {
  const { label, t } = useApp();
  if (p.type === "model") return <ModelField p={p} value={String(value ?? "")} onChange={onChange} moduleId={moduleId || ""} />;
  const unit = p.unit && !["ratio", "sigma"].includes(p.unit) ? `（${p.unit === "um" ? "µm" : p.unit === "deg" ? "°" : p.unit}）` : "";
  const range = p.min !== null && p.max !== null ? `${p.min} – ${p.max}` : "";
  const mark = changed ? <span className="changed-mark" title={t("ui.manual.changed")}> *</span> : null;
  if (p.type === "bool") {
    return <label className="check"><input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />{label(p.label, p.key)}{mark}</label>;
  }
  if (p.type === "enum") {
    return (
      <label className="field"><span>{label(p.label, p.key)}{mark}</span>
        <select value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {p.choices.map((c) => <option key={c} value={c}>{t(`ui.choice.${p.key}.${c}`, c)}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label className="field"><span>{label(p.label, p.key)}{unit}{mark}</span>
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
