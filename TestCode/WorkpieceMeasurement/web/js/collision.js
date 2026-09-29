// 干涉檢查用的距離計算（純數學）。移動件以表面取樣點表示，對固定件算最小間隙。
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

export function distPoint(p, b) {
  if (b.kind === 'box') { let s = 0; for (let i = 0; i < 3; i++) { const d = Math.max(b.min[i] - p[i], 0, p[i] - b.max[i]); s += d * d; } return Math.sqrt(s); }
  // 有限圓柱：軸向與徑向分開算
  const ax = sub(b.p1, b.p0), len = Math.hypot(...ax), n = ax.map(v => v / len), v = sub(p, b.p0), h = dot(v, n);
  const radial = Math.sqrt(Math.max(0, dot(v, v) - h * h)), dr = Math.max(0, radial - b.r), dh = Math.max(0, -h, h - len);
  return Math.hypot(dr, dh);
}
export function samples(b, step = 2) {
  const P = [];
  if (b.kind === 'box') {
    const n = [0, 1, 2].map(i => Math.max(1, Math.ceil((b.max[i] - b.min[i]) / step)));
    for (let i = 0; i <= n[0]; i++) for (let j = 0; j <= n[1]; j++) for (let k = 0; k <= n[2]; k++) {
      if (i && j && k && i < n[0] && j < n[1] && k < n[2]) continue;      // 只取表面
      P.push([b.min[0] + (b.max[0] - b.min[0]) * i / n[0], b.min[1] + (b.max[1] - b.min[1]) * j / n[1], b.min[2] + (b.max[2] - b.min[2]) * k / n[2]]);
    }
    return P;
  }
  // 只處理鉛直圓柱（工件）
  const h = b.p1[1] - b.p0[1], nh = Math.max(1, Math.ceil(h / step));
  for (let j = 0; j <= nh; j++) for (let a = 0; a < 24; a++) P.push([b.p0[0] + b.r * Math.cos(a * Math.PI / 12), b.p0[1] + h * j / nh, b.p0[2] + b.r * Math.sin(a * Math.PI / 12)]);
  P.push([b.p0[0], b.p0[1], b.p0[2]], [b.p1[0], b.p1[1], b.p1[2]]);
  return P;
}
export function clearance(moving, fixed, step = 2) {
  let best = { d: Infinity };
  for (const m of moving) for (const p of samples(m, step)) for (const f of fixed) { const d = distPoint(p, f); if (d < best.d) best = { d, moving: m.id, fixed: f.id, at: p.map(v => +v.toFixed(2)) }; }
  return best;
}
