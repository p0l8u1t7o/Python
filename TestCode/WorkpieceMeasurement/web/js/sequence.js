// 動作序列：由絕對時間取樣出完整狀態（軸位置＋工件所在＋取像進度），跳站／倒退不殘留。
// 排程建在共用的 createStepSequence（core/anim/sequence.js）上：這裡只負責依軸限速反推每步時間、
// 指定每步的緩動（smooth／trap，以步驟的 ease 交給 core 插值），以及取樣後附加的完成項目與取像進度。
import { createStepSequence } from '@core/anim/sequence.js';
import { SPECS, SCENARIOS, DEMO, LIMIT, X1, X2, XW, YM, YS, YT, YC, RETRACT, pocket, shuttleFor } from './spec.js';

export const STATIONS = ['取料', 'ST1 外觀／尺寸', '移載', 'ST2 底部量測', '判定分料'];
const smooth = u => u * u * (3 - 2 * u);   // 三次 smoothstep（與 core 的五次 smooth 不同，dur() 的限速反推依此曲線）
const trap = u => { const k = 0.12; return u < k ? u * u / (2 * k * (1 - k)) : u > 1 - k ? 1 - (1 - u) * (1 - u) / (2 * k * (1 - k)) : (u - k / 2) / (1 - k); };
const EASE = { smooth, trap };
// smoothstep 的峰值速度 1.5 d/T、峰值加速度 6 d/T²，由限速反推時間
const dur = (d, v, a) => Math.max(0.06, 1.5 * Math.abs(d) / v, Math.sqrt(6 * Math.abs(d) / a));
const axisDur = (k, d) => k === 'tx' ? dur(d, LIMIT.vx, LIMIT.ax) : k === 'zt' ? dur(d, LIMIT.vz, LIMIT.az) : k === 'inZ' || k === 'outZ' ? dur(d, LIMIT.vShuttle, LIMIT.aShuttle) : k === 'a' ? 0.08 : k === 'jaw' ? 0.15 : 0.06;
const AXES = ['tx', 'zt', 'a', 'jaw', 'th1', 'th2', 'r2', 'inZ', 'outZ', 'headLift'];
const TAU = Math.PI * 2;

export function createSequence({ spec = 'B', scenario = 'OK', apply } = {}) {
  const s = SPECS[spec], sc = SCENARIOS[scenario];
  const pin = pocket('IN', DEMO.k), outTray = sc.out === 'IN' ? null : sc.out, pout = outTray ? pocket(outTray, DEMO.filled[outTray]) : pin;
  // 軸位置在步驟中插值；工件所在、真空、取像通道等在步驟開始時切換（discrete）
  const axes = { tx: pin.x, zt: YC, a: RETRACT, jaw: 1, th1: 0, th2: 0, r2: s.scan.r0, inZ: shuttleFor('IN', DEMO.k), outZ: shuttleFor('OK', DEMO.filled.OK), headLift: 30 };
  const flags = { loc: 'in', vac: 0, optic: null, pip: 'idle', shotB: 0, zone: 'free', scanNo: 0 };
  // 軸位置由 core 依每步的 ease（函式）插值；序列預設 smooth
  const seq = createStepSequence({ base: { ...axes, ...flags }, discrete: Object.keys(flags), ease: smooth, stations: STATIONS });
  let station = 0;
  // step(動作, 說明, { to: 軸目標, set: 狀態切換, dur: 指定秒數（省略時由軸限速反推）, ease, done, prog, exposure })
  function step(action, sub, o = {}) {
    const to = o.to || {}, now = seq.state;
    const d = o.dur ?? Math.max(0.06, ...Object.entries(to).map(([k, v]) => axisDur(k, v - now[k])));
    return seq.add(station, d, action, sub, { ...to, ...o.set }, { index: seq.steps.length, ease: EASE[o.ease || 'smooth'], done: o.done, prog: o.prog, exposure: o.exposure });
  }
  const xMove = (x, action, sub, o = {}) => step(action, sub, { ...o, to: { ...(o.to || {}), tx: x } });
  // 吸附：前進貼靠 → 建立真空（工件所在於步驟交界切換，位置連續）
  const grab = (from, sub) => { step('吸嘴前進貼靠外壁', sub, { to: { a: 0 }, set: { zone: 'contact' } }); step('建立真空，確認吸附', '真空開關到達設定值才放行下一步', { dur: 0.1, set: { vac: 1, loc: 'noz' }, done: 'grab:' + from }); };
  const release = (loc, id) => { step('破真空，工件落座', '吸嘴保持貼靠到真空歸零', { dur: 0.1, set: { vac: 0, loc }, done: id }); step('吸嘴後退', `貼靠氣缸退回 ${RETRACT} mm`, { to: { a: RETRACT }, set: { zone: 'free' } }); };

  // ------------------------------------------------ S0 取料
  station = 0;
  step(`入料托盤第 ${pin.row + 1} 列對準取料線`, `入料第 ${DEMO.k + 1} 穴；手臂側的列已取空，吸嘴由後方伸入`, { dur: 0.25, set: { pip: 'idle' } });
  step('Z 下降到吸附高度', `吸嘴中心距工件底面 1.8 mm，在夾持帶與穴位之間`, { to: { zt: YT }, set: { zone: 'slow' } });
  grab('in', '側向真空吸嘴貼靠外壁，不碰杯口與底面');
  step('Z 上升離開托盤', '工件底面高於同列工件頂面後才走 X', { to: { zt: YC } });
  xMove(X1, 'X 移到 ST1 下方', '沿低位走廊通過通道 B 鏡頭下方', { set: { zone: 'free' } });
  step('Z 上升，杯口送入三爪夾頭', '夾頭回到原點角度，後方爪間空隙對準吸嘴', { to: { zt: YM - s.len }, set: { zone: 'slow' } });
  // ------------------------------------------------ S1 ST1
  station = 1;
  step('三爪 PEEK 夾頭夾持杯口', `夾持帶寬 1.5 mm、夾持力 1.5 N（上限 2 N），以減壓閥限力`, { to: { jaw: 0 }, set: { zone: 'contact' }, done: 'clamp' });
  release('chuck', 'handoff1');
  step('吸嘴下降避讓', '退到走廊高度，讓出旋轉與光路空間', { to: { zt: YC } });
  step('通道 A：θ 旋轉 1 圈線掃展開', `編碼器硬體觸發 3300 行／圈・4.67 µm/px・RGB 三角度同步照明`, { dur: 1.0, to: { th1: TAU }, ease: 'trap', set: { optic: 'A', pip: 'A' }, prog: 'scanA', done: 'scanA', exposure: 'A' });
  for (let i = 0; i < 4; i++) {
    if (i) step(`θ 分度到 ${i * 90}°`, '分度期間背光熄滅', { dur: 0.16, to: { th1: TAU + i * Math.PI / 2 }, set: { optic: null, pip: 'B' } });
    step(`通道 B：遠心剪影 ${i * 90}°`, '遠心鏡頭＋平行背光頻閃，量外徑／全長／直線度' + (s.flare ? '／喇叭口' : ''), { dur: 0.08, set: { optic: 'B', pip: 'B', shotB: i + 1 }, done: 'shotB' + i, exposure: 'B' });
  }
  step('通道 C：口部端面取像', '由中空軸向下同軸落射＋環形低角度光，擬合內外圓', { dur: 0.2, set: { optic: 'C', pip: 'C' }, done: 'shotC', exposure: 'C' });
  step('θ 回原點', '爪間空隙對準吸嘴', { dur: 0.2, to: { th1: TAU * 2 }, set: { optic: null } });
  step('吸嘴上升到吸附高度', '', { to: { zt: YM - s.len }, set: { zone: 'slow' } });
  grab('chuck', '先取得吸附再鬆開夾頭');
  step('三爪夾頭鬆開', '確認鬆開到位才下降', { to: { jaw: 1 }, done: 'unclamp' });
  // ------------------------------------------------ S2 移載
  station = 2;
  step('Z 下降到走廊高度', '', { to: { zt: YC }, set: { zone: 'free', pip: 'idle' } });
  xMove(XW, 'X 移到升降點', '由平行背光下方通過');
  step('Z 上升到 ST2 進入高度', '工件底面高於薄環座 3 mm', { to: { zt: YS + 3 } });
  xMove(X2, 'X 移到 ST2 中心', '由上感測器與轉接板之間進入', { set: { zone: 'slow' } });
  step('Z 下降落座', '外底面外緣落在鎢鋼薄環座', { to: { zt: YS }, set: { zone: 'contact' } });
  release('seat', 'seat');
  // ------------------------------------------------ S3 ST2
  station = 3;
  const scan = (n, id) => {
    step('上感測頭下降到量測位置', '杯體已落座、吸嘴退開；15 mm 參考距離，實際光路待樣品驗證', { dur: .6, to: { headLift: 0 }, set: { optic: null, pip: 'CF' } });
    step('落座穩定', '掃描期間移載模組不動作', { dur: 0.3, set: { pip: 'CF', optic: null, scanNo: n } });
    step(`螺旋掃描 ${s.scan.rev} 圈（上下共焦同步）`, `R ${s.scan.r0.toFixed(2)} → ${s.scan.r1.toFixed(2)} mm・${s.scan.rpm} rpm・上下同步與取樣率待 POC；動畫示意`, { dur: s.scan.rev * 60 / s.scan.rpm, to: { th2: TAU * s.scan.rev * (n + 1), r2: s.scan.r1 }, ease: 'trap', set: { optic: 'CF', pip: 'CF', scanNo: n }, prog: 'spiral' + n, done: id, exposure: 'CF' });
    step('R 軸回起始半徑', '', { dur: 0.15, to: { r2: s.scan.r0 }, set: { optic: null } });
    step('上感測頭上升避讓', '上頭退回後才允許重新取件；避讓軸為新增規劃', { dur: .6, to: { headLift: 30 } });
  };
  scan(0, 'spiral0');
  if (sc.id === 'ERR') {
    step('有效點不足，判定 ERR', '不直接判 NG；重新落座後重測一次', { dur: 0.3, done: 'err0' });
    grab('seat', '重新落座');
    step('Z 抬起 2 mm 再落座', '', { to: { zt: YS + 2 }, dur: 0.1 });
    step('Z 下降落座', '', { to: { zt: YS }, dur: 0.1 });
    release('seat', 'reseat');
    scan(1, 'spiral1');
  }
  // ------------------------------------------------ S4 判定分料
  station = 4;
  const outZ = outTray ? shuttleFor(outTray, DEMO.filled[outTray]) : seq.state.outZ;
  step('判定＋資料寫入', outTray ? `分流到 ${outTray} 托盤第 ${pout.row + 1} 列第 ${pout.col + 1} 穴` : '重測仍異常：退回入料原穴，通知人工處理', { dur: 0.4, to: { outZ }, set: { pip: 'result' }, done: 'judge' });
  grab('seat', '');
  step('Z 上升', '', { to: { zt: YS + 3 }, set: { zone: 'free' } });
  xMove(XW, 'X 退到升降點', '');
  step('Z 下降到走廊高度', '', { to: { zt: YC } });
  xMove(pout.x, outTray ? `X 移到 ${outTray} 托盤` : 'X 移到入料托盤原穴', '');
  step('Z 下降放料', '', { to: { zt: YT }, set: { zone: 'slow' } });
  release(outTray ? 'out:' + outTray : 'back', 'out');
  step('Z 上升回待命位', '下一件由入料托盤取料', { to: { zt: YC }, done: 'home' });

  const { steps, total, stationStart, events } = seq;
  function sample(T) {
    const { state, step: st, index: i, u, time } = seq.sample(T);
    const S = { ...Object.fromEntries(Object.keys(flags).map(k => [k, state[k]])), station: st.station, action: st.action, sub: st.sub, u, step: i, time };
    for (const k of AXES) S[k] = state[k];
    const completed = new Set(); for (const x of steps) if (x.done && (x.index < i || (x.index === i && time >= total - 1e-9))) completed.add(x.done);
    const prog = id => { const x = steps.find(y => y.prog === id); return !x ? 0 : x.index < i ? 1 : x.index === i ? u : 0; };
    S.scanA = prog('scanA'); S.spiral = [prog('spiral0'), prog('spiral1')];
    S.flash = st.exposure && st.exposure !== 'A' && st.exposure !== 'CF' ? 1 : 0;
    if (apply) apply(S);
    return { state: S, step: st, index: i, completed };
  }
  // events／stationStart／total 與其他專案同一介面（播放列、事件選單、錄影分鏡共用）
  return { steps, events, total, stationStart, sample, spec: s, scenario: sc };
}
