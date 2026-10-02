// 動畫排程：每台設備與每個桶各有一條時間軌，依站位占用（流水線阻塞）推算交接時刻。
// 任一時刻的畫面完全由絕對時間決定，倒退、跳站與連續播放結果一致。
import * as THREE from 'three';
import { RACK, PALLET, DRUM, AGV, FORK, AISLE, PALLET_STATION, GANTRY, LYING, LABEL, UPENDER, UPRIGHT, DECAP, BOOTH, WASTE, INBOUND } from './layout.js';
import { jibPoint, jibTarget, DOLLY_H } from './inbound.js';
import { smooth, D2R } from './parts.js';
import { JOINTS, SPEED } from './robot.js';

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

export const STATIONS = [
  { id: 'inbound', name: '散桶入庫', short: 'S0' }, { id: 'agv', name: '倉儲／AGV', short: 'S1' }, { id: 'gantry', name: '龍門上料', short: 'S2' },
  { id: 'label', name: '貼標讀碼', short: 'S3' }, { id: 'upender', name: '90° 翻桶', short: 'S4' }, { id: 'decap', name: '自動開蓋', short: 'S5' },
  { id: 'robot', name: '手臂清洗', short: 'S6' }, { id: 'waste', name: '廢液回收', short: 'S7' },
];
export const DRUM_IDS = [1, 2, 3, 4].map(i => `CTW-2610-${String(i).padStart(4, '0')}`);
export const IN_IDS = [101, 102, 103, 104].map(i => `CTW-2610-${String(i).padStart(4, '0')}`);
// 時間軌名稱：產線 4 桶＋入庫 4 桶
export const DRUM_KEYS = [...DRUM_IDS.map((_, k) => 'drum' + k), ...IN_IDS.map((_, k) => 'in' + k)];
const YAW0 = [37, 151, 263, 312], YAW_IN = [12, 205, 98, 300];
// 每次沖洗時間：兩支噴槍同時進水（2" 旋轉噴頭＋3/4" 直噴）
export const SPRAY_S = WASTE.rinseL / (BOOTH.flow.big + BOOTH.flow.small) * 60;
export const SPRAY_SINGLE_S = WASTE.rinseL / BOOTH.flow.big * 60;

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
  // lance：0 收回、1 噴洗深度、BOOTH.suckExt 伸到桶底抽液；lance2 為 3/4" 直噴頭
  const booth = track('booth', { lance: 0, lance2: 0, spray: false, vac: false, src: 'R', pour: '', pool: 0 });   // pour：倒液中的桶序（字串，不插值）
  const sump = track('sump', { level: 0, pump: false, dest: 'W' });
  const makeup = track('makeup', { on: false });   // TK-F 液位控制補水（廠務自來水／RO）
  const tanks = track('tanks', { W: WASTE.tanks.W.init, R: WASTE.tanks.R.init, F: WASTE.tanks.F.init });
  const jib = track('jib', { a: INBOUND.jib.park, r: 700, y: 2000, clamp: 0 });
  const dolly = track('dolly', { x: INBOUND.dolly.x0 });
  const drums = DRUM_IDS.map((id, k) => track('drum' + k, { mode: 'pallet', slot: k, yaw: YAW0[k], lx: LYING.place, uz: UPRIGHT.z0, water: 0, capBig: true, capSmall: true, label: false, labelAng: 0, read: false, rinse: 0, dry: false, state: '倉儲' }));
  const inDrums = IN_IDS.map((id, k) => track('in' + k, { mode: 'hidden', slot: 0, yaw: YAW_IN[k], water: 0, capBig: true, capSmall: true, label: false, labelAng: 0, read: false, rinse: 0, dry: false, state: '廠外待入' }));
  const events = [];
  const ev = (s, station, label) => { events.push({ time: s.start, station, label: label || s.action }); return s; };

  // ================================================================ S1 AGV 取料：第 2 道第 2 層前位
  const laneX = RACK.lanes[RACK.demo.lane], rail = RACK.levels[RACK.demo.level], pivotRack = RACK.pos[0] + AGV.palletX, pivotStation = PALLET_STATION.z - AGV.palletX;
  const move = (to, o) => { const s = agv.state, d = Math.hypot(to.x - s.x, to.z - s.z); return agv.add(o.dur ?? d / (o.speed ?? AGV.speed) + 1.2, { ...to, moving: true }, o); };
  const turn = (yaw, extra = {}, o = {}) => agv.add(Math.abs(yaw - agv.state.yaw) / AGV.turn + .8, { yaw, moving: true, ...extra }, o);
  const fork = (v, o = {}) => agv.add(Math.abs(v - agv.state.fork) / AGV.lift + .5, { fork: v, moving: false }, o);
  // 入庫弧線：走道中心線（朝西）⇄ 西側入庫通道（朝北），以圓弧行駛；reverse 為倒車原路退出
  const acx = INBOUND.arcStart[0], acz = INBOUND.arcEnd[1], AR = INBOUND.arc, arcDur = AR * Math.PI / 2 / AGV.slow * .9 + 1.5;
  const arcPose = a => ({ x: acx - AR * Math.sin(a), z: acz + AR * Math.cos(a), yaw: 180 - a / D2R });
  const arc = (reverse, o) => agv.add(arcDur, { moving: true }, { ...o, motion: e => arcPose((reverse ? 1 - e : e) * Math.PI / 2) });
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
  agv.add(.5, { moving: false }, { action: '走道待命', sub: '等待龍門取完 4 桶，空棧板送往入庫站' });

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
  const dep = []; let upFree = 0, robotFree = 0, robotStart = null, tPickedClear = 0;
  const travelLy = d => Math.abs(d) / LYING.speed + 1, travelUp = d => Math.abs(d) / UPRIGHT.speed + 1;
  // 機器人位姿（固定物件，關節解快取在物件上）
  const V = (x, y, z) => new THREE.Vector3(x, y, z), E = V(1, 0, 0), S = V(0, 0, 1), UP = V(0, 1, 0), cy = UPRIGHT.top + DRUM.H / 2;
  // 抽殘水姿態：桶身朝 2" 桶口側傾 BOOTH.suckTilt，讓殘水集中到桶口正下方；以 2" 桶口不動為旋轉點
  const suckPose = (() => {
    const base = robot.poseDrum(V(...BOOTH.drum), UP, S), tilt = robot.poseDrum(V(...BOOTH.drum), UP, S, -BOOTH.suckTilt * D2R);
    const bung = V(DRUM.bungR, DRUM.H / 2 - 4, 0);
    const c = V(...BOOTH.drum).add(bung.clone().applyQuaternion(base.rot)).sub(bung.clone().applyQuaternion(tilt.rot));
    return robot.poseDrum(c, UP, S, -BOOTH.suckTilt * D2R);
  })();
  const P = {
    // 張開的夾爪前緣在桶中心前約 210 mm；退到 600 mm 外才不會碰到在取桶位等候的下一桶
    wait: robot.poseDrum(V(UPRIGHT.x - 600, cy, UPRIGHT.pick), UP, E),   // 與取桶預備點同高（再抬高腕部會太靠近基座）
    pre: robot.poseDrum(V(UPRIGHT.x - 600, cy, UPRIGHT.pick), UP, E),
    pick: robot.poseDrum(V(UPRIGHT.x, cy, UPRIGHT.pick), UP, E),
    lift: robot.poseDrum(V(UPRIGHT.x, cy + 250, UPRIGHT.pick), UP, E),
    // 過渡點：沖洗站東北外側，桶身留在圍籬內、隔間北面之外；進出沖洗站都經過這裡
    via: robot.poseDrum(V(10300, 1600, 13250), UP, V(1, 0, 1).normalize()),
    entry: robot.poseDrum(V(BOOTH.drum[0], 1600, BOOTH.entryZ), UP, S),
    u: robot.poseDrum(V(...BOOTH.drum), UP, S),
    pour: robot.poseDrum(V(...BOOTH.drum), UP, S, 190 * D2R),
    suck: suckPose,
    above: robot.poseDrum(V(UPRIGHT.x, cy + 250, UPRIGHT.place), UP, E),
    place: robot.poseDrum(V(UPRIGHT.x, cy, UPRIGHT.place), UP, E),
    retract: robot.poseDrum(V(UPRIGHT.x - 600, cy, UPRIGHT.place), UP, E),
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

  for (let k = 0; k < 4; k++) {
    const d = drums[k], [sx, sz] = PALLET.slots[k], px = PALLET_STATION.x - sx, pz = PALLET_STATION.z - sz, prev = dep[k - 1] || {};   // 棧板站上棧板轉了 180°
    const id = DRUM_IDS[k];
    // ---- S2 龍門：取桶 → 抬升 → 移出棧板範圍 → 等放料位空 → 邊移邊翻 90° → 放上 V 槽輥
    gantry.hold(tAgvOut + 1);
    const g0 = gantry.add(Math.hypot(px - gantry.state.x, pz - gantry.state.z) / 600 + 1.2, { x: px, z: pz, y: gp.safeY, tilt: 0, jaw: 0 }, { action: `移至第 ${k + 1} 桶上方`, sub: id });
    if (k === 0) ev(g0, 'gantry', '龍門開始上料');
    gantry.add(2, { y: gp.pickY }, { action: '下降夾桶位', sub: '雙弧形 PU 爪由南北兩側包覆桶身上半部' });
    gantry.add(1, { jaw: 1 }, { action: '夾爪夾緊', sub: '夾持確認後才抬升' });
    d.add(0, { mode: 'gantry', yaw: d.state.yaw + 180, state: '龍門夾持' }, { at: gantry.t });
    gantry.add(2, { y: gp.safeY }, { action: '抬升至安全高度', sub: `翻轉軸 ${gp.safeY} mm；桶底高於相鄰桶頂` });
    gantry.add(1.5, { x: 4900 }, { action: '沿 X 移出棧板範圍', sub: '先平移再翻轉，避免掃到相鄰桶' });
    tPickedClear = gantry.t;
    gantry.hold(prev.place != null ? prev.place + 3.2 : 0);
    ev(gantry.add(3.5, { x: placePivot, z: LYING.z, tilt: 1 }, { action: '邊移邊翻轉 90°', sub: '桶頂朝西、桶底朝東（配合翻桶機方向）' }), 'gantry', `${id} 翻轉放倒`);
    gantry.add(2.5, { y: gp.placeY }, { action: '下降至 V 槽滾輪', sub: `水平沙漏形滾輪，桶中心高 ${LYING.y} mm` });
    gantry.add(1, { jaw: 0 }, { action: '夾爪鬆開' });
    d.add(0, { mode: 'lying', lx: LYING.place, state: '橫躺輸送' }, { at: gantry.t });
    gantry.add(2, { y: gp.safeY }, { action: '夾爪上升', sub: '放料位交給輸送' });
    const r = { placed: gantry.t };
    if (k === 3) gantry.add(3, { x: gp.home.x, z: gp.home.z, tilt: 0 }, { action: '回原點', sub: '4 桶上料完成' });

    // ---- 輸送：放料位 → 貼標站
    r.place = Math.max(r.placed, prev.label ?? 0);
    d.add(travelLy(LYING.label - LYING.place), { lx: LYING.label, state: '往貼標站' }, { at: r.place });
    // ---- S3 貼標＋讀碼
    labeler.hold(d.t);
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

    // ---- S6 手臂清洗：從取桶位取下 → 沖洗站 → 放回同一條線的放回位
    const tRobot = Math.max(tAtPick, robotFree);
    if (robotStart == null) robotStart = tRobot;
    const a0 = rAdd('lin', P.pre, 1.2, { at: tRobot, action: '接近取桶位', sub: '夾爪張開，沿 +X 前進' });
    if (k === 0) events.push({ time: a0.start, station: 'robot', label: '手臂開始取桶' });
    rAdd('lin', P.pick, 1.6, { action: '夾爪包覆桶身' });
    grip.hold(rt); grip.add(1, { jaw: 1 }, { action: '夾爪夾緊' }); rt = grip.t;
    d.add(0, { mode: 'robot', state: '手臂夾持' }, { at: rt });
    rAdd('lin', P.lift, 1, { action: '抬升 250 mm', sub: '桶底高過輸送側導引' });
    r.pick = rt;
    rAdd('ptp', P.via, null, { action: '移到沖洗站東北過渡點', sub: '桶身避開圍籬東南角與隔間' });
    rAdd('ptp', P.entry, null, { action: '轉向沖洗站', sub: '關節同步插值（PTP），桶身停在隔間開口外' });
    const en = rAdd('lin', P.u, 1.8, { action: '送入沖洗站', sub: '2" 與 3/4" 桶口對準兩支噴槍' });
    events.push({ time: en.start, station: 'robot', label: `${id} 進入沖洗站` });
    for (let c = 1; c <= 3; c++) {
      const src = c === 1 ? 'R' : 'F', dest = c < 3 ? 'W' : 'R';
      booth.hold(rt);
      booth.add(1, { lance: 1, lance2: 1, src }, { action: `第 ${c} 次沖洗：兩支噴槍伸入桶口`, sub: '2" 旋轉噴頭、3/4" 直噴頭同時伸入約 140 mm' });
      const sp = booth.add(SPRAY_S, { spray: true }, { action: `第 ${c} 次沖洗：雙孔同時進水 ${SPRAY_S.toFixed(1)} s`, sub: `${WASTE.rinseL} L ＝ 2" ${BOOTH.flow.big}＋3/4" ${BOOTH.flow.small} L/min（單孔需 ${SPRAY_SINGLE_S.toFixed(0)} s）；水源 ${src === 'R' ? 'TK-R 回收水' : 'TK-F 清水'}` });
      if (c === 1 && k === 0) events.push({ time: sp.start, station: 'waste', label: '沖洗水由 TK-R 供應' });
      d.add(0, { rinse: c, state: `第 ${c} 次沖洗` }, { at: sp.start }); d.add(SPRAY_S, { water: WASTE.rinseL }, { at: sp.start });
      tanks.add(SPRAY_S, { [src]: tanks.state[src] - WASTE.rinseL }, { at: sp.start, action: `P-1 供水 ${src === 'R' ? 'TK-R' : 'TK-F'} → 噴槍` });
      if (src === 'F') { tanks.add(4, { F: tanks.state.F + WASTE.rinseL }, { at: sp.start + SPRAY_S, action: 'TK-F 液位補水' }); makeup.add(4, { on: true }, { at: sp.start + SPRAY_S, action: '廠務清水補入 TK-F' }); makeup.add(0, { on: false }); }
      booth.add(1, { spray: false, lance: 0, lance2: 0 }, { action: '噴槍退回' });
      rt = booth.t;
      rAdd('path', null, 5, { motion: shakeAt, action: `第 ${c} 次搖晃`, sub: '繞夾爪軸來回滾轉 ±25°，殘液沖刷桶壁' });
      rAdd('lin', P.pour, 2.2, { action: `第 ${c} 次倒液：翻轉 190°`, sub: '2" 桶口轉到最低點出水，3/4" 在上方當通氣口' });
      booth.hold(rt);
      const pr = booth.add(BOOTH.pourS, { pour: String(k), pool: 1 }, { action: `倒入集液漏斗 → ${dest === 'W' ? 'TK-W 廢液槽' : 'TK-R 回收槽'}`, sub: `3/4" 通氣不咕嚕，約 ${BOOTH.pourS} s（不通氣約 ${BOOTH.pourNoVentS} s）` });
      d.add(BOOTH.pourS, { water: c < 3 ? 0 : BOOTH.residualL }, { at: pr.start });
      if (k === 0 && c === 1) ev(pr, 'waste', '倒液進集液漏斗');
      sump.add(BOOTH.pourS, { level: 1, dest }, { at: pr.start });
      booth.add(.1, { pour: '', pool: 0 });
      const pm = sump.add(3, { pump: true, level: 0 }, { action: `P-2 送液 → ${dest === 'W' ? 'TK-W' : 'TK-R'}`, sub: 'V-3 三通閥切換去向' });
      tanks.add(3, { [dest]: tanks.state[dest] + WASTE.rinseL }, { at: pm.start, action: `集液槽 → ${dest === 'W' ? 'TK-W' : 'TK-R'}` });
      if (k === 0 && c === 3) ev(pm, 'waste', '末道沖洗水回收至 TK-R');
      sump.add(0, { pump: false });
      rt = Math.max(rt, pr.start + BOOTH.pourS);
      if (c < 3) rAdd('lin', P.u, 2, { action: '轉回桶口朝上' });
    }
    // ---- 末道倒液後：轉正微傾，2" 噴槍伸到桶底，以負壓抽乾殘水
    rAdd('path', null, 2, { motion: () => P.pour, action: '倒置滴乾', sub: '桶口朝下停留 2 s' });
    rAdd('lin', P.suck, 2.4, { action: '轉正並朝 2" 側微傾', sub: `傾 ${BOOTH.suckTilt}°，殘水集中到 2" 桶口正下方` });
    booth.hold(rt);
    booth.add(2.2, { lance: BOOTH.suckExt }, { action: '抽液管伸到桶底', sub: '2" 噴槍長行程伸入，吸口距桶底約 15 mm' });
    const vs = booth.add(BOOTH.vacS, { vac: true }, { action: '負壓抽乾殘水', sub: `真空泵 VP-1 抽約 ${BOOTH.residualL} L 殘水 → 集液槽 → TK-R；目標殘水 < 50 mL` });
    if (k === 0) ev(vs, 'waste', '負壓抽乾桶內殘水');
    d.add(BOOTH.vacS, { water: 0, dry: true }, { at: vs.start });
    sump.add(BOOTH.vacS, { level: .3, dest: 'R' }, { at: vs.start });
    booth.add(2, { vac: false, lance: 0 }, { action: '抽液管收回' });
    sump.add(1.5, { pump: true, level: 0 }, { action: 'P-2 送液 → TK-R' }); sump.add(0, { pump: false });
    rt = booth.t;
    rAdd('lin', P.u, 1.5, { action: '轉正' });
    d.add(0, { state: '清洗完成' }, { at: rt });
    rAdd('lin', P.entry, 1.6, { action: '退出沖洗站' });
    r.placeFree = prev.handoff ?? 0;
    rAdd('ptp', P.via, null, { action: '退到過渡點', sub: '先離開隔間東北角再轉回產線' });
    rAdd('ptp', P.above, null, { at: r.placeFree, action: '轉回產線放回位', sub: '關節同步插值（PTP）' });
    rAdd('lin', P.place, 1.2, { action: '下降放回輸送線' });
    grip.hold(rt); grip.add(.8, { jaw: 0 }, { action: '夾爪鬆開' }); rt = grip.t;
    d.add(0, { mode: 'upright', uz: UPRIGHT.place, yaw: 90, state: '已洗淨' }, { at: rt });
    ev(rAdd('lin', P.retract, 1, { action: '夾爪退出' }), 'robot', `${id} 放回輸送線`);
    d.add(travelUp(UPRIGHT.handoff - UPRIGHT.place), { uz: UPRIGHT.handoff, state: '送往裝填區' }, { at: rt });
    r.handoff = d.t;
    d.add(2.5, { state: '交裝填區' });
    d.add(0, { mode: 'gone' });
    rAdd('ptp', P.wait, null, { action: '回到取桶等待點', vf: .7 });
    robotFree = rt;
    dep.push(r);
  }

  // ================================================================ AGV：空棧板 → 入庫站；散桶上棧板；滿棧板入架
  const ib = INBOUND, pivotInbound = ib.z + AGV.palletX, putX = RACK.lanes[RACK.putaway.lane], putRail = RACK.levels[RACK.putaway.level];
  agv.hold(tPickedClear + 1);
  ev(move({ x: PALLET_STATION.x, z: pivotStation }, { speed: AGV.slow, action: '駛入棧板站取空棧板', sub: '光柵屏蔽；龍門已離開棧板範圍' }), 'agv', 'AGV 取空棧板送入庫站');
  agv.add(.4, { fork: PALLET_STATION.stand + FORK.deck, moving: false }, { action: '貨叉接觸空棧板' });
  pallet.add(0, { mode: 'agv' }, { at: agv.t });
  agv.add(.5, { fork: PALLET_STATION.stand + FORK.lifted }, { action: '抬起空棧板' });
  move({ x: PALLET_STATION.x, z: AISLE.zc }, { speed: AGV.slow, action: '倒車退出龍門區' });
  turn(180, {}, { action: '原地轉向西' });
  move({ x: ib.arcStart[0], z: AISLE.zc }, { speed: AGV.slow, action: '倒車到入庫弧線起點', sub: '沿走道中心線往東倒退' });
  arc(false, { action: '弧線右轉進入西側入庫通道', sub: `半徑 ${AR} mm；最西一道只做 3 深讓出轉彎空間` });
  move({ x: ib.x, z: pivotInbound }, { speed: AGV.slow, action: '低速駛向入庫站' });
  agv.add(.4, { fork: ib.stand + FORK.deck, moving: false }, { action: '空棧板落座' });
  pallet.add(0, { mode: 'inbound' }, { at: agv.t });
  const tPalletAtInbound = agv.t;
  agv.add(.5, { fork: ib.stand + FORK.deck - 60 }, { action: '貨叉脫離' });
  move({ x: ib.x, z: ib.arcEnd[1] }, { speed: AGV.slow, action: '倒車退出' });
  arc(true, { action: '倒車沿弧線退回走道', sub: '讓出入庫作業區給作業員與懸臂吊' });
  agv.add(.5, { moving: false }, { action: '走道待命', sub: '等待 4 個散桶上棧板' });

  // ---- S0 散桶入庫：台車推入 → 懸臂吊夾桶 → 放上棧板（先放遠側兩格）
  const dropAt = jibTarget(ib.dolly.x1, ib.dolly.z), dollyY = DOLLY_H + DRUM.H / 2, deckY = ib.stand + PALLET.H + DRUM.H / 2, carryY = deckY + 220;
  const order = [2, 3, 0, 1];
  dolly.hold(Math.max(tPalletAtInbound - 6, 0)); jib.hold(agv.t);
  IN_IDS.forEach((id, i) => {
    const d = inDrums[i], slot = order[i], [sx, sz] = PALLET.slots[slot], to = jibTarget(ib.x + sx, ib.z + sz);
    d.add(0, { mode: 'dolly', state: '台車推入' }, { at: dolly.t });
    const dm = dolly.add((ib.dolly.x1 - ib.dolly.x0) / 500 + 1, { x: ib.dolly.x1 }, { action: `台車推入 ${id}`, sub: '作業員由西牆捲門推入（散桶，未開蓋）' });
    if (i === 0) ev(dm, 'inbound', '散桶入庫：台車推入');
    jib.hold(dolly.t);
    jib.add(2.5, { a: dropAt.a, r: dropAt.r, y: dollyY + 300, clamp: 0 }, { action: '懸臂吊移到台車上方' });
    jib.add(1.2, { y: dollyY }, { action: '夾具下降套住桶頂 L 環' });
    jib.add(.8, { clamp: 1 }, { action: '夾具夾緊' });
    d.add(0, { mode: 'jib', state: '懸臂吊搬運' }, { at: jib.t });
    jib.add(1.5, { y: carryY }, { action: '吊起', sub: '桶底高過棧板 220 mm' });
    dolly.hold(jib.t); dolly.add((ib.dolly.x1 - ib.dolly.x0) / 700 + 1, { x: ib.dolly.x0 }, { action: '台車回門外取下一桶' });
    const sw = jib.add(Math.abs(to.a - jib.state.a) / 45 + Math.abs(to.r - jib.state.r) / 800 + 1.2, { a: to.a, r: to.r }, { action: `旋臂到棧板第 ${slot + 1} 格`, sub: '先放遠側兩格，近側兩格不必越過' });
    if (i === 0) ev(sw, 'inbound', '懸臂吊上棧板');
    jib.add(1.2, { y: deckY }, { action: '放下' });
    jib.add(.6, { clamp: 0 }, { action: '鬆開夾具' });
    d.add(0, { mode: 'pallet', slot, state: '入庫棧板' }, { at: jib.t });
    jib.add(1, { y: carryY + 150 }, { action: '夾具上升' });
  });
  jib.add(3, { a: ib.jib.park, r: 700, y: 2000 }, { action: '懸臂吊回待命', sub: '手臂朝西讓出 AGV 通道' });
  // AGV 取滿棧板 → 第 3 道底層前位
  agv.hold(jib.t);
  ev(arc(false, { action: '弧線轉入入庫通道', sub: '取 4 桶滿棧板' }), 'inbound', 'AGV 取滿棧板入架');
  move({ x: ib.x, z: pivotInbound }, { speed: AGV.slow, action: '低速插入棧板' });
  agv.add(.4, { fork: ib.stand + FORK.deck, moving: false }, { action: '貨叉接觸棧板' });
  pallet.add(0, { mode: 'agv' }, { at: agv.t });
  agv.add(.5, { fork: ib.stand + FORK.lifted }, { action: '抬起滿棧板' });
  move({ x: ib.x, z: ib.arcEnd[1] }, { speed: AGV.slow, action: '倒車退出' });
  arc(true, { action: '倒車沿弧線退回走道' });
  move({ x: putX, z: AISLE.zc }, { speed: AGV.slow, action: `倒車到第 ${RACK.putaway.lane + 1} 道前` });
  turn(90, { fork: putRail + FORK.lifted }, { action: '原地轉向北', sub: `第 ${RACK.putaway.lane + 1} 道底層前位` });
  move({ x: putX, z: pivotRack }, { speed: AGV.slow, action: '低速入道' });
  agv.add(.4, { fork: putRail + FORK.deck, moving: false }, { action: '棧板落軌' });
  pallet.add(0, { mode: 'putaway' }, { at: agv.t });
  ev(agv.add(.5, { fork: putRail + FORK.deck - 60 }, { action: '貨叉脫離', sub: '入庫完成；穿梭車可再往深處送' }), 'agv', '入庫上架完成');
  IN_IDS.forEach((_, i) => inDrums[i].add(0, { state: '已入架' }, { at: agv.t }));
  move({ x: putX, z: AISLE.zc }, { speed: AGV.slow, action: '倒車退出' });
  fork(AGV.travel, { action: '貨叉降至行駛高度' });
  turn(0, {}, { action: '原地轉向東' });
  move({ x: RACK.lanes[3], z: AISLE.zc }, { action: '行駛至柱旁東道前', sub: '柱前不能原地迴轉' });
  turn(-180, {}, { action: '原地轉向西' });
  ev(move({ x: AGV.charger.x, z: AGV.charger.z }, { action: '回充電板', sub: '柱前走道中心線，地面接觸式充電' }), 'agv', 'AGV 回充電板');
  agv.add(.5, { moving: false }, { action: '待命：充電中' });

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
  const at = (x, y, z, yaw) => ({ pos: new THREE.Vector3(x, y, z), yaw });
  if (p.mode === 'rack') return at(RACK.lanes[RACK.demo.lane], RACK.levels[RACK.demo.level] + p.lift * RACK.shuttleLift, RACK.pos[0], 0);
  if (p.mode === 'station') return at(PALLET_STATION.x, PALLET_STATION.stand, PALLET_STATION.z, 180);
  if (p.mode === 'inbound') return at(INBOUND.x, INBOUND.stand, INBOUND.z, 0);
  if (p.mode === 'putaway') return at(RACK.lanes[RACK.putaway.lane], RACK.levels[RACK.putaway.level], RACK.pos[0], 0);
  const a = agvState, y = a.yaw * D2R;
  // 棧板在車道內朝向 0°，AGV 朝北（90°）叉起，所以棧板方位 = AGV 方位 − 90°
  return at(a.x + Math.cos(y) * AGV.palletX, a.fork - FORK.deck, a.z - Math.sin(y) * AGV.palletX, a.yaw - 90);
}
// 回傳桶中心位置與姿態（key：drum0–3、in0–3；robotTcp：手臂 TCP 的世界矩陣，僅 robot 模式需要）
export function drumWorld(key, st, robotTcp) {
  const d = st[typeof key === 'number' ? 'drum' + key : key], pos = new THREE.Vector3(), q = new THREE.Quaternion();
  switch (d.mode) {
    case 'hidden': case 'gone': return { pos: pos.set(0, -5000, 0), q, hidden: true };
    case 'dolly': pos.set(st.dolly.x, DOLLY_H + DRUM.H / 2, INBOUND.dolly.z); q.setFromAxisAngle(Yax, d.yaw * D2R); break;
    case 'jib': pos.copy(jibPoint(st.jib.a, st.jib.r, st.jib.y)); q.setFromAxisAngle(Yax, d.yaw * D2R); break;
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
    case 'robot': robotTcp.decompose(pos, q, new THREE.Vector3()); break;
  }
  return { pos, q };
}
