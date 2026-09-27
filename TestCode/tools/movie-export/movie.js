import * as THREE from 'three';
import {setElectricalMode} from './electrical-cabinet.js';

/** Absolute-time export, isolated from the interactive web source by prepare.py. */
export function installMovie({project,scene,renderer,camera,controls,render,setView,total,steps,sample,focus,offset}) {
  const W=1920,H=1080,FPS=30,shots=[];
  const acid=project==='AutomaticAcid-BaseTitration', pcb=project==='PCB-CopperAssembly';
  const names={'AutomaticAcid-BaseTitration':'自動酸鹼滴定','MilitaryGradePC':'軍規電腦檢測','PCB-CopperAssembly':'PCB 散熱板組裝','RobotArmPressSSD':'SSD USB 銀腳壓合','shutter assembly':'快門葉片與上蓋組裝'};
  let frames=0;
  const add=(kind,seconds,data={})=>{const frameCount=Math.max(1,Math.round(seconds*FPS));shots.push({kind,startFrame:frames,frameCount,...data});frames+=frameCount;};
  add('overview',5,{t:0,label:names[project]+' · 設備全景'});
  let previousPhase=null;
  steps.forEach((s,index)=>{
    const phase=s.station??(acid?Math.floor(s.start/600):0),firstInPhase=phase!==previousPhase;
    let seconds;
    if(acid) seconds=Math.max(.1,s.dur/(s.idle?100:12));
    else if(project==='MilitaryGradePC')seconds=Math.max(.25,s.dur/(s.contact||s.exposure?1.25:3));
    else if(pcb)seconds=s.dur;
    else seconds=Math.max(.45,s.dur*1.2);
    add('process',seconds,{simStart:s.start,simDuration:s.dur,label:s.action||s.label||'製程',phase,firstInPhase,step:index});previousPhase=phase;
  });
  if(pcb)for(const [view,label] of [['load','S0 基板上料'],['s1','S1 孔位定位'],['feeder','銅片供料與翻面'],['head','吸嘴取放細節'],['s3','S3 植入檢查'],['unload','S4 成品下料']])add('station',5,{view,label,simStart:0,simDuration:total});
  add('electrical',7,{t:total,label:'電盤配置 · 剖視'});
  const devices=[],glands=[];scene.updateMatrixWorld(true);
  scene.traverse(o=>{if(o.userData.electrical)devices.push(o);if(o.userData.feedThrough)glands.push(o);});
  const picks=[devices.find(o=>o.userData.electrical.id==='PLC1'),devices.find(o=>o.userData.electrical.id==='RC1'),devices.find(o=>o.userData.electrical.role==='motion'),devices.find(o=>o.userData.electrical.id==='PS1')].filter((o,i,a)=>o&&a.indexOf(o)===i);
  for(const d of picks.slice(0,3))add('device',4,{id:d.userData.electrical.id,label:d.userData.electrical.id+' · '+d.userData.electrical.title,t:total});
  add('wiring',7,{t:total,label:'整線 · 固定線槽、線夾與活動線束'});
  for(let i=0;i<Math.min(2,glands.length);i++)add('gland',4,{gland:i,t:total,label:'桌板穿線孔 · 接頭與下方電盤走線'});
  add('overview',5,{t:total,label:'完整流程展示完成'});

  const style=document.createElement('style');style.textContent=`#app{position:fixed!important;inset:0!important}#app>canvas{width:${W}px!important;height:${H}px!important;position:fixed!important;left:0!important;top:0!important}#film{position:fixed;inset:0;z-index:99999;background:#07111b;display:flex;align-items:center;justify-content:center}#film canvas{width:100%;height:100%;object-fit:contain}#filmControls{position:absolute;bottom:6px;left:8px;padding:8px;background:#132333e8;color:#d8e7ed;font:13px system-ui;display:flex;gap:10px}#filmControls button{padding:5px 12px}#filmControls input{width:210px}`;document.head.append(style);
  const host=document.createElement('section');host.id='film';host.innerHTML='<canvas width="1920" height="1080" aria-label="展示影片預覽"></canvas><div id="filmControls"><button id="exportFilm">輸出完整影片</button><input id="filmFrame" aria-label="影片影格" type="range"><span id="filmStatus"></span></div>';document.body.append(host);
  const output=host.querySelector('canvas'),ctx=output.getContext('2d',{alpha:false}),status=host.querySelector('span'),button=host.querySelector('button'),slider=host.querySelector('input');slider.min=0;slider.max=frames-1;slider.value=0;
  for(const id of ['showPip','showPath','showLabels','showGuards','showMarks']){const el=document.getElementById(id);if(el){el.checked=false;el.dispatchEvent(new Event('change'));}}
  for(const [k,v] of Object.entries({width:W+'px',height:H+'px','min-width':W+'px','max-width':W+'px','min-height':H+'px','max-height':H+'px',left:'0px',top:'0px',right:'auto',bottom:'auto'}))renderer.domElement.style.setProperty(k,v,'important');
  renderer.setPixelRatio(1);renderer.setSize(W,H,false);camera.aspect=W/H;camera.near=.1;camera.updateProjectionMatrix();controls.enableDamping=false;
  let shotIndex=-1,pose=null;
  const V=a=>new THREE.Vector3(...a);
  function draw(index){
    const si=shots.findIndex(s=>index<s.startFrame+s.frameCount),sh=shots[si],u=(index-sh.startFrame)/Math.max(1,sh.frameCount-1);
    const t=sh.kind==='process'||sh.kind==='station'?sh.simStart+sh.simDuration*u:sh.t;
    sample(Math.min(total,t));
    if(si!==shotIndex){
      if(sh.kind==='process'){if(shotIndex<0||shots[shotIndex].kind!=='process')setView('iso',true);setElectricalMode(scene,'shell',false);}
      else {setView(sh.kind==='overview'?'iso':sh.kind==='wiring'?'wiring':sh.kind==='station'?sh.view:'electrical',true);if(sh.kind==='device'||sh.kind==='gland'||sh.kind==='electrical')setElectricalMode(scene,'cutaway',false);}
      pose={p:camera.position.clone(),t:controls.target.clone()};shotIndex=si;
    }
    let p,target;
    if(sh.kind==='process'){
      target=focus().clone();p=target.clone().add(V(typeof offset==='function'?offset():offset));
    }else if(sh.kind==='device'){
      const d=devices.find(o=>o.userData.electrical.id===sh.id),box=new THREE.Box3().setFromObject(d),size=box.getSize(new THREE.Vector3());target=box.getCenter(new THREE.Vector3());
      const distance=Math.max(size.x*1.8,size.y*2.2,150);p=target.clone().add(new THREE.Vector3(distance*.12,distance*.12,distance));
    }else if(sh.kind==='gland'){
      target=glands[sh.gland].getWorldPosition(new THREE.Vector3());p=target.clone().add(pcb?new THREE.Vector3(target.x<0?-180:180,140,150):new THREE.Vector3(85,105,160));
    }else{
      target=pose.t.clone();const d=pose.p.clone().sub(target);if(sh.kind==='overview')d.multiplyScalar(1.5);
      // A small external arc reveals depth without flying through the enclosure.
      if(sh.kind==='overview'||sh.kind==='wiring')d.applyAxisAngle(new THREE.Vector3(0,1,0),(u-.5)*.15);
      p=target.clone().add(d);
    }
    camera.position.copy(p);controls.target.copy(target);camera.lookAt(target);camera.aspect=W/H;camera.near=.1;camera.updateProjectionMatrix();
    renderer.setSize(W,H,false);render();ctx.drawImage(renderer.domElement,0,0,W,H);
    // Information appears briefly; the remaining frames are unobstructed.
    const local=(index-sh.startFrame)/FPS;
    if(sh.kind!=='process'||sh.firstInPhase){
      const a=Math.min(1,Math.max(0,(2-local)*3));
      if(a>0){ctx.globalAlpha=a;ctx.fillStyle='#081722e8';ctx.fillRect(32,30,1220,126);ctx.fillStyle='#72e3cd';ctx.fillRect(32,30,5,126);ctx.fillStyle='#f2f6f8';ctx.font='600 30px "Microsoft JhengHei", sans-serif';ctx.fillText(sh.kind==='process'?names[project]+' · '+sh.label:sh.label,56,79,1160);ctx.fillStyle='#adbdc9';ctx.font='20px "Microsoft JhengHei", sans-serif';ctx.fillText(acid?'工程模擬 · 全批次依序呈現，動作 12×／等待 100× 加速':pcb?'工程模擬 · 五站並行節拍；後段分站展示':'工程模擬 · 完整動作順序，展示變速',56,122);ctx.globalAlpha=1;}
    }
    slider.value=index;status.textContent=`${project} · ${index+1}/${frames} · ${sh.label}`;
  }
  slider.oninput=()=>draw(+slider.value);
  async function post(path,body,headers={}){
    for(let i=0;i<4;i++)try{const r=await fetch('/render/'+path,{method:'POST',body,headers});const data=await r.json();if(!r.ok)throw Error(data.error);return data;}catch(e){if(i===3)throw e;await new Promise(r=>setTimeout(r,500));}
  }
  button.onclick=async()=>{
    button.disabled=true;slider.disabled=true;
    try{
      await document.fonts.ready;
      const gl=renderer.getContext(),ext=gl.getExtension('WEBGL_debug_renderer_info');
      const gpu=ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
      const spec={project,width:W,height:H,fps:FPS,frames,duration:frames/FPS,simulationDuration:total,steps:steps.length,shots,gpu};
      const job=await post('start',JSON.stringify(spec),{'Content-Type':'application/json'});
      for(let i=job.nextFrame;i<frames;i++){
        draw(i);const raw=atob(output.toDataURL('image/jpeg',.92).split(',')[1]);
        await post('frame',Uint8Array.from(raw,c=>c.charCodeAt(0)),{'X-Render-Token':job.token,'X-Frame-Index':String(i)});
      }
      const result=await post('finish','',{'X-Render-Token':job.token});status.textContent='輸出完成：'+result.file;
      const order=['RobotArmPressSSD','shutter assembly','PCB-CopperAssembly','MilitaryGradePC','AutomaticAcid-BaseTitration'];
      const next=order[order.indexOf(project)+1];
      if(new URLSearchParams(location.search).has('queue')&&next)location.href='/'+encodeURIComponent(next)+'/?pause&movie&queue&auto';
    }catch(e){status.textContent='輸出失敗：'+e.message;button.disabled=false;slider.disabled=false;}
  };
  draw(0);
  if(new URLSearchParams(location.search).has('auto'))button.click();
}
