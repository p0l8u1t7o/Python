// node --experimental-loader ./WorkpieceMeasurement/tools/three-loader.mjs WorkpieceMeasurement/tools/verify-details.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as THREE from 'three';
import {DEVICES,PANEL,AXES,IO} from '../web/js/control-plan.js';
import {SPECS,fixedBodies} from '../web/js/spec.js';
import {createSequence} from '../web/js/sequence.js';
import {addEquipmentDetail} from '../web/js/equipment-detail.js';
import {distPoint} from '../web/js/collision.js';
const errors=[];const check=(ok,msg)=>{if(!ok)errors.push(msg);};
for(const d of DEVICES){
 const[x,y,z]=d.at,[w,h,depth]=d.size;
 check(Math.abs(x)+w/2<278&&Math.abs(y)+h/2<PANEL.height/2,d.id+' exceeds board usable area');
 check(PANEL.center[2]+z+depth<248,d.id+' hits front door');
 for(const b of DEVICES)if(d.id<b.id)check(Math.abs(x-b.at[0])>=(w+b.size[0])/2||Math.abs(y-b.at[1])>=(h+b.size[1])/2,d.id+' overlaps '+b.id);
}
assert.equal(new Set(IO.map(p=>p.terminal)).size,IO.length);assert.equal(AXES.length,8);
let samples=0;
for(const s of Object.values(SPECS)){
 const root=new THREE.Group(),deco=new THREE.Group(),rotor1=new THREE.Group(),rotor2=new THREE.Group();root.add(deco,rotor1,rotor2);
 const fixed=fixedBodies(s),byId={};
 for(const b of fixed){const size=b.kind==='box'?b.min.map((v,i)=>b.max[i]-v):[b.r*2,Math.abs(b.p1[1]-b.p0[1])||1,b.r*2];const mesh=new THREE.Mesh(new THREE.BoxGeometry(...size),new THREE.MeshStandardMaterial());mesh.position.fromArray(b.kind==='box'?b.min.map((v,i)=>(v+b.max[i])/2):b.p0.map((v,i)=>(v+b.p1[i])/2));root.add(mesh);byId[b.id]=mesh;}
 const original=new THREE.MeshStandardMaterial();const face=new THREE.Mesh(new THREE.BoxGeometry(2,2,2),original);deco.add(face);
 const detail=addEquipmentDetail({root,deco,byId,cabinetFaces:[face],rotor1,rotor2,s});
 detail.setMode('xray');assert.ok(!Array.isArray(face.material));detail.setMode('cutaway');assert.equal(face.visible,false);detail.setMode('shell');assert.equal(face.material,original);assert.equal(face.visible,true);
 root.traverse(o=>{if(o.name==='field harness through deck gland'){const a=o.geometry.attributes.position;for(let i=0;i<a.count;i++)if(a.getY(i)<816)check(Math.abs(a.getZ(i))<248,'Cable crosses cabinet skin');}});
 const top=deco.children.find(o=>o.geometry?.type==='ExtrudeGeometry');assert.ok(top);
 top.updateMatrixWorld(true);
 // Cast down through each actual cut-out, then an adjacent solid point.
 for(const x of [-290,290]){const ray=new THREE.Raycaster(new THREE.Vector3(x,840,231),new THREE.Vector3(0,-1,0));assert.equal(ray.intersectObject(top).length,0);ray.ray.origin.x=x-25;assert.ok(ray.intersectObject(top).length>0);}
 const seq=createSequence({spec:s.id,scenario:'ERR'});
 for(let t=0;t<=seq.total;t+=.08){const st=seq.sample(t).state;detail.update(st);samples++;
   for(const mesh of detail.moving){const pos=mesh.geometry.attributes.position;for(let i=0;i<pos.count;i++)check(Number.isFinite(pos.getX(i)+pos.getY(i)+pos.getZ(i)),'Nonfinite cable');}
   const rail=fixed.find(b=>b.id==='zadj');check(rail.max[2]<=-s.probeR-1,'Lift head intersects rail');
   // Check the two fiber paths against non-attachment C-frame bodies.
   for(const mesh of detail.moving.filter(m=>['HEAD-LEAD','HEAD-LOOP','LOWER-LEAD'].includes(m.name))){const pts=mesh.geometry.parameters.path.getPoints(100);for(const p of pts)for(const b of fixed.filter(b=>['colC','armUp','armDn'].includes(b.id))){const body={...b,min:b.min.map((v,i)=>v+(i===0?st.r2:0)),max:b.max.map((v,i)=>v+(i===0?st.r2:0))};check(distPoint(p.toArray(),body)>1.3,`${s.id} ${mesh.name} intersects ${b.id}`);}}
 }
 root.traverse(o=>o.geometry?.dispose());
}
const failures=[...new Set(errors)];
fs.writeFileSync(new URL('../review/detail-verification.json',import.meta.url),JSON.stringify({devices:DEVICES.length,axes:AXES.length,io:IO.length,samples,pass:!failures.length,failures,scope:'Board envelope/pairs, real feed-through raycasts, cable finite geometry/cabinet skin, lift rail clearance, paired fiber vs C-frame. Other cable/component pairs and OEM bend radii not certified.'},null,2));
console.log({samples,failures});assert.equal(failures.length,0);
