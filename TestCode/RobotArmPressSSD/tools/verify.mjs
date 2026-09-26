// 驗證（每個配方 × 壓墊選擇 × OK／NG 示意）：全部步驟可達性（PTP 檢查終點）、狀態一致性、倒退／跳站一致性、
// 壓合力上限、手臂對固定結構與產品的碰撞（接觸與接近步驟只允許壓頭進入產品包絡），結束時的接頭狀態，以及連續播放。
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { createStation } from '../web/js/station.js';
import { createSequence, SPEC } from '../web/js/sequence.js';
import { RECIPES } from '../web/js/recipes.js';
globalThis.document = { createElement: () => ({ width: 1024, height: 512, getContext: () => ({ fillRect() {}, fillText() {} }) }) };
const failures = [], report = [];
const cases = [];
for (const [key, recipe] of Object.entries(RECIPES)) {
  // 標準壓墊 OK／NG，有整排接頭的機種另驗單點逐顆（比較用）
  cases.push([key, recipe.insert, false], [key, recipe.insert, true]);
  if (recipe.multiPad) cases.push([key, 'single', false]);
}
for (const [key, insert, ngHold] of cases) {
  const recipe = RECIPES[key], mode = `${key}/${insert}${ngHold ? '/NG' : ''}`;
  const scene = new THREE.Scene(), st = createStation(scene, recipe, insert); st.opts.ngHold = ngHold;
  const { robot, cell, product } = st, seq = createSequence({ robot, product, apply: st.apply, recipe, insert });
  const visible = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
  const meshes = []; robot.root.traverse(o => { if (o.isMesh && !o.material.transparent && visible(o)) meshes.push(o); });
  const vtx = new THREE.Vector3(), mbox = new THREE.Box3();
  function collisions(contact) {
    const fixed = cell.keepout.map(m => [m.name, new THREE.Box3().setFromObject(m).expandByScalar(10)]);
    const prod = st.productBoxes(3).map(b => ['產品', b]), hits = new Set();
    for (const m of meshes) {
      mbox.setFromObject(m);
      const list = [...fixed, ...(contact && m.userData.contact ? [] : prod)].filter(([, b]) => mbox.intersectsBox(b));
      if (!list.length) continue;
      const pos = m.geometry.attributes.position;
      for (const [name, b] of list) for (let i = 0; i < pos.count; i++) { vtx.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld); if (b.containsPoint(vtx)) { hits.add(name); break; } }
    }
    return [...hits];
  }
  let maxError = 0, worst = '', maxForce = 0;
  for (const step of seq.steps) for (const frac of [.001, .5, .999]) {
    const time = step.start + step.dur * frac, { state: s } = seq.sample(time);
    robot.snap();
    const e = step.ptp ? robot.reach(step.pose1) : robot.error();
    if (e.position > maxError) { maxError = e.position; worst = step.action; }
    if (e.position > 1 || e.angle > 1) failures.push({ mode, action: step.action, frac, ...e });
    maxForce = Math.max(maxForce, st.state.force);
    if (st.state.force > SPEC.forceLimit) failures.push({ mode, action: step.action, frac, force: st.state.force });
    if (s.lift > 0) assert(s.located && s.stop > .99 && Math.abs(s.palletX - st.place.x) < 1e-9, 'lift without located pallet');
    const hit = collisions(step.contact || step.near); if (hit.length) failures.push({ mode, action: step.action, frac, collision: hit });
    const before = JSON.stringify(s), target = robot.goal.target.toArray();
    seq.sample(seq.total - 1); seq.sample(0); const after = seq.sample(time).state;
    assert.equal(JSON.stringify(after), before, 'history-dependent machine state'); assert.deepEqual(robot.goal.target.toArray(), target, 'history-dependent TCP goal');
  }
  seq.sample(seq.total);
  const open = product.ids.filter(id => st.state.gap[id] > recipe.gapLimit);
  if (ngHold) assert.deepEqual(open, [recipe.stubborn.id], `${mode}: NG demo should leave only the stubborn connector open`);
  else assert.deepEqual(open, [], `${mode}: all connectors seated at end`);
  const shotSteps = seq.steps.filter(s => s.exposure && s.station === 3).length;
  report.push({ mode, steps: seq.steps.length, cycle: +seq.total.toFixed(2), shots: shotSteps, maxError: +maxError.toFixed(4), worst, maxForce: +maxForce.toFixed(1), openAtEnd: open });
  // 連續播放：實際限速＋到位等待，每 0.25 秒做一次碰撞檢查
  let time = 0, elapsed = 0, wait = 0, frame = seq.sample(0), maxContactError = 0, iteration = 0; robot.snap();
  const dt = .01;
  while (time < seq.total && elapsed < seq.total * 4) {
    const e = robot.error(), s = frame.step, end = s.start + s.dur;
    const blocked = (time >= end - 1e-7 || (s.contact && e.position > 2)) && (e.position > 1 || e.angle > 1);
    if (blocked) { wait += dt; if (wait > 8) { failures.push({ mode, continuous: true, action: s.action, time, ...e }); break; } }
    else { wait = 0; time = time >= end - 1e-7 ? Math.min(seq.total, end + 1e-6) : Math.min(end, time + dt); frame = seq.sample(time >= end - 1e-7 && time <= end ? Math.max(s.start, end - 1e-8) : time); }
    robot.update(dt); elapsed += dt;
    if (s.contact) maxContactError = Math.max(maxContactError, e.position);
    if (++iteration % 25 === 0) { const hit = collisions(s.contact || s.near); if (hit.length) failures.push({ mode, continuous: true, action: s.action, time, collision: hit }); }
  }
  report.push({ mode, continuous: true, time: +time.toFixed(2), elapsed: +elapsed.toFixed(2), maxContactError: +maxContactError.toFixed(3) });
  if (time < seq.total && !failures.some(f => f.continuous && f.mode === mode)) failures.push({ mode, continuous: true, time, reason: 'did not finish' });
}
console.log(JSON.stringify({ report, failures }, null, 2));
if (failures.length) process.exitCode = 1;
