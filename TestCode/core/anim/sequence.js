// 步驟序列：一條依序排列的製程步驟（單一手臂工作站常用）。每步記下起點與終點狀態快照，
// 任一時刻的狀態只由時間決定（倒退、跳站與連續播放結果一致）。多台設備各自並行時改用 track.js 的 createTimeline。
//
//   const seq = createStepSequence({ base: { lift: 0, grip: 0, zone: 'free' }, discrete: ['zone'], latch: ['loc'], apply: s => station.apply(s) });
//   seq.add(0, 1.2, '進板定位', '止擋伸出', { stop: 1 });
//   seq.add(1, 0.8, '全局定位', '取像', { shot: 'G1' }, { exposure: true, ease: linear });   // 第 6 個參數附加在步驟上
//   const { state, step, index, u, e } = seq.sample(T);
//
// 插值規則（每個鍵）：
//   數值 → 依緩動由起點插到終點；nested: true 時，數值組成的陣列／物件也逐項插值（例如多扇門的開度）
//   discrete 列出的鍵與字串、布林 → 步驟開始時切換
//   latch 列出的鍵 → 步驟結束時才切換（例如零件歸屬：放下那一刻才換手）
//   緩動：步驟的 extra.ease 優先，其次序列預設 ease；extra.easeKeys = { 鍵: 緩動 } 可逐鍵指定
//
// 兩種排程都提供同樣的事件介面：events（[{ time, dur, label, sub, station }]）、stationStart、total，
// 播放列（core/ui/player.js）、事件選單與錄影分鏡都用它。
import { smooth } from './track.js';

const copy = v => (v && typeof v === 'object') ? JSON.parse(JSON.stringify(v)) : v;
// 數值或「全由數值組成」的陣列／物件，逐項插值；形狀不同時取終點
function mix(a, b, e) {
  if (typeof a === 'number' && typeof b === 'number') return a + (b - a) * e;
  if (Array.isArray(a) && Array.isArray(b) && a.length === b.length) return a.map((x, i) => mix(x, b[i], e));
  if (a && b && typeof a === 'object' && typeof b === 'object' && !Array.isArray(a) && !Array.isArray(b)) {
    const out = {}; for (const k of Object.keys(b)) out[k] = k in a ? mix(a[k], b[k], e) : copy(b[k]); return out;
  }
  return copy(b);
}

export function createStepSequence({ base = {}, apply = () => { }, discrete = [], latch = [], ease = smooth, stations = 0, nested = false } = {}) {
  const DISCRETE = new Set(discrete), LATCH = new Set(latch);
  const steps = [], stationStart = Array.isArray(stations) ? Array(stations.length).fill(0) : [];
  let previous = copy(base), time = 0;

  // 預覽：照 add 的規則算出終點狀態，但不加入序列（例如先看終點姿態再決定要不要插退離步驟）
  function peek(values = {}) {
    const end = copy(previous);
    for (const [k, v] of Object.entries(values)) end[k] = copy(v);
    return end;
  }
  function add(station, dur, action, sub = '', values = {}, extra = {}) {
    if (!steps.some(s => s.station === station)) stationStart[station] = time;
    const initial = copy(previous), end = peek(values);
    end.station = station; end.action = action; end.sub = sub;
    const s = { station, start: time, dur, action, sub, initial, end, ...extra };
    apply(end, s);                                   // 建立時套用終點狀態（例如讓手臂逆解以終點姿態為下一步的起點）
    steps.push(s); previous = end; time += dur; return s;
  }
  const hold = (station, dur, action, sub = '', extra = {}) => add(station, dur, action, sub, {}, extra);

  // 試排：mark() 記下目前位置，rollback(m) 退回（給需要試排、撞到再重排的規劃器）
  const mark = () => ({ n: steps.length, previous: copy(previous), time, stationStart: [...stationStart] });
  function rollback(m) {
    steps.length = m.n; previous = copy(m.previous); time = m.time;
    stationStart.length = 0; stationStart.push(...m.stationStart);
  }
  // 事後重排時間：fn(step, index) 回傳新的 dur（例如依規劃好的關節角度算 PTP 時間）
  function retime(fn) {
    time = 0; const seen = new Set(); stationStart.fill(0);
    steps.forEach((s, i) => {
      if (!seen.has(s.station)) { stationStart[s.station] = time; seen.add(s.station); }
      s.start = time; s.dur = fn(s, i) ?? s.dur; time += s.dur;
    });
  }

  function indexAt(T) {
    let lo = 0, hi = steps.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (T < steps[m].start + steps[m].dur) hi = m; else lo = m + 1; }
    return lo;
  }
  function sample(T) {
    T = Number.isFinite(T) ? Math.min(Math.max(T, 0), time) : 0;
    const index = indexAt(T), step = steps[index];
    const u = step.dur > 0 ? Math.min(1, Math.max(0, (T - step.start) / step.dur)) : 1;
    const stepEase = typeof step.ease === 'function' ? step.ease : ease, e = stepEase(u);   // 步驟上的 ease 須為函式（字串等專案自用的標記不影響）
    const state = copy(step.initial);
    for (const [k, v] of Object.entries(step.end)) {
      if (LATCH.has(k)) state[k] = copy(u >= 1 ? v : step.initial[k]);
      else if (DISCRETE.has(k)) state[k] = copy(v);
      else {
        const a = step.initial[k], ek = step.easeKeys?.[k] ? step.easeKeys[k](u) : e;
        state[k] = typeof v === 'number' && typeof a === 'number' ? a + (v - a) * ek : nested ? mix(a, v, ek) : copy(v);
      }
    }
    return { state, step, index, u, e, time: T };
  }

  return {
    add, hold, peek, mark, rollback, retime, sample, steps, stationStart,
    get total() { return time; },
    get state() { return previous; },
    get events() { return steps.filter(s => s.action).map(s => ({ time: s.start, dur: s.dur, label: s.action, sub: s.sub, station: s.station })); },
  };
}

// 多軌時間軸（createTimeline）轉成同樣的事件介面
export function timelineEvents(tl) {
  return tl.events.map(s => ({ time: s.start, dur: s.dur, label: s.action, sub: s.sub, station: s.station ?? s.track }));
}
