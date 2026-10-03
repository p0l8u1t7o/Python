// 由配方自動產生的單盤流程：進板定位 → 全局定位 → 壓合 → 相機檢查 → 補壓判定 → 出板
// 步驟、狀態快照、插值、stationStart、total 與 events 由共用步驟序列（core/anim/sequence.js）提供；
// 本檔只放本站的規劃（分組、壓合／取像順序）與手臂姿態層（pose0／pose1、motion、PTP 時間用 retime 重排、接觸速度）。
import * as THREE from 'three';
import { createStepSequence } from '@core/anim/sequence.js';
import { smooth } from '@core/anim/track.js';
import { CONNECTOR_TYPES } from './recipes.js';
import { tiltForLift, liftForTilt, gapForTilt } from './product.js';
import { LAYOUT, palletPlacement } from './cell.js';
import { TOOL } from './robot.js';

export { smooth }; // 起停速度與加速度為零（舊呼叫端相容）
export const STATIONS = ['進板定位', '全局定位', '壓合', '相機檢查', '補壓判定', '出板'];
// 步驟開始時立即切換、不插值的鍵
export const DISCRETE = ['station', 'flashTool', 'belt', 'globalShot', 'detected'];
export const SPEC = { forceLimit: 60, fovSpan: 72 }; // 力上限 N；一張照片內接頭中心的最大跨距 mm（視野約 93 mm）
// 手臂到位規則（core/anim/arrival.js；main.js 播放與 tools/verify.mjs 連續播放共用）：停在步驟終點、或接觸步驟中位置誤差 > 2 mm 時，
// 要位置 ≤ 1 mm、角度 ≤ 1° 才前進；連續等 8 s 判到位逾時；網頁以 ≤ 10 ms 的子步推進
export const ARRIVAL = { tolerance: { position: 1, angle: 1 }, contactPosition: 2, timeout: 8, maxStep: .01 };
const PAD_K = 2.5, SEAT_F = 2.0; // 壓頭彈簧 N/mm、單顆接頭壓回所需力 N（示意）

/** 由狀態算出每顆接頭的翹起角、間隙、壓頭壓縮量與力值（主程式與驗證共用） */
export function productState(s, recipe, { ngHold = false } = {}) {
  const tilt = {}, gap = {}, stub = recipe.stubborn;
  let force = 0;
  for (const c of recipe.connectors) {
    const T = CONNECTOR_TYPES[c.type], isStub = stub && c.id === stub.id;
    let t = recipe.tilt0[c.id] || 0;
    if (s.seated[c.id]) t = isStub ? (s.fixed > 0.5 && !ngHold ? 0 : stub.residual) : 0;
    const before = t;
    if (s.pressIds.includes(c.id)) { t = Math.min(t, tiltForLift(T, Math.max(0, s.pressH))); if (before > 0 && s.pressH < liftForTilt(T, before)) force += SEAT_F; }
    tilt[c.id] = t; gap[c.id] = gapForTilt(T, t);
  }
  const padComp = s.pressIds.length ? THREE.MathUtils.clamp(-s.pressH, 0, TOOL.padStroke) : 0;
  force += s.pressIds.length * PAD_K * padComp;
  return { tilt, gap, padComp, force };
}

/** 依配方分組：同方向、同一直線上的接頭，沿排方向排序 */
export function planGroups(recipe) {
  const along = c => (c.rot % 180 === 0 ? c.x : c.z), line = c => Math.round(c.rot % 180 === 0 ? c.z : c.x);
  const rows = new Map();
  for (const c of recipe.connectors) { const k = `${c.rot}|${line(c)}`; if (!rows.has(k)) rows.set(k, []); rows.get(k).push(c); }
  const lines = [...rows.values()].map(list => list.sort((a, b) => along(a) - along(b)));
  // 拍攝分組：一張內接頭中心跨距 ≤ fovSpan
  const shots = [];
  for (const list of lines) {
    let cur = [];
    for (const c of list) { if (cur.length && along(c) - along(cur[0]) > SPEC.fovSpan) { shots.push(cur); cur = []; } cur.push(c); }
    if (cur.length) shots.push(cur);
  }
  // 8 頭壓墊可用的排：數量與片距都符合
  const mp = recipe.multiPad;
  const barRows = mp ? lines.filter(l => l.length === mp.count && l.every((c, i) => i === 0 || Math.abs(along(c) - along(l[i - 1]) - mp.pitch) < 0.5)) : [];
  return { lines, shots, barRows };
}

export function createSequence({ robot, product, apply, recipe, insert = recipe.insert }) {
  const place = palletPlacement(recipe), px = place.x, gap0 = LAYOUT.flowGap;
  const base = { palletX: px - gap0, prevX: px + gap0, nextX: px - gap0 - 900, stop: 0, lift: 0, located: false, belt: 0, globalShot: 0, detected: 0,
    pressIds: [], pressH: 120, seated: {}, fixed: 0, flashTool: 0, shot: '', zone: 'free', station: 0, action: '', sub: '' };
  const v = (x, y, z) => new THREE.Vector3(x, y, z);
  const byId = Object.fromEntries(recipe.connectors.map(c => [c.id, c]));
  const yawOf = id => product.pointing(id).negate();                 // 工具 +Y 朝板內 → 相機從板內側看銀腳
  const mean = pts => pts.reduce((a, p) => a.add(p), v(0, 0, 0)).multiplyScalar(1 / pts.length);
  const pose = (tcp, target, yaw) => robot.poseFor(tcp, target, yaw);
  // At park, point the side-mounted camera away from J2/shoulder. The former
  // inward yaw placed its body at z ≈ -410, inside the shoulder at z = -430.
  // Use the same outward pose for startup and the return at the end of a cycle.
  const park = () => pose('press', v(0, LAYOUT.conveyorTop + 200, -260), v(0, 0, 1));
  const pressMotion = ids => (t, s) => pose('press', mean(ids.map(id => product.pressPoint(id))).add(v(0, s.pressH, 0)), yawOf(ids[0]));
  const camMotion = ids => () => pose('cam', mean(ids.map(id => product.leadPoint(id))), yawOf(ids[0]));
  // 共用步驟序列在建立每步時套用終點狀態，這裡順便記下手臂起訖姿態
  // （motion(1, end) 依套用後的載盤位置求壓點／取像點，終點姿態即下一步的起點）
  let lastPose = park();
  const seq = createStepSequence({ base, discrete: DISCRETE, stations: STATIONS, ease: smooth, apply(end, s) {
    s.pose0 = lastPose; s.ptp = !s.path && !s.contact && end.zone === 'free';
    apply(end); lastPose = s.motion ? s.motion(1, end) : lastPose; s.pose1 = lastPose;
  } });
  const add = (st, dur, action, sub, values = {}, motion = null, extra = {}) => seq.add(st, dur, action, sub, values, { motion, ...extra });
  const { lines, shots, barRows } = planGroups(recipe);
  const useBar = insert === 'bar' && barRows.length > 0;
  const label = ids => ids.length > 1 ? `${ids[0]}–${ids[ids.length - 1]}` : ids[0];
  const force = ids => ids.length > 1 ? `${recipe.press.bar} N（${ids.length} 顆）` : `${recipe.press.single} N`;
  /** 壓合一組（單顆或整排）：移至 → 接近 → 壓合 → 保壓 → 回升 */
  function pressGroup(st, ids, { first, hold, holdValues = {}, done, verb = '壓合' }) {
    const m = pressMotion(ids);
    add(st, first ? .8 : .22, `移至 ${label(ids)}`, first ? `PTP；J6 轉到接頭方向（${byId[ids[0]].rot}°）` : '沿排移動、保持 8 mm 高度', { pressIds: ids, pressH: 8, zone: 'free' }, m);
    add(st, .12, '接近', '直線下降至 1.5 mm', { pressH: 1.5, zone: 'slow' }, m, { path: true, near: true });
    add(st, ids.length > 1 ? .3 : .15, `${verb} ${label(ids)} ${force(ids)}`, ids.length > 1 ? '8 頭壓墊各自以彈簧壓一顆' : '單點壓頭；力覺感測器記錄這顆的力對高度曲線', { pressH: -1.5, zone: 'contact' }, m, { path: true, contact: true });
    add(st, hold, '保壓', '銀腳壓入錫膏', { ...holdValues }, m, { path: true, contact: true });
    add(st, .15, '回升', '回升 8 mm', { pressH: 8, zone: 'slow' }, m, { path: true, near: true, done });
  }

  // ---- S0 進板定位 ----
  add(0, .5, '前一盤出站', 'SMEMA：下游可收板，前一盤離開本站', { prevX: px + 1750 });
  add(0, .3, '止擋上升', '本站淨空，止擋伸出', { stop: 1 });
  add(0, 2.0, '上游送板', `前站完成 USB 放置；軌寬已依配方調為 ${recipe.pallet.d} mm`, { palletX: px - 80, belt: 1, nextX: px - gap0 });
  add(0, .6, '減速到位', '到位感測 ON，載盤前緣靠止擋停止', { palletX: px, belt: 0, located: true });
  add(0, .5, '頂升定位', '支撐板頂升 3 mm，載盤壓住軌道壓邊；後軌為基準邊', { lift: 1 }, null, { done: 'locate' });

  // ---- S1 全局定位 ----
  add(1, .3, '全局取像', '固定 20MP 全局相機拍整盤；手臂停在視野外', { globalShot: 1 }, null, { exposure: true });
  add(1, .35, '辨識與定位', `讀取載盤碼 ${recipe.pallet.code} → 配方「${recipe.short}」；找到 ${recipe.connectors.length} 顆接頭，位置與方向修正`, { globalShot: 0, detected: 1 }, null, { done: 'detect' });

  // ---- S2 壓合 ----
  let seated = {};
  if (useBar) {
    barRows.forEach((row, k) => { const ids = row.map(c => c.id); seated = { ...seated, ...Object.fromEntries(ids.map(id => [id, 1])) };
      pressGroup(2, ids, { first: true, hold: .5, holdValues: { seated }, done: 'press' + k }); });
  }
  const barIds = new Set(useBar ? barRows.flat().map(c => c.id) : []);
  const singles = lines.flatMap((l, k) => (k % 2 ? [...l].reverse() : l)).filter(c => !barIds.has(c.id));  // 蛇行順序
  let lastRot = null;
  for (const c of singles) {
    seated = { ...seated, [c.id]: 1 };
    pressGroup(2, [c.id], { first: c.rot !== lastRot, hold: .2, holdValues: { seated }, done: 'press' + c.id }); lastRot = c.rot;
  }

  // ---- S3 相機檢查：依方向分組，每張最多 4 顆 ----
  lastRot = null;
  shots.forEach((grp, k) => {
    const ids = grp.map(c => c.id), m = camMotion(ids), first = grp[0].rot !== lastRot; lastRot = grp[0].rot;
    add(3, first ? .9 : .35, `移至 ${label(ids)}`, first ? `PTP；相機 45° 從板內側看銀腳（方向 ${grp[0].rot}°）` : '沿排移動', { pressIds: [], pressH: 120, zone: 'free' }, m);
    add(3, .15, `取像 ${label(ids)}`, `20MP・條形光頻閃；一張 ${ids.length} 顆，量測銀腳末端與焊墊間隙`, { flashTool: 1, shot: String(k) }, null, { exposure: true });
    add(3, .1, `判定 ${label(ids)}`, `間隙 ≤ ${recipe.gapLimit.toFixed(2)} mm 為貼合（示意允收值）`, { flashTool: 0 }, null, { done: 'shot' + k });
  });

  // ---- S4 補壓判定：回彈的那一顆原位補壓後複檢 ----
  const stub = recipe.stubborn.id, stubRow = useBar ? barRows.find(r => r.some(c => c.id === stub)) : null;
  add(4, .3, `判定：${stub} 未貼合`, `間隙超過 ${recipe.gapLimit.toFixed(2)} mm；原位補壓一次`, {}, null, { done: 'judgeNG' });
  pressGroup(4, stubRow ? stubRow.map(c => c.id) : [stub], { first: true, hold: .4, holdValues: { fixed: 1 }, verb: '補壓', done: 'repress' });
  add(4, .8, `${stub} 複檢定位`, 'PTP；相機只對準這一顆', { pressIds: [], pressH: 120, zone: 'free' }, camMotion([stub]));
  add(4, .15, `複檢取像 ${stub}`, '同一光源與曝光條件', { flashTool: 1, shot: 'R' }, null, { exposure: true });
  add(4, .2, `複檢判定 ${stub}`, '通過才放行；仍未貼合則停線待人工', { flashTool: 0 }, null, { done: 'recheck' });
  add(4, .3, '結果彙整', '逐顆寫入壓合力曲線、間隙與影像索引（示意）', { shot: '' }, null, { done: 'judge' });

  // ---- S5 出板 ----
  add(5, .8, '手臂回待命', 'PTP 回待命位置，讓出輸送與全局相機視野', {}, park);
  add(5, .4, '頂升下降', '載盤回到皮帶', { lift: 0 });
  add(5, .3, '止擋下降', 'SMEMA：下游可收板', { stop: 0 });
  add(5, 2.0, '出板', '送往下游（迴焊爐）', { palletX: px + gap0, belt: 1, located: false }, null, { done: 'out' });
  add(5, .2, '單盤循環完成', '下一盤已在上游等待', { belt: 0 });

  // 逆解規劃全部起訖姿態後，PTP 步驟時間依關節角度差重算（至少為原排定值，取 0.05 s 刻度）；
  // 起點、stationStart、total、events 由共用序列的 retime 重排
  robot.plan(seq.steps.flatMap(s => [s.pose0, s.pose1]));
  seq.retime(s => s.ptp ? Math.max(s.dur, Math.ceil(robot.ptpTime(s.pose0, s.pose1) * 20) / 20) : s.dur);
  const steps = seq.steps;

  /** 取樣：共用序列給狀態與所在步驟，這裡把狀態套到設備並設定手臂目標（不移動關節；播放時由 robot.update 限速追蹤） */
  function sample(sec) {
    const { state, step: s, index: idx, u: t, e } = seq.sample(sec);
    apply(state);
    const destination = s.motion ? s.motion(t, state) : s.pose1;
    // 自由移位走關節插值（PTP）；接近、接觸、回升走直線
    const p = s.path ? destination : s.ptp ? { ptp: { from: s.pose0, to: s.pose1, e } } :
      { origin: s.pose0.origin.clone().lerp(destination.origin, e), rotation: s.pose0.rotation.clone().slerp(destination.rotation, e), tcp: destination.tcp };
    if (!p.ptp) p.ref = s.pose0;
    robot.setPose(p); robot.goal.speed = s.contact ? 40 : state.zone === 'slow' ? 120 : 500;
    const completed = new Set(steps.slice(0, idx).map(x => x.done).filter(Boolean)); if (t === 1 && s.done) completed.add(s.done);
    return { state, step: s, index: idx, t, completed };
  }
  return { sample, steps, total: seq.total, stationStart: seq.stationStart, events: seq.events, base, shots, useBar, barRows };
}
