// 相機／感測器模擬畫面（2D 繪製的示意影像，不是實拍）
import { profile, inTol } from './spec.js';

const W = 612, H = 512, FONT = '"Noto Sans TC","Microsoft JhengHei",sans-serif';
const rng = seed => () => (seed = (seed * 16807) % 2147483647) / 2147483647;
// 厚度偏差色階：偏薄偏藍、中心綠、偏厚偏紅
const hue = f => `hsl(${f < 0 ? 150 + 60 * -f : 150 - 150 * f},85%,55%)`;
export const TITLES = {
  idle: '待命 · 等待工件', A: '通道 A · 4K 線掃展開（R 暗場／G 明場／B 同軸）', B: '通道 B · 5MP 遠心剪影 0.5×',
  C: '通道 C · 5MP 口部端面 1×', CF: 'ST2 · 上下共焦差分測厚（螺旋掃描）', result: '判定結果',
};

export function createCameraSim(canvas, s, m, scenario) {
  canvas.width = W; canvas.height = H; const g = canvas.getContext('2d');
  // 展開圖：x = 圓周角、y = 軸向；三個照明通道各一張
  const strips = ['R', 'G', 'B'].map((ch, k) => {
    const c = document.createElement('canvas'); c.width = 560; c.height = 118; const x = c.getContext('2d'), r = rng(11 + k * 7);
    const base = ch === 'R' ? 26 : ch === 'G' ? 150 : 118;
    for (let i = 0; i < 560; i++) { const v = base + (r() - 0.5) * (ch === 'R' ? 22 : 34) + 10 * Math.sin(i / 89 + k); x.fillStyle = `rgb(${v},${v},${v})`; x.fillRect(i, 0, 1, 118); }
    x.fillStyle = 'rgba(0,0,0,.55)'; x.fillRect(0, 0, 560, 9);                                     // 夾持帶遮蔽
    for (const d of m.defects) {
      const px = d.theta / 360 * 560, py = 118 - d.y * 118, len = d.len / s.len * 118;
      x.strokeStyle = ch === 'R' ? '#fff' : ch === 'G' ? 'rgba(40,40,40,.8)' : 'rgba(90,90,90,.5)'; x.lineWidth = ch === 'R' ? 2.2 : 1.4; x.beginPath(); x.moveTo(px, py - len / 2); x.lineTo(px + 1.5, py + len / 2); x.stroke();
    }
    return c;
  });
  const text = (t, x, y, color = '#d8e9f1', size = 15, align = 'left') => { g.font = `${size}px ${FONT}`; g.fillStyle = color; g.textAlign = align; g.fillText(t, x, y); };
  const tol = (v, range, d = 3) => `${v.toFixed(d)}  ${inTol(v, range) ? '✓' : '✗'}`, col = (v, range) => inTol(v, range) ? '#7fe0b4' : '#ff8d80';

  function drawA(S) {
    g.fillStyle = '#05080c'; g.fillRect(0, 0, W, H);
    const w = Math.round(560 * S.scanA);
    ['R 暗場 15°（拉傷、刮痕）', 'G 明場 60°（凹陷、壓傷）', 'B 同軸（污染、變色）'].forEach((name, k) => {
      const y = 40 + k * 152; text(name, 26, y - 8, ['#ff8d80', '#7fe0b4', '#8fbfff'][k], 14);
      g.fillStyle = '#0d141b'; g.fillRect(26, y, 560, 118); if (w > 0) g.drawImage(strips[k], 0, 0, w, 118, 26, y, w, 118);
      if (S.scanA < 1 && w > 0) { g.fillStyle = '#ffe27a'; g.fillRect(26 + w, y, 1.5, 118); }
      if (S.scanA >= 1) for (const d of m.defects) { const px = 26 + d.theta / 360 * 560, py = y + 118 - d.y * 118; g.strokeStyle = '#ff4d4d'; g.lineWidth = 1.5; g.strokeRect(px - 9, py - 16, 20, 32); if (k === 0) text(`${d.type} ${d.len.toFixed(2)} mm · ${d.conf}`, px + 16, py - 4, '#ff8d80', 14); }
    });
    text(`θ ${(S.scanA * 360).toFixed(0)}° · ${Math.round(S.scanA * 3300)} / 3300 行`, W - 26, 22, '#9fb6c4', 14, 'right');
    text('0°', 26, H - 8, '#6f8394', 13); text('360°', 586, H - 8, '#6f8394', 13, 'right');
  }
  function drawB(S) {
    g.fillStyle = '#d9f5d3'; g.fillRect(0, 0, W, H);
    const k = 30, cx = W / 2, top = 70, P = profile(s), R = Math.max(...P.map(p => p[0]));
    g.fillStyle = '#060606';
    g.beginPath(); P.filter((p, i) => i <= P.findIndex(q => q[1] === s.len)).forEach(([r, y], i) => { const X = cx + r * k, Y = top + (s.len - y) * k; i ? g.lineTo(X, Y) : g.moveTo(X, Y); });
    [...P.filter((p, i) => i <= P.findIndex(q => q[1] === s.len))].reverse().forEach(([r, y]) => g.lineTo(cx - r * k, top + (s.len - y) * k)); g.closePath(); g.fill();
    g.fillRect(cx - (s.gripR + 2.8) * k, top - 60, 2.6 * k, 60 + 1.5 * k); g.fillRect(cx + (s.gripR + 0.2) * k, top - 60, 2.6 * k, 60 + 1.5 * k); g.fillRect(cx - 11 * k / 2, 0, 11 * k, top - 50);
    if (!S.shotB) return;
    const i = S.shotB - 1, yMid = top + s.len * k * 0.55, c = s.criteria;
    g.strokeStyle = '#0a62ff'; g.lineWidth = 1.5; g.setLineDash([5, 4]);
    g.beginPath(); g.moveTo(cx - R * k - 30, yMid); g.lineTo(cx + R * k + 30, yMid); g.moveTo(cx + R * k + 46, top); g.lineTo(cx + R * k + 46, top + s.len * k); g.stroke(); g.setLineDash([]);
    g.fillStyle = 'rgba(8,16,24,.82)'; g.fillRect(14, H - 118, 300, 104);
    text(`θ = ${i * 90}°（${S.shotB} / 4）`, 26, H - 96, '#ffe27a', 13);
    text(`外徑 OD   ${tol(m.od[i], c.od)}`, 26, H - 74, col(m.od[i], c.od)); text(`全長 L    ${tol(m.length, c.length)}`, 26, H - 54, col(m.length, c.length));
    text(`直線度   ${m.straightness.toFixed(3)}` + (m.flare ? `　喇叭 ${m.flare.toFixed(1)}° ≤ ${c.flare}°` : ''), 26, H - 34, '#7fe0b4');
    text('次圖元邊緣擬合 · 6.9 µm/px', W - 20, H - 20, '#25482a', 14, 'right');
  }
  function drawC(S) {
    g.fillStyle = '#0a0c0f'; g.fillRect(0, 0, W, H);
    const k = 66, cx = W / 2, cy = H / 2 - 10, ro = (s.neck ? s.neck.od / 2 : s.od / 2 + (s.flare ? s.flare.dr : 0)) * k, ri = s.bore / 2 * k + (s.flare ? s.flare.dr * k : 0);
    const grad = g.createRadialGradient(cx, cy, ri, cx, cy, ro); grad.addColorStop(0, '#e9edf0'); grad.addColorStop(0.5, '#fafcfd'); grad.addColorStop(1, '#cfd6dc');
    g.fillStyle = grad; g.beginPath(); g.arc(cx, cy, ro, 0, 7); g.arc(cx, cy, ri, 0, 7, true); g.fill('evenodd');
    g.fillStyle = '#16191d'; g.beginPath(); g.arc(cx, cy, ri, 0, 7); g.fill();
    g.fillStyle = '#3a3126'; for (let i = 0; i < 3; i++) { const a = Math.PI / 2 + i * 2.0944; g.save(); g.translate(cx + (ro + 0.9 * k) * Math.cos(a), cy + (ro + 0.9 * k) * Math.sin(a)); g.rotate(a); g.fillRect(-0.85 * k, -0.8 * k, 1.7 * k, 1.6 * k); g.restore(); }
    if (!S.shown) return;
    g.strokeStyle = '#38d6ff'; g.lineWidth = 1.5; g.setLineDash([6, 4]); for (const r of [ro, ri]) { g.beginPath(); g.arc(cx, cy, r, 0, 7); g.stroke(); } g.setLineDash([]);
    g.fillStyle = 'rgba(8,16,24,.82)'; g.fillRect(14, H - 96, 330, 82); const c = s.criteria;
    text(`口部內徑 ID   ${tol(m.idLip, c.idLip)}`, 26, H - 72, col(m.idLip, c.idLip)); text(`口部壁厚 (OD−ID)/2   ${tol(m.wallLip, c.wallLip)}`, 26, H - 52, col(m.wallLip, c.wallLip));
    text('真圓度 0.004 · 毛邊／缺口 無', 26, H - 32, '#7fe0b4');
    text('最小平方圓擬合 · 3.45 µm/px', W - 20, 24, '#9fb6c4', 14, 'right');
  }
  function drawCF(S) {
    g.fillStyle = '#080b10'; g.fillRect(0, 0, W, H);
    const n = S.scanNo || 0, u = S.spiral[n], cx = 200, cy = H / 2 + 6, k = 150 / (s.ringBore / 2), N = 1800, r = rng(5 + n), err = scenario === 'ERR', c = s.criteria;
    g.strokeStyle = '#2b3946'; g.lineWidth = 1; for (const rr of [s.ringBore / 2, s.hole / 2].filter(Boolean)) { g.beginPath(); g.arc(cx, cy, rr * k, 0, 7); g.stroke(); }
    if (s.hole) { g.fillStyle = '#11161c'; g.beginPath(); g.arc(cx, cy, s.hole / 2 * k, 0, 7); g.fill(); text('底孔', cx, cy + 4, '#566879', 13, 'center'); }
    const nominal = (c.thk[0] + c.thk[1]) / 2, shift = m.thkMean === null ? 0 : m.thkMean - nominal;
    for (let i = 0; i < N * u; i++) {
      const q = i / N, rad = s.scan.r0 + (s.scan.r1 - s.scan.r0) * q, th = q * s.scan.rev * Math.PI * 2, v = r();
      const bad = err && Math.cos(th - 0.6) > 0.25 && v < 0.85;
      const dev = shift + 0.006 * Math.sin(th + 0.4) * rad / s.scan.r1 + (v - 0.5) * 0.002, f = Math.max(-1, Math.min(1, dev / ((c.thk[1] - c.thk[0]) / 2)));
      g.fillStyle = bad ? '#56616b' : hue(f);
      g.fillRect(cx + rad * k * Math.cos(th) - 1.6, cy + rad * k * Math.sin(th) - 1.6, 3.2, 3.2);
    }
    text(`掃描 ${n + 1}${n ? '（重測）' : ''} · ${(u * s.scan.rev).toFixed(1)} / ${s.scan.rev} 圈 · ${Math.round(u * 18000)} 點`, 20, 26, '#9fb6c4', 14);
    text('t = K − d_up − d_dn', 20, H - 14, '#b79cff', 14);
    const X = 392; text('底厚', X, 70, '#9fb6c4', 14);
    if (u >= 1) {
      if (err) { text('有效點 62 %', X, 100, '#ffb020', 15); text('訊號強度不足', X, 124, '#ffb020', 13); text(n ? '→ ERR，退回人工' : '→ 重新落座重測', X, 148, '#ffb020', 13); }
      else { text(`平均 ${tol(m.thkMean, c.thk)}`, X, 100, col(m.thkMean, c.thk), 14); text(`最小 ${m.thkMin.toFixed(3)}`, X, 124, '#d8e9f1'); text(`最大 ${m.thkMax.toFixed(3)}`, X, 146, '#d8e9f1'); text(`TIR ${m.thkTir.toFixed(3)} ≤ ${c.tir}`, X, 168, m.thkTir <= c.tir ? '#7fe0b4' : '#ff8d80'); text(`平整度 ${m.flatness.toFixed(4)}`, X, 190, '#7fe0b4'); text('（規格待客戶定義）', X, 208, '#6f8394', 13); }
    } else text('取樣中…', X, 100, '#d8e9f1');
    const gx = X, gy = H - 150; text(`${c.thk[0]}`, gx, gy + 118, '#6f8394', 13); text(`${c.thk[1]} mm`, gx + 150, gy + 118, '#6f8394', 13, 'right');
    for (let i = 0; i < 150; i++) { const f = i / 149 * 2 - 1; g.fillStyle = hue(f); g.fillRect(gx + i, gy + 90, 1, 14); }
  }
  function drawResult() {
    g.fillStyle = '#0a121a'; g.fillRect(0, 0, W, H);
    const ok = m.result === 'OK', c = s.criteria, color = ok ? '#3dd68c' : m.result === 'ERR' ? '#ffb020' : '#ff4d4d';
    text(m.result, 30, 78, color, 58); text(ok ? '全部項目在規格內 → OK 托盤' : m.code, 32, 112, color, 15);
    const rows = [['外徑 OD（4 方位）', m.od.map(v => v.toFixed(3)).join(' / '), m.od.every(v => inTol(v, c.od))], ['全長 L', m.length.toFixed(3), inTol(m.length, c.length)], ['口部內徑', m.idLip.toFixed(3), inTol(m.idLip, c.idLip)], ['口部壁厚', m.wallLip.toFixed(3), inTol(m.wallLip, c.wallLip)],
      ['外觀缺陷', m.defects.length ? `${m.defects.length} 處（${m.defects[0].type}）` : '0 處', !m.defects.length], ['底厚平均', m.thkMean === null ? '無效' : m.thkMean.toFixed(3), m.thkMean !== null && inTol(m.thkMean, c.thk)], ['有效點數', `${m.valid} / 18000`, m.invalid === 0]];
    rows.forEach(([k, v, good], i) => { const y = 160 + i * 36; g.fillStyle = i % 2 ? '#0e1822' : '#111d29'; g.fillRect(24, y - 22, W - 48, 34); text(k, 38, y, '#a9c0d2', 14); text(v, W - 80, y, '#e6edf3', 14, 'right'); text(good ? '✓' : '✗', W - 46, y, good ? '#3dd68c' : '#ff6b5e', 16, 'center'); });
    text(`配方 ${s.recipe} · 模型 shell-defect-v1.3 · 模擬值，非實測`, 30, H - 22, '#6f8394', 14);
  }
  function drawIdle() {
    g.fillStyle = '#0a121a'; g.fillRect(0, 0, W, H); text(s.name, 30, 70, '#d8e9f1', 26); text(`配方 ${s.recipe} · 環座 ${s.ring} · 上感測器 ${s.upper}`, 30, 104, '#9fb6c4', 14);
    text(s.note, 30, 134, '#ffb020', 13); text('等待工件進入取像位置', 30, H - 30, '#6f8394', 13);
    const P = profile(s), k = Math.min(24, 300 / s.len), ox = W / 2, oy = 190;
    g.fillStyle = '#c9d1d9'; for (const sign of [1, -1]) { g.beginPath(); P.forEach(([r, y], i) => { const X = ox + sign * r * k, Y = oy + (s.len - y) * k; i ? g.lineTo(X, Y) : g.moveTo(X, Y); }); g.closePath(); g.fill(); }
  }
  return {
    draw(S, completed) {
      const mode = S.pip;
      if (mode === 'A') drawA(S); else if (mode === 'B') drawB(S); else if (mode === 'C') drawC({ shown: completed.has('shotC') || S.optic === 'C' }); else if (mode === 'CF') drawCF(S); else if (mode === 'result') drawResult(); else drawIdle();
      return mode;
    },
  };
}
