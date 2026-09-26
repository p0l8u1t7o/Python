// DENSO VS-068 六軸手臂＋共用末端工具（快拆壓頭介面＋20MP 斜視相機）
// 工具本地座標：+Z 為工具前進方向（朝下壓）、X 沿壓墊長邊、Y 橫向（相機所在側為 +Y）。單位 mm。
import * as THREE from 'three';
import { createIK } from './kinematics.js';
import { block, cylinder, decal, bevelBox, screw, tube } from './detail.js';

const matArm   = new THREE.MeshStandardMaterial({ color: 0xeceeef, roughness: 0.42, metalness: 0.12 });
const matArmD  = new THREE.MeshStandardMaterial({ color: 0x30353b, roughness: 0.5, metalness: 0.3 });
const matJoint = new THREE.MeshStandardMaterial({ color: 0x1c1f23, roughness: 0.4, metalness: 0.5 });
const matTool  = new THREE.MeshStandardMaterial({ color: 0x9aa3ad, roughness: 0.35, metalness: 0.75 });
const matAnod  = new THREE.MeshStandardMaterial({ color: 0x3b4149, roughness: 0.4, metalness: 0.6 });
const matPU    = new THREE.MeshStandardMaterial({ color: 0xd9a441, roughness: 0.9 });
const matGlass = new THREE.MeshPhysicalMaterial({ color: 0x8fb8ff, roughness: 0.05, transmission: 0.6, transparent: true, opacity: 0.8 });
const D2R = Math.PI / 180;

function cyl(r1, r2, h, mat, seg = 32) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, seg), mat); m.castShadow = m.receiveShadow = true; return m; }
function box(w, h, d, mat) { return bevelBox(w,h,d,mat,Math.min(6,w*.08)); }

// 工具幾何（供序列與驗證共用）
export const TOOL = {
  padTip: 95, padStroke: 3,                           // 壓頭（8 頭或單點）底面在工具軸心、法蘭下 95 mm；彈簧行程 3 mm
  barPitch: 21, barPads: 8,                           // 標準 8 頭整排壓墊（每頭獨立彈簧）
  camTilt: 45, camY: 150, camZ: 10, camReach: 63.5, camWD: 175, // 20MP＋25 mm 鏡頭：機身前緣到鏡頭前緣 63.5、工作距離 175
};

export function createRobot() {
  const root = new THREE.Group(); root.name = 'robot';
  // ---- 連桿（DENSO VS-068 型錄：臂長 340＋340、動作半徑 710）----
  // 基座到 J2 高度 345、J5 到法蘭 80 為參考值，型錄未列，需以 DENSO CAD 核對。
  const L = { base: 200, shoulderY: 145, shoulderX: 0, upper: 340, fore: 340, foreOffset: 0, wrist1: 120, wrist2: 70, flange: 10 };
  const j = {};
  const base = cyl(88, 100, L.base, matArm); base.position.y = L.base / 2; root.add(base);
  const baseRing = cyl(92, 92, 10, matJoint); baseRing.position.y = L.base - 5; root.add(baseRing);
  decal(root, 90, 22, [0, 70, 101], [0, 0, 0], 'DENSO', { color: '#c8102e', center: true, bold: true });

  j.j1 = new THREE.Group(); j.j1.position.y = L.base; root.add(j.j1);                               // J1 繞 Y
  const shoulder = box(150, 150, 170, matArm); shoulder.position.y = 70; j.j1.add(shoulder);
  j.j2 = new THREE.Group(); j.j2.position.set(L.shoulderX, L.shoulderY, 0); j.j1.add(j.j2);          // J2 繞 Z
  const j2disc = cyl(72, 72, 190, matJoint); j2disc.rotation.x = Math.PI / 2; j.j2.add(j2disc);
  const upper = box(100, L.upper, 110, matArm); upper.position.y = L.upper / 2; j.j2.add(upper);
  const upperCap = cyl(58, 58, 112, matArm); upperCap.rotation.x = Math.PI / 2; upperCap.position.y = L.upper; j.j2.add(upperCap);
  for(let k=0;k<6;k++) {
    const a=k*Math.PI/3; screw(j.j2,[Math.cos(a)*58,Math.sin(a)*58,96],4,'z');
  }
  decal(j.j2, 60, 150, [0, 170, 56], [0, 0, 0], ['VS-068', 'DENSO'], { color: '#4a525b', center: true });

  j.j3 = new THREE.Group(); j.j3.position.set(0, L.upper, 0); j.j2.add(j.j3);                       // J3 繞 Z
  const j3disc = cyl(55, 55, 150, matJoint); j3disc.rotation.x = Math.PI / 2; j.j3.add(j3disc);
  for(let k=0;k<6;k++) { const a=k*Math.PI/3; screw(j.j3,[Math.cos(a)*43,Math.sin(a)*43,76],3.5,'z'); }
  const fore = box(L.fore - L.wrist1 + 30, 80, 90, matArm); fore.position.set((L.fore - L.wrist1 - 30) / 2, L.foreOffset, 0); j.j3.add(fore);
  j.j4 = new THREE.Group(); j.j4.position.set(L.fore - L.wrist1, L.foreOffset, 0); j.j3.add(j.j4);   // J4 繞 X
  const w1 = cyl(42, 42, L.wrist1, matArm); w1.rotation.z = Math.PI / 2; w1.position.x = L.wrist1 / 2; j.j4.add(w1);
  j.j5 = new THREE.Group(); j.j5.position.set(L.wrist1, 0, 0); j.j4.add(j.j5);                      // J5 繞 Z
  const w2 = cyl(38, 38, 96, matJoint); w2.rotation.x = Math.PI / 2; j.j5.add(w2);
  const w2b = box(L.wrist2, 62, 62, matArm); w2b.position.x = L.wrist2 / 2; j.j5.add(w2b);
  j.j6 = new THREE.Group(); j.j6.position.set(L.wrist2, 0, 0); j.j5.add(j.j6);                      // J6 繞 X
  const flange = cyl(32, 32, L.flange, matJoint); flange.rotation.z = Math.PI / 2; flange.position.x = L.flange / 2; j.j6.add(flange);

  // ---- 末端工具（所有機種共用）----
  const tool = new THREE.Group(); tool.position.x = L.flange; tool.rotation.y = Math.PI / 2; j.j6.add(tool);
  const ft = cyl(41, 41, 25, matAnod); ft.rotation.x = Math.PI / 2; ft.position.z = 12.5; tool.add(ft);   // ATI Axia80
  const ftRing = new THREE.Mesh(new THREE.TorusGeometry(41, 1.8, 8, 40), new THREE.MeshStandardMaterial({ color: 0x3dd68c, emissive: 0x3dd68c, emissiveIntensity: 1.2 }));
  ftRing.position.z = 12.5; tool.add(ftRing);
  block(tool, [90, 90, 8], [0, 0, 29], matTool);                                        // 工具本體板
  block(tool, [52, 52, 10], [0, 0, 38], matAnod);                                       // 快拆介面（定位銷＋識別碼）
  for(const x of [-35,35]) for(const y of [-35,35]) screw(tool,[x,y,33.3],3.2,'z');
  decal(tool,29,10,[0,-30,33.1],[0,0,0],'AXIA / F-T',{color:'#222d36',center:true});
  for (const s of [-1, 1]) cylinder(tool, 2, 4, [s * 18, 18, 44], matTool, 'z', 8);
  // 單點彈簧壓頭（快拆，只有單顆接頭的機種用）：PU 壓墊 8×4 mm，在工具軸心
  const single = new THREE.Group(); tool.add(single);
  block(single, [22, 22, 26], [0, 0, 56], matTool);
  cylinder(single, 3, 14, [0, 0, 75], matAnod, 'z', 12);
  const singlePad = new THREE.Group(); single.add(singlePad);
  cylinder(singlePad, 2, 10, [0, 0, 84], matTool, 'z', 10);
  block(singlePad, [8, 4, 6], [0, 0, TOOL.padTip - 3], matPU);
  const spring = new THREE.Group(); spring.name='single-spring';spring.position.z=69.5; single.add(spring);
  const coil=[]; for(let i=0;i<=144;i++) { const a=i/144*Math.PI*12; coil.push([3.8*Math.cos(a),3.8*Math.sin(a),i/144*16.5]); }
  tube(spring,coil,.38,matTool,144);
  // 標準 8 頭整排壓墊：同一快拆介面，片距 21 mm；每頭獨立彈簧，各自吃掉接頭翹起的高低差
  const bar = new THREE.Group(); tool.add(bar);
  block(bar, [184, 22, 30], [0, 0, 58], matTool);
  const barPads = [],barSprings=[];
  for (let i = 0; i < TOOL.barPads; i++) {
    const x = (i - (TOOL.barPads - 1) / 2) * TOOL.barPitch;
    cylinder(bar, 2.6, 10, [x, 0, 78], matAnod, 'z', 10);
    const pad = new THREE.Group(); pad.position.x = x; bar.add(pad);
    cylinder(pad, 1.6, 8, [0, 0, 84], matTool, 'z', 8);
    block(pad, [7, 9, 6], [0, 0, TOOL.padTip - 3], matPU);
    // Upper seat stays on the bar; only the lower seat follows pad compression.
    const spring=new THREE.Group();spring.name=`bar-spring-${i}`;spring.position.set(x,0,73.5);bar.add(spring);barSprings.push(spring);
    const coil = []; for (let k = 0; k <= 96; k++) { const a = k / 96 * Math.PI * 8; coil.push([3.3 * Math.cos(a), 3.3 * Math.sin(a), k / 96 * 9.5]); }
    tube(spring, coil, .3, matTool, 96);
    barPads.push(pad);
  }
  // 20MP 斜視相機（45°、光軸朝下並朝 −Y）＋100 mm 條形光
  block(tool, [30, TOOL.camY - 40, 8], [0, (TOOL.camY + 40) / 2 - 5, 30], matTool);
  const camAxis = new THREE.Vector3(0, -Math.sin(TOOL.camTilt * D2R), Math.cos(TOOL.camTilt * D2R));
  const camCenter = new THREE.Vector3(0, TOOL.camY, TOOL.camZ);
  const camMount = new THREE.Group(); camMount.position.copy(camCenter);
  camMount.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), camAxis); tool.add(camMount);
  camMount.add(box(44, 34, 47, matArmD));
  const lens = cyl(16, 16, 40, matJoint); lens.rotation.x = Math.PI / 2; lens.position.z = 23.5 + 20; camMount.add(lens);
  const lensGlass = cyl(12, 12, 1, matGlass); lensGlass.rotation.x = Math.PI / 2; lensGlass.position.z = TOOL.camReach + 0.1; camMount.add(lensGlass);
  for(const z of [28,34,49,56,62]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(16,.7,6,40),matTool); ring.position.z=z; camMount.add(ring);
  }
  for(const x of [-18,18]) for(const y of [-12,12]) screw(camMount,[x,y,23.5],1.5,'z');
  decal(camMount,25,12,[0,17.05,-3],[-Math.PI/2,0,0],['VISION','20 MP'],{color:'#c5d0d8',center:true});
  tube(tool,[[20,38,13],[32,65,8],[30,105,-14],[15,135,-14]],2.1,matJoint);
  const lightMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.05 });
  const barLight = box(100, 10, 16, lightMat); barLight.position.set(0, 30, 52); camMount.add(barLight);
  const flash = new THREE.SpotLight(0xffffff, 0, 500, 0.5, 0.5, 1); flash.position.set(0, 0, 60); flash.target.position.set(0, 0, 260); camMount.add(flash, flash.target);
  // 手臂相機視角（子畫面用）：IMX183 1"（13.2 × 8.8 mm）、25 mm 鏡頭
  const pipCam = new THREE.PerspectiveCamera(2 * Math.atan(8.8 / 2 / 25) / D2R, 1.5, 5, 3000);
  pipCam.position.set(0, 0, TOOL.camReach);
  pipCam.quaternion.setFromRotationMatrix(new THREE.Matrix4().lookAt(new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 1, 0)));
  camMount.add(pipCam);

  // TCP：壓頭底面（單點或 8 頭中心）、相機對焦點
  const tcpPress = new THREE.Object3D(); tcpPress.position.set(0, 0, TOOL.padTip); tool.add(tcpPress);
  const tcpCam = new THREE.Object3D(); tcpCam.position.copy(camCenter).addScaledVector(camAxis, TOOL.camReach + TOOL.camWD); tool.add(tcpCam);
  const tcps = { press: tcpPress, cam: tcpCam };

  // ---- 關節狀態 ----
  const q = { j1: -90 * D2R, j2: -10 * D2R, j3: 40 * D2R, j4: 0, j5: -70 * D2R, j6: 0 };
  // VS-068 型錄範圍：J1 ±170、J2 +135/−100、J3 +153/−120、J4 ±270、J5 ±120、J6 ±360。
  // 換算到本模型座標（假設 DENSO J2 零點為上臂垂直、J3=90° 為前臂水平；正向相反）：j2 = −J2、j3 = 90° − J3。
  const limits = { j1: [-170, 170], j2: [-135, 100], j3: [-63, 210], j4: [-270, 270], j5: [-120, 120], j6: [-360, 360] };
  const home = { ...q };
  const JOINTS = ['j1', 'j2', 'j3', 'j4', 'j5', 'j6'];
  // 關節速度上限（rad/s）：取 VS-068 型錄最高速度（J1 356、J2 303、J3 379、J4 475、J5 475、J6 760 °/s）的 50%
  const JOINT_SPEED = { j1: 3.1, j2: 2.6, j3: 3.3, j4: 4.1, j5: 4.1, j6: 6.6 };

  function apply() {
    j.j1.rotation.set(0, q.j1, 0); j.j2.rotation.set(0, 0, q.j2); j.j3.rotation.set(0, 0, q.j3);
    j.j4.rotation.set(q.j4, 0, 0); j.j5.rotation.set(0, 0, q.j5); j.j6.rotation.set(q.j6, 0, 0);
    root.updateMatrixWorld(true);
  }
  apply();
  const ik = createIK({ q, j, tool, apply, limits });

  // ---- 目標與追蹤 ----
  const cur = { target: new THREE.Vector3(), tcp: 'press' };
  const goal = { target: new THREE.Vector3(), quaternion: new THREE.Quaternion(), tcp: 'press', speed: 500, joints: null };
  const curRotation = new THREE.Quaternion(); tool.getWorldQuaternion(curRotation);
  const tcpWorld = new THREE.Vector3(), _p = new THREE.Vector3();
  function getTcpWorld(name, out = new THREE.Vector3()) { return tcps[name].getWorldPosition(out); }
  function syncCur() { cur.tcp = goal.tcp; getTcpWorld(cur.tcp, cur.target); tool.getWorldQuaternion(curRotation); }

  function update(dt) {
    if (dt <= 0) return getTcpWorld(cur.tcp, tcpWorld);
    if (goal.joints) {
      // 同步 PTP：各軸依同一比例前進、同時到位。
      let f = 1; for (const name of JOINTS) { const d = Math.abs(goal.joints[name] - q[name]); if (d > 1e-9) f = Math.min(f, JOINT_SPEED[name] * dt / d); }
      for (const name of JOINTS) q[name] += (goal.joints[name] - q[name]) * f;
      apply(); syncCur(); return getTcpWorld(goal.tcp, tcpWorld);
    }
    if (cur.tcp !== goal.tcp) { getTcpWorld(goal.tcp, cur.target); cur.tcp = goal.tcp; }
    const d = _p.copy(goal.target).sub(cur.target), dist = d.length(), step = goal.speed * dt;
    if (dist > step) cur.target.addScaledVector(d.normalize(), step); else cur.target.copy(goal.target);
    curRotation.rotateTowards(goal.quaternion, dt * 3);
    const previous = { ...q }; ik.solve(tcps[cur.tcp], cur.target, curRotation, 14);
    for (const name of JOINTS) q[name] = previous[name] + THREE.MathUtils.clamp(q[name] - previous[name], -JOINT_SPEED[name] * dt, JOINT_SPEED[name] * dt);
    apply(); return getTcpWorld(cur.tcp, tcpWorld);
  }

  // 幾何初始解：肘部上下 × 手腕翻轉共四組，角度折回限位內；逐組求解取誤差最小者。
  function wrapJ(name, v) { const [lo, hi] = limits[name].map(x => x * D2R); for (const k of [0, 2 * Math.PI, -2 * Math.PI]) if (v + k >= lo && v + k <= hi) return v + k; return THREE.MathUtils.clamp(v, lo, hi); }
  function seeds() {
    const dir = new THREE.Vector3(0, 0, 1).applyQuaternion(goal.quaternion);
    const origin = goal.target.clone().sub(tcps[goal.tcp].position.clone().applyQuaternion(goal.quaternion));
    const wrist = origin.addScaledVector(dir, -L.wrist2 - L.flange).sub(new THREE.Vector3(root.position.x, root.position.y + L.base + L.shoulderY, root.position.z));
    const radial = Math.hypot(wrist.x, wrist.z) - L.shoulderX, a = L.upper, b = Math.hypot(L.fore, L.foreOffset), phi = Math.atan2(L.foreOffset, L.fore);
    const j1 = Math.atan2(-wrist.z, wrist.x), elbow = Math.acos(THREE.MathUtils.clamp((radial * radial + wrist.y * wrist.y - a * a - b * b) / (2 * a * b), -1, 1)), out = [];
    for (const beta of [-elbow, elbow]) {
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
  /** 逆解：有參考關節角時，在收斂的解中取離參考最近者（J4／J6 另試 ±360° 等價角），避免相鄰點換肘部或手腕組合 */
  function solveIK(ref = null) {
    cur.target.copy(goal.target); curRotation.copy(goal.quaternion); cur.tcp = goal.tcp;
    let best = null, score = Infinity, near = null, nearD = Infinity;
    for (const c of ref ? [ref, ...seeds()] : seeds()) {
      Object.assign(q, home, c); apply(); ik.solve(tcps[goal.tcp], goal.target, goal.quaternion, 100);
      const e = error(), v = e.position + e.angle * 10; if (v < score) { score = v; best = { ...q }; }
      if (v < 0.05) { if (!ref) break; const d = jointDist(q, ref); if (d < nearD) { nearD = d; near = { ...q }; } }
    }
    Object.assign(q, near || best);
    if (ref) {
      // 球形手腕的等價解：(J4+π, −J5, J6+π) 與 J4／J6 ±360° 姿態完全相同，取離參考最近且在限位內者
      const within = c => JOINTS.every(n => c[n] >= limits[n][0] * D2R - 1e-9 && c[n] <= limits[n][1] * D2R + 1e-9);
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
  function snap() {
    if (goal.joints) { Object.assign(q, goal.joints); apply(); syncCur(); return getTcpWorld(goal.tcp); }
    solveIK(goal.refPose ? jointCache.get(goal.refPose) || null : null); return getTcpWorld(goal.tcp);
  }
  // 位姿→關節角（快取於位姿物件），倒退／跳站時結果一致
  const jointCache = new WeakMap();
  function solveJoints(pose, ref = null) {
    let c = jointCache.get(pose); if (c) return c;
    const saved = { ...q }, savedGoal = { target: goal.target.clone(), quaternion: goal.quaternion.clone(), tcp: goal.tcp, joints: goal.joints };
    const curSaved = { target: cur.target.clone(), rotation: curRotation.clone(), tcp: cur.tcp };
    setGoal(pose); solveIK(ref); const e = error(); c = { ...q, position: e.position, angle: e.angle };
    Object.assign(q, saved); Object.assign(goal, savedGoal); cur.target.copy(curSaved.target); curRotation.copy(curSaved.rotation); cur.tcp = curSaved.tcp; apply();
    jointCache.set(pose, c); return c;
  }
  function reach(pose) { const c = solveJoints(pose); return { position: c.position, angle: c.angle }; }
  /** 依流程順序規劃關節解：每個位姿以前一個位姿的解為參考 */
  function plan(poses) { let ref = null; for (const p of poses) ref = solveJoints(p, ref); }
  /** 兩位姿間 PTP（五次曲線、峰速為平均的 1.875 倍）所需的最短時間 */
  function ptpTime(a, b) { const ja = solveJoints(a), jb = solveJoints(b); return 1.875 * Math.max(...JOINTS.map(n => Math.abs(jb[n] - ja[n]) / JOINT_SPEED[n])); }
  /** 工具朝下（+Z＝世界 −Y），yaw 指定工具 +Y 在水平面上的方向 */
  function poseFor(tcp, target, yaw) {
    const z = new THREE.Vector3(0, -1, 0), y = yaw.clone().setY(0).normalize(), x = new THREE.Vector3().crossVectors(y, z);
    const rotation = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z));
    return { origin: target.clone().sub(tcps[tcp].position.clone().applyQuaternion(rotation)), rotation, tcp };
  }
  function setGoal(pose) { goal.joints = null; goal.refPose = pose.ref || null; goal.tcp = pose.tcp; goal.quaternion.copy(pose.rotation); goal.target.copy(pose.origin).add(tcps[pose.tcp].position.clone().applyQuaternion(pose.rotation)); }
  function setPose(pose) {
    if (!pose.ptp) return setGoal(pose);
    const a = solveJoints(pose.ptp.from), b = solveJoints(pose.ptp.to), e = pose.ptp.e, joints = {};
    for (const name of JOINTS) joints[name] = THREE.MathUtils.lerp(a[name], b[name], e);
    const saved = { ...q }; Object.assign(q, joints); apply();
    goal.tcp = pose.ptp.to.tcp; getTcpWorld(goal.tcp, goal.target); tool.getWorldQuaternion(goal.quaternion); goal.joints = joints;
    Object.assign(q, saved); apply();
  }

  function setForceColor(f) { const c = f < 2 ? 0x3dd68c : f < 45 ? 0xffb020 : 0xff4d4d; ftRing.material.color.setHex(c); ftRing.material.emissive.setHex(c); }
  function setFlash(on) { flash.intensity = on ? 300 : 0; lightMat.emissiveIntensity = on ? 1.1 : 0.05; }
  /** 快拆壓墊：'bar'（標準 8 頭整排）或 'single'（單顆機種的單點壓頭） */
  function setInsert(kind) { single.visible = kind !== 'bar'; bar.visible = kind === 'bar'; }
  /** 壓頭彈簧壓縮量（mm）；8 頭時可逐顆給值 */
  function setPadCompression(list) {
    const c = i => -Math.min(TOOL.padStroke, Math.max(0, Array.isArray(list) ? list[i] || 0 : list));
    singlePad.position.z = c(0); barPads.forEach((p, i) => { p.position.z = c(i); });
    spring.scale.z = (16.5+c(0))/16.5;
    barSprings.forEach((s,i)=>{s.scale.z=(9.5+c(i))/9.5;});
  }
  setInsert('single');
  // 壓頭是預期接觸產品的部位，驗證時接觸步驟允許它們進入產品包絡
  for (const part of [singlePad, ...barPads]) part.traverse(o => { o.userData.contact = true; });

  return { root, q, home, goal, cur, update, apply, getTcpWorld, snap, error, poseFor, setPose, reach, plan, ptpTime, tool, tcps, pipCam,
    setForceColor, setFlash, setPadCompression, setInsert, get insert() { return bar.visible ? 'bar' : 'single'; }, limits, L };
}
