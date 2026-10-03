// 主程式：場景、依絕對時間套用各設備狀態、側欄面板、視角、相機子畫面與焦點追隨。
// 共用元件：舞台與 3D 標籤（core/ui/stage.js）、播放列（core/ui/player.js）、相機子畫面與焦點追隨（core/ui/viewer-workspace.js）。
import * as THREE from 'three';
import { createStage, exposeSim } from '@core/ui/stage.js';
import { createPlayer } from '@core/ui/player.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { createVisionOverlay } from '@core/ui/vision-overlay.js';
import { COLUMN, UPRIGHT, DECAP, BOOTH, WASTE, layoutChecks, ROBOT, LABEL, LYING, INBOUND, PAYLOAD, payloadAt } from './layout.js';
import { MAT } from '@core/geom/materials.js';
import { applyPlant } from './plant.js';
import { createProject } from './project.js';
import { STATIONS, DRUM_IDS, IN_IDS, DRUM_KEYS, SPRAY_S, SPRAY_SINGLE_S } from './sequence.js';
import { finishMaterials } from '@core/geom/hardware.js';

const qp = new URLSearchParams(location.search);
// ---------------------------------------------------------------- 場景（共用舞台，按需重繪：靜止時不重畫，狀態改變時 stage.invalidate）
const canvas = document.getElementById('c');
// 對數深度緩衝：場景 15 m、細節到 mm，一般深度緩衝會讓貼地的分區、標線互搶深度而閃爍
const stage = createStage({
  canvas, qp, exposure: .86, logDepth: true, onDemand: true,
  camera: { fov: 40, near: 100, far: 150000 },
  controls: { maxPolarAngle: Math.PI * .495, minDistance: 400, maxDistance: 70000 },
  hemi: { sky: 0xcfe0ff, ground: 0x30363d, intensity: .55 },
  sun: { intensity: 1.7, position: [-3000, 17000, 4000], target: [5000, 0, 8000], shadow: { mapSize: 4096, camera: { left: -11000, right: 11000, top: 11000, bottom: -11000, near: 2000, far: 40000 }, bias: -.0003, normalBias: 3 } },
  fill: { color: 0x9fb8ff, intensity: .45, position: [16000, 9000, 22000] },
});
const { renderer, scene, camera, controls } = stage;
finishMaterials(renderer);
// r160 的環境反射強度設在材質 envMapIntensity（finishMaterials）。

// ---------------------------------------------------------------- 物件（與 core 統一檢查共用 project.js）
const project = createProject({ scene });
const { plant, seq } = project;
const { building, agv, line, robot, washing, drums } = plant;
const total = seq.total;

// 相機取像事件（子畫面自動切換用）
const shots = [];
for (const [key, cam, title] of [['labeler', line.labelCam, '貼標相機 · 桶塞定位／標籤檢查（模擬影像）'], ['decap', line.decapCam, '頂視相機 · 桶塞定位（模擬影像）']])
  for (const s of seq.tracks[key].steps) if (s.end.flash && !s.initial.flash) shots.push({ start: s.start, cam, title, result: s.sub });
shots.sort((a, b) => a.start - b.start);

// ---------------------------------------------------------------- 套用狀態（時間只由播放列推進，畫面一律經 applyState(T)）
let S = null, player = null, selectedView = 'iso';
const isPlaying = () => player ? player.playing : !qp.has('pause');
function applyState(T) {
  S = seq.sample(T); applyPlant(plant, S, { playing: isPlaying() });
  stage.invalidate(true); return S;
}

// ---------------------------------------------------------------- UI
const $ = id => document.getElementById(id);
const ui = Object.fromEntries(['payload', 'speed', 'cycleTime', 'phase', 'equip', 'drums', 'tanks', 'checks', 'chkCount', 'showDims', 'showFence', 'showLabels', 'showCeiling', 'xray', 'stations', 'focusTarget', 'focusStatus', 'pipSource'].map(id => [id, $(id)]));
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
ui.cycleTime.textContent = `本棧板 4 桶共 ${Math.round(total)} s（模擬時間）`;
// 手臂節拍：相鄰兩桶放回輸送線的間隔
const placed = seq.events.filter(e => e.label.endsWith('放回輸送線')).map(e => e.time), cycle = placed.at(-1) - placed.at(-2);
$('cycleNote').textContent = `散桶入庫 4 桶＋一個棧板（4 桶）走完全線。手臂一桶約 ${cycle.toFixed(0)} s，是整線瓶頸（約 ${Math.floor(3600 / cycle)} 桶／h；200 桶約 ${(200 * cycle / 3600).toFixed(1)} h）。雙孔進水每道 ${SPRAY_S.toFixed(1)} s（單孔 ${SPRAY_SINGLE_S.toFixed(0)} s）。`;
const VIEW_OF = { inbound: 'inbound', agv: 'storage', gantry: 'gantry', label: 'label', upender: 'upender', decap: 'decap', robot: 'robot', waste: 'waste' };
for (const s of STATIONS) {
  const b = document.createElement('button'); b.className = 'st'; b.dataset.st = s.id; b.innerHTML = `<span class="idx">${s.short}</span>${s.name}`;
  b.onclick = () => { player.seekTo(seq.stationStart[s.id]); setView(VIEW_OF[s.id]); }; ui.stations.appendChild(b);
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

ui.showDims.onchange = () => { building.dims.visible = ui.showDims.checked; };
ui.showFence.onchange = () => { line.fences.visible = ui.showFence.checked; };
ui.showCeiling.onchange = () => { building.ceiling.visible = ui.showCeiling.checked; };
$('cutaway').onchange = e => {
  for (const m of [MAT.pp, MAT.tankW]) { m.transparent = e.target.checked; m.opacity = e.target.checked ? .2 : 1; m.depthWrite = !e.target.checked; m.needsUpdate = true; }
};
ui.xray.onchange = () => drums.forEach(d => d.setXray(ui.xray.checked));
// 面板操作後重繪一格（勾選類操作可能改變陰影）
for (const type of ['input', 'change', 'click', 'keydown']) $('app').addEventListener(type, () => stage.invalidate(type === 'change'));

// ---------------------------------------------------------------- 相機子畫面與焦點追隨（viewer-workspace）
// 焦點目標由頂列「焦點」選單決定；◎（追隨焦點）跟著它移動。目標離線時保持視角不動。
const FAR = 6000, FOCUS_OFFSET = new THREE.Vector3(-2200, 1800, 2400);
let startOffset = FOCUS_OFFSET.clone();
// 對準時的鏡頭偏移：離目標遠時拉近到預設偏移，已在附近則保留目前的觀看方向與距離
function focusOffsetFor(key, p) {
  const current = camera.position.clone().sub(controls.target);
  if (!p || camera.position.distanceTo(controls.target) <= FAR) return current;
  return key === 'gripper' ? gripperOffset() : FOCUS_OFFSET.clone();
}
function markFocusView() {
  stage.goTo(camera.position.toArray(), controls.target.toArray(), true);   // 中止進行中的視角轉場
  selectedView = 'focus';
  document.querySelectorAll('.views button[data-view]').forEach(b => b.classList.remove('selected'));
}
const workspace = createViewerWorkspace({
  camera, controls, canvas, resize: stage.resize, focusNear: 100,
  getFocus: () => focusPosition(ui.focusTarget.value) ?? controls.target.clone(),
  // viewer-workspace 以固定陣列讀取偏移；這裡用可迭代物件交出開始追隨當下算好的偏移（見 onFocus）
  focusOffset: { *[Symbol.iterator]() { yield* startOffset.toArray(); } },
  onFocus() { startOffset = focusOffsetFor(ui.focusTarget.value, focusPosition(ui.focusTarget.value)); markFocusView(); },
});
const followButton = $('followProduct');   // viewer-workspace 工具列的 ◎
// 單次對準：追隨中則以新目標重新開始追隨
function focusOnce() {
  if (workspace.following) { workspace.stopFollowing(); followButton.click(); return; }
  const key = ui.focusTarget.value, p = focusPosition(key);
  markFocusView(); if (!p) return;
  stage.goTo(p.clone().add(focusOffsetFor(key, p)).toArray(), p.toArray(), true);
}
$('focusNow').onclick = focusOnce;
ui.focusTarget.onchange = () => workspace.follow();
function startFollow(key = ui.focusTarget.value) { ui.focusTarget.value = key; if (workspace.following) workspace.stopFollowing(); followButton.click(); }

// 子畫面來源：自動（依最近一次取像事件切換貼標／桶口相機）、指定相機或清洗夾具
const vision = createVisionOverlay(), gripperCam = new THREE.PerspectiveCamera(42, 1.5, 30, 25000);
const ROI = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
// 模擬檢測標記：畫面內各桶的 2" 與 3/4" 桶塞位置（取像後 4 秒內標示定位結果）
function bungMarks(fresh) {
  const out = [];
  drums.forEach((d, k) => {
    if (!d.root.visible) return;
    const s = S.st[DRUM_KEYS[k]];
    for (const [kind, name, closed, r] of [['big', '2"', s.capBig, 45], ['small', '3/4"', s.capSmall, 30]]) {
      const c = d.bungWorld(kind);
      out.push({ points: ROI.map(([a, b]) => c.clone().add(new THREE.Vector3(a * r, 0, b * r))), status: fresh ? 'ok' : 'preview', label: fresh ? `${name} ${closed ? '桶塞定位' : '桶口已開'}` : '' });
    }
  });
  return out;
}
function renderPip() {
  const T = player.T, source = ui.pipSource.value, gripper = source === 'gripper';
  const shot = shots.filter(s => s.start <= T).at(-1);
  const sensor = gripper ? gripperCam : source === 'decap' ? line.decapCam : source === 'label' ? line.labelCam : shot?.cam || line.labelCam;
  if (gripper) { const target = focusPosition('gripper'); gripperCam.position.copy(target).add(gripperOffset()); gripperCam.lookAt(target); }
  const fresh = !gripper && !!shot && shot.cam === sensor && T - shot.start < 4;
  const name = gripper ? '清洗夾具' : sensor === line.decapCam ? '桶口相機' : '貼標相機';
  const fenceVisible = line.fences.visible; line.fences.visible = false;
  renderer.setScissorTest(false); renderer.setViewport(0, 0, canvas.clientWidth, canvas.clientHeight);
  workspace.renderCamera({
    renderer, scene, camera: sensor, vision, aspect: 1.5, title: `${name} · 即時視野`,
    result: gripper ? `夾爪閉合 ${(S.st.grip.jaw * 100).toFixed(0)}% · 防脫扣隨爪同步開合` : fresh ? shot.result : '即時畫面 · 等待檢測觸發（模擬訊號）',
    marks: { title: name, state: gripper ? '即時' : fresh ? '取像' : '預覽', time: T, marks: gripper ? [] : bungMarks(fresh) },
  });
  line.fences.visible = fenceVisible;
}

// ---------------------------------------------------------------- 播放列（core/ui/player.js）
player = createPlayer({
  total, speeds: [.25, 8], apply: applyState, onChange: () => workspace.follow(),
  events: seq.events.map(e => { const st = STATIONS.find(s => s.id === e.station); return { time: e.time, label: `${st.short} ${st.name} · ${e.label}` }; }),
});
const seekTo = t => player.seekTo(t);

// ---------------------------------------------------------------- 視角
const VIEWS = {
  iso: [[-3500, 14500, 24000], [5600, 0, 8200]], top: [[5040, 28000, 7790], [5040, 0, 7760]],
  storage: [[2300, 4300, 8600], [6300, 1500, 3800]], gantry: [[1200, 4300, 13800], [4700, 1100, 9700]],
  label: [[6300, 2600, 7600], [7550, 850, 9750]], upender: [[8400, 3600, 7400], [10900, 1000, 10100]],
  decap: [[9700, 3300, 8900], [11290, 1350, 11000]], robot: [[6200, 5600, 10200], [9900, 1100, 13400]],
  booth: [[7600, 2800, 12000], [9400, 1350, 14700]], waste: [[1500, 4300, 11600], [5000, 800, 14600]],
  inbound: [[-900, 3900, 7400], [2300, 900, 2900]], weigh: [[10150, 1500, 12650], [11292, 650, 13400]],
};
const highlightView = name => document.querySelectorAll('.views button[data-view]').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
function setView(name, instant = false) {
  if (!VIEWS[name] && name !== 'follow' && name !== 'gripper') return;
  workspace.stopFollowing();
  if (name === 'follow') {   // 跟隨 #1：先放到第 1 桶斜上方，再交給焦點追隨
    const p = focusPosition('drum0');
    if (p) stage.goTo(p.clone().add(new THREE.Vector3(-2600, 2200, 2600)).toArray(), p.toArray(), true);
    startFollow('drum0');
  } else if (name === 'gripper') {
    const t = focusPosition('gripper');
    stage.goTo(t.clone().add(gripperOffset()).toArray(), t.toArray(), instant);
  } else stage.goTo(...VIEWS[name], instant);
  selectedView = name; highlightView(name);
}
document.querySelectorAll('.views button[data-view]').forEach(b => b.onclick = () => setView(b.dataset.view));
// 手動轉動視角時中止視角轉場
controls.addEventListener('start', () => stage.goTo(camera.position.toArray(), controls.target.toArray(), true));

// ---------------------------------------------------------------- 3D 標籤（stage.addLabel；位置函式回傳 null 時隱藏）
const P = (x, y, z) => { const v = new THREE.Vector3(x, y, z); return () => v; };
const showLabel = pos => () => ui.showLabels.checked ? pos() : null;
const label = (html, pos) => stage.addLabel(html, showLabel(pos));
label('<b>倉儲</b> 穿梭車密集架 212 桶', P(6000, 4000, 2700));
label('<b>AGV</b> 平衡重式堆高', () => agv.root.position.clone().add(new THREE.Vector3(0, 2500, 0)));
label('<b>S2</b> 棧板站＋龍門翻轉夾爪', P(4800, 3600, 9050));
label('<b>S3</b> 貼標＋讀碼', P(LABEL.x, 2350, LYING.z + 500));
label('<b>S4</b> 90° 翻桶機', P(10500, 1700, 9500));
label('<b>S5</b> 自動開蓋站', P(UPRIGHT.x, 2900, DECAP.z));
label('<b>S6</b> FANUC R-2000iC/165F', P(ROBOT.x, 2700, ROBOT.z - 300));
label('<b>S6</b> 沖洗站', P(9500, 2950, BOOTH.z0 + 200));
label('<b>S7</b> 廢液回收', P(5700, 2500, 14300));
label('<b>S0</b> 散桶入庫（捲門＋懸臂吊）', P(1500, 3500, INBOUND.z));
label('裝填區（下一站）', P(11400, 1500, 14700));
label('結構柱', P(COLUMN.x, 2600, COLUMN.z));
for (const d of building.dimLabels) stage.addLabel(d.text, () => ui.showDims.checked ? d.pos : null, 'dim');
// stage 以畫布左上角為原點擺放標籤；畫布在頂列下方，標籤層對齊畫布位置
let labelOrigin = '';
function placeLabels() {
  const origin = `${canvas.offsetLeft}px ${canvas.offsetTop}px`;
  if (origin !== labelOrigin) { labelOrigin = origin; $('app').style.setProperty('--canvas-left', canvas.offsetLeft + 'px'); $('app').style.setProperty('--canvas-top', canvas.offsetTop + 'px'); }
  stage.updateLabels(true);
}

// ---------------------------------------------------------------- 面板更新
function drawHud() {
  const T = player.T, st = S.st, act = seq.activity(T);
  ui.phase.textContent = T >= total - 2 ? 'COMPLETE · 本棧板 4 桶完成' : player.playing ? `AUTO · 執行中 ${+ui.speed.value}×` : 'HOLD · 暫停';
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
  const focusName = ui.focusTarget.selectedOptions[0].textContent, present = !!focusPosition(ui.focusTarget.value);
  ui.focusStatus.textContent = workspace.following ? (present ? '追蹤中 · ' + focusName : '目標已離開產線') : selectedView === 'focus' ? (present ? '焦點 · ' + focusName : '目標已離開產線') : '自由視角';
  $('diagnostics').textContent = JSON.stringify({ T, total, playing: player.playing, view: selectedView, following: workspace.following, agv: st.agv, gantry: st.gantry, drums: DRUM_IDS.map((_, k) => st['drum' + k].state), robot: S.robot.err || null });
}

// ---------------------------------------------------------------- 繪製（stage.loop 只在有變化時呼叫）
function draw() {
  washing.tick(player.T);
  workspace.follow();
  drawHud(); placeLabels();
  renderPip();
  workspace.renderOverview(renderer, scene);
}

setView(qp.get('view') || 'iso', true);
if (qp.has('dims')) { ui.showDims.checked = true; building.dims.visible = true; }
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6) stage.goTo(a.slice(0, 3), a.slice(3), true); }
$('loading').classList.add('hide');
stage.loop(dt => player.update(dt), { render: draw });

// 焦點與相機視窗的相容介面（舊版 view-controls 的成員，給 tools/review-camera.mjs 與除錯用）
const pipFrame = $('pipFrame');
const focus = {
  get enabled() { return workspace.following; }, get target() { return ui.focusTarget.value; },
  start: startFollow, stop: () => workspace.stopFollowing(), snap: () => workspace.follow(), update: () => workspace.follow(), once: focusOnce,
};
const cameraWindow = {
  layout: () => dispatchEvent(new Event('resize')),
  get state() { const r = pipFrame.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, expanded: pipFrame.classList.contains('expanded'), visible: !pipFrame.hidden }; },
  get viewport() { return $('pipImage').getBoundingClientRect(); },
  get source() { return ui.pipSource.value; },
  get visible() { return !pipFrame.hidden; },
};
exposeSim({
  seekTo, setView, views: Object.keys(VIEWS), play: () => player.play(), pause: () => player.pause(),
  get T() { return player.T; }, seq, get state() { return S; }, robot, total, focus, cameraWindow, camera, controls, focusPosition, player, workspace, stage,
});
