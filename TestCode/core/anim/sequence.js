// 步驟序列：一條依序排列的製程步驟（單一手臂工作站常用）。每步記下起點與終點狀態快照，
// 任一時刻的狀態只由時間決定（倒退、跳站與連續播放結果一致）。多台設備各自並行時改用 track.js 的 createTimeline。
//
//   const seq = createStepSequence({ base: { lift: 0, grip: 0, zone: 'free' }, discrete: ['zone'], apply: s => station.apply(s) });
//   seq.add(0, 1.2, '進板定位', '止擋伸出', { stop: 1 });
//   seq.add(1, 0.8, '全局定位', '取像', { shot: 'G1' }, { exposure: true });   // 第 6 個參數附加在步驟上（給專案用）
//   const { state, step, index, u, e } = seq.sample(T);
//
// 兩種排程都提供同樣的事件介面：events（[{ time, dur, label, sub, station }]）、stationStart、total，
// 播放列（core/ui/player.js）、事件選單與錄影分鏡都用它。
import { smooth } from './track.js';

const copy = v => (v && typeof v === 'object') ? JSON.parse(JSON.stringify(v)) : v;

export function createStepSequence({ base = {}, apply = () => { }, discrete = [], ease = smooth, stations = 0 } = {}) {
  const DISCRETE = new Set(discrete);
  const steps = [], stationStart = Array.isArray(stations) ? Array(stations.length).fill(0) : [];
  let previous = copy(base), time = 0;

  // values 中的數值在步驟期間由起點插到終點（discrete 列出的鍵與非數值在步驟開始時切換）
  function add(station, dur, action, sub = '', values = {}, extra = {}) {
    if (!steps.some(s => s.station === station)) stationStart[station] = time;
    const initial = copy(previous), end = copy(initial);
    for (const [k, v] of Object.entries(values)) end[k] = copy(v);
    end.station = station; end.action = action; end.sub = sub;
    const s = { station, start: time, dur, action, sub, initial, end, ...extra };
    apply(end, s);                                   // 建立時套用終點狀態（例如讓手臂逆解以終點姿態為下一步的起點）
    steps.push(s); previous = end; time += dur; return s;
  }
  // 停留：狀態不變，只占時間
  const hold = (station, dur, action, sub = '', extra = {}) => add(station, dur, action, sub, {}, extra);

  function indexAt(T) {
    let lo = 0, hi = steps.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (T < steps[m].start + steps[m].dur) hi = m; else lo = m + 1; }
    return lo;
  }
  function sample(T) {
    T = Number.isFinite(T) ? Math.min(Math.max(T, 0), time) : 0;
    const index = indexAt(T), step = steps[index];
    const u = step.dur > 0 ? Math.min(1, Math.max(0, (T - step.start) / step.dur)) : 1, e = ease(u);
    const state = copy(step.initial);
    for (const [k, v] of Object.entries(step.end)) {
      const a = step.initial[k];
      state[k] = typeof v === 'number' && typeof a === 'number' && !DISCRETE.has(k) ? a + (v - a) * e : copy(v);
    }
    return { state, step, index, u, e, time: T };
  }

  return {
    add, hold, sample, steps, stationStart,
    get total() { return time; },
    get state() { return previous; },
    get events() { return steps.filter(s => s.action).map(s => ({ time: s.start, dur: s.dur, label: s.action, sub: s.sub, station: s.station })); },
  };
}

// 多軌時間軸（createTimeline）轉成同樣的事件介面
export function timelineEvents(tl) {
  return tl.events.map(s => ({ time: s.start, dur: s.dur, label: s.action, sub: s.sub, station: s.station ?? s.track }));
}
