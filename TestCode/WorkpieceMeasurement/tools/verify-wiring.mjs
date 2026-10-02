import fs from 'node:fs';
import {STATIC_ROUTES,FIXED_SUPPORTS,movingRoutes,movingSupports} from '../web/js/wiring-plan.js';
import {SPECS,SCENARIOS,fixedBodies,transferBodies,trayBodies,partPose} from '../web/js/spec.js';
import {createSequence} from '../web/js/sequence.js';
import {distPoint} from '../web/js/collision.js';
const problems=new Map(),lengths=new Map();let states=0,minClearance=Infinity;
const issue=(id,data)=>{if(!problems.has(id))problems.set(id,data);};
const bounds=b=>b.kind==='box'?{min:b.min,max:b.max}:{min:b.p0.map((v,i)=>Math.min(v,b.p1[i])-b.r),max:b.p0.map((v,i)=>Math.max(v,b.p1[i])+b.r)};
function distance(p,b){
 let d=distPoint(p,b);
 if(b.bore){const cx=b.kind==='box'?b.bore[0]:b.p0[0],cz=b.kind==='box'?b.bore[1]:b.p0[2],r=b.kind==='box'?b.bore[2]:b.bore;d=Math.max(d,r-Math.hypot(p[0]-cx,p[2]-cz));}
 return d;
}
function inspect(r,bodies,tag){
 const radius=r.carrier?14.4:r.radius+(r.guide?1.5:0),path=r.path,n=Math.ceil(path.getLength()/3),points=Array.from({length:n+1},(_,i)=>path.getPoint(i/n).toArray());
 const bb={min:[0,1,2].map(i=>Math.min(...points.map(p=>p[i]))-radius),max:[0,1,2].map(i=>Math.max(...points.map(p=>p[i]))+radius)};
 const near=bodies.filter(b=>{const bnd=bounds(b);return [0,1,2].every(i=>bb.max[i]>=bnd.min[i]&&bb.min[i]<=bnd.max[i]);});
 for(const b of near)for(let j=0;j<points.length;j++){
  const p=points[j];
  // Local, intentional connector penetration only; no whole-body exclusion.
  if((r.attachments||[]).includes(b.id)&&[points[0],points.at(-1)].some(e=>Math.hypot(...p.map((v,i)=>v-e[i]))<20))continue;
  let gap=distance(p,b)-radius;
  if(r.carrier){const normal=r.id==='X-CHAIN'?2:0,bd=bounds(b),d=p.map((v,i)=>Math.max(bd.min[i]-v,0,v-bd.max[i]));gap=Math.max(d[normal]-13,Math.hypot(...d.filter((_,i)=>i!==normal))-6);}
  minClearance=Math.min(minClearance,gap);
  if(gap<-.05){issue(r.id+'/'+b.id,{tag,route:r.id,body:b.id,point:p.map(v=>+v.toFixed(2)),gap:+gap.toFixed(2)});break;}
 }
 const length=path.getLength(),key=tag.split('/')[0]+'/'+r.id;
 const rec=lengths.get(key)||{min:Infinity,max:0};rec.min=Math.min(rec.min,length);rec.max=Math.max(rec.max,length);lengths.set(key,rec);
 if(r.designLength&&Math.abs(length-r.designLength)>.01)issue('length/'+key,{length,expected:r.designLength});
 return {...r,points,bb,collisionRadius:radius};
}
// Exact segment distance after broad phase. Endpoint connections have a local allowance.
const sub=(a,b)=>a.map((v,i)=>v-b[i]),dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0),clamp=x=>Math.max(0,Math.min(1,x));
function segDist(p1,q1,p2,q2){const d1=sub(q1,p1),d2=sub(q2,p2),r=sub(p1,p2),a=dot(d1,d1),e=dot(d2,d2),f=dot(d2,r);let s=0,t=0;
 if(a<1e-12)t=clamp(f/e);else{const c=dot(d1,r);if(e<1e-12)s=clamp(-c/a);else{const b=dot(d1,d2),den=a*e-b*b;s=den?clamp((b*f-c*e)/den):0;t=(b*s+f)/e;if(t<0){t=0;s=clamp(-c/a);}else if(t>1){t=1;s=clamp((b-c)/a);}}}return {distance:Math.hypot(...r.map((v,i)=>v+d1[i]*s-d2[i]*t)),a:p1.map((v,i)=>v+d1[i]*s),b:p2.map((v,i)=>v+d2[i]*t)};}
function wirePairs(routes,tag){
 for(let a=0;a<routes.length;a++)for(let b=a+1;b<routes.length;b++){
  const x=routes[a],y=routes[b],id='wires/'+x.id+'/'+y.id;if(problems.has(id))continue;
  if(![0,1,2].every(k=>x.bb.max[k]>=y.bb.min[k]&&x.bb.min[k]<=y.bb.max[k]))continue;
  const shared=[];for(const p of [x.points[0],x.points.at(-1)])for(const q of[y.points[0],y.points.at(-1)])if(Math.hypot(...sub(p,q))<.1)shared.push(p);
  const rad=x.collisionRadius+y.collisionRadius;
  outer:for(let i=1;i<x.points.length;i++)for(let j=1;j<y.points.length;j++){
   const p=x.points[i-1],q=x.points[i],r=y.points[j-1],s=y.points[j];
   if(shared.some(e=>Math.hypot(...sub(p,e))<22&&Math.hypot(...sub(r,e))<22))continue;
   if(![0,1,2].every(k=>Math.max(p[k],q[k])+rad>=Math.min(r[k],s[k])&&Math.min(p[k],q[k])-rad<=Math.max(r[k],s[k])))continue;
   const result=segDist(p,q,r,s),junction=x.carrier||y.carrier?36:22;if(shared.some(e=>Math.hypot(...sub(result.a,e))<junction&&Math.hypot(...sub(result.b,e))<junction))continue;
   const gap=result.distance-rad;if(gap<-.1){issue(id,{tag,routes:[x.id,y.id],gap,at:result.a});break outer;}
  }
 }
}
const supportBodies=FIXED_SUPPORTS.map(([id,size,at])=>({id,kind:'box',min:at.map((v,i)=>v-size[i]/2),max:at.map((v,i)=>v+size[i]/2)}));
for(const r of STATIC_ROUTES)inspect(r,supportBodies,'fixed/supports');
for(const s of Object.values(SPECS)){
 const originals=fixedBodies(s);
 // enclosure and desk exclusion surfaces, in the same mm frame as machine.js
 const guard=(id,min,max)=>({id,kind:'box',min,max});
 const enclosure=[guard('rear guard',[-335,858,-247],[335,1328,-243]),guard('left guard',[-347,858,-235],[-343,1328,235]),guard('right guard',[343,858,-235],[347,1328,235]),guard('roof',[-335,1326,-235],[335,1330,235])];
 for(const x of [-345,345])for(const z of [-245,245])enclosure.push(guard('post'+x+','+z,[x-10,858,z-10],[x+10,1328,z+10]));
 for(const scenario of Object.keys(SCENARIOS)){
  const seq=createSequence({spec:s.id,scenario}),times=new Set([0,seq.total,...seq.steps.flatMap(p=>[p.start,p.start+p.dur/2,p.start+p.dur])]);for(let t=0;t<seq.total;t+=.04)times.add(t);
  for(const t of times){states++;const st=seq.sample(t).state,tag=s.id+'/'+scenario+'@'+t.toFixed(3);
   const fixed=originals.map(b=>{const shift=p=>p.map((v,i)=>v+(i===0&&b.cframe?st.r2:0)+(i===1&&b.id==='sensorUp'?st.headLift:0));return b.kind==='box'?{...b,min:shift(b.min),max:shift(b.max)}:{...b,p0:shift(b.p0),p1:shift(b.p1)};});
   const p=partPose(st,s),dynamic=[...transferBodies(st,s),...trayBodies(st,s),{id:'active cup',kind:'cyl',p0:[p.x,p.y,p.z],p1:[p.x,p.y+s.len,p.z],r:s.od/2}];
   const checked=movingRoutes(st,s).map(r=>inspect(r,[...fixed,...dynamic,...enclosure],tag));
   wirePairs(checked,tag);
   for(const r of STATIC_ROUTES)inspect(r,[...dynamic,...(scenario==='OK'&&t===0?[...fixed,...enclosure]:[])],tag);
   for(const b of supportBodies)for(const m of dynamic){const a=bounds(m);if([0,1,2].every(i=>b.max[i]>a.min[i]+.05&&b.min[i]<a.max[i]-.05))issue('support/'+b.id+'/'+m.id,{tag,support:b.id,body:m.id});}
   for(const [id,size,at,owners]of movingSupports(st,s))for(const m of [...fixed,...dynamic,...enclosure]){
     if(owners.includes(m.id))continue;const a=bounds(m),lo=at.map((v,i)=>v-size[i]/2),hi=at.map((v,i)=>v+size[i]/2);
     if([0,1,2].every(i=>hi[i]>a.min[i]+.1&&lo[i]<a.max[i]-.1))issue('moving support/'+id+'/'+m.id,{tag,support:id,body:m.id});
   }
   // 掛在不同軸上的移動支架不得互相穿過（例如 Z 鏈座隨 Z 上下時不可穿過 X 鏈固定座）
   const ms=movingSupports(st,s);
   for(let i=0;i<ms.length;i++)for(let j=i+1;j<ms.length;j++){const [ia,sa,pa,,fa]=ms[i],[ib,sb,pb,,fb]=ms[j];if(fa!==fb&&[0,1,2].every(k=>Math.abs(pa[k]-pb[k])<(sa[k]+sb[k])/2-.1))issue('moving support pair/'+ia+'/'+ib,{tag,supports:[ia,ib]});}
  }
 }
}
for(const [id,l]of lengths)if(l.max-l.min>.05)issue('stretch/'+id,{id,...l,change:l.max-l.min});
const report={generated:new Date().toISOString(),states,pass:!problems.size,minClearance,problems:[...problems.values()],lengths:Object.fromEntries(lengths),scope:'3 mm arc-length sampling with jacket radius / 26x12 carrier section; every 40 ms plus step endpoints/midpoints, all 15 scenarios. Fixed guides vs supports and moving mechanisms; loops vs core bodies, trays, cups and enclosure; moving support vs core bodies. Moving wire-pair segment distances. Connector/body allowance within 20 mm; joined cable/carrier endpoints within 22/36 mm. OEM fatigue, bend approval, full intra-cabinet wiring and assembly tolerance not certified.'};
fs.writeFileSync(new URL('../review/wiring-verification.json',import.meta.url),JSON.stringify(report,null,2));console.log(JSON.stringify({states,pass:report.pass,problems:report.problems},null,2));if(!report.pass)process.exitCode=1;
