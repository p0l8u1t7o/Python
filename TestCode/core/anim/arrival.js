// 手臂到位閘門：連續播放時手臂以限速追蹤目標，時間停在步驟終點等手臂到位才跨入下一步；等太久判到位逾時故障。
// 跳播（手臂直接到位）不經過這裡，只要呼叫 reset() 清除等待與故障。網頁（播放列的 advance）與 Node 驗證腳本共用同一份規則，不碰 DOM。
//
//   // sequence.js：本站規則（main.js 與 tools/verify.mjs 都 import）
//   export const ARRIVAL = { tolerance: { position: 1, angle: 1 }, contactPosition: 2, timeout: 8, maxStep: .01 };
//   // main.js：播放列的 advance 交給閘門，跳播時 reset
//   const gate = createArrivalGate({ ...ARRIVAL, total, error: () => robot.error(), step: () => current.step,
//     sample: t => { current = project.sample(t); }, update: h => robot.update(h), fault: () => ng ? 'NG · 停線' : '' });
//   const player = createPlayer({ total, advance: gate.advance,
//     apply: (T, { seek }) => { if (seek) { gate.reset(); current = project.apply(T); } return current; } });
//   // tools/verify.mjs：逐子步驅動
//   while (time < total) { const next = gate.step(time, .01); if (next == null) { /* gate.fault */ break; } time = next; }
//
// 選項：
//   total                       動畫總長（秒）
//   error()                     手臂誤差（例如 { position, angle, rail }），每個子步判斷前讀一次
//   step()                      目前步驟（最後一次取樣的 step，需有 start、dur，接觸步驟有 contact）
//   sample(t)                   取樣流程（不移動手臂關節）；停在步驟終點時閘門傳入終點前一點（仍屬本步驟，手臂目標不換到下一步）
//   update(h)                   手臂限速追蹤 h 秒
//   tolerance                   到位門檻 { 鍵: 上限 }：error() 任一鍵超過上限就是未到位
//   contactPosition             接觸步驟中位置誤差超過此值也要等（不必到步驟終點）
//   blocked(e, step, atEnd)     自訂「時間不可前進」規則；預設＝（atEnd 或接觸步驟位置誤差超過 contactPosition）且未到位
//   timeout／timeoutText        連續等待超過 timeout 秒（模擬時間）判到位逾時，故障文字為 timeoutText
//   fault()                     額外故障（例如 NG 停線）：回傳文字就停住；每個子步開始時檢查
//   maxStep                     advance 把一格切成不超過 maxStep 秒的等長子步（高倍速時手臂追蹤仍穩定）
//
// 回傳：
//   advance(t, dt)  給 createPlayer：回傳新時間，故障時回傳 null 停住（本格時間已前進時先回傳已推進的時間，下一格再回傳 null）；
//                   最後一步的終點先停在 total 前一點，手臂到位後才回傳 total（播放列在到位前不會結束）
//   step(t, h)      單一子步：回傳新時間（可等於 total），故障回傳 null；不切子步、不停在 total 前一點（驗證腳本用）
//   reset()         清除到位等待與故障（跳播、按播放恢復時呼叫）
//   waiting／fault  目前連續等待秒數與故障文字（沒有故障為 ''）
export function createArrivalGate({
  total, error, step: current, sample, update = () => { }, tolerance = { position: 1, angle: 1 }, contactPosition = Infinity,
  blocked = null, timeout = Infinity, timeoutText = '到位逾時 · 請檢查 TCP 姿態', fault: extra = null, maxStep = 0,
}) {
  const limits = Object.entries(tolerance);
  const isBlocked = blocked || ((e, s, atEnd) => (atEnd || (!!s.contact && e.position > contactPosition)) && limits.some(([k, v]) => e[k] > v));
  let waiting = 0, fault = '', done = false;

  // 單一子步：先查故障，再判斷到位——未到位就累計等待（時間不動），到位就推進時間（最多到步驟終點；已在終點則跨入下一步）並取樣；最後讓手臂追蹤 h 秒
  function step(t, h) {
    done = false;
    if (!fault && extra) fault = extra() || '';
    if (fault) return null;
    const s = current(), end = s.start + s.dur, atEnd = t >= end - 1e-7;
    if (isBlocked(error(), s, atEnd)) {
      waiting += h;
      if (waiting > timeout) { fault = timeoutText; return null; }
    } else {
      waiting = 0;
      t = atEnd ? Math.min(total, end + 1e-6) : Math.min(end, t + h);
      done = atEnd && t >= total;
      // 停在步驟終點時取樣終點前一點（仍屬本步驟）
      sample(t >= end - 1e-7 && t <= end ? Math.max(s.start, end - 1e-8) : t);
    }
    update(h);
    return t;
  }
  // 最後一步的終點尚未確認到位：先停在 total 前一點
  const hold = t => t >= total - 1e-9 ? total - 1e-8 : t;
  function advance(t, dt) {
    const n = maxStep > 0 ? Math.max(1, Math.ceil(dt / maxStep)) : 1, h = dt / n, t0 = t;
    for (let k = 0; k < n; k++) {
      const next = step(t, h);
      // 故障：本格時間沒前進就立即停住；已前進則先回傳已推進的時間（下一格再停）
      if (next == null) return t !== t0 ? hold(t) : null;
      t = next;
      if (done) return total;   // 最後一步已到位：播完
    }
    return hold(t);
  }
  function reset() { waiting = 0; fault = ''; }
  return { advance, step, reset, get waiting() { return waiting; }, get fault() { return fault; } };
}
