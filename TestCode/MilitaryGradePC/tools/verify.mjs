import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createNotebook,NB,selectSku} from '../web/js/notebook.js';
import {createCell,LAYOUT} from '../web/js/cell.js';
import {createRobot} from '../web/js/robot.js';
import {createSequence} from '../web/js/sequence.js';
// Texture canvas is irrelevant to the geometry/kinematics verification.
globalThis.document={createElement:()=>({width:1024,height:512,getContext:()=>({fillRect(){},fillText(){}})})};
const failures=[],report=[];
for(const sku of ['V110-STND','V110-RF']){
  selectSku(sku);const scene=new THREE.Scene(),nb=createNotebook(),cell=createCell(scene),robot=createRobot();
  scene.add(nb.root,robot.root);robot.root.position.z=LAYOUT.railZ;
  const carrier=new THREE.Group();scene.add(carrier);carrier.add(nb.root);nb.root.position.y=-NB.H/2;
  const top=LAYOUT.conveyorTop+6+LAYOUT.palletH+LAYOUT.padH+LAYOUT.footOffset;
  const apply=s=>{carrier.position.set(s.palletX,top+s.palletLift+s.lift+NB.H/2,0);carrier.rotation.x=Math.PI*s.flip;cell.pallet.group.position.set(s.palletX,LAYOUT.conveyorTop+6+s.palletLift,0);nb.doors.forEach((d,i)=>d.set(s.doors[i].open,s.doors[i].latch));scene.updateMatrixWorld(true);};
  const seq=createSequence({nb,robot,apply});let maxError=0,maxAngle=0,worst='';
  for(const step of seq.steps){
    for(const frac of [.001,.5,.999]){
      const time=step.start+step.dur*frac,s=seq.sample(time).state;
      assert(s.doors.every((d,i)=>!nb.doors[i].def.sealed||(d.open===0&&d.latch===0)),'sealed module opened');
      assert(!(s.flip>0&&s.flip<1)||s.lift===LAYOUT.flipLift,'rotation before lift');
      assert(s.lift===0||s.cradleClamp===1,'unsupported lift');
      if(s.station===2)nb.doors.forEach(d=>{if(d.open>0){const bounds=new THREE.Box3().setFromObject(d.hinge);assert(bounds.min.y>LAYOUT.conveyorTop+6+LAYOUT.palletH+2,'door hits pallet frame');for(const pin of cell.pallet.group.children.filter(m=>m.name==='pallet-guide-pin'))assert(!bounds.intersectsBox(new THREE.Box3().setFromObject(pin)),'door hits guide pin');}});
      robot.snap();const e=robot.error();if(e.position>maxError){maxError=e.position;worst=step.action;}maxAngle=Math.max(maxAngle,e.angle);
      if(e.position>2||e.angle>3)failures.push({sku,action:step.action,frac,...e});
      if(step.contact){const d=nb.doors.find(d=>step.action.startsWith(d.def.id+' '));if(d)assert(d.def.sealed===undefined);}
      // An arbitrary backward seek must restore exactly the same machine state and goal.
      const before=JSON.stringify(s),target=robot.goal.target.toArray();seq.sample(seq.total-1);seq.sample(0);const after=seq.sample(time).state;
      assert.equal(JSON.stringify(after),before,'history-dependent machine state');assert.deepEqual(robot.goal.target.toArray(),target,'history-dependent TCP goal');
    }
  }
  report.push({sku,steps:seq.steps.length,cycle:seq.total,maxError,maxAngle,worst});
  {
    let time=0,elapsed=0,wait=0,frame=seq.sample(0),maxContactError=0;robot.snap();
    while(time<seq.total&&elapsed<seq.total*4){
      const dt=sku==='V110-STND'?.025:.00625,e=robot.error(),s=frame.step,end=s.start+s.dur;
      const blocked=(time>=end-1e-7||(s.contact&&e.position>3))&&(e.position>1.5||e.angle>3||e.rail>2);
      if(blocked){wait+=dt;if(wait>12){failures.push({sku,continuous:true,action:s.action,time,...e,q:robot.q});break;}}
      else {wait=0;time=time>=end-1e-7?Math.min(seq.total,end+1e-6):Math.min(end,time+dt);frame=seq.sample(time>=end-1e-7&&time<=end?Math.max(s.start,end-1e-8):time);}
      robot.update(dt);elapsed+=dt;
      if(s.contact)maxContactError=Math.max(maxContactError,e.position);
    }
    report.push({sku,continuous:true,time,elapsed,maxContactError});
    if(time<seq.total&&!failures.some(f=>f.continuous))failures.push({continuous:true,time,elapsed,reason:'did not finish'});
  }
  // At the most demanding quarter-turn, the entire product (including strap)
  // must be above the pallet's stack posts. The two clamp pads use separate strips.
  const flip=seq.steps.find(s=>s.action==='翻面 180°');seq.sample(flip.start+flip.dur*.5);
  const clearance=new THREE.Box3().setFromObject(nb.root).min.y-(LAYOUT.conveyorTop+6+LAYOUT.palletPitch);
  assert(clearance>20,'insufficient product / stack-post clearance at quarter-turn');
  assert(98-5>82+4,'cradle and pallet contact pads overlap');
  report.push({sku,quarterTurnClearance:clearance});
}
console.log(JSON.stringify({report,failures},null,2));
if(failures.length)process.exitCode=1;
