import {robotController,controllerLeads} from '@core/electrical/electrical-components.js';
// 線體：地面、載具式輸送線（5 站）、載具（定位銷＋側夾＋堆疊柱）、進／出料升降堆料架、S1 頂視相機、S3 翻轉夾持治具、圍籬、三色燈
import * as THREE from 'three';
import {cabinetShell,controlPanel,entryGland,panelFeed} from '@core/electrical/electrical-cabinet.js';
import { cable, cableTray, carrier, support, CABLE } from '@core/electrical/cable-routing.js';
import { NB } from './notebook.js';
import { block, cylinder, decal, tube } from '@core/geom/primitives.js';

export const LAYOUT = {
  // S3 在 x=1150：S2 右側護蓋作業時手腕在 x≤約 680，翻轉治具左端（x≥695）不在手腕範圍內
  stationX: [-2000, -1000, 0, 1150, 2000],   // S0 進料（堆料架）、S1 閉合外觀、S2 側邊護蓋、S3 翻面檢測、S4 出料（堆料架）
  stackerInX: -2000, stackerOutX: 2000,
  conveyorTop: 760,
  palletH: 40,
  padH: 14,
  palletPitch: 110,                          // 堆疊間距（載具 40 + 機台 36 + 淨空）
  railZ: -560,
  flipLift: 210,
  cradlePark: 100,                           // 翻轉治具待命高度：輸送期間停在上方 100 mm，讓出載具與筆電通道
  footOffset: 3.25,
  // S1 頂視取像頭：前側懸臂上的 Z 向滑軌；移入時穹頂光底緣在產品上方 80 mm，退出後讓手臂巡拍四側
  // 立柱在 z=1050（1010～1090）：取像頭退到 780 時滑座（≤850）與穹頂光外緣（≤990）都在立柱前方
  s1PostZ: 1050, s1HeadOut: 780, s1DomeGap: 80, s1DomeR: 200, s1BeamY: 2000,
};

const matFloor = new THREE.MeshStandardMaterial({ color: 0x1b2027, roughness: 0.95 });
const matFrame = new THREE.MeshStandardMaterial({ color: 0x6b7480, roughness: 0.5, metalness: 0.6 });
const matAlu   = new THREE.MeshStandardMaterial({ color: 0xb9c0c8, roughness: 0.35, metalness: 0.8 });
const matBelt  = new THREE.MeshStandardMaterial({ color: 0x23272c, roughness: 0.9 });
const matPallet= new THREE.MeshStandardMaterial({ color: 0x9aa4ae, roughness: 0.4, metalness: 0.7 });
const matDark  = new THREE.MeshStandardMaterial({ color: 0x1e2226, roughness: 0.5, metalness: 0.4 });
const matCam   = new THREE.MeshStandardMaterial({ color: 0x2c3138, roughness: 0.4, metalness: 0.5 });
const matDome  = new THREE.MeshStandardMaterial({ color: 0xf2f2f2, roughness: 0.9, side: THREE.DoubleSide });
const matYellow= new THREE.MeshStandardMaterial({ color: 0xf2b21b, roughness: 0.6 });
const matPin   = new THREE.MeshStandardMaterial({ color: 0xd0d5da, roughness: 0.3, metalness: 0.9 });
const matPU    = new THREE.MeshStandardMaterial({ color: 0xd9a441, roughness: 0.9 });
const matBlue  = new THREE.MeshStandardMaterial({ color: 0x2f5f9e, roughness: 0.5, metalness: 0.4 });

function box(w, h, d, mat) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.castShadow = true; m.receiveShadow = true; return m; }
function cyl(r, h, mat, seg = 24) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, seg), mat); m.castShadow = true; m.receiveShadow = true; return m; }

/** 載具：鋁框鏤空、PU 承載墊、定位銷×3、側夾×2、四角堆疊柱（可疊放入堆料架） */
export function createPallet(withClamps = true) {
  const pallet = new THREE.Group(); pallet.name = 'pallet';
  const pw = 440, pd = 330, ph = LAYOUT.palletH;
  for (const [w, h, d, x, z] of [[pw, ph, 55, 0, pd / 2 - 27], [pw, ph, 55, 0, -pd / 2 + 27], [70, ph, pd, pw / 2 - 35, 0], [70, ph, pd, -pw / 2 + 35, 0]]) {
    const m = box(w, h, d, matPallet); m.position.set(x, ph / 2, z); pallet.add(m);
  }
  for (const [x, z] of [[-150, -95], [150, -95], [-150, 95], [150, 95]]) { const p = box(40, LAYOUT.padH, 40, matPU); p.position.set(x, ph + LAYOUT.padH/2, z); pallet.add(p); }
  for (const [x, z] of [[-170, 127], [170, 127], [-170, -127]]) { const p = cyl(4, 30, matPin, 12);p.name='pallet-guide-pin'; p.position.set(x, ph + 15, z); pallet.add(p); }
  // 堆疊柱（四角，高度 = 堆疊間距）；內縮到 z=±125，讓出堆料架托叉（z=±140～164）的通道，推出／拉入時柱子不穿過托叉
  for (const [x, z] of [[-pw / 2 + 20, -pd / 2 + 40], [pw / 2 - 20, -pd / 2 + 40], [-pw / 2 + 20, pd / 2 - 40], [pw / 2 - 20, pd / 2 - 40]]) {
    const post = box(24, LAYOUT.palletPitch - ph, 24, matAlu); post.position.set(x, ph + (LAYOUT.palletPitch - ph) / 2, z); pallet.add(post);
  }
  const clamps = [];
  if (withClamps) for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const cg = new THREE.Group(); cg.position.set(sx * 207.5, ph + 18 + LAYOUT.padH + LAYOUT.footOffset, sz * 82); pallet.add(cg);
    // 氣缸本體放低（離載具框 2 mm、頂面低於護蓋下緣），以連接片帶動推桿：手臂在側門作業時工具不碰氣缸
    const cylBody = box(32, 12, 20, matDark); cylBody.position.set(sx * 9, -27, 0); cg.add(cylBody);
    const rod = new THREE.Group(); cg.add(rod);
    const rodM = cyl(4, 40, matPin, 10); rodM.rotation.z = Math.PI / 2; rodM.position.x = -sx * 30; rod.add(rodM);
    block(rod, [6, 26, 8], [-sx * 12, -14, 0], matDark);
    const pad = box(8, 18, 8, matPU); pad.name = 'pallet clamp pad'; pad.position.x = -sx * 52; rod.add(pad);
    clamps.push({ rod, sx });
  }
  decal(pallet,110,22,[0,ph/2,pd/2+1.2],[0,0,0],'QC • P001',{bg:'#1b3139',center:true});
  for (const sx of [-1,1]) for (const sz of [-1,1]) cylinder(pallet,3,1,[sx*200,ph+1,sz*125],matDark);
  return { group: pallet, setClamp(v) { for (const c of clamps) c.rod.position.x = -c.sx * (v * 25 - 25); } };
}

/** 升降式堆料架：立柱框架、升降平台（伺服＋皮帶）、推／拉載具的氣缸 */
function createStacker(x, dir) {
  const g = new THREE.Group(); g.position.set(x, 0, 0);
  const top = LAYOUT.conveyorTop;
  const W = 560, D = 460, H = 1750;
  for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) { const p = box(40, H, 40, matFrame); p.position.set(sx * W / 2, H / 2, sz * D / 2); g.add(p); }
  for (const y of [40, H - 20]) for (const sz of [-1, 1]) { const r = box(W, 30, 30, matFrame); r.position.set(0, y, sz * D / 2); g.add(r); }
  // 升降立柱（伺服）＋平台
  const column = box(80, H, 60, matDark); column.position.set(0, H / 2, -D / 2 - 40); g.add(column);
  const lift = new THREE.Group(); g.add(lift);
  // 平台 430×270：z 方向窄於托叉（z=±140～164）、x 方向避開推／拉料鞋，升降時不穿過托叉與料鞋
  const platform = box(430, 20, 270, matAlu); platform.position.y = 10; lift.add(platform);
  // 平台托架在平台下方接到後側升降立柱，上升到托叉高度時不碰托叉
  const bracket = box(120, 59.2, 110, matDark); bracket.position.set(0, -30.4, -185); lift.add(bracket);
  // 推料氣缸（在輸送線高度，把最底層載具推出／拉入）
  const pusher = new THREE.Group(); pusher.position.set(-dir * (W / 2 + 60), top + 30, 0); g.add(pusher);
  const pBody = box(70, 40, 60, matDark); pusher.add(pBody);
  const rod = new THREE.Group(); pusher.add(rod);
  const rodM = cyl(6, 200, matPin, 12); rodM.rotation.z = Math.PI / 2; rodM.position.x = dir * 135; rod.add(rodM);
  const plate = box(10, 40, 120, matPU); plate.position.x = dir * 240; rod.add(plate);
  // 操作面板
  const hmi = box(160, 110, 14, new THREE.MeshStandardMaterial({ color: 0x0c1a2b, emissive: 0x1f4f8f, emissiveIntensity: 0.6 })); hmi.position.set(0, 1500, D / 2 + 10); g.add(hmi);
  const forks=[];
  for(const sz of [-1,1]){
    // 托叉 24 mm 寬、z=±140～164：承托載具前後框，與堆疊柱（z=±113～137）錯開
    const fork=block(g,[440,12,24],[0,top+6+LAYOUT.palletPitch-6,sz*152],matBlue);forks.push({fork,sz});
    for(const sx of [-1,1])block(g,[12,1400,12],[sx*235,850,sz*218],matPin);
  }
  cylinder(g,13,1450,[0,850,-D/2-78],matPin);
  const motor=box(100,110,90,matBlue);motor.position.set(0,150,-D/2-78);g.add(motor);
  decal(g,140,70,[0,1500,D/2+18],[0,0,0],[dir===1?'INFEED':'OUTFEED','SERVO LIFT','6 PALLETS'],{bg:'#122d3c',center:true});
  return { group:g,lift,rod,dir,forks,setForks(v){for(const {fork,sz} of forks)fork.position.z=sz*(152+(1-v)*85);},setPush(mm){
    // Pusher shoe remains on the pallet edge; rod grows from the cylinder head.
    plate.position.x=dir*(115+mm);rodM.position.x=dir*(35+(80+mm)/2);rodM.scale.y=(80+mm)/200;
  }};
}

/** 翻轉夾持治具（S3）：龍門立柱、升降滑台、旋轉軸（±X 兩端夾臂，PU 壓塊夾機台橡膠護角）。龍門在輸送線前側，後側留給手臂底部取像。 */
function createFlipCradle(x) {
  const g = new THREE.Group(); g.position.set(x, 0, 0);
  const top = LAYOUT.conveyorTop;
  const keepout = [];
  // 龍門立柱 z=225～285：讓出輸送線前側線槽（z=291～349）
  for (const sx of [-1, 1]) { const post = box(60, 1800, 60, matFrame); post.position.set(sx * 380, 900, 255); g.add(post); post.name = sx < 0 ? 'S3 左立柱' : 'S3 右立柱'; keepout.push(post); block(g,[18,900,15],[sx*380,1050,216],matPin); }
  const beam = box(840, 60, 60, matFrame); beam.position.set(0, 1800, 255); g.add(beam); beam.name = 'S3 橫樑'; keepout.push(beam);
  // 升降滑台（兩側），帶動旋轉軸
  const lift = new THREE.Group(); g.add(lift);
  for (const sx of [-1, 1]) {
    const slide = box(90, 120, 70, matDark); slide.position.set(sx * 380, 0, 225); lift.add(slide);
    block(lift,[60,60,225],[sx*380,0,112.5],matAlu);
    const motor = cyl(38, 90, matBlue); motor.rotation.z = Math.PI / 2; motor.position.set(sx * 410, 0, 0); lift.add(motor);
  }
  // 旋轉框：兩支夾臂沿 X 伸向機台兩端，夾墊在 z=±85（避開側邊護蓋）
  const rot = new THREE.Group(); lift.add(rot);
  const arms = [];
  for (const sx of [-1, 1]) {
    const shaft = cyl(18, 180, matAlu); shaft.rotation.z = Math.PI / 2; shaft.position.set(sx * 300, 0, 0); rot.add(shaft);
    const arm = new THREE.Group(); arm.position.set(sx * 235, 0, 0); rot.add(arm);
    // 夾臂橫樑外移 46 mm（夾緊時 x≥235.5），避開載具四角側夾的氣缸本體（x≤232.5、z=±72～92）；指桿在 z=±95～103
    const yoke = box(30, 40, 240, matDark); yoke.position.x = sx * 46; arm.add(yoke);
    for (const sz of [-1, 1]) { const finger = box(85, 22, 8, matDark); finger.position.set(-sx * 2.5, 0, sz * 99); arm.add(finger); const pad = box(10, 20.6, 8.6, matPU); pad.name = 'cradle clamp pad'; pad.position.set(-sx * 48, 0, sz * 98); arm.add(pad); }
    arms.push({ arm, sx });
  }
  return { group: g, lift, rot, arms, keepout, setClamp(v) { for (const a of arms) a.arm.position.x = a.sx * (235 - v * 30.5); } };
}

export function createCell(scene) {
  const g = new THREE.Group(); g.name = 'cell'; scene.add(g);
  const { stationX, conveyorTop: top, railZ } = LAYOUT;

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(11000, 7000), matFloor); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; g.add(floor);
  const grid = new THREE.GridHelper(11000, 55, 0x2c3540, 0x222a33); grid.position.y = 0.5; g.add(grid);
  for (const z of [1150, -1150]) { const l = box(6000, 1, 40, matYellow); l.position.set(0, 1, z); g.add(l); }

  // ---- 載具式輸送線（S0 堆料架出口 → S4 堆料架入口）----
  const x0 = stationX[0] + 300, x1 = stationX[4] - 300, len = x1 - x0, cx = (x0 + x1) / 2;
  for (const z of [-170, 170]) {
    const beam = box(len, 80, 60, matAlu); beam.position.set(cx, top - 40, z); g.add(beam);
    const belt = box(len - 20, 6, 30, matBelt); belt.position.set(cx, top + 3, z); g.add(belt);
    for (let x = x0 + 100; x <= x1 - 100; x += 600) { const leg = box(50, top - 80, 50, matFrame); leg.name='conveyor leg'; leg.position.set(x, (top - 80) / 2, z); g.add(leg); const foot = box(120, 12, 90, matDark); foot.name='conveyor foot'; foot.position.set(x, 6, z); g.add(foot); }
  }
  for (let x = x0 + 100; x <= x1 - 100; x += 600) { const cross = box(40, 40, 400, matFrame); cross.position.set(x, top - 100, 0); g.add(cross); }
  const stops=[];
  for (const x of [-1450,...stationX.slice(1,4),1450]) {
    const base=box(45,70,70,matDark);base.position.set(x+225,top-35,0);g.add(base);
    const st=box(10,24,68,matYellow);st.position.set(x+225,top-14,0);g.add(st);
    const sensor=box(16,18,24,matBlue);sensor.position.set(x,top+12,210);g.add(sensor);
    const led=cylinder(g,3,2,[x,top+23,210],new THREE.MeshStandardMaterial({color:0x1b4f3d,emissive:0x32d49b,emissiveIntensity:0}));
    stops.push({x,st,led});
  }
  for(const z of [-170,170])for(const x of [x0+30,x1-30]){const r=cyl(30,38,matDark);r.rotation.x=Math.PI/2;r.position.set(x,top-28,z);g.add(r);}
  for(let x=x0+30;x<x1;x+=120)for(const z of [-201,201])block(g,[42,3,1],[x,top-30,z],matDark);
  const drive=box(140,120,100,matBlue);drive.position.set(x1-20,top-90,265);   // 驅動馬達放在輸送線末端外側，避開 S3 右立柱g.add(drive);
  const beltMarks=new THREE.Group();g.add(beltMarks);
  for(let x=x0+30;x<x1-100;x+=110)for(const z of [-170,170])block(beltMarks,[3,1.4,28],[x,top+6,z],matAlu);

  // ---- 主載具（隨機台移動）----
  const pallet = createPallet(true);
  pallet.group.position.set(stationX[0], top + 6, 0); g.add(pallet.group);
  const palletApi = { group: pallet.group, setClamp: pallet.setClamp, topY: top + 6 + LAYOUT.palletH + LAYOUT.padH };

  // ---- 進／出料升降堆料架 ----
  const stackerIn = createStacker(LAYOUT.stackerInX, +1);
  const stackerOut = createStacker(LAYOUT.stackerOutX, -1);
  g.add(stackerIn.group, stackerOut.group);

  // ---- S0：底視 SN 條碼讀取器（穿過載具鏤空）----
  const snReader = new THREE.Group(); snReader.position.set(stationX[0] + 300 + 250, 420, 0); g.add(snReader);
  const srBody = box(70, 60, 70, matCam); snReader.add(srBody);
  const srLens = cyl(18, 40, matDark); srLens.position.y = 50; snReader.add(srLens);
  const srStand = box(60, 400, 60, matFrame); srStand.position.y = -230; snReader.add(srStand);
  const snFlash = new THREE.SpotLight(0xff3030, 0, 700, 0.5, 0.6, 1); snFlash.position.set(0, 60, 0); snFlash.target.position.set(0, 400, 0); snReader.add(snFlash, snFlash.target);

  // ---- S1：前側懸臂＋頂視取像頭（相機＋穹頂光同一組，沿 Z 滑軌移入／退出）----
  // 舊版門型架的後立柱落在手臂滑軌通道上，改為單邊懸臂；取像頭退到前側，手臂巡拍時不干涉。
  const s1x = stationX[1], productTop = top + 6 + LAYOUT.palletH + LAYOUT.padH + LAYOUT.footOffset + NB.H;
  const domeRim = productTop + LAYOUT.s1DomeGap, beamY = LAYOUT.s1BeamY, keepout = [];
  const s1 = new THREE.Group(); s1.position.set(s1x, 0, 0); g.add(s1);
  const s1Post = box(80, beamY + 60, 80, matFrame); s1Post.position.set(0, (beamY + 60) / 2, LAYOUT.s1PostZ); s1.add(s1Post); s1Post.name = 'S1 懸臂立柱'; keepout.push(s1Post);
  const s1Beam = box(80, 60, LAYOUT.s1PostZ + 140, matFrame); s1Beam.position.set(0, beamY + 30, (LAYOUT.s1PostZ - 100) / 2); s1.add(s1Beam); s1Beam.name = 'S1 懸臂橫樑'; keepout.push(s1Beam);
  block(s1, [30, 12, LAYOUT.s1PostZ + 100], [0, beamY - 6, (LAYOUT.s1PostZ - 100) / 2], matPin);
  const head = new THREE.Group(); s1.add(head);
  const headCar = box(120, 50, 140, matDark); headCar.position.y = beamY - 37; head.add(headCar); headCar.name = 'S1 取像頭滑座'; keepout.push(headCar);
  const hanger = box(40, beamY - 62 - (domeRim + 405), 40, matFrame); hanger.position.y = (beamY - 62 + domeRim + 405) / 2; head.add(hanger); hanger.name = 'S1 取像頭吊臂'; keepout.push(hanger);
  const topCam = new THREE.Group(); topCam.position.y = domeRim + 360; head.add(topCam);
  const camBody = box(80, 90, 80, matCam); topCam.add(camBody); camBody.name = 'S1 頂視相機'; keepout.push(camBody);
  const tcLens = cyl(28, 70, matDark); tcLens.position.y = -80; topCam.add(tcLens); tcLens.name = 'S1 頂視鏡頭'; keepout.push(tcLens);
  const dome = new THREE.Mesh(new THREE.SphereGeometry(LAYOUT.s1DomeR, 32, 16, 0, Math.PI * 2, .16, Math.PI / 2 - .16), matDome); dome.position.y = domeRim; dome.castShadow = true; head.add(dome); dome.name = 'S1 穹頂光'; keepout.push(dome);
  const domeRing = new THREE.Mesh(new THREE.TorusGeometry(LAYOUT.s1DomeR + 2, 8, 8, 48), matDark); domeRing.rotation.x = Math.PI / 2; domeRing.position.y = domeRim; head.add(domeRing);
  const topFlash = new THREE.SpotLight(0xffffff, 0, 1200, 0.5, 0.6, 1); topFlash.position.set(0, domeRim + 250, 0); topFlash.target.position.set(0, productTop - 100, 0); head.add(topFlash, topFlash.target);
  const cameraHarness=carrier(s1,'S1 / retracting camera carrier',{origin:[85,beamY+90,0],axis:[0,0,1],fixed:390,min:0,max:780,radius:55,width:34,pitch:20});
  for(const z of [50,420,750])support(s1,'S1 / fixed guide mount',[40,beamY+45,z],[85,beamY+79,z],6);
  cable(head,'S1 / moving camera drop',[[85,beamY+200,0],[90,beamY+110,20],[65,beamY-30,30],[55,domeRim+410,30],[55,domeRim+365,0],[43.5,domeRim+365,0]],{radius:3,color:CABLE.signal,clips:5,backing:{offset:[18,0,0],feet:[[0,[60,beamY-12,0]],[3,[20,domeRim+430,0]]]}});
  cable(head,'S1 / dome-light lead',[[43.5,domeRim+365,0],[90,domeRim+340,0],[220,domeRim+240,0],[225,domeRim+60,0],[211,domeRim+4,0]],{radius:2.5,color:CABLE.power,clips:3});
  const setHead = v => { head.position.z = (1 - v) * LAYOUT.s1HeadOut; cameraHarness.set(head.position.z); };
  setHead(0);
  // ---- S3：翻轉夾持治具 ----
  const cradle = createFlipCradle(stationX[3]);
  g.add(cradle.group);

  // ---- 三色燈、圍籬（後側與兩端）、前側光柵 ----
  const occ = new THREE.Group(); occ.name = 'occluders'; g.add(occ);   // 錄製時可隱藏的遮擋物
  const tower = new THREE.Group(); tower.position.set(stationX[4] - 450, top + 320, -300); g.add(tower);
  const towerPole = cyl(8, 300, matFrame); towerPole.position.y = -150; tower.add(towerPole);
  const towerLamps = {};
  [['red', 0xff3b3b, 90], ['yellow', 0xffb020, 50], ['green', 0x3dd68c, 10]].forEach(([k, c, y]) => {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(22, 22, 36, 20), new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.08, transparent: true, opacity: 0.85 }));
    m.position.y = y; tower.add(m); towerLamps[k] = m;
  });
  const towerApi = { set(k) { for (const n in towerLamps) towerLamps[n].material.emissiveIntensity = n === k ? 1.6 : 0.08; } };
  // 後圍籬：手臂待命／PTP 時肘部最遠到 z≈-996，圍籬放在 railZ-500，保留約 60 mm
  const backZ = railZ - 500, endX = 2700;
  for (let x = -endX; x <= endX; x += 675) { const p = box(40, 1400, 40, matFrame); p.position.set(x, 700, backZ); occ.add(p); }
  for (const y of [500, 1380]) { const r = box(endX * 2, 14, 14, y > 1000 ? matYellow : matFrame); r.position.set(0, y, backZ); occ.add(r); }
  for (const x of [-endX, endX]) {
    const post = box(40, 1400, 40, matFrame); post.position.set(x, 700, 700); occ.add(post);
    for (const y of [500, 1380]) { const r = box(14, 14, 700 - backZ, y > 1000 ? matYellow : matFrame); r.position.set(x, y, (700 + backZ) / 2); occ.add(r); }
    const lc = box(30, 900, 30, matYellow); lc.position.set(x, 450, 900); occ.add(lc);
  }
  const cab = box(600, 1800, 500, matDark); cab.position.set(-3300, 900, -300); occ.add(cab);
  const screen = box(500, 300, 20, new THREE.MeshStandardMaterial({ color: 0x0c1a2b, emissive: 0x1f4f8f, emissiveIntensity: 0.5 })); screen.position.set(-3300, 1350, -40); occ.add(screen);

  // Frame fasteners, levelling feet, pneumatic service unit and electrical panel details.
  for(let x=x0+100;x<x1;x+=600)for(const z of [-170,170]){cylinder(g,8,35,[x,25,z],matPin);cylinder(g,27,8,[x,7,z],matDark);}
  block(g,[160,100,80],[430,570,240],matAlu);
  for(const x of [380,430,480])cylinder(g,14,65,[x,490,250],matDome);
  cylinder(g,22,10,[430,590,287],matDark,'z');decal(g,28,28,[430,590,293],[0,0,0],'0.5 MPa',{center:true});
  tube(g,[[430,500,220],[430,400,190],[600,400,190],[650,720,190]],5,matBlue);
  for(let i=0;i<9;i++)block(occ,[180,3,3],[-3300,350+i*12,-48],matFrame);
  cylinder(occ,24,12,[-3120,1080,-40],matYellow,'z');cylinder(occ,15,20,[-3120,1080,-30],new THREE.MeshStandardMaterial({color:0xd53730}),'z');
  decal(occ,390,220,[-3300,1350,-28],[0,0,0],['QC CELL / AUTO','WORK ORDER : RMK12608372','VISION + FORCE CONTROL','SIMULATION'],{bg:'#102635',color:'#65d7b8'});
  const columns=[];g.traverse(m=>{const p=m.geometry?.parameters;if(m.material===matFrame&&p?.height>500&&p.width<=80&&p.depth<=80)columns.push(m);});
  for(const column of columns){
    const p=column.geometry.parameters;
    for(const side of [-1,1]){
      block(column,[3,p.height-55,.6],[side*p.width*.2,0,p.depth/2+.4],matDark);
      for(const y of [-p.height/2+25,p.height/2-25])cylinder(column,3,2,[side*p.width*.27,y,p.depth/2+1],matPin,'z',6);
    }
  }
  cableTray(g,'CELL / segregated field wiring',[-2530,400,320],[2500,400,320],{width:58});
  for(let x=x0+100;x<=x1-100;x+=600)if([LAYOUT.stationX[3]-380,LAYOUT.stationX[3]+380].every(px=>Math.abs(x-px)>60))support(g,'CELL / trough leg bracket',[x,389,195],[x,389,320],6);
  cable(g,'S1 / rear-of-post feed',[[s1x,400,335],[s1x+240,600,LAYOUT.s1PostZ+60],[s1x+240,1900,LAYOUT.s1PostZ+60],[s1x+85,2090,LAYOUT.s1PostZ-100],[s1x+85,2090,390]],{radius:6,color:CABLE.sleeve,clips:9,backing:{offset:[20,0,0],feet:[[1,[s1x+40,600,LAYOUT.s1PostZ]],[2,[s1x+40,1900,LAYOUT.s1PostZ]],[4,[s1x+40,beamY+45,390]]],radius:8}});
  // 滑軌供電：從前側線槽下到地面，沿滑軌前方地面繞過滑軌端部（x=-1460），再從後方接到拖鏈固定端；
  // 不橫越滑座行程（舊路徑斜穿滑軌，滑座經過 x≈-180 時會撞線）
  cable(g,'RAIL / fixed supply',[[0,400,300],[0,10,300],[0,10,railZ+180],[-1460,10,railZ+180],[-1460,10,railZ-290],[0,10,railZ-290],[0,30,railZ-246]],{radius:8,color:CABLE.sleeve,clips:0});
  const cabinet=cabinetShell(g,'CTRL / under-conveyor cabinet',{center:[-700,300,20],size:[460,600,440],entries:[{x:-150,z:180,hole:14},{x:150,z:180,hole:16},{x:0,z:180,hole:10}],thickness:12});
  const panel=controlPanel(g,'CTRL / drive and vision IO',{center:[-700,300,-150],width:410,height:460,backZ:-197,profile:'military'});
  const controller=robotController(g,{at:[-700,63,-145],floor:4});controllerLeads(g,controller,panel);
  const motionCabinet=cabinetShell(g,'CTRL / peripheral drive cabinet',{center:[-1300,300,20],size:[460,600,440],entries:[{x:0,z:180,hole:10}],thickness:12});
  const motionPanel=controlPanel(g,'CTRL / peripheral drives',{center:[-1300,300,-150],width:410,height:460,backZ:-197,profile:'military-motion'});
  for(const x of [-700,-1300])entryGland(g,'CTRL / inter-cabinet service '+x,{at:[x,600,200],hole:10,wire:4,thickness:12});
  panelFeed(g,'CTRL / inter-cabinet bus',[panel.ports[11],[-700,500,-100],[-700,540,200],[-700,660,200],[-700,680,250],[-1300,680,250],[-1300,660,200],[-1300,540,200],[-1300,500,-100],motionPanel.ports[0]],{radius:4});
  for(const [x,hole,wire] of [[-850,14,6],[-550,16,8]])entryGland(g,'CTRL / roof entry '+x,{at:[x,600,200],hole,wire,thickness:12});
  panelFeed(g,'CTRL / S1 to panel',[[s1x,400,335],[s1x,660,335],[-850,660,335],[-850,660,200],[-850,540,200],[-850,505,-100],panel.ports[3]],{radius:6});
  panelFeed(g,'CTRL / rail power to panel',[[0,400,300],[-140,400,320],[-140,660,320],[-550,660,200],[-550,540,200],[-550,505,-100],panel.ports[9]],{radius:8,color:CABLE.power});
  // keepout：手臂不得進入的固定結構（S1 懸臂與取像頭、S3 龍門），供驗證做碰撞檢查
  return { group:g,occluders:occ,pallet:palletApi,stackerIn,stackerOut,cradle,topFlash,snFlash,tower:towerApi,stops,setHead,keepout:[...keepout,...cradle.keepout,...cabinet.solids,...motionCabinet.solids],
    updateTransport(x,located){beltMarks.position.x=((x%110)+110)%110;for(const s of stops){const hit=Math.abs(x-s.x)<2;s.st.position.y=top-14+(hit&&located?28:0);s.led.material.emissiveIntensity=hit?1.4:0;}},
    get topCamPos(){return topCam.getWorldPosition(new THREE.Vector3());},snReaderPos:snReader.position.clone() };
}
