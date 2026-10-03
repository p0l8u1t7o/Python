// DENSO HSR065 SCARA 手臂本體：基座柱、第一臂（J1）、第二臂（J2）、花鍵軸（J3 上下、J4 旋轉）、臂上線材與 Z 軸拖鏈、工具法蘭。
// 原用於 shutter assembly。工具頭（吸嘴、夾爪、相機）、TCP 與作業姿態留在各專案，裝在 arm.flange 底下（法蘭本地 −y 朝下）。
// 局部座標：原點在底座底面中心，y 向上；J1＝J2＝0 時手臂伸向 +z。角度 rad、長度 mm。
import * as THREE from 'three';
import { cable, carrier, support, CABLE } from '../../electrical/cable-routing.js';
import { block, cylinder, decal, bevelBox, screw, tube } from '../../geom/primitives.js';

const D2R = Math.PI / 180;

/**
 * 機型參數：HSR065 型錄動作範圍 650 mm、Z 行程 200 mm；臂長分配、J1 座高、法蘭高與速度為假設值，需以 DENSO 型錄／CAD 核對。
 * flange0：Z＝0（最上）時法蘭端面距底座底面的高度。speed：假設型錄最高速度的 50%（rad/s、mm/s）。
 */
export const HSR065 = {
  L1: 350, L2: 300, colH: 320, arm1H: 80, arm2H: 70,
  flange0: 270,
  limits: { j1: [-170, 170], j2: [-145, 145], d3: [0, 200], j4: [-360, 360] },
  speed: { j1: 3.3, j2: 6.1, d3: 850, j4: 21 },
};
/** 關節名稱：j1、j2、j4 為 rad，d3 為 Z 下降量 mm（0＝最上） */
export const JOINTS = ['j1', 'j2', 'd3', 'j4'];
export const wrapPi = a => Math.atan2(Math.sin(a), Math.cos(a));

/** 本體材質；工具頭可共用（例如法蘭、花鍵軸同色的零件） */
export const HSR065_MAT = {
  arm: new THREE.MeshStandardMaterial({ color: 0xeef0f1, roughness: 0.4, metalness: 0.1 }),
  armDark: new THREE.MeshStandardMaterial({ color: 0x2f343a, roughness: 0.5, metalness: 0.3 }),
  joint: new THREE.MeshStandardMaterial({ color: 0x1c1f23, roughness: 0.4, metalness: 0.5 }),
  shaft: new THREE.MeshStandardMaterial({ color: 0xd9dee3, roughness: 0.12, metalness: 0.95 }),
};

const ZERO = { x: 0, y: 0, z: 0 };

/** 關節是否在動作範圍內 */
export function withinLimits(c) {
  return JOINTS.every(n => { const [lo, hi] = HSR065.limits[n]; const v = n === 'd3' ? c[n] : c[n] / D2R; return v >= lo - 1e-6 && v <= hi + 1e-6; });
}

/**
 * 正解：關節 → 法蘭本地偏移 o（隨 J4 轉）的位置與 yaw。
 * base：底座底面中心的位置（例如 arm.root.position）；回傳座標與 base 同一座標系。
 */
export function fk(c, o = ZERO, base = ZERO) {
  const { L1, L2 } = HSR065;
  const a = c.j1, b = c.j1 + c.j2, yaw = c.j1 + c.j2 + c.j4, y0 = base.y + HSR065.flange0;
  const fx = base.x + L1 * Math.sin(a) + L2 * Math.sin(b), fz = base.z + L1 * Math.cos(a) + L2 * Math.cos(b);
  return { p: new THREE.Vector3(fx + o.x * Math.cos(yaw) + o.z * Math.sin(yaw), y0 - c.d3 + o.y, fz - o.x * Math.sin(yaw) + o.z * Math.cos(yaw)), yaw };
}

/**
 * 逆解：讓偏移 o 到達 target、整體 yaw 為 yaw。兩組肘部解中取離參考 ref 最近者；J4 取 ±360° 內最接近參考的等價角。
 * 超出工作範圍或關節限制時回傳 null。
 */
export function ik(target, yaw, ref = { j1: 0, j2: 0, d3: 0, j4: 0 }, o = ZERO, base = ZERO) {
  const { L1, L2 } = HSR065, y0 = base.y + HSR065.flange0;
  const fx = target.x - (o.x * Math.cos(yaw) + o.z * Math.sin(yaw)) - base.x, fz = target.z - (-o.x * Math.sin(yaw) + o.z * Math.cos(yaw)) - base.z;
  const r2 = fx * fx + fz * fz, c2 = (r2 - L1 * L1 - L2 * L2) / (2 * L1 * L2), d3 = y0 - (target.y - o.y);
  if (Math.abs(c2) > 1) return null;
  let best = null, bestD = Infinity;
  for (const s of [1, -1]) {
    const b2 = s * Math.acos(c2), b1 = Math.atan2(fx, fz) - Math.atan2(L2 * Math.sin(b2), L1 + L2 * Math.cos(b2));
    const c = { j1: wrapPi(b1), j2: b2, d3, j4: 0 };
    const j4 = wrapPi(yaw - c.j1 - c.j2);
    for (const k of [0, 2 * Math.PI, -2 * Math.PI]) {
      const cand = { ...c, j4: j4 + k }; if (!withinLimits(cand)) continue;
      const d = Math.abs(cand.j1 - ref.j1) * 2 + Math.abs(cand.j2 - ref.j2) + Math.abs(cand.j4 - ref.j4) * 0.2;
      if (d < bestD) { bestD = d; best = cand; }
    }
  }
  return best;
}

/**
 * 建立手臂本體。回傳：
 *   root      底座（放到安裝位置即可；fk／ik 的 base 傳 root.position）
 *   flange    隨 J4 旋轉的工具法蘭群組（已含法蘭盤，端面在本地 y＝0，工具往 −y 裝）
 *   j1, j2, shaft  各關節群組；armParts 為本體主要外殼（[0] 為基座柱，給間隙檢查用）
 *   setJoints({ j1, j2, d3, j4 })  放到關節值並更新世界矩陣
 */
export function createHSR065() {
  const { L1, L2, colH, arm1H, arm2H } = HSR065;
  const { arm: matArm, armDark: matArmD, joint: matJoint, shaft: matShaft } = HSR065_MAT;
  const root = new THREE.Group(); root.name = 'HSR065';
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
  const bellow = new THREE.Mesh(new THREE.CylinderGeometry(15, 15, 60, 20), matJoint); j2.add(bellow); bellow.position.set(0, -30, L2);
  armParts.push(spline, stopper);
  // ---- 工具法蘭（隨 J4 旋轉；工具頭由專案裝在其下）----
  const flange = new THREE.Group(); flange.name = 'flange'; shaft.add(flange);
  cylinder(flange, 22, 10, [0, -5, 0], matJoint, 'y', 28);

  // ---- 臂上線材與 Z 軸拖鏈 ----
  cable(j1, 'SCARA / upper fixed sleeve', [[0, 88, 60], [0, 104, 115], [0, 104, 200], [0, 88, 250]], { radius: 5, color: CABLE.sleeve });
  cable(j2, 'SCARA / forearm fixed sleeve', [[0, 70, 60], [0, 94, 95], [0, 94, 140], [0, 70, 165]], { radius: 4, color: CABLE.sleeve, clips: 1 });
  const zHarness = carrier(j2, 'SCARA / Z service carrier', { origin: [90, 40, L2], axis: [0, 1, 0], rise: [1, 0, 0], min: -440, max: 0, radius: 25, width: 20, pitch: 12 });
  support(j2, 'SCARA / fixed guide mount', [60, 100, L2], [79, 100, L2], 5);
  // 線材起點在拖鏈活動端固定座（寬 26 mm）內；背撐軌偏 18 mm，軌與腳座不穿過固定座
  cable(shaft, 'SCARA / Z return to rotary inlet', [[140, 0, 0], [95, 16, 0], [40, 20, 0], [15, 20, 0]], { radius: 3, color: CABLE.sleeve, backing: { offset: [0, 0, 18], feet: [[0, [15, 30, 0]], [3, [10, 20, 0]]], radius: 4 } });

  // ---- 關節狀態 ----
  const shaft0 = HSR065.flange0 - colH - arm1H;            // Z＝0 時花鍵軸群組相對 J2 群組的高度
  function setJoints(q) {
    j1.rotation.y = q.j1; j2.rotation.y = q.j2;
    shaft.position.y = shaft0 - q.d3;
    zHarness.group.position.y = 40;                          // 拖鏈固定端在第二臂內（相對 J2 群組）
    zHarness.set(shaft.position.y - zHarness.group.position.y);
    flange.rotation.y = q.j4;
    root.updateMatrixWorld(true);
  }
  setJoints({ j1: 0, j2: 0, d3: 0, j4: 0 });

  return { root, j1, j2, shaft, flange, zHarness, armParts, setJoints };
}

// ---------------------------------------------------------------- 模型目錄
// 目錄的 J2 範圍刻意比關節限制（±145°）窄：J2 > 120° 深摺時 Z 軸拖鏈（往第二臂 +x 側伸出）會撞基座柱；
// J2 < −140° 且 Z 接近行程底時法蘭盤會碰後方出線管。這兩區是本模型的基座干涉區，專案的作業姿態需避開
// （J1、Z 全範圍在 −140°～120° 內都不干涉）。
const S = HSR065.limits;
export const meta = {
  id: 'denso-hsr065', name: 'DENSO HSR065 SCARA', category: '機械手臂', source: 'shutter assembly',
  params: {},
  states: {
    j1: { value: 0, min: S.j1[0], max: S.j1[1], unit: '°', label: 'J1 第一臂' },
    j2: { value: 0, min: -140, max: 120, unit: '°', label: 'J2 第二臂（限制 ±145°，兩端為基座干涉區）' },
    z: { value: 0, min: S.d3[0], max: S.d3[1], unit: 'mm', label: 'J3 花鍵軸下降量' },
    r: { value: 0, min: S.j4[0], max: S.j4[1], unit: '°', label: 'J4 花鍵軸旋轉' },
  },
  usage: "import { createHSR065, HSR065, fk, ik } from '@core/models/robots/denso-hsr065.js';\nconst arm = createHSR065(); arm.root.position.set(x, 900, z); scene.add(arm.root);\narm.flange.add(myTool);                         // 工具往法蘭本地 −y 裝\nconst q = ik(target, yaw, ref, tcpOffset, arm.root.position);   // 回傳 { j1, j2, d3, j4 } 或 null\nif (q) arm.setJoints(q);",
};

export function create() {
  const arm = createHSR065();
  return {
    root: arm.root,
    set({ j1 = 0, j2 = 0, z = 0, r = 0 } = {}) { arm.setJoints({ j1: j1 * D2R, j2: j2 * D2R, d3: z, j4: r * D2R }); },
  };
}
