// 筆刷／橡皮擦標註 (PLAN-005 第 4 節)：在遮罩上運算後轉回多邊形，標註格式維持多邊形
// 純運算 (不依賴 canvas)，座標皆為影像像素。

export type Pt = [number, number];
type Poly = number[][];

const MAX_GRID = 1400;          // 遮罩邊長上限 (格)；區域較大時降低解析度
const SIMPLIFY_PX = 0.3;        // 多邊形簡化容許誤差 (影像像素)

interface Grid { x0: number; y0: number; s: number; w: number; h: number; m: Uint8Array }

function bboxOf(pts: number[][], pad = 0): [number, number, number, number] {
  let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
  for (const p of pts) { a = Math.min(a, p[0]); b = Math.min(b, p[1]); c = Math.max(c, p[0]); d = Math.max(d, p[1]); }
  return [a - pad, b - pad, c + pad, d + pad];
}
const overlap = (p: number[], q: number[]) => p[0] <= q[2] && q[0] <= p[2] && p[1] <= q[3] && q[1] <= p[3];

function makeGrid(box: number[]): Grid {
  const side = Math.max(box[2] - box[0], box[3] - box[1], 1);
  const s = Math.min(4, MAX_GRID / side);                      // 每影像像素幾格
  const x0 = Math.floor(box[0]) - 2, y0 = Math.floor(box[1]) - 2;
  const w = Math.ceil((box[2] - x0 + 2) * s), h = Math.ceil((box[3] - y0 + 2) * s);
  return { x0, y0, s, w, h, m: new Uint8Array(w * h) };
}

// 多邊形填滿 (掃描線，格中心取樣)
function fillPoly(g: Grid, poly: Poly, val: number) {
  const P = poly.map((p) => [(p[0] - g.x0) * g.s, (p[1] - g.y0) * g.s]);
  const [, ya, , yb] = bboxOf(P);
  for (let j = Math.max(0, Math.floor(ya)); j <= Math.min(g.h - 1, Math.ceil(yb)); j++) {
    const yc = j + 0.5, xs: number[] = [];
    for (let i = 0, k = P.length - 1; i < P.length; k = i++) {
      const [x1, y1] = P[i], [x2, y2] = P[k];
      if ((y1 > yc) !== (y2 > yc)) xs.push(x1 + ((yc - y1) * (x2 - x1)) / (y2 - y1));
    }
    xs.sort((a, b) => a - b);
    for (let n = 0; n + 1 < xs.length; n += 2) {
      const a = Math.max(0, Math.ceil(xs[n] - 0.5)), b = Math.min(g.w - 1, Math.floor(xs[n + 1] - 0.5));
      for (let i = a; i <= b; i++) g.m[j * g.w + i] = val;
    }
  }
}

// 筆畫 (折線加圓頭，半徑 r)
function fillStroke(g: Grid, stroke: Pt[], r: number, val: number) {
  const S = stroke.map((p) => [(p[0] - g.x0) * g.s, (p[1] - g.y0) * g.s]);
  const R = r * g.s, R2 = R * R;
  const segs = S.length === 1 ? [[S[0], S[0]]] : S.slice(1).map((p, i) => [S[i], p]);
  for (const [a, b] of segs) {
    const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
    const i0 = Math.max(0, Math.floor(Math.min(a[0], b[0]) - R)), i1 = Math.min(g.w - 1, Math.ceil(Math.max(a[0], b[0]) + R));
    const j0 = Math.max(0, Math.floor(Math.min(a[1], b[1]) - R)), j1 = Math.min(g.h - 1, Math.ceil(Math.max(a[1], b[1]) + R));
    for (let j = j0; j <= j1; j++) {
      for (let i = i0; i <= i1; i++) {
        const px = i + 0.5, py = j + 0.5;
        const u = L ? Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / L)) : 0;
        const ex = px - (a[0] + u * dx), ey = py - (a[1] + u * dy);
        if (ex * ex + ey * ey <= R2) g.m[j * g.w + i] = val;
      }
    }
  }
}

// 外輪廓追蹤：沿格邊行走 (前景在左側)，得到與遮罩面積完全相同的多邊形；孔洞輪廓捨棄 (格式不支援孔洞)
function traceOuter(g: Grid): Poly[] {
  const { w, h, m } = g;
  const at = (i: number, j: number) => (i >= 0 && j >= 0 && i < w && j < h ? m[j * w + i] : 0);
  // 有向邊：以起點為鍵；方向 0 右、1 下、2 左、3 上 (沿順時針繞前景格)
  const out = new Map<number, number[]>();
  const key = (x: number, y: number) => y * (w + 1) + x;
  const add = (x: number, y: number, d: number) => { const k = key(x, y); const l = out.get(k); if (l) l.push(d); else out.set(k, [d]); };
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    if (!m[j * w + i]) continue;
    if (!at(i, j - 1)) add(i, j, 0);
    if (!at(i + 1, j)) add(i + 1, j, 1);
    if (!at(i, j + 1)) add(i + 1, j + 1, 2);
    if (!at(i - 1, j)) add(i, j + 1, 3);
  }
  const DX = [1, 0, -1, 0], DY = [0, 1, 0, -1];
  const polys: Poly[] = [];
  for (const [k0, l0] of out) {
    while (l0.length) {
      let x = k0 % (w + 1), y = Math.floor(k0 / (w + 1));
      let d = l0.pop()!;
      const pts: number[][] = [[x, y]];
      for (let guard = 0; guard < 4 * w * h + 8; guard++) {
        x += DX[d]; y += DY[d];
        const l = out.get(key(x, y));
        if (!l || !l.length) break;
        // 兩條出邊 (對角相接) 時優先右轉，使相接的區域分開
        const pref = [(d + 1) % 4, d, (d + 3) % 4];
        const nd = pref.find((q) => l.includes(q));
        if (nd === undefined) break;
        l.splice(l.indexOf(nd), 1);
        if (nd !== d) pts.push([x, y]);
        d = nd;
      }
      let area = 0;
      for (let i = 0, k = pts.length - 1; i < pts.length; k = i++) area += pts[k][0] * pts[i][1] - pts[i][0] * pts[k][1];
      if (area > 0 && pts.length >= 3)                                       // 螢幕座標下順時針 = 外輪廓
        polys.push(pts.map((p) => [g.x0 + p[0] / g.s, g.y0 + p[1] / g.s]));
    }
  }
  return polys;
}

function simplify(pts: Poly, eps: number): Poly {
  if (pts.length <= 4) return pts;
  // 封閉多邊形：以最遠的兩點拆成兩段各自簡化
  let far = 0, fd = -1;
  for (let i = 1; i < pts.length; i++) { const d = Math.hypot(pts[i][0] - pts[0][0], pts[i][1] - pts[0][1]); if (d > fd) { fd = d; far = i; } }
  const dp = (a: Poly): Poly => {
    if (a.length <= 2) return a;
    const [p, q] = [a[0], a[a.length - 1]];
    const L = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1e-9;
    let idx = 0, md = -1;
    for (let i = 1; i < a.length - 1; i++) {
      const d = Math.abs((q[0] - p[0]) * (p[1] - a[i][1]) - (p[0] - a[i][0]) * (q[1] - p[1])) / L;
      if (d > md) { md = d; idx = i; }
    }
    if (md <= eps) return [p, q];
    return [...dp(a.slice(0, idx + 1)).slice(0, -1), ...dp(a.slice(idx))];
  };
  const a = dp(pts.slice(0, far + 1)), b = dp([...pts.slice(far), pts[0]]);
  const res = [...a.slice(0, -1), ...b.slice(0, -1)];
  return res.length >= 3 ? res : pts;
}

export function polyArea(p: number[][]): number {
  let a = 0;
  for (let i = 0, k = p.length - 1; i < p.length; k = i++) a += p[k][0] * p[i][1] - p[i][0] * p[k][1];
  return Math.abs(a) / 2;
}

/**
 * 套用一筆筆刷 (add) 或橡皮擦 (erase)：與筆畫重疊的空洞在遮罩上合併或扣除後重新轉成多邊形；
 * 未碰到筆畫的空洞維持原樣。回傳新的空洞清單。
 */
export function applyStroke(voids: Poly[], stroke: Pt[], radius: number, mode: "add" | "erase"): Poly[] {
  if (!stroke.length || radius <= 0) return voids;
  const sbox = bboxOf(stroke, radius + 1);
  const cand = voids.map((v, i) => ({ v, i })).filter(({ v }) => overlap(bboxOf(v, 1), sbox));
  // 實際與筆畫重疊 (或相接) 的空洞
  const sg = makeGrid(sbox);
  fillStroke(sg, stroke, radius + 0.5 / sg.s, 1);
  const touched = cand.filter(({ v }) => {
    const t = makeGrid(sbox);
    fillPoly(t, v, 1);
    for (let n = 0; n < t.m.length; n++) if (t.m[n] && sg.m[n]) return true;
    return false;
  });
  if (mode === "erase" && !touched.length) return voids;
  const box = [sbox, ...touched.map(({ v }) => bboxOf(v, 1))].reduce((a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]);
  const g = makeGrid(box);
  for (const { v } of touched) fillPoly(g, v, 1);
  fillStroke(g, stroke, radius, mode === "add" ? 1 : 0);
  const eps = SIMPLIFY_PX;
  // 格邊輪廓呈鋸齒；取各邊中點 (較接近真實邊界) 再簡化，避免保留外角造成面積偏大
  const mid = (p: Poly) => p.map((q, i) => { const r = p[(i + 1) % p.length]; return [(q[0] + r[0]) / 2, (q[1] + r[1]) / 2]; });
  // 簡化後以形心為中心微調大小，使面積等於遮罩面積 (遮罩以格中心取樣，面積無偏差)
  const fit = (p: Poly) => {
    const q = simplify(mid(p), eps);
    const k = Math.sqrt(polyArea(p) / Math.max(polyArea(q), 1e-9));
    const cx = q.reduce((t, r) => t + r[0], 0) / q.length, cy = q.reduce((t, r) => t + r[1], 0) / q.length;
    return q.map((r) => [cx + (r[0] - cx) * k, cy + (r[1] - cy) * k]);
  };
  const fresh = traceOuter(g).map((p) => fit(p).map((q) => [Math.round(q[0] * 10) / 10, Math.round(q[1] * 10) / 10]))
    .filter((p) => polyArea(p) >= 1);
  const drop = new Set(touched.map(({ i }) => i));
  return [...voids.filter((_, i) => !drop.has(i)), ...fresh];
}
