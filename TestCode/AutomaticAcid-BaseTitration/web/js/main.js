import {createElectricalInspector} from '@core/electrical/electrical-inspector.js';
import {setElectricalCutaway} from '@core/electrical/electrical-cabinet.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { routingLegend } from '@core/electrical/cable-routing.js';
routingLegend();
// 主程式：場景、批次時間軸、樣品表、滴定曲線、交握訊號、通訊紀錄
import * as THREE from 'three';
import { createVisionOverlay } from '@core/ui/vision-overlay.js';
import { liquidResults } from './vision-results.js';
const vision = createVisionOverlay();
const fullProcessVision = createVisionOverlay();
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { createProject } from './project.js';
import { ST, Y0, SAMPLES, TITRANT, ANALYTE, smooth } from './layout.js';

const qp = new URLSearchParams(location.search);
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: qp.get('aa') !== '0', powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0; renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x0d1117); scene.fog = new THREE.Fog(0x0d1117, 6000, 14000);
const room=new RoomEnvironment(renderer),pmrem=new THREE.PMREMGenerator(renderer);
room.traverse(o=>{if(o.isPointLight)o.intensity=240;});
scene.environment=pmrem.fromScene(room,.04).texture;room.dispose();pmrem.dispose();
const camera = new THREE.PerspectiveCamera(40, 1, 2, 30000);
const controls = new OrbitControls(camera, canvas); controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 30; controls.maxDistance = 9000;
scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x2a2f36, 0.6));
const sun = new THREE.DirectionalLight(0xfff8ef, 1.25); sun.position.set(-1400, 3600, 2000); sun.castShadow = qp.get('shadow') !== '0'; sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -1800, right: 1800, top: 1800, bottom: -1800, near: 500, far: 9000 }); sun.shadow.bias = -0.0003; scene.add(sun);
sun.shadow.normalBias=.08;
const fill = new THREE.DirectionalLight(0x9fb8ff, 0.5); fill.position.set(1800, 1500, -1800); scene.add(fill);
const cupLight=new THREE.DirectionalLight(0xfffbf3,.5);cupLight.position.set(590,1530,260);cupLight.target.position.set(810,990,60);
cupLight.castShadow=renderer.shadowMap.enabled;cupLight.shadow.mapSize.set(1024,1024);
Object.assign(cupLight.shadow.camera,{left:-130,right:130,top:180,bottom:-180,near:50,far:1000});
cupLight.shadow.normalBias=.025;cupLight.shadow.bias=-.00001;scene.add(cupLight,cupLight.target);

// 場景物件與時間狀態由 project.js 建立與套用（core 統一檢查用同一份，檢查的就是畫面上的幾何）
const project = createProject({ scene }), plan = project.plan, lab = project.lab, total = project.total;
const $ = id => document.getElementById(id);
const ui = Object.fromEntries(['phase', 'act', 'stepLabel', 'tbody', 'log', 'modeHint', 'tableHint', 'curve', 'titrPhase', 'titrInfo', 'titrRes', 'balance', 'sigs', 'showLabels', 'showZones', 'exportBtn',
  'playBtn', 'restartBtn', 'speed', 'autoSpeed', 'previous', 'next', 'stepSelect', 'cycleTime', 'timeline', 'progBar', 'clock', 'stations', 'mode', 'subtitle'].map(id => [id, $(id)]));
const fmtT = t => { t = Math.max(0, t); const m = Math.floor(t / 60), s = Math.floor(t % 60); return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`; };

// ---------------------------------------------------------------- Metrohm 整合方式（兩案並陳）
const MODES = {
  tiamo: { name: 'tiamo', label: 'tiamo＋Titrando＋814 進樣器', link: 'Remote Box 數位 I/O＋樣品表／結果檔交換', screen: 'tiamo™' },
  omnis: { name: 'OMNIS', label: 'OMNIS Titrator＋OMNIS 進樣模組', link: 'OMNIS 遠端介面（待 Metrohm 確認）', screen: 'OMNIS' },
};
let mode = qp.get('mode') === 'omnis' ? 'omnis' : 'tiamo'; ui.mode.value = mode;
ui.mode.onchange = () => { mode = ui.mode.value; lastLog = ''; refreshMode(); render(); };
function refreshMode() {
  const M = MODES[mode];
  ui.subtitle.textContent = `DENSO COBOTTA PRO 900 · 6 瓶 × 2 重複 = 12 次滴定 · 批次 ${Math.round(total / 60)} 分 · Metrohm ${M.label}`;
  ui.modeHint.textContent = M.link; ui.tableHint.textContent = `整合軟體 → ${M.name}`;
}
refreshMode();

// ---------------------------------------------------------------- 流程步驟按鈕（對照用戶文件 ①～⑨）
const FLOW = [[0, '①', '初始化'], [2, '②', '空杯秤重'], [3, '③', '讀碼開蓋'], [4, '④', '移液'], [5, '⑤', '樣品秤重'], [6, '⑥', '進樣器'], [8, '⑧', '關蓋'], [9, '⑨', '分析・取杯']];
const flowBtns = FLOW.map(([ph, idx, name]) => {
  const b = document.createElement('button'); b.className = 'st'; b.innerHTML = `<span class="idx">${idx}</span>${name}`;
  b.onclick = () => { const e = plan.events.find(x => x.phase === ph && x.t > T + 0.5) || plan.events.find(x => x.phase === ph); if (e) { pause(); seekTo(e.t); } };
  ui.stations.appendChild(b); return b;
});

// ---------------------------------------------------------------- 視角
const views = {
  electrical: [[-950,700,1400],[0,480,0]],
  wiring: [[1550,1850,1100],[850,1250,60]],
  titration: [[680,1105,270],[810,1003,60]], liquid: [[90,1020,-190],[-20,905,-370]], bottles:[[-260,1140,650],[-500,970,300]],
  iso: [[-1450, 2550, 2450], [80, 930, -20]], balance: [[-80, 1720, 820], [-560, 1000, -40]], decap: [[-470, 1420, 60], [-180, 1030, -330]],
  pipette: [[120, 1560, -980], [90, 1000, -300]], sampler: [[330, 1650, 760], [690, 960, 40]], top: [[0, 3700, 250], [0, 850, 0]],
};
let camAnim = null, follow = false, liquidTrack = null, visionView='iso';
function liquidFocus(){
  const cup=lab.items[`beaker${info?.sampler.job?.beaker??0}`],fluid=cup.userData.fluid;
  return cup.localToWorld(new THREE.Vector3(0,fluid.surface.position.y,0));
}
function setView(name, instant = false) {
  workspace.stopFollowing(); setElectricalCutaway(scene,name==='electrical');
  liquidTrack=null;visionView=name;
  follow = name === 'follow';
  document.querySelectorAll('.views button').forEach(b => b.classList.toggle('selected', b.dataset.view === name));
  if (follow) return;
  if(name==='meniscus'){
    info=project.apply(T);liquidTrack=liquidFocus();camAnim=null;
    controls.target.copy(liquidTrack);camera.position.copy(liquidTrack).add(new THREE.Vector3(-75,115,90));controls.update();return;
  }
  if (!views[name]) return; const [p, t] = views[name].map(a => new THREE.Vector3(...a));
  if (instant) { camAnim = null; camera.position.copy(p); controls.target.copy(t); controls.update(); } else camAnim = { p0: camera.position.clone(), t0: controls.target.clone(), p, t, u: 0 };
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));
const _tcp = new THREE.Vector3();
function followCam(dt) { project.robot.getTcpWorld('grip', _tcp); const k = 1 - Math.exp(-dt * 3); controls.target.lerp(_tcp, k); camera.position.lerp(_tcp.clone().add(new THREE.Vector3(260, 420, 620)), k); }

// ---------------------------------------------------------------- 3D 標籤
const labels = [];
function addLabel(text, x, y, z) { const el = document.createElement('div'); el.className = 'label3d'; el.innerHTML = text; $('app').appendChild(el); labels.push({ el, pos: new THREE.Vector3(x, Y0 + y, z) }); }
addLabel('<b>DENSO</b> COBOTTA PRO 900', 0, 980, 0);
addLabel('分析天平（上方滑門）', ST.balance.x, 420, ST.balance.z);
addLabel('待處理杯區', ST.emptyRack.cols[1], 160, ST.emptyRack.rows[0]);
addLabel('樣品瓶座／開蓋', ST.clamp.x, 260, ST.clamp.z);
addLabel('瓶蓋暫放', ST.capRest.x, 90, ST.capRest.z);
addLabel('滴定杯座', ST.holder.x, 140, ST.holder.z);
addLabel('廢液漏斗', ST.funnel.x, 120, ST.funnel.z);
addLabel('吸頭廢料口', ST.tipChute.x, 60, ST.tipChute.z);
addLabel('5 mL 吸頭', ST.tipRack.x0 + 75, 220, ST.tipRack.z[0]);
addLabel('移液模組座', ST.dock.x, 330, ST.dock.z);
addLabel('條碼讀取', ST.scanner.x, 200, ST.scanner.z);
addLabel('待驗樣品瓶區', ST.sampleRack.cols[1], 260, ST.sampleRack.rows[500]);
addLabel('完成樣品瓶區', ST.doneBottleRack.cols[1], 260, ST.doneBottleRack.rows[500]);
addLabel('完成滴定杯區', ST.doneRack.cols[1], 150, ST.doneRack.rows[3]);
addLabel('<b>Metrohm</b> 自動進樣器', ST.sampler.x, 330, ST.sampler.z - 150);
addLabel('滴定儀＋Dosino', ST.titrator.x, 560, ST.titrator.z);
addLabel('整合軟體／Metrohm 軟體', ST.pc.x, 520, ST.pc.z);
addLabel('安全雷射掃描器', 0, -700, 580);

// ---------------------------------------------------------------- 樣品表、訊號、紀錄
const rows = [];
for (let k = 0; k < 12; k++) { const tr = document.createElement('tr'); tr.innerHTML = '<td></td><td></td><td></td><td></td><td></td><td></td><td></td>'; ui.tbody.appendChild(tr); rows.push(tr); }
const SIGS = [['door', '天平門開'], ['stable', '天平穩定'], ['clamp', '瓶座夾緊'], ['tip', '吸頭已裝'], ['pip', '移液中'], ['zone', '手臂在進樣器區'], ['cup', '杯子到位'], ['rotating', '轉盤轉動'], ['titrating', '滴定中'], ['done', '分析完成'], ['cycle', 'Cycle Complete'], ['safe', '安全區無人・全速']];
const sigEls = {};
for (const [k, name] of SIGS) { const d = document.createElement('div'); d.innerHTML = `<i></i>${name}`; ui.sigs.appendChild(d); sigEls[k] = d; }
plan.events.forEach((m, i) => { const o = document.createElement('option'); o.value = i; o.textContent = `${fmtT(m.t)} · ${m.label}`; ui.stepSelect.appendChild(o); });
ui.timeline.max = total;
ui.cycleTime.textContent = `批次 ${fmtT(total)}・手臂前處理 ${fmtT(plan.stats.prepEnd)}・每杯滴定 7 分`;

// ---------------------------------------------------------------- 滴定曲線
const cctx = ui.curve.getContext('2d');
function drawCurve(g, W, H, info, big = false) {
  g.fillStyle = '#0b1520'; g.fillRect(0, 0, W, H);
  const pad = big ? 60 : 34, x0 = pad, y0 = H - pad * 0.7, w = W - pad - 14, h = H - pad * 0.7 - 16, vmax = TITRANT.buret;
  g.strokeStyle = '#243444'; g.lineWidth = 1; g.font = `${big ? 20 : 15}px Arial`; g.fillStyle = '#6f8090';
  for (let p = 0; p <= 14; p += 2) { const y = y0 - p / 14 * h; g.beginPath(); g.moveTo(x0, y); g.lineTo(x0 + w, y); g.stroke(); g.fillText(p, x0 - (big ? 30 : 22), y + 5); }
  for (let v = 0; v <= vmax; v += 5) { const x = x0 + v / vmax * w; g.beginPath(); g.moveTo(x, y0); g.lineTo(x, y0 - h); g.stroke(); g.fillText(`${v}`, x - 6, y0 + (big ? 24 : 17)); }
  g.fillText('pH', 4, 16); g.fillText(`V ${TITRANT.name} (mL)`, x0 + w - (big ? 150 : 100), y0 + (big ? 48 : 32) > H ? y0 - 6 : y0 + (big ? 48 : 30));
  if (!info.curve) { g.fillStyle = '#50606e'; g.fillText('等待樣品', x0 + w / 2 - 40, y0 - h / 2); return; }
  const { v, f, job } = info.curve;
  g.strokeStyle = '#4aa8ff'; g.lineWidth = big ? 3 : 2; g.beginPath();
  for (let u = 0; u <= v + 1e-9; u += 0.05) { const x = x0 + u / vmax * w, y = y0 - f(u) / 14 * h; u === 0 ? g.moveTo(x, y) : g.lineTo(x, y); }
  g.stroke();
  if (v > job.veq) { const x = x0 + job.veq / vmax * w; g.strokeStyle = '#3dd68c'; g.setLineDash([6, 5]); g.beginPath(); g.moveTo(x, y0); g.lineTo(x, y0 - h); g.stroke(); g.setLineDash([]); g.fillStyle = '#3dd68c'; g.fillText(`EP ${job.veq.toFixed(3)} mL`, x + 6, y0 - h + 18); }
}
function drawScreens(info, T) {
  const M = MODES[mode], j = info.curve?.job, key = `${mode}|${j ? j.k : '-'}|${info.curve ? info.curve.v.toFixed(2) : ''}|${info.sampler.phase}`;
  lab.screen.draw(key, (g, W, H) => {
    g.fillStyle = '#e9eef3'; g.fillRect(0, 0, W, H); g.fillStyle = '#1b4f8a'; g.fillRect(0, 0, W, 54);
    g.fillStyle = '#fff'; g.font = 'bold 30px Arial'; g.fillText(`Metrohm ${M.screen}`, 18, 38); g.font = '22px Arial'; g.fillText(info.sampler.phase, W - 360, 36);
    const cw = Math.round(W * 0.62), ch = H - 70; g.save(); g.translate(10, 62); drawCurve(g, cw, ch, info, true); g.restore();
    g.fillStyle = '#20303f'; g.font = 'bold 22px Arial'; g.fillText('樣品表', cw + 30, 92); g.font = '19px Arial';
    info.table.forEach((r, k) => { g.fillStyle = r.status.startsWith('完成') ? '#1d7a45' : r.status === '滴定中' ? '#b36b00' : '#4a5663'; g.fillText(`${k + 1}. S${(r.sample ?? Math.floor(k / 2)) + 1}-${(r.rep ?? k % 2) + 1}  ${r.status}${r.result ? '  ' + r.result.toFixed(3) + '%' : ''}`, cw + 30, 124 + k * 38); });
  });
  lab.tscreen.draw(key, (g, W, H) => {
    g.fillStyle = '#0b1a2a'; g.fillRect(0, 0, W, H); g.fillStyle = '#9fd0ff'; g.font = 'bold 26px Arial';
    g.fillText(j ? `S${j.sample + 1}-${j.rep + 1}  DET pH` : 'Ready', 14, 40);
    g.font = '24px Consolas, monospace'; g.fillStyle = '#e6edf3';
    if (info.curve) { g.fillText(`V  ${info.curve.v.toFixed(3)} mL`, 14, 100); g.fillText(`pH ${info.curve.f(info.curve.v).toFixed(2)}`, 14, 140); }
    g.fillStyle = '#8b98a8'; g.font = '20px Arial'; g.fillText(info.sampler.phase, 14, 190);
  });
}

// ---------------------------------------------------------------- 時間
let T = 0, playing = !qp.has('pause'), lastLog = '', info = null;
const pause = () => { playing = false; ui.playBtn.textContent = '▶ 播放'; };
function seekTo(t) { T = THREE.MathUtils.clamp(t, 0, total); render(); }
const play = () => { if (T >= total) T = 0; playing = true; ui.playBtn.textContent = '⏸ 暫停'; };
ui.playBtn.onclick = () => playing ? pause() : play();
ui.restartBtn.onclick = () => seekTo(0);
const closeShots={
  dose:{view:'titration',time:()=>plan.jobs[0].start+90},
  water:{view:'titration',time:()=>plan.jobs[0].start+7},
  dispense:{view:'liquid',time:()=>{const s=plan.steps.find(s=>s.label==='吐出 5 mL＋吹出');return s.start+s.dur*.55;}},
  bottles:{view:'bottles',time:()=>0},
};
$('detailShot').onchange=e=>{const shot=closeShots[e.target.value];if(shot){pause();seekTo(shot.time());setView(shot.view,true);}e.target.value='';};
ui.timeline.oninput = () => { pause(); seekTo(+ui.timeline.value); };
const jumpMs = d => { pause(); const ms = plan.events; let i = ms.findIndex(m => m.t > T + 1e-6); if (d < 0) { i = -1; ms.forEach((m, j) => { if (m.t < T - 0.5) i = j; }); } if (i >= 0) seekTo(ms[i].t); };
ui.previous.onclick = () => jumpMs(-1); ui.next.onclick = () => jumpMs(1);
ui.stepSelect.onchange = () => { pause(); seekTo(plan.events[+ui.stepSelect.value].t); };
ui.showZones.onchange = () => { for (const z of lab.zones) z.visible = ui.showZones.checked; };
ui.exportBtn.onclick = () => {
  const end = project.apply(total);
  const report = {
    mode: 'SIMULATION', integration: MODES[mode].label, batchSec: +total.toFixed(1), robotPrepSec: +plan.stats.prepEnd.toFixed(1), titrant: `${TITRANT.name} ${TITRANT.c} mol/L`, resultBasis: `${ANALYTE.name}（示意）`,
    samples: SAMPLES.map(s => ({ id: s.id + 1, barcode: s.barcode, bottleMl: s.size, simulatedConcMolL: +s.conc.toFixed(5) })),
    table: plan.jobs.map(j => ({ row: j.k + 1, sample: j.sample + 1, replicate: j.rep + 1, beaker: j.beaker + 1, samplerPosition: j.slot + 1, tareG: +end.table[j.k].tare.toFixed(4), netG: +j.net.toFixed(4), placeSec: +j.placeT.toFixed(1), startSec: +j.start.toFixed(1), endSec: +j.end.toFixed(1), removeSec: +j.removeT.toFixed(1), epMl: +j.veq.toFixed(4), resultPct: +j.result.toFixed(4) })),
    messages: plan.msgs.map(m => ({ t: +m.t.toFixed(1), from: m.from, to: m.to === 'Metrohm' ? MODES[mode].name : m.to, text: m.text.replace('Metrohm', MODES[mode].name) })),
    physicalMeasurement: false,
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href = url; a.download = 'titration-batch-sim.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};

function drawHud() {
  info = project.apply(T);
  if(liquidTrack){const p=liquidFocus(),delta=p.clone().sub(liquidTrack);camera.position.add(delta);controls.target.add(delta);liquidTrack=p;camera.lookAt(controls.target);}
  const f = info, s = f.state, smp = f.sampler;
  ui.act.textContent = s.act; ui.stepLabel.textContent = `${f.step.label}${f.step.idle ? '' : `（${f.step.dur.toFixed(1)} s）`}`;
  ui.phase.textContent = T >= total ? 'CYCLE COMPLETE · 批次完成' : playing ? `AUTO · ${smp.phase === '待機' ? '前處理中' : 'Metrohm ' + smp.phase}` : 'HOLD · 暫停';
  // 樣品表
  const active = smp.job ? smp.job.k : -1, prep = f.table.findIndex(r => ['空杯秤重', '移液', '樣品秤重'].includes(r.status));
  f.table.forEach((r, k) => {
    const c = rows[k].children, S = SAMPLES[r.sample ?? Math.floor(k / 2)];
    c[0].textContent = k + 1; c[1].textContent = `${S.barcode.slice(-3)}-${(r.rep ?? k % 2) + 1}`;
    c[2].textContent = r.tare ? r.tare.toFixed(4) : '—'; c[3].textContent = r.net ? r.net.toFixed(4) : '—'; c[4].textContent = r.slot !== undefined ? r.slot + 1 : '—';
    c[5].textContent = r.status; c[5].className = r.status.startsWith('完成') ? 'st-done' : r.status === '滴定中' ? 'st-run' : r.status === '排隊' ? 'st-q' : r.status === '等待' ? 'st-wait' : '';
    c[6].textContent = r.result ? r.result.toFixed(3) : '—';
    rows[k].classList.toggle('active', k === active || k === prep);
  });
  // 滴定
  drawCurve(cctx, ui.curve.width, ui.curve.height, f);
  ui.titrPhase.textContent = smp.phase;
  if (f.curve) { ui.titrInfo.textContent = `樣品 ${f.curve.job.sample + 1}-${f.curve.job.rep + 1}・V ${f.curve.v.toFixed(3)} mL・pH ${f.curve.f(f.curve.v).toFixed(2)}`; ui.titrRes.textContent = T >= f.curve.job.end - 20 ? `${f.curve.job.result.toFixed(3)} %` : ''; }
  else { ui.titrInfo.textContent = '—'; ui.titrRes.textContent = ''; }
  // 天平與訊號
  ui.balance.textContent = s.balText; ui.balance.classList.toggle('stable', s.balStable && s.balPan > 0 && s.door === 0);
  const sig = { ...f.sig, safe: true };
  for (const [k] of SIGS) { sigEls[k].classList.toggle('on', !!sig[k]); sigEls[k].classList.toggle('warn', k === 'rotating' || k === 'zone'); }
  // 流程按鈕
  let ph = 0; for (const e of plan.events) { if (e.t > T + 1e-6) break; if (e.phase !== undefined) ph = e.phase; }
  FLOW.forEach(([p], i) => { flowBtns[i].classList.toggle('active', p === ph || (p === 9 && ph === 10)); });
  // 通訊紀錄（最近 8 筆）
  let n = 0; for (const m of plan.msgs) { if (m.t > T + 1e-6) break; n++; }
  const M = MODES[mode], logKey = `${mode}|${n}`;
  if (logKey !== lastLog) {
    lastLog = logKey;
    ui.log.innerHTML = plan.msgs.slice(Math.max(0, n - 8), n).reverse().map((m, i) => `<li class="${i === 0 ? 'new' : ''}"><time>${fmtT(m.t)}</time><span><b>${m.from.replace('Metrohm', M.name)} → ${m.to.replace('Metrohm', M.name)}</b> ${m.text.replace('Metrohm', M.name)}</span></li>`).join('');
  }
  drawScreens(f, T);
  ui.timeline.value = T; ui.progBar.style.width = T / total * 100 + '%'; ui.clock.textContent = fmtT(T);
  let mi = 0; plan.events.forEach((m, j) => { if (m.t <= T + 1e-6) mi = j; }); ui.stepSelect.value = mi;
  for (const l of labels) { const p = l.pos.clone().project(camera), vis = ui.showLabels.checked && p.z < 1 && Math.abs(p.x) < .98 && Math.abs(p.y) < .9; l.el.style.display = vis ? 'block' : 'none'; if (vis) { const r = canvas.getBoundingClientRect(); l.el.style.left = r.left + (p.x * .5 + .5) * r.width + 'px'; l.el.style.top = r.top + (-p.y * .5 + .5) * r.height + 'px'; } }
  $('diagnostics').textContent = JSON.stringify({ T, total, step: f.step.label, act: s.act });
}
function resize() { const w = canvas.clientWidth, h = canvas.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
window.addEventListener('resize', resize);
let focusItem='beaker0';
function activeProduct(){
  const touched=info?.step.touch?.find(id=>/^(beaker|bottle)/.test(id));
  const held=Object.entries(info?.state.loc||{}).find(([id,l])=>/^(beaker|bottle)/.test(id)&&l.g)?.[0];
  const job=info?.step.idle&&info?.sampler.job;
  focusItem=held||touched||(job?'beaker'+job.beaker:focusItem);
  return lab.items[focusItem].getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,35,0));
}
const processCamera=new THREE.PerspectiveCamera(38,1.5,.5,10000);
function render() {
  drawHud();workspace.follow();electrical.update({time:T,playing,action:info?.step.label,motion:!info?.step.idle,vision:false});workspace.renderOverview(renderer,scene);
  if(['meniscus','titration','liquid','bottles','balance','decap','pipette','sampler','follow'].includes(visionView)) fullProcessVision.draw(camera,canvas.getBoundingClientRect(),liquidResults(lab,info,T,visionView)); else fullProcessVision.hide();
  const p=activeProduct();processCamera.position.copy(p).add(new THREE.Vector3(-150,180,230));processCamera.lookAt(p);processCamera.updateMatrixWorld(true);
  workspace.renderCamera({renderer,scene,camera:processCamera,vision,title:'製程觀察 · 液面示意（虛擬相機）',result:'跟隨目前處理的樣品，非實拍量測',marks:liquidResults(lab,info,T,info.sampler.job&&info.step.idle?'titration':visionView)});
}
const workspace=createViewerWorkspace({camera,controls,canvas,resize,getFocus:activeProduct,
  focusOffset:[-150,180,230],focusNear:.5,onFocus:()=>{setElectricalCutaway(scene,false);camAnim=null;liquidTrack=null;follow=false;visionView='focus';document.querySelectorAll('.views button').forEach(b=>b.classList.remove('selected'));}});
const electrical=createElectricalInspector({scene,camera,controls,canvas,onEnter:()=>setView('electrical',true),onExit:()=>setView('iso',true),title:'AutomaticAcid-BaseTitration'});
const clock = new THREE.Clock();
function frame() {
  requestAnimationFrame(frame); const dt = Math.min(clock.getDelta(), 0.05);
  if (playing) {
    const idle = info?.step.idle && ui.autoSpeed.checked;
    T += dt * +ui.speed.value * (idle ? 10 : 1);
    if (T >= total) { T = total; pause(); }
  }
  if (camAnim) { camAnim.u = Math.min(1, camAnim.u + dt * 1.4); camera.position.lerpVectors(camAnim.p0, camAnim.p, smooth(camAnim.u)); controls.target.lerpVectors(camAnim.t0, camAnim.t, smooth(camAnim.u)); if (camAnim.u === 1) camAnim = null; }
  if (follow) followCam(dt);
  controls.update(); render();
}
setView(qp.get('view') || 'iso', true); resize(); ui.playBtn.textContent = playing ? '⏸ 暫停' : '▶ 播放';
if (qp.has('speed')) ui.speed.value = qp.get('speed');
if (qp.has('t')) { pause(); T = +qp.get('t') || 0; }
if (qp.get('view') === 'follow') { project.apply(T); project.robot.getTcpWorld('grip', _tcp); controls.target.copy(_tcp); camera.position.copy(_tcp).add(new THREE.Vector3(260, 420, 620)); }
window.sim = { plan, seekTo, get T() { return T; }, setView, views: [...Object.keys(views), 'meniscus', 'follow'], total, play, pause };
$('loading').classList.add('hide'); render(); frame();
