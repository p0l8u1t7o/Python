// FANUC R-2000iC/165F 六軸手臂本體（不含工具）。共用模型，原用於 ChemicalTankWashing。
// 臂長取型錄概略值（J1–J2 偏移 312、J2 高 670、上臂 1075、J3 偏移 225、前臂 1280、J5 至法蘭 215，最大伸展 2655）；
// 關節零點方向與 J2／J3 連動限位為假設，採用前須以 FANUC 型錄／CAD 核對。
// 局部座標：原點在底座底面中心，+Y 向上；零位時上臂垂直、前臂與法蘭面朝 +X。
// 關節：j1 繞 Y，j2／j3／j5 繞 Z，j4／j6 繞 X（與 core/robot/kinematics.js 一致）。
// 工具掛在 arm.flange（法蘭面中心，軸向 +X）；IK 解算器見 arm.createSolver。
import * as THREE from 'three';
import { createIK } from '../../robot/kinematics.js';
import { D2R, block, cylinder } from '../../geom/shapes.js';
import { MAT } from '../../geom/materials.js';
import { bolts, housing } from '../../geom/hardware.js';

export const K = { j2h: 670, j1x: 312, upper: 1075, foreOff: 225, fore: 1280, wrist: 175, flange: 40 };
// 模型座標的關節範圍：j2 = −J2（FANUC J2 −60～+76）；j3 為相對上臂，連動限位尚未建模
export const LIMITS = { j1: [-185, 185], j2: [-76, 60], j3: [-80, 200], j4: [-360, 360], j5: [-125, 125], j6: [-360, 360] };
export const SPEED = { j1: 105, j2: 105, j3: 105, j4: 130, j5: 130, j6: 210 };   // deg/s，概略值
export const JOINTS = ['j1', 'j2', 'j3', 'j4', 'j5', 'j6'];
// 大型手臂：姿態權重與阻尼較大、收斂門檻較嚴（core/robot/kinematics.js 的預設值是 DENSO 小手臂）
export const IK_OPTIONS = { weight: 400, iterations: 30, lambda: [20, 4], step: .2, tol: [.05, .0005] };

// 建立手臂本體。root 可平移（XZ／Y），不可旋轉（解算器的幾何初始解假設底座水平、朝向不變）。
export function createArm({ name = 'robot' } = {}) {
  const root = new THREE.Group(); root.name = name;
  const j = {};
  block(root, [1000, 60, 1000], [0, 30, 0], MAT.fanucDark);
  cylinder(root, 400, 300, [0, 210, 0], MAT.fanuc, 'y', 36);
  j.j1 = new THREE.Group(); root.add(j.j1);
  cylinder(j.j1, 360, 300, [0, 470, 0], MAT.fanuc, 'y', 36);
  cylinder(j.j1, 270, 600, [K.j1x, K.j2h, 0], MAT.fanuc, 'z', 32);
  cylinder(j.j1, 150, 240, [K.j1x, K.j2h, -400], MAT.fanucDark, 'z', 20);
  block(j.j1, [420, 300, 380], [60, 560, 0], MAT.fanuc);
  j.j2 = new THREE.Group(); j.j2.position.set(K.j1x, K.j2h, 0); j.j1.add(j.j2);
  housing(j.j2, 320, K.upper - 200, 300, MAT.fanuc, 0, K.upper / 2, 120, 28);
  cylinder(j.j2, 230, 280, [0, 0, 160], MAT.fanuc, 'z', 28);
  cylinder(j.j2, 210, 380, [0, K.upper, 100], MAT.fanuc, 'z', 28);
  block(j.j2, [140, 700, 120], [-170, 453, 260], MAT.fanucDark);                                  // 平衡器
  j.j3 = new THREE.Group(); j.j3.position.set(0, K.upper, 0); j.j2.add(j.j3);
  housing(j.j3, 620, 440, 360, MAT.fanuc, -120, 150, -60, 30);
  for (const [y, z] of [[90, -150], [250, -150], [170, 40]]) cylinder(j.j3, 85, 220, [-500, y, z], MAT.fanucDark, 'x', 18);
  housing(j.j3, K.fore - 300 - 180, 250, 250, MAT.fanuc, (180 + K.fore - 300) / 2, K.foreOff, 0, 22);
  j.j4 = new THREE.Group(); j.j4.position.set(K.fore - 300, K.foreOff, 0); j.j3.add(j.j4);
  cylinder(j.j4, 150, 200, [100, 0, 0], MAT.fanuc, 'x', 28);
  for (const s of [-1, 1]) block(j.j4, [160, 160, 40], [230, 0, s * 115], MAT.fanuc);
  j.j5 = new THREE.Group(); j.j5.position.set(300, 0, 0); j.j4.add(j.j5);
  cylinder(j.j5, 115, 190, [0, 0, 0], MAT.fanuc, 'z', 24);
  cylinder(j.j5, 105, 150, [85, 0, 0], MAT.fanuc, 'x', 24);
  j.j6 = new THREE.Group(); j.j6.position.set(K.wrist, 0, 0); j.j5.add(j.j6);
  cylinder(j.j6, 100, K.flange, [K.flange / 2, 0, 0], MAT.fanucDark, 'x', 24);
  // 工具安裝點：法蘭面中心，局部 +X 為法蘭軸向
  const flange = new THREE.Object3D(); flange.name = 'flange'; flange.position.x = K.flange; j.j6.add(flange);

  // 鑄件端蓋、基座錨栓、檢修蓋與氣缸接頭，跟隨各自關節。
  bolts(root, [-1, 1].flatMap(x => [-1, 1].map(z => [x * 420, 68, z * 420])), 24);
  for (const [parent, x, y, z, radius] of [[j.j2, 0, 0, 310, 155], [j.j2, 0, K.upper, 300, 140], [j.j5, 0, 0, 102, 80]]) {
    cylinder(parent, radius, 12, [x, y, z], MAT.steelDark, 'z', 28);
    bolts(parent, Array.from({ length: 8 }, (_, k) => [x + Math.cos(k * Math.PI / 4) * radius * .78, y + Math.sin(k * Math.PI / 4) * radius * .78, z + 12]), 9, 'z');
  }
  block(j.j2, [170, 460, 5], [0, K.upper / 2, 274], MAT.fanucDark);
  for (let i = 0; i < 6; i++) block(j.j3, [6, 120, 3], [-340 + i * 40, 180, -242], MAT.black);

  const q = { j1: 0, j2: 0, j3: 0, j4: 0, j5: 0, j6: 0 };   // rad
  function apply() {
    j.j1.rotation.set(0, q.j1, 0); j.j2.rotation.set(0, 0, q.j2); j.j3.rotation.set(0, 0, q.j3);
    j.j4.rotation.set(q.j4, 0, 0); j.j5.rotation.set(0, 0, q.j5); j.j6.rotation.set(q.j6, 0, 0);
    root.updateMatrixWorld(true);
  }
  apply();
  function setJoints(c) { for (const n of JOINTS) q[n] = c[n]; apply(); }

  // 各連桿中心線（碰撞檢查用）：[起點, 終點, 半徑]；給 toolEnd 時再加一段法蘭→工具端（回傳的向量會重複使用）
  const pts = ['j2', 'j3', 'j4', 'j5', 'j6'].map(() => new THREE.Vector3());
  function links(toolEnd = null, toolRadius = 300) {
    ['j2', 'j3', 'j4', 'j5', 'j6'].forEach((n, i) => j[n].getWorldPosition(pts[i]));
    const elbowOff = j.j3.localToWorld(new THREE.Vector3(0, K.foreOff, 0));
    const out = [[pts[0], pts[1], 200], [pts[1], elbowOff, 220], [elbowOff, pts[2], 150], [pts[2], pts[3], 150], [pts[3], pts[4], 120]];
    if (toolEnd) out.push([pts[4], toolEnd, toolRadius]);
    return out;
  }

  // IK 解算器。tool：掛在 flange 下的工具座標（姿態目標），tcp：tool 的直接子物件（位置目標）。
  // approach：tool 局部座標中與法蘭軸（flange +X）同向的單位向量；toFlange：tool → flange 的旋轉（tool.quaternion 的反向）。
  // 兩者預設由 tool.quaternion 推得；工具以 90° 等整數角掛上時可明確傳入，避免浮點誤差。
  function createSolver({ tool, tcp, approach = null, toFlange = null }) {
    toFlange = toFlange || tool.quaternion.clone().invert();
    approach = approach || new THREE.Vector3(1, 0, 0).applyQuaternion(toFlange);
    const ik = createIK({ q, j, tool, apply, limits: LIMITS, ...IK_OPTIONS });
    const wrapJ = (n, v) => { const [lo, hi] = LIMITS[n].map(x => x * D2R); for (const k of [0, 2 * Math.PI, -2 * Math.PI]) if (v + k >= lo && v + k <= hi) return v + k; return THREE.MathUtils.clamp(v, lo, hi); };
    // 幾何初始解：肘上／肘下 × 手腕翻轉共四組。pose = { target: TCP 世界位置, rot: tool 世界姿態 }
    function seeds(pose) {
      const dir = approach.clone().applyQuaternion(pose.rot);
      const origin = pose.target.clone().sub(tcp.position.clone().applyQuaternion(pose.rot));
      const w = origin.addScaledVector(dir, -(K.wrist + K.flange)).sub(new THREE.Vector3(root.position.x, root.position.y + K.j2h, root.position.z));
      const radial = Math.hypot(w.x, w.z) - K.j1x, a = K.upper, b = Math.hypot(K.fore, K.foreOff), phi = Math.atan2(K.foreOff, K.fore);
      const j1 = Math.atan2(-w.z, w.x), elbow = Math.acos(THREE.MathUtils.clamp((radial * radial + w.y * w.y - a * a - b * b) / (2 * a * b), -1, 1)), out = [];
      for (const beta of [-elbow, elbow]) {
        const j2 = Math.atan2(w.y, radial) - Math.atan2(b * Math.sin(beta), a + b * Math.cos(beta)) - Math.PI / 2, j3 = beta + Math.PI / 2 - phi;
        const shoulder = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), j1).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), j2 + j3));
        const rel = shoulder.invert().multiply(pose.rot).multiply(toFlange);
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
    return { ik, seeds, solve, track, error };
  }

  return { root, j, flange, q, apply, setJoints, links, createSolver };
}

// ---------------------------------------------------------------- 模型目錄
// 目錄的關節範圍比 LIMITS 窄，任意組合本體都不自撞（J2／J3 連動限位尚未建模，手腕外形為概略）：
//   j2 ≤ 55：再往後仰、j3 約 75～90° 時前臂後方馬達碰到 J1 轉座；
//   j3 −30～160：更小會讓前臂折回撞底座，更大會讓手腕撞底座台；
//   j5 ±100：超過約 ±103° 法蘭碰到 J4 腕殼；j4／j6 收在 ±180°（再多轉一圈外觀相同）。
export const meta = {
  id: 'fanuc-r2000ic', name: 'FANUC R-2000iC/165F 六軸手臂', category: '機械手臂', source: 'ChemicalTankWashing',
  params: {
    pedestal: { value: 400, min: 0, max: 1500, step: 10, unit: 'mm', label: '底座台高' },
  },
  states: {
    j1: { value: 0, min: LIMITS.j1[0], max: LIMITS.j1[1], unit: '°', label: 'J1 旋轉' },
    j2: { value: 0, min: LIMITS.j2[0], max: 55, unit: '°', label: 'J2 下臂（模型座標 = −J2）' },
    j3: { value: 0, min: -30, max: 160, unit: '°', label: 'J3 上臂（相對下臂）' },
    j4: { value: 0, min: -180, max: 180, unit: '°', label: 'J4 前臂旋轉' },
    j5: { value: 0, min: -100, max: 100, unit: '°', label: 'J5 手腕擺動' },
    j6: { value: 0, min: -180, max: 180, unit: '°', label: 'J6 法蘭旋轉' },
  },
  usage: "import { createArm, K, LIMITS, SPEED, JOINTS } from '@core/models/robots/fanuc-r2000ic.js';\nconst arm = createArm({ name: 'robot' }); arm.root.position.set(x, 0, z); scene.add(arm.root);\nconst tool = new THREE.Group(); arm.flange.add(tool);   // 工具掛在法蘭（+X 為法蘭軸）\nconst tcp = new THREE.Object3D(); tool.add(tcp);\nconst s = arm.createSolver({ tool, tcp }); const c = s.solve({ target, rot }); arm.setJoints(c);",
};

export function create(p = {}) {
  const P = { ...Object.fromEntries(Object.entries(meta.params).map(([k, v]) => [k, v.value])), ...p };
  const root = new THREE.Group(); root.name = 'fanuc-r2000ic';
  if (P.pedestal > 0) block(root, [1100, P.pedestal, 1100], [0, P.pedestal / 2, 0], MAT.steelDark);
  const arm = createArm({ name: 'arm' }); arm.root.position.y = P.pedestal; root.add(arm.root); arm.apply();
  return {
    root, arm,
    set(s = {}) { arm.setJoints(Object.fromEntries(JOINTS.map(n => [n, (s[n] ?? meta.states[n].value) * D2R]))); },
  };
}
