// 播放控制：綁定標準底部列（播放、重播、速度、時間軸、時鐘、事件選單、上一步／下一步）。
// 時間只由這裡推進；畫面狀態一律經 apply(T) 取得，所以拖曳、倒退、跳站與連續播放結果一致。
//
//   const player = createPlayer({ total, apply: T => project.apply(T), events: tl.events.map(e => ({ time: e.start, label: e.action })) });
//   stage.loop(dt => player.update(dt));
const $ = id => document.getElementById(id);
export const fmtTime = t => `${String(Math.floor(t / 60)).padStart(2, '0')}:${(t % 60).toFixed(1).padStart(4, '0')}`;

export function createPlayer({ total, apply, events = [], qp = new URLSearchParams(location.search), speeds = [.25, 4], onChange = () => { } }) {
  const ui = { play: $('playBtn'), restart: $('restartBtn'), speed: $('speed'), speedVal: $('speedVal'), timeline: $('timeline'), clock: $('clock'), steps: $('stepSelect'), prev: $('previous'), next: $('next') };
  let T = 0, playing = !qp.has('pause'), speed = +(qp.get('speed') || 1);
  if (ui.timeline) { ui.timeline.min = 0; ui.timeline.max = total; ui.timeline.step = 'any'; }
  if (ui.speed) { ui.speed.min = speeds[0]; ui.speed.max = speeds[1]; ui.speed.step = .25; ui.speed.value = speed; }
  if (ui.steps) ui.steps.innerHTML = events.map((e, i) => `<option value="${i}">${fmtTime(e.time)}  ${e.label}</option>`).join('');

  function show() {
    if (ui.play) ui.play.textContent = playing ? '⏸ 暫停' : '▶ 播放';
    if (ui.timeline) ui.timeline.value = T;
    if (ui.clock) ui.clock.textContent = fmtTime(T);
    if (ui.speedVal) ui.speedVal.textContent = speed + '×';
    if (ui.steps && events.length) ui.steps.value = String(eventIndex());
  }
  const eventIndex = () => { let i = 0; events.forEach((e, k) => { if (e.time <= T + 1e-6) i = k; }); return i; };
  function seekTo(t) { T = Math.min(total, Math.max(0, Number.isFinite(+t) ? +t : 0)); const s = apply(T); show(); onChange(T, s); return s; }
  const play = () => { if (T >= total) T = 0; playing = true; show(); };
  const pause = () => { playing = false; show(); };

  ui.play?.addEventListener('click', () => playing ? pause() : play());
  ui.restart?.addEventListener('click', () => { seekTo(0); play(); });
  ui.speed?.addEventListener('input', () => { speed = +ui.speed.value; show(); });
  ui.timeline?.addEventListener('input', () => { playing = false; seekTo(+ui.timeline.value); });
  ui.steps?.addEventListener('change', () => { playing = false; seekTo(events[+ui.steps.value].time); });
  ui.prev?.addEventListener('click', () => { playing = false; const i = eventIndex(); seekTo(events[Math.max(0, events[i].time < T - .5 ? i : i - 1)]?.time ?? 0); });
  ui.next?.addEventListener('click', () => { playing = false; seekTo(events[Math.min(events.length - 1, eventIndex() + 1)]?.time ?? total); });

  seekTo(qp.has('t') ? +qp.get('t') : 0);
  return {
    get T() { return T; }, get playing() { return playing; }, total, seekTo, play, pause,
    // 每格呼叫；播放中回傳 true（需要重繪）
    update(dt) { if (!playing) return false; T = Math.min(total, T + dt * speed); if (T >= total) playing = false; const s = apply(T); show(); onChange(T, s); return true; },
  };
}
