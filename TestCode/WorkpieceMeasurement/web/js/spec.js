// 規格、配方、機台配置與模擬量測值（純資料，不依賴 three，瀏覽器與 Node 驗證腳本共用）
// 座標：X 向右（料盤 → ST1 → ST2）、Y 向上、Z 向操作者；單位 mm。

export const Y0 = 900;                       // 花崗岩平台上表面
export const X1 = 30, X2 = 215;              // ST1／ST2 旋轉中心
export const YM = Y0 + 150;                  // ST1 杯口高度（夾頭固定，工件向下延伸）
export const YA = YM - 7;                    // 通道 A／B 光軸高度
export const YS = Y0 + 136;                  // ST2 薄環座上表面
export const YT = Y0 + 88;                   // 托盤穴底
export const YC = YT + 16;                   // 走廊高度（吸附中工件底面）
export const XW = 150;                       // 背光與 ST2 平台之間的升降點
export const GRIP_H = 1.8;                   // 吸嘴中心距工件底面
export const RETRACT = 6;                    // 貼靠氣缸行程
export const PITCH = 12;
export const LIMIT = { vx: 1200, ax: 12000, vz: 400, az: 6000, vShuttle: 300, aShuttle: 3000 };

export const SPECS = {
  A: {
    id: 'A', name: '規格 A（4.2 短杯）', recipe: 'SHELL-A-0420', ring: 'RING-A-40', ringBore: 4.0,
    od: 4.805, bore: 4.28, len: 4.2, base: 0.26, hole: 2.6, rOuter: 0.38, rInner: 0.13,
    gripR: 2.4025, padR: 2.4025, upper: 'IFD2410-6', wd: 30, probeR: 14,
    scan: { r0: 1.45, r1: 1.85, rev: 5, rpm: 120 },
    criteria: { od: [4.78, 4.83], length: [4.15, 4.25], idLip: [4.26, 4.31], wallLip: [0.235, 0.285], thk: [0.221, 0.297], tir: 0.03, flat: 0.008 },
    note: '底部 Ø2.60 依圖面判讀為貫穿孔，厚度量測區為環帶（待確認）',
  },
  B: {
    id: 'B', name: '規格 B（9.91 中杯）', recipe: 'SHELL-B-0980-0991', ring: 'RING-B-40', ringBore: 4.0,
    od: 4.76, bore: 4.44, len: 9.86, base: 0.18, hole: 0, rOuter: 0.38, rInner: 0.2, flare: { len: 0.45, dr: 0.1 },
    gripR: 2.43, padR: 2.38, upper: 'IFD2410-6', wd: 30, probeR: 14,
    scan: { r0: 0.05, r1: 1.8, rev: 5, rpm: 120 },
    criteria: { od: [4.72, 4.80], length: [9.81, 9.91], idLip: [4.42, 4.47], wallLip: [0.16, 0.20], flare: 37, thk: [0.16, 0.20], tir: 0.024, flat: 0.008 },
    note: '壁厚 0.18 mm，夾持力上限 2 N',
  },
  C: {
    id: 'C', name: '規格 C（13.8 長管）', recipe: 'SHELL-C-1380', ring: 'RING-C-34', ringBore: 3.4,
    od: 4.85, bore: 3.77, len: 13.75, base: 0.88, hole: 2.34, rOuter: 0.25, rInner: 0, neck: { od: 4.25, len: 1.8 },
    gripR: 2.125, padR: 2.425, upper: 'IFC2411＋IFS 光纖探頭', wd: 45, probeR: 5,
    scan: { r0: 1.30, r1: 1.62, rev: 5, rpm: 120 },
    criteria: { od: [4.80, 4.90], length: [13.70, 13.80], idLip: [3.72, 3.82], wallLip: [0.19, 0.29], thk: [0.80, 0.95], tir: 0.05, flat: 0.008 },
    note: '口部依圖面判讀為外徑 Ø4.3 縮頸、內孔 Ø3.72 直通；底孔 Ø2.34 視為貫穿（R-02 待確認）',
  },
};

export const SCENARIOS = {
  OK: { id: 'OK', name: '合格 → OK 托盤', out: 'OK', tower: 'green' },
  'NG-D': { id: 'NG-D', name: '尺寸不良（外徑超規）→ NG1', out: 'NG1', tower: 'red' },
  'NG-A': { id: 'NG-A', name: '外觀不良（外壁拉傷）→ NG2', out: 'NG2', tower: 'red' },
  'NG-T': { id: 'NG-T', name: '底部不良（底厚超規）→ NG1', out: 'NG1', tower: 'red' },
  ERR: { id: 'ERR', name: '量測異常（訊號不足）→ 重測 → 退回人工', out: 'IN', tower: 'yellow' },
};

// ---------------------------------------------------------------- 工件剖面
const arc = (cx, cy, r, a0, a1, n = 6) => Array.from({ length: n + 1 }, (_, i) => { const a = a0 + (a1 - a0) * i / n; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; });
export function profile(s) {
  const R = s.od / 2, ri = s.bore / 2, L = s.len, t = s.base, h = s.hole / 2, P = [];
  P.push([h, 0], ...arc(R - s.rOuter, s.rOuter, s.rOuter, -Math.PI / 2, 0));
  if (s.neck) { const rn = s.neck.od / 2; P.push([R, L - s.neck.len - (R - rn)], [rn, L - s.neck.len], [rn, L], [ri, L]); }
  else if (s.flare) P.push([R, L - s.flare.len], [R + s.flare.dr, L], [ri + s.flare.dr, L], [ri, L - s.flare.len]);
  else P.push([R, L], [ri, L]);
  if (s.rInner > 0) P.push(...arc(ri - s.rInner, t + s.rInner, s.rInner, 0, -Math.PI / 2)); else P.push([ri, t]);
  P.push([h, t]);
  if (h > 0) P.push([h, 0]);
  return P;
}

// ---------------------------------------------------------------- 托盤
export const TRAYS = {
  IN: { id: 'IN', name: '入料托盤', cx: -255, cols: 5, rows: 4, shuttle: 'in', order: 'rear' },
  OK: { id: 'OK', name: 'OK 托盤', cx: -165, cols: 5, rows: 4, shuttle: 'out', order: 'front' },
  NG1: { id: 'NG1', name: 'NG1（尺寸／底部）', cx: -100, cols: 2, rows: 4, shuttle: 'out', order: 'front' },
  NG2: { id: 'NG2', name: 'NG2（外觀）', cx: -60, cols: 2, rows: 4, shuttle: 'out', order: 'front' },
};
export const DEMO = { k: 6, filled: { OK: 5, NG1: 1, NG2: 1 } };   // 本件為入料第 7 穴；出料托盤已有的數量
// 手臂由後方伸入，所以手臂側（−Z）的列必須是空的：入料從最後一列開始取，出料從最前一列開始放
export function pocket(tray, i) {
  const t = TRAYS[tray], row = Math.floor(i / t.cols), col = i % t.cols;
  const lz = t.order === 'rear' ? -PITCH * (t.rows - 1) / 2 + PITCH * row : PITCH * (t.rows - 1) / 2 - PITCH * row;
  return { x: t.cx - PITCH * (t.cols - 1) / 2 + PITCH * col, lz, row, col };
}
export const shuttleFor = (tray, i) => -pocket(tray, i).lz;      // 讓該列對準取放線 z = 0
export const traySize = t => ({ w: PITCH * TRAYS[t].cols + 12, d: PITCH * TRAYS[t].rows + 12, h: 10 });
export function occupied(tray, state) {
  const out = [];
  if (tray === 'IN') { for (let i = DEMO.k + 1; i < 20; i++) out.push(i); if (state.loc === 'in' || state.loc === 'back') out.push(DEMO.k); }
  else { for (let i = 0; i < DEMO.filled[tray]; i++) out.push(i); if (state.loc === 'out:' + tray) out.push(DEMO.filled[tray]); }
  return out;
}

// ---------------------------------------------------------------- 固定機構（顯示與干涉檢查共用）
const box = (id, x0, x1, y0, y1, z0, z1, mat = 'frame') => ({ id, kind: 'box', min: [x0, y0, z0], max: [x1, y1, z1], mat });
const cyl = (id, p0, p1, r, mat = 'steel', o = {}) => ({ id, kind: 'cyl', p0, p1, r, mat, ...o });
export const DIR_A = [0.5, 0, Math.sin(Math.PI / 3)];              // 通道 A：前右 60°
export const DIR_R = [-Math.SQRT1_2, 0, Math.SQRT1_2];             // 紅光暗場：與相機軸夾 75°
const along = (d, r, y = YA) => [X1 + d[0] * r, y, d[2] * r];

export function fixedBodies(s) {
  const jawR = s.gripR + 1.4, up = YS + s.base + s.wd, B = [];
  B.push(box('granite', -310, 310, Y0 - 42, Y0, -215, 215, 'granite'));
  // 移載 X 軸（後側）
  B.push(box('xaxis', -305, 300, Y0, Y0 + 50, -200, -150, 'axis'));
  // 托盤梭台軸
  B.push(box('shuttleIn', -275, -235, Y0, Y0 + 40, -70, 200, 'axis'), box('shuttleOut', -135, -95, Y0, Y0 + 40, -70, 200, 'axis'));
  // 通道 B：遠心鏡頭（左）＋平行背光（右），都由前側立柱懸臂
  B.push(cyl('lensB', [X1 - 60, YA, 0], [X1 - 170, YA, 0], 19, 'lens'), box('camB', X1 - 215, X1 - 170, YA - 18, YA + 18, -18, 18, 'camera'));
  for (const [i, x] of [[0, -215], [1, -45]]) B.push(box('lensPost' + i, x, x + 10, Y0, YA + 8, 36, 46), box('lensClamp' + i, x, x + 10, YA - 8, YA + 8, 19, 36));
  B.push(cyl('backlight', [X1 + 45, YA, 0], [X1 + 105, YA, 0], 16, 'light'), box('blPost', X1 + 70, X1 + 80, Y0, YA + 8, 36, 46), box('blClamp', X1 + 70, X1 + 80, YA - 8, YA + 8, 16, 36));
  // 通道 A：線掃相機＋遠心鏡頭
  B.push(cyl('lensA', along(DIR_A, 60), along(DIR_A, 150), 17, 'lens'), cyl('camA', along(DIR_A, 150), along(DIR_A, 200), 22, 'camera', { square: true }));
  for (const [i, r] of [[0, 110], [1, 178]]) { const p = along(DIR_A, r); B.push(box('postA' + i, p[0] - 6, p[0] + 6, Y0, YA - (i ? 22 : 17), p[2] - 6, p[2] + 6)); }
  // RGB 線光源：G 明場（前方 30°）、R 暗場（75°）；B 同軸併在鏡頭前端
  B.push(box('lightG', X1 - 6, X1 + 6, YA - 14, YA + 14, 36, 58, 'ledG'), box('postG', X1 - 4, X1 + 4, Y0, YA - 14, 48, 58));
  const pr = along(DIR_R, 47); B.push(cyl('lightR', [pr[0], YA - 14, pr[2]], [pr[0], YA + 14, pr[2]], 9, 'ledR'), cyl('postR', [pr[0], Y0, pr[2]], [pr[0], YA - 14, pr[2]], 4, 'frame'));
  // ST1 立柱、DD 中空軸馬達、夾頭、通道 C（由中空軸往下看杯口）
  B.push(box('col1', X1 - 20, X1 + 20, Y0, YM + 260, 120, 160), box('arm1', X1 - 20, X1 + 20, YM + 40, YM + 70, 38, 120), box('armC', X1 - 12, X1 + 12, YM + 120, YM + 140, 14, 120));
  B.push(cyl('dd', [X1, YM + 22, 0], [X1, YM + 72, 0], 40, 'motor'), cyl('chuck', [X1, YM + 3, 0], [X1, YM + 22, 0], 11, 'steel'));
  B.push(cyl('lensC', [X1, YM + 80, 0], [X1, YM + 190, 0], 15, 'lens'), box('camC', X1 - 18, X1 + 18, YM + 190, YM + 240, -18, 18, 'camera'));
  for (let i = 0; i < 3; i++) { const a = Math.PI / 2 + i * 2 * Math.PI / 3; B.push(cyl('jaw' + i, [X1 + jawR * Math.cos(a), YM - 1.5, jawR * Math.sin(a)], [X1 + jawR * Math.cos(a), YM + 3, jawR * Math.sin(a)], 1.4, 'peek', { rotor: 1 })); }
  // ST2：橋板、空心軸 θ 平台、三支柱、轉接板、鎢鋼薄環座
  B.push(box('bridgeF', 170, 260, Y0, Y0 + 50, 50, 70), box('bridgeR', 170, 260, Y0, Y0 + 50, -70, -50), box('bridge', 165, 265, Y0 + 50, Y0 + 62, -70, 70, 'plate', { bore: [X2, 0, 30] }));
  B.push(cyl('stage', [X2, Y0 + 62, 0], [X2, Y0 + 112, 0], 50, 'motor', { bore: 29 }));
  for (let i = 0; i < 3; i++) { const a = Math.PI / 6 + i * 2 * Math.PI / 3; B.push(cyl('pillar' + i, [X2 + 22 * Math.cos(a), Y0 + 112, 22 * Math.sin(a)], [X2 + 22 * Math.cos(a), YS - 4, 22 * Math.sin(a)], 3, 'steel', { rotor: 2 })); }
  B.push(cyl('adapter', [X2, YS - 4, 0], [X2, YS - 1, 0], 28, 'anodized', { bore: 15, rotor: 2 }), cyl('ring', [X2, YS - 4, 0], [X2, YS, 0], 15, 'carbide', { bore: s.ringBore / 2, rotor: 2 }));
  // C 型架：R 軸微動台承載整個 C 型架，上下感測器共線
  B.push(box('rstage', 268, 308, Y0, Y0 + 25, -40, 40, 'axis', { cframe: 0 }));
  B.push(box('colC', 275, 301, Y0 + 25, Y0 + 360, -25, 25, 'frame', { cframe: 1 }), box('armUp', X2 - 22, 301, Y0 + 330, Y0 + 360, -20, 20, 'frame', { cframe: 1 }), box('armDn', X2 - 18, 280, Y0 + 28, Y0 + 44, -14, 14, 'frame', { cframe: 1 }));
  B.push(cyl('sensorDn', [X2, Y0 + 44, 0], [X2, YS - 15, 0], 13.5, 'sensor', { cframe: 1 }));
  B.push(box('zadj', X2 - 20, X2 + 20, up + 70, Y0 + 330, -18, 18, 'axis', { cframe: 1 }), cyl('sensorUp', [X2, up, 0], [X2, up + 70, 0], s.probeR, 'sensor', { cframe: 1 }));
  return B;
}

// ---------------------------------------------------------------- 移動機構
export function transferBodies(st, s) {
  const z1 = -s.padR - st.a, y = st.zt, x = st.tx;
  return [
    box('blade', x - 1.5, x + 1.5, y + 1.3, y + 2.4, z1 - 25, z1, 'steel'),
    box('armBody', x - 5, x + 5, y + 1.3, y + 9.2, -135 - st.a, z1 - 25, 'anodized'),
    box('zplate', x - 20, x + 20, y - 10, y + 40, -150, -135, 'axis'),
    box('zcol', x - 25, x + 25, Y0 + 50, Y0 + 200, -165, -150, 'axis'),
    box('carriage', x - 40, x + 40, Y0 + 50, Y0 + 65, -200, -150, 'axis'),
  ];
}
export function trayPose(tray, st) { const t = TRAYS[tray]; return { x: t.cx, z: t.shuttle === 'in' ? st.inZ : st.outZ }; }
export function trayBodies(st, s) {
  const B = [];
  for (const id of Object.keys(TRAYS)) {
    const p = trayPose(id, st), g = traySize(id);
    B.push(box('tray' + id, p.x - g.w / 2, p.x + g.w / 2, YT - 9, YT + 1, p.z - g.d / 2, p.z + g.d / 2, 'tray'));
    for (const i of occupied(id, st)) { const q = pocket(id, i); B.push(cyl(`part${id}${i}`, [q.x, YT, p.z + q.lz], [q.x, YT + s.len, p.z + q.lz], s.od / 2 + (s.flare ? s.flare.dr : 0), 'part')); }
  }
  for (const [id, x] of [['In', -255], ['Out', -115]]) { const z = id === 'In' ? st.inZ : st.outZ, w = id === 'In' ? 84 : 186; B.push(box('table' + id, x - w / 2, x + w / 2, Y0 + 40, YT - 9, z - 40, z + 40, 'plate')); }
  return B;
}
// 工件底面中心位置與自轉角
export function partPose(st, s) {
  const [where, tray] = String(st.loc).split(':');
  if (where === 'in' || where === 'back') { const q = pocket('IN', DEMO.k); return { x: q.x, y: YT, z: st.inZ + q.lz, rot: 0 }; }
  if (where === 'noz') return { x: st.tx, y: st.zt, z: -st.a, rot: 0 };
  if (where === 'chuck') return { x: X1, y: YM - s.len, z: 0, rot: st.th1 };
  if (where === 'seat') return { x: X2, y: YS, z: 0, rot: st.th2 };
  const q = pocket(tray, DEMO.filled[tray]); return { x: q.x, y: YT, z: st.outZ + q.lz, rot: 0 };
}

// ---------------------------------------------------------------- 模擬量測值（示意，非實測）
const mid = ([a, b]) => (a + b) / 2;
export function measurement(s, scenario) {
  const c = s.criteria, od0 = mid(c.od) + 0.004;
  const m = {
    od: [od0, od0 + 0.003, od0 - 0.002, od0 + 0.001], length: mid(c.length) + 0.012, idLip: mid(c.idLip) - 0.006,
    flare: c.flare ? 31.4 : null, straightness: 0.006, thkMean: mid(c.thk) + 0.004, thkMin: mid(c.thk) - 0.003, thkMax: mid(c.thk) + 0.011,
    flatness: 0.0046, valid: 18000, invalid: 0, defects: [], result: 'OK', code: '', retest: false,
  };
  if (scenario === 'NG-D') { m.od = m.od.map((v, i) => c.od[1] + 0.012 + i * 0.002); m.result = 'NG-D'; m.code = '外徑超出上限'; }
  if (scenario === 'NG-A') { m.defects = [{ type: '拉傷', channel: 'A-R', theta: 142, y: 0.42, len: 0.86, conf: 0.91 }]; m.result = 'NG-A'; m.code = '外壁拉傷 0.86 mm（上限 0.5 mm）'; }
  if (scenario === 'NG-T') { m.thkMean = c.thk[0] - 0.014; m.thkMin = m.thkMean - 0.009; m.thkMax = m.thkMean + 0.008; m.result = 'NG-T'; m.code = '底厚低於下限'; }
  if (scenario === 'ERR') { m.valid = 11240; m.invalid = 6760; m.thkMean = m.thkMin = m.thkMax = m.flatness = null; m.result = 'ERR'; m.code = '上感測器訊號強度不足（有效點 62 %）'; m.retest = true; }
  m.wallLip = (m.od[0] - m.idLip) / 2;
  if (s.neck) m.wallLip = (mid([s.neck.od - 0.05, s.neck.od + 0.05]) - m.idLip) / 2;
  m.thkTir = m.thkMax === null ? null : m.thkMax - m.thkMin;
  return m;
}
export const inTol = (v, [a, b]) => v >= a - 1e-9 && v <= b + 1e-9;
