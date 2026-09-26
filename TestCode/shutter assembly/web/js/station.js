// 組裝整站並把流程狀態套到場景（主程式與驗證共用，確保畫面與驗證看到同一個狀態）。
// 零件位置由「歸屬」決定：料盤、工具（跟著實際 TCP）、治具、本體上（隨本體移動）、NG 盒、放回料盤。
import * as THREE from 'three';
import { createCell, LAYOUT, NEST_SEAT, pocket } from './cell.js';
import { createBase, createBlade, createCover, setCoverFlex, BLADES, bladeSeat, PART } from './product.js';
import { createRobot } from './robot.js';
import { SPEC, OFFSETS, slots } from './sequence.js';

const D2R = Math.PI / 180;
const rot = (x, z, a) => ({ x: x * Math.cos(a) + z * Math.sin(a), z: -x * Math.sin(a) + z * Math.cos(a) });

export function createStation(scene, { ng = false } = {}) {
  const cell = createCell(scene, { k: SPEC.k, ng });
  const robot = createRobot(); robot.root.position.set(...LAYOUT.robot); scene.add(robot.root); robot.apply();
  const parts = { base: createBase(), S1: createBlade('small'), S2: createBlade('small'), L1: createBlade('large'), L2: createBlade('large'), cover: createCover() };
  if (ng) {
    // 兩片黏在一起的大葉片（示意 NG）：下片略為錯開
    const d = new THREE.Group(); d.add(createBlade('large')); const lower = createBlade('large'); lower.position.set(0.25, -PART.blade.t, 0.18); lower.rotation.y = 0.05; d.add(lower); parts.L2x = d;
  }
  for (const p of Object.values(parts)) scene.add(p);
  const S = slots(ng), ids = Object.keys(parts);
  const binPose = { p: new THREE.Vector3(LAYOUT.ngBin.x - 6, LAYOUT.table + 2 + PART.blade.t * 2, LAYOUT.ngBin.z + 4), yaw: Math.PI + OFFSETS.L2x.a*D2R };
  let s = null;

  function trayPose(id) {
    const [kind, idx] = S[id], p = pocket(kind, idx), off = OFFSETS[id];
    if (id === 'base') return { p: p.clone().add(new THREE.Vector3(off.x, 0, 0.2)), yaw: 0.6 * D2R };  // 格內自然偏移；夾爪夾持時置中
    return { p: p.clone().add(new THREE.Vector3(off.x, id === 'L2x' ? PART.blade.t : 0, off.z)), yaw: off.a * D2R };
  }
  function heldPose(id, tcp) {
    const p = robot.getTcpWorld(tcp), yaw = robot.getTcpYaw();
    const off = id === 'base' && s.loc.cover === 'base' ? { x: 0, z: 0, a: 0 } : OFFSETS[id], o = rot(off.x, off.z, yaw);
    return { p: p.add(new THREE.Vector3(o.x, 0, o.z)), yaw: yaw + off.a * D2R };
  }
  function basePose() {
    const loc = s.loc.base;
    if (loc === 'tray') {
      const p=trayPose('base'),home=pocket('base',S.base[1]);
      p.p.z=home.z+.2*s.open;p.yaw=.6*D2R*s.open;return p;
    }
    if (loc === 'T3') return heldPose('base', 'T3');
    if (loc === 'out') return { p: pocket('base', S.base[1]), yaw: 0 };
    const r = 1 - s.baseShift; // Clamps releasing do not pull the seated body away from its datum.
    return { p: new THREE.Vector3(NEST_SEAT.x + 0.25 * r, NEST_SEAT.y, NEST_SEAT.z + 0.15 * r), yaw: 0 };
  }
  const onBase = (bp, x, y, z, yaw) => { const o = rot(x, z, bp.yaw); return { p: new THREE.Vector3(bp.p.x + o.x, bp.p.y + y, bp.p.z + o.z), yaw: bp.yaw + yaw }; };
  const poses = {};
  function sync() {
    if (!s) return;
    const bp = basePose(); poses.base = bp;
    for (const b of [...BLADES, ...(ng ? [{ id: 'L2x' }] : [])]) {
      const loc = s.loc[b.id];
      if (loc === 'tray') poses[b.id] = trayPose(b.id);
      else if (loc === 'T1') poses[b.id] = heldPose(b.id, 'T1');
      else if (loc === 'fall') {
        const start=heldPose(b.id,'T1'),p=start.p.clone().lerp(binPose.p,s.drop);
        p.y=start.p.y-(start.p.y-binPose.p.y)*s.drop*s.drop;
        poses[b.id]={p,yaw:start.yaw};
      }
      else if (loc === 'bin') poses[b.id] = binPose;
      else { const q = bladeSeat(b); poses[b.id] = onBase(bp, q.x, q.y, q.z, q.yaw); }
    }
    const cl = s.loc.cover;
    poses.cover = cl === 'tray' ? trayPose('cover') : cl === 'T2' ? heldPose('cover', 'T2') : onBase(bp, 0, PART.cover.t + s.float * PART.cover.float, 0, 0);
    for (const id of ids) { parts[id].position.copy(poses[id].p); parts[id].rotation.set(0, poses[id].yaw, 0); }
    const nearBase=Math.hypot(poses.cover.p.x-bp.p.x,poses.cover.p.z-bp.p.z)<.2;
    setCoverFlex(parts.cover,nearBase ? poses.cover.p.y-bp.p.y-PART.cover.t : 2);
    const tcp2=robot.getTcpWorld('T2'), atCover=Math.hypot(tcp2.x-poses.cover.p.x,tcp2.z-poses.cover.p.z)<1;
    const compression=s.loc.cover==='base' && s.t2>.99 && atCover ? Math.max(0,poses.cover.p.y-tcp2.y) : 0;
    robot.setCompliance(Math.min(.3,compression));
    scene.updateMatrixWorld(true);
  }
  function apply(state) {
    s = state;
    robot.setTools({ T1: s.t1, T2: s.t2, T3: s.t3, open: s.open });
    cell.setClamp(s.clamp); cell.setVacuum(s.clamp > 0.5); cell.setUpFlash(s.flashUp > 0); robot.setFlash(s.flashDown > 0);
    robot.apply(); sync();
  }
  /** 壓合力（示意）：浮動壓頭壓縮 0.30 mm 時達到設定力值。 */
  const force = () => robot.compliance / .3 * SPEC.pressForce;
  /** 零件世界位姿（驗證用） */
  const pose = id => poses[id];
  /** 產品包絡：治具上的本體（含已放零件）、料盤、NG 盒；接觸步驟只允許工具尖端進入 */
  function productBoxes(margin = 0) {
    const boxes = [];
    if (s && (s.loc.base === 'nest')) boxes.push(new THREE.Box3().setFromObject(parts.base));
    return [...boxes, ...cell.trayBoxes.map(b => b.clone())].map(b => b.expandByScalar(margin));
  }
  return { cell, robot, parts, apply, sync, force, pose, productBoxes, slots: S, get state() { return s; } };
}
