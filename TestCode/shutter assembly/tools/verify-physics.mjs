import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import * as THREE from 'three';
import { meshBounds, separatingGap, sampleTimes } from '../../tools/geometry-clearance.mjs';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
const {createStation}=await import('../web/js/station.js');
const {createSequence}=await import('../web/js/sequence.js');
const {TRAYS,pocket,LAYOUT}=await import('../web/js/cell.js');
const {createBase,createBlade,createCover,createAssembly,setCoverFlex,bladeSeat,BLADES,PART}=await import('../web/js/product.js');
const failures=[],report=[];
const meshes=o=>{const a=[];o.traverse(m=>{if(m.isMesh && m.geometry.type!=='PlaneGeometry')a.push(m)});return a;};
const label=m=>m.name||`${m.geometry.type}@${m.position.toArray().map(x=>x.toFixed(1)).join(',')}`;
const box=m=>new THREE.Box3().setFromObject(m);
const overlap=(a,b)=>a.clone().intersect(b).getSize(new THREE.Vector3()).toArray().every(x=>x>1e-4);
const remember=(key,detail)=>{if(!failures.some(f=>f.key===key))failures.push({key,...detail});};

// Surface samples against the actual extruded body, including reliefs and openings.
const body=createBase(),bodyLayers=meshes(body).filter(m=>m.geometry.type==='ExtrudeGeometry');
const cast=new THREE.Raycaster(),down=new THREE.Vector3(0,-1,0),point=new THREE.Vector3();
body.updateMatrixWorld(true);
function bodyIntersections(part,label) {
  part.updateMatrixWorld(true);
  for(const mesh of meshes(part)) {
    const positions=mesh.geometry.attributes.position;
    for(let i=0;i<positions.count;i++) {
      point.fromBufferAttribute(positions,i).applyMatrix4(mesh.matrixWorld);
      for(const layer of bodyLayers) {
        const b=box(layer);if(point.y<=b.min.y+1e-5 || point.y>=b.max.y-1e-5)continue;
        cast.set(new THREE.Vector3(point.x,10,point.z),down);
        if(cast.intersectObject(layer)[0]) {remember(label,{point:point.toArray()});return;}
      }
    }
  }
}
for(const b of BLADES) {
  const part=createBlade(b.kind),seat=bladeSeat(b);part.position.set(seat.x,seat.y,seat.z);part.rotation.y=seat.yaw;
  bodyIntersections(part,'blade-body/'+b.id);
}
const clipCover=createCover();
for(let i=0;i<=200;i++) {const gap=i/100;clipCover.position.y=PART.cover.t+gap;setCoverFlex(clipCover,gap);bodyIntersections(clipCover,'cover-body');}
report.push({staticChecks:['tray cavity fit under ±0.35 mm / ±0.03 rad offsets','blade/body fit','201 cover approach / spring-latch positions']});

// Every tray product must fit its cavity, including the lead/connector and pickup offset.
for(const kind of Object.keys(TRAYS)) {
  const t=TRAYS[kind],part=kind==='base'?createAssembly():kind==='cover'?createCover():createBlade(kind);
  for(const yaw of [-.03,0,.03]) for(const dx of [-.35,.35]) for(const dz of [-.35,.35]) {
    part.rotation.y=yaw;part.position.set(dx,kind==='base'?PART.base.h:kind==='cover'?1.45:PART.blade.t,dz);
    const b=box(part),cx=t.offsetX||0;
    if(b.min.x<cx-t.pocket[0]/2+.15 || b.max.x>cx+t.pocket[0]/2-.15 || b.min.z<-t.pocket[1]/2+.15 || b.max.z>t.pocket[1]/2-.15 || b.min.y<-.001)
      remember('tray-fit/'+kind,{bounds:[b.min.toArray(),b.max.toArray()],yaw,dx,dz});
  }
}

for(const ng of [false,true]) {
  const mode=ng?'NG':'OK',scene=new THREE.Scene(),st=createStation(scene,{ng}),seq=createSequence({robot:st.robot,apply:st.apply,ng});
  const tool=meshes(st.robot.tool),arm=st.robot.clearanceParts.arm;
  const fixed=[...st.cell.keepout.flatMap(meshes),...meshes(st.cell.occluders)];
  let samples=0,maxCompression=0,minRearGap=Infinity;
  for(const step of seq.steps) for(const time of sampleTimes(step.start,step.dur,.02)) {
    seq.sample(time);st.robot.snap();st.sync();samples++;
    const boxes=tool.map(m=>({m,b:box(m)})),fx=fixed.map(m=>({m,b:box(m)}));
    for(const {m,b} of boxes) {
      for(const f of fx) if(overlap(b,f.b) && separatingGap(meshBounds(m),meshBounds(f.m))<-.001)
        remember(`${mode}/tool-fixed/${label(m)}/${label(f.m)}`,{time,action:step.action});
      for(const a of arm) if(overlap(b,box(a)) && separatingGap(meshBounds(m),meshBounds(a))<-.001)
        remember(`${mode}/tool-arm/${label(m)}/${label(a)}`,{time,action:step.action});
      if(b.min.y<915) for(const solid of st.cell.traySolids) if(overlap(b,solid.box))
        remember(`${mode}/tool-tray/${label(m)}/${solid.name}`,{time,action:step.action});
    }
    for(const a of arm) for(const f of meshes(st.cell.occluders)) if(overlap(box(a),box(f)) && separatingGap(meshBounds(a),meshBounds(f))<-.001)
      remember(`${mode}/arm-guard/${label(a)}/${label(f)}`,{time,action:step.action});
    for(const a of arm)minRearGap=Math.min(minRearGap,box(a).min.z-LAYOUT.encl.z0-1);
    if(st.state.loc.cover==='base') {
      const lidTop=st.pose('cover').p.y;
      for(const {m,b} of boxes.filter(({m})=>m.name==='T2-vacuum-pad')) {
        if(st.state.press>0 && b.min.y<lidTop-.005)remember(mode+'/press-penetration',{time,penetration:lidTop-b.min.y});
      }
      maxCompression=Math.max(maxCompression,st.robot.compliance);
    }
  }
  const release=seq.steps.find(s=>s.action==='鬆開夾緊');
  seq.sample(release.start);st.robot.snap();st.sync();const before=st.pose('base').p.clone();
  seq.sample(release.start+release.dur);st.robot.snap();st.sync();assert(before.distanceTo(st.pose('base').p)<1e-6,'Unclamping moves body');
  // The actual optical axis passes through the table, ESD mat and light housing.
  cast.set(new THREE.Vector3(LAYOUT.upCam.x,LAYOUT.table-24,LAYOUT.upCam.z),new THREE.Vector3(0,1,0));
  for(const name of ['table-optical-port','esd-optical-port','上視環形光']) {
    assert.equal(cast.intersectObject(st.cell.group.getObjectByName(name)).length,0,'Blocked optical port: '+name);
  }
  if(ng) {
    const drop=seq.steps.find(s=>s.action==='NG 料落入盒內');let prevY=Infinity;
    for(let i=0;i<=20;i++) {seq.sample(drop.start+drop.dur*i/20);st.robot.snap();st.sync();const y=st.pose('L2x').p.y;assert(y<=prevY+1e-5,'Reject rises while falling');prevY=y;}
    assert(Math.abs(prevY-(LAYOUT.table+2+PART.blade.t*2))<1e-5,'Reject not on bin floor');
  }
  report.push({mode,samples,maxCompression:+maxCompression.toFixed(4),rearPanelGapMm:+minRearGap.toFixed(3)});
}
writeFileSync(new URL('../review/physics.json',import.meta.url),JSON.stringify({report,failures},null,2));
console.log(JSON.stringify({report,failures},null,2));if(failures.length)process.exitCode=1;
