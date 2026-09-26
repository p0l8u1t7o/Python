import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createSim} from '../web/js/sim.js';
import {ST,Y0,BEAKER} from '../web/js/layout.js';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
const scene=new THREE.Scene(),sim=createSim(scene),{lab}=sim;
sim.apply(sim.plan.jobs[0].start+40);scene.updateMatrixWorld(true);
const probes=lab.head.children.filter(o=>o.name.startsWith('probe-')&&!o.name.startsWith('probe-collar-'));
let minimum=Infinity;
for(let i=0;i<probes.length;i++)for(let j=i+1;j<probes.length;j++){
 const a=probes[i],b=probes[j],gap=Math.hypot(a.position.x-b.position.x,a.position.z-b.position.z)-a.geometry.parameters.radiusTop-b.geometry.parameters.radiusTop-2.8;
 assert(gap>.25,a.name+' / '+b.name+' collars intersect');minimum=Math.min(minimum,gap);
}
for(const p of probes){const radial=Math.hypot(p.position.x-lab.headX,p.position.z-ST.sampler.z)+p.geometry.parameters.radiusTop+1.4;assert(radial<BEAKER.d/2-2,'probe crosses glass wall');}
const stirR=Math.hypot(12,14)+Math.hypot(11,3);assert(stirR<BEAKER.d/2-2,'rotating paddle hits glass');
const shaft=lab.head.getObjectByName('stirrer-shaft');let shaftGap=Infinity;
for(const p of lab.head.children.filter(o=>o.name.startsWith('probe-'))){
 const gap=Math.hypot(p.position.x-shaft.position.x,p.position.z-shaft.position.z)-p.geometry.parameters.radiusTop-shaft.geometry.parameters.radiusTop;
 assert(gap>.25,'stirrer shaft intersects '+p.name);shaftGap=Math.min(shaftGap,gap);
}
for(const p of probes){
 const horizontal=Math.hypot(p.position.x-lab.prop.position.x,p.position.z-lab.prop.position.z)-p.geometry.parameters.radiusTop-Math.hypot(11,3);
 const vertical=p.position.y-p.geometry.parameters.height/2-(lab.prop.position.y+1.5);
 assert(Math.max(horizontal,vertical)>.25,'paddle sweep intersects '+p.name);
}
const bench=scene.getObjectByName('bench-with-service-bores'),rack=scene.getObjectByName('tiprack-bored-body');
for(const [x,z] of [[ST.dock.x,ST.dock.z],[ST.tipChute.x,ST.tipChute.z],[ST.funnel.x,ST.funnel.z]]){
 const ray=new THREE.Raycaster(new THREE.Vector3(x,Y0+200,z),new THREE.Vector3(0,-1,0));assert.equal(ray.intersectObject(bench).length,0,'service port is blocked by solid bench');
}
for(let i=0;i<ST.tipRack.n;i++)for(const z of ST.tipRack.z){
 const ray=new THREE.Raycaster(new THREE.Vector3(ST.tipRack.x0+i*ST.tipRack.pitch,Y0+250,z),new THREE.Vector3(0,-1,0));assert.equal(ray.intersectObject(rack).length,0,'tip rack has no bore');
}
console.log(`PASS: probe collar clearance >= ${minimum.toFixed(2)} mm; stirrer shaft >= ${shaftGap.toFixed(2)} mm; paddle/probe sweep, three bench openings and all tip bores clear.`);
