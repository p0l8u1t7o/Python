// 主程式：場景、依絕對時間套用各設備狀態、側欄面板、視角與相機子畫面。
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { RACK, COLUMN, UPRIGHT, DECAP, BOOTH, WASTE, layoutChecks, ROBOT, LABEL, LYING, INBOUND, PAYLOAD, payloadAt } from './layout.js';
import { MAT, D2R, smooth } from '@core/geom/parts.js';
import { applyPlant } from './plant.js';
import { createProject } from './project.js';
import { STATIONS, DRUM_IDS, IN_IDS, DRUM_KEYS, SPRAY_S, SPRAY_SINGLE_S } from './sequence.js';
import { finishMaterials } from '@core/geom/hardware.js';
import { createFocusTracking, createCameraWindow } from '@core/ui/view-controls.js';

const qp = new URLSearchParams(location.search);
// ---------------------------------------------------------------- 場景
const canvas = document.getElementById('c');
// 對數深度緩衝：場景 15 m、細節到 mm，一般深度緩衝會讓貼地的分區、標線互搶深度而閃爍
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance', logarithmicDepthBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.shadowMap.autoUpdate = false;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMappingExposure = .86;
finishMaterials(renderer);
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0d1117);
const pmrem = new THREE.PMREMGenerator(renderer), room = new RoomEnvironment(renderer);
scene.environment = pmrem.fromScene(room, .04).texture; room.dispose(); pmrem.dispose();
// r160 的環境反射強度設在材質 envMapIntensity（finishMaterials）。
const camera = new THREE.PerspectiveCamera(40, 1, 100, 150000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = .08; controls.maxPolarAngle = Math.PI * .495; controls.minDistance = 400; controls.maxDistance = 70000;
scene.add(new THREE.HemisphereLight(0xcfe0ff, 0x30363d, .55));
const sun = new THREE.DirectionalLight(0xffffff, 1.7); sun.position.set(-3000, 17000, 4000); sun.target.position.set(5000, 0, 8000);
sun.castShadow = renderer.shadowMap.enabled; sun.shadow.mapSize.set(4096, 4096);
Object.assign(sun.shadow.camera, { left: -11000, right: 11000, top: 11000, bottom: -11000, near: 2000, far: 40000 });
sun.shadow.bias = -.0003; sun.shadow.normalBias = 3; scene.add(sun, sun.target);
const fill = new THREE.DirectionalLight(0x9fb8ff, .45); fill.position.set(16000, 9000, 22000); scene.add(fill);

// ---------------------------------------------------------------- 物件（與 core 統一檢查共用 project.js）
const project = createProject({ scene });
const { plant, seq } = project;
const { building, storage, agv, line, robot, washing, inbound, drums } = plant;

// 相機取像事件（子畫面用）
const shots = [];
for (const [key, cam, title] of [['labeler', line.labelCam, '貼標相機 · 桶塞定位／標籤檢查（模擬影像）'], ['decap', line.decapCam, '頂視相機 · 桶塞定位（模擬影像）']])
  for (const s of seq.tracks[key].steps) if (s.end.flash && !s.initial.flash) shots.push({ start: s.start, cam, title, result: s.sub });
shots.sort((a, b) => a.start - b.start);

// ---------------------------------------------------------------- 套用狀態
let S = null;
function applyState(sm) {
  needsFrame = true; renderer.shadowMap.needsUpdate = true;
  S = sm; applyPlant(plant, sm, { playing });
}

// ---------------------------------------------------------------- UI
const ui = Object.fromEntries(['payload', 'playBtn', 'restartBtn', 'speed', 'speedVal', 'stepSelect', 'previous', 'next', 'timeline', 'clock', 'cycleTime', 'phase', 'equip', 'drums', 'tanks', 'checks', 'chkCount', 'showDims', 'showFence', 'showLabels', 'showCeiling', 'xray', 'showPip', 'pip', 'pipTitle', 'pipResult', 'stations'].map(id => [id, document.getElementById(id)]));
const SPEEDS = [.25, .5, 1, 2, 4, 8];
let T = 0, playing = !qp.has('pause'), speed = 1, selectedView = 'iso', camAnim = null, needsFrame = true;
function focusPosition(key) {
  if (key === 'gripper') return robot.tool.localToWorld(new THREE.Vector3(0, 80, ROBOT.grip * .65));
  if (key === 'agv') return agv.root.position.clone().add(new THREE.Vector3(0, 750, 0));
  if (key === 'gantry') return line.gantryPivot.getWorldPosition(new THREE.Vector3());
  if (key === 'auto') {
    key = ['robot', 'gantry', 'upender', 'upright', 'lying', 'jib', 'dolly', 'pallet'].map(mode => DRUM_KEYS.find(k => S.st[k].mode === mode)).find(Boolean);
  }
  const i = DRUM_KEYS.indexOf(key);
  return i >= 0 && drums[i].root.visible ? drums[i].root.position.clone() : null;
}
function gripperOffset() {
  const forward = new THREE.Vector3().setFromMatrixColumn(robot.tool.matrixWorld, 2); forward.y = 0; forward.normalize();
  const side = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), forward);
  const p = robot.tcp.getWorldPosition(new THREE.Vector3());
  if (p.z > BOOTH.z0 - 150 && p.x < BOOTH.x1) return forward.multiplyScalar(-1850).addScaledVector(side, -350).add(new THREE.Vector3(0, 800, 0));
  return forward.multiplyScalar(-1320).addScaledVector(side, -1140).add(new THREE.Vector3(0, 960, 0));
}
const focus = createFocusTracking({camera, controls, getTarget: focusPosition,
  getOffset: key => key === 'gripper' ? gripperOffset() : new THREE.Vector3(-2200, 1800, 2400), onFocus() {
  camAnim = null; selectedView = 'focus';
  document.querySelectorAll('.views button[data-view]').forEach(b => b.classList.remove('selected'));
}});
const cameraWindow = createCameraWindow(canvas, ui.showPip);
const gripperCam = new THREE.PerspectiveCamera(42, 1, 30, 25000);
const total = seq.total;
ui.timeline.max = total; ui.cycleTime.textContent = `本棧板 4 桶共 ${Math.round(total)} s（模擬時間）`;
// 手臂節拍：相鄰兩桶放回輸送線的間隔
const placed = seq.events.filter(e => e.label.endsWith('放回輸送線')).map(e => e.time), cycle = placed.at(-1) - placed.at(-2);
document.getElementById('cycleNote').textContent = `散桶入庫 4 桶＋一個棧板（4 桶）走完全線。手臂一桶約 ${cycle.toFixed(0)} s，是整線瓶頸（約 ${Math.floor(3600 / cycle)} 桶／h；200 桶約 ${(200 * cycle / 3600).toFixed(1)} h）。雙孔進水每道 ${SPRAY_S.toFixed(1)} s（單孔 ${SPRAY_SINGLE_S.toFixed(0)} s）。`;
seq.events.forEach((e, i) => { const o = document.createElement('option'); o.value = i; const st = STATIONS.find(s => s.id === e.station); o.textContent = `${fmt(e.time)}  ${st.short} ${st.name} · ${e.label}`; ui.stepSelect.appendChild(o); });
const VIEW_OF = { inbound: 'inbound', agv: 'storage', gantry: 'gantry', label: 'label', upender: 'upender', decap: 'decap', robot: 'robot', waste: 'waste' };
for (const s of STATIONS) {
  const b = document.createElement('button'); b.className = 'st'; b.dataset.st = s.id; b.innerHTML = `<span class="idx">${s.short}</span>${s.name}`;
  b.onclick = () => { seekTo(seq.stationStart[s.id]); setView(VIEW_OF[s.id]); }; ui.stations.appendChild(b);
}
const EQUIP = [['dolly', '入庫台車'], ['jib', '入庫懸臂吊'], ['agv', 'AGV'], ['shuttle', '穿梭車'], ['gantry', '龍門'], ['labeler', '貼標讀碼'], ['upender', '翻桶機'], ['decap', '開蓋站'], ['robot', '清洗手臂'], ['booth', '沖洗站'], ['sump', '集液／泵'], ['scale', '秤重段']];
ui.equip.innerHTML = EQUIP.map(([k, n]) => `<div class="row" data-k="${k}"><span class="name"><i></i>${n}</span><span class="act"></span></div>`).join('');
ui.drums.innerHTML = DRUM_IDS.map((id, k) => `<div class="d" data-k="${k}"><span class="id">${id}</span><span class="state"></span><span class="tags"></span></div>`).join('')
  + `<div class="d inb"><span class="id">入庫 0101–0104</span><span class="state"></span></div>`;
const TANKS = [['WA', '#c77b34'], ['WB', '#8c6bd6'], ['R', '#58b6f2'], ['F', '#8fd3ff']];
ui.tanks.innerHTML = TANKS.map(([k, c]) => `<div class="tank" data-k="${k}"><span>${WASTE.tanks[k].name}</span><span class="bar"><i style="background:${c}"></i></span><span class="v"></span></div>`).join('');
const checks = layoutChecks();
ui.checks.innerHTML = checks.map(c => `<li class="${c.ok ? '' : 'ng'}"><span class="mk">${c.ok ? '✓' : '!'}</span><span><b>${c.group}｜${c.name}</b><small>${c.value}</small></span></li>`).join('');
ui.chkCount.textContent = `${checks.filter(c => c.ok).length} / ${checks.length} 通過`;

function fmt(t) { return `${String(Math.floor(t / 60)).padStart(2, '0')}:${(t % 60).toFixed(1).padStart(4, '0')}`; }
function seekTo(t) { T = THREE.MathUtils.clamp(Number.isFinite(t) ? t : 0, 0, total); applyState(seq.sample(T)); focus.snap(); }
ui.playBtn.onclick = () => { if (T >= total) seekTo(0); playing = !playing; };
ui.restartBtn.onclick = () => { seekTo(0); playing = true; };
ui.speed.oninput = () => { speed = SPEEDS[+ui.speed.value]; ui.speedVal.textContent = speed + '×'; };
ui.timeline.oninput = () => { playing = false; seekTo(+ui.timeline.value); };
ui.stepSelect.onchange = () => { playing = false; seekTo(seq.events[+ui.stepSelect.value].time); };
const eventIndex = () => { let i = 0; seq.events.forEach((e, k) => { if (e.time <= T + 1e-6) i = k; }); return i; };
ui.previous.onclick = () => { playing = false; const i = eventIndex(); seekTo(seq.events[Math.max(0, seq.events[i].time < T - .5 ? i : i - 1)].time); };
ui.next.onclick = () => { playing = false; seekTo(seq.events[Math.min(seq.events.length - 1, eventIndex() + 1)].time); };
ui.showDims.onchange = () => { building.dims.visible = ui.showDims.checked; };
ui.showFence.onchange = () => { line.fences.visible = ui.showFence.checked; };
ui.showCeiling.onchange = () => { building.ceiling.visible = ui.showCeiling.checked; };
document.getElementById('cutaway').onchange = e => {
  for (const m of [MAT.pp, MAT.tankW]) { m.transparent = e.target.checked; m.opacity = e.target.checked ? .2 : 1; m.depthWrite = !e.target.checked; m.needsUpdate = true; }
};
ui.xray.onchange = () => drums.forEach(d => d.setXray(ui.xray.checked));

// ---------------------------------------------------------------- 視角
const VIEWS = {
  iso: [[-3500, 14500, 24000], [5600, 0, 8200]], top: [[5040, 28000, 7790], [5040, 0, 7760]],
  storage: [[2300, 4300, 8600], [6300, 1500, 3800]], gantry: [[1200, 4300, 13800], [4700, 1100, 9700]],
  label: [[6300, 2600, 7600], [7550, 850, 9750]], upender: [[8400, 3600, 7400], [10900, 1000, 10100]],
  decap: [[9700, 3300, 8900], [11290, 1350, 11000]], robot: [[6200, 5600, 10200], [9900, 1100, 13400]],
  booth: [[7600, 2800, 12000], [9400, 1350, 14700]], waste: [[1500, 4300, 11600], [5000, 800, 14600]],
  inbound: [[-900, 3900, 7400], [2300, 900, 2900]], weigh: [[10150, 1500, 12650], [11292, 650, 13400]],
};
function setView(name, instant = false) {
  if (!VIEWS[name] && name !== 'follow' && name !== 'gripper') return;
  focus.stop();
  selectedView = name;
  document.querySelectorAll('.views button[data-view]').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
  if (name === 'follow') {
    const p = focusPosition('drum0');
    if (p) { controls.target.copy(p); camera.position.copy(p).add(new THREE.Vector3(-2600, 2200, 2600)); }
    focus.start('drum0'); return;
  }
  const t = name === 'gripper' ? focusPosition('gripper') : new THREE.Vector3(...VIEWS[name][1]);
  const p = name === 'gripper' ? t.clone().add(gripperOffset()) : new THREE.Vector3(...VIEWS[name][0]);
  if (instant) { camAnim = null; camera.position.copy(p); controls.target.copy(t); controls.update(); }
  else camAnim = { p0: camera.position.clone(), t0: controls.target.clone(), p, t, u: 0 };
}
document.querySelectorAll('.views button[data-view]').forEach(b => b.onclick = () => setView(b.dataset.view));
controls.addEventListener('start', () => { camAnim = null; });
controls.addEventListener('change', () => { needsFrame = true; });
for (const type of ['input', 'change', 'click', 'pointermove', 'keydown']) document.getElementById('app').addEventListener(type, () => { needsFrame = true; if (type === 'change') renderer.shadowMap.needsUpdate = true; });

// 3D 標籤
const labels = [];
function addLabel(html, getPos, cls = '') { const el = document.createElement('div'); el.className = 'label3d ' + cls; el.innerHTML = html; document.getElementById('app').appendChild(el); labels.push({ el, getPos, dim: cls === 'dim' }); }
const P = (x, y, z) => () => new THREE.Vector3(x, y, z);
addLabel('<b>倉儲</b> 穿梭車密集架 212 桶', P(6000, 4000, 2700));
addLabel('<b>AGV</b> 平衡重式堆高', () => agv.root.position.clone().add(new THREE.Vector3(0, 2500, 0)));
addLabel('<b>S2</b> 棧板站＋龍門翻轉夾爪', P(4800, 3600, 9050));
addLabel('<b>S3</b> 貼標＋讀碼', P(LABEL.x, 2350, LYING.z + 500));
addLabel('<b>S4</b> 90° 翻桶機', P(10500, 1700, 9500));
addLabel('<b>S5</b> 自動開蓋站', P(UPRIGHT.x, 2900, DECAP.z));
addLabel('<b>S6</b> FANUC R-2000iC/165F', P(ROBOT.x, 2700, ROBOT.z - 300));
addLabel('<b>S6</b> 沖洗站', P(9500, 2950, BOOTH.z0 + 200));
addLabel('<b>S7</b> 廢液回收', P(5700, 2500, 14300));
addLabel('<b>S0</b> 散桶入庫（捲門＋懸臂吊）', P(1500, 3500, INBOUND.z));
addLabel('裝填區（下一站）', P(11400, 1500, 14700));
addLabel('結構柱', P(COLUMN.x, 2600, COLUMN.z));
for (const d of building.dimLabels) addLabel(d.text, () => d.pos, 'dim');

// ---------------------------------------------------------------- 面板更新
function drawHud() {
  const st = S.st, act = seq.activity(T);
  ui.phase.textContent = T >= total - 2 ? 'COMPLETE · 本棧板 4 桶完成' : playing ? `AUTO · 執行中 ${speed}×` : 'HOLD · 暫停';
  for (const row of ui.equip.children) {
    const s = act[row.dataset.k]; row.classList.toggle('on', !!s);
    row.querySelector('.act').innerHTML = s ? `${s.action}${s.sub ? `<small>${s.sub}</small>` : ''}` : '<span style="color:#6f8190">待命</span>';
  }
  for (const row of ui.drums.children) {
    if (row.classList.contains('inb')) { const n = IN_IDS.filter((_, i) => st['in' + i].mode === 'pallet').length; row.querySelector('.state').textContent = st.in0.state === '已入架' ? '4 桶已入架（第 3 道底層）' : `已上棧板 ${n}/4`; continue; }
    const s = st['drum' + row.dataset.k];
    row.querySelector('.state').textContent = s.state;
    row.querySelector('.tags').innerHTML = [
      [s.label ? (s.read ? `讀碼 OK · ${s.chem === 'acid' ? '酸性' : '鹼性'}` : '已貼標') : '未貼標', s.read],
      [s.capBig || s.capSmall ? '桶蓋未開' : '桶口已開', !s.capBig && !s.capSmall],
      [`沖洗 ${s.rinse}/3`, s.rinse === 3 && s.mode !== 'robot'],
      [s.weighG >= 0 ? `殘水 ${s.weighG} g OK` : s.dry ? `熱風吹乾（附著 ${s.film.toFixed(0)} g）` : s.film > 0 ? `附著水 ${s.film.toFixed(0)} g` : `桶內水 ${s.water.toFixed(1)} L`, s.weighG >= 0],
    ].map(([t, ok]) => `<span class="tag ${ok ? 'ok' : ''}">${t}</span>`).join('');
  }
  // 手臂負載：夾持中的桶＋桶內水量
  const heldKey = DRUM_IDS.map((_, k) => 'drum' + k).find(k => st[k].mode === 'robot'), pl = payloadAt(heldKey ? st[heldKey].water : 0, !!heldKey);
  for (const [k, v, lim, unit] of [['kg', pl.kg, PAYLOAD.rated, 'kg'], ['j5', pl.j5, PAYLOAD.moment.j5, 'N·m'], ['j6', pl.j6, PAYLOAD.moment.j6, 'N·m'], ['i5', pl.i5, PAYLOAD.inertia.j5, 'kg·m²']]) {
    const row = ui.payload.querySelector(`[data-k="${k}"]`), r = v / lim; row.querySelector('i').style.width = Math.min(100, r * 100).toFixed(1) + '%';
    row.querySelector('i').style.background = r > .9 ? '#ff4d4d' : r > .7 ? '#ffb020' : '#3dd68c'; row.querySelector('.v').textContent = `${v.toFixed(unit === 'kg·m²' ? 1 : 0)} / ${lim}`;
  }
  for (const row of ui.tanks.children) { const k = row.dataset.k, v = st.tanks[k], cap = WASTE.tanks[k].cap; row.querySelector('i').style.width = (v / cap * 100).toFixed(1) + '%'; row.querySelector('.v').textContent = `${v.toFixed(0)} L`; }
  const ACT_OF = { label: 'labeler', waste: 'sump', inbound: 'jib' };
  document.querySelectorAll('#stations .st').forEach(b => b.classList.toggle('active', !!act[ACT_OF[b.dataset.st] || b.dataset.st]));
  ui.timeline.value = T; ui.clock.textContent = fmt(T); ui.stepSelect.value = eventIndex();
  ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放';
  const rect = canvas.getBoundingClientRect();
  for (const l of labels) {
    const visible = l.dim ? ui.showDims.checked : ui.showLabels.checked;
    const p = l.getPos().clone().project(camera), on = visible && p.z < 1 && Math.abs(p.x) < .97 && Math.abs(p.y) < .95;
    l.el.style.display = on ? 'block' : 'none';
    if (on) { l.el.style.left = rect.left + (p.x * .5 + .5) * rect.width + 'px'; l.el.style.top = rect.top + (-p.y * .5 + .5) * rect.height + 'px'; }
  }
  document.getElementById('diagnostics').textContent = JSON.stringify({ T, total, playing, view: selectedView, agv: st.agv, gantry: st.gantry, drums: DRUM_IDS.map((_, k) => st['drum' + k].state), robot: S.robot.err || null });
}

// ---------------------------------------------------------------- 繪製
function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); needsFrame = true; }
addEventListener('resize', resize);
function render(dt) {
  washing.tick(T);
  drawHud();
  const w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setScissorTest(false); renderer.setViewport(0, 0, w, h); renderer.render(scene, camera);
  // 相機子畫面：最近 4 秒內有取像才顯示
  const source = cameraWindow.source;
  const shot = shots.filter(s => s.start <= T).at(-1);
  const inspectionCam = source === 'decap' ? line.decapCam : source === 'label' ? line.labelCam : shot?.cam || line.labelCam;
  const pipCam = source === 'gripper' ? gripperCam : inspectionCam;
  if (source === 'gripper') {
    const target = focusPosition('gripper');
    gripperCam.position.copy(target).add(gripperOffset()); gripperCam.lookAt(target);
  }
  if (cameraWindow.visible) {
    ui.pipTitle.textContent = source === 'gripper' ? '清洗夾具 · 即時視野' : pipCam === line.decapCam ? '桶口相機 · 即時視野' : '貼標相機 · 即時視野';
    ui.pipResult.textContent = source === 'gripper' ? `夾爪閉合 ${(S.st.grip.jaw * 100).toFixed(0)}% · 防脫扣隨爪同步開合` : shot && shot.cam === pipCam && T - shot.start < 4 ? shot.result : '即時畫面 · 等待檢測觸發（模擬訊號）';
    const r = cameraWindow.viewport, c = canvas.getBoundingClientRect();
    const x = r.left - c.left, y = c.bottom - r.bottom, pw = r.width, ph = r.height;
    pipCam.aspect = pw / ph; pipCam.updateProjectionMatrix();
    renderer.setScissorTest(true); renderer.setScissor(x, y, pw, ph); renderer.setViewport(x, y, pw, ph);
    const fenceVis = line.fences.visible; line.fences.visible = false;
    renderer.render(scene, pipCam); line.fences.visible = fenceVis; renderer.setScissorTest(false);
  }
}
const clock = new THREE.Clock();
function frame() {
  requestAnimationFrame(frame);
  const dt = Math.min(clock.getDelta(), .05);
  if (playing) { T = Math.min(total, T + dt * speed); if (T >= total) playing = false; applyState(seq.sample(T)); }
  if (camAnim) { camAnim.u = Math.min(1, camAnim.u + dt * 1.3); const e = smooth(camAnim.u); camera.position.lerpVectors(camAnim.p0, camAnim.p, e); controls.target.lerpVectors(camAnim.t0, camAnim.t, e); if (camAnim.u === 1) camAnim = null; }
  else focus.update(dt);
  controls.update();
  if (needsFrame || playing) { render(dt); needsFrame = false; }
}

resize(); seekTo(+(qp.get('t') || 0)); setView(qp.get('view') || 'iso', true);
if (qp.has('dims')) { ui.showDims.checked = true; building.dims.visible = true; }
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6) { camera.position.set(...a.slice(0, 3)); controls.target.set(...a.slice(3)); controls.update(); } }
document.getElementById('loading').classList.add('hide');
frame();
window.sim = { seekTo, setView, views: Object.keys(VIEWS), play() { playing = true; }, pause() { playing = false; }, get T() { return T; }, seq, get state() { return S; }, robot, total, focus, cameraWindow, camera, controls, focusPosition };
