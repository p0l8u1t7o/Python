// 實際夾具 mesh 的定向包圍盒對固定設備 + 表面取樣對桶輪廓。
// 0.05s 與交接事件取樣；不代表連續碰撞或製造公差認證。
import * as THREE from 'three';
import {writeFileSync} from 'node:fs';
import {createRobot} from '../web/js/robot.js';
import {createSequence,drumWorld,DRUM_KEYS} from '../web/js/sequence.js';
import {DRUM_GEO} from '../web/js/drum.js';
import {GRIPPER} from '../web/js/gripper.js';
import {BOOTH,UPRIGHT,DECAP,DRUM,ROBOT,FENCE,pointInPolygon} from '../web/js/layout.js';
const robot=createRobot(),seq=createSequence({robot}),grip=robot.gripper;
const V=(x=0,y=0,z=0)=>new THREE.Vector3(x,y,z),axes=[V(1),V(0,1),V(0,0,1)];
const failures=[],counts={},checks=[];
const fail=(kind,data)=>{counts[kind]=(counts[kind]||0)+1;if(failures.filter(f=>f.kind===kind).length<5)failures.push({kind,...data});};
const check=(name,ok,detail)=>{checks.push({name,ok,detail});if(!ok)fail(name,{detail});};
const b=BOOTH,[x0,x1,y0,y1]=b.opening;
const boxes=[
  ['左側板',b.x0,0,b.z0,b.x0+20,b.h,b.z1],['右側板',b.x1-20,0,b.z0,b.x1,b.h,b.z1],
  ['後板',b.x0,0,b.z1-20,b.x1,b.h,b.z1],['頂板',b.x0,b.h-20,b.z0,b.x1,b.h,b.z1],
  ['前左板',b.x0,0,b.z0,x0,b.h,b.z0+20],['前右板',x1,0,b.z0,b.x1,b.h,b.z0+20],
  ['入口上樑',x0,y1-25,b.z0-25,x1,y1+25,b.z0+25],['入口下板',x0,0,b.z0,x1,y0,b.z0+20],
  ['集液漏斗',b.funnel.x0,250,b.funnel.z0,b.funnel.x1,b.funnel.y,b.funnel.z1],
  ['左風刀',x0+10,500,b.z0-110,x0+70,2200,b.z0-30],['右風刀',x1-70,500,b.z0-110,x1-10,2200,b.z0-30],
  ['输送機',UPRIGHT.x-350,0,UPRIGHT.z0+450,UPRIGHT.x+350,UPRIGHT.top-5,UPRIGHT.z1],
  ...[[-650,-400],[650,-400],[-650,400],[650,400]].map(([x,z])=>['開蓋柱',UPRIGHT.x+x-50,0,DECAP.z+z-50,UPRIGHT.x+x+50,2600,DECAP.z+z+50]),
  ...[x0,x1].map(x=>['入口框',x-30,0,b.z0-30,x+30,b.h,b.z0+30]),
].map(([name,...a])=>({name,box:new THREE.Box3(V(...a.slice(0,3)),V(...a.slice(3)))}));
// 定向包圍盒 SAT；圓弧與圓柱使用保守包圍盒，不用世界 AABB 誤判轉向。
function intersects(mesh,box){
  const local=mesh.geometry.boundingBox,center=local.getCenter(V()).applyMatrix4(mesh.matrixWorld),half=local.getSize(V()).multiplyScalar(.5);
  const a=axes.map((_,i)=>V().setFromMatrixColumn(mesh.matrixWorld,i));
  const lengths=a.map(p=>p.length());a.forEach(p=>p.normalize());
  const h=[half.x*lengths[0],half.y*lengths[1],half.z*lengths[2]], bh=box.getSize(V()).multiplyScalar(.5),delta=box.getCenter(V()).sub(center);
  for(const n of [...axes,...a,...a.flatMap(p=>axes.map(q=>V().crossVectors(p,q)))]){
    if(n.lengthSq()<1e-12)continue;
    const radius=h.reduce((r,v,i)=>r+v*Math.abs(n.dot(a[i])),0)+Math.abs(n.x)*bh.x+Math.abs(n.y)*bh.y+Math.abs(n.z)*bh.z;
    if(Math.abs(delta.dot(n))>=radius-.05)return false;
  }return true;
}
function surface(mesh){
  const g=mesh.geometry,p=g.attributes.position,idx=g.index,pts=new Map();
  const add=q=>pts.set(q.toArray().map(v=>v.toFixed(2)).join(','),q);
  const n=idx?idx.count:p.count;
  for(let i=0;i<n;i+=3){const a=[0,1,2].map(j=>V().fromBufferAttribute(p,idx?idx.getX(i+j):i+j));
    for(let j=0;j<3;j++){const t=a[j],u=a[(j+1)%3],steps=Math.ceil(t.distanceTo(u)/20);for(let k=0;k<=steps;k++)add(t.clone().lerp(u,k/Math.max(1,steps)));}
    add(a[0].clone().add(a[1]).add(a[2]).multiplyScalar(1/3));
  }return [...pts.values()];
}
const meshes=[...grip.solids,...grip.pads].map((mesh,i)=>{mesh.geometry.computeBoundingBox();return {mesh,i,points:surface(mesh)};});
const profile=DRUM_GEO.parameters.points;
function radius(y){let r=0;for(let i=1;i<profile.length;i++){const a=profile[i-1],b=profile[i];if(y<Math.min(a.y,b.y)||y>Math.max(a.y,b.y))continue;const t=a.y===b.y?0:(y-a.y)/(b.y-a.y);r=Math.max(r,a.x+(b.x-a.x)*t);}return r;}
// 掃過完整開合行程：PU 可以接觸桶身，金屬不得穿入桶身或 L 環。
let minMetalGap=Infinity,padContact=Infinity,guideHits=0,driveHits=0,rodEndError=0;
for(let jaw=0;jaw<=100;jaw++){
  grip.set(jaw/100);robot.root.updateMatrixWorld(true);const inv=robot.tool.matrixWorld.clone().invert();
  for(const rail of grip.rails){
    const inverse=rail.matrixWorld.clone().invert();
    for(const carriage of grip.carriages)for(const mesh of carriage.children)if(intersects({geometry:mesh.geometry,matrixWorld:inverse.clone().multiply(mesh.matrixWorld)},rail.geometry.boundingBox))guideHits++;
    for(const mesh of grip.crossbars)if(intersects({geometry:mesh.geometry,matrixWorld:inverse.clone().multiply(mesh.matrixWorld)},rail.geometry.boundingBox))driveHits++;
  }
  grip.rods.forEach(({piston},i)=>{const end=grip.crossbars[i].getWorldPosition(V());rodEndError=Math.max(rodEndError,Math.min(...[-.5,.5].map(y=>V(0,y,0).applyMatrix4(piston.matrixWorld).distanceTo(end))));});
  for(const {mesh,points}of meshes){const mat=inv.clone().multiply(mesh.matrixWorld),isPad=grip.pads.includes(mesh);
    for(const p of points){const q=p.clone().applyMatrix4(mat),r=radius(q.y);if(!r)continue;const gap=Math.hypot(q.x,q.z-ROBOT.grip)-r;
      if(isPad&&jaw===100)padContact=Math.min(padContact,gap);else if(!isPad)minMetalGap=Math.min(minMetalGap,gap);
    }
  }
}
check('全開合金屬避開桶身與頂部 L 環',minMetalGap>=-.1,{mm:minMetalGap});
check('閉合 PU 墊貼合桶身',Math.abs(padContact)<.1,{mm:padContact});
check('全開合滑座通槽不穿入導軌及支承梁',guideHits===0,{collisions:guideHits,positions:101});
check('驅動橫桿全行程避開導軌',driveHits===0,{collisions:driveHits});
check('活塞桿全行程接到滑座橫桿',rodEndError<.01,{mm:rodEndError});
const backInverse=grip.backplate.matrixWorld.clone().invert();
check('氣缸本體不埋入背板',grip.cylinders.every(mesh=>!intersects({geometry:mesh.geometry,matrixWorld:backInverse.clone().multiply(mesh.matrixWorld)},grip.backplate.geometry.boundingBox)));
const boreHits=grip.glands.map(({cap,s})=>{const origin=V(s*210,0,GRIPPER.driveZ).applyMatrix4(robot.tool.matrixWorld),direction=V(s,0,0).transformDirection(robot.tool.matrixWorld);return new THREE.Raycaster(origin,direction,0,30).intersectObject(cap).length;});
check('兩側氣缸前蓋具有實際貫穿孔',boreHits.every(n=>n===0),{hits:boreHits});
check('滑座全開仍在止擋內',GRIPPER.jawX+GRIPPER.stroke+25<GRIPPER.railHalf-22,{gap:GRIPPER.railHalf-22-GRIPPER.jawX-GRIPPER.stroke-25});
check('空夾具全開可側向進退',GRIPPER.padRadius+GRIPPER.stroke>DRUM.envelopeR+20,{sideGap:GRIPPER.padRadius+GRIPPER.stroke-DRUM.envelopeR});
let samples=0,minFenceGap=Infinity;
const times=[...new Set([...Array.from({length:Math.floor(seq.total/.05)+1},(_,i)=>i*.05),...seq.events.flatMap(e=>[e.time,Math.min(seq.total,e.time+.001)])])].sort((a,b)=>a-b);
for(const t of times){
  const sm=seq.sample(t),st=sm.st;grip.set(st.grip.jaw);robot.root.updateMatrixWorld(true);samples++;
  const allBox=new THREE.Box3().setFromObject(grip.root),near=boxes.filter(o=>allBox.intersectsBox(o.box));
  const drums=DRUM_KEYS.map(k=>({k,...drumWorld(k,st,robot.tcp.matrixWorld)})).filter(w=>!w.hidden&&allBox.distanceToPoint(w.pos)<600);
  for(const {mesh,i,points}of meshes){
    const wb=mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld);
    for(const obstacle of near)if(wb.intersectsBox(obstacle.box)&&intersects(mesh,obstacle.box))fail('設備干涉',{t,mesh:i,obstacle:obstacle.name,action:sm.robot.step?.action});
    for(const w of drums){
      if(wb.distanceToPoint(w.pos)>Math.hypot(DRUM.H/2,DRUM.envelopeR))continue;
      const inv=new THREE.Matrix4().compose(w.pos,w.q,V(1,1,1)).invert().multiply(mesh.matrixWorld);
      const hit=points.find(p=>{const q=p.clone().applyMatrix4(inv);return Math.abs(q.y)<467.45&&Math.hypot(q.x,q.z)<radius(q.y)-.15;});
      if(hit)fail('夾具穿桶',{t,mesh:i,drum:w.k,mode:st[w.k].mode,action:sm.robot.step?.action});
    }
  }
  // 外形八角點與各零件頂點須留在圍籬內，避免空夾具退出時越界。
  for(const {mesh,i}of meshes){const a=mesh.geometry.boundingBox;for(const x of [a.min.x,a.max.x])for(const y of [a.min.y,a.max.y])for(const z of [a.min.z,a.max.z]){const p=V(x,y,z).applyMatrix4(mesh.matrixWorld);if(!pointInPolygon([p.x,p.z],FENCE))fail('夾具越界',{t,mesh:i,point:p.toArray()});
    for(let j=1;j<FENCE.length;j++){const [ax,az]=FENCE[j-1],[bx,bz]=FENCE[j],dx=bx-ax,dz=bz-az,u=Math.max(0,Math.min(1,((p.x-ax)*dx+(p.z-az)*dz)/(dx*dx+dz*dz)));minFenceGap=Math.min(minFenceGap,Math.hypot(p.x-ax-u*dx,p.z-az-u*dz)-20);}
  }}
}
check('夾具與 40mm 圍籬框保持間隙',minFenceGap>=0,{mm:minFenceGap});
const report={ok:failures.length===0,samples,dt:.05,checks,counts,failures,scope:'夾具各零件定向包圍盒對設備、20mm 邊線取樣對桶輪廓；0.05s 與事件取樣。接觸墊允許 0.15mm 曲面離散誤差；非連續碰撞或製造驗證。'};
writeFileSync(new URL('../review/gripper-verification.json',import.meta.url),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));process.exitCode=report.ok?0:1;
