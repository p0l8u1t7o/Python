import {createElectricalInspector} from '@core/electrical/electrical-inspector.js';
import {setElectricalCutaway} from '@core/electrical/electrical-cabinet.js';
import { createViewerWorkspace } from '@core/ui/viewer-workspace.js';
import { routingLegend } from '@core/electrical/cable-routing.js';
routingLegend();
// 主程式：場景、時間軸（動作序列）、UI
import * as THREE from 'three';
import { createVisionOverlay } from '@core/ui/vision-overlay.js';
import { notebookResults } from './vision-results.js';
const vision = createVisionOverlay();
const fullSensorVision = createVisionOverlay();
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { SKUS } from './notebook.js';
import { LAYOUT } from './cell.js';
import { smooth } from './sequence.js';
import { createProject, DEFAULT_SKU } from './project.js';

// ---------------------------------------------------------------- SKU（由網址參數或選單決定；換 SKU 重建整條時間軸）
const qp = new URLSearchParams(location.search);
const SKU = qp.get('sku') && SKUS[qp.get('sku')] ? qp.get('sku') : DEFAULT_SKU;

// ---------------------------------------------------------------- 場景
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: qp.get('aa') !== '0', powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = qp.get('shadow') ? THREE.PCFShadowMap : THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.0;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);
scene.fog = new THREE.Fog(0x0d1117, 7000, 14000);
const pmrem = new THREE.PMREMGenerator(renderer);
const room=new RoomEnvironment(renderer);room.traverse(o=>{if(o.isPointLight)o.intensity=240;});
scene.environment = pmrem.fromScene(room, 0.04).texture;room.dispose();pmrem.dispose();

const camera = new THREE.PerspectiveCamera(42, 1, 10, 30000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 150; controls.maxDistance = 10000;

scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x2a2f36, 0.55));
const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(-2500, 4200, 2600);
sun.castShadow = qp.get('shadow') !== '0'; sun.shadow.mapSize.set(+(qp.get('shadow') || 2048), +(qp.get('shadow') || 2048));
Object.assign(sun.shadow.camera, { left: -3500, right: 3500, top: 3500, bottom: -3500, near: 500, far: 12000 }); sun.shadow.bias = -0.0004;
scene.add(sun);
sun.shadow.normalBias=.08;
const detailLight=new THREE.DirectionalLight(0xfff8ef,.65);detailLight.castShadow=renderer.shadowMap.enabled;
detailLight.shadow.mapSize.set(2048,2048);Object.assign(detailLight.shadow.camera,{left:-240,right:240,top:230,bottom:-230,near:50,far:1500});
detailLight.shadow.bias=-.00001;detailLight.shadow.normalBias=.035;scene.add(detailLight,detailLight.target);
const fill = new THREE.DirectionalLight(0x9fb8ff, 0.5); fill.position.set(2500, 2000, -2500); scene.add(fill);

// ---------------------------------------------------------------- 物件（與 core 統一檢查共用 project.js）
const project = createProject({ scene, sku: SKU });
const { cell, nb, carrier, robot, sequence, roiBox, seamLaser, trail, trailGeo, trailPos, trailN } = project;
const [zoneSlow, zoneSlowE, zoneKeep] = project.zones;

// 手臂路徑（播放時累積，跳播時清空）
let trailCount = 0;
function pushTrail(p) { if (trailCount >= trailN) { trailPos.copyWithin(0, 3); trailCount = trailN - 1; } trailPos.set([p.x, p.y, p.z], trailCount * 3); trailCount++; trailGeo.attributes.position.needsUpdate = true; trailGeo.setDrawRange(0, trailCount); }

// 3D 標籤
const labels = [];
function addLabel(text, getPos) { const el = document.createElement('div'); el.className = 'label3d'; el.innerHTML = text; document.getElementById('app').appendChild(el); labels.push({ el, getPos }); return el; }
const sName = ['<b>S0</b> 進料升降堆料架', '<b>S1</b> 閉合外觀站', '<b>S2</b> 側邊護蓋站', '<b>S3</b> 翻面檢測站', '<b>S4</b> 出料升降堆料架'];
LAYOUT.stationX.forEach((x, i) => addLabel(sName[i], () => new THREE.Vector3(x, LAYOUT.conveyorTop + (i === 0 || i === 4 ? 1100 : 330), 0)));
addLabel('DENSO VM-60B1＋第七軸滑軌', () => new THREE.Vector3(robot.q.rail, 250, LAYOUT.railZ));
addLabel('頂視 20MP＋穹頂光', () => cell.topCamPos.clone().add(new THREE.Vector3(0, 120, 0)));
addLabel('SN 條碼讀取器', () => cell.snReaderPos.clone().add(new THREE.Vector3(0, -70, 0)));
addLabel('翻轉夾持治具', () => new THREE.Vector3(LAYOUT.stationX[3] + 380, 1560, -270));
addLabel('力覺末端', () => robot.getTcpWorld('cam').add(new THREE.Vector3(0, 90, 0)));

const ui=Object.fromEntries(['action','substep','forceBar','forceVal','zoneDot','zoneTxt','checklist','chkCount','playBtn','restartBtn','speed','speedVal','showZone','showPath','progBar','clock','sku','timeline','stepSelect','previous','next','signals','poseError','phase','result','exportBtn','showGuards','showLabels','cycleTime'].map(id=>[id,document.getElementById(id)]));
let S,playing=!qp.has('pause'),T=0,speed=1,current,waiting=0,fault='',curStation=-1;
const CAPTURE=qp.has('capture');
// 時間 → 場景一律經由 project：apply（跳播，手臂直接到位）或 sample（播放，手臂由 robot.update 追上）
function go(c){current=c;S=c.state;return c;}
const total=project.total,stationStart=sequence.stationStart;
ui.timeline.max=total;ui.cycleTime.textContent=`配方 ${Math.round(total)} s ＋到位等待`;
ui.sku.value=SKU;ui.sku.onchange=()=>{const q=new URLSearchParams(location.search);q.set('sku',ui.sku.value);location.search=q.toString();};
sequence.steps.forEach((s,i)=>{const opt=document.createElement('option');opt.value=i;opt.textContent=`S${s.station} · ${s.action}`;ui.stepSelect.appendChild(opt);});
const checklist=[
  [['sn','工單配方 / 底面 SN'],['locate','載具定位與四角夾緊']],
  [['lid','閉合外蓋 Logo / 麥拉 / 螺絲'],['sides','四側圖示 / 門扣 / 按鍵外觀'],['seam','指定接縫輪廓記錄']],
  nb.doors.map(d=>[d.def.id,d.def.name+(d.def.sealed?'：外觀與封印':'：開門 / 取像 / 關門鎖定')]),
  [['flip','夾持交接 / 抬升 / 翻面'],['print','底面法規白字'],['labels','SN / 安規 / 鈕扣電池警語'],['dock','外露 Docking 接點'],['screws','分區螺絲 / 腳墊 / 維修蓋'],['return','翻回 / 落座 / 夾持交接']],
  [['judge','第一階段結果彙整'],['stack','出料托叉承重 / 堆疊']]
];
const views={
  electrical: [[-1000,530,1550],[-1000,330,20]],
  wiring: [[1200,2300,-2700],[-350,1050,-350]],
  iso:[[3300,2750,3900],[0,650,-100]],robot:[[1050,1400,1150],[-100,870,-250]],
  stacker:[[-2850,1800,1650],[-1850,990,0]],flip:[[1620,1340,1120],[1000,980,0]],
  top:[[0,5300,500],[0,750,0]],product:[[310,1120,360],[0,835,0]],door:[[-480,990,470],[-130,850,0]]
};
let selectedView='iso',camAnim=null,viewDoorId='';
function setView(name,instant=false){
  workspace.stopFollowing(); setElectricalCutaway(scene,name==='electrical');
  if(!views[name]&&name!=='sensor')return;selectedView=name;controls.enabled=name!=='sensor';
  document.querySelectorAll('.views button').forEach(b=>b.classList.toggle('selected',b.dataset.view===name));
  if(name==='sensor'){camAnim=null;return;}
  let [p,t]=views[name].map(a=>new THREE.Vector3(...a));
  if(name==='door'||name==='product'){p.x+=S.palletX;t.x+=S.palletX;p.y+=S.lift;t.y+=S.lift;}
  if(name==='door'){
    const d=nb.doors.find(d=>S.action.startsWith(d.def.id+' '));viewDoorId=d?.def.id||'';
    if(d){t=d.centerWorld();const n=d.normalWorld(),tangent=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),n);p=t.clone().addScaledVector(n,250).addScaledVector(tangent,150).add(new THREE.Vector3(0,120,0));}
  }
  if(instant){camAnim=null;camera.position.copy(p);controls.target.copy(t);camera.lookAt(t);controls.update();}
  else camAnim={p0:camera.position.clone(),t0:controls.target.clone(),p,t,u:0};
  document.querySelectorAll('.views button').forEach(b=>b.classList.toggle('selected',b.dataset.view===name));
}
document.querySelectorAll('.views button').forEach(b=>b.onclick=()=>{
  if(b.dataset.view==='sensor'){playing=false;ui.playBtn.textContent='▶ 播放';}
  if(b.dataset.view==='sensor'&&!S.flashTool){
    const exposures=sequence.steps.filter(s=>s.exposure&&s.end.flashTool);
    const e=exposures.find(s=>s.start>=T)||exposures[0];if(e){playing=false;seekTo(e.start+e.dur*.5);}
  }
  setView(b.dataset.view);
});
function seekTo(sec,snap=true){
  T=Number.isFinite(sec)?THREE.MathUtils.clamp(sec,0,total):0;go(snap?project.apply(T):project.sample(T));
  waiting=0;fault='';trailCount=0;trailGeo.setDrawRange(0,0);
  ui.playBtn.textContent=playing?'⏸ 暫停':'▶ 播放';render();
}
ui.playBtn.onclick=()=>{if(T>=total)seekTo(0);playing=!playing;fault='';waiting=0;ui.playBtn.textContent=playing?'⏸ 暫停':'▶ 播放';};
ui.restartBtn.onclick=()=>seekTo(0);
ui.previous.onclick=()=>{playing=false;seekTo(sequence.steps[Math.max(0,current.index-1)].start);};
ui.next.onclick=()=>{playing=false;seekTo(sequence.steps[Math.min(sequence.steps.length-1,current.index+1)].start);};
ui.stepSelect.onchange=()=>{playing=false;seekTo(sequence.steps[+ui.stepSelect.value].start);};
ui.timeline.oninput=()=>{playing=false;seekTo(+ui.timeline.value);};
ui.speed.oninput=()=>{speed=+ui.speed.value;ui.speedVal.textContent=speed+'×';};
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
  const e=robot.error(),arrived=project.arrived(current);
  // 光源、雷射、ROI 框、接縫雷射線、力覺色環、三色燈與 apply(t) 用同一段程式
  project.effects(current,{arrived,capture:CAPTURE,result:ui.result.value,fault});
  const force=arrived?S.force:0;
  cell.occluders.visible=ui.showGuards.checked;
  zoneSlow.visible=zoneSlowE.visible=zoneKeep.visible=ui.showZone.checked;trail.visible=ui.showPath.checked;
  ui.action.textContent=S.action;ui.substep.textContent=S.sub;
  ui.phase.textContent=fault|| (T>=total?'COMPLETE · 本台完成':waiting>0?'等待手臂到位':playing?'AUTO · 執行中':'HOLD · 暫停');ui.phase.classList.toggle('fault',!!fault);
  ui.forceBar.style.width=(force/12*100)+'%';ui.forceVal.textContent=force.toFixed(1)+' N';
  ui.zoneTxt.textContent=S.zone==='contact'?'接觸動作 · 模擬力值':S.zone==='slow'?'減速接近 · ≤50 mm/s':'自由移動 / 工位保持';
  ui.zoneDot.className='dot '+(S.zone==='contact'?'contact':S.zone==='slow'?'slow':'');
  ui.poseError.textContent=`TCP ${e.position.toFixed(2)} mm · ${e.angle.toFixed(1)}° · 軸 ${robot.q.rail.toFixed(0)} mm`;
  [...ui.signals.children].forEach((el,i)=>el.classList.toggle('on',signals[i][1]()));
  if(curStation!==S.station){curStation=S.station;ui.checklist.innerHTML='';checklist[curStation].forEach(([id,txt])=>{const li=document.createElement('li');li.dataset.id=id;li.innerHTML=`<span class="box"></span><span>${txt}</span>`;ui.checklist.appendChild(li);});}
  let done=0;for(const li of ui.checklist.children){const ok=current.completed.has(li.dataset.id);li.classList.toggle('done',ok);li.querySelector('.box').textContent=ok?'✓':'';if(ok)done++;}
  ui.chkCount.textContent=done+' / '+checklist[S.station].length;
  document.querySelectorAll('#stations .st').forEach(b=>b.classList.toggle('active',+b.dataset.st===S.station));
  ui.timeline.value=T;ui.stepSelect.value=current.index;ui.progBar.style.width=T/total*100+'%';
  ui.clock.textContent=`${Math.floor(T/60).toString().padStart(2,'0')}:${(T%60).toFixed(1).padStart(4,'0')}`;
  for(const l of labels){const p=l.getPos().project(camera),visible=ui.showLabels.checked&&p.z<1&&Math.abs(p.x)<.98&&Math.abs(p.y)<.83;l.el.style.display=visible?'block':'none';if(visible){l.el.style.left=canvas.offsetLeft+(p.x*.5+.5)*canvas.clientWidth+'px';l.el.style.top=canvas.offsetTop+(-p.y*.5+.5)*canvas.clientHeight+'px';}}
  document.getElementById('diagnostics').textContent=JSON.stringify({time:T,total,step:current.index,station:S.station,action:S.action,poseError:e,force,playing,waiting,fault,doors:S.doors,flip:S.flip,lift:S.lift,clamp:S.clamp,cradleClamp:S.cradleClamp});
}
function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
window.addEventListener('resize',resize);
function render(){
  drawHud();workspace.follow();electrical.update({time:T,playing,action:S.action,motion:true,vision:!!(S.flashTool||S.flashTop||S.flashUp||S.flashDown||S.flashSn)});detailLight.target.position.copy(carrier.position);detailLight.position.copy(carrier.position).add(new THREE.Vector3(-260,700,320));
  const caption=document.getElementById('sensorCaption'),sensor=selectedView==='sensor';caption.hidden=!sensor;fullSensorVision.hide();
  const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setScissorTest(false);renderer.setViewport(0,0,w,h);
  const hidden=[roiBox,zoneSlow,zoneSlowE,zoneKeep,trail],visible=hidden.map(o=>o.visible);
  if(sensor){
    hidden.forEach(o=>o.visible=false);labels.forEach(l=>l.el.style.display='none');
    const ph=Math.min(h,w/1.5),pw=ph*1.5;renderer.clear();renderer.setViewport((w-pw)/2,(h-ph)/2,pw,ph);renderer.render(scene,robot.inspectionCam);
    caption.textContent='手臂鏡頭 · 3:2 完整視野 · 模擬影像';
  }else workspace.renderOverview(renderer,scene);
  hidden.forEach(o=>o.visible=false);
  const e=robot.error(),exposure=S.flashTool>0&&e.position<2&&e.angle<3&&e.rail<2;
  if(sensor){const rect=canvas.getBoundingClientRect(),ph=Math.min(h,w/1.5),pw=ph*1.5;fullSensorVision.draw(robot.inspectionCam,{left:rect.left+(w-pw)/2,top:rect.top+(h-ph)/2,width:pw,height:ph},notebookResults(nb,S,exposure,T));}
  workspace.renderCamera({renderer,scene,camera:robot.inspectionCam,vision,title:'手臂相機 · 外觀檢測',result:exposure?'本幀取像':'即時預覽／移動中',marks:notebookResults(nb,S,exposure,T)});
  renderer.setViewport(0,0,w,h);hidden.forEach((o,i)=>o.visible=visible[i]);
}
const workspace=createViewerWorkspace({camera,controls,canvas,resize,focusOccluders:[cell.occluders],getFocus:()=>carrier.getWorldPosition(new THREE.Vector3()),
  focusOffset:[-360,340,470],onFocus:()=>{setElectricalCutaway(scene,false);camAnim=null;selectedView='focus';controls.enabled=true;document.querySelectorAll('.views button').forEach(b=>b.classList.remove('selected'));}});
const electrical=createElectricalInspector({scene,camera,controls,canvas,onEnter:()=>setView('electrical',true),onExit:()=>setView('iso',true),title:'MilitaryGradePC'});
const clock=new THREE.Clock();
function tick(dt){
  // Work at bounded substeps, so changing playback speed changes every axis equally.
  if(!playing)return;
  if(S.station===4&&ui.result.value==='NG'){fault='NG · 停留 S4 等待人工覆判';playing=false;ui.playBtn.textContent='▶ 播放';return;}
  const e=robot.error(),s=current.step,end=s.start+s.dur;
  const blocked=(T>=end-1e-7||(s.contact&&e.position>3))&&(e.position>1.5||e.angle>3||e.rail>2);
  if(blocked){waiting+=dt;if(waiting>12){fault='到位逾時 · 請檢查 TCP 姿態';playing=false;ui.playBtn.textContent='▶ 播放';}}
  else{
    waiting=0;
    if(T>=total-1e-7){playing=false;ui.playBtn.textContent='▶ 播放';}
    else {T=T>=end-1e-7?Math.min(total,end+1e-6):Math.min(end,T+dt);go(project.sample(T>=end-1e-7&&T<=end?Math.max(s.start,end-1e-8):T));}
  }
  robot.update(dt);
}
function frame(){
  requestAnimationFrame(frame);const dt=Math.min(clock.getDelta(),.05);
  if(CAPTURE)return;
  const n=Math.max(1,Math.ceil(dt*speed/.025));for(let k=0;k<n;k++)tick(dt*speed/n);
  if(playing&&ui.showPath.checked)pushTrail(robot.getTcpWorld(robot.goal.tcp));
  const d=nb.doors.find(d=>S.action.startsWith(d.def.id+' '));if(selectedView==='door'&&d&&d.def.id!==viewDoorId)setView('door');
  if(camAnim){camAnim.u=Math.min(1,camAnim.u+dt*1.4);camera.position.lerpVectors(camAnim.p0,camAnim.p,smooth(camAnim.u));controls.target.lerpVectors(camAnim.t0,camAnim.t,smooth(camAnim.u));if(camAnim.u===1)camAnim=null;}
  controls.update();render();
}
go(project.apply(0));setView('iso',true);resize();ui.playBtn.textContent=playing?'⏸ 暫停':'▶ 播放';
window.sim={jump(st,view,off=0){seekTo((stationStart[THREE.MathUtils.clamp(Math.trunc(st)||0,0,4)]||0)+off);if(view)setView(view,true);},seekTo,pause(){playing=false;ui.playBtn.textContent='▶ 播放';},play(){playing=true;ui.playBtn.textContent='⏸ 暫停';},get state(){return S;},get T(){return T;},setView,views:[...Object.keys(views),'sensor'],project,robot,total,stationStart,steps:sequence.steps};
if(qp.has('st'))window.sim.jump(+qp.get('st'),qp.get('view'),+(qp.get('t')||0));else if(qp.has('view'))setView(qp.get('view'),true);
if(qp.has('step')){playing=false;seekTo(sequence.steps[THREE.MathUtils.clamp(+qp.get('step')||0,0,sequence.steps.length-1)].start);if(qp.has('view'))setView(qp.get('view'),true);}
if(qp.has('cam')){const a=qp.get('cam').split(',').map(Number);if(a.length===6&&a.every(Number.isFinite)){camera.position.set(...a.slice(0,3));controls.target.set(...a.slice(3));controls.update();}}
document.getElementById('loading').classList.add('hide');render();frame();
// Capture uses the same absolute mechanical sequence as interactive playback.
if(CAPTURE){
  const {installVideo}=await import('./video.js');
  ui.showGuards.checked=false;ui.showLabels.checked=false;
  window.capture=installVideo({steps:sequence.steps,renderer,camera,controls,render,nb,getState:()=>S,sample(time){T=time;go(project.apply(time,{capture:true}));}});
}
