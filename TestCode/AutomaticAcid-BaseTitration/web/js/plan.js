// 排程：手臂動作序列（逐步計算 PTP 時間）＋ Metrohm 進樣器轉盤／滴定排程＋樣品表與交握訊息
// 每一步存起始狀態快照；sample(T) 只由 T 決定，倒退／跳站結果一致。
import * as THREE from 'three';
import { Y0, ST, BEAKER, BOTTLES, CAP, PIPETTE, TRAVEL, PIP_TRAVEL, TIME, SPEED, RINSE, ALIQUOT, TITRANT, ANALYTE, SAMPLES, rng, gauss, smooth } from './layout.js';

const SP = ST.sampler, SLOT = 2 * Math.PI / SP.slots;
const JOINTS = ['j1', 'j2', 'j3', 'j4', 'j5', 'j6'];
const pureJ = c => c && Object.fromEntries(JOINTS.map(n => [n, c[n]]));
const wrapPi = a => { a = (a + Math.PI) % (2 * Math.PI); if (a < 0) a += 2 * Math.PI; return a - Math.PI; };
const mod = (a, n) => ((a % n) + n) % n;

// ---------------------------------------------------------------- 滴定曲線（強酸 × 強鹼，示意）
export function titrationCurve(job) {
  const na = job.conc * job.aliquot / 1000, v0 = job.aliquot + job.waterMl, cb = TITRANT.c, Kw = 1e-14;
  return v => { const vt = (v0 + v) / 1000, d = (na - cb * v / 1000) / vt, h = (d + Math.sqrt(d * d + 4 * Kw)) / 2; return -Math.log10(h); };
}
// 滴定進度（DET 動態加液：遠離終點快、接近終點慢）
export function dosedVolume(job, T) {
  const t0 = job.start + 35, t1 = job.end - 20, veq = job.veq, vEnd = Math.min(TITRANT.buret, veq * 1.3);
  if (T <= t0) return 0; if (T >= t1) return vEnd;
  const u = (T - t0) / (t1 - t0);
  if (u < 0.35) return 0.9 * veq * u / 0.35;
  if (u < 0.8) return 0.9 * veq + 0.2 * veq * (u - 0.35) / 0.45;
  return 1.1 * veq + (vEnd - 1.1 * veq) * (u - 0.8) / 0.2;
}

export function buildPlan(robot) {
  const R = rng(828);
  // ---------------------------------------------------------------- 初始狀態
  const s = {
    loc: {}, vol: {}, tipVol: {}, door: 0, clampGap: 150, grip: 90,
    balPan: 0, balTare: 0, balStable: true, balJit: 0,
    rec: Array.from({ length: 12 }, () => ({})), bottle: SAMPLES.map(() => ({ stage: '待驗' })),
    sig: {}, scanning: false, act: '待命',
  };
  const W = (x, y, z) => [x, Y0 + y, z];
  const sampleRackPos = i => { const S = SAMPLES[i]; return W(ST.sampleRack.cols[S.rackSlot], ST.sampleRack.base, ST.sampleRack.rows[S.size]); };
  const doneBottlePos = i => { const S = SAMPLES[i]; return W(ST.doneBottleRack.cols[S.doneSlot], ST.doneBottleRack.base, ST.doneBottleRack.rows[S.size]); };
  const emptyPos = k => W(ST.emptyRack.cols[k % 3], ST.emptyRack.base, ST.emptyRack.rows[Math.floor(k / 3)]);
  const donePos = n => W(ST.doneRack.cols[n % 3], ST.doneRack.base, ST.doneRack.rows[Math.floor(n / 3)]);
  const tipPos = t => W(ST.tipRack.x0 + (t % ST.tipRack.n) * ST.tipRack.pitch, ST.tipRack.top, ST.tipRack.z[Math.floor(t / ST.tipRack.n)]);
  const clampPos = W(ST.clamp.x, ST.clamp.base, ST.clamp.z), holderPos = W(ST.holder.x, ST.holder.base, ST.holder.z), panPos = W(ST.balance.x, ST.balance.pan, ST.balance.z);
  const dockPos = W(ST.dock.x, ST.dock.collar - PIPETTE.collar, ST.dock.z);
  SAMPLES.forEach((S, i) => {
    s.loc[`bottle${i}`] = { w: sampleRackPos(i), yaw: 0 };
    s.loc[`cap${i}`] = { on: `bottle${i}`, off: [0, BOTTLES[S.size].h + BOTTLES[S.size].neckH - CAP.h + 4, 0], yaw: 0 };
    s.vol[`bottle${i}`] = BOTTLES[S.size].fill;
  });
  for (let t = 0; t < 12; t++) s.loc[`tip${t}`] = { w: tipPos(t), yaw: 0 };
  const beakerMass = [];
  for (let k = 0; k < 12; k++) { s.loc[`beaker${k}`] = { w: emptyPos(k), yaw: 0 }; s.vol[`beaker${k}`] = 0; beakerMass.push(BEAKER.mass + gauss(R) * 0.6); }
  s.loc.pip = { w: dockPos, yaw: 0 };

  // ---------------------------------------------------------------- 轉盤與滴定排程（隨手臂放杯逐步決定）
  const TQ = { rots: [], jobs: [] };
  function rackAngleAt(time) {
    let a = 0;
    for (const r of TQ.rots) { if (time < r.t0) break; a = time >= r.t1 ? r.a1 : THREE.MathUtils.lerp(r.a0, r.a1, smooth((time - r.t0) / (r.t1 - r.t0))); }
    return a;
  }
  const lastRotEnd = () => TQ.rots.length ? TQ.rots.at(-1).t1 : 0;
  const towerSlotAt = time => mod(Math.round(-rackAngleAt(time) / SLOT), SP.slots);
  const slotDist = (a, b) => { const d = mod(a - b, SP.slots); return Math.min(d, SP.slots - d); };
  function slotWorld(slot, time) { const a = rackAngleAt(time) + slot * SLOT; return { p: [SP.x + Math.cos(a) * SP.r, Y0 + SP.plate, SP.z - Math.sin(a) * SP.r], a }; }
  const msgs = [];                                       // 交握／通訊紀錄 { t, from, to, text }
  const say = (t, from, to, text) => msgs.push({ t, from, to, text });
  function addRotation(t0, toAngle, kind, job) {
    const a0 = rackAngleAt(t0); let d = wrapPi(toAngle - a0);
    const n = Math.round(Math.abs(d) / SLOT), dur = n ? TIME.rotBase + TIME.rotPerSlot * n : 0;
    if (!dur) return t0;
    TQ.rots.push({ t0, t1: t0 + dur, a0, a1: a0 + d, kind, job });
    return t0 + dur;
  }
  // 手臂放杯後排入滴定：轉盤轉到滴定頭下 → 下降 → 加水、攪拌、滴定 → 上升 → 電極噴洗
  function scheduleJob(job, placeT) {
    const prev = TQ.jobs.at(-1);
    const rotStart = Math.max(placeT + TIME.startDelay, prev ? prev.rinseEnd : 0, lastRotEnd());
    const rotEnd = addRotation(rotStart, -job.slot * SLOT, 'titration', job.k);
    Object.assign(job, { rotStart, rotEnd, start: rotEnd + TIME.lower, placeT });
    job.end = job.start + TIME.titrate; job.liftEnd = job.end + TIME.lift; job.rinseEnd = job.liftEnd + TIME.rinse;
    TQ.jobs.push(job);
    say(placeT, '整合軟體', 'Metrohm', `樣品表第 ${job.k + 1} 列：位置 ${job.slot + 1}、淨重 ${job.net.toFixed(4)} g → 啟動`);
    say(rotStart, 'Metrohm', '—', `轉盤轉到位置 ${job.slot + 1}`);
    say(job.start, 'Metrohm', '整合軟體', `滴定中：樣品 ${job.sample + 1}-${job.rep + 1}`);
    say(job.end, 'Metrohm', '整合軟體', `分析完成：樣品 ${job.sample + 1}-${job.rep + 1}，${job.result.toFixed(3)} %`);
  }

  // ---------------------------------------------------------------- 手臂動作建構
  const steps = [], events = [];
  const B = { t: 0, pose: null, j: null };
  const jawVec = a => new THREE.Vector3(Math.sin(a), 0, Math.cos(a));   // 夾爪沿 (cos a, 0, −sin a) 開合
  function P(x, y, z, a = 0, sym = true) {
    // 對稱夾持（圓形器皿、移液模組）：a 與 a+π 等價，取相對手臂徑向在 ±90° 內者，J6 不會越轉越多
    if (sym) { const phi = Math.atan2(-(z - ST.robot.z), x - ST.robot.x), rel = wrapPi(a - phi); a = phi + (rel > Math.PI / 2 ? rel - Math.PI : rel <= -Math.PI / 2 ? rel + Math.PI : rel); }
    const p = robot.poseFor('grip', new THREE.Vector3(x, y, z), jawVec(a)); p.m = { x, y, z, a }; return p;
  }
  const at = (y, dx = 0, dz = 0) => P(B.pose.m.x + dx, y, B.pose.m.z + dz, B.pose.m.a, false);
  function add(st) {
    st.start = B.t; st.s0 = JSON.stringify(s); st.act = s.act; steps.push(st);
    B.t += st.dur; if (st.fx) st.fx(s, 1); B.pose = st.p1; B.j = pureJ(robot.solveJoints(st.p1));
  }
  function go(p1, label, o = {}) {
    robot.solveJoints(p1, B.j);
    const dur = Math.max(o.min ?? 0.4, robot.ptpTime(B.pose, p1));
    add({ kind: 'ptp', p0: B.pose, p1, dur, label, ...o });
  }
  function lin(p1, label, o = {}) {
    robot.solveJoints(p1, B.j);
    const dist = p1.target.distanceTo(B.pose.target), dur = Math.max(o.min ?? 0.3, 1.875 * dist / (o.v || SPEED.lin), robot.ptpTime(B.pose, p1));
    add({ kind: 'lin', p0: B.pose, p1, dur, label, ...o });
  }
  // 垂直接近／離開：遠段快速、靠近工件的最後 SPEED.near 用慢速
  function down(y, label, o = {}) { const y0 = B.pose.m.y; if (y0 - y > SPEED.near + 20) lin(at(y + SPEED.near), label, { ...o, v: SPEED.fast }); lin(at(y), label, o); }
  function up(y, label, o = {}) { const y0 = B.pose.m.y; if (y - y0 > SPEED.near + 20) { lin(at(y0 + SPEED.near), label, o); lin(at(y), label, { ...o, v: SPEED.fast }); } else lin(at(y), label, o); }
  function wait(dur, label, fx, o = {}) { add({ kind: 'wait', p0: B.pose, p1: B.pose, dur, label, fx, ...o }); }
  function grip(w, label, o = {}) { const w0 = s.grip; wait(TIME.grip, label, (st, e) => { st.grip = THREE.MathUtils.lerp(w0, w, e); }, o); }
  const act = text => { s.act = text; };
  const ev = (label, o = {}) => events.push({ t: B.t, label, ...o });
  const setSig = (k, v) => { s.sig[k] = v; };
  // 手上物件：以 TCP 座標系記錄相對位置（放開時換回世界座標）
  function itemWorld(id) {
    const L = s.loc[id];
    if (L.w) return { p: new THREE.Vector3(...L.w), q: new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), L.yaw || 0) };
    if (L.on) { const par = itemWorld(L.on); return { p: par.p.clone().add(new THREE.Vector3(...L.off).applyQuaternion(par.q)), q: par.q.clone().multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), L.yaw || 0)) }; }
    if (L.as !== undefined) { const w = slotWorld(L.as, B.t); return { p: new THREE.Vector3(...w.p), q: new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), w.a + (L.yaw || 0)) }; }
    const tq = B.pose.rotation; return { p: B.pose.target.clone().add(new THREE.Vector3(...L.g).applyQuaternion(tq)), q: tq.clone().multiply(new THREE.Quaternion(...L.q)) };
  }
  function attach(id) {
    const w = itemWorld(id), inv = B.pose.rotation.clone().invert();
    s.loc[id] = { g: w.p.sub(B.pose.target).applyQuaternion(inv).toArray(), q: inv.multiply(w.q).toArray() };
  }
  const yawOf = q => { const v = new THREE.Vector3(1, 0, 0).applyQuaternion(q); return Math.atan2(-v.z, v.x); };
  function detach(id, loc) {
    const w = itemWorld(id);
    if (loc && loc.as !== undefined && loc.yaw === undefined) loc.yaw = wrapPi(yawOf(w.q) - slotWorld(loc.as, B.t).a);
    s.loc[id] = loc || { w: w.p.toArray(), yaw: yawOf(w.q) };
  }
  // 暫存／還原（進樣器區需避開轉盤轉動時重排）
  const mark = () => ({ n: steps.length, t: B.t, pose: B.pose, j: B.j, s: JSON.stringify(s), ev: events.length });
  function rollback(m) { steps.length = m.n; B.t = m.t; B.pose = m.pose; B.j = m.j; const o = JSON.parse(m.s); for (const k of Object.keys(s)) delete s[k]; Object.assign(s, o); events.length = m.ev; }

  // 高度（TCP y，世界座標）
  const Y_EMPTY = Y0 + 440, Y_BEAKER = Y0 + TRAVEL + BEAKER.h / 2, Y_PIP = Y0 + PIP_TRAVEL + PIPETTE.tipEnd;
  const yBottle = i => Y0 + TRAVEL + BOTTLES[SAMPLES[i].size].grip;

  // 起始位姿：前右方待命
  const HOME = { x: 280, z: 260 };
  B.pose = P(HOME.x, Y_EMPTY, HOME.z, 0, false); B.j = pureJ(robot.solveJoints(B.pose));
  const goHome = label => go(P(HOME.x, Y_EMPTY, HOME.z, 0), label);

  // 一般取放：上方 → 直線下降 → 夾／放 → 直線上升
  function pick(id, x, yGrip, z, a, wOpen, wClose, yUp, labels, o = {}) {
    const yFrom = B.pose.m.y, w0 = s.grip;
    go(P(x, yFrom, z, a, o.sym !== false), labels[0], { fx: (st, e) => { st.grip = THREE.MathUtils.lerp(w0, wOpen, Math.min(1, e * 2)); }, ...o.stepOpts });
    down(yGrip, labels[1], { touch: [id, ...(o.touch || [])], ...o.stepOpts });
    grip(wClose, labels[2], { touch: [id, ...(o.touch || [])], ...o.stepOpts }); attach(id);
    o.onGrip?.();
    up(yUp, labels[3], { touch: [id, ...(o.touch || [])], ...o.stepOpts });
  }
  function place(id, x, yGrip, z, a, wOpen, loc, yUp, labels, o = {}) {
    go(P(x, B.pose.m.y, z, a, o.sym !== false), labels[0], o.stepOpts);
    down(yGrip, labels[1], { touch: [id, ...(o.touch || [])], ...o.stepOpts });
    detach(id, loc); o.onRelease?.();
    grip(wOpen, labels[2], { touch: [id, ...(o.touch || [])], ...o.stepOpts });
    up(yUp, labels[3], { touch: [id, ...(o.touch || [])], ...o.stepOpts });
  }

  // ---------------------------------------------------------------- 天平
  const BAL = ST.balance, Y_TAB = Y0 + BAL.chamber.y[1] + 21 + 15;       // 指尖在推把中段
  const A_BAL = Math.PI / 2;                                              // 夾爪沿 Z 開合（防風罩開口 250 × 230）
  function doorMove(open) {
    // 開門：指尖在推把 +X 側往 −X 推；關門：指尖在推把 −X 側往 +X 拉（推把厚 8、手指寬 28、間隙 3）
    const tabX = open ? BAL.tab : BAL.tab - BAL.doorTravel, side = open ? 1 : -1;
    const x0 = tabX + side * (4 + 14 + 3), xEnd = x0 - side * BAL.doorTravel;
    const w0 = s.grip;
    go(P(x0, Y_TAB + 60, BAL.z, A_BAL), open ? '移到天平推把' : '移到推把後方', { fx: (st, e) => { st.grip = THREE.MathUtils.lerp(w0, 0, Math.min(1, e * 2)); } });
    lin(at(Y_TAB), '指尖下降到推把旁', { touch: ['balance-door'] });
    const d0 = s.door, d1 = open ? 1 : 0;
    lin(P(xEnd, Y_TAB, BAL.z, B.pose.m.a, false), open ? '推開天平上門' : '拉回關閉天平上門', { v: SPEED.push, touch: ['balance-door'], fx: (st, e) => { st.door = THREE.MathUtils.lerp(d0, d1, smooth(e)); st.sig.door = e > 0.02 || d1 > 0; } });
    s.door = d1; setSig('door', open);
    up(Y_EMPTY, '離開推把', { touch: ['balance-door'] });
  }
  function weigh(label, fxDone) {
    const pan = s.balPan, tare = s.balTare;
    wait(TIME.settle, label, (st, e) => { st.balJit = e < 0.75 ? 0.004 * Math.sin(e * 40) * (1 - e) : 0; st.balStable = e >= 0.75; st.sig.stable = e >= 0.75; });
    s.balJit = 0; s.balStable = true; setSig('stable', true); fxDone?.(pan, tare);
  }
  const balanceIn = (id, mass, labelPrefix, extraTouch = []) => {
    place(id, panPos[0], panPos[1] + BEAKER.h / 2, panPos[2], A_BAL, 90, null, Y_EMPTY, [`${labelPrefix}：移到天平上方`, '直線下降進防風罩', '放上秤盤', '直線上升離開防風罩'],
      { touch: ['balance-pan', ...extraTouch], onRelease: () => { s.balPan = mass; s.balStable = false; setSig('stable', false); } });
  };
  const balanceOut = (id, yUp, label) => {
    pick(id, panPos[0], panPos[1] + BEAKER.h / 2, panPos[2], A_BAL, 90, BEAKER.d - 2, yUp, [`${label}：移到天平上方`, '直線下降進防風罩', '夾取滴定杯', '直線上升離開防風罩'],
      { touch: ['balance-pan'], onGrip: () => { s.balPan = 0; s.balStable = false; } });
  };

  // ---------------------------------------------------------------- 開蓋／關蓋（手臂自行旋轉，棘輪式重夾）
  const TWIST = 2 * Math.PI / 3, TURNS = 5, A_CAP = Math.PI / 2;                                // 每次 120°，5 次 = 1.67 圈（GL45 約 1.5 圈脫牙）
  function capTwist(i, loosen) {
    const bottle = BOTTLES[SAMPLES[i].size], capId = `cap${i}`, lift = CAP.pitch / 3;
    const capBase = clampPos[1] + bottle.h + bottle.neckH - CAP.h + 4;
    const a0 = B.pose.m.a, x = clampPos[0], z = clampPos[2];
    for (let n = 0; n < TURNS; n++) {
      const cy = capBase + CAP.h / 2 + (loosen ? n * lift : (TURNS - n) * lift);
      const dy = loosen ? lift : -lift, dir = loosen ? 1 : -1;
      if (n > 0 || !loosen) { lin(P(x, cy, z, a0, false), '下降夾住瓶蓋', { touch: [capId, `bottle${i}`] }); grip(CAP.d - 2, '夾緊瓶蓋', { touch: [capId, `bottle${i}`] }); }
      attach(capId);
      go(P(x, cy + dy, z, a0 + dir * TWIST, false), `${loosen ? '逆時針' : '順時針'}旋轉 120°（${n + 1}/${TURNS}）`, { touch: [capId, `bottle${i}`], min: 0.8, sig: 'twist' });
      if (n === TURNS - 1 && loosen) break;                                // 最後一次不放開，直接提起
      const w = itemWorld(capId), bw = itemWorld(`bottle${i}`);
      detach(capId, { on: `bottle${i}`, off: [0, w.p.y - bw.p.y, 0], yaw: yawOf(w.q) - yawOf(bw.q) });
      grip(CAP.d + 16, '放開瓶蓋', { touch: [capId, `bottle${i}`] });
      lin(P(x, cy + dy + 6, z, a0 + dir * TWIST, false), '上移 6 mm', { touch: [capId, `bottle${i}`] });
      go(P(x, cy + dy + 6, z, a0, false), '夾爪轉回', { touch: [capId, `bottle${i}`], min: 0.6 });
    }
  }

  // ---------------------------------------------------------------- 移液模組
  let hasTip = null;
  function pipetteTake() {
    act('取移液模組');
    const w0 = s.grip;
    go(P(dockPos[0], Y_PIP, dockPos[2], 0), '移到移液模組座上方', { fx: (st, e) => { st.grip = THREE.MathUtils.lerp(w0, 70, Math.min(1, e * 2)); } });
    down(Y0 + ST.dock.collar, '直線下降到夾持環', { touch: ['pip', 'dock', 'bench', ...(hasTip ? [hasTip] : [])] });
    grip(38, '夾住移液模組', { touch: ['pip', 'dock', 'bench', ...(hasTip ? [hasTip] : [])] }); attach('pip');
    up(Y_PIP, '提起移液模組', { touch: ['pip', 'dock', 'bench', ...(hasTip ? [hasTip] : [])] });
  }
  function pipetteReturn() {
    act('移液模組放回');
    go(P(dockPos[0], Y_PIP, dockPos[2], 0), '移到移液模組座上方');
    down(Y0 + ST.dock.collar, '直線下降放入停放座', { touch: ['pip', 'dock', 'bench', ...(hasTip ? [hasTip] : [])] });
    detach('pip');
    grip(70, '放開移液模組', { touch: ['pip', 'dock'] });
    up(Y_PIP, '夾爪上移', { touch: ['pip', 'dock'] });
  }
  function tipMount(t) {
    const p = tipPos(t), y = p[1] - PIPETTE.tipSeat + PIPETTE.collar;
    go(P(p[0], Y_PIP, p[2], 0), `移到吸頭架（第 ${t + 1} 支）`);
    down(y + 30, '對準吸頭');
    lin(at(y), '下壓裝上吸頭', { v: SPEED.linSlow, touch: [`tip${t}`, 'tiprack', 'pip'], sig: 'tip' });
    s.loc[`tip${t}`] = { on: 'pip', off: [0, PIPETTE.tipSeat, 0], yaw: 0 }; hasTip = `tip${t}`; setSig('tip', true);
    up(Y_PIP, '提起', { touch: [`tip${t}`, 'tiprack'] });
  }
  // 模組電動退吸頭：吸頭尖端停在廢料口上方 25 mm，退出後落入桌下廢料桶
  function tipEject() {
    const S = ST.tipChute, y = Y0 + 25 + PIPETTE.tipEnd, tipId = hasTip;
    act('退吸頭');
    go(P(S.x, Y_PIP, S.z, 0), '移到吸頭廢料口上方');
    down(y, '下降到退吸頭高度');
    const y0 = itemWorld(tipId).p.y;
    wait(0.8, '模組電動退吸頭', null, { sig: 'eject' });
    detach(tipId); hasTip = null; setSig('tip', false);
    wait(0.35, '吸頭落入廢料口', (st, e) => { st.loc[tipId].w[1] = y0 - 300 * e * e; if (e >= 1) st.loc[tipId].gone = true; }, { touch: [tipId, 'chute', 'bench'] });
    s.loc[tipId].gone = true; s.tipVol[tipId] = 0;
    up(Y_PIP, '上升');
  }
  // 吸液：吸頭尖端在液面下 12 mm（最低離瓶底 8 mm）
  function aspirate(i, ml, label) {
    const b = BOTTLES[SAMPLES[i].size], r = b.d / 2 - 3, level = s.vol[`bottle${i}`] * 1000 / (Math.PI * r * r) * (1 - ml / s.vol[`bottle${i}`] / 2);
    const endY = clampPos[1] + 4 + Math.max(8, level - 12), tcpY = endY + PIPETTE.tipEnd;
    go(P(clampPos[0], Y_PIP, clampPos[2], 0), `移到樣品瓶上方（${label}）`);
    down(tcpY, '吸頭伸入液面下', { touch: [hasTip, 'pip', `bottle${i}`, 'clamp'] });
    const v0 = s.vol[`bottle${i}`], t0 = s.tipVol[hasTip] || 0, tip = hasTip;
    wait(ml / 2.5, `吸 ${ml} mL`, (st, e) => { st.vol[`bottle${i}`] = v0 - ml * e; st.tipVol[tip] = t0 + ml * e; st.sig.pip = e < 1; }, { touch: [tip, 'pip', `bottle${i}`, 'clamp'] });
    wait(0.6, '吸液後停留', null, { touch: [tip, 'pip', `bottle${i}`, 'clamp'] });
    up(Y_PIP, '吸頭退出樣品瓶', { touch: [tip, 'pip', `bottle${i}`, 'clamp'] });
  }
  function dispense(to, ml, label) {
    const tip = hasTip, t0 = s.tipVol[tip];
    if (to === 'waste') {
      const F = ST.funnel, endY = Y0 + F.top - 25;
      go(P(F.x, Y_PIP, F.z, 0), '移到廢液漏斗上方');
      down(endY + PIPETTE.tipEnd, '吸頭伸入漏斗', { touch: [tip, 'funnel'] });
      wait(ml / 3 + TIME.blowout, `吐出潤洗液 ${ml} mL＋吹出`, (st, e) => { st.tipVol[tip] = t0 * (1 - e); st.sig.pip = e < 1; }, { touch: [tip, 'funnel'] });
      up(Y_PIP, '上升', { touch: [tip, 'funnel'] });
    } else {
      const endY = holderPos[1] + 18, k = to, v0 = s.vol[`beaker${k}`];
      go(P(holderPos[0] + 12, Y_PIP, holderPos[2], 0), `移到滴定杯上方（${label}）`);
      down(endY + PIPETTE.tipEnd, '吸頭伸入滴定杯（貼杯壁）', { touch: [tip, 'pip', `beaker${k}`, 'holder'] });
      wait(ml / 3 + TIME.blowout, `吐出 ${ml} mL＋吹出`, (st, e) => { st.tipVol[tip] = t0 * (1 - e); st.vol[`beaker${k}`] = v0 + ml * e; st.sig.pip = e < 1; }, { touch: [tip, 'pip', `beaker${k}`, 'holder'] });
      up(Y_PIP, '吸頭退出滴定杯', { touch: [tip, 'pip', `beaker${k}`, 'holder'] });
    }
  }

  // ---------------------------------------------------------------- 進樣器：放杯／取杯（避開轉盤轉動）
  const STAGE = P(380, Y_BEAKER, 20, 0, false);
  const samplerVisit = (build, labelWait) => {
    for (let guard = 0; guard < 80; guard++) {
      const m = mark(), t0 = B.t, info = build(t0);
      if (info === null) { rollback(m); return null; }
      const hit = TQ.rots.find(r => r.t0 < B.t + 0.5 && r.t1 > t0 - 0.5);
      if (!hit && info.ok !== false) return info;
      rollback(m);
      const until = hit ? hit.t1 + 0.3 : info.retryAt;
      wait(Math.max(0.5, until - B.t), labelWait, null, { idle: true });
    }
    throw new Error('sampler visit: no window');
  };
  function freeSlots() { const used = new Set(TQ.jobs.filter(j => !j.removed).map(j => j.slot)); return [...Array(SP.slots).keys()].filter(x => !used.has(x)); }
  const idleFrom = () => Math.max(lastRotEnd(), TQ.jobs.length ? TQ.jobs.at(-1).rinseEnd : 0);
  function placeInSampler(k, job) {
    go(P(STAGE.m.x, Y_BEAKER, STAGE.m.z, 0), '移到進樣器前待命點');
    return samplerVisit(t0 => {
      const tower = towerSlotAt(t0), cand = freeSlots().filter(x => slotDist(x, tower) >= 3).sort((a, b) => slotDist(b, tower) - slotDist(a, tower) || a - b);
      if (!cand.length) {
        // 可放的空位都在滴定頭附近：等轉盤空閒後把空位轉到手臂側（MOVE 指令）
        const future = TQ.rots.find(r => r.t0 >= t0);
        if (future) return { ok: false, retryAt: future.t1 + 0.3 };
        const t = Math.max(t0, idleFrom()), slot = freeSlots()[0];
        addRotation(t, Math.PI - slot * SLOT, 'move');
        say(t, '整合軟體', 'Metrohm', `轉盤移動：空位 ${slot + 1} 轉到手臂側`);
        return { ok: false, retryAt: lastRotEnd() + 0.3 };
      }
      const slot = cand[0], w = slotWorld(slot, t0);
      job.slot = slot;
      place(`beaker${k}`, w.p[0], w.p[1] + BEAKER.h / 2, w.p[2], w.a, 80, { as: slot }, Y_EMPTY,
        [`放入進樣器位置 ${slot + 1}：移到上方`, '直線下降', '放開', '直線上升'], { sym: true, stepOpts: { zone: 'sampler' } });
      return { ok: true, slot };
    }, '等待轉盤轉動完成');
  }
  function removeFromSampler(job, n) {
    const r = samplerVisit(t0 => {
      if (TQ.rots.some(r => r.t0 <= t0 && r.t1 > t0)) return { ok: false, retryAt: TQ.rots.find(r => r.t0 <= t0 && r.t1 > t0).t1 + 0.3 };
      const w = slotWorld(job.slot, t0);
      pick(`beaker${job.k}`, w.p[0], w.p[1] + BEAKER.h / 2, w.p[2], w.a, 80, BEAKER.d - 2, Y_BEAKER,
        [`進樣器位置 ${job.slot + 1}：移到上方`, '直線下降', '夾取已滴定杯', '直線上升'], { stepOpts: { zone: 'sampler' } });
      go(P(STAGE.m.x, Y_BEAKER, STAGE.m.z, 0), '離開進樣器');
      return { ok: true };
    }, '等待轉盤轉動完成');
    const p = donePos(n);
    place(`beaker${job.k}`, p[0], p[1] + BEAKER.h / 2, p[2], 0, 80, null, Y_EMPTY, ['移到完成滴定杯區', '直線下降', '放開', '直線上升']);
    return r;
  }

  // ================================================================ 流程
  ev('① 初始化：人員掃條碼、整合軟體建立樣品表（6 瓶 × 2 重複）', { phase: 0 });
  say(0, '人員', '整合軟體', '掃描 6 瓶條碼、選方法、按開始');
  say(0, '整合軟體', 'Metrohm', '下載樣品表（12 列，位置待定）');
  wait(3, '整合軟體檢查天平、Metrohm、移液模組連線');
  let beakerNext = 0;
  for (let i = 0; i < SAMPLES.length; i++) {
    const S = SAMPLES[i], b = BOTTLES[S.size], id = `bottle${i}`, rp = sampleRackPos(i);
    // ---- 取樣品瓶 → 讀碼 → 放到樣品瓶座並夾緊
    act(`樣品 ${i + 1}：取瓶讀碼`); ev(`樣品 ${i + 1}：取瓶、讀條碼`, { sample: i, phase: 3 });
    s.bottle[i].stage = '讀碼';
    if (B.pose.m.y < yBottle(i)) lin(at(yBottle(i)), '上升到搬運高度');
    pick(id, rp[0], rp[1] + b.grip, rp[2], 0, b.open, b.d - 2, yBottle(i), ['移到待驗樣品瓶上方', '直線下降', '夾取樣品瓶', '提起'], { touch: [`cap${i}`] });
    const rd = ST.scanner.read;
    go(P(rd.x, Y0 + 40 + b.grip + 60, rd.z, 0), '移到讀碼位置上方');
    down(Y0 + 40 + b.grip, '下降到讀碼高度', { touch: [`cap${i}`] });
    s.scanning = true;
    go(P(rd.x, Y0 + 40 + b.grip, rd.z, B.pose.m.a + Math.PI, false), '旋轉讀取條碼', { min: TIME.scan, touch: [`cap${i}`], sig: 'scan' });
    s.scanning = false;
    say(B.t, '讀碼器', '整合軟體', `${S.barcode} ✓ 與樣品表第 ${2 * i + 1}、${2 * i + 2} 列相符`);
    up(yBottle(i), '上升', { touch: [`cap${i}`] });
    act(`樣品 ${i + 1}：放上樣品瓶座`); s.bottle[i].stage = '開蓋';
    // 放上樣品瓶座：夾座先夾緊，夾爪再放開
    go(P(clampPos[0], B.pose.m.y, clampPos[2], 0), '移到樣品瓶座上方');
    down(clampPos[1] + b.grip, '直線下降', { touch: ['clamp', id, `cap${i}`] });
    { const g0 = s.clampGap; wait(TIME.clampAct, '樣品瓶座夾緊（請求開蓋）', (st, e) => { st.clampGap = THREE.MathUtils.lerp(g0, b.d, e); st.sig.clamp = e > 0.5; }, { touch: ['clamp', id, `cap${i}`] }); }
    s.clampGap = b.d; setSig('clamp', true);
    detach(id);
    grip(b.open, '放開樣品瓶', { touch: ['clamp', id, `cap${i}`] });
    // ---- 開蓋
    ev(`樣品 ${i + 1}：開蓋（棘輪旋轉 5 × 120°）`, { sample: i, phase: 3 });
    act(`樣品 ${i + 1}：開蓋`);
    const capY0 = clampPos[1] + b.h + b.neckH - CAP.h + 4 + CAP.h / 2;
    lin(at(capY0 + 40), '上移到瓶蓋高度', { touch: [`cap${i}`, id] });
    grip(CAP.d + 16, '夾爪張開', { touch: [`cap${i}`, id] });
    lin(at(capY0), '下降夾住瓶蓋', { touch: [`cap${i}`, id] });
    grip(CAP.d - 2, '夾緊瓶蓋', { touch: [`cap${i}`, id] });
    capTwist(i, true);
    lin(at(B.pose.m.y + 40), '提起瓶蓋（脫牙）', { touch: [`cap${i}`, id] });
    say(B.t, '手臂', '整合軟體', `樣品 ${i + 1} 開蓋完成`);
    const cr = W(ST.capRest.x, ST.capRest.base, ST.capRest.z);
    up(Y0 + TRAVEL + CAP.h / 2, '提到搬運高度', { touch: [`cap${i}`] });
    // 瓶蓋暫放座離樣品瓶座 130 mm：夾爪改沿 Z 開合，本體（180 mm）才不會碰到瓶子
    place(`cap${i}`, cr[0], cr[1] + CAP.h / 2, cr[2], A_CAP, CAP.d + 16, null, Y_EMPTY, ['移到瓶蓋暫放座', '直線下降', '放下瓶蓋', '上升'], { sym: false, touch: ['caprest'] });
    s.bottle[i].stage = '取樣';

    for (let rep = 0; rep < 2; rep++) {
      const k = beakerNext++, bk = `beaker${k}`, jobK = 2 * i + rep, ep = emptyPos(k);
      const job = { k: jobK, beaker: k, sample: i, rep, conc: S.conc, aliquot: 0, waterMl: 50 };
      s.rec[jobK] = { sample: i, rep, beaker: k, status: '空杯秤重' };
      act(`樣品 ${i + 1}-${rep + 1}：空杯秤重`); ev(`樣品 ${i + 1}-${rep + 1}：空杯秤重（開天平門 → 放杯 → 關門 → 去皮）`, { sample: i, job: jobK, phase: 2 });
      if (s.door < 0.5) doorMove(true);
      pick(bk, ep[0], ep[1] + BEAKER.h / 2, ep[2], 0, 90, BEAKER.d - 2, Y_BEAKER, ['移到待處理杯區', '直線下降', '夾取空杯', '提起']);
      balanceIn(bk, beakerMass[k], '空杯');
      doorMove(false);
      weigh('天平穩定中（空杯）', () => { s.balTare = beakerMass[k]; s.rec[jobK].tare = beakerMass[k]; });
      say(B.t, '天平', '整合軟體', `空杯 ${beakerMass[k].toFixed(4)} g（穩定）→ 去皮`);
      s.rec[jobK].status = '移液';
      doorMove(true);
      balanceOut(bk, Y_BEAKER, '取出空杯');
      s.balStable = false;
      place(bk, holderPos[0], holderPos[1] + BEAKER.h / 2, holderPos[2], 0, 90, null, Y_EMPTY, ['移到滴定杯座', '直線下降', '放開', '上升'], { touch: ['holder'] });
      // ---- 移液潤洗＋取樣 20 mL
      ev(`樣品 ${i + 1}-${rep + 1}：移液（潤洗 2 次＋取 4 × 5 mL）`, { sample: i, job: jobK, phase: 4 });
      act(`樣品 ${i + 1}-${rep + 1}：移液`);
      pipetteTake();
      if (!hasTip) tipMount(i);
      for (let n = 0; n < RINSE.times; n++) { act(`樣品 ${i + 1}-${rep + 1}：潤洗 ${n + 1}/${RINSE.times}`); aspirate(i, RINSE.vol, `潤洗 ${n + 1}`); dispense('waste', RINSE.vol); }
      for (let n = 0; n < ALIQUOT.times; n++) { act(`樣品 ${i + 1}-${rep + 1}：取樣 ${n + 1}/${ALIQUOT.times}`); aspirate(i, ALIQUOT.vol, `取樣 ${n + 1}`); dispense(k, ALIQUOT.vol, `取樣 ${n + 1}`); }
      job.aliquot = ALIQUOT.vol * ALIQUOT.times;
      say(B.t, '移液模組', '整合軟體', `樣品 ${i + 1}-${rep + 1}：已加 ${ALIQUOT.times} × ${ALIQUOT.vol} mL = ${job.aliquot} mL`);
      if (rep === 1) tipEject();
      pipetteReturn();
      // ---- 樣品秤重
      act(`樣品 ${i + 1}-${rep + 1}：樣品秤重`); ev(`樣品 ${i + 1}-${rep + 1}：樣品秤重（讀淨重）`, { sample: i, job: jobK, phase: 5 });
      s.rec[jobK].status = '樣品秤重';
      const net = job.aliquot * (1.002 + gauss(R) * 0.0015);
      pick(bk, holderPos[0], holderPos[1] + BEAKER.h / 2, holderPos[2], 0, 90, BEAKER.d - 2, Y_BEAKER, ['移到滴定杯座', '直線下降', '夾取滴定杯', '提起'], { touch: ['holder'] });
      balanceIn(bk, beakerMass[k] + net, '含樣品');
      doorMove(false);
      weigh('天平穩定中（含樣品）', () => { s.rec[jobK].net = net; s.rec[jobK].gross = beakerMass[k] + net; });
      say(B.t, '天平', '整合軟體', `淨重 ${net.toFixed(4)} g（穩定）`);
      doorMove(true);
      balanceOut(bk, Y_BEAKER, '取出樣品杯');
      // ---- 移入進樣器
      act(`樣品 ${i + 1}-${rep + 1}：移入進樣器`); ev(`樣品 ${i + 1}-${rep + 1}：移入自動進樣器`, { sample: i, job: jobK, phase: 6 });
      job.net = net; job.veq = S.conc * job.aliquot / TITRANT.c * (1 + gauss(R) * 0.0015);
      job.result = job.veq * TITRANT.c * ANALYTE.M / (10 * net);
      const res = placeInSampler(k, job);
      s.rec[jobK].slot = res.slot; s.rec[jobK].status = '排隊'; setSig('cup', jobK);
      say(B.t, '手臂', '整合軟體', `杯子到位：樣品 ${i + 1}-${rep + 1} 在位置 ${res.slot + 1}`);
      scheduleJob(job, B.t);
      s.rec[jobK].placeT = B.t;
    }
    // ---- 關蓋 → 完成樣品區
    act(`樣品 ${i + 1}：關蓋`); ev(`樣品 ${i + 1}：關蓋、移到完成樣品瓶區`, { sample: i, phase: 8 });
    s.bottle[i].stage = '關蓋';
    pick(`cap${i}`, cr[0], cr[1] + CAP.h / 2, cr[2], A_CAP, CAP.d + 16, CAP.d - 2, Y0 + TRAVEL + CAP.h / 2, ['移到瓶蓋暫放座', '直線下降', '夾取瓶蓋', '提起'], { sym: false, touch: ['caprest'] });
    const capTop = clampPos[1] + b.h + b.neckH - CAP.h + 4 + CAP.h / 2 + TURNS * CAP.pitch / 3;
    go(P(clampPos[0], capTop + 30, clampPos[2], B.pose.m.a, false), '移到樣品瓶上方');
    lin(at(capTop), '瓶蓋對準瓶口', { v: SPEED.linSlow, touch: [`cap${i}`, id] });
    capTwist(i, false);
    say(B.t, '手臂', '整合軟體', `樣品 ${i + 1} 關蓋完成`);
    up(clampPos[1] + b.h + 60 + b.grip, '上升', { touch: [`cap${i}`, id] });
    const db = doneBottlePos(i);
    pick(id, clampPos[0], clampPos[1] + b.grip, clampPos[2], 0, b.open, b.d - 2, yBottle(i), ['移到樣品瓶上方', '直線下降', '夾住樣品瓶', '提起'],
      { touch: ['clamp', `cap${i}`], onGrip: () => { const gg = s.clampGap; wait(TIME.clampAct, '樣品瓶座鬆開', (st, e) => { st.clampGap = THREE.MathUtils.lerp(gg, 150, e); st.sig.clamp = e < 0.5; }, { touch: ['clamp', id, `cap${i}`] }); s.clampGap = 150; setSig('clamp', false); } });
    place(id, db[0], db[1] + b.grip, db[2], 0, b.open, null, Y_EMPTY, ['移到完成樣品瓶區', '直線下降', '放開', '上升'], { touch: [`cap${i}`] });
    s.bottle[i].stage = '完成';
  }
  // 天平門收尾：關上
  if (s.door > 0.5) doorMove(false);
  { const tare = s.balTare; wait(TIME.zero, '整合軟體對天平歸零（Z）', (st, e) => { st.balTare = e < 0.5 ? tare : 0; }); s.balTare = 0; say(B.t, '整合軟體', '天平', '歸零（Z）'); }
  const prepEnd = B.t;
  // ---- 等待滴定完成、逐杯取出
  ev('⑨ 等待分析完成，逐杯移到完成滴定杯區', { phase: 9 });
  act('等待分析完成'); goHome('回待命位置');
  const pending = [...TQ.jobs]; let doneN = 0;
  for (let guard = 0; pending.length && guard < 200; guard++) {
    const t0 = B.t;
    const ready = pending.filter(j => j.rinseEnd <= t0 + 1e-6 && slotDist(j.slot, towerSlotAt(t0)) >= 3 && !TQ.rots.some(r => r.t0 <= t0 && r.t1 > t0));
    if (ready.length) {
      const j = ready.sort((a, b) => a.end - b.end)[0];
      act(`取出樣品 ${j.sample + 1}-${j.rep + 1}`); ev(`取出樣品 ${j.sample + 1}-${j.rep + 1}（分析完成）`, { job: j.k, phase: 9 });
      removeFromSampler(j, doneN++); j.removed = true; j.removeT = B.t; pending.splice(pending.indexOf(j), 1);
      s.rec[j.k].removed = true;
      continue;
    }
    // 下一個時間點：某杯分析完成、或轉盤轉完
    const cands = [...pending.map(j => j.rinseEnd), ...TQ.rots.map(r => r.t1)].filter(x => x > t0 + 1e-6);
    const allDone = pending.every(j => j.rinseEnd <= t0 + 1e-6);
    if (allDone && !TQ.rots.some(r => r.t1 > t0)) {
      // 全部分析完成，剩下的杯子在滴定頭附近：轉盤把它轉到手臂側
      const j = pending[0]; addRotation(t0, Math.PI - j.slot * SLOT, 'move');
      say(t0, '整合軟體', 'Metrohm', `轉盤移動：位置 ${j.slot + 1} 轉到手臂側`);
      continue;
    }
    const next = Math.min(...cands);
    if (B.pose.m.x !== HOME.x || B.pose.m.z !== HOME.z) goHome('回待命位置');
    wait(Math.max(0.5, next - B.t + 0.2), '等待分析完成', null, { idle: true });
  }
  goHome('回待命位置');
  say(B.t, '手臂', '整合軟體', 'Cycle Complete');
  ev('Cycle Complete：批次完成', { phase: 10 });
  act('批次完成'); setSig('cycle', true);
  wait(10, '批次完成', null, { idle: true });

  const total = B.t;
  msgs.sort((a, b) => a.t - b.t); events.sort((a, b) => a.t - b.t);
  const idx = new Float64Array(steps.map(st => st.start));
  function stepAt(T) { let lo = 0, hi = steps.length - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (idx[m] <= T) lo = m; else hi = m - 1; } return lo; }
  /** 任一時間的手臂位姿與器皿狀態（純函數） */
  function sample(T) {
    T = THREE.MathUtils.clamp(T, 0, total);
    const n = stepAt(T), st = steps[n], e = st.dur > 0 ? THREE.MathUtils.clamp((T - st.start) / st.dur, 0, 1) : 1;
    const state = JSON.parse(st.s0); st.fx?.(state, e);
    const pose = st.kind === 'ptp' ? { ptp: { from: st.p0, to: st.p1, e: smooth(e) } } : st.kind === 'lin' ? { lin: { from: st.p0, to: st.p1, e: smooth(e) } } : st.p1;
    return { step: st, index: n, e, state, pose };
  }
  // 轉盤、滴定頭與滴定進度（純函數）
  function sampler(T) {
    const angle = rackAngleAt(T);
    let drop = 0, job = null, phase = '待機', stir = false, spray = false;
    for (const j of TQ.jobs) {
      if (T < j.rotStart) continue;
      if (T < j.rotEnd) { phase = `轉到位置 ${j.slot + 1}`; job = j; break; }
      if (T < j.start) { drop = (T - j.rotEnd) / TIME.lower; phase = '滴定頭下降'; job = j; break; }
      if (T < j.end) { drop = 1; job = j; stir = true; const u = T - j.start; phase = u < 15 ? '加純水 50 mL' : u < 35 ? '攪拌、電極平衡' : T < j.end - 20 ? '動態滴定（DET）' : '終點判定、計算結果'; break; }
      if (T < j.liftEnd) { drop = 1 - (T - j.end) / TIME.lift; phase = '滴定頭上升'; job = j; break; }
      if (T < j.rinseEnd) { phase = '電極噴洗'; spray = true; job = j; break; }
    }
    const rot = TQ.rots.find(r => T >= r.t0 && T < r.t1);
    if (rot && !job) phase = rot.kind === 'move' ? '轉盤移動（空位轉到手臂側）' : phase;
    return { angle, drop: THREE.MathUtils.clamp(drop, 0, 1), job, phase, stir, spray, rotating: !!rot };
  }
  const stats = {
    total, prepEnd, steps: steps.length, jobs: TQ.jobs.length,
    firstStart: TQ.jobs[0]?.start, lastEnd: TQ.jobs.at(-1)?.end,
    robotBusy: steps.filter(s => !s.idle).reduce((a, s) => a + s.dur, 0),
  };
  return { steps, total, sample, sampler, jobs: TQ.jobs, rots: TQ.rots, events, msgs, stats, towerSlotAt, slotDist, beakerMass };
}
