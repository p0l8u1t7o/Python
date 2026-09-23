import { useEffect, useRef, useState } from "react";
import { get } from "../api/client";
import type { RegionShape, Regions, RunRow } from "../api/types";
import { useApp } from "../app/context";
import { fmtTime } from "./ui";

type Kind = "include" | "exclude";
type Tool = "rect" | "polygon";

export const REGION_COLORS: Record<Kind, string> = { include: "#16a34a", exclude: "#dc2626" };

// 檢測區域編輯：選一張參考影像，以矩形或多邊形框選包含／排除區域 (座標為參考影像的像素座標)
export function RegionEditor({ value, onChange, readOnly }:
  { value: Regions | null | undefined; onChange: (v: Regions | null) => void; readOnly: boolean }) {
  const { t } = useApp();
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runId, setRunId] = useState<number | null>(value?.reference?.run_id ?? null);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [imgError, setImgError] = useState(false);
  const [tool, setTool] = useState<Tool>("rect");
  const [kind, setKind] = useState<Kind>("include");
  const [draft, setDraft] = useState<number[][] | null>(null);      // 繪製中的圖形 (參考影像座標)
  const [hover, setHover] = useState<number[] | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [cw, setCw] = useState(900);

  const ref = value?.reference || (runs.find((r) => r.id === runId) ? { width: runs.find((r) => r.id === runId)!.width, height: runs.find((r) => r.id === runId)!.height, run_id: runId! } : null);
  const include = value?.include || [];
  const exclude = value?.exclude || [];

  useEffect(() => {
    if (!readOnly) get<{ items: RunRow[] }>("/api/runs", { limit: 50 }).then((r) => setRuns(r.items)).catch(() => setRuns([]));
  }, [readOnly]);

  useEffect(() => {
    setImg(null);
    setImgError(false);
    if (!runId) return;
    const im = new Image();
    im.onload = () => setImg(im);
    im.onerror = () => setImgError(true);
    im.src = `/api/runs/${runId}/image?max_size=1600`;
  }, [runId]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setCw(Math.max(320, el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const scale = ref ? cw / ref.width : 1;
  const ch = ref ? Math.round(ref.height * scale) : 0;

  // 繪製
  useEffect(() => {
    const c = canvas.current;
    if (!c || !ref) return;
    const g = c.getContext("2d")!;
    g.clearRect(0, 0, c.width, c.height);
    g.fillStyle = "#808080";
    g.fillRect(0, 0, c.width, c.height);
    if (img) g.drawImage(img, 0, 0, c.width, c.height);
    const path = (s: RegionShape) => {
      g.beginPath();
      if (s.type === "rect") g.rect(s.x0! * scale, s.y0! * scale, (s.x1! - s.x0!) * scale, (s.y1! - s.y0!) * scale);
      else s.points!.forEach((p, i) => (i ? g.lineTo(p[0] * scale, p[1] * scale) : g.moveTo(p[0] * scale, p[1] * scale)));
      g.closePath();
    };
    for (const [k, list] of [["include", include], ["exclude", exclude]] as [Kind, RegionShape[]][]) {
      for (const s of list) {
        path(s);
        g.fillStyle = k === "include" ? "rgba(22,163,74,0.15)" : "rgba(220,38,38,0.25)";
        g.fill();
        g.strokeStyle = REGION_COLORS[k];
        g.lineWidth = 2;
        g.stroke();
      }
    }
    if (draft) {
      g.strokeStyle = REGION_COLORS[kind];
      g.setLineDash([6, 4]);
      g.lineWidth = 2;
      g.beginPath();
      const pts = tool === "rect" && hover ? rectPts(draft[0], hover) : [...draft, ...(hover ? [hover] : [])];
      pts.forEach((p, i) => (i ? g.lineTo(p[0] * scale, p[1] * scale) : g.moveTo(p[0] * scale, p[1] * scale)));
      if (tool === "rect") g.closePath();
      g.stroke();
      g.setLineDash([]);
    }
  }, [img, ref, include, exclude, draft, hover, scale, tool, kind, cw]);

  const toRef = (e: React.MouseEvent) => {
    const b = canvas.current!.getBoundingClientRect();
    return [Math.round((e.clientX - b.left) / scale), Math.round((e.clientY - b.top) / scale)];
  };
  const commit = (s: RegionShape) => {
    const base: Regions = value && value.reference ? value : { reference: ref!, include: [], exclude: [] };
    onChange({ ...base, reference: base.reference || ref!, [kind]: [...(base[kind] || []), s] });
    setDraft(null);
    setHover(null);
  };
  const onDown = (e: React.MouseEvent) => {
    if (readOnly || !ref) return;
    const p = toRef(e);
    if (tool === "rect") setDraft([p]);
    else setDraft([...(draft || []), p]);
  };
  const onUp = (e: React.MouseEvent) => {
    if (readOnly || tool !== "rect" || !draft) return;
    const p = toRef(e);
    const [a] = draft;
    if (Math.abs(p[0] - a[0]) >= 3 && Math.abs(p[1] - a[1]) >= 3)
      commit({ type: "rect", x0: Math.min(a[0], p[0]), y0: Math.min(a[1], p[1]), x1: Math.max(a[0], p[0]), y1: Math.max(a[1], p[1]) });
    else setDraft(null);
  };
  const onDbl = () => {
    if (readOnly || tool !== "polygon" || !draft) return;
    const pts = draft.filter((p, i) => i === 0 || p[0] !== draft[i - 1][0] || p[1] !== draft[i - 1][1]);
    if (pts.length >= 3) commit({ type: "polygon", points: pts });
    else setDraft(null);
  };
  const remove = (k: Kind, i: number) => {
    const next = { ...value!, [k]: (value![k] || []).filter((_, j) => j !== i) };
    onChange(next.include.length || next.exclude.length ? next : null);
  };
  const pickRun = (id: number) => {
    setRunId(id);
    const r = runs.find((x) => x.id === id);
    // 尺寸相同才更新參考紀錄；不同時保留原參考尺寸 (已框選的座標以它為準)，並提示確認位置
    if (r && value && value.reference.width === r.width && value.reference.height === r.height)
      onChange({ ...value, reference: { ...value.reference, run_id: id } });
  };

  const sizeMismatch = !!(value?.reference && runId && runs.find((r) => r.id === runId) &&
    (runs.find((r) => r.id === runId)!.width !== value.reference.width || runs.find((r) => r.id === runId)!.height !== value.reference.height));

  return (
    <div className="stack">
      <div className="muted">{t("ui.region.hint")}</div>
      {!readOnly && (
        <div className="row" style={{ flexWrap: "wrap", gap: "var(--sp-2)" }}>
          <label className="field" style={{ minWidth: 320 }}>{t("ui.region.reference")}
            <select value={runId ?? ""} onChange={(e) => pickRun(Number(e.target.value))}>
              <option value="" disabled>{t("ui.region.pick_reference")}</option>
              {runs.map((r) => <option key={r.id} value={r.id}>{r.file_name}（{r.width}×{r.height}，{fmtTime(r.created_at)}）</option>)}
            </select>
          </label>
          <label className="field">{t("ui.region.tool")}
            <select value={tool} onChange={(e) => { setTool(e.target.value as Tool); setDraft(null); }}>
              <option value="rect">{t("ui.region.rect")}</option>
              <option value="polygon">{t("ui.region.polygon")}</option>
            </select>
          </label>
          <label className="field">{t("ui.region.kind")}
            <select value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
              <option value="include">{t("ui.region.include")}</option>
              <option value="exclude">{t("ui.region.exclude")}</option>
            </select>
          </label>
          {draft && <button className="btn small" style={{ alignSelf: "flex-end" }} onClick={() => setDraft(null)}>{t("ui.cancel")}</button>}
        </div>
      )}
      {!readOnly && <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t(tool === "rect" ? "ui.region.rect_hint" : "ui.region.polygon_hint")}</div>}
      {sizeMismatch && <div className="alert info">{t("ui.region.size_mismatch")}</div>}
      {imgError && <div className="alert info">{t("error.image_unavailable")}</div>}
      <div ref={wrap} style={{ width: "100%" }}>
        {ref ? (
          <canvas ref={canvas} width={cw} height={ch} style={{ display: "block", cursor: readOnly ? "default" : "crosshair", borderRadius: 4 }}
            onMouseDown={onDown} onMouseUp={onUp} onDoubleClick={onDbl}
            onMouseMove={(e) => draft && setHover(toRef(e))} onMouseLeave={() => setHover(null)} />
        ) : <div className="muted">{readOnly ? t("ui.region.none") : t("ui.region.pick_first")}</div>}
      </div>
      {(include.length > 0 || exclude.length > 0) && (
        <table className="table">
          <thead><tr><th>{t("ui.region.kind")}</th><th>{t("ui.region.tool")}</th><th>{t("ui.region.coords")}</th><th></th></tr></thead>
          <tbody>
            {([["include", include], ["exclude", exclude]] as [Kind, RegionShape[]][]).flatMap(([k, list]) => list.map((s, i) => (
              <tr key={`${k}${i}`}>
                <td><span style={{ color: REGION_COLORS[k], fontWeight: 600 }}>■</span> {t(`ui.region.${k}`)}</td>
                <td>{t(`ui.region.${s.type}`)}</td>
                <td className="mono" style={{ fontSize: "var(--fs-xs)" }}>{s.type === "rect"
                  ? `(${Math.round(s.x0!)}, ${Math.round(s.y0!)}) – (${Math.round(s.x1!)}, ${Math.round(s.y1!)})`
                  : `${s.points!.length} ${t("ui.region.points")}`}</td>
                <td>{!readOnly && <button className="btn small danger" onClick={() => remove(k, i)}>{t("ui.delete")}</button>}</td>
              </tr>
            )))}
          </tbody>
        </table>
      )}
      {!readOnly && (include.length > 0 || exclude.length > 0) && (
        <div><button className="btn small" onClick={() => onChange(null)}>{t("ui.region.clear")}</button></div>
      )}
    </div>
  );
}

function rectPts(a: number[], b: number[]): number[][] {
  return [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
}
