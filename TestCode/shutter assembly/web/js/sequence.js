// 單顆組裝流程：本體上料 → 定位取像 → 小葉片 ×2 → 大葉片 ×2 → 上蓋壓合 → 檢查下料
// 狀態由步驟起點快照＋絕對時間求值，任意倒退／跳站都能重建（與 RobotArmPressSSD 相同做法）。
import * as THREE from 'three';
import { LAYOUT, NEST_SEAT, pocket } from './cell.js';
import { PART, BLADES, bladeSeat } from './product.js';

export const smooth = t => t * t * t * (10 + t * (-15 + 6 * t)); // 起停速度與加速度為零
export const STATIONS = ['本體上料', '定位取像', '小葉片', '大葉片', '上蓋壓合', '檢查下料'];
export const SPEC = {
  k: 9,                     // 本循環用到抽屜 A 的第 10 格（前 9 顆已完成、放回原格）
  pressForce: 15, forceLimit: 25,               // 上蓋卡勾壓合力 N（示意，待樣品試壓）
  vFree: 600, vApproach: 30, vContact: 8,        // 直線速度 mm/s
  approach: 2,                                   // 減速接近距離 mm
};
/** 料件在格內／吸嘴上的偏移（mm、度）：上視相機量得、放料前補正。數值為示意 */
export const OFFSETS = {
  base: { x: 0.10, z: 0, a: 0 },     // 夾爪在 z 向自動置中、夾平面時轉角歸零；x 向殘差（< 槽間隙 0.15）由治具推塊消除
  S1: { x: 0.05, z: -0.03, a: 1.1 }, S2: { x: -0.04, z: 0.06, a: -0.8 },
  L1: { x: 0.02, z: 0.04, a: 1.6 }, L2: { x: -0.06, z: -0.02, a: -1.2 }, L2x: { x: 0.08, z: 0.05, a: 2.4 },
  cover: { x: 0.08, z: -0.05, a: 0.6 },
};
const D2R = Math.PI / 180;
const clone = s => JSON.parse(JSON.stringify(s));
const v = (x, y, z) => new THREE.Vector3(x, y, z);
const fmt = n => (n >= 0 ? '+' : '') + n.toFixed(2);

/** 零件料格（依是否示意疊片 NG 決定大葉片 B 的取料格） */
export function slots(ng) {
  const k = SPEC.k;
  return { base: ['base', k], cover: ['cover', k], S1: ['small', 2 * k], S2: ['small', 2 * k + 1], L1: ['large', 2 * k], L2: ['large', ng ? 2 * k + 2 : 2 * k + 1], L2x: ['large', 2 * k + 1] };
}
/** 在治具上（夾緊後）的世界位姿：本體、葉片、上蓋（上蓋 float=1 為卡勾頂住邊緣、0 為壓合到底） */
export function nestPose(id, float = 0) {
  if (id === 'base') return { p: v(NEST_SEAT.x, NEST_SEAT.y, NEST_SEAT.z), yaw: 0 };
  if (id === 'cover') return { p: v(NEST_SEAT.x, NEST_SEAT.y + PART.cover.t + float * PART.cover.float, NEST_SEAT.z), yaw: 0 };
  const b = BLADES.find(x => x.id === id), s = bladeSeat(b);
  return { p: v(NEST_SEAT.x + s.x, NEST_SEAT.y + s.y, NEST_SEAT.z + s.z), yaw: s.yaw };
}
/** 讓吸在工具上、帶偏移 off 的零件落到 (p, yaw) 時，TCP 應在的位置與 yaw */
export function tcpFor(p, yaw, off) {
  const ty = yaw - off.a * D2R, c = Math.cos(ty), s = Math.sin(ty);
  return { p: v(p.x - (off.x * c + off.z * s), p.y, p.z - (-off.x * s + off.z * c)), yaw: ty };
}

export function createSequence({ robot, apply, ng = false }) {
  const S = slots(ng), T = LAYOUT.travel, U = LAYOUT.upCam, B = LAYOUT.ngBin;
  const base = {
    loc: { base: 'tray', S1: 'tray', S2: 'tray', L1: 'tray', L2: 'tray', L2x: 'tray', cover: 'tray' },
    t1: 0, t2: 0, t3: 1, open: 1, clamp: 0, baseShift: 0, float: 1, press: 0, drop: 0, vac: 0, flashUp: 0, flashDown: 0, view: 'down', shot: '',
    zone: 'free', station: 0, action: '', sub: '',
  };
  const steps = [], stationStart = Array(STATIONS.length).fill(0);
  const P = (tcp, p, yaw = 0) => robot.poseFor(tcp, p, yaw);
  const at = (p, y) => v(p.x, y, p.z);
  const lin = (d, speed) => Math.max(0.04, Math.ceil(1.875 * Math.abs(d) / speed * 100) / 100);
  let time = 0, previous = clone(base), lastPose = P('T3', at(pocket('base', SPEC.k - 1), T));
  function add(st, dur, action, sub, values = {}, pose = null, extra = {}) {
    const initial = clone(previous), end = clone(initial);
    for (const [key, value] of Object.entries(values)) end[key] = key === 'loc' ? { ...initial.loc, ...value } : clone(value);
    end.station = st; end.action = action; end.sub = sub;
    const s = { station: st, start: time, dur, action, sub, initial, end, pose0: lastPose, pose1: pose || lastPose, ...extra };
    s.ptp = !!pose && !s.path && !s.contact;
    lastPose = s.pose1; steps.push(s); previous = end; time += dur; return s;
  }
  /** 取料：移至上方（PTP）→ 下降 → 減速接近 → 吸取／夾取 → 上升 */
  function pick(st, tcp, label, where, yaw, id, grabText, tools) {
    const y = where.y;
    add(st, .3, `移至${label}`, `PTP；${tcp === 'T1' ? '葉片吸嘴' : tcp === 'T2' ? '上蓋吸盤' : '本體夾爪'}伸出 12 mm`, { ...tools, zone: 'free' }, P(tcp, at(where, T), yaw));
    add(st, lin(T - y - SPEC.approach, SPEC.vFree), '下降', `直線下降至零件上方 ${SPEC.approach} mm`, {}, P(tcp, at(where, y + SPEC.approach), yaw), { path: true, near: true });
    add(st, lin(SPEC.approach, SPEC.vApproach), '減速接近', `≤ ${SPEC.vApproach} mm/s`, { zone: 'slow' }, P(tcp, at(where, y), yaw), { path: true, near: true });
    add(st, tcp === 'T3' ? .15 : .08, grabText, tcp === 'T3' ? '夾爪閉合、夾持感測 ON' : '真空建立、真空開關 ON', { loc: { [id]: tcp }, ...(tcp === 'T3' ? { open: 0 } : { vac: 1 }) }, null, { near: true });
    add(st, lin(T - y, SPEC.vFree), '上升', '直線上升至移動高度', { zone: 'free' }, P(tcp, at(where, T), yaw), { path: true, near: true });
  }
  /** 放料：移至上方（PTP）→ 下降 → 減速放入 → 放開 → 上升 */
  function place(st, tcp, label, target, yaw, id, releaseText, locValue, moveValues = {}) {
    add(st, .3, `移至${label}`, tcp === 'T3' ? 'PTP' : 'PTP；J4 同步轉到放料角度並補正偏移', { zone: 'free', ...moveValues }, P(tcp, at(target, T), yaw));
    add(st, lin(T - target.y - SPEC.approach, SPEC.vFree), '下降', `直線下降至放料點上方 ${SPEC.approach} mm`, {}, P(tcp, at(target, target.y + SPEC.approach), yaw), { path: true, near: true });
    add(st, lin(SPEC.approach, SPEC.vApproach), '減速放入', id.startsWith('S') || id.startsWith('L') ? '樞軸孔套入 φ0.80 銷、長孔套入撥桿銷' : `≤ ${SPEC.vApproach} mm/s`, { zone: 'slow' }, P(tcp, target, yaw), { path: true, near: true });
    add(st, tcp === 'T3' ? .12 : .06, releaseText, tcp === 'T3' ? '夾爪張開' : '破真空＋微量吹氣', { loc: { [id]: locValue }, ...(tcp === 'T3' ? { open: 1 } : { vac: 0 }) }, null, { near: true });
    add(st, lin(T - target.y, SPEC.vFree), '上升', '先慢後快，避免帶起葉片', { zone: 'free' }, P(tcp, at(target, T), yaw), { path: true, near: true });
  }
  const camAtNest = () => P('cam', v(NEST_SEAT.x, NEST_SEAT.y, NEST_SEAT.z), 0);
  function upShot(st, id, label, yaw, text, done) {
    add(st, .3, `移至上視相機`, `PTP；帶${label}經過相機上方，J4 先轉到放料角度`, { view: 'up' }, P(id === 'cover' ? 'T2' : 'T1', v(U.x, U.focus, U.z), yaw));
    add(st, .05, `上視取像 · ${label}`, '遠心鏡頭＋同軸光頻閃；停留取像', { flashUp: 1, shot: 'up:' + id }, null, { exposure: 'up' });
    add(st, .05, `對位計算 · ${label}`, text, { flashUp: 0 }, null, { done });
  }

  // ---- S0 本體上料 ----
  const pBase = pocket(...S.base);
  pick(0, 'T3', `本體料盤 #${SPEC.k + 1}`, pBase, 0, 'base', '夾取本體', { t1: 0, t2: 0, t3: 1, open: 1 });
  // 本體沒有上視對位：TCP 對準治具槽中心放入，x 向殘差由推塊消除
  place(0, 'T3', '組裝治具', nestPose('base').p.clone().add(v(0.15, 0, 0.15)), 0, 'base', '放開本體', 'nest');
  add(0, .2, '側推夾緊', '+x、+z 推塊把本體推靠基準邊；治具真空 ON', { clamp: 1, baseShift: 1 }, null, { done: 'base' });

  // ---- S1 定位取像 ----
  add(1, .3, '下視相機移至治具', 'PTP；工具全部縮回', { t3: 0, view: 'down' }, camAtNest());
  add(1, .06, '下視取像 · 樞軸銷', '環形光頻閃；找出 2 支 φ0.80 樞軸銷與 2 支撥桿銷', { flashDown: 1, shot: 'down:pins' }, null, { exposure: 'down' });
  add(1, .06, '計算 4 片葉片目標', '本體位置 Δx −0.15、Δz −0.15（已靠基準）；撥桿銷在停靠位', { flashDown: 0 }, null, { done: 'locate' });

  // ---- S2／S3 葉片 ----
  function blade(st, b, id = b.id) {
    const [kind, idx] = S[id], off = OFFSETS[id], seat = nestPose(b.id), p = pocket(kind, idx);
    const onTool = { x: off.x, z: off.z, a: off.a };
    // 吸嘴對準格中心；料在格內的偏移 off 要到上視相機才量得
    pick(st, 'T1', `${b.name.slice(0, 3)}盤 #${idx + 1}`, v(p.x, p.y + (id === 'L2x' ? PART.blade.t : 0), p.z), 0, id, '真空吸取', { t1: 1, t2: 0, t3: 0 });
    if (id === 'L2x') {
      upShot(st, id, b.name, seat.yaw, '偵測到兩片黏疊（厚度與輪廓異常）→ 判定 NG', 'judgeNG');
      add(st, .3, '移至 NG 盒', 'PTP；疊片不組裝', { view: 'down' }, P('T1', v(B.x, B.top + 25, B.z), seat.yaw));
      add(st, .08, '吹落 NG 料', '破真空＋吹氣', { loc: { L2x: 'fall' }, vac: 0 }, null);
      const dropHeight=B.top+25-(LAYOUT.table+2+PART.blade.t*2);
      add(st, Math.sqrt(2*dropHeight/9810), 'NG 料落入盒內', '自由落下完成後再離開，避免零件瞬間移到盒底', {drop:1,loc:{L2x:'bin'}}, null, {done:'reject'});
      return;
    }
    upShot(st, id, b.name, seat.yaw, `樞軸孔 Δx ${fmt(onTool.x)}、Δz ${fmt(onTool.z)} mm、θ ${fmt(onTool.a)}° → 補正放料位置`, 'shot' + id);
    const t = tcpFor(seat.p, seat.yaw, off);
    place(st, 'T1', `治具 · ${b.name}`, t.p, t.yaw, id, '放開葉片', 'base', { view: 'down' });
    steps[steps.length - 1].done = 'place' + id;
  }
  const check = (st, ids, done, text) => {
    add(st, .3, '下視相機移至治具', 'PTP', { t1: 0, view: 'down' }, camAtNest());
    add(st, .06, `下視檢查 · ${ids}`, '確認葉片套入樞軸銷、疊放順序與無翹起', { flashDown: 1, shot: 'down:' + done }, null, { exposure: 'down' });
    add(st, .05, `判定 ${ids}`, text, { flashDown: 0 }, null, { done });
  };
  blade(2, BLADES[0]); blade(2, BLADES[1]);
  check(2, '小葉片 A、B', 'checkS', '2 片貼平、孔位在銷上 → OK');
  blade(3, BLADES[2]);
  if (ng) blade(3, BLADES[3], 'L2x');
  blade(3, BLADES[3]);
  check(3, '4 片葉片', 'checkL', '4 片疊放順序正確、無疊片或漏片 → OK');

  // ---- S4 上蓋壓合 ----
  const pCover = pocket(...S.cover), offC = OFFSETS.cover;
  pick(4, 'T2', `上蓋料盤 #${SPEC.k + 1}`, pCover, 0, 'cover', '真空吸取上蓋', { t1: 0, t2: 1, t3: 0 });
  upShot(4, 'cover', '上蓋', 0, `外形與光圈 Δx ${fmt(offC.x)}、Δz ${fmt(offC.z)} mm、θ ${fmt(offC.a)}° → 補正`, 'shotcover');
  const seatC = nestPose('cover', 1), tc = tcpFor(seatC.p, 0, offC);
  add(4, .3, '移至治具 · 上蓋', 'PTP；J4 補正角度', { view: 'down' }, P('T2', at(tc.p, T), tc.yaw));
  add(4, lin(T - tc.p.y - SPEC.approach, SPEC.vFree), '下降', '直線下降至上蓋卡勾接觸前 2 mm', {}, P('T2', at(tc.p, tc.p.y + SPEC.approach), tc.yaw), { path: true, near: true });
  add(4, lin(SPEC.approach, SPEC.vApproach), '放上蓋', '卡勾頂在本體邊緣（浮高 0.5 mm）', { zone: 'slow', loc: { cover: 'base' } }, P('T2', tc.p, tc.yaw), { path: true, near: true });
  const down = PART.cover.float + 0.3;
  add(4, lin(down, SPEC.vContact), `壓合 ${SPEC.pressForce} N`, '荷重元監看力對行程；4 個卡勾扣入側邊', { float: 0, press: 1, zone: 'contact' }, P('T2', v(tc.p.x, tc.p.y - down, tc.p.z), tc.yaw), { path: true, contact: true });
  add(4, .3, '保壓', `力值 ${SPEC.pressForce} N、行程到底 → 卡合確認`, {}, null, { contact: true });
  add(4, .06, '破真空', '上蓋留在本體上', { vac: 0 }, null, { contact: true });
  add(4, lin(T - tc.p.y + down, SPEC.vFree), '上升', '壓墊離開', { press: 0, zone: 'free' }, P('T2', at(tc.p, T), tc.yaw), { path: true, near: true, done: 'press' });

  // ---- S5 檢查下料 ----
  add(5, .3, '下視相機移至治具', 'PTP', { t2: 0, view: 'down' }, camAtNest());
  add(5, .06, '成品取像', '上蓋平貼、4 卡勾到位、光圈淨空無葉片外露', { flashDown: 1, shot: 'down:final' }, null, { exposure: 'down' });
  add(5, .05, '成品判定 OK', '結果寫入紀錄（示意）', { flashDown: 0 }, null, { done: 'final' });
  add(5, .15, '鬆開夾緊', '推塊退回、治具真空 OFF', { clamp: 0 });
  const baseTop = v(NEST_SEAT.x, NEST_SEAT.y, NEST_SEAT.z);
  pick(5, 'T3', '治具取成品', baseTop, 0, 'base', '夾取成品', { t1: 0, t2: 0, t3: 1, open: 1 });
  place(5, 'T3', `料盤 #${SPEC.k + 1}（放回原格）`, pBase, 0, 'base', '放開成品', 'out');
  steps[steps.length - 1].done = 'out';

  // ---- 關節規劃與時間重排 ----
  robot.plan(steps.flatMap(s => [s.pose0, s.pose1]));
  time = 0; stationStart.fill(0);
  const seen = new Set();
  for (const s of steps) {
    if (s.ptp) s.dur = Math.max(s.dur, Math.ceil(robot.ptpTime(s.pose0, s.pose1) * 20) / 20);
    if (!seen.has(s.station)) { seen.add(s.station); stationStart[s.station] = time; }
    s.start = time; time += s.dur;
  }
  const DISCRETE = new Set(['station', 'flashUp', 'flashDown', 'vac']);
  function sample(sec) {
    sec = Number.isFinite(sec) ? THREE.MathUtils.clamp(sec, 0, time) : 0;
    const index = steps.findIndex(s => sec < s.start + s.dur), idx = index < 0 ? steps.length - 1 : index, s = steps[idx];
    const t = THREE.MathUtils.clamp((sec - s.start) / s.dur, 0, 1), e = smooth(t), state = clone(s.initial);
    for (const [key, value] of Object.entries(s.end)) {
      if (typeof value === 'number' && typeof s.initial[key] === 'number' && !DISCRETE.has(key)) state[key] = THREE.MathUtils.lerp(s.initial[key], value, key==='drop'?t:e);
      else state[key] = clone(value);
    }
    // 零件的歸屬在該步驟完成時才改變（吸取／放開的瞬間），位置因此連續
    if (t < 1) state.loc = clone(s.initial.loc);
    // 自由移位走關節插值（PTP）；下降、接近、上升走直線
    const p = s.path ? { tcp: s.pose1.tcp, target: s.pose0.target.clone().lerp(s.pose1.target, e), yaw: s.pose1.yaw, ref: s.pose0 }
      : s.ptp ? { ptp: { from: s.pose0, to: s.pose1, e } } : s.pose1;
    robot.setPose(p); robot.goal.speed = s.contact ? 60 : 2000;
    apply(state);
    const completed = new Set(steps.slice(0, idx).map(x => x.done).filter(Boolean)); if (t === 1 && s.done) completed.add(s.done);
    return { state, step: s, index: idx, t, completed };
  }
  return { sample, steps, total: time, stationStart, base, slots: S };
}
