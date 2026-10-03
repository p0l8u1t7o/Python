// DENSO VM-60B1 六軸垂直多關節手臂（共用模型）：基座、連桿、關節群組 j1～j6、手臂外部線材保護段、法蘭工具安裝座與 IK。
// 原用於 MilitaryGradePC（軍規筆電外觀檢測線，手臂裝在第七軸滑軌的立座上）。單位 mm；局部 +Y 朝上，原點在基座底面中心。
// 關節軸：j1 繞 Y、j2／j3／j5 繞 Z、j4／j6 繞 X（與 core/robot/kinematics.js 相同）。
// 工具安裝座 arm.tool：在法蘭面上，局部 +Z 為工具前進方向；末端工具、TCP、立座／滑軌與流程規劃由各專案自行處理。
import * as THREE from 'three';
import { armDress } from '../../electrical/cable-routing.js';
import { createIK } from '../../robot/kinematics.js';
import { cylinder } from '../../geom/shapes.js';

const D2R = Math.PI / 180;
export const JOINTS = ['j1', 'j2', 'j3', 'j4', 'j5', 'j6'];

// 連桿（DENSO VM-60B1 型錄：臂長 520＋590、J1–J2 偏移 180、J3 偏移 100）。
// 基座高 160、J1 到 J2 高度 210、J5 以後的手腕長度型錄未列，為概念值，需以 DENSO CAD 核對。
export const LINKS = Object.freeze({ base: 160, shoulderY: 210, shoulderX: 180, upper: 520, fore: 590, foreOffset: 100, wrist1: 110, wrist2: 90, flange: 40 });
// 關節限位（度）。VM-60B1 型錄範圍：J1 ±170、J2 +135/−90、J3 +168/−80、J4 ±185、J5 ±120、J6 ±360。
// 換算到本模型座標（假設 DENSO J2 零點為上臂垂直、J3=90° 為前臂水平；正向相反）：j2 = −J2、j3 = 90° − J3。採用前以 DENSO CAD 核對。
export const LIMITS = Object.freeze({ j1: [-170, 170], j2: [-135, 90], j3: [-78, 170], j4: [-185, 185], j5: [-120, 120], j6: [-360, 360] });
// 關節速度上限（rad/s）：各軸統一 1.8 rad/s（約 103°/s），為 MilitaryGradePC 動作規劃採用的保守值，低於型錄最高速度
export const JOINT_SPEED = Object.freeze({ j1: 1.8, j2: 1.8, j3: 1.8, j4: 1.8, j5: 1.8, j6: 1.8 });
// 預設姿態（度）：上臂後仰 30°、前臂水平、手腕下彎
export const READY = Object.freeze({ j1: 0, j2: -30, j3: 0, j4: 0, j5: -50, j6: 0 });
// IK 參數（core/robot/kinematics.js 的 DENSO 調校值，明確寫出以免預設值變動影響既有專案）
export const IK_OPTIONS = Object.freeze({ weight: 180, iterations: 16, lambda: [6, 2], step: .22, tol: [.08, .001] });

// 材質：工具可沿用 dark（深灰）與 joint（黑色關節）讓外觀一致；bolt 為關節蓋螺栓
export const VM60B1_MAT = {
  arm: new THREE.MeshStandardMaterial({ color: 0xe8e9eb, roughness: 0.45, metalness: 0.15 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x2f3439, roughness: 0.5, metalness: 0.3 }),
  joint: new THREE.MeshStandardMaterial({ color: 0x1c1f23, roughness: 0.4, metalness: 0.5 }),
  bolt: new THREE.MeshStandardMaterial({ color: 0x8d949c, roughness: 0.4, metalness: 0.7 }),
};
const matArm = VM60B1_MAT.arm, matJoint = VM60B1_MAT.joint;

function cyl(r1, r2, h, mat, seg = 32) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, seg), mat); m.castShadow = true; m.receiveShadow = true; return m; }
function box(w, h, d, mat) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.castShadow = true; m.receiveShadow = true; return m; }

/**
 * 建立 VM-60B1 手臂。
 *   q：起始關節角（度，缺的軸為 0）；ik：覆寫 IK_OPTIONS；dress：是否加上臂／前臂外部線材保護段；name：root 名稱。
 * 回傳 { root, j, L, q（rad，可直接改後呼叫 apply）, limits（度）, tool（工具安裝座）, parts（手臂本體零件）,
 *        apply(), set({ j1..j6 }（度）), ik.solve(tcp, target, quaternion, iters), seeds(origin, quaternion, base) }
 * 手臂裝在會移動的父層（例如滑軌）時：父層移動後先更新父層的 matrixWorld，再呼叫 apply()／ik.solve（apply 只更新手臂本身）。
 */
export function createVM60B1({ q: pose = READY, ik: ikOptions = {}, dress = true, name = 'robot' } = {}) {
  const L = { ...LINKS };
  const root = new THREE.Group(); root.name = name;
  const j = {};
  const base = cyl(120, 140, L.base, matArm); base.position.y = L.base / 2; root.add(base);
  const baseRing = cyl(128, 128, 14, matJoint); baseRing.position.y = L.base - 7.7; root.add(baseRing);   // 環頂比基座頂面低 0.7 mm，避免重合面閃爍

  j.j1 = new THREE.Group(); j.j1.position.y = L.base; root.add(j.j1);                                    // J1 繞 Y
  const shoulderHouse = cyl(100, 110, 140, matArm); shoulderHouse.position.y = 70; j.j1.add(shoulderHouse);
  const shoulderSide = box(L.shoulderX + 110, 190, 220, matArm); shoulderSide.position.set(L.shoulderX / 2, 165, 0); j.j1.add(shoulderSide);

  j.j2 = new THREE.Group(); j.j2.position.set(L.shoulderX, L.shoulderY, 0); j.j1.add(j.j2);               // J2 繞 Z
  const j2disc = cyl(95, 95, 250, matJoint); j2disc.rotation.x = Math.PI / 2; j.j2.add(j2disc);
  const upperArm = box(130, L.upper, 150, matArm); upperArm.position.y = L.upper / 2; j.j2.add(upperArm);
  const upperArmCap = cyl(75, 75, 152, matArm); upperArmCap.rotation.x = Math.PI / 2; upperArmCap.position.y = L.upper; j.j2.add(upperArmCap);

  j.j3 = new THREE.Group(); j.j3.position.set(0, L.upper, 0); j.j2.add(j.j3);                            // J3 繞 Z
  const j3disc = cyl(72, 72, 200, matJoint); j3disc.rotation.x = Math.PI / 2; j.j3.add(j3disc);
  const elbow = box(150, L.foreOffset + 60, 120, matArm); elbow.position.y = L.foreOffset / 2; j.j3.add(elbow);
  // 前臂沿 +X，J4 軸高於 J3 軸 foreOffset
  const foreArm = box(L.fore - L.wrist1 + 30, 100, 110, matArm); foreArm.position.set((L.fore - L.wrist1 - 30) / 2, L.foreOffset, 0); j.j3.add(foreArm);
  // 前臂端蓋縮到前臂寬度內（z ±52、半徑 56），手腕大角度折疊時不碰
  const foreCap = cyl(56, 56, 104, matArm); foreCap.rotation.x = Math.PI / 2; foreCap.position.set(L.fore - L.wrist1, L.foreOffset, 0); j.j3.add(foreCap);
  if (dress) armDress(j, L, { upperDepth: 76, foreDepth: 56, large: true });
  // J2／J3 關節蓋螺栓（各 6 顆）
  for (const joint of [j.j2, j.j3]) for (let k = 0; k < 6; k++) cylinder(joint, 4, 3, [45 * Math.cos(k * Math.PI / 3), 45 * Math.sin(k * Math.PI / 3), 104], VM60B1_MAT.bolt, 'z', 6);

  j.j4 = new THREE.Group(); j.j4.position.set(L.fore - L.wrist1, L.foreOffset, 0); j.j3.add(j.j4);       // J4 繞 X（前臂軸 roll）
  const w1 = cyl(52, 52, L.wrist1, matArm); w1.rotation.z = Math.PI / 2; w1.position.x = L.wrist1 / 2; j.j4.add(w1);
  j.j5 = new THREE.Group(); j.j5.position.set(L.wrist1, 0, 0); j.j4.add(j.j5);                           // J5 繞 Z
  const w2 = cyl(48, 48, 120, matJoint); w2.rotation.x = Math.PI / 2; j.j5.add(w2);
  const w2b = box(L.wrist2, 80, 80, matArm); w2b.position.x = L.wrist2 / 2; j.j5.add(w2b);
  j.j6 = new THREE.Group(); j.j6.position.set(L.wrist2, 0, 0); j.j5.add(j.j6);                           // J6 繞 X（法蘭 roll）
  const flange = cyl(40, 40, L.flange, matJoint); flange.rotation.z = Math.PI / 2; flange.position.x = L.flange / 2; j.j6.add(flange);

  // 手臂本體零件（具名），供專案做手臂對工具的自身間隙檢查；基座環與法蘭不具名（與原專案檢查報告的名稱一致）
  const parts = [base, shoulderHouse, shoulderSide, j2disc, upperArm, upperArmCap, j3disc, elbow, foreArm, foreCap, w1, w2, w2b];
  ['base', 'shoulder', 'shoulder-side', 'J2', 'upper-arm', 'elbow-cap', 'J3', 'elbow', 'forearm', 'forearm-cap', 'J4', 'J5', 'wrist']
    .forEach((n, i) => { parts[i].name = n; });

  // 工具安裝座：法蘭面中心，局部 +Z 沿法蘭軸向外（工具前進方向）
  const tool = new THREE.Group(); tool.position.x = L.flange; tool.rotation.y = Math.PI / 2; j.j6.add(tool);

  // ---- 關節狀態（rad）----
  const q = Object.fromEntries(JOINTS.map(n => [n, (pose[n] ?? 0) * D2R]));
  const limits = Object.fromEntries(JOINTS.map(n => [n, [...LIMITS[n]]]));
  function apply() {
    j.j1.rotation.set(0, q.j1, 0); j.j2.rotation.set(0, 0, q.j2); j.j3.rotation.set(0, 0, q.j3);
    j.j4.rotation.set(q.j4, 0, 0); j.j5.rotation.set(0, 0, q.j5); j.j6.rotation.set(q.j6, 0, 0);
    root.updateMatrixWorld(true);
  }
  apply();
  const ik = createIK({ q, j, tool, apply, limits, ...IK_OPTIONS, ...ikOptions });

  /** 關節角（度）；超出限位者夾回限位內 */
  function set(deg = {}) {
    for (const n of JOINTS) if (deg[n] != null) q[n] = THREE.MathUtils.clamp(deg[n], ...limits[n]) * D2R;
    apply();
  }

  // 幾何初始解：給工具安裝座的世界位置 origin 與姿態 quaternion，回傳肘部上下 × 手腕翻轉共四組關節角（rad），
  // 角度折回限位內；供 ik.solve 當初值逐組求解。base：手臂基座底面中心的世界座標（root 不旋轉；預設 root.position，
  // 裝在滑軌等移動父層上時由專案給目前位置）。
  function wrapJ(n, v) { const [lo, hi] = limits[n].map(x => x * D2R); for (const k of [0, 2 * Math.PI, -2 * Math.PI]) if (v + k >= lo && v + k <= hi) return v + k; return THREE.MathUtils.clamp(v, lo, hi); }
  function seeds(origin, quaternion, base = root.position) {
    const dir = new THREE.Vector3(0, 0, 1).applyQuaternion(quaternion);
    const wrist = origin.clone().addScaledVector(dir, -L.wrist2 - L.flange).sub(new THREE.Vector3(base.x, base.y + L.base + L.shoulderY, base.z));
    const radial = Math.hypot(wrist.x, wrist.z) - L.shoulderX, a = L.upper, b = Math.hypot(L.fore, L.foreOffset), phi = Math.atan2(L.foreOffset, L.fore);
    const j1 = Math.atan2(-wrist.z, wrist.x), elbow = Math.acos(THREE.MathUtils.clamp((radial * radial + wrist.y * wrist.y - a * a - b * b) / (2 * a * b), -1, 1)), out = [];
    for (const beta of [-elbow, elbow]) {
      const j2 = Math.atan2(wrist.y, radial) - Math.atan2(b * Math.sin(beta), a + b * Math.cos(beta)) - Math.PI / 2, j3 = beta + Math.PI / 2 - phi;
      const shoulderQ = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), j1).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), j2 + j3));
      const relative = shoulderQ.invert().multiply(quaternion).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -Math.PI / 2));
      const m = new THREE.Matrix4().makeRotationFromQuaternion(relative).elements;
      const j5 = Math.acos(THREE.MathUtils.clamp(m[0], -1, 1));
      let j4 = 0, j6 = Math.atan2(m[6], m[5]); if (Math.sin(j5) > 1e-5) { j4 = Math.atan2(m[2], m[1]); j6 = Math.atan2(m[8], -m[4]); }
      for (const [w4, w5, w6] of [[j4, j5, j6], [j4 + Math.PI, -j5, j6 + Math.PI]]) {
        const c = { j1, j2, j3, j4: w4, j5: w5, j6: w6 }; for (const n in limits) c[n] = wrapJ(n, c[n]); out.push(c);
      }
    }
    return out;
  }

  return { root, j, L, q, limits, tool, parts, apply, set, ik, seeds };
}

// ---------------------------------------------------------------- 模型目錄
// 目錄只把 J2 負向與 J3 負向收窄（其餘四軸為全限位）：模型目錄把六軸同時從最小掃到最大，
// J2 −135°（上臂大幅後仰）配 J3 −78° 時，簡化的方塊前臂、J4／J5 手腕會折回去撞基座與肩部外殼；
// 實機以 DENSO 干涉區設定限制，這裡收到 J2 ≥ −90°、J3 ≥ −70° 後全程無干涉（與 core/verify/models.mjs 相同的掃描）。
export const meta = {
  id: 'denso-vm60b1', name: 'DENSO VM-60B1 六軸手臂', category: '機械手臂', source: 'MilitaryGradePC',
  params: {},
  states: {
    j1: { value: READY.j1, min: -170, max: 170, unit: '°', label: 'J1 基座旋轉' },
    j2: { value: READY.j2, min: -90, max: 90, unit: '°', label: 'J2 上臂' },
    j3: { value: READY.j3, min: -70, max: 170, unit: '°', label: 'J3 前臂（0＝前臂水平）' },
    j4: { value: READY.j4, min: -185, max: 185, unit: '°', label: 'J4 前臂旋轉' },
    j5: { value: READY.j5, min: -120, max: 120, unit: '°', label: 'J5 手腕彎曲' },
    j6: { value: READY.j6, min: -360, max: 360, unit: '°', label: 'J6 法蘭旋轉' },
  },
  usage: "import { createVM60B1, JOINT_SPEED } from '@core/models/robots/denso-vm60b1.js';\nconst arm = createVM60B1({ q: { j1: -90, j2: -30, j5: -50 } }); scene.add(arm.root);\narm.tool.add(myTool);          // 工具安裝座：法蘭面，+Z 為工具前進方向\narm.set({ j1, j2, j3, j4, j5, j6 });   // 度；或改 arm.q（rad）後 arm.apply()\narm.ik.solve(tcpObject, targetWorld, toolQuaternion, 100); arm.seeds(toolOrigin, toolQuaternion, baseWorld);",
};
export function create() {
  const arm = createVM60B1({ name: 'denso-vm60b1' });
  return { root: arm.root, arm, set(s = {}) { arm.set(s); } };
}
