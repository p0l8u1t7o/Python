// 播放控制：綁定標準底部列（播放、重播、速度、時間軸、時鐘、事件選單、上一步／下一步、循環）。
// 時間只由這裡推進；畫面狀態一律經 apply(T, { seek }) 取得，所以拖曳、倒退、跳站與連續播放結果一致。
//
//   const player = createPlayer({ total, apply: (T, { seek }) => project.apply(T), events: seq.events });
//   stage.loop(dt => player.update(dt));
//
// 選項：
//   apply(T, { seek, dt })  seek 為 true 時是跳播（手臂直接到位，dt 為 0），false 是連續播放中的一格（dt 為這格的模擬時間）
//   advance(T, dt)          自訂時間推進：回傳新時間（可小於 T + dt，用來等手臂到位）；回傳 null 代表停住（例如故障）
//   maxStep                 每次推進的模擬時間上限（秒）：一格超過時拆成多個子步（高倍速時手臂追蹤仍穩定）
//   loop                    true 或函式：播到結尾從頭再播；頁面有 #loop 勾選框時自動綁定
//   speed                   預設速度；#speed 若是 <select> 以選項為準，若是拉桿用 speeds = [最小, 最大, 刻度]
//   format(T)               時鐘格式（預設 mm:ss.s）
//   onChange(T, state, { seek })／onEnd()
const $ = id => document.getElementById(id);
export const fmtTime = t => `${String(Math.floor(t / 60)).padStart(2, '0')}:${(t % 60).toFixed(1).padStart(4, '0')}`;

export function createPlayer({
  total, apply, events = [], qp = new URLSearchParams(location.search), speeds = [.25, 4, .25], speed: defaultSpeed = 1,
  advance = null, maxStep = 0, loop = null, format = fmtTime, onChange = () => { }, onEnd = () => { },
}) {
  const ui = { play: $('playBtn'), restart: $('restartBtn'), speed: $('speed'), speedVal: $('speedVal'), timeline: $('timeline'), clock: $('clock'), steps: $('stepSelect'), prev: $('previous'), next: $('next'), loop: $('loop') };
  const isSelect = ui.speed?.tagName === 'SELECT';
  let T = 0, playing = !qp.has('pause');
  let speed = +(qp.get('speed') || (isSelect && ui.speed.value) || defaultSpeed);
  if (ui.timeline) { ui.timeline.min = 0; ui.timeline.max = total; ui.timeline.step = 'any'; }
  if (ui.speed && !isSelect) { ui.speed.min = speeds[0]; ui.speed.max = speeds[1]; ui.speed.step = speeds[2] ?? .25; }
  if (ui.speed) ui.speed.value = speed;
  if (ui.steps) ui.steps.innerHTML = events.map((e, i) => `<option value="${i}">${format(e.time)}  ${e.label}</option>`).join('');
  const looping = () => typeof loop === 'function' ? loop() : loop ?? !!ui.loop?.checked;

  function show() {
    if (ui.play) ui.play.textContent = playing ? '⏸ 暫停' : '▶ 播放';
    if (ui.timeline) ui.timeline.value = T;
    if (ui.clock) ui.clock.textContent = format(T);
    if (ui.speedVal) ui.speedVal.textContent = speed + '×';
    if (ui.steps && events.length) ui.steps.value = String(eventIndex());
  }
  const eventIndex = () => { let i = 0; events.forEach((e, k) => { if (e.time <= T + 1e-6) i = k; }); return i; };
  function go(t, seek, dt = 0) { T = Math.min(total, Math.max(0, Number.isFinite(+t) ? +t : 0)); const s = apply(T, { seek, dt }); show(); onChange(T, s, { seek }); return s; }
  const seekTo = t => go(t, true);
  const play = () => { if (T >= total - 1e-9) seekTo(0); playing = true; show(); };
  const pause = () => { playing = false; show(); };

  ui.play?.addEventListener('click', () => playing ? pause() : play());
  ui.restart?.addEventListener('click', () => { seekTo(0); play(); });
  ui.speed?.addEventListener(isSelect ? 'change' : 'input', () => { speed = +ui.speed.value; show(); });
  ui.timeline?.addEventListener('input', () => { playing = false; seekTo(+ui.timeline.value); });
  ui.steps?.addEventListener('change', () => { playing = false; seekTo(events[+ui.steps.value].time); });
  // 上一步：已播過目前步驟 0.5 s 以上時回到目前步驟開頭，否則回到前一個時刻的步驟（短步驟逐一經過，同一時刻多筆事件也不會卡住）
  ui.prev?.addEventListener('click', () => {
    playing = false;
    const cur = events.filter(e => e.time <= T + 1e-6).at(-1);
    if (cur && T - cur.time > .5) { seekTo(cur.time); return; }
    seekTo(cur ? events.filter(e => e.time < cur.time - 1e-6).at(-1)?.time ?? 0 : 0);
  });
  ui.next?.addEventListener('click', () => { playing = false; seekTo(events.find(e => e.time > T + 1e-6)?.time ?? total); });

  // 推進一個子步（d 為模擬時間）
  function step(d) {
    const next = advance ? advance(T, d) : T + d;
    if (next == null) { pause(); return; }
    if (next >= total - 1e-9) {
      if (looping()) { seekTo(0); return; }
      playing = false; go(total, false, d); onEnd(); return;
    }
    go(next, false, d);
  }

  seekTo(qp.has('t') ? +qp.get('t') : 0);
  return {
    get T() { return T; }, get playing() { return playing; }, total, seekTo, play, pause,
    get speed() { return speed; }, set speed(v) { speed = +v; if (ui.speed) ui.speed.value = speed; show(); },
    // 每格呼叫；播放中回傳 true（需要重繪）
    update(dt) {
      if (!playing) return false;
      const sim = dt * speed, n = maxStep > 0 ? Math.max(1, Math.ceil(sim / maxStep)) : 1;
      for (let k = 0; k < n && playing; k++) step(sim / n);
      return true;
    },
  };
}
