// Geometry checks for the photo-derived changes: real holes, vacuum support,
// thin-sheet stack and recessed windings. No rasterizer or npm dependencies.
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import * as THREE from 'three';
import { createBase, createBlade, createCover, PART, BLADES, bladeSeat, bladeHoles } from '../web/js/product.js';

const ray = new THREE.Raycaster(), down = new THREE.Vector3(0,-1,0);
function hit(object,x,z) {
  object.updateMatrixWorld(true);
  ray.set(new THREE.Vector3(x,10,z),down);
  return ray.intersectObject(object,true)[0];
}
const cover = createCover(), checks = [];
for(const [x,z] of [[0,0],[6.1,-5.1],[-6.1,5.1],[6.6,-2.9],[-6.6,2.9],[7.6,6.9],[-7.6,-6.9],[6.35,.2],[6.35,1.7]]) {
  assert.equal(hit(cover,x,z),undefined,`Cover opening filled at ${x},${z}`);
}
checks.push('9 cover openings are real through-holes');
let vacuumSamples=0;
for(const x of PART.coverPads.x) for(const z of PART.coverPads.z) {
  for(let i=0;i<=8;i++) for(let j=0;j<=8;j++) {
    const h=hit(cover,x+(i/8-.5)*PART.coverPads.w,z+(j/8-.5)*PART.coverPads.d);
    assert(h && Math.abs(h.point.y)<1e-5,'Vacuum pad overlaps a hole or overhang'); vacuumSamples++;
  }
}
checks.push(`${vacuumSamples} lid vacuum contact samples are supported`);
for(const kind of ['small','large']) {
  const blade=createBlade(kind), holes=bladeHoles();
  for(const p of Object.values(holes)) assert.equal(hit(blade,p.x,p.z),undefined,kind+' blade hole filled');
  for(let i=0;i<=8;i++) for(let j=0;j<=16;j++) assert(hit(blade,(i/8-.5)*1.4,(j/16-.5)*5),'Blade vacuum pad overhang');
  const bounds=new THREE.Box3().setFromObject(blade);
  assert(Math.abs(bounds.max.y)<1e-6 && Math.abs(bounds.min.y+PART.blade.t)<1e-6,'Blade thickness changed');
}
checks.push('Both blade holes and full T1 contact footprint are clear/supported');
const base=createBase(); base.updateMatrixWorld(true);
const lowestBladeBottom=bladeSeat(BLADES[0]).y-PART.blade.t;
let windingGap=Infinity;
for(const name of ['actuator-winding-0','actuator-winding-1']) {
  const winding=base.getObjectByName(name), bounds=new THREE.Box3().setFromObject(winding);
  const h=hit(base,winding.position.x,winding.position.z);
  assert.equal(h?.object,winding,'Body closes over winding pocket');
  assert(bounds.min.y>-2,'Winding intersects pocket floor');
  windingGap=Math.min(windingGap,lowestBladeBottom-bounds.max.y);
}
assert(windingGap>.1,'Windings interfere with the blade stack');
globalThis.document = { createElement: () => ({ width:1024,height:512,getContext:()=>({fillRect(){},fillText(){}}) }) };
const { createStation }=await import('../web/js/station.js');
const { createSequence }=await import('../web/js/sequence.js');
let opticalSamples=0;
for(const ng of [false,true]) {
  const scene=new THREE.Scene(), st=createStation(scene,{ng});
  const seq=createSequence({robot:st.robot,apply:st.apply,ng});
  for(const step of seq.steps.filter(s=>s.exposure==='up')) {
    const {state}=seq.sample(step.start+step.dur/2);st.robot.snap();st.sync();
    const id=state.shot.split(':')[1]; if(id==='cover') continue;
    const part=st.parts[id], meshes=[];
    st.robot.tool.traverse(o=>{if(o.isMesh && !o.material.transparent)meshes.push(o);});
    const backdrop=st.robot.tool.getObjectByName('T1-camera-backdrop');
    // Across the sensor, the first solid must be the blade or the physical white plate.
    // A nozzle collar visible beyond the silhouette fails this check.
    for(let i=0;i<=12;i++) for(let j=0;j<=10;j++) {
      ray.setFromCamera(new THREE.Vector2(-.98+i*1.96/12,-.98+j*1.96/10),st.cell.upCam);
      const bladeHit=ray.intersectObject(part,true)[0];
      const first=ray.intersectObjects([...meshes,part],true)[0];
      assert(first,'Empty up-camera ray');
      assert(bladeHit ? first.object===bladeHit.object : first.object===backdrop,`${id}: tool obscures blade/background`);
      opticalSamples++;
    }
  }
}
checks.push(`${opticalSamples} up-camera rays: blade silhouette/background unobstructed (OK and NG)`);
const report={checks,windingToBladeGapMm:+windingGap.toFixed(4),vacuumSamples,opticalSamples,failures:[]};
writeFileSync(new URL('../review/product-detail.json',import.meta.url),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
