// DENSO VM-60B1 六軸手臂（共用模型 @core/models/robots/denso-vm60b1.js）＋本站的第七軸線性滑軌、手臂立座與力覺末端
// （F/T 感測器、12MP 相機＋環形光、鉤爪／PU 壓頭、3D 線雷射輪廓儀）。單位 mm。
// 本檔只放滑軌、立座、末端工具、TCP 與關節規劃（逆解選解、PTP、位姿快取）；手臂本體、限位、IK 與幾何初始解在共用模型。
import * as THREE from 'three';
import { createVM60B1, VM60B1_MAT, JOINTS, JOINT_SPEED } from '@core/models/robots/denso-vm60b1.js';
import { cable, carrier, support, CABLE } from '@core/electrical/cable-routing.js';
import { cylinder, decal } from '@core/geom/primitives.js';

const matArmD  = new THREE.MeshStandardMaterial({ color: 0x2f3439, roughness: 0.5, metalness: 0.3 });
const matJoint = VM60B1_MAT.joint;
const matRail  = new THREE.MeshStandardMaterial({ color: 0x8d949c, roughness: 0.4, metalness: 0.7 });
const matTool  = new THREE.MeshStandardMaterial({ color: 0x3b4149, roughness: 0.4, metalness: 0.6 });
const matGlass = new THREE.MeshPhysicalMaterial({ color: 0x8fb8ff, roughness: 0.05, metalness: 0, transmission: 0.6, transparent: true, opacity: 0.8 });
const matPU    = new THREE.MeshStandardMaterial({ color: 0xd9a441, roughness: 0.9 });
const matLaser = new THREE.MeshStandardMaterial({ color: 0xff2020, emissive: 0xff2020, emissiveIntensity: 1.5 });

const D2R = Math.PI / 180;
// Offset the profiler beyond the 48 mm outer ring-light radius, leaving 7 mm.
const PROFILER_X = 90;
// 滑軌座標：滑座頂面在滑軌底面上 144 mm；立座底面在滑座上 60 mm、高 600 mm，手臂基座底面在立座頂面
const CARRIAGE_Y = 144, RISER = 600, ARM_Y = 60 + RISER;
// 第七軸行程 ±1100 mm、速度 400 mm/s
const RAIL_TRAVEL = 1100, RAIL_SPEED = 400;

function cyl(r1, r2, h, mat, seg = 32) { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, seg), mat); m.castShadow = true; m.receiveShadow = true; return m; }
function box(w, h, d, mat) { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.castShadow = true; m.receiveShadow = true; return m; }

export function createRobot() {
  const root = new THREE.Group(); root.name = 'robotRail';

  // ---- 第七軸滑軌（X 向）----
  const railLen = 2800;
  const railBase = box(railLen, 120, 260, matArmD); railBase.position.y = 60; root.add(railBase);
  for (const z of [-80, 80]) { const r = box(railLen - 40, 24, 24, matRail); r.position.set(0, 132, z); root.add(r); }
  const carriage = new THREE.Group(); carriage.position.y = CARRIAGE_Y; root.add(carriage);
  // 滑座本體（底面離滑軌螺絲頭 1 mm），上接手臂立座。原程式的 carriage.add 誤寫在註解裡，2026-10-03 補回
  const carBody = box(360, 57, 300, matArmD); carBody.position.y = 31.5; carriage.add(carBody);
  const railHarness=carrier(root,'RAIL / rolling power-data-air carrier',{origin:[0,30,-220],min:-1100,max:1100,radius:65,width:44,pitch:24});
  for(const x of [-1050,-550,-50,50,550,1050])support(root,'RAIL / guide cantilever',[x,19,-130],[x,19,-220],8);
  support(carriage,'RAIL / moving anchor',[0,16,-150],[0,16,-220],6);
  for(let x=-1300;x<=1300;x+=140)for(const z of [-80,80])cylinder(root,4,2,[x,145,z],matJoint);

  // ---- 手臂立座（VM-60B1 手腕 ±120°，肩部太低時俯拍與側拍都會超限）＋滑座端線材 ----
  const riser = box(300, RISER, 300, matArmD); riser.position.y = 60 + RISER / 2; carriage.add(riser);

  // ---- 手臂本體（共用模型）：起始姿態 J1 −90°（朝向輸送線）----
  const arm = createVM60B1({ q: { j1: -90, j2: -30, j3: 0, j4: 0, j5: -50, j6: 0 }, name: 'VM-60B1' });
  arm.root.position.y = ARM_Y; carriage.add(arm.root);
  const { j, q, limits, ik } = arm;
  const L = { riser: RISER, ...arm.L };
  cylinder(carriage,10,20,[0,740,-140],matJoint,'z');
  cable(carriage,'RAIL / moving-end strain relief',[[0,16,-220],[0,75,-195],[0,340,-176],[0,740,-176],[0,740,-143]],{radius:8,color:CABLE.sleeve,clips:7});
  decal(j.j2,80,160,[0,220,76],[0,0,0],['6 AXIS','VISION','QC CELL'],{color:'#444c55',center:true});
  const armParts = arm.parts;

  // ---- 力覺末端（裝在手臂的工具安裝座：法蘭面，本地 +Z 為工具前進方向）----
  const tool = arm.tool;
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

  // ---- 關節狀態：手臂六軸（rad，共用模型的 q）＋第七軸 rail（mm）----
  q.rail = 0;
  const home = { ...q };
  const tcps={cam:tcpCam,hook:tcpHook,press:tcpPress,laser:tcpLaser};
  const clampRail = v => THREE.MathUtils.clamp(v, -RAIL_TRAVEL, RAIL_TRAVEL);

  // 滑座與拖鏈先到位並更新整個滑軌的世界矩陣，手臂關節由共用模型設定（IK 迭代時滑軌不動，只呼叫 arm.apply）
  function apply() {
    carriage.position.x = q.rail;
    railHarness.set(q.rail);
    arm.apply();
    root.updateMatrixWorld(true);
  }
  apply();

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

  // PTP 模式：關節各自以限速逼近目標關節角，笛卡兒追蹤狀態同步到目前工具位姿，切回直線移動時不跳動。
  function syncCur(){cur.tcp=goal.tcp;getTcpWorld(cur.tcp,cur.target);tool.getWorldQuaternion(curRotation);cur.dir.set(0,0,1).applyQuaternion(curRotation);}
  function update(dt) {
    if(dt<=0)return getTcpWorld(cur.tcp,tcpWorld);
    if(goal.joints){
      // 同步 PTP：各軸與滑軌依同一比例前進、同時到位，路徑為關節空間直線（與實機同步插值一致）。
      let f=1;for(const name of JOINTS){const d=Math.abs(goal.joints[name]-q[name]);if(d>1e-9)f=Math.min(f,JOINT_SPEED[name]*dt/d);}
      const dr=Math.abs(goal.joints.rail-q.rail);if(dr>1e-9)f=Math.min(f,RAIL_SPEED*dt/dr);
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
    const dr = clampRail(goal.rail) - q.rail; const rs = RAIL_SPEED * dt;
    q.rail += Math.abs(dr) > rs ? Math.sign(dr) * rs : dr;
    apply();
    const previous={...q};ik.solve(tcps[cur.tcp],cur.target,curRotation,14);
    for(const name of JOINTS)q[name]=previous[name]+THREE.MathUtils.clamp(q[name]-previous[name],-JOINT_SPEED[name]*dt,JOINT_SPEED[name]*dt);
    apply();tcps[cur.tcp].getWorldPosition(tcpWorld);
    return tcpWorld;
  }

  function getTcpWorld(name, out = new THREE.Vector3()) { return tcps[name].getWorldPosition(out); }
  // 幾何初始解（共用模型）：肘部上下 × 手腕翻轉共四組，角度折回限位內；手臂基座位置取目標滑軌位置。snap 逐組求解，取誤差最小者。
  function seeds(){
    const origin=goal.target.clone().sub(tcps[goal.tcp].position.clone().applyQuaternion(goal.quaternion));
    return arm.seeds(origin,goal.quaternion,new THREE.Vector3(q.rail,CARRIAGE_Y+ARM_Y,root.position.z));
  }
  const jointDist = (a,b) => JOINTS.reduce((sum,n) => sum + Math.abs(a[n]-b[n]),0);
  function solveIK(ref=null){
    Object.assign(q,home);q.rail=clampRail(goal.rail);cur.target.copy(goal.target);cur.dir.copy(goal.dir);curRotation.copy(goal.quaternion);cur.tcp=goal.tcp;
    let best=null,score=Infinity,near=null,nearD=Infinity;
    for(const c of ref?[ref,...seeds()]:seeds()){
      Object.assign(q,home,c);q.rail=clampRail(goal.rail);apply();
      ik.solve(tcps[goal.tcp],goal.target,goal.quaternion,100);
      const e=error(),v=e.position+e.angle*10;
      if(v<score){score=v;best={...q};}
      if(v<.05){if(!ref)break;const d=jointDist(q,ref);if(d<nearD){nearD=d;near={...q};}}
    }
    Object.assign(q,near||best);
    if(ref){
      // 球形手腕的等價解：(J4+π, −J5, J6+π) 與 J4／J6 ±360° 姿態完全相同，取離參考最近且在限位內者
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
  function error(){const position=getTcpWorld(goal.tcp).distanceTo(goal.target);const axis=new THREE.Vector3(0,0,1).applyQuaternion(tool.getWorldQuaternion(new THREE.Quaternion()));return {position,angle:THREE.MathUtils.radToDeg(axis.angleTo(goal.dir)),rail:Math.abs(q.rail-clampRail(goal.rail))};}

  function setForceColor(f) {
    const c = f < 2 ? 0x3dd68c : f < 8 ? 0xffb020 : 0xff4d4d;
    ftRing.material.color.setHex(c); ftRing.material.emissive.setHex(c);
  }
  function setFlash(on) { flash.intensity = on ? 360 : 0; ringLightMat.emissiveIntensity = on ? .65 : 0.05; }
  function setLaser(on) { laserPlane.material.opacity = on ? 0.35 : 0; profWin.material.emissiveIntensity = on ? 3 : 1.5; }

  return { root,q,home,goal,cur,update,apply,getTcpWorld,setForceColor,setFlash,setLaser,tool,tcpCam,tcpHook,tcpPress,tcpLaser,inspectionCam,snap,error,poseFor,setPose,reach,plan,
    arm,L,limits,
    clearanceParts: { arm: armParts, tool: toolParts, optics: [camBody,lens,lensGlass,ringLight,profiler,profWin] } };
}
