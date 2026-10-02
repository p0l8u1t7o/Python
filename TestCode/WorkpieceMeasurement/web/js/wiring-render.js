import * as THREE from 'three';
import {STATIC_ROUTES,FIXED_SUPPORTS,movingRoutes,movingSupports,frameOrigin} from './wiring-plan.js';
const color=hex=>new THREE.MeshStandardMaterial({color:hex,roughness:.65,metalness:.15});
const jacket=color(0x263940),metal=color(0x8c9ca4),fiber=color(0xc293ec),hose=color(0x54a8c3);
const V=a=>new THREE.Vector3(...a),Y=new THREE.Vector3(0,1,0);
function box(g,name,size,at,mat=metal){const m=new THREE.Mesh(new THREE.BoxGeometry(...size),mat);m.name=name;m.position.set(...at);m.castShadow=true;g.add(m);return m;}
export function managedWiring(root,s,owners){
 const group=new THREE.Group();group.name='Supported wiring / constant-length carriers';root.add(group);
 const fixed=new THREE.Group();group.add(fixed);
 for(const [n,size,at]of FIXED_SUPPORTS)box(fixed,n,size,at);
 for(const r of STATIC_ROUTES){const mesh=new THREE.Mesh(new THREE.TubeGeometry(r.path,140,r.radius+1.5,8,false),jacket);mesh.name=r.id+' / fixed protective sleeve';mesh.userData.wiring=r;fixed.add(mesh);}
 const moving=[],chains=new Map(),ports=new Map();
 // X 鏈末端與 Z 鏈起點是同一個接續點，只放一個應力消除環；軟管起點由 hose anchor 夾持，不另加環
 const anchors=new Set(['X-CHAIN0','X-CHAIN1','Z-CHAIN1','HOSE-LEAD1','HEAD-LEAD0','HEAD-LOOP1','LOWER-LEAD0','UP-R-LOOP0','DN-R-LOOP0']);
 const initialize=movingRoutes({tx:0,zt:1010,a:6,headLift:30,r2:0},s);
 for(const r of initialize){
   const mesh=new THREE.Mesh(new THREE.TubeGeometry(r.path,140,r.radius,8,false),r.id.includes('HEAD')||r.id.includes('LOOP')||r.id.includes('LOWER')?fiber:r.id.includes('HOSE')?hose:jacket);mesh.name=r.id;group.add(mesh);moving.push(mesh);
   for(const end of [0,1]){if(!anchors.has(r.id+end))continue;const p=new THREE.Mesh(new THREE.TorusGeometry(r.radius+1.5,1.2,8,20),jacket);p.name=r.id+' strain relief collar '+end;group.add(p);ports.set(r.id+end,p);}
   if(r.carrier){const count=Math.ceil(r.designLength/9),side=new THREE.InstancedMesh(new THREE.BoxGeometry(12,7.5,2),jacket,count*2),bars=new THREE.InstancedMesh(new THREE.BoxGeometry(2,7.5,24),metal,count);side.name=r.id+' articulated side links';bars.name=r.id+' cross bars';group.add(side,bars);chains.set(r.id,{side,bars,count});}
 }
 // Fixtures below move only with their owning axis; cable load is taken by these brackets.
 // owners 有給時掛到所屬軸（與軸成為同一剛體），否則留在世界座標（驗證腳本用）
 const S0={tx:0,zt:1010,a:6,headLift:30,r2:0},parentOf=frame=>owners?.[frame]||null;
 const supports=movingSupports(S0,s).map(([id,size,at,,frame])=>box(parentOf(frame)||group,id,size,at));
 let key='';
 function update(S){
   const k=[S.tx,S.zt,S.a,S.headLift,S.r2].join(',');if(k===key)return;key=k;
   movingSupports(S,s).forEach((b,i)=>{const o=parentOf(b[4])?frameOrigin(b[4],S,s):[0,0,0];supports[i].position.set(b[2][0]-o[0],b[2][1]-o[1],b[2][2]-o[2]);});
   const routes=movingRoutes(S,s);
   for(let i=0;i<routes.length;i++){
     const r=routes[i],mesh=moving[i];mesh.geometry.dispose();mesh.geometry=new THREE.TubeGeometry(r.path,140,r.radius,8,false);mesh.userData.wiring=r;mesh.userData.route=[r.path.getPoint(0).toArray(),r.path.getPoint(1).toArray()];
     for(const end of [0,1]){const port=ports.get(r.id+end);if(!port)continue;port.position.copy(r.path.getPoint(end));port.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),r.path.getTangent(end).normalize());}
     const chain=chains.get(r.id);if(!chain)continue;
     const normal=r.id==='X-CHAIN'?new THREE.Vector3(0,0,1):new THREE.Vector3(1,0,0),obj=new THREE.Object3D();
     for(let j=0;j<chain.count;j++){const u=(j+.5)/chain.count,p=r.path.getPoint(u),t=r.path.getTangent(u).normalize(),radial=t.clone().cross(normal).normalize();obj.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(radial,t,normal));
       for(const side of [-1,1]){obj.position.copy(p).addScaledVector(normal,side*12);obj.updateMatrix();chain.side.setMatrixAt(j*2+(side>0?1:0),obj.matrix);}
       obj.position.copy(p).addScaledVector(radial,-5);obj.updateMatrix();chain.bars.setMatrixAt(j,obj.matrix);
     }chain.side.instanceMatrix.needsUpdate=true;chain.bars.instanceMatrix.needsUpdate=true;chain.side.computeBoundingSphere();chain.bars.computeBoundingSphere();
   }
 }
 return {group,moving,update};
}
