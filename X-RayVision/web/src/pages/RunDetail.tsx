import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { get, send } from "../api/client";
import type { Finding, HistoryItem, Judgment, ModuleResult, RunDetail as RunDetailT } from "../api/types";
import { reasonText, useApp } from "../app/context";
import { FindingTable, SummaryKV } from "../components/ModuleSummary";
import { DiagnosticsDialog } from "../components/DiagnosticsDialog";
import { ImageViewer, buildShapes, layersOf, pickFinding } from "../components/ImageViewer";
import { Layout } from "../components/Layout";
import { ReanalyzeDialog } from "../components/ReanalyzeDialog";
import { ErrorBox, JudgmentBadge, QualityBadge, fmt, fmtSigned, fmtTime, useLoad } from "../components/ui";
import { RUNS_NAV_KEY } from "./Runs";

type Tab = "result" | "quality" | "groups" | "object" | "acq" | "history" | "review";

// 紀錄頁當時的清單順序 (上一張／下一張、返回原位置)
function runsNav(): { ids: number[]; query: string } | null {
  try {
    const v = JSON.parse(sessionStorage.getItem(RUNS_NAV_KEY) || "null");
    return v && Array.isArray(v.ids) ? v : null;
  } catch {
    return null;
  }
}

export function RunDetail() {
  const { id } = useParams();
  const runId = Number(id);
  const { t, modules, can } = useApp();
  const nav = useNavigate();
  const [data, error, reload] = useLoad(() => get<RunDetailT>(`/api/runs/${runId}`), [runId]);
  const [tab, setTab] = useState<Tab>("result");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [opacity, setOpacity] = useState(0.9);
  const [vscale, setVscale] = useState(10);
  const [bright, setBright] = useState(1);
  const [contrast, setContrast] = useState(1);
  const [picked, setPicked] = useState<{ moduleId: string; finding: Finding } | null>(null);
  const [showDiag, setShowDiag] = useState(false);
  const [showReanalyze, setShowReanalyze] = useState(false);
  useEffect(() => setPicked(null), [runId]);          // 上一張／下一張切換時清除點選的物件

  const shapes = useMemo(() => (data ? buildShapes(data.result, modules, vscale, t("ui.group")) : []),
    [data, modules, vscale, t]);
  const layers = useMemo(() => layersOf(shapes), [shapes]);

  if (!data) {
    return <Layout title={t("ui.run_detail")}><ErrorBox error={error} /></Layout>;
  }
  const { run, result, reviews } = data;
  const imgSrc = `/api/runs/${runId}/image?max_size=4096`;
  const navList = runsNav();
  const idx = navList ? navList.ids.indexOf(runId) : -1;
  const prevId = idx > 0 ? navList!.ids[idx - 1] : null;
  const nextId = idx >= 0 && idx + 1 < navList!.ids.length ? navList!.ids[idx + 1] : null;
  const backTo = `/runs?${navList?.query ? navList.query + "&" : ""}sel=${runId}`;

  return (
    <Layout full title={`${run.file_name}`}
      actions={<>
        <Link className="btn" to={backTo}>{t("ui.back_to_runs")}</Link>
        {idx >= 0 && <>
          <button className="btn" disabled={!prevId} onClick={() => prevId && nav(`/runs/${prevId}`)}>{t("ui.prev_image")}</button>
          <button className="btn" disabled={!nextId} onClick={() => nextId && nav(`/runs/${nextId}`)}>{t("ui.next_image")}</button>
        </>}
        <Link className="btn" to={`/runs/${runId}/report`}>{t("ui.report")}</Link>
        {can("import") && <button className="btn" onClick={() => setShowReanalyze(true)}>{t("ui.reanalyze")}</button>}
        {result.modules.some((m) => m.module_id === "void") && (
          <Link className="btn" to={`/runs/${runId}/annotate`}>{t(can("annotate") ? "ui.annot.open" : "ui.annot.view")}</Link>
        )}
        {can("diagnostics") && <button className="btn" onClick={() => setShowDiag(true)}>{t("ui.diag.export")}</button>}
      </>}>
      <div className="review-layout">
        <div style={{ position: "relative", minHeight: 0 }}>
          <ImageViewer src={imgSrc} width={result.image.width} height={result.image.height} shapes={shapes}
            hiddenLayers={hidden} opacity={opacity} brightness={bright} contrast={contrast}
            selected={picked ? `${picked.moduleId}:${picked.finding.id}` : null}
            onPick={(x, y) => {
              const p = pickFinding(result, x, y);
              setPicked(p);
              if (p) setTab("object");
            }} />
          <div className="viewer-tools">
            <div className="panel">
              {layers.map((l) => (
                <label key={l} className="check" style={{ fontSize: "var(--fs-xs)" }}>
                  <input type="checkbox" checked={!hidden.has(l)} onChange={() => {
                    const n = new Set(hidden);
                    if (n.has(l)) n.delete(l);
                    else n.add(l);
                    setHidden(n);
                  }} />
                  {t(`ui.layer.${l.split(".").slice(1).join(".")}`, l)}
                </label>
              ))}
            </div>
            <div className="panel">
              {t("ui.opacity")}<input type="range" min={0} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(+e.target.value)} />
              {t("ui.vector_scale")}<input type="range" min={1} max={40} step={1} value={vscale} onChange={(e) => setVscale(+e.target.value)} />×{vscale}
            </div>
            <div className="panel">
              {t("ui.brightness")}<input type="range" min={0.3} max={2.5} step={0.05} value={bright} onChange={(e) => setBright(+e.target.value)} />
              {t("ui.contrast")}<input type="range" min={0.3} max={3} step={0.05} value={contrast} onChange={(e) => setContrast(+e.target.value)} />
              <button className="btn small" onClick={() => { setBright(1); setContrast(1); }}>{t("ui.reset")}</button>
            </div>
          </div>
        </div>
        <aside className="side">
          <div style={{ padding: "var(--sp-3) var(--sp-4)", borderBottom: "1px solid var(--border)" }} className="stack">
            <div className="row">
              <JudgmentBadge value={run.final_judgment} />
              {run.final_judgment !== run.auto_judgment && (
                <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.auto_judgment")}: {t(`judgment.${run.auto_judgment}`)}</span>
              )}
              <span className="spacer" />
              <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.quality")}</span>
              <QualityBadge value={run.quality_level} />
            </div>
            {run.superseded_by && (
              <div className="alert info">{t("ui.run.superseded")}{" "}
                <Link to={`/runs/${run.superseded_by}`}>{t("ui.run.goto_current")}</Link></div>
            )}
            {result.reference_only && <div className="alert info">{t("note.non_raw_image")}</div>}
            {result.notes.includes("regions_scaled") && <div className="alert info">{t("note.regions_scaled")}</div>}
            <dl className="kv">
              <dt>{t("ui.lot")}</dt><dd>{run.lot_no || "–"}</dd>
              <dt>{t("ui.sample")}</dt><dd>{run.sample_no}</dd>
              <dt>{t("ui.recipe")}</dt><dd>{run.recipe_id} v{run.recipe_version}</dd>
              <dt>{t("ui.time")}</dt><dd>{fmtTime(run.created_at)}</dd>
            </dl>
          </div>
          <div className="tabs">
            {(["result", "quality", "groups", "object", "acq", "history", "review"] as Tab[]).filter((k) => k !== "review" || can("review")).map((k) => (
              <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{t(`ui.tab.${k}`)}</button>
            ))}
          </div>
          <div className="side-body">
            {tab === "result" && <ResultTab data={data} />}
            {tab === "quality" && <QualityTab data={data} />}
            {tab === "groups" && <GroupsTab modules={result.modules} />}
            {tab === "object" && <ObjectTab picked={picked} />}
            {tab === "acq" && <AcqTab data={data} />}
            {tab === "history" && <HistoryTab items={data.history} current={runId} />}
            {tab === "review" && <ReviewTab runId={runId} reviews={reviews} current={run.final_judgment} onDone={reload} />}
          </div>
        </aside>
      </div>
      {showDiag && <DiagnosticsDialog runIds={[runId]} onClose={() => setShowDiag(false)} />}
      {showReanalyze && <ReanalyzeDialog runIds={[runId]} onClose={() => setShowReanalyze(false)} />}
    </Layout>
  );
}

function ResultTab({ data }: { data: RunDetailT }) {
  const { t, label, modules } = useApp();
  const r = data.result;
  return (
    <>
      {r.judgment_reasons.length > 0 && (
        <div className="stack">
          <h3>{t("ui.reasons")}</h3>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {r.judgment_reasons.map((x) => <li key={x}>{reasonText(t, x)}</li>)}
          </ul>
        </div>
      )}
      {r.modules.map((m) => {
        const s = m.summary || {};
        const d = s.die_shift;
        const px = s.pixel_size_um as number | null | undefined;
        return (
          <div key={m.module_id} className="stack">
            <div className="row"><h3>{label(modules[m.module_id]?.names, m.module_id)}</h3><span className="spacer" />
              <JudgmentBadge value={m.judgment} /></div>
            {r.unvalidated_modules?.includes(m.module_id) && <div className="alert info">{t("note.module_unvalidated")}</div>}
            {m.status !== "ok" && <div className="alert info">{t(`status.${m.status}`)}：{m.reasons.map((x) => reasonText(t, x)).join("、")}</div>}
            {d && (
              <table className="table">
                <tbody>
                  <tr><th>{t("ui.die_shift")}</th><td className="num">{fmtSigned(d.dx)}, {fmtSigned(d.dy)} px</td>
                    <td className="num">{d.dx_um !== undefined ? `${fmtSigned(d.dx_um)}, ${fmtSigned(d.dy_um)} µm` : "–"}</td></tr>
                  <tr><th>{t("ui.magnitude")}</th><td className="num">{fmt(d.mag, 3)} px</td>
                    <td className="num">{d.mag_um !== undefined ? `${fmt(d.mag_um, 3)} µm` : "–"}</td></tr>
                  <tr><th>{t("ui.std_error")}</th><td className="num">± {fmt(d.se, 3)} px</td>
                    <td className="num">{d.se_um !== undefined ? `± ${fmt(d.se_um, 3)} µm` : "–"}</td></tr>
                  <tr><th>{t("ui.correction")}</th><td className="num" colSpan={2}>{fmtSigned(-d.dx)}, {fmtSigned(-d.dy)} px</td></tr>
                  <tr><th>{t("ui.rotation")}</th><td className="num" colSpan={2}>{fmt(d.rot_deg, 4)}°</td></tr>
                  <tr><th>{t("ui.scale")}</th><td className="num" colSpan={2}>{fmt(d.scale_ppm, 0)} ppm</td></tr>
                  <tr><th>{t("ui.inliers")}</th><td className="num" colSpan={2}>{d.n_in} / {d.n}</td></tr>
                </tbody>
              </table>
            )}
            {s.sites_used === undefined && <SummaryKV m={m} />}
            {s.sites_used === undefined && <FindingTable m={m} info={modules[m.module_id]} compact />}
            <dl className="kv">
              {s.sites_used !== undefined && <><dt>{t("ui.sites_used")}</dt><dd>{fmt(s.sites_used as number, 0)} / {fmt(s.candidates as number, 0)}</dd></>}
              <dt>{t("ui.pixel_size")}</dt><dd>{px ? `${fmt(px, 4)} µm/px (${t(`ui.pixel_source.${s.pixel_size_source}`)})` : t("ui.not_set")}</dd>
              <dt>{t("ui.module_version")}</dt><dd>{m.module_version}</dd>
              <dt>{t("ui.elapsed")}</dt><dd>{fmt(m.elapsed_s, 1)} s</dd>
            </dl>
          </div>
        );
      })}
      <dl className="kv muted">
        <dt>{t("ui.software_version")}</dt><dd>{r.software_version}</dd>
        <dt>SHA-256</dt><dd className="mono" style={{ wordBreak: "break-all" }}>{r.image.sha256}</dd>
        <dt>{t("ui.image_kind")}</dt><dd>{t(`image.kind.${r.image.kind}`)} {r.image.width}×{r.image.height}</dd>
      </dl>
    </>
  );
}

function QualityTab({ data }: { data: RunDetailT }) {
  const { t } = useApp();
  const q = data.result.quality;
  const checked = new Map(q.checks.map((c) => [c.metric, c]));
  const keys = Array.from(new Set([...q.checks.map((c) => c.metric), ...Object.keys(q.metrics)]));
  const lim = (lo?: number | null, hi?: number | null) =>
    [lo !== null && lo !== undefined ? `< ${fmt(lo, 3)}` : "", hi !== null && hi !== undefined ? `> ${fmt(hi, 3)}` : ""].filter(Boolean).join(" / ") || "–";
  return (
    <table className="table">
      <thead><tr><th>{t("ui.metric")}</th><th className="num">{t("ui.value")}</th><th>{t("ui.warn")}</th><th>{t("ui.fail")}</th><th>{t("ui.level")}</th></tr></thead>
      <tbody>
        {keys.map((k) => {
          const c = checked.get(k);
          const v = c ? c.value : q.metrics[k];
          return (
            <tr key={k}>
              <td>{t(`metric.${k}`, t(k, k))}</td>
              <td className="num">{typeof v === "number" ? fmt(v, Math.abs(v) >= 100 ? 0 : 3) : String(v ?? "–")}</td>
              <td className="muted">{c ? lim(c.rule.warn_below, c.rule.warn_above) : ""}</td>
              <td className="muted">{c ? lim(c.rule.fail_below, c.rule.fail_above) : ""}</td>
              <td>{c ? <QualityBadge value={c.level} /> : <span className="muted">–</span>}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function GroupsTab({ modules }: { modules: ModuleResult[] }) {
  const { t } = useApp();
  return (
    <>
      {modules.map((m) => (
        <table key={m.module_id} className="table">
          <thead><tr><th>{t("ui.group")}</th><th className="num">{t("ui.count")}</th><th className="num">dx</th>
            <th className="num">dy</th><th className="num">se</th><th className="num">ppm</th><th>{t("ui.grade")}</th></tr></thead>
          <tbody>
            {m.groups.map((g) => (
              <tr key={g.id}>
                <td>{g.id}</td><td className="num">{g.estimate ? `${g.estimate.n_in}/${g.size}` : g.size}</td>
                <td className="num">{fmtSigned(g.estimate?.dx)}</td><td className="num">{fmtSigned(g.estimate?.dy)}</td>
                <td className="num">{fmt(g.estimate?.se, 3)}</td><td className="num">{fmt(g.estimate?.scale_ppm, 0)}</td>
                <td>{g.grade ? t(`grade.${g.grade}`) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </>
  );
}

function ObjectTab({ picked }: { picked: { moduleId: string; finding: Finding } | null }) {
  const { t } = useApp();
  if (!picked) return <div className="muted">{t("ui.object.hint")}</div>;
  const f = picked.finding;
  return (
    <div className="stack">
      <div className="row"><h3>{t(`finding.${f.category}`, f.category)} #{f.id}</h3><span className="spacer" />
        {f.used ? <span className="badge q-pass">{t("ui.used")}</span> : <span className="badge q-warn">{reasonText(t, f.reason)}</span>}</div>
      <dl className="kv">
        <dt>{t("ui.group")}</dt><dd>{f.group || "–"}</dd>
        {Object.entries(f.flags).map(([k, v]) => <Fragment key={k}><dt>{t(`ui.flag.${k}`, k)}</dt><dd>{t(`ui.flagval.${k}.${String(v)}`, String(v))}</dd></Fragment>)}
      </dl>
      <table className="table">
        <tbody>
          {Object.entries(f.measurements).map(([k, v]) => (
            <tr key={k}><th>{t(`measure.${k}`, k)}</th><td className="num">{fmt(v, 3)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AcqTab({ data }: { data: RunDetailT }) {
  const { t } = useApp();
  const a = data.result.acquisition;
  const cal = data.result.calibration;
  return (
    <div className="stack">
      <dl className="kv">
        <dt>{t("ui.acq.source")}</dt><dd>{t(`ui.acq.source.${a.source}`, a.source)}</dd>
        {Object.entries(a.params).filter(([k]) => k !== "extra").map(([k, v]) => (
          <Fragment key={k}><dt>{t(`acquisition.${k}`, k)}</dt><dd>{String(v)}</dd></Fragment>
        ))}
        {a.params.extra ? Object.entries(a.params.extra as Record<string, unknown>).map(([k, v]) => (
          <Fragment key={`x-${k}`}><dt>{k}</dt><dd>{String(v)}</dd></Fragment>
        )) : null}
      </dl>
      <h3>{t("ui.calibration")}</h3>
      <div>{cal ? `${cal.profile_id}` : t("ui.not_used")}</div>
    </div>
  );
}

function ReviewTab({ runId, reviews, current, onDone }:
  { runId: number; reviews: RunDetailT["reviews"]; current: Judgment; onDone: () => void }) {
  const { t } = useApp();
  const [judgment, setJudgment] = useState<Judgment>(current === "fail" ? "fail" : "pass");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await send("POST", `/api/runs/${runId}/review`, { judgment, comment });
      setComment("");
      setError(null);
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      <div className="row">
        {(["pass", "fail", "review"] as Judgment[]).map((j) => (
          <label key={j} className="check"><input type="radio" name="j" checked={judgment === j} onChange={() => setJudgment(j)} />
            <span className={`badge j-${j}`}>{t(`judgment.${j}`)}</span></label>
        ))}
      </div>
      <textarea rows={3} value={comment} placeholder={t("ui.review.comment")} onChange={(e) => setComment(e.target.value)} />
      <div className="row"><span className="spacer" /><button className="btn primary" disabled={busy} onClick={submit}>{t("ui.review.submit")}</button></div>
      <ErrorBox error={error} />
      <h3>{t("ui.review.history")}</h3>
      {reviews.length === 0 ? <div className="muted">{t("ui.review.none")}</div> : (
        <table className="table">
          <tbody>
            {[...reviews].reverse().map((r) => (
              <tr key={r.id}><td>{fmtTime(r.created_at)}</td><td>{r.reviewer}</td><td><JudgmentBadge value={r.judgment} /></td><td>{r.comment}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// 分析歷程：同一影像的所有紀錄；舊紀錄的人工複判不沿用到新結果，僅供參考
function HistoryTab({ items, current }: { items: HistoryItem[]; current: number }) {
  const { t } = useApp();
  return (
    <div className="stack">
      <div className="muted">{t("ui.history.hint")}</div>
      {items.map((h, i) => (
        <div key={h.id} className="stack" style={{ gap: 4, paddingBottom: "var(--sp-3)", borderBottom: "1px solid var(--border)" }}>
          <div className="row">
            {h.id === current ? <b>#{h.id}</b> : <Link to={`/runs/${h.id}`}>#{h.id}</Link>}
            <span className="muted">{fmtTime(h.created_at)}</span>
            <span>{h.recipe_id} v{h.recipe_version}</span>
            <span className="spacer" />
            {i === 0 ? <span className="tag">{t("ui.history.current")}</span> : <span className="tag">{t("ui.run.superseded_tag")}</span>}
            <JudgmentBadge value={h.final_judgment} />
          </div>
          {h.reviews.map((r, j) => (
            <div key={j} className="muted" style={{ fontSize: "var(--fs-xs)" }}>
              {t("ui.history.review")}：{t(`judgment.${r.judgment}`)}　{r.reviewer}　{fmtTime(r.created_at)}{r.comment ? `　${r.comment}` : ""}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
