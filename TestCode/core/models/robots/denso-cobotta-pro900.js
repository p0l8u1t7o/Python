// DENSO COBOTTA PRO 900 協作型六軸手臂（不含末端工具）。共用模型，原用於 AutomaticAcid-BaseTitration。
// 局部座標：原點在底座盤底面中心，+Y 朝上；j1 繞 Y，j2／j3／j5 繞 Z，j4／j6 繞 X（與 core/robot/kinematics.js 相同）。
// 全部關節角為 0 時上臂垂直、前臂朝 +X 水平、手腕沿 +X；法蘭面朝 +X。單位 mm。
// 工具掛在 mount：mount 的 +Z 為工具前進方向（法蘭法線），工具在專案裡建立後加到 arm.mount 底下即可。
// 連桿長度為示意值（最大到達半徑約 900 mm），需以 DENSO CAD 核對。
import * as THREE from 'three';
import { cable, armDress, CABLE } from '../../electrical/cable-routing.js';
import { createIK } from '../../robot/kinematics.js';
import { cylinder, decal } from '../../geom/primitives.js';

const D2R = Math.PI / 180;

// 連桿尺寸：基座到 J2 高 290（base 160 + shoulderY 130）、上臂 450、前臂 450、J5 到法蘭 110
export const L = Object.freeze({ base: 160, shoulderY: 130, shoulderX: 0, upper: 450, fore: 450, foreOffset: 0, wrist1: 120, wrist2: 100, flange: 10 });
export const JOINTS = Object.freeze(['j1', 'j2', 'j3', 'j4', 'j5', 'j6']);
// COBOTTA PRO 900 型錄範圍：J1 ±270、J2 ±150、J3 ±150、J4 ±270、J5 ±150、J6 ±360（假設，需核對）。
// 換算到本模型座標（假設 DENSO J2 零點為上臂垂直、J3=90° 為前臂水平；正向相反）：j2 = −J2、j3 = 90° − J3。
export const LIMITS = Object.freeze({ j1: [-270, 270], j2: [-150, 150], j3: [-60, 240], j4: [-270, 270], j5: [-150, 150], j6: [-360, 360] });
// 型錄最高速度（°/s，假設）
export const MAX_SPEED = Object.freeze({ j1: 240, j2: 200, j3: 240, j4: 300, j5: 300, j6: 360 });
// 預設運轉速度（rad/s）：型錄最高速度的 50%；協作模式（偵測到人員）另由專案降速
export const JOINT_SPEED = Object.freeze({ j1: 2.09, j2: 1.75, j3: 2.09, j4: 2.62, j5: 2.62, j6: 3.14 });

// 材質（手臂外殼、關節環、金屬件、狀態燈）；專案的工具可沿用 MAT.tool 讓顏色一致
export const MAT = {
  arm: new THREE.MeshStandardMaterial({ color: 0xf2f3f1, roughness: 0.38, metalness: 0.05 }),
  joint: new THREE.MeshStandardMaterial({ color: 0x2a2e33, roughness: 0.45, metalness: 0.35 }),
  tool: new THREE.MeshStandardMaterial({ color: 0x9aa3ad, roughness: 0.35, metalness: 0.75 }),
  led: new THREE.MeshStandardMaterial({ color: 0x3dd6c4, emissive: 0x3dd6c4, emissiveIntensity: 1.1 }),
};

function cyl(r1, r2, h, mat, seg = 36) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, seg), mat); m.castShadow = m.receiveShadow = true; return m; }
function box(w, h, d, mat) {
  const b = Math.min(7, w / 8, h / 8, d / 8), s = new THREE.Shape();
  s.moveTo(-w / 2 + b, -h / 2 + b); s.lineTo(w / 2 - b, -h / 2 + b); s.lineTo(w / 2 - b, h / 2 - b); s.lineTo(-w / 2 + b, h / 2 - b); s.closePath();
  const geo = new THREE.ExtrudeGeometry(s, { depth: d - 2 * b, bevelEnabled: true, bevelSize: b, bevelThickness: b, bevelSegments: 3, steps: 1 }); geo.translate(0, 0, -d / 2 + b);
  const m = new THREE.Mesh(geo, mat); m.castShadow = m.receiveShadow = true; return m;
}

/**
 * 建立手臂（含 IK）。
 * @param {object} o
 * @param {object} [o.q]     初始關節角（rad），未給的關節為 0
 * @param {boolean} [o.dress] 是否畫手臂外部線材（上臂／前臂護套、底座電源入口），預設 true
 * @param {object} [o.ik]    傳給 core/robot/kinematics.js createIK 的調校參數（weight、lambda、step、tol…）
 * @returns {{ root, j, q, L, limits, JOINT_SPEED, mount, armParts, apply, setDegrees, ik, seedJoints, wrapJoint }}
 *   root：Group 'robot'；j.j1～j.j6：關節群組；mount：工具安裝座（+Z＝工具前進方向）；
 *   armParts：手臂本體零件（不含線材，自我間隙檢查用）；apply()：把 q 套到關節並更新世界矩陣；
 *   ik.solve(tcp, target, quaternion, iters)：阻尼最小平方 IK（姿態以 mount 為準）；
 *   seedJoints(origin, quaternion, opts)：由工具安裝座目標（世界座標）求幾何初始解。
 */
export function createCobottaPro900({ q: q0 = {}, dress = true, ik: ikOptions = {} } = {}) {
  const root = new THREE.Group(); root.name = 'robot';
  const j = {};
  // 基座從底座盤頂面（14）起算，底面不與底座盤底面重合（避免閃爍）；錐度與原本 0～160 相同
  const base = cyl(95, 110 - 15 * 14 / L.base, L.base - 14, MAT.arm); base.position.y = 14 + (L.base - 14) / 2; root.add(base);
  const foot = cyl(125, 125, 14, MAT.joint); foot.position.y = 7; root.add(foot);
  const ledBase = cyl(97, 97, 6, MAT.led); ledBase.position.y = L.base - 12; root.add(ledBase);
  decal(root, 110, 26, [0, 60, 111], [0, 0, 0], 'DENSO', { color: '#c8102e', center: true, bold: true });

  j.j1 = new THREE.Group(); j.j1.position.y = L.base; root.add(j.j1);                               // J1 繞 Y
  const shoulder = cyl(88, 92, 120, MAT.arm); shoulder.position.y = 60; j.j1.add(shoulder);
  j.j2 = new THREE.Group(); j.j2.position.set(L.shoulderX, L.shoulderY, 0); j.j1.add(j.j2);          // J2 繞 Z
  const j2disc = cyl(80, 80, 200, MAT.arm); j2disc.rotation.x = Math.PI / 2; j.j2.add(j2disc);
  const j2cap = cyl(62, 62, 204, MAT.joint); j2cap.rotation.x = Math.PI / 2; j.j2.add(j2cap);
  for (const side of [-1, 1]) for (let k = 0; k < 6; k++) { const a = k * Math.PI / 3; cylinder(j.j2, 3, 1, [Math.cos(a) * 48, Math.sin(a) * 48, side * 102.5], MAT.tool, 'z', 12); }
  const upper = box(110, L.upper, 120, MAT.arm); upper.position.y = L.upper / 2; j.j2.add(upper);
  const upperCap = cyl(66, 66, 150, MAT.arm); upperCap.rotation.x = Math.PI / 2; upperCap.position.y = L.upper; j.j2.add(upperCap);
  const ledUp = cyl(67, 67, 6, MAT.led); ledUp.rotation.x = Math.PI / 2; ledUp.position.set(0, L.upper, 70); j.j2.add(ledUp);
  decal(j.j2, 70, 190, [0, 230, 61], [0, 0, 0], ['COBOTTA', 'PRO 900'], { color: '#4a525b', center: true });

  j.j3 = new THREE.Group(); j.j3.position.set(0, L.upper, 0); j.j2.add(j.j3);                       // J3 繞 Z
  const j3disc = cyl(60, 60, 140, MAT.joint); j3disc.rotation.x = Math.PI / 2; j.j3.add(j3disc);
  const fore = box(L.fore - L.wrist1 + 20, 90, 96, MAT.arm); fore.position.set((L.fore - L.wrist1 - 20) / 2, L.foreOffset, 0); j.j3.add(fore);
  j.j4 = new THREE.Group(); j.j4.position.set(L.fore - L.wrist1, L.foreOffset, 0); j.j3.add(j.j4);   // J4 繞 X
  const w1 = cyl(46, 46, L.wrist1, MAT.arm); w1.rotation.z = Math.PI / 2; w1.position.x = L.wrist1 / 2; j.j4.add(w1);
  const ledW = cyl(47, 47, 5, MAT.led); ledW.rotation.z = Math.PI / 2; ledW.position.x = 8; j.j4.add(ledW);
  j.j5 = new THREE.Group(); j.j5.position.set(L.wrist1, 0, 0); j.j4.add(j.j5);                      // J5 繞 Z
  const w2 = cyl(44, 44, 100, MAT.arm); w2.rotation.x = Math.PI / 2; j.j5.add(w2);
  const w2cap = cyl(34, 34, 104, MAT.joint); w2cap.rotation.x = Math.PI / 2; j.j5.add(w2cap);
  const w2b = cyl(40, 40, L.wrist2, MAT.arm); w2b.rotation.z = Math.PI / 2; w2b.position.x = L.wrist2 / 2; j.j5.add(w2b);
  j.j6 = new THREE.Group(); j.j6.position.set(L.wrist2, 0, 0); j.j5.add(j.j6);                      // J6 繞 X
  const flange = cyl(32, 32, L.flange, MAT.joint); flange.rotation.z = Math.PI / 2; flange.position.x = L.flange / 2; j.j6.add(flange);
  const armParts = [base, shoulder, j2disc, j2cap, upper, upperCap, j3disc, fore, w1, w2, w2cap, w2b];
  ['base', 'shoulder', 'J2', 'J2-cap', 'upper-arm', 'elbow-cap', 'J3', 'forearm', 'J4', 'J5', 'J5-cap', 'wrist']
    .forEach((name, i) => { armParts[i].name = name; });

  // 工具安裝座：法蘭面上，+Z 沿法蘭法線（j6 的 +X）
  const mount = new THREE.Group(); mount.position.x = L.flange; mount.rotation.y = Math.PI / 2; j.j6.add(mount);

  if (dress) {
    armDress(j, L, { upperDepth: 61, foreDepth: 49 });
    cable(root, 'PWR / base inlet', [[-165, 0, 0], [-165, 25, 0], [-135, 50, 0], [-116, 50, 0]], { radius: 6, color: CABLE.power });
  }

  // ---- 關節狀態 ----
  const q = { j1: 0, j2: 0, j3: 0, j4: 0, j5: 0, j6: 0, ...q0 };
  const limits = Object.fromEntries(JOINTS.map(n => [n, [...LIMITS[n]]]));
  function apply() {
    j.j1.rotation.set(0, q.j1, 0); j.j2.rotation.set(0, 0, q.j2); j.j3.rotation.set(0, 0, q.j3);
    j.j4.rotation.set(q.j4, 0, 0); j.j5.rotation.set(0, 0, q.j5); j.j6.rotation.set(q.j6, 0, 0);
    root.updateMatrixWorld(true);
  }
  /** 以角度（°）設定關節，未給的不變 */
  function setDegrees(deg = {}) { for (const n of JOINTS) if (deg[n] != null) q[n] = deg[n] * D2R; apply(); }
  apply();
  const ik = createIK({ q, j, tool: mount, apply, limits, ...ikOptions });

  /** 把角度折回限位內（先試 ±360°，都不行再夾住） */
  function wrapJoint(name, v) { const [lo, hi] = limits[name].map(x => x * D2R); for (const k of [0, 2 * Math.PI, -2 * Math.PI]) if (v + k >= lo && v + k <= hi) return v + k; return THREE.MathUtils.clamp(v, lo, hi); }
  /**
   * 幾何初始解：給工具安裝座原點（世界座標）與姿態，回傳關節角組（rad）。手臂 root 只可平移（不旋轉、不縮放）。
   * 每個肘部解各有手腕不翻／翻轉兩組；角度以 wrapJoint 折回限位內。
   * @param {THREE.Vector3} origin  mount 原點的世界位置（不會被修改）
   * @param {THREE.Quaternion} quaternion  mount 的世界姿態
   * @param {{ wrapJ1?: (v:number)=>number, elbowDown?: boolean }} [opts]  wrapJ1：J1 角度窗；elbowDown：另加肘部朝下的解
   */
  function seedJoints(origin, quaternion, { wrapJ1 = v => v, elbowDown = false } = {}) {
    const dir = new THREE.Vector3(0, 0, 1).applyQuaternion(quaternion);
    const wrist = origin.clone().addScaledVector(dir, -L.wrist2 - L.flange).sub(new THREE.Vector3(root.position.x, root.position.y + L.base + L.shoulderY, root.position.z));
    const radial = Math.hypot(wrist.x, wrist.z) - L.shoulderX, a = L.upper, b = Math.hypot(L.fore, L.foreOffset), phi = Math.atan2(L.foreOffset, L.fore);
    const j1 = wrapJ1(Math.atan2(-wrist.z, wrist.x)), elbow = Math.acos(THREE.MathUtils.clamp((radial * radial + wrist.y * wrist.y - a * a - b * b) / (2 * a * b), -1, 1)), out = [];
    for (const beta of elbowDown ? [-elbow, elbow] : [-elbow]) {             // −elbow 為肘部朝上（j3 < 90°）
      const j2 = Math.atan2(wrist.y, radial) - Math.atan2(b * Math.sin(beta), a + b * Math.cos(beta)) - Math.PI / 2, j3 = beta + Math.PI / 2 - phi;
      const shoulderQ = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), j1).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), j2 + j3));
      const relative = shoulderQ.invert().multiply(quaternion).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -Math.PI / 2));
      const m = new THREE.Matrix4().makeRotationFromQuaternion(relative).elements;
      const j5 = Math.acos(THREE.MathUtils.clamp(m[0], -1, 1));
      let j4 = 0, j6 = Math.atan2(m[6], m[5]); if (Math.sin(j5) > 1e-5) { j4 = Math.atan2(m[2], m[1]); j6 = Math.atan2(m[8], -m[4]); }
      for (const [w4, w5, w6] of [[j4, j5, j6], [j4 + Math.PI, -j5, j6 + Math.PI]]) {
        const c = { j1, j2, j3, j4: w4, j5: w5, j6: w6 }; for (const name in limits) c[name] = wrapJoint(name, c[name]); out.push(c);
      }
    }
    return out;
  }

  return { root, j, q, L, limits, JOINT_SPEED, mount, armParts, apply, setDegrees, ik, seedJoints, wrapJoint };
}

// ---------------------------------------------------------------- 模型目錄
// 目錄的狀態範圍比關節限位窄：檢查會把六軸同時由最小掃到最大，用滿限位（j2 ±150、j3 −60～240）時前臂、上臂會掃進底座。
export const meta = {
  id: 'denso-cobotta-pro900', name: 'DENSO COBOTTA PRO 900 協作手臂', category: '機械手臂', source: 'AutomaticAcid-BaseTitration',
  params: {},
  states: {
    j1: { value: 0, min: -180, max: 180, unit: '°', label: 'J1 底座旋轉' },
    j2: { value: -20, min: -90, max: 90, unit: '°', label: 'J2 肩（0＝上臂垂直）' },
    j3: { value: 70, min: -30, max: 180, unit: '°', label: 'J3 肘（90＝前臂與上臂成直線）' },
    j4: { value: 0, min: -180, max: 180, unit: '°', label: 'J4 前臂旋轉' },
    j5: { value: -50, min: -130, max: 130, unit: '°', label: 'J5 手腕彎曲' },
    j6: { value: 0, min: -360, max: 360, unit: '°', label: 'J6 法蘭旋轉' },
  },
  usage: "import { createCobottaPro900, JOINT_SPEED } from '@core/models/robots/denso-cobotta-pro900.js';\nconst arm = createCobottaPro900({ q: { j2: -20 * Math.PI / 180 } }); scene.add(arm.root);\narm.mount.add(myTool);                 // +Z＝工具前進方向\narm.ik.solve(tcp, target, quaternion); // 或 arm.setDegrees({ j1, j2, j3, j4, j5, j6 })",
};

export function create() {
  const arm = createCobottaPro900();
  return { root: arm.root, arm, set(state = {}) { arm.setDegrees(state); } };
}
