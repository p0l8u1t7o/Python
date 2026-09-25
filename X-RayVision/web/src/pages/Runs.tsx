import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { get, query } from "../api/client";
import type { RecipeSummary, RunRow } from "../api/types";
import { useApp } from "../app/context";
import { DatasetDialog } from "../components/DatasetDialog";
import { DiagnosticsDialog } from "../components/DiagnosticsDialog";
import { Layout } from "../components/Layout";
import { ReanalyzeDialog } from "../components/ReanalyzeDialog";
import { RunPreview, clearRunCache, keyMeasure, prefetchRun } from "../components/RunPreview";
import { Empty, ErrorBox, JudgmentBadge, QualityBadge, fmt, fmtSigned, fmtTime, useLoad } from "../components/ui";

const PAGE = 50;
export const RUNS_NAV_KEY = "xrv.runs.nav";     // 檢閱頁的上一張／下一張依紀錄頁當時的清單順序

export function Runs() {
  const { t, locale, can } = useApp();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const filters = {
    judgment: sp.get("judgment") || "",
    lot_no: sp.get("lot_no") || "",
    recipe_id: sp.get("recipe_id") || "",
    date_from: sp.get("date_from") || "",
    date_to: sp.get("date_to") || "",
  };
  const currentOnly = sp.get("all") !== "1";
  const view = sp.get("view") === "table" ? "table" : "list";
  const page = Number(sp.get("page") || 0);
  const selParam = sp.get("sel") || "";
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [dialog, setDialog] = useState<"diag" | "dataset" | "reanalyze" | "reanalyze_one" | null>(null);
  const [recipes] = useLoad(() => get<RecipeSummary[]>("/api/recipes", { include_retired: "true" }), []);
  const apiFilters = { ...filters, date_to: filters.date_to ? filters.date_to + "T23:59:59" : "", current_only: String(currentOnly) };
  const [data, error, reload] = useLoad(
    () => get<{ total: number; items: RunRow[] }>("/api/runs", { ...apiFilters, limit: PAGE, offset: page * PAGE }),
    [sp.get("judgment"), sp.get("lot_no"), sp.get("recipe_id"), sp.get("date_from"), sp.get("date_to"), sp.get("all"), page],
  );
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => { clearRunCache(); }, []);

  const items = data?.items || [];
  const total = data?.total || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const selIndex = selParam === "last" ? items.length - 1 : items.findIndex((r) => String(r.id) === selParam);
  const cur = selIndex >= 0 ? items[selIndex] : null;

  const patch = (changes: Record<string, string | null>, replace = false) => {
    const n = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(changes)) {
      if (v) n.set(k, v);
      else n.delete(k);
    }
    setSp(n, { replace });
  };
  const setFilter = (k: string, v: string) => patch({ [k]: v, page: null, sel: null });

  // 沒有選取 (或選取不在本頁) 時選第一筆；"last" 換成實際編號
  useEffect(() => {
    if (!data || view !== "list" || !items.length) return;
    if (selIndex < 0) patch({ sel: String(items[0].id) }, true);
    else if (selParam === "last") patch({ sel: String(items[selIndex].id) }, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, selIndex, selParam, view]);

  // 記錄清單順序給檢閱頁；預先載入前後一筆
  useEffect(() => {
    if (!data) return;
    const q = new URLSearchParams(sp);
    q.delete("sel");
    try {
      sessionStorage.setItem(RUNS_NAV_KEY, JSON.stringify({ ids: items.map((r) => r.id), query: q.toString() }));
    } catch { /* 無法使用 sessionStorage 時只是沒有上一張／下一張 */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);
  useEffect(() => {
    if (selIndex < 0) return;
    if (items[selIndex + 1]) prefetchRun(items[selIndex + 1].id);
    if (items[selIndex - 1]) prefetchRun(items[selIndex - 1].id);
    listRef.current?.querySelector(".browse-item.active")?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selIndex, data]);

  const toggle = (id: number) => {
    const n = new Set(selected);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    setSelected(n);
  };

  const move = (d: number) => {
    const i = selIndex + d;
    if (i >= 0 && i < items.length) patch({ sel: String(items[i].id) }, true);
    else if (i >= items.length && page + 1 < pages) patch({ page: String(page + 1), sel: null });
    else if (i < 0 && page > 0) patch({ page: String(page - 1), sel: "last" });
  };

  // 鍵盤：↑↓ 切換、Enter 進入檢閱、空白鍵勾選 (輸入框內不處理)
  useEffect(() => {
    if (view !== "list") return;
    const h = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName) || document.querySelector(".modal-back")) return;
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter" && cur) { e.preventDefault(); nav(`/runs/${cur.id}`); }
      else if (e.key === " " && cur) { e.preventDefault(); toggle(cur.id); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  const csvUrl = `/api/runs/export.csv?${query({ ...apiFilters, locale })}`;

  return (
    <Layout full title={t("ui.nav.runs")}
      actions={<>
        <div className="seg">
          <button className={view === "list" ? "active" : ""} onClick={() => patch({ view: null })}>{t("ui.runs.view_list")}</button>
          <button className={view === "table" ? "active" : ""} onClick={() => patch({ view: "table" })}>{t("ui.runs.view_table")}</button>
        </div>
        {can("import") && (
          <button className="btn" disabled={!selected.size} onClick={() => setDialog("reanalyze")}>
            {t("ui.reanalyze")}{selected.size ? ` (${selected.size})` : ""}
          </button>
        )}
        {can("diagnostics") && (
          <button className="btn" disabled={!selected.size} onClick={() => setDialog("diag")}>
            {t("ui.diag.export")}{selected.size ? ` (${selected.size})` : ""}
          </button>
        )}
        {can("annotate") && (
          <button className="btn" disabled={!selected.size} onClick={() => setDialog("dataset")}>
            {t("ui.annot.export")}{selected.size ? ` (${selected.size})` : ""}
          </button>
        )}
        <a className="btn" href={csvUrl}>{t("ui.export_csv")}</a>
      </>}>
      <div className="runs-page">
        <div className="runs-filters row">
          <label className="field">{t("ui.judgment")}
            <select value={filters.judgment} onChange={(e) => setFilter("judgment", e.target.value)}>
              <option value="">{t("ui.all")}</option>
              {["pass", "fail", "review", "quality_insufficient", "not_judged"].map((j) =>
                <option key={j} value={j}>{t(`judgment.${j}`)}</option>)}
            </select>
          </label>
          <label className="field">{t("ui.recipe")}
            <select value={filters.recipe_id} onChange={(e) => setFilter("recipe_id", e.target.value)}>
              <option value="">{t("ui.all")}</option>
              {recipes?.map((r) => <option key={r.recipe_id} value={r.recipe_id}>{r.recipe_id}</option>)}
            </select>
          </label>
          <label className="field">{t("ui.lot")}
            <input type="text" defaultValue={filters.lot_no} onKeyDown={(e) => e.key === "Enter" && setFilter("lot_no", e.currentTarget.value.trim())}
              onBlur={(e) => e.currentTarget.value.trim() !== filters.lot_no && setFilter("lot_no", e.currentTarget.value.trim())} />
          </label>
          <label className="field">{t("ui.date_from")}
            <input type="date" value={filters.date_from} onChange={(e) => setFilter("date_from", e.target.value)} />
          </label>
          <label className="field">{t("ui.date_to")}
            <input type="date" value={filters.date_to} onChange={(e) => setFilter("date_to", e.target.value)} />
          </label>
          <label className="check" title={t("ui.runs.current_only_hint")}>
            <input type="checkbox" checked={currentOnly} onChange={(e) => patch({ all: e.target.checked ? null : "1", page: null, sel: null })} />
            {t("ui.runs.current_only")}
          </label>
          <span className="spacer" />
          <span className="muted" style={{ fontSize: "var(--fs-sm)" }}>{t("ui.runs.count").replace("{n}", String(total))}</span>
          <Pager page={page} pages={pages} onPage={(p) => patch({ page: String(p), sel: null })} />
        </div>
        <ErrorBox error={error} />
        {view === "table" ? (
          <div className="runs-table-scroll">
            {!items.length ? <Empty /> : <RunsTable items={items} selected={selected} setSelected={setSelected} toggle={toggle} />}
          </div>
        ) : !items.length ? (
          <div className="runs-table-scroll"><Empty /></div>
        ) : (
          <div className="browse-layout">
            <div className="browse-list" ref={listRef}>
              <div className="browse-list-h">
                <input type="checkbox" aria-label={t("ui.select_all")} checked={items.every((r) => selected.has(r.id))}
                  onChange={(e) => {
                    const n = new Set(selected);
                    items.forEach((r) => (e.target.checked ? n.add(r.id) : n.delete(r.id)));
                    setSelected(n);
                  }} />
                <span className="muted">{t("ui.select_all")}</span>
              </div>
              {items.map((r) => (
                <div key={r.id} className={`browse-item ${cur?.id === r.id ? "active" : ""} ${r.superseded_by ? "superseded" : ""}`}
                  onClick={() => patch({ sel: String(r.id) }, true)} onDoubleClick={() => nav(`/runs/${r.id}`)}>
                  <input type="checkbox" checked={selected.has(r.id)} onClick={(e) => e.stopPropagation()} onChange={() => toggle(r.id)} aria-label={String(r.id)} />
                  <div className="browse-item-body">
                    <div className="row" style={{ gap: "var(--sp-2)" }}>
                      <span className="mono browse-name">{r.file_name}</span>
                      <span className="spacer" />
                      <JudgmentBadge value={r.final_judgment} />
                    </div>
                    <div className="browse-meta">
                      <span>{fmtTime(r.created_at)}</span>
                      <span>{r.lot_no || "–"} / {r.sample_no}</span>
                      <span>v{r.recipe_version}</span>
                      <span>{t("ui.quality")}</span><QualityBadge value={r.quality_level} />
                    </div>
                    <div className="browse-meta">
                      <span>{keyMeasure(t, r.summary.modules)}</span>
                      {r.superseded_by && <span className="tag">{t("ui.run.superseded_tag")}</span>}
                      {r.final_judgment !== r.auto_judgment && <span className="tag">{t("ui.reviewed")}</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            {cur && <RunPreview runId={cur.id} onReanalyze={() => setDialog("reanalyze_one")} />}
          </div>
        )}
      </div>
      {dialog === "diag" && <DiagnosticsDialog runIds={[...selected]} onClose={() => setDialog(null)} />}
      {dialog === "dataset" && <DatasetDialog runIds={[...selected]} onClose={() => setDialog(null)} />}
      {dialog === "reanalyze" && <ReanalyzeDialog runIds={[...selected]} onClose={() => setDialog(null)} onDone={() => setSelected(new Set())} />}
      {dialog === "reanalyze_one" && cur && <ReanalyzeDialog runIds={[cur.id]} onClose={() => { setDialog(null); reload(); }} />}
    </Layout>
  );
}

function RunsTable({ items, selected, setSelected, toggle }:
  { items: RunRow[]; selected: Set<number>; setSelected: (s: Set<number>) => void; toggle: (id: number) => void }) {
  const { t } = useApp();
  const nav = useNavigate();
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th style={{ width: 32 }}>
              <input type="checkbox" aria-label={t("ui.select_all")}
                checked={items.every((r) => selected.has(r.id))}
                onChange={(e) => {
                  const n = new Set(selected);
                  items.forEach((r) => (e.target.checked ? n.add(r.id) : n.delete(r.id)));
                  setSelected(n);
                }} />
            </th>
            <th>{t("ui.time")}</th><th>{t("ui.lot")}</th><th>{t("ui.sample")}</th><th>{t("ui.file")}</th>
            <th>{t("ui.recipe")}</th><th>{t("ui.quality")}</th><th>{t("ui.judgment")}</th>
            <th className="num">{t("ui.die_shift")} X</th><th className="num">{t("ui.die_shift")} Y</th>
            <th className="num">{t("ui.sites_used")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => {
            const m = Object.values(r.summary.modules)[0];
            const d = m?.summary?.die_shift;
            const um = d?.dx_um !== undefined;
            return (
              <tr key={r.id} className={`clickable ${selected.has(r.id) ? "selected" : ""} ${r.superseded_by ? "superseded" : ""}`} onClick={() => nav(`/runs/${r.id}`)}>
                <td onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r.id)} aria-label={String(r.id)} />
                </td>
                <td>{fmtTime(r.created_at)}</td>
                <td>{r.lot_no || "–"}</td>
                <td>{r.sample_no}</td>
                <td className="mono">{r.file_name}</td>
                <td>{r.recipe_id} v{r.recipe_version}</td>
                <td><QualityBadge value={r.quality_level} /></td>
                <td>
                  <JudgmentBadge value={r.final_judgment} />
                  {r.final_judgment !== r.auto_judgment && <span className="muted" style={{ fontSize: "var(--fs-xs)" }}> {t("ui.reviewed")}</span>}
                  {r.reference_only && <span className="muted" style={{ fontSize: "var(--fs-xs)" }}> {t("ui.reference_only")}</span>}
                  {r.superseded_by && <span className="tag" style={{ marginLeft: 6 }}>{t("ui.run.superseded_tag")}</span>}
                </td>
                <td className="num">{d ? (um ? `${fmtSigned(d.dx_um)} µm` : `${fmtSigned(d.dx)} px`) : "–"}</td>
                <td className="num">{d ? (um ? `${fmtSigned(d.dy_um)} µm` : `${fmtSigned(d.dy)} px`) : "–"}</td>
                <td className="num">{fmt(m?.summary?.sites_used as number, 0)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  const { t } = useApp();
  return (
    <div className="row">
      <button className="btn small" disabled={page <= 0} onClick={() => onPage(page - 1)}>{t("ui.prev")}</button>
      <span className="muted" style={{ fontSize: "var(--fs-sm)" }}>{page + 1} / {pages}</span>
      <button className="btn small" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)}>{t("ui.next")}</button>
    </div>
  );
}
