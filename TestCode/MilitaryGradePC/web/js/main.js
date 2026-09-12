// 主程式：場景、時間軸（動作序列）、UI
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { createNotebook, NB, SKUS, selectSku } from './notebook.js';
import { createRobot } from './robot.js';
import { createCell, createPallet, LAYOUT } from './cell.js';
import { createSequence, smooth } from './sequence.js';

// ---------------------------------------------------------------- SKU（由網址參數或選單決定；換 SKU 重建整條時間軸）
const qp = new URLSearchParams(location.search);
const SKU = qp.get('sku') && SKUS[qp.get('sku')] ? qp.get('sku') : 'V110-STND';
const DOOR_DEFS = selectSku(SKU);

// ---------------------------------------------------------------- 場景
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: qp.get('aa') !== '0', powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = qp.get('shadow') !== '0'; renderer.shadowMap.type = qp.get('shadow') ? THREE.PCFShadowMap : THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.25;
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);
scene.fog = new THREE.Fog(0x0d1117, 7000, 14000);
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(42, 1, 10, 30000);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 150; controls.maxDistance = 10000;

scene.add(new THREE.HemisphereLight(0xbfd4ff, 0x2a2f36, 0.55));
const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(-2500, 4200, 2600);
sun.castShadow = qp.get('shadow') !== '0'; sun.shadow.mapSize.set(+(qp.get('shadow') || 2048), +(qp.get('shadow') || 2048));
Object.assign(sun.shadow.camera, { left: -3500, right: 3500, top: 3500, bottom: -3500, near: 500, far: 12000 }); sun.shadow.bias = -0.0004;
scene.add(sun);
const fill = new THREE.DirectionalLight(0x9fb8ff, 0.5); fill.position.set(2500, 2000, -2500); scene.add(fill);

// ---------------------------------------------------------------- 物件
const cell = createCell(scene);
const nb = createNotebook();
const notebook = nb.root;
// 載體（carrier）：機台的實際位置／翻轉由它決定（載具上、升降、翻轉治具中）
const carrier = new THREE.Group(); scene.add(carrier); carrier.add(notebook);
notebook.position.set(0, -NB.H / 2, 0);
const robot = createRobot();
robot.root.position.set(0, 0, LAYOUT.railZ);
scene.add(robot.root);

// 堆料架內的載具堆（進料 4 台待檢、出料 2 台已檢）
const stackIn = [], stackOut = [];
function stackedUnit() { const p = createPallet(true);p.setClamp(1); const n = createNotebook().root; n.position.y = LAYOUT.palletH + LAYOUT.padH + LAYOUT.footOffset; p.group.add(n); return p.group; }
for (let i = 0; i < 5; i++) { const u = stackedUnit(); cell.stackerIn.group.add(u); stackIn.push(u); }
for (let i = 0; i < 2; i++) { const u = stackedUnit(); cell.stackerOut.group.add(u); stackOut.push(u); }

// 防撞區
const zoneMat = new THREE.MeshBasicMaterial({ color: 0x4aa8ff, transparent: true, opacity: 0.08, depthWrite: false });
const zoneEdge = new THREE.LineBasicMaterial({ color: 0x4aa8ff, transparent: true, opacity: 0.35 });
const zoneSlow = new THREE.Mesh(new THREE.BoxGeometry(NB.W + 200, NB.H + 200, NB.D + 200), zoneMat); zoneSlow.position.y = NB.H / 2;
const zoneSlowE = new THREE.LineSegments(new THREE.EdgesGeometry(zoneSlow.geometry), zoneEdge); zoneSlowE.position.y = NB.H / 2;
const zoneKeep = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(NB.W + 60, NB.H + 60, NB.D + 60)), new THREE.LineBasicMaterial({ color: 0xff4d4d, transparent: true, opacity: 0.5 })); zoneKeep.position.y = NB.H / 2;
notebook.add(zoneSlow, zoneSlowE, zoneKeep);

// ROI 框
const roiMat = new THREE.LineBasicMaterial({ color: 0x3dd68c, transparent: true, opacity: 0.0 });
const roiBox = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), roiMat); scene.add(roiBox);
let roiTimer = 0;
function showROI(center, size, life = 0.9) { roiBox.position.copy(center); roiBox.scale.set(size.x, size.y, size.z); roiBox.quaternion.identity(); roiMat.opacity = 1; roiTimer = life; }
function showROIObj(obj, pad = 6, life = 0.9) { scene.updateMatrixWorld(true); const b = new THREE.Box3().setFromObject(obj); showROI(b.getCenter(new THREE.Vector3()), b.getSize(new THREE.Vector3()).addScalar(pad), life); }

// A 面接縫雷射線
const seamLaser = new THREE.Mesh(new THREE.PlaneGeometry(3, 16), new THREE.MeshBasicMaterial({ color: 0xff2a2a, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
seamLaser.rotation.x = -Math.PI / 2; scene.add(seamLaser);

// 手臂路徑
const trailN = 500; const trailPos = new Float32Array(trailN * 3); let trailCount = 0;
const trailGeo = new THREE.BufferGeometry(); trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPos, 3)); trailGeo.setDrawRange(0, 0);
const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0x7fd4ff, transparent: true, opacity: 0.6 })); scene.add(trail);
function pushTrail(p) { if (trailCount >= trailN) { trailPos.copyWithin(0, 3); trailCount = trailN - 1; } trailPos.set([p.x, p.y, p.z], trailCount * 3); trailCount++; trailGeo.attributes.position.needsUpdate = true; trailGeo.setDrawRange(0, trailCount); }

// 3D 標籤
const labels = [];
function addLabel(text, getPos) { const el = document.createElement('div'); el.className = 'label3d'; el.innerHTML = text; document.getElementById('app').appendChild(el); labels.push({ el, getPos }); return el; }
const sName = ['<b>S0</b> 進料升降堆料架', '<b>S1</b> 閉合外觀站', '<b>S2</b> 側邊護蓋站', '<b>S3</b> 翻面檢測站', '<b>S4</b> 出料升降堆料架'];
LAYOUT.stationX.forEach((x, i) => addLabel(sName[i], () => new THREE.Vector3(x, LAYOUT.conveyorTop + (i === 0 || i === 4 ? 1100 : 330), 0)));
addLabel('六軸手臂＋第七軸滑軌（概念尺寸）', () => new THREE.Vector3(robot.q.rail, 250, LAYOUT.railZ));
addLabel('頂視 20MP＋穹頂光', () => cell.topCamPos.clone().add(new THREE.Vector3(0, 120, 0)));
addLabel('SN 條碼讀取器', () => cell.snReaderPos.clone().add(new THREE.Vector3(0, -70, 0)));
addLabel('翻轉夾持治具', () => new THREE.Vector3(LAYOUT.stationX[3] + 380, 1560, -270));
addLabel('力覺末端', () => robot.getTcpWorld('cam').add(new THREE.Vector3(0, 90, 0)));

const ui=Object.fromEntries(['action','substep','forceBar','forceVal','zoneDot','zoneTxt','checklist','chkCount','playBtn','restartBtn','speed','speedVal','showZone','showPath','progBar','clock','sku','timeline','stepSelect','previous','next','signals','poseError','phase','result','exportBtn','showGuards','showLabels','cycleTime'].map(id=>[id,document.getElementById(id)]));
let S,playing=!qp.has('pause'),T=0,speed=1,current,waiting=0,fault='',curStation=-1;
const top=LAYOUT.conveyorTop+6+LAYOUT.palletH+LAYOUT.padH+LAYOUT.footOffset;
const CAPTURE=qp.has('capture');
function applyState(s){
  S=s;
  cell.pallet.group.position.set(s.palletX,LAYOUT.conveyorTop+6+s.palletLift,0);
  carrier.position.set(s.palletX,top+s.palletLift+s.lift+NB.H/2,0);carrier.rotation.x=Math.PI*s.flip;
  cell.pallet.setClamp(s.clamp);nb.doors.forEach((d,i)=>d.set(s.doors[i].open,s.doors[i].latch));
  const inBase=LAYOUT.conveyorTop+6;
  cell.stackerIn.lift.position.y=inBase-20+s.inLift;
  stackIn.forEach((u,i)=>u.position.set(0,inBase+(i+1)*LAYOUT.palletPitch+s.inStackY,0));
  cell.stackerOut.lift.position.y=inBase-20+s.outLift;
  stackOut.forEach((u,i)=>u.position.set(0,inBase+(i+1)*LAYOUT.palletPitch+s.outStackY,0));
  cell.stackerIn.setPush(s.pushIn);cell.stackerOut.setPush(s.pushOut);cell.stackerIn.setForks(s.inFork);cell.stackerOut.setForks(s.outFork);
  cell.cradle.lift.position.y=top+NB.H/2+s.cradleLift;cell.cradle.rot.rotation.x=Math.PI*s.flip;cell.cradle.setClamp(s.cradleClamp);
  cell.updateTransport(s.palletX,s.located);
  scene.updateMatrixWorld(true);
}
const sequence=createSequence({nb,robot,apply:applyState});
const total=sequence.total,stationStart=sequence.stationStart;
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
  iso:[[3300,2750,3900],[0,650,-100]],robot:[[1050,1400,1150],[-100,870,-250]],
  stacker:[[-2850,1800,1650],[-1850,990,0]],flip:[[1620,1340,1120],[1000,980,0]],
  top:[[0,5300,500],[0,750,0]],product:[[310,1120,360],[0,835,0]],door:[[-480,990,470],[-130,850,0]]
};
let selectedView='iso',camAnim=null,viewDoorId='';
function setView(name,instant=false){
  if(!views[name])return;selectedView=name;
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
document.querySelectorAll('.views button').forEach(b=>b.onclick=()=>setView(b.dataset.view));
function seekTo(sec,snap=true){
  T=Number.isFinite(sec)?THREE.MathUtils.clamp(sec,0,total):0;current=sequence.sample(T);
  if(snap)robot.snap();waiting=0;fault='';trailCount=0;trailGeo.setDrawRange(0,0);roiTimer=0;
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
const signals=[['載具到位',()=>S.located],['載具夾緊',()=>S.clamp>.99],['翻轉夾緊',()=>S.cradleClamp>.99],['升降到位',()=>S.lift===0||S.lift===LAYOUT.flipLift],['所有門關閉',()=>S.doors.every(d=>d.open<.001&&d.latch<.001)],['工具到位',()=>{const e=robot.error();return e.position<1.5&&e.angle<2&&e.rail<1;}]];
signals.forEach(([name])=>{const row=document.createElement('div');row.innerHTML=`<i></i><span>${name}</span>`;ui.signals.appendChild(row);});
function drawHud(){
  const e=robot.error(),arrived=e.position<(current.step.contact?1:2)&&e.angle<3&&e.rail<2;
  const illuminated=arrived||CAPTURE;
  robot.setFlash(S.flashTool>0&&illuminated);robot.setLaser(S.laserTool>0&&illuminated);
  cell.topFlash.intensity=S.flashTop*2000;cell.snFlash.intensity=S.flashSn*800;
  const activeDoor=nb.doors.find(d=>S.action.startsWith(d.def.id+' '));
  roiBox.visible=!!(S.flashTool&&illuminated);
  if(roiBox.visible)showROIObj(activeDoor?activeDoor.portGroup:S.action.includes('Docking')?nb.dock:S.action.includes('法規')?nb.printing:nb.labels.sn,3);
  const force=arrived?S.force:0;robot.setForceColor(force);
  cell.tower.set(fault?'red':S.station===4?(ui.result.value==='NG'?'red':'green'):'yellow');
  cell.occluders.visible=ui.showGuards.checked;
  seamLaser.material.opacity=S.seamLaser>=0&&illuminated?.7:0;
  seamLaser.position.set(S.palletX-125+250*smooth(current.t),top+NB.H+1,-94);
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
function render(){drawHud();renderer.render(scene,camera);}
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
    else {T=T>=end-1e-7?Math.min(total,end+1e-6):Math.min(end,T+dt);current=sequence.sample(T>=end-1e-7&&T<=end?Math.max(s.start,end-1e-8):T);}
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
current=sequence.sample(0);robot.snap();setView('iso',true);resize();ui.playBtn.textContent=playing?'⏸ 暫停':'▶ 播放';
window.sim={jump(st,view,off=0){seekTo((stationStart[THREE.MathUtils.clamp(Math.trunc(st)||0,0,4)]||0)+off);if(view)setView(view,true);},seekTo,pause(){playing=false;ui.playBtn.textContent='▶ 播放';},play(){playing=true;ui.playBtn.textContent='⏸ 暫停';},get state(){return S;},robot,total,stationStart,steps:sequence.steps};
if(qp.has('st'))window.sim.jump(+qp.get('st'),qp.get('view'),+(qp.get('t')||0));else if(qp.has('view'))setView(qp.get('view'),true);
if(qp.has('step')){playing=false;seekTo(sequence.steps[THREE.MathUtils.clamp(+qp.get('step')||0,0,sequence.steps.length-1)].start);if(qp.has('view'))setView(qp.get('view'),true);}
if(qp.has('cam')){const a=qp.get('cam').split(',').map(Number);if(a.length===6&&a.every(Number.isFinite)){camera.position.set(...a.slice(0,3));controls.target.set(...a.slice(3));controls.update();}}
document.getElementById('loading').classList.add('hide');render();frame();
// Capture uses the same absolute mechanical sequence as interactive playback.
if(CAPTURE){
  const {installVideo}=await import('./video.js');
  ui.showGuards.checked=false;ui.showLabels.checked=false;
  window.capture=installVideo({steps:sequence.steps,renderer,camera,controls,render,nb,getState:()=>S,sample(time){T=time;current=sequence.sample(time);robot.snap();}});
}
