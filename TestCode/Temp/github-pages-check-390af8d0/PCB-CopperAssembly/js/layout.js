// 機台與產品的共用尺寸、運動參數與誤差模型。座標：x 沿流向、y 向上、z 橫向（+z 為前側／作業員側）。單位 mm、s。
// 產品尺寸依照片目測（350 × 350 基板、6 排 × 23 個長圓孔）；實際以圖面校正。

/** 機種配方：同一台機切換長圓孔／圓孔基板（換配方、供料盤清料換料、吸嘴快換） */
export const RECIPES = {
  'obround-138': {
    name: '長圓孔基板 · 138 孔（照片）', short: '長圓 138', source: '照片目測：6 排 × 23 個長圓孔',
    hole: { shape: 'obround', w: 3.4, l: 7.4, radius: .85 }, coin: { shape: 'obround', w: 3.0, l: 7.0, t: 1.5, radius: .65 },   // 單邊間隙 0.2 mm；照片圓角長條外觀，圓角尺寸為示意
    columnsX: [-137.5, -82.5, -27.5, 27.5, 82.5, 137.5], rows: 23, rowPitch: 14,
    nozzleR: 1.2, feederCount: 14, feederGap: 10,                                                    // 吸嘴 Ø2.4；供料盤每次攤開 14 顆
  },
  'round-72': {
    name: '圓孔基板 · 72 孔（假設）', short: '圓形 72', source: '假設：圓形銅片 Ø10、孔 Ø10.4、6 排 × 12 孔；待用戶提供圖面',
    hole: { shape: 'round', w: 10.4, l: 10.4 }, coin: { shape: 'round', w: 10.0, l: 10.0, t: 1.5 },
    columnsX: [-137.5, -82.5, -27.5, 27.5, 82.5, 137.5], rows: 12, rowPitch: 26,
    nozzleR: 2.0, feederCount: 10, feederGap: 13,                                                    // 快換 Ø4 吸嘴
  },
};
export const DEFAULT_RECIPE = 'obround-138';

/** 產品（依目前配方；setRecipe 會就地更新） */
export const PRODUCT = {
  board: { w: 350, d: 350, t: 1.6, adhesive: 0.15 },          // 銅箔基板＋底部黏紙
  fiducials: [[-165, -165], [165, -165], [-165, 165]],        // 板邊工具孔（照片可見），當作基準點
  spec: 0.1524,                                               // 放置精度 ±6 mil
};
export const HOLES = [];
export function setRecipe(key) {
  const r = RECIPES[key] || RECIPES[DEFAULT_RECIPE];
  Object.assign(PRODUCT, { recipe: RECIPES[key] ? key : DEFAULT_RECIPE, name: r.name, short: r.short, source: r.source, hole: r.hole, coin: r.coin, nozzleR: r.nozzleR, feederCount: r.feederCount, feederGap: r.feederGap });
  HOLES.length = 0;
  r.columnsX.forEach((x, c) => { for (let row = 0; row < r.rows; row++) HOLES.push({ id: c * r.rows + row, col: c, row, x, z: (row - (r.rows - 1) / 2) * r.rowPitch, angle: 0 }); });  // angle：銅片長軸相對 z 軸（°）
  return PRODUCT;
}
setRecipe(DEFAULT_RECIPE);

/** 機台配置 */
export const LAYOUT = {
  conveyorTop: 950,                                           // 基板底面（黏紙底）高度
  stations: [-1400, -700, 0, 700, 1400],                      // S0 上料、S1 基板定位、S2 放置、S3 檢查、S4 下料
  railInner: 178,                                             // 輸送邊軌內側 |z|
  stackZ: 560,                                                // 上料／收料料倉在前側
  // S2 雙龍門：A 在前（+z）、B 在後（−z）；吸嘴裝在橫樑內側，懸伸 87 mm
  gantry: { railX: 520, beamY: 1250, beamDepth: 120, overhang: 87, downCamDX:95, downCamOut:10, nozzleDX: [-33, -11, 11, 33], minBeamGap: 140 },
  feeder: { A: { x: -300, z: 330 }, B: { x: 300, z: -330 }, w: 150, d: 110, top: 955 },   // 柔性供料盤（中心、尺寸、盤面高度）
  upCam: { A: { x: -120, z: 250 }, B: { x: 120, z: -250 }, lensY: 880, flyV: 400, flySpan: 110 },
  scan: { cols: [-131.25, -43.75, 43.75, 131.25], rows: [-140, -70, 0, 70, 140], fov: [110, 73] }, // S1／S3 掃描格：20 張
  safeTip: 975,                                               // 吸嘴移位時的最低尖端高度（板面上方約 23 mm）
};
export const BOARD_TOP = LAYOUT.conveyorTop + PRODUCT.board.adhesive + PRODUCT.board.t;
export const COIN_SEAT_TOP = LAYOUT.conveyorTop + PRODUCT.board.adhesive + PRODUCT.coin.t;  // 銅片落在黏紙上的上表面
export const FEED_COIN_TOP = LAYOUT.feeder.top + PRODUCT.coin.t;

/** 運動參數（龍門線性馬達等級；吸嘴 Z 為獨立音圈／伺服軸） */
export const MOTION = { xyV: 1500, xyA: 15000, zV: 600, zA: 30000, settle: 0.02, thetaV: 1800,  // mm/s、mm/s²、°/s
  vacuum: 0.02, press: 0.04, blow: 0.01, scanShot: 0.12, fidShot: 0.15 };
/** 單軸移動時間：短距三角速度、長距梯形速度 */
export function moveTime(d, v = MOTION.xyV, a = MOTION.xyA) { d = Math.abs(d); if (d < 1e-9) return 0; return d < v * v / a ? 2 * Math.sqrt(d / a) : d / v + v / a; }

/** 誤差模型（1σ，mm）：用於模擬每顆的放置結果；數值為設計目標，需實機 GR&R 驗證 */
export const ERRORS = { holeMap: 0.008, fiducial: 0.006, gantry: 0.010, upCam: 0.008, release: 0.012, theta: 0.15 };

/** 可重現的亂數（示範用：每次載入的偏差、供料位置都一樣） */
export function rng(seed) { let s = seed >>> 0; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
export function gauss(r) { let u = 0; while (u === 0) u = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r()); }
export const smooth = t => t * t * t * (10 + t * (-15 + 6 * t));
