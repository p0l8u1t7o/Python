import { useEffect, useMemo, useRef, useState } from "react";
import { send } from "../api/client";
import type { CornerPosition, RunDetail } from "../api/types";
import { useApp } from "../app/context";
import { ImageViewer, buildShapes, type View, type ViewerTool } from "./ImageViewer";
import { ErrorBox, fmt } from "./ui";

const POSITIONS: CornerPosition[] = ["top_left", "top_right", "bottom_left", "bottom_right"];
// 角落位置 → 晶片所在方向 (+1 = 角點右方／下方)
const DIE_SIDE: Record<CornerPosition, [number, number]> = {
  top_left: [1, 1], top_right: [-1, 1], bottom_left: [1, -1], bottom_right: [-1, -1],
};
const COLOR = "#38bdf8";
const HIT_PX = 12;

type Corner = { position: CornerPosition; x: number; y: number; angle_deg: number };

// 本影像手動指定晶片角點 (PLAN-006 第 3.3 節)：拖曳角點、點選影像移動角點、拖曳邊緣末端的把手旋轉。
// 只影響圖組計算，單張分析結果不變；手動角點只新增、可改回自動，並留下稽核紀錄。
export function DieCornerDialog({ data, onClose, onSaved }: { data: RunDetail; onClose: () => void; onSaved: () => void }) {
  const { t, modules } = useApp();
  const { run, result } = data;
  const W = result.image.width, H = result.image.height;
  const auto = result.die_corner;
  const autoCorner: Corner | null = auto?.found && auto.position && auto.x != null && auto.y != null
    ? { position: auto.position, x: auto.x, y: auto.y, angle_deg: auto.angle_deg ?? 0 } : null;
  const [c, setC] = useState<Corner>(() => data.manual_corner
    ? { position: data.manual_corner.position, x: data.manual_corner.x, y: data.manual_corner.y, angle_deg: data.manual_corner.angle_deg }
    : autoCorner || { position: "top_left", x: W / 2, y: H / 2, angle_deg: 0 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const drag = useRef<"corner" | "rotate" | null>(null);

  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose, busy]);

  const shapes = useMemo(() => buildShapes(result, modules, 10, t("ui.group")), [result, modules, t]);
  const L = 0.25 * Math.min(W, H);
  const geom = (k: Corner) => {
    const a = (k.angle_deg * Math.PI) / 180;
    const [sx, sy] = DIE_SIDE[k.position];
    const hx = [k.x + sx * L * Math.cos(a), k.y + sx * L * Math.sin(a)];       // 沿水平邊
    const vy = [k.x - sy * L * Math.sin(a), k.y + sy * L * Math.cos(a)];       // 沿垂直邊
    return { hx, vy };
  };

  const tool: ViewerTool = useMemo(() => {
    const near = (x: number, y: number, px: number, py: number, view: View) => Math.hypot(x - px, y - py) * view.zoom <= HIT_PX;
    const setAngleFrom = (x: number, y: number) => setC((k) => {
      const [sx] = DIE_SIDE[k.position];
      const deg = (Math.atan2((y - k.y) * sx, (x - k.x) * sx) * 180) / Math.PI;
      return { ...k, angle_deg: Math.max(-10, Math.min(10, Math.round(deg * 1000) / 1000)) };
    });
    return {
      cursor: "crosshair",
      down: (x, y, _e, view) => {
        const { hx } = geom(c);
        if (near(x, y, hx[0], hx[1], view)) drag.current = "rotate";
        else {
          drag.current = "corner";
          if (!near(x, y, c.x, c.y, view)) setC((k) => ({ ...k, x: clamp(x, 0, W), y: clamp(y, 0, H) }));
        }
        return true;
      },
      move: (x, y) => {
        if (drag.current === "corner") setC((k) => ({ ...k, x: clamp(x, 0, W), y: clamp(y, 0, H) }));
        else if (drag.current === "rotate") setAngleFrom(x, y);
      },
      up: () => { drag.current = null; },
      paint: (g, view) => {
        const P = (x: number, y: number) => [view.ox + x * view.zoom, view.oy + y * view.zoom];
        const { hx, vy } = geom(c);
        const [cx, cy] = P(c.x, c.y);
        g.save();
        g.lineWidth = 2.5;
        g.strokeStyle = COLOR;
        for (const e of [hx, vy]) {
          const [ex, ey] = P(e[0], e[1]);
          g.beginPath(); g.moveTo(cx, cy); g.lineTo(ex, ey); g.stroke();
        }
        g.beginPath(); g.arc(cx, cy, 9, 0, Math.PI * 2); g.stroke();
        g.beginPath(); g.moveTo(cx - 16, cy); g.lineTo(cx + 16, cy); g.moveTo(cx, cy - 16); g.lineTo(cx, cy + 16); g.stroke();
        const [rx, ry] = P(hx[0], hx[1]);
        g.fillStyle = "#ffffff"; g.strokeStyle = "#111"; g.lineWidth = 1;
        g.beginPath(); g.arc(rx, ry, 7, 0, Math.PI * 2); g.fill(); g.stroke();
        g.restore();
      },
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c, W, H]);

  const save = async (clear: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await send("PUT", `/api/runs/${run.id}/corner`, clear ? { clear: true } : c);
      onSaved();
      onClose();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="card modal modal-wide" role="dialog" aria-label={t("ui.corner.manual_title")}>
        <div className="card-h">
          <h2>{t("ui.corner.manual_title")}：{run.file_name}</h2>
          <span className="muted">{t(data.manual_corner ? "ui.corner.current_manual" : "ui.corner.current_auto")}</span>
        </div>
        <div className="card-b stack">
          <div className="muted">{t("ui.corner.manual_hint")}</div>
          <div className="image-regions-layout">
            <div style={{ height: "60vh", position: "relative" }}>
              <ImageViewer src={`/api/runs/${run.id}/image?max_size=4096`} width={W} height={H} shapes={shapes}
                hiddenLayers={new Set()} opacity={0.7} brightness={1} contrast={1} tool={tool} />
            </div>
            <div className="stack">
              <label className="field">{t("ui.corner.position")}
                <select value={c.position} onChange={(e) => setC({ ...c, position: e.target.value as CornerPosition })}>
                  {POSITIONS.map((p) => <option key={p} value={p}>{t(`ui.corner.pos_${p}`)}</option>)}
                </select>
              </label>
              <label className="field">X (px)
                <input type="number" step="0.5" value={round1(c.x)} onChange={(e) => setC({ ...c, x: clamp(+e.target.value, 0, W) })} />
              </label>
              <label className="field">Y (px)
                <input type="number" step="0.5" value={round1(c.y)} onChange={(e) => setC({ ...c, y: clamp(+e.target.value, 0, H) })} />
              </label>
              <label className="field">{t("ui.corner.angle")} (°)
                <input type="number" step="0.01" min={-10} max={10} value={c.angle_deg} onChange={(e) => setC({ ...c, angle_deg: clamp(+e.target.value, -10, 10) })} />
              </label>
              {autoCorner ? (
                <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>
                  {t("ui.corner.auto_result")}：{t(`ui.corner.pos_${autoCorner.position}`)}（{fmt(autoCorner.x, 1)}, {fmt(autoCorner.y, 1)}）
                  <div><button className="btn small" onClick={() => setC(autoCorner)}>{t("ui.corner.use_auto")}</button></div>
                </div>
              ) : (
                <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.corner.auto_result")}：{t(`corner.reason.${auto?.reason}`, auto?.reason || "–")}</div>
              )}
              <div className="muted" style={{ fontSize: "var(--fs-xs)" }}>{t("ui.corner.manual_note")}</div>
            </div>
          </div>
          <ErrorBox error={error} />
        </div>
        <div className="card-b row" style={{ justifyContent: "flex-end", borderTop: "1px solid var(--border)" }}>
          {data.manual_corner && <button className="btn" disabled={busy} onClick={() => save(true)}>{t("ui.corner.clear_manual")}</button>}
          <span className="spacer" />
          <button className="btn" disabled={busy} onClick={onClose}>{t("ui.cancel")}</button>
          <button className="btn primary" disabled={busy} onClick={() => save(false)}>{t("ui.save")}</button>
        </div>
      </div>
    </div>
  );
}

function clamp(v: number, lo: number, hi: number) {
  return Number.isFinite(v) ? Math.min(Math.max(v, lo), hi) : lo;
}

function round1(v: number) {
  return Math.round(v * 10) / 10;
}
