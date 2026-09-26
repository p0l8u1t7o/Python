// Run with the selected project's Three.js loader. Tests the rendered routing.
import assert from 'node:assert/strict';
import {writeFileSync,mkdirSync} from 'node:fs';
import * as THREE from 'three';
import {sampleTimes} from './geometry-clearance.mjs';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
const project=process.argv[2],interval=Number(process.env.CABLE_INTERVAL||.1);
const base=new URL('../'+project+'/web/js/',import.meta.url),imp=name=>import(new URL(name+'.js',base));
const {carrier,routeIntersectsBox,cable}=await imp('cable-routing');
// Independent controls: a route's empty bounding-box interior is clear, its
// material span is blocked, and the carrier endpoints obey an absolute stroke.
{
  const s=new THREE.Scene(),r=cable(s,'control',[[0,0,0],[0,100,0],[100,100,0]],{radius:2,clips:0});s.updateMatrixWorld(true);
  assert(!routeIntersectsBox(r.children[0],new THREE.Box3(new THREE.Vector3(48,48,-3),new THREE.Vector3(52,52,3))));
  assert(routeIntersectsBox(r.children[0],new THREE.Box3(new THREE.Vector3(-3,48,-3),new THREE.Vector3(3,52,3))));
  const c=carrier(s,'control carrier',{min:-100,max:100,radius:40});
  for(const x of [-100,-70,0,23,100]){c.set(x);assert(c.at(0).p.distanceTo(new THREE.Vector3(0,0,0))<1e-8);assert(c.at(c.length).p.distanceTo(new THREE.Vector3(x,80,0))<1e-8);}
  assert.throws(()=>c.set(101),/stroke/);
}
const scenarios=[],scene=()=>new THREE.Scene();
const meshList=root=>{const a=[];root.traverse(m=>{if(m.isMesh&&!m.userData.routingHardware&&m.geometry.type!=='PlaneGeometry')a.push(m);});return a;};
if(project==='PCB-CopperAssembly') {
  const {createSim}=await imp('sim'),{RECIPES,setRecipe}=await imp('layout');
  for(const key of Object.keys(RECIPES)) {setRecipe(key);const s=scene(),sim=createSim(s),m=sim.machine;
    const times=new Set(sampleTimes(0,sim.plan.cycle,interval));
    for(const tr of [sim.plan.s0,sim.plan.s4,sim.plan.s1.tr,sim.plan.s3.tr,...Object.values(sim.plan.heads).map(h=>h.tr)])for(const seg of tr.segs){times.add(seg.t0);times.add(seg.t1);}
    scenarios.push({name:key,scene:s,apply:t=>sim.apply(t),times:[...times].sort((a,b)=>a-b),obstacles:[...m.keepout,...meshList(m.occluders),...Object.values(m.heads).flatMap(h=>meshList(h.beam)),...Object.values(m.loaders).flatMap(h=>meshList(h.car)),...Object.values(m.scanners).flatMap(h=>meshList(h.beam)),...Object.values(m.feeders).flatMap(h=>meshList(h.cam.group))]});
  }
} else if(project==='AutomaticAcid-BaseTitration') {
  const {createSim}=await imp('sim'),s=scene(),sim=createSim(s);
  scenarios.push({name:'full-batch',scene:s,apply:t=>sim.apply(t),times:sim.plan.steps.flatMap(p=>sampleTimes(p.start,p.dur,p.kind==='wait'?p.dur||1:interval)),obstacles:[...sim.robot.clearanceParts.arm,...sim.robot.clearanceParts.tool,...sim.lab.keepout.map(k=>k.mesh)]});
} else if(project==='RobotArmPressSSD'||project==='shutter assembly') {
  const {createStation}=await imp('station'),{createSequence}=await imp('sequence');
  const modes=project==='RobotArmPressSSD'?Object.entries((await imp('recipes')).RECIPES).flatMap(([key,r])=>(r.multiPad?['bar','single']:['single']).map(insert=>({key:key+'/'+insert,recipe:r,insert}))):[{key:'OK',ng:false},{key:'NG',ng:true}];
  for(const mode of modes) {const s=scene(),st=mode.recipe?createStation(s,mode.recipe,mode.insert):createStation(s,mode);
    const seq=mode.recipe?createSequence({...st,...mode}):createSequence({robot:st.robot,apply:st.apply,ng:mode.ng});
    scenarios.push({name:mode.key,scene:s,apply:t=>{seq.sample(t);st.robot.snap();st.sync?.();},times:seq.steps.flatMap(p=>sampleTimes(p.start,p.dur,interval)),obstacles:[...st.robot.clearanceParts.arm,...meshList(st.robot.tool),...st.cell.keepout.flatMap(meshList),...meshList(st.cell.occluders)]});
  }
} else if(project==='MilitaryGradePC') {
  const {createNotebook,NB,selectSku}=await imp('notebook'),{createCell,LAYOUT}=await imp('cell'),{createRobot}=await imp('robot'),{createSequence}=await imp('sequence');
  for(const sku of ['V110-STND','V110-RF']) {selectSku(sku);const s=scene(),nb=createNotebook(),cell=createCell(s),robot=createRobot(),holder=new THREE.Group();s.add(robot.root,holder);holder.add(nb.root);nb.root.position.y=-NB.H/2;robot.root.position.z=LAYOUT.railZ;
    const top=LAYOUT.conveyorTop+6+LAYOUT.palletH+LAYOUT.padH+LAYOUT.footOffset;
    const apply=q=>{holder.position.set(q.palletX,top+q.palletLift+q.lift+NB.H/2,0);holder.rotation.x=Math.PI*q.flip;nb.doors.forEach((d,i)=>d.set(q.doors[i].open,q.doors[i].latch));cell.cradle.lift.position.y=top+NB.H/2+q.cradleLift;cell.cradle.rot.rotation.x=Math.PI*q.flip;cell.cradle.setClamp(q.cradleClamp);cell.setHead(q.s1Head);s.updateMatrixWorld(true);};
    const seq=createSequence({nb,robot,apply});scenarios.push({name:sku,scene:s,apply:t=>{seq.sample(t);robot.snap();},times:seq.steps.flatMap(p=>sampleTimes(p.start,p.dur,interval)),obstacles:[...robot.clearanceParts.arm,...robot.clearanceParts.tool,...cell.keepout,...meshList(cell.occluders)]});
  }
} else throw new Error('Specify a supported project folder');

// Segment against expanded mesh-local bounds: conservative capsule broad test.
function segmentBox(a,b,box) {
  let lo=0,hi=1;
  for(const k of ['x','y','z']){const d=b[k]-a[k];if(Math.abs(d)<1e-10){if(a[k]<box.min[k]||a[k]>box.max[k])return false;}else{let x=(box.min[k]-a[k])/d,y=(box.max[k]-a[k])/d;if(x>y)[x,y]=[y,x];lo=Math.max(lo,x);hi=Math.min(hi,y);if(lo>hi)return false;}}
  return true;
}
const failures=new Map(),report=[];
const fail=(key,detail)=>{if(!failures.has(key))failures.set(key,{key,...detail});};
for(const sc of scenarios) {
  const routes=[];sc.scene.traverse(g=>{if(g.userData.cable||g.userData.carrier)routes.push(g);});
  const obstacles=[...new Set(sc.obstacles)].filter(m=>!m.userData.routingHardware),lengths=new Map();let samples=0,carriers=0;
  for(const t of sc.times) {
    sc.apply(t);sc.scene.updateMatrixWorld(true);samples++;
    const obs=obstacles.map(m=>{if(!m.geometry.boundingBox)m.geometry.computeBoundingBox();return {m,b:m.geometry.boundingBox.clone(),world:new THREE.Box3().setFromObject(m),inv:m.matrixWorld.clone().invert()};});
    for(const g of routes) {
      const d=g.userData.carrier||g.userData.cable,isCarrier=!!g.userData.carrier;
      if(isCarrier){assert(d.firstStraight>=0&&d.lastStraight>=0,g.name+' taut');assert(Math.abs(d.firstStraight+d.lastStraight+Math.PI*d.radius-d.length)<1e-8,g.name+' length changes');assert(!lengths.has(g)||Math.abs(lengths.get(g)-d.length)<1e-8);lengths.set(g,d.length);}
      const points=d.points.map(p=>new THREE.Vector3(...p).applyMatrix4(g.matrixWorld)),radius=isCarrier?Math.hypot(d.width/2+3,8):d.radius;
      const world=new THREE.Box3().setFromPoints(points).expandByScalar(radius);
      for(const ob of obs) {
        if(!world.intersectsBox(ob.world))continue;
        const local=points.map(p=>p.clone().applyMatrix4(ob.inv)),b=ob.b.clone().expandByScalar(radius);
        // Only the first/last 10 mm may seat in a connector/mount. No whole
        // mechanism exemption; the free span is still checked against its host.
        let distance=0;const total=points.slice(1).reduce((sum,p,i)=>sum+p.distanceTo(points[i]),0);
        for(let i=1;i<local.length;i++){const seg=points[i].distanceTo(points[i-1]),start=distance;distance+=seg;if(distance<=10||start>=total-10||seg<1e-9)continue;
          const a=local[i-1].clone().lerp(local[i],Math.max(0,(10-start)/seg)),end=local[i-1].clone().lerp(local[i],Math.min(1,(total-10-start)/seg));
          const bores=ob.m.userData.serviceBores||[];
          if(bores.some(([x,z,r])=>[a,end].every(p=>Math.hypot(p.x-x,p.z-z)+radius+.25<r)))continue;
          // A cylinder does not occupy the four corners of its enclosing box.
          const shape=ob.m.geometry.parameters;
          if(ob.m.geometry.type==='CylinderGeometry'){
            const r=Math.max(shape.radiusTop,shape.radiusBottom),sz=ob.b.getSize(new THREE.Vector3());
            if(Math.abs(sz.x-2*r)<.01&&Math.abs(sz.z-2*r)<.01){const dx=end.x-a.x,dz=end.z-a.z,u=THREE.MathUtils.clamp(-(a.x*dx+a.z*dz)/(dx*dx+dz*dz||1),0,1);if(Math.hypot(a.x+u*dx,a.z+u*dz)>r+radius+.01)continue;}
          }
          if(segmentBox(a,end,b)){fail(sc.name+'/'+g.name+'/'+(ob.m.name||ob.m.geometry.type),{time:+t.toFixed(3),point:points[i].toArray().map(x=>+x.toFixed(2)),obstacleLocal:[a.toArray(),end.toArray()],obstacleBounds:[ob.b.min.toArray(),ob.b.max.toArray()],method:'expanded mesh bounds; potential interference'});break;}
        }
      }
    }
  }
  carriers=routes.filter(g=>g.userData.carrier).length;
  assert(routes.length>=5,'Routing missing');report.push({scenario:sc.name,samples,routes:routes.length,carriers});
}
const out={project,interval,method:'constant carrier length/radius; conservative cable-segment vs expanded mesh bounds; endpoint mount allowance 10 mm',report,failures:[...failures.values()]};
const dir=new URL('../'+project+'/review/',import.meta.url);mkdirSync(dir,{recursive:true});writeFileSync(new URL('cables.json',dir),JSON.stringify(out,null,2));
console.log(JSON.stringify({...out,failures:out.failures.slice(0,35)},null,2));
if(out.failures.length)process.exitCode=1;
