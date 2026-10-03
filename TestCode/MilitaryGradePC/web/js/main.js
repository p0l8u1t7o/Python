import {createElectricalInspector} from '@core/electrical/electrical-inspector.js';
import {setElectricalCutaway} from '@core/electrical/electrical-cabinet.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { routingLegend } from '@core/electrical/cable-routing.js';
routingLegend();
// 主程式：舞台（core/ui/stage.js）＋播放列（core/ui/player.js）＋到位閘門（core/anim/arrival.js）＋本站的視角、面板與錄影
import * as THREE from 'three';
import { createVisionOverlay } from '@core/ui/vision-overlay.js';
import { notebookResults } from './vision-results.js';
const vision = createVisionOverlay();
const fullSensorVision = createVisionOverlay();
import { createStage, exposeSim } from '@core/ui/stage.js';
import { createPlayer } from '@core/ui/player.js';
import { createArrivalGate } from '@core/anim/arrival.js';
import { SKUS } from './notebook.js';
import { LAYOUT } from './cell.js';
import { createProject, DEFAULT_SKU } from './project.js';
import { ARRIVAL } from './sequence.js';

// ---------------------------------------------------------------- SKU（由網址參數或選單決定；換 SKU 重建整條時間軸）
const qp = new URLSearchParams(location.search);
const SKU = qp.get('sku') && SKUS[qp.get('sku')] ? qp.get('sku') : DEFAULT_SKU;

// ---------------------------------------------------------------- 場景（共用舞台 core/ui/stage.js）
// 本站場景約 7 m、近裁切面 10 mm，維持一般深度緩衝（logDepth: false；?movie 時 stage 一律開啟對數深度）
const canvas = document.getElementById('c');
const stage = createStage({
  canvas, qp, exposure: 1.0, background: 0x0d1117, fog: [7000, 14000], logDepth: false,
  camera: { fov: 42, near: 10, far: 30000 },
  controls: { enableDamping: true, dampingFactor: .08, maxPolarAngle: Math.PI * .49, minDistance: 150, maxDistance: 10000 },
  envLight: 240, envBlur: .04,
  hemi: { sky: 0xbfd4ff, ground: 0x2a2f36, intensity: .55 },
  sun: { color: 0xffffff, intensity: 1.6, position: [-2500, 4200, 2600], target: [0, 0, 0],
    shadow: { mapSize: 2048, camera: { left: -3500, right: 3500, top: 3500, bottom: -3500, near: 500, far: 12000 }, bias: -.0004, normalBias: .08 } },
  fill: { color: 0x9fb8ff, intensity: .5, position: [2500, 2000, -2500] },
  // 載具特寫光：位置與照射點每格跟著載具（render 內更新），陰影範圍只涵蓋筆電周圍
  extraLights: [{ color: 0xfff8ef, intensity: .65, position: [0, 1, 0], target: [0, 0, 0],
    shadow: { mapSize: 2048, camera: { left: -240, right: 240, top: 230, bottom: -230, near: 50, far: 1500 }, bias: -.00001, normalBias: .035 } }],
});
const { renderer, scene, camera, controls } = stage;
const detailLight = stage.lights.extra[0];
// 舊網址參數相容：?shadow=4096 之類給數字時改用 PCF 陰影並放大主光陰影貼圖（?shadow=0 仍為關閉）
if (qp.get('shadow') && qp.get('shadow') !== '0') { renderer.shadowMap.type = THREE.PCFShadowMap; stage.lights.sun.shadow.mapSize.set(+qp.get('shadow'), +qp.get('shadow')); }

// ---------------------------------------------------------------- 物件（與 core 統一檢查共用 project.js）
const project = createProject({ scene, sku: SKU });
const { cell, nb, carrier, robot, sequence, roiBox, seamLaser, trail, trailGeo, trailPos, trailN } = project;
const [zoneSlow, zoneSlowE, zoneKeep] = project.zones;

// 手臂路徑（播放時累積，跳播時清空）
let trailCount = 0;
function pushTrail(p) { if (trailCount >= trailN) { trailPos.copyWithin(0, 3); trailCount = trailN - 1; } trailPos.set([p.x, p.y, p.z], trailCount * 3); trailCount++; trailGeo.attributes.position.needsUpdate = true; trailGeo.setDrawRange(0, trailCount); }

// 3D 標籤（stage.addLabel；畫布在頁面中的位移由 stage 處理）
const sName = ['<b>S0</b> 進料升降堆料架', '<b>S1</b> 閉合外觀站', '<b>S2</b> 側邊護蓋站', '<b>S3</b> 翻面檢測站', '<b>S4</b> 出料升降堆料架'];
LAYOUT.stationX.forEach((x, i) => stage.addLabel(sName[i], () => new THREE.Vector3(x, LAYOUT.conveyorTop + (i === 0 || i === 4 ? 1100 : 330), 0)));
stage.addLabel('DENSO VM-60B1＋第七軸滑軌', () => new THREE.Vector3(robot.q.rail, 250, LAYOUT.railZ));
stage.addLabel('頂視 20MP＋穹頂光', () => cell.topCamPos.clone().add(new THREE.Vector3(0, 120, 0)));
stage.addLabel('SN 條碼讀取器', () => cell.snReaderPos.clone().add(new THREE.Vector3(0, -70, 0)));
stage.addLabel('翻轉夾持治具', () => new THREE.Vector3(LAYOUT.stationX[3] + 380, 1560, -270));
stage.addLabel('力覺末端', () => robot.getTcpWorld('cam').add(new THREE.Vector3(0, 90, 0)));

const ui=Object.fromEntries(['action','substep','forceBar','forceVal','zoneDot','zoneTxt','checklist','chkCount','playBtn','speed','showZone','showPath','progBar','sku','signals','poseError','phase','result','exportBtn','showGuards','showLabels','cycleTime'].map(id=>[id,document.getElementById(id)]));
// T 由播放列（player）推進；S／current 為目前取樣結果
let S,T=0,current,curStation=-1,ready=false,quiet=false;
const CAPTURE=qp.has('capture');
// 時間 → 場景一律經由 project：apply（跳播，手臂直接到位）或 sample（播放，手臂由 robot.update 追上）
function go(c){current=c;S=c.state;return c;}
const total=project.total,stationStart=sequence.stationStart;
ui.cycleTime.textContent=`配方 ${Math.round(total)} s ＋到位等待`;
ui.sku.value=SKU;ui.sku.onchange=()=>{const q=new URLSearchParams(location.search);q.set('sku',ui.sku.value);location.search=q.toString();};
const checklist=[
  [['sn','工單配方 / 底面 SN'],['locate','載具定位與四角夾緊']],
  [['lid','閉合外蓋 Logo / 麥拉 / 螺絲'],['sides','四側圖示 / 門扣 / 按鍵外觀'],['seam','指定接縫輪廓記錄']],
  nb.doors.map(d=>[d.def.id,d.def.name+(d.def.sealed?'：外觀與封印':'：開門 / 取像 / 關門鎖定')]),
  [['flip','夾持交接 / 抬升 / 翻面'],['print','底面法規白字'],['labels','SN / 安規 / 鈕扣電池警語'],['dock','外露 Docking 接點'],['screws','分區螺絲 / 腳墊 / 維修蓋'],['return','翻回 / 落座 / 夾持交接']],
  [['judge','第一階段結果彙整'],['stack','出料托叉承重 / 堆疊']]
];
// ---------------------------------------------------------------- 視角：[相機位置, 注視點]，切換用 stage.goTo
const views={
  electrical: [[-1000,530,1550],[-1000,330,20]],
  wiring: [[1200,2300,-2700],[-350,1050,-350]],
  iso:[[3300,2750,3900],[0,650,-100]],robot:[[1050,1400,1150],[-100,870,-250]],
  stacker:[[-2850,1800,1650],[-1850,990,0]],flip:[[LAYOUT.stationX[3]+620,1340,1120],[LAYOUT.stationX[3],980,0]],
  top:[[0,5300,500],[0,750,0]],product:[[310,1120,360],[0,835,0]],door:[[-480,990,470],[-130,850,0]]
};
let selectedView='iso',viewDoorId='';
function setView(name,instant=false){
  workspace.stopFollowing(); setElectricalCutaway(scene,name==='electrical');
  if(!views[name]&&name!=='sensor')return;selectedView=name;controls.enabled=name!=='sensor';
  document.querySelectorAll('.views button').forEach(b=>b.classList.toggle('selected',b.dataset.view===name));
  if(name==='sensor'){stage.cancelTween();return;}   // 手臂取景：相機不再被轉場拉走
  let [p,t]=views[name].map(a=>new THREE.Vector3(...a));
  if(name==='door'||name==='product'){p.x+=S.palletX;t.x+=S.palletX;p.y+=S.lift;t.y+=S.lift;}
  if(name==='door'){
    const d=nb.doors.find(d=>S.action.startsWith(d.def.id+' '));viewDoorId=d?.def.id||'';
    if(d){t=d.centerWorld();const n=d.normalWorld(),tangent=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),n);p=t.clone().addScaledVector(n,250).addScaledVector(tangent,150).add(new THREE.Vector3(0,120,0));}
  }
  stage.goTo(p.toArray(),t.toArray(),instant);
}
document.querySelectorAll('.views button').forEach(b=>b.onclick=()=>{
  if(b.dataset.view==='sensor')player.pause();
  if(b.dataset.view==='sensor'&&!S.flashTool){
    const exposures=sequence.steps.filter(s=>s.exposure&&s.end.flashTool);
    const e=exposures.find(s=>s.start>=T)||exposures[0];if(e)seekTo(e.start+e.dur*.5);
  }
  setView(b.dataset.view);
});
// 跳到時間 sec（手臂直接到位、清除到位等待與 TCP 軌跡）；播放列、站別按鈕與 window.sim 共用
const seekTo=sec=>player.seekTo(sec);
// 開始播放：清除故障與到位等待（播放列在終點按播放時會自己跳回起點）
function play(){gate.reset();player.play();}
document.querySelectorAll('#stations .st').forEach(b=>b.onclick=()=>{seekTo(stationStart[+b.dataset.st]);if(['product','door'].includes(selectedView))setView(selectedView,true);});
function exportReport(){
  const report={mode:'SIMULATION',workOrder:'RMK12608372',sku:SKU,sn:'DEMO-0001',time:T,plannedCycle:total,result:T>=stationStart[4]?ui.result.value:'PENDING',
    completed:[...current.completed],pending:checklist.flat().filter(([id])=>!current.completed.has(id)).map(([id])=>id),
    exposureEvents:sequence.steps.filter(s=>s.exposure&&s.start+s.dur<=T).map(s=>({station:s.station,action:s.action,plannedTime:s.start,simulation:true})),
    scope:'Closed unit / external cosmetic QC only',mesConnected:false,physicalMeasurement:false,
    sources:['QII-RSBU-P5-V110系列_R00-002.pdf','RMK12608372(LFF126071920).pdf'],motion:robot.error()};
  const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='QC-DEMO-0001.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
ui.exportBtn.onclick=exportReport;
const signals=[['載具到位',()=>S.located],['載具夾緊',()=>S.clamp>.99],['翻轉夾緊',()=>S.cradleClamp>.99],['升降到位',()=>S.lift===0||S.lift===LAYOUT.flipLift],['取像頭退出',()=>S.s1Head<.001],['所有門關閉',()=>S.doors.every(d=>d.open<.001&&d.latch<.001)],['工具到位',()=>{const e=robot.error();return e.position<1.5&&e.angle<2&&e.rail<1;}]];
signals.forEach(([name])=>{const row=document.createElement('div');row.innerHTML=`<i></i><span>${name}</span>`;ui.signals.appendChild(row);});
function drawHud(){
  const e=robot.error(),arrived=project.arrived(current),playing=player.playing;
  // 光源、雷射、ROI 框、接縫雷射線、力覺色環、三色燈與 apply(t) 用同一段程式
  project.effects(current,{arrived,capture:CAPTURE,result:ui.result.value,fault:gate.fault});
  const force=arrived?S.force:0;
  cell.occluders.visible=ui.showGuards.checked;
  zoneSlow.visible=zoneSlowE.visible=zoneKeep.visible=ui.showZone.checked;trail.visible=ui.showPath.checked;
  ui.action.textContent=S.action;ui.substep.textContent=S.sub;
  ui.phase.textContent=gate.fault|| (T>=total?'COMPLETE · 本台完成':gate.waiting>0?'等待手臂到位':playing?'AUTO · 執行中':'HOLD · 暫停');ui.phase.classList.toggle('fault',!!gate.fault);
  ui.forceBar.style.width=(force/12*100)+'%';ui.forceVal.textContent=force.toFixed(1)+' N';
  ui.zoneTxt.textContent=S.zone==='contact'?'接觸動作 · 模擬力值':S.zone==='slow'?'減速接近 · ≤50 mm/s':'自由移動 / 工位保持';
  ui.zoneDot.className='dot '+(S.zone==='contact'?'contact':S.zone==='slow'?'slow':'');
  ui.poseError.textContent=`TCP ${e.position.toFixed(2)} mm · ${e.angle.toFixed(1)}° · 軸 ${robot.q.rail.toFixed(0)} mm`;
  [...ui.signals.children].forEach((el,i)=>el.classList.toggle('on',signals[i][1]()));
  if(curStation!==S.station){curStation=S.station;ui.checklist.innerHTML='';checklist[curStation].forEach(([id,txt])=>{const li=document.createElement('li');li.dataset.id=id;li.innerHTML=`<span class="box"></span><span>${txt}</span>`;ui.checklist.appendChild(li);});}
  let done=0;for(const li of ui.checklist.children){const ok=current.completed.has(li.dataset.id);li.classList.toggle('done',ok);li.querySelector('.box').textContent=ok?'✓':'';if(ok)done++;}
  ui.chkCount.textContent=done+' / '+checklist[S.station].length;
  document.querySelectorAll('#stations .st').forEach(b=>b.classList.toggle('active',+b.dataset.st===S.station));
  // 時間軸、時鐘、步驟選單由播放列更新；這裡只畫進度條
  ui.progBar.style.width=T/total*100+'%';
  stage.updateLabels(ui.showLabels.checked&&selectedView!=='sensor');
  document.getElementById('diagnostics').textContent=JSON.stringify({time:T,total,step:current.index,station:S.station,action:S.action,poseError:e,force,playing,waiting:gate.waiting,fault:gate.fault,doors:S.doors,flip:S.flip,lift:S.lift,clamp:S.clamp,cradleClamp:S.cradleClamp});
}
// 完整一格：面板、主畫面（或手臂鏡頭全幅）、相機子畫面與疊圖（跳播、截圖、錄影直接呼叫；stage.loop 每格也用它繪製）
function render(){
  drawHud();workspace.follow();electrical.update({time:T,playing:player.playing,action:S.action,motion:true,vision:!!(S.flashTool||S.flashTop||S.flashUp||S.flashDown||S.flashSn)});detailLight.target.position.copy(carrier.position);detailLight.position.copy(carrier.position).add(new THREE.Vector3(-260,700,320));
  const caption=document.getElementById('sensorCaption'),sensor=selectedView==='sensor';caption.hidden=!sensor;fullSensorVision.hide();
  const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setScissorTest(false);renderer.setViewport(0,0,w,h);
  const hidden=[roiBox,zoneSlow,zoneSlowE,zoneKeep,trail],visible=hidden.map(o=>o.visible);
  if(sensor){
    hidden.forEach(o=>o.visible=false);
    const ph=Math.min(h,w/1.5),pw=ph*1.5;renderer.clear();renderer.setViewport((w-pw)/2,(h-ph)/2,pw,ph);renderer.render(scene,robot.inspectionCam);
    caption.textContent='手臂鏡頭 · 3:2 完整視野 · 模擬影像';
  }else workspace.renderOverview(renderer,scene);
  hidden.forEach(o=>o.visible=false);
  const e=robot.error(),exposure=S.flashTool>0&&e.position<2&&e.angle<3&&e.rail<2;
  if(sensor){const rect=canvas.getBoundingClientRect(),ph=Math.min(h,w/1.5),pw=ph*1.5;fullSensorVision.draw(robot.inspectionCam,{left:rect.left+(w-pw)/2,top:rect.top+(h-ph)/2,width:pw,height:ph},notebookResults(nb,S,exposure,T));}
  workspace.renderCamera({renderer,scene,camera:robot.inspectionCam,vision,title:'手臂相機 · 外觀檢測',result:exposure?'本幀取像':'即時預覽／移動中',marks:notebookResults(nb,S,exposure,T)});
  renderer.setViewport(0,0,w,h);hidden.forEach((o,i)=>o.visible=visible[i]);
}
const workspace=createViewerWorkspace({camera,controls,canvas,resize:stage.resize,focusOccluders:[cell.occluders],getFocus:()=>carrier.getWorldPosition(new THREE.Vector3()),
  focusOffset:[-360,340,470],onFocus:()=>{setElectricalCutaway(scene,false);stage.cancelTween();selectedView='focus';controls.enabled=true;document.querySelectorAll('.views button').forEach(b=>b.classList.remove('selected'));}});
const electrical=createElectricalInspector({scene,camera,controls,canvas,onEnter:()=>setView('electrical',true),onExit:()=>setView('iso',true),title:'MilitaryGradePC'});

// ---------------------------------------------------------------- 播放列（core/ui/player.js）＋到位閘門（core/anim/arrival.js）
// 到位規則 ARRIVAL 在 sequence.js（與 tools/verify.mjs 共用）：≤ 25 ms 子步、步驟終點等手臂到位、等超過 12 s 判到位逾時；S4 判 NG 時停住
const gate=createArrivalGate({...ARRIVAL,total,error:()=>robot.error(),step:()=>current.step,sample:t=>go(project.sample(t)),update:h=>robot.update(h),
  fault:()=>S.station===4&&ui.result.value==='NG'?'NG · 停留 S4 等待人工覆判':''});
// 事件選單用排程的 events。跳播（seek）走 project.apply（手臂直接到位）並清除到位等待與故障；連續播放由 gate.advance 推進時間、
// 以 project.sample 取樣並讓手臂以限速追上目標，apply 只記下時間
const player=createPlayer({total,qp,
  events:sequence.events.map(e=>({...e,label:`S${e.station} · ${e.label}`})),
  advance:gate.advance,
  apply(t,{seek}){
    T=t;
    if(seek){gate.reset();trailCount=0;trailGeo.setDrawRange(0,0);return go(project.apply(t,{capture:CAPTURE}));}
    return current;
  },
  // 跳播後重繪（連續播放由 stage.loop 每格繪製；錄影取樣時不重繪）
  onChange(t,s,{seek}){if(ready&&!quiet&&seek)render();}});
// 播放鍵：清除故障與到位等待（播放列自己處理播放／暫停與終點歸零）
ui.playBtn.addEventListener('click',()=>gate.reset());
// stage.loop 每格：frameTick(dt) → controls.update() → render()（主畫面＋相機子畫面＋疊圖）
function frameTick(dt){
  player.update(dt);
  if(player.playing&&ui.showPath.checked)pushTrail(robot.getTcpWorld(robot.goal.tcp));
  const d=nb.doors.find(d=>S.action.startsWith(d.def.id+' '));if(selectedView==='door'&&d&&d.def.id!==viewDoorId)setView('door');
}
// 錄影（?capture、?movie）依絕對時間取樣，不重繪（錄影程式自己呼叫 render）
function sampleQuiet(t){quiet=true;try{player.seekTo(t);}finally{quiet=false;}}
setView('iso',true);stage.resize();
const sim=exposeSim({jump(st,view,off=0){seekTo((stationStart[THREE.MathUtils.clamp(Math.trunc(st)||0,0,4)]||0)+off);if(view)setView(view,true);},seekTo,pause:()=>player.pause(),play,get state(){return S;},get T(){return T;},setView,views:[...Object.keys(views),'sensor'],project,robot,total,stationStart,steps:sequence.steps,events:sequence.events,player});
if(qp.has('st'))sim.jump(+qp.get('st'),qp.get('view'),+(qp.get('t')||0));else if(qp.has('view'))setView(qp.get('view'),true);
if(qp.has('step')){player.pause();seekTo(sequence.steps[THREE.MathUtils.clamp(+qp.get('step')||0,0,sequence.steps.length-1)].start);if(qp.has('view'))setView(qp.get('view'),true);}
if(qp.has('cam')){const a=qp.get('cam').split(',').map(Number);if(a.length===6&&a.every(Number.isFinite))stage.goTo(a.slice(0,3),a.slice(3),true);}
document.getElementById('loading').classList.add('hide');ready=true;render();
// ?capture=1 由 video.js 逐格繪製，不跑互動迴圈；?movie 時 stage 也不啟動迴圈（交給 installMovie）
if(!CAPTURE)stage.loop(frameTick,{render});
// Capture uses the same absolute mechanical sequence as interactive playback.
if(CAPTURE){
  const {installVideo}=await import('./video.js');
  ui.showGuards.checked=false;ui.showLabels.checked=false;
  window.capture=installVideo({steps:sequence.steps,renderer,camera,controls,render,nb,getState:()=>S,sample:sampleQuiet});
}

// ---------------------------------------------------------------- 展示影片（?movie）：依絕對時間逐格取樣，與 project.apply 同一路徑
if(qp.has('movie')&&!CAPTURE){
  player.pause();
  const {installMovie}=await import('@core/movie/movie.js');
  installMovie({project:'MilitaryGradePC',scene,renderer,camera,controls,render,setView,total,steps:sequence.steps,
    sample:sampleQuiet,
    focus:()=>carrier.getWorldPosition(new THREE.Vector3()),offset:[-650,620,1050]});
}
