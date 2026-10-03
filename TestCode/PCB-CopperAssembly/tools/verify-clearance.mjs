import * as THREE from 'three';
import assert from 'node:assert/strict';
import {createSim} from '../web/js/sim.js';
import {RECIPES,setRecipe} from '../web/js/layout.js';
import {routeIntersectsBox} from '@core/electrical/cable-routing.js';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
for(const recipe of Object.keys(RECIPES)){
 setRecipe(recipe);const scene=new THREE.Scene(),sim=createSim(scene),heads=sim.machine.heads;
 const parts=H=>{const a=[];heads[H].beam.traverse(m=>{if(m.isMesh&&!m.material.transparent)a.push({m,b:new THREE.Box3()});});return a;};
 const A=parts('A'),B=parts('B'),hits=new Map(),fixed=[];
 for(const H of ['A','B'])sim.machine.feeders[H].cam.group.traverse(m=>{if(m.isMesh)fixed.push({m,b:new THREE.Box3(),name:'feeder-camera-'+H});});
 for(const H of ['A','B'])sim.machine.upCams[H].group.traverse(m=>{if(m.isMesh)fixed.push({m,b:new THREE.Box3(),name:'up-camera-'+H});});
 sim.machine.occluders.traverse(m=>{if(m.isMesh)fixed.push({m,b:new THREE.Box3(),name:'enclosure-'+m.geometry.type});});
 for(const m of sim.machine.keepout)fixed.push({m,b:new THREE.Box3(),name:m.name});
 for(const sc of Object.values(sim.machine.scanners))sc.beam.traverse(m=>{if(m.isMesh&&!m.material.transparent)fixed.push({m,b:new THREE.Box3(),name:'scanner-'+m.geometry.type});});
 const visible=m=>{for(let o=m;o;o=o.parent)if(!o.visible)return false;return true;};
 let samples=0;
 const times=new Set([0,sim.plan.cycle]);
 for(let t=0;t<sim.plan.cycle;t+=.002)times.add(t);
 for(const tr of [sim.plan.conveyor,sim.plan.s0,sim.plan.s4,sim.plan.s1.tr,sim.plan.s3.tr,...Object.values(sim.plan.heads).map(h=>h.tr)])
  for(const s of tr.steps){times.add(s.start);times.add(s.start+s.dur);}
 for(const t of [...times].sort((a,b)=>a-b)){sim.apply(t);samples++;
  for(const p of [...A,...B])p.b.setFromObject(p.m).expandByScalar(.25);
  for(const a of A)for(const b of B){if(!visible(a.m)||!visible(b.m)||!a.b.intersectsBox(b.b)||!routeIntersectsBox(a.m,b.b,.25)||!routeIntersectsBox(b.m,a.b,.25))continue;
   const key=[a.m.name||a.m.geometry.type,b.m.name||b.m.geometry.type].join(' / ');
   if(!hits.has(key))hits.set(key,{t:+t.toFixed(3),pair:key,a:a.m.getWorldPosition(new THREE.Vector3()).toArray(),b:b.m.getWorldPosition(new THREE.Vector3()).toArray()});
  }
  for(const b of fixed){b.b.setFromObject(b.m);for(const a of [...A,...B])if(visible(a.m)&&a.b.intersectsBox(b.b)&&routeIntersectsBox(a.m,b.b,.25)&&routeIntersectsBox(b.m,a.b,.25)){
   if(a.m.name==='moving-gantry-beam'&&b.name==='S2 Y 軌')continue; // Intended sliding support contact.
   const key=(a.m.name||a.m.geometry.type)+' / '+b.name;if(!hits.has(key))hits.set(key,{t:+t.toFixed(3),pair:key,position:b.m.getWorldPosition(new THREE.Vector3()).toArray(),size:b.b.getSize(new THREE.Vector3()).toArray()});}}
 }
 assert.equal(hits.size,0,recipe+' '+JSON.stringify([...hits.values()]));
 // The lens, not the nozzle row, must be directly over each fiducial.
 for(const e of sim.plan.log.filter(e=>e.type==='fid')){
  sim.apply(e.t-.001);const cam=heads[e.H].downCam.cam;cam.updateMatrixWorld(true);
  const p=new THREE.Vector3(e.x,950,e.z).project(cam);assert(Math.abs(p.x)<1e-5&&Math.abs(p.y)<1e-5,'fiducial not on camera optical axis');
 }
 // Bores must be genuinely open along each spindle, not a painted circle.
 for(const H of ['A','B'])for(const shot of sim.plan.feeders[H].tr.steps.filter(s=>s.flash))for(const f of [.01,.5,.99]){
  sim.apply(shot.start+shot.dur*f);const cam=sim.machine.feeders[H].cam.cam,origin=cam.getWorldPosition(new THREE.Vector3()),plate=sim.machine.feeders[H].plate.getWorldPosition(new THREE.Vector3());
  for(const [dx,dz] of [[0,0],[-65,-45],[-65,45],[65,-45],[65,45]]){
   const target=new THREE.Vector3(plate.x+dx,957,plate.z+dz),distance=target.distanceTo(origin),ray=new THREE.Raycaster(origin,target.sub(origin).normalize(),0,distance-1);
   assert.equal(ray.intersectObjects([...A,...B].filter(p=>visible(p.m)).map(p=>p.m)).length,0,'gantry obscures feeder exposure');
  }
 }
 for(const H of ['A','B']){const h=heads[H].head;h.updateMatrixWorld(true);
  for(const name of ['spindle-guide','spindle-bracket'])for(const n of heads[H].nozzles){
   const o=h.localToWorld(new THREE.Vector3(n.n.position.x,1400,n.n.position.z));
   const ray=new THREE.Raycaster(o,new THREE.Vector3(0,-1,0));assert.equal(ray.intersectObject(h.getObjectByName(name)).length,0,name+' blocks spindle');
  }
 }
 console.log(`${recipe}: ${samples} swept-volume samples, fixed camera/support clearance, spindle bores and fiducial axes passed`);
}
