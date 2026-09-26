import * as THREE from 'three';
export function liquidResults(lab,info,T,view) {
  const job=info.sampler.job,active=`beaker${job?.beaker??0}`;
  const ids=view==='bottles'?Object.keys(lab.items).filter(id=>id.startsWith('bottle')):
    ['meniscus','titration','sampler'].includes(view)?[active]:
    (info.step.touch||[]).filter(id=>/^beaker|^bottle/.test(id));
  const targets=ids.length?ids:[active];
  const marks=targets.flatMap(id=>{
    const o=lab.items[id],u=o?.userData;if(!u?.fluid)return [];
    const ml=info.state.vol[id]||0,y=u.fluid.surface.position.y,r=u.r;
    const line=[-r,r].map(x=>o.localToWorld(new THREE.Vector3(x,y,0)));
    const contour=Array.from({length:49},(_,i)=>o.localToWorld(new THREE.Vector3(r*Math.cos(i*Math.PI/24),y,r*Math.sin(i*Math.PI/24))));
    return [{points:contour,contour,line,status:ml>0?'preview':'pending',
      label:`${id.startsWith('beaker')?'杯 '+(u.k+1):'瓶 '+(u.i+1)} · ${ml.toFixed(1)} mL · ${ml>0?'液面':'空杯'}`}];
  });
  return {title:'液面追蹤示意',state:'模型體積／非影像量測',time:T,marks};
}
