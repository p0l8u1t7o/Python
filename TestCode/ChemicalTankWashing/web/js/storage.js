// 穿梭車密集架、棧板、架上桶槽（靜態以 InstancedMesh 繪製）、示範車道與穿梭車。
import * as THREE from 'three';
import { RACK, PALLET, DRUM, lanePositions } from './layout.js';
import { MAT, box, plate, rod, cyl } from './parts.js';
import { foot } from './detail.js';
import { createDrumInstances } from './drum.js';

// 塑膠棧板：上板＋三條沿 Z 的底樑（叉子由 Z 向插入，兩側底樑落在穿梭車軌道上）
export function createPallet(empty = false) {
  const g = new THREE.Group(), mat = empty ? MAT.palletEmpty : MAT.pallet;
  box(g, PALLET.W, 30, PALLET.W, mat, 0, PALLET.H - 15, 0);
  for (const x of [-550, 0, 550]) box(g, 100, PALLET.H - 30, PALLET.W, mat, x, (PALLET.H - 30) / 2, 0);
  return g;
}
const rand = seed => () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32;

export function createStorage(scene, makeDrum) {
  const group = new THREE.Group(); group.name = 'storage'; scene.add(group);
  const half = RACK.pitch / 2;
  // ---- 架體：立柱（藍）、軌道（橘）、頂樑；最西一道只做 3 深 ----
  const blocks = [[0, 1, 2], [3, 4]];
  const front = l => l === RACK.shortLane ? RACK.shortFront : RACK.zFront;
  const framesTo = f => [RACK.zBack, 1450, 2750, 4050, f - 50].filter((z, i, a) => z <= f - 50 && (i === 0 || z - a[i - 1] > 300));
  for (const lanes of blocks) {
    // 每支立柱的深度取兩側車道較深者
    const xs = [[RACK.lanes[lanes[0]] - half, front(lanes[0])], ...lanes.map((l, k) => [RACK.lanes[l] + half, Math.max(front(l), k + 1 < lanes.length ? front(lanes[k + 1]) : 0)])];
    for (const [x, f] of xs) {
      const zs = framesTo(f);
      for (const z of zs) { box(group, 90, RACK.topBeam, 90, MAT.steelBlue, x, RACK.topBeam / 2, z); foot(group, x, z, 130); }
      for (let k = 0; k < zs.length - 1; k++) for (let y = 430; y < 3100; y += 1330) rod(group, [x, y, zs[k]], [x, y + 980, zs[k + 1]], 12, MAT.steel, 8);
      for (let k = 0; k < zs.length - 1; k++) box(group, 40, 40, zs[k + 1] - zs[k], MAT.steelBlue, x, RACK.topBeam - 300, (zs[k] + zs[k + 1]) / 2);
    }
    for (const l of lanes) for (const z of [RACK.zBack, front(l) - 50]) box(group, RACK.pitch + 90, 120, 70, MAT.steelBlue, RACK.lanes[l], RACK.topBeam - 60, z);
    for (const i of lanes) for (const y of RACK.levels) for (const s of [-1, 1]) {
      box(group, 80, 105, front(i) - RACK.zBack, MAT.steelOrange, RACK.lanes[i] + s * 600, y - 52, (RACK.zBack + front(i)) / 2);
      box(group, 60, 220, 60, MAT.steelOrange, RACK.lanes[i] + s * 650, y + 60, front(i) - 30);   // 入口導引
    }
    for (const i of lanes) plate(group, [`第 ${i + 1} 道`], 520, 130, [RACK.lanes[i], RACK.topBeam + 90, front(i) - 10], 0, { w: 512, h: 128 });
  }

  // ---- 架上棧板與桶槽 ----
  const key = (l, v, p) => `${l},${v},${p}`;
  // 空位：第 3 道底層前位留給動畫入庫，其餘為零星空位
  const emptySlots = new Set([key(2, 0, 0), key(3, 2, 0), key(4, 1, 0), key(4, 2, 0)]);
  const inst = createDrumInstances(200), palletDeck = [], r = rand(11);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), Y = new THREE.Vector3(0, 1, 0), one = new THREE.Vector3(1, 1, 1);
  let full = 0;
  for (let l = 0; l < RACK.lanes.length; l++) for (let v = 0; v < RACK.levels.length; v++) for (const p of lanePositions(l)) {
    if (l === RACK.demo.lane && v === RACK.demo.level) continue;
    if (l === RACK.emptyLane && v === RACK.emptyLevel) continue;
    if (emptySlots.has(key(l, v, p))) continue;
    const x = RACK.lanes[l], y = RACK.levels[v], z = RACK.pos[p];
    palletDeck.push([x, y, z]); full++;
    for (const [dx, dz] of PALLET.slots) inst.add(m.compose(new THREE.Vector3(x + dx, y + PALLET.H + DRUM.H / 2, z + dz), q.setFromAxisAngle(Y, r() * Math.PI * 2), one));
  }
  inst.done(); group.add(inst.group);
  for (const [w, h, dx, dy] of [[PALLET.W, 30, 0, 135], [100, 120, -550, 60], [100, 120, 0, 60], [100, 120, 550, 60]]) {
    const deck = new THREE.InstancedMesh(new THREE.BoxGeometry(w, h, PALLET.W), MAT.pallet, palletDeck.length);
    palletDeck.forEach(([x, y, z], i) => deck.setMatrixAt(i, m.makeTranslation(x + dx, y + dy, z)));
    deck.castShadow = deck.receiveShadow = true; group.add(deck);
  }

  // ---- 空棧板疊（東側最後一道底層前位）----
  const empties = new THREE.Group(); empties.position.set(RACK.lanes[RACK.emptyLane], RACK.levels[RACK.emptyLevel], RACK.pos[0]); group.add(empties);
  for (let i = 0; i < RACK.emptyStack; i++) { const p = createPallet(true); p.position.y = i * PALLET.H; empties.add(p); }

  // ---- 示範車道（第 2 道第 2 層）：4 個棧板，前位那一個由產線動畫接手 ----
  const demo = [];
  for (let p = 0; p < RACK.pos.length; p++) {
    const pal = createPallet(); group.add(pal);
    const drums = p === 0 ? [] : PALLET.slots.map(([dx, dz], k) => {
      const d = makeDrum(`CTW-2610-${String(p * 4 + k + 1).padStart(4, '0')}`); d.root.position.set(dx, PALLET.H + DRUM.H / 2, dz); d.root.rotation.y = r() * Math.PI * 2; pal.add(d.root); return d;
    });
    demo.push({ group: pal, drums });
  }
  // 穿梭車（無線遙控型，在軌道下緣行走，頂升 40 mm 搬運棧板）
  const shuttle = new THREE.Group(); group.add(shuttle);
  box(shuttle, 1000, 120, 1080, MAT.yellow, 0, -80, 0);
  for (const x of [-480, 480]) for (const z of [-400, 400]) cyl(shuttle, 45, 35, MAT.black, x, -70, z, "x", 16);
  box(shuttle, 900, 16, 980, MAT.steelDark, 0, -12, 0);
  for (const s of [-1, 1]) box(shuttle, 30, 60, 200, MAT.red, s * 505, -95, 520);
  // 其他兩層的穿梭車停在各自車道後端（示意；換道由 AGV 搬運）
  for (const [l, v, p] of RACK.shuttles) if (v !== RACK.demo.level) { const s = shuttle.clone(); s.position.set(RACK.lanes[l], RACK.levels[v], RACK.pos[p]); group.add(s); }
  const laneX = RACK.lanes[RACK.demo.lane], laneY = RACK.levels[RACK.demo.level];
  const zAt = pos => { const i = Math.max(0, Math.min(2.999, Math.floor(pos))); return RACK.pos[i] + (RACK.pos[i + 1] - RACK.pos[i]) * (pos - i); };

  return {
    group, demo, shuttle, empties, fullCount: full + 4, zAt,
    // 示範車道狀態：pallets[i] = { pos, lift }；shuttle = { pos, lift }
    setDemo(pallets, sh) {
      pallets.forEach((s, i) => { if (!s) return; demo[i].group.visible = true; demo[i].group.position.set(laneX, laneY + s.lift * RACK.shuttleLift, zAt(s.pos)); });
      shuttle.position.set(laneX, laneY + sh.lift * RACK.shuttleLift, zAt(sh.pos));
    },
    setEmpties(n) { empties.children.forEach((p, i) => { p.visible = i < n; }); },
    emptyTop: n => RACK.levels[RACK.emptyLevel] + n * PALLET.H,
  };
}
