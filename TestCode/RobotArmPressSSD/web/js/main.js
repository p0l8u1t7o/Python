import { routingLegend } from './cable-routing.js';
routingLegend();
// 主程式：場景、配方選擇、時間軸（動作序列）、UI、相機子畫面（手臂相機／全局相機）
import * as THREE from 'three';
import { createVisionOverlay } from './vision-overlay.js';
import { ssdResults } from './vision-results.js';
const vision = createVisionOverlay();
import { cameraPanel } from './camera-panel.js';
cameraPanel();
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { createStation } from './station.js';
import { createSequence, smooth, STATIONS, SPEC } from './sequence.js';
import { RECIPES, DEFAULT_RECIPE } from './recipes.js';
import { LAYOUT } from './cell.js';
import { cameraSource, stationPreviewTime, sensorViewport, SENSOR_ASPECT } from './camera-view.js';

const qp = new URLSearchParams(location.search);
const RECIPE_KEY = RECIPES[qp.get('recipe')] ? qp.get('recipe') : DEFAULT_RECIPE, recipe = RECIPES[RECIPE_KEY];
// 壓墊預設取配方的標準；有整排接頭的機種可切換單點逐顆作比較
const INSERT = qp.get('insert') === 'single' ? 'single' : qp.get('insert') === 'bar' && recipe.multiPad ? 'bar' : recipe.insert;

// ---------------------------------------------------------------- 場景
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: qp.get('aa') !== '0', powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);
scene.fog = new THREE.Fog(0x0d1117, 5000, 11000);
const pmrem = new THREE.PMREMGenerator(renderer);
const environmentRoom = new RoomEnvironment(renderer);
environmentRoom.traverse(o=>{if(o.isPointLight) o.intensity=220;});
const environmentTarget = pmrem.fromScene(environmentRoom, 0.04);
scene.environment = environmentTarget.texture;
environmentRoom.dispose(); pmrem.dispose();

const camera = new THREE.PerspectiveCamera(40, 1, 2, 20000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 8; controls.maxDistance = 7000;

scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x2a2f36, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.5); sun.position.set(-1500, 3200, 1800);
sun.castShadow = qp.get('shadow') !== '0'; sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -1800, right: 1800, top: 1800, bottom: -1800, near: 500, far: 8000 }); sun.shadow.bias = -0.0003;
scene.add(sun);
const fill = new THREE.DirectionalLight(0x9fb8ff, 0.5); fill.position.set(1800, 1500, -1800); scene.add(fill);
const taskLight = new THREE.DirectionalLight(0xfff5e7, 1.3);
taskLight.position.set(180,1350,160); taskLight.target.position.set(0,900,0);
taskLight.castShadow=renderer.shadowMap.enabled; taskLight.shadow.mapSize.set(2048,2048);
Object.assign(taskLight.shadow.camera,{left:-190,right:190,top:180,bottom:-180,near:10,far:850});
taskLight.shadow.bias=-.000015; taskLight.shadow.normalBias=.025;
scene.add(taskLight,taskLight.target);

// ---------------------------------------------------------------- 物件
const st = createStation(scene, recipe, INSERT);
const { cell, robot, product } = st;
const ui = Object.fromEntries(['action', 'substep', 'forceBar', 'forceVal', 'forceLim', 'zoneDot', 'zoneTxt', 'checklist', 'chkCount', 'playBtn', 'restartBtn', 'speed', 'speedVal', 'showPath', 'progBar', 'clock', 'timeline', 'stepSelect', 'previous', 'next', 'signals', 'poseError', 'phase', 'result', 'exportBtn', 'showGuards', 'showLabels', 'showPip', 'cycleTime', 'units', 'okCount', 'pipFrame', 'pipResult', 'pipTitle', 'stations', 'recipe', 'insert', 'recipeNote'].map(id => [id, document.getElementById(id)]));
st.opts.ngHold = qp.get('result') === 'NG'; ui.result.value = st.opts.ngHold ? 'NG' : 'OK';

// 配方與壓墊選擇（換機種只換配方；治具共用）
for (const [key, r] of Object.entries(RECIPES)) { const o = document.createElement('option'); o.value = key; o.textContent = r.name; ui.recipe.appendChild(o); }
ui.recipe.value = RECIPE_KEY; ui.insert.value = INSERT;
ui.insert.querySelector('[value=bar]').disabled = !recipe.multiPad;
const reload = () => { const q = new URLSearchParams(location.search); q.set('recipe', ui.recipe.value); q.set('insert', ui.insert.value); q.delete('step'); q.delete('st'); location.search = q.toString(); };
ui.recipe.onchange = reload; ui.insert.onchange = reload;
ui.recipeNote.textContent = `${recipe.name}：${recipe.source}。壓合力、允收間隙與翹起角為示意值，待實機量測校正。`;
document.getElementById('forceHint').textContent = INSERT === 'bar' ? 'ATI Axia80 · 整排合力對高度' : 'ATI Axia80 · 每顆記錄力對高度';
ui.forceLim.textContent = INSERT === 'bar' ? `整排 ${recipe.press.bar} N・上限 ${SPEC.forceLimit} N` : `每顆 ${recipe.press.single} N・上限 ${SPEC.forceLimit} N`;

// ROI 框（取像、全局辨識）
const roiMats = [], roiBoxes = [];
for (let k = 0; k < product.ids.length; k++) { const m = new THREE.LineBasicMaterial({ color: 0x3dd68c, transparent: true, opacity: 0.95 }); const b = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), m); b.visible = false; scene.add(b); roiMats.push(m); roiBoxes.push(b); }
function showROI(k, id, color) {
  const b = new THREE.Box3().setFromObject(product.conns[id].pivot);
  roiBoxes[k].position.copy(b.getCenter(new THREE.Vector3())); roiBoxes[k].scale.copy(b.getSize(new THREE.Vector3()).addScalar(2.5)); roiMats[k].color.setHex(color); roiBoxes[k].visible = true;
}

// 手臂 TCP 軌跡
const trailN = 800, trailPos = new Float32Array(trailN * 3); let trailCount = 0;
const trailGeo = new THREE.BufferGeometry(); trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPos, 3)); trailGeo.setDrawRange(0, 0);
const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0x7fd4ff, transparent: true, opacity: 0.7 })); scene.add(trail);
function pushTrail(p) { if (trailCount >= trailN) { trailPos.copyWithin(0, 3); trailCount = trailN - 1; } trailPos.set([p.x, p.y, p.z], trailCount * 3); trailCount++; trailGeo.attributes.position.needsUpdate = true; trailGeo.setDrawRange(0, trailCount); }

// 3D 標籤
const labels = [];
function addLabel(text, getPos) { const el = document.createElement('div'); el.className = 'label3d'; el.innerHTML = text; document.getElementById('app').appendChild(el); labels.push({ el, getPos }); }
const top = LAYOUT.conveyorTop;
addLabel('<b>DENSO</b> VS-068', () => new THREE.Vector3(...LAYOUT.robot).add(new THREE.Vector3(0, 120, -110)));
addLabel(INSERT === 'bar' ? '8 頭整排壓墊（獨立彈簧）' : '單點彈簧壓頭（快拆）', () => robot.getTcpWorld('press').add(new THREE.Vector3(0, 50, 0)));
addLabel('20MP 斜視相機 45°', () => robot.tcps.cam.parent.localToWorld(new THREE.Vector3(0, 150, 10)).add(new THREE.Vector3(0, 50, 0)));
addLabel('固定全局相機 20MP', () => new THREE.Vector3(...LAYOUT.globalCam).add(new THREE.Vector3(0, 120, 0)));
addLabel('止擋＋頂升', () => new THREE.Vector3(LAYOUT.stopFace, top - 60, 150));
addLabel('上游 · 前站放置 USB', () => new THREE.Vector3(-1100, top + 120, 0));
addLabel('下游 · 迴焊爐', () => new THREE.Vector3(1100, top + 120, 0));
addLabel('RC8A／PLC／IPC', () => new THREE.Vector3(0, 700, -240));

// 站別按鈕
STATIONS.forEach((name, i) => { const b = document.createElement('button'); b.className = 'st'; b.dataset.st = i; b.innerHTML = `<span class="idx">S${i}</span>${name}`; ui.stations.appendChild(b); });

// ---------------------------------------------------------------- 時間軸
let S, playing = !qp.has('pause'), T = 0, speed = 1, current, waiting = 0, fault = '', curStation = -1;
function applyState(s) { S = s; st.apply(s); }
const sequence = createSequence({ robot, product, apply: applyState, recipe, insert: INSERT });
const total = sequence.total, stationStart = sequence.stationStart, shots = sequence.shots;
ui.timeline.max = total;
ui.cycleTime.textContent = `規劃 ${total.toFixed(1)} s／盤（含一次補壓）＋到位等待 · ${product.ids.length} 顆 · 拍 ${shots.length} 張`;
sequence.steps.forEach((s, i) => { const opt = document.createElement('option'); opt.value = i; opt.textContent = `S${s.station} · ${s.action}`; ui.stepSelect.appendChild(opt); });
const stub = recipe.stubborn.id, shotOf = Object.fromEntries(shots.flatMap((g, k) => g.map(c => [c.id, k])));
const label = ids => ids.length > 1 ? `${ids[0]}–${ids[ids.length - 1]}` : ids[0];
const has = id => c => c.has(id);
const rowsOf = recipe.rows.map(([name, key]) => [name, recipe.connectors.filter(c => c.row === key).map(c => c.id)]);
const checklist = [
  [['載盤到位・頂升定位', has('locate')]],
  [['讀碼、辨識機種、找出接頭位置與方向', has('detect')]],
  INSERT === 'bar' && sequence.useBar ? sequence.barRows.map((r, k) => [`${label(r.map(c => c.id))} 整排壓合 ${recipe.press.bar} N`, has('press' + k)])
    : rowsOf.map(([name, ids]) => [`${name} 排逐顆壓合（${ids.length} 顆 × ${recipe.press.single} N）`, c => ids.every(id => c.has('press' + id))]),
  shots.map((g, k) => [`${label(g.map(c => c.id))} 銀腳貼合取像（${g.length} 顆）`, has('shot' + k)]),
  [[`${stub} 間隙超標 → 原位補壓`, has('repress')], [`${stub} 複檢`, has('recheck')], ['全部結果彙整', has('judge')]],
  [['出板至下游', has('out')]],
];
// 視角：特寫以載盤在本站（頂升後）時的第一顆接頭為準
let focusId = product.ids.includes(qp.get('focus')) ? qp.get('focus') : product.ids[0];
function stationPoint(id) {
  const r = product.root.position;
  return product.pressPoint(id).add(new THREE.Vector3(st.place.x - r.x, LAYOUT.conveyorTop + LAYOUT.liftStroke - r.y, st.place.z - r.z));
}
const views = {
  wiring: () => [[-1200,1850,700],[0,1200,-300]],
  iso: () => [[-1250, 1650, 1550], [0, 950, -200]], conveyor: () => [[-420, 1180, 820], [st.place.x, 915, st.place.z]], robot: () => [[-950, 1450, 150], [0, 1030, -280]],
  press: () => { const p = stationPoint(product.ids[0]); return [p.clone().add(new THREE.Vector3(-150, 60, 90)).toArray(), p.toArray()]; },
  inspect: () => { const p = stationPoint(product.ids[0]); return [p.clone().add(new THREE.Vector3(130, 80, 120)).toArray(), p.clone().add(new THREE.Vector3(20, -5, 10)).toArray()]; },
  top: () => [[st.place.x, 2400, st.place.z + 120], [st.place.x, 900, st.place.z - 150]],
  product: () => { const p=product.root.position.clone().add(new THREE.Vector3(0,recipe.pallet.t,0)); const d=Math.max(recipe.pallet.w,recipe.pallet.d); return [p.clone().add(new THREE.Vector3(-d*.48,d*.95,d*.85)).toArray(),p.toArray()]; },
  leads: () => { const c=product.conns[focusId], p=product.leadPoint(focusId); const offset=(c.T.w<10 ? new THREE.Vector3(4,5,14) : new THREE.Vector3(9,7,20)).applyAxisAngle(new THREE.Vector3(0,1,0),c.rot*Math.PI/180); return [p.clone().add(offset).toArray(),p.toArray()]; },
};
let selectedView = 'iso', camAnim = null;
function setView(name, instant = false) {
  if (!views[name]) return; selectedView = name;
  lastProductPosition.copy(product.root.position);
  camera.near=name==='leads' ? .15 : 2; camera.updateProjectionMatrix();
  const [p, t] = views[name]().map(a => new THREE.Vector3(...a));
  if (instant) { camAnim = null; camera.position.copy(p); controls.target.copy(t); camera.lookAt(t); controls.update(); }
  else camAnim = { p0: camera.position.clone(), t0: controls.target.clone(), p, t, u: 0 };
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));
function seekTo(sec, snap = true) {
  T = Number.isFinite(sec) ? THREE.MathUtils.clamp(sec, 0, total) : 0; current = sequence.sample(T);
  if (snap) robot.snap(); waiting = 0; fault = ''; trailCount = 0; trailGeo.setDrawRange(0, 0);
  ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放'; render();
}
ui.playBtn.onclick = () => { if (T >= total || fault) seekTo(fault ? T : 0); playing = !playing; fault = ''; waiting = 0; ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放'; };
ui.restartBtn.onclick = () => seekTo(0);
ui.previous.onclick = () => { playing = false; seekTo(sequence.steps[Math.max(0, current.index - 1)].start); };
ui.next.onclick = () => { playing = false; seekTo(sequence.steps[Math.min(sequence.steps.length - 1, current.index + 1)].start); };
ui.stepSelect.onchange = () => { playing = false; seekTo(sequence.steps[+ui.stepSelect.value].start); };
ui.timeline.oninput = () => { playing = false; seekTo(+ui.timeline.value); };
ui.speed.oninput = () => { speed = +ui.speed.value; ui.speedVal.textContent = speed.toFixed(2).replace(/0$/, '') + '×'; };
ui.result.onchange = () => { st.opts.ngHold = ui.result.value === 'NG'; seekTo(T); };
ui.stations.querySelectorAll('.st').forEach(b => b.onclick = () => seekTo(stationPreviewTime(sequence, +b.dataset.st)));

// 接頭狀態格（依配方的排）
const unitEls = {}, maxCols = Math.max(...rowsOf.map(([, ids]) => ids.length));
ui.units.style.gridTemplateColumns = `${recipe.rows.length > 1 ? 18 : 30}px repeat(${maxCols}, 1fr)`;
for (const [name, ids] of rowsOf) {
  const tag = document.createElement('div'); tag.className = 'rowTag'; tag.textContent = name; ui.units.appendChild(tag);
  ids.forEach(id => { const el = document.createElement('button'); el.type='button'; el.setAttribute('aria-label',`查看 ${id} 銀腳`); el.className = 'u'; el.innerHTML = `<b>${id}</b><span></span>`; el.onclick=()=>{focusId=id;setView('leads');}; ui.units.appendChild(el); unitEls[id] = el; });
  for (let k = ids.length; k < maxCols; k++) ui.units.appendChild(document.createElement('div'));
}
function unitStatus(id) {
  const c = current.completed, gap = st.state.gap[id];
  if (S.pressIds.includes(id) && S.zone === 'contact') return ['press', '壓合中'];
  if (id === stub && c.has('judgeNG') && !c.has('recheck')) return ['repress', '補壓中'];
  if (c.has('shot' + shotOf[id])) return gap <= recipe.gapLimit ? ['ok', 'OK'] : ['ng', 'NG'];
  if (S.seated[id]) return ['pressed', '已壓合'];
  return [gap > recipe.gapLimit ? 'lift' : '', '待壓合'];
}
function shotIds() { if (!S.shot) return []; return S.shot === 'R' ? [stub] : shots[+S.shot].map(c => c.id); }

function exportReport() {
  const units = product.ids.map(id => ({ id, simulatedGapMm: +st.state.gap[id].toFixed(3), status: unitStatus(id)[1] }));
  const report = { mode: 'SIMULATION', recipe: RECIPE_KEY, recipeName: recipe.name, insert: INSERT, pallet: recipe.pallet.code, time: T, plannedCycle: total, result: current.completed.has('judge') ? (st.opts.ngHold ? 'NG' : 'OK') : 'PENDING', gapLimitMm: recipe.gapLimit,
    units, exposureEvents: sequence.steps.filter(s => s.exposure && s.start + s.dur <= T).map(s => ({ action: s.action, plannedTime: s.start, simulation: true })),
    physicalMeasurement: false, mesConnected: false, assumptions: recipe.source, motion: robot.error() };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = `USB-PRESS-${RECIPE_KEY}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
ui.exportBtn.onclick = exportReport;

const arrived = () => { const e = robot.error(); return e.position < (current.step.contact ? 1 : 2) && e.angle < 2; };
const signals = [['載盤到位', () => S.located], ['止擋伸出', () => S.stop > .99], ['頂升定位', () => S.lift > .99], ['全局辨識完成', () => S.detected > 0],
  ['壓頭接觸', () => st.state.force > .5], ['工具到位', arrived], ['下游可收板', () => S.station === 5 || S.station === 0]];
signals.forEach(([name]) => { const row = document.createElement('div'); row.innerHTML = `<i></i><span>${name}</span>`; ui.signals.appendChild(row); });
const useGlobalView = () => cameraSource(S, current.step, arrived()) === 'global';

function drawHud() {
  const e = robot.error(), ps = st.state, force = ps.force;
  robot.setFlash(S.flashTool > 0 && arrived()); robot.setForceColor(force);
  const ids = S.flashTool > 0 ? shotIds() : [];
  roiBoxes.forEach(b => { b.visible = false; });
  if (S.station === 1 && S.detected > 0) product.ids.forEach((id, k) => showROI(k, id, 0x4aa8ff));
  else ids.forEach((id, k) => showROI(k, id, ps.gap[id] <= recipe.gapLimit ? 0x3dd68c : 0xff4d4d));
  const last = shotIds();
  const globalView = useGlobalView();
  ui.pipTitle.textContent = globalView ? '全局相機 · 載盤預覽（模擬）' : '手臂相機 · USB 貼合檢查（模擬）';
  ui.pipTitle.title = globalView ? '20MP · 20 mm · 距離約 800 mm' : '20MP · 25 mm · 45° 斜視 · WD 175 mm';
  ui.pipResult.innerHTML = globalView ? (S.station === 1 ? (S.detected > 0 ? `<span class="ok">${recipe.pallet.code}・找到 ${product.ids.length} 顆</span>` : '<span>全局取像中…</span>') : !S.located ? '<span>等待載盤到站</span>' : '<span>手臂未在取像位 · 顯示整盤 USB</span>')
    : last.length ? (S.flashTool > 0 ? '取像中　' : '最近取像　') + last.map(id => { const g = ps.gap[id], ok = g <= recipe.gapLimit; return `<span class="${ok ? 'ok' : 'ng'}">${id} ${g.toFixed(2)} mm ${ok ? 'OK' : 'NG'}</span>`; }).join('　') : '<span>—</span>';
  cell.tower.set(fault ? 'red' : T >= total - 1e-6 ? 'green' : S.station === 4 && !current.completed.has('recheck') ? 'yellow' : playing ? 'green' : 'yellow');
  cell.occluders.visible = ui.showGuards.checked; trail.visible = ui.showPath.checked;
  ui.pipFrame.hidden = !ui.showPip.checked;
  ui.action.textContent = S.action; ui.substep.textContent = S.sub;
  ui.phase.textContent = fault || (T >= total ? 'COMPLETE · 本盤完成' : waiting > 0 ? '等待手臂到位' : playing ? 'AUTO · 執行中' : 'HOLD · 暫停'); ui.phase.classList.toggle('fault', !!fault);
  ui.forceBar.style.width = Math.min(100, force / SPEC.forceLimit * 100) + '%'; ui.forceVal.textContent = force.toFixed(1) + ' N';
  ui.zoneTxt.textContent = S.zone === 'contact' ? '接觸 · ≤ 40 mm/s・模擬力值' : S.zone === 'slow' ? '減速接近 · ≤ 120 mm/s' : '自由移動 / 工位保持';
  ui.zoneDot.className = 'dot ' + (S.zone === 'contact' ? 'contact' : S.zone === 'slow' ? 'slow' : '');
  ui.poseError.textContent = `TCP ${e.position.toFixed(2)} mm · ${e.angle.toFixed(1)}° · ${robot.goal.tcp === 'cam' ? '相機' : INSERT === 'bar' ? '8 頭壓墊' : '單點壓頭'} TCP`;
  [...ui.signals.children].forEach((el, i) => el.classList.toggle('on', !!signals[i][1]()));
  let ok = 0; const shotSet = new Set(ids);
  for (const id of product.ids) { const [cls, txt] = unitStatus(id), el = unitEls[id]; if (cls === 'ok') ok++; el.className = 'u ' + cls + (shotSet.has(id) ? ' shot' : ''); el.lastChild.textContent = ps.gap[id].toFixed(2); el.title = `${id}：${txt}，模擬間隙 ${ps.gap[id].toFixed(3)} mm`; }
  ui.okCount.textContent = `${ok} / ${product.ids.length} OK`;
  const detailNote=document.getElementById('detailNote');
  detailNote.hidden=selectedView!=='leads' && selectedView!=='product';
  detailNote.textContent=selectedView==='leads' ? `${focusId} 銀腳特寫 · 模擬間隙 ${ps.gap[focusId].toFixed(3)} mm · ${unitStatus(focusId)[1]}\n銀腳／錫膏／PCB 焊墊 · 幾何示意，非實拍量測` : '載盤近看 · 依現場照片重建外觀\n點選右側接頭編號，可近看該顆銀腳';
  document.body.classList.toggle('detail-view',selectedView==='leads'||selectedView==='product');
  if (curStation !== S.station) { curStation = S.station; ui.checklist.innerHTML = ''; checklist[curStation].forEach(([txt]) => { const li = document.createElement('li'); li.innerHTML = `<span class="box"></span><span>${txt}</span>`; ui.checklist.appendChild(li); }); }
  let done = 0; [...ui.checklist.children].forEach((li, i) => { const d = checklist[S.station][i][1](current.completed); li.classList.toggle('done', d); li.querySelector('.box').textContent = d ? '✓' : ''; if (d) done++; });
  ui.chkCount.textContent = done + ' / ' + checklist[S.station].length;
  ui.stations.querySelectorAll('.st').forEach(b => { const i = +b.dataset.st; b.classList.toggle('active', i === S.station); b.classList.toggle('done', i < S.station || T >= total); });
  ui.timeline.value = T; ui.stepSelect.value = current.index; ui.progBar.style.width = T / total * 100 + '%';
  ui.clock.textContent = `${Math.floor(T / 60).toString().padStart(2, '0')}:${(T % 60).toFixed(1).padStart(4, '0')}`;
  for (const l of labels) { const p = l.getPos().project(camera), visible = ui.showLabels.checked && p.z < 1 && Math.abs(p.x) < .98 && Math.abs(p.y) < .83; l.el.style.display = visible ? 'block' : 'none'; if (visible) { l.el.style.left = canvas.offsetLeft + (p.x * .5 + .5) * canvas.clientWidth + 'px'; l.el.style.top = canvas.offsetTop + (-p.y * .5 + .5) * canvas.clientHeight + 'px'; } }
  document.getElementById('diagnostics').textContent = JSON.stringify({ recipe: RECIPE_KEY, insert: INSERT, time: T, total, step: current.index, station: S.station, action: S.action, poseError: e, force, playing, waiting, fault, gaps: ps.gap, lift: S.lift, stop: S.stop });
}
function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
window.addEventListener('resize', resize);
function render() {
  drawHud();
  const w = canvas.clientWidth, h = canvas.clientHeight;
  renderer.setScissorTest(false); renderer.setViewport(0, 0, w, h); renderer.render(scene, camera);
  vision.hide();
  if (ui.showPip.checked) {
    // 子畫面：目前使用中的相機實際看到的畫面（位置對齊 #pipFrame）
    const c = canvas.getBoundingClientRect(), f = document.getElementById('pipImage').getBoundingClientRect();
    const box = sensorViewport(f.width, f.height);
    const x = f.left - c.left + box.x, y = c.bottom - f.bottom + box.y, pw = box.width, ph = box.height, cam = useGlobalView() ? cell.globalCam : robot.pipCam;
    // Preserve the full sensor field of view; text belongs outside the image.
    cam.aspect = SENSOR_ASPECT; cam.updateProjectionMatrix();
    const vis = [cell.occluders.visible, trail.visible]; cell.occluders.visible = false; trail.visible = false;
    const roiVisible=roiBoxes.map(b=>b.visible);roiBoxes.forEach(b=>b.visible=false);
    const exposure=renderer.toneMappingExposure;renderer.toneMappingExposure=.88;
    renderer.setScissorTest(true); renderer.setScissor(f.left-c.left,c.bottom-f.bottom,f.width,f.height);
    renderer.setClearColor(0x080d13,1); renderer.clear();
    renderer.setScissorTest(true); renderer.setScissor(x, y, pw, ph); renderer.setViewport(x, y, pw, ph); renderer.render(scene, cam);
    const global=useGlobalView(),shotReady=S.flashTool>0&&arrived();
    vision.draw(cam,{left:f.left+box.x,top:f.top+box.y,width:pw,height:ph},{title:global?'USB 定位':'銀腳貼合',state:global?(S.station===1&&S.detected>0?'定位示意':'預覽'):shotReady?`本幀取像 · ≤ ${recipe.gapLimit} mm`:'待取像',time:T,marks:ssdResults(product,recipe,{global,detected:S.station===1&&S.detected>0,exposure:shotReady,ids:shotIds(),gaps:st.state.gap})});
    renderer.setClearColor(scene.background,1);
    renderer.toneMappingExposure=exposure;roiBoxes.forEach((b,i)=>b.visible=roiVisible[i]);
    renderer.setScissorTest(false); renderer.setViewport(0, 0, w, h); [cell.occluders.visible, trail.visible] = vis;
  }
}
const clock = new THREE.Clock();
const lastProductPosition = product.root.position.clone();
function tick(dt) {
  if (!playing) return;
  if (st.opts.ngHold && current.completed.has('recheck')) { fault = `NG · ${stub} 補壓後仍未貼合，停線待人工確認`; playing = false; ui.playBtn.textContent = '▶ 播放'; return; }
  const e = robot.error(), s = current.step, end = s.start + s.dur;
  const blocked = (T >= end - 1e-7 || (s.contact && e.position > 2)) && (e.position > 1 || e.angle > 1);
  if (blocked) { waiting += dt; if (waiting > 8) { fault = '到位逾時 · 請檢查 TCP 姿態'; playing = false; ui.playBtn.textContent = '▶ 播放'; } }
  else {
    waiting = 0;
    if (T >= total - 1e-7) { playing = false; ui.playBtn.textContent = '▶ 播放'; }
    else { T = T >= end - 1e-7 ? Math.min(total, end + 1e-6) : Math.min(end, T + dt); current = sequence.sample(T >= end - 1e-7 && T <= end ? Math.max(s.start, end - 1e-8) : T); }
  }
  robot.update(dt);
}
function frame() {
  requestAnimationFrame(frame); const dt = Math.min(clock.getDelta(), .05);
  const n = Math.max(1, Math.ceil(dt * speed / .01)); for (let k = 0; k < n; k++) tick(dt * speed / n);
  if (selectedView==='product'||selectedView==='leads') {
    const delta=product.root.position.clone().sub(lastProductPosition);
    camera.position.add(delta); controls.target.add(delta);
    if(camAnim) for(const key of ['p0','t0','p','t']) camAnim[key].add(delta);
  }
  lastProductPosition.copy(product.root.position);
  if (playing && ui.showPath.checked) pushTrail(robot.getTcpWorld(robot.goal.tcp));
  if (camAnim) { camAnim.u = Math.min(1, camAnim.u + dt * 1.4); camera.position.lerpVectors(camAnim.p0, camAnim.p, smooth(camAnim.u)); controls.target.lerpVectors(camAnim.t0, camAnim.t, smooth(camAnim.u)); if (camAnim.u === 1) camAnim = null; }
  controls.update(); render();
}
current = sequence.sample(0); robot.snap(); setView('iso', true); resize(); ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放';
window.sim = { seekTo, pause() { playing = false; ui.playBtn.textContent = '▶ 播放'; }, play() { playing = true; ui.playBtn.textContent = '⏸ 暫停'; }, get state() { return S; }, robot, total, stationStart, steps: sequence.steps, setView, recipe: RECIPE_KEY, insert: INSERT };
if (qp.has('st')) { playing = false; const station = THREE.MathUtils.clamp(+qp.get('st') || 0, 0, STATIONS.length - 1); seekTo(qp.has('t') ? stationStart[station] + (+qp.get('t') || 0) : stationPreviewTime(sequence, station)); }
if (qp.has('step')) { playing = false; seekTo(sequence.steps[THREE.MathUtils.clamp(+qp.get('step') || 0, 0, sequence.steps.length - 1)].start + (+qp.get('t') || 0)); }
if (qp.has('view')) setView(qp.get('view'), true);
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6 && a.every(Number.isFinite)) { camera.position.set(...a.slice(0, 3)); controls.target.set(...a.slice(3)); controls.update(); } }
document.getElementById('loading').classList.add('hide'); render(); frame();
