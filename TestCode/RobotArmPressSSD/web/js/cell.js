// 壓合站設備：上游／本站／下游 SMT 雙邊輸送（後軌固定為基準邊、前軌依配方調寬）、止擋、頂升支撐、
// 固定全局相機、機台底櫃、手臂座、外罩、三色燈、HMI。
// 座標：x 沿流向（上游 −x → 下游 +x）、y 向上、z 橫向（手臂在 −z 後側，作業員在 +z 前側）。單位 mm。
import * as THREE from 'three';
import { block, cylinder, decal, screw } from './detail.js';
import { microTexture } from './surfaces.js';

export const LAYOUT = {
  conveyorTop: 900,                   // SMT 輸送面（載盤底面）
  rearInner: -101,                    // 後軌內側面（固定基準邊）
  segments: [[-1600, -620], [-600, 600], [620, 1600]], // 上游、本站模組、下游
  stopFace: 156,                      // 止擋面：載盤前緣停在這裡（各機種共用）
  flowGap: 1000,                      // 上下游等待位置與本站的距離
  liftStroke: 3,                      // 頂升後載盤貼住軌道壓邊
  entrySensorX: -430, posSensorX: 120,
  robot: [0, 820, -430],              // 手臂座面中心
  encl: { x: 600, z0: -760, z1: 420, h: 2050 },
  globalCam: [10, 1700, 20],          // 全局相機鏡頭位置（朝下）
};
/** 依配方算出載盤在本站的中心位置與前軌內側面 */
export function palletPlacement(recipe) {
  const { w, d } = recipe.pallet;
  return { x: LAYOUT.stopFace - w / 2, z: LAYOUT.rearInner + d / 2, frontInner: LAYOUT.rearInner + d + 2 };
}

const matFrame = new THREE.MeshStandardMaterial({ color: 0x6b7480, roughness: 0.5, metalness: 0.6 });
const matAlu   = new THREE.MeshStandardMaterial({ color: 0xb9c0c8, roughness: 0.4, metalness: 0.8, bumpMap: microTexture('brushed'), bumpScale: .025 });
const matBelt  = new THREE.MeshStandardMaterial({ color: 0x2e7d56, roughness: 0.75 });
const matDark  = new THREE.MeshStandardMaterial({ color: 0x1e2226, roughness: 0.5, metalness: 0.4 });
const matCab   = new THREE.MeshStandardMaterial({ color: 0xd9dcdf, roughness: 0.6, metalness: 0.2 });
const matBlue  = new THREE.MeshStandardMaterial({ color: 0x2f5f9e, roughness: 0.5, metalness: 0.4 });
const matYellow= new THREE.MeshStandardMaterial({ color: 0xf2b21b, roughness: 0.6 });
const matPin   = new THREE.MeshStandardMaterial({ color: 0xd0d5da, roughness: 0.3, metalness: 0.9 });
const matPC    = new THREE.MeshPhysicalMaterial({ color: 0xcfe3ff, roughness: 0.1, transmission: 0.3, transparent: true, opacity: 0.12, depthWrite: false, side: THREE.DoubleSide });
const matFloor = new THREE.MeshStandardMaterial({ color: 0x1b2027, roughness: 0.95 });

export function createCell(scene, recipe) {
  const g = new THREE.Group(); g.name = 'cell'; scene.add(g);
  const { conveyorTop: top, rearInner } = LAYOUT, place = palletPlacement(recipe), frontInner = place.frontInner, keepout = [];
  const ko = (m, name) => { m.name = name; keepout.push(m); return m; };

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(9000, 6000), matFloor); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; g.add(floor);
  const grid = new THREE.GridHelper(9000, 45, 0x2c3540, 0x222a33); grid.position.y = 0.5; g.add(grid);
  for (const z of [900, -1100]) block(g, [4200, 1, 40], [0, 1, z], matYellow);

  // ---- 輸送段：後軌固定、前軌依配方寬度；平皮帶、壓邊、端輪、腳架 ----
  const beltMarks = [];
  const railZ = { rear: { rail: rearInner - 10, lip: rearInner + 3, belt: rearInner + 4 }, front: { rail: frontInner + 10, lip: frontInner - 3, belt: frontInner - 4 } };
  LAYOUT.segments.forEach(([x0, x1], si) => {
    const len = x1 - x0, cx = (x0 + x1) / 2, station = si === 1;
    for (const side of ['rear', 'front']) {
      const z = railZ[side];
      const rail = block(g, [len, 50, 20], [cx, top - 13, z.rail], matAlu);
      const lip = block(g, [len, 3, 6], [cx, top + LAYOUT.liftStroke + 7.5, z.lip], matAlu);
      for(let x=x0+65;x<x1-25;x+=130) screw(g,[x,top+12.3,z.rail],3.2);
      block(g,[len-4,1.4,.3],[cx,top-7,z.rail+(side==='front'?10.05:-10.05)],matDark);
      block(g, [len - 30, 2, 8], [cx, top - 1, z.belt], matBelt);
      for (const x of [x0 + 15, x1 - 15]) cylinder(g, 14, 10, [x, top - 15, z.belt], matDark, 'z');
      if (station) { ko(rail, side === 'rear' ? '後軌' : '前軌'); ko(lip, side === 'rear' ? '後軌壓邊' : '前軌壓邊'); }
      for (const x of [x0 + 40, x1 - 40]) { block(g, [40, top - 38, 40], [x, (top - 38) / 2, z.rail], matFrame); block(g, [90, 10, 70], [x, 5, z.rail], matDark); }
    }
    for (const x of [x0 + 40, x1 - 40]) block(g, [30, 30, frontInner - rearInner + 40], [x, top - 60, (rearInner + frontInner) / 2], matFrame);
    block(g, [120, 90, 80], [x1 - 120, top - 95, rearInner - 70], matBlue);            // 皮帶驅動
    const marks = new THREE.Group(); g.add(marks); beltMarks.push(marks);
    for (let x = x0 + 30; x < x1 - 30; x += 60) for (const side of ['rear', 'front']) block(marks, [3, 0.6, 7], [x, top + 0.3, railZ[side].belt], matAlu);
    decal(g, 150, 22, [cx, top - 20, frontInner + 20.5], [0, 0, 0], si === 0 ? '上游 · 前站放置 USB' : si === 1 ? 'USB 壓合＋檢查站' : '下游 · 迴焊爐', { bg: '#122d3c', color: '#9fd8ff', center: true });
  });
  // 寬度調整：伺服＋滾珠螺桿（依配方自動調寬）
  for (const x of [-450, 450]) { cylinder(g, 8, frontInner - rearInner + 80, [x, top - 55, (rearInner + frontInner) / 2 + 10], matPin, 'z', 12); block(g, [50, 50, 60], [x, top - 55, frontInner + 70], matBlue); }
  decal(g, 120, 16, [450, top - 20, frontInner + 101], [0, 0, 0], `軌寬 ${recipe.pallet.d} mm`, { bg: '#102635', color: '#9fd8ff', center: true });

  // ---- 本站：止擋（前緣定位）、頂升支撐板（無定位銷，後軌為基準邊）、感測器 ----
  block(g, [30, 40, 30], [LAYOUT.stopFace + 12, top - 40, place.z], matDark);
  const stopPin = new THREE.Group(); g.add(stopPin);
  ko(cylinder(stopPin, 6, 26, [LAYOUT.stopFace + 6, top - 1, place.z], matPin, 'y', 16), '止擋');
  const lift = new THREE.Group(); g.add(lift);
  block(lift, [240, 8, 160], [10, top - 8, rearInner + 85], matAlu);                 // 支撐板：取最小載盤可涵蓋的範圍
  for (const x of [-80, 100]) block(g, [40, 60, 40], [x, top - 50, rearInner + 85], matDark);  // 頂升氣缸
  const sensors = [];
  for (const [x, name] of [[LAYOUT.entrySensorX, '入口'], [LAYOUT.posSensorX, '到位']]) {
    block(g, [16, 18, 24], [x, top + 22, rearInner - 14], matBlue);
    const led = cylinder(g, 3, 2, [x, top + 32, rearInner - 14], new THREE.MeshStandardMaterial({ color: 0x1b4f3d, emissive: 0x32d49b, emissiveIntensity: 0 }));
    sensors.push({ x, name, led });
  }

  // ---- 機台底櫃（RC8A、PLC、IPC）＋手臂座 ----
  const [rx, ry, rz] = LAYOUT.robot, { x: ex, z0, z1, h } = LAYOUT.encl;
  ko(block(g, [2 * ex, ry - 20, -240 - z0], [0, (ry - 20) / 2, (z0 - 240) / 2], matCab), '機台底櫃');
  block(g, [300, 20, 300], [rx, ry - 10, rz], matDark);
  for (const x of [-420, -140, 140, 420]) block(g, [240, 700, 2], [x, 420, -239], matCab);
  decal(g, 520, 90, [0, 560, -238], [0, 0, 0], ['RC8A 手臂控制器 · KV-X PLC · 視覺 IPC', 'SIMULATION'], { bg: '#102635', color: '#65d7b8' });

  // ---- 固定全局相機：20MP＋20 mm 鏡頭，距輸送面約 800 mm，視野約 530 × 355 mm ----
  const [gx, gy, gz] = LAYOUT.globalCam;
  ko(block(g, [40, 40, z1 - z0], [gx, h - 60, (z0 + z1) / 2], matFrame), '全局相機橫樑');
  ko(block(g, [30, h - 80 - (gy + 90), 30], [gx, (h - 80 + gy + 90) / 2, gz], matFrame), '全局相機吊桿');
  const gcam = new THREE.Group(); gcam.position.set(gx, gy, gz); g.add(gcam);
  ko(block(gcam, [44, 47, 34], [0, 60, 0], matDark), '全局相機');
  ko(cylinder(gcam, 16, 36, [0, 18, 0], new THREE.MeshStandardMaterial({ color: 0x1c1f23, roughness: 0.4, metalness: 0.5 }), 'y', 20), '全局相機鏡頭');
  const gLightMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.05 });
  for (const s of [-1, 1]) ko(block(gcam, [260, 12, 30], [0, 20, s * 70], gLightMat), '全局光源');
  const gFlash = new THREE.SpotLight(0xffffff, 0, 1400, 0.45, 0.5, 1); gFlash.target.position.set(0, -800, 0); gcam.add(gFlash, gFlash.target);
  const globalCam = new THREE.PerspectiveCamera(2 * Math.atan(8.8 / 2 / 20) * 180 / Math.PI, 1.5, 50, 3000);
  globalCam.position.set(gx, gy, gz); globalCam.up.set(0, 0, -1); globalCam.lookAt(gx, top, gz); g.add(globalCam);

  // ---- 外罩：鋁擠型框＋壓克力（可隱藏）、前門互鎖、三色燈、HMI、急停 ----
  const occ = new THREE.Group(); occ.name = 'occluders'; g.add(occ);
  for (const x of [-ex, ex]) for (const z of [z0, z1]) ko(block(occ, [40, h, 40], [x, h / 2, z], matFrame), '外罩立柱');
  for (const z of [z0, z1]) ko(block(occ, [2 * ex, 40, 40], [0, h - 20, z], matFrame), '外罩橫樑');
  for (const x of [-ex, ex]) ko(block(occ, [40, 40, z1 - z0], [x, h - 20, (z0 + z1) / 2], matFrame), '外罩橫樑');
  block(occ, [2 * ex, 2, z1 - z0], [0, h, (z0 + z1) / 2], matPC);
  block(occ, [2 * ex, h - 800, 2], [0, 800 + (h - 800) / 2, z0], matPC);
  block(occ, [2 * ex, h - 1000, 2], [0, 1000 + (h - 1000) / 2, z1], matPC);
  block(occ, [2 * ex, 40, 30], [0, 1000, z1], matFrame);
  block(occ, [2 * ex, 900, 2], [0, 510, z1], matPC);
  for (const x of [-ex, ex]) { block(occ, [2, h - 980, z1 - z0], [x, 980 + (h - 980) / 2, (z0 + z1) / 2], matPC); block(occ, [2, 780, z1 - z0], [x, 450, (z0 + z1) / 2], matPC); }
  block(occ, [60, 22, 30], [ex - 120, 1520, z1 + 18], matDark); decal(occ, 70, 14, [ex - 120, 1545, z1 + 34], [0, 0, 0], '前門互鎖', { center: true });
  block(g, [210, 150, 16], [ex - 150, 1300, z1 + 12], new THREE.MeshStandardMaterial({ color: 0x0c1a2b, emissive: 0x1f4f8f, emissiveIntensity: 0.55 }));
  decal(g, 190, 125, [ex - 150, 1300, z1 + 21], [0, 0, 0], ['USB 壓合站', recipe.short, 'SIMULATION'], { bg: '#102635', color: '#65d7b8' });
  cylinder(g, 22, 12, [ex - 150, 1150, z1 + 10], matYellow, 'z'); cylinder(g, 15, 18, [ex - 150, 1150, z1 + 20], new THREE.MeshStandardMaterial({ color: 0xd53730 }), 'z');
  const tower = new THREE.Group(); tower.position.set(ex - 80, h + 40, z0 + 80); g.add(tower);
  cylinder(tower, 8, 80, [0, 0, 0], matFrame);
  const towerLamps = {};
  [['red', 0xff3b3b, 110], ['yellow', 0xffb020, 75], ['green', 0x3dd68c, 40]].forEach(([k, c, y]) => {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(22, 22, 34, 20), new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.08, transparent: true, opacity: 0.85 }));
    m.position.y = y; tower.add(m); towerLamps[k] = m;
  });

  return {
    group: g, occluders: occ, keepout, sensors, globalCam, place,
    tower: { set(k) { for (const n in towerLamps) towerLamps[n].material.emissiveIntensity = n === k ? 1.6 : 0.08; } },
    setStop(v) { stopPin.position.y = (v - 1) * 24; },
    setLift(v) { lift.position.y = v * (LAYOUT.liftStroke + 4); },
    setGlobalFlash(on) { gFlash.intensity = on ? 1800 : 0; gLightMat.emissiveIntensity = on ? 1.2 : 0.05; },
    updateTransport(x, sensorOn) {
      for (const marks of beltMarks) marks.position.x = ((x % 60) + 60) % 60;
      for (const s of sensors) s.led.material.emissiveIntensity = sensorOn(s) ? 1.4 : 0;
    },
  };
}
