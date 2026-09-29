// 機台：由 spec.js 的機構資料建模（與干涉檢查同一份數字），另加底櫃、外罩、HMI 與光束示意
import * as THREE from 'three';
import { Y0, X1, X2, YM, YA, YS, YT, DIR_A, DIR_R, TRAYS, PITCH, DEMO, fixedBodies, transferBodies, trayPose, traySize, pocket, occupied, partPose } from './spec.js';
import { createPart } from './product.js';
import { applyFinishes, cabinetDoorMaterial } from './render-finishes.js';
import { addEquipmentDetail } from './equipment-detail.js';

const M = (color, metalness, roughness, o = {}) => new THREE.MeshStandardMaterial({ color, metalness, roughness, ...o });
const MAT = {
  granite: M(0x4b4f55, 0.05, 0.62), frame: M(0x8e98a3, 0.75, 0.42), axis: M(0x2c333c, 0.6, 0.45), plate: M(0xaab3bc, 0.8, 0.35),
  lens: M(0x15181d, 0.55, 0.38), camera: M(0x1f4f86, 0.45, 0.45), light: M(0xd8dde2, 0.4, 0.4), motor: M(0x23272d, 0.55, 0.42),
  steel: M(0xc8ced5, 0.95, 0.25), peek: M(0xc9a36a, 0.05, 0.6), anodized: M(0x3a4654, 0.7, 0.4), carbide: M(0x6c7077, 0.95, 0.2),
  sensor: M(0x6f4bd1, 0.4, 0.4), tray: M(0x1b1e23, 0.1, 0.7), ledG: M(0x1d3a27, 0.3, 0.5), ledR: M(0x3c1d1d, 0.3, 0.5), part: M(0xd0d5da, 0.85, 0.34),
  cabinet: M(0x39424d, 0.35, 0.6), glass: M(0x9fd0ff, 0, 0.1, { transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false }), screen: M(0x0b1b2b, 0.2, 0.3, { emissive: 0x16466e, emissiveIntensity: 0.9 }),
};
const V = (x, y, z) => new THREE.Vector3(x, y, z), UP = V(0, 1, 0);
const beamMat = (color, opacity) => new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending });

function mesh(b) {
  let m;
  if (b.kind === 'box') {
    const w=b.max[0]-b.min[0],h=b.max[1]-b.min[1],d=b.max[2]-b.min[2];
    if(Array.isArray(b.bore)){
      const sh=new THREE.Shape();sh.moveTo(-w/2,-d/2);sh.lineTo(w/2,-d/2);sh.lineTo(w/2,d/2);sh.lineTo(-w/2,d/2);sh.closePath();
      const hole=new THREE.Path();hole.absarc(b.bore[0]-(b.min[0]+b.max[0])/2,b.bore[1]-(b.min[2]+b.max[2])/2,b.bore[2],0,Math.PI*2,true);sh.holes.push(hole);
      const geo=new THREE.ExtrudeGeometry(sh,{depth:h,bevelEnabled:false});geo.rotateX(Math.PI/2);geo.translate(0,h/2,0);m=new THREE.Mesh(geo,MAT[b.mat]);
    }else m = new THREE.Mesh(new THREE.BoxGeometry(w,h,d), MAT[b.mat]);
    m.position.set((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2);
  } else {
    const p0 = V(...b.p0), p1 = V(...b.p1), len = p0.distanceTo(p1);
    const geo = b.square ? new THREE.BoxGeometry(b.r * 1.5, len, b.r * 1.5)
      : b.bore ? new THREE.LatheGeometry([[b.bore, -len / 2], [b.r, -len / 2], [b.r, len / 2], [b.bore, len / 2], [b.bore, -len / 2]].map(p => new THREE.Vector2(...p)), 64)
        : new THREE.CylinderGeometry(b.r, b.r, len, b.r < 5 ? 20 : 48);
    m = new THREE.Mesh(geo, MAT[b.mat]); m.position.copy(p0).lerp(p1, 0.5); m.quaternion.setFromUnitVectors(UP, p1.clone().sub(p0).normalize());
  }
  m.castShadow = m.receiveShadow = true; m.name = b.id; return m;
}
const addBox = (g, mat, w, h, d, x, y, z) => { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.position.set(x, y, z); m.castShadow = m.receiveShadow = true; g.add(m); return m; };

export function createMachine(scene, s) {
  applyFinishes(MAT);
  const root = new THREE.Group(); scene.add(root);
  const fixed = fixedBodies(s), byId = {};
  // 旋轉件與 C 型架各自成群，其餘固定
  const rotor1 = new THREE.Group(), rotor2 = new THREE.Group(), cframe = new THREE.Group();
  rotor1.position.set(X1, 0, 0); rotor2.position.set(X2, 0, 0); root.add(rotor1, rotor2, cframe);
  const jaws = [];
  for (const b of fixed) {
    const m = mesh(b); byId[b.id] = m;
    if (b.rotor === 1) { const pivot = new THREE.Group(); pivot.rotation.y = -Math.atan2(b.p0[2], b.p0[0] - X1); m.position.set(Math.hypot(b.p0[0] - X1, b.p0[2]), m.position.y, 0); m.scale.set(1, 1, 1.6); pivot.add(m); rotor1.add(pivot); jaws.push({ m, r: m.position.x }); }
    else if (b.rotor === 2) { m.position.x -= X2; rotor2.add(m); }
    else if (b.cframe === 1) cframe.add(m);
    else root.add(m);
  }
  byId.chuck.removeFromParent(); byId.chuck.position.x -= X1; rotor1.add(byId.chuck);
  // 夾頭環形低角度光
  const ringLight = new THREE.Mesh(new THREE.TorusGeometry(8.5, 1.1, 12, 48), M(0xffffff, 0, 0.4, { emissive: 0xfff2c4, emissiveIntensity: 0 })); ringLight.rotation.x = Math.PI / 2; ringLight.position.set(X1, YM + 3, 0); root.add(ringLight);

  // ---------------------------------------------- 底櫃、避震腳座、外罩、HMI、三色燈
  const deco = new THREE.Group(), hood = new THREE.Group(), cabinetFaces=[]; root.add(deco, hood);
  for(const [size,at] of [[[4,760,500],[-348,440,0]],[[4,760,500],[348,440,0]],[[692,760,4],[0,440,-248]],[[692,4,492],[0,62,0]]])cabinetFaces.push(addBox(deco,MAT.cabinet,...size,...at));
  for (const x of [-320, 320]) for (const z of [-220, 220]) { addBox(deco, MAT.axis, 50, 60, 50, x, 30, z); const iso = new THREE.Mesh(new THREE.CylinderGeometry(22, 26, Y0 - 42 - 820, 24), MAT.anodized); iso.position.set(x * 0.85, 820 + (Y0 - 42 - 820) / 2, z * 0.85); deco.add(iso); }
  const doorFinish = cabinetDoorMaterial();
  for (const x of [-170, 170]) { const door = addBox(deco, [MAT.cabinet, MAT.cabinet, MAT.cabinet, MAT.cabinet, doorFinish, MAT.cabinet], 320, 640, 4, x, 420, 252); door.name = 'door'; cabinetFaces.push(door,addBox(deco, MAT.steel, 8, 90, 6, x + (x < 0 ? 130 : -130), 470, 256)); }
  const H = 470, top = Y0 - 42 + H;
  for (const x of [-345, 345]) for (const z of [-245, 245]) addBox(hood, MAT.frame, 20, H, 20, x, Y0 - 42 + H / 2, z);
  for (const z of [-245, 245]) addBox(hood, MAT.frame, 710, 20, 20, 0, top, z);
  for (const x of [-345, 345]) addBox(hood, MAT.frame, 20, 20, 470, x, top, 0);
  addBox(hood, MAT.glass, 670, H - 20, 3, 0, Y0 - 42 + H / 2, -245); addBox(hood, MAT.glass, 3, H - 20, 470, -345, Y0 - 42 + H / 2, 0); addBox(hood, MAT.glass, 3, H - 20, 470, 345, Y0 - 42 + H / 2, 0); addBox(hood, MAT.glass, 670, 3, 470, 0, top, 0);
  addBox(hood, MAT.glass, 300, H - 20, 3, 195, Y0 - 42 + H / 2, 245);           // 前門只蓋量測區，托盤側開放人工上下料
  // HMI
  addBox(deco, MAT.frame, 30, 30, 30, 395, top - 120, 200); addBox(deco, MAT.frame, 14, 14, 60, 370, top - 120, 215);
  const hmi = addBox(deco, MAT.axis, 370, 235, 22, 470, top - 110, 270); hmi.rotation.y = -0.45; hmi.rotation.x = -0.12;
  const screenTex = new THREE.CanvasTexture(document.createElement('canvas'));
  screenTex.colorSpace = THREE.SRGBColorSpace; screenTex.anisotropy = 4;
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(340, 205), new THREE.MeshBasicMaterial({ map: screenTex })); screen.position.set(0, 0, 11.6); hmi.add(screen);
  // 三色燈
  const tower = {}; [['red', 0xff3b30], ['yellow', 0xffc400], ['green', 0x2ee67a]].forEach(([k, c], i) => { const m = new THREE.Mesh(new THREE.CylinderGeometry(16, 16, 28, 24), M(c, 0, 0.35, { emissive: c, emissiveIntensity: 0.05, transparent: true, opacity: 0.92 })); m.position.set(330, top + 90 - i * 30, -230); deco.add(m); tower[k] = m; });
  addBox(deco, MAT.frame, 10, 40, 10, 330, top + 25, -230);
  // 校正件座：標準厚度片與環規
  addBox(deco, MAT.anodized, 60, 8, 40, 120, Y0 + 4, 185); for (const [i, c] of [0x8a96a3, 0xb9c1c9, 0xd9dee3].entries()) { const d = new THREE.Mesh(new THREE.CylinderGeometry(7, 7, 1 + i, 24), M(c, 0.9, 0.2)); d.position.set(100 + i * 20, Y0 + 8.5 + i / 2, 185); deco.add(d); }

  // ---------------------------------------------- 托盤與梭台
  const trays = {}, tables = {};
  for (const id of Object.keys(TRAYS)) {
    const t = TRAYS[id], g = traySize(id), grp = new THREE.Group(); root.add(grp);
    addBox(grp, MAT.tray, g.w, g.h, g.d, 0, YT - 4, 0);
    const edge = { IN: 0x4aa8ff, OK: 0x3dd68c, NG1: 0xff8a4d, NG2: 0xff4d4d }[id];
    addBox(grp, M(edge, 0.1, 0.5, { emissive: edge, emissiveIntensity: 0.35 }), g.w, 1.2, 1.5, 0, YT + 0.4, g.d / 2 - 0.75);
    const parts = [];
    for (let i = 0; i < t.cols * t.rows; i++) {
      const q = pocket(id, i), hole = new THREE.Mesh(new THREE.CylinderGeometry(s.od / 2 + 0.15, s.od / 2 + 0.15, 1.02, 32), M(0x07090b, 0, 0.9)); hole.position.set(q.x - t.cx, YT + 0.5, q.lz); grp.add(hole);
      const p = createPart(s); p.position.set(q.x - t.cx, YT, q.lz); grp.add(p); parts.push(p);
    }
    trays[id] = { grp, parts };
  }
  for (const [id, x, w] of [['in', -255, 84], ['out', -115, 186]]) { const g = new THREE.Group(); addBox(g, MAT.anodized, w, YT - 9 - (Y0 + 40), 80, x, (Y0 + 40 + YT - 9) / 2, 0); root.add(g); tables[id] = g; }

  // ---------------------------------------------- 移載
  const tr = {}, ref = { tx: 0, zt: 0, a: 0 };
  for (const b of transferBodies(ref, s)) { const m = mesh(b); m.userData.c0 = m.position.clone(); root.add(m); tr[b.id] = m; }
  const pad = new THREE.Mesh(new THREE.BoxGeometry(3.4, 1.5, 0.8), M(0x20242a, 0, 0.8)); root.add(pad);
  const chain = addBox(root, MAT.axis, 560, 24, 30, -5, Y0 + 62, -215);
  chain.name = 'cableChain';

  // ---------------------------------------------- 工件
  const part = createPart(s, 0xfff0d6); root.add(part);

  // ---------------------------------------------- 光束示意
  const beams = new THREE.Group(); root.add(beams);
  const P1 = V(X1, YA, 0), sheet = (from, color, h = 17) => {
    const d = from.clone().sub(P1), len = d.length(), m = new THREE.Mesh(new THREE.PlaneGeometry(len, h), beamMat(color, 0.32));
    m.position.copy(P1).addScaledVector(d, 0.5); m.rotation.y = -Math.atan2(d.z, d.x); beams.add(m); return m;
  };
  const beam = {
    A: [sheet(V(X1 + DIR_A[0] * 60, YA, DIR_A[2] * 60), 0xffffff, 16), sheet(V(X1 + DIR_R[0] * 38, YA, DIR_R[2] * 38), 0xff3b30), sheet(V(X1, YA, 36), 0x39e27a), sheet(V(X1 + DIR_A[0] * 58, YA + 0.3, DIR_A[2] * 58), 0x4a8bff, 15)],
    B: [], C: [], CF: [],
  };
  { const m = new THREE.Mesh(new THREE.CylinderGeometry(9, 9, 105, 32, 1, true), beamMat(0x8dff8a, 0.22)); m.rotation.z = Math.PI / 2; m.position.set(X1 - 7.5, YA, 0); beams.add(m); beam.B.push(m); }
  { const m = new THREE.Mesh(new THREE.CylinderGeometry(4, 4, 80, 32, 1, true), beamMat(0xfff0b0, 0.3)); m.position.set(X1, YM + 40, 0); beams.add(m); beam.C.push(m); }
  const upY = YS + s.base + s.wd, coneUp = new THREE.Mesh(new THREE.CylinderGeometry(.08,.08,s.wd,12), beamMat(0xa77bff, 0.45));
  coneUp.rotation.x = Math.PI; coneUp.position.set(0, upY - s.wd / 2, 0);
  const coneDn = new THREE.Mesh(new THREE.CylinderGeometry(.08,.08,15,12), beamMat(0xa77bff, 0.45)); coneDn.position.set(0, YS - 7.5, 0);
  const cf = new THREE.Group(); cf.add(coneUp, coneDn); cf.position.x = X2; beams.add(cf); beam.CF.push(cf);
  // 螺旋掃描軌跡（隨工件旋轉）
  const N = 600, spiral = new THREE.Line(new THREE.BufferGeometry().setAttribute('position', new THREE.BufferAttribute(new Float32Array(N * 3), 3)), new THREE.LineBasicMaterial({ color: 0xd9b8ff, transparent: true, opacity: 0.95 }));
  { const a = spiral.geometry.attributes.position; for (let i = 0; i < N; i++) { const u = i / (N - 1), r = s.scan.r0 + (s.scan.r1 - s.scan.r0) * u, th = -u * s.scan.rev * Math.PI * 2; a.setXYZ(i, r * Math.cos(th), 0, r * Math.sin(th)); } }
  spiral.position.y = s.base + 0.01; part.add(spiral); spiral.frustumCulled = false;

  // ---------------------------------------------- 套用狀態
  const details=addEquipmentDetail({root,deco,byId,cabinetFaces,rotor1,rotor2,s});
  const state = { last: null };
  function apply(S) {
    state.last = S;
    rotor1.rotation.y = -S.th1; rotor2.rotation.y = -S.th2; cframe.position.x = S.r2; cf.position.x = X2 + S.r2;
    byId.sensorUp.position.y = YS + s.base + s.wd + 35 + S.headLift;
    details.update(S);
    for (const j of jaws) j.m.position.x = j.r + S.jaw * 1.2;
    for (const id of Object.keys(TRAYS)) { const p = trayPose(id, S), occ = new Set(occupied(id, S)); trays[id].grp.position.set(p.x, 0, p.z); trays[id].parts.forEach((m, i) => { m.visible = occ.has(i) && !(id === 'IN' && i === DEMO.k) && !(S.loc === 'out:' + id && i === DEMO.filled[id]); }); }
    tables.in.position.z = S.inZ; tables.out.position.z = S.outZ;
    for (const [id, m] of Object.entries(tr)) { const c = m.userData.c0; m.position.set(c.x + S.tx, id === 'zcol' || id === 'carriage' ? c.y : c.y + S.zt, id === 'blade' || id === 'armBody' ? c.z - S.a : c.z); }
    pad.position.set(S.tx, S.zt + 1.85, -s.padR - S.a - 0.4);
    pad.material.emissive.setHex(S.vac ? 0x1d7dff : 0); pad.material.emissiveIntensity = S.vac ? 0.9 : 0;
    const p = partPose(S, s); part.position.set(p.x, p.y, p.z); part.rotation.y = -p.rot;
    for (const [k, list] of Object.entries(beam)) for (const m of list) m.visible = S.optic === k;
    spiral.visible = S.loc === 'seat' && (S.spiral[0] > 0 || S.spiral[1] > 0);
    const sp = S.scanNo ? S.spiral[1] : S.spiral[0]; spiral.geometry.setDrawRange(0, Math.max(2, Math.round(N * sp)));
    byId.lightG.material = S.optic === 'A' ? LIT.g : MAT.ledG; byId.lightR.material = S.optic === 'A' ? LIT.r : MAT.ledR;
    byId.backlight.material = S.optic === 'B' ? LIT.b : MAT.light; ringLight.material.emissiveIntensity = S.optic === 'C' ? 2.2 : 0;
  }
  const LIT = { g: M(0x39e27a, 0, 0.4, { emissive: 0x39e27a, emissiveIntensity: 1.6 }), r: M(0xff3b30, 0, 0.4, { emissive: 0xff3b30, emissiveIntensity: 1.6 }), b: M(0xb9ffb0, 0, 0.4, { emissive: 0x8dff8a, emissiveIntensity: 1.4 }) };
  function setTower(color) { for (const [k, m] of Object.entries(tower)) m.material.emissiveIntensity = k === color ? 1.8 : 0.05; }
  function drawScreen(lines, color = '#7fe0b4') {
    const c = screenTex.image; c.width = 680; c.height = 410; const g = c.getContext('2d');
    g.fillStyle = '#0a1622'; g.fillRect(0, 0, 680, 410); g.fillStyle = '#12304a'; g.fillRect(0, 0, 680, 54);
    g.fillStyle = '#dcecf7'; g.font = '600 26px "Microsoft JhengHei",sans-serif'; g.fillText(lines[0], 18, 36);
    g.font = '22px "Microsoft JhengHei",sans-serif'; lines.slice(1).forEach((t, i) => { g.fillStyle = i === 0 ? color : '#a9c0d2'; g.fillText(t, 18, 96 + i * 38); });
    screenTex.needsUpdate = true;
  }
  return { root, hood, part, apply, setTower, drawScreen, partWorld: () => part.position.clone().add(V(0, s.len / 2, 0)), byId, trays, details };
}
