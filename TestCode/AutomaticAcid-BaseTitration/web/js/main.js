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
import { createStage, exposeSim } from '@core/ui/stage.js';
import { createPlayer } from '@core/ui/player.js';
import { createProject } from './project.js';
import { ST, Y0, SAMPLES, TITRANT, ANALYTE } from './layout.js';

// 共用舞台（core/ui/stage.js）：參數與原本手寫的 renderer／燈光完全相同，畫面不變
const canvas = document.getElementById('c');
const stage = createStage({
  canvas, exposure: 1.0, background: 0x0d1117, fog: [6000, 14000],
  logDepth: false,                                   // 原本未開對數深度；?movie 時由 stage 強制開啟
  envLight: 240,                                     // RoomEnvironment 點光強度
  camera: { fov: 40, near: 2, far: 30000 },
  controls: { minDistance: 30, maxDistance: 9000 },  // 阻尼 .08、仰角上限 .49π 為 stage 預設
  sun: { color: 0xfff8ef, intensity: 1.25, position: [-1400, 3600, 2000], target: [0, 0, 0],
    shadow: { mapSize: 2048, camera: { left: -1800, right: 1800, top: 1800, bottom: -1800, near: 500, far: 9000 }, bias: -0.0003, normalBias: .08 } },
  fill: { color: 0x9fb8ff, intensity: 0.5, position: [1800, 1500, -1800] },
});
const { renderer, scene, camera, controls, qp } = stage;
// 滴定杯補光：有自己的投影目標與陰影相機，stage 的 extraLights 無法表達，留在這裡
const cupLight=new THREE.DirectionalLight(0xfffbf3,.5);cupLight.position.set(590,1530,260);cupLight.target.position.set(810,990,60);
cupLight.castShadow=renderer.shadowMap.enabled;cupLight.shadow.mapSize.set(1024,1024);
Object.assign(cupLight.shadow.camera,{left:-130,right:130,top:180,bottom:-180,near:50,far:1000});
cupLight.shadow.normalBias=.025;cupLight.shadow.bias=-.00001;scene.add(cupLight,cupLight.target);

// 場景物件與時間狀態由 project.js 建立與套用（core 統一檢查用同一份，檢查的就是畫面上的幾何）
const project = createProject({ scene }), plan = project.plan, lab = project.lab, total = project.total;
const $ = id => document.getElementById(id);
const ui = Object.fromEntries(['phase', 'act', 'stepLabel', 'tbody', 'log', 'modeHint', 'tableHint', 'curve', 'titrPhase', 'titrInfo', 'titrRes', 'balance', 'sigs', 'showLabels', 'showZones', 'exportBtn',
  'speed', 'autoSpeed', 'cycleTime', 'progBar', 'stations', 'mode', 'subtitle'].map(id => [id, $(id)]));
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

// ---------------------------------------------------------------- 流程步驟按鈕（對照用戶文件 ①～⑨；排程的 station 即流程編號）
// 按下跳到該流程下一次出現的節點（每瓶都會重複），之後沒有就回到第一次（stationStart）
const FLOW = [[0, '①', '初始化'], [2, '②', '空杯秤重'], [3, '③', '讀碼開蓋'], [4, '④', '移液'], [5, '⑤', '樣品秤重'], [6, '⑥', '進樣器'], [8, '⑧', '關蓋'], [9, '⑨', '分析・取杯']];
const flowBtns = FLOW.map(([ph, idx, name]) => {
  const b = document.createElement('button'); b.className = 'st'; b.innerHTML = `<span class="idx">${idx}</span>${name}`;
  b.onclick = () => { const e = plan.events.find(x => x.station === ph && x.time > T + 0.5); pause(); seekTo(e ? e.time : plan.stationStart[ph]); };
  ui.stations.appendChild(b); return b;
});

// ---------------------------------------------------------------- 視角：[相機位置, 注視點]，切換用 stage.goTo；液面俯拍與跟隨手臂是動態視角，另外處理
const VIEWS = {
  electrical: [[-950,700,1400],[0,480,0]],
  wiring: [[1550,1850,1100],[850,1250,60]],
  titration: [[680,1105,270],[810,1003,60]], liquid: [[90,1020,-190],[-20,905,-370]], bottles:[[-260,1140,650],[-500,970,300]],
  iso: [[-1450, 2550, 2450], [80, 930, -20]], balance: [[-80, 1720, 820], [-560, 1000, -40]], decap: [[-470, 1420, 60], [-180, 1030, -330]],
  pipette: [[120, 1560, -980], [90, 1000, -300]], sampler: [[330, 1650, 760], [690, 960, 40]], top: [[0, 3700, 250], [0, 850, 0]],
};
let follow = false, liquidTrack = null, visionView='iso';
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
    info=project.apply(T);liquidTrack=liquidFocus();
    stage.goTo(liquidTrack.clone().add(new THREE.Vector3(-75,115,90)).toArray(),liquidTrack.toArray(),true);return;
  }
  if (!VIEWS[name]) return;
  stage.goTo(...VIEWS[name], instant, .72);          // 轉場 0.72 s（與原本的視角動畫同長）
}
document.querySelectorAll('.views button').forEach(b => b.onclick = () => setView(b.dataset.view));
const _tcp = new THREE.Vector3();
function followCam(dt) { project.robot.getTcpWorld('grip', _tcp); const k = 1 - Math.exp(-dt * 3); controls.target.lerp(_tcp, k); camera.position.lerp(_tcp.clone().add(new THREE.Vector3(260, 420, 620)), k); }

// ---------------------------------------------------------------- 3D 標籤（stage.addLabel；y 相對桌面）
const addLabel = (text, x, y, z) => stage.addLabel(text, new THREE.Vector3(x, Y0 + y, z));
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
// 標籤掛在 #app，畫布左側有樣品表、上方有工具列：標籤原點對齊畫布左上角（版面改變時重設）
let labelOrigin = '';
function updateLabels(show) {
  const origin = canvas.offsetLeft + ',' + canvas.offsetTop;
  if (origin !== labelOrigin) { labelOrigin = origin; for (const l of stage.labels) { l.el.style.left = canvas.offsetLeft + 'px'; l.el.style.top = canvas.offsetTop + 'px'; } }
  stage.updateLabels(show);
}

// ---------------------------------------------------------------- 樣品表、訊號、紀錄
const rows = [];
for (let k = 0; k < 12; k++) { const tr = document.createElement('tr'); tr.innerHTML = '<td></td><td></td><td></td><td></td><td></td><td></td><td></td>'; ui.tbody.appendChild(tr); rows.push(tr); }
const SIGS = [['door', '天平門開'], ['stable', '天平穩定'], ['clamp', '瓶座夾緊'], ['tip', '吸頭已裝'], ['pip', '移液中'], ['zone', '手臂在進樣器區'], ['cup', '杯子到位'], ['rotating', '轉盤轉動'], ['titrating', '滴定中'], ['done', '分析完成'], ['cycle', 'Cycle Complete'], ['safe', '安全區無人・全速']];
const sigEls = {};
for (const [k, name] of SIGS) { const d = document.createElement('div'); d.innerHTML = `<i></i>${name}`; ui.sigs.appendChild(d); sigEls[k] = d; }
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

// ---------------------------------------------------------------- 時間（播放列：core/ui/player.js；事件選單、上一步／下一步用排程的流程節點）
let T = 0, lastLog = '', info = null;
// 預設速度取 HTML 選單的預設值（5×）；網址 ?speed= 優先
const playerQp = new URLSearchParams(location.search); if (!playerQp.has('speed')) playerQp.set('speed', ui.speed.value);
const player = createPlayer({ total, qp: playerQp, events: plan.events, apply: t => { T = t; return (info = project.apply(T)); } });
const { play, pause } = player;
if (qp.has('t')) pause();
// 跳到時間 t 並立即重畫（流程按鈕、細節示範、window.sim；播放列自己的拖曳由畫面迴圈重畫）
function seekTo(t) { player.seekTo(t); render(); }
const closeShots={
  dose:{view:'titration',time:()=>plan.jobs[0].start+90},
  water:{view:'titration',time:()=>plan.jobs[0].start+7},
  dispense:{view:'liquid',time:()=>{const s=plan.steps.find(s=>s.label==='吐出 5 mL＋吹出');return s.start+s.dur*.55;}},
  bottles:{view:'bottles',time:()=>0},
};
$('detailShot').onchange=e=>{const shot=closeShots[e.target.value];if(shot){pause();seekTo(shot.time());setView(shot.view,true);}e.target.value='';};
ui.showZones.onchange = () => { for (const z of lab.zones) z.visible = ui.showZones.checked; };
ui.exportBtn.onclick = () => {
  const end = project.apply(total); info = project.apply(T);    // 取批次結束的樣品表後，場景放回目前時間
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
  if(liquidTrack){const p=liquidFocus(),delta=p.clone().sub(liquidTrack);camera.position.add(delta);controls.target.add(delta);liquidTrack=p;camera.lookAt(controls.target);}
  const f = info, s = f.state, smp = f.sampler;
  ui.act.textContent = s.act; ui.stepLabel.textContent = `${f.step.label}${f.step.idle ? '' : `（${f.step.dur.toFixed(1)} s）`}`;
  ui.phase.textContent = T >= total ? 'CYCLE COMPLETE · 批次完成' : player.playing ? `AUTO · ${smp.phase === '待機' ? '前處理中' : 'Metrohm ' + smp.phase}` : 'HOLD · 暫停';
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
  // 流程按鈕：目前步驟所屬的流程編號
  const ph = f.step.station;
  FLOW.forEach(([p], i) => { flowBtns[i].classList.toggle('active', p === ph || (p === 9 && ph === 10)); });
  // 通訊紀錄（最近 8 筆）
  let n = 0; for (const m of plan.msgs) { if (m.t > T + 1e-6) break; n++; }
  const M = MODES[mode], logKey = `${mode}|${n}`;
  if (logKey !== lastLog) {
    lastLog = logKey;
    ui.log.innerHTML = plan.msgs.slice(Math.max(0, n - 8), n).reverse().map((m, i) => `<li class="${i === 0 ? 'new' : ''}"><time>${fmtT(m.t)}</time><span><b>${m.from.replace('Metrohm', M.name)} → ${m.to.replace('Metrohm', M.name)}</b> ${m.text.replace('Metrohm', M.name)}</span></li>`).join('');
  }
  drawScreens(f, T);
  ui.progBar.style.width = T / total * 100 + '%';
  updateLabels(ui.showLabels.checked);
  $('diagnostics').textContent = JSON.stringify({ T, total, step: f.step.label, act: s.act });
}
let focusItem='beaker0';
function activeProduct(){
  const touched=info?.step.touch?.find(id=>/^(beaker|bottle)/.test(id));
  const held=Object.entries(info?.state.loc||{}).find(([id,l])=>/^(beaker|bottle)/.test(id)&&l.g)?.[0];
  const job=info?.step.idle&&info?.sampler.job;
  focusItem=held||touched||(job?'beaker'+job.beaker:focusItem);
  return lab.items[focusItem].getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,35,0));
}
const processCamera=new THREE.PerspectiveCamera(38,1.5,.5,10000);
// 一格畫面分三段：主畫面前（HUD、跟隨、電控）、主畫面、主畫面後（疊圖與製程相機）
function beforeMain() { drawHud();workspace.follow();electrical.update({time:T,playing:player.playing,action:info?.step.label,motion:!info?.step.idle,vision:false}); }
// 完整一格（跳播、切換模式、錄影都用這個）
function render() { beforeMain(); workspace.renderOverview(renderer,scene); afterMain(); }
function afterMain() {
  camera.updateMatrixWorld();   // 疊圖投影要用這一格的相機（迴圈中主畫面在 stage 內最後才畫）
  if(['meniscus','titration','liquid','bottles','balance','decap','pipette','sampler','follow'].includes(visionView)) fullProcessVision.draw(camera,canvas.getBoundingClientRect(),liquidResults(lab,info,T,visionView)); else fullProcessVision.hide();
  const p=activeProduct();processCamera.position.copy(p).add(new THREE.Vector3(-150,180,230));processCamera.lookAt(p);processCamera.updateMatrixWorld(true);
  workspace.renderCamera({renderer,scene,camera:processCamera,vision,title:'製程觀察 · 液面示意（虛擬相機）',result:'跟隨目前處理的樣品，非實拍量測',marks:liquidResults(lab,info,T,info.sampler.job&&info.step.idle?'titration':visionView)});
}
const workspace=createViewerWorkspace({camera,controls,canvas,resize:stage.resize,getFocus:activeProduct,
  focusOffset:[-150,180,230],focusNear:.5,onFocus:()=>{setElectricalCutaway(scene,false);stage.goTo(camera.position.toArray(),controls.target.toArray(),true);liquidTrack=null;follow=false;visionView='focus';document.querySelectorAll('.views button').forEach(b=>b.classList.remove('selected'));}});
const electrical=createElectricalInspector({scene,camera,controls,canvas,onEnter:()=>setView('electrical',true),onExit:()=>setView('iso',true),title:'AutomaticAcid-BaseTitration'});
// 每格：stage 先推進視角轉場 → 時間推進（手臂等待分析時可再加速 10 倍）、跟隨 → HUD 與疊圖 → stage 做 controls.update() 與主畫面渲染
function tick(dt) {
  player.update(info?.step.idle && ui.autoSpeed.checked ? dt * 10 : dt);
  if (follow) followCam(dt);
  camera.lookAt(controls.target);   // 與 controls.update() 的朝向一致，讓本格疊圖對齊
  beforeMain(); afterMain();
}
setView(qp.get('view') || 'iso', true); stage.resize();
if (qp.get('view') === 'follow') { project.apply(T); project.robot.getTcpWorld('grip', _tcp); controls.target.copy(_tcp); camera.position.copy(_tcp).add(new THREE.Vector3(260, 420, 620)); }
exposeSim({ plan, seekTo, get T() { return T; }, setView, views: [...Object.keys(VIEWS), 'meniscus', 'follow'], total, play, pause });
$('loading').classList.add('hide'); render();
stage.loop(tick);   // ?movie 時 stage 不啟動迴圈，由錄影程式逐格驅動

// ---------------------------------------------------------------- 錄影（?movie）：core/movie/movie.js 逐格取樣並呼叫 render()
if (qp.has('movie')) {
  pause();
  const { installMovie } = await import('@core/movie/movie.js');
  installMovie({
    project: 'AutomaticAcid-BaseTitration', scene, renderer, camera, controls, render, setView, total,
    steps: plan.steps,
    sample(t) { T = t; info = project.apply(T); },
    // 秤重相關步驟對準天平秤盤，其餘跟隨目前處理的杯／瓶
    focus: () => { const bal = /天平|秤重|歸零|讀重|推把/.test(info.step.label); if (bal) return new THREE.Vector3(ST.balance.x, Y0 + ST.balance.pan + 45, ST.balance.z); return activeProduct(); },
    offset: [-420, 470, 680],
  });
}
