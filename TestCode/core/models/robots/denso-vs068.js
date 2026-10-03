// DENSO VS-068 六軸垂直多關節手臂（共用模型）：基座、連桿、關節群組 j1～j6、手臂外部線材保護段、法蘭工具安裝座與 IK。
// 原用於 RobotArmPressSSD（SSD USB 接頭壓合站）。單位 mm；局部 +Y 朝上，原點在基座底面中心。
// 關節軸：j1 繞 Y、j2／j3／j5 繞 Z、j4／j6 繞 X（與 core/robot/kinematics.js 相同）。
// 工具安裝座 arm.tool：在法蘭面上，局部 +Z 為工具前進方向；末端工具、TCP 與流程規劃由各專案自行掛在這裡。
import * as THREE from 'three';
import { cable, armDress, CABLE } from '../../electrical/cable-routing.js';
import { createIK } from '../../robot/kinematics.js';
import { decal, bevelBox, screw } from '../../geom/primitives.js';

const D2R = Math.PI / 180;
export const JOINTS = ['j1', 'j2', 'j3', 'j4', 'j5', 'j6'];

// 連桿（DENSO VS-068 型錄：臂長 340＋340、動作半徑 710）。
// 基座到 J2 高度 345、J5 到法蘭 80 為參考值，型錄未列，需以 DENSO CAD 核對。
export const LINKS = Object.freeze({ base: 200, shoulderY: 145, shoulderX: 0, upper: 340, fore: 340, foreOffset: 0, wrist1: 120, wrist2: 70, flange: 10 });
// 關節限位（度）。VS-068 型錄範圍：J1 ±170、J2 +135/−100、J3 +153/−120、J4 ±270、J5 ±120、J6 ±360。
// 換算到本模型座標（假設 DENSO J2 零點為上臂垂直、J3=90° 為前臂水平；正向相反）：j2 = −J2、j3 = 90° − J3。
export const LIMITS = Object.freeze({ j1: [-170, 170], j2: [-135, 100], j3: [-63, 210], j4: [-270, 270], j5: [-120, 120], j6: [-360, 360] });
// 關節速度上限（rad/s）：取型錄最高速度（J1 356、J2 303、J3 379、J4 475、J5 475、J6 760 °/s）的 50%
export const JOINT_SPEED = Object.freeze({ j1: 3.1, j2: 2.6, j3: 3.3, j4: 4.1, j5: 4.1, j6: 6.6 });
// 預設姿態（度）：上臂微後仰、前臂前伸、手腕朝下
export const READY = Object.freeze({ j1: 0, j2: -10, j3: 40, j4: 0, j5: -70, j6: 0 });
// IK 參數（core/robot/kinematics.js 的 DENSO 調校值，明確寫出以免預設值變動影響既有專案）
export const IK_OPTIONS = Object.freeze({ weight: 180, iterations: 16, lambda: [6, 2], step: .22, tol: [.08, .001] });

// 材質：工具可沿用 dark（深灰機身）與 joint（黑色關節）讓外觀一致
export const VS068_MAT = {
  arm: new THREE.MeshStandardMaterial({ color: 0xeceeef, roughness: 0.42, metalness: 0.12 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x30353b, roughness: 0.5, metalness: 0.3 }),
  joint: new THREE.MeshStandardMaterial({ color: 0x1c1f23, roughness: 0.4, metalness: 0.5 }),
};
const matArm = VS068_MAT.arm, matJoint = VS068_MAT.joint;

function cyl(r1, r2, h, mat, seg = 32) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, seg), mat); m.castShadow = m.receiveShadow = true; return m; }
function box(w, h, d, mat) { return bevelBox(w, h, d, mat, Math.min(6, w * .08)); }

/**
 * 建立 VS-068 手臂。
 *   q：起始關節角（度，缺的軸為 0）；ik：覆寫 IK_OPTIONS；dress：是否加手臂外部線材保護段與基座電源線；name：root 名稱。
 * 回傳 { root, j, L, q（rad，可直接改後呼叫 apply）, limits（度）, tool（工具安裝座）, parts（手臂本體零件）,
 *        apply(), set({ j1..j6 }（度）), ik.solve(tcp, target, quaternion, iters), seeds(origin, quaternion) }
 */
export function createVS068({ q: pose = READY, ik: ikOptions = {}, dress = true, name = 'robot' } = {}) {
  const L = { ...LINKS };
  const root = new THREE.Group(); root.name = name;
  const j = {};
  const base = cyl(88, 100, L.base, matArm); base.position.y = L.base / 2; root.add(base);
  const baseRing = cyl(92, 92, 10, matJoint); baseRing.position.y = L.base - 4; root.add(baseRing);   // 頂面高出基座 1 mm，避免重合面閃爍
  decal(root, 90, 22, [0, 70, 101], [0, 0, 0], 'DENSO', { color: '#c8102e', center: true, bold: true });

  j.j1 = new THREE.Group(); j.j1.position.y = L.base; root.add(j.j1);                               // J1 繞 Y
  const shoulder = box(150, 150, 170, matArm); shoulder.position.y = 70; j.j1.add(shoulder);
  j.j2 = new THREE.Group(); j.j2.position.set(L.shoulderX, L.shoulderY, 0); j.j1.add(j.j2);          // J2 繞 Z
  const j2disc = cyl(72, 72, 190, matJoint); j2disc.rotation.x = Math.PI / 2; j.j2.add(j2disc);
  const upper = box(100, L.upper, 110, matArm); upper.position.y = L.upper / 2; j.j2.add(upper);
  const upperCap = cyl(58, 58, 112, matArm); upperCap.rotation.x = Math.PI / 2; upperCap.position.y = L.upper; j.j2.add(upperCap);
  for (let k = 0; k < 6; k++) { const a = k * Math.PI / 3; screw(j.j2, [Math.cos(a) * 58, Math.sin(a) * 58, 96], 4, 'z'); }
  decal(j.j2, 60, 150, [0, 170, 56], [0, 0, 0], ['VS-068', 'DENSO'], { color: '#4a525b', center: true });

  j.j3 = new THREE.Group(); j.j3.position.set(0, L.upper, 0); j.j2.add(j.j3);                       // J3 繞 Z
  const j3disc = cyl(55, 55, 150, matJoint); j3disc.rotation.x = Math.PI / 2; j.j3.add(j3disc);
  for (let k = 0; k < 6; k++) { const a = k * Math.PI / 3; screw(j.j3, [Math.cos(a) * 43, Math.sin(a) * 43, 76], 3.5, 'z'); }
  const fore = box(L.fore - L.wrist1 + 30, 80, 90, matArm); fore.position.set((L.fore - L.wrist1 - 30) / 2, L.foreOffset, 0); j.j3.add(fore);
  j.j4 = new THREE.Group(); j.j4.position.set(L.fore - L.wrist1, L.foreOffset, 0); j.j3.add(j.j4);   // J4 繞 X
  const w1 = cyl(42, 42, L.wrist1, matArm); w1.rotation.z = Math.PI / 2; w1.position.x = L.wrist1 / 2; j.j4.add(w1);
  j.j5 = new THREE.Group(); j.j5.position.set(L.wrist1, 0, 0); j.j4.add(j.j5);                      // J5 繞 Z
  const w2 = cyl(38, 38, 96, matJoint); w2.rotation.x = Math.PI / 2; j.j5.add(w2);
  const w2b = box(L.wrist2, 62, 62, matArm); w2b.position.x = L.wrist2 / 2; j.j5.add(w2b);
  j.j6 = new THREE.Group(); j.j6.position.set(L.wrist2, 0, 0); j.j5.add(j.j6);                      // J6 繞 X
  const flange = cyl(32, 32, L.flange, matJoint); flange.rotation.z = Math.PI / 2; flange.position.x = L.flange / 2; j.j6.add(flange);

  // 手臂本體零件（具名），供專案做手臂對工具的自身間隙檢查
  const parts = [base, baseRing, shoulder, j2disc, upper, upperCap, j3disc, fore, w1, w2, w2b, flange];
  ['base', 'base-ring', 'shoulder', 'J2', 'upper-arm', 'elbow-cap', 'J3', 'forearm', 'J4', 'J5', 'wrist', 'flange']
    .forEach((n, i) => { parts[i].name = n; });

  // 工具安裝座：法蘭面中心，局部 +Z 沿法蘭軸向外（工具前進方向）
  const tool = new THREE.Group(); tool.position.x = L.flange; tool.rotation.y = Math.PI / 2; j.j6.add(tool);

  if (dress) {
    armDress(j, L, { upperDepth: 56, foreDepth: 46 });
    cable(root, 'PWR / base inlet', [[0, 0, -180], [0, 32, -180], [0, 70, -125], [0, 80, -100]], { radius: 7, color: CABLE.power });
  }

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

  // 幾何初始解：給工具安裝座的世界位置 origin 與姿態 quaternion（root 不旋轉、無父層變換），
  // 回傳肘部上下 × 手腕翻轉共四組關節角（rad），角度折回限位內；供 ik.solve 當初值逐組求解。
  function wrapJ(n, v) { const [lo, hi] = limits[n].map(x => x * D2R); for (const k of [0, 2 * Math.PI, -2 * Math.PI]) if (v + k >= lo && v + k <= hi) return v + k; return THREE.MathUtils.clamp(v, lo, hi); }
  function seeds(origin, quaternion) {
    const dir = new THREE.Vector3(0, 0, 1).applyQuaternion(quaternion);
    const wrist = origin.clone().addScaledVector(dir, -L.wrist2 - L.flange).sub(new THREE.Vector3(root.position.x, root.position.y + L.base + L.shoulderY, root.position.z));
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
// 目錄的狀態範圍比限位窄：模型目錄把六軸同時從最小掃到最大，全限位組合會讓前臂／手腕撞上基座或上臂。
export const meta = {
  id: 'denso-vs068', name: 'DENSO VS-068 六軸手臂', category: '機器手臂', source: 'RobotArmPressSSD',
  params: {},
  states: {
    j1: { value: READY.j1, min: -170, max: 170, unit: '°', label: 'J1 基座旋轉' },
    j2: { value: READY.j2, min: -80, max: 90, unit: '°', label: 'J2 上臂' },
    j3: { value: READY.j3, min: -40, max: 170, unit: '°', label: 'J3 前臂（0＝與上臂垂直）' },
    j4: { value: READY.j4, min: -270, max: 270, unit: '°', label: 'J4 前臂旋轉' },
    j5: { value: READY.j5, min: -120, max: 120, unit: '°', label: 'J5 手腕彎曲' },
    j6: { value: READY.j6, min: -360, max: 360, unit: '°', label: 'J6 法蘭旋轉' },
  },
  usage: "import { createVS068, JOINT_SPEED } from '@core/models/robots/denso-vs068.js';\nconst arm = createVS068({ q: { j1: -90, j2: -10, j3: 40, j5: -70 } }); scene.add(arm.root);\narm.tool.add(myTool);          // 工具安裝座：法蘭面，+Z 為工具前進方向\narm.set({ j1, j2, j3, j4, j5, j6 });   // 度；或改 arm.q（rad）後 arm.apply()\narm.ik.solve(tcpObject, targetWorld, toolQuaternion, 100); arm.seeds(toolOrigin, toolQuaternion);",
};
export function create() {
  const arm = createVS068({ name: 'denso-vs068' });
  return { root: arm.root, arm, set(s = {}) { arm.set(s); } };
}
