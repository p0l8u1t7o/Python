// 配方：接頭型錄＋各機種的載盤、板子與接頭配置。換機種只換配方，治具不換。
// 載盤座標：原點在載盤底面中心，x 沿流向、z 橫向；接頭 rot（°）＝插頭指向，0 朝 −z、90 朝 −x、180 朝 +z、270 朝 +x。
// USB 連板依照片目測；3.5 吋 SSD 與 90° 轉向連板為假設配置，拿到用戶資料後替換。

/** 接頭型錄：接頭本地座標插頭朝 −z，後緣（銀腳出口）在 z=0、PCB 上表面 y=0 */
export const CONNECTOR_TYPES = {
  'USB-A': { w: 12, h: 4.5, l: 14, sink: 1.0, leads: 9, leadPitch: 1.0, leadL: 3.5, pressFromTip: 11, tongue: 0x1f5fa8, holes: true },
  'USB-C': { w: 8.94, h: 3.26, l: 7.35, sink: 1.6, leads: 12, leadPitch: 0.5, leadL: 2.5, pressFromTip: 5.2, tongue: 0x202428, holes: false },
};

const usbUnitComps = [
  { x: 0, z: 12, w: 6, d: 6, h: 0.9, kind: 'chip' },
  { x: 5.6, z: 12, w: 2, d: 2.5, h: .65, kind: 'chip' },
  ...[0,1,2].flatMap(k => [-1,1].map(s => ({x:s*5.5,z:4.5+k*1.6,w:1.2,d:.65,h:.45,kind:'passive'}))),
  ...[0,1,2,3].map(k => ({x:-5.7,z:11+k*1.7,w:1.2,d:.65,h:.45,kind:'passive'})),
  { x: 5.5, z: 16, w: 1.6, d: 0.8, h: 0.6, kind: 'passive' },
  { x: -6, z: 27, w: 1.6, d: 0.8, h: 0.6, kind: 'passive' }, { x: 6, z: 28, w: 1.6, d: 0.8, h: 0.6, kind: 'passive' },
  { x: 0, z: 35, w: 1.6, d: 0.8, h: 0.6, kind: 'passive' },
];

/** USB 隨身碟 2×8 連板（照片），以連板中心為原點；deg 為整片旋轉角 */
function usbPanel(deg) {
  const pitch = 21, rowGap = 4, len = 42, edge = rowGap / 2 + len, boards = [], connectors = [], rails = [];
  const unitX = i => (i - 3.5) * pitch;
  for (const [row, side, rot] of [['A', -1, 0], ['B', 1, 180]]) for (let i = 0; i < 8; i++) {
    const id = row + (i + 1), x = unitX(i), z = side * edge;
    connectors.push({ id, row, type: 'USB-A', x, z, rot });
    boards.push({ x, z, rot, cx: 0, cz: len / 2, w: 18.5, d: len, t: 1.0, comps: usbUnitComps });
  }
  const panelW = 8 * pitch + 12;
  for (const s of [-1, 1]) rails.push({ x: s * (panelW / 2 - 3), z: 0, w: 6, d: 2 * edge, t: 1.0 });
  rails.push({ x: 0, z: 0, w: panelW, d: rowGap, t: 1.0 });
  return rotateLayout({ boards, connectors, rails }, deg);
}
/** 3.5 吋 SSD 裸板（假設）：101.6 × 146 mm，USB-C 在短邊、偏離中心 20 mm；每盤 2 片、接頭朝左右 */
function ssdPair() {
  const comps = [
    { x: -20, z: 40, w: 15, d: 15, h: 1.3, kind: 'chip' }, { x: -20, z: 62, w: 10, d: 8, h: 1.0, kind: 'chip' },
    ...[0, 1, 2, 3].map(k => ({ x: -44 + 26 * (k % 2) + 30, z: 85 + 26 * Math.floor(k / 2), w: 14, d: 18, h: 1.2, kind: 'chip' })),
    { x: 12, z: 18, w: 6, d: 6, h: 6, kind: 'cap' }, { x: -48, z: 15, w: 6, d: 6, h: 6, kind: 'cap' },
    ...[0, 1, 2, 3, 4, 5].map(k => ({ x: -60 + 8 * k, z: 30, w: 1.6, d: 0.8, h: 0.6, kind: 'passive' })),
  ];
  const board = { cx: -20, cz: 73, w: 101.6, d: 146, t: 1.6, comps };
  return {
    boards: [{ ...board, x: -152, z: -20, rot: 90 }, { ...board, x: 152, z: 20, rot: 270 }],
    connectors: [{ id: 'S1', row: 'SSD', type: 'USB-C', x: -152, z: -20, rot: 90 }, { id: 'S2', row: 'SSD', type: 'USB-C', x: 152, z: 20, rot: 270 }],
    rails: [],
  };
}
function rotateLayout(layout, deg) {
  if (!deg) return layout;
  const r = deg * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
  const p = o => ({ ...o, x: o.x * c + o.z * s, z: -o.x * s + o.z * c });
  return {
    boards: layout.boards.map(b => ({ ...p(b), rot: (b.rot + deg) % 360 })),
    connectors: layout.connectors.map(k => ({ ...p(k), rot: (k.rot + deg) % 360 })),
    rails: layout.rails.map(q => { const o = p(q); return deg % 180 ? { ...o, w: q.d, d: q.w } : o; }),
  };
}

// tilt0：示意翹起角（°），依照片放大；stubborn：壓後回彈、示範補壓的一顆
// insert：標準壓墊。整排接頭（8 顆、片距 21 mm）用 8 頭獨立彈簧壓墊一次壓一排；只有單顆接頭的機種快拆換單點壓頭
const usbTilt = { A1: 3.5, A2: 4.2, A4: 1.2, A6: 2.6, A8: 0.8, B2: 1.5, B5: 2.2, B7: 0.9 };
export const RECIPES = {
  'usb-2x8': {
    name: 'USB 隨身碟 2×8 連板', short: 'USB 2×8', source: '照片目測',
    pallet: { w: 300, d: 200, t: 6, code: '29-0290' }, ...usbPanel(0), pcbT: 1.0,
    rows: [['A', 'A'], ['B', 'B']], tilt0: usbTilt, stubborn: { id: 'A6', residual: 1.1 },
    press: { single: 5, bar: 40 }, multiPad: { pitch: 21, count: 8 }, insert: 'bar', gapLimit: 0.10,
  },
  'usb-2x8-r90': {
    name: 'USB 隨身碟 2×8 連板・接頭轉 90°（假設）', short: 'USB 2×8 轉 90°', source: '假設：同一連板轉 90° 放置',
    pallet: { w: 200, d: 280, t: 6, code: '29-0290R' }, ...usbPanel(90), pcbT: 1.0,
    rows: [['A', 'A'], ['B', 'B']], tilt0: usbTilt, stubborn: { id: 'A6', residual: 1.1 },
    press: { single: 5, bar: 40 }, multiPad: { pitch: 21, count: 8 }, insert: 'bar', gapLimit: 0.10,
  },
  'ssd35-usbc': {
    name: '3.5 吋 SSD ×2・USB-C（假設）', short: '3.5" SSD ×2', source: '假設：尺寸、接頭型號與位置待用戶資料',
    pallet: { w: 360, d: 250, t: 8, code: 'SSD35-02' }, ...ssdPair(), pcbT: 1.6,
    rows: [['SSD', 'SSD']], tilt0: { S1: 2.4, S2: 1.6 }, stubborn: { id: 'S2', residual: 1.4 },
    press: { single: 6, bar: 0 }, multiPad: null, insert: 'single', gapLimit: 0.10,
  },
};
export const DEFAULT_RECIPE = 'usb-2x8';
