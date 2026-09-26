import { routingLegend } from './cable-routing.js';
routingLegend();
// 主程式：場景、時間軸（動作序列）、UI、相機子畫面（上視遠心相機／手臂下視相機）
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { createVisionOverlay } from './vision-overlay.js';
import { cameraPanel } from './camera-panel.js';
import { createStation } from './station.js';
import { createSequence, smooth, STATIONS, SPEC, OFFSETS } from './sequence.js';
import { LAYOUT, NEST_SEAT, TRAYS } from './cell.js';
import { BLADES, PART } from './product.js';
import { TOOL, SCARA } from './robot.js';
import { cameraSource, stationPreviewTime, sensorViewport, SENSOR_ASPECT } from './camera-view.js';
import { shutterMarks } from './vision-results.js';
const vision = createVisionOverlay();
cameraPanel();

const qp = new URLSearchParams(location.search);
const NG = qp.get('result') === 'NG';

// ---------------------------------------------------------------- 場景
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: qp.get('aa') !== '0', powerPreference: 'high-performance', logarithmicDepthBuffer: qp.get('logdepth') !== '0' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);
scene.fog = new THREE.Fog(0x0d1117, 5000, 11000);
const pmrem = new THREE.PMREMGenerator(renderer);
const environmentRoom = new RoomEnvironment(renderer);
environmentRoom.traverse(o => { if (o.isPointLight) o.intensity = 220; });
scene.environment = pmrem.fromScene(environmentRoom, 0.04).texture;
environmentRoom.dispose(); pmrem.dispose();

const camera = new THREE.PerspectiveCamera(40, 1, 2, 20000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 3; controls.maxDistance = 7000;

scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x2a2f36, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.5); sun.position.set(-1500, 3200, 1800);
sun.castShadow = renderer.shadowMap.enabled; sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -1200, right: 1200, top: 1200, bottom: -1200, near: 500, far: 8000 }); sun.shadow.bias = -0.00004; sun.shadow.normalBias = .08;
scene.add(sun);
const fill = new THREE.DirectionalLight(0x9fb8ff, 0.5); fill.position.set(1800, 1500, -1800); scene.add(fill);
// 作業區局部光：治具與相機附近的小零件需要細緻陰影
const taskLight = new THREE.DirectionalLight(0xfff5e7, 1.2);
taskLight.position.set(-25, 994, 120); taskLight.target.position.set(0, 929, 80);
taskLight.castShadow = renderer.shadowMap.enabled; taskLight.shadow.mapSize.set(2048, 2048);
Object.assign(taskLight.shadow.camera, { left: -28, right: 28, top: 28, bottom: -28, near: 10, far: 140 });
taskLight.shadow.bias = -.00001; taskLight.shadow.normalBias = .004;
scene.add(taskLight, taskLight.target);

// ---------------------------------------------------------------- 物件
const st = createStation(scene, { ng: NG });
const { cell, robot } = st;
const ui = Object.fromEntries(['action', 'substep', 'forceBar', 'forceVal', 'forceLim', 'zoneDot', 'zoneTxt', 'checklist', 'chkCount', 'playBtn', 'restartBtn', 'speed', 'speedVal', 'showPath', 'progBar', 'clock', 'timeline', 'stepSelect', 'previous', 'next', 'signals', 'poseError', 'phase', 'result', 'exportBtn', 'showGuards', 'showLabels', 'showPip', 'cycleTime', 'units', 'okCount', 'pipFrame', 'pipResult', 'pipTitle', 'stations', 'drawerNote'].map(id => [id, document.getElementById(id)]));
ui.result.value = NG ? 'NG' : 'OK';
ui.result.onchange = () => { const q = new URLSearchParams(location.search); q.set('result', ui.result.value); q.delete('step'); q.delete('st'); location.search = q.toString(); };
ui.forceLim.textContent = `設定 ${SPEC.pressForce} N・上限 ${SPEC.forceLimit} N`;
cell.setDrawers(0x3dd68c, 0x4aa8ff);
ui.drawerNote.textContent = '抽屜 A 供料中｜B 滿料待命（可拉出換盤）';

// 手臂 TCP 軌跡
const trailN = 1200, trailPos = new Float32Array(trailN * 3); let trailCount = 0;
const trailGeo = new THREE.BufferGeometry(); trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPos, 3)); trailGeo.setDrawRange(0, 0);
const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0x7fd4ff, transparent: true, opacity: 0.7 })); scene.add(trail);
function pushTrail(p) { if (trailCount >= trailN) { trailPos.copyWithin(0, 3); trailCount = trailN - 1; } trailPos.set([p.x, p.y, p.z], trailCount * 3); trailCount++; trailGeo.attributes.position.needsUpdate = true; trailGeo.setDrawRange(0, trailCount); }

// 3D 標籤
const labels = [];
function addLabel(text, getPos) { const el = document.createElement('div'); el.className = 'label3d'; el.innerHTML = text; document.getElementById('app').appendChild(el); labels.push({ el, getPos }); }
const V = (x, y, z) => new THREE.Vector3(x, y, z);
addLabel('<b>DENSO</b> HSR065 SCARA', () => V(...LAYOUT.robot).add(V(0, 420, -40)));
addLabel('T1 葉片吸嘴', () => robot.getTcpWorld('T1').add(V(0, 60, 0)));
addLabel('T2 上蓋吸盤＋荷重元', () => robot.getTcpWorld('T2').add(V(0, 75, 0)));
addLabel('T3 本體夾爪', () => robot.getTcpWorld('T3').add(V(0, 60, 0)));
addLabel('下視相機 5MP', () => robot.getTcpWorld('cam').add(V(0, 95, 0)));
addLabel('上視遠心相機', () => V(LAYOUT.upCam.x, LAYOUT.table + 30, LAYOUT.upCam.z));
addLabel('組裝治具（基準邊＋推塊夾緊）', () => V(LAYOUT.nest.x, LAYOUT.nest.top + 20, LAYOUT.nest.z));
addLabel('離子風嘴', () => V(LAYOUT.upCam.x - 75, LAYOUT.table + 60, LAYOUT.upCam.z));
addLabel('NG 盒', () => V(LAYOUT.ngBin.x, LAYOUT.ngBin.top + 15, LAYOUT.ngBin.z));
addLabel('抽屜 A · 供料中', () => V(-LAYOUT.drawerX, LAYOUT.table + 60, 0));
addLabel('抽屜 B · 待命可換盤', () => V(LAYOUT.drawerX, LAYOUT.table + 60, 0));
addLabel('RC8A／PLC／視覺 IPC', () => V(0, 700, LAYOUT.encl.z1 + 10));

// 站別按鈕
STATIONS.forEach((name, i) => { const b = document.createElement('button'); b.className = 'st'; b.dataset.st = i; b.innerHTML = `<span class="idx">S${i}</span>${name}`; ui.stations.appendChild(b); });

// ---------------------------------------------------------------- 時間軸
let S, playing = !qp.has('pause'), T = 0, speed = 1, current, waiting = 0, fault = '', curStation = -1;
const sequence = createSequence({ robot, apply: s => { S = s; st.apply(s); }, ng: NG });
const total = sequence.total, stationStart = sequence.stationStart;
ui.timeline.max = total;
const shots = sequence.steps.filter(s => s.exposure).length;
ui.cycleTime.textContent = `規劃 ${total.toFixed(1)} s／顆＋到位等待 · 取像 ${shots} 次${NG ? ' · 含一次疊片剔除重取' : ''}`;
sequence.steps.forEach((s, i) => { const opt = document.createElement('option'); opt.value = i; opt.textContent = `S${s.station} · ${s.action}`; ui.stepSelect.appendChild(opt); });
const has = id => c => c.has(id);
const bladeItems = list => list.flatMap(b => [[`${b.name} 上視對位（偏移補正）`, has('shot' + b.id)], [`${b.name} 套入 ${b.pivot} 樞軸銷＋撥桿銷`, has('place' + b.id)]]);
const checklist = [
  [['夾取本體（料盤 #' + (SPEC.k + 1) + '）放入治具', has('base')]],
  [['下視定位 2 支樞軸銷＋2 支撥桿銷', has('locate')]],
  [...bladeItems(BLADES.slice(0, 2)), ['下視檢查 2 片小葉片', has('checkS')]],
  [...bladeItems(BLADES.slice(2, 3)), ...(NG ? [['疊片偵測 → 吹落 NG 盒、改取下一格', has('reject')]] : []), ...bladeItems(BLADES.slice(3)), ['下視檢查 4 片疊放', has('checkL')]],
  [['上蓋上視對位', has('shotcover')], [`上蓋放上、壓合 ${SPEC.pressForce} N`, has('press')]],
  [['成品取像判定', has('final')], ['成品放回料盤原格 #' + (SPEC.k + 1), has('out')]],
];

// 視角
const nestP = V(NEST_SEAT.x, NEST_SEAT.y, NEST_SEAT.z);
const views = {
  wiring: () => [[800,1750,-700],[0,1310,-300]],
  iso: () => [[-1350, 1850, 1650], [0, 930, -150]],
  robot: () => [[-850, 1450, 650], [0, 1100, -220]],
  nest: () => [nestP.clone().add(V(-70, 85, 115)).toArray(), nestP.clone().add(V(0, 0, -5)).toArray()],
  part: () => { const p = st.pose('base').p; return [p.clone().add(V(-16, 26, 28)).toArray(), p.toArray()]; },
  upcam: () => { const p = V(LAYOUT.upCam.x, LAYOUT.upCam.focus - 20, LAYOUT.upCam.z); return [p.clone().add(V(-120, 45, 150)).toArray(), p.toArray()]; },
  trays: () => [[-390, 1180, 40], [-390, 912, -305]],
  top: () => [[0, 2300, -80], [0, 900, -100]],
};
let selectedView = 'iso', camAnim = null;
const followBase = () => selectedView === 'part';
function setView(name, instant = false) {
  if (!views[name]) return; selectedView = name;
  camera.near = name === 'part' ? 0.1 : name === 'nest' || name === 'upcam' ? 0.5 : 2; camera.updateProjectionMatrix();
  lastBase.copy(st.pose('base').p);
  const [p, t] = views[name]().map(a => V(...a));
  if (instant) { camAnim = null; camera.position.copy(p); controls.target.copy(t); camera.lookAt(t); controls.update(); }
  else camAnim = { p0: camera.position.clone(), t0: controls.target.clone(), p, t, u: 0 };
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));
function seekTo(sec, snap = true) {
  T = Number.isFinite(sec) ? THREE.MathUtils.clamp(sec, 0, total) : 0; current = sequence.sample(T);
  if (snap) robot.snap(); st.sync(); waiting = 0; fault = ''; trailCount = 0; trailGeo.setDrawRange(0, 0);
  ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放'; render();
}
ui.playBtn.onclick = () => { if (T >= total || fault) seekTo(fault ? T : 0); playing = !playing; fault = ''; waiting = 0; ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放'; };
ui.restartBtn.onclick = () => seekTo(0);
ui.previous.onclick = () => { playing = false; seekTo(sequence.steps[Math.max(0, current.index - 1)].start); };
ui.next.onclick = () => { playing = false; seekTo(sequence.steps[Math.min(sequence.steps.length - 1, current.index + 1)].start); };
ui.stepSelect.onchange = () => { playing = false; seekTo(sequence.steps[+ui.stepSelect.value].start); };
ui.timeline.oninput = () => { playing = false; seekTo(+ui.timeline.value); };
ui.speed.oninput = () => { speed = +ui.speed.value; ui.speedVal.textContent = speed.toFixed(2).replace(/0$/, '') + '×'; };
ui.stations.querySelectorAll('.st').forEach(b => b.onclick = () => { playing = false; seekTo(stationPreviewTime(sequence, +b.dataset.st)); });

// 零件狀態格
const UNITS = [{ id: 'base', name: '本體' }, ...BLADES.map(b => ({ id: b.id, name: b.name })), { id: 'cover', name: '上蓋' }, ...(NG ? [{ id: 'L2x', name: '疊片（剔除）' }] : [])];
const unitEls = {};
for (const u of UNITS) { const el = document.createElement('div'); el.className = 'u'; el.innerHTML = `<b>${u.name}</b><span></span>`; ui.units.appendChild(el); unitEls[u.id] = el; }
function unitStatus(id) {
  const c = current.completed, loc = S.loc[id];
  if (id === 'L2x') return loc === 'bin' ? ['ng', '已剔除'] : loc === 'fall' ? ['ng','落入 NG 盒'] : loc === 'T1' ? (c.has('judgeNG') ? ['ng', '疊片 NG'] : ['held', '吸取中']) : ['tray', '料盤'];
  if (id === 'base') return loc === 'tray' ? ['tray', '料盤'] : loc === 'T3' ? ['held', c.has('final') ? '取出成品' : '夾持中'] : loc === 'out' ? ['ok', '成品回盤'] : c.has('final') ? ['ok', '成品 OK'] : ['placed', S.clamp > .99 ? '治具夾緊' : '放入治具'];
  if (loc === 'tray') return ['tray', '料盤'];
  if (loc === 'T1' || loc === 'T2') return c.has('shot' + id) ? ['aligned', '已對位'] : ['held', '吸取中'];
  const checked = id === 'cover' ? c.has('final') : c.has(id.startsWith('S') ? 'checkS' : 'checkL');
  return checked ? ['ok', '檢查 OK'] : ['placed', id === 'cover' && !c.has('press') ? '壓合中' : '已放置'];
}

function exportReport() {
  const parts = UNITS.map(u => ({ id: u.id, name: u.name, status: unitStatus(u.id)[1], simulatedOffset: OFFSETS[u.id] || null }));
  const report = { mode: 'SIMULATION', scenario: NG ? 'double-blade-reject' : 'normal', time: +T.toFixed(2), plannedCycle: +total.toFixed(2), trayPocket: SPEC.k + 1,
    result: current.completed.has('out') ? 'OK' : 'PENDING', parts, pressForceN: SPEC.pressForce,
    exposureEvents: sequence.steps.filter(s => s.exposure && s.start + s.dur <= T).map(s => ({ action: s.action, camera: s.exposure, plannedTime: +s.start.toFixed(2), simulation: true })),
    physicalMeasurement: false, mesConnected: false, motion: robot.error() };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = `SHUTTER-ASSY-${NG ? 'NG' : 'OK'}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
ui.exportBtn.onclick = exportReport;

const arrived = () => { const e = robot.error(); return e.position < 0.05 && e.angle < 0.2; };
const signals = [['抽屜 A 鎖定', () => true], ['抽屜 B 可換盤', () => true], ['治具有料', () => S.loc.base === 'nest'], ['治具夾緊', () => S.clamp > .99],
  ['吸嘴真空', () => S.vac > 0], ['夾爪夾持', () => S.open < .01 && S.loc.base === 'T3'], ['工具到位', arrived], ['前門關閉', () => true]];
signals.forEach(([name]) => { const row = document.createElement('div'); row.innerHTML = `<i></i><span>${name}</span>`; ui.signals.appendChild(row); });

function pipText(cam, exposure) {
  const [kind, id] = (S.shot || '').split(':');
  if (cam === 'up') {
    const held = Object.keys(st.parts).find(k => ['T1', 'T2'].includes(S.loc[k]));
    if (!held) return '<span>等待零件經過</span>';
    if (!exposure && !current.completed.has(held === 'cover' ? 'shotcover' : 'shot' + held) && !current.completed.has('judgeNG')) return `<span>${held === 'cover' ? '上蓋' : '葉片'}到位中…</span>`;
    if (held === 'L2x') return '<span class="ng">兩片黏疊 → NG，吹落 NG 盒</span>';
    const o = OFFSETS[held]; return `<span class="ok">Δx ${o.x.toFixed(2)}　Δz ${o.z.toFixed(2)} mm　θ ${o.a.toFixed(1)}° → 補正後放料</span>`;
  }
  if (kind === 'down' && S.flashDown > 0) return `<span class="ok">${{ pins: '樞軸銷／撥桿銷定位完成', checkS: '小葉片 A、B 套銷 OK', checkL: '4 片疊放順序 OK', final: '成品 OK：上蓋平貼、光圈淨空' }[id]}</span>`;
  return `<span class="info">即時畫面 · ${S.view === 'down' && current.step.station === 0 ? '本體上料' : '手臂移動中'}</span>`;
}

function drawHud() {
  const e = robot.error(), force = st.force();
  const src = cameraSource(S);
  ui.pipTitle.textContent = src === 'up' ? '上視遠心相機 · 5MP · 0.35× · 視野 24 × 20 mm（模擬）' : '手臂下視相機 · 5MP · 20 mm · WD 57 mm（模擬）';
  ui.pipResult.innerHTML = pipText(src, src === 'up' ? S.flashUp > 0 : S.flashDown > 0);
  cell.tower.set(fault ? 'red' : NG && current.completed.has('judgeNG') && !current.completed.has('reject') ? 'yellow' : T >= total - 1e-6 ? 'green' : playing ? 'green' : 'yellow');
  cell.occluders.visible = ui.showGuards.checked; trail.visible = ui.showPath.checked;
  ui.pipFrame.hidden = !ui.showPip.checked;
  ui.action.textContent = S.action; ui.substep.textContent = S.sub;
  ui.phase.textContent = fault || (T >= total ? 'COMPLETE · 本顆完成' : waiting > 0 ? '等待手臂到位' : playing ? 'AUTO · 執行中' : 'HOLD · 暫停'); ui.phase.classList.toggle('fault', !!fault);
  ui.forceBar.style.width = Math.min(100, force / SPEC.forceLimit * 100) + '%'; ui.forceVal.textContent = force.toFixed(1) + ' N';
  ui.forceBar.style.background = force > SPEC.pressForce * 1.2 ? 'var(--bad)' : force > .5 ? 'var(--warn)' : 'var(--ok)';
  ui.zoneTxt.textContent = S.zone === 'contact' ? `壓合 · ≤ ${SPEC.vContact} mm/s` : S.zone === 'slow' ? `減速接近 · ≤ ${SPEC.vApproach} mm/s` : '自由移動 / 工位保持';
  ui.zoneDot.className = 'dot ' + (S.zone === 'contact' ? 'contact' : S.zone === 'slow' ? 'slow' : '');
  const q = robot.q;
  ui.poseError.textContent = `${TOOL[robot.goal.tcp].name} TCP 誤差 ${e.position.toFixed(3)} mm · J1 ${(q.j1 * 57.3).toFixed(0)}° J2 ${(q.j2 * 57.3).toFixed(0)}° Z ${q.d3.toFixed(0)} mm J4 ${(q.j4 * 57.3).toFixed(0)}°`;
  [...ui.signals.children].forEach((el, i) => el.classList.toggle('on', !!signals[i][1]()));
  let ok = 0;
  for (const u of UNITS) { const [cls, txt] = unitStatus(u.id), el = unitEls[u.id]; if (cls === 'ok') ok++; const active = S.shot && S.shot.endsWith(':' + u.id); el.className = 'u ' + cls + (active ? ' active' : ''); el.lastChild.textContent = txt; }
  ui.okCount.textContent = `${ok} / ${UNITS.length - (NG ? 1 : 0)} OK`;
  const detailNote = document.getElementById('detailNote');
  detailNote.hidden = !['part', 'nest'].includes(selectedView);
  detailNote.textContent = selectedView === 'part' ? '產品近看 · 本體 18 × 17 × 4.05 mm · 視角跟著本體移動\n葉片厚度 0.06 mm（示意）；外形依照片描繪，非 CAD' : '組裝治具 · −x／−z 為基準邊，+x／+z 推塊夾緊\n−x 側為預成形導線容置區，±z 側中央為夾指避讓槽';
  document.body.classList.toggle('detail-view', !detailNote.hidden);
  if (curStation !== S.station) { curStation = S.station; ui.checklist.innerHTML = ''; checklist[curStation].forEach(([txt]) => { const li = document.createElement('li'); li.innerHTML = `<span class="box"></span><span>${txt}</span>`; ui.checklist.appendChild(li); }); }
  let done = 0; [...ui.checklist.children].forEach((li, i) => { const d = checklist[S.station][i][1](current.completed); li.classList.toggle('done', d); li.querySelector('.box').textContent = d ? '✓' : ''; if (d) done++; });
  ui.chkCount.textContent = done + ' / ' + checklist[S.station].length;
  ui.stations.querySelectorAll('.st').forEach(b => { const i = +b.dataset.st; b.classList.toggle('active', i === S.station); b.classList.toggle('done', i < S.station || T >= total); });
  ui.timeline.value = T; ui.stepSelect.value = current.index; ui.progBar.style.width = T / total * 100 + '%';
  ui.clock.textContent = `${Math.floor(T / 60).toString().padStart(2, '0')}:${(T % 60).toFixed(1).padStart(4, '0')}`;
  for (const l of labels) { const p = l.getPos().project(camera), vis = ui.showLabels.checked && p.z < 1 && Math.abs(p.x) < .98 && Math.abs(p.y) < .9; l.el.style.display = vis ? 'block' : 'none'; if (vis) { l.el.style.left = canvas.offsetLeft + (p.x * .5 + .5) * canvas.clientWidth + 'px'; l.el.style.top = canvas.offsetTop + (-p.y * .5 + .5) * canvas.clientHeight + 'px'; } }
  document.getElementById('diagnostics').textContent = JSON.stringify({ time: T, total, step: current.index, station: S.station, action: S.action, poseError: e, force, playing, waiting, fault, loc: S.loc, view: S.view, shot: S.shot });
}
function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
window.addEventListener('resize', resize);
function render() {
  drawHud();
  // Keep sub-millimetre contact shadows on the actual moving product.
  taskLight.target.position.copy(st.pose('base').p);
  taskLight.position.copy(st.pose('base').p).add(V(-25,65,40));
  const w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setScissorTest(false); renderer.setViewport(0, 0, w, h); renderer.render(scene, camera);
  vision.hide();
  if (ui.showPip.checked) {
    const c = canvas.getBoundingClientRect(), f = document.getElementById('pipImage').getBoundingClientRect();
    const box = sensorViewport(f.width, f.height), src = cameraSource(S);
    const x = f.left - c.left + box.x, y = c.bottom - f.bottom + box.y, pw = box.width, ph = box.height, cam = src === 'up' ? cell.upCam : robot.pipCam;
    if (cam.isPerspectiveCamera) { cam.aspect = SENSOR_ASPECT; cam.updateProjectionMatrix(); }
    const vis = [cell.occluders.visible, trail.visible]; cell.occluders.visible = false; trail.visible = false;
    const exposure = renderer.toneMappingExposure; renderer.toneMappingExposure = .9;
    renderer.setScissorTest(true); renderer.setScissor(f.left - c.left, c.bottom - f.bottom, f.width, f.height);
    renderer.setClearColor(0x080d13, 1); renderer.clear();
    renderer.setScissor(x, y, pw, ph); renderer.setViewport(x, y, pw, ph); renderer.render(scene, cam);
    const shooting = src === 'up' ? S.flashUp > 0 : S.flashDown > 0;
    vision.draw(cam, { left: f.left + box.x, top: f.top + box.y, width: pw, height: ph }, { title: src === 'up' ? '上視對位' : '下視檢查', state: shooting ? '本幀取像' : '即時', time: T, marks: shutterMarks(st, S, { cam: src, exposure: shooting }) });
    renderer.setClearColor(scene.background, 1); renderer.toneMappingExposure = exposure;
    renderer.setScissorTest(false); renderer.setViewport(0, 0, w, h); [cell.occluders.visible, trail.visible] = vis;
  }
}
const clock = new THREE.Clock();
const lastBase = new THREE.Vector3();
function tick(dt) {
  if (!playing) return;
  const e = robot.error(), s = current.step, end = s.start + s.dur;
  const blocked = (T >= end - 1e-7 || ((s.contact || s.near) && e.position > .5)) && (e.position > .05 || e.angle > .2);
  if (blocked) { waiting += dt; if (waiting > 5) { fault = '到位逾時 · 請檢查 TCP 位置'; playing = false; ui.playBtn.textContent = '▶ 播放'; } }
  else {
    waiting = 0;
    if (T >= total - 1e-7) { playing = false; ui.playBtn.textContent = '▶ 播放'; }
    else { T = T >= end - 1e-7 ? Math.min(total, end + 1e-6) : Math.min(end, T + dt); current = sequence.sample(T >= end - 1e-7 && T <= end ? Math.max(s.start, end - 1e-8) : T); }
  }
  robot.update(dt); st.sync();
}
function frame() {
  requestAnimationFrame(frame); const dt = Math.min(clock.getDelta(), .05);
  const n = Math.max(1, Math.ceil(dt * speed / .005)); for (let k = 0; k < n; k++) tick(dt * speed / n);
  if (followBase()) {
    const p = st.pose('base').p, delta = p.clone().sub(lastBase);
    camera.position.add(delta); controls.target.add(delta);
    if (camAnim) for (const key of ['p0', 't0', 'p', 't']) camAnim[key].add(delta);
  }
  lastBase.copy(st.pose('base').p);
  if (playing && ui.showPath.checked) pushTrail(robot.getTcpWorld(robot.goal.tcp));
  if (camAnim) { camAnim.u = Math.min(1, camAnim.u + dt * 1.4); camera.position.lerpVectors(camAnim.p0, camAnim.p, smooth(camAnim.u)); controls.target.lerpVectors(camAnim.t0, camAnim.t, smooth(camAnim.u)); if (camAnim.u === 1) camAnim = null; }
  controls.update(); render();
}
current = sequence.sample(0); robot.snap(); st.sync(); lastBase.copy(st.pose('base').p); setView('iso', true); resize(); ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放';
window.sim = { seekTo, pause() { playing = false; ui.playBtn.textContent = '▶ 播放'; }, play() { playing = true; ui.playBtn.textContent = '⏸ 暫停'; }, get state() { return S; }, robot, total, stationStart, steps: sequence.steps, setView, ng: NG, trays: TRAYS, scara: SCARA, part: PART };
if (qp.has('st')) { playing = false; const station = THREE.MathUtils.clamp(+qp.get('st') || 0, 0, STATIONS.length - 1); seekTo(qp.has('t') ? stationStart[station] + (+qp.get('t') || 0) : stationPreviewTime(sequence, station)); }
if (qp.has('step')) { playing = false; seekTo(sequence.steps[THREE.MathUtils.clamp(+qp.get('step') || 0, 0, sequence.steps.length - 1)].start + (+qp.get('t') || 0)); }
if (qp.has('time')) { playing = false; seekTo(+qp.get('time')); }
if (qp.has('view')) setView(qp.get('view'), true);
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6 && a.every(Number.isFinite)) { camera.position.set(...a.slice(0, 3)); controls.target.set(...a.slice(3)); controls.update(); } }
document.getElementById('loading').classList.add('hide'); render(); frame();
