// 動畫排程：每台設備與每個桶各有一條時間軌，依站位占用（流水線阻塞）推算交接時刻。
// 任一時刻的畫面完全由絕對時間決定，倒退、跳站與連續播放結果一致。
import * as THREE from 'three';
import { RACK, PALLET, DRUM, AGV, FORK, AISLE, PALLET_STATION, GANTRY, LYING, LABEL, UPENDER, UPRIGHT, DECAP, ROBOT, BOOTH, OUT, WASTE } from './layout.js';
import { smooth, D2R } from './parts.js';
import { JOINTS, SPEED } from './robot.js';

const linear = t => t;

class Track {
  constructor(name, base) { this.name = name; this.base = { ...base }; this.state = { ...base }; this.steps = []; this.t = 0; }
  // dur 秒內把 values 的數值以 S 曲線插到目標；非數值鍵在步驟開始時立即生效
  add(dur, values = {}, o = {}) {
    const start = Math.max(o.at ?? this.t, this.t), initial = { ...this.state }, end = { ...initial, ...values };
    const s = { track: this.name, start, dur, initial, end, action: o.action ?? '', sub: o.sub ?? '', ease: o.ease ?? smooth, motion: o.motion, event: o.event, station: o.station };
    if (s.motion) Object.assign(s.end, s.motion(1));
    this.steps.push(s); this.state = s.end; this.t = start + dur; return s;
  }
  hold(until) { this.t = Math.max(this.t, until); }
  find(T) { let lo = 0, hi = this.steps.length - 1, idx = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (this.steps[m].start <= T) { idx = m; lo = m + 1; } else hi = m - 1; } return idx; }
  sample(T) {
    const i = this.find(T); if (i < 0) return { ...this.base };
    const s = this.steps[i], t = s.dur > 0 ? Math.min(1, (T - s.start) / s.dur) : 1;
    if (t >= 1) return { ...s.end };
    const e = s.ease(t), out = {};
    for (const k in s.end) { const a = s.initial[k], b = s.end[k]; out[k] = typeof a === 'number' && typeof b === 'number' ? a + (b - a) * e : b; }
    if (s.motion) Object.assign(out, s.motion(e, t));
    return out;
  }
  active(T) { const i = this.find(T); if (i < 0) return null; const s = this.steps[i]; return T < s.start + s.dur ? s : null; }
  get end() { return this.steps.length ? Math.max(...this.steps.map(s => s.start + s.dur)) : 0; }
}

// 三次 Bezier（AGV 曲線行駛）：回傳位置與切線方位，方位展開到接近 ref
function bezier(p0, c1, c2, p3, refYaw, reverse = false) {
  const at = e => {
    const u = 1 - e, w = [u * u * u, 3 * u * u * e, 3 * u * e * e, e * e * e], d = [-3 * u * u, 3 * u * u - 6 * u * e, 6 * u * e - 3 * e * e, 3 * e * e];
    const x = w[0] * p0[0] + w[1] * c1[0] + w[2] * c2[0] + w[3] * p3[0], z = w[0] * p0[1] + w[1] * c1[1] + w[2] * c2[1] + w[3] * p3[1];
    const dx = d[0] * p0[0] + d[1] * c1[0] + d[2] * c2[0] + d[3] * p3[0], dz = d[0] * p0[1] + d[1] * c1[1] + d[2] * c2[1] + d[3] * p3[1];
    let yaw = Math.atan2(-dz, dx) / D2R + (reverse ? 180 : 0); yaw += 360 * Math.round((refYaw - yaw) / 360);
    return { x, z, yaw };
  };
  let L = 0, prev = at(0); for (let i = 1; i <= 40; i++) { const p = at(i / 40); L += Math.hypot(p.x - prev.x, p.z - prev.z); prev = p; }
  return { at, length: L };
}

export const STATIONS = [
  { id: 'agv', name: '倉儲／AGV', short: 'S1' }, { id: 'gantry', name: '龍門上料', short: 'S2' }, { id: 'label', name: '貼標讀碼', short: 'S3' },
  { id: 'upender', name: '90° 翻桶', short: 'S4' }, { id: 'decap', name: '自動開蓋', short: 'S5' }, { id: 'robot', name: '手臂清洗', short: 'S6' }, { id: 'waste', name: '廢液回收', short: 'S7' },
];
export const DRUM_IDS = [1, 2, 3, 4].map(i => `CTW-2610-${String(i).padStart(4, '0')}`);
const YAW0 = [37, 151, 263, 312];

export function createSequence({ robot }) {
  const T = {};
  const track = (name, base) => (T[name] = new Track(name, base));
  const agv = track('agv', { x: AGV.charger.x, z: AGV.charger.z, yaw: AGV.charger.yaw, fork: AGV.travel, moving: false });
  const shuttle = track('shuttle', { pos: 1, lift: 0 });
  const pallet = track('pallet', { mode: 'rack', pos: 0, lift: 0 });
  const rackPal = [1, 2, 3].map(i => track('pal' + i, { pos: i, lift: 0 }));
  const gantry = track('gantry', { x: GANTRY.home.x, z: GANTRY.home.z, y: GANTRY.safeY, tilt: 0, jaw: 0 });
  const labeler = track('labeler', { pad: 0, print: 0, spin: 0, flash: false });
  const upender = track('upender', { tilt: 0, clamp: 0 });
  const decap = track('decap', { hx: 0, hz: 0, hy: DECAP.safeY, spinBig: 0, spinSmall: 0, flash: false, clamp: 0, table: 0, caps: 0, heldBig: false, heldSmall: false });
  const grip = track('grip', { jaw: 0 });
  const booth = track('booth', { lance: 0, spray: false, src: 'R', pour: '', pool: 0 });   // pour：倒液中的桶序（字串，不插值）
  const sump = track('sump', { level: 0, pump: false, dest: 'W' });
  const makeup = track('makeup', { on: false });   // TK-F 液位控制補水（廠務自來水／RO）
  const tanks = track('tanks', { W: WASTE.tanks.W.init, R: WASTE.tanks.R.init, F: WASTE.tanks.F.init });
  const drums = DRUM_IDS.map((id, k) => track('drum' + k, { mode: 'pallet', slot: k, yaw: YAW0[k], lx: LYING.place, uz: UPRIGHT.z0, ox: OUT.place, water: 0, capBig: true, capSmall: true, label: false, labelAng: 0, read: false, rinse: 0, state: '倉儲' }));
  const events = [];
  const ev = (s, station, label) => { events.push({ time: s.start, station, label: label || s.action }); return s; };

  // ================================================================ S1 AGV 取料：第 2 道第 2 層前位
  const laneX = RACK.lanes[RACK.demo.lane], rail = RACK.levels[RACK.demo.level], pivotRack = RACK.pos[0] + AGV.palletX, pivotStation = PALLET_STATION.z - AGV.palletX;
  const move = (to, o) => { const s = agv.state, d = Math.hypot(to.x - s.x, to.z - s.z); return agv.add(o.dur ?? d / (o.speed ?? AGV.speed) + 1.2, { ...to, moving: true }, o); };
  const turn = (yaw, extra = {}, o = {}) => agv.add(Math.abs(yaw - agv.state.yaw) / AGV.turn + .8, { yaw, moving: true, ...extra }, o);
  const fork = (v, o = {}) => agv.add(Math.abs(v - agv.state.fork) / AGV.lift + .5, { fork: v, moving: false }, o);
  const curve = (p0, c1, c2, p3, o) => { const b = bezier(p0, c1, c2, p3, agv.state.yaw); return agv.add(b.length / AGV.speed + 1.5, { moving: true }, { ...o, motion: e => b.at(e) }); };
  agv.add(1, {}, { action: '待命：充電座', sub: '接到取料任務：第 2 道第 2 層' });
  ev(move({ x: laneX, z: AISLE.zc }, { action: 'AGV 出發：行駛至第 2 道前', sub: '離開走道中心線上的地面充電板，直行往西' }), 'agv', 'AGV 出發取料');
  turn(90, { fork: rail + FORK.entry }, { action: '原地轉向北＋貨叉升至第 2 層', sub: `迴轉半徑 ${Math.round(Math.hypot(AGV.palletX + 600, 600))} mm；叉面 ${rail + FORK.entry} mm` });
  move({ x: laneX, z: pivotRack }, { speed: AGV.slow, action: '低速進入車道口', sub: '貨叉插入前位棧板底樑之間' });
  agv.add(.4, { fork: rail + FORK.deck, moving: false }, { action: '貨叉接觸棧板' });
  pallet.add(0, { mode: 'agv' }, { at: agv.t });
  ev(agv.add(.6, { fork: rail + FORK.lifted }, { action: '抬起棧板', sub: '棧板離軌 60 mm' }), 'agv');
  move({ x: laneX, z: AISLE.zc }, { speed: AGV.slow, action: '倒車退出車道' });
  const tOutOfRack = agv.t;
  fork(AGV.travel, { action: '貨叉降至行駛高度' });
  turn(180, {}, { action: '原地轉向西' });
  move({ x: PALLET_STATION.x, z: AISLE.zc }, { action: '行駛至棧板站前' });
  turn(270, {}, { action: '原地轉向南', sub: '對準棧板站與龍門光柵入口' });
  move({ x: PALLET_STATION.x, z: pivotStation }, { speed: AGV.slow, action: '低速駛入棧板站', sub: '光柵屏蔽（muting）開啟' });
  agv.add(.4, { fork: PALLET_STATION.stand + FORK.deck, moving: false }, { action: '棧板落座' });
  pallet.add(0, { mode: 'station' }, { at: agv.t });
  ev(agv.add(.5, { fork: PALLET_STATION.stand + FORK.deck - 60 }, { action: '貨叉脫離棧板' }), 'agv', 'AGV 將棧板放上棧板站');
  move({ x: PALLET_STATION.x, z: AISLE.zc }, { speed: AGV.slow, action: '倒車退出龍門區', sub: '退出後光柵恢復，龍門才允許動作' });
  const tAgvOut = agv.t;
  agv.add(.5, { moving: false }, { action: '走道待命', sub: '等待龍門取完 4 桶後回收空棧板' });

  // 穿梭車把同層後方棧板逐一往前補位
  shuttle.hold(tOutOfRack + .5);
  for (let i = 1; i <= 3; i++) {
    const p = rackPal[i - 1];
    if (shuttle.state.pos !== i) shuttle.add(Math.abs(shuttle.state.pos - i) * 1.3 / .6 + 1, { pos: i }, { action: `穿梭車回到第 ${i + 1} 位` });
    p.hold(shuttle.t);
    shuttle.add(1.2, { lift: 1 }, { action: '頂升棧板 40 mm' }); p.add(1.2, { lift: 1 }, { at: shuttle.t - 1.2 });
    const s = shuttle.add(1.3 / .5 + 1, { pos: i - 1 }, { action: `第 ${i + 1} 位棧板前移一格` }); p.add(s.dur, { pos: i - 1 }, { at: s.start });
    if (i === 1) ev(s, 'agv', '穿梭車補位');
    shuttle.add(1.2, { lift: 0 }, { action: '放下棧板' }); p.add(1.2, { lift: 0 }, { at: shuttle.t - 1.2 });
  }
  shuttle.add(1.3 / .6 + 1, { pos: 3 }, { action: '穿梭車停回後端' });

  // ================================================================ 流水線：逐桶推算
  const gp = GANTRY, hang = gp.hang, placePivot = LYING.place - hang;
  const dep = []; let upFree = 0, robotFree = 0, robotStart = null;
  const travelLy = d => Math.abs(d) / LYING.speed + 1, travelUp = d => Math.abs(d) / UPRIGHT.speed + 1;
  // 機器人位姿（固定物件，關節解快取在物件上）
  const V = (x, y, z) => new THREE.Vector3(x, y, z), E = V(1, 0, 0), W = V(-1, 0, 0), S = V(0, 0, 1), UP = V(0, 1, 0);
  const P = {
    wait: robot.poseDrum(V(UPRIGHT.x - 450, 1200, UPRIGHT.pick), UP, E),
    pre: robot.poseDrum(V(UPRIGHT.x - 450, UPRIGHT.top + DRUM.H / 2, UPRIGHT.pick), UP, E),
    pick: robot.poseDrum(V(UPRIGHT.x, UPRIGHT.top + DRUM.H / 2, UPRIGHT.pick), UP, E),
    lift: robot.poseDrum(V(UPRIGHT.x, UPRIGHT.top + DRUM.H / 2 + 250, UPRIGHT.pick), UP, E),
    entry: robot.poseDrum(V(BOOTH.drum[0], 1600, BOOTH.entryZ), UP, S),
    u: robot.poseDrum(V(...BOOTH.drum), UP, S),
    pour: robot.poseDrum(V(...BOOTH.drum), UP, S, 190 * D2R),
    above: robot.poseDrum(V(OUT.place, OUT.top + DRUM.H / 2 + 150, OUT.z), UP, W),
    place: robot.poseDrum(V(OUT.place, OUT.top + DRUM.H / 2, OUT.z), UP, W),
    retract: robot.poseDrum(V(OUT.place + 450, OUT.top + DRUM.H / 2, OUT.z), UP, W),
  };
  // 搖晃：只繞夾爪軸（J6）來回滾轉 ±25°，3 個週期，振幅以正弦包絡起停；J6 峰值約 100°/s
  const shakeAt = e => robot.poseDrum(V(...BOOTH.drum), UP, S, 25 * D2R * Math.sin(Math.PI * e) * Math.sin(e * Math.PI * 2 * 3));
  const rsteps = []; let rpose = P.wait, rjoints = robot.solve(P.wait), rt = 0;
  const rAdd = (kind, to, dur, o = {}) => {
    const start = Math.max(o.at ?? rt, rt), j0 = rjoints, j1 = kind === 'path' ? j0 : robot.solve(to, j0);
    if (kind === 'ptp' && dur == null) dur = Math.max(1.2, ...JOINTS.map(n => Math.abs(j1[n] - j0[n]) / (SPEED[n] * D2R * (o.vf ?? .55)) * 1.875));
    const s = { track: 'robot', start, dur, kind, pose0: rpose, pose1: kind === 'path' ? rpose : to, j0, j1, motion: o.motion, action: o.action ?? '', sub: o.sub ?? '' };
    rsteps.push(s); rt = start + dur; if (kind !== 'path') { rpose = to; rjoints = j1; } return s;
  };
  const tankLevel = () => ({ ...tanks.state });

  for (let k = 0; k < 4; k++) {
    const d = drums[k], [sx, sz] = PALLET.slots[k], px = PALLET_STATION.x - sx, pz = PALLET_STATION.z - sz, prev = dep[k - 1] || {};   // 棧板站上棧板轉了 180°
    const id = DRUM_IDS[k];
    // ---- S2 龍門：取桶 → 抬升 → 移出棧板範圍 → 等放料位空 → 邊移邊翻 90° → 放上 V 輥
    gantry.hold(tAgvOut + 1);
    const g0 = gantry.add(Math.hypot(px - gantry.state.x, pz - gantry.state.z) / 600 + 1.2, { x: px, z: pz, y: gp.safeY, tilt: 0, jaw: 0 }, { action: `移至第 ${k + 1} 桶上方`, sub: id, station: 'gantry' });
    if (k === 0) ev(g0, 'gantry', '龍門開始上料');
    gantry.add(2, { y: gp.pickY }, { action: '下降夾桶位', sub: '雙弧形 PU 爪由南北兩側包覆桶身上半部' });
    gantry.add(1, { jaw: 1 }, { action: '夾爪夾緊', sub: '夾持確認後才抬升' });
    d.add(0, { mode: 'gantry', yaw: d.state.yaw + 180, state: '龍門夾持' }, { at: gantry.t });
    gantry.add(2, { y: gp.safeY }, { action: '抬升至安全高度', sub: `翻轉軸 ${gp.safeY} mm；桶底高於相鄰桶頂` });
    gantry.add(1.5, { x: 4900 }, { action: '沿 X 移出棧板範圍', sub: '先平移再翻轉，避免掃到相鄰桶' });
    const tPickedClear = gantry.t;
    const freePlace = prev.place != null ? prev.place + 3.2 : 0;
    gantry.hold(freePlace);
    ev(gantry.add(3.5, { x: placePivot, z: LYING.z, tilt: 1 }, { action: '邊移邊翻轉 90°', sub: '桶頂朝西、桶底朝東（配合翻桶機方向）' }), 'gantry', `${id} 翻轉放倒`);
    gantry.add(2.5, { y: gp.placeY }, { action: '下降至 V 形輥', sub: `桶中心高 ${LYING.y} mm` });
    gantry.add(1, { jaw: 0 }, { action: '夾爪鬆開' });
    d.add(0, { mode: 'lying', lx: LYING.place, state: '橫躺輸送' }, { at: gantry.t });
    gantry.add(2, { y: gp.safeY }, { action: '夾爪上升', sub: '放料位交給輸送' });
    const r = { placed: gantry.t };
    if (k === 3) { gantry.add(3, { x: gp.home.x, z: gp.home.z, tilt: 0 }, { action: '回原點', sub: '4 桶上料完成' }); }

    // ---- 輸送：放料位 → 貼標站
    r.place = Math.max(r.placed, prev.label ?? 0);
    d.add(travelLy(LYING.label - LYING.place), { lx: LYING.label, state: '往貼標站' }, { at: r.place });
    // ---- S3 貼標＋讀碼
    const tl = d.t;
    labeler.hold(tl);
    const p0 = labeler.add(1.8, { print: 1 }, { action: '列印識別標籤', sub: `${id}｜QR＋桶號` });
    if (k === 0) ev(p0, 'label', '貼標站開始');
    labeler.add(1.2, { pad: 1 }, { action: '貼標頭推出', sub: '吸附標籤推向桶身南側' });
    // 貼附當下桶面朝南的局部方位
    const qLy = yaw => new THREE.Quaternion().setFromAxisAngle(V(0, 0, 1), Math.PI / 2).multiply(new THREE.Quaternion().setFromAxisAngle(UP, yaw * D2R));
    const dl = S.clone().applyQuaternion(qLy(d.state.yaw).invert()), labelAng = Math.atan2(dl.x, dl.z) / D2R;
    d.add(0, { label: true, labelAng, state: '已貼標' }, { at: labeler.t });
    labeler.add(.4, { print: 0 }, { action: '壓貼', sub: '標籤 100×150 mm，貼於桶身中段' });
    labeler.add(1, { pad: 0 }, { action: '貼標頭退回' });
    // 轉 ±90° 讓標籤朝上給相機
    const upLocal = yaw => UP.clone().applyQuaternion(qLy(yaw).invert());
    const lblVec = new THREE.Vector3(Math.sin(labelAng * D2R), 0, Math.cos(labelAng * D2R));
    const spin = [90, -90].find(sg => upLocal(d.state.yaw + sg).dot(lblVec) > .99) ?? 90;
    const rs = labeler.add(1.6, { spin: labeler.state.spin + spin / 90 }, { action: '旋轉輥帶動桶身', sub: '標籤轉到正上方' });
    d.add(1.6, { yaw: d.state.yaw + spin }, { at: rs.start });
    ev(labeler.add(.9, { flash: true }, { action: '相機取像讀碼', sub: `QR ${id} 讀取 OK · 位置偏差 0.6 mm（模擬）` }), 'label', `${id} 讀碼`);
    d.add(0, { read: true }, { at: labeler.t });
    labeler.add(.2, { flash: false }, { action: '讀碼完成' });
    r.labelDone = labeler.t;
    // ---- 貼標站 → 緩衝位 → 翻桶機
    r.label = Math.max(r.labelDone, prev.buffer ?? 0);
    d.add(travelLy(LYING.buffer - LYING.label), { lx: LYING.buffer, state: '緩衝位' }, { at: r.label });
    r.buffer = Math.max(d.t, upFree, prev.upender ?? 0);
    d.add(travelLy(LYING.upender - LYING.buffer), { lx: LYING.upender, state: '進入翻桶機' }, { at: r.buffer });
    // ---- S4 翻桶
    upender.hold(d.t);
    const u0 = upender.add(.8, { clamp: 1 }, { action: '側夾夾緊', sub: '桶底靠緊翻轉靠板' });
    if (k === 0) ev(u0, 'upender', '翻桶機開始');
    d.add(0, { mode: 'upender', state: '翻桶中' }, { at: upender.t });
    ev(upender.add(4, { tilt: 1 }, { action: '翻轉 90°', sub: '以桶底下緣為軸，桶口朝上' }), 'upender', `${id} 翻正`);
    upender.add(.6, { clamp: 0 }, { action: '側夾鬆開' });
    r.upender = Math.max(upender.t, prev.decap ?? 0);
    d.add(0, { mode: 'upright', uz: UPRIGHT.z0, yaw: d.state.yaw, state: '立放輸送' }, { at: r.upender });
    d.add(travelUp(DECAP.z - UPRIGHT.z0), { uz: DECAP.z }, { at: r.upender });
    upender.add(3.5, { tilt: 0 }, { at: r.upender + 2.5, action: '翻轉台復歸' });
    upFree = upender.t;
    // ---- S5 開蓋
    decap.hold(d.t);
    const c0 = decap.add(.8, { clamp: 1 }, { action: '定心夾持', sub: id });
    if (k === 0) ev(c0, 'decap', '開蓋站開始');
    const bungAt = ((d.state.yaw % 360) + 360) % 360;
    decap.add(1, { flash: true }, { action: '頂視相機定位桶塞', sub: `2" 桶塞方位 ${bungAt.toFixed(0)}°、3/4" ${((bungAt + 180) % 360).toFixed(0)}°（模擬）` });
    decap.add(.2, { flash: false });
    const delta = ((90 - d.state.yaw) % 360 + 540) % 360 - 180;
    const rt0 = decap.add(Math.abs(delta) / 60 + 1, { table: decap.state.table + delta }, { action: '旋轉台對位', sub: '2" 桶塞轉到北側、3/4" 轉到南側' });
    d.add(rt0.dur, { yaw: d.state.yaw + delta }, { at: rt0.start });
    const capTop = UPRIGHT.top + DRUM.H / 2 + 463 + 12;
    for (const [key, hx, hz, binX, name] of [['Big', 90, -200, DECAP.bin.x - UPRIGHT.x + 90, '2"'], ['Small', -90, 200, DECAP.bin.x - UPRIGHT.x - 90, '3/4"']]) {
      decap.add(1.6, { hx, hz, hy: DECAP.safeY }, { action: `鎖付軸移至 ${name} 桶塞` });
      decap.add(1, { hy: capTop - 40 }, { action: '套筒下降套住桶蓋' });
      const sp = decap.add(2.4, { ['spin' + key]: decap.state['spin' + key] + 1, hy: capTop - 25 }, { action: `反轉拆下 ${name} 桶蓋`, sub: '扭力監控；蓋子隨套筒內撐爪帶出' });
      if (k === 0 && key === 'Big') ev(sp, 'decap', '拆 2" 桶蓋');
      d.add(0, { ['cap' + key]: false }, { at: decap.t }); decap.add(0, { ['held' + key]: true });
      decap.add(.9, { hy: DECAP.safeY }, { action: '帶蓋上升' });
      decap.add(1.6, { hx: binX, hz: 0 }, { action: '移至桶蓋收集桶' });
      decap.add(.8, { hy: 1150 }, { action: '下降' });
      decap.add(.4, { ['held' + key]: false, caps: decap.state.caps + 1 }, { action: '鬆開桶蓋' });
      decap.add(.6, { hy: DECAP.safeY });
    }
    decap.add(1.2, { hx: 0, hz: 0 }, { action: '鎖付軸回原點' });
    decap.add(.6, { clamp: 0 }, { action: '鬆開定心夾' });
    d.add(0, { state: '桶口已開' }, { at: decap.t });
    r.decap = Math.max(decap.t, prev.pick ?? 0);
    d.add(travelUp(UPRIGHT.pick - DECAP.z), { uz: UPRIGHT.pick, state: '待手臂取桶' }, { at: r.decap });
    const tAtPick = d.t;

    // ---- S6 手臂清洗
    const tRobot = Math.max(tAtPick, robotFree);
    if (robotStart == null) robotStart = tRobot;
    const a0 = rAdd('lin', P.pre, 1.2, { at: tRobot, action: '接近取桶位', sub: '夾爪張開，沿 +X 前進' });
    if (k === 0) events.push({ time: a0.start, station: 'robot', label: '手臂開始取桶' });
    rAdd('lin', P.pick, 1.4, { action: '夾爪包覆桶身' });
    grip.hold(rt); grip.add(1, { jaw: 1 }, { action: '夾爪夾緊' }); rt = grip.t;
    d.add(0, { mode: 'robot', state: '手臂夾持' }, { at: rt });
    rAdd('lin', P.lift, 1, { action: '抬升 250 mm', sub: '桶底高過輸送側導引' });
    r.pick = rt;
    rAdd('ptp', P.entry, null, { action: '轉向沖洗站', sub: '關節同步插值（PTP），桶身停在隔間開口外' });
    const en = rAdd('lin', P.u, 1.8, { action: '送入沖洗站', sub: '2" 桶口對準沖洗噴槍' });
    events.push({ time: en.start, station: 'robot', label: `${id} 進入沖洗站` });
    for (let c = 1; c <= 3; c++) {
      const src = c === 1 ? 'R' : 'F', dest = c < 3 ? 'W' : 'R';
      booth.hold(rt);
      booth.add(1, { lance: 1, src }, { action: `第 ${c} 次沖洗：噴槍伸入桶口`, sub: '噴頭伸入 2" 桶口約 140 mm' });
      const sp = booth.add(5, { spray: true }, { action: `第 ${c} 次沖洗：旋轉噴頭噴洗`, sub: `${WASTE.rinseL} L，水源 ${src === 'R' ? 'TK-R 回收沖洗水（逆流再利用）' : 'TK-F 清水'}` });
      if (c === 1 && k === 0) events.push({ time: sp.start, station: 'waste', label: '沖洗水由 TK-R 供應' });
      d.add(0, { rinse: c, state: `第 ${c} 次沖洗` }, { at: sp.start }); d.add(5, { water: WASTE.rinseL }, { at: sp.start });
      tanks.add(5, { [src]: tanks.state[src] - WASTE.rinseL }, { at: sp.start, action: `P-1 供水 ${src === 'R' ? 'TK-R' : 'TK-F'} → 噴槍` });
      if (src === 'F') { tanks.add(4, { F: tanks.state.F + WASTE.rinseL }, { at: sp.start + 5, action: 'TK-F 液位補水' }); makeup.add(4, { on: true }, { at: sp.start + 5, action: '廠務清水補入 TK-F' }); makeup.add(0, { on: false }); }
      booth.add(1, { spray: false, lance: 0 }, { action: '噴槍退回' });
      rt = booth.t;
      rAdd('path', null, 5, { motion: shakeAt, action: `第 ${c} 次搖晃`, sub: '繞夾爪軸來回滾轉 ±25°，殘液沖刷桶壁' });
      rAdd('lin', P.pour, 2.2, { action: `第 ${c} 次倒液：翻轉 190°`, sub: '2" 桶口轉到最低點，對準集液漏斗' });
      booth.hold(rt);
      const pr = booth.add(3.5, { pour: String(k), pool: 1 }, { action: `倒入集液漏斗 → ${dest === 'W' ? 'TK-W 廢液槽' : 'TK-R 回收槽'}`, sub: dest === 'W' ? '含化學殘液，委外處理' : '末道沖洗水較乾淨，回收作下一桶第 1 道' });
      d.add(3.5, { water: 0 }, { at: pr.start });
      if (k === 0 && c === 1) ev(pr, 'waste', '倒液進集液漏斗');
      sump.add(3.5, { level: 1, dest }, { at: pr.start });
      booth.add(.1, { pour: '', pool: 0 });
      const pm = sump.add(3, { pump: true, level: 0 }, { action: `P-2 送液 → ${dest === 'W' ? 'TK-W' : 'TK-R'}`, sub: 'V-3 三通閥切換去向' });
      tanks.add(3, { [dest]: tanks.state[dest] + WASTE.rinseL }, { at: pm.start, action: `集液槽 → ${dest === 'W' ? 'TK-W' : 'TK-R'}` });
      if (k === 0 && c === 3) ev(pm, 'waste', '末道沖洗水回收至 TK-R');
      sump.add(0, { pump: false });
      rt = Math.max(rt, pr.start + 3.5);
      if (c === 3) rAdd('path', null, 3, { motion: () => P.pour, action: '倒置滴乾', sub: '桶口朝下停留 3 s' });
      rAdd('lin', P.u, 2, { action: c < 3 ? '轉回桶口朝上' : '轉正' });
    }
    d.add(0, { state: '清洗完成' }, { at: rt });
    rAdd('lin', P.entry, 1.6, { action: '退出沖洗站' });
    rAdd('ptp', P.above, null, { action: '轉向出料輸送', sub: '關節同步插值（PTP）' });
    rAdd('lin', P.place, 1.2, { action: '下降放桶' });
    grip.hold(rt); grip.add(.8, { jaw: 0 }, { action: '夾爪鬆開' }); rt = grip.t;
    d.add(0, { mode: 'out', ox: OUT.place, yaw: -90, state: '出料' }, { at: rt });
    ev(rAdd('lin', P.retract, 1, { action: '夾爪退出' }), 'robot', `${id} 放上出料輸送`);
    d.add(Math.abs(OUT.place - OUT.stops[3 - k]) / OUT.speed + 1, { ox: OUT.stops[k], state: '送往裝填區' }, { at: rt });
    rAdd('ptp', P.wait, null, { action: '回到取桶等待點', vf: .7 });
    robotFree = rt;
    dep.push(r);
    // AGV 回收空棧板：第 4 桶離開棧板範圍後
    if (k === 3) {
      agv.hold(tPickedClear + 1);
      ev(move({ x: PALLET_STATION.x, z: pivotStation }, { speed: AGV.slow, action: '駛入棧板站回收空棧板', sub: '光柵屏蔽；龍門已離開棧板範圍' }), 'agv', 'AGV 回收空棧板');
      agv.add(.4, { fork: PALLET_STATION.stand + FORK.deck, moving: false }, { action: '貨叉接觸空棧板' });
      pallet.add(0, { mode: 'agv' }, { at: agv.t });
      agv.add(.5, { fork: PALLET_STATION.stand + FORK.lifted }, { action: '抬起空棧板' });
      move({ x: PALLET_STATION.x, z: AISLE.zc }, { speed: AGV.slow, action: '倒車退出龍門區' });
      turn(360, {}, { action: '原地轉向東' });
      const stackTop = RACK.levels[RACK.emptyLevel] + RACK.emptyStack * PALLET.H, laneE = RACK.lanes[RACK.emptyLane];
      move({ x: laneE, z: AISLE.zc }, { action: '行駛至空棧板道', sub: `第 ${RACK.emptyLane + 1} 道底層` });
      turn(450, { fork: stackTop + FORK.deck + 60 }, { action: '原地轉向北＋抬高', sub: '空棧板高於疊頂 60 mm' });
      move({ x: laneE, z: pivotRack }, { speed: AGV.slow, action: '低速進入空棧板道' });
      agv.add(.4, { fork: stackTop + FORK.deck, moving: false }, { action: '疊放空棧板' });
      pallet.add(0, { mode: 'empties' }, { at: agv.t });
      agv.add(.5, { fork: stackTop + FORK.deck - 60 }, { action: '貨叉脫離' });
      move({ x: laneE, z: AISLE.zc }, { speed: AGV.slow, action: '倒車退出' });
      fork(AGV.travel, { action: '貨叉降至行駛高度' });
      turn(540, {}, { action: '原地轉向西' });
      ev(move({ x: AGV.charger.x, z: AGV.charger.z }, { action: '回充電板', sub: '柱前走道中心線，地面接觸式充電' }), 'agv', 'AGV 回充電板');
      agv.add(.5, { moving: false }, { action: '待命：充電中' });
    }
  }

  // ---------------------------------------------------------------- 取樣
  const robotSample = Tm => {
    let s = null; for (let i = rsteps.length - 1; i >= 0; i--) if (rsteps[i].start <= Tm) { s = rsteps[i]; break; }
    if (!s) { robot.setJoints(robotHome); return { step: null }; }
    const t = s.dur > 0 ? Math.min(1, (Tm - s.start) / s.dur) : 1, e = smooth(t);
    if (t >= 1 || s.kind === 'ptp') {
      const j = {}; for (const n of JOINTS) j[n] = s.j0[n] + (s.j1[n] - s.j0[n]) * (t >= 1 ? 1 : e);
      robot.setJoints(j); return { step: Tm < s.start + s.dur ? s : null, pose: t >= 1 ? s.pose1 : null };
    }
    let pose, seed = {};
    if (s.kind === 'path') { pose = s.motion(e); for (const n of JOINTS) seed[n] = s.j0[n]; }
    else { pose = { target: s.pose0.target.clone().lerp(s.pose1.target, e), rot: s.pose0.rot.clone().slerp(s.pose1.rot, e) }; for (const n of JOINTS) seed[n] = s.j0[n] + (s.j1[n] - s.j0[n]) * e; }
    const r = robot.track(pose, seed); return { step: s, pose, err: r.err };
  };
  const robotHome = robot.solve(P.wait);
  const total = Math.max(...Object.values(T).map(t => t.end), rt) + 2;
  events.sort((a, b) => a.time - b.time);
  const stationStart = Object.fromEntries(STATIONS.map(s => [s.id, events.find(e => e.station === s.id)?.time ?? 0]));

  function sample(Tm) {
    const st = {}; for (const [k, t] of Object.entries(T)) st[k] = t.sample(Tm);
    const r = robotSample(Tm);
    return { time: Tm, st, robot: r };
  }
  function activity(Tm) {
    const out = {}; for (const [k, t] of Object.entries(T)) { const s = t.active(Tm); if (s && s.action) out[k] = s; }
    const r = rsteps.find(s => s.start <= Tm && Tm < s.start + s.dur); if (r) out.robot = r;
    return out;
  }
  return { sample, activity, tracks: T, robotSteps: rsteps, events, total, stationStart, poses: P, robotStart };
}

// ---------------------------------------------------------------- 由狀態推算世界座標（主程式與驗證共用）
const _q = new THREE.Quaternion(), _q2 = new THREE.Quaternion(), Yax = new THREE.Vector3(0, 1, 0), Zax = new THREE.Vector3(0, 0, 1);
export function palletWorld(p, agvState) {
  if (p.mode === 'rack') return { pos: new THREE.Vector3(RACK.lanes[RACK.demo.lane], RACK.levels[RACK.demo.level] + p.lift * RACK.shuttleLift, RACK.pos[0]), yaw: 0 };
  if (p.mode === 'station') return { pos: new THREE.Vector3(PALLET_STATION.x, PALLET_STATION.stand, PALLET_STATION.z), yaw: 180 };
  if (p.mode === 'empties') return { pos: new THREE.Vector3(RACK.lanes[RACK.emptyLane], RACK.levels[RACK.emptyLevel] + RACK.emptyStack * PALLET.H, RACK.pos[0]), yaw: 0 };
  const a = agvState, y = a.yaw * D2R;
  // 棧板在車道內朝向 0°，AGV 朝北（90°）叉起，所以棧板方位 = AGV 方位 − 90°
  return { pos: new THREE.Vector3(a.x + Math.cos(y) * AGV.palletX, a.fork - FORK.deck, a.z - Math.sin(y) * AGV.palletX), yaw: a.yaw - 90 };
}
// 回傳桶中心位置與姿態（robotTcp：手臂 TCP 的世界矩陣，僅 robot 模式需要）
export function drumWorld(k, st, robotTcp) {
  const d = st['drum' + k], pos = new THREE.Vector3(), q = new THREE.Quaternion();
  switch (d.mode) {
    case 'pallet': {
      const pw = palletWorld(st.pallet, st.agv), [sx, sz] = PALLET.slots[d.slot], c = Math.cos(pw.yaw * D2R), s = Math.sin(pw.yaw * D2R);
      pos.set(pw.pos.x + sx * c + sz * s, pw.pos.y + PALLET.H + DRUM.H / 2, pw.pos.z - sx * s + sz * c);
      q.setFromAxisAngle(Yax, (d.yaw + pw.yaw) * D2R); break;
    }
    case 'gantry': {
      const g = st.gantry, a = g.tilt * Math.PI / 2;
      pos.set(g.x + Math.sin(a) * GANTRY.hang, g.y - Math.cos(a) * GANTRY.hang, g.z);
      q.setFromAxisAngle(Zax, a).multiply(_q.setFromAxisAngle(Yax, d.yaw * D2R)); break;
    }
    case 'lying':
      pos.set(d.lx, LYING.y, LYING.z); q.setFromAxisAngle(Zax, Math.PI / 2).multiply(_q.setFromAxisAngle(Yax, d.yaw * D2R)); break;
    case 'upender': {
      const a = -st.upender.tilt * Math.PI / 2, [px, py, pz] = UPENDER.pivot, rx = LYING.upender - px, ry = LYING.y - py;
      pos.set(px + rx * Math.cos(a) - ry * Math.sin(a), py + rx * Math.sin(a) + ry * Math.cos(a), pz);
      q.setFromAxisAngle(Zax, a).multiply(_q.setFromAxisAngle(Zax, Math.PI / 2)).multiply(_q2.setFromAxisAngle(Yax, d.yaw * D2R)); break;
    }
    case 'upright': pos.set(UPRIGHT.x, UPRIGHT.top + DRUM.H / 2, d.uz); q.setFromAxisAngle(Yax, d.yaw * D2R); break;
    case 'out': pos.set(d.ox, OUT.top + DRUM.H / 2, OUT.z); q.setFromAxisAngle(Yax, d.yaw * D2R); break;
    case 'robot': robotTcp.decompose(pos, q, new THREE.Vector3()); break;
  }
  return { pos, q };
}
