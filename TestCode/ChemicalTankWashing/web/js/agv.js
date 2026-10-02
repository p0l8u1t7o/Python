// 平衡重式堆高 AGV（雷射導引）。局部 +X 為前進方向，原點為前輪軸中心（原地迴轉中心）。
import * as THREE from 'three';
import { AGV, FORK } from './layout.js';
import { MAT, box, cyl, D2R } from '@core/geom/parts.js';
import { bolts, housing } from '@core/geom/hardware.js';

export function createAgv(scene) {
  const root = new THREE.Group(); root.name = 'agv'; scene.add(root);
  housing(root, AGV.rear + 150, 1000, AGV.halfW * 2, MAT.agv, (-AGV.rear + 150) / 2, 650, 0, 35);
  // 配重比車身寬 12 mm、後退 6 mm、底面低 4 mm：與車身外殼不共面，避免深度互搶閃爍
  housing(root, 320, 944, AGV.halfW * 2 + 12, MAT.agvDark, -AGV.rear + 154, 618, 0, 35);           // 配重
  box(root, 900, 30, 700, MAT.agvDark, -650, 1165, 0);
  const beaconMat = MAT.amber.clone(); const beacon = cyl(root, 55, 110, beaconMat, -650, 1235, 0);
  for (const s of [-1, 1]) cyl(root, 200, 160, MAT.black, 0, 200, s * 400, 'z');
  cyl(root, 160, 140, MAT.black, -1250, 160, 0, 'z');
  for (const [x, z] of [[160, -460], [160, 460], [-AGV.rear + 30, -460], [-AGV.rear + 30, 460]]) cyl(root, 45, 70, MAT.yellow, x, 300, z);
  box(root, 20, 120, 600, MAT.screen, -AGV.rear - 5, 900, 0);
  // 門架：外柱固定，內柱在叉面超過 1400 後隨之伸出
  const [m0, m1] = AGV.mast;
  for (const s of [-1, 1]) box(root, m1 - m0, AGV.mastLowered, 90, MAT.steelDark, (m0 + m1) / 2, AGV.mastLowered / 2 + 60, s * 400);
  box(root, m1 - m0 + 10, 100, 890, MAT.steelDark, (m0 + m1) / 2, AGV.mastLowered + 10, 0);
  const inner = new THREE.Group(); root.add(inner);
  for (const s of [-1, 1]) box(inner, 70, AGV.mastLowered - 100, 70, MAT.steel, (m0 + m1) / 2 + 20, AGV.mastLowered / 2 + 60, s * 320);
  box(inner, 70, 70, 710, MAT.steel, (m0 + m1) / 2 + 20, AGV.mastLowered + 5, 0);      // 底面高於外柱頂橫樑底面 5 mm，不共面
  const carriage = new THREE.Group(); root.add(carriage);
  box(carriage, 36, 520, 900, MAT.steelDark, m1 + 15, 210, 0);                       // 背面在 m1 − 3：不與載運中棧板的後緣（palletX − 600 = m1）共面
  for (let k = 0; k < 5; k++) box(carriage, 24, 600, 24, MAT.steelDark, m1 + 20, 790, -360 + k * 180);
  box(carriage, 30, 30, 900, MAT.steelDark, m1 + 20, AGV.backrest, 0);
  for (const s of [-1, 1]) {
    box(carriage, AGV.fork[1] - AGV.fork[0], 45, 120, MAT.steelDark, (AGV.fork[0] + AGV.fork[1]) / 2, -23.5, s * 275);   // 叉面略低於棧板面板底，不共面
    box(carriage, 45, 450, 120, MAT.steelDark, m1 + 64, 200, s * 275);              // 叉柄掛在托架板前方，不與托架板共面
  }
  // 載物點：棧板原點（底面中心）＝叉面 − 120
  const carry = new THREE.Object3D(); carry.position.set(AGV.palletX, -FORK.deck, 0); carriage.add(carry);
  const hubs = [];
  for (const s of [-1, 1]) { const hub = cyl(root, 100, 12, MAT.steel, 0, 200, s * 492, 'z', 24); hubs.push(hub); bolts(root, Array.from({length: 6}, (_, k) => [65 * Math.cos(k * Math.PI / 3), 200 + 65 * Math.sin(k * Math.PI / 3), s * 503]), 9, 'z'); }
  for (let i = 0; i < 9; i++) box(root, 480, 9, 4, MAT.black, -900, 430 + i * 35, -502);
  cyl(root, 62, 55, MAT.black, -1150, 1230, 0); cyl(root, 58, 20, MAT.screen, -1150, 1268, 0);
  const liftRod = cyl(root, 27, 1, MAT.steel, 280, 400, 0);
  cyl(root, 52, 950, MAT.black, 280, 520, 0);
  return {
    root, carry,
    set({ x, z, yaw, fork, moving = false, time = 0 }) {
      root.position.set(x, 0, z); root.rotation.y = yaw * D2R;
      carriage.position.y = fork; inner.position.y = Math.max(0, fork - 1400);
      for (const hub of hubs) hub.rotation.y = (x - z) / 200;
      // 警示燈以亮度脈動表示行駛中（不切換材質，避免畫面閃爍）
      liftRod.scale.y = Math.max(1, fork + 250 - 600); liftRod.position.y = 600 + liftRod.scale.y / 2;
      beaconMat.emissiveIntensity = moving ? .5 + .35 * Math.sin(time * 5) : .05;
    },
    // 車身與棧板的俯視多邊形（驗證用）
    footprint(loaded) {
      const pts = [[-AGV.rear, -AGV.halfW], [m1, -AGV.halfW], [m1, AGV.halfW], [-AGV.rear, AGV.halfW]];
      const front = loaded ? [[AGV.palletX - 600, -600], [AGV.palletX + 600, -600], [AGV.palletX + 600, 600], [AGV.palletX - 600, 600]] : [[m1, -AGV.forkHalf], [AGV.fork[1], -AGV.forkHalf], [AGV.fork[1], AGV.forkHalf], [m1, AGV.forkHalf]];
      return { body: pts, front };
    },
  };
}
