// 平衡重式堆高 AGV（雷射導引）。局部 +X 為前進方向，原點為前輪軸中心（原地迴轉中心）。
import * as THREE from 'three';
import { AGV, FORK } from './layout.js';
import { MAT, box, cyl, D2R } from './parts.js';

export function createAgv(scene) {
  const root = new THREE.Group(); root.name = 'agv'; scene.add(root);
  box(root, AGV.rear + 150, 1000, AGV.halfW * 2, MAT.agv, (-AGV.rear + 150) / 2, 650, 0);
  box(root, 320, 940, AGV.halfW * 2 + 10, MAT.agvDark, -AGV.rear + 160, 620, 0);           // 配重
  box(root, 900, 30, 700, MAT.agvDark, -650, 1165, 0);
  const beacon = cyl(root, 55, 110, MAT.amber, -650, 1235, 0);
  for (const s of [-1, 1]) cyl(root, 200, 160, MAT.black, 0, 200, s * 400, 'z');
  cyl(root, 160, 140, MAT.black, -1250, 160, 0, 'z');
  for (const [x, z] of [[160, -460], [160, 460], [-AGV.rear + 30, -460], [-AGV.rear + 30, 460]]) cyl(root, 45, 70, MAT.yellow, x, 300, z);
  box(root, 20, 120, 600, MAT.screen, -AGV.rear - 5, 900, 0);
  // 門架：外柱固定，內柱在叉面超過 1400 後隨之伸出
  const [m0, m1] = AGV.mast;
  for (const s of [-1, 1]) box(root, m1 - m0, AGV.mastLowered, 90, MAT.steelDark, (m0 + m1) / 2, AGV.mastLowered / 2 + 60, s * 400);
  box(root, m1 - m0, 100, 890, MAT.steelDark, (m0 + m1) / 2, AGV.mastLowered + 10, 0);
  const inner = new THREE.Group(); root.add(inner);
  for (const s of [-1, 1]) box(inner, 70, AGV.mastLowered - 100, 70, MAT.steel, (m0 + m1) / 2 + 20, AGV.mastLowered / 2 + 60, s * 320);
  box(inner, 70, 80, 710, MAT.steel, (m0 + m1) / 2 + 20, AGV.mastLowered, 0);
  const carriage = new THREE.Group(); root.add(carriage);
  box(carriage, 40, 520, 900, MAT.steelDark, m1 + 20, 210, 0);
  for (let k = 0; k < 5; k++) box(carriage, 24, 600, 24, MAT.steelDark, m1 + 20, 790, -360 + k * 180);
  box(carriage, 30, 30, 900, MAT.steelDark, m1 + 20, AGV.backrest, 0);
  for (const s of [-1, 1]) {
    box(carriage, AGV.fork[1] - AGV.fork[0], 45, 120, MAT.steelDark, (AGV.fork[0] + AGV.fork[1]) / 2, -22, s * 275);
    box(carriage, 45, 450, 120, MAT.steelDark, AGV.fork[0] + 22, 200, s * 275);
  }
  // 載物點：棧板原點（底面中心）＝叉面 − 120
  const carry = new THREE.Object3D(); carry.position.set(AGV.palletX, -FORK.deck, 0); carriage.add(carry);
  let blink = 0;
  return {
    root, carry,
    set({ x, z, yaw, fork, moving = false }) {
      root.position.set(x, 0, z); root.rotation.y = yaw * D2R;
      carriage.position.y = fork; inner.position.y = Math.max(0, fork - 1400);
      blink = moving ? blink + 1 : 0; beacon.material = moving && (blink >> 3) % 2 ? MAT.amber : MAT.agvDark;
    },
    // 車身與棧板的俯視多邊形（驗證用）
    footprint(loaded) {
      const pts = [[-AGV.rear, -AGV.halfW], [m1, -AGV.halfW], [m1, AGV.halfW], [-AGV.rear, AGV.halfW]];
      const front = loaded ? [[AGV.palletX - 600, -600], [AGV.palletX + 600, -600], [AGV.palletX + 600, 600], [AGV.palletX - 600, 600]] : [[m1, -AGV.forkHalf], [AGV.fork[1], -AGV.forkHalf], [AGV.fork[1], AGV.forkHalf], [m1, AGV.forkHalf]];
      return { body: pts, front };
    },
  };
}
