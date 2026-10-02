// 快門產品：本體（含樞軸銷、撥桿銷、導線）、4 片葉片（小×2、大×2）、上蓋。
// 本體座標：原點在本體頂面中心，x 沿寬（18 mm）、z 沿深（17 mm，+z 朝作業員）、y 向上。單位 mm。
// 尺寸依工程圖（2-φ0.80 銷、A 4.05 厚、O 0.20）與照片目測；葉片外形與孔位依照片描繪，非 CAD。
import * as THREE from 'three';
import { microTexture } from '@core/geom/surfaces.js';

export const PART = {
  base: { w: 18.0, d: 17.0, h: 4.05, chamfer: 0.8, chamber: [15.2, 14.2, 1.5], depth: 0.6, aperture: [9.4, 8.4, 1.0], holes: [8.1, 7.6, 0.55] },
  pivots: { P1: { x: 6.1, z: -5.1, yaw: 0 }, P2: { x: -6.1, z: 5.1, yaw: Math.PI } },  // 右上、左下兩個樞軸（工程圖圓形轉子位置）
  pin: { pivotR: 0.40, driveR: 0.30, pivotTop: -0.05, driveTop: -0.10 },               // φ0.80 樞軸銷、φ0.60 撥桿銷（撥桿銷徑為假設）
  blade: { t: 0.06, pitch: 0.08, gap: 0.02, holeR: 0.43, slot: { x: -2.1, z: -0.15, len: 1.0, r: 0.33 }, pick: { x: 0.3, z: 5.5 } },
  cover: { w: 17.8, d: 16.8, t: 0.2, float: 0.5 },   // 壓合前卡勾頂在本體邊緣，上蓋浮高 0.5 mm
  coverPads: { x: [-3.1, 3.1], z: [-6.7, 6.7], w: 2.4, d: 1.6 }, // 避開沖孔的四個真空接觸面
  wire: { len: 32 },
};

// 葉片外形（樞軸孔在原點；P1 位置時長邊沿 +z、C 形開口朝 −x 包住光圈）
const OUTLINE = {
  small: [[-3.3,-1],[-1.3,-1.5],[.6,-1.4],[1.3,-.6],[1.3,2.4],[1.3,7.9],[.9,10.6],[.3,11.4],[-6.7,11.4],[-7.4,10.7],[-7,10],[-1.1,10],[-.5,9.3],[-.5,2.1],[-1.2,1.1],[-3.4,.9]],
  large: [[-3.3,-1],[-1.3,-1.5],[.6,-1.4],[1.3,-.6],[1.3,2.4],[1.3,8.4],[.8,10.9],[.1,11.6],[-8.7,11.6],[-9.5,10.9],[-9.1,9.6],[-1.9,9.6],[-1.1,8.8],[-1.1,2.1],[-1.7,1.1],[-3.4,.9]],
};
/** 4 片葉片：疊放順序即組裝順序（小 A → 小 B → 大 A → 大 B） */
export const BLADES = [
  { id: 'S1', name: '小葉片 A', kind: 'small', pivot: 'P1', layer: 0 },
  { id: 'S2', name: '小葉片 B', kind: 'small', pivot: 'P2', layer: 1 },
  { id: 'L1', name: '大葉片 A', kind: 'large', pivot: 'P1', layer: 2 },
  { id: 'L2', name: '大葉片 B', kind: 'large', pivot: 'P2', layer: 3 },
];

const matBase = new THREE.MeshStandardMaterial({ color: 0xaeb4ba, roughness: 0.43, metalness: 0.88, bumpMap: microTexture('brushed'), bumpScale: .003 });
const matFloor = new THREE.MeshStandardMaterial({ color: 0x17191c, roughness: 0.55, metalness: 0.35 });
const matPin = new THREE.MeshStandardMaterial({ color: 0xe1e5ea, roughness: 0.18, metalness: 0.95 });
const matRotor = new THREE.MeshStandardMaterial({ color: 0x2b2f35, roughness: 0.4, metalness: 0.6 });
const matCopper = new THREE.MeshStandardMaterial({ color: 0xc4834a, roughness: 0.28, metalness: 0.86 });
const matBladeS = new THREE.MeshStandardMaterial({ color: 0x39413f, roughness: 0.72, metalness: 0.22, bumpMap: microTexture('grain'), bumpScale: .0015 });
const matBladeL = new THREE.MeshStandardMaterial({ color: 0x181c20, roughness: 0.64, metalness: 0.28, bumpMap: microTexture('grain'), bumpScale: .0015 });
const matCover = new THREE.MeshStandardMaterial({ color: 0x161b20, roughness: 0.5, metalness: 0.55, bumpMap: microTexture('brushed'), bumpScale: .002 });
const matCut = new THREE.MeshStandardMaterial({ color: 0x70777d, roughness: .42, metalness: .8 });
const matRed = new THREE.MeshStandardMaterial({ color: 0xc8261e, roughness: 0.55 });
const matBlack = new THREE.MeshStandardMaterial({ color: 0x1b1b1b, roughness: 0.55 });
const matConn = new THREE.MeshStandardMaterial({ color: 0xf1efe6, roughness: 0.6 });
export const PART_MATERIALS = { matBladeS, matBladeL };

// ---- 2D 形狀工具（輸入為 (x, z)；擠出方向 +y）----
function toShape(points, Cls = THREE.Shape) { const s = new Cls(); points.forEach(([x, z], i) => (i ? s.lineTo(x, -z) : s.moveTo(x, -z))); s.closePath(); return s; }
// Rounded stamped contour. The vision overlay samples this same path.
function bladeShape(kind) {
  const points = OUTLINE[kind], s = new THREE.Shape();
  points.forEach(([x,z], i) => {
    const prev = points[(i + points.length - 1) % points.length], next = points[(i + 1) % points.length];
    const a = [.8*x + .2*prev[0], .8*z + .2*prev[1]], b = [.8*x + .2*next[0], .8*z + .2*next[1]];
    if (i) s.lineTo(a[0], -a[1]); else s.moveTo(a[0], -a[1]);
    s.quadraticCurveTo(x, -z, b[0], -b[1]);
  });
  s.closePath(); return s;
}
function windowPath(x, z, w, d, r) {
  return toShape(roundRectPath(w,d,r).getPoints(6).map(p => [p.x+x, -p.y+z]), THREE.Path);
}
function chamferRect(w, d, c) { const x = w / 2, z = d / 2; return [[-x + c, -z], [x - c, -z], [x, -z + c], [x, z - c], [x - c, z], [-x + c, z], [-x, z - c], [-x, -z + c]]; }
// Four reliefs under the folded cover tabs. Dimensions remain schematic pending CAD.
function clipRelief(indent) {
  return [[-8.2,-8.5],[8.2,-8.5],[9,-7.7],[9,-6.4],[indent,-6.4],[indent,-4],[9,-4],[9,4],[indent,4],[indent,6.4],[9,6.4],[9,7.7],[8.2,8.5],[-8.2,8.5],[-9,7.7],[-9,6.4],[-indent,6.4],[-indent,4],[-9,4],[-9,-4],[-indent,-4],[-indent,-6.4],[-9,-6.4],[-9,-7.7]];
}
function roundRectPath(w, d, r, Cls = THREE.Path) {
  // Shape 座標為 (x, −z)；逆時針畫圓角矩形
  const p = new Cls(), x = w / 2, y = d / 2;
  p.moveTo(-x + r, -y); p.lineTo(x - r, -y); p.absarc(x - r, -y + r, r, -Math.PI / 2, 0, false);
  p.lineTo(x, y - r); p.absarc(x - r, y - r, r, 0, Math.PI / 2, false);
  p.lineTo(-x + r, y); p.absarc(-x + r, y - r, r, Math.PI / 2, Math.PI, false);
  p.lineTo(-x, -y + r); p.absarc(-x + r, -y + r, r, Math.PI, Math.PI * 1.5, false);
  return p;
}
function circlePath(x, z, r) { const p = new THREE.Path(); p.absarc(x, -z, r, 0, Math.PI * 2, true); return p; }
function slotPath(x, z, len, r) {
  const p = new THREE.Path(), h = len / 2 - r;
  p.moveTo(x - h, -z - r); p.lineTo(x + h, -z - r); p.absarc(x + h, -z, r, -Math.PI / 2, Math.PI / 2, false);
  p.lineTo(x - h, -z + r); p.absarc(x - h, -z, r, Math.PI / 2, Math.PI * 1.5, false); return p;
}
function extrude(shape, y0, y1, mat, curveSegments = 10) {
  const g = new THREE.ExtrudeGeometry(shape, { depth: y1 - y0, bevelEnabled: false, curveSegments });
  g.rotateX(-Math.PI / 2); g.translate(0, y0, 0);
  const m = new THREE.Mesh(g, mat); m.castShadow = m.receiveShadow = true; return m;
}
function cyl(parent, r, y0, y1, x, z, mat, seg = 18) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, y1 - y0, seg), mat);
  m.position.set(x, (y0 + y1) / 2, z); m.castShadow = m.receiveShadow = true; parent.add(m); return m;
}

/** 以樞軸為原點的平面旋轉（與 three.js 的 rotation.y 相同方向） */
export function rotY(x, z, a) { const c = Math.cos(a), s = Math.sin(a); return { x: x * c + z * s, z: -x * s + z * c }; }

/** 葉片在本體座標中的安裝位置：原點（吸取點、頂面）與 yaw；樞軸孔、長孔中心 */
export function bladeSeat(b) {
  const P = PART.pivots[b.pivot], B = PART.blade;
  const pick = rotY(B.pick.x, B.pick.z, P.yaw), slot = rotY(B.slot.x, B.slot.z, P.yaw);
  const y = -PART.base.depth + B.gap + b.layer * B.pitch + B.t;
  return { x: P.x + pick.x, y, z: P.z + pick.z, yaw: P.yaw, pivot: { x: P.x, z: P.z }, drive: { x: P.x + slot.x, z: P.z + slot.z } };
}
/** 撥桿銷位置（本體座標）：由葉片長孔反推 */
export function drivePin(pivotKey) { const P = PART.pivots[pivotKey], s = rotY(PART.blade.slot.x, PART.blade.slot.z, P.yaw); return { x: P.x + s.x, z: P.z + s.z }; }

// ---- 幾何建構 ----
export function createBase() {
  const g = new THREE.Group(); g.name = 'shutter-base';
  const B = PART.base, [hx, hz, hr] = B.holes;
  const outer = chamferRect(B.w, B.d, B.chamfer);
  const corners = [[hx, hz], [-hx, hz], [hx, -hz], [-hx, -hz]];
  // 下層本體：光圈與四角孔貫穿
  const low = toShape(outer); low.holes.push(roundRectPath(...B.aperture)); corners.forEach(([x, z]) => low.holes.push(circlePath(x, z, hr)));
  g.add(extrude(low, -B.h, -2, matBase, 12));
  // Two recessed actuator winding pockets, visible in the assembly reference.
  const coils = [{ x: -1.4, z: -5.9 }, { x: 1.4, z: 5.9 }];
  const middle = toShape(outer); middle.holes.push(roundRectPath(...B.aperture));
  corners.forEach(([x,z]) => middle.holes.push(circlePath(x,z,hr)));
  coils.forEach(({x,z}) => middle.holes.push(windowPath(x,z,8.7,1.7,.25)));
  g.add(extrude(middle, -2, -1.3, matBase, 12));
  for(const [y0,y1,indent] of [[-1.3,-.9,8.65],[-.9,-B.depth-.04,8.85]]) {
    const relieved=toShape(clipRelief(indent));relieved.holes=middle.holes;
    g.add(extrude(relieved,y0,y1,matBase,12));
  }
  // 黑色底板（葉片滑動面）：葉片腔形狀，含光圈
  const floorShape = roundRectPath(...B.chamber, THREE.Shape); floorShape.holes.push(roundRectPath(...B.aperture));
  coils.forEach(({x,z}) => floorShape.holes.push(windowPath(x,z,8.7,1.7,.25)));
  // 底面比上層框底面高 0.01 mm：兩個底面重合會深度互搶（隱藏面，但仍是重合面）
  g.add(extrude(floorShape, -B.depth - 0.03, -B.depth, matFloor, 12));
  // 上層框：外框減葉片腔
  const rim = toShape(clipRelief(8.85)); rim.holes.push(roundRectPath(...B.chamber)); corners.forEach(([x, z]) => rim.holes.push(circlePath(x, z, hr)));
  g.add(extrude(rim, -B.depth - 0.04, 0, matBase, 12));
  // 轉子座、樞軸銷、撥桿銷
  for (const key of ['P1', 'P2']) {
    const P = PART.pivots[key], D = drivePin(key);
    cyl(g, 1.55, -B.depth - 0.01, -B.depth + 0.01, P.x, P.z, matRotor, 24);   // 頂面高出底板 0.01 mm，仍在最低葉片底面（−0.58）之下
    cyl(g, PART.pin.pivotR, -B.depth, PART.pin.pivotTop, P.x, P.z, matPin, 16).name = 'pivot-' + key;
    cyl(g, PART.pin.driveR, -B.depth, PART.pin.driveTop, D.x, D.z, matPin, 14).name = 'drive-' + key;
    const bearing = new THREE.Mesh(new THREE.TorusGeometry(1.13,.10,6,28),matCut);
    bearing.rotation.x = Math.PI/2; bearing.scale.z=.1; bearing.position.set(P.x,-B.depth+.006,P.z); g.add(bearing);
  }
  // Lathed fine ridges represent lacquered copper turns without hundreds of separate rings.
  for (const [i,{x,z}] of coils.entries()) {
    const profile = [];
    for(let n=0;n<=144;n++) profile.push(new THREE.Vector2(.52 + .035*Math.cos(n*Math.PI/2), -3.7+n*7.4/144));
    const winding = new THREE.Mesh(new THREE.LatheGeometry(profile,16),matCopper);
    winding.rotation.z = Math.PI/2; winding.position.set(x,-1.27,z); winding.name = 'actuator-winding-'+i;
    winding.castShadow = winding.receiveShadow = true; g.add(winding);
    for(const side of [-1,1]) {
      const cap = new THREE.Mesh(new THREE.CylinderGeometry(.64,.64,.28,20),matRotor);
      cap.rotation.z=Math.PI/2; cap.position.set(x+side*3.9,-1.27,z); g.add(cap);
    }
  }
  // 側面 M1.6 螺孔（工程圖 B：4-M1.6）
  for (const x of [-B.w / 2 - 0.01, B.w / 2 + 0.01]) for (const y of [-1.2, -2.9]) {
    const h = new THREE.Mesh(new THREE.CircleGeometry(0.42, 16), matFloor); h.position.set(x, y, 0); h.rotation.y = x > 0 ? Math.PI / 2 : -Math.PI / 2; g.add(h);
  }
  // 線圈座（−x 側）與紅黑導線、白色端子
  // 線圈座頂面在 −1.48：上蓋 −x 側卡勾（底端 −1.45）壓合到底時從上方經過，不壓入線圈座
  const terminal = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.82, 5.0), matRotor); terminal.position.set(-B.w / 2 - 0.5, -2.39, 2.8); g.add(terminal);
  for(const z of [2.2,3.4]) {
    const pad = new THREE.Mesh(new THREE.SphereGeometry(.37,12,8),matPin);
    pad.scale.set(.55,.8,1); pad.position.set(-B.w/2-1.28,-2.2,z); g.add(pad);
  }
  // Preformed harness loop remains inside the dedicated tray/nest wire bay.
  // Both conductors follow parallel curves, instead of crossing the neighbouring pocket.
  const harness = new THREE.CatmullRomCurve3([[-10.2,-2.2,2.8],[-12,-2.4,2.8],[-13,-2.5,1],[-12.5,-2.6,-4],[-15,-2.6,-6.5],[-17.5,-2.6,-4],[-17,-2.6,1],[-15.8,-2.7,4.7]].map(p=>new THREE.Vector3(...p)));
  [matRed,matBlack].forEach((mat,i) => {
    const pts=Array.from({length:65},(_,n)=>{
      const t=n/64,p=harness.getPoint(t),d=harness.getTangent(t);
      return p.add(new THREE.Vector3(-d.z,0,d.x).normalize().multiplyScalar(i ? -.6 : .6));
    });
    const curve=new THREE.CatmullRomCurve3(pts);
    const m=new THREE.Mesh(new THREE.TubeGeometry(curve,96,.32,8,false),mat);
    m.name='harness-'+i; m.userData.length=curve.getLength(); m.castShadow=true;g.add(m);
  });
  const conn = new THREE.Mesh(new THREE.BoxGeometry(3.2, 2.4, 4.2), matConn); conn.position.set(-15.8,-2.7,6.8); conn.name='harness-connector';g.add(conn);
  for(const x of [-16.55,-15.05]) {
    const socket = new THREE.Mesh(new THREE.PlaneGeometry(.95,1.2),matBlack);
    socket.position.set(x,-2.7,8.915); g.add(socket);   // 離接頭端面 0.015 mm，不重合
  }
  return g;
}

const bladeGeoCache = {};
function bladeGeometry(kind) {
  if (bladeGeoCache[kind]) return bladeGeoCache[kind];
  const B = PART.blade, s = bladeShape(kind);
  s.holes.push(circlePath(0, 0, B.holeR), slotPath(B.slot.x, B.slot.z, B.slot.len, B.slot.r));
  const g = new THREE.ExtrudeGeometry(s, { depth: B.t, bevelEnabled: false, curveSegments: 10 });
  g.rotateX(-Math.PI / 2); g.translate(-B.pick.x, -B.t, -B.pick.z);   // 原點＝吸取點、頂面
  return (bladeGeoCache[kind] = g);
}
/** 葉片：群組原點＝吸嘴吸取點（葉片頂面）；樞軸孔在本地 (−pick.x, −pick.z) */
export function createBlade(kind) {
  const g = new THREE.Group(); g.name = 'blade-' + kind;
  const m = new THREE.Mesh(bladeGeometry(kind), kind === 'small' ? matBladeS : matBladeL); m.castShadow = m.receiveShadow = true; g.add(m);
  return g;
}
/** 葉片外形（群組座標，(x, z)），供相機標記描邊 */
export function bladeOutline(kind) { const B = PART.blade; return bladeShape(kind).getPoints(6).map(p => ({ x: p.x - B.pick.x, z: -p.y - B.pick.z })); }
/** 葉片本地的樞軸孔、長孔中心（群組座標） */
export function bladeHoles() { const B = PART.blade; return { pivot: { x: -B.pick.x, z: -B.pick.z }, slot: { x: B.slot.x - B.pick.x, z: B.slot.z - B.pick.z } }; }

export function createCover() {
  const g = new THREE.Group(); g.name = 'cover';
  const C = PART.cover, s = toShape(chamferRect(C.w, C.d, 0.8)); s.holes.push(roundRectPath(...PART.base.aperture));
  // Photo: diagonal elongated access holes, pilot holes and two pressed slots.
  for(const side of [-1,1]) {
    s.holes.push(windowPath(side*6.1,-side*5.1,1.25,2.5,.55));
    s.holes.push(circlePath(side*6.6,-side*2.9,.38));
    s.holes.push(windowPath(side*7.6,side*6.9,.85,1.2,.35));
  }
  s.holes.push(windowPath(6.35,.2,1.65,.42,.18));
  s.holes.push(windowPath(6.35,1.7,.42,1.25,.18));
  const plate = extrude(s, -C.t, 0, [matCover,matCut], 12); plate.name='stamped-cover'; g.add(plate);
  // 4 個卡勾：折向下、卡入本體側邊
  for (const side of [-1,1]) for(const z of [-5.2,5.2]) {
    const clip=new THREE.Group();clip.name='cover-clip';clip.userData.side=side;g.add(clip);
    const tab = new THREE.Mesh(new THREE.BoxGeometry(C.t, 1.3, 2.2), matCover); tab.position.set(side*9,-.8,z);tab.castShadow=true;clip.add(tab);
    const hook=new THREE.Mesh(new THREE.BoxGeometry(.35,.2,2.0),matCover);hook.position.set(side*8.925,-1.3,z);clip.add(hook);
    const bridge=new THREE.Mesh(new THREE.BoxGeometry(1,.2,2.2),matCover);bridge.position.set(side*8.95,-.1,z);bridge.scale.x=.3;bridge.name='clip-bridge';g.add(bridge);
    clip.userData.bridge=bridge;
  }
  return g;
}

export function setCoverFlex(cover,gap) {
  // A schematic spring deflection: ramp on the lead-in, snap into the relief.
  const flex=gap>=.095 && gap<1.5 ? Math.min(.2,(1.5-gap)/.3*.2) : 0;
  for(const clip of cover.children.filter(c=>c.name==='cover-clip')) {
    const side=clip.userData.side;clip.position.x=side*flex;
    const bridge=clip.userData.bridge;bridge.scale.x=.3+flex;bridge.position.x=side*(8.95+flex/2);
  }
}

/** 成品（本體＋4 片葉片＋上蓋），給料盤中已完成的格子用 */
export function createAssembly({ blades = true, cover = true } = {}) {
  const g = new THREE.Group(); g.add(createBase());
  if (blades) for (const b of BLADES) { const s = bladeSeat(b), m = createBlade(b.kind); m.position.set(s.x, s.y, s.z); m.rotation.y = s.yaw; g.add(m); }
  if (cover) { const c = createCover(); c.position.y = PART.cover.t; g.add(c); }
  return g;
}
