// 單站組裝設備：機台（台面 900 mm）、雙抽屜吸塑盤（本體／上蓋／小葉片／大葉片）、組裝治具、上視遠心相機、
// 離子風嘴、NG 盒、外罩、三色燈、HMI。座標：x 向右、y 向上、z 朝作業員（前方）；手臂在後方中央。單位 mm。
import * as THREE from 'three';
import { block, cylinder, decal, screw } from './detail.js';
import { microTexture, batchStatic } from './surfaces.js';
import { PART, createBase, createBlade, createCover, createAssembly } from './product.js';

export const LAYOUT = {
  table: 900,
  robot: [0, 900, -300],
  nest: { x: 0, z: 80, floor: 925, top: 928 },       // 治具槽底＝本體底面
  upCam: { x: 0, z: -20, focus: 985 },                // 上視相機焦平面＝移動高度，吸嘴帶料經過即可取像
  travel: 985,                                        // 使用中工具尖端的移動高度
  ngBin: { x: 110, z: -10, top: 935 },
  drawerX: 400, drawer: { w: 330, z0: -485, z1: 315 },
  encl: { x: 720, z0: -640, z1: 340, h: 1900 },
};
/** 吸塑盤規格：格數、片距、槽深；抽屜 A 的中心（抽屜 B 以 x 鏡射） */
export const TRAYS = {
  base:  { name: '本體／成品盤', cols: 4, rows: 6, px: 36, pz: 27, pocket: [24, 23], floor: 909, cx: -477, cz: -392, size: [155, 172] },
  cover: { name: '上蓋盤', cols: 4, rows: 6, px: 30, pz: 26, pocket: [21, 20], floor: 912, cx: -320, cz: -392, size: [140, 172] },
  small: { name: '小葉片盤', cols: 6, rows: 8, px: 16, pz: 20, pocket: [12.5, 16], floor: 913.5, cx: -305, cz: -205, size: [110, 172] },
  large: { name: '大葉片盤', cols: 6, rows: 8, px: 16, pz: 20, pocket: [12.5, 16], floor: 913.5, cx: -425, cz: -205, size: [110, 172] },
};
export const TRAY_TOP = 915;
/** 治具中本體的定位（夾緊後靠 −x／−z 基準邊）；推塊接觸面 */
export const NEST_SEAT = { x: LAYOUT.nest.x - 0.15, y: LAYOUT.nest.floor + PART.base.h, z: LAYOUT.nest.z - 0.15 };
const NEST_PUSH = { x: PART.base.w / 2 - 0.15, z: PART.base.d / 2 - 0.15 };
/** 零件在格內的頂面高度（本體與上蓋的原點在頂面） */
const PART_TOP = { base: 909 + PART.base.h, cover: 912 + 1.45, small: 913.5 + PART.blade.t, large: 913.5 + PART.blade.t };
/** 第 i 格中心（世界座標，y＝零件頂面） */
export function pocket(kind, i, drawer = 'A') {
  const T = TRAYS[kind], c = i % T.cols, r = Math.floor(i / T.cols), s = drawer === 'A' ? 1 : -1;
  return new THREE.Vector3(s * T.cx + (c - (T.cols - 1) / 2) * T.px, PART_TOP[kind], T.cz + (r - (T.rows - 1) / 2) * T.pz);
}
export const pocketCount = kind => TRAYS[kind].cols * TRAYS[kind].rows;
/** 決定性的擺放偏移（料在格內的自然偏差），顯示用；本循環用到的格子另由 sequence 指定 */
function jitter(i, k) { const h = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453; return (h - Math.floor(h)) * 2 - 1; }

const matFrame = new THREE.MeshStandardMaterial({ color: 0x6b7480, roughness: 0.5, metalness: 0.6 });
const matAlu = new THREE.MeshStandardMaterial({ color: 0xb9c0c8, roughness: 0.38, metalness: 0.8, bumpMap: microTexture('brushed'), bumpScale: .02 });
const matPlate = new THREE.MeshStandardMaterial({ color: 0x8a939c, roughness: 0.45, metalness: 0.7, bumpMap: microTexture('brushed'), bumpScale: .015 });
const matDark = new THREE.MeshStandardMaterial({ color: 0x1e2226, roughness: 0.5, metalness: 0.4 });
const matCab = new THREE.MeshStandardMaterial({ color: 0xd9dcdf, roughness: 0.6, metalness: 0.2 });
const matBlue = new THREE.MeshStandardMaterial({ color: 0x2f5f9e, roughness: 0.5, metalness: 0.4 });
const matYellow = new THREE.MeshStandardMaterial({ color: 0xf2b21b, roughness: 0.6 });
const matESDmat = new THREE.MeshStandardMaterial({ color: 0x2d6b56, roughness: 0.9 });
const matNest = new THREE.MeshStandardMaterial({ color: 0x2b3038, roughness: 0.35, metalness: 0.55 });
const matPOM = new THREE.MeshStandardMaterial({ color: 0xe8e4d8, roughness: 0.6 });
const matTray = new THREE.MeshPhysicalMaterial({ color: 0xcfe6f2, roughness: 0.15, transmission: 0.2, transparent: true, opacity: 0.22, depthWrite: false, side: THREE.DoubleSide });
const matTrayEdge = new THREE.MeshStandardMaterial({ color: 0x9fc4d6, roughness: 0.3, transparent: true, opacity: 0.55 });
const matPC = new THREE.MeshPhysicalMaterial({ color: 0xcfe3ff, roughness: 0.1, transmission: 0.3, transparent: true, opacity: 0.12, depthWrite: false, side: THREE.DoubleSide });
const matFloor = new THREE.MeshStandardMaterial({ color: 0x1b2027, roughness: 0.95 });
const matGlass = new THREE.MeshPhysicalMaterial({ color: 0x9fc6ff, roughness: 0.05, transmission: 0.7, transparent: true, opacity: 0.5 });

/**
 * @param k 本循環使用的本體格號（0 起算）；ng 示意疊片時大葉片多用一格
 */
export function createCell(scene, { k = 9, ng = false } = {}) {
  const g = new THREE.Group(); g.name = 'cell'; scene.add(g);
  const { table: top } = LAYOUT, keepout = [], trayBoxes = [];
  const ko = (m, name) => { m.name = name; keepout.push(m); return m; };

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(9000, 6000), matFloor); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; g.add(floor);
  const grid = new THREE.GridHelper(9000, 45, 0x2c3540, 0x222a33); grid.position.y = 0.5; g.add(grid);
  for (const z of [1100, -1000]) block(g, [3600, 1, 40], [0, 1, z], matYellow);

  // ---- 機台：底櫃（RC8A／PLC／視覺 IPC）＋ 20 mm 台面 ----
  const { x: ex, z0, z1, h } = LAYOUT.encl;
  block(g, [2 * ex, top - 20, z1 - z0], [0, (top - 20) / 2, (z0 + z1) / 2], matCab);
  block(g, [2 * ex, 20, z1 - z0], [0, top - 10, (z0 + z1) / 2], matPlate);
  for (const x of [-480, -160, 160, 480]) block(g, [300, 640, 2], [x, 400, z1 + 1], matCab);
  decal(g, 560, 80, [0, 700, z1 + 2.5], [0, 0, 0], ['RC8A 手臂控制器 · KV-X PLC · 視覺 IPC', 'SIMULATION'], { bg: '#102635', color: '#65d7b8' });
  // 中央 ESD 墊（治具與相機區）
  block(g, [440, 1.2, 330], [0, top + 0.6, -10], matESDmat);

  // ---- 組裝治具：精密槽（−x／−z 為基準邊）、側推夾緊、導線槽、夾指避讓槽、真空 ----
  const N = LAYOUT.nest, nest = new THREE.Group(); nest.position.set(N.x, 0, N.z); g.add(nest);
  ko(block(nest, [110, N.floor - top - 1.2, 90], [0, (N.floor + top + 1.2) / 2, 0], matAlu), '治具座');
  const bw = PART.base.w + 0.3, bd = PART.base.d + 0.3, wallH = N.top - N.floor, wy = (N.floor + N.top) / 2, W = 12;
  // 槽壁（x 範圍、z 範圍）：−x 側留導線槽（z 0.3～5.3）、+x 側留推塊孔、±z 側中央留夾指避讓槽
  const X0 = -bw / 2, X1 = bw / 2, Z0 = -bd / 2, Z1 = bd / 2;
  const wall = (x0, x1, z0w, z1w, name) => ko(block(nest, [x1 - x0, wallH, z1w - z0w], [(x0 + x1) / 2, wy, (z0w + z1w) / 2], matNest), name);
  wall(X0 - W, X0, Z0 - W, 0.3, '治具基準壁 −x'); wall(X0 - W, X0, 5.3, Z1 + W, '治具基準壁 −x');
  wall(X1, X1 + W, Z0 - W, -6.5, '治具壁 +x'); wall(X1, X1 + W, 0.5, Z1 + W, '治具壁 +x');
  wall(X0, -4, Z0 - W, Z0, '治具基準壁 −z'); wall(4, X1, Z0 - W, Z0, '治具基準壁 −z');
  wall(X0, -4, Z1, Z1 + W, '治具壁 +z'); wall(7.5, X1, Z1, Z1 + W, '治具壁 +z');
  decal(nest, 40, 9, [0, (N.floor + top) / 2, 45.1], [0, 0, 0], 'NEST-01 · 快門治具', { color: '#2c5f86', center: true });
  block(nest, [36, 0.6, 5], [X0 - 18, N.floor - 0.2, 2.8], matDark);                // 導線槽底
  // 側推夾緊：+x、+z 兩支微型氣缸＋POM 推塊，把本體推靠 −x／−z 基準邊
  const clampX = new THREE.Group(), clampZ = new THREE.Group(); nest.add(clampX, clampZ);
  ko(block(nest, [16, 6, 10], [X1 + W + 8, N.floor + 3, -3], matBlue), '夾緊氣缸 X');
  ko(block(nest, [10, 6, 16], [4.5, N.floor + 3, Z1 + W + 8], matBlue), '夾緊氣缸 Z');
  block(clampX, [6 + W, 2.6, 5.4], [NEST_PUSH.x + (6 + W) / 2, N.floor + 1.6, -3], matPOM).name = '推塊 X';
  block(clampZ, [5.4, 2.6, 6 + W], [4.5, N.floor + 1.6, NEST_PUSH.z + (6 + W) / 2], matPOM).name = '推塊 Z';
  const vacLed = cylinder(nest, 1.5, 1.2, [-40, N.top + 0.6, -30], new THREE.MeshStandardMaterial({ color: 0x1b4f3d, emissive: 0x32d49b, emissiveIntensity: 0 }));
  decal(nest, 18, 6, [-40, N.top + 0.02, -24], [-Math.PI / 2, 0, 0], 'VAC', { color: '#9fd8ff', center: true });

  // ---- 上視遠心相機（台面下，經玻璃窗朝上）＋同軸環形光 ----
  const U = LAYOUT.upCam, uc = new THREE.Group(); uc.position.set(U.x, 0, U.z); g.add(uc);
  const ringMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.05 });
  ko(cylinder(uc, 30, 12, [0, top + 6, 0], matDark, 'y', 36), '上視環形光');
  const ringLed = new THREE.Mesh(new THREE.TorusGeometry(24, 2, 8, 40), ringMat); ringLed.rotation.x = Math.PI / 2; ringLed.position.y = top + 12.2; uc.add(ringLed);
  cylinder(uc, 18, 1, [0, top + 12.3, 0], matGlass, 'y', 32);
  cylinder(uc, 20, 90, [0, top - 70, 0], matDark, 'y', 28);          // 遠心鏡頭
  block(uc, [44, 44, 50], [0, top - 140, 0], matDark);                // 相機
  decal(g, 60, 12, [U.x + 48, top + 1.3, U.z], [-Math.PI / 2, 0, 0], 'UP-CAM', { color: '#9fd8ff', center: true });
  const upFlash = new THREE.PointLight(0xffffff, 0, 120, 1.5); upFlash.position.set(U.x, top + 30, U.z); g.add(upFlash);
  // 遠心鏡頭：正交投影，視野 24 × 20 mm（2448 × 2048、約 9.8 µm/px）
  const upCam = new THREE.OrthographicCamera(-12, 12, 10, -10, 1, 400);
  upCam.position.set(U.x, top + 13, U.z); upCam.up.set(0, 0, -1); upCam.lookAt(U.x, U.focus, U.z); g.add(upCam);
  // 離子風嘴：對準相機上方的吸嘴，消除葉片靜電
  const ion = new THREE.Group(); ion.position.set(U.x - 75, top, U.z); g.add(ion);
  ko(block(ion, [16, 40, 16], [0, 20, 0], matCab), '離子風嘴');
  ko(cylinder(ion, 4, 18, [12, 36, 0], matDark, 'x', 12), '離子風嘴噴頭');
  decal(ion, 14, 6, [0, 28, 8.1], [0, 0, 0], 'ION', { color: '#2c5f86', center: true });

  // ---- NG 盒 ----
  const B = LAYOUT.ngBin, bin = new THREE.Group(); bin.position.set(B.x, top, B.z); g.add(bin);
  const matRed = new THREE.MeshStandardMaterial({ color: 0xb8322a, roughness: 0.6 });
  for (const [s, p] of [[[54, B.top - top, 3], [0, (B.top - top) / 2, -18]], [[54, B.top - top, 3], [0, (B.top - top) / 2, 18]], [[3, B.top - top, 36], [-26, (B.top - top) / 2, 0]], [[3, B.top - top, 36], [26, (B.top - top) / 2, 0]]]) ko(block(bin, s, p, matRed), 'NG 盒');
  block(bin, [54, 2, 36], [0, 1, 0], matRed);
  decal(bin, 24, 10, [0, (B.top - top) / 2, 19.6], [0, 0, 0], 'NG', { color: '#fff', center: true, bold: true });

  // ---- 雙抽屜：全伸縮滑軌、往前拉出換盤；料盤區在抽屜後段 ----
  const statusLamps = {};
  for (const [name, s] of [['A', 1], ['B', -1]]) {
    const dg = new THREE.Group(); dg.name = 'drawer-' + name; g.add(dg);
    const X = -s * LAYOUT.drawerX, { w, z0: dz0, z1: dz1 } = LAYOUT.drawer, len = dz1 - dz0;
    block(dg, [w, 5, len], [X, top + 2.5, (dz0 + dz1) / 2], matAlu);
    for (const side of [-1, 1]) {
      ko(block(dg, [6, 26, len], [X + side * (w / 2 - 3), top + 13, (dz0 + dz1) / 2], matAlu), `抽屜 ${name} 側壁`);
      block(dg, [12, 14, len + 40], [X + side * (w / 2 + 8), top - 7, (dz0 + dz1) / 2 - 20], matDark);   // 滑軌
    }
    ko(block(dg, [w, 26, 6], [X, top + 13, dz0 + 3], matAlu), `抽屜 ${name} 後壁`);
    const front = block(dg, [w + 20, 90, 18], [X, top + 20, dz1 + 9], matCab); front.name = `抽屜 ${name} 面板`; keepout.push(front);
    block(dg, [140, 12, 14], [X, top + 30, dz1 + 26], matFrame);
    decal(dg, 120, 26, [X - 70 * s * 0, top + 52, dz1 + 18.2], [0, 0, 0], `抽屜 ${name}`, { bg: '#102635', color: '#9fd8ff', center: true });
    const lamp = cylinder(dg, 6, 4, [X + 120, top + 52, dz1 + 19], new THREE.MeshStandardMaterial({ color: 0x333333, emissive: 0x3dd68c, emissiveIntensity: 0 }), 'z', 18);
    statusLamps[name] = lamp;
    for (const x of [X - 150, X + 150]) screw(dg, [x, top + 5.3, dz1 - 20], 3);
    // 料盤
    const content = new THREE.Group(); content.name = 'tray-content-' + name;
    for (const [kind, T] of Object.entries(TRAYS)) {
      const cx = s * T.cx, [sw, sd] = T.size;
      // 吸塑盤：頂面板挖出格孔，每格是開口的杯（底＋四壁），零件不會被半透明面蓋住
      const sheet = new THREE.Shape(); sheet.moveTo(-sw / 2, -sd / 2); sheet.lineTo(sw / 2, -sd / 2); sheet.lineTo(sw / 2, sd / 2); sheet.lineTo(-sw / 2, sd / 2); sheet.closePath();
      for (let i = 0; i < pocketCount(kind); i++) {
        const p = pocket(kind, i, name), [pw, pd] = T.pocket, hx = p.x - cx, hz = -(p.z - T.cz), hole = new THREE.Path();
        hole.moveTo(hx - pw / 2, hz - pd / 2); hole.lineTo(hx + pw / 2, hz - pd / 2); hole.lineTo(hx + pw / 2, hz + pd / 2); hole.lineTo(hx - pw / 2, hz + pd / 2); hole.closePath(); sheet.holes.push(hole);
      }
      const sg = new THREE.ExtrudeGeometry(sheet, { depth: 0.6, bevelEnabled: false }); sg.rotateX(-Math.PI / 2); sg.translate(cx, TRAY_TOP - 0.6, T.cz);
      dg.add(new THREE.Mesh(sg, matTray));
      for (const [bw2, bd2, ox, oz] of [[sw, 2, 0, -sd / 2], [sw, 2, 0, sd / 2], [2, sd, -sw / 2, 0], [2, sd, sw / 2, 0]]) block(dg, [bw2, TRAY_TOP - 905, bd2], [cx + ox, (TRAY_TOP + 905) / 2, T.cz + oz], matTrayEdge);
      const box = new THREE.Box3(new THREE.Vector3(cx - sw / 2, 905, T.cz - sd / 2), new THREE.Vector3(cx + sw / 2, TRAY_TOP, T.cz + sd / 2)); box.name = `${T.name}（${name}）`; trayBoxes.push(box);
      decal(dg, 60, 9, [cx, TRAY_TOP + 0.05, T.cz + sd / 2 - 5], [-Math.PI / 2, 0, 0], `${T.name} ${name}`, { color: '#274b60', center: true });
      const n = pocketCount(kind);
      for (let i = 0; i < n; i++) {
        const p = pocket(kind, i, name), [pw, pd] = T.pocket;
        const ch = TRAY_TOP - T.floor, cy = (TRAY_TOP + T.floor) / 2;
        for (const [w, hh, d, x, y, z] of [[pw, 0.3, pd, p.x, T.floor - 0.15, p.z], [pw, ch, 0.3, p.x, cy, p.z - pd / 2], [pw, ch, 0.3, p.x, cy, p.z + pd / 2], [0.3, ch, pd, p.x - pw / 2, cy, p.z], [0.3, ch, pd, p.x + pw / 2, cy, p.z]]) {
          const m = new THREE.Mesh(new THREE.BoxGeometry(w, hh, d), matTray); m.position.set(x, y, z); content.add(m);
        }
        // 料況：抽屜 A 已用到第 k 顆，本循環使用的格子由 station 以動態零件表示；抽屜 B 滿料待命
        const used = name === 'A' ? { base: [k], cover: [k], small: [2 * k, 2 * k + 1], large: ng ? [2 * k, 2 * k + 1, 2 * k + 2] : [2 * k, 2 * k + 1] }[kind] : [];
        if (used.includes(i)) continue;
        let part = null;
        if (kind === 'base') part = name === 'A' && i < k ? createAssembly() : createBase();
        else if (name === 'B' || i > used[used.length - 1]) part = kind === 'cover' ? createCover() : createBlade(kind);
        if (!part) continue;
        part.position.set(p.x + jitter(i, 1) * 0.35, p.y, p.z + jitter(i, 2) * 0.35); part.rotation.y = jitter(i, 3) * 0.03;
        content.add(part);
      }
    }
    dg.add(content); batchStatic(content);
  }

  // ---- 外罩：鋁擠型框＋壓克力（可隱藏）、前門互鎖、三色燈、HMI、急停 ----
  const occ = new THREE.Group(); occ.name = 'occluders'; g.add(occ);
  for (const x of [-ex, ex]) for (const z of [z0, z1]) ko(block(occ, [40, h - top, 40], [x, (h + top) / 2, z], matFrame), '外罩立柱');
  for (const z of [z0, z1]) block(occ, [2 * ex, 40, 40], [0, h - 20, z], matFrame);
  for (const x of [-ex, ex]) block(occ, [40, 40, z1 - z0], [x, h - 20, (z0 + z1) / 2], matFrame);
  block(occ, [2 * ex, 40, 30], [0, top + 110, z1], matFrame);
  block(occ, [2 * ex, 2, z1 - z0], [0, h, (z0 + z1) / 2], matPC);
  block(occ, [2 * ex, h - top, 2], [0, (h + top) / 2, z0], matPC);
  block(occ, [2 * ex, h - top - 130, 2], [0, (h + top + 130) / 2, z1], matPC);
  for (const x of [-ex, ex]) block(occ, [2, h - top, z1 - z0], [x, (h + top) / 2, (z0 + z1) / 2], matPC);
  block(occ, [60, 22, 30], [0, 1500, z1 + 18], matDark); decal(occ, 70, 14, [0, 1525, z1 + 34], [0, 0, 0], '前門互鎖', { center: true });
  block(g, [210, 150, 16], [ex - 150, 1250, z1 + 12], new THREE.MeshStandardMaterial({ color: 0x0c1a2b, emissive: 0x1f4f8f, emissiveIntensity: 0.55 }));
  decal(g, 190, 125, [ex - 150, 1250, z1 + 21], [0, 0, 0], ['快門組裝站', 'HSR065 · 雙抽屜', 'SIMULATION'], { bg: '#102635', color: '#65d7b8' });
  cylinder(g, 22, 12, [ex - 150, 1110, z1 + 10], matYellow, 'z'); cylinder(g, 15, 18, [ex - 150, 1110, z1 + 20], new THREE.MeshStandardMaterial({ color: 0xd53730 }), 'z');
  const tower = new THREE.Group(); tower.position.set(ex - 80, h + 40, z0 + 80); g.add(tower);
  cylinder(tower, 8, 80, [0, 0, 0], matFrame);
  const towerLamps = {};
  [['red', 0xff3b3b, 110], ['yellow', 0xffb020, 75], ['green', 0x3dd68c, 40]].forEach(([key, c, y]) => {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(22, 22, 34, 20), new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.08, transparent: true, opacity: 0.85 }));
    m.position.y = y; tower.add(m); towerLamps[key] = m;
  });

  const ringFlash = on => { ringMat.emissiveIntensity = on ? 1.6 : 0.05; upFlash.intensity = on ? 40 : 0; };
  return {
    group: g, occluders: occ, keepout, trayBoxes, upCam,
    tower: { set(key) { for (const n in towerLamps) towerLamps[n].material.emissiveIntensity = n === key ? 1.6 : 0.08; } },
    setUpFlash: ringFlash,
    setClamp(v) { clampX.position.x = (1 - v) * 3; clampZ.position.z = (1 - v) * 3; },
    setVacuum(on) { vacLed.material.emissiveIntensity = on ? 1.4 : 0; },
    setDrawers(a, b) { statusLamps.A.material.emissive.setHex(a); statusLamps.A.material.emissiveIntensity = 1.2; statusLamps.B.material.emissive.setHex(b); statusLamps.B.material.emissiveIntensity = 1.2; },
  };
}
