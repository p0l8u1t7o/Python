import { useCallback, useEffect, useRef, useState } from "react";
import type { AnalysisResult, Finding, ModuleInfo } from "../api/types";

// 疊圖圖形 (原始影像座標)
export interface Shape {
  kind: "circle" | "line" | "arrow" | "rect" | "cross" | "text";
  layer: string;          // 圖層名稱 (可開關)
  color: string;
  width: number;
  x: number;
  y: number;
  r?: number;
  x2?: number;
  y2?: number;
  text?: string;
  findingKey?: string;    // 點選對應的檢測物件
  dash?: boolean;
}

export interface View {
  zoom: number;   // 螢幕像素 / 原始影像像素
  ox: number;     // 影像原點在畫布上的位置
  oy: number;
}

interface Props {
  src: string;
  width: number;             // 原始影像寬
  height: number;
  shapes: Shape[];
  hiddenLayers: Set<string>;
  opacity: number;
  brightness: number;        // 1 = 原始
  contrast: number;
  selected?: string | null;
  onPick?: (x: number, y: number) => void;
}

export function ImageViewer({ src, width, height, shapes, hiddenLayers, opacity, brightness, contrast, selected, onPick }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const img = useRef<HTMLImageElement | null>(null);
  const [ready, setReady] = useState(false);
  const [view, setView] = useState<View>({ zoom: 1, ox: 0, oy: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number; moved: boolean } | null>(null);
  const [dragging, setDragging] = useState(false);

  const fit = useCallback(() => {
    const el = wrap.current;
    if (!el) return;
    const z = Math.min(el.clientWidth / width, el.clientHeight / height) * 0.98;
    setView({ zoom: z, ox: (el.clientWidth - width * z) / 2, oy: (el.clientHeight - height * z) / 2 });
  }, [width, height]);

  useEffect(() => {
    setReady(false);
    const im = new Image();
    im.onload = () => {
      img.current = im;
      setReady(true);
      fit();
    };
    im.src = src;
  }, [src, fit]);

  const draw = useCallback(() => {
    const c = canvas.current;
    const el = wrap.current;
    if (!c || !el) return;
    const dpr = window.devicePixelRatio || 1;
    const W = el.clientWidth;
    const H = el.clientHeight;
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) {
      c.width = Math.round(W * dpr);
      c.height = Math.round(H * dpr);
    }
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const im = img.current;
    if (!ready || !im) return;
    const { zoom, ox, oy } = view;
    ctx.save();
    ctx.imageSmoothingEnabled = zoom < 2;
    ctx.filter = `brightness(${brightness}) contrast(${contrast})`;
    ctx.drawImage(im, ox, oy, width * zoom, height * zoom);
    ctx.restore();
    // 疊圖在螢幕座標繪製，放大時線條仍保持細而清晰
    paintShapes(ctx, shapes, view, hiddenLayers, opacity, selected ?? null);
  }, [ready, view, shapes, hiddenLayers, opacity, brightness, contrast, selected, width, height]);

  useEffect(draw, [draw]);

  // 畫布大小跟隨容器
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(el);
    return () => ro.disconnect();
  }, [draw]);

  const onWheel = (e: React.WheelEvent) => {
    const rect = canvas.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const k = Math.exp(-e.deltaY * 0.0015);
    setView((v) => {
      const z = Math.min(Math.max(v.zoom * k, 0.05), 40);
      const f = z / v.zoom;
      return { zoom: z, ox: mx - (mx - v.ox) * f, oy: my - (my - v.oy) * f };
    });
  };

  const onDown = (e: React.MouseEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, ox: view.ox, oy: view.oy, moved: false };
    setDragging(true);
  };
  const onMove = (e: React.MouseEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    setView((v) => ({ ...v, ox: d.ox + dx, oy: d.oy + dy }));
  };
  const onUp = (e: React.MouseEvent) => {
    const d = drag.current;
    drag.current = null;
    setDragging(false);
    if (d && !d.moved && onPick) {
      const rect = canvas.current!.getBoundingClientRect();
      onPick((e.clientX - rect.left - view.ox) / view.zoom, (e.clientY - rect.top - view.oy) / view.zoom);
    }
  };

  return (
    <div ref={wrap} className="viewer" style={{ width: "100%", height: "100%" }}>
      <canvas
        ref={canvas}
        className={dragging ? "dragging" : ""}
        onWheel={onWheel}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={onUp}
        onMouseLeave={() => {
          drag.current = null;
          setDragging(false);
        }}
        onDoubleClick={fit}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// 疊圖繪製 (互動檢視與報告快照共用)
// ---------------------------------------------------------------------------
export function paintShapes(ctx: CanvasRenderingContext2D, shapes: Shape[], view: View, hidden: Set<string>,
  opacity: number, selected: string | null) {
  const { zoom, ox, oy } = view;
  ctx.save();
  ctx.globalAlpha = opacity;
  const P = (x: number, y: number): [number, number] => [ox + x * zoom, oy + y * zoom];
  for (const s of shapes) {
    if (hidden.has(s.layer)) continue;
    const hi = selected && s.findingKey === selected;
    ctx.strokeStyle = hi ? "#ffffff" : s.color;
    ctx.fillStyle = s.color;
    ctx.lineWidth = hi ? s.width + 1.5 : s.width;
    ctx.setLineDash(s.dash ? [5, 4] : []);
    const [x, y] = P(s.x, s.y);
    ctx.beginPath();
    if (s.kind === "circle") {
      ctx.arc(x, y, Math.max((s.r || 0) * zoom, 0.5), 0, Math.PI * 2);
      ctx.stroke();
    } else if (s.kind === "line" || s.kind === "arrow") {
      const [x2, y2] = P(s.x2!, s.y2!);
      ctx.moveTo(x, y);
      ctx.lineTo(x2, y2);
      ctx.stroke();
      if (s.kind === "arrow") {
        const a = Math.atan2(y2 - y, x2 - x);
        const L = Math.min(14, Math.hypot(x2 - x, y2 - y) * 0.35);
        ctx.beginPath();
        ctx.moveTo(x2, y2);
        ctx.lineTo(x2 - L * Math.cos(a - 0.45), y2 - L * Math.sin(a - 0.45));
        ctx.moveTo(x2, y2);
        ctx.lineTo(x2 - L * Math.cos(a + 0.45), y2 - L * Math.sin(a + 0.45));
        ctx.stroke();
      }
    } else if (s.kind === "rect") {
      const [x2, y2] = P(s.x2!, s.y2!);
      ctx.strokeRect(x, y, x2 - x, y2 - y);
    } else if (s.kind === "cross") {
      const d = Math.max((s.r || 6) * zoom * 0.5, 4);
      ctx.moveTo(x - d, y - d);
      ctx.lineTo(x + d, y + d);
      ctx.moveTo(x + d, y - d);
      ctx.lineTo(x - d, y + d);
      ctx.stroke();
    } else if (s.kind === "text") {
      ctx.font = "600 13px Segoe UI, sans-serif";
      ctx.lineWidth = 4;
      ctx.strokeStyle = "rgba(0,0,0,0.75)";
      ctx.strokeText(s.text || "", x, y);
      ctx.fillText(s.text || "", x, y);
    }
  }
  ctx.restore();
}

// 報告用快照：影像 + 疊圖，回傳 PNG data URL
export function snapshot(src: string, width: number, height: number, shapes: Shape[], outWidth = 1400): Promise<string> {
  return new Promise((resolve, reject) => {
    const im = new Image();
    im.onload = () => {
      const zoom = outWidth / width;
      const c = document.createElement("canvas");
      c.width = outWidth;
      c.height = Math.round(height * zoom);
      const ctx = c.getContext("2d")!;
      ctx.drawImage(im, 0, 0, c.width, c.height);
      paintShapes(ctx, shapes, { zoom, ox: 0, oy: 0 }, new Set(), 1, null);
      resolve(c.toDataURL("image/png"));
    };
    im.onerror = reject;
    im.src = src;
  });
}

// ---------------------------------------------------------------------------
// 分析結果 → 疊圖圖形 (依幾何類型與模組宣告的樣式，通用於所有檢測模組)
// ---------------------------------------------------------------------------
export function buildShapes(result: AnalysisResult, modules: Record<string, ModuleInfo>, vectorScale: number,
  groupLabel: string): Shape[] {
  const out: Shape[] = [];
  // 配方的檢測區域 (依影像與參考影像的尺寸比例縮放)
  const reg = result.recipe?.regions;
  if (reg && reg.reference) {
    const sx = result.image.width / reg.reference.width, sy = result.image.height / reg.reference.height;
    for (const [kind, color] of [["include", "#16a34a"], ["exclude", "#dc2626"]] as ["include" | "exclude", string][]) {
      for (const s of reg[kind] || []) {
        const pts = s.type === "rect"
          ? [[s.x0!, s.y0!], [s.x1!, s.y0!], [s.x1!, s.y1!], [s.x0!, s.y1!]]
          : s.points!;
        pts.forEach((p, j) => {
          const q = pts[(j + 1) % pts.length];
          out.push({ kind: "line", layer: "recipe.regions", color, width: 2, x: p[0] * sx, y: p[1] * sy, x2: q[0] * sx, y2: q[1] * sy, dash: true });
        });
      }
    }
  }
  for (const m of result.modules) {
    const styles = modules[m.module_id]?.overlay_styles || {};
    const unused = styles.unused || { color: "#969696", thickness: 1 };
    for (const f of m.findings) {
      const key = `${m.module_id}:${f.id}`;
      const names = Object.keys(f.geometry);
      names.forEach((name, i) => {
        const g = f.geometry[name];
        if (!f.used && i > 0) return;
        const st = f.used ? styles[name] || { color: "#ffffff", thickness: 1 } : unused;
        const layer = f.used ? `${m.module_id}.${name}` : `${m.module_id}.unused`;
        const width = Math.max(1, (st.thickness || 1) * 0.75);
        if (g.type === "circle") {
          out.push({ kind: "circle", layer, color: st.color, width, x: g.x!, y: g.y!, r: g.r!, findingKey: key, dash: !f.used });
        } else if (g.type === "vector") {
          const k = vectorScale;
          out.push({ kind: "line", layer, color: st.color, width, x: g.x!, y: g.y!, x2: g.x! + k * g.dx!, y2: g.y! + k * g.dy!, findingKey: key });
        } else if (g.type === "bbox") {
          out.push({ kind: "rect", layer, color: st.color, width, x: g.x0!, y: g.y0!, x2: g.x1!, y2: g.y1!, findingKey: key });
        } else if (g.type === "polygon" && g.points) {
          const pts = g.points;
          pts.forEach((p, j) => {
            const q = pts[(j + 1) % pts.length];
            out.push({ kind: "line", layer, color: st.color, width, x: p[0], y: p[1], x2: q[0], y2: q[1], findingKey: key });
          });
        }
      });
    }
    for (const r of m.rejected) {
      if (r.reason === "border" || r.reason === "on_ball" || r.reason === "not_ball") continue;
      out.push({ kind: "cross", layer: `${m.module_id}.rejected`, color: "#ff3cc8", width: 1.5, x: r.x, y: r.y, r: r.r });
    }
    const gs = styles.group || { color: "#00a0ff", thickness: 2 };
    const ga = styles.group_shift || { color: "#00a0ff", thickness: 3, scale: 40 };
    for (const g of m.groups) {
      if (!g.bbox) continue;
      const [x0, y0, x1, y1] = g.bbox;
      out.push({ kind: "rect", layer: `${m.module_id}.group`, color: gs.color, width: 2, x: x0, y: y0, x2: x1, y2: y1 });
      out.push({ kind: "text", layer: `${m.module_id}.group`, color: gs.color, width: 1, x: x0 + 4, y: y0 + 18, text: `${groupLabel} ${g.id}` });
      const e = g.estimate;
      if (e) {
        const k = (ga.scale || 40) * (vectorScale / ((styles.offset?.scale as number) || 10));
        out.push({ kind: "arrow", layer: `${m.module_id}.group`, color: ga.color, width: 3, x: e.cx, y: e.cy, x2: e.cx + k * e.dx, y2: e.cy + k * e.dy });
      }
    }
  }
  return out;
}

export function layersOf(shapes: Shape[]): string[] {
  return Array.from(new Set(shapes.map((s) => s.layer)));
}

// 點選位置最近的檢測物件 (以第一個圓形幾何判斷)
export function pickFinding(result: AnalysisResult, x: number, y: number): { moduleId: string; finding: Finding } | null {
  let best: { moduleId: string; finding: Finding; d: number } | null = null;
  for (const m of result.modules) {
    for (const f of m.findings) {
      const g = Object.values(f.geometry).find((q) => q.type === "circle");
      if (!g) continue;
      const d = Math.hypot(g.x! - x, g.y! - y);
      if (d <= (g.r || 10) * 1.3 && (!best || d < best.d)) best = { moduleId: m.module_id, finding: f, d };
    }
  }
  return best ? { moduleId: best.moduleId, finding: best.finding } : null;
}
