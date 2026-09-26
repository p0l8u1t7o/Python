// 驗證：可達性、關節限位與連續性（實際限速）、手臂與手上器皿對設備／器皿的碰撞、
// 器皿交接不跳位、秤重與滴定流程邏輯、轉盤與手臂互鎖、倒退／跳站一致性。
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import * as THREE from 'three';
globalThis.document = { createElement: () => ({ width: 1024, height: 512, getContext: () => ({ fillRect() {}, fillText() {} }) }) };
const { createSim } = await import('../web/js/sim.js');
const { ST, Y0, SAMPLES, TIME } = await import('../web/js/layout.js');

const t0 = Date.now();
const scene = new THREE.Scene(), sim = createSim(scene), { robot, lab, plan } = sim;
const failures = [], fail = (kind, info) => { if (failures.filter(f => f.kind === kind).length < 12) failures.push({ kind, ...info }); failures.count = (failures.count || 0) + 1; };
const D2R = Math.PI / 180, JOINTS = ['j1', 'j2', 'j3', 'j4', 'j5', 'j6'];

// ---------------------------------------------------------------- 1. 可達性（每個目標位姿）
let maxReach = 0, worstReach = '';
for (const st of plan.steps) { const e = robot.reach(st.p1); if (e.position > maxReach) { maxReach = e.position; worstReach = st.label; } if (e.position > 0.5 || e.angle > 0.5) fail('reach', { t: st.start, label: st.label, ...e }); }

// ---------------------------------------------------------------- 2. 碰撞
const visible = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
// 固定基座不檢查（本來就站在桌面上），只檢查 J1 之後會動的連桿與夾爪
const robotMeshes = []; robot.root.children.find(c => c.isGroup).traverse(o => { if (o.isMesh && !o.material.transparent) robotMeshes.push(o); });
const vtx = new THREE.Vector3(), mbox = new THREE.Box3();
function heldSet(s) {
  const held = new Set(), isHeld = id => { const L = s.loc[id]; if (!L || L.gone) return false; if (L.g) return true; if (L.on) return isHeld(L.on); return false; };
  for (const id in s.loc) if (isHeld(id)) held.add(id);
  return held;
}
// 器皿以直立圓柱表示（相鄰轉盤位 78 mm、杯 Ø65，軸對齊包圍盒會誤判）
const { BEAKER, BOTTLES, CAP, PIPETTE } = await import('../web/js/layout.js');
function itemCyl(id) {
  const g = lab.items[id], u = g.userData, p = g.getWorldPosition(new THREE.Vector3());
  if (u.kind === 'beaker') return { x: p.x, z: p.z, r: BEAKER.d / 2 + 2, y0: p.y, y1: p.y + BEAKER.h };
  if (u.kind === 'bottle') { const b = BOTTLES[SAMPLES[u.i].size]; return { x: p.x, z: p.z, r: b.d / 2, y0: p.y, y1: p.y + b.h + b.neckH }; }
  if (u.kind === 'cap') return { x: p.x, z: p.z, r: CAP.d / 2, y0: p.y, y1: p.y + CAP.h };
  if (u.kind === 'tip') return { x: p.x, z: p.z, r: PIPETTE.tipR, y0: p.y - PIPETTE.tipLen, y1: p.y };
  return null;
}
const boxCyl = (b, c, m = 0) => { if (b.max.y < c.y0 - m || b.min.y > c.y1 + m) return false; const dx = Math.max(b.min.x - c.x, 0, c.x - b.max.x), dz = Math.max(b.min.z - c.z, 0, c.z - b.max.z); return Math.hypot(dx, dz) < c.r + m; };
const cylCyl = (a, c, m = 0) => !(a.y1 < c.y0 - m || a.y0 > c.y1 + m) && Math.hypot(a.x - c.x, a.z - c.z) < a.r + c.r + m;
function collisions(T, st, s) {
  const touch = new Set(st.touch || []), held = heldSet(s), hits = new Set();
  const boxes = [], cyls = [];
  for (const k of lab.keepout) if (!touch.has(k.name) && visible(k.mesh)) boxes.push([k.name, new THREE.Box3().setFromObject(k.mesh, true).expandByScalar(3)]);
  for (const id in lab.items) if (lab.items[id].visible && !held.has(id) && !touch.has(id)) { const c = itemCyl(id); if (c) cyls.push([id, c]); else boxes.push([id, new THREE.Box3().setFromObject(lab.items[id]).expandByScalar(2)]); }
  const pt = new THREE.Box3();
  for (const m of robotMeshes) {
    if (!visible(m)) continue;
    mbox.setFromObject(m);
    const lb = boxes.filter(([, b]) => mbox.intersectsBox(b)), lc = cyls.filter(([, c]) => boxCyl(mbox, c, 2)); if (!lb.length && !lc.length) continue;
    const pos = m.geometry.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      vtx.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld); pt.min.copy(vtx); pt.max.copy(vtx);
      for (const [name, b] of lb) if (b.containsPoint(vtx)) hits.add(`手臂×${name}`);
      for (const [name, c] of lc) if (boxCyl(pt, c, 2)) hits.add(`手臂×${name}`);
    }
  }
  for (const id of held) {
    const hc = itemCyl(id);
    if (hc) { hc.y0 += 4; for (const [name, c] of cyls) if (cylCyl(hc, c, 2)) hits.add(`${id}×${name}`); }
    // 逐個網格的包圍盒（移液器細長，整體包圍盒太粗）；底面放在架上／秤盤上屬正常接觸
    lab.items[id].traverse(m => {
      if (!m.isMesh || m.geometry.type === 'PlaneGeometry') return;
      const hb = new THREE.Box3().setFromObject(m); hb.min.y += 4;
      for (const [name, b] of boxes) if (hb.intersectsBox(b) && name !== id) hits.add(`${id}×${name}`);
      if (!hc) for (const [name, c] of cyls) if (boxCyl(hb, c, 1)) hits.add(`${id}×${name}`);
    });
  }
  return [...hits];
}
let checks = 0;
for (const st of plan.steps) {
  const fr = st.kind === 'wait' ? [0.5] : [0.02, 0.35, 0.65, 0.98];
  for (const f of fr) {
    const T = st.start + st.dur * f, info = sim.apply(T); scene.updateMatrixWorld(true); checks++;
    const hit = collisions(T, st, info.state); if (hit.length) fail('collision', { t: +T.toFixed(2), label: st.label, hit });
    for (const n of JOINTS) { const v = robot.q[n] / D2R, [lo, hi] = robot.limits[n]; if (v < lo - 1e-6 || v > hi + 1e-6) fail('limit', { t: T, label: st.label, joint: n, v }); }
    if (st.kind === 'lin') { const e = robot.error(); if (e.position > 0.5 || e.angle > 0.5) fail('linear', { t: T, label: st.label, ...e }); }
  }
}

// ---------------------------------------------------------------- 3. 連續性：以 20 ms 取樣，關節速度不超過上限 × 1.05，器皿交接不跳位
let prevQ = null, prevT = 0, maxRatio = 0, worstJ = '';
for (const st of plan.steps) {
  if (st.kind === 'wait') { prevQ = null; continue; }
  for (let T = st.start; T <= st.start + st.dur + 1e-9; T += 0.02) {
    const f = plan.sample(T); robot.setPose(f.pose); robot.snap();
    const q = { ...robot.q };
    if (prevQ && T - prevT > 1e-6) for (const n of JOINTS) { const r = Math.abs(q[n] - prevQ[n]) / (T - prevT) / robot.JOINT_SPEED[n]; if (r > maxRatio) { maxRatio = r; worstJ = `${st.label} ${n}`; } }
    prevQ = q; prevT = T;
  }
}
if (maxRatio > 1.05) fail('speed', { maxRatio, worstJ });
const _p = new THREE.Vector3();
function itemPositions(T) { sim.apply(T); scene.updateMatrixWorld(true); const o = {}; for (const id in lab.items) if (lab.items[id].visible) o[id] = lab.items[id].getWorldPosition(_p).toArray(); return o; }
let maxJump = 0, jumpAt = '';
for (let n = 1; n < plan.steps.length; n++) {
  const T = plan.steps[n].start, a = itemPositions(T - 1e-4), b = itemPositions(T + 1e-4);
  for (const id in a) if (b[id]) { const d = Math.hypot(a[id][0] - b[id][0], a[id][1] - b[id][1], a[id][2] - b[id][2]); if (d > maxJump) { maxJump = d; jumpAt = `${plan.steps[n].label} ${id}`; } if (d > 1) fail('jump', { t: T, label: plan.steps[n].label, id, d }); }
}

// ---------------------------------------------------------------- 4. 流程邏輯
const end = plan.sample(plan.total).state;
const jobs = plan.jobs;
assert.equal(jobs.length, 12, '12 titrations');
for (const [k, j] of jobs.entries()) {
  const r = end.rec[j.k];
  assert.ok(r.tare > 90 && r.net > 19 && r.net < 21, `job ${j.k} weighed`);
  assert.ok(j.start > j.placeT && Math.abs(j.end - j.start - TIME.titrate) < 1e-6, `job ${j.k} titration after placing`);
  if (k) assert.ok(j.rotStart >= jobs[k - 1].rinseEnd - 1e-9, `job ${j.k} sequential titration`);
  assert.ok(j.removeT > j.rinseEnd, `job ${j.k} removed after analysis`);
  // 滴定開始時該杯在滴定頭正下方
  assert.equal(plan.towerSlotAt(j.start), j.slot, `job ${j.k} under titration head`);
  const a = plan.sampler(j.start + 1).angle + j.slot * 2 * Math.PI / 12; assert.ok(Math.abs(Math.atan2(Math.sin(a), Math.cos(a))) < 1e-6, `job ${j.k} aligned`);
  const loc = end.loc[`beaker${j.beaker}`]; assert.ok(loc.w && Math.abs(loc.w[2] - ST.doneRack.rows[0]) < 400 && loc.w[0] > 100, `beaker ${j.beaker} in done rack`);
}
SAMPLES.forEach((S, i) => {
  const b = end.loc[`bottle${i}`], c = end.loc[`cap${i}`];
  assert.ok(b.w && Math.abs(b.w[0] - ST.doneBottleRack.cols[S.doneSlot]) < 1, `bottle ${i} in done rack`);
  assert.equal(c.on, `bottle${i}`, `bottle ${i} recapped`); assert.ok(Math.abs(c.off[1] - (plan.sample(0).state.loc[`cap${i}`].off[1])) < 0.2, `bottle ${i} cap fully screwed`);
  assert.ok(Math.abs(end.vol[`bottle${i}`] - (S.size === 500 ? 400 : 90) + 52) < 1e-6, `bottle ${i} used 52 mL`);
});
for (let t = 0; t < 12; t++) assert.equal(!!end.loc[`tip${t}`].gone, t < 6, `tip ${t}`);
assert.ok(end.loc.pip.w, 'pipette back in dock'); assert.equal(end.door, 0, 'balance door closed'); assert.ok(end.clampGap > 140, 'clamp open');
// 秤重時天平門關著、杯子在秤盤上
for (const st of plan.steps.filter(s => s.label.startsWith('天平穩定中'))) { const s = JSON.parse(st.s0); assert.equal(s.door, 0, 'door closed while weighing'); assert.ok(s.balPan > 90, 'beaker on pan'); }
// 進樣器互鎖：手臂在進樣器區時轉盤不轉；放杯位置離滴定頭 ≥ 90°
for (const st of plan.steps.filter(s => s.zone === 'sampler')) for (const r of plan.rots) if (r.t0 < st.start + st.dur && r.t1 > st.start) fail('interlock', { t: st.start, label: st.label });
for (const j of jobs) assert.ok(plan.slotDist(j.slot, plan.towerSlotAt(j.placeT - 1)) >= 3, `job ${j.k} placed away from head`);
// 倒退／跳站一致
for (const T of [0, 95.3, 700, 1800.7, 3000, plan.total - 5]) {
  const a = JSON.stringify(plan.sample(T).state); sim.apply(T); const qa = JSON.stringify(robot.q);
  sim.apply(plan.total); sim.apply(0); sim.apply(T * 0.37);
  assert.equal(JSON.stringify(plan.sample(T).state), a, 'history-independent state'); sim.apply(T); assert.equal(JSON.stringify(robot.q), qa, 'history-independent joints');
}

const report = {
  mode: 'SIMULATION', total: +plan.total.toFixed(1), totalMin: +(plan.total / 60).toFixed(1), prepEndMin: +(plan.stats.prepEnd / 60).toFixed(1),
  steps: plan.steps.length, checks, robotBusyMin: +(plan.stats.robotBusy / 60).toFixed(1),
  titrations: jobs.map(j => ({ k: j.k + 1, sample: j.sample + 1, rep: j.rep + 1, slot: j.slot + 1, placeMin: +(j.placeT / 60).toFixed(2), startMin: +(j.start / 60).toFixed(2), endMin: +(j.end / 60).toFixed(2), removeMin: +(j.removeT / 60).toFixed(2), netG: +j.net.toFixed(4), veqMl: +j.veq.toFixed(3), resultPct: +j.result.toFixed(4) })),
  rackMoves: plan.rots.filter(r => r.kind === 'move').length,
  maxReachErrMm: +maxReach.toFixed(4), worstReach, maxJointSpeedRatio: +maxRatio.toFixed(3), worstJ, maxItemJumpMm: +maxJump.toFixed(3), jumpAt,
  failures: failures.count || 0, failureSamples: failures, seconds: (Date.now() - t0) / 1000,
};
writeFileSync(new URL('../review/verification.json', import.meta.url), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ ...report, titrations: undefined }, null, 2));
if (failures.length) { console.error('FAILED'); process.exit(1); }
console.log('ALL CHECKS PASSED');
