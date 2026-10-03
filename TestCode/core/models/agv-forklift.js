// 平衡重式堆高 AGV（雷射導引）。局部 +X 為前進方向，原點為前輪軸中心（原地迴轉中心）。
// 車寬固定 1000 mm（輪、輪轂、門架位置依此配置）；車長、門架高、貨叉長、載物點可調。
// 原用於 ChemicalTankWashing（200L 桶棧板倉儲）。
import * as THREE from 'three';
import { D2R, block, cylinder } from '../geom/shapes.js';
import { MAT } from '../geom/materials.js';
import { bolts, housing } from '../geom/hardware.js';

export const meta = {
  id: 'agv-forklift', name: '平衡重式堆高 AGV', category: '物流', source: 'ChemicalTankWashing',
  params: {
    rear: { value: 1550, min: 1200, max: 2200, step: 10, unit: 'mm', label: '前輪軸到車尾' },
    mastLowered: { value: 2100, min: 1600, max: 3000, step: 10, unit: 'mm', label: '門架收合高' },
    forkEnd: { value: 1500, min: 1000, max: 2000, step: 10, unit: 'mm', label: '叉尖位置（距前輪軸）' },
    backrest: { value: 1100, min: 600, max: 1500, step: 10, unit: 'mm', label: '擋貨架高' },
    palletX: { value: 950, min: 700, max: 1300, step: 5, unit: 'mm', label: '棧板中心（距前輪軸）' },
    deck: { value: 120, min: 60, max: 200, step: 5, unit: 'mm', label: '叉面到棧板底' },
  },
  states: {
    fork: { value: 0, min: 0, max: 3000, unit: 'mm', label: '叉面高度' },
    yaw: { value: 0, min: -180, max: 180, unit: '°', label: '車頭方位' },
  },
  usage: "import { create as agv } from '@core/models/agv-forklift.js';\nconst a = agv({ rear: 1550 }); scene.add(a.root);\na.set({ x, z, yaw, fork, moving, time });  // a.carry 為載物點（棧板原點）",
};

export function create(p = {}) {
  const P = { ...Object.fromEntries(Object.entries(meta.params).map(([k, v]) => [k, v.value])), halfW: 500, mast: [220, 350], forkStart: 350, forkHalf: 350, palletHalf: 600, ...p };
  const root = new THREE.Group(); root.name = 'agv';
  housing(root, P.rear + 150, 1000, P.halfW * 2, MAT.agv, (-P.rear + 150) / 2, 650, 0, 35);
  // 配重比車身寬 12 mm、後退 6 mm、底面低 4 mm：與車身外殼不共面，避免深度互搶閃爍
  housing(root, 320, 944, P.halfW * 2 + 12, MAT.agvDark, -P.rear + 154, 618, 0, 35);
  block(root, [900, 30, 700], [-650, 1165, 0], MAT.agvDark);
  const beaconMat = MAT.amber.clone(); cylinder(root, 55, 110, [-650, 1235, 0], beaconMat, 'y', 28);
  for (const s of [-1, 1]) cylinder(root, 200, 160, [0, 200, s * 400], MAT.black, 'z', 28);
  cylinder(root, 160, 140, [-1250, 160, 0], MAT.black, 'z', 28);
  for (const [x, z] of [[160, -460], [160, 460], [-P.rear + 30, -460], [-P.rear + 30, 460]]) cylinder(root, 45, 70, [x, 300, z], MAT.yellow, 'y', 28);
  block(root, [20, 120, 600], [-P.rear - 5, 900, 0], MAT.screen);
  // 門架：外柱固定，內柱在叉面超過 1400 後隨之伸出
  const [m0, m1] = P.mast;
  for (const s of [-1, 1]) block(root, [m1 - m0, P.mastLowered, 90], [(m0 + m1) / 2, P.mastLowered / 2 + 60, s * 400], MAT.steelDark);
  block(root, [m1 - m0 + 10, 100, 890], [(m0 + m1) / 2, P.mastLowered + 10, 0], MAT.steelDark);
  const inner = new THREE.Group(); root.add(inner);
  for (const s of [-1, 1]) block(inner, [70, P.mastLowered - 100, 70], [(m0 + m1) / 2 + 20, P.mastLowered / 2 + 60, s * 320], MAT.steel);
  block(inner, [70, 70, 710], [(m0 + m1) / 2 + 20, P.mastLowered + 5, 0], MAT.steel);      // 底面高於外柱頂橫樑底面 5 mm，不共面
  const carriage = new THREE.Group(); root.add(carriage);
  block(carriage, [36, 520, 900], [m1 + 15, 210, 0], MAT.steelDark);                       // 背面在 m1 − 3：不與載運中棧板的後緣共面
  for (let k = 0; k < 5; k++) block(carriage, [24, 600, 24], [m1 + 20, 790, -360 + k * 180], MAT.steelDark);
  block(carriage, [30, 30, 900], [m1 + 20, P.backrest, 0], MAT.steelDark);
  for (const s of [-1, 1]) {
    block(carriage, [P.forkEnd - P.forkStart, 45, 120], [(P.forkStart + P.forkEnd) / 2, -23.5, s * 275], MAT.steelDark);   // 叉面略低於棧板面板底，不共面
    block(carriage, [45, 450, 120], [m1 + 64, 200, s * 275], MAT.steelDark);              // 叉柄掛在托架板前方，不與托架板共面
  }
  // 載物點：棧板原點（底面中心）＝叉面 − deck
  const carry = new THREE.Object3D(); carry.position.set(P.palletX, -P.deck, 0); carriage.add(carry);
  const hubs = [];
  for (const s of [-1, 1]) { const hub = cylinder(root, 100, 12, [0, 200, s * 492], MAT.steel, 'z', 24); hubs.push(hub); bolts(root, Array.from({ length: 6 }, (_, k) => [65 * Math.cos(k * Math.PI / 3), 200 + 65 * Math.sin(k * Math.PI / 3), s * 503]), 9, 'z'); }
  for (let i = 0; i < 9; i++) block(root, [480, 9, 4], [-900, 430 + i * 35, -502], MAT.black);
  cylinder(root, 62, 55, [-1150, 1230, 0], MAT.black, 'y', 28); cylinder(root, 58, 20, [-1150, 1268, 0], MAT.screen, 'y', 28);
  const liftRod = cylinder(root, 27, 1, [280, 400, 0], MAT.steel, 'y', 28);
  cylinder(root, 52, 950, [280, 520, 0], MAT.black, 'y', 28);
  return {
    root, carry, params: P,
    set({ x = 0, z = 0, yaw = 0, fork = 0, moving = false, time = 0 } = {}) {
      root.position.set(x, 0, z); root.rotation.y = yaw * D2R;
      carriage.position.y = fork; inner.position.y = Math.max(0, fork - 1400);
      for (const hub of hubs) hub.rotation.y = (x - z) / 200;
      liftRod.scale.y = Math.max(1, fork + 250 - 600); liftRod.position.y = 600 + liftRod.scale.y / 2;
      // 警示燈以亮度脈動表示行駛中（不切換材質，避免畫面閃爍）
      beaconMat.emissiveIntensity = moving ? .5 + .35 * Math.sin(time * 5) : .05;
    },
    // 車身與棧板（或空叉）的俯視多邊形（驗證用）
    footprint(loaded) {
      const body = [[-P.rear, -P.halfW], [m1, -P.halfW], [m1, P.halfW], [-P.rear, P.halfW]];
      const h = P.palletHalf, front = loaded ? [[P.palletX - h, -h], [P.palletX + h, -h], [P.palletX + h, h], [P.palletX - h, h]] : [[m1, -P.forkHalf], [P.forkEnd, -P.forkHalf], [P.forkEnd, P.forkHalf], [m1, P.forkHalf]];
      return { body, front };
    },
  };
}
