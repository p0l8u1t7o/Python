import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import * as THREE from 'three';
import {checkFeedthroughs} from './check-feedthroughs.mjs';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
const projects=['AutomaticAcid-BaseTitration','MilitaryGradePC','PCB-CopperAssembly','RobotArmPressSSD','shutter assembly'];
const report=[];
function segmentHits(a,b,box){let lo=0,hi=1;for(const k of ['x','y','z']){const d=b[k]-a[k];if(Math.abs(d)<1e-8){if(a[k]<box.min[k]||a[k]>box.max[k])return false;}else{let x=(box.min[k]-a[k])/d,y=(box.max[k]-a[k])/d;if(x>y)[x,y]=[y,x];lo=Math.max(lo,x);hi=Math.min(hi,y);if(lo>hi)return false;}}return true;}
for(const project of projects){
 const scene=new THREE.Scene(),base=new URL('../'+project+'/web/js/',import.meta.url),imp=n=>import(new URL(n+'.js',base));
 if(project==='AutomaticAcid-BaseTitration'||project==='PCB-CopperAssembly'){const {createSim}=await imp('sim');createSim(scene).apply(0);}
 else if(project==='MilitaryGradePC'){const {createCell}=await imp('cell');createCell(scene);}
 else {const {createStation}=await imp('station');if(project==='RobotArmPressSSD'){const {RECIPES}=await imp('recipes');createStation(scene,Object.values(RECIPES)[0],'bar');}else createStation(scene,{ng:false});}
 scene.updateMatrixWorld(true);const devices=[],wires=[],enclosures=[];scene.traverse(o=>{if(o.userData.electrical)devices.push(o);if(o.userData.electricalWire)wires.push(o);if(o.userData.electricalEnclosure){const e=o.userData.electricalEnclosure;enclosures.push(new THREE.Box3(new THREE.Vector3(...e.min),new THREE.Vector3(...e.max)).applyMatrix4(o.matrixWorld));}});
 const failures=[],ids=new Set();
 const bodies=devices.map(d=>{const m=d.children.find(c=>c.userData.electricalBody);return {d,b:new THREE.Box3().setFromObject(m)};});
 for(const {d,b} of bodies){if(ids.has(d.userData.electrical.id))failures.push('Duplicate ID '+d.name);ids.add(d.userData.electrical.id);if(!enclosures.some(e=>e.containsBox(b)))failures.push('Body outside cabinet '+d.name);}
 for(let i=0;i<bodies.length;i++)for(let j=i+1;j<bodies.length;j++){const overlap=bodies[i].b.clone().intersect(bodies[j].b).getSize(new THREE.Vector3());if([overlap.x,overlap.y,overlap.z].every(x=>x>.01))failures.push('Body overlap '+bodies[i].d.name+' / '+bodies[j].d.name);}
 for(const wire of wires){const points=wire.userData.electricalWire.points.map(p=>new THREE.Vector3(...p).applyMatrix4(wire.matrixWorld));for(const {d,b} of bodies){if(points.slice(1).some((p,i)=>segmentHits(points[i],p,b.clone().expandByScalar(.75))))failures.push('Wire crosses body '+wire.name+' / '+d.name);}}
 const ports=checkFeedthroughs(scene);failures.push(...ports.failures.map(f=>f.name+' / '+f.detail));
 assert(devices.length>8&&wires.length>5,project+' has no equipment');
 const {electricalActivity}=await imp('electrical-components');
 for(const role of ['motion','vision','force','io'])assert.equal(electricalActivity(role,{action:'壓合',vision:true,playing:true}),electricalActivity(role,{action:'壓合',vision:true,playing:false}),'Pause must freeze indicated process state');
 assert.equal(electricalActivity('motion',{action:'等待分析',motion:false}),false);
 assert.equal(electricalActivity('vision',{action:'移動',vision:false}),false);
 report.push({project,devices:devices.length,connections:wires.length,components:devices.map(o=>o.userData.electrical),feedthroughs:ports,failures});console.log(project,devices.length+' components',failures.length?'FAIL':'PASS',failures.slice(0,15));
}
writeFileSync(new URL('./review/electrical-plan-checks.json',import.meta.url),JSON.stringify({scope:'Static component body containment, body overlap, functional wire/body checks and real feedthroughs; not electrical certification',passed:report.every(r=>!r.failures.length),report},null,2));
if(report.some(r=>r.failures.length))process.exitCode=1;
