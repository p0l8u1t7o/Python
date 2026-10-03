// DENSO VS-068 六軸手臂（共用模型 @core/models/robots/denso-vs068.js）＋本站共用末端工具（快拆壓頭介面＋20MP 斜視相機）
// 工具本地座標：+Z 為工具前進方向（朝下壓）、X 沿壓墊長邊、Y 橫向（相機所在側為 +Y）。單位 mm。
// 本檔只放本站的末端工具、TCP 與關節規劃（逆解選解、PTP、位姿快取）；手臂本體、限位、速度與 IK 在共用模型。
import * as THREE from 'three';
import { createVS068, VS068_MAT, JOINTS, JOINT_SPEED } from '@core/models/robots/denso-vs068.js';
import { cable, CABLE } from '@core/electrical/cable-routing.js';
import { bevelBox, block, cylinder, decal, screw, tube } from '@core/geom/shapes.js';
import { MAT } from '@core/geom/materials.js';

const matArmD  = VS068_MAT.dark;
const matJoint = VS068_MAT.joint;
// 常用材質取共用表（core/geom/materials.js）；力值環與相機光源會在執行時改顏色／亮度，各自建立
const matTool  = MAT.steel;       // 工具本體、彈簧
const matAnod  = MAT.steelDark;   // 陽極處理件（力感測器、快拆介面）
const matPU    = MAT.pu;          // PU 壓墊
const matGlass = MAT.glass;       // 鏡頭玻璃
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
  // ---- 手臂本體（共用模型）：起始姿態 J1 −90°（朝向工作台）----
  const arm = createVS068({ q: { j1: -90, j2: -10, j3: 40, j4: 0, j5: -70, j6: 0 } });
  const { root, L, q, limits, apply, ik } = arm;
  // Keep the arm and camera geometry separate for self-clearance regression checks.
  const armParts = arm.parts;

  // ---- 末端工具（所有機種共用），裝在手臂的工具安裝座（法蘭面，+Z 朝下壓）----
  const tool = arm.tool;
  const ft =cyl(41, 41, 25, matAnod); ft.rotation.x = Math.PI / 2; ft.position.z = 12.5; tool.add(ft);   // ATI Axia80
  const ftRing = new THREE.Mesh(new THREE.TorusGeometry(41, 1.8, 8, 40), new THREE.MeshStandardMaterial({ color: 0x3dd68c, emissive: 0x3dd68c, emissiveIntensity: 1.2 }));
  ftRing.position.z = 12.5; tool.add(ftRing);
  block(tool, [90, 90, 8], [0, 0, 29], matTool);                                        // 工具本體板
  block(tool, [52, 52, 10], [0, 0, 38], matAnod);                                       // 快拆介面（定位銷＋識別碼）
  for(const x of [-35,35]) for(const y of [-35,35]) screw(tool,[x,y,33.3],3.2,'z');
  decal(tool,29,10,[0,-30,33.7],[0,0,0],'AXIA / F-T',{color:'#222d36',center:true});   // 離板面 0.7 mm，避免閃爍
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
  const cameraBracket = block(tool, [30, TOOL.camY - 40, 8], [0, (TOOL.camY + 40) / 2 - 5, 30], matTool);
  cameraBracket.name = 'camera-bracket';
  const camAxis = new THREE.Vector3(0, -Math.sin(TOOL.camTilt * D2R), Math.cos(TOOL.camTilt * D2R));
  const camCenter = new THREE.Vector3(0, TOOL.camY, TOOL.camZ);
  const camMount = new THREE.Group(); camMount.position.copy(camCenter);
  camMount.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), camAxis); tool.add(camMount);
  camMount.name = 'wrist-camera';
  const cameraBody = box(44, 34, 47, matArmD); cameraBody.name = 'camera-body'; camMount.add(cameraBody);
  const lens = cyl(16, 16, 40, matJoint); lens.rotation.x = Math.PI / 2; lens.position.z = 23.5 + 20; camMount.add(lens);
  const lensGlass = cyl(12, 12, 1, matGlass); lensGlass.rotation.x = Math.PI / 2; lensGlass.position.z = TOOL.camReach + 0.4; camMount.add(lensGlass);   // 前面離鏡筒端面 0.9 mm
  for(const z of [28,34,49,56,62]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(16,.7,6,40),matTool); ring.position.z=z; camMount.add(ring);
  }
  for(const x of [-18,18]) for(const y of [-12,12]) screw(camMount,[x,y,23.5],1.5,'z');
  decal(camMount,25,12,[0,17.7,-3],[-Math.PI/2,0,0],['VISION','20 MP'],{color:'#c5d0d8',center:true});
  // Route along the outside of the mounting plate, on the tool side of the
  // flange; the previous rearward loop entered the rotating wrist envelope.
  const cameraCable = tube(tool,[[35,42,20],[38,78,20],[36,118,24],[22,150,10]],2.1,matJoint);
  cameraCable.name = 'camera-cable';
  const lightMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.05 });
  const barLight = box(100, 10, 16, lightMat); barLight.position.set(0, 30, 52); camMount.add(barLight);
  const flash = new THREE.SpotLight(0xffffff, 0, 500, 0.5, 0.5, 1); flash.position.set(0, 0, 60); flash.target.position.set(0, 0, 260); camMount.add(flash, flash.target);
  // 手臂相機視角（子畫面用）：IMX183 1"（13.2 × 8.8 mm）、25 mm 鏡頭
  const pipCam = new THREE.PerspectiveCamera(2 * Math.atan(8.8 / 2 / 25) / D2R, 1.5, 5, 3000);
  pipCam.position.set(0, 0, TOOL.camReach);
  pipCam.quaternion.setFromRotationMatrix(new THREE.Matrix4().lookAt(new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 1, 0)));
  camMount.add(pipCam);
  const cameraParts = [cameraBracket, cameraCable];
  camMount.traverse(o => { if (o.isMesh) cameraParts.push(o); });

  // TCP：壓頭底面（單點或 8 頭中心）、相機對焦點
  const tcpPress = new THREE.Object3D(); tcpPress.position.set(0, 0, TOOL.padTip); tool.add(tcpPress);
  const tcpCam = new THREE.Object3D(); tcpCam.position.copy(camCenter).addScaledVector(camAxis, TOOL.camReach + TOOL.camWD); tool.add(tcpCam);
  const tcps = { press: tcpPress, cam: tcpCam };

  // 手臂外部線材保護段與基座電源線由共用模型建立（dress）；以下是工具上的線材
  cable(tool,'FT / flange junction',[[43,0,12],[55,0,12],[55,42,20],[35,42,20]],{radius:2,color:CABLE.signal,clips:1});
  cable(camMount,'LIGHT / rear-routed lead',[[22,0,-12],[30,12,-10],[35,30,20],[35,30,44]],{radius:1.6,color:CABLE.power,clips:1});

  // ---- 關節狀態（q、limits、JOINT_SPEED、IK 來自共用模型）----
  const home = { ...q };
  apply();

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

  // 幾何初始解（共用模型）：肘部上下 × 手腕翻轉共四組，角度折回限位內；逐組求解取誤差最小者。
  function seeds() {
    const origin = goal.target.clone().sub(tcps[goal.tcp].position.clone().applyQuaternion(goal.quaternion));
    return arm.seeds(origin, goal.quaternion);
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
    setForceColor, setFlash, setPadCompression, setInsert, get insert() { return bar.visible ? 'bar' : 'single'; }, limits, L, arm,
    clearanceParts: { arm: armParts, camera: cameraParts } };
}
