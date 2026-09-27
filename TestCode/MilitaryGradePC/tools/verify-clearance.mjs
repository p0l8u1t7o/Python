import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createNotebook,selectSku} from '../web/js/notebook.js';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
let minimum=Infinity,checks=0;
for(const sku of ['V110-STND','V110-RF']){
 selectSku(sku);const nb=createNotebook();nb.root.updateMatrixWorld(true);
 for(const door of nb.doors){
  const panel=door.hinge.children[0],inv=door.group.matrixWorld.clone().invert();
  function bounds(root){const box=new THREE.Box3(),v=new THREE.Vector3();root.traverse(m=>{if(!m.isMesh)return;const matrix=new THREE.Matrix4().multiplyMatrices(inv,m.matrixWorld),p=m.geometry.attributes.position;for(let i=0;i<p.count;i++)box.expandByPoint(v.fromBufferAttribute(p,i).applyMatrix4(matrix));});return box;}
  const gap=bounds(panel).min.z-bounds(door.portGroup).max.z;assert(gap>=.2,sku+' '+door.def.id+' closed cover intersects connector');minimum=Math.min(minimum,gap);checks++;
 }
}
console.log(`PASS: ${checks} closed doors; minimum connector/cover clearance ${minimum.toFixed(2)} mm.`);
const {createCell}=await import('../web/js/cell.js');
const scene=new THREE.Scene(),cell=createCell(scene);scene.updateMatrixWorld(true);
for(const name of ['CTRL / under-conveyor cabinet','CTRL / peripheral drive cabinet']){
const cabinet=scene.getObjectByName(name);
const cabinetBounds=new THREE.Box3().setFromObject(cabinet);
assert(Math.abs(cabinetBounds.min.y)<.01,'Cabinet must rest on floor');
let cabinetGap=Infinity,frameChecks=0;
cell.group.traverse(m=>{
 if(!['conveyor leg','conveyor foot'].includes(m.name))return;
 const b=new THREE.Box3().setFromObject(m),gap=Math.max(b.min.x-cabinetBounds.max.x,cabinetBounds.min.x-b.max.x,b.min.y-cabinetBounds.max.y,cabinetBounds.min.y-b.max.y,b.min.z-cabinetBounds.max.z,cabinetBounds.min.z-b.max.z);
 assert(gap>=10,'Electrical cabinet overlaps conveyor support '+m.position.toArray());
 cabinetGap=Math.min(cabinetGap,gap);frameChecks++;
});
assert(frameChecks>0);
console.log(`PASS: cabinet grounded; ${frameChecks} conveyor support checks, minimum clearance ${cabinetGap.toFixed(1)} mm.`);
}
