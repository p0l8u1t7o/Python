// Run from RobotArmPressSSD with the existing Three.js loader.
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { projectPoint, projectRegion } from '@core/ui/vision-overlay.js';
import { ssdResults } from '../web/js/vision-results.js';
import { createStation } from '../web/js/station.js';
import { createSequence } from '../web/js/sequence.js';
import { RECIPES } from '../web/js/recipes.js';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
let checks=0;
const check=(v,msg)=>{assert.ok(v,msg);checks++;};
const cam=new THREE.PerspectiveCamera(50,1.5,1,1000);cam.updateMatrixWorld(true);
check(projectPoint(new THREE.Vector3(0,0,5),cam,600,400)===null,'behind-camera targets hidden');
check(projectPoint(new THREE.Vector3(0,0,-.5),cam,600,400)===null,'near-plane targets hidden');
const points=[new THREE.Vector3(-1,-1,-10),new THREE.Vector3(1,1,-10)];
const small=projectRegion(points,cam,300,200),large=projectRegion(points,cam,600,400);
check(Math.abs(large.x-small.x*2)<1e-8&&Math.abs(large.w-small.w*2)<1e-8,'resize preserves optical alignment');
check(projectRegion([new THREE.Vector3(100,0,-10)],cam,300,200)===null,'offscreen target hidden');
check(projectRegion([new THREE.Vector3(0,0,-10),new THREE.Vector3(100,0,-10)],cam,300,200).clipped,'partial target cannot claim a complete inspection');
for(const recipe of Object.values(RECIPES)){
  const st=createStation(new THREE.Scene(),recipe,recipe.multiPad?'bar':'single'),seq=createSequence({...st,recipe,insert:recipe.multiPad?'bar':'single'});
  for(const step of seq.steps.filter(s=>s.exposure&&s.station!==1)){
    const {state}=seq.sample(step.start+step.dur/2);st.robot.snap();st.robot.pipCam.updateWorldMatrix(true,false);
    const ids=state.shot==='R'?[recipe.stubborn.id]:seq.shots[+state.shot].map(c=>c.id);
    const marks=ssdResults(st.product,recipe,{global:false,exposure:true,ids,gaps:st.state.gap});
    for(const m of marks)check(!!projectRegion(m.points,st.robot.pipCam,600,400),'all silver-lead ROIs in camera');
    const pending=ssdResults(st.product,recipe,{global:false,exposure:false,ids,gaps:st.state.gap});
    check(pending.every(m=>m.status==='pending'&&!m.label.includes('OK')),'no stale pass before exposure');
    const ng=ssdResults(st.product,recipe,{global:false,exposure:true,ids:[ids[0]],gaps:{[ids[0]]:recipe.gapLimit+.01}});
    check(ng[0].status==='ng','gap above recipe limit is NG');
  }
}
const {createSim:createCopper}=await import('../../PCB-CopperAssembly/web/js/sim.js');
const {copperResults}=await import('../../PCB-CopperAssembly/web/js/vision-results.js');
const c=createCopper(new THREE.Scene()),{plan,machine:M,boards}=c;
for(const H of ['A','B']){
  for(const type of ['feed','up','down']){
    const tr=type==='feed'?plan.feeders[H].tr:plan.heads[H].tr;
    const t=type==='up'?plan.events.find(e=>e.type==='upcam'&&e.H===H).t:tr.segs.find(s=>s.flash).t1-.001;
    c.apply(t);const r=copperResults(type+H,t,plan,M,boards);
    const camera=type==='feed'?M.feeders[H].cam.cam:type==='up'?M.upCams[H].cam:M.heads[H].downCam.cam;
    check(r.marks.some(m=>projectRegion(m.points,camera,600,400)),type+H+' has a visible exposure target');
    if(type==='up'){c.apply(0);check(copperResults(type+H,0,plan,M,boards).marks.length===0,'flyby result cleared after exposure');}
    if(type==='feed')check(r.marks.some(m=>m.status==='ng'),'back-facing coin rejected');
  }
}
for(const src of ['s1','s3']){
  const t=plan[src].tr.segs.find(s=>s.flash).t1-.001;c.apply(t);
  const r=copperResults(src,t,plan,M,boards),cam=M.scanners[src.toUpperCase()].cam.cam;
  check(r.marks.some(m=>projectRegion(m.points,cam,600,400)),src+' ROI follows the correct conveyor board');
  c.apply(0);check(copperResults(src,0,plan,M,boards).marks.every(m=>m.status==='preview'),'scan no premature pass');
}
const {createNotebook}=await import('../../MilitaryGradePC/web/js/notebook.js');
const {notebookResults}=await import('../../MilitaryGradePC/web/js/vision-results.js');
const nb=createNotebook();nb.root.updateMatrixWorld(true);
for(const action of ['D1 連接器取像','BAT1 門面取像','底殼法規印刷','SN 與警語','外露 Docking 接點','螺絲／腳墊區域 1']){
  check(notebookResults(nb,{action},true,0).marks.length>0,action+' ROI');
  check(notebookResults(nb,{action},false,0).marks.length===0,'moving camera has no stale result');
}
const {createSim:createAcid}=await import('../../AutomaticAcid-BaseTitration/web/js/sim.js');
const {liquidResults}=await import('../../AutomaticAcid-BaseTitration/web/js/vision-results.js');
const acid=createAcid(new THREE.Scene());
for(const job of acid.plan.jobs){
  const t=job.start+90,info=acid.apply(t),r=liquidResults(acid.lab,info,t,'meniscus');
  const cup=acid.lab.items[`beaker${job.beaker}`],y=cup.localToWorld(new THREE.Vector3(0,cup.userData.fluid.surface.position.y,0)).y;
  check(r.marks[0].contour.every(p=>Math.abs(p.y-y)<1e-7),'meniscus ROI follows actual liquid height');
  check(r.marks[0].label.includes(`杯 ${job.beaker+1}`),'correct active cup ID');
}
console.log(`PASS: ${checks} vision checks; all camera sources, projection, exposure gating, NG threshold and liquid tracking.`);
