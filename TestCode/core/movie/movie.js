import * as THREE from 'three';
import {smooth,filterTargets,atFrame} from './camera-path.mjs';

/** One absolute-time renderer for preview, audit and recording.
 *  各專案在 main.js 以 ?movie 呼叫：installMovie({ project, scene, renderer, camera, controls, render, setView, total, steps, sample, focus, offset, detailShots, electricalMode, keepGuards })。
 *  網頁本身的畫面迴圈在 ?movie 時不啟動（core/ui/stage.js 已處理；未用 stage 的專案在自己的迴圈開頭判斷）。 */
export async function installMovie({project,scene,renderer,camera,controls,render,setView,total,steps,sample,focus,offset,detailShots=[],electricalMode,keepGuards=false}) {
  const setElectricalMode=electricalMode||(await import('@core/electrical/electrical-cabinet.js')).setElectricalMode;
  const W=1920,H=1080,FPS=30,SSAA=2,shots=[];
  const acid=project==='AutomaticAcid-BaseTitration',pcb=project==='PCB-CopperAssembly';
  const names={'AutomaticAcid-BaseTitration':'自動酸鹼滴定','MilitaryGradePC':'軍規電腦檢測','PCB-CopperAssembly':'PCB 散熱板組裝','RobotArmPressSSD':'SSD USB 銀腳壓合','shutter assembly':'快門葉片與上蓋組裝','WorkpieceMeasurement':'杯體加工件 AOI＋共焦量測'};
  let frames=0;
  const add=(kind,seconds,data={})=>{const frameCount=Math.max(1,Math.round(seconds*FPS));shots.push({kind,startFrame:frames,frameCount,...data});frames+=frameCount;};
  add('overview',12,{t:0,label:names[project]+' · 全景到製程',intro:true});
  let previousPhase=null;
  steps.forEach((s,index)=>{
    const phase=s.station??(acid?Math.floor(s.start/600):0),firstInPhase=phase!==previousPhase;
    const seconds=acid?Math.max(.1,s.dur/(s.idle?100:12)):
      project==='MilitaryGradePC'?Math.max(.25,s.dur/(s.contact||s.exposure?1.25:3)):
      pcb?s.dur:Math.max(.45,s.dur*1.2);
    add('process',seconds,{simStart:s.start,simDuration:s.dur,label:s.action||s.label||'製程',phase,firstInPhase,step:index});previousPhase=phase;
  });
  for(const shot of detailShots)add('station',Math.max(6,shot.simDuration*1.2),shot);
  add('electrical',9,{t:total,label:'電盤配置 · 剖視'});
  const devices=[],glands=[];scene.updateMatrixWorld(true);
  scene.traverse(o=>{if(o.userData.electrical)devices.push(o);if(o.userData.feedThrough)glands.push(o);});
  const picks=[devices.find(o=>o.userData.electrical.id==='PLC1'),devices.find(o=>o.userData.electrical.id==='RC1'),devices.find(o=>o.userData.electrical.role==='motion'),devices.find(o=>o.userData.electrical.id==='PS1')].filter((o,i,a)=>o&&a.indexOf(o)===i);
  for(const d of picks.slice(0,3))add('device',5,{id:d.userData.electrical.id,label:d.userData.electrical.id+' · '+d.userData.electrical.title,t:total});
  add('wiring',9,{t:total,label:'整線 · 固定線槽、線夾與活動線束'});
  for(let i=0;i<Math.min(2,glands.length);i++)add('gland',5,{gland:i,t:total,label:'桌板穿線孔 · 接頭與下方電盤走線'});
  add('overview',7,{t:total,label:'完整流程展示完成'});

  const style=document.createElement('style');style.textContent=`#app{position:fixed!important;inset:0!important}#app>canvas{width:${W}px!important;height:${H}px!important;position:fixed!important;left:0!important;top:0!important}#film{position:fixed;inset:0;z-index:99999;background:#07111b;display:flex;align-items:center;justify-content:center}#film canvas{width:100%;height:100%;object-fit:contain}#filmControls{position:absolute;bottom:6px;left:8px;padding:8px;background:#132333ed;color:#d8e7ed;font:13px system-ui;display:flex;gap:10px;flex-wrap:wrap}#filmControls button{padding:5px 12px}#filmControls input{width:180px}`;document.head.append(style);
  const host=document.createElement('section');host.id='film';host.innerHTML='<canvas width="1920" height="1080" aria-label="展示影片預覽"></canvas><div id="filmControls"><button id="exportFilm" disabled>輸出完整影片</button><button id="auditFilm" disabled>檢查鏡頭與固定影格</button><input id="filmFrame" aria-label="影片影格" type="range"><input id="filmSeek" aria-label="跳至影格" type="number" min="0" style="width:90px"><button id="seekFilm">跳轉</button><span id="filmStatus">準備平滑運鏡…</span></div>';document.body.append(host);
  const output=host.querySelector('canvas'),ctx=output.getContext('2d',{alpha:false});
  const status=host.querySelector('span'),button=host.querySelector('#exportFilm'),auditButton=host.querySelector('#auditFilm'),slider=host.querySelector('#filmFrame'),seek=host.querySelector('#filmSeek');
  slider.min=0;slider.max=frames-1;slider.value=0;seek.max=frames-1;seek.value=0;
  for(const id of ['showPip','showPath','showLabels','showGuards','showMarks']){if(id==='showGuards'&&keepGuards)continue;const el=document.getElementById(id);if(el){el.checked=false;el.dispatchEvent(new Event('change'));}}
  for(const [k,v] of Object.entries({width:W+'px',height:H+'px','min-width':W+'px','max-width':W+'px','min-height':H+'px','max-height':H+'px',left:'0px',top:'0px',right:'auto',bottom:'auto'}))renderer.domElement.style.setProperty(k,v,'important');
  // Allocate once; render at 4K and downsample to stabilize fine cables/edges.
  renderer.setPixelRatio(SSAA);renderer.setSize(W,H,false);controls.enableDamping=false;
  camera.aspect=W/H;camera.near=2;camera.far=16000;camera.updateProjectionMatrix();
  ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';
  const strobes=[];
  scene.traverse(o=>{
    if(o.isSpotLight&&o.intensity===0)strobes.push(o);
    if(o.isDirectionalLight&&o.castShadow){
      o.shadow.mapSize.set(4096,4096);o.shadow.needsUpdate=true;
      if(o.shadow.camera.right-o.shadow.camera.left>500)o.shadow.normalBias=Math.max(o.shadow.normalBias,.4);
    }
    if(o.isMesh)for(const m of [].concat(o.material)){
      if(m.isMeshStandardMaterial&&m.metalness>.25)m.roughness=Math.max(m.roughness,.32);
    }
  });
  const V=a=>new THREE.Vector3(...a);
  const locate=i=>shots.findIndex(s=>i<s.startFrame+s.frameCount);
  const simTime=(sh,u)=>sh.kind==='process'||sh.kind==='station'?sh.simStart+sh.simDuration*u:sh.t;
  const processes=shots.filter(s=>s.kind==='process'),processStart=processes[0].startFrame;
  const processEnd=processes.at(-1).startFrame+processes.at(-1).frameCount-1;
  const processLength=processEnd-processStart,raw=[],stride=6;
  let cursor=1;
  // Precompute chronologically so target smoothing never depends on seek order.
  for(let f=0;f<=processLength+stride;f+=stride){
    const index=Math.min(processStart+f,processEnd);
    while(index>=shots[cursor].startFrame+shots[cursor].frameCount)cursor++;
    const sh=shots[cursor],u=(index-sh.startFrame)/Math.max(1,sh.frameCount-1);
    sample(Math.min(total,simTime(sh,u)));scene.updateMatrixWorld(true);raw.push(focus().toArray());
    if(raw.length%150===0){status.textContent='建立全流程平滑運鏡 '+Math.round(f/processLength*100)+'%';await new Promise(r=>setTimeout(r,0));}
  }
  const targets=filterTargets(raw,10),processOffset=typeof offset==='function'?offset():offset;
  const firstTarget=V(targets[0]),firstPosition=firstTarget.clone().add(V(processOffset));
  const ray=new THREE.Raycaster(),opaque=[];
  scene.traverse(o=>{if(o.isMesh&&[].concat(o.material).some(m=>m.opacity>=.5))opaque.push(o);});
  const visible=o=>{for(let p=o;p;p=p.parent)if(!p.visible)return false;return true;};
  function fitOverview(){
    const bounds=new THREE.Box3();
    scene.traverse(o=>{
      if(!o.isMesh||!visible(o))return;
      o.geometry.computeBoundingBox();const b=o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld);
      // Exclude floor planes, painted floor markings and the factory grid.
      if(b.max.y<25||b.getSize(new THREE.Vector3()).y<.001)return;
      bounds.union(b);
    });
    const center=bounds.getCenter(new THREE.Vector3()),dir=camera.position.clone().sub(controls.target).normalize();
    const right=new THREE.Vector3(0,1,0).cross(dir).normalize(),up=dir.clone().cross(right);
    const tanV=Math.tan(camera.fov*Math.PI/360),tanH=tanV*W/H;let distance=0;
    for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z]){
      const d=new THREE.Vector3(x,y,z).sub(center);
      distance=Math.max(distance,d.dot(dir)+Math.max(Math.abs(d.dot(right))/tanH,Math.abs(d.dot(up))/tanV));
    }
    return {p:center.clone().addScaledVector(dir,distance*1.08).toArray(),t:center.toArray()};
  }
  function clearDetail(center,delta){
    for(const angle of [0,-30,30,-60,60,-90,90,180]){
      const candidate=delta.clone().applyAxisAngle(new THREE.Vector3(0,1,0),angle*Math.PI/180);
      const clear=[1.08,1.18].every(scale=>{
        const p=center.clone().addScaledVector(candidate,scale),distance=p.distanceTo(center);
        const forward=center.clone().sub(p).normalize(),right=forward.clone().cross(new THREE.Vector3(0,1,0)).normalize(),up=right.clone().cross(forward);
        return [[0,0],[-70,30],[70,30],[-70,100],[70,100]].every(([x,y])=>{
          const aim=center.clone().addScaledVector(right,x).addScaledVector(up,y);
          ray.set(p,aim.sub(p).normalize());ray.far=distance-45;
          return !ray.intersectObjects(opaque,false).some(hit=>visible(hit.object));
        });
      });
      if(clear)return candidate;
    }
    // A higher view remains outside the base even for dense table fittings.
    return delta.clone().setY(Math.max(delta.y,450));
  }
  for(const sh of shots){
    if(sh.kind==='process')continue;
    sample(Math.min(total,simTime(sh,0)));
    setView(sh.kind==='overview'?'iso':sh.kind==='wiring'?'wiring':sh.kind==='station'?sh.view:'electrical',true);
    scene.updateMatrixWorld(true);sh.pose={p:camera.position.toArray(),t:controls.target.toArray()};
    if(sh.kind==='overview')sh.pose=fitOverview();
    else if(sh.kind==='station'&&['feeder','head'].includes(sh.view)){
      // Stay below the 1260 mm moving beam while keeping the entire tray/tool
      // in view; raising the camera above it would obscure the insertion point.
      const center=V(sh.pose.t),delta=sh.view==='feeder'?new THREE.Vector3(-220,190,430):new THREE.Vector3(120,130,480);
      sh.pose={p:center.clone().add(delta).toArray(),t:center.toArray()};
    }
    else if(sh.kind==='device'){
      const d=devices.find(o=>o.userData.electrical.id===sh.id),box=new THREE.Box3().setFromObject(d),size=box.getSize(new THREE.Vector3());
      const center=box.getCenter(new THREE.Vector3()),distance=Math.max(size.x*2.8,size.y*3.4,320);
      sh.pose={p:center.clone().add(new THREE.Vector3(distance*.10,distance*.15,distance)).toArray(),t:center.toArray()};
    }else if(sh.kind==='gland'){
      const center=glands[sh.gland].getWorldPosition(new THREE.Vector3());
      const delta=clearDetail(center,pcb?new THREE.Vector3(center.x<0?-350:350,280,340):new THREE.Vector3(180,230,350));
      sh.pose={p:center.clone().add(delta).toArray(),t:center.toArray()};
    }
  }
  let activeMode=null;
  function poseAt(index){
    const sh=shots[locate(index)],u=(index-sh.startFrame)/Math.max(1,sh.frameCount-1);
    let p,target;
    if(sh.kind==='process'){
      target=V(atFrame(targets,index-processStart,stride));p=target.clone().add(V(processOffset));
    }else{
      target=V(sh.pose.t);const delta=V(sh.pose.p).sub(target);
      if(sh.intro){
        const wide=target.clone().add(delta.multiplyScalar(1.05)),zoom=smooth(((index-sh.startFrame)/FPS-3)/(9-1/FPS));
        p=wide.lerp(firstPosition,zoom);target.lerp(firstTarget,zoom);
      }else{
        delta.multiplyScalar(sh.kind==='overview'?1.05:1.18-.10*smooth(u));
        if(sh.kind==='overview'||sh.kind==='wiring')delta.applyAxisAngle(new THREE.Vector3(0,1,0),(u-.5)*.10);
        p=target.clone().add(delta);
      }
    }
    return {sh,u,p,target,t:Math.min(total,simTime(sh,u))};
  }
  function sceneFrame(index){
    const v=poseAt(index);sample(v.t);
    // Industrial exposure pulses are events, not presentation lighting. Keep
    // their process/LED state, but avoid broad illumination flashes in the film.
    strobes.forEach(light=>{light.intensity=0;});
    const mode=['electrical','device','gland'].includes(v.sh.kind)?'cutaway':'shell';
    if(activeMode!==mode){setElectricalMode(scene,mode,false);activeMode=mode;}
    camera.position.copy(v.p);controls.target.copy(v.target);camera.lookAt(v.target);
    camera.near=Math.max(2,Math.min(8,v.p.distanceTo(v.target)/250));
    camera.aspect=W/H;camera.updateProjectionMatrix();(scene.children.forEach(o=>{if(o.type==='Box3Helper')o.visible=false;}),render());return v;
  }
  const transition=document.createElement('canvas');transition.width=W;transition.height=H;
  const transitionContext=transition.getContext('2d',{alpha:false});
  transitionContext.imageSmoothingQuality='high';let transitionShot=-1;
  function draw(index){
    index=Math.max(0,Math.min(frames-1,Math.round(index)));const si=locate(index),sh=shots[si],local=(index-sh.startFrame)/FPS;
    const dissolve=si>0&&sh.kind!=='process'&&local<.8;
    // Detail inserts dissolve rather than flying through solid enclosures.
    if(dissolve&&transitionShot!==si){sceneFrame(sh.startFrame-1);transitionContext.drawImage(renderer.domElement,0,0,W,H);transitionShot=si;}
    const v=sceneFrame(index);ctx.globalAlpha=1;ctx.drawImage(renderer.domElement,0,0,W,H);
    if(dissolve){ctx.globalAlpha=1-smooth(local/.8);ctx.drawImage(transition,0,0);ctx.globalAlpha=1;}
    if(sh.kind!=='process'||sh.firstInPhase){
      const a=Math.min(1,Math.max(0,(2-local)*3));
      if(a>0){ctx.globalAlpha=a;ctx.fillStyle='#081722e8';ctx.fillRect(32,30,1220,126);ctx.fillStyle='#72e3cd';ctx.fillRect(32,30,5,126);ctx.fillStyle='#f2f6f8';ctx.font='600 30px "Microsoft JhengHei",sans-serif';ctx.fillText(sh.kind==='process'?names[project]+' · '+sh.label:sh.label,56,79,1160);ctx.fillStyle='#adbdc9';ctx.font='20px "Microsoft JhengHei",sans-serif';ctx.fillText(acid?'工程模擬 · 全批次依序呈現，動作 12×／等待 100× 加速':pcb?'工程模擬 · 五站並行節拍；後段分站展示':'工程模擬 · 完整動作順序，展示變速',56,122);ctx.globalAlpha=1;}
    }
    slider.value=index;seek.value=index;status.textContent=`${project} · ${index+1}/${frames} · ${sh.label}`;
    return {frame:index,kind:sh.kind,simulationTime:v.t,camera:v.p.toArray(),target:v.target.toArray(),near:camera.near};
  }
  slider.oninput=()=>draw(+slider.value);host.querySelector('#seekFilm').onclick=()=>draw(+seek.value);
  async function post(path,body,headers={}){
    for(let i=0;i<4;i++)try{const r=await fetch('/render/'+path,{method:'POST',body,headers});const data=await r.json();if(!r.ok)throw Error(data.error);return data;}catch(e){if(i===3)throw e;await new Promise(r=>setTimeout(r,500));}
  }
  const bytes=()=>{const raw=atob(output.toDataURL('image/jpeg',.96).split(',')[1]);return Uint8Array.from(raw,c=>c.charCodeAt(0));};
  const gl=renderer.getContext(),ext=gl.getExtension('WEBGL_debug_renderer_info');
  const gpu=ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
  const spec={revision:'2026-09-29-cinematic-v2',project,width:W,height:H,fps:FPS,frames,duration:frames/FPS,simulationDuration:total,steps:steps.length,shots,gpu,supersampling:SSAA,processOffset,focusFilterSeconds:4,openingSeconds:12};
  const disable=value=>{button.disabled=value;auditButton.disabled=value;slider.disabled=value;seek.disabled=value;host.querySelector('#seekFilm').disabled=value;};
  auditButton.onclick=async()=>{
    disable(true);
    try{
      await document.fonts.ready;await post('audit-start',JSON.stringify(spec),{'Content-Type':'application/json'});
      const indices=new Set([0,90,180,270,359,frames-1]);
      for(let j=0;j<=12;j++)indices.add(Math.round(processStart+processLength*j/12));
      for(const s of shots)if(s.kind!=='process')indices.add(Math.min(frames-1,s.startFrame+Math.floor(s.frameCount*.65)));
      const work=[...[...indices].sort((a,b)=>a-b).map(i=>({i,name:'frame-'+String(i).padStart(6,'0')})),...Array.from({length:10},(_,j)=>({i:Math.round(processStart+processLength*.4),name:'repeat-'+String(j).padStart(2,'0')}))];
      for(const x of work){const telemetry=draw(x.i);await post('audit-frame',bytes(),{'X-Project':encodeURIComponent(project),'X-Sample-Name':x.name,'X-Telemetry':JSON.stringify(telemetry)});}
      status.textContent='鏡頭及固定影格檢查完成：'+work.length+' 張';
    }catch(e){status.textContent='檢查失敗：'+e.message;}finally{disable(false);}
  };
  button.onclick=async()=>{
    disable(true);
    try{
      await document.fonts.ready;const job=await post('start',JSON.stringify(spec),{'Content-Type':'application/json'});
      for(let i=job.nextFrame;i<frames;i++){draw(i);await post('frame',bytes(),{'X-Render-Token':job.token,'X-Frame-Index':String(i)});}
      const result=await post('finish','',{'X-Render-Token':job.token});status.textContent='輸出完成：'+result.file;
      const order=['RobotArmPressSSD','shutter assembly','PCB-CopperAssembly','MilitaryGradePC','AutomaticAcid-BaseTitration'],next=order[order.indexOf(project)+1];
      if(new URLSearchParams(location.search).has('queue')&&next){
        const active=await (await fetch('/render/status')).json();
        if(active[next])status.textContent+='；下一影片已在另一視窗輸出／完成';
        else location.href='/'+encodeURIComponent(next)+'/?pause&movie&queue&auto';
      }
    }catch(e){status.textContent='輸出失敗：'+e.message;disable(false);}
  };
  await document.fonts.ready;draw(0);disable(false);
  if(new URLSearchParams(location.search).has('auto'))button.click();
}
