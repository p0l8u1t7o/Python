// 主程式：場景、節拍時間軸、UI、相機子畫面
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { LAYOUT, PRODUCT, RECIPES, setRecipe, smooth } from './layout.js';

const qp = new URLSearchParams(location.search);
setRecipe(qp.get('recipe'));                            // 先套配方，再建機台與排程
const { createSim } = await import('./sim.js');
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: qp.get('aa') !== '0', powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.2; renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0d1117); scene.fog = new THREE.Fog(0x0d1117, 6000, 13000);
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;
const camera = new THREE.PerspectiveCamera(40, 1, 2, 30000);
const controls = new OrbitControls(camera, canvas); controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 30; controls.maxDistance = 9000;
scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x2a2f36, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.5); sun.position.set(-1500, 3500, 2200); sun.castShadow = qp.get('shadow') !== '0'; sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -2200, right: 2200, top: 2200, bottom: -2200, near: 500, far: 9000 }); sun.shadow.bias = -0.0003; scene.add(sun);
const fill = new THREE.DirectionalLight(0x9fb8ff, 0.5); fill.position.set(1800, 1500, -1800); scene.add(fill);

const sim = createSim(scene), plan = sim.plan, M = sim.machine;
const ui = Object.fromEntries(['phase', 'cycleHint', 'pA', 'pB', 'pT', 'nA', 'nB', 'nT', 'errBar', 'errVal', 'errLim', 'stationStatus', 'showPip', 'showGuards', 'showLabels', 'exportBtn', 'pipFrame', 'pipTitle', 'pipResult', 'pipSel',
  'playBtn', 'restartBtn', 'speed', 'speedVal', 'loop', 'previous', 'next', 'stepSelect', 'cycleTime', 'timeline', 'progBar', 'clock', 'stations'].map(id => [id, document.getElementById(id)]));
const total = plan.cycle, nA = plan.heads.A.trips.flat().length, nB = plan.heads.B.trips.flat().length, N = plan.holes.length;
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
const views = {
  iso: [[-2300, 2100, 2300], [0, 950, 0]], s2: [[650, 1650, 1250], [0, 1000, 0]], head: [[40, 1060, 260], [-90, 958, 90]],
  feeder: [[-330, 1230, 560], [-300, 960, 330]], s1: [[X[1], 1550, 700], [X[1], 960, 0]], s3: [[X[3], 1550, 700], [X[3], 960, 0]],
  load: [[X[0] - 300, 1500, 1350], [X[0], 950, 280]], unload: [[X[4] + 300, 1500, 1350], [X[4], 950, 280]], top: [[0, 3800, 300], [0, 950, 0]],
};
let camAnim = null;
function setView(name, instant = false) {
  if (!views[name]) return; const [p, t] = views[name].map(a => new THREE.Vector3(...a));
  if (instant) { camAnim = null; camera.position.copy(p); controls.target.copy(t); controls.update(); } else camAnim = { p0: camera.position.clone(), t0: controls.target.clone(), p, t, u: 0 };
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));

// 3D 標籤
const labels = [];
function addLabel(text, pos) { const el = document.createElement('div'); el.className = 'label3d'; el.innerHTML = text; document.getElementById('app').appendChild(el); labels.push({ el, pos: new THREE.Vector3(...pos) }); }
STNAMES.forEach((n, i) => addLabel(`<b>S${i}</b> ${n}`, [X[i], 1480, -120]));
addLabel('柔性供料 A', [LAYOUT.feeder.A.x, 1010, LAYOUT.feeder.A.z]); addLabel('柔性供料 B', [LAYOUT.feeder.B.x, 1010, LAYOUT.feeder.B.z]);
addLabel('仰視相機 A', [LAYOUT.upCam.A.x, 890, LAYOUT.upCam.A.z]); addLabel('仰視相機 B', [LAYOUT.upCam.B.x, 890, LAYOUT.upCam.B.z]);
addLabel('龍門 A（4 吸嘴）', [0, 1350, 360]); addLabel('龍門 B（4 吸嘴）', [0, 1350, -360]);

// ---------------------------------------------------------------- 時間
let T = 0, playing = !qp.has('pause'), speed = 1, info = null;
function lastUpcam(H) { let e = null; for (const x of plan.events) { if (x.t > T) break; if (x.type === 'upcam' && x.H === H) e = x; } return e; }
function pipSource() {
  const sel = ui.pipSel.value; if (sel !== 'auto') return sel;
  const a = plan.heads.A.tr.sample(T);
  if (a.seg?.flyby && !a.done) return 'upA';
  const s1 = plan.s1.tr.sample(T); if (s1.label.startsWith('拍攝') || s1.label.startsWith('移至第')) return 's1';
  if (a.seg?.flash && !a.done) return 'downA';
  return 'feedA';
}
function pipInfo(src) {
  if (src === 'upA' || src === 'upB') {
    const H = src.slice(-1), e = lastUpcam(H);
    if (!e) return [`仰視相機 ${H}`, '—'];
    const hold = plan.heads[H].hold[e.k].find(x => x.t0 <= e.t && e.t < x.t1), o = hold?.coin.pickOffset;
    return [`仰視相機 ${H} · 飛越取像 · 400 mm/s`, o ? `吸嘴 ${e.k + 1}：偏移 x ${o.dx >= 0 ? '+' : ''}${o.dx.toFixed(3)} · z ${o.dz >= 0 ? '+' : ''}${o.dz.toFixed(3)} mm · θ ${o.dt >= 0 ? '+' : ''}${o.dt.toFixed(1)}° → <span class="ok">放置時補償</span>` : '—'];
  }
  if (src === 's1') return ['S1 基板定位相機 · 20MP · 視野約 111 × 74 mm', `孔位量測 ${info.mapped} / ${N}`];
  if (src === 's3') return ['S3 檢查相機 · 20MP', `檢查 ${info.inspected} / ${N} · <span class="ok">全數在孔內</span>`];
  if (src === 'feedA') return ['供料相機 A · 找出正面朝上的銅片', `盤面：${plan.feeders.A.coins.filter(c => c.t0 <= T && T < c.t1 && c.good).length} 顆可取`];
  return ['A 頭下視相機 · 基準點', '板邊工具孔 → 修正 S1 孔位圖'];
}
const pipCams = { upA: () => M.upCams.A.cam, upB: () => M.upCams.B.cam, s1: () => M.scanners.S1.cam.cam, s3: () => M.scanners.S3.cam.cam, feedA: () => M.feeders.A.cam.cam, downA: () => M.heads.A.downCam.cam };

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
  info = sim.apply(T);
  const pl = info.placed, tot = pl.A + pl.B;
  ui.pA.style.width = pl.A / nA * 100 + '%'; ui.pB.style.width = pl.B / nB * 100 + '%'; ui.pT.style.width = tot / N * 100 + '%';
  ui.nA.textContent = `${pl.A} / ${nA}`; ui.nB.textContent = `${pl.B} / ${nB}`; ui.nT.textContent = `${tot} / ${N}`;
  ui.errBar.style.width = Math.min(100, info.maxErr / PRODUCT.spec * 100) + '%';
  ui.errVal.textContent = tot ? `最大 ${info.maxErr.toFixed(3)} mm（${(info.maxErr / 0.0254).toFixed(1)} mil）` : '—';
  for (const [key] of STATUS) statusEls[key].textContent = info.status[key] || '—';
  ui.phase.textContent = T >= total ? 'CYCLE END · 本節拍完成' : playing ? 'AUTO · 五站並行' : 'HOLD · 暫停';
  M.tower.set(playing ? 'green' : 'yellow'); M.occluders.visible = ui.showGuards.checked;
  ui.timeline.value = T; ui.progBar.style.width = T / total * 100 + '%';
  ui.clock.textContent = `${Math.floor(T / 60).toString().padStart(2, '0')}:${(T % 60).toFixed(1).padStart(4, '0')}`;
  let mi = 0; plan.milestones.forEach((m, j) => { if (m.t <= T + 1e-6) mi = j; }); ui.stepSelect.value = mi;
  ui.pipFrame.hidden = !ui.showPip.checked;
  const src = pipSource(), [title, res] = pipInfo(src); ui.pipTitle.textContent = title; ui.pipResult.innerHTML = res;
  for (const l of labels) { const p = l.pos.clone().project(camera), vis = ui.showLabels.checked && p.z < 1 && Math.abs(p.x) < .98 && Math.abs(p.y) < .85; l.el.style.display = vis ? 'block' : 'none'; if (vis) { l.el.style.left = (p.x * .5 + .5) * canvas.clientWidth + 'px'; l.el.style.top = (-p.y * .5 + .5) * canvas.clientHeight + 'px'; } }
  document.getElementById('diagnostics').textContent = JSON.stringify({ T, total, placed: pl, maxErr: info.maxErr, mapped: info.mapped, inspected: info.inspected });
  return src;
}
function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
window.addEventListener('resize', resize);
function render() {
  const src = drawHud(), w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setScissorTest(false); renderer.setViewport(0, 0, w, h); renderer.render(scene, camera);
  if (ui.showPip.checked) {
    const c = canvas.getBoundingClientRect(), f = ui.pipFrame.getBoundingClientRect(), cam = pipCams[src]();
    cam.aspect = f.width / f.height; cam.updateProjectionMatrix();
    const vis = M.occluders.visible; M.occluders.visible = false;
    renderer.setScissorTest(true); renderer.setScissor(f.left - c.left, c.bottom - f.bottom, f.width, f.height); renderer.setViewport(f.left - c.left, c.bottom - f.bottom, f.width, f.height);
    renderer.render(scene, cam); renderer.setScissorTest(false); renderer.setViewport(0, 0, w, h); M.occluders.visible = vis;
  }
}
const clock = new THREE.Clock();
function frame() {
  requestAnimationFrame(frame); const dt = Math.min(clock.getDelta(), 0.05);
  if (playing) { T += dt * speed; if (T >= total) { if (ui.loop.checked) T -= total; else { T = total; playing = false; ui.playBtn.textContent = '▶ 播放'; } } }
  if (camAnim) { camAnim.u = Math.min(1, camAnim.u + dt * 1.4); camera.position.lerpVectors(camAnim.p0, camAnim.p, smooth(camAnim.u)); controls.target.lerpVectors(camAnim.t0, camAnim.t, smooth(camAnim.u)); if (camAnim.u === 1) camAnim = null; }
  controls.update(); render();
}
setView(qp.get('view') || 'iso', true); resize(); ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放';
if (qp.has('t')) { playing = false; T = +qp.get('t') || 0; ui.playBtn.textContent = '▶ 播放'; }
if (qp.has('pip')) ui.pipSel.value = qp.get('pip');
window.sim = { plan, seekTo, get T() { return T; }, setView };
document.getElementById('loading').classList.add('hide'); render(); frame();
