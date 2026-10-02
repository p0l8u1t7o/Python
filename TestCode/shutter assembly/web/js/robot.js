// DENSO HSR065 SCARA（J1、J2 水平旋轉、J3 花鍵軸 Z 行程、J4 花鍵軸旋轉）＋三工具頭與下視相機。
// 世界座標：x 向右、y 向上、z 朝作業員。工具本地：原點在花鍵軸法蘭，y 向上（工具在 −y），隨 J4 轉動。單位 mm。
import * as THREE from 'three';
import { cable, carrier, support, CABLE } from '@core/electrical/cable-routing.js';
import { block, cylinder, decal, bevelBox, screw, tube } from '@core/geom/primitives.js';
import { PART } from './product.js';

const D2R = Math.PI / 180;
const matArm = new THREE.MeshStandardMaterial({ color: 0xeef0f1, roughness: 0.4, metalness: 0.1 });
const matArmD = new THREE.MeshStandardMaterial({ color: 0x2f343a, roughness: 0.5, metalness: 0.3 });
const matJoint = new THREE.MeshStandardMaterial({ color: 0x1c1f23, roughness: 0.4, metalness: 0.5 });
const matShaft = new THREE.MeshStandardMaterial({ color: 0xd9dee3, roughness: 0.12, metalness: 0.95 });
const matTool = new THREE.MeshStandardMaterial({ color: 0x9aa3ad, roughness: 0.35, metalness: 0.75 });
const matAnod = new THREE.MeshStandardMaterial({ color: 0x3b4149, roughness: 0.4, metalness: 0.6 });
const matBlueAnod = new THREE.MeshStandardMaterial({ color: 0x2f5f9e, roughness: 0.45, metalness: 0.5 });
const matPad = new THREE.MeshStandardMaterial({ color: 0x3a3f33, roughness: 0.95 });         // 導電 PU／多孔陶瓷吸盤面
const matESD = new THREE.MeshStandardMaterial({ color: 0x2c2c2c, roughness: 0.85 });         // ESD PEEK 夾指
const matGlass = new THREE.MeshPhysicalMaterial({ color: 0x8fb8ff, roughness: 0.05, transmission: 0.6, transparent: true, opacity: 0.8 });

/** 機型參數：HSR065 型錄動作範圍 650 mm、Z 行程 200 mm；臂長分配、J1 座高與速度為假設值，需以 DENSO 型錄／CAD 核對 */
export const SCARA = {
  L1: 350, L2: 300, colH: 320, arm1H: 80, arm2H: 70,
  Y0: 1170,                                           // Z=0（最上）時法蘭的世界高度（手臂裝在 900 mm 台面上）
  limits: { j1: [-170, 170], j2: [-145, 145], d3: [0, 200], j4: [-360, 360] },
  speed: { j1: 3.3, j2: 6.1, d3: 850, j4: 21 },       // 假設型錄最高速度的 50%（rad/s、mm/s）
};
/** 工具頭：三支氣動滑台（行程 12 mm，只有使用中的那支伸出）＋固定的下視相機 */
export const TOOL = {
  stroke: 12, tip: -110,
  T1: { x: 0, z: 0, name: '葉片吸嘴' },               // 多孔吸盤 1.4 × 5 mm，吸葉片長邊中段
  T2: { x: 36, z: 0, name: '上蓋吸盤（含荷重元）' },   // 外框吸盤，壓合時量測力值
  T3: { x: -36, z: 0, name: '本體夾爪' },              // 平行夾爪夾本體前後側面，TCP＝本體頂面
  cam: { x: 0, z: -46, y: -115, name: '下視相機' },    // 5MP＋20 mm 鏡頭，工作距離 57 mm，視野約 24 × 20 mm
  gripZ: 8.5, fingerT: 1.5, fingerOpen: 1.2,
};
export const TCP_OFFSET = {
  T1: new THREE.Vector3(TOOL.T1.x, TOOL.tip, TOOL.T1.z),
  T2: new THREE.Vector3(TOOL.T2.x, TOOL.tip, TOOL.T2.z),
  T3: new THREE.Vector3(TOOL.T3.x, TOOL.tip + 3, TOOL.T3.z),
  cam: new THREE.Vector3(TOOL.cam.x, TOOL.cam.y, TOOL.cam.z),
};
const JOINTS = ['j1', 'j2', 'd3', 'j4'];
const wrapPi = a => Math.atan2(Math.sin(a), Math.cos(a));

export function createRobot() {
  const root = new THREE.Group(); root.name = 'robot';
  const { L1, L2, colH, arm1H, arm2H } = SCARA;
  // ---- 基座柱 ----
  // 柱底埋在底板內 1 mm 起算，柱底面不與底板底面重合（閃爍）
  const column = bevelBox(200, colH - 1, 240, matArm, 8); column.position.set(0, (colH + 1) / 2, -30); root.add(column);
  block(root, [230, 12, 270], [0, 6, -30], matArmD);
  for (const x of [-100, 100]) for (const z of [-150, 90]) screw(root, [x, 12.4, z], 4);
  decal(root, 120, 34, [0, colH - 70, 90.8], [0, 0, 0], 'DENSO', { color: '#c8102e', center: true, bold: true });
  decal(root, 110, 26, [0, colH - 120, 90.8], [0, 0, 0], 'HSR065', { color: '#59616b', center: true });
  tube(root, [[0, 60, -150], [0, 40, -210], [0, 30, -280]], 14, matArmD).name = 'robot rear cable outlet';
  const armParts = [column];
  // ---- J1、第一臂 ----
  const j1 = new THREE.Group(); j1.position.y = colH; root.add(j1);
  const a1 = bevelBox(130, arm1H, L1, matArm, 10); a1.position.set(0, arm1H / 2, L1 / 2); j1.add(a1);
  const a1c = new THREE.Mesh(new THREE.CylinderGeometry(78, 78, arm1H, 40), matArm); a1c.position.y = arm1H / 2; j1.add(a1c);
  const a1e = new THREE.Mesh(new THREE.CylinderGeometry(65, 65, arm1H, 40), matArm); a1e.position.set(0, arm1H / 2, L1); j1.add(a1e);
  decal(j1, 150, 30, [66, arm1H / 2, L1 / 2], [0, Math.PI / 2, 0], 'DENSO', { color: '#c8102e', center: true, bold: true });
  armParts.push(a1, a1c, a1e);
  // ---- J2、第二臂 ----
  const j2 = new THREE.Group(); j2.position.set(0, arm1H, L1); j1.add(j2);
  const a2 = bevelBox(110, arm2H, L2, matArm, 10); a2.position.set(0, arm2H / 2, L2 / 2); j2.add(a2);
  const a2c = new THREE.Mesh(new THREE.CylinderGeometry(60, 60, arm2H, 40), matArm); a2c.position.y = arm2H / 2; j2.add(a2c);
  const cover = bevelBox(120, 95, 170, matArm, 12); cover.position.set(0, arm2H + 47, L2 - 30); j2.add(cover);    // J3／J4 馬達蓋
  const joint2 = new THREE.Mesh(new THREE.CylinderGeometry(50, 50, 8, 40), matJoint); joint2.position.y = 0; j2.add(joint2);
  armParts.push(a2, a2c, cover);
  // ---- 花鍵軸（J3 上下、J4 旋轉）----
  const shaft = new THREE.Group(); shaft.position.set(0, 0, L2); j2.add(shaft);
  const spline = new THREE.Mesh(new THREE.CylinderGeometry(10, 10, 400, 24), matShaft); spline.position.y = 200; shaft.add(spline);
  const stopper = cylinder(shaft, 14, 10, [0, 395.8, 0], matJoint, 'y', 24);   // 頂面高出花鍵軸端 0.8 mm，不重合
  const bellow = new THREE.Mesh(new THREE.CylinderGeometry(15, 15, 60, 20), matJoint); bellow.position.set(0, 0, 0); j2.add(bellow); bellow.position.set(0, -30, L2);
  armParts.push(spline, stopper);
  // ---- 工具頭（隨 J4 旋轉）----
  const tool = new THREE.Group(); tool.name = 'tool'; shaft.add(tool);
  cylinder(tool, 22, 10, [0, -5, 0], matJoint, 'y', 28);
  const plate = block(tool, [108, 8, 100], [0, -14, -18], matTool); plate.name = 'tool-plate';
  for (const x of [-46, 46]) for (const z of [-60, 24]) screw(tool, [x, -9.7, z], 2.2);
  decal(tool, 40, 10, [0, -9.3, 20], [-Math.PI / 2, 0, 0], 'EOAT', { color: '#2b3540', center: true });
  const slides = {}, contact = [];
  function slide(key, bodyColor = matBlueAnod) {
    const { x, z } = TOOL[key], g = new THREE.Group(); g.position.set(x, 0, z); tool.add(g);
    block(g, [20, 40, 22], [0, -38, 0], bodyColor);                // 氣動滑台本體
    const move = new THREE.Group(); g.add(move); slides[key] = move;
    return move;
  }
  // T1 葉片吸嘴：真空管、軟性緩衝、多孔吸盤（長 5 mm、寬 1.4 mm）
  const t1 = slide('T1');
  cylinder(t1, 4, 24, [0, -66, 0], matTool, 'y', 16);
  const t1shaft = cylinder(t1, 1.8, 10, [0, -83, 0], matShaft, 'y', 16);
  const t1body = cylinder(t1, 2.6, 6, [0, -85, 0], matAnod, 'y', 16);
  // Below the white plate, only a narrow vacuum stem fits behind the blade.
  // The former 5.2 mm collar obscured the real contour in the up-camera image.
  const t1stem = cylinder(t1, .45, 8.8, [0, -92.4, 0], matShaft, 'y', 16);
  t1stem.name = 'T1-vacuum-stem';
  const t1tip = block(t1, [1.4, 1.2, 5.0], [0, -97.4, 0], matPad); t1tip.name = 'T1-pad';
  tube(t1, [[4, -60, 0], [9, -52, 4], [12, -30, 8]], .9, matGlass, 12);
  // 白色背景板：上視相機拍葉片時形成剪影（黑色葉片對白底），同時遮住上方的工具頭
  const backdrop = new THREE.Mesh(new THREE.CylinderGeometry(16, 16, 0.8, 48), new THREE.MeshStandardMaterial({ color: 0xf4f6f7, roughness: 0.9, emissive: 0xffffff, emissiveIntensity: 0.25 }));
  backdrop.name = 'T1-camera-backdrop';
  backdrop.position.y = -89.6; backdrop.castShadow = true; t1.add(backdrop);
  contact.push(t1tip, t1stem, t1shaft, t1body);
  // T2：外框均壓背板＋四個真空接觸墊，避開上蓋的沖孔。
  const t2 = slide('T2');
  cylinder(t2, 9, 6, [0, -61, 0], matAnod, 'y', 24);                // 荷重元
  decal(t2, 10, 3, [0, -61, 9.05], [0, 0, 0], 'LOAD', { color: '#d6e1ea', center: true });
  cylinder(t2, 3, 16, [0, -72, 0], matShaft, 'y', 12);
  const t2springs = [];
  for (const [sx, sz] of [[-6, -6], [6, -6], [-6, 6], [6, 6]]) { const s = cylinder(t2, 1.3, 10, [sx, -83, sz], matTool, 'y', 10); t2springs.push(s); }
  const frame = new THREE.Group(); t2.add(frame);
  block(frame, [20, 3, 19], [0, -89.5, 0], matAnod);
  const fw = 17.8, fd = 16.8, band = 2.6, fy = -96.5, fh = 3;
  for (const [w, d, x, z] of [[fw, band, 0, -(fd - band) / 2], [fw, band, 0, (fd - band) / 2], [band, fd - 2 * band, -(fw - band) / 2, 0], [band, fd - 2 * band, (fw - band) / 2, 0]]) {
    block(frame, [w, 1, d], [x, fy + 1, z], matAnod);
  }
  for(const x of PART.coverPads.x) for(const z of PART.coverPads.z) {
    const pad = block(frame, [PART.coverPads.w, fh, PART.coverPads.d], [x, fy, z], matPad);
    pad.name = 'T2-vacuum-pad'; contact.push(pad);
  }
  block(frame, [4, 4, 4], [0, -93, 0], matAnod);
  function setCompliance(mm) {
    frame.position.y=mm;
    for(const spring of t2springs) { spring.scale.y=(10-mm)/10;spring.position.y=-83+mm/2; }
  }
  // T3 本體夾爪：平行夾爪，ESD 夾指夾本體 ±z 側面
  const t3 = slide('T3', matAnod);
  block(t3, [26, 14, 18], [0, -65, 0], matBlueAnod);
  decal(t3, 16, 5, [0, -65, 9.7], [0, 0, 0], 'GRIP', { color: '#d6e1ea', center: true });
  const fingers = [];
  for (const s of [-1, 1]) {
    const f = new THREE.Group(); t3.add(f);
    block(f, [8, 4, 3], [0, -73, 0], matAnod);
    const tip = block(f, [6, 26, TOOL.fingerT], [0, -85, 0], matESD); contact.push(tip);
    fingers.push({ group: f, side: s });
  }
  // 下視相機：5MP 相機＋20 mm 鏡頭＋環形光（固定，不伸縮）
  const cam = new THREE.Group(); cam.position.set(TOOL.cam.x, 0, TOOL.cam.z); tool.add(cam);
  const camBody = block(cam, [29, 29, 29], [0, -32, 0], matArmD);
  decal(cam, 22, 8, [0, -32, 15.2], [0, 0, 0], '5 MP', { color: '#c5d0d8', center: true });
  cylinder(cam, 9, 12, [0, -52, 0], matJoint, 'y', 20);
  const ringMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.05 });
  const ring = new THREE.Mesh(new THREE.TorusGeometry(12, 2.2, 10, 36), ringMat); ring.rotation.x = Math.PI / 2; ring.position.y = -58; cam.add(ring);
  const glass = cylinder(cam, 7, .6, [0, -58.8, 0], matGlass, 'y', 20);   // 保護玻璃凸出鏡頭端面 1.1 mm
  tube(cam, [[0, -20, -12], [0, -14, -24], [10, -8, -40]], 2, matJoint, 12);
  const flash = new THREE.SpotLight(0xffffff, 0, 300, 0.6, 0.6, 1); flash.position.set(0, -60, 0); flash.target.position.set(0, -200, 0); cam.add(flash, flash.target);
  // 子畫面用相機：IMX264 2/3"（8.45 × 7.07 mm）＋20 mm
  const pipCam = new THREE.PerspectiveCamera(2 * Math.atan(7.07 / 2 / 20) / D2R, 2448 / 2048, 0.5, 600);
  pipCam.position.set(0, -59.2, 0); pipCam.rotation.x = -Math.PI / 2; cam.add(pipCam);   // 光軸朝工具 −y，畫面上方＝工具 −z
  void glass;
  const cameraParts = [camBody];
  // TCP 物件
  const tcps = {};
  for (const key of ['T1', 'T2', 'T3', 'cam']) { const o = new THREE.Object3D(); o.position.copy(TCP_OFFSET[key]); tool.add(o); tcps[key] = o; }
  for (const part of contact) part.traverse(o => { o.userData.contact = true; });

  cable(j1,'SCARA / upper fixed sleeve',[[0,88,60],[0,104,115],[0,104,200],[0,88,250]],{radius:5,color:CABLE.sleeve});
  cable(j2,'SCARA / forearm fixed sleeve',[[0,70,60],[0,94,95],[0,94,140],[0,70,165]],{radius:4,color:CABLE.sleeve,clips:1});
  const zHarness=carrier(j2,'SCARA / Z service carrier',{origin:[90,40,L2],axis:[0,1,0],rise:[1,0,0],min:-440,max:0,radius:25,width:20,pitch:12});
  support(j2,'SCARA / fixed guide mount',[60,100,L2],[79,100,L2],5);
  // 線材起點在拖鏈活動端固定座（寬 26 mm）內；背撐軌偏 18 mm，軌與腳座不穿過固定座
  cable(shaft,'SCARA / Z return to rotary inlet',[[140,0,0],[95,16,0],[40,20,0],[15,20,0]],{radius:3,color:CABLE.sleeve,backing:{offset:[0,0,18],feet:[[0,[15,30,0]],[3,[10,20,0]]],radius:4}});
  cable(tool,'CAM / rear connector',[[40,-10,-64],[40,-23,-75],[20,-32,-72],[0,-32,-60.5]],{radius:1.8,color:CABLE.signal});
  for(const x of [-36,0,36])cable(tool,'AIR / slide '+x,[[x,-18,18],[x,-29,27],[x,-44,26],[x,-48,11]],{radius:1.4,color:CABLE.air,clips:1});

  // ---- 關節狀態 ----
  const q = { j1: -1.5, j2: 1.9, d3: 60, j4: 0 };
  const home = { ...q };
  function apply() {
    j1.rotation.y = q.j1; j2.rotation.y = q.j2;
    shaft.position.y = SCARA.Y0 - SCARA.colH - SCARA.arm1H - root.position.y - q.d3;   // 相對 J2 群組
    // Like the spline datum, the routing mount uses the installed world height.
    zHarness.group.position.y=940-root.position.y;
    zHarness.set(shaft.position.y-zHarness.group.position.y);
    tool.rotation.y = q.j4;
    root.updateMatrixWorld(true);
  }
  apply();
  let ext = { T1: 0, T2: 0, T3: 0 };
  function setTools({ T1 = 0, T2 = 0, T3 = 0, open = 1 } = {}) {
    ext = { T1, T2, T3 };
    for (const k of ['T1', 'T2', 'T3']) slides[k].position.y = -ext[k] * TOOL.stroke;
    for (const f of fingers) f.group.position.z = f.side * (TOOL.gripZ + TOOL.fingerT / 2 + open * TOOL.fingerOpen);
  }
  setTools({});

  // ---- 運動學 ----
  const base = () => root.position;
  /** 正解：關節 → 某 TCP 的世界座標與 yaw（工具頭以伸出狀態計） */
  function fk(c, key = 'T1') {
    const a = c.j1, b = c.j1 + c.j2, yaw = c.j1 + c.j2 + c.j4, o = TCP_OFFSET[key];
    const fx = base().x + L1 * Math.sin(a) + L2 * Math.sin(b), fz = base().z + L1 * Math.cos(a) + L2 * Math.cos(b);
    return { p: new THREE.Vector3(fx + o.x * Math.cos(yaw) + o.z * Math.sin(yaw), SCARA.Y0 - c.d3 + o.y, fz - o.x * Math.sin(yaw) + o.z * Math.cos(yaw)), yaw };
  }
  const within = c => JOINTS.every(n => { const [lo, hi] = SCARA.limits[n]; const v = n === 'd3' ? c[n] : c[n] / D2R; return v >= lo - 1e-6 && v <= hi + 1e-6; });
  /** 逆解：兩組肘部解中取離參考最近者；J4 取 ±360° 內最接近參考的等價角 */
  function ik(key, target, yaw, ref = q) {
    const o = TCP_OFFSET[key];
    const fx = target.x - (o.x * Math.cos(yaw) + o.z * Math.sin(yaw)) - base().x, fz = target.z - (-o.x * Math.sin(yaw) + o.z * Math.cos(yaw)) - base().z;
    const r2 = fx * fx + fz * fz, c2 = (r2 - L1 * L1 - L2 * L2) / (2 * L1 * L2), d3 = SCARA.Y0 - (target.y - o.y);
    if (Math.abs(c2) > 1) return null;
    let best = null, bestD = Infinity;
    for (const s of [1, -1]) {
      const b2 = s * Math.acos(c2), b1 = Math.atan2(fx, fz) - Math.atan2(L2 * Math.sin(b2), L1 + L2 * Math.cos(b2));
      const c = { j1: wrapPi(b1), j2: b2, d3, j4: 0 };
      const j4 = wrapPi(yaw - c.j1 - c.j2);
      for (const k of [0, 2 * Math.PI, -2 * Math.PI]) {
        const cand = { ...c, j4: j4 + k }; if (!within(cand)) continue;
        const d = Math.abs(cand.j1 - ref.j1) * 2 + Math.abs(cand.j2 - ref.j2) + Math.abs(cand.j4 - ref.j4) * 0.2;
        if (d < bestD) { bestD = d; best = cand; }
      }
    }
    return best;
  }

  // ---- 目標與追蹤 ----
  const goal = { target: new THREE.Vector3(), yaw: 0, tcp: 'T1', speed: 800, joints: null };
  const cur = { target: new THREE.Vector3(), yaw: 0, tcp: 'T1' };
  const jointCache = new WeakMap();
  function solveJoints(pose, ref = null) {
    let c = jointCache.get(pose); if (c) return c;
    c = ik(pose.tcp, pose.target, pose.yaw, ref || q) || { ...q, unreachable: true };
    jointCache.set(pose, c); return c;
  }
  function plan(poses) { let ref = null; for (const p of poses) ref = solveJoints(p, ref); }
  function ptpTime(a, b) { const ja = solveJoints(a), jb = solveJoints(b); return 1.875 * Math.max(...JOINTS.map(n => Math.abs(jb[n] - ja[n]) / SCARA.speed[n])); }
  function poseFor(tcp, target, yaw = 0) { return { tcp, target: target.clone(), yaw }; }
  function setGoal(pose) { goal.joints = null; goal.tcp = pose.tcp; goal.target.copy(pose.target); goal.yaw = pose.yaw; goal.ref = pose.ref || null; }
  function setPose(p) {
    if (!p.ptp) return setGoal(p);
    const a = solveJoints(p.ptp.from), b = solveJoints(p.ptp.to), joints = {};
    for (const n of JOINTS) joints[n] = THREE.MathUtils.lerp(a[n], b[n], p.ptp.e);
    const f = fk(joints, p.ptp.to.tcp); goal.tcp = p.ptp.to.tcp; goal.target.copy(f.p); goal.yaw = f.yaw; goal.joints = joints;
  }
  function syncCur() { const f = fk(q, goal.tcp); cur.tcp = goal.tcp; cur.target.copy(f.p); cur.yaw = f.yaw; }
  const _d = new THREE.Vector3();
  function update(dt) {
    if (dt <= 0) return;
    let want;
    if (goal.joints) want = goal.joints;
    else {
      if (cur.tcp !== goal.tcp) syncCur();
      const d = _d.copy(goal.target).sub(cur.target), dist = d.length(), step = goal.speed * dt;
      if (dist > step) cur.target.addScaledVector(d.normalize(), step); else cur.target.copy(goal.target);
      const dy = wrapPi(goal.yaw - cur.yaw), ys = 8 * dt; cur.yaw += Math.abs(dy) > ys ? Math.sign(dy) * ys : dy;
      want = ik(goal.tcp, cur.target, cur.yaw, q) || q;
    }
    for (const n of JOINTS) q[n] += THREE.MathUtils.clamp(want[n] - q[n], -SCARA.speed[n] * dt, SCARA.speed[n] * dt);
    apply(); if (goal.joints) syncCur();
  }
  function snap() {
    const c = goal.joints || ik(goal.tcp, goal.target, goal.yaw, goal.ref ? solveJoints(goal.ref) : q);
    if (c) Object.assign(q, { j1: c.j1, j2: c.j2, d3: c.d3, j4: c.j4 });
    apply(); syncCur();
  }
  function error() {
    const f = fk(q, goal.tcp);
    return { position: f.p.distanceTo(goal.target), angle: Math.abs(wrapPi(f.yaw - goal.yaw)) / D2R };
  }
  function reach(pose) { const c = solveJoints(pose); if (c.unreachable) return { position: Infinity, angle: Infinity }; const f = fk(c, pose.tcp); return { position: f.p.distanceTo(pose.target), angle: Math.abs(wrapPi(f.yaw - pose.yaw)) / D2R }; }
  function getTcpWorld(key, out = new THREE.Vector3()) { return tcps[key].getWorldPosition(out); }
  function getTcpYaw() { return q.j1 + q.j2 + q.j4; }
  function setFlash(on) { flash.intensity = on ? 60 : 0; ringMat.emissiveIntensity = on ? 1.4 : 0.05; }

  return { root, q, home, goal, cur, update, apply, snap, error, reach, plan, ptpTime, poseFor, setPose, fk, ik, solveJoints,
    getTcpWorld, getTcpYaw, setTools, setFlash, setCompliance, tcps, tool, pipCam, get ext() { return ext; }, get compliance() { return frame.position.y; },
    clearanceParts: { arm: armParts, camera: cameraParts } };
}
