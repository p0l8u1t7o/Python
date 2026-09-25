import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api/client";
import type { ModuleResult, ModuleSummaryLite, RunDetail } from "../api/types";
import { reasonText, useApp } from "../app/context";
import { ImageViewer, buildShapes } from "./ImageViewer";
import { summaryEntries } from "./ModuleSummary";
import { ErrorBox, JudgmentBadge, QualityBadge, fmt, fmtSigned, fmtTime } from "./ui";

const PREVIEW_PX = 1024;          // 預覽先載入的縮圖長邊
const FULL_PX = 4096;

// 預覽資料快取：清單連續切換時不重複取得；紀錄頁重新進入時清除 (複判等變更才會反映)
const cache = new Map<number, Promise<RunDetail>>();

export function clearRunCache() {
  cache.clear();
}

export function loadRun(id: number): Promise<RunDetail> {
  let p = cache.get(id);
  if (!p) {
    p = get<RunDetail>(`/api/runs/${id}`);
    p.catch(() => cache.delete(id));
    cache.set(id, p);
    if (cache.size > 60) cache.delete(cache.keys().next().value as number);
  }
  return p;
}

export function previewSrc(id: number, full = false) {
  return `/api/runs/${id}/image?max_size=${full ? FULL_PX : PREVIEW_PX}`;
}

// 預先載入 (前後一筆)：結果 JSON 與縮圖
export function prefetchRun(id: number) {
  loadRun(id).catch(() => undefined);
  const im = new Image();
  im.src = previewSrc(id);
}

// 清單與比較表用的主要量測值：晶片偏移，或模組摘要的第一個數值 (空洞模組為最大空洞率)
const PRIMARY = ["max_void_pct"];

export function keyMeasure(t: (k: string, d?: string) => string, mods: Record<string, ModuleSummaryLite>): string {
  const out: string[] = [];
  for (const m of Object.values(mods || {})) {
    const s = m?.summary || {};
    const d = s.die_shift;
    if (d) {
      out.push(d.dx_um !== undefined ? `${fmtSigned(d.dx_um)}, ${fmtSigned(d.dy_um)} µm` : `${fmtSigned(d.dx)}, ${fmtSigned(d.dy)} px`);
      continue;
    }
    const k = PRIMARY.find((x) => typeof s[x] === "number")
      || Object.keys(s).find((x) => typeof s[x] === "number" && !["pixel_size_um", "candidates"].includes(x));
    if (k) out.push(`${t(`summary.${k}`, k)} ${fmt(s[k] as number, Number.isInteger(s[k]) ? 0 : 2)}`);
  }
  return out.join("；");
}

// 模組主要量測 (預覽與試跑比較共用)
export function ModuleMeasures({ m }: { m: ModuleResult }) {
  const { t } = useApp();
  const d = m.summary?.die_shift;
  if (d) {
    return (
      <dl className="kv">
        <dt>{t("ui.die_shift")}</dt>
        <dd>{fmtSigned(d.dx)}, {fmtSigned(d.dy)} px{d.dx_um !== undefined ? `（${fmtSigned(d.dx_um)}, ${fmtSigned(d.dy_um)} µm）` : ""}</dd>
        <dt>{t("ui.std_error")}</dt><dd>± {fmt(d.se, 3)} px</dd>
        <dt>{t("ui.sites_used")}</dt><dd>{fmt(m.summary.sites_used as number, 0)}</dd>
      </dl>
    );
  }
  const items = summaryEntries(m);
  return (
    <dl className="kv">
      {items.map(([k, v]) => <Fragment key={k}><dt>{t(`summary.${k}`, k)}</dt><dd>{fmt(v, Number.isInteger(v) ? 0 : 2)}</dd></Fragment>)}
    </dl>
  );
}

// 紀錄頁右側預覽：影像＋疊圖 (唯讀) 與判定摘要
export function RunPreview({ runId, onReanalyze }: { runId: number; onReanalyze?: () => void }) {
  const { t, label, modules, can } = useApp();
  const [data, setData] = useState<RunDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [full, setFull] = useState(false);

  useEffect(() => {
    let alive = true;
    setError(null);
    setFull(false);
    loadRun(runId).then((d) => alive && setData(d)).catch((e) => alive && setError(e));
    return () => { alive = false; };
  }, [runId]);

  const shapes = useMemo(() => (data && data.run.id === runId ? buildShapes(data.result, modules, 10, t("ui.group")) : []),
    [data, runId, modules, t]);

  if (!data || data.run.id !== runId) {
    return <>
      <div className="browse-viewer">{error ? null : <div className="muted browse-loading">{t("ui.loading")}</div>}</div>
      <aside className="browse-info"><ErrorBox error={error} /></aside>
    </>;
  }
  const { run, result } = data;
  return (
    <>
      <div className="browse-viewer">
        <ImageViewer src={previewSrc(runId, full)} width={result.image.width} height={result.image.height} shapes={shapes}
          hiddenLayers={new Set()} opacity={0.9} brightness={1} contrast={1} />
        {!full && (
          <div className="viewer-tools"><div className="panel">
            <button className="btn small" onClick={() => setFull(true)}>{t("ui.preview.full_res")}</button>
          </div></div>
        )}
      </div>
      <aside className="browse-info">
        <div className="stack">
          <div className="mono" style={{ fontWeight: 600, wordBreak: "break-all" }}>{run.file_name}</div>
          <div className="row">
            <JudgmentBadge value={run.final_judgment} />
            {run.final_judgment !== run.auto_judgment && <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.reviewed")}</span>}
            <span className="spacer" />
            <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.quality")}</span>
            <QualityBadge value={run.quality_level} />
          </div>
          {run.superseded_by && (
            <div className="alert info">{t("ui.run.superseded")}{" "}
              <Link to={`/runs?sel=${run.superseded_by}&all=1`}>{t("ui.run.goto_current")}</Link></div>
          )}
          {result.reference_only && <div className="alert info">{t("note.non_raw_image")}</div>}
          <dl className="kv">
            <dt>{t("ui.lot")}</dt><dd>{run.lot_no || "–"}</dd>
            <dt>{t("ui.sample")}</dt><dd>{run.sample_no}</dd>
            <dt>{t("ui.recipe")}</dt><dd>{run.recipe_id} v{run.recipe_version}</dd>
            <dt>{t("ui.time")}</dt><dd>{fmtTime(run.created_at)}</dd>
          </dl>
          {result.modules.map((m) => (
            <div key={m.module_id} className="stack">
              <div className="row"><h3>{label(modules[m.module_id]?.names, m.module_id)}</h3><span className="spacer" />
                <JudgmentBadge value={m.judgment} /></div>
              <ModuleMeasures m={m} />
            </div>
          ))}
          {result.judgment_reasons.length > 0 && (
            <div className="stack">
              <h3>{t("ui.reasons")}</h3>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {result.judgment_reasons.slice(0, 3).map((x) => <li key={x}>{reasonText(t, x)}</li>)}
                {result.judgment_reasons.length > 3 && <li className="muted">…</li>}
              </ul>
            </div>
          )}
          <div className="row">
            <Link className="btn primary" to={`/runs/${runId}`}>{t("ui.review_open")}</Link>
            <Link className="btn" to={`/runs/${runId}/report`}>{t("ui.report")}</Link>
            {can("import") && onReanalyze && <button className="btn" onClick={onReanalyze}>{t("ui.reanalyze")}</button>}
          </div>
          <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.runs.keys_hint")}</div>
        </div>
      </aside>
    </>
  );
}
