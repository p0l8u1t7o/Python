// 產品：依配方建出載盤、板子與接頭。接頭可翹起（以插頭尖端底緣為支點），銀腳端抬高即為未貼合。
// 座標：產品根節點在載盤底面中心；單位 mm。尺寸為照片目測或假設，實際以圖面校正。
import * as THREE from 'three';
import { finish } from '@core/geom/finish.js';
import { block, cylinder, decal, rounded } from '@core/geom/shapes.js';
import { microTexture, pcbSurface, batchStatic } from '@core/geom/surfaces.js';
import { CONNECTOR_TYPES } from './recipes.js';

const D2R = Math.PI / 180;
const matPallet = new THREE.MeshStandardMaterial({ color: 0x666158, roughness: 0.8, metalness: 0.08, map: microTexture('weave'), bumpMap: microTexture('weave'), bumpScale: .10 });
const matPocket = new THREE.MeshStandardMaterial({ color: 0x24211f, roughness: 0.95 });
const matRail = new THREE.MeshStandardMaterial({ color: 0x1a5a31, roughness: 0.6 });
const matGold = new THREE.MeshStandardMaterial({ color: 0xd8b04a, roughness: 0.3, metalness: 0.9 });
const matShell = new THREE.MeshStandardMaterial({ color: 0xc9cdd2, roughness: 0.32, metalness: 0.88, roughnessMap: microTexture('brushed'), bumpMap: microTexture('grain'), bumpScale: .012 });
const matHole = new THREE.MeshStandardMaterial({ color: 0x15181b, roughness: 0.6 });
const matLead = new THREE.MeshStandardMaterial({ color: 0xe6e8ea, roughness: 0.2, metalness: 1 });
const matPaste = new THREE.MeshStandardMaterial({ color: 0x9da5a4, roughness: .75, metalness: .45 });
finish(matPaste,'polymer',.005);
finish(matLead,'metal',.002); matLead.roughness=.34;
const matEdge = new THREE.MeshStandardMaterial({ color: 0x929b68, roughness: .83 });
const matTongues = new Map();
const COMP = {
  chip: new THREE.MeshStandardMaterial({ color: 0x1b1d20, roughness: 0.5 }),
  passive: new THREE.MeshStandardMaterial({ color: 0x8a6a4a, roughness: 0.5 }),
  cap: new THREE.MeshStandardMaterial({ color: 0x3a3f8a, roughness: 0.4, metalness: 0.3 }),
};

function rectangle(x, z, w, d) {
  const s = new THREE.Shape(); s.moveTo(x-w/2,-z-d/2); s.lineTo(x+w/2,-z-d/2);
  s.lineTo(x+w/2,-z+d/2); s.lineTo(x-w/2,-z+d/2); s.closePath(); return s;
}
function circleHole(shape, x, z, r) {
  const p = new THREE.Path(); p.absarc(x,-z,r,0,Math.PI*2,true); shape.holes.push(p);
}
function extrude(parent, shape, y, depth, material, uvScale = 1) {
  const geo = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments: 12 });
  geo.rotateX(-Math.PI/2);
  const uv = geo.getAttribute('uv'); for(let i=0;i<uv.count;i++) uv.setXY(i,uv.getX(i)/uvScale,uv.getY(i)/uvScale);
  const m = new THREE.Mesh(geo, material); m.position.y = y; m.castShadow = m.receiveShadow = true; parent.add(m); return m;
}

// Rectangular stamped lead cross-section, with a curved shoulder and flat landing foot.
function lead(parent, x, T) {
  const foot = T.sink + .085, s = new THREE.Shape();
  s.moveTo(-.35,foot+.95); s.lineTo(.12,foot+.95);
  s.bezierCurveTo(.8,foot+.95,.85,foot,.1+T.leadL*.52,foot);
  s.lineTo(T.leadL,foot); s.lineTo(T.leadL,foot+.15); s.lineTo(.1+T.leadL*.52,foot+.15);
  s.bezierCurveTo(1.05,foot+.15,1,foot+1.1,.12,foot+1.1); s.lineTo(-.35,foot+1.1); s.closePath();
  const width = Math.min(.34,T.leadPitch*.58);
  const geo = new THREE.ExtrudeGeometry(s,{depth:width,bevelEnabled:false,curveSegments:8});
  geo.rotateY(-Math.PI/2); geo.translate(x+width/2,0,T.l);
  const m = new THREE.Mesh(geo,matLead); m.castShadow=m.receiveShadow=true; parent.add(m);
}

/** 單顆接頭：pivot 在插頭尖端底緣，旋轉 −tilt 讓後緣（銀腳）抬高 */
function buildConnector(T) {
  const pivot = new THREE.Group(), { w, h, l } = T;
  // 以 pivot（尖端底緣）為原點：殼體 z ∈ [0, l]、y ∈ [0, h]；銀腳從後緣延伸到 PCB 焊墊上
  const lid = rectangle(0,l/2,w,l);
  if (T.holes) for (const s of [-1,1]) lid.holes.push(rectangle(s*2.6,4,2.3,2.15));
  extrude(pivot,lid,h-.28,.28,matShell,5);
  block(pivot, [w, 0.3, l], [0, 0.15, l / 2], matShell);
  for (const s of [-1, 1]) block(pivot, [0.3, h, l], [s * (w / 2 - 0.15), h / 2, l / 2], matShell);
  if (!matTongues.has(T.tongue)) matTongues.set(T.tongue,new THREE.MeshStandardMaterial({color:T.tongue,roughness:.65}));
  block(pivot, [w - 1, Math.min(1.2, h * 0.3), l - 1.5], [0, h * 0.50, l / 2 - 0.3], matTongues.get(T.tongue));
  for(let k=0;k<4;k++) block(pivot,[.8,.04,l*.42],[(k-1.5)*2,h*.50+.62,l*.29],matGold);
  block(pivot, [w-.7, h-.5, .55], [0, h / 2, l - .3], matHole);
  // Rolled front lip, shell seams and small stamped dimples.
  for(const side of [-1,1]) {
    block(pivot,[.12,h-.5,l-.5],[side*(w/2+.015),h/2,l/2],matShell);
    cylinder(pivot,.32,.055,[side*2.6,h+.025,6.3],matShell,'y',12);
  }
  block(pivot,[w,.12,.16],[0,h-.1,.08],matLead);
  cylinder(pivot,.34,.04,[0,h+.02,l*.73],matShell,'y',12);
  for (let k = 0; k < T.leads; k++) lead(pivot,(k-(T.leads-1)/2)*T.leadPitch,T);
  batchStatic(pivot);
  return pivot;
}

function buildBoard(parent, b, pcbTop) {
  const g = new THREE.Group(); g.position.set(b.x, 0, b.z); g.rotation.y = b.rot * D2R; parent.add(g);
  let shape = rectangle(b.cx,b.cz,b.w,b.d);
  if(b.w<25) {
    const x=b.w/2,z=b.d, points=[[-x+.6,0],[x-.6,0],[x,.6],[x,5],[x-.9,5.4],[x-.9,7],[x,7.4],[x,17],[x-.7,17.4],[x-.7,19],[x,19.4],[x,z-.6],[x-.6,z],[-x+.6,z],[-x,z-.6],[-x,19.4],[-x+.7,19],[-x+.7,17.4],[-x,17],[-x,7.4],[-x+.9,7],[-x+.9,5.4],[-x,5],[-x,.6]];
    shape=new THREE.Shape(points.map(([px,pz])=>new THREE.Vector2(px+b.cx,-(pz+b.cz-b.d/2)))); shape.closePath();
  }
  for(const side of [-1,1]) circleHole(shape,b.cx+side*(b.w/2-1.3),b.cz+b.d/2-1.6,.65);
  extrude(g,shape,pcbTop-b.t,b.t,matEdge);
  const topGeo = new THREE.ShapeGeometry(shape,12); topGeo.rotateX(-Math.PI/2);
  const pos = topGeo.getAttribute('position'), uv=topGeo.getAttribute('uv');
  for(let i=0;i<pos.count;i++) uv.setXY(i,(pos.getX(i)-b.cx)/b.w+.5,.5-(pos.getZ(i)-b.cz)/b.d);
  const topMesh = new THREE.Mesh(topGeo,pcbSurface(b)); topMesh.position.y=pcbTop+.006; topMesh.receiveShadow=true; g.add(topMesh);
  // The routed edges expose the FR-4 laminate; top solder mask follows the same outline.
  for (const c of b.comps || []) {
    rounded(g,c.w,c.d,c.h,.12,[c.x,pcbTop,c.z],COMP[c.kind]);
    if(c.kind==='chip') {
      const n = Math.min(12,Math.floor(c.w/.5));
      for(let k=0;k<n;k++) for(const side of [-1,1]) {
        const p = (k-(n-1)/2)*c.w/n;
        block(g,[.19,.13,.7],[c.x+p,pcbTop+.11,c.z+side*(c.d/2+.22)],matLead);
        block(g,[.7,.13,.19],[c.x+side*(c.w/2+.22),pcbTop+.11,c.z+p],matLead);
      }
      decal(g,c.w*.78,c.d*.42,[c.x,pcbTop+c.h+.06,c.z],[-Math.PI/2,0,0],['CONTROLLER','DEMO'],{color:'#8e9795',center:true});
      cylinder(g,.18,.018,[c.x-c.w*.32,pcbTop+c.h+.07,c.z-c.d*.3],matPocket,'y',10);
    } else for(const side of [-1,1]) block(g,[c.w*.23,c.h+.02,c.d+.04],[c.x+side*c.w*.39,pcbTop+c.h/2,c.z],matLead);
  }
  for(const side of [-1,1]) {
    const m=block(g,[.8,.025,.8],[b.cx+side*(b.w/2-1.1),pcbTop+.035,b.cz-b.d/2+2],matGold); m.rotation.y=Math.PI/4;
  }
  return g;
}

export function createProduct(recipe) {
  const root = new THREE.Group(); root.name = 'product';
  const { w: PW, d: PD, t: PT, code } = recipe.pallet, pcbTop = PT + recipe.pcbT;
  const solid = new THREE.Group(); root.add(solid);
  // Machined recesses in a woven carrier; the floor remains beneath each connector.
  const carrier = rectangle(0,0,PW,PD), base = rectangle(0,0,PW,PD);
  for(const x of [-PW/2+13,PW/2-13]) for(const z of [-PD/2+14,PD/2-14]) { circleHole(carrier,x,z,2.4); circleHole(base,x,z,2.4); }
  for(const c of recipe.connectors) {
    const T=CONNECTOR_TYPES[c.type], hole=rectangle(0,-T.l/2,T.w+2,T.l+3);
    // Shape coordinates are (x,-z); rotate into the recipe mount frame.
    const r=c.rot*D2R, points=hole.getPoints().map(p=>new THREE.Vector2(c.x+p.x*Math.cos(r)-p.y*Math.sin(r),-c.z+p.x*Math.sin(r)+p.y*Math.cos(r)));
    carrier.holes.push(new THREE.Path(points));
  }
  extrude(solid,base,0,PT-2.2,matPallet,8);
  extrude(solid,carrier,PT-2.2,2.2,matPallet,8);
  decal(solid,44,9,[0,PT+.035,-PD/2+12],[-Math.PI/2,0,0],code,{color:'#292825',center:true,bold:true});
  const panel = new THREE.Group(); solid.add(panel);
  for (const b of recipe.boards) buildBoard(panel, b, pcbTop);
  for (const r of recipe.rails) block(panel, [r.w, recipe.pcbT, r.d], [r.x, pcbTop - recipe.pcbT / 2, r.z], matRail);
  batchStatic(solid);
  const conns = {};
  for (const c of recipe.connectors) {
    const T = CONNECTOR_TYPES[c.type];
    // mount：接頭參考框架（後緣中心、PCB 上表面），插頭朝本地 −z；不隨翹起轉動
    const mount = new THREE.Group(); mount.position.set(c.x, pcbTop, c.z); mount.rotation.y = c.rot * D2R; root.add(mount);
    block(mount, [T.w + 1.8, .08, T.l + 2.8], [0, -recipe.pcbT-2.15, -T.l / 2], matPocket);
    for (let k = 0; k < T.leads; k++) {
      const x=(k-(T.leads-1)/2)*T.leadPitch, w=Math.min(.55,T.leadPitch*.8);
      block(mount,[w,.035,T.leadL],[x,.025,T.leadL/2],matGold);
      // Unreflowed solder paste, not a finished solder fillet.
      block(mount,[w*.82,.045,T.leadL*.66],[x,.06,T.leadL*.62],matPaste);
    }
    batchStatic(mount);
    const pivot = buildConnector(T); pivot.position.set(0, -T.sink, -T.l); mount.add(pivot);
    conns[c.id] = { ...c, T, mount, pivot, tilt: 0 };
  }
  const v = new THREE.Vector3();
  function setTilt(id, deg) { const c = conns[id]; c.tilt = deg; c.pivot.rotation.x = -deg * D2R; }
  /** 貼平狀態下的壓點（殼頂、靠銀腳側）世界座標 */
  function pressPoint(id) { const c = conns[id]; return c.mount.localToWorld(v.set(0, c.T.h - c.T.sink, -c.T.l + c.T.pressFromTip).clone()); }
  /** 銀腳與焊墊交界（相機對焦點）世界座標 */
  function leadPoint(id) { return conns[id].mount.localToWorld(v.set(0, 0, 1.5).clone()); }
  /** 插頭指向（世界、水平） */
  function pointing(id) { const r = conns[id].rot * D2R; return new THREE.Vector3(-Math.sin(r), 0, -Math.cos(r)); }
  const gap = id => { const c = conns[id]; return (c.T.l + c.T.leadL) * Math.sin(c.tilt * D2R); };
  return { root, conns, ids: recipe.connectors.map(c => c.id), setTilt, pressPoint, leadPoint, pointing, gap };
}

/** 壓點抬高 h mm 時的翹起角（°） */
export const tiltForLift = (T, h) => Math.asin(Math.min(1, Math.max(0, h / T.pressFromTip))) / D2R;
/** 翹起角對應的壓點抬高量（mm） */
export const liftForTilt = (T, deg) => T.pressFromTip * Math.sin(deg * D2R);
export const gapForTilt = (T, deg) => (T.l + T.leadL) * Math.sin(deg * D2R);
