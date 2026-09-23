import { Fragment } from "react";
import type { ModuleInfo, ModuleResult } from "../api/types";
import { useApp } from "../app/context";
import { fmt } from "./ui";

// 通用模組摘要：summary 中的純數值欄位 (標籤取 summary.<鍵>)；個別模組不需另寫畫面
const SKIP = new Set(["pixel_size_um", "candidates"]);

export function summaryEntries(m: ModuleResult): [string, number][] {
  return Object.entries(m.summary || {}).filter(([k, v]) => typeof v === "number" && !SKIP.has(k)) as [string, number][];
}

export function SummaryKV({ m }: { m: ModuleResult }) {
  const { t } = useApp();
  const items = summaryEntries(m);
  if (!items.length) return null;
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <Fragment key={k}><dt>{t(`summary.${k}`, k)}</dt><dd>{fmt(v, Number.isInteger(v) ? 0 : 2)}</dd></Fragment>
      ))}
    </dl>
  );
}

// 物件排行表 (模組以 finding_table 宣告)，並附量測值分布
export function FindingTable({ m, info, compact }: { m: ModuleResult; info?: ModuleInfo; compact?: boolean }) {
  const { t } = useApp();
  const spec = info?.finding_table;
  if (!spec) return null;
  const rows = m.findings.filter((f) => f.category === spec.category && f.used);
  if (!rows.length) return null;
  const top = [...rows].sort((a, b) => (b.measurements[spec.sort] ?? 0) - (a.measurements[spec.sort] ?? 0)).slice(0, spec.limit);
  const cols = compact ? spec.columns.slice(0, 3) : spec.columns;       // 側欄空間有限，只列前 3 欄
  const vals = rows.map((f) => f.measurements[spec.sort] ?? 0);
  const max = Math.max(10, Math.ceil(Math.max(...vals) / 10) * 10);
  const bins = Array.from({ length: 10 }, () => 0);
  vals.forEach((v) => { bins[Math.min(9, Math.floor((v / max) * 10))] += 1; });
  const peak = Math.max(...bins, 1);
  return (
    <div className="stack">
      <table className="table">
        <thead><tr><th>#</th>{cols.map((c) => <th key={c} className="num">{t(`measure.${c}`, c)}</th>)}</tr></thead>
        <tbody>
          {top.map((f) => (
            <tr key={f.id}><td>{String(f.flags.label ?? f.id).replace(/^ball/, "")}</td>
              {cols.map((c) => <td key={c} className="num">{fmt(f.measurements[c], Number.isInteger(f.measurements[c]) ? 0 : 2)}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {!compact && (
        <div>
          <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.distribution")}：{t(`measure.${spec.sort}`, spec.sort)}（{t("ui.count")} {rows.length}）</div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 48 }}>
            {bins.map((n, i) => (
              <div key={i} title={`${(i * max) / 10}–${((i + 1) * max) / 10}: ${n}`}
                style={{ flex: 1, height: `${(n / peak) * 100}%`, minHeight: n ? 2 : 0, background: "var(--accent)" }} />
            ))}
          </div>
          <div className="row muted" style={{ fontSize: "var(--fs-xs)" }}><span>0</span><span className="spacer" /><span>{max}</span></div>
        </div>
      )}
    </div>
  );
}
