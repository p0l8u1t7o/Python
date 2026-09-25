import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { get } from "../api/client";
import type { RunDetail } from "../api/types";
import { reasonText, useApp } from "../app/context";
import { buildShapes, snapshot } from "../components/ImageViewer";
import { FindingTable, SummaryKV } from "../components/ModuleSummary";
import { ErrorBox, fmt, fmtSigned, fmtTime, localNow, useLoad } from "../components/ui";

// 單張檢測報告 (A4 列印版面；瀏覽器「列印」可另存 PDF)
export function Report() {
  const { id } = useParams();
  const runId = Number(id);
  const { t, label, modules } = useApp();
  const [data, error] = useLoad(() => get<RunDetail>(`/api/runs/${runId}`), [runId]);
  const [img, setImg] = useState<string>("");

  useEffect(() => {
    if (!data || !Object.keys(modules).length) return;
    const shapes = buildShapes(data.result, modules, 10, t("ui.group")).filter((s) => !s.layer.endsWith(".rejected"));
    snapshot(`/api/runs/${runId}/image?max_size=2048`, data.result.image.width, data.result.image.height, shapes)
      .then(setImg)
      .catch(() => setImg(""));
  }, [data, modules, runId, t]);

  if (!data) return <div className="content"><ErrorBox error={error} /></div>;
  const { run, result, reviews } = data;
  const lastReview = reviews[reviews.length - 1];
  return (
    <div style={{ background: "var(--bg)", minHeight: "100%" }}>
      <div className="report-toolbar no-print">
        <Link className="btn" to={`/runs/${runId}`}>{t("ui.back")}</Link>
        <button className="btn primary" onClick={() => window.print()}>{t("ui.print")}</button>
      </div>
      <div className="report">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h1>{t("ui.report.title")}</h1>
          <div>{t("product.name")}</div>
        </div>
        {run.superseded_by && <p><b>{t("ui.report.superseded").replace("{id}", String(run.superseded_by))}</b></p>}
        <table>
          <tbody>
            <tr><th>{t("ui.lot")}</th><td>{run.lot_no || "–"}</td><th>{t("ui.sample")}</th><td>{run.sample_no}</td></tr>
            <tr><th>{t("ui.file")}</th><td>{run.file_name}</td><th>{t("ui.time")}</th><td>{fmtTime(run.created_at)}</td></tr>
            <tr><th>{t("ui.recipe")}</th><td>{run.recipe_id} v{run.recipe_version}</td><th>{t("ui.image_kind")}</th>
              <td>{t(`image.kind.${result.image.kind}`)} {result.image.width}×{result.image.height}</td></tr>
            <tr><th>{t("ui.judgment")}</th><td><b>{t(`judgment.${run.final_judgment}`)}</b>
              {run.final_judgment !== run.auto_judgment && ` （${t("ui.auto_judgment")}：${t(`judgment.${run.auto_judgment}`)}）`}</td>
              <th>{t("ui.quality")}</th><td>{t(`quality.${run.quality_level}`)}</td></tr>
          </tbody>
        </table>
        {result.reference_only && <p><b>{t("note.non_raw_image")}</b></p>}
        {result.judgment_reasons.length > 0 && (
          <p>{t("ui.reasons")}：{result.judgment_reasons.map((x) => reasonText(t, x)).join("；")}</p>
        )}
        {result.modules.map((m) => {
          const d = m.summary?.die_shift;
          return (
            <div key={m.module_id}>
              <h2 style={{ fontSize: 14, marginTop: 8 }}>{label(modules[m.module_id]?.names, m.module_id)}（{t(`judgment.${m.judgment}`)}）</h2>
              {result.unvalidated_modules?.includes(m.module_id) && <p><b>{t("note.module_unvalidated")}</b></p>}
              {!d && <SummaryKV m={m} />}
              {!d && <FindingTable m={m} info={modules[m.module_id]} />}
              {d && (
                <table>
                  <thead><tr><th></th><th>X</th><th>Y</th><th>{t("ui.magnitude")}</th><th>{t("ui.std_error")}</th></tr></thead>
                  <tbody>
                    <tr><th>{t("ui.die_shift")} (px)</th><td>{fmtSigned(d.dx, 3)}</td><td>{fmtSigned(d.dy, 3)}</td><td>{fmt(d.mag, 3)}</td><td>± {fmt(d.se, 3)}</td></tr>
                    {d.dx_um !== undefined && (
                      <tr><th>{t("ui.die_shift")} (µm)</th><td>{fmtSigned(d.dx_um, 3)}</td><td>{fmtSigned(d.dy_um, 3)}</td><td>{fmt(d.mag_um, 3)}</td><td>± {fmt(d.se_um, 3)}</td></tr>
                    )}
                    <tr><th>{t("ui.correction")} (px)</th><td>{fmtSigned(-d.dx, 3)}</td><td>{fmtSigned(-d.dy, 3)}</td><td colSpan={2}>
                      {t("ui.rotation")} {fmt(d.rot_deg, 4)}°，{t("ui.scale")} {fmt(d.scale_ppm, 0)} ppm，{t("ui.inliers")} {d.n_in}/{d.n}</td></tr>
                  </tbody>
                </table>
              )}
              {m.groups.length > 0 && (
                <table>
                  <thead><tr><th>{t("ui.group")}</th><th>{t("ui.count")}</th><th>dx (px)</th><th>dy (px)</th><th>se (px)</th><th>{t("ui.grade")}</th></tr></thead>
                  <tbody>
                    {m.groups.map((g) => (
                      <tr key={g.id}><td>{g.id}</td><td>{g.estimate ? `${g.estimate.n_in}/${g.size}` : g.size}</td>
                        <td>{fmtSigned(g.estimate?.dx, 3)}</td><td>{fmtSigned(g.estimate?.dy, 3)}</td><td>{fmt(g.estimate?.se, 3)}</td>
                        <td>{g.grade ? t(`grade.${g.grade}`) : "–"}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
        {img && <img className="report-img" src={img} alt={run.file_name} />}
        <table>
          <thead><tr><th>{t("ui.metric")}</th><th>{t("ui.value")}</th><th>{t("ui.level")}</th></tr></thead>
          <tbody>
            {result.quality.checks.map((c) => (
              <tr key={c.metric}><td>{t(`metric.${c.metric}`, c.metric)}</td><td>{fmt(c.value, Math.abs(c.value) >= 100 ? 0 : 3)}</td><td>{t(`quality.${c.level}`)}</td></tr>
            ))}
          </tbody>
        </table>
        {lastReview && (
          <p>{t("ui.review.last")}：{t(`judgment.${lastReview.judgment}`)}，{lastReview.reviewer}，{fmtTime(lastReview.created_at)}
            {lastReview.comment && `，${lastReview.comment}`}</p>
        )}
        <p style={{ color: "#666", marginTop: 12 }}>
          {t("ui.software_version")} {result.software_version}；
          {result.modules.map((m) => `${label(modules[m.module_id]?.names, m.module_id)} ${m.module_version}`).join("；")}；
          SHA-256 {result.image.sha256.slice(0, 16)}…；{t("ui.report.printed_at")} {localNow()}
        </p>
      </div>
    </div>
  );
}
