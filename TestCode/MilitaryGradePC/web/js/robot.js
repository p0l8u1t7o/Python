// 六軸手臂（第七軸線性滑軌）＋ 力覺末端（F/T 感測器、12MP 相機＋環形光、微距鏡頭、鉤爪、3D 線雷射）
import * as THREE from 'three';
import { cable, armDress, carrier, support, CABLE } from '@core/electrical/cable-routing.js';
import { createIK } from '@core/robot/kinematics.js';
import { block, cylinder, tube, decal } from '@core/geom/primitives.js';

const matArm   = new THREE.MeshStandardMaterial({ color: 0xe8e9eb, roughness: 0.45, metalness: 0.15 });
const matArmD  = new THREE.MeshStandardMaterial({ color: 0x2f3439, roughness: 0.5, metalness: 0.3 });
const matJoint = new THREE.MeshStandardMaterial({ color: 0x1c1f23, roughness: 0.4, metalness: 0.5 });
const matRail  = new THREE.MeshStandardMaterial({ color: 0x8d949c, roughness: 0.4, metalness: 0.7 });
const matTool  = new THREE.MeshStandardMaterial({ color: 0x3b4149, roughness: 0.4, metalness: 0.6 });
const matGlass = new THREE.MeshPhysicalMaterial({ color: 0x8fb8ff, roughness: 0.05, metalness: 0, transmission: 0.6, transparent: true, opacity: 0.8 });
const matPU    = new THREE.MeshStandardMaterial({ color: 0xd9a441, roughness: 0.9 });
const matLaser = new THREE.MeshStandardMaterial({ color: 0xff2020, emissive: 0xff2020, emissiveIntensity: 1.5 });

const D2R = Math.PI / 180;
// Offset the profiler beyond the 48 mm outer ring-light radius, leaving 7 mm.
const PROFILER_X = 90;

function cyl(r1, r2, h, mat, seg = 32) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, seg), mat); m.castShadow = true; m.receiveShadow = true; return m; }
function box(w, h, d, mat) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.castShadow = true; m.receiveShadow = true; return m; }

export function createRobot() {
  const root = new THREE.Group(); root.name = 'robotRail';

  // ---- 第七軸滑軌（X 向 2000 mm）----
  const railLen = 2800;
  const railBase = box(railLen, 120, 260, matArmD); railBase.position.y = 60; root.add(railBase);
  for (const z of [-80, 80]) { const r = box(railLen - 40, 24, 24, matRail); r.position.set(0, 132, z); root.add(r); }
  const carriage = new THREE.Group(); carriage.position.y = 144; root.add(carriage);
  const carBody = box(360, 57, 300, matArmD); carBody.position.y = 31.5;   // 底面離滑軌螺絲頭 1 mm carriage.add(carBody);
  const railHarness=carrier(root,'RAIL / rolling power-data-air carrier',{origin:[0,30,-220],min:-1100,max:1100,radius:65,width:44,pitch:24});
  for(const x of [-1050,-550,-50,50,550,1050])support(root,'RAIL / guide cantilever',[x,19,-130],[x,19,-220],8);
  support(carriage,'RAIL / moving anchor',[0,16,-150],[0,16,-220],6);
  for(let x=-1300;x<=1300;x+=140)for(const z of [-80,80])cylinder(root,4,2,[x,145,z],matJoint);

  // ---- 手臂連桿 ----
  // DENSO VM-60B1 型錄：臂長 520＋590、J1–J2 偏移 180、J3 偏移 100。基座高度與 J5 以後的手腕長度型錄未列，仍為概念值。
  // riser：手臂立座。VM-60B1 手腕 ±120°，肩部太低時俯拍與側拍都會超限。
  const L = { riser: 600, base: 160, shoulderX: 180, upper: 520, fore: 590, foreOffset: 100, wrist1: 110, wrist2: 90, flange: 40 };
  const j = {};  // joints groups

  const riser = box(300, L.riser, 300, matArmD); riser.position.y = 60 + L.riser / 2; carriage.add(riser);
  const base = cyl(120, 140, L.base, matArm); base.position.y = 60 + L.riser + L.base / 2; carriage.add(base);
  const baseRing = cyl(128, 128, 14, matJoint); baseRing.position.y = 60 + L.riser + L.base - 7.7; carriage.add(baseRing);
  cylinder(carriage,10,20,[0,740,-140],matJoint,'z');
  cable(carriage,'RAIL / moving-end strain relief',[[0,16,-220],[0,75,-195],[0,340,-176],[0,740,-176],[0,740,-143]],{radius:8,color:CABLE.sleeve,clips:7});

  j.j1 = new THREE.Group(); j.j1.position.y = 60 + L.riser + L.base; carriage.add(j.j1);          // J1 繞 Y
  const shoulderHouse = cyl(100, 110, 140, matArm); shoulderHouse.position.y = 70; j.j1.add(shoulderHouse);
  const shoulderSide = box(L.shoulderX + 110, 190, 220, matArm); shoulderSide.position.set(L.shoulderX / 2, 165, 0); j.j1.add(shoulderSide);

  j.j2 = new THREE.Group(); j.j2.position.set(L.shoulderX, 210, 0); j.j1.add(j.j2);               // J2 繞 Z（pitch）
  const j2disc = cyl(95, 95, 250, matJoint); j2disc.rotation.x = Math.PI / 2; j.j2.add(j2disc);
  const upperArm = box(130, L.upper, 150, matArm); upperArm.position.y = L.upper / 2; j.j2.add(upperArm);
  const upperArmCap = cyl(75, 75, 152, matArm); upperArmCap.rotation.x = Math.PI / 2; upperArmCap.position.y = L.upper; j.j2.add(upperArmCap);

  j.j3 = new THREE.Group(); j.j3.position.set(0, L.upper, 0); j.j2.add(j.j3);           // J3 繞 Z（pitch）
  const j3disc = cyl(72, 72, 200, matJoint); j3disc.rotation.x = Math.PI / 2; j.j3.add(j3disc);
  const elbow = box(150, L.foreOffset + 60, 120, matArm); elbow.position.y = L.foreOffset / 2; j.j3.add(elbow);
  const foreArm = box(L.fore - L.wrist1 + 30, 100, 110, matArm); foreArm.position.set((L.fore - L.wrist1 - 30) / 2, L.foreOffset, 0); j.j3.add(foreArm);   // 前臂沿 +X，J4 軸高於 J3 軸 foreOffset
  // 前臂端蓋縮到前臂寬度內（z ±52、半徑 56），手腕大角度折疊時不碰
  const foreCap = cyl(56, 56, 104, matArm); foreCap.rotation.x = Math.PI / 2; foreCap.position.set(L.fore - L.wrist1, L.foreOffset, 0); j.j3.add(foreCap);
  armDress(j,L,{upperDepth:76,foreDepth:56,large:true});
  decal(j.j2,80,160,[0,220,76],[0,0,0],['6 AXIS','VISION','QC CELL'],{color:'#444c55',center:true});
  for(const joint of [j.j2,j.j3])for(let k=0;k<6;k++)cylinder(joint,4,3,[45*Math.cos(k*Math.PI/3),45*Math.sin(k*Math.PI/3),104],matRail,'z',6);

  j.j4 = new THREE.Group(); j.j4.position.set(L.fore - L.wrist1, L.foreOffset, 0); j.j3.add(j.j4);       // J4 繞 X（前臂軸 roll）
  const w1 = cyl(52, 52, L.wrist1, matArm); w1.rotation.z = Math.PI / 2; w1.position.x = L.wrist1 / 2; j.j4.add(w1);

  j.j5 = new THREE.Group(); j.j5.position.set(L.wrist1, 0, 0); j.j4.add(j.j5);          // J5 繞 Z（pitch）
  const w2 = cyl(48, 48, 120, matJoint); w2.rotation.x = Math.PI / 2; j.j5.add(w2);
  const w2b = box(L.wrist2, 80, 80, matArm); w2b.position.x = L.wrist2 / 2; j.j5.add(w2b);

  j.j6 = new THREE.Group(); j.j6.position.set(L.wrist2, 0, 0); j.j5.add(j.j6);          // J6 繞 X（flange roll）
  const flange = cyl(40, 40, L.flange, matJoint); flange.rotation.z = Math.PI / 2; flange.position.x = L.flange / 2; j.j6.add(flange);
  const armParts = [base, shoulderHouse, shoulderSide, j2disc, upperArm, upperArmCap, j3disc, elbow, foreArm, foreCap, w1, w2, w2b];
  ['base','shoulder','shoulder-side','J2','upper-arm','elbow-cap','J3','elbow','forearm','forearm-cap','J4','J5','wrist']
    .forEach((name,i) => { armParts[i].name = name; });

  // ---- 力覺末端（tool）----  本地 +Z 為工具前進方向
  const tool = new THREE.Group(); tool.position.x = L.flange; tool.rotation.y = Math.PI / 2; j.j6.add(tool);   // 工具本地 +Z → 父層 +X
  const ft = cyl(44, 44, 34, matTool); ft.rotation.x = Math.PI / 2; ft.position.z = 17; tool.add(ft);
  const ftRing = new THREE.Mesh(new THREE.TorusGeometry(44, 2.2, 8, 40), new THREE.MeshStandardMaterial({ color: 0x3dd68c, emissive: 0x3dd68c, emissiveIntensity: 1.2 }));
  ftRing.position.z = 17; tool.add(ftRing);
  const plate = box(150, 110, 10, matArmD); plate.position.z = 39; tool.add(plate);

  // 相機 + 環形光（工具中心）
  const camBody = box(44, 44, 60, matArmD); camBody.position.set(0, 0, 74); tool.add(camBody);
  const lens = cyl(16, 16, 40, matJoint); lens.rotation.x = Math.PI / 2; lens.position.set(0, 0, 124); tool.add(lens);
  const lensGlass = cyl(12, 12, 2, matGlass); lensGlass.rotation.x = Math.PI / 2; lensGlass.position.set(0, 0, 145); tool.add(lensGlass);
  const ringLightMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.05 });
  const ringLight = new THREE.Mesh(new THREE.TorusGeometry(40, 8, 10, 48), ringLightMat); ringLight.position.set(0, 0, 130); tool.add(ringLight);
  const flash = new THREE.SpotLight(0xffffff, 0, 600, 0.6, 0.5, 1); flash.position.set(0, 0, 130); flash.target.position.set(0, 0, 400); tool.add(flash, flash.target);

  // 鉤爪（右側，POM 接觸面）
  const hookArm = box(16, 16, 150, matTool); hookArm.position.set(-62, -30, 110); tool.add(hookArm);
  const hookTip = box(10, 4, 20, matPU); hookTip.position.set(-62, -38, 190); tool.add(hookTip);
  const pressPad = cyl(11, 11, 8, matPU); pressPad.rotation.x = Math.PI / 2; pressPad.position.set(-62, -30, 189); tool.add(pressPad);

  // 3D 線雷射輪廓儀（左側）：Gocator 2520 CD 47.5 mm、MR 25 mm，TCP 取量測範圍中央
  const profiler = box(70, 40, 90, matArmD); profiler.position.set(PROFILER_X, 20, 90); tool.add(profiler);
  const profWin = box(40, 20, 4, matLaser); profWin.position.set(PROFILER_X, 20, 136); tool.add(profWin);
  const laserPlane = new THREE.Mesh(new THREE.PlaneGeometry(30, 70), new THREE.MeshBasicMaterial({ color: 0xff2a2a, transparent: true, opacity: 0.0, side: THREE.DoubleSide, depthWrite: false }));
  laserPlane.rotation.x = Math.PI / 2; laserPlane.position.set(PROFILER_X, 20, 170); tool.add(laserPlane);

  // TCP 定義：相機 TCP（鏡頭前方工作距離 150 mm）、鉤爪 TCP、雷射 TCP
  const tcpCam = new THREE.Object3D(); tcpCam.position.set(0, 0, 145 + 150); tool.add(tcpCam);
  // A 12 mm lens on a 13.2 × 8.8 mm sensor; illustrative optical specification.
  const inspectionCam=new THREE.PerspectiveCamera(2*Math.atan(8.8/24)*180/Math.PI,1.5,.3,3000);
  inspectionCam.position.set(0,0,146.1);inspectionCam.rotation.y=Math.PI;tool.add(inspectionCam);
  const tcpHook = new THREE.Object3D(); tcpHook.position.set(-62, -38, 200); tool.add(tcpHook);
  const tcpPress = new THREE.Object3D(); tcpPress.position.set(-62,-30,193); tool.add(tcpPress);
  const tcpLaser = new THREE.Object3D(); tcpLaser.position.set(PROFILER_X, 20, 195); tool.add(tcpLaser);

  const toolParts = [ft, plate, camBody, lens, lensGlass, ringLight, hookArm, hookTip, pressPad, profiler, profWin];
  ['force-sensor','tool-plate','camera','lens','lens-glass','ring-light','hook-arm','hook-tip','press-pad','profiler','profiler-window']
    .forEach((name,i) => { toolParts[i].name = name; });


  cable(tool,'VISION / camera supply',[[46,0,17],[82,0,17],[88,45,25],[88,65,55],[28,65,75],[28,14,80],[22,14,80]],{radius:2.5,color:CABLE.signal});
  cable(tool,'VISION / ring-light power',[[65,45,44],[49,49,66],[42,40,100],[38,26,124]],{radius:2,color:CABLE.power});
  cable(tool,'PROFILE / sensor data',[[70,40,48],[80,58,48],[110,58,60],[110,43,75]],{radius:2.5,color:CABLE.signal,clips:1});

  // ---- 關節狀態 ----
  const q = { rail: 0, j1: -90 * D2R, j2: -30 * D2R, j3: 0 * D2R, j4: 0, j5: -50 * D2R, j6: 0 };
  // VM-60B1 型錄範圍：J1 ±170、J2 +135/−90、J3 +168/−80、J4 ±185、J5 ±120、J6 ±360。
  // 換算到本模型座標（假設 DENSO J2 零點為上臂垂直、J3=90° 為前臂水平；正向相反）：j2 = −J2、j3 = 90° − J3。採用前以 DENSO CAD 核對。
  const limits = { j1: [-170, 170], j2: [-135, 90], j3: [-78, 170], j4: [-185, 185], j5: [-120, 120], j6: [-360, 360] };
  const home = { ...q };
  const tcps={cam:tcpCam,hook:tcpHook,press:tcpPress,laser:tcpLaser};

  function apply() {
    carriage.position.x = q.rail;
    railHarness.set(q.rail);
    j.j1.rotation.set(0, q.j1, 0);
    j.j2.rotation.set(0, 0, q.j2);
    j.j3.rotation.set(0, 0, q.j3);
    j.j4.rotation.set(q.j4, 0, 0);
    j.j5.rotation.set(0, 0, q.j5);
    j.j6.rotation.set(q.j6, 0, 0);
    root.updateMatrixWorld(true);
  }
  apply();
  const ik=createIK({q,j,tool,apply,limits});

  const _p = new THREE.Vector3();

  /** 依工具軸方向建立工具座標系（z = dir，y 盡量朝上） */
  const _R = new THREE.Matrix4(), _x = new THREE.Vector3(), _y = new THREE.Vector3(), _z = new THREE.Vector3(), _up = new THREE.Vector3();
  function frameFor(dir) {
    _z.copy(dir).normalize();
    _up.set(0, 1, 0); if (Math.abs(_z.y) > 0.9) _up.set(0, 0, -1);
    _x.crossVectors(_up, _z).normalize(); _y.crossVectors(_z, _x).normalize();
    return _R.makeBasis(_x, _y, _z);
  }
  // ---- 平滑追蹤目標（每幀呼叫）----
  const cur = { target: new THREE.Vector3(0, 900, 0), dir: new THREE.Vector3(0, -1, 0), tcp: 'cam', rail: 0 };
  const goal = { target: new THREE.Vector3(0, 900, 0), dir: new THREE.Vector3(0, -1, 0), quaternion:new THREE.Quaternion(),tcp: 'cam', rail: 0, speed: 600 };
  const curRotation=new THREE.Quaternion();tool.getWorldQuaternion(curRotation);
  const tcpWorld = new THREE.Vector3();

  const JOINTS=['j1','j2','j3','j4','j5','j6'];
  // PTP 模式：關節各自以限速逼近目標關節角，笛卡兒追蹤狀態同步到目前工具位姿，切回直線移動時不跳動。
  function syncCur(){cur.tcp=goal.tcp;getTcpWorld(cur.tcp,cur.target);tool.getWorldQuaternion(curRotation);cur.dir.set(0,0,1).applyQuaternion(curRotation);}
  function update(dt) {
    if(dt<=0)return getTcpWorld(cur.tcp,tcpWorld);
    if(goal.joints){
      // 同步 PTP：各軸與滑軌依同一比例前進、同時到位，路徑為關節空間直線（與實機同步插值一致）。
      let f=1;for(const name of JOINTS){const d=Math.abs(goal.joints[name]-q[name]);if(d>1e-9)f=Math.min(f,1.8*dt/d);}
      const dr=Math.abs(goal.joints.rail-q.rail);if(dr>1e-9)f=Math.min(f,400*dt/dr);
      for(const name of [...JOINTS,'rail'])q[name]+=(goal.joints[name]-q[name])*f;
      apply();syncCur();return getTcpWorld(goal.tcp,tcpWorld);
    }
    if(cur.tcp!==goal.tcp){cur.target.copy(getTcpWorld(goal.tcp));cur.tcp=goal.tcp;}
    // 目標點以限速逼近（mm/s），滑軌獨立
    const d = _p.copy(goal.target).sub(cur.target); const dist = d.length();
    const step = goal.speed * dt;
    if (dist > step) cur.target.addScaledVector(d.normalize(), step); else cur.target.copy(goal.target);
    curRotation.rotateTowards(goal.quaternion,dt*1.8);cur.dir.set(0,0,1).applyQuaternion(curRotation);
    cur.tcp = goal.tcp;
    const dr = THREE.MathUtils.clamp(goal.rail,-1100,1100) - q.rail; const rs = 400 * dt;
    q.rail += Math.abs(dr) > rs ? Math.sign(dr) * rs : dr;
    apply();
    const previous={...q};ik.solve(tcps[cur.tcp],cur.target,curRotation,14);
    for(const name of JOINTS)q[name]=previous[name]+THREE.MathUtils.clamp(q[name]-previous[name],-1.8*dt,1.8*dt);
    apply();tcps[cur.tcp].getWorldPosition(tcpWorld);
    return tcpWorld;
  }

  function getTcpWorld(name, out = new THREE.Vector3()) { return tcps[name].getWorldPosition(out); }
  // 幾何初始解：肘部上下 × 手腕翻轉共四組，角度折回限位內；snap 逐組求解，取誤差最小者。
  function wrapJ(name,v){const [lo,hi]=limits[name].map(x=>x*D2R);for(const k of [0,2*Math.PI,-2*Math.PI])if(v+k>=lo&&v+k<=hi)return v+k;return THREE.MathUtils.clamp(v,lo,hi);}
  function seeds(){
    const dir=new THREE.Vector3(0,0,1).applyQuaternion(goal.quaternion);
    const origin=goal.target.clone().sub(tcps[goal.tcp].position.clone().applyQuaternion(goal.quaternion));
    const wrist=origin.addScaledVector(dir,-L.wrist2-L.flange).sub(new THREE.Vector3(q.rail,144+60+L.riser+L.base+210,root.position.z));
    const radial=Math.hypot(wrist.x,wrist.z)-L.shoulderX,a=L.upper,b=Math.hypot(L.fore,L.foreOffset),phi=Math.atan2(L.foreOffset,L.fore);
    const j1=Math.atan2(-wrist.z,wrist.x),elbow=Math.acos(THREE.MathUtils.clamp((radial*radial+wrist.y*wrist.y-a*a-b*b)/(2*a*b),-1,1)),out=[];
    for(const beta of [-elbow,elbow]){
      const j2=Math.atan2(wrist.y,radial)-Math.atan2(b*Math.sin(beta),a+b*Math.cos(beta))-Math.PI/2,j3=beta+Math.PI/2-phi;
      const shoulder=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),j1).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),j2+j3));
      const relative=shoulder.invert().multiply(goal.quaternion).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),-Math.PI/2));
      const m=new THREE.Matrix4().makeRotationFromQuaternion(relative).elements;
      const j5=Math.acos(THREE.MathUtils.clamp(m[0],-1,1));
      let j4=0,j6=Math.atan2(m[6],m[5]);if(Math.sin(j5)>.00001){j4=Math.atan2(m[2],m[1]);j6=Math.atan2(m[8],-m[4]);}
      for(const [w4,w5,w6] of [[j4,j5,j6],[j4+Math.PI,-j5,j6+Math.PI]]){
        const c={j1,j2,j3,j4:w4,j5:w5,j6:w6};for(const name in limits)c[name]=wrapJ(name,c[name]);out.push(c);
      }
    }
    return out;
  }
  const jointDist = (a,b) => JOINTS.reduce((sum,n) => sum + Math.abs(a[n]-b[n]),0);
  function solveIK(ref=null){
    Object.assign(q,home);q.rail=THREE.MathUtils.clamp(goal.rail,-1100,1100);cur.target.copy(goal.target);cur.dir.copy(goal.dir);curRotation.copy(goal.quaternion);cur.tcp=goal.tcp;
    let best=null,score=Infinity,near=null,nearD=Infinity;
    for(const c of ref?[ref,...seeds()]:seeds()){
      Object.assign(q,home,c);q.rail=THREE.MathUtils.clamp(goal.rail,-1100,1100);apply();
      ik.solve(tcps[goal.tcp],goal.target,goal.quaternion,100);
      const e=error(),v=e.position+e.angle*10;
      if(v<score){score=v;best={...q};}
      if(v<.05){if(!ref)break;const d=jointDist(q,ref);if(d<nearD){nearD=d;near={...q};}}
    }
    Object.assign(q,near||best);
    if(ref){
      const within=c=>JOINTS.every(n=>c[n]>=limits[n][0]*D2R-1e-9&&c[n]<=limits[n][1]*D2R+1e-9);
      let pick={...q},pickD=jointDist(q,ref);
      for(const [d4,s5,d6] of [[0,1,0],[Math.PI,-1,Math.PI],[Math.PI,-1,-Math.PI],[-Math.PI,-1,Math.PI],[-Math.PI,-1,-Math.PI]])
        for(const k4 of [0,2*Math.PI,-2*Math.PI])for(const k6 of [0,2*Math.PI,-2*Math.PI]){
          const c={...q,j4:q.j4+d4+k4,j5:s5*q.j5,j6:q.j6+d6+k6};
          if(within(c)){const d=jointDist(c,ref);if(d<pickD-1e-9){pickD=d;pick=c;}}
        }
      Object.assign(q,pick);
    }
    apply();
  }
  function snap(){
    if(goal.joints){Object.assign(q,goal.joints);apply();syncCur();return getTcpWorld(goal.tcp);}
    solveIK(goal.refPose?jointCache.get(goal.refPose)||null:null);return getTcpWorld(goal.tcp);
  }
  // 位姿→關節角（快取於位姿物件）；同一位姿永遠得到同一組解，倒退／跳站結果一致。
  const jointCache=new WeakMap();
  function solveJoints(pose,ref=null){
    let c=jointCache.get(pose);if(c)return c;
    const saved={...q},savedGoal={target:goal.target.clone(),quaternion:goal.quaternion.clone(),dir:goal.dir.clone(),tcp:goal.tcp,rail:goal.rail,joints:goal.joints,refPose:goal.refPose};
    const curSaved={target:cur.target.clone(),rotation:curRotation.clone(),dir:cur.dir.clone(),tcp:cur.tcp};
    setGoal(pose);solveIK(ref);const e=error();c={...q,position:e.position,angle:e.angle};
    Object.assign(q,saved);Object.assign(goal,savedGoal);cur.target.copy(curSaved.target);curRotation.copy(curSaved.rotation);cur.dir.copy(curSaved.dir);cur.tcp=curSaved.tcp;apply();
    jointCache.set(pose,c);return c;
  }
  function reach(pose){const c=solveJoints(pose);return {position:c.position,angle:c.angle};}
  // 待命位姿（fresh）不沿用上一個解的參考：避免偏軸工具繞軸轉動後，把 J6 圈數與手腕翻轉帶進待命姿態
  function plan(poses){let ref=null;for(const pose of poses)ref=solveJoints(pose,pose.fresh?null:ref);}
  function poseFor(tcp,target,dir,rail=0){const rotation=new THREE.Quaternion().setFromRotationMatrix(frameFor(dir));return {origin:target.clone().sub(tcps[tcp].position.clone().applyQuaternion(rotation)),rotation,rail,tcp};}
  function setGoal(pose){goal.joints=null;goal.refPose=pose.ref||null;goal.tcp=pose.tcp;goal.quaternion.copy(pose.rotation);goal.dir.set(0,0,1).applyQuaternion(pose.rotation);goal.target.copy(pose.origin).add(tcps[pose.tcp].position.clone().applyQuaternion(pose.rotation));goal.rail=pose.rail;}
  function setPose(pose){
    if(!pose.ptp)return setGoal(pose);
    const a=solveJoints(pose.ptp.from),b=solveJoints(pose.ptp.to),e=pose.ptp.e,joints={rail:THREE.MathUtils.lerp(a.rail,b.rail,e)};
    for(const name of JOINTS)joints[name]=THREE.MathUtils.lerp(a[name],b[name],e);
    const saved={...q};Object.assign(q,joints);apply();
    goal.tcp=pose.ptp.to.tcp;getTcpWorld(goal.tcp,goal.target);tool.getWorldQuaternion(goal.quaternion);goal.dir.set(0,0,1).applyQuaternion(goal.quaternion);goal.rail=joints.rail;goal.joints=joints;
    Object.assign(q,saved);apply();
  }
  function error(){const position=getTcpWorld(goal.tcp).distanceTo(goal.target);const axis=new THREE.Vector3(0,0,1).applyQuaternion(tool.getWorldQuaternion(new THREE.Quaternion()));return {position,angle:THREE.MathUtils.radToDeg(axis.angleTo(goal.dir)),rail:Math.abs(q.rail-THREE.MathUtils.clamp(goal.rail,-1100,1100))};}

  function setForceColor(f) {
    const c = f < 2 ? 0x3dd68c : f < 8 ? 0xffb020 : 0xff4d4d;
    ftRing.material.color.setHex(c); ftRing.material.emissive.setHex(c);
  }
  function setFlash(on) { flash.intensity = on ? 360 : 0; ringLightMat.emissiveIntensity = on ? .65 : 0.05; }
  function setLaser(on) { laserPlane.material.opacity = on ? 0.35 : 0; profWin.material.emissiveIntensity = on ? 3 : 1.5; }

  return { root,q,home,goal,cur,update,apply,getTcpWorld,setForceColor,setFlash,setLaser,tool,tcpCam,tcpHook,tcpPress,tcpLaser,inspectionCam,snap,error,poseFor,setPose,reach,plan,
    clearanceParts: { arm: armParts, tool: toolParts, optics: [camBody,lens,lensGlass,ringLight,profiler,profWin] } };
}
