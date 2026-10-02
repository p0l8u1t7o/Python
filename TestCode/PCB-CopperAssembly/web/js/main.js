import {createElectricalInspector} from '@core/electrical/electrical-inspector.js';
import {setElectricalCutaway} from '@core/electrical/electrical-cabinet.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { routingLegend } from '@core/electrical/cable-routing.js';
routingLegend();
// 主程式：場景、節拍時間軸、UI、相機子畫面
import * as THREE from 'three';
import { createVisionOverlay } from '@core/ui/vision-overlay.js';
import { copperResults } from './vision-results.js';
const vision = createVisionOverlay();
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { LAYOUT, PRODUCT, RECIPES, smooth } from './layout.js';

const qp = new URLSearchParams(location.search);
// 場景物件與每個時間點的狀態都來自 project.js（與 core 統一檢查共用）；配方在建立時套用
const { createProject } = await import('./project.js');
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: qp.get('aa') !== '0', powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05; renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0d1117); scene.fog = new THREE.Fog(0x0d1117, 6000, 13000);
const room = new RoomEnvironment(renderer), pmrem = new THREE.PMREMGenerator(renderer);
room.traverse(o => { if (o.isPointLight) o.intensity = 240; });
scene.environment = pmrem.fromScene(room, .04).texture; room.dispose(); pmrem.dispose();
const camera = new THREE.PerspectiveCamera(40, 1, .1, 30000);
const controls = new OrbitControls(camera, canvas); controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 7; controls.maxDistance = 9000;
scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x2a2f36, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.5); sun.position.set(-1500, 3500, 2200); sun.castShadow = qp.get('shadow') !== '0'; sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -2200, right: 2200, top: 2200, bottom: -2200, near: 500, far: 9000 }); sun.shadow.bias = -0.0003; scene.add(sun);
sun.shadow.normalBias = .05;
const fill = new THREE.DirectionalLight(0x9fb8ff, 0.5); fill.position.set(1800, 1500, -1800); scene.add(fill);

const project = createProject({ scene, recipe: qp.get('recipe') }), sim = project.sim, plan = project.plan, M = project.machine;
const ui = Object.fromEntries(['phase', 'cycleHint', 'pA', 'pB', 'pT', 'nA', 'nB', 'nT', 'errBar', 'errVal', 'errLim', 'stationStatus', 'showPip', 'showGuards', 'showLabels', 'exportBtn', 'pipFrame', 'pipTitle', 'pipResult', 'pipSel',
  'playBtn', 'restartBtn', 'speed', 'speedVal', 'loop', 'previous', 'next', 'stepSelect', 'cycleTime', 'timeline', 'progBar', 'clock', 'stations'].map(id => [id, document.getElementById(id)]));
const total = project.total, nA = plan.heads.A.trips.flat().length, nB = plan.heads.B.trips.flat().length, N = plan.holes.length;
// 機種選單：換配方即重建頁面（實機：切換配方、供料盤清料換料、吸嘴快換）
for (const [key, r] of Object.entries(RECIPES)) { const o = document.createElement('option'); o.value = key; o.textContent = `機種：${r.name}`; document.getElementById('recipe').appendChild(o); }
document.getElementById('recipe').value = PRODUCT.recipe;
document.getElementById('recipe').onchange = e => { const q = new URLSearchParams(location.search); q.set('recipe', e.target.value); q.delete('t'); location.search = q.toString(); };
document.getElementById('subtitle').textContent = `350 × 350 mm 基板 · ${PRODUCT.name} · ±6 mil · 雙龍門 4 吸嘴＋飛越仰視補償 · 五站並行（穩態一節拍）`;
ui.timeline.max = total;
ui.cycleTime.textContent = `節拍 ${total.toFixed(1)} s（目標 60 s）· S2 放置 ${plan.s2End.toFixed(1)} s · 每頭 ${plan.heads.A.trips.length} 趟 × 4 顆`;
ui.cycleHint.textContent = `目標 60 s／片`;
ui.errLim.textContent = `規格 ±${PRODUCT.spec.toFixed(3)} mm（6 mil）`;
plan.milestones.forEach((m, i) => { const o = document.createElement('option'); o.value = i; o.textContent = `${m.t.toFixed(1)} s · ${m.label}`; ui.stepSelect.appendChild(o); });
const STATUS = [['S0', 'S0', '上料'], ['S1', 'S1', '定位'], ['S2A', 'S2A', '放置 A'], ['feederA', '供料 A', ''], ['S2B', 'S2B', '放置 B'], ['feederB', '供料 B', ''], ['S3', 'S3', '檢查'], ['S4', 'S4', '下料'], ['conveyor', '輸送', '']];
const statusEls = {};
for (const [key, tag] of STATUS) { const t = document.createElement('div'); t.className = 'tag'; t.textContent = tag; const x = document.createElement('div'); x.className = 'txt'; ui.stationStatus.append(t, x); statusEls[key] = x; }

// 站別按鈕 → 視角
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
const views = {
  electrical: [[900,850,1700],[0,410,-180]],
  wiring: [[-1900,2450,-1800],[0,1350,0]],
  board: () => closeView(false), hole: () => closeView(true),
  iso: [[-2300, 2100, 2300], [0, 950, 0]], s2: [[650, 1650, 1250], [0, 1000, 0]], head: [[40, 1060, 260], [-90, 958, 90]],
  feeder: [[-330, 1230, 560], [-300, 960, 330]], s1: [[X[1], 1550, 700], [X[1], 960, 0]], s3: [[X[3], 1550, 700], [X[3], 960, 0]],
  load: [[X[0] - 300, 1500, 1350], [X[0], 950, 280]], unload: [[X[4] + 300, 1500, 1350], [X[4], 950, 280]], top: [[0, 3800, 300], [0, 950, 0]],
};
let camAnim = null, currentView = '', lastFocus = null;
function setView(name, instant = false) {
  workspace.stopFollowing(); setElectricalCutaway(scene,name==='electrical');
  if (!views[name]) return;
  currentView = name; lastFocus = ['board', 'hole'].includes(name) ? focusPoint(name === 'hole') : null;
  camera.near = name === 'hole' ? .2 : 5; camera.updateProjectionMatrix();
  const [p, t] = (typeof views[name] === 'function' ? views[name]() : views[name]).map(a => new THREE.Vector3(...a));
  if (instant) { camAnim = null; camera.position.copy(p); controls.target.copy(t); controls.update(); } else camAnim = { p0: camera.position.clone(), t0: controls.target.clone(), p, t, u: 0 };
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));
holeSelect.onchange = () => setView('hole');
function inspectHole(state) {
  playing = false; ui.playBtn.textContent = '▶ 播放';
  const h = selectedHole();
  seekTo(state === 'empty' ? 2.8 : h.placeT + (state === 'before' ? -.06 : .25));
  setView('hole', true); render();
}
document.getElementById('emptyHole').onclick = () => inspectHole('empty');
document.getElementById('beforeInsert').onclick = () => inspectHole('before');
document.getElementById('afterInsert').onclick = () => inspectHole('after');

// 3D 標籤
const labels = [];
function addLabel(text, pos) { const el = document.createElement('div'); el.className = 'label3d'; el.innerHTML = text; document.getElementById('app').appendChild(el); labels.push({ el, pos: new THREE.Vector3(...pos) }); }
STNAMES.forEach((n, i) => addLabel(`<b>S${i}</b> ${n}`, [X[i], 1480, -120]));
addLabel('柔性供料 A', [LAYOUT.feeder.A.x, 1010, LAYOUT.feeder.A.z]); addLabel('柔性供料 B', [LAYOUT.feeder.B.x, 1010, LAYOUT.feeder.B.z]);
addLabel('仰視相機 A', [LAYOUT.upCam.A.x, 890, LAYOUT.upCam.A.z]); addLabel('仰視相機 B', [LAYOUT.upCam.B.x, 890, LAYOUT.upCam.B.z]);
addLabel('龍門 A（4 吸嘴）', [0, 1350, 360]); addLabel('龍門 B（4 吸嘴）', [0, 1350, -360]);

// ---------------------------------------------------------------- 時間
let T = 0, playing = !qp.has('pause'), speed = 1, info = null;
function pipSource() {
  const sel = ui.pipSel.value; if (sel !== 'auto') return sel;
  const a = plan.heads.A.tr.sample(T), b = plan.heads.B.tr.sample(T);
  if (a.seg?.flyby && !a.done) return 'upA';
  if (b.seg?.flyby && !b.done) return 'upB';
  const s1 = plan.s1.tr.sample(T); if (s1.label.startsWith('拍攝') || s1.label.startsWith('移至第')) return 's1';
  if (a.seg?.flash && !a.done) return 'downA';
  if (b.seg?.flash && !b.done) return 'downB';
  const s3=plan.s3.tr.sample(T);if(s3.seg?.flash&&!s3.done)return 's3';
  const feedB=plan.feeders.B.tr.sample(T);if(feedB.seg?.flash&&!feedB.done)return 'feedB';
  return 'feedA';
}
function pipInfo(src) {
  if (src === 'upA' || src === 'upB') {
    const H = src.slice(-1), e = plan.events.filter(e=>e.type==='upcam'&&e.H===H&&Math.abs(e.t-T)<.03).sort((a,b)=>Math.abs(a.t-T)-Math.abs(b.t-T))[0];
    if (!e) return [`仰視相機 ${H} · 即時畫面`, '等待吸嘴通過取像中心 · 無本幀量測'];
    const hold = plan.heads[H].hold[e.k].find(x => x.t0 <= e.t && e.t < x.t1), o = hold?.coin.pickOffset;
    return [`仰視相機 ${H} · 飛越取像 · 400 mm/s`, o ? `吸嘴 ${e.k + 1}：偏移 x ${o.dx >= 0 ? '+' : ''}${o.dx.toFixed(3)} · z ${o.dz >= 0 ? '+' : ''}${o.dz.toFixed(3)} mm · θ ${o.dt >= 0 ? '+' : ''}${o.dt.toFixed(1)}° → <span class="ok">放置時補償</span>` : '—'];
  }
  if (src === 's1') return ['S1 基板定位相機 · 20MP · 視野約 111 × 74 mm', `孔位量測 ${info.mapped} / ${N}`];
  if (src === 's3') return ['S3 檢查相機 · 20MP', `模擬檢查 ${info.inspected} / ${N}${info.inspected === N ? ' · <span class="ok">檢查完成</span>' : ''}`];
  if (src.startsWith('feed')) {const H=src.slice(-1);return [`供料相機 ${H} · 正反面與方向`, `盤面：${plan.feeders[H].coins.filter(c => c.t0 <= T && T < c.t1 && c.good).length} 顆可取`];}
  return [src.slice(-1)+' 頭下視相機 · 基準點', '板邊工具孔 → 修正 S1 孔位圖'];
}
const pipCams = { feedB: () => M.feeders.B.cam.cam, downB: () => M.heads.B.downCam.cam, upA: () => M.upCams.A.cam, upB: () => M.upCams.B.cam, s1: () => M.scanners.S1.cam.cam, s3: () => M.scanners.S3.cam.cam, feedA: () => M.feeders.A.cam.cam, downA: () => M.heads.A.downCam.cam };

function seekTo(t) { T = THREE.MathUtils.clamp(t, 0, total); render(); }
ui.playBtn.onclick = () => { if (T >= total) T = 0; playing = !playing; ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放'; };
ui.restartBtn.onclick = () => seekTo(0);
ui.speed.oninput = () => { speed = +ui.speed.value; ui.speedVal.textContent = speed.toFixed(2).replace(/0$/, '') + '×'; };
ui.timeline.oninput = () => { playing = false; ui.playBtn.textContent = '▶ 播放'; seekTo(+ui.timeline.value); };
const jumpMs = d => { playing = false; ui.playBtn.textContent = '▶ 播放'; const ms = plan.milestones; let i = ms.findIndex(m => m.t > T + 1e-6); if (d < 0) { i = -1; ms.forEach((m, j) => { if (m.t < T - 1e-6) i = j; }); } if (i >= 0) seekTo(ms[i].t); };
ui.previous.onclick = () => jumpMs(-1); ui.next.onclick = () => jumpMs(1);
ui.stepSelect.onchange = () => { playing = false; ui.playBtn.textContent = '▶ 播放'; seekTo(plan.milestones[+ui.stepSelect.value].t); };
ui.exportBtn.onclick = () => {
  const holes = plan.holes.map(h => ({ id: h.id + 1, column: h.col + 1, row: h.row + 1, xNominal: h.x, zNominal: h.z, head: h.by.H, nozzle: h.by.k + 1, trip: h.by.trip + 1, placeTime: +h.placeT.toFixed(3), errX: +h.ex.toFixed(4), errZ: +h.ez.toFixed(4), errMm: +h.err.toFixed(4), errMil: +(h.err / 0.0254).toFixed(2), thetaErrDeg: +h.et.toFixed(3) }));
  const report = { mode: 'SIMULATION', recipe: PRODUCT.recipe, recipeName: PRODUCT.name, assumptions: PRODUCT.source, cycleSec: +total.toFixed(2), s2PlaceSec: +plan.s2End.toFixed(2), specMm: PRODUCT.spec, maxErrMm: +plan.stats.maxErr.toFixed(4), meanErrMm: +plan.stats.meanErr.toFixed(4), errorModelSigmaMm: +plan.stats.sigma.toFixed(4), holes, physicalMeasurement: false };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = 'copper-insert-sim.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};

function drawHud() {
  info = project.apply(T, { playing });
  if (lastFocus) {
    const now = focusPoint(currentView === 'hole'), delta = now.clone().sub(lastFocus);
    camera.position.add(delta); controls.target.add(delta);
    if (camAnim) for (const key of ['p0', 't0', 'p', 't']) camAnim[key].add(delta);
    lastFocus = now;
    camera.lookAt(controls.target);
  }
  const h = selectedHole();
  document.getElementById('holeState').textContent = `#${h.id + 1} · ${T >= h.placeT ? '已放入' : '待放入'} · 名義單邊間隙 ${((PRODUCT.hole.w - PRODUCT.coin.w) / 2).toFixed(2)} mm`;
  const pl = info.placed, tot = pl.A + pl.B;
  ui.pA.style.width = pl.A / nA * 100 + '%'; ui.pB.style.width = pl.B / nB * 100 + '%'; ui.pT.style.width = tot / N * 100 + '%';
  ui.nA.textContent = `${pl.A} / ${nA}`; ui.nB.textContent = `${pl.B} / ${nB}`; ui.nT.textContent = `${tot} / ${N}`;
  ui.errBar.style.width = Math.min(100, info.maxErr / PRODUCT.spec * 100) + '%';
  ui.errVal.textContent = tot ? `最大 ${info.maxErr.toFixed(3)} mm（${(info.maxErr / 0.0254).toFixed(1)} mil）` : '—';
  for (const [key] of STATUS) statusEls[key].textContent = info.status[key] || '—';
  ui.phase.textContent = T >= total ? 'CYCLE END · 本節拍完成' : playing ? 'AUTO · 五站並行' : 'HOLD · 暫停';
  M.occluders.visible = ui.showGuards.checked;
  ui.timeline.value = T; ui.progBar.style.width = T / total * 100 + '%';
  ui.clock.textContent = `${Math.floor(T / 60).toString().padStart(2, '0')}:${(T % 60).toFixed(1).padStart(4, '0')}`;
  let mi = 0; plan.milestones.forEach((m, j) => { if (m.t <= T + 1e-6) mi = j; }); ui.stepSelect.value = mi;
  const src = pipSource(), [title, res] = pipInfo(src); ui.pipTitle.textContent = title; ui.pipResult.innerHTML = res;
  for (const l of labels) { const p = l.pos.clone().project(camera), vis = ui.showLabels.checked && p.z < 1 && Math.abs(p.x) < .98 && Math.abs(p.y) < .85; l.el.style.display = vis ? 'block' : 'none'; if (vis) { l.el.style.left = (p.x * .5 + .5) * canvas.clientWidth + 'px'; l.el.style.top = (-p.y * .5 + .5) * canvas.clientHeight + 'px'; } }
  document.getElementById('diagnostics').textContent = JSON.stringify({ T, total, placed: pl, maxErr: info.maxErr, mapped: info.mapped, inspected: info.inspected });
  return src;
}
function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
window.addEventListener('resize', resize);
function render() {
  const src=drawHud();workspace.follow();electrical.update({time:T,playing,action:'S0–S4 多站同步 · '+(T<plan.s2End?'雙頭放置':'換站'),motion:T<plan.s2End,vision:!!(plan.s3.tr.sample(T).seg?.flash)});
  const marks=document.getElementById('showMarks').checked;Object.values(sim.boards).forEach(b=>b.setAnnotations(marks));
  renderer.setScissorTest(false);renderer.setViewport(0,0,canvas.clientWidth,canvas.clientHeight);workspace.renderOverview(renderer,scene);
  const vis=M.occluders.visible;M.occluders.visible=false;Object.values(sim.boards).forEach(b=>b.setAnnotations(false));
  workspace.renderCamera({renderer,scene,camera:pipCams[src](),vision,marks:copperResults(src,T,plan,M,sim.boards)});
  M.occluders.visible=vis;Object.values(sim.boards).forEach(b=>b.setAnnotations(marks));
}
const workspace=createViewerWorkspace({camera,controls,canvas,resize,focusOccluders:[M.occluders],getFocus:()=>focusPoint(false),
  focusOffset:[0,190,440],onFocus:()=>{setElectricalCutaway(scene,false);camAnim=null;lastFocus=null;currentView='focus';document.querySelectorAll('.views button').forEach(b=>b.classList.remove('selected'));}});
const electrical=createElectricalInspector({scene,camera,controls,canvas,onEnter:()=>setView('electrical',true),onExit:()=>setView('iso',true),title:'PCB-CopperAssembly'});
const clock = new THREE.Clock();
function frame() {
  requestAnimationFrame(frame); const dt = Math.min(clock.getDelta(), 0.05);
  if (playing) { T += dt * speed; if (T >= total) { if (ui.loop.checked) T -= total; else { T = total; playing = false; ui.playBtn.textContent = '▶ 播放'; } } }
  if (camAnim) { camAnim.u = Math.min(1, camAnim.u + dt * 1.4); camera.position.lerpVectors(camAnim.p0, camAnim.p, smooth(camAnim.u)); controls.target.lerpVectors(camAnim.t0, camAnim.t, smooth(camAnim.u)); if (camAnim.u === 1) camAnim = null; }
  controls.update(); render();
}
resize(); ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放';
if (qp.has('t')) { playing = false; T = +qp.get('t') || 0; ui.playBtn.textContent = '▶ 播放'; }
if (qp.has('pip')) ui.pipSel.value = qp.get('pip');
T = THREE.MathUtils.clamp(T, 0, total); project.apply(T, { playing }); setView(qp.get('view') || 'iso', true);
const play = () => { if (T >= total) T = 0; playing = true; ui.playBtn.textContent = '⏸ 暫停'; };
const pause = () => { playing = false; ui.playBtn.textContent = '▶ 播放'; };
window.sim = { plan, seekTo, get T() { return T; }, setView, views: Object.keys(views), total, play, pause, project };
document.getElementById('loading').classList.add('hide'); render(); frame();
