// 洗桶區建築：地坪、牆、門窗、柱、分區標線、樓高與尺寸標註。
import * as THREE from 'three';
import { ROOM, OUTLINE, DOORS, COLUMN, AISLE, AGV, FOOTPRINTS, WALKWAYS, FILLING, SHUTTLE_BAY, WASTE, RACK, AGV_TURNS, agvSweep, pointInPolygon, doorSwing, ROBOT, rackBlocks, FENCE, INBOUND, INBOUND_AREA, inboundArcPoses } from './layout.js';
import { block, floorText, rod } from '@core/geom/shapes.js';
import { MAT } from '@core/geom/materials.js';

const line = (pts, color, opacity = 1) => {
  const g = new THREE.BufferGeometry().setFromPoints(pts.map(p => new THREE.Vector3(...p)));
  return new THREE.Line(g, new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity }));
};
// 地面分區：每塊固定 renderOrder 與 polygonOffset，重疊的半透明面不會隨視角翻轉排序而閃爍
let zoneOrder = 1;
function zone(parent, [x0, z0, x1, z1], color, opacity = .14, y = 3) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0, z1 - z0), new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -zoneOrder }));
  m.rotation.x = -Math.PI / 2; m.position.set((x0 + x1) / 2, y, (z0 + z1) / 2); m.renderOrder = zoneOrder++; parent.add(m);
  parent.add(Object.assign(line([[x0, y + 1, z0], [x1, y + 1, z0], [x1, y + 1, z1], [x0, y + 1, z1], [x0, y + 1, z0]], color, .8), { renderOrder: zoneOrder++ }));
  return m;
}
function ring(parent, x, z, r, color, opacity = .7, y = 8) {
  const m = new THREE.Mesh(new THREE.RingGeometry(r - 22, r + 22, 128), new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide }));
  m.rotation.x = -Math.PI / 2; m.position.set(x, y, z); m.renderOrder = 2; parent.add(m); return m;
}

export function createBuilding(scene) {
  const group = new THREE.Group(); group.name = 'building'; scene.add(group);
  // 地坪
  const outside = new THREE.Mesh(new THREE.PlaneGeometry(60000, 60000), MAT.floorOut);
  outside.rotation.x = -Math.PI / 2; outside.position.set(5000, -2, 8000); outside.receiveShadow = true; group.add(outside);
  const shape = new THREE.Shape(OUTLINE.map(([x, z]) => new THREE.Vector2(x, -z)));
  const floor = new THREE.Mesh(new THREE.ShapeGeometry(shape), MAT.floor); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; group.add(floor);
  // 更衣室地坪（區外，僅示意）
  const lockerShape = new THREE.Shape([[-2050, 4700], [1770, 4700], [1770, 8520], [-2050, 8520]].map(([x, z]) => new THREE.Vector2(x, -z)));
  const locker = new THREE.Mesh(new THREE.ShapeGeometry(lockerShape), new THREE.MeshStandardMaterial({ color: 0x59636c, roughness: .9 }));
  locker.rotation.x = -Math.PI / 2; locker.position.y = -1; group.add(locker);

  // 牆：沿內牆輪廓外推 100 mm；半透明以便觀察
  for (let i = 0; i < OUTLINE.length; i++) {
    const [ax, az] = OUTLINE[i], [bx, bz] = OUTLINE[(i + 1) % OUTLINE.length];
    const L = Math.hypot(bx - ax, bz - az), dx = (bx - ax) / L, dz = (bz - az) / L;
    let nx = -dz, nz = dx; const mx = (ax + bx) / 2, mz = (az + bz) / 2;
    if (pointInPolygon([mx + nx * 20, mz + nz * 20])) { nx = -nx; nz = -nz; }
    const yaw = Math.atan2(-dz, dx);
    for (const [h, mat, y] of [[ROOM.H, MAT.wall, ROOM.H / 2], [160, MAT.wallBase, 80]]) {
      if (ax === 0 && bx === 0 && Math.min(az, bz) < INBOUND.door[0] && Math.max(az, bz) > INBOUND.door[1]) {
        const low = Math.min(az, bz), high = Math.max(az, bz), [d0, d1] = INBOUND.door;
        for (const [za, zb] of [[low, d0], [d1, high]]) block(group, [ROOM.wall, h, zb - za], [nx * ROOM.wall / 2, y, (za + zb) / 2], mat);
        if (h === ROOM.H) block(group, [ROOM.wall, ROOM.H - 2600, d1 - d0], [nx * ROOM.wall / 2, (ROOM.H + 2600) / 2, (d0 + d1) / 2], mat);
      } else {
        const w = new THREE.Mesh(new THREE.BoxGeometry(L + ROOM.wall, h, ROOM.wall), mat);
        w.position.set(mx + nx * ROOM.wall / 2, y, mz + nz * ROOM.wall / 2); w.rotation.y = yaw; w.receiveShadow = true; group.add(w);
      }
    }
  }
  // 更衣室西牆與南牆（輪廓以外）
  block(group, [ROOM.wall, ROOM.H, 3820], [-2150, ROOM.H / 2, 6610], MAT.wall);
  // 樓高輪廓線
  group.add(line([...OUTLINE, OUTLINE[0]].map(([x, z]) => [x, ROOM.H, z]), 0x8fb6c8, .55));
  const ceiling = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color: 0x9fc3d6, transparent: true, opacity: .07, side: THREE.DoubleSide, depthWrite: false }));
  ceiling.rotation.x = -Math.PI / 2; ceiling.position.y = ROOM.H; ceiling.visible = false; group.add(ceiling);

  // 門（門扇以 30° 半開示意）＋開啟範圍
  for (const d of DOORS) {
    const w = d.x1 - d.x0;
    const leaf = block(group, [w, 2100, 45], [0, 1050, 0], MAT.door);
    const hinge = new THREE.Group(); hinge.position.set(d.x0, 0, d.z); group.add(hinge); hinge.add(leaf); leaf.position.x = w / 2;
    hinge.rotation.y = -d.dir * 30 * Math.PI / 180;
    const pts = []; for (let i = 0; i <= 24; i++) { const a = i / 24 * Math.PI / 2; pts.push([d.x0 + w * Math.cos(a), 6, d.z + d.dir * w * Math.sin(a)]); }
    group.add(line([[d.x0, 6, d.z], ...pts, [d.x0, 6, d.z]], 0xffd27a, .8));
    const s = doorSwing(d); zone(group, s, 0xffd27a, .08, 2);
  }
  // 窗（東牆一段、南牆五樘）
  block(group, [30, 1500, 5400], [ROOM.W + 105, 1650, 7250], MAT.window);
  for (const x of [-1600, 400, 2400, 7200, 9800]) block(group, [1700, 1500, 30], [x + 850, 1650, ROOM.D + 105], MAT.window);
  // 柱
  block(group, [COLUMN.size, ROOM.H, COLUMN.size], [COLUMN.x, ROOM.H / 2, COLUMN.z], MAT.column);
  // 柱面 AGV 充電櫃
  { const [x0, z0, x1, z1, h] = FOOTPRINTS.charger; block(group, [x1 - x0, h, z1 - z0], [(x0 + x1) / 2, h / 2, (z0 + z1) / 2], MAT.cabinet); block(group, [120, 120, 6], [(x0 + x1) / 2, h - 200, z1 + 3], MAT.green); }

  // 分區
  const zones = new THREE.Group(); group.add(zones);
  zone(zones, [0, 0, ROOM.W, RACK.zFront], 0x4aa8ff, .06);
  zone(zones, [1770, AISLE.z0, ROOM.W, AISLE.z1], 0xffc233, .1);
  for (const w of WALKWAYS) zone(zones, w, 0x3dd68c, .12);
  zone(zones, FILLING, 0x9aa7b3, .12);
  zone(zones, INBOUND_AREA, 0xb07cff, .12);
  zone(zones, SHUTTLE_BAY, 0x7d8b97, .12);
  zone(zones, WASTE.bund, 0xff9f43, .12);
  const cell = new THREE.Shape(FENCE.map(([x, z]) => new THREE.Vector2(x, -z)));
  const cellFloor = new THREE.Mesh(new THREE.ShapeGeometry(cell), new THREE.MeshBasicMaterial({ color: 0x4fd1e8, transparent: true, opacity: .07, depthWrite: false }));
  cellFloor.rotation.x = -Math.PI / 2; cellFloor.position.y = 3; zones.add(cellFloor);
  floorText(zones, ['倉儲區 · 穿梭車密集架', '第 1 道 3 深，其餘 4 深 × 3 層'], 6300, 5050, 3000, 520);
  floorText(zones, 'AGV 走道 3.6 m', 6000, 8600, 2200, 300, { fg: '#ffd56a' });
  floorText(zones, '人車共用通道', 2335, 6900, 1800, 260, { fg: '#9ff0c6', rot: Math.PI / 2 });
  floorText(zones, ['散桶入庫作業區', '台車推入 → 懸臂吊上棧板'], 1050, 4150, 1900, 420, { fg: '#d7bcff' });
  floorText(zones, ['裝填區', '下一站・不在本案範圍'], 10700, 14900, 1300, 520, { fg: '#c7d1da', rot: Math.PI / 2 });
  floorText(zones, ['預留區', '控制櫃・廢液槽西側'], 1000, 13300, 3000, 800, { fg: '#8796a3' });
  floorText(zones, ['穿梭車', '充電／維修'], 7900, 2400, 1400, 600, { fg: '#c7d1da' });
  floorText(zones, '更衣室 106', -150, 6600, 2000, 300, { fg: '#c7d1da' });
  floorText(zones, '清洗區（DCS＋圍籬）', 7900, 13300, 2300, 260, { fg: '#8fe5f2' });

  // 尺寸與淨空標註（可切換）
  const dims = new THREE.Group(); dims.visible = false; group.add(dims);
  const dimLabels = [];
  // 尺寸線用細圓桿（WebGL 線寬固定 1 px，俯視全場時看不到）
  const dimMat = c => new THREE.MeshBasicMaterial({ color: c });
  const dim = (a, b, text, color = 0x7fd0ff) => {
    const m = dimMat(color); rod(dims, a, b, 18, m, 6);
    const d = new THREE.Vector3(...b).sub(new THREE.Vector3(...a)).normalize();
    const n = Math.abs(d.y) > .9 ? new THREE.Vector3(150, 0, 0) : new THREE.Vector3(-d.z, 0, d.x).multiplyScalar(150);
    for (const p of [a, b]) rod(dims, [p[0] - n.x, p[1], p[2] - n.z], [p[0] + n.x, p[1], p[2] + n.z], 14, m, 6);
    dimLabels.push({ text, pos: new THREE.Vector3(...a).add(new THREE.Vector3(...b)).multiplyScalar(.5) });
  };
  dim([0, 30, -700], [ROOM.W, 30, -700], '12,560');
  dim([ROOM.W + 700, 30, 0], [ROOM.W + 700, 30, ROOM.D], '15,520');
  dim([2400, 30, 0], [2400, 30, RACK.zFront], '貨架深 5,400');
  dim([2400, 30, AISLE.z0], [2400, 30, AISLE.z1], '走道 3,600');
  dim([1770, 30, 8200], [2900, 30, 8200], '通道 1,130');
  const [bw] = rackBlocks();
  dim([bw[0] - 300, 0, RACK.zFront + 200], [bw[0] - 300, RACK.levels[2] + 150 + 935, RACK.zFront + 200], '貨頂 3,895', 0xffd27a);
  dim([bw[0] - 600, 0, RACK.zFront + 200], [bw[0] - 600, ROOM.H, RACK.zFront + 200], '樓高 4,500', 0xffd27a);
  dim([COLUMN.x - 400, 30, COLUMN.z + 900], [COLUMN.x + 400, 30, COLUMN.z + 900], '柱 800（圖面量測）', 0xff9f9f);
  // AGV 地面充電板（齊平）
  zone(group, [AGV.charger.x - 500, AGV.charger.z - 550, AGV.charger.x + 1300, AGV.charger.z + 550], 0x3dd68c, .25, 4);
  // AGV 入庫弧線（中心線）
  for (const p of inboundArcPoses(40)) { const m = new THREE.Mesh(new THREE.CircleGeometry(28, 10), new THREE.MeshBasicMaterial({ color: 0xd7bcff })); m.rotation.x = -Math.PI / 2; m.position.set(p.x, 9, p.z); dims.add(m); }
  dimLabels.push({ text: `AGV 入庫弧線 R${INBOUND.arc}`, pos: new THREE.Vector3(INBOUND.arcStart[0] - 900, 40, INBOUND.arcEnd[1] + 1500) });
  const agvRings = new THREE.Group(); dims.add(agvRings);
  for (const t of AGV_TURNS) { ring(agvRings, t.x, t.z, agvSweep(t.loaded), 0xffc233, .8); }
  dimLabels.push({ text: `AGV 迴轉 R${agvSweep(true).toFixed(0)}`, pos: new THREE.Vector3(AGV_TURNS[1].x, 40, AGV_TURNS[1].z - agvSweep(true)) });
  ring(dims, ROBOT.x, ROBOT.z, 2655, 0x4fd1e8, .45);
  dimLabels.push({ text: 'R-2000iC 最大伸展 R2655（DCS 限制在圍籬內）', pos: new THREE.Vector3(ROBOT.x - 1900, 40, ROBOT.z - 1850) });

  return { group, zones, dims, dimLabels, ceiling };
}
