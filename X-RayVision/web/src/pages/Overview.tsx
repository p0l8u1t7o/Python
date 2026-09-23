import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { get } from "../api/client";
import type { Judgment, RunRow, Stats, SystemInfo, WatchFolder } from "../api/types";
import { useApp, usePolling } from "../app/context";
import { Layout } from "../components/Layout";
import { Card, Empty, ErrorBox, JudgmentBadge, fmtSigned, fmtTime, localDay } from "../components/ui";

const ORDER: Judgment[] = ["pass", "fail", "review", "quality_insufficient", "not_judged"];
const COLOR: Record<Judgment, string> = {
  pass: "var(--j-pass)", fail: "var(--j-fail)", review: "var(--j-review)",
  quality_insufficient: "var(--j-quality)", not_judged: "var(--j-none)",
};

export function Overview() {
  const { t } = useApp();
  const nav = useNavigate();
  const [stats, setStats] = useState<Stats | null>(null);
  const [sys, setSys] = useState<SystemInfo | null>(null);
  const [pending, setPending] = useState<RunRow[]>([]);
  const [recent, setRecent] = useState<RunRow[]>([]);
  const [watch, setWatch] = useState<WatchFolder[]>([]);
  const [error, setError] = useState<unknown>(null);

  usePolling(() => {
    Promise.all([
      get<Stats>("/api/stats", { days: 14 }),
      get<SystemInfo>("/api/system"),
      get<{ items: RunRow[] }>("/api/runs", { judgment: "review", limit: 10 }),
      get<{ items: RunRow[] }>("/api/runs", { limit: 10 }),
      get<WatchFolder[]>("/api/watch-folders"),
    ])
      .then(([s, y, p, r, w]) => {
        setStats(s);
        setSys(y);
        setPending(p.items);
        setRecent(r.items);
        setWatch(w);
        setError(null);
      })
      .catch(setError);
  }, 10000);

  const today = localDay(new Date());
  const todayCounts: Partial<Record<Judgment, number>> = {};
  stats?.by_day.filter((d) => d.day === today).forEach((d) => (todayCounts[d.judgment] = d.n));
  const todayTotal = Object.values(todayCounts).reduce((a, b) => a + (b || 0), 0);

  return (
    <Layout title={t("ui.nav.overview")}>
      <div className="stack">
        <ErrorBox error={error} />
        <div className="grid cols-4">
          <Stat label={t("ui.overview.today_total")} value={todayTotal} />
          {(["pass", "fail", "review", "quality_insufficient"] as Judgment[]).map((j) => (
            <Stat key={j} label={<><span className={`badge plain j-${j}`} style={{ border: 0, padding: 0 }}>●</span>{t(`judgment.${j}`)}</>}
              value={todayCounts[j] || 0} />
          ))}
          <Stat label={t("ui.overview.review_pending")} value={stats?.review_pending ?? 0}
            onClick={() => nav("/runs?judgment=review")} />
          <Stat label={t("ui.overview.queue")} value={(sys?.queue.queued || 0) + (sys?.queue.running || 0)}
            sub={`${t("job.failed")} ${sys?.queue.failed || 0}`} onClick={() => nav("/imports")} />
        </div>

        <Card title={t("ui.overview.trend")}>
          {stats ? <DayChart stats={stats} /> : <Empty />}
        </Card>

        <div className="grid cols-2">
          <Card title={t("ui.overview.pending_list")} bodyClass="">
            <RunTable rows={pending} onOpen={(id) => nav(`/runs/${id}`)} />
          </Card>
          <Card title={t("ui.overview.recent")} bodyClass="">
            <RunTable rows={recent} onOpen={(id) => nav(`/runs/${id}`)} />
          </Card>
        </div>

        <Card title={t("ui.nav.watch")} bodyClass="">
          {watch.length === 0 ? <Empty>{t("ui.watch.none")}</Empty> : (
            <table className="table">
              <thead><tr><th>{t("ui.watch.path")}</th><th>{t("ui.recipe")}</th><th>{t("ui.status")}</th>
                <th className="num">{t("ui.watch.imported")}</th><th>{t("ui.watch.last_scan")}</th></tr></thead>
              <tbody>
                {watch.map((w) => (
                  <tr key={w.id}>
                    <td className="mono">{w.path}</td><td>{w.recipe_id}</td>
                    <td>{w.enabled ? t("ui.enabled") : t("ui.disabled")}</td>
                    <td className="num">{w.counts.imported || 0}</td><td>{fmtTime(w.last_scan_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </Layout>
  );
}

function Stat({ label, value, sub, onClick }: { label: React.ReactNode; value: number; sub?: string; onClick?: () => void }) {
  return (
    <div className="card stat" style={{ cursor: onClick ? "pointer" : undefined }} onClick={onClick}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{sub}</div>}
    </div>
  );
}

export function RunTable({ rows, onOpen }: { rows: RunRow[]; onOpen: (id: number) => void }) {
  const { t } = useApp();
  if (!rows.length) return <Empty />;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr><th>{t("ui.time")}</th><th>{t("ui.lot")}</th><th>{t("ui.sample")}</th><th>{t("ui.judgment")}</th>
            <th className="num">{t("ui.die_shift")} (px)</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const d = Object.values(r.summary.modules)[0]?.summary?.die_shift;
            return (
              <tr key={r.id} className="clickable" onClick={() => onOpen(r.id)}>
                <td>{fmtTime(r.created_at)}</td><td>{r.lot_no || "–"}</td><td>{r.sample_no}</td>
                <td><JudgmentBadge value={r.final_judgment} /></td>
                <td className="num">{d ? `${fmtSigned(d.dx)}, ${fmtSigned(d.dy)}` : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// 每日判定堆疊長條圖 (SVG)
function DayChart({ stats }: { stats: Stats }) {
  const { t } = useApp();
  const days: string[] = [];
  const start = new Date(stats.since.slice(0, 10) + "T00:00:00");
  for (let d = new Date(start); localDay(d) <= localDay(new Date()); d.setDate(d.getDate() + 1)) days.push(localDay(d));
  const by: Record<string, Partial<Record<Judgment, number>>> = {};
  for (const r of stats.by_day) (by[r.day] ||= {})[r.judgment] = r.n;
  const max = Math.max(1, ...days.map((d) => ORDER.reduce((a, j) => a + (by[d]?.[j] || 0), 0)));
  const W = 1600, H = 170, pad = 28, bw = (W - pad * 2) / days.length;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H + 24}`} width="100%" role="img" aria-label={t("ui.overview.trend")}>
        <line x1={pad} y1={H} x2={W - pad} y2={H} stroke="var(--border)" />
        <text x={4} y={14} fontSize="11" fill="var(--text-2)">{max}</text>
        {days.map((d, i) => {
          let y = H;
          return (
            <g key={d}>
              {ORDER.map((j) => {
                const n = by[d]?.[j] || 0;
                if (!n) return null;
                const h = (n / max) * (H - 20);
                y -= h;
                return <rect key={j} x={pad + i * bw + bw * 0.15} y={y} width={bw * 0.7} height={h} fill={COLOR[j]}>
                  <title>{`${d} ${t(`judgment.${j}`)}: ${n}`}</title></rect>;
              })}
              {(i % Math.ceil(days.length / 14) === 0) && (
                <text x={pad + i * bw + bw / 2} y={H + 16} fontSize="11" textAnchor="middle" fill="var(--text-2)">{d.slice(5)}</text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="chart-legend">
        {ORDER.map((j) => <span key={j}><i style={{ background: COLOR[j] }} />{t(`judgment.${j}`)}</span>)}
      </div>
    </div>
  );
}
