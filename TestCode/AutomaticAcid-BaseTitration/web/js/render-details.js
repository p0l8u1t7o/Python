// Offline render details. Dimensions are in mm; appearance is illustrative, not a calibrated instrument.
import * as THREE from 'three';
export const glass = new THREE.MeshPhysicalMaterial({ color: 0xe0f0ef, roughness: .08, metalness: .02, clearcoat: 1, clearcoatRoughness: .08, ior: 1.47, transparent: true, opacity: .14, depthWrite: false });
export const glassRim = new THREE.MeshPhysicalMaterial({ color: 0xd5e9e8, roughness: .12, clearcoat: 1, transparent: true, opacity: .55, depthWrite: false });
export const liquidMaterial = new THREE.MeshPhysicalMaterial({ color: 0xc7dfda, roughness: .13, clearcoat: 1, clearcoatRoughness: .06, transparent: true, opacity: .55, depthWrite: false, side: THREE.DoubleSide });
export function lathe(parent, points, material = glass) {
  const m = new THREE.Mesh(new THREE.LatheGeometry(points.map(p => new THREE.Vector2(...p)), 64), material);
  m.renderOrder = material.transparent ? 3 : 0; parent.add(m); return m;
}
export function rim(parent, r, y, material = glassRim, tube = .65) {
  const m = new THREE.Mesh(new THREE.TorusGeometry(r, tube, 8, 64), material);
  m.rotation.x = Math.PI / 2; m.position.y = y; m.renderOrder = 4; parent.add(m); return m;
}
export function glassVessel(parent, r, h, bottom = 3, spout = false) {
  const g = new THREE.Group(); parent.add(g);
  lathe(g, [[0,0],[r-1,0],[r,1],[r,h-1],[r-.5,h],[r-1.6,h],[r-1.8,h-1],[r-1.8,bottom],[0,bottom]]);
  rim(g, r-.8, h-.5); rim(g, r-.8, 1.4, glassRim, .5);
  if(spout){
    // A formed pouring lip: the glass and rolled rim flare together near +Z.
    g.updateMatrixWorld(true);
    for(const mesh of g.children){
      const p=mesh.geometry.attributes.position,local=new THREE.Vector3();
      for(let i=0;i<p.count;i++){
        local.fromBufferAttribute(p,i).applyMatrix4(mesh.matrix);
        const a=Math.atan2(local.x,local.z),weight=Math.exp(-Math.pow(a/.20,2))*Math.pow(Math.max(0,(local.y-h+14)/14),2);
        local.z+=4*weight;local.y-=1.1*weight;local.applyMatrix4(mesh.matrix.clone().invert());p.setXYZ(i,local.x,local.y,local.z);
      }p.needsUpdate=true;mesh.geometry.computeVertexNormals();mesh.geometry.computeBoundingSphere();
    }
  }
  return g;
}
export function glassBottle(parent, b) {
  const r = b.d/2, n = b.neck/2-1, h = b.h, top = h+b.neckH-2;
  lathe(parent, [[0,0],[r-2,0],[r,3],[r,h-34],[r-2,h-28],[n+5,h-7],[n,h],[n,top],[n-1.8,top],[n-1.8,h],[r-2,h-34],[r-2,4],[0,4]]);
  rim(parent,n-.7,top);
  const pts = Array.from({length:129}, (_,i) => { const a=i/128*Math.PI*6;return new THREE.Vector3(Math.sin(a)*(n+.35),h+3+i/128*12,Math.cos(a)*(n+.35)); });
  const thread = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts),128,.6,6,false),glassRim);
  thread.renderOrder=4; parent.add(thread);
}
const markCache = new Map();
export function graduations(parent, radius, height, bottom, innerRadius, step, max) {
  const key = `${radius}:${height}:${step}:${max}`;
  let tex = markCache.get(key);
  if (!tex) {
    const c=document.createElement('canvas');c.width=256;c.height=1024;const ctx=c.getContext('2d');
    ctx.fillStyle='#455c66';ctx.font='30px Arial';ctx.textAlign='left';
    for(let v=step;v<=max;v+=step){const y=1024*(1-(bottom+v*1000/(Math.PI*innerRadius**2))/height);if(y<35)continue;
      ctx.fillRect(14,y,v%(step*2)===0?95:62,3); if(v%(step*2)===0)ctx.fillText(String(v),120,y+11);}
    ctx.font='24px Arial';ctx.fillText('mL',125,36);
    tex=new THREE.CanvasTexture(c);tex.colorSpace=THREE.SRGBColorSpace;tex.anisotropy=4;markCache.set(key,tex);
  }
  const geo=new THREE.CylinderGeometry(radius+.2,radius+.2,height,32,1,true,.35,.72);
  const m=new THREE.Mesh(geo,new THREE.MeshBasicMaterial({map:tex,transparent:true,depthWrite:false,side:THREE.DoubleSide}));
  m.position.y=height/2;m.renderOrder=5;parent.add(m);return m;
}
export function createLiquid(parent,r,bottom) {
  const body=new THREE.Mesh(new THREE.CylinderGeometry(r,r,1,64,1,true),liquidMaterial);body.renderOrder=1;parent.add(body);
  const surface=lathe(parent,[[0,0],[r*.65,0],[r*.92,.08],[r-.3,.32],[r,.65]],liquidMaterial);surface.renderOrder=2;
  const ripple=new THREE.Group();parent.add(ripple);
  const rippleMat=new THREE.MeshBasicMaterial({color:0xe5f4ee,transparent:true,opacity:.28,depthWrite:false,side:THREE.DoubleSide});
  for(const f of [.42,.76]){const m=new THREE.Mesh(new THREE.RingGeometry(r*f,r*f+.25,64),rippleMat);m.rotation.x=-Math.PI/2;ripple.add(m);}
  body.userData.fx=surface.userData.fx=ripple.userData.fx=true; // 液體：效果，不做干涉檢查
  const base=surface.geometry.attributes.position.array.slice();
  let lastKey='';
  function set(volume,time=0,stir=false){
    const key=`${volume}:${stir?time:'still'}`;if(key===lastKey)return;lastKey=key;
    const h=Math.max(0,volume)*1000/(Math.PI*r*r),visible=volume>.05;
    body.visible=surface.visible=visible;ripple.visible=visible&&stir;
    body.scale.y=Math.max(.001,h);body.position.y=bottom+h/2;surface.position.y=bottom+h;
    const p=surface.geometry.attributes.position;
    for(let i=0;i<p.count;i++){const x=base[i*3],y=base[i*3+1],z=base[i*3+2],rr=Math.hypot(x,z)/r;
      p.setY(i,y+(stir?-.65*(1-rr*rr)+.14*Math.sin(Math.atan2(z,x)*3+time*5)*rr:0));}
    p.needsUpdate=true;surface.geometry.computeVertexNormals();
    ripple.position.y=bottom+h+.1;ripple.rotation.y=time*.8;
    ripple.children.forEach((m,i)=>m.scale.setScalar(1+.025*Math.sin(time*4+i*2)));
  }
  return {body,surface,ripple,set};
}
export function tipFillHeight(volume) {
  let lo=0,hi=140;
  for(let i=0;i<28;i++){const h=(lo+hi)/2,rt=.7+7.5*h/140,v=Math.PI*h*(.7*.7+.7*rt+rt*rt)/3/1000;if(v<volume)lo=h;else hi=h;}
  return (lo+hi)/2;
}
export function screw(parent,x,y,z,material) {
  const m=new THREE.Mesh(new THREE.CylinderGeometry(2.5,2.5,1.2,16),material);m.position.set(x,y,z);parent.add(m);
  const socket=new THREE.Mesh(new THREE.CylinderGeometry(1.1,1.1,.12,6),new THREE.MeshStandardMaterial({color:0x33383b,roughness:.7}));socket.position.set(x,y+.65,z);parent.add(socket);
}
export function flowLine(parent,radius,material=liquidMaterial) {
  const m=new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,1,12),material);m.visible=false;m.renderOrder=2;m.userData.fx=true;parent.add(m);
  const up=new THREE.Vector3(0,1,0),delta=new THREE.Vector3();
  return {mesh:m,set(a,b,on){delta.subVectors(b,a);m.visible=!!on&&delta.length()>.05;if(!m.visible)return;m.position.copy(a).add(b).multiplyScalar(.5);m.scale.y=delta.length();m.quaternion.setFromUnitVectors(up,delta.normalize());}};
}
