// 線體：地面、載具式輸送線（5 站）、載具（定位銷＋側夾＋堆疊柱）、進／出料升降堆料架、S1 頂視相機、S3 翻轉夾持治具、圍籬、三色燈
import * as THREE from 'three';
import { NB } from './notebook.js';
import { block, cylinder, decal, tube } from './detail.js';

export const LAYOUT = {
  stationX: [-2000, -1000, 0, 1000, 2000],   // S0 進料（堆料架）、S1 閉合外觀、S2 側邊護蓋、S3 翻面檢測、S4 出料（堆料架）
  stackerInX: -2000, stackerOutX: 2000,
  conveyorTop: 760,
  palletH: 40,
  padH: 14,
  palletPitch: 110,                          // 堆疊間距（載具 40 + 機台 36 + 淨空）
  railZ: -560,
  flipLift: 210,
  footOffset: 3.25,
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
  // 堆疊柱（四角，高度 = 堆疊間距）
  for (const [x, z] of [[-pw / 2 + 20, -pd / 2 + 20], [pw / 2 - 20, -pd / 2 + 20], [-pw / 2 + 20, pd / 2 - 20], [pw / 2 - 20, pd / 2 - 20]]) {
    const post = box(24, LAYOUT.palletPitch - ph, 24, matAlu); post.position.set(x, ph + (LAYOUT.palletPitch - ph) / 2, z); pallet.add(post);
  }
  const clamps = [];
  if (withClamps) for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const cg = new THREE.Group(); cg.position.set(sx * 207.5, ph + 18 + LAYOUT.padH + LAYOUT.footOffset, sz * 82); pallet.add(cg);
    const cylBody = box(26, 22, 20, matDark); cylBody.position.x = sx * 12; cg.add(cylBody);
    const rod = new THREE.Group(); cg.add(rod);
    const rodM = cyl(4, 40, matPin, 10); rodM.rotation.z = Math.PI / 2; rodM.position.x = -sx * 30; rod.add(rodM);
    const pad = box(8, 18, 8, matPU); pad.position.x = -sx * 52; rod.add(pad);
    clamps.push({ rod, sx });
  }
  decal(pallet,110,22,[0,ph/2,pd/2+.5],[0,0,0],'QC • P001',{bg:'#1b3139',center:true});
  for (const sx of [-1,1]) for (const sz of [-1,1]) cylinder(pallet,3,1,[sx*200,ph+1,sz*145],matDark);
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
  const platform = box(W - 80, 20, D - 80, matAlu); platform.position.y = 10; lift.add(platform);
  const bracket = box(120, 60, 60, matDark); bracket.position.set(0, 30, -D / 2 + 40); lift.add(bracket);
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
    const fork=block(g,[440,12,34],[0,top+6+LAYOUT.palletPitch-6,sz*147],matBlue);forks.push({fork,sz});
    for(const sx of [-1,1])block(g,[12,1400,12],[sx*235,850,sz*218],matPin);
  }
  cylinder(g,13,1450,[0,850,-D/2-78],matPin);
  const motor=box(100,110,90,matBlue);motor.position.set(0,150,-D/2-78);g.add(motor);
  decal(g,140,70,[0,1500,D/2+18],[0,0,0],[dir===1?'INFEED':'OUTFEED','SERVO LIFT','6 PALLETS'],{bg:'#122d3c',center:true});
  return { group:g,lift,rod,dir,forks,setForks(v){for(const {fork,sz} of forks)fork.position.z=sz*(147+(1-v)*85);},setPush(mm){
    // Pusher shoe remains on the pallet edge; rod grows from the cylinder head.
    plate.position.x=dir*(115+mm);rodM.position.x=dir*(35+(80+mm)/2);rodM.scale.y=(80+mm)/200;
  }};
}

/** 翻轉夾持治具（S3）：龍門立柱、升降滑台、旋轉軸（±X 兩端夾臂，PU 壓塊夾機台橡膠護角） */
function createFlipCradle(x) {
  const g = new THREE.Group(); g.position.set(x, 0, 0);
  const top = LAYOUT.conveyorTop;
  for (const sx of [-1, 1]) { const post = box(60, 1500, 60, matFrame); post.position.set(sx * 380, 750, -270); g.add(post); block(g,[18,900,15],[sx*380,1050,-231],matPin); }
  const beam = box(840, 60, 60, matFrame); beam.position.set(0, 1500, -270); g.add(beam);
  // 升降滑台（兩側），帶動旋轉軸
  const lift = new THREE.Group(); g.add(lift);
  for (const sx of [-1, 1]) {
    const slide = box(90, 120, 70, matDark); slide.position.set(sx * 380, 0, -240); lift.add(slide);
    block(lift,[60,60,240],[sx*380,0,-120],matAlu);
    const motor = cyl(38, 90, matBlue); motor.rotation.z = Math.PI / 2; motor.position.set(sx * 410, 0, 0); lift.add(motor);
  }
  // 旋轉框：兩支夾臂沿 X 伸向機台兩端，夾墊在 z=±85（避開側邊護蓋）
  const rot = new THREE.Group(); lift.add(rot);
  const arms = [];
  for (const sx of [-1, 1]) {
    const shaft = cyl(18, 180, matAlu); shaft.rotation.z = Math.PI / 2; shaft.position.set(sx * 300, 0, 0); rot.add(shaft);
    const arm = new THREE.Group(); arm.position.set(sx * 235, 0, 0); rot.add(arm);
    const yoke = box(30, 40, 240, matDark); arm.add(yoke);
    for (const sz of [-1, 1]) { const finger = box(50, 22, 10, matDark); finger.position.set(-sx * 20, 0, sz * 98); arm.add(finger); const pad = box(10, 22, 10, matPU); pad.position.set(-sx * 48, 0, sz * 98); arm.add(pad); }
    arms.push({ arm, sx });
  }
  return { group: g, lift, rot, arms, setClamp(v) { for (const a of arms) a.arm.position.x = a.sx * (235 - v * 30.5); } };
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
    for (let x = x0 + 100; x <= x1 - 100; x += 600) { const leg = box(50, top - 80, 50, matFrame); leg.position.set(x, (top - 80) / 2, z); g.add(leg); const foot = box(120, 12, 90, matDark); foot.position.set(x, 6, z); g.add(foot); }
  }
  for (let x = x0 + 100; x <= x1 - 100; x += 600) { const cross = box(40, 40, 400, matFrame); cross.position.set(x, top - 100, 0); g.add(cross); }
  const stops=[];
  for (const x of [-1450,...stationX.slice(1,4),1450]) {
    const base=box(45,70,70,matDark);base.position.set(x+225,top-35,0);g.add(base);
    const st=box(10,24,70,matYellow);st.position.set(x+225,top-14,0);g.add(st);
    const sensor=box(16,18,24,matBlue);sensor.position.set(x,top+12,210);g.add(sensor);
    const led=cylinder(g,3,2,[x,top+23,210],new THREE.MeshStandardMaterial({color:0x1b4f3d,emissive:0x32d49b,emissiveIntensity:0}));
    stops.push({x,st,led});
  }
  for(const z of [-170,170])for(const x of [x0+30,x1-30]){const r=cyl(30,38,matDark);r.rotation.x=Math.PI/2;r.position.set(x,top-28,z);g.add(r);}
  for(let x=x0+30;x<x1;x+=120)for(const z of [-201,201])block(g,[42,3,1],[x,top-30,z],matDark);
  const drive=box(140,120,100,matBlue);drive.position.set(x1-90,top-90,265);g.add(drive);
  const beltMarks=new THREE.Group();g.add(beltMarks);
  for(let x=x0+30;x<x1-100;x+=110)for(const z of [-170,170])block(beltMarks,[3,1,28],[x,top+6.3,z],matAlu);

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

  // ---- S1：頂視相機門型架＋穹頂光 ----
  const s1x = stationX[1];
  const gantry = new THREE.Group(); gantry.position.set(s1x, 0, 0); g.add(gantry);
  for (const z of [-420, 420]) { const post = box(60, 1900, 60, matFrame); post.position.set(0, 950, z); gantry.add(post); }
  const beam1 = box(60, 60, 900, matFrame); beam1.position.set(0, 1900, 0); gantry.add(beam1);
  const topCam = new THREE.Group(); topCam.position.set(0, 1560, 0); gantry.add(topCam);
  topCam.add(box(80, 90, 80, matCam));
  const tcLens = cyl(28, 70, matDark); tcLens.position.y = -80; topCam.add(tcLens);
  const tcMount = box(30, 300, 30, matFrame); tcMount.position.y = 190; topCam.add(tcMount);
  const dome = new THREE.Mesh(new THREE.SphereGeometry(190, 32, 16, 0, Math.PI * 2, .16, Math.PI / 2-.16), matDome); dome.position.set(0, 1330, 0); gantry.add(dome);
  const domeRing = new THREE.Mesh(new THREE.TorusGeometry(192, 8, 8, 48), matDark); domeRing.rotation.x = Math.PI / 2; domeRing.position.y = 1330; gantry.add(domeRing);
  const topFlash = new THREE.SpotLight(0xffffff, 0, 1200, 0.5, 0.6, 1); topFlash.position.set(0, 1560, 0); topFlash.target.position.set(0, 800, 0); gantry.add(topFlash, topFlash.target);

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
  const backZ = railZ - 420, endX = 2700;
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
  return { group:g,occluders:occ,pallet:palletApi,stackerIn,stackerOut,cradle,topFlash,snFlash,tower:towerApi,stops,
    updateTransport(x,located){beltMarks.position.x=((x%110)+110)%110;for(const s of stops){const hit=Math.abs(x-s.x)<2;s.st.position.y=top-14+(hit&&located?28:0);s.led.material.emissiveIntensity=hit?1.4:0;}},
    topCamPos:new THREE.Vector3(s1x,1560,0),snReaderPos:snReader.position.clone() };
}
