// 驗證（每個機種配方）：節拍、每孔各放一次、取放配對、供料只取正面且在盤上的銅片、雙龍門不相撞、吸嘴移位時在安全高度、
// 放下瞬間銅片中心與角度等於目標、精度 ≤ ±6 mil、S1／S3 涵蓋全部孔、取樣與歷史無關，以及整台場景可套用。
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { buildPlan } from '../web/js/plan.js';
import { createSim } from '../web/js/sim.js';
import { LAYOUT, PRODUCT, RECIPES, setRecipe, COIN_SEAT_TOP } from '../web/js/layout.js';
globalThis.document = { createElement: () => ({ width: 1024, height: 512, getContext: () => ({ fillRect() {}, fillText() {} }) }) };
const failures = [], reports = [];
for (const recipe of Object.keys(RECIPES)) {
setRecipe(recipe);
const fail = (what, data = {}) => failures.push({ recipe, what, ...data });
const plan = buildPlan(), G = LAYOUT.gantry, TIP_R = PRODUCT.nozzleR, N = plan.holes.length;
const report = { recipe, holes: N, cycle: +plan.cycle.toFixed(2), s2End: +plan.s2End.toFixed(2), tripsA: plan.heads.A.trips.length, tripsB: plan.heads.B.trips.length, maxErr: +plan.stats.maxErr.toFixed(4), meanErr: +plan.stats.meanErr.toFixed(4) };
if (plan.cycle > 60) fail('cycle over 60 s', { cycle: plan.cycle });
// 放置：每孔一次、在基準點與頂升之後
const placeEv = plan.log.filter(e => e.type === 'place');
if (placeEv.length !== N) fail('place count', { n: placeEv.length });
if (new Set(placeEv.map(e => e.hole)).size !== N) fail('duplicate placement');
for (const H of ['A', 'B']) {
  const fidT = Math.max(...plan.log.filter(e => e.type === 'fid' && e.H === H).map(e => e.t));
  for (const e of placeEv.filter(e => e.H === H)) if (e.t < fidT || e.t < 2.7 || e.t > plan.cycle) fail('place timing', { H, t: e.t });
  // 取放配對、供料
  const h = plan.heads[H];
  h.hold.forEach((list, k) => { let last = -1; for (const x of list) { if (!(x.t1 > x.t0)) fail('unplaced pick', { H, k }); if (x.t0 < last) fail('nozzle double hold', { H, k }); last = x.t1; const c = x.coin; if (!c.good || c.t0 > x.t0 + 1e-9) fail('bad pick', { H, id: c.id }); } });
  // 吸嘴 XY 移位時的高度
  for (const s of h.tr.steps) {
    const moves = Math.abs(s.end.x - s.initial.x) > 1e-6 || Math.abs(s.end.nz - s.initial.nz) > 1e-6;
    if (moves) for (let k = 0; k < 4; k++) if (Math.min(s.initial[`y${k}`], s.end[`y${k}`]) < LAYOUT.safeTip - 1e-6) fail('nozzle low while moving', { H, t: s.start, label: s.action });
    if (Math.abs(s.end.x) > G.railX - 90 || Math.abs(s.end.nz) > 470) fail('head out of travel', { H, t: s.start });
  }
}
// 放下瞬間：銅片中心＝孔目標、角度＝孔角度＋誤差；吸嘴尖不碰孔邊
for (const hole of plan.holes) {
  const { H, k } = hole.by, s = plan.heads[H].tr.sample(hole.placeT - 1e-9), hold = plan.heads[H].hold[k].find(x => x.hole === hole.id), o = hold.coin.pickOffset;
  const a = s[`t${k}`] * Math.PI / 180, cx = s.x + G.nozzleDX[k] + o.dx * Math.cos(a) + o.dz * Math.sin(a), cz = s.nz - o.dx * Math.sin(a) + o.dz * Math.cos(a);
  const dx = cx - (hole.ax + hole.ex), dz = cz - (hole.az + hole.ez), dth = s[`t${k}`] + o.dt - (hole.angle + hole.et);
  if (Math.hypot(dx, dz) > 1e-6 || Math.abs(dth) > 1e-6) fail('coin not at target at release', { hole: hole.id, dx, dz, dth });
  if (Math.abs(s[`y${k}`] - COIN_SEAT_TOP) > 1e-6) fail('release height', { hole: hole.id });
  if (hole.err > PRODUCT.spec) fail('placement error over spec', { hole: hole.id, err: hole.err });
  if (Math.hypot(o.dx, o.dz) + TIP_R > PRODUCT.hole.w / 2) fail('nozzle tip may touch hole edge', { hole: hole.id });
  if (!Number.isFinite(hole.mapT) || !Number.isFinite(hole.inspT)) fail('scan coverage', { hole: hole.id });
}
// 雙龍門橫樑間距
let minGap = Infinity, gapT = 0;
for (let T = 0; T <= plan.cycle; T += 0.005) {
  const a = plan.heads.A.tr.sample(T).nz + G.overhang, b = plan.heads.B.tr.sample(T).nz - G.overhang, gap = a - b;
  if (gap < minGap) { minGap = gap; gapT = T; }
}
report.minBeamGap = +minGap.toFixed(1); report.minBeamGapAt = +gapT.toFixed(2);
if (minGap < G.minBeamGap) fail('beam collision risk', { minGap, at: gapT });
// 取樣與歷史無關
const probe = [3.1, 17.4, 40.2];
const snap = () => probe.map(T => JSON.stringify(['A', 'B'].map(H => plan.heads[H].tr.sample(T))));
const s1 = snap(); plan.heads.A.tr.sample(plan.cycle); plan.heads.B.tr.sample(0); assert.deepEqual(snap(), s1);
// 標準事件介面：時間遞增且不重複、在節拍內；各軌在節拍終點收尾；五站都有開始時間
const evs = plan.events;
if (!evs.length || evs.some((e, i) => !(e.time >= 0 && e.time <= plan.total && e.dur >= 0 && e.label && (i === 0 || e.time > evs[i - 1].time + 1e-6)))) fail('events shape');
if (plan.total !== plan.cycle || Math.abs(plan.timeline.total - plan.cycle) > 1e-9) fail('timeline total', { total: plan.timeline.total, cycle: plan.cycle });
if (plan.stationStart.length !== 5 || plan.stationStart.some(t => !(t >= 0 && t < plan.cycle))) fail('stationStart', { stationStart: plan.stationStart });
report.events = evs.length; report.stationStart = plan.stationStart.map(t => +t.toFixed(2));
// 整台場景可套用
const scene = new THREE.Scene(), sim = createSim(scene);
let last = null;
for (let T = 0; T <= sim.plan.cycle; T += 0.25) last = sim.apply(T);
last = sim.apply(sim.plan.cycle);
if (last.placed.A + last.placed.B !== N || last.inspected !== N || last.mapped !== N) fail('end state', last);
report.endState = { placed: last.placed, mapped: last.mapped, inspected: last.inspected };
reports.push(report);
}
console.log(JSON.stringify({ reports, failures: failures.slice(0, 30), failureCount: failures.length }, null, 2));
if (failures.length) process.exitCode = 1;
