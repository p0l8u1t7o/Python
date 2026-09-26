import * as THREE from 'three';
import { objectRegion, planeRegion } from './vision-overlay.js';
export function ssdResults(product, recipe, {global, detected, exposure, ids, gaps}) {
  if(global)return product.ids.map(id=>({points:objectRegion(product.conns[id].pivot),label:id,status:detected?'ok':'preview'}));
  return ids.map(id=>{
    const c=product.conns[id],gap=gaps[id],y=Math.max(0,gap),status=exposure?(gap<=recipe.gapLimit?'ok':'ng'):'pending';
    const line=[0,y].map(h=>c.mount.localToWorld(new THREE.Vector3(0,h,c.T.leadL)));
    return {points:planeRegion(c.mount,0,y,c.T.leadL/2,c.T.leads*c.T.leadPitch,c.T.leadL),line,status,
      label:exposure?`${id} ${status.toUpperCase()} Δ ${gap.toFixed(3)} mm`:id+' 待取像'};
  });
}
