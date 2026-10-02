// FANUC R-2000iC/165F 六軸手臂＋夾桶夾爪。
// 臂長取型錄概略值（J1–J2 偏移 312、J2 高 670、上臂 1075、J3 偏移 225、前臂 1280、J5 至法蘭 215，最大伸展 2655）；
// 關節零點方向與 J2／J3 連動限位為假設，採用前須以 FANUC 型錄／CAD 核對。
import * as THREE from 'three';
import { createIK } from './kinematics.js';
import { MAT, box, cyl, D2R } from './parts.js';
import { createWashGripper } from './gripper.js';
import { ROBOT } from './layout.js';
import { bolts, housing } from './detail.js';

export const K = { j2h: 670, j1x: 312, upper: 1075, foreOff: 225, fore: 1280, wrist: 175, flange: 40 };
// 模型座標的關節範圍：j2 = −J2（FANUC J2 −60～+76）；j3 為相對上臂，連動限位尚未建模
export const LIMITS = { j1: [-185, 185], j2: [-76, 60], j3: [-80, 200], j4: [-360, 360], j5: [-125, 125], j6: [-360, 360] };
export const SPEED = { j1: 105, j2: 105, j3: 105, j4: 130, j5: 130, j6: 210 };   // deg/s，概略值
export const JOINTS = ['j1', 'j2', 'j3', 'j4', 'j5', 'j6'];

export function createRobot() {
  const root = new THREE.Group(); root.name = 'robot'; root.position.set(ROBOT.x, 0, ROBOT.z);
  const j = {};
  box(root, 1000, 60, 1000, MAT.fanucDark, 0, 30, 0);
  cyl(root, 400, 300, MAT.fanuc, 0, 210, 0, 'y', 36);
  j.j1 = new THREE.Group(); root.add(j.j1);
  cyl(j.j1, 360, 300, MAT.fanuc, 0, 470, 0, 'y', 36);
  cyl(j.j1, 270, 600, MAT.fanuc, K.j1x, K.j2h, 0, 'z', 32);
  cyl(j.j1, 150, 240, MAT.fanucDark, K.j1x, K.j2h, -400, 'z', 20);
  box(j.j1, 420, 300, 380, MAT.fanuc, 60, 560, 0);
  j.j2 = new THREE.Group(); j.j2.position.set(K.j1x, K.j2h, 0); j.j1.add(j.j2);
  housing(j.j2, 320, K.upper - 200, 300, MAT.fanuc, 0, K.upper / 2, 120, 28);
  cyl(j.j2, 230, 280, MAT.fanuc, 0, 0, 160, 'z', 28);
  cyl(j.j2, 210, 380, MAT.fanuc, 0, K.upper, 100, 'z', 28);
  box(j.j2, 140, 700, 120, MAT.fanucDark, -170, 450, 260);                                  // 平衡器
  j.j3 = new THREE.Group(); j.j3.position.set(0, K.upper, 0); j.j2.add(j.j3);
  housing(j.j3, 620, 440, 360, MAT.fanuc, -120, 150, -60, 30);
  for (const [y, z] of [[90, -150], [250, -150], [170, 40]]) cyl(j.j3, 85, 220, MAT.fanucDark, -500, y, z, 'x', 18);
  housing(j.j3, K.fore - 300 - 180, 250, 250, MAT.fanuc, (180 + K.fore - 300) / 2, K.foreOff, 0, 22);
  j.j4 = new THREE.Group(); j.j4.position.set(K.fore - 300, K.foreOff, 0); j.j3.add(j.j4);
  cyl(j.j4, 150, 200, MAT.fanuc, 100, 0, 0, 'x', 28);
  for (const s of [-1, 1]) box(j.j4, 160, 160, 40, MAT.fanuc, 230, 0, s * 115);
  j.j5 = new THREE.Group(); j.j5.position.set(300, 0, 0); j.j4.add(j.j5);
  cyl(j.j5, 115, 190, MAT.fanuc, 0, 0, 0, 'z', 24);
  cyl(j.j5, 105, 150, MAT.fanuc, 85, 0, 0, 'x', 24);
  j.j6 = new THREE.Group(); j.j6.position.set(K.wrist, 0, 0); j.j5.add(j.j6);
  cyl(j.j6, 100, K.flange, MAT.fanucDark, K.flange / 2, 0, 0, 'x', 24);

  // ---- 夾桶夾爪：工具 +Z 指向桶軸，桶軸為工具 +Y，桶中心在工具 Z = ROBOT.grip ----
  const tool = new THREE.Group(); tool.position.x = K.flange; tool.rotation.y = Math.PI / 2; j.j6.add(tool);
  const gripper = createWashGripper(tool);
  const tcp = new THREE.Object3D(); tcp.position.z = ROBOT.grip; tool.add(tcp);

  // 鑄件端蓋、基座錨栓、檢修蓋與氣缸接頭，跟隨各自關節。
  bolts(root, [-1, 1].flatMap(x => [-1, 1].map(z => [x * 420, 68, z * 420])), 24);
  for (const [parent, x, y, z, radius] of [[j.j2, 0, 0, 310, 155], [j.j2, 0, K.upper, 300, 140], [j.j5, 0, 0, 102, 80]]) {
    cyl(parent, radius, 12, MAT.steelDark, x, y, z, 'z');
    bolts(parent, Array.from({length: 8}, (_, k) => [x + Math.cos(k * Math.PI / 4) * radius * .78, y + Math.sin(k * Math.PI / 4) * radius * .78, z + 12]), 9, 'z');
  }
  box(j.j2, 170, 460, 5, MAT.fanucDark, 0, K.upper / 2, 274);
  for (let i = 0; i < 6; i++) box(j.j3, 6, 120, 3, MAT.black, -340 + i * 40, 180, -242);


  const q = { j1: 0, j2: 0, j3: 0, j4: 0, j5: 0, j6: 0 };
  function apply() {
    j.j1.rotation.set(0, q.j1, 0); j.j2.rotation.set(0, 0, q.j2); j.j3.rotation.set(0, 0, q.j3);
    j.j4.rotation.set(q.j4, 0, 0); j.j5.rotation.set(0, 0, q.j5); j.j6.rotation.set(q.j6, 0, 0);
    root.updateMatrixWorld(true);
  }
  apply();
  const ik = createIK({ q, j, tool, apply, limits: LIMITS });

  // 夾桶位姿：center 為桶中心，up 為桶軸（桶頂方向），approach 為夾爪前進方向；roll 繞工具 Z 再轉
  const _m = new THREE.Matrix4();
  function poseDrum(center, up = new THREE.Vector3(0, 1, 0), approach = new THREE.Vector3(1, 0, 0), roll = 0, extra = null) {
    const Y = up.clone().normalize(), Z = approach.clone().addScaledVector(Y, -approach.dot(Y)).normalize(), X = new THREE.Vector3().crossVectors(Y, Z);
    const rot = new THREE.Quaternion().setFromRotationMatrix(_m.makeBasis(X, Y, Z));
    if (roll) rot.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), roll));
    if (extra) rot.multiply(extra);
    return { target: center.clone(), rot };
  }
  const wrapJ = (n, v) => { const [lo, hi] = LIMITS[n].map(x => x * D2R); for (const k of [0, 2 * Math.PI, -2 * Math.PI]) if (v + k >= lo && v + k <= hi) return v + k; return THREE.MathUtils.clamp(v, lo, hi); };
  // 幾何初始解：肘上／肘下 × 手腕翻轉共四組
  function seeds(pose) {
    const dir = new THREE.Vector3(0, 0, 1).applyQuaternion(pose.rot);
    const origin = pose.target.clone().sub(tcp.position.clone().applyQuaternion(pose.rot));
    const w = origin.addScaledVector(dir, -(K.wrist + K.flange)).sub(new THREE.Vector3(root.position.x, K.j2h, root.position.z));
    const radial = Math.hypot(w.x, w.z) - K.j1x, a = K.upper, b = Math.hypot(K.fore, K.foreOff), phi = Math.atan2(K.foreOff, K.fore);
    const j1 = Math.atan2(-w.z, w.x), elbow = Math.acos(THREE.MathUtils.clamp((radial * radial + w.y * w.y - a * a - b * b) / (2 * a * b), -1, 1)), out = [];
    for (const beta of [-elbow, elbow]) {
      const j2 = Math.atan2(w.y, radial) - Math.atan2(b * Math.sin(beta), a + b * Math.cos(beta)) - Math.PI / 2, j3 = beta + Math.PI / 2 - phi;
      const shoulder = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), j1).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), j2 + j3));
      const rel = shoulder.invert().multiply(pose.rot).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -Math.PI / 2));
      const m = new THREE.Matrix4().makeRotationFromQuaternion(rel).elements;
      const j5 = Math.acos(THREE.MathUtils.clamp(m[0], -1, 1));
      let j4 = 0, j6 = Math.atan2(m[6], m[5]); if (Math.sin(j5) > 1e-5) { j4 = Math.atan2(m[2], m[1]); j6 = Math.atan2(m[8], -m[4]); }
      for (const [w4, w5, w6] of [[j4, j5, j6], [j4 + Math.PI, -j5, j6 + Math.PI]]) {
        const c = { j1, j2, j3, j4: w4, j5: w5, j6: w6 }; for (const n of JOINTS) c[n] = wrapJ(n, c[n]); out.push(c);
      }
    }
    return out;
  }
  const _p = new THREE.Vector3(), _r = new THREE.Quaternion();
  function error(pose) {
    tcp.getWorldPosition(_p); tool.getWorldQuaternion(_r);
    return { position: _p.distanceTo(pose.target), angle: _r.angleTo(pose.rot) / D2R };
  }
  const dist = (a, b) => JOINTS.reduce((s, n) => s + Math.abs(a[n] - b[n]), 0);
  const within = c => JOINTS.every(n => c[n] >= LIMITS[n][0] * D2R - 1e-9 && c[n] <= LIMITS[n][1] * D2R + 1e-9);
  const cache = new WeakMap();
  // 位姿 → 關節角（結果快取在位姿物件上；有參考解時取最接近的等價解，避免手腕多轉一圈）
  function solve(pose, ref = null) {
    const hit = cache.get(pose); if (hit) return hit;
    let best = null, score = Infinity, near = null, nearD = Infinity;
    for (const c of ref ? [ref, ...seeds(pose)] : seeds(pose)) {
      for (const n of JOINTS) q[n] = c[n]; apply(); ik.solve(tcp, pose.target, pose.rot, 120);
      const e = error(pose), v = e.position + e.angle * 10;
      if (v < score) { score = v; best = { ...q }; }
      if (v < .1) { if (!ref) break; const d = dist(q, ref); if (d < nearD) { nearD = d; near = { ...q }; } }
    }
    for (const n of JOINTS) q[n] = (near || best)[n];
    if (ref) {
      let pick = { ...q }, pickD = dist(q, ref);
      for (const [d4, s5, d6] of [[0, 1, 0], [Math.PI, -1, Math.PI], [Math.PI, -1, -Math.PI], [-Math.PI, -1, Math.PI], [-Math.PI, -1, -Math.PI]])
        for (const k4 of [0, 2 * Math.PI, -2 * Math.PI]) for (const k6 of [0, 2 * Math.PI, -2 * Math.PI]) {
          const c = { ...q, j4: q.j4 + d4 + k4, j5: s5 * q.j5, j6: q.j6 + d6 + k6 };
          if (within(c)) { const d = dist(c, ref); if (d < pickD - 1e-9) { pickD = d; pick = c; } }
        }
      for (const n of JOINTS) q[n] = pick[n];
    }
    apply();
    const out = { ...q, err: error(pose) };
    cache.set(pose, out); return out;
  }
  // 從鄰近種子追蹤直線／擺動路徑上的中間位姿（不快取）
  function track(pose, seed) {
    for (const n of JOINTS) q[n] = seed[n]; apply(); ik.solve(tcp, pose.target, pose.rot, 40);
    return { ...q, err: error(pose) };
  }
  function setJoints(c) { for (const n of JOINTS) q[n] = c[n]; apply(); }
  // 各連桿中心線（碰撞檢查用）：[起點, 終點, 半徑]
  const pts = ['j2', 'j3', 'j4', 'j5', 'j6'].map(() => new THREE.Vector3());
  function links() {
    ['j2', 'j3', 'j4', 'j5', 'j6'].forEach((n, i) => j[n].getWorldPosition(pts[i]));
    const toolEnd = tool.localToWorld(new THREE.Vector3(0, 0, 230)), elbowOff = j.j3.localToWorld(new THREE.Vector3(0, K.foreOff, 0));
    return [[pts[0], pts[1], 200], [pts[1], elbowOff, 220], [elbowOff, pts[2], 150], [pts[2], pts[3], 150], [pts[3], pts[4], 120], [pts[4], toolEnd, 300]];
  }
  return { root, q, j, tool, tcp, apply, poseDrum, solve, track, setJoints, gripper, setJaw: v => gripper.set(v), links, error };
}
