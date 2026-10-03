import {createElectricalInspector} from '@core/electrical/electrical-inspector.js';
import {setElectricalCutaway} from '@core/electrical/electrical-cabinet.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { routingLegend } from '@core/electrical/cable-routing.js';
routingLegend();
// 主程式：場景、配方選擇、時間軸（動作序列）、UI、相機子畫面（手臂相機／全局相機）
import * as THREE from 'three';
import { createVisionOverlay } from '@core/ui/vision-overlay.js';
import { ssdResults } from './vision-results.js';
const vision = createVisionOverlay();
import { createStage, exposeSim } from '@core/ui/stage.js';
import { createPlayer } from '@core/ui/player.js';
import { createArrivalGate } from '@core/anim/arrival.js';
import { createProject, resolveRecipe } from './project.js';
import { STATIONS, SPEC, ARRIVAL } from './sequence.js';
import { RECIPES } from './recipes.js';
import { LAYOUT } from './cell.js';
import { cameraSource, stationPreviewTime, SENSOR_ASPECT } from './camera-view.js';

const qp = new URLSearchParams(location.search);
// 配方與壓墊的預設規則在 project.js（檢查用同一規則）
const { key: RECIPE_KEY, recipe, insert: INSERT } = resolveRecipe(qp.get('recipe'), qp.get('insert'));

// ---------------------------------------------------------------- 場景（共用舞台 core/ui/stage.js）
// 配色、曝光、半球光與燈光強度取 look 'cell'，只列出差異；本站場景約 2 m、銀腳特寫近裁切面 0.15 mm，不用對數深度（?movie 時 stage 一律開啟）。
// 太陽／補光位置與陰影範圍沿用原值（extent 推算的燈位與 normalBias 會改變桌面畫面），霧也照舊明確給
const canvas = document.getElementById('c');
const stage = createStage({
  canvas, qp, look: 'cell', envLight: 220, fog: [5000, 11000], logDepth: false,
  controls: { minDistance: 8, maxDistance: 7000 },
  sun: { position: [-1500, 3200, 1800], target: [0, 0, 0], shadow: { mapSize: 2048, camera: { left: -1800, right: 1800, top: 1800, bottom: -1800, near: 500, far: 8000 }, bias: -.0003 } },
  fill: { position: [1800, 1500, -1800] },
  // 作業區局部光（本站專屬）：照壓合／取像區，帶小範圍陰影
  extraLights: [{ color: 0xfff5e7, intensity: 1.3, position: [180, 1350, 160], target: [0, 900, 0],
    shadow: { mapSize: 2048, camera: { left: -190, right: 190, top: 180, bottom: -180, near: 10, far: 850 }, bias: -.000015, normalBias: .025 } }],
});
const { renderer, scene, camera, controls } = stage;

// ---------------------------------------------------------------- 物件（與 core 統一檢查共用 project.js：整站、ROI 框、流程）
const project = createProject({ scene, recipe: RECIPE_KEY, insert: INSERT, ngHold: qp.get('result') === 'NG' });
const st = project.station, { cell, robot, product, sequence } = project;
const ui =Object.fromEntries(['action', 'substep', 'forceBar', 'forceVal', 'forceLim', 'zoneDot', 'zoneTxt', 'checklist', 'chkCount', 'playBtn', 'restartBtn', 'speed', 'speedVal', 'showPath', 'progBar', 'clock', 'timeline', 'stepSelect', 'previous', 'next', 'signals', 'poseError', 'phase', 'result', 'exportBtn', 'showGuards', 'showLabels', 'showPip', 'cycleTime', 'units', 'okCount', 'pipFrame', 'pipResult', 'pipTitle', 'stations', 'recipe', 'insert', 'recipeNote'].map(id => [id, document.getElementById(id)]));
ui.result.value = st.opts.ngHold ? 'NG' : 'OK';

// 配方與壓墊選擇（換機種只換配方；治具共用）
for (const [key, r] of Object.entries(RECIPES)) { const o = document.createElement('option'); o.value = key; o.textContent = r.name; ui.recipe.appendChild(o); }
ui.recipe.value = RECIPE_KEY; ui.insert.value = INSERT;
ui.insert.querySelector('[value=bar]').disabled = !recipe.multiPad;
const reload = () => { const q = new URLSearchParams(location.search); q.set('recipe', ui.recipe.value); q.set('insert', ui.insert.value); q.delete('step'); q.delete('st'); location.search = q.toString(); };
ui.recipe.onchange = reload; ui.insert.onchange = reload;
ui.recipeNote.textContent = `${recipe.name}：${recipe.source}。壓合力、允收間隙與翹起角為示意值，待實機量測校正。`;
document.getElementById('forceHint').textContent = INSERT === 'bar' ? 'ATI Axia80 · 整排合力對高度' : 'ATI Axia80 · 每顆記錄力對高度';
ui.forceLim.textContent = INSERT === 'bar' ? `整排 ${recipe.press.bar} N・上限 ${SPEC.forceLimit} N` : `每顆 ${recipe.press.single} N・上限 ${SPEC.forceLimit} N`;

// 手臂 TCP 軌跡
const trailN = 800, trailPos = new Float32Array(trailN * 3); let trailCount = 0;
const trailGeo = new THREE.BufferGeometry(); trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPos, 3)); trailGeo.setDrawRange(0, 0);
const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0x7fd4ff, transparent: true, opacity: 0.7 })); scene.add(trail);
function pushTrail(p) { if (trailCount >= trailN) { trailPos.copyWithin(0, 3); trailCount = trailN - 1; } trailPos.set([p.x, p.y, p.z], trailCount * 3); trailCount++; trailGeo.attributes.position.needsUpdate = true; trailGeo.setDrawRange(0, trailCount); }

// 3D 標籤（共用舞台的標籤層；畫布在頁面中的偏移由 stage 處理），標籤放在點的上方；
// priority：小畫面標籤重疊時先留下手臂、壓墊與兩台相機，輸送與電控的說明其次
const addLabel = (html, getPos, priority = 0) => stage.addLabel(html, getPos, '', { anchor: 'above', priority });
const top = LAYOUT.conveyorTop;
addLabel('<b>DENSO</b> VS-068', () => new THREE.Vector3(...LAYOUT.robot).add(new THREE.Vector3(0, 120, -110)), 3);
addLabel(INSERT === 'bar' ? '8 頭整排壓墊（獨立彈簧）' : '單點彈簧壓頭（快拆）', () => robot.getTcpWorld('press').add(new THREE.Vector3(0, 50, 0)), 2);
addLabel('20MP 斜視相機 45°', () => robot.tcps.cam.parent.localToWorld(new THREE.Vector3(0, 150, 10)).add(new THREE.Vector3(0, 50, 0)), 1);
addLabel('固定全局相機 20MP', () => new THREE.Vector3(...LAYOUT.globalCam).add(new THREE.Vector3(0, 120, 0)), 1);
addLabel('止擋＋頂升', () => new THREE.Vector3(LAYOUT.stopFace, top - 60, 150));
addLabel('上游 · 前站放置 USB', () => new THREE.Vector3(-1100, top + 120, 0));
addLabel('下游 · 迴焊爐', () => new THREE.Vector3(1100, top + 120, 0));
addLabel('RC8A／PLC／IPC', () => new THREE.Vector3(0, 700, -240));

// 站別按鈕
STATIONS.forEach((name, i) => { const b = document.createElement('button'); b.className = 'st'; b.dataset.st = i; b.innerHTML = `<span class="idx">S${i}</span>${name}`; ui.stations.appendChild(b); });

// ---------------------------------------------------------------- 時間軸（時間與播放狀態在 createPlayer，見下方）
let S, T = 0, current, curStation = -1, player;
// 流程取樣（不移動手臂關節；播放中由到位閘門呼叫）；跳播用 project.apply（取樣＋手臂直接到位）
function sample(t) { current = project.sample(t); S = current.state; return current; }
const total = sequence.total, stationStart = sequence.stationStart, shots = sequence.shots;
ui.cycleTime.textContent = `規劃 ${total.toFixed(1)} s／盤（含一次補壓）＋到位等待 · ${product.ids.length} 顆 · 拍 ${shots.length} 張`;
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
// 壓合特寫的注視點：桌面看第一顆接頭；窄畫布（手機直向，寬高比 < 1.25）用整排壓墊時改看第一排的中點，
// 拉遠後整排接頭才不會被畫面右緣切掉（距離仍由 stage 的 narrowFit 依畫面比例拉遠）
function pressFocus() {
  const first = recipe.connectors[0], narrow = canvas.clientWidth / canvas.clientHeight < 1.25;
  if (!narrow || INSERT !== 'bar') return stationPoint(first.id);
  const row = recipe.connectors.filter(c => c.row === first.row);
  return row.reduce((s, c) => s.add(stationPoint(c.id)), new THREE.Vector3()).divideScalar(row.length);
}
const views = {
  electrical: () => [[0,520,850],[0,420,-500]],
  wiring: () => [[-1200,1850,700],[0,1200,-300]],
  iso: () => [[-1250, 1650, 1550], [0, 950, -200]], conveyor: () => [[-420, 1180, 820], [st.place.x, 915, st.place.z]], robot: () => [[-950, 1450, 150], [0, 1030, -280]],
  press: () => { const p = pressFocus(); return [p.clone().add(new THREE.Vector3(-150, 60, 90)).toArray(), p.toArray()]; },
  inspect: () => { const p = stationPoint(product.ids[0]); return [p.clone().add(new THREE.Vector3(130, 80, 120)).toArray(), p.clone().add(new THREE.Vector3(20, -5, 10)).toArray()]; },
  top: () => [[st.place.x, 2400, st.place.z + 120], [st.place.x, 900, st.place.z - 150]],
  product: () => { const p=product.root.position.clone().add(new THREE.Vector3(0,recipe.pallet.t,0)); const d=Math.max(recipe.pallet.w,recipe.pallet.d); return [p.clone().add(new THREE.Vector3(-d*.48,d*.95,d*.85)).toArray(),p.toArray()]; },
  leads: () => { const c=product.conns[focusId], p=product.leadPoint(focusId); const offset=(c.T.w<10 ? new THREE.Vector3(4,5,14) : new THREE.Vector3(9,7,20)).applyAxisAngle(new THREE.Vector3(0,1,0),c.rot*Math.PI/180); return [p.clone().add(offset).toArray(),p.toArray()]; },
};
let selectedView = 'iso';
// 視角轉場交給共用舞台（stage.goTo）；轉場時間與原本相同（約 0.7 s）
function setView(name, instant = false) {
  workspace.stopFollowing(); setElectricalCutaway(scene,name==='electrical');
  if (!views[name]) return; selectedView = name;
  lastProductPosition.copy(product.root.position);
  camera.near=name==='leads' ? .15 : 2; camera.updateProjectionMatrix();
  const [p, t, fit] = views[name]();
  stage.goTo(p, t, instant, 1 / 1.4, fit);
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));
// player 的 apply：seek（播放列、站別按鈕、sim.seekTo）→ 流程取樣＋手臂直接到位，清除到位等待、故障與軌跡；
// 連續播放 → 流程已由到位閘門取樣（手臂在 gate.advance 裡限速追蹤）
let lastSeek = true;
function applyTime(t, { seek }) {
  T = t; lastSeek = seek;
  if (seek) { current = project.apply(T); S = current.state; gate.reset(); trailCount = 0; trailGeo.setDrawRange(0, 0); }
  return current;
}
// 到位閘門（core/anim/arrival.js）＝player 的 advance：規則 ARRIVAL 在 sequence.js（與 tools/verify.mjs 的連續播放共用）——
// ≤ 10 ms 子步、手臂未到位就停在步驟終點等、等超過 8 s 判故障；示意 NG 時複檢後停線
const gate = createArrivalGate({ ...ARRIVAL, total, error: () => robot.error(), step: () => current.step, sample, update: h => robot.update(h),
  fault: () => st.opts.ngHold && current.completed.has('recheck') ? `NG · ${stub} 補壓後仍未貼合，停線待人工確認` : '' });
// 按播放時：故障後從原處重新到位、播完則從頭（在 player 自己的處理之前執行）
function resume() { if (gate.fault || T >= total) player.seekTo(gate.fault ? T : 0); gate.reset(); }
ui.playBtn.addEventListener('click', () => { if (!player.playing) resume(); });
ui.result.onchange = () => { st.opts.ngHold = ui.result.value === 'NG'; player.seekTo(T); };
ui.stations.querySelectorAll('.st').forEach(b => b.onclick = () => player.seekTo(stationPreviewTime(sequence, +b.dataset.st)));

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
const shotIds = () => project.shotIds(S);

function exportReport() {
  const units = product.ids.map(id => ({ id, simulatedGapMm: +st.state.gap[id].toFixed(3), status: unitStatus(id)[1] }));
  const report = { mode: 'SIMULATION', recipe: RECIPE_KEY, recipeName: recipe.name, insert: INSERT, pallet: recipe.pallet.code, time: T, plannedCycle: total, result: current.completed.has('judge') ? (st.opts.ngHold ? 'NG' : 'OK') : 'PENDING', gapLimitMm: recipe.gapLimit,
    units, exposureEvents: sequence.steps.filter(s => s.exposure && s.start + s.dur <= T).map(s => ({ action: s.action, plannedTime: s.start, simulation: true })),
    physicalMeasurement: false, mesConnected: false, assumptions: recipe.source, motion: robot.error() };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = `USB-PRESS-${RECIPE_KEY}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
ui.exportBtn.onclick = exportReport;

const arrived = () => project.arrived(current);
const signals = [['載盤到位', () => S.located], ['止擋伸出', () => S.stop > .99], ['頂升定位', () => S.lift > .99], ['全局辨識完成', () => S.detected > 0],
  ['壓頭接觸', () => st.state.force > .5], ['工具到位', arrived], ['下游可收板', () => S.station === 5 || S.station === 0]];
signals.forEach(([name]) => { const row = document.createElement('div'); row.innerHTML = `<i></i><span>${name}</span>`; ui.signals.appendChild(row); });
const useGlobalView = () => cameraSource(S, current.step, arrived()) === 'global';

function drawHud() {
  const e = robot.error(), ps = st.state, force = ps.force;
  // 取像閃光、力值顏色、ROI 框、三色燈（與 project.apply 同一份）
  project.show(current, { time: T, playing: player.playing, fault: gate.fault });
  const ids = S.flashTool > 0 ? shotIds() : [];
  const last = shotIds();
  const globalView = useGlobalView();
  ui.pipTitle.textContent = globalView ? '全局相機 · 載盤預覽（模擬）' : '手臂相機 · USB 貼合檢查（模擬）';
  ui.pipTitle.title = globalView ? '20MP · 20 mm · 距離約 800 mm' : '20MP · 25 mm · 45° 斜視 · WD 175 mm';
  ui.pipResult.innerHTML = globalView ? (S.station === 1 ? (S.detected > 0 ? `<span class="ok">${recipe.pallet.code}・找到 ${product.ids.length} 顆</span>` : '<span>全局取像中…</span>') : !S.located ? '<span>等待載盤到站</span>' : '<span>手臂未在取像位 · 顯示整盤 USB</span>')
    : last.length ? (S.flashTool > 0 ? '取像中　' : '最近取像　') + last.map(id => { const g = ps.gap[id], ok = g <= recipe.gapLimit; return `<span class="${ok ? 'ok' : 'ng'}">${id} ${g.toFixed(2)} mm ${ok ? 'OK' : 'NG'}</span>`; }).join('　') : '<span>—</span>';
  cell.occluders.visible = ui.showGuards.checked; trail.visible = ui.showPath.checked;
  ui.action.textContent = S.action; ui.substep.textContent = S.sub;
  ui.phase.textContent = gate.fault || (T >= total ? 'COMPLETE · 本盤完成' : gate.waiting > 0 ? '等待手臂到位' : player.playing ? 'AUTO · 執行中' : 'HOLD · 暫停'); ui.phase.classList.toggle('fault', !!gate.fault);
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
  ui.progBar.style.width = T / total * 100 + '%';   // 時間軸、時鐘、步驟選單由 player 更新
  stage.updateLabels(ui.showLabels.checked);
  document.getElementById('diagnostics').textContent = JSON.stringify({ recipe: RECIPE_KEY, insert: INSERT, time: T, total, step: current.index, station: S.station, action: S.action, poseError: e, force, playing: player.playing, waiting: gate.waiting, fault: gate.fault, gaps: ps.gap, lift: S.lift, stop: S.stop });
}
// 主畫面以外的每格工作：面板、產品追隨、電控狀態、相機子畫面（子畫面畫進離屏目標，不動主畫布）
function prepareFrame() {
  drawHud(); workspace.follow();electrical.update({time:T,playing:player.playing,action:S.action,motion:true,vision:!!(S.flashTool||S.flashTop||S.flashUp||S.flashDown||S.flashSn)});
  renderer.setScissorTest(false); renderer.setViewport(0,0,canvas.clientWidth,canvas.clientHeight);
  const hidden=[cell.occluders,trail,...project.roiBoxes],visible=hidden.map(o=>o.visible); hidden.forEach(o=>o.visible=false);
  const exposure=renderer.toneMappingExposure;renderer.toneMappingExposure=.88;
  const global=useGlobalView(),shotReady=S.flashTool>0&&arrived();
  workspace.renderCamera({renderer,scene,camera:global?cell.globalCam:robot.pipCam,vision,aspect:SENSOR_ASPECT,
    marks:{title:global?'USB 定位':'銀腳貼合',state:global?(S.station===1&&S.detected>0?'定位示意':'預覽'):shotReady?`本幀取像 · ≤ ${recipe.gapLimit} mm`:'待取像',time:T,marks:ssdResults(product,recipe,{global,detected:S.station===1&&S.detected>0,exposure:shotReady,ids:shotIds(),gaps:st.state.gap})}});
  renderer.toneMappingExposure=exposure;hidden.forEach((o,i)=>o.visible=visible[i]);
}
// 完整一格（跳播、截圖、錄影直接呼叫）
function render() { prepareFrame(); workspace.renderOverview(renderer,scene); }
const workspace=createViewerWorkspace({camera,controls,canvas,resize:stage.resize,focusOccluders:[cell.occluders],
  getFocus:()=>product.root.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,recipe.pallet.t+5,0)),
  focusOffset:[-recipe.pallet.w*.55,recipe.pallet.w*.85,recipe.pallet.d*.95],
  onFocus:()=>{setElectricalCutaway(scene,false);stage.cancelTween();selectedView='focus';document.querySelectorAll('.views button').forEach(b=>b.classList.remove('selected'));}});
const electrical=createElectricalInspector({scene,camera,controls,canvas,onEnter:()=>setView('electrical',true),onExit:()=>setView('iso',true),title:'RobotArmPressSSD'});
const lastProductPosition = product.root.position.clone();
// stage.loop 每格：視角轉場 → frameTick(dt) → controls.update() → 主畫面 renderer.render(scene, camera)
function frameTick(dt) {
  player.update(dt);   // 推進時間（gate.advance：到位等待、故障停住、手臂限速追蹤）→ apply
  // 載盤近看／銀腳特寫時視角跟著輸送中的載盤（含進行中的轉場）
  if (selectedView==='product'||selectedView==='leads') stage.shiftView(product.root.position.clone().sub(lastProductPosition));
  lastProductPosition.copy(product.root.position);
  if (player.playing && ui.showPath.checked) pushTrail(robot.getTcpWorld(robot.goal.tcp));
  prepareFrame();
  // 主畫面接著由 stage 繪製；產品追隨（◎）時與 workspace.renderOverview 相同，暫時隱藏外罩（下一格 drawHud 依勾選還原）
  if (workspace.following) cell.occluders.visible = false;
}
// 播放列（共用 createPlayer）：時間、播放／暫停、重播、速度、時間軸、時鐘、步驟選單與上一步／下一步；
// 跳播走 applyTime（手臂直接到位）並立即重畫一格（截圖與檢查直接呼叫 sim.seekTo）；連續播放由 frameTick 繪製
player = createPlayer({ total, apply: applyTime, advance: gate.advance, events: sequence.events.map(ev => ({ ...ev, label: `S${ev.station} · ${ev.label}` })),
  onChange: () => { if (lastSeek && player) render(); } });   // 建立時的第一次跳播不重畫（最後統一 render）
setView('iso', true); stage.resize();
exposeSim({ seekTo: player.seekTo, views: Object.keys(views), project, pause: player.pause, play() { resume(); player.play(); }, get state() { return S; }, get T() { return T; }, get playing() { return player.playing; }, robot, total, stationStart, steps: sequence.steps, events: sequence.events, setView, recipe: RECIPE_KEY, insert: INSERT });
if (qp.has('st')) { player.pause(); const station = THREE.MathUtils.clamp(+qp.get('st') || 0, 0, STATIONS.length - 1); player.seekTo(qp.has('t') ? stationStart[station] + (+qp.get('t') || 0) : stationPreviewTime(sequence, station)); }
if (qp.has('step')) { player.pause(); player.seekTo(sequence.steps[THREE.MathUtils.clamp(+qp.get('step') || 0, 0, sequence.steps.length - 1)].start + (+qp.get('t') || 0)); }
if (qp.has('view')) setView(qp.get('view'), true);
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6 && a.every(Number.isFinite)) stage.goTo(a.slice(0, 3), a.slice(3), true); }
document.getElementById('loading').classList.add('hide'); render(); stage.loop(frameTick);   // ?movie 時 stage 不啟動迴圈

// ---------------------------------------------------------------- 展示影片（?movie）：依絕對時間逐格取樣，與 project.apply 同一路徑
if (qp.has('movie')) {
  player.pause();
  const { installMovie } = await import('@core/movie/movie.js');
  installMovie({ project: 'RobotArmPressSSD', scene, renderer, camera, controls, render, setView, total, steps: sequence.steps,
    sample(t) { T = t; current = project.apply(t); S = current.state; },
    focus: () => product.root.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, recipe.pallet.t + 5, 0)),
    offset: [-recipe.pallet.w * 1.1, recipe.pallet.w * 1.65, recipe.pallet.d * 1.9] });
}
