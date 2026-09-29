import * as THREE from 'three';
import {managedWiring} from './wiring-render.js';
import {electricalDevice, CIRCUITS} from './electrical-components.js';
import {DEVICES,PANEL} from './control-plan.js';
import {Y0,X1,X2,YM,YS} from './spec.js';
const V = a => new THREE.Vector3(...a);
const mat=(color,metalness=.35)=>new THREE.MeshStandardMaterial({color,metalness,roughness:.45});
const steel=mat(0xaab7bf,.8),dark=mat(0x26313a),rubber=mat(0x202628,0),blue=mat(0x226b9e),brass=mat(0xa29761,.65);
function box(g,n,size,at,m=steel){const o=new THREE.Mesh(new THREE.BoxGeometry(...size),m);o.name=n;o.position.set(...at);o.castShadow=o.receiveShadow=true;g.add(o);return o;}
function ring(g,n,ro,ri,h,at,m=steel){const geo=new THREE.LatheGeometry([[ri,-h/2],[ro,-h/2],[ro,h/2],[ri,h/2],[ri,-h/2]].map(a=>new THREE.Vector2(...a)),48);const o=new THREE.Mesh(geo,m);o.name=n;o.position.set(...at);g.add(o);return o;}
function label(g,text,w,h,at){if(typeof document==='undefined')return;const c=document.createElement('canvas');c.width=768;c.height=128;const x=c.getContext('2d');x.fillStyle='#10212c';x.fillRect(0,0,768,128);x.fillStyle='#e4edf3';x.font='bold 36px sans-serif';x.textAlign='center';x.fillText(text,384,77,736);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;const o=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:t}));o.position.set(...at);g.add(o);return o;}
function wire(g,name,points,color,r=1.5){const path=new THREE.CatmullRomCurve3(points.map(V));const o=new THREE.Mesh(new THREE.TubeGeometry(path,Math.max(32,points.length*12),r,6,false),mat(color,0));o.name=name;o.userData.route=points;g.add(o);return o;}
function screw(g,at,r=2){const o=new THREE.Mesh(new THREE.CylinderGeometry(r,r,1.3,6),steel);o.rotation.x=Math.PI/2;o.position.set(...at);g.add(o);return o;}
export function addEquipmentDetail({root,deco,byId,cabinetFaces,rotor1,rotor2,s}) {
  const electrical=new THREE.Group();electrical.name='Control cabinet / planning';root.add(electrical);
  const panel=new THREE.Group();panel.position.set(...PANEL.center);electrical.add(panel);
  box(panel,'bolted backplate',[620,660,3],[0,0,0]);
  for(const x of [-285,285])for(const y of [-305,305]){
    box(panel,'backplate standoff',[14,14,23],[x,y,-13]);screw(panel,[x,y,3],3);
  }
  const devices={};
  for(const d of DEVICES)devices[d.id]=electricalDevice(panel,d,d.at);
  for(const y of [237,100,-45,-225]){
    box(panel,'DIN rail',[550,35,3],[0,y,5]);
    box(panel,'DIN rail lip',[550,3,8],[0,y+16,7]);
    const bottom=y===-225?-311:y-66;
    box(panel,'covered horizontal wire duct',[548,20,24],[0,bottom,16],dark);
    for(let x=-260;x<270;x+=12)box(panel,'duct finger',[2,18,2],[x,bottom,29],rubber);
  }
  for(const x of [-291,291])box(panel,'segregated vertical duct',[25,624,28],[x,0,17],dark);
  for(let i=0;i<18;i++){
    box(panel,'X24 / X0 / XDI / XDO terminal',[9,24,18],[-235+i*10,314,17],i<3?brass:blue);
    screw(panel,[-235+i*10,316,27],1.6);
  }
  box(panel,'PE bonded busbar',[120,8,10],[207,-311,12],brass);
  label(panel,'POWER  /  CONTROL  /  MEASUREMENT',370,15,[0,285,29]);
  for(const d of DEVICES){
    const [x,y,z]=d.at,[w,h,depth]=d.size;
    const routeY=y===-225?-311:y-66;
    wire(panel,'W-'+d.id+' / '+d.category,[[x-w*.28,y-h/2,z+depth*.65],[x-w*.28,y-h/2-7,z+depth*.65],[x-w*.28,routeY,35]],CIRCUITS[d.category].color,1);
  }
  // Top service plate has two actual through-holes, outside the granite slab.
  const sh=new THREE.Shape();sh.moveTo(-350,-250);sh.lineTo(350,-250);sh.lineTo(350,250);sh.lineTo(-350,250);sh.closePath();
  for(const x of [-290,290]){const hole=new THREE.Path();hole.absarc(x,231,13,0,Math.PI*2,true);sh.holes.push(hole);}
  const top=new THREE.Mesh(new THREE.ExtrudeGeometry(sh,{depth:4,bevelEnabled:false}),mat(0xb7c1c5,.12));top.rotation.x=Math.PI/2;top.position.y=820;deco.add(top);cabinetFaces.push(top);
  for(const x of [-290,290]){
    ring(root,'panel feed-through / real opening',17,10,14,[x,822,231],rubber);
    const color=x<0?CIRCUITS.ac.color:CIRCUITS.signal.color;
    wire(root,'field harness through deck gland',[[x,960,231],[x,880,231],[x,822,231],[x,798,231],[x,780,218],[x,766,180],[x,741,-100],[x,735,-186]],color,5);
    // Clamp plates and fasteners meet the rear posts/inner cabinet side.
    for(const y of [795,865,918]){
      ring(root,'split saddle / clear cable bore',8,5.6,7,[x,y,231],dark);
      box(root,'saddle support',[345-Math.abs(x)-8,5,8],[(x+Math.sign(x)*353)/2,y,231]);
    }
  }
  // Visible fasteners remain within existing fixture envelopes.
  for(let i=0;i<6;i++){const a=i*Math.PI/3;const b=screw(rotor1,[8*Math.cos(a),YM+12,8*Math.sin(a)],1.2);b.rotation.set(0,0,0);}
  for(let i=0;i<3;i++){const a=Math.PI/6+i*Math.PI*2/3;const o=new THREE.Mesh(new THREE.CylinderGeometry(1.7,1.7,.6,6),steel);o.position.set(23*Math.cos(a),YS-1.2,23*Math.sin(a));rotor2.add(o);}
  for(const id of ['sensorUp','sensorDn']){
    const sensor=byId[id];sensor.material=steel;
    const h=sensor.geometry.parameters?.height||70;
    ring(sensor,id+' lens retaining ring',Math.min(13.8,s.probeR),Math.min(10,s.probeR*.7),2,[0,id==='sensorUp'?-h/2+1:h/2-1,0],dark);
    label(sensor,'CL-S015',23,6,[0,0,14.1]);
  }
  ring(byId.sensorUp,'split clamp on lift carriage',16,14,9,[0,20,0]);
  box(byId.sensorUp,'DH lift carriage',[30,22,12],[0,20,-19]);
  const railHeight=byId.zadj.geometry.parameters.height;
  box(byId.zadj,'DH mounting cap to upper arm',[40,6,56],[0,railHeight/2,16]);
  // OP-88864 is an adjustment fixture, not the workpiece-holding chuck.
  label(root,'ST2  /  OP-88864 adjustment concept',95,10,[278,1192,27]);
  for(const id of ['colC','zadj','chuck']){const o=byId[id];if(!o)continue;const bounds=new THREE.Box3().setFromObject(o);const z=bounds.max.z+.5;for(const dx of [-.3,.3]){const p=bounds.getCenter(new THREE.Vector3());screw(o,[dx*(bounds.max.x-bounds.min.x),0,z-o.position.z],1.6);}}
  for(const y of [-38,38]){
    const knob=new THREE.Mesh(new THREE.CylinderGeometry(5,5,9,24),dark);knob.rotation.z=Math.PI/2;knob.position.set(26,y,0);byId.zadj.add(knob);
    box(byId.zadj,'adjustment screw boss',[4,18,18],[21,y,0]);
  }
  const wiring=managedWiring(root,s),moving=wiring.moving;
  function update(S){
    wiring.update(S);
    for(const [id,o]of Object.entries(devices)){const led=o.userData.electricalLed;if(led)led.material.emissiveIntensity=id==='CL1'||id.startsWith('OM')?(S.optic==='CF'?1.2:.15):.3;}
  }
  const originals=new Map();
  let currentMode='';
  function setMode(mode){if(mode===currentMode)return;currentMode=mode;for(const o of cabinetFaces){if(!originals.has(o))originals.set(o,o.material);o.visible=mode!=='cutaway';if(o.material!==originals.get(o))for(const m of [].concat(o.material))m.dispose();o.material=originals.get(o);if(mode==='xray'){const fade=m=>{const n=m.clone();n.transparent=true;n.opacity=.12;n.depthWrite=false;return n;};o.material=Array.isArray(o.material)?o.material.map(fade):fade(o.material);}}}
  return {update,setMode,electrical,devices,moving,wiring};
}
