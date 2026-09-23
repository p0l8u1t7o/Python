import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { get, send } from "../api/client";
import type { RunDetail } from "../api/types";
import { useApp } from "../app/context";
import { Layout } from "../components/Layout";
import { ErrorBox, fmtTime, useLoad } from "../components/ui";

interface AnnotationData { balls: number[][]; voids: number[][][] }
interface AnnotationInfo {
  current: { id: number; data: AnnotationData; actor: string; created_at: string; note: string } | null;
  history_count: number;
  base: AnnotationData;
}
type Tool = "select" | "polygon" | "erase";

// 空洞標註 (規劃書 PLAN-002 第 6 節)：修正空洞輪廓，作為訓練資料與模組驗證的正確答案
export function Annotate() {
  const { id } = useParams();
  const runId = Number(id);
  const { t, can } = useApp();
  const edit = can("annotate");
  const [detail, error] = useLoad(() => get<RunDetail>(`/api/runs/${runId}`), [runId]);
  const [info, infoError, reloadInfo] = useLoad(() => get<AnnotationInfo>(`/api/runs/${runId}/annotation`, { module_id: "void" }), [runId]);
  const [data, setData] = useState<AnnotationData | null>(null);
  const [dirty, setDirty] = useState(false);
  const [tool, setTool] = useState<Tool>("polygon");
  const [sel, setSel] = useState<number | null>(null);
  const [draft, setDraft] = useState<number[][] | null>(null);
  const [hover, setHover] = useState<number[] | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [msg, setMsg] = useState("");
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const view = useRef({ zoom: 1, ox: 0, oy: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number; moved: boolean } | null>(null);
  const [, redraw] = useState(0);

  useEffect(() => {
    if (info && !data) setData(info.current ? info.current.data : info.base);
  }, [info, data]);

  useEffect(() => {
    const im = new Image();
    im.onload = () => setImg(im);
    im.src = `/api/runs/${runId}/image?max_size=4096`;
  }, [runId]);

  const W = detail?.result.image.width || 1, H = detail?.result.image.height || 1;

  const fit = useCallback(() => {
    const c = canvas.current;
    if (!c) return;
    const z = Math.min(c.width / W, c.height / H);
    view.current = { zoom: z, ox: (c.width - W * z) / 2, oy: (c.height - H * z) / 2 };
    redraw((n) => n + 1);
  }, [W, H]);

  useEffect(() => {
    const el = wrap.current, c = canvas.current;
    if (!el || !c) return;
    const ro = new ResizeObserver(() => {
      c.width = el.clientWidth;
      c.height = el.clientHeight;
      fit();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit, detail, info]);

  // 繪製 (每次都確認畫布尺寸與外框一致；外框在資料載入後才出現，尺寸不一致時重新置中)
  useEffect(() => {
    const c = canvas.current, el = wrap.current;
    if (!c || !data) return;
    if (el && el.clientWidth > 0 && (c.width !== el.clientWidth || c.height !== el.clientHeight)) {
      c.width = el.clientWidth;
      c.height = el.clientHeight;
      fit();
      return;
    }
    const g = c.getContext("2d")!;
    const { zoom, ox, oy } = view.current;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = "#3a3a3a";
    g.fillRect(0, 0, c.width, c.height);
    g.setTransform(zoom, 0, 0, zoom, ox, oy);
    if (img) g.drawImage(img, 0, 0, W, H);
    const lw = 1.5 / zoom;
    g.lineWidth = lw;
    g.strokeStyle = "#22d3ee";
    for (const [x, y, r] of data.balls) {
      g.beginPath();
      g.arc(x, y, r, 0, Math.PI * 2);
      g.stroke();
    }
    data.voids.forEach((poly, i) => {
      g.beginPath();
      poly.forEach((p, j) => (j ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
      g.closePath();
      g.fillStyle = i === sel ? "rgba(250,204,21,0.45)" : "rgba(239,68,68,0.25)";
      g.fill();
      g.strokeStyle = i === sel ? "#facc15" : "#ef4444";
      g.lineWidth = 2 / zoom;
      g.stroke();
    });
    if (draft) {
      g.beginPath();
      [...draft, ...(hover ? [hover] : [])].forEach((p, j) => (j ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
      g.strokeStyle = "#facc15";
      g.lineWidth = 2 / zoom;
      g.setLineDash([6 / zoom, 4 / zoom]);
      g.stroke();
      g.setLineDash([]);
      for (const p of draft) {
        g.beginPath();
        g.arc(p[0], p[1], 3 / zoom, 0, Math.PI * 2);
        g.fillStyle = "#facc15";
        g.fill();
      }
    }
  });

  const toImg = (e: { clientX: number; clientY: number }) => {
    const b = canvas.current!.getBoundingClientRect();
    const { zoom, ox, oy } = view.current;
    return [(e.clientX - b.left - ox) / zoom, (e.clientY - b.top - oy) / zoom];
  };
  const update = (d: AnnotationData) => { setData(d); setDirty(true); setMsg(""); };

  const inside = (p: number[], poly: number[][]) => {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) c = !c;
    }
    return c;
  };
  const centroid = (poly: number[][]) => [poly.reduce((s, p) => s + p[0], 0) / poly.length, poly.reduce((s, p) => s + p[1], 0) / poly.length];

  const finishPolygon = () => {
    if (!draft || !data) return;
    const pts = draft.filter((p, i) => i === 0 || Math.hypot(p[0] - draft[i - 1][0], p[1] - draft[i - 1][1]) > 0.5);
    if (pts.length >= 3) update({ ...data, voids: [...data.voids, pts.map((p) => [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10])] });
    setDraft(null);
    setHover(null);
  };
  const removeSelected = () => {
    if (sel === null || !data) return;
    update({ ...data, voids: data.voids.filter((_, i) => i !== sel) });
    setSel(null);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT" || (e.target as HTMLElement)?.tagName === "TEXTAREA") return;
      if (e.key === "Delete" || e.key === "Backspace") removeSelected();
      if (e.key === "Escape") { setDraft(null); setSel(null); }
      if (e.key === "Enter") finishPolygon();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const onDown = (e: React.MouseEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, ox: view.current.ox, oy: view.current.oy, moved: false };
  };
  const onMove = (e: React.MouseEvent) => {
    const d = drag.current;
    if (d && (e.buttons & 1 || e.buttons & 4)) {
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (Math.abs(dx) + Math.abs(dy) > 4 && (tool !== "polygon" || e.buttons & 4 || e.shiftKey)) {
        d.moved = true;
        view.current = { ...view.current, ox: d.ox + dx, oy: d.oy + dy };
        redraw((n) => n + 1);
      }
    }
    if (draft) setHover(toImg(e));
  };
  const onUp = (e: React.MouseEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!data || !edit || (d && d.moved) || e.button !== 0) return;
    const p = toImg(e);
    if (tool === "polygon") setDraft([...(draft || []), p]);
    else if (tool === "select") {
      const i = data.voids.findIndex((poly) => inside(p, poly));
      setSel(i >= 0 ? i : null);
    } else if (tool === "erase") {
      const ball = data.balls.find(([x, y, r]) => Math.hypot(p[0] - x, p[1] - y) <= r);
      if (ball) {
        const [x, y, r] = ball;
        update({ ...data, voids: data.voids.filter((poly) => { const c = centroid(poly); return Math.hypot(c[0] - x, c[1] - y) > r; }) });
      }
    }
  };
  const onWheel = (e: React.WheelEvent) => {
    const b = canvas.current!.getBoundingClientRect();
    const mx = e.clientX - b.left, my = e.clientY - b.top;
    const v = view.current;
    const z = Math.min(40, Math.max(0.05, v.zoom * (e.deltaY < 0 ? 1.2 : 1 / 1.2)));
    view.current = { zoom: z, ox: mx - ((mx - v.ox) * z) / v.zoom, oy: my - ((my - v.oy) * z) / v.zoom };
    redraw((n) => n + 1);
  };

  const save = async () => {
    if (!data) return;
    try {
      await send("PUT", `/api/runs/${runId}/annotation`, { module_id: "void", balls: data.balls, voids: data.voids, note });
      setDirty(false);
      setErr(null);
      setMsg(t("ui.saved"));
      reloadInfo();
    } catch (e) {
      setErr(e);
    }
  };

  if (!detail || !info) return <Layout title={t("ui.annot.title")}><ErrorBox error={error || infoError} /></Layout>;
  return (
    <Layout full title={`${t("ui.annot.title")}：${detail.run.file_name}`}
      actions={<>
        <Link className="btn" to={`/runs/${runId}`}>{t("ui.back")}</Link>
        {edit && <button className="btn primary" disabled={!dirty} onClick={save}>{t("ui.save")}</button>}
      </>}>
      <div className="review-layout">
        <div style={{ position: "relative", minHeight: 0 }}>
          <div className="viewer-tools no-print"><div className="panel">
            {edit && (["polygon", "select", "erase"] as Tool[]).map((k) => (
              <button key={k} className={`btn small ${tool === k ? "primary" : ""}`} onClick={() => { setTool(k); setDraft(null); }}>{t(`ui.annot.tool.${k}`)}</button>
            ))}
            {edit && sel !== null && <button className="btn small danger" onClick={removeSelected}>{t("ui.delete")}</button>}
            {draft && <button className="btn small" onClick={finishPolygon}>{t("ui.annot.finish")}</button>}
            <button className="btn small" onClick={fit}>{t("ui.annot.fit")}</button>
          </div></div>
          <div ref={wrap} style={{ position: "absolute", inset: 0 }}>
            <canvas ref={canvas} style={{ display: "block", cursor: tool === "polygon" ? "crosshair" : "default" }}
              onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp} onWheel={onWheel}
              onDoubleClick={() => tool === "polygon" && finishPolygon()} onContextMenu={(e) => e.preventDefault()} />
          </div>
        </div>
        <aside className="side">
          <div className="side-body stack">
            <div className="muted">{t("ui.annot.hint")}</div>
            <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t(`ui.annot.help.${tool}`)}</div>
            <dl className="kv">
              <dt>{t("ui.annot.balls")}</dt><dd>{data?.balls.length ?? 0}</dd>
              <dt>{t("ui.annot.voids")}</dt><dd>{data?.voids.length ?? 0}</dd>
              <dt>{t("ui.annot.source")}</dt>
              <dd>{info.current ? `${info.current.actor}　${fmtTime(info.current.created_at)}` : t("ui.annot.from_result")}</dd>
              <dt>{t("ui.annot.history")}</dt><dd>{info.history_count}</dd>
            </dl>
            {info.current?.note && <div className="muted">{info.current.note}</div>}
            {edit && (
              <>
                <label className="field">{t("ui.annot.note")}
                  <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
                </label>
                <div className="row">
                  <button className="btn small" onClick={() => { update(info.base); setSel(null); }}>{t("ui.annot.reset")}</button>
                  <span className="spacer" />
                  {msg && <span className="muted">{msg}</span>}
                </div>
              </>
            )}
            {dirty && <div className="alert info">{t("ui.annot.unsaved")}</div>}
            <ErrorBox error={err} />
          </div>
        </aside>
      </div>
    </Layout>
  );
}
