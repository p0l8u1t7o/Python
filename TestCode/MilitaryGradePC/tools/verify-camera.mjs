import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createNotebook,NB,selectSku} from '../web/js/notebook.js';
import {createCell,LAYOUT} from '../web/js/cell.js';
import {createRobot} from '../web/js/robot.js';
import {createSequence} from '../web/js/sequence.js';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
let exposures=0,ports=0;
for(const sku of ['V110-STND','V110-RF']){
  selectSku(sku);const scene=new THREE.Scene(),nb=createNotebook(),cell=createCell(scene),robot=createRobot(),carrier=new THREE.Group();
  scene.add(carrier,robot.root);carrier.add(nb.root);nb.root.position.y=-NB.H/2;robot.root.position.z=LAYOUT.railZ;
  const top=LAYOUT.conveyorTop+6+LAYOUT.palletH+LAYOUT.padH+LAYOUT.footOffset;
  const apply=s=>{carrier.position.set(s.palletX,top+s.palletLift+s.lift+NB.H/2,0);carrier.rotation.x=Math.PI*s.flip;cell.pallet.group.position.set(s.palletX,LAYOUT.conveyorTop+6+s.palletLift,0);nb.doors.forEach((d,i)=>d.set(s.doors[i].open,s.doors[i].latch));cell.setHead(s.s1Head);scene.updateMatrixWorld(true);};
  const seq=createSequence({nb,robot,apply}),cam=robot.inspectionCam,ray=new THREE.Raycaster();
  for(const step of seq.steps.filter(s=>s.exposure&&s.end.flashTool)){
    seq.sample(step.start+step.dur*.5);robot.snap();scene.updateMatrixWorld(true);cam.updateMatrixWorld(true);
    const target=robot.getTcpWorld('cam'),ndc=target.clone().project(cam),origin=cam.getWorldPosition(new THREE.Vector3());
    assert(Math.abs(ndc.x)<.001&&Math.abs(ndc.y)<.001,step.action+' optical axis');
    assert(ndc.z>-1&&ndc.z<1,step.action+' clipping');
    const cameraRay=new THREE.Vector3().subVectors(target,origin).normalize();assert(cameraRay.dot(cam.getWorldDirection(new THREE.Vector3()))>.999);
    const door=nb.doors.find(d=>step.action.startsWith(d.def.id+' '));
    if(door&&step.action.includes('連接器取像')){
      const bounds=new THREE.Box3().setFromObject(door.portGroup);
      for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z]){
        const p=new THREE.Vector3(x,y,z).project(cam);assert(Math.abs(p.x)<.98&&Math.abs(p.y)<.98,step.action+' complete connector field');
      }
      for(const port of door.portGroup.children){
        const p=port.localToWorld(new THREE.Vector3(0,0,2)),mouthDistance=p.distanceTo(origin);ray.set(origin,p.sub(origin).normalize());
        const hit=ray.intersectObjects(scene.children,true).find(h=>h.object.isMesh&&!h.object.material.transparent);
        let o=hit?.object;while(o&&o!==port)o=o.parent;
        // Looking through an empty socket may hit its recessed black backing.
        assert(o===port||(hit?.object===door.cavity&&hit.distance>mouthDistance),step.action+' connector occluded');ports++;
      }
    }
    exposures++;
  }
}
console.log(`PASS: ${exposures} optical poses and ${ports} unobstructed ports; complete connector framing for both SKUs.`);
