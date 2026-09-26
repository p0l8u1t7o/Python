import * as THREE from 'three';
// Solid plate with actual through-bores. Position is the block centre, dimensions in mm.
export function perforated(parent,size,pos,holes,material){
  const [w,h,d]=size,s=new THREE.Shape();s.moveTo(-w/2,-d/2);s.lineTo(w/2,-d/2);s.lineTo(w/2,d/2);s.lineTo(-w/2,d/2);s.closePath();
  for(const [x,z,r] of holes){const p=new THREE.Path();p.absarc(x,-z,r,0,Math.PI*2,true);s.holes.push(p);}
  const geometry=new THREE.ExtrudeGeometry(s,{depth:h,bevelEnabled:false,curveSegments:32});geometry.rotateX(-Math.PI/2);geometry.translate(0,-h/2,0);
  const mesh=new THREE.Mesh(geometry,material);mesh.position.set(...pos);mesh.castShadow=mesh.receiveShadow=true;parent.add(mesh);return mesh;
}
