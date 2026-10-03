import {createElectricalInspector} from '@core/electrical/electrical-inspector.js';
import {setElectricalCutaway} from '@core/electrical/electrical-cabinet.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { routingLegend } from '@core/electrical/cable-routing.js';
routingLegend();
// 主程式：場景、時間軸（動作序列）、UI、相機子畫面（上視遠心相機／手臂下視相機）
// 舞台、3D 標籤、視角轉場用 core/ui/stage.js；播放列用 core/ui/player.js（advance 提供「等手臂到位才前進」的播放推進）
import * as THREE from 'three';
import { createStage, exposeSim } from '@core/ui/stage.js';
import { createPlayer } from '@core/ui/player.js';
import { createVisionOverlay } from '@core/ui/vision-overlay.js';
import { createProject } from './project.js';
import { STATIONS, SPEC, OFFSETS } from './sequence.js';
import { LAYOUT, NEST_SEAT, TRAYS } from './cell.js';
import { BLADES, PART } from './product.js';
import { TOOL, SCARA } from './robot.js';
import { cameraSource, stationPreviewTime, SENSOR_ASPECT } from './camera-view.js';
import { shutterMarks } from './vision-results.js';
const vision = createVisionOverlay();

const qp = new URLSearchParams(location.search);
const NG = qp.get('result') === 'NG';

// ---------------------------------------------------------------- 場景（共用舞台 core/ui/stage.js）
// 畫面迴圈仍由本檔管理：每格要畫 HUD、主畫面與相機子畫面（多次 render），stage.loop 只會畫一次主相機
const canvas = document.getElementById('c');
// 外觀用 look 'cell'（曝光、背景、半球光與太陽／補光的顏色強度）；燈位、陰影與霧照舊明確寫，不用 extent：
// extent 推算的燈位、陰影範圍與 bias（-0.0003）都和本站原本的設定（bias -0.00004）不同，換掉會改變桌面畫面
const stage = createStage({
  canvas, qp, look: 'cell', fog: [5000, 11000],
  logDepth: true,                                   // ?logdepth=0 可關
  envLight: 220,                                    // RoomEnvironment 點光強度（look 'cell' 為 230）
  camera: { fov: 40, near: 2, far: 20000 },
  controls: { enableDamping: true, dampingFactor: .08, maxPolarAngle: Math.PI * .49, minDistance: 3, maxDistance: 7000 },
  sun: { position: [-1500, 3200, 1800], target: [0, 0, 0],
    shadow: { mapSize: 2048, camera: { left: -1200, right: 1200, top: 1200, bottom: -1200, near: 500, far: 8000 }, bias: -.00004, normalBias: .08 } },
  fill: { position: [1800, 1500, -1800] },
});
const { renderer, scene, camera, controls } = stage;
// 作業區局部光：治具與相機附近的小零件需要細緻陰影（stage 的 extraLights 不含陰影與 target，故在此自建）
const taskLight = new THREE.DirectionalLight(0xfff5e7, 1.2);
taskLight.position.set(-25, 994, 120); taskLight.target.position.set(0, 929, 80);
taskLight.castShadow = renderer.shadowMap.enabled; taskLight.shadow.mapSize.set(2048, 2048);
Object.assign(taskLight.shadow.camera, { left: -28, right: 28, top: 28, bottom: -28, near: 10, far: 140 });
taskLight.shadow.bias = -.00001; taskLight.shadow.normalBias = .004;
scene.add(taskLight, taskLight.target);

// ---------------------------------------------------------------- 物件（與 core 統一檢查共用 project.js）
const project = createProject({ scene, ng: NG });
const { st, cell, robot, sequence } = project;
const ui = Object.fromEntries(['action', 'substep', 'forceBar', 'forceVal', 'forceLim', 'zoneDot', 'zoneTxt', 'checklist', 'chkCount', 'playBtn', 'speed', 'showPath', 'progBar', 'signals', 'poseError', 'phase', 'result', 'exportBtn', 'showGuards', 'showLabels', 'showPip', 'cycleTime', 'units', 'okCount', 'pipFrame', 'pipResult', 'pipTitle', 'stations', 'drawerNote'].map(id => [id, document.getElementById(id)]));
ui.result.value = NG ? 'NG' : 'OK';
ui.result.onchange = () => { const q = new URLSearchParams(location.search); q.set('result', ui.result.value); q.delete('step'); q.delete('st'); location.search = q.toString(); };
ui.forceLim.textContent = `設定 ${SPEC.pressForce} N・上限 ${SPEC.forceLimit} N`;
ui.drawerNote.textContent = '抽屜 A 供料中｜B 滿料待命（可拉出換盤）';

// 手臂 TCP 軌跡
const trailN = 1200, trailPos = new Float32Array(trailN * 3); let trailCount = 0;
const trailGeo = new THREE.BufferGeometry(); trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPos, 3)); trailGeo.setDrawRange(0, 0);
const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0x7fd4ff, transparent: true, opacity: 0.7 })); scene.add(trail);
function pushTrail(p) { if (trailCount >= trailN) { trailPos.copyWithin(0, 3); trailCount = trailN - 1; } trailPos.set([p.x, p.y, p.z], trailCount * 3); trailCount++; trailGeo.attributes.position.needsUpdate = true; trailGeo.setDrawRange(0, trailCount); }

// 3D 標籤（stage.addLabel；位置每格由 stage.updateLabels 更新）；小螢幕重疊時先留手臂，其次治具與上視相機（priority）
const V = (x, y, z) => new THREE.Vector3(x, y, z);
stage.addLabel('<b>DENSO</b> HSR065 SCARA', () => V(...LAYOUT.robot).add(V(0, 420, -40)), '', { priority: 2 });
stage.addLabel('T1 葉片吸嘴', () => robot.getTcpWorld('T1').add(V(0, 60, 0)));
stage.addLabel('T2 上蓋吸盤＋荷重元', () => robot.getTcpWorld('T2').add(V(0, 75, 0)));
stage.addLabel('T3 本體夾爪', () => robot.getTcpWorld('T3').add(V(0, 60, 0)));
stage.addLabel('下視相機 5MP', () => robot.getTcpWorld('cam').add(V(0, 95, 0)));
stage.addLabel('上視遠心相機', () => V(LAYOUT.upCam.x, LAYOUT.table + 30, LAYOUT.upCam.z), '', { priority: 1 });
stage.addLabel('組裝治具（基準邊＋推塊夾緊）', () => V(LAYOUT.nest.x, LAYOUT.nest.top + 20, LAYOUT.nest.z), '', { priority: 1 });
stage.addLabel('離子風嘴', () => V(LAYOUT.upCam.x - 75, LAYOUT.table + 60, LAYOUT.upCam.z));
stage.addLabel('NG 盒', () => V(LAYOUT.ngBin.x, LAYOUT.ngBin.top + 15, LAYOUT.ngBin.z));
stage.addLabel('抽屜 A · 供料中', () => V(-LAYOUT.drawerX, LAYOUT.table + 60, 0));
stage.addLabel('抽屜 B · 待命可換盤', () => V(LAYOUT.drawerX, LAYOUT.table + 60, 0));
stage.addLabel('RC8A／PLC／視覺 IPC', () => V(0, 700, LAYOUT.encl.z1 + 10));

// 站別按鈕（跳到該站第一次取像，讓相機子畫面有內容）
STATIONS.forEach((name, i) => { const b = document.createElement('button'); b.className = 'st'; b.dataset.st = i; b.innerHTML = `<span class="idx">S${i}</span>${name}`; ui.stations.appendChild(b); });
ui.stations.querySelectorAll('.st').forEach(b => b.onclick = () => { player.pause(); player.seekTo(stationPreviewTime(sequence, +b.dataset.st)); });

// ---------------------------------------------------------------- 時間軸
let S, T = 0, current, waiting = 0, fault = '', curStation = -1, player = null;
const total = project.total, stationStart = sequence.stationStart;
const shots = sequence.steps.filter(s => s.exposure).length;
ui.cycleTime.textContent = `規劃 ${total.toFixed(1)} s／顆＋到位等待 · 取像 ${shots} 次${NG ? ' · 含一次疊片剔除重取' : ''}`;
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
// 橫向手機（精簡版面且畫布寬高比 > 2）：垂直方向看得到的範圍很小，上視相機視角整體下移 30 mm，環形光才不會落在畫布底邊；桌面不受影響
const wideShort = () => document.body.classList.contains('viewer-compact') && canvas.clientWidth > 2 * canvas.clientHeight;
const views = {
  electrical: () => [[900,1000,1250],[0,480,-400]],
  wiring: () => [[800,1750,-700],[0,1310,-300]],
  iso: () => [[-1350, 1850, 1650], [0, 930, -150]],
  robot: () => [[-850, 1450, 650], [0, 1100, -220]],
  nest: () => [nestP.clone().add(V(-70, 85, 115)).toArray(), nestP.clone().add(V(0, 0, -5)).toArray()],
  part: () => { const p = st.pose('base').p; return [p.clone().add(V(-16, 26, 28)).toArray(), p.toArray()]; },
  upcam: () => { const p = V(LAYOUT.upCam.x, LAYOUT.upCam.focus - (wideShort() ? 50 : 20), LAYOUT.upCam.z); return [p.clone().add(V(-120, 45, 150)).toArray(), p.toArray()]; },
  trays: () => [[-390, 1180, 40], [-390, 912, -305]],
  top: () => [[0, 2300, -80], [0, 900, -100]],
};
let selectedView = 'iso';
const followBase = () => selectedView === 'part';
function setView(name, instant = false) {
  workspace.stopFollowing(); setElectricalCutaway(scene,name==='electrical');
  if (!views[name]) return; selectedView = name;
  camera.near = name === 'part' ? 0.1 : name === 'nest' || name === 'upcam' ? 0.5 : 2; camera.updateProjectionMatrix();
  lastBase.copy(st.pose('base').p);
  const [p, t] = views[name]();
  stage.goTo(p, t, instant, 1 / 1.4);
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));
// 跳播（拖曳、選步驟、上一步／下一步、跳站、sim.seekTo）：整個場景由 project.apply(T) 決定（與檢查相同）；
// snap=false 只換流程狀態、手臂保持原姿態
let snapSeek = true;
function jump(t) {
  T = t;
  if (snapSeek) current = project.apply(T); else { current = sequence.sample(T); st.sync(); }
  S = current.state; waiting = 0; fault = ''; trailCount = 0; trailGeo.setDrawRange(0, 0);
  return current;
}
function seekTo(sec, snap = true) { snapSeek = snap; try { player.seekTo(sec); } finally { snapSeek = true; } render(); }

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
  const playing = player.playing;
  cell.tower.set(fault ? 'red' : NG && current.completed.has('judgeNG') && !current.completed.has('reject') ? 'yellow' : T >= total - 1e-6 ? 'green' : playing ? 'green' : 'yellow');
  cell.occluders.visible = ui.showGuards.checked; trail.visible = ui.showPath.checked;
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
  // 時間軸、時鐘、步驟選單由播放列（createPlayer）更新
  ui.progBar.style.width = T / total * 100 + '%';
  stage.updateLabels(ui.showLabels.checked);
  document.getElementById('diagnostics').textContent = JSON.stringify({ time: T, total, step: current.index, station: S.station, action: S.action, poseError: e, force, playing, waiting, fault, loc: S.loc, view: S.view, shot: S.shot });
}
const resize = stage.resize;   // stage 已掛視窗 resize 事件
function render() {
  drawHud(); workspace.follow();electrical.update({time:T,playing:player.playing,action:S.action,motion:true,vision:!!(S.flashTool||S.flashTop||S.flashUp||S.flashDown||S.flashSn)});
  taskLight.target.position.copy(st.pose('base').p); taskLight.position.copy(st.pose('base').p).add(V(-25,65,40));
  renderer.setScissorTest(false);renderer.setViewport(0,0,canvas.clientWidth,canvas.clientHeight);workspace.renderOverview(renderer,scene);
  const src=cameraSource(S),shooting=src==='up'?S.flashUp>0:S.flashDown>0;
  const hidden=[cell.occluders,trail],visible=hidden.map(o=>o.visible);hidden.forEach(o=>o.visible=false);
  const exposure=renderer.toneMappingExposure;renderer.toneMappingExposure=.9;
  workspace.renderCamera({renderer,scene,camera:src==='up'?cell.upCam:robot.pipCam,vision,aspect:SENSOR_ASPECT,
    marks:{title:src==='up'?'上視對位':'下視檢查',state:shooting?'本幀取像':'即時',time:T,marks:shutterMarks(st,S,{cam:src,exposure:shooting})}});
  renderer.toneMappingExposure=exposure;hidden.forEach((o,i)=>o.visible=visible[i]);
}
const workspace=createViewerWorkspace({camera,controls,canvas,resize,focusOccluders:[cell.occluders],getFocus:()=>st.pose('base').p,
  focusOffset:[-24,35,42],focusNear:.1,onFocus:()=>{setElectricalCutaway(scene,false);stage.cancelTween();selectedView='focus';document.querySelectorAll('.views button').forEach(b=>b.classList.remove('selected'));}});
const electrical=createElectricalInspector({scene,camera,controls,canvas,onEnter:()=>setView('electrical',true),onExit:()=>setView('iso',true),title:'shutter assembly'});
const lastBase = new THREE.Vector3();

// ---------------------------------------------------------------- 播放
// 播放列（core/ui/player.js）負責按鈕、時間軸、步驟選單、上一步／下一步與時間推進：
//   apply(T, { seek: true })  跳播 → jump（project.apply，手臂直接到位）
//   advance(T, dt)            連續播放 → 以 5 ms 細分推進：手臂以實際限速追蹤目標，步驟結束或接近／接觸中偏離時
//                             「等到位」才前進；等超過 5 秒判定逾時，回傳 null 讓播放列停住
//   apply(T, { seek: false }) 連續播放的一格：狀態已在 advance 中取樣，直接回傳
// 一顆的最後一步也要等手臂到位才算播完；從逾時處再按播放時，手臂先依目前時間重新到位。
// 等待計時只在播放中累計（暫停即歸零，與原本「按播放時歸零」相同）。
function tick(dt) {
  const e = robot.error(), s = current.step, end = s.start + s.dur;
  const blocked = (T >= end - 1e-7 || ((s.contact || s.near) && e.position > .5)) && (e.position > .05 || e.angle > .2);
  let going = true;
  if (blocked) { waiting += dt; if (waiting > 5) { fault = '到位逾時 · 請檢查 TCP 位置'; going = false; } }
  else {
    waiting = 0;
    if (T >= total - 1e-7) going = false;
    else { T = T >= end - 1e-7 ? Math.min(total, end + 1e-6) : Math.min(end, T + dt); current = sequence.sample(T >= end - 1e-7 && T <= end ? Math.max(s.start, end - 1e-8) : T); S = current.state; }
  }
  robot.update(dt); st.sync();
  return going;
}
function advance(t, dt) {
  if (fault) jump(t);                                 // 從逾時停住處恢復：手臂重新到位
  const n = Math.max(1, Math.ceil(dt / .005));
  let going = true;
  for (let k = 0; k < n && going; k++) going = tick(dt / n);
  if (fault) return null;
  return going ? Math.min(T, total - 1e-8) : total;  // 最後一步到位前不讓播放列判定播完
}
player = createPlayer({
  total, advance, apply: (t, { seek }) => seek ? jump(t) : current,
  events: sequence.events.map(e => ({ time: e.time, label: `S${e.station} · ${e.label}` })),
});
function frame(dt) {
  player.update(dt);
  if (!player.playing && !fault) waiting = 0;
  // 產品近看：視角跟著本體移動（轉場進行中，stage.shiftView 連同轉場起訖點一起平移）
  if (followBase()) stage.shiftView(st.pose('base').p.clone().sub(lastBase));
  lastBase.copy(st.pose('base').p);
  if (player.playing && ui.showPath.checked) pushTrail(robot.getTcpWorld(robot.goal.tcp));
  return true;
}
lastBase.copy(st.pose('base').p); setView('iso', true);
exposeSim({ seekTo, views: Object.keys(views), pause: player.pause, play: player.play, get state() { return S; }, get T() { return T; }, robot, total, stationStart, steps: sequence.steps, events: sequence.events, setView, ng: NG, trays: TRAYS, scara: SCARA, part: PART });
if (qp.has('st')) { player.pause(); const station = THREE.MathUtils.clamp(+qp.get('st') || 0, 0, STATIONS.length - 1); seekTo(qp.has('t') ? stationStart[station] + (+qp.get('t') || 0) : stationPreviewTime(sequence, station)); }
if (qp.has('step')) { player.pause(); seekTo(sequence.steps[THREE.MathUtils.clamp(+qp.get('step') || 0, 0, sequence.steps.length - 1)].start + (+qp.get('t') || 0)); }
if (qp.has('time')) { player.pause(); seekTo(+qp.get('time')); }
if (qp.has('view')) setView(qp.get('view'), true);
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6 && a.every(Number.isFinite)) stage.goTo(a.slice(0, 3), a.slice(3), true); }
document.getElementById('loading').classList.add('hide');
// 畫面迴圈交給 stage（?movie 時 stage 不跑迴圈）；每格自訂繪製：HUD、主畫面、相機子畫面
stage.loop(frame, { render });
render();
if (qp.has('movie')) {
  // 錄影（?movie）：不跑畫面迴圈，由 core/movie/movie.js 依絕對時間逐格驅動
  player.pause();
  const { installMovie } = await import('@core/movie/movie.js');
  installMovie({
    project: 'shutter assembly', scene, renderer, camera, controls, render, setView, total,
    steps: sequence.steps,
    // 與檢查相同的 project.apply 路徑（流程狀態 → 手臂 snap → 零件就位）
    sample(t) { T = t; current = project.apply(t); S = current.state; },
    // 鏡頭焦點：手上的零件；手上沒有就看本步驟要去拿的零件，再沒有就看本體
    focus: () => {
      const held = Object.entries(S.loc).find(([, loc]) => /^T[123]$/.test(loc));
      if (held) return st.pose(held[0]).p;
      const next = current.step.end.loc;
      const pick = Object.keys(next).find(id => /^T[123]$/.test(next[id]));
      return pick ? st.pose(pick).p : st.pose('base').p;
    },
    offset: [-130, 200, 270],
  });
}
