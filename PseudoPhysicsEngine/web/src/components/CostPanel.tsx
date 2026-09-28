import { useEffect, useState } from "react";
import { api } from "../api";

type Total = { value: string | null; low?: string | null; high?: string | null };
type Line = {
  item: string;
  name: string;
  kind_label: string;
  subsystem: string;
  unit: string;
  quantity: string;
  unit_price: string | null;
  amount: string | null;
  missing: string | null;
  trust: string;
};
type Costing = {
  version: number;
  currency: string;
  as_of: string;
  complete: boolean;
  totals: Record<string, Total>;
  formulas: Record<string, string>;
  coverage: { priced_lines: number; total_lines: number; ratio: string };
  by_subsystem: { subsystem: string; known: string; low: string; high: string; missing: number }[];
  purchase_lines: Line[];
  missing: { type: string; id: string; name: string; quantity: string; unit: string; reason: string }[];
  issues: { severity: string; code: string; message: string }[];
  policy: { pricing: { method: string; rate: string } | null; contingency_rate: string; tax_rate: string };
};

const TOTAL_ROWS: [string, string][] = [
  ["equipment", "設備成本"],
  ["development", "專案開發成本"],
  ["overhead", "管理費"],
  ["contingency", "預備費"],
  ["cost", "成本合計（未稅）"],
  ["budget_tax", "預算稅額"],
  ["budget_with_tax", "含稅預算"],
  ["price", "售價（未稅）"],
  ["quote_tax", "報價稅額"],
  ["quote_with_tax", "含稅報價"],
];

function money(value: string | null | undefined): string {
  if (value === null || value === undefined) return "待報價";
  const [whole, fraction] = value.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction && Number(fraction) !== 0 ? `${grouped}.${fraction}` : grouped;
}

export function CostPanel({ projectId, version }: { projectId: string; version?: string }) {
  const [costing, setCosting] = useState<Costing>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    setCosting(undefined);
    setError(undefined);
    if (!version) return;
    api<Costing>(`/projects/${encodeURIComponent(projectId)}/versions/${version}/costing`)
      .then(setCosting)
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [projectId, version]);
  if (!version) return <p className="lead">尚未建置版本。</p>;
  if (error) return <p className="lead">{error}</p>;
  if (!costing) return <p className="lead">正在載入成本資料…</p>;
  const pricing = costing.policy.pricing;
  return (
    <div className="cost-panel">
      <div className={`check-row ${costing.complete ? "check-green" : "check-yellow"}`}>
        <b>
          {costing.complete ? "成本已涵蓋全部項目" : `含 ${costing.missing.length} 項缺價：以下為已知成本小計`}
        </b>
        <p>
          {costing.currency}・估算基準日 {costing.as_of}・覆蓋率 {costing.coverage.priced_lines}/
          {costing.coverage.total_lines}（{(Number(costing.coverage.ratio) * 100).toFixed(1)}%）
          {pricing
            ? `・${pricing.method === "margin" ? "毛利率" : "加價率"} ${(Number(pricing.rate) * 100).toFixed(1)}%`
            : "・未設定計價政策，只輸出預算"}
        </p>
      </div>
      <table className="cost-table">
        <thead>
          <tr>
            <th>項目</th>
            <th>金額</th>
            <th>下限</th>
            <th>上限</th>
          </tr>
        </thead>
        <tbody>
          {TOTAL_ROWS.filter(([key]) => costing.totals[key]).map(([key, label]) => (
            <tr key={key} title={costing.formulas[key] ?? ""}>
              <td>{label}</td>
              <td>{money(costing.totals[key].value)}</td>
              <td>{money(costing.totals[key].low)}</td>
              <td>{money(costing.totals[key].high)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>子系統</h3>
      <table className="cost-table">
        <tbody>
          {costing.by_subsystem.map((entry) => (
            <tr key={entry.subsystem}>
              <td>{entry.subsystem}</td>
              <td>{money(entry.known)}</td>
              <td>{entry.missing ? `缺價 ${entry.missing}` : ""}</td>
            </tr>
          ))}
          {costing.totals.labor && (
            <tr title={costing.formulas.labor ?? ""}>
              <td>人工（工時）</td>
              <td>{money(costing.totals.labor.value)}</td>
              <td />
            </tr>
          )}
        </tbody>
      </table>
      {costing.missing.length > 0 && (
        <>
          <h3>缺價清單</h3>
          <div className="compact-list">
            {costing.missing.map((entry) => (
              <article key={`${entry.type}-${entry.id}`}>
                <b>
                  {entry.id} {entry.name}
                </b>
                <p>
                  {entry.quantity} {entry.unit}・{entry.reason}
                </p>
              </article>
            ))}
          </div>
        </>
      )}
      {costing.issues.length > 0 && (
        <>
          <h3>資料問題</h3>
          <div className="compact-list">
            {costing.issues.map((issue, index) => (
              <article key={index} className={issue.severity === "error" ? "cost-error" : ""}>
                <b>{issue.code}</b>
                <p>{issue.message}</p>
              </article>
            ))}
          </div>
        </>
      )}
      <h3>採購明細（{costing.purchase_lines.length} 項）</h3>
      <table className="cost-table cost-lines">
        <thead>
          <tr>
            <th>項目</th>
            <th>數量</th>
            <th>單價</th>
            <th>小計</th>
          </tr>
        </thead>
        <tbody>
          {costing.purchase_lines.map((line) => (
            <tr key={line.item} className={line.missing ? "cost-missing" : ""}>
              <td title={`${line.subsystem}・${line.kind_label}・${line.trust}`}>{line.name}</td>
              <td>
                {line.quantity} {line.unit}
              </td>
              <td>{money(line.unit_price)}</td>
              <td>{line.missing ? line.missing : money(line.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="lead">匯出交付包時會同時產生成本 XLSX（保留公式）與採購 BOM CSV。</p>
    </div>
  );
}
