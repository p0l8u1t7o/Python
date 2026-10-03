// 穩態一個節拍（takt）的完整排程：五片基板同時在五站作業。
// 每個機構是 core 時間軸（@core/anim/track.js 的 createTimeline）上的一條軌，步驟依絕對時間排列；
// 畫面與驗證都由同一份排程取樣，倒退／跳轉結果一致。
// 每一步的 action 是該機構當下的動作說明（狀態面板）；flash（曝光）、flyby（飛越取像）附加在步驟上。
// 下拉選單、上一步／下一步用 events（各站與每一趟的節點，標準格式 { time, dur, label, sub, station }）。
import { createTimeline, linear } from '@core/anim/track.js';
import { PRODUCT, HOLES, LAYOUT, MOTION, moveTime, ERRORS, rng, gauss, BOARD_TOP, COIN_SEAT_TOP, FEED_COIN_TOP } from './layout.js';

const { gantry: G, upCam: UC, feeder: FD, scan: SC } = LAYOUT;
const zTime = d => moveTime(d, MOTION.zV, MOTION.zA);

/** dur 秒內移到 to（五次曲線；extra.linear＝等速），其餘 extra 欄位附加在步驟上 */
function move(tr, dur, to, label, { linear: lin, ...extra } = {}) {
  return Object.assign(tr.add(dur, to, { action: label, ease: lin ? linear : undefined }), extra);
}
const wait = (tr, dur, label, extra) => move(tr, dur, {}, label, extra);
/** 停留到時間 t（留下一個停留步驟，狀態面板顯示 label） */
const until = (tr, t, label = '待命') => { if (t > tr.t + 1e-9) wait(tr, t - tr.t, label); };
/** 狀態面板文字：core Track.at(T) 的 step（最後一個已開始的步驟）的動作說明；還沒有步驟時為「待命」 */
export const actionOf = ({ step }) => step ? step.action : '待命';

export function buildPlan(seed = 20260911) {
  // log：取放、仰視取像、基準點的逐顆紀錄 { t, type, H, k, … }；milestones：各站與每一趟的節點（轉成 events）
  const r = rng(seed), log = [], milestones = [], tl = createTimeline();
  const ev = (t, type, data) => { log.push({ t, type, ...data }); };
  const T_TRANSFER = [0.3, 2.3], T_LIFT_UP = 2.7;

  // ---- 基板實際孔位（S2 上）：擺放偏移＋旋轉、收縮、個別孔位偏差 ----
  const place = { dx: 0.35, dz: -0.25, rot: 0.12 * Math.PI / 180, shrink: 60e-6 };
  const holes = HOLES.map(h => {
    const x0 = h.x * (1 - place.shrink) + gauss(r) * 0.04, z0 = h.z * (1 - place.shrink) + gauss(r) * 0.04;
    const c = Math.cos(place.rot), s = Math.sin(place.rot);
    return { ...h, lx: x0, lz: z0, ax: x0 * c - z0 * s + place.dx, az: x0 * s + z0 * c + place.dz };   // lx/lz：板上實際孔位；ax/az：S2 上的機台座標
  });
  // 每顆的放置誤差：孔位圖＋基準點＋龍門＋仰視相機＋釋放，各軸獨立常態分佈
  const sig = Math.hypot(ERRORS.holeMap, ERRORS.fiducial, ERRORS.gantry, ERRORS.upCam, ERRORS.release);
  for (const h of holes) { h.ex = gauss(r) * sig; h.ez = gauss(r) * sig; h.et = gauss(r) * ERRORS.theta; h.err = Math.hypot(h.ex, h.ez); }

  // ---- 輸送換站與頂升（S1–S3 共用）----
  const conveyor = tl.track('conveyor', { lift: 1, belt: 0, shift: 0 });
  move(conveyor, 0.3, { lift: 0 }, '頂升下降、真空破除');
  move(conveyor, 2.0, { belt: 1, shift: 700 }, '全線換站：各板前進一站');
  move(conveyor, 0.4, { lift: 1, belt: 0 }, '到位止擋、頂升＋真空吸附');
  milestones.push({ t: 0, st: 'ALL', label: '全線換站' });

  // ---- S1 基板視覺定位：20 張拍攝建立孔位圖 ----
  const scanTrack = (name, stLabel, verb) => {
    const homeX=name==='S1'?-175:175; // Park away from the neighbouring S2 gantry.
    const tr = tl.track(name, { x: homeX, z: -175 }); until(tr, T_LIFT_UP, '等待換站');
    const shots = [];
    SC.rows.forEach((z, ri) => (ri % 2 ? [...SC.cols].reverse() : SC.cols).forEach(x => {
      const d = Math.max(Math.abs(x - tr.state.x), Math.abs(z - tr.state.z));
      move(tr, moveTime(d) + MOTION.settle, { x, z }, `移至第 ${shots.length + 1} 格`);
      shots.push({ t: tr.t, x, z }); wait(tr, MOTION.scanShot, `${verb} ${shots.length}／20`, { flash: true });
    }));
    wait(tr, 0.3, stLabel);
    move(tr, moveTime(Math.max(Math.abs(homeX - tr.state.x), Math.abs(-175 - tr.state.z))), { x: homeX, z: -175 }, '回原點');
    return { tr, shots };
  };
  const s1 = scanTrack('S1', `建立 ${holes.length} 孔位圖（位置、角度、孔徑）`, '拍攝');
  const s3 = scanTrack('S3', `判定：${holes.length} 顆全部在孔內、偏差 ≤ ±6 mil`, '檢查');
  // 每個孔被哪一張涵蓋（S1 量到、S3 檢查到的時間）
  const inFov = (h, s) => Math.abs(h.x - s.x) <= SC.fov[0] / 2 - 3 && Math.abs(h.z - s.z) <= SC.fov[1] / 2 - 4;
  for (const h of holes) { h.mapT = s1.shots.find(s => inFov(h, s))?.t ?? Infinity; h.inspT = s3.shots.find(s => inFov(h, s))?.t ?? Infinity; }
  milestones.push({ t: T_LIFT_UP, st: 'S1', label: 'S1 開始掃描孔位' }, { t: T_LIFT_UP, st: 'S3', label: 'S3 開始檢查' });

  // ---- S2 雙龍門 ----
  const heads = {}, feeders = {};
  let coinSeq = 0;
  for (const H of ['A', 'B']) {
    const side = H === 'A' ? 1 : -1, fd = FD[H], cam = UC[H];
    // 分工：A 放 z>0 與中線 x>0；B 放 z<0 與中線 x<0。依排蛇行，從靠近供料盤的一側開始
    const mine = holes.filter(h => (H === 'A' ? h.z > 0 || (h.z === 0 && h.x > 0) : h.z < 0 || (h.z === 0 && h.x < 0)));
    const cols = [...new Set(mine.map(h => h.x))].sort((a, b) => (a - b) * (H === 'A' ? 1 : -1));
    const order = cols.flatMap((x, ci) => mine.filter(h => h.x === x).sort((a, b) => (b.z - a.z) * side * (ci % 2 ? -1 : 1)));
    const trips = []; for (let i = 0; i < order.length; i += 4) trips.push(order.slice(i, i + 4));
    // 供料盤：每次震動後重新攤開（示意：依配方的顆數、約 85% 毛邊面朝下可取；反面靠震動翻面）
    const feed = { H, coins: [], epochs: [] };
    const spread = (t, keep) => {
      const pos = [], list = [];
      for (const c of [...keep, ...Array.from({ length: PRODUCT.feederCount - keep.length }, () => ({ id: coinSeq++ }))]) {
        let x, z, ok = false, tries = 0;
        while (!ok && tries++ < 200) { x = fd.x + (r() - 0.5) * (FD.w - 20); z = fd.z + (r() - 0.5) * (FD.d - 20); ok = pos.every(p => Math.hypot(p[0] - x, p[1] - z) > PRODUCT.feederGap); }
        pos.push([x, z]);
        const rec = { id: c.id, x, z, theta: r() * 180, good: r() < 0.85, t0: t, t1: Infinity };
        feed.coins.push(rec); list.push(rec);
      }
      feed.epochs.push({ t, list }); return list;
    };
    let avail = spread(0, []);
    const tr = tl.track(H, { x: fd.x, nz: fd.z, ...Object.fromEntries([0, 1, 2, 3].flatMap(k => [[`y${k}`, LAYOUT.safeTip], [`t${k}`, 0]])) });
    const fr = tl.track('feeder' + H, { vib: 0 });
    const hold = [[], [], [], []];                        // 每支吸嘴的持有區間
    const xyMove = (x, nz, thetas, label, opts) => {
      const p = tr.state, d = Math.max(Math.abs(x - p.x), Math.abs(nz - p.nz));
      const dth = thetas ? Math.max(...thetas.map((t, k) => Math.abs(t - p[`t${k}`]))) / MOTION.thetaV : 0;
      const to = { x, nz }; if (thetas) thetas.forEach((t, k) => { to[`t${k}`] = t; });
      move(tr, Math.max(moveTime(d), dth) + MOTION.settle, to, label, opts);
    };
    trips.forEach((trip, j) => {
      // 1) 吸取：挑可取（正面）的銅片，吸嘴轉到銅片角度
      const goods = avail.filter(c => c.good && c.t1 === Infinity);
      if (goods.length < trip.length) throw new Error(`feeder ${H} starved`);
      const picked = goods.sort((a, b) => a.x - b.x).slice(0, trip.length);
      milestones.push({ t: tr.t, st: 'S2' + H, label: `${H} 頭第 ${j + 1} 趟：吸取 ${trip.length} 顆` });
      picked.forEach((c, k) => {
        c.pickOffset = { dx: gauss(r) * 0.15, dz: gauss(r) * 0.15, dt: gauss(r) * 2 };
        xyMove(c.x - G.nozzleDX[k], c.z, [0, 1, 2, 3].map(i => (i === k ? c.theta : tr.state[`t${i}`])), `吸嘴 ${k + 1} 對位並轉到銅片角度`);
        move(tr, zTime(LAYOUT.safeTip - FEED_COIN_TOP), { [`y${k}`]: FEED_COIN_TOP }, `吸嘴 ${k + 1} 下降`);
        wait(tr, MOTION.vacuum, `吸嘴 ${k + 1} 真空吸取`);
        c.t1 = tr.t; c.pickedBy = { H, k, trip: j }; hold[k].push({ t0: tr.t, coin: c });
        ev(tr.t, 'pick', { H, k, coin: c.id });
        move(tr, zTime(LAYOUT.safeTip - FEED_COIN_TOP), { [`y${k}`]: LAYOUT.safeTip }, `吸嘴 ${k + 1} 上升`);
      });
      // 供料盤：頭離開後震動、補料、重新攤開、拍照找正面銅片
      const tv = tr.t; until(fr, tv, '待命');
      move(fr, 0.6, { vib: 1 }, '震動攤料＋補料'); move(fr, 0.01, { vib: 0 }, '等待視野淨空');
      for (const c of avail) if (c.t1 === Infinity) c.t1 = tv + 0.6;
      avail = spread(tv + 0.6, avail.filter(c => c.t1 === tv + 0.6).map(c => ({ id: c.id })));
      // 2) 飛越仰視相機：等速通過，四支吸嘴依序觸發頻閃
      const xs = cam.x - G.nozzleDX[3] - 20, xe = cam.x - G.nozzleDX[0] + 20;
      xyMove(xs, cam.z, null, '移往仰視相機');
      const t0 = tr.t; move(tr, (xe - xs) / UC.flyV, { x: xe }, '飛越仰視相機：量測 4 顆偏移與角度', { linear: true, flyby: true });
      G.nozzleDX.forEach((dx, k) => { if (k < trip.length) ev(t0 + (cam.x - dx - xs) / UC.flyV, 'upcam', { H, k }); });
      // 3) 放置：等基板定位與基準點完成
      if (j === 0) {
        until(tr, T_LIFT_UP, '等待換站與頂升');
        const fids = PRODUCT.fiducials.filter(([, z]) => (H === 'A' ? z > 0 : z < 0));
        for (const [fx, fz] of fids) {
          xyMove(fx - side * G.downCamDX, fz - side * G.downCamOut, null, '移至基準點');
          wait(tr, MOTION.fidShot, `下視相機拍基準點（${fx}, ${fz}）`, { flash: true }); ev(tr.t, 'fid', { H, x: fx, z: fz });
        }
      }
      trip.forEach((h, k) => {
        // 仰視相機量到銅片在吸嘴上的偏移（dx, dz, dθ），放置時由吸嘴位置與角度反向補償
        const c = picked[k], th = h.angle + h.et - c.pickOffset.dt, a = th * Math.PI / 180;
        const offX = c.pickOffset.dx * Math.cos(a) + c.pickOffset.dz * Math.sin(a), offZ = -c.pickOffset.dx * Math.sin(a) + c.pickOffset.dz * Math.cos(a);
        const tx = h.ax + h.ex - offX - G.nozzleDX[k], tz = h.az + h.ez - offZ;
        xyMove(tx, tz, [0, 1, 2, 3].map(i => (i === k ? th : tr.state[`t${i}`])), `吸嘴 ${k + 1} 對位孔 #${h.id + 1}（仰視補償＋孔位圖）`);
        if (k === 0 && j < trips.length - 1) { until(fr, tr.t, '等待橫樑讓出供料視野'); wait(fr, .12, '供料相機拍照', { flash: true }); }
        move(tr, zTime(LAYOUT.safeTip - COIN_SEAT_TOP), { [`y${k}`]: COIN_SEAT_TOP }, `吸嘴 ${k + 1} 放入孔內`);
        wait(tr, MOTION.press, `輕壓 3 N 貼上黏紙`);
        h.placeT = tr.t; h.by = { H, k, trip: j }; hold[k][hold[k].length - 1].t1 = tr.t; hold[k][hold[k].length - 1].hole = h.id;
        ev(tr.t, 'place', { H, k, hole: h.id });
        wait(tr, MOTION.blow, '破真空吹氣');
        move(tr, zTime(LAYOUT.safeTip - COIN_SEAT_TOP), { [`y${k}`]: LAYOUT.safeTip }, `吸嘴 ${k + 1} 上升`);
      });
    });
    xyMove(fd.x, fd.z, [0, 0, 0, 0], '回供料盤待命');
    heads[H] = { tr, hold, trips, side };
    feeders[H] = { ...feed, tr: fr };
  }

  // ---- 節拍終點：所有機構回到起始姿勢（下一節拍由此接續）----
  const s2End = Math.max(...Object.values(heads).map(h => h.hold.flat().reduce((m, x) => Math.max(m, x.t1 || 0), 0)));
  // ---- S0 上料、S4 下料（料倉 ↔ 輸送線）----
  const loader = (name, fromZ, toZ, t0, labels) => {
    const tr = tl.track(name, { z: fromZ, y: 1, grip: 0 });
    until(tr, t0, '待命');
    move(tr, moveTime(LAYOUT.stackZ), { z: fromZ }, labels[0]); move(tr, 0.35, { y: 0 }, labels[1]); wait(tr, 0.25, '真空吸附'); move(tr, 0, { grip: 1 }, '');
    move(tr, 0.45, { y: 1 }, labels[2]); wait(tr, 0.3, labels[3]); move(tr, 0.6, { z: toZ }, labels[4]); move(tr, 0.35, { y: 0 }, labels[5]); move(tr, 0, { grip: 0 }, ''); wait(tr, 0.2, '破真空放下');
    move(tr, 0.35, { y: 1 }, '上升'); move(tr, 0.6, { z: fromZ }, '回待命');
    return tr;
  };
  // y：0＝吸盤貼板面，1＝上升到安全高度（實際高度由畫面換算）
  const s0 = loader('S0', LAYOUT.stackZ, 0, T_TRANSFER[1] + 0.2, ['移至料倉上方', '下降到最上層', '吸起並上升', '分板吹氣、雙片偵測', '移到輸送線 S0', '下降放板']);
  const s4 = loader('S4', 0, LAYOUT.stackZ, T_LIFT_UP, ['移至 S4 輸送線上方', '下降到基板', '吸起並上升', '確認已離開輸送線', '移到收料料倉', '下降疊放']);
  const cycle = Math.max(heads.A.tr.t, heads.B.tr.t, s1.tr.t, s3.tr.t, s0.t, s4.t, feeders.A.tr.t, feeders.B.tr.t) + 0.3;
  for (const tr of Object.values(tl.tracks)) until(tr, cycle, '待命');
  milestones.push({ t: s2End, st: 'S2', label: `S2 ${holes.length} 顆放置完成` });
  milestones.sort((a, b) => a.t - b.t);
  log.sort((a, b) => a.t - b.t);

  // ---- 標準事件介面（與 core/anim/sequence.js 相同：events、stationStart、total）----
  // 同一時刻的節點併成一筆（例如 S1、S3 同時開始）：選單一個時間只列一項，比並列多筆清楚
  const STATION = { S0: 0, S1: 1, S2: 2, S2A: 2, S2B: 2, S3: 3, S4: 4 };
  const events = [];
  for (const m of milestones) {
    const last = events.at(-1);
    if (last && Math.abs(last.time - m.t) < 1e-6) { last.label += '／' + m.label; if (last.station !== STATION[m.st]) last.station = null; continue; }
    events.push({ time: m.t, dur: 0, label: m.label, sub: '', station: STATION[m.st] ?? null });
  }
  events.forEach((e, i) => { e.dur = (events[i + 1]?.time ?? cycle) - e.time; });
  // 各站開始作業的時間（第一個不是待命／等待的步驟）
  const firstWork = (...trs) => Math.min(...trs.map(tr => tr.steps.find(s => s.action && !/^(待命|等待)/.test(s.action))?.start ?? cycle));
  const stationStart = [firstWork(s0), firstWork(s1.tr), firstWork(heads.A.tr, heads.B.tr), firstWork(s3.tr), firstWork(s4)];

  const errs = holes.map(h => h.err);
  return { seed, cycle, total: cycle, timeline: tl, events, stationStart, log, s2End, holes, heads, feeders, conveyor, s0, s1, s3, s4, place,
    stats: { maxErr: Math.max(...errs), meanErr: errs.reduce((a, b) => a + b, 0) / errs.length, sigma: sig } };
}
