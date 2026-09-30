import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, send } from "../api/client";
import type { ModuleInfo, ReanalysisScope, RecipeDiff, RecipeRow } from "../api/types";
import { useApp } from "../app/context";
import { ErrorBox, Modal } from "./ui";

// 配方差異的項目名稱：模組參數取參數結構的標籤，其餘取固定欄位名稱
// 模組參數未設定時以參數結構的預設值顯示
function pathLabel(path: string, t: (k: string, d?: string) => string, label: (l: Record<string, string> | undefined, d: string) => string,
  modules: Record<string, ModuleInfo>): [string, unknown] {
  const p = path.split(".");
  if (p[0] === "modules" && p.length >= 3) {
    const info = modules[p[1]];
    const key = p.slice(3).join(".");
    const defs = p[2] === "params" ? info?.params : p[2] === "judgment" ? info?.judgment_params : undefined;
    const def = defs?.find((d) => d.key === key);
    const mod = label(info?.names, p[1]);
    return def ? [`${mod} › ${label(def.label, key)}`, def.default] : [`${mod} › ${p.slice(2).join(".")}`, undefined];
  }
  const fixed: Record<string, string> = {
    "name.zh-TW": "ui.recipe.name_zh", "name.en": "ui.recipe.name_en", pixel_size_um: "ui.pixel_size",
    calibration_profile: "ui.calibration", regions: "ui.region.title", quality_rules: "ui.recipe.quality_rules",
  };
  if (fixed[path]) return [t(fixed[path]), undefined];
  if (p[0] === "acquisition_limits" && p[1]) return [`${t("ui.recipe.acq_limits")} › ${t(`acquisition.${p[1]}`, p[1])}`, undefined];
  return [path, undefined];
}

function valueText(v: unknown, t: (k: string, d?: string) => string): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "boolean") return t(v ? "ui.diff.on" : "ui.diff.off");
  if (Array.isArray(v)) return t("ui.diff.items").replace("{n}", String(v.length));
  if (typeof v === "object") return JSON.stringify(v).slice(0, 60);
  return String(v);
}

export function RecipeDiffView({ diff }: { diff: RecipeDiff }) {
  const { t, label, modules } = useApp();
  if (!diff.base) return null;
  if (!diff.changes.length) return <div className="muted">{t("ui.diff.none")}</div>;
  return (
    <table className="table">
      <thead><tr><th>{t("ui.diff.item")}</th><th>v{diff.base.version}</th><th>{t("ui.diff.new")}</th></tr></thead>
      <tbody>
        {diff.changes.map((c) => {
          const [name, def] = pathLabel(c.path, t, label, modules);
          const show = (v: unknown) => (v === null || v === undefined) && def !== undefined && def !== null
            ? `${valueText(def, t)}（${t("ui.diff.default")}）` : valueText(v, t);
          return (
            <tr key={c.path}><td>{name}</td><td className="muted">{show(c.old)}</td><td><b>{show(c.new)}</b></td></tr>
          );
        })}
      </tbody>
    </table>
  );
}

type Scope = "all_previous" | "lot" | "none";

// 發布並重新分析 (PLAN-003 第 5.2 節)：預設重新分析使用此配方舊版本的全部影像
export function ReleaseDialog({ pk, name, onClose, onReleased }:
  { pk: number; name: string; onClose: () => void; onReleased: (row: RecipeRow) => void }) {
  const { t } = useApp();
  const nav = useNavigate();
  const [diff, setDiff] = useState<RecipeDiff | null>(null);
  const [scope, setScope] = useState<ReanalysisScope | null>(null);
  const [mode, setMode] = useState<Scope>("all_previous");
  const [lot, setLot] = useState("");
  const [keepRegions, setKeepRegions] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<(RecipeRow & { reanalysis?: { queued: number; skipped: string[] } }) | null>(null);

  useEffect(() => {
    get<RecipeDiff>(`/api/recipes/${pk}/diff`).then(setDiff).catch(setError);
    get<ReanalysisScope>(`/api/recipes/${pk}/reanalysis-scope`).then((s) => {
      setScope(s);
      if (!s.total) setMode("none");
      if (s.lots.length) setLot(s.lots[0].lot_no);
    }).catch(setError);
  }, [pk]);

  const count = !scope ? 0 : mode === "all_previous" ? scope.total : mode === "lot" ? (scope.lots.find((l) => l.lot_no === lot)?.n || 0) : 0;
  const minutes = scope?.avg_elapsed_s && count ? Math.max(1, Math.ceil((count * scope.avg_elapsed_s) / Math.max(1, scope.workers) / 60)) : 0;

  const submit = async () => {
    setBusy(true);
    try {
      const r = await send<RecipeRow & { reanalysis?: { queued: number; skipped: string[] } }>("POST", `/api/recipes/${pk}/release`,
        { reanalyze: mode, lot_no: mode === "lot" ? lot : "", keep_image_regions: keepRegions });
      setDone(r);
      setError(null);
      onReleased(r);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <Modal title={t("ui.recipe.released_title")} onClose={onClose}
        footer={<>
          <button className="btn" onClick={onClose}>{t("ui.close")}</button>
          {done.reanalysis && done.reanalysis.queued > 0 && <button className="btn primary" onClick={() => nav("/imports")}>{t("ui.reanalysis.view_progress")}</button>}
        </>}>
        <p>{name}</p>
        {done.reanalysis
          ? <p>{t("ui.reanalysis.queued").replace("{n}", String(done.reanalysis.queued))}
            {done.reanalysis.skipped.length > 0 && `；${t("ui.reanalysis.skipped").replace("{n}", String(done.reanalysis.skipped.length))}`}</p>
          : <p className="muted">{t("ui.recipe.release_no_reanalysis")}</p>}
      </Modal>
    );
  }
  return (
    <Modal title={t("ui.recipe.confirm_release")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{t("ui.cancel")}</button>
        <button className="btn primary" disabled={busy || !scope || (mode === "lot" && !lot)} onClick={submit}>{t("ui.recipe.release")}</button>
      </>}>
      <p><b>{name}</b></p>
      {diff?.base && (
        <div className="stack">
          <h3>{t("ui.diff.title").replace("{v}", String(diff.base.version))}</h3>
          <RecipeDiffView diff={diff} />
        </div>
      )}
      <h3>{t("ui.recipe.reanalyze_after")}</h3>
      <label className="check"><input type="radio" checked={mode === "all_previous"} disabled={!scope?.total} onChange={() => setMode("all_previous")} />
        {t("ui.recipe.scope_all").replace("{n}", String(scope?.total ?? "…"))}
        {scope && scope.skipped > 0 && <span className="muted">（{t("ui.recipe.scope_skipped").replace("{n}", String(scope.skipped))}）</span>}</label>
      <label className="check"><input type="radio" checked={mode === "lot"} disabled={!scope?.lots.length} onChange={() => setMode("lot")} />
        {t("ui.recipe.scope_lot")}
        <select value={lot} disabled={mode !== "lot"} onChange={(e) => setLot(e.target.value)}>
          {scope?.lots.map((l) => <option key={l.lot_no} value={l.lot_no}>{l.lot_no}（{l.n}）</option>)}
        </select></label>
      <label className="check"><input type="radio" checked={mode === "none"} onChange={() => setMode("none")} />{t("ui.recipe.scope_none")}</label>
      {mode !== "none" && !!scope?.image_regions && (
        <label className="check" title={t("ui.image_regions.keep_hint")}>
          <input type="checkbox" checked={keepRegions} onChange={(e) => setKeepRegions(e.target.checked)} />
          {t("ui.image_regions.keep").replace("{n}", String(scope.image_regions))}
        </label>
      )}
      {minutes > 0 && <p className="muted">{t("ui.recipe.scope_estimate").replace("{n}", String(count)).replace("{m}", String(minutes))}</p>}
      <p className="muted">{t("ui.recipe.confirm_release_hint")}</p>
      <ErrorBox error={error} />
    </Modal>
  );
}
