// 時間軌：每台設備（或每個工件）一條，步驟依序排在絕對時間上。
// 任一時刻的狀態只由時間 T 決定（二分搜尋到所在步驟再插值），所以倒退、跳站與連續播放結果一致——
// 統一檢查的 determinism 項目依賴這個性質。
//
//   const tl = createTimeline();
//   const robot = tl.track('robot', { x: 0, grip: 0 });
//   robot.add(2, { x: 500 }, { action: '移到取料位' });
//   const conveyor = tl.track('conveyor', { s: 0 });
//   conveyor.add(3, { s: 1200 }, { at: robot.t });          // 等手臂完成再動（流水線阻塞）
//   const st = tl.sample(T);                                 // { robot: {...}, conveyor: {...} }
export const smooth = t => t * t * t * (10 + t * (-15 + 6 * t));   // 五次 S 曲線：起訖速度、加速度皆為 0
export const linear = t => t;
export const lerp = (a, b, t) => a + (b - a) * t;
export const clamp01 = t => Math.max(0, Math.min(1, t));

export class Track {
  constructor(name, base) { this.name = name; this.base = { ...base }; this.state = { ...base }; this.steps = []; this.t = 0; }
  // dur 秒內把 values 的數值插到目標；非數值鍵（字串、布林）在步驟開始時立即生效。
  // o.at：最早開始時間（與目前軌尾取較晚者）；o.ease：緩動；o.motion(e, t)：自訂路徑（回傳要覆寫的鍵）
  // o.action／o.sub：給狀態面板與事件列表的說明
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
  // 一次取得狀態、所在步驟與是否動作中
  at(T) { const i = this.find(T), step = i < 0 ? null : this.steps[i]; return { state: this.sample(T), step, active: !!step && T < step.start + step.dur }; }
  get end() { return this.steps.length ? Math.max(...this.steps.map(s => s.start + s.dur)) : 0; }
}

// 多條時間軌的集合：sample(T) 一次取得全部狀態，activity(T) 列出正在動作的步驟
export function createTimeline() {
  const tracks = {};
  return {
    tracks,
    track(name, base) { return (tracks[name] = new Track(name, base)); },
    get total() { return Math.max(0, ...Object.values(tracks).map(t => t.end)); },
    sample(T) { return Object.fromEntries(Object.entries(tracks).map(([k, t]) => [k, t.sample(T)])); },
    activity(T) { return Object.values(tracks).map(t => t.active(T)).filter(Boolean); },
    // 有 action 文字的步驟，依時間排序（做事件下拉選單、上一步／下一步）
    get events() { return Object.values(tracks).flatMap(t => t.steps.filter(s => s.action)).sort((a, b) => a.start - b.start); },
    // 各站最早開始作業的時間（步驟上有 station 編號時；與 createStepSequence 的 stationStart 相同用途）
    get stationStart() {
      const out = [];
      for (const t of Object.values(tracks)) for (const s of t.steps) if (Number.isInteger(s.station) && !(s.start >= out[s.station])) out[s.station] = s.start;
      return Array.from(out, v => v ?? 0);
    },
  };
}
