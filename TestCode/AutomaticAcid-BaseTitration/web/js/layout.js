// 工作台配置、器皿尺寸、樣品批次與時間參數（單位 mm、秒、mL、g）
// 世界座標：X 向右、Y 向上、Z 朝操作員（前方）。手臂基座在原點、桌面高 Y0。
// 用戶文件（酸鹼自動滴定-機械手臂規劃-0828.pptx）只有流程與示意配置，尺寸與時間皆為設計假設。

export const Y0 = 850;                                   // 桌面高度
export const BENCH = { x: [-1200, 1200], z: [-500, 500], top: Y0 };

// 器皿
export const BEAKER = { d: 65, h: 90, vol: 200, mass: 95.4 };                   // 200 mL 滴定杯（高型）
export const BOTTLES = {
  500: { d: 86, h: 176, neck: 45, neckH: 22, grip: 120, open: 112, fill: 400 },   // 500 mL 試劑瓶，GL45 瓶蓋
  100: { d: 56, h: 105, neck: 45, neckH: 22, grip: 70, open: 82, fill: 90 },      // 100 mL 試劑瓶，GL45 瓶蓋
};
export const CAP = { d: 53, h: 26, pitch: 4 };                                  // GL45 螺牙節距約 4 mm
// 10 mL 電動移液器（夾持環在上方）＋ 10 mL 吸頭
export const PIPETTE = { collar: 245, top: 290, r: 18, nose: 35, tipLen: 160, tipSeat: 12, tipR: 10, tipMax: 10 };
PIPETTE.tipEnd = PIPETTE.collar + PIPETTE.tipLen - PIPETTE.tipSeat;              // TCP（夾持環）到吸頭尖端 393 mm

// 站別位置（x, z）；高度為器皿底部所在高度（相對桌面）
export const ST = {
  robot: { x: 0, z: 0 },
  // 天平：前方（+X）朝向手臂，上方滑門往 −X 滑開
  balance: { x: -560, z: 20, pan: 90, chamber: { x: [-685, -435], z: [-95, 135], y: [75, 345] }, doorTravel: 250, tab: -440 },
  emptyRack: { cols: [-620, -520, -420], rows: [-420, -340, -260, -180], base: 10 },   // 待處理杯區（12 杯）
  capRest: { x: -300, z: -300, base: 18 },
  clamp: { x: -170, z: -330, base: 10 },                                                 // 樣品瓶座＋開蓋區（氣動自定心 V 型夾座）
  holder: { x: -20, z: -370, base: 15 },                                                 // 滴定杯座
  funnel: { x: 100, z: -345, top: 80 },                                                  // 廢液漏斗（接桌下廢液桶）
  stripper: { x: 170, z: -230, plate: 180 },                                             // 吸頭退除叉＋落料槽
  tipRack: { x0: 235, z: [-380, -345], pitch: 30, n: 6, top: 175 },                     // 10 mL 吸頭架（2 × 6）
  dock: { x: 470, z: -250, collar: 250 },                                                // 移液器停放座（吸頭伸入桌面孔）
  scanner: { x: -250, z: -30, read: { x: -250, z: 90 }, h: 130 },                       // 固定式條碼讀取器
  sampleRack: { cols: [-620, -500, -380], rows: { 500: 250, 100: 370 }, base: 8, pitch: 120 },       // 待驗樣品瓶區
  doneBottleRack: { cols: [-250, -130, -10], rows: { 500: 250, 100: 370 }, base: 8, pitch: 120 },    // 完成樣品瓶區
  doneRack: { cols: [150, 250, 350], rows: [200, 280, 360, 440], base: 10 },             // 完成滴定杯區
  // Metrohm 自動進樣器（814／815 USB Sample Processor 級，12 × 250 mL 轉盤）：滴定頭在轉盤最遠端（+X）
  sampler: { x: 660, z: 60, r: 150, slots: 12, plate: 110, housing: { x: [440, 880], z: [-160, 280], h: 80 }, towerX: 950 },
  titrator: { x: 1000, z: -300 },
  pc: { x: 1000, z: 400 },
};

// 搬運高度：手上物件底部離桌面至少 TRAVEL（越過天平 345、瓶子 202、停放座 295）
export const TRAVEL = 420;
export const PIP_TRAVEL = 250;                           // 拿移液器時吸頭尖端的高度（只在移液區內移動）

// 時間參數（秒）
export const TIME = {
  grip: 0.6, clampAct: 0.8, settle: 8, zero: 3,           // 夾爪開合、夾座動作、天平穩定、歸零
  aspirate: 10 / 2.5, dispense: 10 / 3, blowout: 1.0,     // 移液速度：吸 2.5 mL/s、吐 3 mL/s
  scan: 2.0,
  rotBase: 2.5, rotPerSlot: 0.6,                          // 轉盤：啟動＋每格
  lower: 4, lift: 4, rinse: 12,                           // 滴定頭下降、上升、電極噴洗
  titrate: 420,                                           // 分析時間（用戶文件：約 7 分鐘）
  startDelay: 2,                                          // 杯子到位 → 送出啟動
};
export const SPEED = { fast: 500, lin: 150, linSlow: 60, push: 120, near: 40 }; // 直線移動 mm/s；接近／離開最後 near mm 用 lin 速度

// 批次：6 瓶（3 × 500 mL、3 × 100 mL），每瓶兩重複，共 12 次滴定
export const RINSE = { vol: 3, times: 2 };                 // 潤洗：吸 3 mL 吐到廢液，兩次
export const ALIQUOT = { vol: 10, times: 2 };              // 取樣：10 mL × 2 = 20 mL
export const TITRANT = { name: 'NaOH', c: 0.1, buret: 20 };// 滴定液 0.1 mol/L NaOH、20 mL 滴定管
export const ANALYTE = { name: 'HCl', M: 36.46 };          // 示意：以 HCl 計算酸含量

export function rng(seed) { let s = seed >>> 0; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
export function gauss(r) { return Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r()); }
export const smooth = e => e * e * e * (e * (e * 6 - 15) + 10);

const R = rng(20260828);
export const SAMPLES = [500, 500, 500, 100, 100, 100].map((size, i) => ({
  id: i, size, barcode: `AB-0828-${String(i + 1).padStart(3, '0')}`,
  conc: 0.045 + 0.012 * R(),                              // 真實濃度（mol/L，模擬）
  rackSlot: i % 3, doneSlot: i % 3,
}));
