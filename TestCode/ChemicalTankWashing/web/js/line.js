// 產線設備：棧板站、三軸龍門＋翻轉夾爪、橫躺輸送、貼標讀碼站、翻桶機、立放直線輸送（開蓋→清洗→裝填區）、圍籬與控制櫃。
import * as THREE from 'three';
import { PALLET_STATION, PALLET, GANTRY, LYING, LABEL, UPENDER, UPRIGHT, DECAP, DRUM, FENCE, GANTRY_FENCE, FOOTPRINTS, ROOM } from './layout.js';
import { MAT, box, boxAt, cyl, rod, plate, D2R } from './parts.js';
import { drumJaws } from './drum.js';

export function createLine(scene) {
  const group = new THREE.Group(); group.name = 'line'; scene.add(group);
  const fences = new THREE.Group(); group.add(fences);

  // ---------------------------------------------------------------- 棧板站
  const ps = PALLET_STATION;
  box(group, 1300, ps.stand, 1300, MAT.steelDark, ps.x, ps.stand / 2, ps.z);
  for (const [dx, dz] of [[-660, 300], [660, 300], [-660, -300], [660, -300]]) box(group, 40, 200, 300, MAT.yellow, ps.x + dx, ps.stand + 100, ps.z + dz);
  box(group, 30, 30, 260, MAT.steelOrange, ps.x, ps.stand + 15, ps.z + 660);           // 後止擋

  // ---------------------------------------------------------------- 龍門（雙 X 樑 → 橫樑沿 X → 台車沿 Z → 兩段伸縮 Z → 翻轉軸 → 夾爪）
  const g = GANTRY, [p0, p1, p2] = g.posts;
  for (const [x, z] of g.posts) box(group, 200, g.beamY + 100, 200, MAT.steelBlue, x, (g.beamY + 100) / 2, z);
  for (const z of [p0[1], p2[1]]) box(group, p1[0] - p0[0] + 200, 220, 200, MAT.steelBlue, (p0[0] + p1[0]) / 2, g.beamY + 210, z);
  for (const z of [p0[1], p2[1]]) box(group, p1[0] - p0[0], 40, 60, MAT.steel, (p0[0] + p1[0]) / 2, g.beamY + 340, z);
  const bridge = new THREE.Group(); group.add(bridge);
  box(bridge, 260, 200, p2[1] - p0[1] + 200, MAT.steelOrange, 0, g.beamY + 460, (p0[1] + p2[1]) / 2);
  const trolley = new THREE.Group(); bridge.add(trolley);
  box(trolley, 420, 300, 360, MAT.steelDark, 0, g.beamY + 300, 0);
  box(trolley, 240, 300, 240, MAT.black, 0, g.beamY + 520, -120);                       // Z 軸馬達
  const z1 = new THREE.Group(), z2 = new THREE.Group(); trolley.add(z1); trolley.add(z2);
  box(z1, 220, 1300, 220, MAT.alu, 0, 650, 0);
  box(z2, 160, 1300, 160, MAT.steel, 0, 800, 0);
  const tilt = new THREE.Group(); z2.add(tilt);                                          // 翻轉軸（世界 Z 向）
  cyl(z2, 140, 360, MAT.black, 0, -40, 0, 'z');
  box(z2, 260, 120, 300, MAT.steelDark, 0, 40, 0);
  box(tilt, 420, 60, 760, MAT.steelDark, 0, -100, 0);
  for (const s of [-1, 1]) box(tilt, 60, 560, 60, MAT.steelDark, 0, -390, s * 360);
  const jawFrame = new THREE.Group(); jawFrame.position.y = -g.hang; jawFrame.rotation.y = Math.PI / 2; tilt.add(jawFrame);   // 爪在 ±Z（局部 ±X）
  const gJaws = drumJaws(jawFrame);
  const gantryPivot = new THREE.Object3D(); tilt.add(gantryPivot);
  // 拖鏈
  box(group, p1[0] - p0[0], 80, 160, MAT.black, (p0[0] + p1[0]) / 2, g.beamY + 420, p0[1] - 220);

  // ---------------------------------------------------------------- 橫躺輸送：水平沙漏形（V 槽）滾輪，滾輪軸橫跨輸送方向
  // 桶身落在 V 槽兩側斜面（半角 LYING.vee）；切點 z = R·sinα，由此反推滾輪軸高
  const ly = LYING, va = ly.vee * D2R, r0 = 40, halfL = 260;
  const axisY = ly.y - DRUM.R * Math.cos(va) - (DRUM.R * Math.sin(va)) * Math.tan(va) - r0;
  const hourglass = new THREE.LatheGeometry([[0, -halfL], [r0 + halfL * Math.tan(va), -halfL], [r0, 0], [r0 + halfL * Math.tan(va), halfL], [0, halfL]].map(([r, y]) => new THREE.Vector2(r, y)), 28);
  for (let x = ly.x0 + 165; x < ly.x1; x += 330) {
    if (Math.abs(x - LABEL.x) < 620) continue;              // 標籤站改用旋轉輥
    const r = new THREE.Mesh(hourglass, MAT.roller); r.rotation.x = Math.PI / 2; r.position.set(x, axisY, ly.z); r.castShadow = r.receiveShadow = true; group.add(r);
    for (const s of [-1, 1]) cyl(group, 12, 60, MAT.steelDark, x, axisY, ly.z + s * (halfL + 30), 'z', 8);
  }
  for (const s of [-1, 1]) box(group, ly.x1 - ly.x0, 140, 50, MAT.steel, (ly.x0 + ly.x1) / 2, axisY, ly.z + s * (halfL + 60));
  for (let x = ly.x0 + 100; x <= ly.x1; x += 1150) for (const s of [-1, 1]) box(group, 70, axisY - 70, 70, MAT.steelDark, x, (axisY - 70) / 2, ly.z + s * (halfL + 60));
  box(group, ly.x1 - ly.x0, 18, 120, MAT.yellow, (ly.x0 + ly.x1) / 2, axisY - 100, ly.z + halfL + 160);
  // 標籤站旋轉輥（取代該段 V 輥，兩支主動輥平行於桶軸）
  const lab = LABEL;
  const rotRollers = [];
  for (const s of [-1, 1]) { const r = cyl(group, 70, 1100, MAT.belt, lab.x, ly.y - DRUM.R - 25, ly.z + s * 220, 'x', 20); rotRollers.push(r); }
  box(group, 1200, 120, 700, MAT.steelDark, lab.x, ly.y - DRUM.R - 140, ly.z);

  // ---------------------------------------------------------------- 貼標機（印字貼標頭，南側推出貼附）＋讀碼相機
  const st = new THREE.Group(); st.position.set(lab.x, 0, lab.standZ); group.add(st);
  box(st, 600, 900, 500, MAT.cabinet, 0, 450, 200);
  box(st, 560, 420, 440, MAT.steelDark, 0, 1110, 160);                                  // 印字引擎
  box(st, 30, 250, 300, MAT.screen, 290, 1150, 160);
  cyl(st, 120, 80, MAT.cap, -200, 1200, 340, 'x');                                     // 標籤捲
  const padRail = box(st, 80, 60, 480, MAT.alu, 0, ly.y, -120);
  const pad = new THREE.Group(); st.add(pad);
  box(pad, 140, 180, 30, MAT.black, 0, ly.y, 0);
  const padLabel = box(pad, 100, 150, 4, MAT.cap, 0, ly.y, -17); padLabel.visible = false;
  const camLabel = new THREE.Group(); camLabel.position.set(lab.x, lab.camY, ly.z); group.add(camLabel);
  box(camLabel, 90, 90, 140, MAT.black, 0, 0, 0);
  cyl(camLabel, 30, 70, MAT.steelDark, 0, -80, 0);
  const barLight = box(camLabel, 520, 40, 80, MAT.cap, 0, -150, 0);
  rod(group, [lab.x - 700, 0, ly.z - 520], [lab.x - 700, lab.camY + 100, ly.z - 520], 45, MAT.alu);
  boxAt(group, [lab.x - 700, lab.camY + 60, ly.z - 520], [lab.x, lab.camY + 120, ly.z], MAT.alu);
  const labelCam = new THREE.PerspectiveCamera(32, 1.5, 50, 6000); labelCam.position.set(lab.x, lab.camY - 200, ly.z); labelCam.lookAt(lab.x, ly.y, ly.z); group.add(labelCam);
  const labelFlash = new THREE.SpotLight(0xffffff, 0, 2500, .55, .5, 1); labelFlash.position.set(lab.x, lab.camY - 160, ly.z); labelFlash.target.position.set(lab.x, ly.y, ly.z); group.add(labelFlash, labelFlash.target);

  // ---------------------------------------------------------------- 翻桶機
  const [ux, uy, uz] = UPENDER.pivot;
  box(group, 1600, 220, 900, MAT.steelDark, ux - 300, 110, uz);
  for (const s of [-1, 1]) cyl(group, 90, 120, MAT.steelBlue, ux, uy, uz + s * 420, 'z');
  for (const s of [-1, 1]) box(group, 120, uy, 120, MAT.steelBlue, ux, uy / 2, uz + s * 420);
  const cradle = new THREE.Group(); cradle.position.set(ux, uy, uz); group.add(cradle);
  box(cradle, 1000, 40, 640, MAT.steel, -500, -20, 0);                                   // 床面（桶身下方）
  for (const s of [-1, 1]) box(cradle, 980, 40, 120, MAT.pu, -500, 10, s * 230);
  box(cradle, 40, 640, 760, MAT.steel, 20, 320, 0);                                      // 桶底靠板（翻後成為承載面）
  for (let k = 0; k < 4; k++) cyl(cradle, 30, 700, MAT.roller, -10, 80 + k * 150, 0, 'z', 12);
  const upClamp = [];
  for (const s of [-1, 1]) { const c = box(cradle, 700, 160, 30, MAT.yellow, -500, DRUM.R, s * (DRUM.R + 60)); upClamp.push({ c, s }); }
  const cyl1 = rod(group, [ux - 900, 220, uz], [ux - 600, 600, uz], 50, MAT.steel);

  // ---------------------------------------------------------------- 立放輸送：一路往南，取桶位與放回位不設側導引
  const up = UPRIGHT;
  for (let z = up.z0 + 450; z < up.z1; z += 120) cyl(group, 30, 700, MAT.roller, up.x, up.top - 32, z, 'x', 12);
  for (const s of [-1, 1]) box(group, 50, 150, up.z1 - up.z0 - 450, MAT.steel, up.x + s * 380, up.top - 70, (up.z0 + 450 + up.z1) / 2);
  for (let z = up.z0 + 600; z < up.z1; z += 900) for (const s of [-1, 1]) box(group, 60, up.top - 140, 60, MAT.steelDark, up.x + s * 380, (up.top - 140) / 2, z);
  for (const [z0, z1] of [[up.z0 + 450, up.pick - 350], [up.pick + 350, up.place - 350], [up.place + 350, up.z1]])
    for (const s of [-1, 1]) box(group, 30, 120, z1 - z0, MAT.yellow, up.x + s * 340, up.top + 160, (z0 + z1) / 2);
  for (const z of [up.pick + DRUM.R + 20, up.place + DRUM.R + 20]) box(group, 120, 60, 40, MAT.steelOrange, up.x + 300, up.top + 40, z);   // 定位擋塊
  // 放回位秤重段：輸送段架在四顆荷重元上，旁邊有秤重顯示器
  box(group, 780, 30, 760, MAT.steelDark, up.x, 40, up.place);
  for (const [dx, dz] of [[-330, -330], [330, -330], [-330, 330], [330, 330]]) cyl(group, 40, 60, MAT.steelBlue, up.x + dx, 85, up.place + dz);
  const scaleScreen = box(group, 40, 200, 320, MAT.screen, up.x + 520, 1150, up.place); box(group, 60, 1050, 60, MAT.steelDark, up.x + 520, 525, up.place);
  box(group, 700, 40, 40, MAT.steelOrange, up.x, up.top + 40, up.z1 - 20);
  plate(group, ['取桶位'], 420, 110, [up.x - 420, up.top + 420, up.pick], -Math.PI / 2, { w: 512, h: 130 });
  plate(group, ['放回位＋秤重'], 520, 110, [up.x - 420, up.top + 420, up.place], -Math.PI / 2, { w: 512, h: 110 });
  plate(group, ['→ 裝填區（下一站）'], 900, 160, [up.x - 420, 1150, up.handoff - 200], -Math.PI / 2, { w: 640, h: 110 });

  // ---------------------------------------------------------------- 自動開蓋站（相機定位 → 旋轉台對位 → 伺服鎖付軸反轉拆蓋）
  const dc = DECAP;
  for (const [dx, dz] of [[-650, -400], [650, -400], [-650, 400], [650, 400]]) box(group, 100, 2600, 100, MAT.steelBlue, up.x + dx, 1300, dc.z + dz);
  for (const dz of [-400, 400]) box(group, 1400, 120, 100, MAT.steelBlue, up.x, 2560, dc.z + dz);
  const turntable = cyl(group, 320, 40, MAT.steelDark, up.x, up.top - 18, dc.z, 'y', 32);
  for (const s of [-1, 1]) box(group, 40, 120, 500, MAT.yellow, up.x + s * (DRUM.R + 110), up.top + 300, dc.z);
  const dcClamp = [];
  for (const s of [-1, 1]) { const c = box(group, 40, 160, 400, MAT.pu, up.x + s * (DRUM.R + 70), up.top + 300, dc.z); dcClamp.push({ c, s }); }
  const dBridge = new THREE.Group(); group.add(dBridge);
  box(dBridge, 1400, 100, 160, MAT.alu, up.x, 2440, 0);
  const dCar = new THREE.Group(); dBridge.add(dCar);
  box(dCar, 260, 220, 220, MAT.steelDark, 0, 2440, 0);
  const dZ = new THREE.Group(); dCar.add(dZ);
  box(dZ, 120, 900, 120, MAT.alu, 0, 450, 0);
  const spindles = {};
  for (const [k, dx, r] of [['big', -90, DRUM.big.r + 8], ['small', 90, DRUM.small.r + 8]]) {
    cyl(dZ, 55, 200, MAT.black, dx, 120, 0);
    const sock = new THREE.Group(); sock.position.set(dx, 0, 0); dZ.add(sock);
    cyl(sock, r, 60, MAT.steel, 0, 30, 0, 'y', 18);
    for (let i = 0; i < 4; i++) box(sock, 8, 50, 14, MAT.black, r * Math.cos(i * Math.PI / 2), 30, r * Math.sin(i * Math.PI / 2));
    spindles[k] = sock;
  }
  const camDecap = new THREE.Group(); camDecap.position.set(up.x + 420, dc.camY, dc.z); group.add(camDecap);
  box(camDecap, 90, 140, 90, MAT.black, 0, 0, 0);
  const ringLight = new THREE.Mesh(new THREE.TorusGeometry(70, 14, 8, 30), MAT.cap); ringLight.rotation.x = Math.PI / 2; ringLight.position.y = -90; camDecap.add(ringLight);
  const decapCam = new THREE.PerspectiveCamera(30, 1.5, 50, 6000); decapCam.position.set(up.x + 420, dc.camY - 100, dc.z); decapCam.lookAt(up.x, up.top + DRUM.H, dc.z); group.add(decapCam);
  const decapFlash = new THREE.SpotLight(0xffffff, 0, 2500, .5, .5, 1); decapFlash.position.copy(decapCam.position); decapFlash.target.position.set(up.x, up.top + DRUM.H, dc.z); group.add(decapFlash, decapFlash.target);
  // 桶蓋收集桶（斜槽）
  const bin = new THREE.Group(); bin.position.set(dc.bin.x, 0, dc.bin.z); group.add(bin);
  cyl(bin, 230, 700, MAT.ppSolid, 0, 350, 0, 'y', 24, 200);
  cyl(bin, 210, 10, MAT.hole, 0, 702, 0);
  const capPile = []; for (let i = 0; i < 8; i++) { const c = cyl(bin, i % 2 ? 18 : 36, 16, MAT.cap, (i % 3 - 1) * 70, 640 + Math.floor(i / 3) * 18, ((i * 7) % 5 - 2) * 40); c.visible = false; capPile.push(c); }
  plate(group, ['桶蓋收集'], 380, 110, [dc.bin.x, 820, dc.bin.z + 232], 0, { w: 512, h: 150 });

  // ---------------------------------------------------------------- 圍籬
  const fencePath = (pts, closed, gaps = []) => {
    const list = closed ? [...pts, pts[0]] : pts;
    for (let i = 1; i < list.length; i++) {
      const [ax, az] = list[i - 1], [bx, bz] = list[i], L = Math.hypot(bx - ax, bz - az), n = Math.max(1, Math.round(L / 1500));
      for (let k = 0; k < n; k++) {
        const t0 = k / n, t1 = (k + 1) / n, x0 = ax + (bx - ax) * t0, z0 = az + (bz - az) * t0, x1 = ax + (bx - ax) * t1, z1 = az + (bz - az) * t1;
        const mx = (x0 + x1) / 2, mz = (z0 + z1) / 2;
        if (gaps.some(([gx, gz, w]) => Math.hypot(mx - gx, mz - gz) < w)) continue;
        const seg = Math.hypot(x1 - x0, z1 - z0), yaw = Math.atan2(-(z1 - z0), x1 - x0);
        const panel = new THREE.Mesh(new THREE.PlaneGeometry(seg - 60, 1800), MAT.mesh); panel.position.set(mx, 1000, mz); panel.rotation.y = yaw; fences.add(panel);
        const frame = box(fences, seg - 60, 30, 30, MAT.fence, mx, 1900, mz); frame.rotation.y = yaw;
        box(fences, 60, 2000, 60, MAT.fence, x0, 1000, z0);
      }
      box(fences, 60, 2000, 60, MAT.fence, bx, 1000, bz);
    }
  };
  fencePath(FENCE, false, [[UPRIGHT.x, FENCE[1][1], 600], [UPRIGHT.x, FENCE[3][1], 600]]);
  fencePath(GANTRY_FENCE, true, [[PALLET_STATION.x, 8950, 800], [6700, LYING.z, 600]]);
  // 光柵（入口）
  for (const [x, z, w, ax] of [[PALLET_STATION.x, 8950, 1400, 'x'], [UPRIGHT.x, FENCE[1][1], 900, 'x'], [UPRIGHT.x, FENCE[3][1], 900, 'x'], [6700, LYING.z, 900, 'z']])
    for (const s of [-1, 1]) box(fences, 50, 1700, 50, MAT.amber, ax === 'x' ? x + s * w / 2 : x, 850, ax === 'x' ? z : z + s * w / 2);

  // ---------------------------------------------------------------- 控制櫃與人機
  const cab = (key, color, name) => { const [x0, z0, x1, z1, h] = FOOTPRINTS[key]; box(group, x1 - x0, h, z1 - z0, color, (x0 + x1) / 2, h / 2, (z0 + z1) / 2); plate(group, name, Math.min(700, x1 - x0 - 60), 160, [(x0 + x1) / 2, h - 150, z0 - 2], Math.PI, { w: 512, h: 120 }); };
  cab('robotCtrl', MAT.cabinet, ['R-30iB Plus']);
  cab('panel', MAT.cabinet, ['主控盤 PLC']);
  const [hx0, hz0, hx1, hz1] = FOOTPRINTS.hmi;
  box(group, 150, 1100, 150, MAT.steelDark, (hx0 + hx1) / 2, 550, (hz0 + hz1) / 2);
  const hmi = box(group, 380, 280, 50, MAT.screen, (hx0 + hx1) / 2, 1250, (hz0 + hz1) / 2); hmi.rotation.x = -.35;
  // 三色燈
  const tower = new THREE.Group(); tower.position.set(FENCE[1][0] + 100, 2000, FENCE[1][1] + 100); group.add(tower);
  const lamps = [MAT.red, MAT.amber, MAT.green].map((m, i) => cyl(tower, 45, 90, m.clone(), 0, 200 - i * 95, 0));
  rod(group, [FENCE[1][0] + 100, 0, FENCE[1][1] + 100], [FENCE[1][0] + 100, 1950, FENCE[1][1] + 100], 25, MAT.steel);

  return {
    group, fences, labelCam, decapCam, gantryPivot, cradle, padLabel,
    setGantry({ x, z, y, tilt: t, jaw }) {
      bridge.position.x = x; trolley.position.z = z;
      // 兩段伸縮：內管原點即翻轉軸；外管底端隨行程移動，兩端都保持與內管、台車重疊
      z2.position.y = y;
      z1.position.y = 2050 + (y - g.placeY) * 250 / (g.safeY - g.placeY);
      tilt.rotation.z = t * Math.PI / 2;
      gJaws.set(jaw);
    },
    setLabeler({ pad: p, print, spin, flash }) {
      pad.position.set(0, 0, -120 - p * (lab.standZ - LYING.z - DRUM.R - 135));
      padLabel.visible = print > .5;
      for (const r of rotRollers) r.rotation.x = spin * 4.2;
      labelFlash.intensity = flash ? 900 : 0; barLight.material = flash ? MAT.green : MAT.cap;
    },
    setUpender({ tilt: t, clamp }) { cradle.rotation.z = -t * Math.PI / 2; for (const { c, s } of upClamp) c.position.z = s * (DRUM.R + 60 + (1 - clamp) * 80); },
    setDecap({ hx, hz, hy, spinBig, spinSmall, flash, clamp, table, caps }) {
      dBridge.position.z = DECAP.z + hz; dCar.position.x = up.x + hx; dZ.position.y = hy;
      spindles.big.rotation.y = spinBig * Math.PI * 2 * 2.5; spindles.small.rotation.y = spinSmall * Math.PI * 2 * 2.5;
      decapFlash.intensity = flash ? 900 : 0; ringLight.material = flash ? MAT.green : MAT.cap;
      for (const { c, s } of dcClamp) c.position.x = up.x + s * (DRUM.R + 70 + (1 - clamp) * 60);
      turntable.rotation.y = table * D2R;
      capPile.forEach((c, i) => { c.visible = i < caps; });
    },
    setScale(on) { scaleScreen.material = on ? MAT.green : MAT.screen; },
    setTower(state) { lamps.forEach((l, i) => { l.material.emissiveIntensity = (state === ['fault', 'wait', 'run'][i]) ? 1.2 : .05; }); },
    socket: k => spindles[k],
  };
}
