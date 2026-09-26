import assert from 'node:assert/strict';
import * as THREE from 'three';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
const {createSim}=await import('../web/js/sim.js');
const {tipFillHeight}=await import('../web/js/render-details.js');
const {Y0,ST,BEAKER}=await import('../web/js/layout.js');
const scene=new THREE.Scene(),sim=createSim(scene),{lab,plan}=sim;
let checks=0;
const check=(condition,message)=>{assert.ok(condition,message);checks++;};
for(const job of plan.jobs){
 sim.apply(job.rotEnd);check(Math.abs(lab.head.position.y-(Y0+190))<1e-6,'head clears vessels before lowering');
 const info=sim.apply(job.start+7),cup=lab.items[`beaker${job.beaker}`],fluid=cup.userData.fluid;
 check(lab.head.position.y===Y0,'head at operating height');check(lab.waterFlow.mesh.visible,'water flows during dilution');
 check(Math.abs(fluid.surface.position.y-(3+info.state.vol[`beaker${job.beaker}`]*1000/(Math.PI*cup.userData.r**2)))<1e-6,'volume determines surface height');
 sim.apply(job.start+90);check(lab.doseDrop.visible,'titrant drop appears during dosing');check(!lab.waterFlow.mesh.visible,'water stops after dilution');check(fluid.ripple.visible,'stirring surface visible');
 check(lab.head.position.y+lab.prop.position.y+1.5<cup.position.y+fluid.surface.position.y,'stirring paddle immersed after dilution');
 const a=JSON.stringify({head:lab.head.position.toArray(),prop:lab.prop.rotation.y,drop:lab.doseDrop.position.toArray(),surface:[...fluid.surface.geometry.attributes.position.array]});
 sim.apply(plan.total);sim.apply(0);sim.apply(job.start+90);
 const b=JSON.stringify({head:lab.head.position.toArray(),prop:lab.prop.rotation.y,drop:lab.doseDrop.position.toArray(),surface:[...fluid.surface.geometry.attributes.position.array]});
 check(a===b,'render state independent of seek history');
 sim.apply(job.liftEnd+.1);check(lab.head.position.y===Y0+190,'head rises after titration');check(lab.sprayLines.every(l=>l.mesh.visible),'rinse jets visible');
}
for(const st of plan.steps.filter(s=>s.label.startsWith('吐出'))){
 sim.apply(st.start+st.dur*.55);check(lab.pipFlow.mesh.visible,'pipette discharge visible');
 sim.apply(st.start+st.dur+.01);check(!lab.pipFlow.mesh.visible,'pipette discharge stops');
}
for(const ml of [.2,1,3,5]){
 const h=tipFillHeight(ml),r=.7+7.5*h/140,volume=Math.PI*h*(.49+.7*r+r*r)/3000;
 check(Math.abs(volume-ml)<1e-6,'conical tip fill preserves volume');check(h>0&&h<140,'tip liquid remains within cone');
}
sim.apply(0);check(!lab.doseDrop.visible&&!lab.waterFlow.mesh.visible&&!lab.pipFlow.mesh.visible,'no fluid effects before start');
check(lab.head.position.y+ST.sampler.plate+12>Y0+ST.sampler.plate+BEAKER.h,'raised probes above cup rim');
console.log(`${checks} render-state checks passed: head clearance, levels, flow timing, tip volume, pause/seek determinism.`);
