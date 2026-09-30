import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, send } from "../api/client";
import type { RecipeSummary } from "../api/types";
import { useApp } from "../app/context";
import { ErrorBox, Modal, useLoad } from "./ui";

interface Result { queued: number; skipped: string[]; no_recipe: string[] }

// 重新分析 (單筆或批次)：預設使用各紀錄所用配方的最新發布版本；新結果成為該影像的目前結果
export function ReanalyzeDialog({ runIds, onClose, onDone }: { runIds: number[]; onClose: () => void; onDone?: () => void }) {
  const { t } = useApp();
  const nav = useNavigate();
  const [recipes] = useLoad(() => get<RecipeSummary[]>("/api/recipes"), []);
  const [mode, setMode] = useState<"latest" | "pick">("latest");
  const [pk, setPk] = useState<number | null>(null);
  const [keepRegions, setKeepRegions] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<Result | null>(null);
  const released = (recipes || []).flatMap((r) => r.versions.filter((v) => v.status === "released").map((v) => ({ ...v, recipe_id: r.recipe_id })));

  const submit = async () => {
    setBusy(true);
    try {
      setResult(await send<Result>("POST", "/api/runs/reanalyze", { run_ids: runIds, recipe_pk: mode === "pick" ? pk : null, keep_image_regions: keepRegions }));
      setError(null);
      onDone?.();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <Modal title={t("ui.reanalyze")} onClose={onClose}
        footer={<>
          <button className="btn" onClick={onClose}>{t("ui.close")}</button>
          <button className="btn primary" onClick={() => nav("/imports")}>{t("ui.reanalysis.view_progress")}</button>
        </>}>
        <p>{t("ui.reanalysis.queued").replace("{n}", String(result.queued))}</p>
        {result.skipped.length > 0 && <p className="muted">{t("ui.reanalysis.skipped").replace("{n}", String(result.skipped.length))}：{result.skipped.join("、")}</p>}
        {result.no_recipe.length > 0 && <p className="muted">{t("ui.reanalysis.no_recipe")}：{result.no_recipe.join("、")}</p>}
      </Modal>
    );
  }
  return (
    <Modal title={runIds.length > 1 ? `${t("ui.reanalyze")}（${runIds.length}）` : t("ui.reanalyze")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{t("ui.cancel")}</button>
        <button className="btn primary" disabled={busy || (mode === "pick" && !pk)} onClick={submit}>{t("ui.reanalyze")}</button>
      </>}>
      <label className="check"><input type="radio" checked={mode === "latest"} onChange={() => setMode("latest")} />{t("ui.reanalysis.latest")}</label>
      <label className="check"><input type="radio" checked={mode === "pick"} onChange={() => setMode("pick")} />{t("ui.reanalysis.pick")}</label>
      {mode === "pick" && (
        <label className="field">{t("ui.recipe")}
          <select value={pk ?? ""} onChange={(e) => setPk(Number(e.target.value) || null)}>
            <option value="">{t("ui.select")}</option>
            {released.map((v) => <option key={v.id} value={v.id}>{v.recipe_id} v{v.version}</option>)}
          </select>
        </label>
      )}
      <label className="check" title={t("ui.image_regions.keep_hint")}>
        <input type="checkbox" checked={keepRegions} onChange={(e) => setKeepRegions(e.target.checked)} />{t("ui.image_regions.keep_batch")}
      </label>
      <p className="muted">{t("ui.reanalysis.hint")}</p>
      <ErrorBox error={error} />
    </Modal>
  );
}
