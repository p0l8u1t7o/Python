// 局部機構回歸檢查：使用畫面同一份 Three.js 幾何，不只比較設備外框。
import * as THREE from 'three';
import { writeFileSync } from 'node:fs';
import { createLine } from '../web/js/line.js';
import { createWashing } from '../web/js/washing.js';
import { createBuilding } from '../web/js/building.js';
import { createDrum, DRUM_GEO } from '../web/js/drum.js';
import { createRobot } from '../web/js/robot.js';
import { createSequence, drumWorld, DRUM_KEYS } from '../web/js/sequence.js';
import { DRUM, LYING, UPRIGHT, BOOTH, WASTE, WEIGH, DECAP, INBOUND } from '../web/js/layout.js';
import { MAT } from '@core/geom/parts.js';

const scene = new THREE.Scene(), line = createLine(scene), wash = createWashing(scene), building = createBuilding(scene);
const robot = createRobot(), seq = createSequence({robot}), m = line.mechanical;
const checks = [], bad = [], check = (name, ok, detail) => { checks.push({name, ok, detail}); if (!ok) bad.push({name, detail}); };
const v = (x,y,z) => new THREE.Vector3(x,y,z);
const box = mesh => new THREE.Box3().setFromObject(mesh);
const vertices = mesh => { const a = mesh.geometry.attributes.position; return Array.from({length:a.count},(_,i)=>v(a.getX(i),a.getY(i),a.getZ(i)).applyMatrix4(mesh.matrixWorld)); };
scene.updateMatrixWorld(true);

const rmax = Math.max(...Array.from({length:DRUM_GEO.attributes.position.count}, (_, i) => Math.hypot(DRUM_GEO.attributes.position.getX(i), DRUM_GEO.attributes.position.getZ(i))));
check('桶滾箍納入碰撞半徑', Math.abs(rmax - DRUM.envelopeR) < .01, {geometryRadius:rmax, envelope:DRUM.envelopeR});
const rollGaps = m.rotRollers.map(r => Math.hypot(r.position.y - LYING.y, r.position.z - LYING.z) - r.geometry.parameters.radiusTop - rmax);
check('貼標旋轉輥支撐桶外環', rollGaps.every(g=>Math.abs(g)<.02), rollGaps);
const tableGap = Math.min(...m.uprightRollers.map(r=>Math.abs(r.position.z-DECAP.z)-r.geometry.parameters.radiusTop-330));
check('開蓋轉台與固定滾輪分離', tableGap>=0, {mm:tableGap});
check('轉台承載面與輸送面等高',m.tableRollers.every(r=>Math.abs(r.position.y+r.geometry.parameters.radius-UPRIGHT.top)<.01), {top:UPRIGHT.top});

let scaleGap = Infinity;
for (let i=0; i<=54; i++) {
  line.setScale({on:true,lift:i/54}); scene.updateMatrixWorld(true);
  for (const tooth of m.weigher.children.filter(c=>c.geometry?.type==='BoxGeometry')) {
    const b = box(tooth);
    for (const r of m.uprightRollers) {
      if (b.max.x < UPRIGHT.x-350 || b.min.x > UPRIGHT.x+350) continue;
      const dy=Math.max(b.min.y-r.position.y,0,r.position.y-b.max.y), dz=Math.max(b.min.z-r.position.z,0,r.position.z-b.max.z);
      scaleGap=Math.min(scaleGap,Math.hypot(dy,dz)-30);
    }
  }
}
check('頂升秤台全 27mm 行程避開滾輪',scaleGap>=-.01,{mm:scaleGap});
const padTop=Math.max(...m.weigher.children.filter(c=>c.material===MAT.pu).map(c=>box(c).max.y));
check('秤重托桶離開輸送面 12mm',Math.abs(padTop-UPRIGHT.top-WEIGH.lift)<.01,{mm:padTop-UPRIGHT.top});

line.setUpender({tilt:0,clamp:1}); scene.updateMatrixWorld(true);
const cradleCenter=v(-DRUM.H/2, DRUM.R, 0);
const supportGaps=m.cradle.children.filter(c=>c.material===MAT.pu).flatMap(c=>{
  c.updateMatrix(); const p=c.geometry.attributes.position; return Array.from({length:p.count},(_,i)=>v(p.getX(i),p.getY(i),p.getZ(i)).applyMatrix4(c.matrix)).map(p=>Math.hypot(p.y-cradleCenter.y,p.z)-rmax);
});
check('翻桶托墊不穿入桶外環',Math.min(...supportGaps)>=-.01,{mm:Math.min(...supportGaps)});
let shortest=Infinity,longest=0;
for(let i=0;i<=180;i++){line.setUpender({tilt:i/180,clamp:1}); shortest=Math.min(shortest,m.piston.scale.y);longest=Math.max(longest,m.piston.scale.y);}
check('翻桶缸全行程長度有效',shortest>0 && longest<700,{rodMin:shortest,rodMax:longest});

const [x0,z0,x1,z1]=WASTE.bund, bw=WASTE.wall;
const tankWallGaps=Object.fromEntries(Object.entries(WASTE.tanks).map(([k,t])=>[k,Math.min(t.x-t.r-x0-bw,x1-bw-t.x-t.r,t.z-t.r-z0-bw,z1-bw-t.z-t.r)]));
check('四槽不嵌入防溢堤',Object.values(tankWallGaps).every(g=>g>=0),tankWallGaps);
const tt=Object.entries(WASTE.tanks), tankGaps=[];
for(let i=0;i<tt.length;i++)for(let j=i+1;j<tt.length;j++){const [ak,a]=tt[i],[bk,b]=tt[j];tankGaps.push({pair:ak+'/'+bk,mm:Math.hypot(a.x-b.x,a.z-b.z)-a.r-b.r});}
check('酸鹼與回收清水槽互不相交',tankGaps.every(g=>g.mm>=0),tankGaps);
const pipeWallHits=[], fenceGaps=[], bundGaps=[];
for(const [name,p]of Object.entries(wash.pipes))for(let i=1;i<p.points.length;i++){
  const a=v(...p.points[i-1]),b=v(...p.points[i]),d=b.clone().sub(a),length=d.length();
  const ray=new THREE.Raycaster(a,d.clone().normalize(),.01,length-.01);
  if(ray.intersectObjects(wash.walls.children,true).length)pipeWallHits.push({name,segment:i});
  if((a.x-7000)*(b.x-7000)<0){const t=(7000-a.x)/d.x,y=a.y+d.y*t,z=a.z+d.z*t;if(z>11300&&z<15520)fenceGaps.push({name,mm:y-p.radius*1.15-2000});}
  if((a.z-(z1-bw/2))*(b.z-(z1-bw/2))<0){const t=(z1-bw/2-a.z)/d.z,y=a.y+d.y*t,x=a.x+d.x*t;if(x>x0&&x<x1)bundGaps.push({name,mm:y-p.radius*1.15-300});}
}
check('排液管穿過實際 PP 板預留孔',pipeWallHits.length===0,pipeWallHits);
check('剛性跨區配管高過圍籬',fenceGaps.length>0&&fenceGaps.every(g=>g.mm>=0),fenceGaps);
check('酸鹼清運管高過防溢堤',bundGaps.length>=2&&bundGaps.every(g=>g.mm>=0),bundGaps);
const nozzles=[['big',wash.lance,DRUM.big.hole],['small',wash.lance2,DRUM.small.hole]];
check('噴頭外徑小於桶口',nozzles.every(([,g,r])=>g.children.filter(c=>c.geometry?.type==='CylinderGeometry' && !c.material.transparent).every(c=>c.geometry.parameters.radiusTop<r)),nozzles.map(([k,g,r])=>({kind:k,holeRadius:r,headRadius:Math.max(...g.children.filter(c=>c.geometry?.type==='CylinderGeometry' && !c.material.transparent).map(c=>c.geometry.parameters.radiusTop))})));

// 噴槍伸入時，取樣軸線轉回實際桶座標，檢查孔位與桶底/桶壁。
let lanceGap=Infinity, bungGap=Infinity, active=0;
const transitionTimes=Object.values(seq.tracks).flatMap(t=>t.steps.flatMap(s=>[s.start-1e-5,s.start,s.start+s.dur-1e-5,s.start+s.dur])).filter(t=>t>=0&&t<=seq.total);
const times=[...new Set([...Array.from({length:Math.floor(seq.total/.05)+1},(_,i)=>i*.05),...transitionTimes])].sort((a,b)=>a-b);
let interlockErrors=0, liquidErrors=0, finiteErrors=0;
for(const t of times){
  const sm=seq.sample(t),st=sm.st;
  if(st.booth.spray && (st.booth.lance<.999 || st.booth.lance2<.999)) interlockErrors++;
  for(const [k,tank]of Object.entries(WASTE.tanks))if(st.tanks[k]<0||st.tanks[k]>tank.cap)liquidErrors++;
  for(const key of DRUM_KEYS){const d=st[key];if(d.mode!=='robot')continue;
    const w=drumWorld(key,st,robot.tcp.matrixWorld), inv=w.q.clone().invert();
    for(const [kind,ext,xy,radius] of [['big',st.booth.lance,BOOTH.lance,24],['small',st.booth.lance2,BOOTH.lance2,10]]){
      const tipY=BOOTH.lanceUp+(BOOTH.lanceDown-BOOTH.lanceUp)*ext;
      if(ext<=0)continue;
      const tip=v(xy[0],tipY,xy[1]).sub(w.pos).applyQuaternion(inv);
      if(tip.y>DRUM.H/2)continue; active++;
      for(let y=tipY;y<w.pos.y+600;y+=10){const p=v(xy[0],y,xy[1]).sub(w.pos).applyQuaternion(inv);if(p.y>455)break;
        lanceGap=Math.min(lanceGap,284-Math.hypot(p.x,p.z)-radius,p.y+455-10);
      }
      const dir=v(0,1,0).applyQuaternion(inv), p=tip.clone().addScaledVector(dir,(463-tip.y)/dir.y);
      bungGap=Math.min(bungGap,(kind==='big'?DRUM.big.hole:DRUM.small.hole)-Math.hypot(p.x-(kind==='big'?200:-200),p.z)-radius/Math.abs(dir.y));
    }
  }
  if(JSON.stringify(st).includes(':null'))finiteErrors++;
}
check('噴槍伸入桶口對位間隙',bungGap>=-.1,{mm:bungGap,activeSamples:active});
check('抽液管與桶內壁桶底間隙',lanceGap>=0,{mm:lanceGap});
check('噴洗必須等待雙槍到位',interlockErrors===0,{violations:interlockErrors});
check('全流程液位不溢流且狀態有限',liquidErrors===0&&finiteErrors===0,{liquidErrors,finiteErrors});

// 入库門空間穿越射線：以實際建築 mesh 驗證牆與踢腳已開洞。
scene.updateMatrixWorld(true);
const ray=new THREE.Raycaster(v(-450,100,2700),v(1,0,0),0,850);
const hits=ray.intersectObjects(building.group.children,true).filter(h=>h.object.isMesh);
check('捲門台車通過面無建築牆阻擋',hits.length===0,{hits:hits.length});

const report={ok:bad.length===0,samples:times.length,dt:.05,checks,failures:bad,scope:'實際局部幾何與全流程雙槍/液位聯鎖；桶內以圓柱近似；不等於製造 CAD、連續碰撞或現場安全認證。'};
writeFileSync(new URL('../review/detail-verification.json',import.meta.url),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));process.exitCode=report.ok?0:1;
