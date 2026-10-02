import * as THREE from 'three';
import {setElectricalMode} from './electrical-cabinet.js';
import {CIRCUITS,electricalActivity} from './electrical-components.js';

/** Inspector consumes the main simulation clock; it never starts its own timeline. */
export function createElectricalInspector({scene,camera,controls,canvas,onEnter,onExit,title}){
  const css=document.createElement('link');css.rel='stylesheet';css.href=new URL('./electrical-inspector.css',import.meta.url);document.head.append(css);
  const devices=[],wires=[];scene.traverse(o=>{if(o.userData.electrical)devices.push(o);if(o.userData.electricalWire)wires.push(o);});
  const panel=document.createElement('section');panel.id='electrical-inspector';panel.hidden=true;panel.setAttribute('aria-label','電控規劃檢視');
  panel.innerHTML='<header><div><small>CONTROL SYSTEM / 3D</small><h2>電控規劃</h2></div><button type="button" data-close aria-label="關閉電控規劃">×</button></header><p class="ep-summary"></p><div class="ep-modes" aria-label="機櫃顯示"><button data-mode="shell">外殼</button><button data-mode="cutaway">剖視</button><button data-mode="xray">透視</button></div><label>電控元件<select aria-label="選擇電控元件"></select></label><div class="ep-actions"><button data-focus>元件特寫</button><button data-overview>電盤總覽</button></div><article><div class="ep-category"></div><h3></h3><p class="ep-purpose"></p><dl><dt>規劃依據</dt><dd class="ep-model"></dd><dt>外形 W × H × D</dt><dd class="ep-size"></dd><dt>功能連接</dt><dd class="ep-links"></dd></dl></article><div class="ep-state"><b>主時間軸</b><output></output><p></p></div><details><summary>配線圖例與規劃範圍</summary><div class="ep-legend"></div><p>線路呈現功能連接與安裝空間；完整芯線、保護容量及散熱需依最終料號設計。指示燈為流程示意，並非實機電氣訊號。</p></details><button data-export>匯出元件與連接清單</button>';
  document.getElementById('app').append(panel);
  const toggle=document.createElement('button');toggle.type='button';toggle.textContent='⚡';toggle.title='電控規劃';toggle.setAttribute('aria-label','電控規劃');toggle.setAttribute('aria-controls',panel.id);toggle.setAttribute('aria-expanded','false');document.querySelector('.viewer-tools').append(toggle);
  panel.querySelector('.ep-summary').textContent=title+' · '+devices.length+' 個電控元件';
  const select=panel.querySelector('select');devices.forEach((o,i)=>{const opt=document.createElement('option');opt.value=i;opt.textContent=o.userData.electrical.id+' · '+o.userData.electrical.title;select.append(opt);});
  for(const [key,c] of Object.entries(CIRCUITS)){const item=document.createElement('span');item.textContent=c.label;item.style.setProperty('--wire','#'+c.color.toString(16).padStart(6,'0'));panel.querySelector('.ep-legend').append(item);}
  const bounds=new THREE.Box3(),outline=new THREE.Box3Helper(bounds,0xffcf61);outline.material.depthTest=false;outline.renderOrder=100;outline.visible=false;scene.add(outline);
  const label=document.createElement('div');label.className='electrical-callout';label.hidden=true;document.getElementById('app').append(label);
  let selected=devices[0],mode='cutaway',lastText='',down=null;
  function displayMode(next){mode=next;setElectricalMode(scene,next,false);panel.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));outline.visible=!panel.hidden&&mode!=='shell';}
  function show(){window.dispatchEvent(new CustomEvent('viewer-panel-open',{detail:{id:panel.id}}));panel.hidden=false;toggle.setAttribute('aria-expanded','true');displayMode('cutaway');choose(+select.value||0);}
  function hide(){panel.hidden=true;toggle.setAttribute('aria-expanded','false');outline.visible=false;label.hidden=true;wires.forEach(w=>{w.material.emissive?.setHex(0);});}
  function choose(index){
    selected=devices[index];if(!selected)return;select.value=String(index);const d=selected.userData.electrical;
    panel.querySelector('h3').textContent=d.id+' · '+d.title;panel.querySelector('.ep-category').textContent=CIRCUITS[d.category].label;
    panel.querySelector('.ep-purpose').textContent=d.description;panel.querySelector('.ep-model').textContent=d.model;
    panel.querySelector('.ep-size').textContent=d.size.join(' × ')+' mm';
    const links=wires.filter(w=>w.userData.electricalWire.to===d.id||w.userData.electricalWire.from===d.id).map(w=>w.userData.electricalWire.from+' → '+w.userData.electricalWire.to);
    panel.querySelector('.ep-links').textContent=links.length?[...new Set(links)].join('；'):'專用手臂電纜／設備電源／安全與通訊交握';
    label.textContent=d.id+' · '+d.title;
    for(const w of wires){const a=w.userData.electricalWire;w.material.emissive?.setHex(a.to===d.id||a.from===d.id?CIRCUITS[a.category].color:0);w.material.emissiveIntensity=.5;}
  }
  function focus(){
    if(!selected)return;const previous=mode;onEnter();displayMode(previous==='shell'?'cutaway':previous);
    scene.updateMatrixWorld(true);const b=new THREE.Box3().setFromObject(selected),center=b.getCenter(new THREE.Vector3()),size=b.getSize(new THREE.Vector3());
    const distance=Math.max(size.y,size.x/Math.max(.5,camera.aspect))/(2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2)))*1.65+size.z/2;
    controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(size.x*.12,size.y*.10,distance));camera.near=.5;camera.updateProjectionMatrix();controls.update();
  }
  toggle.onclick=()=>{if(panel.hidden){onEnter();show();}else{onExit();hide();}};
  panel.querySelector('[data-close]').onclick=()=>{onExit();hide();toggle.focus();};
  panel.querySelector('[data-focus]').onclick=focus;panel.querySelector('[data-overview]').onclick=()=>{const previous=mode;onEnter();displayMode(previous);};
  select.onchange=()=>{choose(+select.value);focus();};
  panel.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>displayMode(b.dataset.mode));
  window.addEventListener('electrical-view',e=>{if(e.detail.mode==='shell')hide();else show();});
  window.addEventListener('viewer-panel-open',e=>{if(document.body.classList.contains('viewer-compact')&&e.detail.id!==panel.id)hide();});
  panel.addEventListener('keydown',e=>{if(e.key==='Escape'){onExit();hide();toggle.focus();}});
  const ray=new THREE.Raycaster(),pointer=new THREE.Vector2(),bodies=[];devices.forEach(d=>d.traverse(m=>{if(m.userData.electricalBody)bodies.push(m);}));
  canvas.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY];});
  canvas.addEventListener('pointerup',e=>{
    if(panel.hidden||mode==='shell'||!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>4)return;
    const r=canvas.getBoundingClientRect();pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);ray.setFromCamera(pointer,camera);
    const hit=ray.intersectObjects(bodies,false)[0];if(hit){let o=hit.object;while(o&&!o.userData.electrical)o=o.parent;choose(devices.indexOf(o));}
  });
  panel.querySelector('[data-export]').onclick=()=>{
    const data={project:title,scope:'電控配置與功能連接示意；非施工接線圖',components:devices.map(o=>o.userData.electrical),connections:wires.map(o=>o.userData.electricalWire)};
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='electrical-plan.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return {update(state){
    for(const o of devices){if(o.userData.electricalLed)o.userData.electricalLed.material.emissiveIntensity=electricalActivity(o.userData.electrical.role,state)?.7:.06;}
    if(panel.hidden||!selected)return;
    scene.updateMatrixWorld(true);bounds.setFromObject(selected);outline.visible=mode!=='shell';
    const p=bounds.getCenter(new THREE.Vector3());p.y=bounds.max.y+12;p.project(camera);const r=canvas.getBoundingClientRect();label.hidden=mode==='shell'||p.z>1||Math.abs(p.x)>.95||Math.abs(p.y)>.95;
    label.style.left=r.left+(p.x*.5+.5)*r.width+'px';label.style.top=r.top+(-p.y*.5+.5)*r.height+'px';
    const text=Number(state.time||0).toFixed(1)+' s · '+(state.playing?'播放':'暫停');if(text!==lastText){panel.querySelector('output').textContent=text;lastText=text;}
    panel.querySelector('.ep-state p').textContent=state.action||'設備待命';
  }};
}
