import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { send } from "../api/client";
import type { AnalysisResult, Regions, RunDetail } from "../api/types";
import { useApp } from "../app/context";
import { buildShapes } from "./ImageViewer";
import { arraysSupported } from "./RecipeForm";
import { RegionCanvas } from "./RegionEditor";
import { ModuleMeasures } from "./RunPreview";
import { ErrorBox, JudgmentBadge, QualityBadge } from "./ui";

// 本影像自訂檢測區域 (PLAN-004 第 6 節)：以同一配方版本＋自訂區域試跑或重新分析；自訂區域取代配方區域
export function ImageRegionsDialog({ data, onClose }: { data: RunDetail; onClose: () => void }) {
  const { t, label, modules } = useApp();
  const nav = useNavigate();
  const { run, result } = data;
  const custom = result.regions_source === "image";
  const [regions, setRegions] = useState<Regions | null>(result.recipe.regions || null);
  const [trial, setTrial] = useState<{ result: AnalysisResult; json: string } | null>(null);
  const [busy, setBusy] = useState<"" | "trial" | "apply" | "reset">("");
  const [error, setError] = useState<unknown>(null);
  const [queued, setQueued] = useState(false);

  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && !document.activeElement?.closest("input,select,textarea") && busy === "" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose, busy]);

  const json = JSON.stringify(regions);
  const shown = trial && trial.json === json ? trial.result : result;
  const shapes = useMemo(() => buildShapes(shown, modules, 10, t("ui.group")), [shown, modules, t]);
  const supported = arraysSupported(result.recipe, modules);

  const call = async (kind: "trial" | "apply" | "reset") => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "trial") {
        const r = await send<{ result: AnalysisResult }>("POST", `/api/runs/${run.id}/regions/trial`, { regions });
        setTrial({ result: r.result, json });
      } else {
        await send("POST", `/api/runs/${run.id}/regions`, { regions: kind === "reset" ? null : regions });
        setQueued(true);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && busy === "" && onClose()}>
      <div className="card modal modal-wide" role="dialog" aria-label={t("ui.image_regions.title")}>
        <div className="card-h">
          <h2>{t("ui.image_regions.title")}：{run.file_name}</h2>
          <span className="muted">{run.recipe_id} v{run.recipe_version}・{t(custom ? "ui.image_regions.current_custom" : "ui.image_regions.current_recipe")}</span>
        </div>
        <div className="card-b stack">
          {queued ? (
            <div className="alert info">{t("ui.image_regions.queued")}</div>
          ) : (
            <>
              <div className="muted">{t("ui.image_regions.hint")}</div>
              <div className="image-regions-layout">
                <RegionCanvas value={regions} onChange={setRegions} readOnly={false} arraysSupported={supported}
                  src={`/api/runs/${run.id}/image?max_size=4096`} width={result.image.width} height={result.image.height}
                  shapes={shapes} viewerHeight="58vh" />
                <div className="stack">
                  <h3>{trial && trial.json === json ? t("ui.image_regions.trial_result") : t("ui.image_regions.current_result")}</h3>
                  <div className="row"><JudgmentBadge value={shown.judgment} /><QualityBadge value={shown.quality.level} /></div>
                  {shown.modules.map((m) => (
                    <div key={m.module_id} className="stack">
                      <b>{label(modules[m.module_id]?.names, m.module_id)}</b>
                      <ModuleMeasures m={m} />
                    </div>
                  ))}
                  {trial && trial.json !== json && <div className="alert info">{t("ui.trial.stale")}</div>}
                  <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.trial.not_saved")}</div>
                </div>
              </div>
            </>
          )}
          <ErrorBox error={error} />
        </div>
        <div className="card-b row" style={{ justifyContent: "flex-end", borderTop: "1px solid var(--border)" }}>
          {queued ? (
            <>
              <button className="btn" onClick={onClose}>{t("ui.close")}</button>
              <button className="btn primary" onClick={() => nav("/imports")}>{t("ui.reanalysis.view_progress")}</button>
            </>
          ) : (
            <>
              {custom && <button className="btn" disabled={busy !== ""} onClick={() => call("reset")}>{t("ui.image_regions.reset")}</button>}
              <span className="spacer" />
              <button className="btn" disabled={busy !== ""} onClick={onClose}>{t("ui.cancel")}</button>
              <button className="btn" disabled={busy !== ""} onClick={() => call("trial")}>{busy === "trial" ? t("ui.trial.running") : t("ui.trial.run")}</button>
              <button className="btn primary" disabled={busy !== "" || !regions} onClick={() => call("apply")}>{t("ui.image_regions.apply")}</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
