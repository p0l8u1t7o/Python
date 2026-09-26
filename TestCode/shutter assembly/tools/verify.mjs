// 驗證（OK 與示意疊片 NG 兩種流程）：
// 1. 全部步驟代表時刻的 TCP 可達性（PTP 檢查終點）與關節限位；兩個抽屜所有料格都搆得到。
// 2. 任意倒退／跳站的狀態與 TCP 目標一致。
// 3. 工具對固定結構（治具槽壁、推塊、上視環形光、離子風嘴、NG 盒、抽屜、手臂基座、外罩）的碰撞；
//    接近與接觸步驟只允許工具尖端（吸盤、夾指）進入產品與料盤包絡；移動中夾持的零件也不得碰撞。
// 4. 組裝結果：4 片葉片的樞軸孔與長孔對準銷（容差 0.005 mm）、疊放順序、上蓋對正且壓到底、成品放回原格。
// 5. 每次取像時被拍物完整在相機視野內。
// 6. 連續播放（實際限速＋到位等待，每 0.25 秒做一次碰撞檢查）。
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import * as THREE from 'three';
globalThis.document = { createElement: () => ({ width: 1024, height: 512, getContext: () => ({ fillRect() {}, fillText() {} }) }) };
const { createStation } = await import('../web/js/station.js');
const { createSequence, SPEC, nestPose } = await import('../web/js/sequence.js');
const { TRAYS, pocket, pocketCount, LAYOUT } = await import('../web/js/cell.js');
const { BLADES, PART, bladeHoles, drivePin } = await import('../web/js/product.js');
const { SCARA } = await import('../web/js/robot.js');

const failures = [], report = [];
const D2R = Math.PI / 180;
const rot = (x, z, a) => ({ x: x * Math.cos(a) + z * Math.sin(a), z: -x * Math.sin(a) + z * Math.cos(a) });

for (const ng of [false, true]) {
  const mode = ng ? 'NG 疊片示意' : 'OK';
  const scene = new THREE.Scene(), st = createStation(scene, { ng }), { robot, cell } = st;
  const seq = createSequence({ robot, apply: st.apply, ng });
  const visible = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
  const meshes = []; robot.tool.traverse(o => { if (o.isMesh && !o.material.transparent && visible(o)) meshes.push(o); });
  const vtx = new THREE.Vector3(), mbox = new THREE.Box3();
  const fixed = () => [...cell.keepout.map(m => [m.name, new THREE.Box3().setFromObject(m)]), ['手臂基座', new THREE.Box3().setFromObject(robot.clearanceParts.arm[0])]];
  function collisions(allowTip) {
    const hits = new Set(), fx = fixed(), prod = st.productBoxes(0.2).map(b => ['產品／料盤', b]);
    for (const m of meshes) {
      mbox.setFromObject(m);
      const list = [...fx, ...(allowTip && m.userData.contact ? [] : prod)].filter(([, b]) => mbox.intersectsBox(b));
      if (!list.length) continue;
      const pos = m.geometry.attributes.position;
      for (const [name, b] of list) for (let i = 0; i < pos.count; i++) { vtx.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld); if (b.containsPoint(vtx)) { hits.add(name + '←' + (m.name || m.parent?.name || 'tool')); break; } }
    }
    // 夾持中的零件在移動段不得碰固定結構（放入治具槽的間隙另由放料精度檢查）
    if (!allowTip) for (const [id, part] of Object.entries(st.parts)) {
      if (!['T1', 'T2', 'T3'].includes(st.state.loc[id])) continue;
      const b = new THREE.Box3().setFromObject(part);
      for (const [name, k] of fx) if (b.intersectsBox(k)) hits.add(`${name}←夾持中的 ${id}`);
    }
    return [...hits];
  }
  let maxError = 0, worst = '', maxForce = 0; const placement = [];
  for (const step of seq.steps) for (const frac of [.001, .5, .999]) {
    const time = step.start + step.dur * frac, { state: s } = seq.sample(time);
    robot.snap(); st.sync();
    const e = step.ptp ? robot.reach(step.pose1) : robot.error();
    if (e.position > maxError) { maxError = e.position; worst = step.action; }
    if (!(e.position < 0.01 && e.angle < 0.05)) failures.push({ mode, action: step.action, frac, ...e });
    maxForce = Math.max(maxForce, st.force());
    if (st.force() > SPEC.forceLimit) failures.push({ mode, action: step.action, force: st.force() });
    const hit = step.ptp ? [] : collisions(step.near || step.contact); if (hit.length) failures.push({ mode, action: step.action, frac, collision: hit });
    // 放料瞬間（仍由工具夾持、TCP 已到位）：零件實際位置對目標位姿
    if (frac === .999 && step.end.loc && s.loc) for (const [id, loc] of Object.entries(step.end.loc)) {
      if (loc !== 'base' || step.initial.loc[id] === 'base') continue;
      const held = st.pose(id), seat = nestPose(id, id === 'cover' ? 1 : 0);
      const err = Math.hypot(held.p.x - seat.p.x, held.p.y - seat.p.y, held.p.z - seat.p.z), eYaw = Math.abs(held.yaw - seat.yaw) / D2R;
      placement.push({ id, err: +err.toFixed(5), yawErr: +eYaw.toFixed(4) });
      if (err > 0.005 || eYaw > 0.01) failures.push({ mode, place: id, err, eYaw });
    }
    const before = JSON.stringify(s), target = robot.goal.target.toArray();
    seq.sample(seq.total - 1); seq.sample(0); const after = seq.sample(time).state;
    assert.equal(JSON.stringify(after), before, 'history-dependent machine state'); assert.deepEqual(robot.goal.target.toArray(), target, 'history-dependent TCP goal');
  }

  // ---- 取像框景：被拍物的包絡八角都在相機視野內 ----
  const framing = [];
  for (const step of seq.steps.filter(x => x.exposure)) {
    const { state: s } = seq.sample(step.start + step.dur * .5); robot.snap(); st.sync();
    const cam = step.exposure === 'up' ? cell.upCam : robot.pipCam; cam.updateMatrixWorld(true);
    const id = s.shot.split(':')[1], obj = step.exposure === 'up' ? st.parts[id] : st.parts.base;
    const b = new THREE.Box3().setFromObject(obj);
    if (step.exposure === 'down') { b.min.x = Math.max(b.min.x, st.pose('base').p.x - PART.base.w / 2 - .2); }   // 導線不在檢查範圍
    let worstN = 0;
    for (const x of [b.min.x, b.max.x]) for (const y of [b.min.y, b.max.y]) for (const z of [b.min.z, b.max.z]) {
      const p = new THREE.Vector3(x, y, z).project(cam); worstN = Math.max(worstN, Math.abs(p.x), Math.abs(p.y));
    }
    framing.push({ shot: s.shot, maxNdc: +worstN.toFixed(3) });
    if (!(worstN < 0.98)) failures.push({ mode, shot: s.shot, framing: worstN });
  }

  // ---- 組裝結果 ----
  seq.sample(seq.total); robot.snap(); st.sync();
  const bp = st.pose('base'), result = [];
  for (const b of BLADES) {
    const q = st.pose(b.id), h = bladeHoles();
    const hole = { x: q.p.x + rot(h.pivot.x, h.pivot.z, q.yaw).x, z: q.p.z + rot(h.pivot.x, h.pivot.z, q.yaw).z };
    const slot = { x: q.p.x + rot(h.slot.x, h.slot.z, q.yaw).x, z: q.p.z + rot(h.slot.x, h.slot.z, q.yaw).z };
    const P = PART.pivots[b.pivot], pr = rot(P.x, P.z, bp.yaw), D = drivePin(b.pivot), dr = rot(D.x, D.z, bp.yaw);
    const ePivot = Math.hypot(hole.x - bp.p.x - pr.x, hole.z - bp.p.z - pr.z), eSlot = Math.hypot(slot.x - bp.p.x - dr.x, slot.z - bp.p.z - dr.z);
    const layer = q.p.y - bp.p.y;
    result.push({ id: b.id, pivotErr: +ePivot.toFixed(5), slotErr: +eSlot.toFixed(5), layerTop: +layer.toFixed(3) });
    if (ePivot > 0.005 || eSlot > 0.005) failures.push({ mode, blade: b.id, ePivot, eSlot });
  }
  const tops = result.map(r => r.layerTop); assert.deepEqual([...tops].sort((a, b) => a - b), tops, `${mode}: stack order`);
  const cv = st.pose('cover'), eCover = Math.hypot(cv.p.x - bp.p.x, cv.p.z - bp.p.z), coverGap = cv.p.y - bp.p.y - PART.cover.t;
  if (eCover > 0.01 || Math.abs(coverGap) > 1e-6 || Math.abs(cv.yaw - bp.yaw) > 0.01 * D2R) failures.push({ mode, cover: { eCover, coverGap } });
  const home = pocket('base', SPEC.k); assert(bp.p.distanceTo(home) < 1e-6, `${mode}: finished product back in pocket`);
  if (ng) assert.equal(st.state.loc.L2x, 'bin', 'NG double blade rejected');
  report.push({ mode, steps: seq.steps.length, cycle: +seq.total.toFixed(2), maxError: +maxError.toFixed(5), worst, maxForce, placement, blades: result, cover: { centerErr: +eCover.toFixed(5), seatedGap: +coverGap.toFixed(6) }, framing });

  // ---- 連續播放 ----
  let time = 0, elapsed = 0, wait = 0, frame = seq.sample(0), maxTrack = 0, iteration = 0; robot.snap(); st.sync();
  const dt = .005;
  while (time < seq.total && elapsed < seq.total * 4) {
    const e = robot.error(), s = frame.step, end = s.start + s.dur;
    const blocked = (time >= end - 1e-7 || ((s.contact || s.near) && e.position > .5)) && (e.position > .05 || e.angle > .2);
    if (blocked) { wait += dt; if (wait > 5) { failures.push({ mode, continuous: true, action: s.action, time, ...e }); break; } }
    else { wait = 0; time = time >= end - 1e-7 ? Math.min(seq.total, end + 1e-6) : Math.min(end, time + dt); frame = seq.sample(time >= end - 1e-7 && time <= end ? Math.max(s.start, end - 1e-8) : time); }
    robot.update(dt); st.sync(); elapsed += dt;
    if (s.near || s.contact) maxTrack = Math.max(maxTrack, e.position);
    if (++iteration % 50 === 0) { const hit = collisions(s.near || s.contact); if (hit.length) failures.push({ mode, continuous: true, action: s.action, time: +time.toFixed(2), collision: hit }); }
  }
  report.push({ mode, continuous: true, planned: +seq.total.toFixed(2), elapsed: +elapsed.toFixed(2), maxTrackErrorNear: +maxTrack.toFixed(3) });
  if (time < seq.total && !failures.some(f => f.continuous && f.mode === mode)) failures.push({ mode, continuous: true, time, reason: 'did not finish' });
}

// ---- 兩個抽屜所有料格都搆得到（取料高度與移動高度、yaw 0） ----
{
  const scene = new THREE.Scene(), { robot } = createStation(scene, {}), tools = { base: 'T3', cover: 'T2', small: 'T1', large: 'T1' };
  let n = 0, minMargin = Infinity;
  for (const kind of Object.keys(TRAYS)) for (const d of ['A', 'B']) for (let i = 0; i < pocketCount(kind); i++) {
    const p = pocket(kind, i, d);
    for (const y of [p.y, LAYOUT.travel]) {
      const c = robot.ik(tools[kind], new THREE.Vector3(p.x, y, p.z), 0);
      if (!c) { failures.push({ reach: `${kind} ${d}#${i + 1}`, y }); continue; }
      n++; minMargin = Math.min(minMargin, SCARA.limits.j2[1] - Math.abs(c.j2) / D2R, SCARA.limits.d3[1] - c.d3, c.d3);
    }
  }
  report.push({ pocketsReachable: n, minJointMargin: +minMargin.toFixed(1) });
}
const out = { date: new Date().toISOString().slice(0, 10), report, failures };
writeFileSync(new URL('../review/verification.json', import.meta.url), JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
if (failures.length) process.exitCode = 1;
