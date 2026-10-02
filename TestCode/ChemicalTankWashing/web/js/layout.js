// 場地與設備配置的唯一資料來源：模型、動畫、空間檢核與 tools/verify.mjs 共用。
// 座標單位 mm；X 向東、Y 向上、Z 向南；原點為洗桶區西北角內牆面（倉儲區西牆 × 北牆）。
// 場地尺寸取自 docs/場地圖.jpg 的標註（1256、455＋540＋557 cm）；未標註的位置（柱、門、更衣室）
// 依圖面比例量測，誤差約 ±300 mm，施工前須現場丈量。

export const ROOM = { W: 12560, D: 15520, H: 4500, wall: 200 };

// 內牆輪廓（俯視）：更衣室由西側凸入，西南角向西延伸。
export const OUTLINE = [
  [0, 0], [12560, 0], [12560, 15520], [-2480, 15520], [-2480, 11190],
  [620, 11190], [620, 8520], [1770, 8520], [1770, 4700], [0, 4700],
];

// 門：swing 為門扇開啟掃過的區域（不得放設備）
export const DOORS = [
  { id: 'D3', x0: 1860, x1: 2830, z: 0, dir: 1, note: '北牆門，往倉儲區內開' },
  { id: 'D2', x0: 230, x1: 1030, z: 4700, dir: -1, note: '更衣室門，往倉儲區開' },
];
export const doorSwing = d => [d.x0, Math.min(d.z, d.z + d.dir * (d.x1 - d.x0)), d.x1, Math.max(d.z, d.z + d.dir * (d.x1 - d.x0))];

// 倉儲南緣的結構柱（圖面量測，800 mm 見方）
export const COLUMN = { x: 8300, z: 5200, size: 800 };
export const columnRect = () => [COLUMN.x - COLUMN.size / 2, COLUMN.z - COLUMN.size / 2, COLUMN.x + COLUMN.size / 2, COLUMN.z + COLUMN.size / 2];

// 200 L 閉口 HDPE 桶（雙 L 環），2" 與 3/4" 螺塞在桶頂同一直徑兩端
export const DRUM = { R: 292.5, H: 935, bungR: 200, big: { r: 36, h: 24, hole: 27 }, small: { r: 18, h: 18, hole: 12 }, kg: 8.5 };
export const PALLET = {
  W: 1200, H: 150,
  // 2×2 擺放（棧板局部座標）。棧板在棧板站轉了 180°，此順序對應世界座標先取東側兩桶，西側兩桶取料時不必越過其他桶
  slots: [[-300, 300], [-300, -300], [300, 300], [300, -300]],
};

// 穿梭車密集架：南北向車道，每道 4 深 × 3 層；柱子前方的道位無法進出，故分成西 3 道、東 2 道
export const RACK = {
  lanes: [3630, 4990, 6350, 9450, 10810], pitch: 1360,
  zFront: 5400, zBack: 100,
  pos: [4800, 3500, 2200, 900],          // 前 → 後的棧板中心 Z（前位棧板與貨架前緣齊）
  levels: [150, 1480, 2810],             // 各層軌道頂面（棧板底）
  topBeam: 3700,
  shuttleLift: 40,
  emptyLane: 4, emptyLevel: 0, emptyStack: 5,   // 空棧板疊放道（東側最後一道底層）
  demo: { lane: 1, level: 1 },                  // 動畫取料：第 2 道第 2 層
};
export const rackBlocks = () => [
  [RACK.lanes[0] - RACK.pitch / 2, RACK.zBack, RACK.lanes[2] + RACK.pitch / 2, RACK.zFront],
  [RACK.lanes[3] - RACK.pitch / 2, RACK.zBack, RACK.lanes[4] + RACK.pitch / 2, RACK.zFront],
];

export const AISLE = { z0: 5400, z1: 9000, zc: 7200 };

// 平衡重式堆高 AGV（局部座標：+X 前進，原點為前輪軸中心，迴轉中心）
export const AGV = {
  rear: 1550, halfW: 500, mast: [220, 350], fork: [350, 1500], forkHalf: 350, palletX: 950,
  travel: 300, mastLowered: 2100, backrest: 1100,
  speed: 1000, slow: 300, turn: 35, lift: 250,
  // 地面接觸式充電板（齊平，不擋迴轉）設在走道中心線柱前；充電櫃掛在柱南面
  charger: { x: 8300, z: 7200, yaw: 180 },
};
// 迴轉掃掠半徑：取車身後角與棧板前角的最大值
export const agvSweep = loaded => Math.max(Math.hypot(AGV.rear, AGV.halfW), loaded ? Math.hypot(AGV.palletX + PALLET.W / 2, PALLET.W / 2) : Math.hypot(AGV.fork[1], AGV.forkHalf));
// 叉面高度：插入（低於上板 50）／抬起（棧板離軌 60）；棧板底 = 叉面 − 120
export const FORK = { entry: 70, lifted: 180, deck: 120 };

// 棧板站＋三軸龍門＋翻轉夾爪
export const PALLET_STATION = { x: 3900, z: 9700, stand: 100 };
export const GANTRY = {
  posts: [[3000, 9050], [6600, 9050], [3000, 10350], [6600, 10350]], beamY: 3000,
  hang: 150 + DRUM.H / 2,      // 翻轉軸到桶中心
  safeY: 2200, placeY: 800, home: { x: 4600, z: 9700 },
};
GANTRY.pickY = PALLET_STATION.stand + PALLET.H + DRUM.H + 150;

// 橫躺輸送：桶軸沿 X，桶頂朝西、桶底朝東（供翻轉機使用）
export const LYING = { z: 9700, y: 800, x0: 5400, x1: 10000, place: 5900, label: 7500, buffer: 9000, speed: 400 };
LYING.upender = 11000 - DRUM.H / 2;
export const LABEL = { x: LYING.label, standZ: 10560, camY: 2000, size: [100, 150] };
// 翻桶機：L 形搖籃以桶底下緣為軸翻 90°
export const UPENDER = { pivot: [11000, LYING.y - DRUM.R, LYING.z] };
// 立放輸送（往南），輸送面＝翻桶後桶底高度
export const UPRIGHT = { x: 11000 + DRUM.R, top: LYING.y - DRUM.R, z0: LYING.z, decap: 10800, pick: 12400, z1: 12750, speed: 300 };
export const DECAP = { z: UPRIGHT.decap, camY: 2500, safeY: 1750, bin: { x: 11850, z: UPRIGHT.decap } };

// 清洗手臂與沖洗站
export const ROBOT = { x: 9400, z: 12000, name: 'FANUC R-2000iC/165F', grip: 250 + DRUM.R };
export const BOOTH = {
  x0: 8750, x1: 10050, z0: 14050, z1: 15420, h: 2600,
  opening: [8850, 9950, 300, 2450],          // 北面開口 X0, X1, Y0, Y1
  drum: [9400, 1300, 14700], entryZ: 13700,   // entryZ：進站前桶中心，桶身仍在隔間外
  lance: [9600, 14700], lanceUp: 2050, lanceDown: 1620,
  funnel: { x0: 8900, x1: 9950, z0: 14150, z1: 15250, y: 650 },
};
export const OUT = { z: 12100, top: UPRIGHT.top, x0: 4400, x1: 7800, place: 7400, stops: [4800, 5420, 6040, 6660], speed: 350 };

// 清洗區圍籬（手臂以 DCS 限制在圍籬內）；南側為牆。東南象限是取桶→沖洗站的迴轉路徑，必須留在圍籬內
export const FENCE = [[7000, 15520], [7000, 11300], [11700, 11300], [11700, 15520]];
export const GANTRY_FENCE = [[2900, 8950], [6700, 8950], [6700, 10450], [2900, 10450]];

// 廢液回收：放在清洗區圍籬外西南側（控制櫃南面）的防溢堤內，避開手臂迴轉範圍
export const WASTE = {
  bund: [4450, 13950, 7000, 15420],
  tanks: {
    W: { x: 5100, z: 14700, r: 600, h: 1800, cap: 2000, init: 640, name: 'TK-W 廢液槽' },
    R: { x: 6200, z: 14400, r: 400, h: 1600, cap: 800, init: 380, name: 'TK-R 回收沖洗水槽' },
    F: { x: 6200, z: 15100, r: 280, h: 1500, cap: 350, init: 260, name: 'TK-F 清水暫存槽' },
  },
  pumpRinse: [6830, 14300], pumpDrain: [6830, 14950], rinseL: 20,
};
export const WALKWAYS = [[1770, 4700, 2900, 8520], [620, 8520, 2900, 11190], [0, 0, 1770, 4700]];
export const FILLING = [-2480, 11400, 4400, 15520];
export const SHUTTLE_BAY = [7030, 100, 8770, 4700];

// 設備俯視外框 [x0, z0, x1, z1, 高度]
export const FOOTPRINTS = {
  rackW: [...rackBlocks()[0], RACK.topBeam], rackE: [...rackBlocks()[1], RACK.topBeam],
  charger: [7900, 5600, 8300, 5750, 1400],   // 柱面充電櫃（西半；東半留給東道 AGV 迴轉）
  gantry: [2900, 8950, 6700, 10450, 3200],
  lying: [5400, 9300, 10000, 10100, 1100],
  labeler: [7000, 10120, 8000, 10900, 1800],
  hmi: [8500, 10500, 8900, 10900, 1500],
  upender: [10000, 9250, 11650, 10150, 1500],
  upright: [10900, 10150, 11690, 12750, 700],
  decap: [10600, 10350, 12100, 11250, 2700],
  robot: [8900, 11500, 9900, 12500, 1200],
  booth: [BOOTH.x0, BOOTH.z0, BOOTH.x1, BOOTH.z1, BOOTH.h],
  out: [OUT.x0, OUT.z - 350, OUT.x1, OUT.z + 350, 700],
  robotCtrl: [6200, 13350, 6940, 13900, 1200],
  panel: [4900, 13350, 6100, 13950, 2000],
  bund: [...WASTE.bund, 1900],
};
// 設計上相接或包含的組合（不算干涉）
export const ALLOWED = [['gantry', 'lying'], ['lying', 'upender'], ['upender', 'upright'], ['upright', 'decap']];

// AGV 原地迴轉點（動畫實際使用＋最東一道的取放）
export const AGV_TURNS = [
  { x: RACK.lanes[1], z: AISLE.zc, loaded: true, note: '第 2 道取料' },
  { x: PALLET_STATION.x, z: AISLE.zc, loaded: true, note: '棧板站' },
  { x: RACK.lanes[4], z: AISLE.zc, loaded: true, note: '空棧板道' },
  { x: RACK.lanes[3], z: AISLE.zc, loaded: true, note: '柱旁東道' },
];

// ---------------------------------------------------------------- 幾何工具
export function pointInPolygon([x, z], poly = OUTLINE) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, zi] = poly[i], [xj, zj] = poly[j];
    if ((zi > z) !== (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}
export const rectsOverlap = (a, b, gap = 0) => a[0] < b[2] + gap && b[0] < a[2] + gap && a[1] < b[3] + gap && b[1] < a[3] + gap;
export function rectInside(r) {
  const corners = [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]];
  if (!corners.every(p => pointInPolygon(p))) return false;
  return !OUTLINE.some(([x, z]) => x > r[0] && x < r[2] && z > r[1] && z < r[3]);
}
export function circleRectGap(cx, cz, r, rect) {
  const dx = Math.max(rect[0] - cx, 0, cx - rect[2]), dz = Math.max(rect[1] - cz, 0, cz - rect[3]);
  return Math.hypot(dx, dz) - r;
}
// 圓到牆的最短距離（輪廓各邊）
export function circleWallGap(cx, cz, r) {
  let best = Infinity;
  for (let i = 0; i < OUTLINE.length; i++) {
    const [ax, az] = OUTLINE[i], [bx, bz] = OUTLINE[(i + 1) % OUTLINE.length];
    const L = Math.hypot(bx - ax, bz - az), t = Math.max(0, Math.min(1, ((cx - ax) * (bx - ax) + (cz - az) * (bz - az)) / (L * L)));
    best = Math.min(best, Math.hypot(cx - (ax + t * (bx - ax)), cz - (az + t * (bz - az))));
  }
  return best - r;
}

// ---------------------------------------------------------------- 空間檢核（網頁面板與驗證共用）
export function layoutChecks() {
  const out = [];
  const add = (group, name, ok, value, note = '') => out.push({ group, name, ok, value, note });
  const full = RACK.lanes.length * RACK.pos.length * RACK.levels.length - RACK.pos.length;
  add('倉儲', '棧板位（扣空棧板道）', full * 4 >= 200, `${full} 位 × 4 桶 = ${full * 4} 桶 ≥ 200`);
  const top = RACK.levels[2] + PALLET.H + DRUM.H + RACK.shuttleLift;
  add('倉儲', '第 3 層貨頂與樓高', top <= ROOM.H - 450, `${top} mm，距樓板 ${ROOM.H - top} mm（灑水頭 ≥ 450）`);
  const gap = RACK.levels[1] - (RACK.levels[0] + PALLET.H + DRUM.H + RACK.shuttleLift) - 105;
  add('倉儲', '層間淨空（含軌道 105）', gap >= 100, `${gap} mm ≥ 100`);
  const swing = agvSweep(true);
  add('AGV', '走道寬 vs 迴轉直徑', AISLE.z1 - AISLE.z0 >= 2 * swing + 200, `${AISLE.z1 - AISLE.z0} ≥ 2×${swing.toFixed(0)}＋200`);
  const obstacles = [['柱', columnRect()], ['西貨架', rackBlocks()[0]], ['東貨架', rackBlocks()[1]], ['龍門', FOOTPRINTS.gantry], ['充電座', FOOTPRINTS.charger]];
  for (const t of AGV_TURNS) {
    const r = agvSweep(t.loaded);
    const gaps = [['牆', circleWallGap(t.x, t.z, r)], ...obstacles.map(([n, rect]) => [n, circleRectGap(t.x, t.z, r, rect)])];
    const [n, g] = gaps.reduce((a, b) => b[1] < a[1] ? b : a);
    add('AGV', `迴轉點 X ${t.x}（${t.note}）`, g >= 50, `最近：${n} ${g.toFixed(0)} mm`);
  }
  const mast = RACK.levels[2] + FORK.lifted + AGV.backrest;
  add('AGV', '第 3 層取放門架高度', mast <= ROOM.H - 150, `${mast} mm`);
  for (const d of DOORS) {
    const s = doorSwing(d), hit = Object.entries(FOOTPRINTS).find(([, r]) => rectsOverlap(r, s, 100));
    add('動線', `${d.id} 門開啟範圍`, !hit, hit ? `與 ${hit[0]} 干涉` : '淨空 ≥ 100 mm');
  }
  const walk = WALKWAYS.map(w => Object.entries(FOOTPRINTS).find(([, r]) => rectsOverlap(r, w)));
  add('動線', '人員通道（更衣室→產線）', walk.every(h => !h), `寬 ${WALKWAYS[0][2] - WALKWAYS[0][0]} mm`);
  const outside = Object.entries(FOOTPRINTS).filter(([, r]) => !rectInside(r)).map(([n]) => n);
  add('配置', '設備都在牆內', !outside.length, outside.length ? outside.join('、') : `${Object.keys(FOOTPRINTS).length} 項`);
  const keys = Object.keys(FOOTPRINTS), clash = [];
  for (let i = 0; i < keys.length; i++) for (let j = i + 1; j < keys.length; j++) {
    const a = keys[i], b = keys[j];
    if (ALLOWED.some(p => p.includes(a) && p.includes(b))) continue;
    if (rectsOverlap(FOOTPRINTS[a], FOOTPRINTS[b])) clash.push(`${a}/${b}`);
  }
  if (rectsOverlap(columnRect(), FOOTPRINTS.charger, -1)) clash.push('column/charger');
  add('配置', '設備外框互不重疊', !clash.length, clash.length ? clash.join('、') : '通過');
  const zTop = GANTRY.safeY + 250 + 1300;
  add('配置', '龍門伸縮 Z 軸頂端', zTop <= ROOM.H - 300, `${zTop} mm（兩段伸縮）`);
  const reachDist = (x, z) => Math.hypot(x - ROBOT.x, z - ROBOT.z);
  const far = Math.max(reachDist(UPRIGHT.x - ROBOT.grip, UPRIGHT.pick), reachDist(BOOTH.drum[0], BOOTH.drum[2] - ROBOT.grip), reachDist(OUT.place + ROBOT.grip, OUT.z));
  add('清洗', '手臂取放點水平距離', far < 2655 - 215, `最遠 ${far.toFixed(0)} mm（型錄伸展 2655）`);
  return out;
}
