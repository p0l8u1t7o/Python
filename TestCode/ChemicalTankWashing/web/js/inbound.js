// 散桶入庫區：西牆捲門、入庫棧板座、懸臂吊（夾桶具）、油桶台車與作業員。
// 懸臂吊方位 a（度）：手臂方向 (cos a, −sin a)，與 AGV 方位同一定義；r 為吊點半徑，y 為桶中心高度。
import * as THREE from 'three';
import { INBOUND, DRUM, ROOM } from './layout.js';
import { MAT, box, cyl, plate, D2R } from './parts.js';

export const DOLLY_H = 120;
// 懸臂吊吊點對應的桶中心
export const jibPoint = (a, r, y) => new THREE.Vector3(INBOUND.jib.x + r * Math.cos(a * D2R), y, INBOUND.jib.z - r * Math.sin(a * D2R));
// 由桶中心反推懸臂吊方位與半徑
export function jibTarget(x, z) { const dx = x - INBOUND.jib.x, dz = z - INBOUND.jib.z; return { a: Math.atan2(-dz, dx) / D2R, r: Math.hypot(dx, dz) }; }

function person(parent, color = 0x2f6fb5) {
  const g = new THREE.Group(); parent.add(g);
  const suit = new THREE.MeshStandardMaterial({ color, roughness: .8 });
  for (const s of [-1, 1]) box(g, 140, 820, 160, suit, 0, 410, s * 110);
  cyl(g, 190, 640, suit, 0, 1150, 0, 'y', 14);
  cyl(g, 110, 220, new THREE.MeshStandardMaterial({ color: 0xe0b48f, roughness: .7 }), 0, 1580, 0, 'y', 14);
  cyl(g, 125, 90, MAT.yellow, 0, 1700, 0, 'y', 16);
  for (const s of [-1, 1]) { const arm = box(g, 110, 560, 110, suit, 200, 1180, s * 230); arm.rotation.z = -.9; }
  return g;
}

export function createInbound(scene) {
  const group = new THREE.Group(); group.name = 'inbound'; scene.add(group);
  const ib = INBOUND, [d0, d1] = ib.door;
  // 西牆捲門：門框＋捲門箱（開口）
  for (const z of [d0, d1]) box(group, 260, 2600, 120, MAT.yellow, -60, 1300, z);
  box(group, 360, 380, d1 - d0 + 240, MAT.steelDark, -80, 2800, (d0 + d1) / 2);
  for (let z = d0 + 150; z < d1; z += 300) box(group, 20, 60, 150, MAT.black, 20, 2620, z);
  plate(group, ['散桶入庫門'], 900, 160, [60, 3200, (d0 + d1) / 2], Math.PI / 2, { w: 640, h: 110 });
  // 入庫棧板座
  box(group, 1300, ib.stand, 1300, MAT.steelDark, ib.x, ib.stand / 2, ib.z);
  for (const [dx, dz] of [[-660, 300], [-660, -300], [300, -660], [-300, -660]]) box(group, dx ? 40 : 300, 200, dx ? 300 : 40, MAT.yellow, ib.x + dx, ib.stand + 100, ib.z + dz);
  // 懸臂吊
  const j = ib.jib;
  cyl(group, 130, j.armY + 200, MAT.steelOrange, j.x, (j.armY + 200) / 2, j.z, 'y', 20);
  box(group, 600, 40, 600, MAT.steelDark, j.x, 20, j.z);
  const arm = new THREE.Group(); arm.position.set(j.x, j.armY, j.z); group.add(arm);
  box(arm, j.reach, 200, 120, MAT.steelOrange, j.reach / 2, 0, 0);
  box(arm, 300, 160, 160, MAT.steelDark, 0, 120, 0);
  const trolley = new THREE.Group(); arm.add(trolley);
  box(trolley, 220, 120, 220, MAT.black, 0, -150, 0);
  const chain = cyl(trolley, 10, 1, MAT.steel, 0, 0, 0, 'y', 6);
  const clamp = new THREE.Group(); trolley.add(clamp);
  box(clamp, 520, 50, 120, MAT.steelDark, 0, 25, 0);
  const claws = [-1, 1].map(s => { const c = box(clamp, 30, 120, 100, MAT.yellow, 0, -30, 0); c.userData.s = s; return c; });
  // 油桶台車（四輪平台）＋作業員
  const dolly = new THREE.Group(); group.add(dolly);
  box(dolly, 640, 40, 640, MAT.steelBlue, 0, DOLLY_H - 20, 0);
  for (const [x, z] of [[-250, -250], [250, -250], [-250, 250], [250, 250]]) cyl(dolly, 40, 40, MAT.black, x, 40, z, 'z', 12);
  box(dolly, 30, 900, 30, MAT.steel, -340, 500, -200); box(dolly, 30, 900, 30, MAT.steel, -340, 500, 200); box(dolly, 30, 30, 430, MAT.steel, -340, 950, 0);
  const worker = person(group);
  plate(group, ['入庫棧板（AGV 取走）'], 900, 140, [ib.x, 450, ib.z + 660], 0, { w: 640, h: 100 });
  return {
    group,
    set({ dollyX, a, r, y, clamp: c, workerX = dollyX - 800, workerZ = ib.dolly.z }) {
      dolly.position.set(dollyX, 0, ib.dolly.z);
      worker.position.set(workerX, 0, workerZ);
      arm.rotation.y = a * D2R; trolley.position.x = r;
      const clampY = y + DRUM.H / 2 + 40 - j.armY;   // 夾具在桶頂 L 環上方
      clamp.position.y = clampY; chain.scale.y = Math.max(1, -clampY - 150); chain.position.y = (clampY - 150) / 2;
      for (const k of claws) k.position.x = k.userData.s * (DRUM.R - 10 + (1 - c) * 60);
    },
  };
}
