// Screen-space simulation annotations. Coordinates are projected through the rendered camera.
import * as THREE from 'three';
export const COLORS = { preview: '#61d5ff', ok: '#69efb0', ng: '#ff747e', pending: '#ffd079' };
export function projectPoint(point, camera, width, height) {
  const p = point.clone().project(camera);
  if (![p.x,p.y,p.z].every(Number.isFinite) || p.z < -1 || p.z > 1) return null;
  return { x: (p.x + 1) * width / 2, y: (1 - p.y) * height / 2 };
}
export function projectRegion(points, camera, width, height) {
  const ps = points.map(p => projectPoint(p,camera,width,height));
  if (!ps.length || ps.some(p=>!p)) return null;
  const x0=Math.min(...ps.map(p=>p.x)), x1=Math.max(...ps.map(p=>p.x));
  const y0=Math.min(...ps.map(p=>p.y)), y1=Math.max(...ps.map(p=>p.y));
  if(x1<0||y1<0||x0>width||y0>height)return null;
  return {x:Math.max(0,x0),y:Math.max(0,y0),w:Math.min(width,x1)-Math.max(0,x0),h:Math.min(height,y1)-Math.max(0,y0),clipped:x0<0||y0<0||x1>width||y1>height};
}
export function objectRegion(object) {
  const b=new THREE.Box3().setFromObject(object),out=[];
  if(b.isEmpty())return out;
  for(const x of [b.min.x,b.max.x])for(const y of [b.min.y,b.max.y])for(const z of [b.min.z,b.max.z])out.push(new THREE.Vector3(x,y,z));
  return out;
}
export function planeRegion(object,x,y,z,w,d) {
  return [[-1,-1],[1,-1],[1,1],[-1,1]].map(([a,b])=>object.localToWorld(new THREE.Vector3(x+a*w/2,y,z+b*d/2)));
}
export function createVisionOverlay() {
  const host=document.createElement('div');host.className='vision-overlay';
  host.style.cssText='position:fixed;pointer-events:none;z-index:12;overflow:hidden;';
  const canvas=document.createElement('canvas');canvas.style.cssText='position:absolute;inset:0;width:100%;height:100%';
  const badge=document.createElement('div');badge.className='vision-summary';
  badge.style.cssText='position:absolute;left:6px;top:6px;max-width:calc(100% - 87px);padding:4px 7px;background:#071720dd;color:#bceaff;font:11px/1.4 system-ui;border-left:2px solid #61d5ff;white-space:pre-line;';
  const button=document.createElement('button');button.textContent='標記 開';button.setAttribute('aria-label','顯示機器視覺檢測標記');button.setAttribute('aria-pressed','true');
  button.style.cssText='position:absolute;right:6px;top:6px;pointer-events:auto;background:#102734e8;color:#d4f3ff;border:1px solid #41616d;border-radius:4px;padding:4px 7px;font:11px system-ui;cursor:pointer';
  let enabled=true;button.onclick=()=>{enabled=!enabled;button.textContent=enabled?'標記 開':'標記 關';button.setAttribute('aria-pressed',String(enabled));};
  host.append(canvas,badge,button);document.body.append(host);const ctx=canvas.getContext('2d');
  function hide(){host.hidden=true;}
  function draw(camera,rect,{title='視覺檢測',state='預覽',time=0,marks=[]}={}) {
    host.hidden=false;Object.assign(host.style,{left:rect.left+'px',top:rect.top+'px',width:rect.width+'px',height:rect.height+'px'});
    const w=rect.width,h=rect.height,dpr=Math.min(devicePixelRatio||1,2);
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);badge.hidden=!enabled;
    if(!enabled){host.dataset.count='0';host.setAttribute('aria-label','檢測標記已關閉');return;}
    camera.updateMatrixWorld(true);
    const visible=marks.map(m=>({...m,box:projectRegion(m.points,camera,w,h)})).filter(m=>m.box).map(m=>m.box.clipped?{...m,status:'pending',label:'邊界 ROI／待完整取像'}:m);
    host.dataset.count=String(visible.length);host.dataset.state=state;
    badge.textContent=`SIM · ${title} · ${state}\n${time.toFixed(2)} s · ${visible.length} 個畫面內 ROI`;
    host.setAttribute('aria-label',`模擬檢測，非實測。${title}，${state}。`+visible.map(m=>m.label).filter(Boolean).join('；'));
    const occupied=[{x:0,y:0,w:w,h:48}];
    ctx.lineWidth=1.25;ctx.font='11px system-ui';
    for(const m of visible){
      const b=m.box,c=COLORS[m.status]||COLORS.preview;ctx.strokeStyle=c;ctx.fillStyle=c;
      ctx.setLineDash(m.status==='pending'?[3,3]:[]);
      const x=b.x-2,y=b.y-2,bw=b.w+4,bh=b.h+4,k=Math.min(9,bw/3,bh/3);
      ctx.beginPath();for(const [a,d,s,t]of[[x,y,1,1],[x+bw,y,-1,1],[x,y+bh,1,-1],[x+bw,y+bh,-1,-1]]){ctx.moveTo(a+s*k,d);ctx.lineTo(a,d);ctx.lineTo(a,d+t*k);}ctx.stroke();ctx.setLineDash([]);
      const cx=b.x+b.w/2,cy=b.y+b.h/2;ctx.beginPath();ctx.moveTo(cx-3,cy);ctx.lineTo(cx+3,cy);ctx.moveTo(cx,cy-3);ctx.lineTo(cx,cy+3);ctx.stroke();
      if(m.line){const ps=m.line.map(p=>projectPoint(p,camera,w,h));if(ps.every(Boolean)){ctx.beginPath();ctx.moveTo(ps[0].x,ps[0].y);ctx.lineTo(ps[1].x,ps[1].y);ctx.stroke();}}
      if(m.contour){const ps=m.contour.map(p=>projectPoint(p,camera,w,h));if(ps.every(Boolean)){ctx.beginPath();ps.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.stroke();}}
      if(!m.label)continue;
      const tw=Math.min(w-12,ctx.measureText(m.label).width+10),th=18;
      const candidates=[{x:b.x,y:b.y-th-4},{x:b.x+b.w+8,y:cy-th/2},{x:b.x,y:b.y+b.h+5},{x:b.x-tw-8,y:cy-th/2}];
      const r=candidates.map(r=>({x:Math.max(6,Math.min(w-tw-6,r.x)),y:r.y,w:tw,h:th})).find(r=>r.y>=49&&r.y+th<h-4&&!occupied.some(o=>r.x<o.x+o.w+3&&r.x+r.w+3>o.x&&r.y<o.y+o.h+3&&r.y+r.h+3>o.y));
      if(!r)continue;occupied.push(r);
      ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(r.x+r.w/2,r.y+r.h/2);ctx.globalAlpha=.55;ctx.stroke();ctx.globalAlpha=1;
      ctx.fillStyle='#071720e8';ctx.fillRect(r.x,r.y,r.w,r.h);ctx.fillStyle=c;ctx.fillText(m.label,r.x+5,r.y+13,r.w-10);
    }
  }
  return {draw,hide};
}
