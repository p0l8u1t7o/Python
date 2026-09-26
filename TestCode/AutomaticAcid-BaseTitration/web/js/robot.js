// DENSO COBOTTA PRO 900 協作型六軸手臂＋長行程電動平行夾爪
// 工具本地座標：+Z 為工具前進方向（朝下）、X 為夾爪開合方向、Y 為手指厚度方向。單位 mm。
import * as THREE from 'three';
import { createIK } from './kinematics.js';
import { block, cylinder, decal } from './detail.js';

const matArm   = new THREE.MeshStandardMaterial({ color: 0xf2f3f1, roughness: 0.38, metalness: 0.05 });
const matJoint = new THREE.MeshStandardMaterial({ color: 0x2a2e33, roughness: 0.45, metalness: 0.35 });
const matTool  = new THREE.MeshStandardMaterial({ color: 0x9aa3ad, roughness: 0.35, metalness: 0.75 });
const matAnod  = new THREE.MeshStandardMaterial({ color: 0x3b4149, roughness: 0.4, metalness: 0.6 });
const matPad   = new THREE.MeshStandardMaterial({ color: 0x1b1d20, roughness: 0.95 });
const matLed   = new THREE.MeshStandardMaterial({ color: 0x3dd6c4, emissive: 0x3dd6c4, emissiveIntensity: 1.1 });
const D2R = Math.PI / 180;

function cyl(r1, r2, h, mat, seg = 36) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, seg), mat); m.castShadow = m.receiveShadow = true; return m; }
function box(w, h, d, mat) {
  const b=Math.min(7,w/8,h/8,d/8),s=new THREE.Shape();
  s.moveTo(-w/2+b,-h/2+b);s.lineTo(w/2-b,-h/2+b);s.lineTo(w/2-b,h/2-b);s.lineTo(-w/2+b,h/2-b);s.closePath();
  const geo=new THREE.ExtrudeGeometry(s,{depth:d-2*b,bevelEnabled:true,bevelSize:b,bevelThickness:b,bevelSegments:3,steps:1});geo.translate(0,0,-d/2+b);
  const m = new THREE.Mesh(geo, mat); m.castShadow = m.receiveShadow = true; return m;
}

// 夾爪幾何（排程與驗證共用）
export const TOOL = {
  body: [180, 70, 80], bodyZ: 10,       // 夾爪本體（開合方向 × 厚度 × 高度），法蘭下 10 mm 起
  finger: [12, 28, 110], fingerZ: 90,   // 手指（厚 × 寬 × 長），從工具 z 90 伸到 200
  tcp: 185,                             // 夾持中心：指墊中段（指尖在 TCP 下 15 mm）
  maxWidth: 160,                        // 最大開口（OnRobot RG6 級長行程）
};

export function createRobot() {
  const root = new THREE.Group(); root.name = 'robot';
  // ---- 連桿（COBOTTA PRO 900：最大到達半徑約 900 mm）----
  // 基座到 J2 高 290、上臂 450、前臂 450、J5 到法蘭 110 為示意值，需以 DENSO CAD 核對。
  const L = { base: 160, shoulderY: 130, shoulderX: 0, upper: 450, fore: 450, foreOffset: 0, wrist1: 120, wrist2: 100, flange: 10 };
  const j = {};
  const base = cyl(95, 110, L.base, matArm); base.position.y = L.base / 2; root.add(base);
  const foot = cyl(125, 125, 14, matJoint); foot.position.y = 7; root.add(foot);
  const ledBase = cyl(97, 97, 6, matLed); ledBase.position.y = L.base - 12; root.add(ledBase);
  decal(root, 110, 26, [0, 60, 111], [0, 0, 0], 'DENSO', { color: '#c8102e', center: true, bold: true });

  j.j1 = new THREE.Group(); j.j1.position.y = L.base; root.add(j.j1);                               // J1 繞 Y
  const shoulder = cyl(88, 92, 120, matArm); shoulder.position.y = 60; j.j1.add(shoulder);
  j.j2 = new THREE.Group(); j.j2.position.set(L.shoulderX, L.shoulderY, 0); j.j1.add(j.j2);          // J2 繞 Z
  const j2disc = cyl(80, 80, 200, matArm); j2disc.rotation.x = Math.PI / 2; j.j2.add(j2disc);
  const j2cap = cyl(62, 62, 204, matJoint); j2cap.rotation.x = Math.PI / 2; j.j2.add(j2cap);
  for(const side of [-1,1])for(let k=0;k<6;k++){const a=k*Math.PI/3;cylinder(j.j2,3,1,[Math.cos(a)*48,Math.sin(a)*48,side*102.5],matTool,'z',12);}
  const upper = box(110, L.upper, 120, matArm); upper.position.y = L.upper / 2; j.j2.add(upper);
  const upperCap = cyl(66, 66, 150, matArm); upperCap.rotation.x = Math.PI / 2; upperCap.position.y = L.upper; j.j2.add(upperCap);
  const ledUp = cyl(67, 67, 6, matLed); ledUp.rotation.x = Math.PI / 2; ledUp.position.set(0, L.upper, 70); j.j2.add(ledUp);
  decal(j.j2, 70, 190, [0, 230, 61], [0, 0, 0], ['COBOTTA', 'PRO 900'], { color: '#4a525b', center: true });

  j.j3 = new THREE.Group(); j.j3.position.set(0, L.upper, 0); j.j2.add(j.j3);                       // J3 繞 Z
  const j3disc = cyl(60, 60, 140, matJoint); j3disc.rotation.x = Math.PI / 2; j.j3.add(j3disc);
  const fore = box(L.fore - L.wrist1 + 20, 90, 96, matArm); fore.position.set((L.fore - L.wrist1 - 20) / 2, L.foreOffset, 0); j.j3.add(fore);
  j.j4 = new THREE.Group(); j.j4.position.set(L.fore - L.wrist1, L.foreOffset, 0); j.j3.add(j.j4);   // J4 繞 X
  const w1 = cyl(46, 46, L.wrist1, matArm); w1.rotation.z = Math.PI / 2; w1.position.x = L.wrist1 / 2; j.j4.add(w1);
  const ledW = cyl(47, 47, 5, matLed); ledW.rotation.z = Math.PI / 2; ledW.position.x = 8; j.j4.add(ledW);
  j.j5 = new THREE.Group(); j.j5.position.set(L.wrist1, 0, 0); j.j4.add(j.j5);                      // J5 繞 Z
  const w2 = cyl(44, 44, 100, matArm); w2.rotation.x = Math.PI / 2; j.j5.add(w2);
  const w2cap = cyl(34, 34, 104, matJoint); w2cap.rotation.x = Math.PI / 2; j.j5.add(w2cap);
  const w2b = cyl(40, 40, L.wrist2, matArm); w2b.rotation.z = Math.PI / 2; w2b.position.x = L.wrist2 / 2; j.j5.add(w2b);
  j.j6 = new THREE.Group(); j.j6.position.set(L.wrist2, 0, 0); j.j5.add(j.j6);                      // J6 繞 X
  const flange = cyl(32, 32, L.flange, matJoint); flange.rotation.z = Math.PI / 2; flange.position.x = L.flange / 2; j.j6.add(flange);

  // ---- 末端工具：長行程電動平行夾爪（燒杯 Ø65、樣品瓶 Ø56／Ø86、瓶蓋 GL45、移液模組夾持環共用）----
  const tool = new THREE.Group(); tool.position.x = L.flange; tool.rotation.y = Math.PI / 2; j.j6.add(tool);
  cylinder(tool, 32, 10, [0, 0, 5], matAnod, 'z', 28);                                       // 快換轉接盤
  const [bw, bt, bh] = TOOL.body;
  block(tool, [bw, bt, bh], [0, 0, TOOL.bodyZ + bh / 2], matTool);
  block(tool, [bw - 20, bt + 4, 8], [0, 0, TOOL.bodyZ + bh - 4], matAnod);                    // 導軌
  decal(tool, 90, 22, [0, -bt / 2 - 0.5, TOOL.bodyZ + 30], [Math.PI / 2, Math.PI, 0], 'GRIPPER', { color: '#20242a', center: true, bold: true });
  const fingers = [];
  for (const s of [-1, 1]) {
    const f = new THREE.Group(); tool.add(f);
    const [ft, fw, fl] = TOOL.finger;
    block(f, [ft, fw + 6, 16], [0, 0, TOOL.fingerZ + 8], matAnod);                            // 滑座
    block(f, [ft, fw, fl - 16], [0, 0, TOOL.fingerZ + 16 + (fl - 16) / 2], matTool);
    block(f, [3, fw - 4, 34], [-s * (ft / 2 + 1.5), 0, TOOL.tcp], matPad);                  // V 槽指墊
    f.userData.side = s; fingers.push(f);
  }

  // TCP：夾持中心
  const tcpGrip = new THREE.Object3D(); tcpGrip.position.set(0, 0, TOOL.tcp); tool.add(tcpGrip);
  const tcps = { grip: tcpGrip };
  let width = 100;
  /** 夾爪開口（兩指墊內側距離，mm） */
  function setGripper(w) {
    width = THREE.MathUtils.clamp(w, 0, TOOL.maxWidth);
    for (const f of fingers) f.position.x = f.userData.side * (width / 2 + TOOL.finger[0] / 2 + 1.5);
  }
  setGripper(width);

  // ---- 關節狀態 ----
  const q = { j1: -60 * D2R, j2: -20 * D2R, j3: 70 * D2R, j4: 0, j5: -50 * D2R, j6: 0 };
  // COBOTTA PRO 900 型錄範圍：J1 ±270、J2 ±150、J3 ±150、J4 ±270、J5 ±150、J6 ±360（假設，需核對）。
  // 換算到本模型座標（假設 DENSO J2 零點為上臂垂直、J3=90° 為前臂水平；正向相反）：j2 = −J2、j3 = 90° − J3。
  const limits = { j1: [-270, 270], j2: [-150, 150], j3: [-60, 240], j4: [-270, 270], j5: [-150, 150], j6: [-360, 360] };
  // J1 採固定角度窗：每個方向只有一種表示法，手臂在站別間移動時不會繞遠路或穿越設備。
  // 窗的斷點在正前方（−90°），該方向沒有放置任何站別。
  const J1_WINDOW = [-90 * D2R, 270 * D2R];
  const home = { ...q };
  const JOINTS = ['j1', 'j2', 'j3', 'j4', 'j5', 'j6'];
  // 關節速度上限（rad/s）：取型錄最高速度（J1 240、J2 200、J3 240、J4 300、J5 300、J6 360 °/s，假設）的 50%；
  // 協作模式（安全掃描器偵測到人員）另降速，見規劃文件。
  const JOINT_SPEED = { j1: 2.09, j2: 1.75, j3: 2.09, j4: 2.62, j5: 2.62, j6: 3.14 };

  function apply() {
    j.j1.rotation.set(0, q.j1, 0); j.j2.rotation.set(0, 0, q.j2); j.j3.rotation.set(0, 0, q.j3);
    j.j4.rotation.set(q.j4, 0, 0); j.j5.rotation.set(0, 0, q.j5); j.j6.rotation.set(q.j6, 0, 0);
    root.updateMatrixWorld(true);
  }
  apply();
  const ik = createIK({ q, j, tool, apply, limits });

  // ---- 目標 ----
  const goal = { target: new THREE.Vector3(), quaternion: new THREE.Quaternion(), tcp: 'grip', joints: null };
  function getTcpWorld(name = 'grip', out = new THREE.Vector3()) { return tcps[name].getWorldPosition(out); }

  // 幾何初始解：肘部上下 × 手腕翻轉共四組，角度折回限位內
  function wrapJ(name, v) { const [lo, hi] = limits[name].map(x => x * D2R); for (const k of [0, 2 * Math.PI, -2 * Math.PI]) if (v + k >= lo && v + k <= hi) return v + k; return THREE.MathUtils.clamp(v, lo, hi); }
  function inWindow(v) { while (v < J1_WINDOW[0]) v += 2 * Math.PI; while (v >= J1_WINDOW[1]) v -= 2 * Math.PI; return v; }
  function seeds() {
    const dir = new THREE.Vector3(0, 0, 1).applyQuaternion(goal.quaternion);
    const origin = goal.target.clone().sub(tcps[goal.tcp].position.clone().applyQuaternion(goal.quaternion));
    const wrist = origin.addScaledVector(dir, -L.wrist2 - L.flange).sub(new THREE.Vector3(root.position.x, root.position.y + L.base + L.shoulderY, root.position.z));
    const radial = Math.hypot(wrist.x, wrist.z) - L.shoulderX, a = L.upper, b = Math.hypot(L.fore, L.foreOffset), phi = Math.atan2(L.foreOffset, L.fore);
    const j1 = inWindow(Math.atan2(-wrist.z, wrist.x)), elbow = Math.acos(THREE.MathUtils.clamp((radial * radial + wrist.y * wrist.y - a * a - b * b) / (2 * a * b), -1, 1)), out = [];
    for (const beta of [-elbow]) {                                             // 只用肘部朝上（j3 < 90°）
      const j2 = Math.atan2(wrist.y, radial) - Math.atan2(b * Math.sin(beta), a + b * Math.cos(beta)) - Math.PI / 2, j3 = beta + Math.PI / 2 - phi;
      const shoulderQ = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), j1).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), j2 + j3));
      const relative = shoulderQ.invert().multiply(goal.quaternion).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -Math.PI / 2));
      const m = new THREE.Matrix4().makeRotationFromQuaternion(relative).elements;
      const j5 = Math.acos(THREE.MathUtils.clamp(m[0], -1, 1));
      let j4 = 0, j6 = Math.atan2(m[6], m[5]); if (Math.sin(j5) > 1e-5) { j4 = Math.atan2(m[2], m[1]); j6 = Math.atan2(m[8], -m[4]); }
      for (const [w4, w5, w6] of [[j4, j5, j6], [j4 + Math.PI, -j5, j6 + Math.PI]]) {
        const c = { j1, j2, j3, j4: w4, j5: w5, j6: w6 }; for (const name in limits) c[name] = wrapJ(name, c[name]); out.push(c);
      }
    }
    return out;
  }
  function error() {
    const position = getTcpWorld(goal.tcp).distanceTo(goal.target);
    const angle = tool.getWorldQuaternion(new THREE.Quaternion()).angleTo(goal.quaternion) / D2R;
    return { position, angle };
  }
  const jointDist = (a, b) => JOINTS.reduce((sum, n) => sum + Math.abs(a[n] - b[n]), 0);
  const within = c => JOINTS.every(n => c[n] >= limits[n][0] * D2R - 1e-9 && c[n] <= limits[n][1] * D2R + 1e-9);
  /** 逆解：在收斂的解中取離參考最近者（J4／J6 另試 ±360° 與手腕翻轉等價角）；J1 固定在角度窗內 */
  function solveIK(ref = null) {
    let best = null, score = Infinity, near = null, nearD = Infinity;
    for (const c of ref ? [ref, ...seeds()] : seeds()) {
      Object.assign(q, home, c); apply(); ik.solve(tcps[goal.tcp], goal.target, goal.quaternion, 100);
      q.j1 = inWindow(q.j1); apply();
      // 肘部朝下（j3 ≥ 90°）時肘部會低於肩部、貼近桌面，不採用
      const e = error(), v = e.position + e.angle * 10 + (q.j3 >= Math.PI / 2 ? 1000 : 0); if (v < score) { score = v; best = { ...q }; }
      if (v < 0.05) { if (!ref) break; const d = jointDist(q, ref); if (d < nearD) { nearD = d; near = { ...q }; } }
    }
    Object.assign(q, near || best);
    if (ref) {
      let pick = { ...q }, pickD = jointDist(q, ref);
      for (const [d4, s5, d6] of [[0, 1, 0], [Math.PI, -1, Math.PI], [Math.PI, -1, -Math.PI], [-Math.PI, -1, Math.PI], [-Math.PI, -1, -Math.PI]])
        for (const k4 of [0, 2 * Math.PI, -2 * Math.PI]) for (const k6 of [0, 2 * Math.PI, -2 * Math.PI]) {
          const c = { ...q, j4: q.j4 + d4 + k4, j5: s5 * q.j5, j6: q.j6 + d6 + k6 };
          if (within(c)) { const d = jointDist(c, ref); if (d < pickD - 1e-9) { pickD = d; pick = c; } }
        }
      Object.assign(q, pick);
    }
    apply();
  }
  // 位姿→關節角（快取於位姿物件），倒退／跳站時結果一致
  const jointCache = new WeakMap();
  function setGoal(pose) { goal.joints = null; goal.tcp = pose.tcp; goal.quaternion.copy(pose.rotation); goal.target.copy(pose.origin).add(tcps[pose.tcp].position.clone().applyQuaternion(pose.rotation)); }
  function solveJoints(pose, ref = null) {
    let c = jointCache.get(pose); if (c) return c;
    const saved = { ...q }, savedGoal = { target: goal.target.clone(), quaternion: goal.quaternion.clone(), tcp: goal.tcp, joints: goal.joints };
    setGoal(pose); solveIK(ref); const e = error(); c = { ...q, position: e.position, angle: e.angle };
    Object.assign(q, saved); Object.assign(goal, savedGoal); apply();
    jointCache.set(pose, c); return c;
  }
  function reach(pose) { const c = solveJoints(pose); return { position: c.position, angle: c.angle }; }
  /** 兩位姿間 PTP（五次曲線、峰速為平均的 1.875 倍）所需的最短時間 */
  function ptpTime(a, b) { const ja = solveJoints(a), jb = solveJoints(b); return 1.875 * Math.max(...JOINTS.map(n => Math.abs(jb[n] - ja[n]) / JOINT_SPEED[n])); }
  /** 工具朝下（+Z＝世界 −Y），yaw 指定工具 +Y 在水平面上的方向；夾爪沿工具 X 開合 */
  function poseFor(tcp, target, yaw) {
    const z = new THREE.Vector3(0, -1, 0), y = yaw.clone().setY(0).normalize(), x = new THREE.Vector3().crossVectors(y, z);
    const rotation = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z));
    return { origin: target.clone().sub(tcps[tcp].position.clone().applyQuaternion(rotation)), rotation, tcp, target: target.clone() };
  }
  const _t = new THREE.Vector3(), _q = new THREE.Quaternion();
  /**
   * 套用位姿：
   * - { ptp: { from, to, e } }：關節空間同步插值
   * - { lin: { from, to, e } }：TCP 直線＋姿態 slerp，以兩端關節角插值為初值求逆解（結果只與 e 有關）
   * - 一般位姿：直接取快取的關節解
   */
  function setPose(pose) {
    let joints;
    if (pose.ptp || pose.lin) {
      const m = pose.ptp || pose.lin, a = solveJoints(m.from), b = solveJoints(m.to), e = m.e;
      joints = {}; for (const name of JOINTS) joints[name] = THREE.MathUtils.lerp(a[name], b[name], e);
      const saved = { ...q }; Object.assign(q, joints); apply();
      if (pose.lin) {
        _t.lerpVectors(m.from.target, m.to.target, e); _q.slerpQuaternions(m.from.rotation, m.to.rotation, e);
        ik.solve(tcps[m.to.tcp], _t, _q, 30); joints = { ...q };
        goal.target.copy(_t); goal.quaternion.copy(_q);
      } else { getTcpWorld(m.to.tcp, goal.target); tool.getWorldQuaternion(goal.quaternion); }
      goal.tcp = m.to.tcp; Object.assign(q, saved); apply();
    } else { setGoal(pose); joints = { ...solveJoints(pose) }; delete joints.position; delete joints.angle; }
    goal.joints = joints;
  }
  function snap() { if (goal.joints) { Object.assign(q, goal.joints); apply(); } return getTcpWorld(goal.tcp); }

  return { root, q, home, goal, apply, getTcpWorld, snap, error, poseFor, setPose, setGoal, solveJoints, reach, ptpTime, setGripper,
    get width() { return width; }, tool, tcps, limits, L, JOINT_SPEED, fingers };
}
