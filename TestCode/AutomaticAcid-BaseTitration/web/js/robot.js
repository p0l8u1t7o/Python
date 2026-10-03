// DENSO COBOTTA PRO 900 協作型六軸手臂（core/models/robots/denso-cobotta-pro900.js）＋長行程電動平行夾爪
// 本檔只放本專案的工具、TCP、J1 角度窗與排程用的逆解／位姿；手臂本體、限位、速度與 IK 在 core。
// 工具本地座標：+Z 為工具前進方向（朝下）、X 為夾爪開合方向、Y 為手指厚度方向。單位 mm。
import * as THREE from 'three';
import { cable, CABLE } from '@core/electrical/cable-routing.js';
import { createCobottaPro900, MAT as ARM_MAT, JOINTS } from '@core/models/robots/denso-cobotta-pro900.js';
import { block, cylinder, decal } from '@core/geom/shapes.js';
import { MAT } from '@core/geom/materials.js';

const matTool  = ARM_MAT.tool;
const matAnod  = MAT.steelDark;                                              // 陽極處理鋁件（快換盤、導軌、滑座）
const matPad   = new THREE.MeshStandardMaterial({ color: 0x1b1d20, roughness: 0.95 });   // 橡膠指墊（霧面，留在本專案）
const D2R = Math.PI / 180;

// 夾爪幾何（排程與驗證共用）
export const TOOL = {
  body: [180, 70, 80], bodyZ: 10,       // 夾爪本體（開合方向 × 厚度 × 高度），法蘭下 10 mm 起
  finger: [12, 28, 110], fingerZ: 90,   // 手指（厚 × 寬 × 長），從工具 z 90 伸到 200
  tcp: 185,                             // 夾持中心：指墊中段（指尖在 TCP 下 15 mm）
  maxWidth: 160,                        // 最大開口（OnRobot RG6 級長行程）
};

export function createRobot() {
  // ---- 手臂（core）：初始姿態為本專案的待命姿態 ----
  const arm = createCobottaPro900({ q: { j1: -60 * D2R, j2: -20 * D2R, j3: 70 * D2R, j4: 0, j5: -50 * D2R, j6: 0 } });
  const { root, q, L, limits, apply, ik, JOINT_SPEED } = arm;

  // ---- 末端工具：長行程電動平行夾爪（燒杯 Ø65、樣品瓶 Ø56／Ø86、瓶蓋 GL45、移液模組夾持環共用）----
  const tool = arm.mount;
  cylinder(tool, 32, 10, [0, 0, 5], matAnod, 'z', 28);                                       // 快換轉接盤
  const [bw, bt, bh] = TOOL.body;
  block(tool, [bw, bt, bh], [0, 0, TOOL.bodyZ + bh / 2], matTool);
  block(tool, [bw - 20, bt + 4, 8], [0, 0, TOOL.bodyZ + bh - 5], matAnod);                    // 導軌（底面內縮 1 mm，不與本體底面重合）
  decal(tool, 90, 22, [0, -bt / 2 - 0.5, TOOL.bodyZ + 30], [Math.PI / 2, Math.PI, 0], 'GRIPPER', { color: '#20242a', center: true, bold: true });
  const fingers = [];
  for (const s of [-1, 1]) {
    const f = new THREE.Group(); tool.add(f);
    const [ft, fw, fl] = TOOL.finger;
    block(f, [ft, fw + 6, 16], [0, 0, TOOL.fingerZ + 8], matAnod);                            // 滑座
    block(f, [ft, fw, fl - 16], [0, 0, TOOL.fingerZ + 16 + (fl - 16) / 2], matTool);
    block(f, [3, fw - 4, 30], [-s * (ft / 2 + 1.5), 0, TOOL.tcp], matPad);                  // V 槽指墊（下緣與指尖齊平）
    f.userData.side = s; fingers.push(f);
  }

  // TCP：夾持中心
  const tcpGrip = new THREE.Object3D(); tcpGrip.position.set(0, 0, TOOL.tcp); tool.add(tcpGrip);
  const tcps = { grip: tcpGrip };
  let width = 100;
  /** 夾爪開口（兩指墊內側距離，mm） */
  function setGripper(w) {
    width = THREE.MathUtils.clamp(w, 0, TOOL.maxWidth);
    // 指墊厚 3 mm、貼在手指內側：width 為兩指墊內側面距離（全閉時兩指墊剛好相貼）
    for (const f of fingers) f.position.x = f.userData.side * (width / 2 + TOOL.finger[0] / 2 + 3);
  }
  setGripper(width);
  const toolParts = [];
  tool.traverse(m => { if (m.isMesh && m.geometry.type !== 'PlaneGeometry') toolParts.push(m); });

  // Tool feed uses the flange's assumed internal connection, above the finger stroke.
  cable(tool,'GRIP / power and control',[[35,0,5],[44,0,5],[60,45,5],[70,45,45],[70,38,45]],{radius:2.8,color:CABLE.signal,clips:2});

  // ---- 關節狀態 ----
  // J1 採固定角度窗：每個方向只有一種表示法，手臂在站別間移動時不會繞遠路或穿越設備。
  // 窗的斷點在正前方（−90°），該方向沒有放置任何站別。
  const J1_WINDOW = [-90 * D2R, 270 * D2R];
  const home = { ...q };
  apply();

  // ---- 目標 ----
  const goal = { target: new THREE.Vector3(), quaternion: new THREE.Quaternion(), tcp: 'grip', joints: null };
  function getTcpWorld(name = 'grip', out = new THREE.Vector3()) { return tcps[name].getWorldPosition(out); }

  // 幾何初始解：只用肘部朝上（j3 < 90°）× 手腕翻轉兩組，角度折回限位內，J1 在角度窗內
  function inWindow(v) { while (v < J1_WINDOW[0]) v += 2 * Math.PI; while (v >= J1_WINDOW[1]) v -= 2 * Math.PI; return v; }
  function seeds() {
    const origin = goal.target.clone().sub(tcps[goal.tcp].position.clone().applyQuaternion(goal.quaternion));
    return arm.seedJoints(origin, goal.quaternion, { wrapJ1: inWindow });
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
    get width() { return width; }, tool, tcps, limits, L, JOINT_SPEED, fingers, arm,
    clearanceParts: { arm: arm.armParts, tool: toolParts } };
}
