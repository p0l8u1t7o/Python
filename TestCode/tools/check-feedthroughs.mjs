import * as THREE from 'three';
// Geometric tests against rendered triangles, not just declared hole metadata.
export function checkFeedthroughs(scene){
  scene.updateMatrixWorld(true);
  const plates=[],glands=[],routes=[],panels=[],meshes=[],failures=[];
  scene.traverse(o=>{if(o.userData.entryPlate)plates.push(o);if(o.userData.feedThrough)glands.push(o);if(o.userData.cable)routes.push(o);if(o.userData.controlPanel)panels.push(o);if(o.isMesh)meshes.push(o);});
  const ray=new THREE.Raycaster(),down=new THREE.Vector3(0,-1,0);
  let holeRays=0,wireCrossings=0,mountChecks=0;
  const fail=(name,detail)=>failures.push({name,detail});
  for(const panel of panels){
    const own=new Set();panel.traverse(o=>own.add(o));
    const walls=meshes.filter(m=>!own.has(m));
    const mounts=panel.children.filter(m=>m.name==='backplate standoff');
    if(mounts.length!==4)fail(panel.name,'Four backplate standoffs required');
    for(const mount of mounts){
      const half=mount.geometry.parameters.height/2;
      ray.set(new THREE.Vector3(0,-half+.1,0).applyMatrix4(mount.matrixWorld),down.clone().transformDirection(mount.matrixWorld));ray.far=.25;mountChecks++;
      if(!ray.intersectObjects(walls,false).length)fail(panel.name,'Backplate standoff has no cabinet wall contact');
    }
  }
  for(const plate of plates){
    plate.geometry.computeBoundingBox();const b=plate.geometry.boundingBox,h=b.max.y-b.min.y;
    for(const [x,z,r] of plate.userData.serviceBores||[]){
      for(const dx of [0,-r*.7,r*.7]){
        const p=new THREE.Vector3(x+dx,b.max.y+1,z).applyMatrix4(plate.matrixWorld);
        ray.set(p,down.clone().transformDirection(plate.matrixWorld));ray.far=h+2;holeRays++;
        if(ray.intersectObject(plate,false).length)fail(plate.name,'Declared hole is filled at '+[x+dx,z]);
      }
      // Positive control: neighbouring plate material must still exist.
      const p=new THREE.Vector3(x+r+2,b.max.y+1,z).applyMatrix4(plate.matrixWorld);
      ray.set(p,down.clone().transformDirection(plate.matrixWorld));ray.far=h+2;
      if(!ray.intersectObject(plate,false).length)fail(plate.name,'Missing material beside hole '+[x,z]);
    }
  }
  for(const gland of glands){
    const d=gland.userData.feedThrough,inv=gland.matrixWorld.clone().invert();
    for(const x of [0,-d.wireRadius,d.wireRadius]){
      ray.set(new THREE.Vector3(x,d.top+1,0).applyMatrix4(gland.matrixWorld),down.clone().transformDirection(gland.matrixWorld));ray.far=d.top-d.bottom+2;holeRays++;
      if(ray.intersectObject(gland,true).length)fail(gland.name,'Gland is not hollow');
    }
    // Every level through the sleeve must carry an actual cable, with radial clearance.
    for(const y of [d.top-.1,(d.bottom+4)/2,d.bottom+.1]){
      let fits=false;
      for(const route of routes){
        const points=route.userData.cable.points.map(p=>new THREE.Vector3(...p).applyMatrix4(route.matrixWorld).applyMatrix4(inv));
        for(let i=1;i<points.length;i++){
          const a=points[i-1],b=points[i],dy=b.y-a.y;if(Math.abs(dy)<1e-8)continue;
          const t=(y-a.y)/dy;if(t<0||t>1)continue;
          const p=a.clone().lerp(b,t);
          if(Math.hypot(p.x,p.z)+route.userData.cable.radius<=d.innerRadius+.05)fits=true;
        }
      }
      if(fits)wireCrossings++;else fail(gland.name,'No continuous cable fitting the gland at local Y='+y);
    }
  }
  return {plates:plates.length,glands:glands.length,holeRays,wireCrossings,mountChecks,failures};
}
