import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, get, send, upload } from "../api/client";
import type { AnalysisResult, RecipeBody, RecipeModule, RecipeRow, RecipeSummary, RunRow, WorkspaceItem, WorkspaceView } from "../api/types";
import { reasonText, useApp } from "../app/context";
import { ImageViewer, buildShapes } from "../components/ImageViewer";
import { Layout } from "../components/Layout";
import { ModuleParamsForm, QualityRulesForm, arraysSupported } from "../components/RecipeForm";
import { RegionCanvas } from "../components/RegionEditor";
import { ModuleMeasures, keyMeasure } from "../components/RunPreview";
import { Empty, ErrorBox, JudgmentBadge, Modal, QualityBadge, fmt, fmtSigned, fmtTime } from "../components/ui";

const IMG_PX = 2048;
const AUTO_DELAY_MS = 1000;
const SAVE_DELAY_MS = 1000;

const imgSrc = (id: number) => `/api/workspace/images/${id}/image?max_size=${IMG_PX}`;

function loadPref(key: string, def: string) {
  try { return localStorage.getItem(key) ?? def; } catch { return def; }
}
function savePref(key: string, v: string) {
  try { localStorage.setItem(key, v); } catch { /* 無法儲存時忽略 */ }
}

// 與來源配方不同的參數鍵 (「params.鍵」「judgment.鍵」)，以及其他變更的項目數
function changedKeys(body: RecipeBody | null, src: RecipeBody | null | undefined): { perModule: Record<string, Set<string>>; count: number } {
  const perModule: Record<string, Set<string>> = {};
  if (!body || !src) return { perModule, count: 0 };
  let count = 0;
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  for (const m of body.modules) {
    const s = src.modules.find((x) => x.module_id === m.module_id);
    const set = new Set<string>();
    for (const part of ["params", "judgment"] as const) {
      const a = (m[part] || {}) as Record<string, unknown>, b = ((s && s[part]) || {}) as Record<string, unknown>;
      for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) if (!same(a[k], b[k])) set.add(`${part}.${k}`);
    }
    if (!s) count += 1;
    perModule[m.module_id] = set;
    count += set.size;
  }
  count += src.modules.filter((s) => !body.modules.some((m) => m.module_id === s.module_id)).length;
  for (const k of ["pixel_size_um", "calibration_profile", "quality_rules", "acquisition_limits", "regions"] as const)
    if (!same(body[k], src[k])) count += 1;
  return { perModule, count };
}

// ---------------------------------------------------------------------------
// 手動檢測 (PLAN-004 第 5 節)：不綁定配方，匯入影像後直接調整參數分析；結果不寫入正式紀錄
// ---------------------------------------------------------------------------
export function ManualInspection() {
  const { t, label, modules, locale, can } = useApp();
  const [ws, setWs] = useState<WorkspaceView | null>(null);
  const [body, setBody] = useState<RecipeBody | null>(null);
  const [savedJson, setSavedJson] = useState("");              // 伺服器上的參數組 (JSON)，判斷是否已存檔
  const [paramsHash, setParamsHash] = useState<string | null>(null);
  const [selId, setSelId] = useState<number | null>(() => Number(loadPref("xrv.manual.sel", "0")) || null);
  const [results, setResults] = useState<Record<number, { hash: string; r: AnalysisResult }>>({});   // 各影像完整結果 (與其參數組雜湊)
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [mode, setMode] = useState<"view" | "regions">("view");
  const [auto, setAuto] = useState(loadPref("xrv.manual.auto", "0") === "1");
  const [advanced, setAdvanced] = useState(false);
  const [tab, setTab] = useState<"table" | "reasons" | "groups" | "quality">("table");
  const [dialog, setDialog] = useState<null | "runs" | "recipe" | "save">(null);
  const [notice, setNotice] = useState<string>("");
  const fileRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const reqSeq = useRef(0);

  const reload = useCallback(async () => {
    const v = await get<WorkspaceView>("/api/workspace");
    setWs(v);
    setParamsHash(v.params_hash);
    return v;
  }, []);

  // 初次載入：沒有參數組時以第一個可用模組的預設值建立
  useEffect(() => {
    reload().then(async (v) => {
      if (v.params) {
        setBody(v.params);
        setSavedJson(JSON.stringify(v.params));
      } else {
        const mid = modules.bump_alignment ? "bump_alignment" : Object.keys(modules)[0];
        if (!mid) return;
        const tpl = await get<RecipeBody>(`/api/recipe-template/${mid}`);
        setBody({ ...tpl, recipe_id: "", name: {} });
      }
    }).catch(setError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Object.keys(modules).length]);

  const images = ws?.images || [];
  const cur = images.find((i) => i.id === selId) || images[0] || null;
  useEffect(() => { if (cur && cur.id !== selId) setSelId(cur.id); }, [cur, selId]);
  useEffect(() => { if (selId) savePref("xrv.manual.sel", String(selId)); }, [selId]);

  const bodyJson = useMemo(() => JSON.stringify(body), [body]);
  const dirty = !!body && bodyJson !== savedJson;
  const isStale = (it: WorkspaceItem) => !it.result || dirty || it.result.hash !== paramsHash;

  // 參數組自動存回工作區 (防抖)
  useEffect(() => {
    if (!body || !dirty) return;
    const h = setTimeout(() => {
      const sent = JSON.stringify(body);
      send<{ params_hash: string }>("PUT", "/api/workspace/params", { body }).then((r) => {
        setSavedJson(sent);
        setParamsHash(r.params_hash);
      }).catch(setError);
    }, SAVE_DELAY_MS);
    return () => clearTimeout(h);
  }, [body, dirty]);

  // 目前影像的完整結果：已有結果但尚未取得時向後端取
  useEffect(() => {
    const it = cur;
    if (!it?.result || results[it.id]?.hash === it.result.hash) return;
    let alive = true;
    const h = it.result.hash;
    get<AnalysisResult>(`/api/workspace/images/${it.id}/result`).then((r) => {
      if (alive) setResults((m) => ({ ...m, [it.id]: { hash: h, r } }));
    }).catch(() => undefined);
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur?.id, cur?.result?.hash]);

  // 前後各預先載入一張影像
  useEffect(() => {
    if (!cur) return;
    const i = images.findIndex((x) => x.id === cur.id);
    for (const j of [i - 1, i + 1]) if (images[j]) { const im = new Image(); im.src = imgSrc(images[j].id); }
  }, [cur, images]);

  const analyze = useCallback(async (it: WorkspaceItem | null) => {
    if (!it || !body) return;
    const seq = ++reqSeq.current;
    const sent = JSON.stringify(body);
    setBusy(it.id);
    setError(null);
    try {
      const r = await send<{ result: AnalysisResult; summary: WorkspaceItem["result"]; params_hash: string }>(
        "POST", `/api/workspace/images/${it.id}/analyze`, { body });
      setSavedJson(sent);
      setParamsHash(r.params_hash);
      setResults((m) => ({ ...m, [it.id]: { hash: r.params_hash, r: r.result } }));
      setWs((w) => w && { ...w, params_hash: r.params_hash, images: w.images.map((x) => (x.id === it.id ? { ...x, result: r.summary } : x)) });
    } catch (e) {
      if (!(e instanceof ApiError && e.code === "superseded")) setError(e);
    } finally {
      if (seq === reqSeq.current) setBusy(null);
    }
  }, [body]);

  // 自動分析：參數停止修改後、或切換到參數已變更的影像時
  useEffect(() => {
    if (!auto || !cur || !body || !isStale(cur) || busy !== null || !ws?.analysis_allowed) return;
    const h = setTimeout(() => analyze(cur), AUTO_DELAY_MS);
    return () => clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, cur?.id, bodyJson, paramsHash]);

  // 分析全部：執行中每秒更新
  const batchRunning = !!ws?.batch?.running;
  useEffect(() => {
    if (!batchRunning) return;
    const h = setInterval(() => reload().catch(() => undefined), 1000);
    return () => clearInterval(h);
  }, [batchRunning, reload]);

  const move = (d: number) => {
    if (!images.length || !cur) return;
    const i = images.findIndex((x) => x.id === cur.id);
    const n = images[Math.min(Math.max(i + d, 0), images.length - 1)];
    setSelId(n.id);
    listRef.current?.querySelector(`[data-id="${n.id}"]`)?.scrollIntoView({ block: "nearest" });
  };

  // 鍵盤：↑↓／PageUp PageDown 切換影像，Ctrl+Enter 分析
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); if (ws?.analysis_allowed) analyze(cur); return; }
      if (["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName) || document.querySelector(".modal-back")) return;
      if (e.key === "ArrowDown" || e.key === "PageDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp" || e.key === "PageUp") { e.preventDefault(); move(-1); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  const onFiles = async (files: FileList | null) => {
    if (!files || !files.length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f, f.name));
    setError(null);
    try {
      const r = await upload<{ added: number[]; errors: { file: string; error: string }[] }>("/api/workspace/images", fd);
      const v = await reload();
      if (r.added.length && !v.images.some((x) => x.id === selId)) setSelId(r.added[0]);
      setNotice(r.errors.length ? r.errors.map((x) => `${x.file}：${t(`error.${x.error}`, x.error)}`).join("；") : "");
    } catch (e) {
      setError(e);
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const removeItem = async (id: number) => {
    await send("DELETE", `/api/workspace/images/${id}`).catch(setError);
    setResults((m) => { const n = { ...m }; delete n[id]; return n; });
    reload().catch(setError);
  };
  const clearAll = async () => {
    if (!window.confirm(t("ui.manual.clear_confirm"))) return;
    await send("DELETE", "/api/workspace").catch(setError);
    setResults({});
    setSavedJson("");
    await reload().catch(setError);
  };
  const analyzeAll = async () => {
    setError(null);
    try {
      await send("POST", "/api/workspace/analyze-all", { body });
      setSavedJson(JSON.stringify(body));
      await reload();
    } catch (e) {
      setError(e);
    }
  };

  const src = ws?.source || null;
  const changes = useMemo(() => changedKeys(body, src?.body), [body, src]);
  const result = cur ? results[cur.id]?.r : undefined;
  const resultStale = !!cur && isStale(cur);
  const shapes = useMemo(() => (result ? buildShapes(result, modules, 10, t("ui.group")) : []), [result, modules, t]);
  const upd = (patch: Partial<RecipeBody>) => body && setBody({ ...body, ...patch });

  const toggleModule = async (mid: string, on: boolean) => {
    if (!body) return;
    if (!on) {
      if (body.modules.length <= 1) return;
      upd({ modules: body.modules.filter((m) => m.module_id !== mid) });
      return;
    }
    const tpl = await get<RecipeBody>(`/api/recipe-template/${mid}`).catch((e) => { setError(e); return null; });
    if (tpl) setBody((b) => b && { ...b, modules: [...b.modules, tpl.modules[0]] });
  };

  if (!body || !ws) {
    return <Layout title={t("ui.nav.manual")}><ErrorBox error={error} />{!error && <div className="muted">{t("ui.loading")}</div>}</Layout>;
  }

  const batch = ws.batch;
  return (
    <Layout full title={t("ui.nav.manual")}
      actions={<>
        <input ref={fileRef} type="file" multiple hidden accept=".tif,.tiff,.png,.bmp,.jpg,.jpeg,.json,.txt,.ini" onChange={(e) => onFiles(e.target.files)} />
        <button className="btn" onClick={() => fileRef.current?.click()}>{t("ui.manual.upload")}</button>
        <button className="btn" onClick={() => setDialog("runs")}>{t("ui.manual.from_runs")}</button>
        <button className="btn" onClick={() => setDialog("recipe")}>{t("ui.manual.from_recipe")}</button>
        {can("recipe_edit") && <button className="btn" onClick={() => setDialog("save")}>{t("ui.manual.save_recipe")}</button>}
        <a className={`btn${images.some((i) => i.result) ? "" : " disabled"}`} href={`/api/workspace/export?locale=${locale}`}>{t("ui.manual.export")}</a>
        <button className="btn danger" onClick={clearAll}>{t("ui.manual.clear")}</button>
      </>}>
      <div className="manual-page">
        <div className="manual-banner">
          <strong>{t("ui.manual.banner")}</strong>
          <span className="muted">{src
            ? `${t("ui.manual.source")}：${src.recipe_id} v${src.version}（${t(`recipe.${src.status}`)}）${changes.count ? `・${t("ui.manual.changed_n").replace("{n}", String(changes.count))}` : ""}`
            : t("ui.manual.no_source")}</span>
          <span className="spacer" />
          <span className="muted">{t("ui.manual.usage").replace("{n}", String(ws.usage.images)).replace("{max}", String(ws.usage.max_images))
            .replace("{mb}", fmt(ws.usage.bytes / 1048576, 0)).replace("{maxmb}", fmt(ws.usage.max_bytes / 1048576, 0))}</span>
        </div>
        {!ws.analysis_allowed && <div className="alert error" style={{ margin: "var(--sp-2) var(--sp-4) 0" }}>{t("ui.manual.license_blocked")}</div>}
        {notice && <div className="alert info" style={{ margin: "var(--sp-2) var(--sp-4) 0" }}>{notice}</div>}
        {!!error && <div style={{ margin: "var(--sp-2) var(--sp-4) 0" }}><ErrorBox error={error} /></div>}
        <div className="manual-layout">
          {/* 影像清單 */}
          <div className="browse-list" ref={listRef}>
            <div className="browse-list-h">
              <span className="muted">{t("ui.manual.images").replace("{n}", String(images.length))}</span>
              <span className="spacer" />
              {batchRunning
                ? <button className="btn small" onClick={() => send("POST", "/api/workspace/analyze-all/cancel").then(reload)}>{t("ui.cancel")}</button>
                : <button className="btn small primary" disabled={!images.length || !ws.analysis_allowed} onClick={analyzeAll}>{t("ui.manual.analyze_all")}</button>}
            </div>
            {batch && (batch.running || batch.total > 0) && (
              <div className="manual-progress">
                <div className="progress"><div style={{ width: `${batch.total ? (batch.done / batch.total) * 100 : 100}%` }} /></div>
                <span className="muted">{t("ui.manual.batch_progress").replace("{done}", String(batch.done)).replace("{total}", String(batch.total))
                  .replace("{failed}", String(batch.failed))}</span>
              </div>
            )}
            {!images.length && <div style={{ padding: "var(--sp-4)" }} className="muted">{t("ui.manual.empty")}</div>}
            {images.map((it) => {
              const stale = isStale(it);
              return (
                <div key={it.id} data-id={it.id} className={`browse-item ${cur?.id === it.id ? "active" : ""}`} onClick={() => setSelId(it.id)}>
                  <div className="browse-item-body">
                    <div className="row" style={{ gap: "var(--sp-2)" }}>
                      <span className="mono browse-name" title={it.name}>{it.name}</span>
                      <span className="spacer" />
                      {busy === it.id || batch?.current === it.id ? <span className="tag">{t("ui.manual.analyzing")}</span>
                        : it.result ? <span style={{ opacity: stale ? 0.55 : 1 }}><JudgmentBadge value={it.result.judgment} /></span>
                          : <span className="tag">{t("ui.manual.not_analyzed")}</span>}
                    </div>
                    <div className="browse-meta">
                      <span>{it.source === "run" ? t("ui.manual.from_record") : t("ui.manual.uploaded")}</span>
                      <span>{it.width}×{it.height}</span>
                      {!it.available && <span className="tag">{t("error.image_unavailable")}</span>}
                      {it.result && stale && <span className="tag">{t("ui.manual.stale")}</span>}
                    </div>
                    {it.result && <div className="browse-meta"><span>{keyMeasure(t, it.result.summary.modules)}</span></div>}
                  </div>
                  <button className="btn small ghost" title={t("ui.delete")} onClick={(e) => { e.stopPropagation(); removeItem(it.id); }}>×</button>
                </div>
              );
            })}
          </div>

          {/* 影像檢視與結果 */}
          <div className="manual-center">
            <div className="manual-toolbar">
              <div className="seg">
                <button className={mode === "view" ? "active" : ""} onClick={() => setMode("view")}>{t("ui.manual.mode_view")}</button>
                <button className={mode === "regions" ? "active" : ""} onClick={() => setMode("regions")}>{t("ui.manual.mode_regions")}</button>
              </div>
              {cur && result && (
                <>
                  <JudgmentBadge value={result.judgment} />
                  <QualityBadge value={result.quality.level} />
                  {resultStale && <span className="tag">{t("ui.manual.stale")}</span>}
                  <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>{fmt(result.elapsed_s, 1)} s</span>
                </>
              )}
              <span className="spacer" />
              {ws.waiting > 1 && <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.manual.queue").replace("{n}", String(ws.waiting))}</span>}
            </div>
            <div className="manual-viewer">
              {!cur ? <Empty>{t("ui.manual.empty")}</Empty>
                : mode === "regions" ? (
                  <div className="manual-regions">
                    <RegionCanvas value={body.regions} readOnly={false} arraysSupported={arraysSupported(body, modules)} compact
                      src={imgSrc(cur.id)} width={cur.width} height={cur.height} shapes={shapes} viewerHeight="calc(100vh - 420px)"
                      onChange={(v) => upd({ regions: v })} />
                    <div className="muted" style={{ fontSize: "var(--fs-xs)", marginTop: "var(--sp-2)" }}>{t("ui.manual.regions_hint")}</div>
                  </div>
                ) : (
                  <>
                    <div style={{ position: "absolute", inset: 0, opacity: resultStale && result ? 0.85 : 1 }}>
                      <ImageViewer src={imgSrc(cur.id)} width={cur.width} height={cur.height} shapes={shapes}
                        hiddenLayers={new Set()} opacity={resultStale ? 0.5 : 0.9} brightness={1} contrast={1} preserveView />
                    </div>
                    {busy === cur.id && <div className="manual-busy">{t("ui.manual.analyzing")}</div>}
                  </>
                )}
            </div>
            {mode === "view" && <div className="manual-bottom">
              <div className="tabs">
                {(["table", "reasons", "groups", "quality"] as const).map((k) => (
                  <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{t(`ui.manual.tab_${k}`)}</button>
                ))}
              </div>
              <div className="manual-bottom-body">
                {tab === "table" && <ResultTable images={images} cur={cur?.id ?? null} isStale={isStale} onPick={setSelId} />}
                {tab === "reasons" && (result ? (
                  <div className="stack">
                    {result.modules.map((m) => (
                      <div key={m.module_id} className="row" style={{ alignItems: "flex-start", gap: "var(--sp-4)" }}>
                        <div style={{ minWidth: 200 }}><b>{label(modules[m.module_id]?.names, m.module_id)}</b> <JudgmentBadge value={m.judgment} /></div>
                        <ModuleMeasures m={m} />
                      </div>
                    ))}
                    {result.judgment_reasons.length ? (
                      <ul style={{ margin: 0, paddingLeft: 18 }}>{result.judgment_reasons.map((x) => <li key={x}>{reasonText(t, x)}</li>)}</ul>
                    ) : <div className="muted">{t("ui.manual.no_reasons")}</div>}
                    {result.notes.length > 0 && <div className="muted">{result.notes.map((n) => t(`note.${n}`, n)).join("；")}</div>}
                  </div>
                ) : <div className="muted">{t("ui.manual.not_analyzed")}</div>)}
                {tab === "groups" && (result ? <GroupsTable result={result} /> : <div className="muted">{t("ui.manual.not_analyzed")}</div>)}
                {tab === "quality" && (result ? (
                  <table className="table">
                    <thead><tr><th>{t("ui.metric")}</th><th className="num">{t("ui.value")}</th><th>{t("ui.quality")}</th></tr></thead>
                    <tbody>{result.quality.checks.map((c) => (
                      <tr key={c.metric}><td>{t(`metric.${c.metric}`, c.metric)}</td><td className="num">{fmt(c.value, 3)}</td><td><QualityBadge value={c.level} /></td></tr>
                    ))}</tbody>
                  </table>
                ) : <div className="muted">{t("ui.manual.not_analyzed")}</div>)}
              </div>
            </div>}
          </div>

          {/* 參數 */}
          <aside className="manual-params">
            <div className="manual-params-body">
              <div className="stack">
                <h3>{t("ui.manual.modules")}</h3>
                {Object.values(modules).map((info) => (
                  <label key={info.module_id} className="check">
                    <input type="checkbox" checked={body.modules.some((m) => m.module_id === info.module_id)}
                      disabled={body.modules.length <= 1 && body.modules.some((m) => m.module_id === info.module_id)}
                      onChange={(e) => toggleModule(info.module_id, e.target.checked)} />
                    {label(info.names, info.module_id)}
                  </label>
                ))}
                <label className="check"><input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />{t("ui.recipe.show_advanced")}</label>
              </div>
              {body.modules.map((m, mi) => {
                const info = modules[m.module_id];
                if (!info) return null;
                return (
                  <details key={m.module_id} open className="manual-section">
                    <summary>{label(info.names, m.module_id)}</summary>
                    <ModuleParamsForm m={m} info={info} advanced={advanced} readOnly={false} compact changed={src ? changes.perModule[m.module_id] : undefined}
                      onChange={(nm: RecipeModule) => { const mods = [...body.modules]; mods[mi] = nm; upd({ modules: mods }); }} />
                  </details>
                );
              })}
              <details className="manual-section">
                <summary>{t("ui.recipe.basic")}</summary>
                <div className="form-grid compact">
                  <label className="field">{t("ui.pixel_size")} (µm/px)
                    <input type="number" step="any" value={body.pixel_size_um ?? ""} placeholder={t("ui.recipe.pixel_auto")}
                      onChange={(e) => upd({ pixel_size_um: e.target.value === "" ? null : Number(e.target.value) })} />
                  </label>
                  <label className="field">{t("ui.calibration")}
                    <input type="text" value={body.calibration_profile ?? ""} placeholder={t("ui.not_used")}
                      onChange={(e) => upd({ calibration_profile: e.target.value || null })} />
                  </label>
                </div>
              </details>
              <details className="manual-section">
                <summary>{t("ui.recipe.quality_rules")}</summary>
                <QualityRulesForm body={body} upd={upd} modules={modules} />
              </details>
              <details className="manual-section" open={!!body.regions}>
                <summary>{t("ui.region.title")}（{(body.regions?.include.length || 0) + (body.regions?.exclude.length || 0)}）</summary>
                <div className="stack">
                  <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{body.regions ? t("ui.manual.regions_set") : t("ui.region.none")}</div>
                  <div className="row">
                    <button type="button" className="btn small" onClick={() => setMode("regions")}>{t("ui.manual.edit_regions")}</button>
                    {body.regions && <button type="button" className="btn small" onClick={() => upd({ regions: null })}>{t("ui.region.clear")}</button>}
                  </div>
                </div>
              </details>
            </div>
            <div className="manual-params-foot">
              <label className="check" title={t("ui.manual.auto_hint")}>
                <input type="checkbox" checked={auto} onChange={(e) => { setAuto(e.target.checked); savePref("xrv.manual.auto", e.target.checked ? "1" : "0"); }} />
                {t("ui.manual.auto")}
              </label>
              <span className="spacer" />
              <button className="btn primary" disabled={!cur || busy !== null || !ws.analysis_allowed} onClick={() => analyze(cur)} title="Ctrl+Enter">
                {busy !== null ? t("ui.manual.analyzing") : t("ui.manual.analyze")}
              </button>
            </div>
          </aside>
        </div>
      </div>
      {dialog === "runs" && <FromRunsDialog onClose={() => setDialog(null)} onDone={(ids) => { setDialog(null); reload().then(() => ids[0] && setSelId(ids[0])); }} />}
      {dialog === "recipe" && <FromRecipeDialog onClose={() => setDialog(null)} onDone={(b) => {
        setDialog(null);
        setBody(b);
        setSavedJson(JSON.stringify(b));
        reload().catch(setError);
      }} />}
      {dialog === "save" && <SaveRecipeDialog hasSource={!!src} sourceName={src ? `${src.recipe_id}` : ""} body={body}
        onClose={() => setDialog(null)} />}
    </Layout>
  );
}

// 結果總表：每張影像一列
function ResultTable({ images, cur, isStale, onPick }:
  { images: WorkspaceItem[]; cur: number | null; isStale: (i: WorkspaceItem) => boolean; onPick: (id: number) => void }) {
  const { t } = useApp();
  const [sort, setSort] = useState<"order" | "judgment" | "name">("order");
  const rows = useMemo(() => {
    const r = [...images];
    if (sort === "name") r.sort((a, b) => a.name.localeCompare(b.name));
    if (sort === "judgment") r.sort((a, b) => (a.result?.judgment || "~").localeCompare(b.result?.judgment || "~"));
    return r;
  }, [images, sort]);
  if (!images.length) return <div className="muted">{t("ui.manual.empty")}</div>;
  return (
    <table className="table">
      <thead><tr>
        <th className="clickable" onClick={() => setSort("name")}>{t("ui.file")}</th>
        <th className="clickable" onClick={() => setSort("judgment")}>{t("ui.judgment")}</th>
        <th>{t("ui.quality")}</th><th>{t("ui.manual.key_measure")}</th><th>{t("ui.manual.analyzed_at")}</th><th></th>
      </tr></thead>
      <tbody>
        {rows.map((it) => (
          <tr key={it.id} className={`clickable ${cur === it.id ? "selected" : ""}`} onClick={() => onPick(it.id)}>
            <td className="mono">{it.name}</td>
            <td>{it.result ? <JudgmentBadge value={it.result.judgment} /> : "–"}</td>
            <td>{it.result ? <QualityBadge value={it.result.quality} /> : "–"}</td>
            <td>{it.result ? keyMeasure(t, it.result.summary.modules) : "–"}</td>
            <td>{it.result ? fmtTime(it.result.analyzed_at) : "–"}</td>
            <td>{it.result && isStale(it) && <span className="tag">{t("ui.manual.stale")}</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function GroupsTable({ result }: { result: AnalysisResult }) {
  const { t } = useApp();
  const groups = result.modules.flatMap((m) => m.groups.map((g) => ({ m: m.module_id, g })));
  if (!groups.length) return <div className="muted">{t("ui.manual.no_groups")}</div>;
  return (
    <table className="table">
      <thead><tr><th>{t("ui.group")}</th><th>{t("ui.manual.group_source")}</th><th className="num">n</th>
        <th className="num">dx (px)</th><th className="num">dy (px)</th><th className="num">± se</th><th>{t("ui.manual.grade")}</th></tr></thead>
      <tbody>
        {groups.map(({ m, g }) => (
          <tr key={`${m}${g.id}`}>
            <td>{g.id}{g.label ? `（${g.label}）` : ""}</td>
            <td>{t(g.source === "region" ? "ui.manual.group_region" : "ui.manual.group_auto")}</td>
            <td className="num">{g.size}</td>
            <td className="num">{g.estimate ? fmtSigned(g.estimate.dx, 3) : "–"}</td>
            <td className="num">{g.estimate ? fmtSigned(g.estimate.dy, 3) : "–"}</td>
            <td className="num">{g.estimate ? fmt(g.estimate.se, 3) : "–"}</td>
            <td>{g.grade ? t(`grade.${g.grade}`, g.grade) : t("reason.insufficient_sites")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// 從檢測紀錄加入影像
function FromRunsDialog({ onClose, onDone }: { onClose: () => void; onDone: (ids: number[]) => void }) {
  const { t } = useApp();
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { get<{ items: RunRow[] }>("/api/runs", { limit: 300 }).then((r) => setRuns(r.items)).catch(setError); }, []);
  const s = q.trim().toLowerCase();
  const shown = runs.filter((r) => !s || `${r.file_name} ${r.lot_no || ""} ${r.sample_no} ${r.recipe_id}`.toLowerCase().includes(s));
  const add = async () => {
    try {
      const r = await send<{ added: number[]; skipped: number; errors: { run_id: number; error: string }[] }>(
        "POST", "/api/workspace/images/from-runs", { run_ids: [...sel] });
      if (r.errors.length) setError(new ApiError(400, r.errors[0].error));
      else onDone(r.added);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal title={t("ui.manual.from_runs")} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>{t("ui.cancel")}</button>
        <button className="btn primary" disabled={!sel.size} onClick={add}>{t("ui.manual.add_n").replace("{n}", String(sel.size))}</button></>}>
      <div className="stack">
        <input type="text" placeholder={t("ui.trial.search")} value={q} onChange={(e) => setQ(e.target.value)} />
        <ErrorBox error={error} />
        <div style={{ maxHeight: 380, overflow: "auto" }}>
          <table className="table">
            <thead><tr>
              <th><input type="checkbox" checked={shown.length > 0 && shown.every((r) => sel.has(r.id))}
                onChange={(e) => { const n = new Set(sel); shown.forEach((r) => (e.target.checked ? n.add(r.id) : n.delete(r.id))); setSel(n); }} /></th>
              <th>{t("ui.file")}</th><th>{t("ui.lot")}</th><th>{t("ui.recipe")}</th><th>{t("ui.judgment")}</th><th>{t("ui.time")}</th>
            </tr></thead>
            <tbody>{shown.map((r) => (
              <tr key={r.id} className="clickable" onClick={() => { const n = new Set(sel); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); setSel(n); }}>
                <td><input type="checkbox" readOnly checked={sel.has(r.id)} /></td>
                <td className="mono">{r.file_name}</td><td>{r.lot_no || "–"}</td><td>{r.recipe_id} v{r.recipe_version}</td>
                <td><JudgmentBadge value={r.final_judgment} /></td><td>{fmtTime(r.created_at)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </Modal>
  );
}

// 由配方帶入參數 (任一配方的任一版本)
function FromRecipeDialog({ onClose, onDone }: { onClose: () => void; onDone: (b: RecipeBody) => void }) {
  const { t, label } = useApp();
  const [list, setList] = useState<RecipeSummary[]>([]);
  const [pk, setPk] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { get<RecipeSummary[]>("/api/recipes", { include_retired: "true" }).then(setList).catch(setError); }, []);
  const load = async () => {
    if (!pk) return;
    try {
      const r = await send<{ params: RecipeBody }>("POST", "/api/workspace/params/from-recipe", { recipe_pk: pk });
      onDone(r.params);
    } catch (e) {
      setError(e);
    }
  };
  return (
    <Modal title={t("ui.manual.from_recipe")} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>{t("ui.cancel")}</button>
        <button className="btn primary" disabled={!pk} onClick={load}>{t("ui.manual.load")}</button></>}>
      <div className="stack">
        <div className="muted">{t("ui.manual.from_recipe_hint")}</div>
        <select value={pk ?? ""} onChange={(e) => setPk(Number(e.target.value) || null)} size={10} style={{ width: "100%" }}>
          {list.flatMap((r) => r.versions.map((v) => (
            <option key={v.id} value={v.id}>{r.recipe_id} v{v.version}（{t(`recipe.${v.status}`)}）{label(r.name, "")}</option>
          )))}
        </select>
        <ErrorBox error={error} />
      </div>
    </Modal>
  );
}

// 另存為配方草稿
function SaveRecipeDialog({ hasSource, sourceName, body, onClose }:
  { hasSource: boolean; sourceName: string; body: RecipeBody; onClose: () => void }) {
  const { t } = useApp();
  const [mode, setMode] = useState<"revise" | "new">(hasSource ? "revise" : "new");
  const [rid, setRid] = useState("");
  const [nameZh, setNameZh] = useState("");
  const [nameEn, setNameEn] = useState("");
  const [overwrite, setOverwrite] = useState(false);
  const [needConfirm, setNeedConfirm] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<RecipeRow | null>(null);
  const save = async () => {
    setError(null);
    try {
      await send("PUT", "/api/workspace/params", { body });
      const r = await send<RecipeRow>("POST", "/api/workspace/save-recipe",
        { mode, recipe_id: rid, name: { "zh-TW": nameZh, en: nameEn }, overwrite_draft: overwrite });
      setDone(r);
    } catch (e) {
      if (e instanceof ApiError && e.code === "draft_exists") setNeedConfirm(e.detail);
      else setError(e);
    }
  };
  return (
    <Modal title={t("ui.manual.save_recipe")} onClose={onClose}
      footer={done ? <><button className="btn" onClick={onClose}>{t("ui.close")}</button>
        <Link className="btn primary" to={`/recipes/${done.id}`}>{t("ui.manual.open_recipe")}</Link></>
        : <><button className="btn" onClick={onClose}>{t("ui.cancel")}</button>
          <button className="btn primary" disabled={(mode === "new" && !rid.trim()) || (!!needConfirm && !overwrite)} onClick={save}>{t("ui.save")}</button></>}>
      {done ? (
        <div className="alert info">{t("ui.manual.saved_recipe").replace("{r}", `${done.recipe_id} v${done.version}`)}</div>
      ) : (
        <div className="stack">
          <label className="check"><input type="radio" checked={mode === "revise"} disabled={!hasSource} onChange={() => setMode("revise")} />
            {t("ui.manual.save_revise").replace("{r}", sourceName || "–")}</label>
          <label className="check"><input type="radio" checked={mode === "new"} onChange={() => setMode("new")} />{t("ui.manual.save_new")}</label>
          {mode === "new" && (
            <div className="form-grid">
              <label className="field">{t("ui.recipe.id")}<input type="text" value={rid} onChange={(e) => setRid(e.target.value)} /></label>
              <label className="field">{t("ui.recipe.name_zh")}<input type="text" value={nameZh} onChange={(e) => setNameZh(e.target.value)} /></label>
              <label className="field">{t("ui.recipe.name_en")}<input type="text" value={nameEn} onChange={(e) => setNameEn(e.target.value)} /></label>
            </div>
          )}
          {mode === "revise" && needConfirm && (
            <label className="check"><input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} />
              {t("ui.manual.overwrite_draft").replace("{r}", needConfirm)}</label>
          )}
          <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.manual.save_hint")}</div>
          <ErrorBox error={error} />
        </div>
      )}
    </Modal>
  );
}
