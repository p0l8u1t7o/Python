// 主程式：舞台（core/ui/stage.js）＋播放控制（core/ui/player.js）＋本專案的視角、面板與相機子畫面。
// 場景與每個時間點的狀態全部來自 project.js（與 core 統一檢查共用）；配方在建立時套用。
import * as THREE from 'three';
import { createElectricalInspector } from '@core/electrical/electrical-inspector.js';
import { setElectricalCutaway } from '@core/electrical/electrical-cabinet.js';
import { routingLegend } from '@core/electrical/cable-routing.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { createVisionOverlay } from '@core/ui/vision-overlay.js';
import { createStage, exposeSim } from '@core/ui/stage.js';
import { createPlayer } from '@core/ui/player.js';
import { copperResults } from './vision-results.js';
import { actionOf } from './plan.js';
import { LAYOUT, PRODUCT, RECIPES } from './layout.js';
routingLegend();
const vision = createVisionOverlay();

const qp = new URLSearchParams(location.search);
const { createProject } = await import('./project.js');
const canvas = document.getElementById('c');
// 共用舞台：只傳與預設不同的部分（霧、環境點光 240、相機範圍、太陽位置與陰影相機）
// 不開對數深度（孔位特寫的近裁切面只有 0.2 mm）；?movie 時舞台會自動開
const stage = createStage({
  canvas, qp, exposure: 1.05, background: 0x0d1117, fog: [6000, 13000], logDepth: false,
  envLight: 240, envBlur: .04,
  camera: { fov: 40, near: .1, far: 30000 },
  controls: { minDistance: 7, maxDistance: 9000 },
  sun: { color: 0xffffff, intensity: 1.5, position: [-1500, 3500, 2200], target: [0, 0, 0],
    shadow: { mapSize: 2048, camera: { left: -2200, right: 2200, top: 2200, bottom: -2200, near: 500, far: 9000 }, bias: -.0003, normalBias: .05 } },
  fill: { color: 0x9fb8ff, intensity: .5, position: [1800, 1500, -1800] },
});
const { renderer, scene, camera, controls } = stage;

const project = createProject({ scene, recipe: qp.get('recipe') }), sim = project.sim, plan = project.plan, M = project.machine;
const ui = Object.fromEntries(['phase', 'cycleHint', 'pA', 'pB', 'pT', 'nA', 'nB', 'nT', 'errBar', 'errVal', 'errLim', 'stationStatus', 'showPip', 'showGuards', 'showLabels', 'exportBtn', 'pipFrame', 'pipTitle', 'pipResult', 'pipSel',
  'cycleTime', 'progBar', 'stations'].map(id => [id, document.getElementById(id)]));
const total = project.total, nA = plan.heads.A.trips.flat().length, nB = plan.heads.B.trips.flat().length, N = plan.holes.length;
// 機種選單：換配方即重建頁面（實機：切換配方、供料盤清料換料、吸嘴快換）
for (const [key, r] of Object.entries(RECIPES)) { const o = document.createElement('option'); o.value = key; o.textContent = `機種：${r.name}`; document.getElementById('recipe').appendChild(o); }
document.getElementById('recipe').value = PRODUCT.recipe;
document.getElementById('recipe').onchange = e => { const q = new URLSearchParams(location.search); q.set('recipe', e.target.value); q.delete('t'); location.search = q.toString(); };
document.getElementById('subtitle').textContent = `350 × 350 mm 基板 · ${PRODUCT.name} · ±6 mil · 雙龍門 4 吸嘴＋飛越仰視補償 · 五站並行（穩態一節拍）`;
ui.cycleTime.textContent = `節拍 ${total.toFixed(1)} s（目標 60 s）· S2 放置 ${plan.s2End.toFixed(1)} s · 每頭 ${plan.heads.A.trips.length} 趟 × 4 顆`;
ui.cycleHint.textContent = `目標 60 s／片`;
ui.errLim.textContent = `規格 ±${PRODUCT.spec.toFixed(3)} mm（6 mil）`;
const STATUS = [['S0', 'S0', '上料'], ['S1', 'S1', '定位'], ['S2A', 'S2A', '放置 A'], ['feederA', '供料 A', ''], ['S2B', 'S2B', '放置 B'], ['feederB', '供料 B', ''], ['S3', 'S3', '檢查'], ['S4', 'S4', '下料'], ['conveyor', '輸送', '']];
const statusEls = {};
for (const [key, tag] of STATUS) { const t = document.createElement('div'); t.className = 'tag'; t.textContent = tag; const x = document.createElement('div'); x.className = 'txt'; ui.stationStatus.append(t, x); statusEls[key] = x; }

// 站別按鈕 → 視角（五站同時作業，所以只換視角不跳時間）
const STNAMES = ['上料', '基板定位', '放置', '檢查', '下料'];
STNAMES.forEach((n, i) => { const b = document.createElement('button'); b.className = 'st'; b.dataset.st = i; b.innerHTML = `<span class="idx">S${i}</span>${n}`; b.onclick = () => setView(['load', 's1', 's2', 's3', 'unload'][i]); ui.stations.appendChild(b); });
const X = LAYOUT.stations;
const holeSelect = document.getElementById('holeSelect');
for (const h of plan.holes) { const o = document.createElement('option'); o.value = h.id; o.textContent = `#${h.id + 1} · 第 ${h.col + 1} 排 / 第 ${h.row + 1} 孔`; holeSelect.appendChild(o); }
holeSelect.value = plan.holes.reduce((a, b) => a.placeT < b.placeT ? a : b).id;
if (qp.has('hole') && plan.holes.some(h => h.id === +qp.get('hole') - 1)) holeSelect.value = +qp.get('hole') - 1;
const selectedHole = () => plan.holes[+holeSelect.value];
const dimension = p => p.shape === 'round' ? `Ø${p.w}` : `${p.w} × ${p.l}`;
document.getElementById('productDims').innerHTML = `<b>350 × 350</b><span>基板厚 ${PRODUCT.board.t}</span><span>孔洞 ${dimension(PRODUCT.hole)}</span><span>散熱片 ${dimension(PRODUCT.coin)} × ${PRODUCT.coin.t}</span>`;
function focusPoint(hole = true) {
  const h = selectedHole();
  return sim.boards.s1.group.localToWorld(new THREE.Vector3(hole ? h.x : 0, PRODUCT.board.adhesive + PRODUCT.board.t, hole ? h.z : 0));
}
function closeView(hole) {
  const t = focusPoint(hole), span = Math.max(PRODUCT.hole.l * 3, 23);
  // Keep the board overview below the gantry beam, including when the A beam crosses the board.
  return [t.clone().add(hole ? new THREE.Vector3(span * .4, span * .72, span) : new THREE.Vector3(200, 235, 450)).toArray(), t.toArray()];
}

// ---------------------------------------------------------------- 視角：[相機位置, 注視點] 或 () => [...]，切換用 stage.goTo
const views = {
  electrical: [[900,850,1700],[0,410,-180]],
  wiring: [[-1900,2450,-1800],[0,1350,0]],
  board: () => closeView(false), hole: () => closeView(true),
  iso: [[-2300, 2100, 2300], [0, 950, 0]], s2: [[650, 1650, 1250], [0, 1000, 0]], head: [[40, 1060, 260], [-90, 958, 90]],
  feeder: [[-330, 1230, 560], [-300, 960, 330]], s1: [[X[1], 1550, 700], [X[1], 960, 0]], s3: [[X[3], 1550, 700], [X[3], 960, 0]],
  load: [[X[0] - 300, 1500, 1350], [X[0], 950, 280]], unload: [[X[4] + 300, 1500, 1350], [X[4], 950, 280]], top: [[0, 3800, 300], [0, 950, 0]],
};
const TWEEN = .9;
// 基板近看／孔位細節：視角跟著輸送中的基板平移（stage.shiftView 連同進行中的轉場起訖點一起移，轉場中與轉場後都只加每格增量）
let follow = null;
function setView(name, instant = false) {
  workspace.stopFollowing(); setElectricalCutaway(scene, name === 'electrical');
  if (!views[name]) return;
  camera.near = name === 'hole' ? .2 : 5; camera.updateProjectionMatrix();
  const [p, t] = typeof views[name] === 'function' ? views[name]() : views[name];
  stage.goTo(p, t, instant, TWEEN);
  follow = ['board', 'hole'].includes(name) ? { hole: name === 'hole', last: focusPoint(name === 'hole') } : null;
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
}
function followBoard() {
  if (!follow) return;
  const now = focusPoint(follow.hole); stage.shiftView(now.clone().sub(follow.last)); follow.last = now;
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));
holeSelect.onchange = () => setView('hole');
function inspectHole(state) {
  player.pause();
  const h = selectedHole();
  seekTo(state === 'empty' ? 2.8 : h.placeT + (state === 'before' ? -.06 : .25));
  setView('hole', true); render();
}
document.getElementById('emptyHole').onclick = () => inspectHole('empty');
document.getElementById('beforeInsert').onclick = () => inspectHole('before');
document.getElementById('afterInsert').onclick = () => inspectHole('after');

// ---------------------------------------------------------------- 3D 標籤（共用舞台；顯示與否由「顯示設備標籤」決定）
const label = (html, pos) => stage.addLabel(html, new THREE.Vector3(...pos));
STNAMES.forEach((n, i) => label(`<b>S${i}</b> ${n}`, [X[i], 1480, -120]));
label('柔性供料 A', [LAYOUT.feeder.A.x, 1010, LAYOUT.feeder.A.z]); label('柔性供料 B', [LAYOUT.feeder.B.x, 1010, LAYOUT.feeder.B.z]);
label('仰視相機 A', [LAYOUT.upCam.A.x, 890, LAYOUT.upCam.A.z]); label('仰視相機 B', [LAYOUT.upCam.B.x, 890, LAYOUT.upCam.B.z]);
label('龍門 A（4 吸嘴）', [0, 1350, 360]); label('龍門 B（4 吸嘴）', [0, 1350, -360]);

// ---------------------------------------------------------------- 相機子畫面
let T = 0, info = null, player = null;
function pipSource() {
  const sel = ui.pipSel.value; if (sel !== 'auto') return sel;
  const a = plan.heads.A.tr.active(T), b = plan.heads.B.tr.active(T);
  if (a?.flyby) return 'upA';
  if (b?.flyby) return 'upB';
  const s1 = actionOf(plan.s1.tr.at(T)); if (s1.startsWith('拍攝') || s1.startsWith('移至第')) return 's1';
  if (a?.flash) return 'downA';
  if (b?.flash) return 'downB';
  if (plan.s3.tr.active(T)?.flash) return 's3';
  if (plan.feeders.B.tr.active(T)?.flash) return 'feedB';
  return 'feedA';
}
function pipInfo(src) {
  if (src === 'upA' || src === 'upB') {
    const H = src.slice(-1), e = plan.log.filter(e => e.type === 'upcam' && e.H === H && Math.abs(e.t - T) < .03).sort((a, b) => Math.abs(a.t - T) - Math.abs(b.t - T))[0];
    if (!e) return [`仰視相機 ${H} · 即時畫面`, '等待吸嘴通過取像中心 · 無本幀量測'];
    const hold = plan.heads[H].hold[e.k].find(x => x.t0 <= e.t && e.t < x.t1), o = hold?.coin.pickOffset;
    return [`仰視相機 ${H} · 飛越取像 · 400 mm/s`, o ? `吸嘴 ${e.k + 1}：偏移 x ${o.dx >= 0 ? '+' : ''}${o.dx.toFixed(3)} · z ${o.dz >= 0 ? '+' : ''}${o.dz.toFixed(3)} mm · θ ${o.dt >= 0 ? '+' : ''}${o.dt.toFixed(1)}° → <span class="ok">放置時補償</span>` : '—'];
  }
  if (src === 's1') return ['S1 基板定位相機 · 20MP · 視野約 111 × 74 mm', `孔位量測 ${info.mapped} / ${N}`];
  if (src === 's3') return ['S3 檢查相機 · 20MP', `模擬檢查 ${info.inspected} / ${N}${info.inspected === N ? ' · <span class="ok">檢查完成</span>' : ''}`];
  if (src.startsWith('feed')) { const H = src.slice(-1); return [`供料相機 ${H} · 正反面與方向`, `盤面：${plan.feeders[H].coins.filter(c => c.t0 <= T && T < c.t1 && c.good).length} 顆可取`]; }
  return [src.slice(-1) + ' 頭下視相機 · 基準點', '板邊工具孔 → 修正 S1 孔位圖'];
}
const pipCams = { feedB: () => M.feeders.B.cam.cam, downB: () => M.heads.B.downCam.cam, upA: () => M.upCams.A.cam, upB: () => M.upCams.B.cam, s1: () => M.scanners.S1.cam.cam, s3: () => M.scanners.S3.cam.cam, feedA: () => M.feeders.A.cam.cam, downA: () => M.heads.A.downCam.cam };

ui.exportBtn.onclick = () => {
  const holes = plan.holes.map(h => ({ id: h.id + 1, column: h.col + 1, row: h.row + 1, xNominal: h.x, zNominal: h.z, head: h.by.H, nozzle: h.by.k + 1, trip: h.by.trip + 1, placeTime: +h.placeT.toFixed(3), errX: +h.ex.toFixed(4), errZ: +h.ez.toFixed(4), errMm: +h.err.toFixed(4), errMil: +(h.err / 0.0254).toFixed(2), thetaErrDeg: +h.et.toFixed(3) }));
  const report = { mode: 'SIMULATION', recipe: PRODUCT.recipe, recipeName: PRODUCT.name, assumptions: PRODUCT.source, cycleSec: +total.toFixed(2), s2PlaceSec: +plan.s2End.toFixed(2), specMm: PRODUCT.spec, maxErrMm: +plan.stats.maxErr.toFixed(4), meanErrMm: +plan.stats.meanErr.toFixed(4), errorModelSigmaMm: +plan.stats.sigma.toFixed(4), holes, physicalMeasurement: false };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = 'copper-insert-sim.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};

// ---------------------------------------------------------------- 面板（每格更新；場景狀態由 player 經 applyAt 套用）
function drawHud() {
  followBoard();
  const h = selectedHole(), playing = player.playing;
  document.getElementById('holeState').textContent = `#${h.id + 1} · ${T >= h.placeT ? '已放入' : '待放入'} · 名義單邊間隙 ${((PRODUCT.hole.w - PRODUCT.coin.w) / 2).toFixed(2)} mm`;
  const pl = info.placed, tot = pl.A + pl.B;
  ui.pA.style.width = pl.A / nA * 100 + '%'; ui.pB.style.width = pl.B / nB * 100 + '%'; ui.pT.style.width = tot / N * 100 + '%';
  ui.nA.textContent = `${pl.A} / ${nA}`; ui.nB.textContent = `${pl.B} / ${nB}`; ui.nT.textContent = `${tot} / ${N}`;
  ui.errBar.style.width = Math.min(100, info.maxErr / PRODUCT.spec * 100) + '%';
  ui.errVal.textContent = tot ? `最大 ${info.maxErr.toFixed(3)} mm（${(info.maxErr / 0.0254).toFixed(1)} mil）` : '—';
  for (const [key] of STATUS) statusEls[key].textContent = info.status[key] || '—';
  ui.phase.textContent = T >= total ? 'CYCLE END · 本節拍完成' : playing ? 'AUTO · 五站並行' : 'HOLD · 暫停';
  M.occluders.visible = ui.showGuards.checked;
  ui.progBar.style.width = T / total * 100 + '%';
  const src = pipSource(), [title, res] = pipInfo(src); ui.pipTitle.textContent = title; ui.pipResult.innerHTML = res;
  stage.updateLabels(ui.showLabels.checked);   // 畫布在 #app 內的偏移由舞台處理
  document.getElementById('diagnostics').textContent = JSON.stringify({ T, total, placed: pl, maxErr: info.maxErr, mapped: info.mapped, inspected: info.inspected });
  return src;
}
// 一格畫面分三段：狀態與 HUD → 相機子畫面（另一個 render target，畫完還原 viewport）→ 主畫面總覽。
// 舞台迴圈在 tick 之後自己呼叫 renderer.render(scene, camera)，所以 tick 只做前兩段，並把場景留在「總覽」狀態；
// render() 則一次畫完整格（跳轉、孔位檢視、錄影用）。
const setMarks = on => Object.values(sim.boards).forEach(b => b.setAnnotations(on));
function prepareFrame() {
  const src = drawHud(); workspace.follow();
  electrical.update({ time: T, playing: player.playing, action: 'S0–S4 多站同步 · ' + (T < plan.s2End ? '雙頭放置' : '換站'), motion: T < plan.s2End, vision: !!plan.s3.tr.at(T).step?.flash });
  const marks = document.getElementById('showMarks').checked; setMarks(marks);
  return { src, marks };
}
function renderPip({ src, marks }) {
  const vis = M.occluders.visible; M.occluders.visible = false; setMarks(false);
  workspace.renderCamera({ renderer, scene, camera: pipCams[src](), vision, marks: copperResults(src, T, plan, M, sim.boards) });
  M.occluders.visible = vis; setMarks(marks);
}
const mainViewport = () => { renderer.setScissorTest(false); renderer.setViewport(0, 0, canvas.clientWidth, canvas.clientHeight); };
function render() {
  const f = prepareFrame();
  mainViewport(); workspace.renderOverview(renderer, scene);
  renderPip(f);
}
const workspace = createViewerWorkspace({ camera, controls, canvas, resize: stage.resize, focusOccluders: [M.occluders], getFocus: () => focusPoint(false),
  focusOffset: [0, 190, 440], onFocus: () => {
    setElectricalCutaway(scene, false); follow = null;
    stage.cancelTween();   // 停掉進行中的視角轉場，交給產品焦點追隨
    document.querySelectorAll('.views button').forEach(b => b.classList.remove('selected'));
  } });
const electrical = createElectricalInspector({ scene, camera, controls, canvas, onEnter: () => setView('electrical', true), onExit: () => setView('iso', true), title: 'PCB-CopperAssembly' });

// ---------------------------------------------------------------- 播放（core/ui/player.js）：時間只由 player 推進，畫面狀態一律經 applyAt(T)
// 循環播放：player 自動綁定 #loop 勾選框（播到結尾從頭再播）
const applyAt = t => { T = t; info = project.apply(T, { playing: player ? player.playing : false }); return info; };
player = createPlayer({ total, apply: applyAt, events: plan.events, qp });
if (qp.has('t')) player.pause();
const seekTo = t => { player.seekTo(t); render(); };
function tick(dt) {
  if (!player.update(dt)) applyAt(player.T);                                     // 暫停時照樣套用（三色燈隨播放狀態）
  renderPip(prepareFrame());
  // 舞台接著畫總覽：等同 workspace.renderOverview（跟隨焦點時隱藏護罩；drawHud 每格會依勾選還原）
  mainViewport(); if (workspace.following) M.occluders.visible = false;
}
if (qp.has('pip')) ui.pipSel.value = qp.get('pip');
stage.resize(); setView(qp.get('view') || 'iso', true);
exposeSim({ plan, seekTo, get T() { return player.T; }, setView, views: Object.keys(views), total, play: player.play, pause: player.pause, project,
  events: plan.events, stationStart: plan.stationStart, player, camera, controls, focusPoint,
  viewPose: name => (typeof views[name] === 'function' ? views[name]() : views[name]) });
document.getElementById('loading').classList.add('hide'); render(); stage.loop(tick);   // ?movie 時舞台不啟動迴圈

// ---------------------------------------------------------------- 展示影片（?movie）：由 core/movie/movie.js 以絕對時間逐格驅動
if (qp.has('movie')) {
  player.pause();
  const { installMovie } = await import('@core/movie/movie.js');
  installMovie({
    project: 'PCB-CopperAssembly', scene, renderer, camera, controls, render, setView, total,
    steps: [{ start: 0, dur: total, label: '雙頭植入與五站同步' }],
    sample(t) { player.seekTo(t); },
    focus: () => new THREE.Vector3(0, 1050, 0), offset: [-2150, 1350, 2650],
    detailShots: (() => {
      const active = tr => tr.steps.filter(s => s.action !== '待命'), end = s => s.start + s.dur;
      const span = (view, label, start, stop) => ({ view, label, simStart: Math.max(0, start), simDuration: Math.min(total, stop) - Math.max(0, start) });
      const load = active(plan.s0), unload = active(plan.s4);
      const vibration = plan.feeders.A.tr.steps.find(s => s.end.vib === 1);
      const placement = plan.log.find(e => e.type === 'place' && e.H === 'A');
      return [span('load', 'S0 上料 · 原速流程', load[0].start, end(load.at(-1))),
        span('s1', 'S1 孔位定位 · 掃描細節', plan.s1.shots[0].t, plan.s1.shots[0].t + 8),
        span('feeder', '銅片供料 · 震動翻面', vibration.start - 1, end(vibration) + 2),
        span('head', '吸嘴取放 · 對位與輕壓', placement.t - 2, placement.t + 3),
        span('s3', 'S3 植入檢查 · 掃描細節', plan.s3.shots[0].t, plan.s3.shots[0].t + 8),
        span('unload', 'S4 成品下料 · 原速流程', unload[0].start, end(unload.at(-1)))];
    })(),
  });
}
