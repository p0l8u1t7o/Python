import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { get } from "../api/client";
import type { RegionShape, Regions, RunDetail, RunRow } from "../api/types";
import { useApp } from "../app/context";
import { ImageViewer, buildShapes, type Shape, type View, type ViewerTool } from "./ImageViewer";
import { fmtTime } from "./ui";

type Kind = "include" | "exclude";
type Tool = "pan" | "rect" | "polygon" | "select";
type Sel = { kind: Kind; index: number } | null;
type Pt = [number, number];

export const REGION_COLORS: Record<Kind, string> = { include: "#16a34a", exclude: "#dc2626" };
const ARRAY_COLOR = "#f59e0b";
const HANDLE_PX = 7;             // 控制點點選範圍 (螢幕像素)
const MIN_PX = 3;                // 矩形最小邊長 (影像像素)

// ---------------------------------------------------------------------------
// 檢測區域編輯 (PLAN-004 第 3 節)：在可縮放、平移的影像檢視器上框選包含／排除區域。
// 座標以 value.reference (參考影像尺寸) 保存；顯示影像尺寸不同時依比例換算。
// ---------------------------------------------------------------------------
export function RegionCanvas({ value, onChange, readOnly, src, width, height, reference, shapes, arraysSupported, viewerHeight = "62vh", compact }: {
  value: Regions | null | undefined;
  onChange: (v: Regions | null) => void;
  readOnly: boolean;
  src: string;
  width: number;                                   // 顯示影像的原始尺寸
  height: number;
  reference?: Regions["reference"];                // 尚未設定區域時使用的參考尺寸 (預設為顯示影像尺寸)
  shapes?: Shape[];                                // 分析結果疊圖 (框選時對照)
  arraysSupported: boolean;
  viewerHeight?: string;
  compact?: boolean;                               // 區域清單放在影像下方 (版面較窄時)
}) {
  const { t } = useApp();
  const [tool, setTool] = useState<Tool>(readOnly ? "pan" : "rect");
  const [kind, setKind] = useState<Kind>("include");
  const [asArray, setAsArray] = useState(false);
  const [sel, setSel] = useState<Sel>(null);
  const [draft, setDraft] = useState<Pt[] | null>(null);
  const [hover, setHover] = useState<Pt | null>(null);
  const [showResult, setShowResult] = useState(true);
  const op = useRef<{ type: "rect" | "move" | "handle"; start: Pt; base: RegionShape; handle?: number; target?: Sel } | null>(null);
  const past = useRef<(Regions | null)[]>([]);
  const future = useRef<(Regions | null)[]>([]);

  const ref = value?.reference || reference || { width, height };
  const sx = width / ref.width, sy = height / ref.height;
  const include = value?.include || [];
  const exclude = value?.exclude || [];
  const list = useMemo(() => ([["include", include], ["exclude", exclude]] as [Kind, RegionShape[]][])
    .flatMap(([k, arr]) => arr.map((s, i) => ({ kind: k, index: i, shape: s }))), [include, exclude]);

  // 參考座標 ↔ 顯示影像座標
  const toImg = useCallback((p: number[]): Pt => [p[0] * sx, p[1] * sy], [sx, sy]);
  const toRef = useCallback((x: number, y: number): Pt => [Math.round(x / sx), Math.round(y / sy)], [sx, sy]);
  const clampRef = (p: Pt): Pt => [Math.min(Math.max(p[0], 0), ref.width), Math.min(Math.max(p[1], 0), ref.height)];

  const apply = useCallback((next: Regions | null, record = true) => {
    if (record) {
      past.current.push(value ?? null);
      if (past.current.length > 100) past.current.shift();
      future.current = [];
    }
    onChange(next && (next.include.length || next.exclude.length) ? next : null);
  }, [value, onChange]);

  const base = (): Regions => value && value.reference ? value : { reference: ref, include: [], exclude: [] };
  const replace = (k: Kind, i: number, s: RegionShape, record: boolean) => {
    const b = base();
    apply({ ...b, [k]: b[k].map((x, j) => (j === i ? s : x)) }, record);
  };
  const remove = (k: Kind, i: number) => {
    const b = base();
    apply({ ...b, [k]: b[k].filter((_, j) => j !== i) });
    setSel(null);
  };
  const add = (s: RegionShape) => {
    const b = base();
    const shape: RegionShape = kind === "include" && asArray && arraysSupported ? { ...s, as_array: true } : s;
    const next = { ...b, [kind]: [...b[kind], shape] };
    apply(next);
    setSel({ kind, index: next[kind].length - 1 });
    setDraft(null);
  };
  const undo = () => {
    if (!past.current.length) return;
    future.current.push(value ?? null);
    onChange(past.current.pop()!);
    setSel(null);
  };
  const redo = () => {
    if (!future.current.length) return;
    past.current.push(value ?? null);
    onChange(future.current.pop()!);
    setSel(null);
  };

  const finishPolygon = () => {
    if (!draft) return;
    const pts = draft.filter((p, i) => i === 0 || p[0] !== draft[i - 1][0] || p[1] !== draft[i - 1][1]);
    if (pts.length >= 3) add({ type: "polygon", points: pts });
    else setDraft(null);
  };

  // 鍵盤：Delete 刪除、Esc 取消、Enter 完成多邊形、Ctrl+Z／Ctrl+Y 復原／重做
  useEffect(() => {
    if (readOnly) return;
    const kd = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT")) return;
      if (e.key === "Escape") { setDraft(null); setSel(null); }
      else if (e.key === "Enter" && draft) { e.preventDefault(); finishPolygon(); }
      else if ((e.key === "Delete" || e.key === "Backspace") && sel) { e.preventDefault(); remove(sel.kind, sel.index); }
      else if (e.ctrlKey && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
      else if (e.ctrlKey && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); }
    };
    window.addEventListener("keydown", kd);
    return () => window.removeEventListener("keydown", kd);
  });

  // 幾何：圖形頂點 (顯示影像座標)、點選測試
  const verts = (s: RegionShape): Pt[] => s.type === "rect"
    ? [toImg([s.x0!, s.y0!]), toImg([s.x1!, s.y0!]), toImg([s.x1!, s.y1!]), toImg([s.x0!, s.y1!])]
    : s.points!.map(toImg);
  const handles = (s: RegionShape): Pt[] => {
    if (s.type !== "rect") return verts(s);
    const [a, b] = [toImg([s.x0!, s.y0!]), toImg([s.x1!, s.y1!])];
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    return [[a[0], a[1]], [mx, a[1]], [b[0], a[1]], [b[0], my], [b[0], b[1]], [mx, b[1]], [a[0], b[1]], [a[0], my]];
  };
  const hitHandle = (x: number, y: number, view: View): number => {
    if (!sel) return -1;
    const s = (sel.kind === "include" ? include : exclude)[sel.index];
    if (!s) return -1;
    const r = HANDLE_PX / view.zoom;
    return handles(s).findIndex((h) => Math.abs(h[0] - x) <= r && Math.abs(h[1] - y) <= r);
  };
  const hitShape = (x: number, y: number): Sel => {
    for (let n = list.length - 1; n >= 0; n--) {
      if (inPoly(verts(list[n].shape), x, y)) return { kind: list[n].kind, index: list[n].index };
    }
    return null;
  };

  // 拖拉：移動整個圖形或控制點 (參考座標)
  const dragTo = (x: number, y: number) => {
    const o = op.current;
    const tg = o?.target;
    if (!o || !tg) return;
    const p = toRef(x, y);
    const s = o.base;
    if (o.type === "move") {
      const dx = p[0] - o.start[0], dy = p[1] - o.start[1];
      const moved: RegionShape = s.type === "rect"
        ? { ...s, x0: s.x0! + dx, x1: s.x1! + dx, y0: s.y0! + dy, y1: s.y1! + dy }
        : { ...s, points: s.points!.map((q) => [q[0] + dx, q[1] + dy]) };
      replace(tg.kind, tg.index, moved, false);
    } else if (o.type === "handle") {
      const q = clampRef(p);
      if (s.type === "rect") {
        const h = o.handle!;
        const n = { ...s };
        if ([0, 6, 7].includes(h)) n.x0 = q[0];
        if ([2, 3, 4].includes(h)) n.x1 = q[0];
        if ([0, 1, 2].includes(h)) n.y0 = q[1];
        if ([4, 5, 6].includes(h)) n.y1 = q[1];
        replace(tg.kind, tg.index, n, false);
      } else {
        replace(tg.kind, tg.index, { ...s, points: s.points!.map((v, i) => (i === o.handle ? q : v)) }, false);
      }
    }
  };
  const normalizeRect = (s: RegionShape): RegionShape | null => {
    if (s.type !== "rect") return s;
    const n = { ...s, x0: Math.min(s.x0!, s.x1!), x1: Math.max(s.x0!, s.x1!), y0: Math.min(s.y0!, s.y1!), y1: Math.max(s.y0!, s.y1!) };
    return n.x1 - n.x0 >= 1 && n.y1 - n.y0 >= 1 ? n : null;
  };

  const viewerTool: ViewerTool | undefined = useMemo(() => {
    const paint = (g: CanvasRenderingContext2D, view: View) => {
      const P = (p: Pt) => [view.ox + p[0] * view.zoom, view.oy + p[1] * view.zoom];
      const outline = (pts: Pt[], close: boolean) => {
        g.beginPath();
        pts.forEach((p, i) => { const [a, b] = P(p); if (i) g.lineTo(a, b); else g.moveTo(a, b); });
        if (close) g.closePath();
      };
      g.save();
      let nIn = 0, nEx = 0;
      for (const it of list) {
        const s = it.shape;
        const pts = verts(s);
        const isSel = sel && sel.kind === it.kind && sel.index === it.index;
        const color = s.as_array ? ARRAY_COLOR : REGION_COLORS[it.kind];
        outline(pts, true);
        g.fillStyle = it.kind === "include" ? (s.as_array ? "rgba(245,158,11,0.12)" : "rgba(22,163,74,0.12)") : "rgba(220,38,38,0.22)";
        g.fill();
        g.setLineDash(it.kind === "exclude" ? [6, 4] : []);
        g.strokeStyle = isSel ? "#ffffff" : color;
        g.lineWidth = isSel ? 2.5 : 2;
        g.stroke();
        g.setLineDash([]);
        const n = it.kind === "include" ? ++nIn : ++nEx;
        const name = s.label || `${t(`ui.region.${it.kind}`)} ${n}`;
        const [lx, ly] = P([Math.min(...pts.map((p) => p[0])), Math.min(...pts.map((p) => p[1]))]);
        g.font = "600 12px Segoe UI, sans-serif";
        const txt = s.as_array ? `${name}・${t("ui.region.as_array_short")}` : name;
        g.lineWidth = 4;
        g.strokeStyle = "rgba(0,0,0,0.75)";
        g.strokeText(txt, lx + 4, ly + 15);
        g.fillStyle = color;
        g.fillText(txt, lx + 4, ly + 15);
        if (isSel && !readOnly) {
          g.fillStyle = "#ffffff";
          g.strokeStyle = "#111";
          g.lineWidth = 1;
          for (const h of handles(s)) {
            const [a, b] = P(h);
            g.fillRect(a - 4, b - 4, 8, 8);
            g.strokeRect(a - 4, b - 4, 8, 8);
          }
        }
      }
      if (draft) {
        const pts = (tool === "rect" && hover
          ? [draft[0], [hover[0], draft[0][1]], hover, [draft[0][0], hover[1]]]
          : [...draft, ...(hover ? [hover] : [])]).map((p) => toImg(p));
        outline(pts as Pt[], tool === "rect");
        g.setLineDash([6, 4]);
        g.strokeStyle = kind === "include" && asArray && arraysSupported ? ARRAY_COLOR : REGION_COLORS[kind];
        g.lineWidth = 2;
        g.stroke();
      }
      g.restore();
    };
    if (readOnly) return { paint };
    return {
      paint,
      cursor: tool === "pan" ? undefined : tool === "select" ? "default" : "crosshair",
      down: (x, y, _e, view) => {
        if (tool === "pan") return false;
        if (tool === "rect") {
          const p = clampRef(toRef(x, y));
          setDraft([p]);
          setHover(p);
          op.current = { type: "rect", start: p, base: { type: "rect" } };
          return true;
        }
        if (tool === "polygon") {
          const p = clampRef(toRef(x, y));
          setDraft((d) => [...(d || []), p]);
          return true;
        }
        // 選取：控制點 → 圖形 → 空白處平移
        const h = hitHandle(x, y, view);
        if (h >= 0 && sel) {
          const s = (sel.kind === "include" ? include : exclude)[sel.index];
          past.current.push(value ?? null);
          future.current = [];
          op.current = { type: "handle", start: toRef(x, y), base: s, handle: h, target: sel };
          return true;
        }
        const hit = hitShape(x, y);
        setSel(hit);
        if (!hit) return false;
        const s = (hit.kind === "include" ? include : exclude)[hit.index];
        past.current.push(value ?? null);
        future.current = [];
        op.current = { type: "move", start: toRef(x, y), base: s, target: hit };
        return true;
      },
      move: (x, y) => {
        if (tool === "rect" || tool === "polygon") {
          if (draft) setHover(clampRef(toRef(x, y)));
          return;
        }
        if (op.current) dragTo(x, y);
      },
      up: (x, y) => {
        const o = op.current;
        op.current = null;
        if (!o) return;
        if (o.type === "rect") {
          const p = clampRef(toRef(x, y));
          const a = o.start;
          if (Math.abs(p[0] - a[0]) * sx >= MIN_PX && Math.abs(p[1] - a[1]) * sy >= MIN_PX)
            add({ type: "rect", x0: Math.min(a[0], p[0]), y0: Math.min(a[1], p[1]), x1: Math.max(a[0], p[0]), y1: Math.max(a[1], p[1]) });
          else setDraft(null);
          setHover(null);
        } else if (o.target) {
          // 矩形拖拉控制點後整理座標；太小時還原
          const tg = o.target;
          const s = (tg.kind === "include" ? include : exclude)[tg.index];
          if (s && s.type === "rect") replace(tg.kind, tg.index, normalizeRect(s) || o.base, false);
        }
      },
      dblclick: (x, y) => {
        if (tool === "polygon") { finishPolygon(); return true; }
        if (tool === "select" && sel) {
          // 在多邊形的邊上連按兩下插入頂點
          const s = (sel.kind === "include" ? include : exclude)[sel.index];
          if (s?.type === "polygon") {
            const pts = verts(s);
            let best = -1, bd = Infinity;
            pts.forEach((p, i) => {
              const d = segDist([x, y], p, pts[(i + 1) % pts.length]);
              if (d < bd) { bd = d; best = i; }
            });
            if (best >= 0) {
              const q = toRef(x, y);
              const np = [...s.points!];
              np.splice(best + 1, 0, q);
              replace(sel.kind, sel.index, { ...s, points: np }, true);
            }
            return true;
          }
        }
        return false;
      },
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list, sel, draft, hover, tool, kind, asArray, arraysSupported, readOnly, sx, sy, value, t]);

  const overlap = useMemo(() => arrayOverlap(include.filter((s) => s.as_array)), [include]);
  const selShape = sel ? (sel.kind === "include" ? include : exclude)[sel.index] : null;
  const updateSel = (patch: Partial<RegionShape>) => {
    if (!sel || !selShape) return;
    const n: RegionShape = { ...selShape, ...patch };
    if (!n.label) delete n.label;
    if (!n.as_array) delete n.as_array;
    replace(sel.kind, sel.index, n, true);
  };

  return (
    <div className={`region-editor${compact ? " compact" : ""}`}>
      {!readOnly && (
        <div className="region-toolbar">
          <div className="seg">
            {(["pan", "rect", "polygon", "select"] as Tool[]).map((k) => (
              <button key={k} className={tool === k ? "active" : ""} onClick={() => { setTool(k); setDraft(null); }}>{t(`ui.region.tool_${k}`)}</button>
            ))}
          </div>
          <div className="seg">
            {(["include", "exclude"] as Kind[]).map((k) => (
              <button key={k} className={kind === k ? "active" : ""} onClick={() => setKind(k)}>
                <span style={{ color: REGION_COLORS[k] }}>■</span> {t(`ui.region.${k}`)}
              </button>
            ))}
          </div>
          {arraysSupported && kind === "include" && (
            <label className="check"><input type="checkbox" checked={asArray} onChange={(e) => setAsArray(e.target.checked)} /> {t("ui.region.as_array")}</label>
          )}
          <button className="btn small" disabled={!past.current.length} onClick={undo} title="Ctrl+Z">{t("ui.region.undo")}</button>
          <button className="btn small" disabled={!future.current.length} onClick={redo} title="Ctrl+Y">{t("ui.region.redo")}</button>
          {shapes && shapes.length > 0 && (
            <label className="check"><input type="checkbox" checked={showResult} onChange={(e) => setShowResult(e.target.checked)} /> {t("ui.region.show_result")}</label>
          )}
        </div>
      )}
      {!readOnly && <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t(`ui.region.hint_${tool}`)}</div>}
      {overlap && <div className="alert info">{t("ui.region.array_overlap")}</div>}
      <div className="region-body">
        <div className="region-viewer" style={{ height: viewerHeight }}>
          <ImageViewer src={src} width={width} height={height} shapes={showResult ? (shapes || []).filter((s) => s.layer !== "recipe.regions") : []}
            hiddenLayers={new Set()} opacity={0.8} brightness={1} contrast={1} tool={viewerTool} />
        </div>
        <div className="region-list">
          {!list.length && <div className="muted">{t("ui.region.none")}</div>}
          {list.map((it, n) => {
            const s = it.shape;
            const active = sel && sel.kind === it.kind && sel.index === it.index;
            const no = list.filter((x, j) => x.kind === it.kind && j <= n).length;
            return (
              <div key={`${it.kind}${it.index}`} className={`region-item${active ? " active" : ""}`} onClick={() => { setSel({ kind: it.kind, index: it.index }); if (!readOnly) setTool("select"); }}>
                <div className="row" style={{ gap: "var(--sp-2)" }}>
                  <span style={{ color: s.as_array ? ARRAY_COLOR : REGION_COLORS[it.kind], fontWeight: 700 }}>■</span>
                  <strong>{s.label || `${t(`ui.region.${it.kind}`)} ${no}`}</strong>
                  <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t(`ui.region.${s.type}`)}{s.as_array ? `・${t("ui.region.as_array_short")}` : ""}</span>
                </div>
                <div className="mono muted" style={{ fontSize: "var(--fs-xs)" }}>{s.type === "rect"
                  ? `(${Math.round(s.x0!)}, ${Math.round(s.y0!)}) – (${Math.round(s.x1!)}, ${Math.round(s.y1!)})`
                  : `${s.points!.length} ${t("ui.region.points")}`}</div>
                {active && !readOnly && (
                  <div className="stack" style={{ gap: "var(--sp-2)", marginTop: "var(--sp-2)" }} onClick={(e) => e.stopPropagation()}>
                    <label className="field">{t("ui.region.label")}
                      <input type="text" maxLength={32} value={s.label || ""} placeholder={`${t(`ui.region.${it.kind}`)} ${no}`}
                        onChange={(e) => updateSel({ label: e.target.value })} />
                    </label>
                    <label className="field">{t("ui.region.kind")}
                      <select value={it.kind} onChange={(e) => {
                        const k = e.target.value as Kind;
                        if (k === it.kind) return;
                        const b = base();
                        const moved: RegionShape = { ...s };
                        delete moved.as_array;
                        const next = { ...b, [it.kind]: b[it.kind].filter((_, j) => j !== it.index), [k]: [...b[k], moved] };
                        apply(next);
                        setSel({ kind: k, index: next[k].length - 1 });
                      }}>
                        <option value="include">{t("ui.region.include")}</option>
                        <option value="exclude">{t("ui.region.exclude")}</option>
                      </select>
                    </label>
                    {arraysSupported && it.kind === "include" && (
                      <label className="check"><input type="checkbox" checked={!!s.as_array} onChange={(e) => updateSel({ as_array: e.target.checked })} /> {t("ui.region.as_array")}</label>
                    )}
                    <div><button className="btn small danger" onClick={() => remove(it.kind, it.index)}>{t("ui.delete")}</button></div>
                  </div>
                )}
              </div>
            );
          })}
          {!readOnly && list.length > 0 && (
            <div><button className="btn small" onClick={() => { apply(null); setSel(null); }}>{t("ui.region.clear")}</button></div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 配方編輯器用：選一筆檢測紀錄的影像作為參考影像，並可疊上該紀錄的分析結果
// ---------------------------------------------------------------------------
export function RegionEditor({ value, onChange, readOnly, arraysSupported }:
  { value: Regions | null | undefined; onChange: (v: Regions | null) => void; readOnly: boolean; arraysSupported: boolean }) {
  const { t, modules } = useApp();
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runId, setRunId] = useState<number | null>(value?.reference?.run_id ?? null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    get<{ items: RunRow[] }>("/api/runs", { limit: 50 }).then((r) => setRuns(r.items)).catch(() => setRuns([]));
  }, []);
  useEffect(() => {
    setDetail(null);
    setError(false);
    if (!runId) return;
    get<RunDetail>(`/api/runs/${runId}`).then(setDetail).catch(() => setError(true));
  }, [runId]);

  const run = detail?.run || runs.find((r) => r.id === runId) || null;
  const shapes = useMemo(() => (detail ? buildShapes(detail.result, modules, 10, t("ui.group")) : []), [detail, modules, t]);
  const pickRun = (id: number) => {
    setRunId(id);
    const r = runs.find((x) => x.id === id);
    // 尺寸相同才更新參考紀錄；不同時保留原參考尺寸 (已框選的座標以它為準)，並提示確認位置
    if (r && value && value.reference.width === r.width && value.reference.height === r.height)
      onChange({ ...value, reference: { ...value.reference, run_id: id } });
  };
  const sizeMismatch = !!(value?.reference && run && (run.width !== value.reference.width || run.height !== value.reference.height));

  return (
    <div className="stack">
      <div className="muted">{t("ui.region.hint")}</div>
      <label className="field" style={{ maxWidth: 480 }}>{t("ui.region.reference")}
        <select value={runId ?? ""} onChange={(e) => pickRun(Number(e.target.value))}>
          <option value="" disabled>{t("ui.region.pick_reference")}</option>
          {runId && !runs.some((r) => r.id === runId) && <option value={runId}>#{runId}</option>}
          {runs.map((r) => <option key={r.id} value={r.id}>{r.file_name}（{r.width}×{r.height}，{fmtTime(r.created_at)}）</option>)}
        </select>
      </label>
      {sizeMismatch && <div className="alert info">{t("ui.region.size_mismatch")}</div>}
      {error && <div className="alert info">{t("error.image_unavailable")}</div>}
      {run ? (
        <RegionCanvas value={value} readOnly={readOnly} arraysSupported={arraysSupported} src={`/api/runs/${run.id}/image?max_size=2048`}
          width={run.width} height={run.height} reference={{ width: run.width, height: run.height, run_id: run.id }} shapes={shapes}
          onChange={onChange} />
      ) : (
        <div className="muted">{value ? t("ui.region.pick_first") : readOnly ? t("ui.region.none") : t("ui.region.pick_first")}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function inPoly(pts: Pt[], x: number, y: number): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function segDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const L = dx * dx + dy * dy;
  const u = L ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L)) : 0;
  return Math.hypot(p[0] - (a[0] + u * dx), p[1] - (a[1] + u * dy));
}

// 「視為一個陣列」區域是否重疊 (以外框判斷)
function arrayOverlap(shapes: RegionShape[]): boolean {
  const box = (s: RegionShape) => s.type === "rect" ? [s.x0!, s.y0!, s.x1!, s.y1!]
    : [Math.min(...s.points!.map((p) => p[0])), Math.min(...s.points!.map((p) => p[1])), Math.max(...s.points!.map((p) => p[0])), Math.max(...s.points!.map((p) => p[1]))];
  for (let i = 0; i < shapes.length; i++)
    for (let j = i + 1; j < shapes.length; j++) {
      const a = box(shapes[i]), b = box(shapes[j]);
      if (a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]) return true;
    }
  return false;
}
