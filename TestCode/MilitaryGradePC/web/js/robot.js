// 六軸手臂（第七軸線性滑軌）＋ 力覺末端（F/T 感測器、12MP 相機＋環形光、微距鏡頭、鉤爪、3D 線雷射）
import * as THREE from 'three';
import { createIK } from './kinematics.js';
import { block, cylinder, tube, decal } from './detail.js';

const matArm   = new THREE.MeshStandardMaterial({ color: 0xe8e9eb, roughness: 0.45, metalness: 0.15 });
const matArmD  = new THREE.MeshStandardMaterial({ color: 0x2f3439, roughness: 0.5, metalness: 0.3 });
const matJoint = new THREE.MeshStandardMaterial({ color: 0x1c1f23, roughness: 0.4, metalness: 0.5 });
const matRail  = new THREE.MeshStandardMaterial({ color: 0x8d949c, roughness: 0.4, metalness: 0.7 });
const matTool  = new THREE.MeshStandardMaterial({ color: 0x3b4149, roughness: 0.4, metalness: 0.6 });
const matGlass = new THREE.MeshPhysicalMaterial({ color: 0x8fb8ff, roughness: 0.05, metalness: 0, transmission: 0.6, transparent: true, opacity: 0.8 });
const matPU    = new THREE.MeshStandardMaterial({ color: 0xd9a441, roughness: 0.9 });
const matLaser = new THREE.MeshStandardMaterial({ color: 0xff2020, emissive: 0xff2020, emissiveIntensity: 1.5 });

const D2R = Math.PI / 180;

function cyl(r1, r2, h, mat, seg = 32) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, seg), mat); m.castShadow = true; m.receiveShadow = true; return m; }
function box(w, h, d, mat) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.castShadow = true; m.receiveShadow = true; return m; }

export function createRobot() {
  const root = new THREE.Group(); root.name = 'robotRail';

  // ---- 第七軸滑軌（X 向 2000 mm）----
  const railLen = 2800;
  const railBase = box(railLen, 120, 260, matArmD); railBase.position.y = 60; root.add(railBase);
  for (const z of [-80, 80]) { const r = box(railLen - 40, 24, 24, matRail); r.position.set(0, 132, z); root.add(r); }
  const carriage = new THREE.Group(); carriage.position.y = 144; root.add(carriage);
  const carBody = box(360, 60, 300, matArmD); carBody.position.y = 30; carriage.add(carBody);
  const cableChain = box(railLen - 200, 40, 50, matJoint); cableChain.position.set(0, 60, -170); root.add(cableChain);
  for(let x=-1250;x<=1250;x+=45)block(root,[4,43,54],[x,60,-170],matTool);
  for(let x=-1300;x<=1300;x+=140)for(const z of [-80,80])cylinder(root,4,3,[x,146,z],matJoint);

  // ---- 手臂連桿 ----
  const L = { base: 160, shoulderZ: 0, upper: 600, fore: 570, wrist1: 110, wrist2: 90, flange: 40 };
  const j = {};  // joints groups

  const base = cyl(120, 140, L.base, matArm); base.position.y = 60 + L.base / 2; carriage.add(base);
  const baseRing = cyl(128, 128, 14, matJoint); baseRing.position.y = 60 + L.base - 7; carriage.add(baseRing);

  j.j1 = new THREE.Group(); j.j1.position.y = 60 + L.base; carriage.add(j.j1);          // J1 繞 Y
  const shoulderHouse = cyl(100, 110, 140, matArm); shoulderHouse.position.y = 70; j.j1.add(shoulderHouse);
  const shoulderSide = box(110, 190, 220, matArm); shoulderSide.position.set(0, 165, 0); j.j1.add(shoulderSide);

  j.j2 = new THREE.Group(); j.j2.position.set(0, 210, 0); j.j1.add(j.j2);               // J2 繞 Z（pitch）
  const j2disc = cyl(95, 95, 250, matJoint); j2disc.rotation.x = Math.PI / 2; j.j2.add(j2disc);
  const upperArm = box(130, L.upper, 150, matArm); upperArm.position.y = L.upper / 2; j.j2.add(upperArm);
  const upperArmCap = cyl(75, 75, 152, matArm); upperArmCap.rotation.x = Math.PI / 2; upperArmCap.position.y = L.upper; j.j2.add(upperArmCap);

  j.j3 = new THREE.Group(); j.j3.position.set(0, L.upper, 0); j.j2.add(j.j3);           // J3 繞 Z（pitch）
  const j3disc = cyl(72, 72, 200, matJoint); j3disc.rotation.x = Math.PI / 2; j.j3.add(j3disc);
  const foreArm = box(L.fore, 100, 110, matArm); foreArm.position.set(L.fore / 2 - 30, 0, 0); j.j3.add(foreArm);   // 前臂沿 +X
  const foreCap = cyl(60, 60, 120, matArm); foreCap.rotation.x = Math.PI / 2; foreCap.position.set(L.fore - 30, 0, 0); j.j3.add(foreCap);
  tube(j.j2,[[0,40,-94],[45,150,-94],[50,390,-94],[0,475,-94]],9,matJoint);
  tube(j.j3,[[0,0,-90],[80,70,-84],[275,65,-75],[355,5,-65]],7,matJoint);
  decal(j.j2,80,160,[0,220,76],[0,0,0],['6 AXIS','VISION','QC CELL'],{color:'#444c55',center:true});
  for(const joint of [j.j2,j.j3])for(let k=0;k<6;k++)cylinder(joint,4,3,[45*Math.cos(k*Math.PI/3),45*Math.sin(k*Math.PI/3),104],matRail,'z',6);

  j.j4 = new THREE.Group(); j.j4.position.set(L.fore - 30, 0, 0); j.j3.add(j.j4);       // J4 繞 X（前臂軸 roll）
  const w1 = cyl(52, 52, L.wrist1, matArm); w1.rotation.z = Math.PI / 2; w1.position.x = L.wrist1 / 2; j.j4.add(w1);

  j.j5 = new THREE.Group(); j.j5.position.set(L.wrist1, 0, 0); j.j4.add(j.j5);          // J5 繞 Z（pitch）
  const w2 = cyl(48, 48, 120, matJoint); w2.rotation.x = Math.PI / 2; j.j5.add(w2);
  const w2b = box(L.wrist2, 80, 80, matArm); w2b.position.x = L.wrist2 / 2; j.j5.add(w2b);

  j.j6 = new THREE.Group(); j.j6.position.set(L.wrist2, 0, 0); j.j5.add(j.j6);          // J6 繞 X（flange roll）
  const flange = cyl(40, 40, L.flange, matJoint); flange.rotation.z = Math.PI / 2; flange.position.x = L.flange / 2; j.j6.add(flange);

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

  // 3D 線雷射輪廓儀（左側）
  const profiler = box(70, 40, 90, matArmD); profiler.position.set(64, 20, 90); tool.add(profiler);
  const profWin = box(40, 4, 60, matLaser); profWin.position.set(64, -1, 100); tool.add(profWin);
  const laserPlane = new THREE.Mesh(new THREE.PlaneGeometry(90, 320), new THREE.MeshBasicMaterial({ color: 0xff2a2a, transparent: true, opacity: 0.0, side: THREE.DoubleSide, depthWrite: false }));
  laserPlane.position.set(64, 0, 260); tool.add(laserPlane);

  // TCP 定義：相機 TCP（鏡頭前方工作距離 150 mm）、鉤爪 TCP、雷射 TCP
  const tcpCam = new THREE.Object3D(); tcpCam.position.set(0, 0, 145 + 150); tool.add(tcpCam);
  const tcpHook = new THREE.Object3D(); tcpHook.position.set(-62, -38, 200); tool.add(tcpHook);
  const tcpPress = new THREE.Object3D(); tcpPress.position.set(-62,-30,193); tool.add(tcpPress);
  const tcpLaser = new THREE.Object3D(); tcpLaser.position.set(64, 0, 330); tool.add(tcpLaser);


  // ---- 關節狀態 ----
  const q = { rail: 0, j1: -90 * D2R, j2: -30 * D2R, j3: 0 * D2R, j4: 0, j5: -50 * D2R, j6: 0 };
  // Concept arm limits; replace with the selected OEM model before commissioning.
  const limits = { j1: [-170, 170], j2: [-120, 120], j3: [-150, 150], j4: [-360, 360], j5: [-170, 170], j6: [-360, 360] };
  const home = { ...q };
  const tcps={cam:tcpCam,hook:tcpHook,press:tcpPress,laser:tcpLaser};

  function apply() {
    carriage.position.x = q.rail;
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
  function clampJ(name,v){const [lo,hi]=limits[name];return THREE.MathUtils.clamp(v,lo*D2R,hi*D2R);}

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

  function update(dt) {
    if(dt<=0)return getTcpWorld(cur.tcp,tcpWorld);
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
    for(const name of ['j1','j2','j3','j4','j5','j6'])q[name]=previous[name]+THREE.MathUtils.clamp(q[name]-previous[name],-1.8*dt,1.8*dt);
    apply();tcps[cur.tcp].getWorldPosition(tcpWorld);
    return tcpWorld;
  }

  function getTcpWorld(name, out = new THREE.Vector3()) { return tcps[name].getWorldPosition(out); }
  function seed(){
    const dir=new THREE.Vector3(0,0,1).applyQuaternion(goal.quaternion);
    const origin=goal.target.clone().sub(tcps[goal.tcp].position.clone().applyQuaternion(goal.quaternion));
    const wrist=origin.addScaledVector(dir,-L.wrist2-L.flange).sub(new THREE.Vector3(q.rail,144+60+L.base+210,root.position.z));
    const radial=Math.hypot(wrist.x,wrist.z),a=L.upper,b=L.fore-30+L.wrist1;
    q.j1=Math.atan2(-wrist.z,wrist.x);
    const beta=-Math.acos(THREE.MathUtils.clamp((radial*radial+wrist.y*wrist.y-a*a-b*b)/(2*a*b),-1,1));
    q.j2=Math.atan2(wrist.y,radial)-Math.atan2(b*Math.sin(beta),a+b*Math.cos(beta))-Math.PI/2;
    q.j3=beta+Math.PI/2;
    const shoulder=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),q.j1).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),q.j2+q.j3));
    const relative=shoulder.invert().multiply(goal.quaternion).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),-Math.PI/2));
    const m=new THREE.Matrix4().makeRotationFromQuaternion(relative).elements;
    q.j5=Math.acos(THREE.MathUtils.clamp(m[0],-1,1));
    if(Math.sin(q.j5)>.00001){q.j4=Math.atan2(m[2],m[1]);q.j6=Math.atan2(m[8],-m[4]);}
    else{q.j4=0;q.j6=Math.atan2(m[6],m[5]);}
    for(const name in limits)q[name]=clampJ(name,q[name]);apply();
  }
  function snap(){Object.assign(q,home);q.rail=THREE.MathUtils.clamp(goal.rail,-1100,1100);cur.target.copy(goal.target);cur.dir.copy(goal.dir);curRotation.copy(goal.quaternion);cur.tcp=goal.tcp;seed();ik.solve(tcps[goal.tcp],goal.target,goal.quaternion,100);return getTcpWorld(goal.tcp);}
  function poseFor(tcp,target,dir,rail=0){const rotation=new THREE.Quaternion().setFromRotationMatrix(frameFor(dir));return {origin:target.clone().sub(tcps[tcp].position.clone().applyQuaternion(rotation)),rotation,rail,tcp};}
  function setPose(pose){goal.tcp=pose.tcp;goal.quaternion.copy(pose.rotation);goal.dir.set(0,0,1).applyQuaternion(pose.rotation);goal.target.copy(pose.origin).add(tcps[pose.tcp].position.clone().applyQuaternion(pose.rotation));goal.rail=pose.rail;}
  function error(){const position=getTcpWorld(goal.tcp).distanceTo(goal.target);const axis=new THREE.Vector3(0,0,1).applyQuaternion(tool.getWorldQuaternion(new THREE.Quaternion()));return {position,angle:THREE.MathUtils.radToDeg(axis.angleTo(goal.dir)),rail:Math.abs(q.rail-THREE.MathUtils.clamp(goal.rail,-1100,1100))};}

  function setForceColor(f) {
    const c = f < 2 ? 0x3dd68c : f < 8 ? 0xffb020 : 0xff4d4d;
    ftRing.material.color.setHex(c); ftRing.material.emissive.setHex(c);
  }
  function setFlash(on) { flash.intensity = on ? 360 : 0; ringLightMat.emissiveIntensity = on ? .65 : 0.05; }
  function setLaser(on) { laserPlane.material.opacity = on ? 0.35 : 0; profWin.material.emissiveIntensity = on ? 3 : 1.5; }

  return { root,q,home,goal,cur,update,apply,getTcpWorld,setForceColor,setFlash,setLaser,tool,tcpCam,tcpHook,tcpPress,tcpLaser,snap,error,poseFor,setPose };
}
