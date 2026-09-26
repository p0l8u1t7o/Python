// Shared source. Run tools/sync-cable-routing.mjs after editing.
// Millimetres. Visible routing concepts, not manufacturer cable/harness CAD.
import * as THREE from 'three';

export const CABLE = { power:0xe89139, signal:0x45acb5, air:0x4394dd, sleeve:0x343b44, earth:0xa4b645 };
const jacket = color => new THREE.MeshStandardMaterial({color,roughness:.66,metalness:.05});
const clipMat = jacket(0x69727c), connectorMat = new THREE.MeshStandardMaterial({color:0xa5adb4,roughness:.3,metalness:.75});
const V = p => new THREE.Vector3(...p);
const mark = (o,kind) => {o.userData.routingHardware=kind;return o;};

/** Clamped, static relative to its parent; endpoints are connector centres. */
export function cable(parent,name,points,{radius=2.5,color=CABLE.signal,clips=2,ends=true}={}) {
  const g=mark(new THREE.Group(),'route');g.name=name;parent.add(g);
  // Rounded polyline stays inside each corner's convex hull. A long Catmull-Rom
  // riser can overshoot its anchors and escape the enclosure by tens of mm.
  const vertices=points.map(V),curve=new THREE.CurvePath();let from=vertices[0];
  for(let i=1;i<vertices.length-1;i++) {
    const at=vertices[i],before=vertices[i-1],after=vertices[i+1],cut=Math.min(radius*12,at.distanceTo(before)*.35,at.distanceTo(after)*.35);
    const enter=at.clone().add(before.clone().sub(at).normalize().multiplyScalar(cut)),leave=at.clone().add(after.clone().sub(at).normalize().multiplyScalar(cut));
    curve.add(new THREE.LineCurve3(from,enter));curve.add(new THREE.QuadraticBezierCurve3(enter,at,leave));from=leave;
  }
  curve.add(new THREE.LineCurve3(from,vertices.at(-1)));
  const tube=mark(new THREE.Mesh(new THREE.TubeGeometry(curve,64,radius,8,false),jacket(color)),'jacket');
  tube.name=name+' / jacket';tube.castShadow=true;g.add(tube);
  g.userData.cable={radius,points:Array.from({length:129},(_,i)=>curve.getPoint(i/128).toArray()),length:curve.getLength(),type:'clamped'};
  const orient=(o,t)=>{o.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),curve.getTangent(t).normalize());o.position.copy(curve.getPoint(t));g.add(o);};
  for(let i=1;i<=clips;i++) {
    const ring=mark(new THREE.Mesh(new THREE.TorusGeometry(radius+1,1,6,12),clipMat),'clamp');orient(ring,i/(clips+1));
  }
  if(ends)for(const t of [0,1]) {
    const plug=mark(new THREE.Mesh(new THREE.CylinderGeometry(radius+1.6,radius+1.6,6,12),connectorMat),'gland');
    plug.geometry.rotateX(Math.PI/2);orient(plug,t);
    const boot=mark(new THREE.Mesh(new THREE.TorusGeometry(radius+.8,.9,6,12),jacket(0x20262c)),'strain-relief');orient(boot,t===0?.02:.98);
  }
  return g;
}

/** External fixed-length dress sections. Joint crossings use assumed internal
 * passages, so no unmodelled hanging loop pretends to support unlimited twist. */
export function armDress(j,L,{upperDepth=60,foreDepth=48,large=false}={}) {
  const uz=large?145:112,fz=large?135:90,end=Math.max(140,L.fore-L.wrist1-85);
  cable(j.j2,'ARM / upper protected section',[[0,115,uz],[0,L.upper-110,uz]],{radius:large?7:5,color:CABLE.sleeve,clips:3});
  cable(j.j3,'ARM / forearm protected section',[[90,L.foreOffset,fz],[end,L.foreOffset,fz]],{radius:large?6:4,color:CABLE.sleeve,clips:2});
  for(const y of [145,L.upper-140])support(j.j2,'ARM / sleeve standoff',[0,y,upperDepth],[0,y,uz-5],3);
  for(const x of [100,end-10])support(j.j3,'ARM / sleeve standoff',[x,L.foreOffset,foreDepth],[x,L.foreOffset,fz-4],3);
}

export function support(parent,name,a,b,radius=5) {
  const start=V(a),end=V(b),delta=end.clone().sub(start);
  const mesh=mark(new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,delta.length(),8),clipMat),'support');mesh.name=name;
  mesh.position.copy(start).add(end).multiplyScalar(.5);mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),delta.normalize());parent.add(mesh);return mesh;
}

/** Open cable trough with visible separate power/data lanes. No filled solid
 * covering up the cables. The installation plane is chosen by the caller. */
export function cableTray(parent,name,a,b,{width=46,height=16}={}) {
  const start=V(a),end=V(b),delta=end.clone().sub(start),length=delta.length();
  const g=mark(new THREE.Group(),'trough');g.name=name;g.position.copy(start).add(end).multiplyScalar(.5);
  g.quaternion.setFromUnitVectors(new THREE.Vector3(1,0,0),delta.normalize());parent.add(g);
  for(const [w,h,d,y,z] of [[length,2,width,-height/2,0],[length,height,2,0,-width/2],[length,height,2,0,width/2],[length,height-3,1,0,0]]) {
    const m=mark(new THREE.Mesh(new THREE.BoxGeometry(w,h,d),clipMat),'trough');m.position.set(0,y,z);g.add(m);
  }
  for(const [z,color] of [[-width/4,CABLE.power],[width/4,CABLE.signal]])
    cable(g,name+(z<0?' / power':' / data'),[[-length/2,0,z],[length/2,0,z]],{radius:3,color,clips:Math.max(2,Math.floor(length/220))});
  return g;
}

/** Constant-length rolling U carrier. Local X = travel, Y = rise, Z = width.
 * Analytic line/semicircle/line centreline keeps R and length fixed at all poses.
 * Cables occupy separate lanes at the neutral radius. Reuses GPU buffers. */
export function carrier(parent,name,{origin=[0,0,0],axis=[1,0,0],rise=[0,1,0],fixed=0,min=-100,max=100,radius=45,width=32,pitch=16,colors=[CABLE.power,CABLE.signal,CABLE.air]}={}) {
  const g=mark(new THREE.Group(),'carrier');g.name=name;parent.add(g);g.position.set(...origin);
  const x=V(axis).normalize(),y=V(rise).normalize(),z=x.clone().cross(y).normalize();
  if(Math.abs(x.dot(y))>1e-8)throw new Error('Carrier axes must be perpendicular');
  g.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x,y,z));
  const length=Math.max(Math.abs(min-fixed),Math.abs(max-fixed))+Math.PI*radius+60;
  const n=Math.ceil(length/pitch),h=12,count=80,radial=8,parts=[];
  const dummy=new THREE.Object3D(),up=new THREE.Vector3(0,0,1);
  for(const [size,offset] of [[[length/n*.9,h,3],[0,0,-width/2]],[[length/n*.9,h,3],[0,0,width/2]],[[3,2,width],[0,-h/2,0]]]) {
    const mesh=mark(new THREE.InstancedMesh(new THREE.BoxGeometry(...size),jacket(0x333d49),n),'chain-link');
    mesh.frustumCulled=false;mesh.castShadow=true;g.add(mesh);parts.push({mesh,offset});
  }
  const wires=[];
  for(const [lane,color] of [[-width*.26,colors[0]],[0,colors[1]],[width*.26,colors[2]]]) {
    const geo=new THREE.BufferGeometry(),positions=new Float32Array((count+1)*(radial+1)*3),normals=new Float32Array(positions.length),indices=[];
    for(let i=0;i<count;i++)for(let k=0;k<radial;k++){const a=i*(radial+1)+k,b=a+radial+1;indices.push(a,b,a+1,b,b+1,a+1);}
    geo.setAttribute('position',new THREE.BufferAttribute(positions,3).setUsage(THREE.DynamicDrawUsage));geo.setAttribute('normal',new THREE.BufferAttribute(normals,3).setUsage(THREE.DynamicDrawUsage));geo.setIndex(indices);
    const mesh=mark(new THREE.Mesh(geo,jacket(color)),'carrier-cable');mesh.frustumCulled=false;g.add(mesh);wires.push({mesh,lane});
  }
  const terminal=[];
  for(let i=0;i<2;i++){const mesh=mark(new THREE.Mesh(new THREE.BoxGeometry(12,h+4,width+6),clipMat),'carrier-anchor');g.add(mesh);terminal.push(mesh);}
  let previous=NaN,coord=fixed;
  function at(distance) {
    const c=(length-Math.PI*radius+fixed+coord)/2,a=c-fixed;
    if(distance<=a)return {p:new THREE.Vector3(fixed+distance,0,0),t:new THREE.Vector3(1,0,0)};
    if(distance<a+Math.PI*radius){const theta=(distance-a)/radius-Math.PI/2;return {p:new THREE.Vector3(c+radius*Math.cos(theta),radius+radius*Math.sin(theta),0),t:new THREE.Vector3(-Math.sin(theta),Math.cos(theta),0)};}
    return {p:new THREE.Vector3(c-(distance-a-Math.PI*radius),2*radius,0),t:new THREE.Vector3(-1,0,0)};
  }
  function set(value) {
    if(Math.abs(value-previous)<1e-7)return;
    if(value<min-1e-5||value>max+1e-5)throw new Error(name+' exceeds cable-carrier stroke: '+value);
    previous=value;coord=value;
    for(let i=0;i<n;i++) {
      const {p,t}=at((i+.5)*length/n),angle=Math.atan2(t.y,t.x);
      for(const {mesh,offset} of parts){dummy.position.copy(V(offset).applyAxisAngle(up,angle)).add(p);dummy.rotation.set(0,0,angle);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);}
    }
    for(const {mesh} of parts){mesh.instanceMatrix.needsUpdate=true;mesh.boundingBox=null;mesh.boundingSphere=null;}
    for(const {mesh,lane} of wires){const pos=mesh.geometry.attributes.position,nor=mesh.geometry.attributes.normal;
      for(let i=0;i<=count;i++){const {p,t}=at(i/count*length);for(let k=0;k<=radial;k++){const a=k/radial*Math.PI*2,c=Math.cos(a),s=Math.sin(a),nx=-t.y*c,ny=t.x*c,index=i*(radial+1)+k;pos.setXYZ(index,p.x+nx*2,p.y+ny*2,lane+s*2);nor.setXYZ(index,nx,ny,s);}}
      pos.needsUpdate=true;nor.needsUpdate=true;
    }
    terminal[0].position.set(fixed,0,0);terminal[1].position.set(coord,2*radius,0);
    g.userData.carrier={radius,length,min,max,coordinate:coord,width,points:Array.from({length:129},(_,i)=>at(i/128*length).p.toArray()),firstStraight:(length-Math.PI*radius-fixed+coord)/2,lastStraight:(length-Math.PI*radius+fixed-coord)/2};
  }
  set(THREE.MathUtils.clamp(fixed,min,max));
  return {group:g,set,at,length,radius};
}

export function routingLegend() {
  if(typeof document==='undefined'||!document.body||document.getElementById('routing-legend'))return;
  const el=document.createElement('details');el.id='routing-legend';
  el.style.cssText='position:fixed;right:18px;bottom:12px;z-index:30;max-width:300px;background:#13222ded;color:#dce7ec;border:1px solid #4b626e;border-radius:7px;padding:7px 11px;font:12px/1.6 sans-serif;box-shadow:0 3px 15px #0005';
  el.innerHTML='<summary style="cursor:pointer">線材配置 · 顏色說明</summary><div><span style="color:#e89139">●</span> 電源／驅動　<span style="color:#45acb5">●</span> 訊號／相機<br><span style="color:#4394dd">●</span> 氣管　灰黑：保護套與固定夾<br>拖鏈隨軸折返；關節內部走線以接頭表示。<br>示意路徑，線種與彎曲半徑待選型確認。</div>';
  document.body.appendChild(el);
}

// Refine a cable's large overall bounding box with its individual spans.
// A U/rounded route's empty interior must not be treated as solid material.
export function routeIntersectsBox(mesh,worldBox,margin=0) {
  const route=mesh.parent?.userData.cable;if(!route)return true;
  const box=worldBox.clone().expandByScalar(route.radius+margin),points=route.points.map(p=>V(p).applyMatrix4(mesh.parent.matrixWorld));
  for(let i=1;i<points.length;i++) {
    const a=points[i-1],b=points[i];let lo=0,hi=1;
    for(const k of ['x','y','z']){const d=b[k]-a[k];if(Math.abs(d)<1e-10){if(a[k]<box.min[k]||a[k]>box.max[k]){hi=-1;break;}}else{let x=(box.min[k]-a[k])/d,y=(box.max[k]-a[k])/d;if(x>y)[x,y]=[y,x];lo=Math.max(lo,x);hi=Math.min(hi,y);}}
    if(lo<=hi)return true;
  }
  return false;
}
