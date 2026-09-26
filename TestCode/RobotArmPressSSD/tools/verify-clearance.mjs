import assert from 'node:assert/strict';
import {createRobot,TOOL} from '../web/js/robot.js';
globalThis.document={createElement:()=>({getContext:()=>({fillRect(){},fillText(){}})})};
const robot=createRobot();
let checks=0;
for(const compression of [0,.5,1.5,TOOL.padStroke]){
 robot.setPadCompression(compression);
 for(const [name,base,seat,length,r,turns,end] of [['single-spring',69,69.5,16.5,3,6,86],...Array.from({length:8},(_,i)=>[`bar-spring-${i}`,73,73.5,9.5,2.6,4,83])]){
  const spring=robot.root.getObjectByName(name),p=spring.children[0].geometry.attributes.position;let radial=Infinity,zmin=Infinity;
  for(let i=0;i<p.count;i++){radial=Math.min(radial,Math.hypot(p.getX(i),p.getY(i)));zmin=Math.min(zmin,spring.position.z+p.getZ(i)*spring.scale.z);}
  assert(radial-r>.3,name+' spring penetrates guide rod');assert(zmin>base,name+' upper coil enters seat body');
  assert(Math.abs(spring.position.z-seat)<1e-9,name+' upper seat moves');
  assert(Math.abs(spring.position.z+length*spring.scale.z-(end-compression))<1e-9,name+' lower seat does not follow pad');
  assert((length-compression)/turns>.8,name+' coil bind');checks++;
 }
}
console.log(`PASS: ${checks} spring/rod checks through full 0–${TOOL.padStroke} mm travel; upper seats fixed, lower seats follow pads.`);
