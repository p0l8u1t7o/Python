import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { get, query } from "../api/client";
import type { RecipeSummary, RunRow } from "../api/types";
import { useApp } from "../app/context";
import { DatasetDialog } from "../components/DatasetDialog";
import { DiagnosticsDialog } from "../components/DiagnosticsDialog";
import { Layout } from "../components/Layout";
import { Card, Empty, ErrorBox, JudgmentBadge, QualityBadge, fmt, fmtSigned, fmtTime, useLoad } from "../components/ui";

const PAGE = 50;

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
  const page = Number(sp.get("page") || 0);
  const [showDataset, setShowDataset] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [showDiag, setShowDiag] = useState(false);
  const [recipes] = useLoad(() => get<RecipeSummary[]>("/api/recipes", { include_retired: "true" }), []);
  const apiFilters = { ...filters, date_to: filters.date_to ? filters.date_to + "T23:59:59" : "" };
  const [data, error] = useLoad(
    () => get<{ total: number; items: RunRow[] }>("/api/runs", { ...apiFilters, limit: PAGE, offset: page * PAGE }),
    [sp.toString()],
  );

  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v);
    else n.delete(k);
    n.delete("page");
    setSp(n);
  };
  const toggle = (id: number) => {
    const n = new Set(selected);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    setSelected(n);
  };
  const csvUrl = `/api/runs/export.csv?${query({ ...apiFilters, locale })}`;
  const total = data?.total || 0;

  return (
    <Layout title={t("ui.nav.runs")}
      actions={<>
        {can("diagnostics") && (
          <button className="btn" disabled={!selected.size} onClick={() => setShowDiag(true)}>
            {t("ui.diag.export")}{selected.size ? ` (${selected.size})` : ""}
          </button>
        )}
        {can("annotate") && (
          <button className="btn" disabled={!selected.size} onClick={() => setShowDataset(true)}>
            {t("ui.annot.export")}{selected.size ? ` (${selected.size})` : ""}
          </button>
        )}
        <a className="btn" href={csvUrl}>{t("ui.export_csv")}</a>
      </>}>
      <div className="stack">
        <Card>
          <div className="row">
            <label className="field">{t("ui.judgment")}
              <select value={filters.judgment} onChange={(e) => set("judgment", e.target.value)}>
                <option value="">{t("ui.all")}</option>
                {["pass", "fail", "review", "quality_insufficient", "not_judged"].map((j) =>
                  <option key={j} value={j}>{t(`judgment.${j}`)}</option>)}
              </select>
            </label>
            <label className="field">{t("ui.recipe")}
              <select value={filters.recipe_id} onChange={(e) => set("recipe_id", e.target.value)}>
                <option value="">{t("ui.all")}</option>
                {recipes?.map((r) => <option key={r.recipe_id} value={r.recipe_id}>{r.recipe_id}</option>)}
              </select>
            </label>
            <label className="field">{t("ui.lot")}
              <input type="text" defaultValue={filters.lot_no} onKeyDown={(e) => e.key === "Enter" && set("lot_no", e.currentTarget.value.trim())}
                onBlur={(e) => e.currentTarget.value.trim() !== filters.lot_no && set("lot_no", e.currentTarget.value.trim())} />
            </label>
            <label className="field">{t("ui.date_from")}
              <input type="date" value={filters.date_from} onChange={(e) => set("date_from", e.target.value)} />
            </label>
            <label className="field">{t("ui.date_to")}
              <input type="date" value={filters.date_to} onChange={(e) => set("date_to", e.target.value)} />
            </label>
          </div>
        </Card>
        <ErrorBox error={error} />
        <Card bodyClass="" title={<h2>{t("ui.runs.count").replace("{n}", String(total))}</h2>}
          actions={<Pager page={page} total={total} onPage={(p) => { const n = new URLSearchParams(sp); n.set("page", String(p)); setSp(n); }} />}>
          {!data?.items.length ? <Empty /> : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 32 }}>
                      <input type="checkbox" aria-label={t("ui.select_all")}
                        checked={data.items.every((r) => selected.has(r.id))}
                        onChange={(e) => {
                          const n = new Set(selected);
                          data.items.forEach((r) => (e.target.checked ? n.add(r.id) : n.delete(r.id)));
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
                  {data.items.map((r) => {
                    const m = Object.values(r.summary.modules)[0];
                    const d = m?.summary?.die_shift;
                    const um = d?.dx_um !== undefined;
                    return (
                      <tr key={r.id} className={`clickable ${selected.has(r.id) ? "selected" : ""}`} onClick={() => nav(`/runs/${r.id}`)}>
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
          )}
        </Card>
      </div>
      {showDiag && <DiagnosticsDialog runIds={[...selected]} onClose={() => setShowDiag(false)} />}
      {showDataset && <DatasetDialog runIds={[...selected]} onClose={() => setShowDataset(false)} />}
    </Layout>
  );
}

function Pager({ page, total, onPage }: { page: number; total: number; onPage: (p: number) => void }) {
  const { t } = useApp();
  const pages = Math.max(1, Math.ceil(total / PAGE));
  return (
    <div className="row">
      <button className="btn small" disabled={page <= 0} onClick={() => onPage(page - 1)}>{t("ui.prev")}</button>
      <span className="muted" style={{ fontSize: "var(--fs-sm)" }}>{page + 1} / {pages}</span>
      <button className="btn small" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)}>{t("ui.next")}</button>
    </div>
  );
}
