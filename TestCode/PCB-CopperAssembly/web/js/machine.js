// 機台：底座、邊軌輸送線（S1–S3 頂升真空台）、S0／S4 料倉與上下料、S1／S3 相機龍門、
// S2 雙龍門（4 吸嘴頭，Z＋θ）、柔性供料盤、仰視相機、外罩與三色燈。座標同 layout.js。
import * as THREE from 'three';
import {cabinetShell,controlPanel,entryGland,panelFeed} from './electrical-cabinet.js';
import { cable, cableTray, carrier, support, CABLE } from './cable-routing.js';
import { finish } from './finish.js';
import { perforated } from './perforated.js';
import { block, cylinder, decal } from './detail.js';
import { LAYOUT, PRODUCT, HOLES, BOARD_TOP } from './layout.js';
import { createCoin } from './board.js';

const matFrame = new THREE.MeshStandardMaterial({ color: 0x6b7480, roughness: 0.5, metalness: 0.6 });
const matAlu = new THREE.MeshStandardMaterial({ color: 0xb9c0c8, roughness: 0.35, metalness: 0.8 });
const matDark = new THREE.MeshStandardMaterial({ color: 0x1e2226, roughness: 0.5, metalness: 0.4 });
const matBase = new THREE.MeshStandardMaterial({ color: 0xd9dcdf, roughness: 0.6, metalness: 0.2 });
const matGranite = new THREE.MeshStandardMaterial({ color: 0x2a2d31, roughness: 0.85 });
const matBlue = new THREE.MeshStandardMaterial({ color: 0x2f5f9e, roughness: 0.5, metalness: 0.4 });
const matBelt = new THREE.MeshStandardMaterial({ color: 0x2e7d56, roughness: 0.75 });
const matYellow = new THREE.MeshStandardMaterial({ color: 0xf2b21b, roughness: 0.6 });
const matPC = new THREE.MeshPhysicalMaterial({ color: 0xcfe3ff, roughness: 0.1, transmission: 0.3, transparent: true, opacity: 0.1, depthWrite: false, side: THREE.DoubleSide });
const matFeeder = new THREE.MeshStandardMaterial({ color: 0xe8eef2, roughness: 0.7, emissive: 0x9fb8c8, emissiveIntensity: 0.25 });
finish(matAlu,'metal',.008); finish(matFrame,'metal',.012); finish(matBase,'polymer',.025);
const glow = () => new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.05 });
const top = LAYOUT.conveyorTop, ST = LAYOUT.stations, G = LAYOUT.gantry;
function annulus(parent, outer, inner, y, material) {
  const mesh = new THREE.Mesh(new THREE.RingGeometry(inner, outer, 40), material);
  mesh.rotation.x = Math.PI / 2; mesh.position.y = y; parent.add(mesh); return mesh;
}
function bolt(parent, x, y, z) {
  cylinder(parent, 3.4, 2, [x, y, z], matAlu, 'y', 20);
  cylinder(parent, 1.5, .12, [x, y + 1.05, z], matDark, 'y', 6);
}

/** 相機外形（朝向 dir：'down' 或 'up'），回傳 { group, ring, cam（視角） } */
function camera(parent, pos, dir, { fov = 20, ringR = 34, power = 600, leadSide = 0 } = {}) {
  const g = new THREE.Group(); g.position.set(...pos); parent.add(g);
  const s = dir === 'down' ? 1 : -1;
  block(g, [44, 47, 34], [0, s * 60, 0], matDark);
  cylinder(g, 15, 36, [0, s * 18, 0], matDark);
  for (const y of [7, 13, 25]) cylinder(g, 15.5, 1.4, [0, s * y, 0], matAlu, 'y', 40);
  // Optical front sits behind the camera origin so it cannot obscure its own image.
  const glass = cylinder(g, 11, .5, [0, s * 1, 0], new THREE.MeshPhysicalMaterial({ color: 0x203b50, metalness: .3, roughness: .09 }), 'y', 40);
  glass.castShadow = false;
  const ringMat = glow(); const ring = new THREE.Mesh(new THREE.TorusGeometry(ringR, 5, 8, 36), ringMat); ring.rotation.x = Math.PI / 2; g.add(ring);
  const light = new THREE.SpotLight(0xffffff, 0, 900, 0.6, 0.5, 1); light.target.position.set(0, -s * 500, 0); g.add(light, light.target);
  // 相機預設朝本地 −z；繞 x 轉 ∓90° 改為朝下／朝上（群組只有平移，直接設旋轉即可）
  const cam = new THREE.PerspectiveCamera(fov, 1.5, 1, 3000); cam.rotation.x = dir === 'down' ? -Math.PI / 2 : Math.PI / 2; g.add(cam);
  const data=leadSide?[[leadSide*22,s*68,0],[leadSide*40,s*70,0],[leadSide*46,s*110,0],[leadSide*46,s*125,0]]:[[0,s*68,-17],[0,s*70,-35],[0,s*(dir==='up'?85:110),-42],[0,s*125,-42]];
  const lightRoute=leadSide?[[leadSide*22,s*63,0],[leadSide*(ringR+12),s*60,0],[leadSide*(ringR+12),s*22,0],[leadSide*ringR,s*5,0]]:[[0,s*63,17],[0,s*60,ringR+12],[0,s*22,ringR+12],[0,s*5,ringR]];
  cable(g,'CAM / data connector',data,{radius:2.4,color:CABLE.signal,clips:1});
  cable(g,'CAM / ring-light lead',lightRoute,{radius:1.5,color:CABLE.power,clips:1});
  return { group: g, cam, flash(on) { ringMat.emissiveIntensity = on ? 1.4 : 0.05; light.intensity = on ? power : 0; } };
}

export function createMachine(scene) {
  const g = new THREE.Group(); g.name = 'machine'; scene.add(g);
  const keepout = [], ko = (m, n) => { m.name = n; keepout.push(m); return m; };
  const routingUpdates=[];
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(9000, 6000), new THREE.MeshStandardMaterial({ color: 0x1b2027, roughness: 0.95 })); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; g.add(floor);
  const grid = new THREE.GridHelper(9000, 45, 0x2c3540, 0x222a33); grid.position.y = 0.5; g.add(grid);

  // ---- 底座（S2 花崗岩平台）與輸送線 ----
  const baseEntries=[{x:-620,z:LAYOUT.feeder.A.z-42,hole:9,sourceY:784},{x:620,z:LAYOUT.feeder.B.z-42,hole:9,sourceY:784},...['A','B'].map(H=>({x:LAYOUT.upCam[H].x,z:LAYOUT.upCam[H].z-42,hole:9,sourceY:755}))];
  const baseCabinet=cabinetShell(g,'BASE / electrical cabinet',{center:[0,390,0],size:[3500,780,1000],entries:baseEntries,thickness:16,material:matBase});
  const basePanel=controlPanel(g,'BASE / motion and vision control',{center:[0,400,-440],width:3200,height:590,backZ:-497,profile:'pcb'});
  for(const [i,e] of baseEntries.entries()){
    entryGland(g,'BASE / camera gland '+i,{at:[e.x,780,e.z],hole:e.hole,wire:2.4,thickness:16});
    panelFeed(g,'BASE / camera to terminal '+i,[[e.x,e.sourceY,e.z],[e.x,720,e.z],[e.x,675,-390],[basePanel.ports[i*3][0],675,-390],basePanel.ports[i*3]],{radius:2.4});
  }
  perforated(g,[1200,60,1000],[0,810,0],Object.values(LAYOUT.upCam).filter(u=>typeof u==='object').map(u=>[u.x,u.z,60]),matGranite).name='granite-camera-service-bores';
  const beltMarks = new THREE.Group(); g.add(beltMarks);
  for (const s of [-1, 1]) {
    block(g, [3400, 40, 16], [0, top - 12, s * (LAYOUT.railInner + 8)], matAlu);
    for (let x = -1640; x <= 1640; x += 140) bolt(g, x, top + 9, s * (LAYOUT.railInner + 8));
    block(g, [3380, 2, 8], [0, top - 1, s * (LAYOUT.railInner - 4)], matBelt);
    for (let x = -1680; x < 1680; x += 60) block(beltMarks, [3, 0.6, 7], [x, top + 0.3, s * (LAYOUT.railInner - 4)], matAlu);
    for (const x of [-1600, -1000, -300, 300, 1000, 1600]) block(g, [40, top - 820, 40], [x, (top + 820) / 2 - 20, s * (LAYOUT.railInner + 8)], matFrame);
  }
  // 頂升真空台（S1、S2、S3）
  const lifts = [1, 2, 3].map(i => { const l = new THREE.Group(); l.position.x = ST[i]; g.add(l); block(l, [330, 10, 330], [0, top - 7, 0], matAlu); for (const [x, z] of [[-120, -120], [120, -120], [-120, 120], [120, 120]]) block(g, [40, 60, 40], [ST[i] + x, top - 60, z], matDark); return l; });
  const stops = [1, 2, 3].map(i => { const s = new THREE.Group(); g.add(s); cylinder(s, 6, 24, [ST[i] + 181, top - 2, 0], matAlu); return s; });

  // ---- S0／S4 料倉＋上下料 ----
  const stacks = {}, loaders = {};
  for (const [key, x, label] of [['S0', ST[0], '上料料倉'], ['S4', ST[4], '收料料倉']]) {
    const sg = new THREE.Group(); sg.position.set(x, 0, LAYOUT.stackZ); g.add(sg);
    block(sg, [420, 820, 420], [0, 410, 0], matBase);
    for (const [px, pz] of [[-190, -190], [190, -190], [-190, 190], [190, 190]]) block(sg, [20, 500, 20], [px, 1070, pz], matAlu);
    const liftPlate = block(sg, [360, 10, 360], [0, 825, 0], matDark);
    const stack = new THREE.Mesh(new THREE.BoxGeometry(350, 1, 350), new THREE.MeshStandardMaterial({ color: 0xb87250, roughness: 0.5, metalness: 0.7 }));
    stack.position.y = 830; sg.add(stack); stacks[key] = { stack, liftPlate };
    decal(g, 160, 26, [x, 720, LAYOUT.stackZ + 211], [0, 0, 0], label, { bg: '#122d3c', color: '#9fd8ff', center: true });
    // 上下料：z 向橫移＋升降＋真空吸盤架
    for (const dx of [-230, 230]) block(g, [40, 1500 - 820, 40], [x + dx, (1500 + 820) / 2, LAYOUT.stackZ + 230], matFrame);
    ko(block(g, [40, 40, LAYOUT.stackZ + 300], [x - 230, 1500, (LAYOUT.stackZ - 60) / 2], matFrame), label + '橫樑');
    ko(block(g, [40, 40, LAYOUT.stackZ + 300], [x + 230, 1500, (LAYOUT.stackZ - 60) / 2], matFrame), label + '橫樑');
    const car = new THREE.Group(); g.add(car); car.position.x = x;
    block(car, [500, 40, 80], [0, 1500, 0], matAlu);
    const zAxis = new THREE.Group(); car.add(zAxis);
    block(zAxis, [60, 300, 60], [0, 150, 0], matDark);
    const frame = new THREE.Group(); zAxis.add(frame);
    block(frame, [330, 12, 20], [0, 6, 0], matAlu); block(frame, [20, 12, 330], [0, 6, 0], matAlu);
    for (const cx of [-140, 0, 140]) for (const cz of [-140, 0, 140]) cylinder(frame, 12, 10, [cx, -2, cz], matDark);
    loaders[key] = { car, zAxis };
    const feed=carrier(g,key+' / horizontal carrier',{origin:[x+280,1540,0],axis:[0,0,1],fixed:280,min:0,max:LAYOUT.stackZ,radius:40,width:28});
    const vertical=carrier(car,key+' / lift carrier',{origin:[65,1500,60],axis:[0,1,0],rise:[1,0,0],min:-410,max:0,radius:35,width:24});
    cable(car,key+' / axis junction',[[280,1620,0],[290,1660,0],[65,1640,60],[65,1500,60]],{radius:4,color:CABLE.sleeve,backing:{offset:[0,0,18],feet:[[0,[240,1520,0]],[3,[65,1500,40]]]}});
    cable(zAxis,key+' / vacuum frame feed',[[135,280,60],[140,245,60],[110,230,60],[33.5,230,0]],{radius:3,color:CABLE.air});
    for(const z of [300,560])support(g,key+' / carrier rail support',[x+250,1500,z],[x+280,1529,z],6);
    support(car,key+' / lift carrier fixed mount',[54,1500,40],[54,1500,60],6);
    support(zAxis,key+' / lift moving anchor',[30,280,0],[135,280,60],5);
    routingUpdates.push(()=>{feed.set(car.position.z);vertical.set(zAxis.position.y+280-1500);});
  }

  // ---- S1／S3 相機龍門（XY） ----
  const scanners = {};
  for (const [key, i] of [['S1', 1], ['S3', 3]]) {
    const x0 = ST[i];
    // Cantilever the inner end; its posts must stay outside S2's full-width moving beams.
    for (const dx of (key==='S1'?[-250,90]:[-90,250])) { ko(block(g,[40,600,40],[x0+dx,1120,-260],matFrame),key+'立柱');ko(block(g,[40,600,40],[x0+dx,1120,260],matFrame),key+'立柱');block(g,[30,30,560],[x0+dx,1420,0],matAlu); }
    const beam = new THREE.Group(); g.add(beam);
    block(beam, [540, 40, 50], [x0, 1450, 0], matAlu);
    const car = new THREE.Group(); beam.add(car);
    block(car, [70, 90, 70], [0, 1410, 0], matDark);
    block(car,[20,140,20],[0,1300,0],matAlu);
    const cam = camera(car,[0,1150,0],'down',{fov:2*Math.atan(8.8/2/23.5)*180/Math.PI,ringR:45}); // WD 約 198 mm，保留約 111 × 74 mm 視野
    decal(g,150,24,[x0,1525,0],[0,0,0],key==='S1'?'S1 基板視覺定位':'S3 放置後檢查',{bg:'#122d3c',color:'#9fd8ff',center:true});
    scanners[key] = { beam, car, cam, x0 };
    const scanX=carrier(beam,key+' / camera X carrier',{origin:[x0,1488,0],min:-180,max:180,radius:35,width:24,pitch:14});
    const scanZ=carrier(g,key+' / camera Z carrier',{origin:[x0+(key==='S1'?-290:290),1600,0],axis:[0,0,1],min:-180,max:180,radius:35,width:24,pitch:14});
    const out=key==='S1'?-1:1;
    cable(car,key+' / camera vertical lead',[[0,1558,0],[0,1575,-55],[0,1500,-60],[0,1400,-60],[0,1275,-42]],{radius:3,color:CABLE.signal,clips:4,backing:{offset:[out*18,0,0],feet:[[2,[out*18,1455,-35]],[4,[out*10,1275,-10]]]}});
    for(const dx of [-120,160])support(beam,key+' / carrier standoff',[x0+dx,1470,0],[x0+dx,1477,0]);
    cable(beam,key+' / axis junction',[[x0+(key==='S1'?-290:290),1670,0],[x0,1685,0],[x0,1488,0]],{radius:3,color:CABLE.signal,backing:{offset:[0,0,18],feet:[[0,[x0+(key==='S1'?-260:260),1470,0]],[2,[x0,1470,0]]]}});
    for(const z of [40,190]){support(g,key+' / fixed scan guide foot',[x0+out*265,1420,z],[x0+out*290,1420,z],6);support(g,key+' / fixed scan guide mount',[x0+out*290,1420,z],[x0+out*290,1589,z],6);}
    routingUpdates.push(()=>{scanX.set(car.position.x-x0);scanZ.set(beam.position.z);});
  }

  // ---- S2 雙龍門放置 ----
  for (const s of [-1, 1]) {
    for (const z of [-470, 470]) ko(block(g, [70, G.beamY - 840, 70], [s * G.railX, (G.beamY + 840) / 2 - 40, z], matFrame), 'S2 立柱');
    ko(block(g, [70, 60, 1010], [s * G.railX, G.beamY - 20, 0], matAlu), 'S2 Y 軌');
  }
  const heads = {};
  for (const H of ['A', 'B']) {
    const side = H === 'A' ? 1 : -1;
    const beam = new THREE.Group(); g.add(beam);
    block(beam,[2*G.railX+70,80,G.beamDepth],[0,G.beamY+50,0],H==='A'?matBlue:matAlu).name='moving-gantry-beam';
    decal(beam, 160, 30, [0, G.beamY + 40, side * (G.beamDepth / 2 + 1)], [0, side < 0 ? Math.PI : 0, 0], `龍門 ${H}`, { bg: '#102635', color: '#65d7b8', center: true });
    const head = new THREE.Group(); beam.add(head);
    const bodyZ=-side*(G.beamDepth/2+10),bracketZ=-side*(G.overhang+32)/2;
    const guide=perforated(head,[120,180,60],[0,G.beamY-50,bodyZ],G.nozzleDX.map(x=>[x,-side*G.overhang-bodyZ,6]),matDark);guide.name='spindle-guide';
    const bracket=perforated(head,[110,40,G.overhang-8],[0,G.beamY-160,bracketZ],G.nozzleDX.map(x=>[x,-side*G.overhang-bracketZ,10.3]),matAlu);bracket.name='spindle-bracket';
    // Side mount keeps both lenses out of the shared corridor between the heads.
    const camZ=-side*(G.overhang-G.downCamOut);
    block(head,[70,12,34],[side*77.5,1120.5,camZ],matAlu).name='camera-side-mount';
    const downCam = camera(head, [side*G.downCamDX,1090,camZ], 'down', { fov: 22, ringR: 16, leadSide:side });
    const nozzles = G.nozzleDX.map(dx => {
      const n = new THREE.Group(); n.position.set(dx, 0, -side * G.overhang); head.add(n);
      const spindle = new THREE.Group(); n.add(spindle);
      cylinder(spindle, 5, 144, [0, 78, 0], matAlu, 'y', 32); // 主軸從 y=6 起，讓細吸嘴露出
      const tip = new THREE.Mesh(new THREE.CylinderGeometry(PRODUCT.nozzleR, PRODUCT.nozzleR, 6, 40, 1, true), matDark);
      tip.position.y = 3; tip.castShadow = true; spindle.add(tip);
      annulus(spindle, PRODUCT.nozzleR, PRODUCT.nozzleR * .43, 0, matDark);
      for (const y of [7, 12, 95]) cylinder(spindle, 5.5, 2, [0, y, 0], matDark, 'y', 32);
      block(spindle, [14, 30, 14], [0, 120, 0], matDark);                // θ 馬達
      const coin = createCoin(); coin.position.y = -PRODUCT.coin.t; coin.visible = false; spindle.add(coin);
      return { n, spindle, coin };
    });
    heads[H] = { beam, head, nozzles, downCam, side };
    // Carriers sit above the fixed feeder camera bridges, on the outside of each beam.
    const routeX=carrier(beam,H+' / gantry X carrier',{origin:[0,1620,side*80],min:-430,max:430,radius:38,width:26,pitch:18});
    const routeZ=carrier(g,H+' / gantry Y carrier',{origin:[side*585,1680,0],axis:[0,0,1],min:-510,max:510,radius:40,width:24,pitch:18});
    cable(beam,H+' / beam feed',[[side*585,1760,0],[side*585,1800,side*80],[0,1790,side*80],[0,1620,side*80]],{radius:4.5,color:CABLE.sleeve,clips:5,backing:{offset:[0,0,side*20],feet:[[0,[side*180,1740,side*20]],[3,[0,1340,side*50]]],radius:8}});
    support(beam,H+' / feed mast',[side*180,1340,side*20],[side*180,1740,side*20],8);
    cable(head,H+' / moving head service',[[0,1696,side*80],[70*side,1630,side*82],[80*side,1400,side*82],[73*side,1290,side*82],[73*side,1258,side*82]],{radius:4,color:CABLE.sleeve,clips:4,backing:{offset:[18*side,0,0],feet:[[2,[side*98,1200,side*82]],[4,[side*84,1252,side*82]]]}});
    support(head,H+' / head rail foot',[side*60,1200,bodyZ],[side*98,1200,bodyZ],6);
    support(head,H+' / head rail outrigger',[side*98,1200,bodyZ],[side*98,1200,side*82],6);
    cable(head,H+' / camera branch',[[86.5*side,1240,side*82],[145*side,1250,side*70],[145*side,1240,camZ],[side*(G.downCamDX+46),1215,camZ]],{radius:2.2,color:CABLE.signal});
    // Four spindle feeds continue inside the bored head from this manifold.
    // Do not leave unsupported tube ends above the moving spindles.
    block(head,[22,28,30],[side*73,1240,side*82],matBlue).name='head-service-manifold';
    for(const x of [-180,180])support(beam,H+' / overhead carrier bracket',[x,1340,side*50],[x,1609,side*80],7);
    for(const z of [380,440])support(g,H+' / outer carrier support',[side*585,840,z],[side*585,1669,z],14);
    routingUpdates.push(()=>{routeX.set(head.position.x);routeZ.set(beam.position.z);});
  }
  // 柔性供料盤＋供料相機、仰視相機、拋料盒
  const feeders = {}, upCams = {};
  for (const H of ['A', 'B']) {
    const f = LAYOUT.feeder[H], u = LAYOUT.upCam[H];
    const fg = new THREE.Group(); fg.position.set(f.x, 0, f.z); g.add(fg);
    block(fg, [LAYOUT.feeder.w + 40, LAYOUT.feeder.top - 845, LAYOUT.feeder.d + 40], [0, (LAYOUT.feeder.top + 845) / 2 - 5, 0], matDark);
    const plate = block(fg, [LAYOUT.feeder.w, 4, LAYOUT.feeder.d], [0, LAYOUT.feeder.top - 2, 0], matFeeder);
    block(fg, [80, 60, 60], [LAYOUT.feeder.w / 2 + 60, LAYOUT.feeder.top + 10, 0], matAlu);    // 料斗
    decal(g, 140, 22, [f.x, LAYOUT.feeder.top - 60, f.z + (H === 'A' ? 76 : -76)], [0, H === 'A' ? 0 : Math.PI, 0], `柔性供料 ${H}`, { bg: '#122d3c', color: '#9fd8ff', center: true });
    // The former 1220 mm lens sat inside the moving head. Mount above its swept volume.
    const postX=H==='A'?-620:620,camY=1460,mountY=1555;
    ko(block(g,[30,mountY-850,30],[postX,(mountY+850)/2,f.z],matFrame),'供料相機支架 '+H);
    ko(block(g,[Math.abs(postX-f.x)+30,24,40],[(postX+f.x)/2,mountY,f.z],matFrame),'供料相機懸臂 '+H);
    const fcam = camera(g,[f.x,camY,f.z],'down',{fov:2*Math.atan(8.8/2/32)*180/Math.PI,ringR:40});
    cable(g,'FEED '+H+' / fixed camera to cabinet',[[f.x,camY+125,f.z-42],[postX,camY+125,f.z-42],[postX,870,f.z-42],[postX,784,f.z-42]],{radius:2.4,color:CABLE.signal,clips:7});
    const coins = Array.from({ length: 40 }, () => { const c = createCoin(); c.visible = false; g.add(c); return c; });
    const backs = Array.from({ length: 40 }, () => { const c = createCoin(true); c.visible = false; g.add(c); return c; });
    feeders[H] = { group: fg, plate, cam: fcam, coins, backs };
    // Body bottom = lens datum - 60 - 47/2. Seat it on the cabinet deck,
    // inside the actual granite opening, instead of embedding it in granite.
    const camBottom=LAYOUT.upCam.lensY-83.5;
    block(g,[50,camBottom-780,50],[u.x,(camBottom+780)/2,u.z],matDark).name='up-camera-support';
    upCams[H] = camera(g, [u.x, LAYOUT.upCam.lensY, u.z], 'up', { fov: 2 * Math.atan(8.8 / 2 / 35) * 180 / Math.PI, ringR: 30, power: 25 });
    block(g, [60, 40, 60], [u.x + (H === 'A' ? 90 : -90), 900, u.z], matYellow);     // 拋料盒
  }

  // ---- 外罩、三色燈、HMI ----
  const occ = new THREE.Group(); occ.name = 'occluders'; g.add(occ);
  // Rear gantry beam extends beyond its nozzle row; keep enclosure posts and
  // the rear panel outside the full beam stroke, not just the working area.
  const EX = 1760, Z0 = -680, Z1 = 840, H1 = 2000;
  for (const x of [-EX, -350, 350, EX]) for (const z of [Z0, Z1]) block(occ, [40, H1 - 780, 40], [x, (H1 + 780) / 2, z], matFrame);
  for (const z of [Z0, Z1]) block(occ, [2 * EX, 40, 40], [0, H1, z], matFrame);
  block(occ, [2 * EX, H1 - 780, 2], [0, (H1 + 780) / 2, Z0], matPC);
  block(occ, [2 * EX, H1 - 1100, 2], [0, (H1 + 1100) / 2, Z1], matPC);
  const tower = new THREE.Group(); tower.position.set(EX - 100, H1 + 50, Z0 + 60); g.add(tower);
  const lamps = {}; [['red', 0xff3b3b, 110], ['yellow', 0xffb020, 75], ['green', 0x3dd68c, 40]].forEach(([k, c, y]) => { const m = new THREE.Mesh(new THREE.CylinderGeometry(22, 22, 34, 20), new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.08 })); m.position.y = y; tower.add(m); lamps[k] = m; });
  block(g, [260, 170, 16], [0, 1250, Z1 + 12], new THREE.MeshStandardMaterial({ color: 0x0c1a2b, emissive: 0x1f4f8f, emissiveIntensity: 0.55 }));
  decal(g, 240, 150, [0, 1250, Z1 + 21], [0, 0, 0], ['散熱銅片植入機', `${PRODUCT.short} · ${HOLES.length} 顆／片`, 'SIMULATION'], { bg: '#102635', color: '#65d7b8' });

  cableTray(g,'BASE / segregated distribution',[-1650,740,-530],[1650,740,-530]);
  // Remove unused risers ending in mid-air. Distribution terminates in the
  // cabinet; axis feeds enter through the fixed carrier connectors.
  for(const x of [-1500,-750,0,750,1500])support(g,'BASE / trough wall bracket',[x,731,-500],[x,731,-530],5);

  return {
    updateRouting(){for(const update of routingUpdates)update();},
    group: g, occluders: occ, keepout, lifts, stops, beltMarks, stacks, loaders, scanners, heads, feeders, upCams,
    tower: { set(k) { for (const n in lamps) lamps[n].material.emissiveIntensity = n === k ? 1.6 : 0.08; } },
  };
}
export const BOARD_SURFACE = BOARD_TOP;
