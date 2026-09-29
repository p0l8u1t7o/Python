// 主程式：場景、時間軸、UI、取像模擬子畫面
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { SPECS, SCENARIOS, TRAYS, DEMO, X1, X2, Y0, YA, YM, YS, YT, DIR_A, occupied, measurement, inTol } from './spec.js';
import { createSequence, smooth, STATIONS } from './sequence.js';
import { createMachine } from './machine.js';
import { createCameraSim, TITLES } from './camera-sim.js';
import { surfaceTexture, overviewFrame } from './render-finishes.js';

const qp = new URLSearchParams(location.search);
const compactViewport=matchMedia('(max-width:900px), (max-height:520px)').matches;
document.body.classList.toggle('info-hidden',compactViewport);
const specId = SPECS[qp.get('spec')] ? qp.get('spec') : 'B', scenarioId = SCENARIOS[qp.get('result')] ? qp.get('result') : 'OK';
const s = SPECS[specId], sc = SCENARIOS[scenarioId], m = measurement(s, scenarioId);

// ---------------------------------------------------------------- 場景
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance', logarithmicDepthBuffer: true, preserveDrawingBuffer: qp.has('shot') });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = .94; renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x202a34);
scene.fog = new THREE.Fog(0x202a34, 4500, 16000);
const pmrem = new THREE.PMREMGenerator(renderer), room = new RoomEnvironment(renderer);
scene.environment = pmrem.fromScene(room, 0.04).texture; room.dispose(); pmrem.dispose();
const camera = new THREE.PerspectiveCamera(38, 1, 2, 20000), controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.minDistance = 8; controls.maxDistance = 6000;
scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x2a2f36, 0.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(-900, 2600, 1400); sun.target.position.set(0, 900, 0);
sun.castShadow = renderer.shadowMap.enabled; sun.shadow.mapSize.set(2048, 2048); Object.assign(sun.shadow.camera, { left: -700, right: 700, top: 700, bottom: -700, near: 300, far: 5000 }); sun.shadow.bias = -0.0001; sun.shadow.normalBias = 0.4;
scene.add(sun, sun.target);
const fill = new THREE.DirectionalLight(0x9fb8ff, 0.5); fill.position.set(1200, 1500, -1500); scene.add(fill);
sun.shadow.mapSize.set(innerWidth > 900 ? 4096 : 2048, innerWidth > 900 ? 4096 : 2048);
const rim = new THREE.DirectionalLight(0xffead2, .65); rim.position.set(700, 2100, -500); scene.add(rim);
const floorFinish = surfaceTexture('powder').clone(); floorFinish.repeat.set(240, 240); floorFinish.needsUpdate = true;
const floor = new THREE.Mesh(new THREE.PlaneGeometry(100000, 100000), new THREE.MeshStandardMaterial({ color: 0x29323a, roughness: .86, roughnessMap: floorFinish, metalness: 0 })); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
const grid = new THREE.GridHelper(6000, 60, 0x2a3644, 0x1c2530); grid.position.y = 0.5; scene.add(grid);
grid.visible = qp.has('grid');

const machine = createMachine(scene, s);
const pipCanvas = document.getElementById('pipImage'), sim = createCameraSim(pipCanvas, s, m, scenarioId);
const ids = ['action', 'substep', 'zoneDot', 'zoneTxt', 'checklist', 'chkCount', 'playBtn', 'restartBtn', 'speed', 'speedVal', 'loop', 'progBar', 'clock', 'timeline', 'stepSelect', 'previous', 'next', 'signals', 'poseError', 'phase', 'result', 'specSel', 'exportBtn', 'showGuards', 'showLabels', 'showBeams', 'showPip', 'cycleTime', 'pipFrame', 'pipTitle', 'stations', 'meas', 'verdict', 'trayMap', 'trayNote', 'specName', 'specNote', 'detailNote'];
const ui = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
for (const v of Object.values(SPECS)) ui.specSel.add(new Option(v.name, v.id));
for (const v of Object.values(SCENARIOS)) ui.result.add(new Option('情境：' + v.name, v.id));
ui.specSel.value = specId; ui.result.value = scenarioId;
const reload = (k, v) => { const q = new URLSearchParams(location.search); q.set(k, v); ['step', 'st', 'time'].forEach(x => q.delete(x)); location.search = q.toString(); };
ui.specSel.onchange = () => reload('spec', ui.specSel.value); ui.result.onchange = () => reload('result', ui.result.value);
ui.specName.textContent = `${s.name} · 配方 ${s.recipe}`; ui.specNote.textContent = `${s.note}。工件採圖面尺寸、設備為規劃包絡；量測值、缺陷與節拍為模擬示意，待樣品與 POC 校正。`;

// 3D 標籤
const V = (x, y, z) => new THREE.Vector3(x, y, z), labels = [];
function addLabel(text, pos) { const el = document.createElement('div'); el.className = 'label3d'; el.innerHTML = text; document.getElementById('app').appendChild(el); labels.push({ el, pos }); }
addLabel('<b>A</b> 4K 線掃＋1.5× 遠心', V(X1 + DIR_A[0] * 150, YA + 30, DIR_A[2] * 150));
addLabel('<b>B</b> 0.5× 雙遠心鏡頭', V(X1 - 150, YA + 28, 0)); addLabel('<b>B</b> 遠心平行背光', V(X1 + 80, YA + 24, 0));
addLabel('<b>C</b> 口部端面（經中空軸）', V(X1, YM + 250, 0)); addLabel('DD 中空軸馬達＋三爪 PEEK 夾頭', V(X1, YM + 78, 40));
addLabel('RGB 三角度線光源', V(X1 - 20, YA + 22, 48)); addLabel('移載：X 軸＋Z 軸＋貼靠氣缸＋側向真空吸嘴', V(-60, Y0 + 210, -160));
addLabel(`上共焦 ${s.upper}`, V(X2, YS + s.wd + 90, 0)); addLabel('下共焦 CL-S015（參考距離 15 mm）', V(X2, Y0 + 50, 80));
addLabel(`空心軸 θ 平台＋${s.ring} 薄環座`, V(X2 - 40, YS + 8, 40)); addLabel('C 型架（R 軸微動台）', V(300, Y0 + 370, 0));
addLabel('入料托盤', V(TRAYS.IN.cx, YT + 25, 40)); addLabel('OK', V(TRAYS.OK.cx, YT + 25, 40)); addLabel('NG1', V(TRAYS.NG1.cx, YT + 25, 40)); addLabel('NG2', V(TRAYS.NG2.cx, YT + 25, 40));
addLabel('花崗岩平台 620 × 430 × 42', V(-200, Y0 + 6, 205));

STATIONS.forEach((name, i) => { const b = document.createElement('button'); b.className = 'st'; b.dataset.st = i; b.innerHTML = `<span class="idx">S${i}</span>${name}`; ui.stations.appendChild(b); });

// ---------------------------------------------------------------- 時間軸
let S, current, playing = !qp.has('pause'), T = 0, speed = +(qp.get('speed') || 0.5), curStation = -1, curStep = -1;
const sequence = createSequence({ spec: specId, scenario: scenarioId, apply: x => { S = x; machine.apply(x); } });
const total = sequence.total; ui.timeline.max = total; ui.speed.value = speed; ui.speedVal.textContent = speed.toFixed(2).replace(/0$/, '') + '×';
ui.cycleTime.textContent = `規劃 ${total.toFixed(1)} s／件 ≈ ${Math.round(3600 / total)} UPH（單件流）`;
sequence.steps.forEach((x, i) => ui.stepSelect.add(new Option(`S${x.station} · ${x.action}`, i)));
const has = id => c => c.has(id);
const checklist = [
  [['入料第 ' + (DEMO.k + 1) + ' 穴吸附取料', has('grab:in')]],
  [['三爪夾持（限力 2 N）', has('clamp')], ['交接：先夾持再破真空', has('handoff1')], ['通道 A 外壁 360° 展開', has('scanA')], ['通道 B 剪影 4 × 90°', has('shotB3')], ['通道 C 口部端面', has('shotC')], ['交接：先吸附再鬆夾', has('unclamp')]],
  [['落座薄環座', has('seat')]],
  [['螺旋掃描（上下共焦同步）', has('spiral0')], ...(scenarioId === 'ERR' ? [['有效點不足 → ERR', has('err0')], ['重新落座', has('reseat')], ['重測一次', has('spiral1')]] : [])],
  [['判定＋資料寫入', has('judge')], [sc.out === 'IN' ? '退回入料原穴（人工處理）' : `放入 ${sc.out} 托盤`, has('out')], ['移載回待命位', has('home')]],
];

// 視角
const views = {
  iso: () => overviewFrame(machine.root, camera), top: () => [[0, 2050, 1], [0, 900, 0]],
  st1: () => [[X1 - 105, YA + 60, -150], [X1 + 5, YA - 2, 5]], chuck: () => [[X1 - 38, YM + 6, -40], [X1, YM - s.len / 2, 0]],
  st2: () => [[X2 - 110, YS + 170, 300], [X2 + 10, YS + 25, 0]], seat: () => [[X2 - 40, YS + 26, -46], [X2, YS + s.len / 2, 0]],
  trays: () => [[-240, YT + 190, 260], [-160, YT, 0]],
  electrical: () => [[0, 470, 1230], [0, 430, -135]],
  xray: () => [[860, 910, 1330], [0, 470, -70]],
  wiring: () => [[-1000, 1460, -1280], [0, 1010, 0]],
  carriers: () => [[-420, 1240, -710], [-40, 1030, -175]],
  fibers: () => [[130, 1270, 530], [270, 1135, 65]],
  part: () => { const p = machine.partWorld(); return [p.clone().add(V(-26, 16, -34)).toArray(), p.toArray()]; },
};
const NEAR = { chuck: 0.5, seat: 0.5, part: 0.5 };
let selectedView = 'iso', camAnim = null; const lastPart = V(0, 0, 0);
function setView(name, instant = false) {
  if (!views[name]) return; selectedView = name; camera.near = NEAR[name] || 4; camera.updateProjectionMatrix();
  machine.details.setMode(name === 'electrical' ? 'cutaway' : name === 'xray' ? 'xray' : 'shell');
  const [p, t] = views[name]().map(a => V(...a));
  if (instant) { camAnim = null; camera.position.copy(p); controls.target.copy(t); controls.update(); } else camAnim = { p0: camera.position.clone(), t0: controls.target.clone(), p, t, u: 0 };
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
  ui.detailNote.hidden = !['chuck', 'seat', 'part', 'electrical', 'xray', 'wiring', 'carriers', 'fibers'].includes(name);
  ui.detailNote.textContent = { chuck: `夾頭特寫 · 夾持帶只在杯口 1.5 mm\n吸嘴由後方爪間空隙伸入，貼靠中心距底面 1.8 mm`, seat: `環座特寫 · ${s.ring} 內孔 Ø${s.ringBore}\n下感測器由空心軸內向上量外底面，上感測器穿過杯口量內底面`, part: `工件跟拍 · Ø${s.od} × ${s.len} mm，實際尺寸` }[name] || '';
  if (['electrical', 'xray'].includes(name)) ui.detailNote.textContent = '電控配置規劃 · CL-3000＋兩組 CL-S015N 光學模組\n8 軸驅動／24 V 控制／獨立視覺網路；外形為安裝包絡，非原廠 CAD';
  if (name === 'wiring') ui.detailNote.textContent = '整線配置 · 固定線槽／移動服務環／桌板穿線護口\n動力與量測訊號分路；光纖彎曲半徑及拖鏈適用性待原廠核定';
  if (name === 'carriers') ui.detailNote.textContent = 'X 拖鏈 650 mm／R35 · Z 拖鏈 180 mm／R22\n固定長度折返，兩端固定於軸座；氣管另行管理';
  if (name === 'fibers') ui.detailNote.textContent = '共焦光纖 · 上頭升降環 R27.5／R 軸補償環 R40\n曲率為配置預留，原廠動態彎曲與壽命尚待確認';
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));
const setPlaying = v => { playing = v; ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放'; };
function seekTo(sec) { T = Number.isFinite(sec) ? THREE.MathUtils.clamp(sec, 0, total) : 0; current = sequence.sample(T); render(); }
ui.playBtn.onclick = () => { if (T >= total) seekTo(0); setPlaying(!playing); };
ui.restartBtn.onclick = () => { seekTo(0); setPlaying(true); };
ui.previous.onclick = () => { setPlaying(false); seekTo(sequence.steps[Math.max(0, current.index - 1)].start); };
ui.next.onclick = () => { setPlaying(false); seekTo(sequence.steps[Math.min(sequence.steps.length - 1, current.index + 1)].start); };
ui.stepSelect.onchange = () => { setPlaying(false); seekTo(sequence.steps[+ui.stepSelect.value].start); };
ui.timeline.oninput = () => { setPlaying(false); seekTo(+ui.timeline.value); };
ui.speed.oninput = () => { speed = +ui.speed.value; ui.speedVal.textContent = speed.toFixed(2).replace(/0$/, '') + '×'; };
// 站別按鈕停在該站最有代表性的一刻
const PREVIEW = [['grab:in', 0], ['scanA', -0.5], ['seat', 0], ['spiral0', -1.2], ['judge', 0]];
const previewTime = i => { const [id, off] = PREVIEW[i], x = sequence.steps.find(y => y.done === id); return x.start + x.dur + off; };
ui.stations.querySelectorAll('.st').forEach(b => b.onclick = () => { setPlaying(false); seekTo(previewTime(+b.dataset.st)); setView(['trays', 'st1', 'st2', 'st2', 'trays'][+b.dataset.st]); });

// 量測表：取像完成後才顯示數值
const c = s.criteria, f3 = v => v.toFixed(3), rng = ([a, b]) => `${a}–${b}`;
const rows = [
  ['外觀缺陷', '0 處', 'scanA', () => m.defects.length ? `${m.defects[0].type} ${m.defects[0].len}` : '0 處', () => !m.defects.length],
  ['外徑 OD', rng(c.od), 'shotB3', () => f3(Math.max(...m.od)), () => m.od.every(v => inTol(v, c.od))],
  ['全長 L', rng(c.length), 'shotB3', () => f3(m.length), () => inTol(m.length, c.length)],
  ...(c.flare ? [['口部喇叭', `≤ ${c.flare}°`, 'shotB3', () => m.flare.toFixed(1) + '°', () => m.flare <= c.flare]] : []),
  ['口部內徑', rng(c.idLip), 'shotC', () => f3(m.idLip), () => inTol(m.idLip, c.idLip)],
  ['口部壁厚', rng(c.wallLip), 'shotC', () => f3(m.wallLip), () => inTol(m.wallLip, c.wallLip)],
  ['底厚平均', rng(c.thk), 'spiral0', () => m.thkMean === null ? '無效' : f3(m.thkMean), () => m.thkMean === null ? null : inTol(m.thkMean, c.thk)],
  ['底厚 TIR', `≤ ${c.tir}`, 'spiral0', () => m.thkTir === null ? '無效' : f3(m.thkTir), () => m.thkTir === null ? null : m.thkTir <= c.tir],
];
rows.forEach(r => { const tr = ui.meas.insertRow(); for (let i = 0; i < 4; i++) tr.insertCell(); tr.cells[0].textContent = r[0]; tr.cells[1].textContent = r[1]; r.el = tr; });
// 托盤圖
const trayEls = {};
for (const id of Object.keys(TRAYS)) { const t = TRAYS[id], wrap = document.createElement('div'), g = document.createElement('div'); g.className = 't'; g.style.gridTemplateColumns = `repeat(${t.cols},1fr)`; const cells = []; for (let i = 0; i < t.cols * t.rows; i++) { const d = document.createElement('i'); g.appendChild(d); cells.push(d); } wrap.appendChild(g); const n = document.createElement('div'); n.className = 'n'; n.textContent = id === 'IN' ? '入料' : id; wrap.appendChild(n); ui.trayMap.appendChild(wrap); trayEls[id] = cells; }
ui.trayNote.textContent = '吸嘴由後方伸入，手臂側的列保持淨空';
// 托盤圖上方是機台後側；入料由最後一列取起、出料由最前一列放起
const cellIndex = (id, i) => { const t = TRAYS[id], row = Math.floor(i / t.cols), col = i % t.cols; return (t.order === 'rear' ? row : t.rows - 1 - row) * t.cols + col; };

const signals = [['安全門關閉', () => true], ['入料列就位', () => true], ['吸嘴真空', () => !!S.vac], ['夾頭夾緊', () => S.jaw < 0.01], ['θ1 原點', () => Math.abs(Math.sin(S.th1 / 2)) < 1e-3], ['吸嘴避讓', () => S.zt <= YT + 16.01 && S.a > 5.9],
  ['ST2 有料', () => S.loc === 'seat'], ['共焦訊號正常', () => !(scenarioId === 'ERR' && S.optic === 'CF' && S.spiral[S.scanNo] > 0.2)]];
signals.forEach(([name]) => { const row = document.createElement('div'); row.innerHTML = `<i></i><span>${name}</span>`; ui.signals.appendChild(row); });

function exportReport() {
  const done = current.completed, report = {
    mode: 'SIMULATION', serial: `SIM-${specId}-${String(DEMO.k + 1).padStart(4, '0')}`, recipe: s.recipe, spec: specId, scenario: scenarioId, time: +T.toFixed(2), plannedCycle: +total.toFixed(2),
    result: done.has('judge') ? m.result : 'PENDING', ngCode: done.has('judge') ? m.code : '', route: done.has('out') ? S.loc : 'PENDING',
    dimension: done.has('shotC') ? { od: m.od, length: m.length, idLip: m.idLip, wallLip: +m.wallLip.toFixed(4), flareDeg: m.flare, straightness: m.straightness } : null,
    baseThickness: done.has('spiral0') ? { mean: m.thkMean, min: m.thkMin, max: m.thkMax, tir: m.thkTir, flatness: m.flatness, validPts: m.valid, invalidPts: m.invalid, retest: m.retest && done.has('spiral1') } : null,
    defects: done.has('scanA') ? m.defects : null, versions: { algorithm: 'sim', model: 'shell-defect-v1.3', jigRing: s.ring },
    exposureEvents: sequence.steps.filter(x => x.exposure && x.start + x.dur <= T + 1e-9).map(x => ({ action: x.action, channel: x.exposure, plannedTime: +x.start.toFixed(2) })),
    physicalMeasurement: false, mesConnected: false,
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })), a = document.createElement('a');
  a.href = url; a.download = `CUP-${specId}-${scenarioId}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
ui.exportBtn.onclick = exportReport;
ui.showBeams.onchange = () => seekTo(T);

function drawHud() {
  const done = current.completed, judged = done.has('judge'), cls = m.result === 'OK' ? 'ok' : m.result === 'ERR' ? 'err' : 'ng';
  ui.action.textContent = S.action; ui.substep.textContent = S.sub;
  ui.phase.textContent = T >= total ? 'COMPLETE · 本件完成' : playing ? 'AUTO · 執行中' : 'HOLD · 暫停';
  ui.zoneTxt.textContent = S.zone === 'contact' ? '接觸／交接 · 限力' : S.zone === 'slow' ? '減速接近' : '自由移動 / 工位保持'; ui.zoneDot.className = 'dot ' + (S.zone === 'contact' ? 'contact' : S.zone === 'slow' ? 'slow' : '');
  ui.poseError.textContent = `X ${S.tx.toFixed(1)}　Z ${(S.zt - Y0).toFixed(1)}　貼靠 ${(6 - S.a).toFixed(1)}　θ1 ${(S.th1 * 57.2958 % 360).toFixed(0)}°　θ2 ${(S.th2 * 57.2958 % 360).toFixed(0)}°　R ${S.r2.toFixed(2)} mm`;
  [...ui.signals.children].forEach((el, i) => el.classList.toggle('on', !!signals[i][1]()));
  for (const r of rows) { const ready = done.has(scenarioId === 'ERR' && r[2] === 'spiral0' ? 'spiral0' : r[2]), good = ready ? r[4]() : undefined; r.el.className = !ready ? 'pending' : good === null ? 'err' : good ? 'ok' : 'ng'; r.el.cells[2].textContent = ready ? r[3]() : '—'; r.el.cells[3].textContent = !ready ? '' : good === null ? '!' : good ? '✓' : '✗'; }
  ui.verdict.className = 'verdict ' + (judged ? cls : ''); ui.verdict.textContent = judged ? `${m.result}${m.code ? ' · ' + m.code : ' · 全部項目在規格內'}` : done.has('err0') ? 'ERR · 重測中' : '量測中…';
  for (const id of Object.keys(TRAYS)) { const occ = new Set(occupied(id, S)); trayEls[id].forEach(e => e.className = ''); for (const i of occ) trayEls[id][cellIndex(id, i)].className = 'full'; }
  if (S.loc === 'in' || S.loc === 'noz' && !done.has('clamp')) trayEls.IN[cellIndex('IN', DEMO.k)].className = 'cur';
  if (S.loc === 'back') trayEls.IN[cellIndex('IN', DEMO.k)].className = 'err';
  if (String(S.loc).startsWith('out:')) trayEls[sc.out][cellIndex(sc.out, DEMO.filled[sc.out])].className = cls;
  machine.setTower(judged && m.result !== 'OK' ? sc.tower : done.has('err0') ? 'yellow' : playing || T >= total ? 'green' : 'yellow');
  machine.hood.visible = ui.showGuards.checked;
  if (curStep !== current.index || judged !== drawHud.judged) { curStep = current.index; drawHud.judged = judged; machine.drawScreen([`${s.recipe}　${STATIONS[S.station]}`, judged ? `判定 ${m.result}` : '量測中', S.action, `節拍 ${total.toFixed(1)} s ≈ ${Math.round(3600 / total)} UPH`, `治具 ${s.ring}　模型 v1.3`, '模擬畫面 · 未接實機'], judged ? { ok: '#7fe0b4', ng: '#ff8d80', err: '#ffc857' }[cls] : '#7fe0b4'); }
  if (curStation !== S.station) { curStation = S.station; ui.checklist.innerHTML = ''; checklist[curStation].forEach(([txt]) => { const li = document.createElement('li'); li.innerHTML = `<span class="box"></span><span>${txt}</span>`; ui.checklist.appendChild(li); }); }
  let n = 0; [...ui.checklist.children].forEach((li, i) => { const d = checklist[S.station][i][1](done); li.classList.toggle('done', d); li.querySelector('.box').textContent = d ? '✓' : ''; if (d) n++; });
  ui.chkCount.textContent = n + ' / ' + checklist[S.station].length;
  ui.stations.querySelectorAll('.st').forEach(b => { const i = +b.dataset.st; b.classList.toggle('active', i === S.station); b.classList.toggle('done', i < S.station || T >= total); });
  ui.timeline.value = T; ui.stepSelect.value = current.index; ui.progBar.style.width = T / total * 100 + '%';
  ui.clock.textContent = `${Math.floor(T / 60).toString().padStart(2, '0')}:${(T % 60).toFixed(2).padStart(5, '0')}`;
  ui.pipFrame.hidden = !ui.showPip.checked; if (ui.showPip.checked) { ui.pipTitle.textContent = TITLES[sim.draw(S, done)] + '（模擬）'; ui.pipFrame.classList.toggle('flash', !!S.flash); }
  if (!ui.showBeams.checked) machine.root.traverse(o => { if (o.material && o.material.blending === THREE.AdditiveBlending) o.visible = false; });
  for (const l of labels) { const p = l.pos.clone().project(camera), vis = ui.showLabels.checked && p.z < 1 && Math.abs(p.x) < 0.98 && Math.abs(p.y) < 0.95; l.el.style.display = vis ? 'block' : 'none'; if (vis) { l.el.style.left = canvas.offsetLeft + (p.x * 0.5 + 0.5) * canvas.clientWidth + 'px'; l.el.style.top = canvas.offsetTop + (-p.y * 0.5 + 0.5) * canvas.clientHeight + 'px'; } }
  document.getElementById('diagnostics').textContent = JSON.stringify({ time: T, total, step: current.index, station: S.station, action: S.action, loc: S.loc, optic: S.optic, pip: S.pip, playing, spec: specId, scenario: scenarioId });
}
function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); if (selectedView === 'iso') setView('iso', true); }
const infoToggle=document.getElementById('infoToggle');
infoToggle.setAttribute('aria-expanded',String(!document.body.classList.contains('info-hidden')));
infoToggle.onclick=()=>{document.body.classList.toggle('info-hidden');infoToggle.setAttribute('aria-expanded',String(!document.body.classList.contains('info-hidden')));resize();};
window.addEventListener('resize', resize);
function render() { drawHud(); renderer.render(scene, camera); }
const clock = new THREE.Clock();
function frame() {
  requestAnimationFrame(frame); const dt = Math.min(clock.getDelta(), 0.05);
  if (playing) { T = Math.min(total, T + dt * speed); current = sequence.sample(T); if (T >= total) { if (ui.loop.checked) T = 0; else setPlaying(false); } }
  const p = machine.partWorld();
  if (selectedView === 'part') { const d = p.clone().sub(lastPart); camera.position.add(d); controls.target.add(d); if (camAnim) for (const k of ['p0', 't0', 'p', 't']) camAnim[k].add(d); }
  lastPart.copy(p);
  if (camAnim) { camAnim.u = Math.min(1, camAnim.u + dt * 1.4); camera.position.lerpVectors(camAnim.p0, camAnim.p, smooth(camAnim.u)); controls.target.lerpVectors(camAnim.t0, camAnim.t, smooth(camAnim.u)); if (camAnim.u === 1) camAnim = null; }
  controls.update(); render();
}
current = sequence.sample(0); lastPart.copy(machine.partWorld()); resize(); setView('iso', true); setPlaying(playing);
window.sim = { seekTo, pause: () => setPlaying(false), play: () => setPlaying(true), setView, get state() { return S; }, total, steps: sequence.steps, stationStart: sequence.stationStart, spec: s, scenario: sc, measurement: m };
if (qp.has('st')) { setPlaying(false); seekTo(previewTime(THREE.MathUtils.clamp(+qp.get('st') || 0, 0, STATIONS.length - 1))); }
if (qp.has('step')) { setPlaying(false); seekTo(sequence.steps[THREE.MathUtils.clamp(+qp.get('step') || 0, 0, sequence.steps.length - 1)].start + (+qp.get('t') || 0)); }
if (qp.has('time')) { setPlaying(false); seekTo(+qp.get('time')); }
if (qp.has('view')) { lastPart.copy(machine.partWorld()); setView(qp.get('view'), true); }
if (qp.has('labels')) ui.showLabels.checked = true;
if (qp.get('hood') === '0') ui.showGuards.checked = false;
if (qp.get('pip') === '0') ui.showPip.checked = false;
if (compactViewport && qp.get('pip') !== '1') ui.showPip.checked = false;
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6 && a.every(Number.isFinite)) { camera.position.set(...a.slice(0, 3)); controls.target.set(...a.slice(3)); controls.update(); } }
document.getElementById('loading').classList.add('hide'); render(); frame();
