// 主程式：舞台（core/ui/stage.js）＋播放控制（core/ui/player.js）＋相機視窗（core/ui/viewer-workspace.js）＋本專案的視角、面板與取像模擬
import * as THREE from 'three';
import { createStage, exposeSim } from '@core/ui/stage.js';
import { createPlayer } from '@core/ui/player.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { SPECS, SCENARIOS, TRAYS, DEMO, X1, X2, Y0, YA, YM, YS, YT, DIR_A, occupied, inTol } from './spec.js';
import { STATIONS } from './sequence.js';
import { createProject } from './project.js';
import { createCameraSim, TITLES, W as SIM_W, H as SIM_H } from './camera-sim.js';
import { overviewFrame } from './render-finishes.js';

const qp = new URLSearchParams(location.search), movie = qp.has('movie');
const specId = SPECS[qp.get('spec')] ? qp.get('spec') : 'B', scenarioId = SCENARIOS[qp.get('result')] ? qp.get('result') : 'OK';

// ---------------------------------------------------------------- 場景
const canvas = document.getElementById('c');
// 共用舞台：外觀用 look 'studio'（曝光、灰藍背景、主光／補光／輪廓光的顏色與強度，輪廓光位置即預設 [700, 2100, -500]）；
// 此處只傳與預設不同的值（霧、相機與控制範圍、主光位置與陰影、補光位置）。燈位與陰影範圍沿用原本手調值，不用 extent 推算
const stage = createStage({
  canvas, qp, look: 'studio', fog: [4500, 16000],
  camera: { fov: 38, near: 2, far: 20000 },
  controls: { minDistance: 8, maxDistance: 6000, maxPolarAngle: Math.PI },   // 維持原本不限仰角（共用預設為 0.49π）
  sun: {
    position: [-900, 2600, 1400], target: [0, 900, 0],
    shadow: { mapSize: innerWidth > 900 ? 4096 : 2048, camera: { left: -700, right: 700, top: 700, bottom: -700, near: 300, far: 5000 }, bias: -0.0001, normalBias: 0.4 },
  },
  fill: { position: [1200, 1500, -1500] },
});
const { renderer, scene, camera, controls } = stage;

// ---------------------------------------------------------------- 物件（與 core 統一檢查共用 project.js）
const project = createProject({ scene, spec: specId, scenario: scenarioId });
const { machine, sequence, spec: s, scenario: sc, measurement: m } = project;
project.grid.visible = qp.has('grid');
const sim = createCameraSim(s, m, scenarioId);
const ids = ['action', 'substep', 'zoneDot', 'zoneTxt', 'checklist', 'chkCount', 'progBar', 'signals', 'poseError', 'phase', 'result', 'specSel', 'exportBtn', 'showGuards', 'showLabels', 'showBeams', 'showPip', 'cycleTime', 'pipFrame', 'stations', 'meas', 'verdict', 'trayMap', 'trayNote', 'specName', 'specNote', 'detailNote'];
const ui = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
for (const v of Object.values(SPECS)) ui.specSel.add(new Option(v.name, v.id));
for (const v of Object.values(SCENARIOS)) ui.result.add(new Option('情境：' + v.name, v.id));
ui.specSel.value = specId; ui.result.value = scenarioId;
const reload = (k, v) => { const q = new URLSearchParams(location.search); q.set(k, v); ['step', 'st', 'time'].forEach(x => q.delete(x)); location.search = q.toString(); };
ui.specSel.onchange = () => reload('spec', ui.specSel.value); ui.result.onchange = () => reload('result', ui.result.value);
ui.specName.textContent = `${s.name} · 配方 ${s.recipe}`; ui.specNote.textContent = `${s.note}。工件採圖面尺寸、設備為規劃包絡；量測值、缺陷與節拍為模擬示意，待樣品與 POC 校正。`;

// 3D 標籤（共用舞台的 addLabel；畫布在頁面中的偏移由舞台處理）。priority 2：兩站主設備、移載與入料，小螢幕避讓時優先保留
const V = (x, y, z) => new THREE.Vector3(x, y, z), addLabel = (html, pos, priority = 0) => stage.addLabel(html, pos, '', { priority });
addLabel('<b>A</b> 4K 線掃＋1.5× 遠心', V(X1 + DIR_A[0] * 150, YA + 30, DIR_A[2] * 150), 2);
addLabel('<b>B</b> 0.5× 雙遠心鏡頭', V(X1 - 150, YA + 28, 0)); addLabel('<b>B</b> 遠心平行背光', V(X1 + 80, YA + 24, 0));
addLabel('<b>C</b> 口部端面（經中空軸）', V(X1, YM + 250, 0)); addLabel('DD 中空軸馬達＋三爪 PEEK 夾頭', V(X1, YM + 78, 40), 2);
addLabel('RGB 三角度線光源', V(X1 - 20, YA + 22, 48)); addLabel('移載：X 軸＋Z 軸＋貼靠氣缸＋側向真空吸嘴', V(-60, Y0 + 210, -160), 2);
addLabel(`上共焦 ${s.upper}`, V(X2, YS + s.wd + 90, 0), 2); addLabel('下共焦 CL-S015（參考距離 15 mm）', V(X2, Y0 + 50, 80));
addLabel(`空心軸 θ 平台＋${s.ring} 薄環座`, V(X2 - 40, YS + 8, 40), 2); addLabel('C 型架（R 軸微動台）', V(300, Y0 + 370, 0));
addLabel('入料托盤', V(TRAYS.IN.cx, YT + 25, 40), 2); addLabel('OK', V(TRAYS.OK.cx, YT + 25, 40)); addLabel('NG1', V(TRAYS.NG1.cx, YT + 25, 40)); addLabel('NG2', V(TRAYS.NG2.cx, YT + 25, 40));
addLabel('花崗岩平台 620 × 430 × 42', V(-200, Y0 + 6, 205));

STATIONS.forEach((name, i) => { const b = document.createElement('button'); b.className = 'st'; b.dataset.st = i; b.innerHTML = `<span class="idx">S${i}</span>${name}`; ui.stations.appendChild(b); });

// ---------------------------------------------------------------- 時間軸（時間只由 player 推進）
let S, current, player = null, curStation = -1, curStep = -1;
// 場景依時間的狀態一律由 project.apply 套用（與統一檢查同一份）；外罩、光束、三色燈另依介面勾選與播放狀態
const displayOpts = () => ({ playing: !!player?.playing, hood: ui.showGuards.checked, beams: ui.showBeams.checked });
function sampleAt(t) { current = project.apply(t, displayOpts()); S = current.state; }
const total = project.total;
ui.cycleTime.textContent = `規劃 ${total.toFixed(1)} s／件 ≈ ${Math.round(3600 / total)} UPH（單件流）`;
const has = id => c => c.has(id);
const checklist = [
  [['入料第 ' + (DEMO.k + 1) + ' 穴吸附取料', has('grab:in')]],
  [['三爪夾持（限力 2 N）', has('clamp')], ['交接：先夾持再破真空', has('handoff1')], ['通道 A 外壁 360° 展開', has('scanA')], ['通道 B 剪影 4 × 90°', has('shotB3')], ['通道 C 口部端面', has('shotC')], ['交接：先吸附再鬆夾', has('unclamp')]],
  [['落座薄環座', has('seat')]],
  [['螺旋掃描（上下共焦同步）', has('spiral0')], ...(scenarioId === 'ERR' ? [['有效點不足 → ERR', has('err0')], ['重新落座', has('reseat')], ['重測一次', has('spiral1')]] : [])],
  [['判定＋資料寫入', has('judge')], [sc.out === 'IN' ? '退回入料原穴（人工處理）' : `放入 ${sc.out} 托盤`, has('out')], ['移載回待命位', has('home')]],
];

// 視角：[相機位置, 注視點] 或依目前狀態計算的函式（全景依機台外廓與畫面比例取景、工件跟拍依工件位置）
// 全景已依畫面比例取景，先除掉舞台窄畫面拉遠的倍數（goTo 會再乘回），手機直向才不會拉遠兩次；桌面倍數為 1
const isoFrame = () => { const [p, t] = overviewFrame(machine.root, camera), k = 1 / stage.fitScale; return [p.map((v, i) => t[i] + (v - t[i]) * k), t]; };
const VIEWS = {
  iso: isoFrame, top: [[0, 2050, 1], [0, 900, 0]],
  st1: [[X1 - 105, YA + 60, -150], [X1 + 5, YA - 2, 5]], chuck: () => [[X1 - 38, YM + 6, -40], [X1, YM - s.len / 2, 0]],
  st2: [[X2 - 110, YS + 170, 300], [X2 + 10, YS + 25, 0]], seat: () => [[X2 - 40, YS + 26, -46], [X2, YS + s.len / 2, 0]],
  trays: [[-240, YT + 190, 260], [-160, YT, 0]],
  electrical: [[0, 470, 1230], [0, 430, -135]],
  xray: [[860, 910, 1330], [0, 470, -70]],
  wiring: [[-1000, 1460, -1280], [0, 1010, 0]],
  carriers: [[-420, 1240, -710], [-40, 1030, -175]],
  fibers: [[130, 1270, 530], [270, 1135, 65]],
  part: () => { const p = machine.partWorld(); return [p.clone().add(V(-26, 16, -34)).toArray(), p.toArray()]; },
};
const NEAR = { chuck: 0.5, seat: 0.5, part: 0.5 }, VIEW_TWEEN = .9;
// 工件跟拍：每格把工件位移交給 stage.shiftView（相機、注視點與進行中轉場的起訖點一起平移）
let selectedView = 'iso'; const lastPart = V(0, 0, 0);
function setView(name, instant = false) {
  if (!VIEWS[name]) return;
  workspace.stopFollowing();                         // 先解除焦點追隨（它會還原自己改過的近裁切面）
  selectedView = name; camera.near = NEAR[name] || 4; camera.updateProjectionMatrix();
  machine.details.setMode(name === 'electrical' ? 'cutaway' : name === 'xray' ? 'xray' : 'shell');
  const [p, t] = typeof VIEWS[name] === 'function' ? VIEWS[name]() : VIEWS[name];
  stage.goTo(p, t, instant, VIEW_TWEEN);
  lastPart.copy(machine.partWorld());                // 視角以目前工件位置為準（同一格先跳播再切視角時，跟拍不把跳播位移算進去）
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
  ui.detailNote.hidden = !['chuck', 'seat', 'part', 'electrical', 'xray', 'wiring', 'carriers', 'fibers'].includes(name);
  ui.detailNote.textContent = { chuck: `夾頭特寫 · 夾持帶只在杯口 1.5 mm\n吸嘴由後方爪間空隙伸入，貼靠中心距底面 1.8 mm`, seat: `環座特寫 · ${s.ring} 內孔 Ø${s.ringBore}\n下感測器由空心軸內向上量外底面，上感測器穿過杯口量內底面`, part: `工件跟拍 · Ø${s.od} × ${s.len} mm，實際尺寸` }[name] || '';
  if (['electrical', 'xray'].includes(name)) ui.detailNote.textContent = '電控配置規劃 · CL-3000＋兩組 CL-S015N 光學模組\n8 軸驅動／24 V 控制／獨立視覺網路；外形為安裝包絡，非原廠 CAD';
  if (name === 'wiring') ui.detailNote.textContent = '整線配置 · 固定線槽／移動服務環／桌板穿線護口\n動力與量測訊號分路；光纖彎曲半徑及拖鏈適用性待原廠核定';
  if (name === 'carriers') ui.detailNote.textContent = 'X 拖鏈 650 mm／R35 · Z 拖鏈 180 mm／R22\n固定長度折返，兩端固定於軸座；氣管另行管理';
  if (name === 'fibers') ui.detailNote.textContent = '共焦光纖 · 上頭升降環 R27.5／R 軸補償環 R40\n曲率為配置預留，原廠動態彎曲與壽命尚待確認';
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));

// 播放列：共用 createPlayer（播放、重播、速度、時間軸、時鐘、步驟選單、上一步／下一步、#loop 連續循環），事件即序列的每一步。
// 本專案預設 0.5×（?speed= 可覆寫）；?movie 由錄影程式逐格驅動，不自動播放
player = createPlayer({
  total, qp: movie ? new URLSearchParams(qp + '&pause') : qp, speeds: [.25, 2], speed: .5,
  events: sequence.events.map(e => ({ time: e.time, label: `S${e.station} · ${e.label}` })),
  apply: t => { sampleAt(t); return current; },
});
// 跳到指定秒數並立即重繪（站別按鈕、網址參數、window.sim 與截圖工具用）
function seekTo(sec) { player.seekTo(sec); render(); }
// 站別按鈕停在該站最有代表性的一刻
const PREVIEW = [['grab:in', 0], ['scanA', -0.5], ['seat', 0], ['spiral0', -1.2], ['judge', 0]];
const previewTime = i => { const [id, off] = PREVIEW[i], x = sequence.steps.find(y => y.done === id); return x.start + x.dur + off; };
ui.stations.querySelectorAll('.st').forEach(b => b.onclick = () => { player.pause(); seekTo(previewTime(+b.dataset.st)); setView(['trays', 'st1', 'st2', 'st2', 'trays'][+b.dataset.st]); });

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
    mode: 'SIMULATION', serial: `SIM-${specId}-${String(DEMO.k + 1).padStart(4, '0')}`, recipe: s.recipe, spec: specId, scenario: scenarioId, time: +player.T.toFixed(2), plannedCycle: +total.toFixed(2),
    result: done.has('judge') ? m.result : 'PENDING', ngCode: done.has('judge') ? m.code : '', route: done.has('out') ? S.loc : 'PENDING',
    dimension: done.has('shotC') ? { od: m.od, length: m.length, idLip: m.idLip, wallLip: +m.wallLip.toFixed(4), flareDeg: m.flare, straightness: m.straightness } : null,
    baseThickness: done.has('spiral0') ? { mean: m.thkMean, min: m.thkMin, max: m.thkMax, tir: m.thkTir, flatness: m.flatness, validPts: m.valid, invalidPts: m.invalid, retest: m.retest && done.has('spiral1') } : null,
    defects: done.has('scanA') ? m.defects : null, versions: { algorithm: 'sim', model: 'shell-defect-v1.3', jigRing: s.ring },
    exposureEvents: sequence.steps.filter(x => x.exposure && x.start + x.dur <= player.T + 1e-9).map(x => ({ action: x.action, channel: x.exposure, plannedTime: +x.start.toFixed(2) })),
    physicalMeasurement: false, mesConnected: false,
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })), a = document.createElement('a');
  a.href = url; a.download = `CUP-${specId}-${scenarioId}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
ui.exportBtn.onclick = exportReport;
ui.showBeams.onchange = () => seekTo(player.T);

function drawHud() {
  const T = player.T, playing = player.playing, done = current.completed, judged = done.has('judge'), cls = m.result === 'OK' ? 'ok' : m.result === 'ERR' ? 'err' : 'ng';
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
  project.display(current, displayOpts());
  if (curStep !== current.index || judged !== drawHud.judged) { curStep = current.index; drawHud.judged = judged; machine.drawScreen([`${s.recipe}　${STATIONS[S.station]}`, judged ? `判定 ${m.result}` : '量測中', S.action, `節拍 ${total.toFixed(1)} s ≈ ${Math.round(3600 / total)} UPH`, `治具 ${s.ring}　模型 v1.3`, '模擬畫面 · 未接實機'], judged ? { ok: '#7fe0b4', ng: '#ff8d80', err: '#ffc857' }[cls] : '#7fe0b4'); }
  if (curStation !== S.station) { curStation = S.station; ui.checklist.innerHTML = ''; checklist[curStation].forEach(([txt]) => { const li = document.createElement('li'); li.innerHTML = `<span class="box"></span><span>${txt}</span>`; ui.checklist.appendChild(li); }); }
  let n = 0; [...ui.checklist.children].forEach((li, i) => { const d = checklist[S.station][i][1](done); li.classList.toggle('done', d); li.querySelector('.box').textContent = d ? '✓' : ''; if (d) n++; });
  ui.chkCount.textContent = n + ' / ' + checklist[S.station].length;
  ui.stations.querySelectorAll('.st').forEach(b => { const i = +b.dataset.st; b.classList.toggle('active', i === S.station); b.classList.toggle('done', i < S.station || T >= total); });
  ui.progBar.style.width = T / total * 100 + '%';
  // 取像模擬畫進 viewer-workspace 的相機視窗（隱藏且未彈出獨立視窗時不繪製）
  ui.pipFrame.classList.toggle('flash', !!S.flash);
  workspace.renderImage({
    draw: (g, w, h) => { g.scale(w / SIM_W, h / SIM_H); sim.draw(S, done, g); }, aspect: SIM_W / SIM_H, time: T,
    title: TITLES[S.pip] + '（模擬）', result: `${S.pip === 'result' && judged ? `判定 ${m.result}${m.code ? ' · ' + m.code : ''}` : pipNote(S)} · 2D 示意影像，非實拍`,
  });
  stage.updateLabels(ui.showLabels.checked);
  document.getElementById('diagnostics').textContent = JSON.stringify({ time: T, total, step: current.index, station: S.station, action: S.action, loc: S.loc, optic: S.optic, pip: S.pip, playing, spec: specId, scenario: scenarioId });
}
const pipNote = S => S.flash ? '本幀頻閃取像' : S.optic === 'A' ? '線掃取像中' : S.optic === 'CF' ? '共焦取樣中' : '待命／移動中';
// 縮放：舞台處理畫布與相機比例；全景視角另依新比例重新取景。viewer-workspace 在視窗、版面（資訊欄收合）或畫布尺寸改變時呼叫；
// 錄影時畫布尺寸由錄影程式固定，不跟視窗變
function resize() { if (movie) return; stage.resize(); if (selectedView === 'iso') setView('iso', true); }
// 相機視窗（拖曳、放大、獨立視窗）、資訊欄收合、產品焦點追隨與手機版面：core viewer-workspace，與其他站共用
if (qp.get('pip') === '0') ui.showPip.checked = false;
const workspace = createViewerWorkspace({
  camera, controls, canvas, resize, focusOccluders: [machine.hood], getFocus: () => machine.partWorld(), focusOffset: [-26, 16, -34], focusNear: .5,
  onFocus: () => {
    stage.cancelTween(); selectedView = 'focus'; machine.details.setMode('shell'); ui.detailNote.hidden = true;
    document.querySelectorAll('.views button').forEach(b => b.classList.remove('selected'));
  },
});
if (qp.get('pip') === '1' && !ui.showPip.checked) { ui.showPip.checked = true; ui.showPip.dispatchEvent(new Event('change')); }   // 手機版預設收合，?pip=1 仍顯示
// 完整一格：介面與場景顯示狀態（drawHud）＋渲染；seekTo 與錄影都用這個
function render() { drawHud(); stage.render(); }
// 每格更新（舞台迴圈接著做 controls.update() 與渲染）
function tick(dt) {
  player.update(dt);                                  // 連續循環由播放列依 #loop 處理
  // 工件跟拍：工件這格的位移整體平移視角（轉場中也跟住，跳播後下一格跟上）
  const p = machine.partWorld(), d = p.clone().sub(lastPart); lastPart.copy(p);
  if (selectedView === 'part' && d.lengthSq() > 0) stage.shiftView(d);
  drawHud(); workspace.follow();
}
lastPart.copy(machine.partWorld()); stage.resize(); setView('iso', true);
exposeSim({
  seekTo, pause: () => player.pause(), play: () => player.play(), setView, views: Object.keys(VIEWS), get T() { return player.T; }, get state() { return S; }, total, project, player, camera, controls,
  steps: sequence.steps, events: sequence.events, stationStart: sequence.stationStart, spec: s, scenario: sc, measurement: m,
});
if (qp.has('st')) { player.pause(); seekTo(previewTime(THREE.MathUtils.clamp(+qp.get('st') || 0, 0, STATIONS.length - 1))); }
if (qp.has('step')) { player.pause(); seekTo(sequence.steps[THREE.MathUtils.clamp(+qp.get('step') || 0, 0, sequence.steps.length - 1)].start + (+qp.get('t') || 0)); }
if (qp.has('time')) { player.pause(); seekTo(+qp.get('time')); }
if (qp.has('view')) { lastPart.copy(machine.partWorld()); setView(qp.get('view'), true); }
if (qp.has('labels')) ui.showLabels.checked = true;
if (qp.get('hood') === '0') ui.showGuards.checked = false;
// 自訂相機：之後縮放不再以全景重新取景
if (qp.has('cam')) { const a = qp.get('cam').split(',').map(Number); if (a.length === 6 && a.every(Number.isFinite)) { stage.goTo(a.slice(0, 3), a.slice(3), true); selectedView = 'cam'; document.querySelectorAll('.views button').forEach(b => b.classList.remove('selected')); } }
document.getElementById('loading').classList.add('hide'); render();
stage.loop(tick, { render: () => workspace.renderOverview(renderer, scene) });   // 跟隨產品焦點時隱藏外罩；?movie 時舞台不啟動迴圈

// ---------------------------------------------------------------- 錄影（?movie）：由 core/movie 以絕對時間逐格驅動
if (movie) {
  player.pause();
  // 影片專用鏡位（ST1／ST2 重播、桌板穿線護口），其餘沿用網頁視角
  const FILM = { 'film-st1': [[-275, 1180, -430], [-120, 1090, 0]], 'film-st2': [[90, 1210, 460], [215, 1070, 0]], 'film-gland': [[20, 1100, 700], [290, 822, 231]] };
  const movieView = (name, instant) => {
    if (!FILM[name]) return setView(name, instant);
    const [p, t] = FILM[name]; camera.position.set(...p); controls.target.set(...t); camera.lookAt(controls.target);
  };
  // 單站重播：該站第一步開始到最後一步結束
  const span = (station, view, label) => { const a = sequence.steps.filter(x => x.station === station); return { view, label, simStart: a[0].start, simDuration: a.at(-1).start + a.at(-1).dur - a[0].start }; };
  const { installMovie } = await import('@core/movie/movie.js');
  installMovie({
    project: 'WorkpieceMeasurement', scene, renderer, camera, controls, render, setView: movieView, total,
    steps: sequence.steps,
    sample(t) { player.seekTo(t); },          // 與網頁、統一檢查同一條 project.apply 路徑
    focus: () => machine.partWorld(), offset: [-580, 400, 850],
    electricalMode: (_, mode) => machine.details.setMode(mode), keepGuards: true,
    detailShots: [
      span(1, 'film-st1', 'ST1 · 夾持、旋轉與三通道取像（重播）'),
      span(3, 'film-st2', 'ST2 · 上頭避讓、落座與上下共焦量測（重播）'),
      { view: 'carriers', label: 'X／Z 拖鏈 · 全行程折返與兩端固定（重播）', simStart: 0, simDuration: total },
      span(3, 'fibers', '光纖整線 · 升降補償環與徑向補償環（重播）'),
      { view: 'film-gland', label: '桌板穿線護口 · 線材通往下方電盤', simStart: total, simDuration: 0 },
    ],
  });
}
