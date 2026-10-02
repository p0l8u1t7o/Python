// 產線設備：棧板站、三軸龍門＋翻轉夾爪、橫躺輸送、貼標讀碼站、翻桶機、立放直線輸送（開蓋→清洗→裝填區）、圍籬與控制櫃。
import * as THREE from 'three';
import { PALLET_STATION, PALLET, GANTRY, LYING, LABEL, UPENDER, UPRIGHT, DECAP, DRUM, FENCE, FENCE_GATES, GANTRY_FENCE, FOOTPRINTS, ROOM, WEIGH } from './layout.js';
import { MAT, box, boxAt, cyl, rod, plate, D2R } from '@core/geom/parts.js';
import { drumJaws } from './drum.js';
import { bolts, foot, motor, sensor, cabinetDetails } from '@core/geom/hardware.js';

export function createLine(scene) {
  const group = new THREE.Group(); group.name = 'line'; scene.add(group);
  const fences = new THREE.Group(); group.add(fences);

  // ---------------------------------------------------------------- 棧板站
  const ps = PALLET_STATION;
  box(group, 1300, ps.stand, 1300, MAT.steelDark, ps.x, ps.stand / 2, ps.z);
  for (const [dx, dz] of [[-660, 300], [660, 300], [-660, -300], [660, -300]]) box(group, 40, 200, 300, MAT.yellow, ps.x + dx, ps.stand + 100, ps.z + dz);
  box(group, 30, 30, 260, MAT.steelOrange, ps.x, ps.stand + 17, ps.z + 660);           // 後止擋

  // ---------------------------------------------------------------- 龍門（雙 X 樑 → 橫樑沿 X → 台車沿 Z → 兩段伸縮 Z → 翻轉軸 → 夾爪）
  const g = GANTRY, [p0, p1, p2] = g.posts;
  for (const [x, z] of g.posts) box(group, 200, g.beamY + 100, 200, MAT.steelBlue, x, (g.beamY + 100) / 2, z);
  for (const z of [p0[1], p2[1]]) box(group, p1[0] - p0[0] + 200, 220, 200, MAT.steelBlue, (p0[0] + p1[0]) / 2, g.beamY + 210, z);
  for (const z of [p0[1], p2[1]]) box(group, p1[0] - p0[0], 40, 60, MAT.steel, (p0[0] + p1[0]) / 2, g.beamY + 340, z);
  // 橫樑為雙樑（中心距 400，間隙 300），Z 軸伸縮管從兩樑之間穿下
  const bridge = new THREE.Group(); group.add(bridge);
  for (const s of [-1, 1]) box(bridge, 100, 200, p2[1] - p0[1] + 200, MAT.steelOrange, s * 200, g.beamY + 460, (p0[1] + p2[1]) / 2);
  const trolley = new THREE.Group(); bridge.add(trolley);
  box(trolley, 560, 60, 360, MAT.steelDark, 0, g.beamY + 590, 0);                         // 跨在雙樑上的台車板
  for (const s of [-1, 1]) box(trolley, 30, 210, 300, MAT.steelDark, s * 130, g.beamY + 455, 0);   // 穿過間隙的吊板
  box(trolley, 420, 300, 360, MAT.steelDark, 0, g.beamY + 200, 0);                       // 樑下導向座
  box(trolley, 240, 300, 240, MAT.black, 0, g.beamY + 770, -300);                        // Z 軸馬達（避開伸縮管）
  const z1 = new THREE.Group(), z2 = new THREE.Group(); trolley.add(z1); trolley.add(z2); z2.userData.nested = z1;   // 兩段伸縮：內管套在外管內
  box(z1, 220, 1300, 220, MAT.alu, 0, 650, 0);
  box(z2, 160, 1300, 160, MAT.steel, 0, 800, 0);
  const tilt = new THREE.Group(); z2.add(tilt);                                          // 翻轉軸（世界 Z 向）
  cyl(z2, 140, 360, MAT.black, 0, -40, 0, 'z');
  box(z2, 260, 120, 300, MAT.steelDark, 0, 40, 0);
  box(tilt, 420, 60, 760, MAT.steelDark, 0, -100, 0);
  for (const s of [-1, 1]) box(tilt, 60, 560, 60, MAT.steelDark, 0, -390, s * 360);
  const jawFrame = new THREE.Group(); jawFrame.position.y = -g.hang; jawFrame.rotation.y = Math.PI / 2; tilt.add(jawFrame);   // 爪在 ±Z（局部 ±X）
  const gJaws = drumJaws(jawFrame, null, g.jawOpen);
  const gantryPivot = new THREE.Object3D(); tilt.add(gantryPivot);
  // 拖鏈
  box(group, p1[0] - p0[0], 80, 160, MAT.black, (p0[0] + p1[0]) / 2, g.beamY + 420, p0[1] - 220);

  // ---------------------------------------------------------------- 橫躺輸送：水平沙漏形（V 槽）滾輪，滾輪軸橫跨輸送方向
  // 桶身落在 V 槽兩側斜面（半角 LYING.vee）；切點 z = R·sinα，由此反推滾輪軸高
  const rollers = [], ly = LYING, va = ly.vee * D2R, r0 = 40, halfL = 260;
  const axisY = ly.y - DRUM.envelopeR * Math.cos(va) - (DRUM.envelopeR * Math.sin(va)) * Math.tan(va) - r0;
  const hourglass = new THREE.LatheGeometry([[0, -halfL], [r0 + halfL * Math.tan(va), -halfL], [r0, 0], [r0 + halfL * Math.tan(va), halfL], [0, halfL]].map(([r, y]) => new THREE.Vector2(r, y)), 28);
  for (let x = ly.x0 + 200; x + 170 <= ly.x1; x += 330) {   // 第一支避開龍門翻轉頂板（放料時翻轉軸在 X 5283）
    if (Math.abs(x - LABEL.x) < 620) continue;              // 標籤站改用旋轉輥
    const r = new THREE.Mesh(hourglass, MAT.roller); r.rotation.x = Math.PI / 2; r.position.set(x, axisY, ly.z); r.castShadow = r.receiveShadow = true; group.add(r); rollers.push({ mesh: r, axis: 'z', radius: 100, along: x });
    for (const s of [-1, 1]) cyl(group, 12, 60, MAT.steelDark, x, axisY, ly.z + s * (halfL + 30), 'z', 8);
  }
  for (const s of [-1, 1]) box(group, ly.x1 - ly.x0, 140, 50, MAT.steel, (ly.x0 + ly.x1) / 2, axisY, ly.z + s * (halfL + 60));
  for (let x = ly.x0 + 100; x <= ly.x1; x += 1150) for (const s of [-1, 1]) box(group, 70, axisY - 70, 70, MAT.steelDark, x, (axisY - 70) / 2, ly.z + s * (halfL + 60));
  box(group, ly.x1 - ly.x0, 18, 120, MAT.yellow, (ly.x0 + ly.x1) / 2, axisY - 100, ly.z + halfL + 160);
  // 標籤站旋轉輥（取代該段 V 輥，兩支主動輥平行於桶軸）
  const lab = LABEL;
  const rotRollers = [];
  for (const s of [-1, 1]) { const r = cyl(group, 70, 1100, MAT.belt, lab.x, ly.y - Math.sqrt((DRUM.envelopeR + 70) ** 2 - 220 ** 2), ly.z + s * 220, 'x', 20); rotRollers.push(r); }
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
  // 讀碼／定位相機：桶頂端西側斜上方，同一張影像看到兩個桶塞（定位）與桶身上方的標籤（貼後檢查）
  const [cx, cy, cz] = lab.cam.pos, camTarget = new THREE.Vector3(...lab.cam.target);
  const camLabel = new THREE.Group(); camLabel.position.set(cx, cy, cz); camLabel.lookAt(camTarget); group.add(camLabel);
  box(camLabel, 90, 90, 140, MAT.black, 0, 0, 0);
  cyl(camLabel, 30, 70, MAT.steelDark, 0, 0, 100, 'z');
  const barLight = box(camLabel, 520, 40, 80, MAT.cap, 0, -110, 60);                  // 側打條形光，避免標籤反光
  // 支架立在龍門圍籬外（X > 6700），避開龍門東側立柱與翻桶擺動範圍
  rod(group, [cx + 100, 0, cz - 520], [cx + 100, cy + 150, cz - 520], 45, MAT.alu);
  boxAt(group, [cx + 60, cy + 110, cz - 520], [cx + 140, cy + 170, cz], MAT.alu);
  rod(group, [cx + 100, cy + 140, cz], [cx, cy, cz], 25, MAT.alu);
  // 虛擬相機放在鏡頭前緣（機身中心往目標 150 mm），否則子畫面會拍到自己的鏡筒
  const labelCam = new THREE.PerspectiveCamera(lab.cam.fov, 1.5, 50, 6000);
  labelCam.position.set(cx, cy, cz).addScaledVector(camTarget.clone().sub(labelCam.position).normalize(), 150); labelCam.lookAt(camTarget); group.add(labelCam);
  const labelFlash = new THREE.SpotLight(0xffffff, 0, 3000, .7, .5, 1); labelFlash.position.set(cx, cy, cz); labelFlash.target.position.copy(camTarget); group.add(labelFlash, labelFlash.target);

  // ---------------------------------------------------------------- 翻桶機
  const [ux, uy, uz] = UPENDER.pivot;
  box(group, 1600, 220, 900, MAT.steelDark, ux - 300, 110, uz);
  for (const s of [-1, 1]) cyl(group, 90, 120, MAT.steelBlue, ux, uy, uz + s * 420, 'z');
  for (const s of [-1, 1]) box(group, 120, uy, 120, MAT.steelBlue, ux, uy / 2, uz + s * 420);
  const cradle = new THREE.Group(); cradle.position.set(ux, uy, uz); group.add(cradle);
  box(cradle, 1000, 40, 640, MAT.steel, -500, -27, 0);                                   // 床面（桶身下方）
  // 兩條窄墊塊與桶外環相切，避免原寬墊塊插入桶身。
  const supportZ = 230, supportHalf = 12;
  const supportTop = DRUM.R - Math.sqrt(DRUM.envelopeR ** 2 - (supportZ - supportHalf) ** 2);
  for (const s of [-1, 1]) box(cradle, 980, 30, supportHalf * 2, MAT.pu, -500, supportTop - 15, s * supportZ);
  box(cradle, 40, 640, 760, MAT.steel, 82, 320, 0);                                      // 桶底靠板（翻後成為承載面）
  for (let k = 0; k < 4; k++) cyl(cradle, 30, 700, MAT.roller, 30, 80 + k * 150, 0, 'z', 12);
  const upClamp = [];
  for (const s of [-1, 1]) { const c = box(cradle, 700, 160, 30, MAT.yellow, -500, DRUM.R, s * (DRUM.R + 60)); upClamp.push({ c, s }); }
  // 侧置液壓缸，活塞端隨翻轉台轉動，避開桶與承載床。
  const actuator = new THREE.Group(); group.add(actuator);
  cyl(actuator, 46, 420, MAT.steelDark, 0, 210, 0);
  const piston = cyl(actuator, 24, 1, MAT.steel, 0, 420, 0);
  const anchor = new THREE.Vector3(ux - 800, 230, uz - 570);
  cyl(group, 65, 110, MAT.steelDark, anchor.x, anchor.y, anchor.z, 'z');

  // ---------------------------------------------------------------- 立放輸送：一路往南，取桶位與放回位不設側導引
  const up = UPRIGHT;
  const uprightRollers = [];
  for (let z = up.z0 + 450; z < up.z1; z += 120) {
    if (Math.abs(z - DECAP.z) < 370) continue;
    const r = cyl(group, 30, 700, MAT.roller, up.x, up.top - 30, z, 'x', 20);
    uprightRollers.push(r); rollers.push({ mesh: r, axis: 'x', radius: 30, along: z });
    for (const s of [-1, 1]) box(group, 26, 68, 70, MAT.steelDark, up.x + s * 357, up.top - 36, z);
  }
  for (const s of [-1, 1]) box(group, 50, 150, up.z1 - up.z0 - 450, MAT.steel, up.x + s * 380, up.top - 70, (up.z0 + 450 + up.z1) / 2);
  for (let z = up.z0 + 600; z < up.z1; z += 900) for (const s of [-1, 1]) box(group, 60, up.top - 140, 60, MAT.steelDark, up.x + s * 380, (up.top - 140) / 2, z);
  for (const [z0, z1] of [[up.z0 + 450, up.pick - 350], [up.pick + 350, up.place - 350], [up.place + 350, up.z1]])
    for (const s of [-1, 1]) box(group, 30, 120, z1 - z0, MAT.yellow, up.x + s * 340, up.top + 160, (z0 + z1) / 2);
  for (const z of [up.pick + DRUM.R + 20, up.place + DRUM.R + 20]) box(group, 120, 60, 40, MAT.steelOrange, up.x + 300, up.top + 40, z);   // 定位擋塊
  // 放回位頂升秤台：梳齒在滾筒縫隙間，平時低於滾筒面；氣缸頂升時把桶托離滾筒，荷重元只承受秤台＋桶
  const weigher = new THREE.Group(); group.add(weigher);
  const gaps = []; for (let z = up.z0 + 450 + 60; z < up.z1; z += 120) if (Math.abs(z - up.place) < 300) gaps.push(z);
  for (const z of gaps) {
    box(weigher, 560, 40, 26, MAT.pu, up.x, up.top - 15 - 20, z);                    // 梳齒（頂面平時低於滾筒面 15 mm）
    box(weigher, 30, 120, 22, MAT.steelDark, up.x, up.top - 95, z);
  }
  box(weigher, 600, 30, gaps.at(-1) - gaps[0] + 60, MAT.steelDark, up.x, up.top - 165, (gaps[0] + gaps.at(-1)) / 2);
  for (const [dx, dz] of [[-240, -180], [240, -180], [-240, 180], [240, 180]]) cyl(weigher, 35, 50, MAT.steelBlue, up.x + dx, up.top - 205, up.place + dz);   // 荷重元
  box(group, 640, 30, 520, MAT.steel, up.x, up.top - 245, up.place);                    // 頂升板
  cyl(group, 55, up.top - 280, MAT.alu, up.x, (up.top - 280) / 2, up.place);           // 頂升氣缸
  const scaleScreen = box(group, 40, 200, 320, MAT.screen, up.x + 520, 1150, up.place); box(group, 60, 1050, 60, MAT.steelDark, up.x + 520, 525, up.place);
  box(group, 700, 40, 40, MAT.steelOrange, up.x, up.top + 40, up.z1 - 20);
  // 站名牌貼在輸送架西側下方：夾爪兩側導軌在桶身高度會掃過 up.x ± 420，牌子不能放在那裡
  plate(group, ['取桶位'], 420, 110, [up.x - 420, up.top - 230, up.pick], -Math.PI / 2, { w: 512, h: 130 });
  plate(group, ['放回位＋頂升秤台'], 560, 110, [up.x - 420, up.top - 230, up.place], -Math.PI / 2, { w: 512, h: 110 });
  plate(group, ['→ 裝填區（下一站）'], 900, 160, [up.x - 420, 1150, up.handoff - 200], -Math.PI / 2, { w: 640, h: 110 });

  // ---------------------------------------------------------------- 自動開蓋站（相機定位 → 旋轉台對位 → 伺服鎖付軸反轉拆蓋）
  const dc = DECAP;
  for (const [dx, dz] of [[-650, -400], [650, -400], [-650, 400], [650, 400]]) box(group, 100, 2600, 100, MAT.steelBlue, up.x + dx, 1300, dc.z + dz);
  for (const dz of [-400, 400]) box(group, 1400, 120, 100, MAT.steelBlue, up.x, 2560, dc.z + dz);
  const turntable = new THREE.Group(); turntable.position.set(up.x, 0, dc.z); group.add(turntable);
  cyl(turntable, 330, 30, MAT.steelDark, 0, up.top - 85, 0, 'y', 48);
  const tableRollers = [];
  for (let dx = -270; dx <= 270; dx += 90) for (let dz = -270; dz <= 270; dz += 90) {
    if (Math.hypot(dx, dz) > 300) continue;
    cyl(turntable, 29, 30, MAT.steelDark, dx, up.top - 40, dz);
    const r = new THREE.Mesh(new THREE.SphereGeometry(24, 16, 10), MAT.roller); r.position.set(dx, up.top - 24, dz); r.castShadow = true; turntable.add(r); tableRollers.push(r);
  }
  cyl(group, 180, 90, MAT.steelBlue, up.x, up.top - 145, dc.z);
  motor(group, up.x + 225, 180, dc.z, .65);
  for (const s of [-1, 1]) box(group, 40, 120, 500, MAT.yellow, up.x + s * (DRUM.R + 110), up.top + 300, dc.z);
  const dcClamp = [];
  for (const s of [-1, 1]) { const c = cyl(group, 20, 160, MAT.pu, up.x + s * (DRUM.R + 70), up.top + 302, dc.z); dcClamp.push({ c, s }); }
  // XY 模組：Z 向導軌在框架兩側，橫樑偏在台車北側，Z 軸立柱不穿過橫樑
  for (const s of [-1, 1]) { const rail = box(group, 60, 40, 900, MAT.steel, up.x + s * dc.rail, 2510, dc.z); rail.userData.guide = 'decap-y'; }
  const dBridge = new THREE.Group(); dBridge.userData.on = 'decap-y'; group.add(dBridge);
  box(dBridge, dc.rail * 2 + 60, 100, 160, MAT.alu, up.x, 2440, -150);
  const dCar = new THREE.Group(); dBridge.add(dCar);
  box(dCar, 260, 220, 220, MAT.steelDark, 0, 2440, 0);
  const dZ = new THREE.Group(); dCar.add(dZ);
  box(dZ, 120, 898, 120, MAT.alu, 0, 451, 0);
  const spindles = {};
  for (const [k, dx, r] of [['big', -90, DRUM.big.r + 8], ['small', 90, DRUM.small.r + 8]]) {
    cyl(dZ, 55, 200, MAT.black, dx, 120, 0);
    const sock = new THREE.Group(); sock.position.set(dx, 0, 0); dZ.add(sock);
    cyl(sock, r, 60, MAT.steel, 0, 30, 0, 'y', 18);
    for (let i = 0; i < 4; i++) box(sock, 8, 50, 14, MAT.black, r * Math.cos(i * Math.PI / 2), 30, r * Math.sin(i * Math.PI / 2));
    spindles[k] = sock;
  }
  // 頂視相機：吊在框架北側橫樑外，斜拍桶頂，完全避開 XY 模組行程（橫樑 Z 範圍約 dc.z −430～+130）
  const camPos = new THREE.Vector3(up.x, 2150, dc.z - 600), camAim = new THREE.Vector3(up.x, up.top + DRUM.H, dc.z);
  box(group, 80, 60, 200, MAT.alu, up.x, 2650, dc.z - 510);
  rod(group, [up.x, 2620, dc.z - 600], [up.x, 2230, dc.z - 600], 22, MAT.alu);
  const camDecap = new THREE.Group(); camDecap.position.copy(camPos); camDecap.lookAt(camAim); group.add(camDecap);
  box(camDecap, 90, 90, 140, MAT.black, 0, 0, 0);
  const ringLight = new THREE.Mesh(new THREE.TorusGeometry(70, 14, 8, 30), MAT.cap); ringLight.position.z = 90; camDecap.add(ringLight);
  const decapCam = new THREE.PerspectiveCamera(36, 1.5, 50, 6000); decapCam.position.copy(camPos); decapCam.lookAt(camAim); group.add(decapCam);
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
      if (i === list.length - 1 && !closed) box(fences, 60, 2000, 60, MAT.fence, bx, 1000, bz);   // 轉角立柱只放一支
    }
  };
  fencePath(FENCE, false, [[...FENCE_GATES.in, 600], [...FENCE_GATES.out, 600]]);
  fencePath(GANTRY_FENCE, true, [[PALLET_STATION.x, 8950, 800], [6700, LYING.z, 600]]);
  // 光柵（入口）
  for (const [x, z, w, ax] of [[PALLET_STATION.x, 8950, 1400, 'x'], [...FENCE_GATES.in, 900, 'x'], [...FENCE_GATES.out, 900, 'x'], [6700, LYING.z, 900, 'z']])
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

  // 緊固、驅動、光電、櫃門、導軌與軸承細節均在既有設備範圍內。
  for (const [x, z] of g.posts) foot(group, x, z, 280);
  for (const [dx, dz] of [[-650, -400], [650, -400], [-650, 400], [650, 400]]) foot(group, up.x + dx, dc.z + dz, 160);
  for (const key of ['panel', 'robotCtrl']) cabinetDetails(group, ...FOOTPRINTS[key]);
  motor(group, ly.x0 + 380, axisY - 100, ly.z + 475, .65);
  motor(group, up.x + 520, 220, up.z1 - 500, .7, Math.PI / 2);
  motor(bridge, 0, g.beamY + 480, p0[1], .65);
  for (const z of [up.decap - 410, up.pick - 260, up.place + 300, up.z1 - 300]) sensor(group, up.x + 340, up.top + 90, z, Math.PI / 2);
  for (const x of [ly.place, ly.label, ly.buffer]) sensor(group, x, axisY + 40, ly.z + 330);   // 低於夾爪下緣，避開龍門張開的夾爪
  for (const s of [-1, 1]) { box(z1, 20, 1240, 12, MAT.steelDark, s * 85, 650, 117); box(trolley, 32, 220, 32, MAT.steel, s * 130, g.beamY + 150, 160); }
  bolts(bridge, [-1, 1].flatMap(s => [-1, 1].map(k => [s * 200, g.beamY + 565, (p0[1] + p2[1]) / 2 + k * 600])), 14);
  return {
    animate(time, st) {
      // 分段滾輪只在相鄰桶輸送時轉動；角度由桶位移決定，重播完全一致。
      for (const r of rollers) {
        const key = r.axis === 'z' ? 'lx' : 'uz', mode = r.axis === 'z' ? 'lying' : 'upright';
        const d = [st.drum0, st.drum1, st.drum2, st.drum3].find(d => d.mode === mode && Math.abs(d[key] - r.along) < 650);
        r.mesh.rotation[r.axis === 'z' ? 'y' : 'x'] = d ? -d[key] / r.radius : 0;
      }
    },
    mechanical: { rotRollers, uprightRollers, tableRollers, turntable, weigher, cradle, actuator, piston, upClamp, dcClamp },
    group, fences, labelCam, decapCam, gantryPivot, cradle, padLabel,
    setGantry({ x, z, y, tilt: t, jaw }) {
      bridge.position.x = x; trolley.position.z = z;
      // 兩段伸縮：內管原點即翻轉軸；外管底端隨行程移動，兩端都保持與內管、台車重疊
      z2.position.y = y;
      // 外管下緣保持在翻轉台擺動範圍（半徑約 250）之上
      z1.position.y = Math.max(2050 + (y - g.placeY) * 250 / (g.safeY - g.placeY), y + 300);
      tilt.rotation.z = t * Math.PI / 2;
      gJaws.set(jaw);
    },
    setLabeler({ pad: p, print, spin, flash }) {
      pad.position.set(0, 0, -120 - p * (lab.standZ - LYING.z - DRUM.R - 135));
      padLabel.visible = print > .5;
      for (const r of rotRollers) r.rotation.x = -spin * Math.PI / 2 * DRUM.envelopeR / 70;
      labelFlash.intensity = flash ? 900 : 0; barLight.material = flash ? MAT.green : MAT.cap;
    },
    setUpender({ tilt: t, clamp }) { cradle.rotation.z = -t * Math.PI / 2;
      const end = new THREE.Vector3(-450, -85, -570).applyAxisAngle(new THREE.Vector3(0, 0, 1), -t * Math.PI / 2).add(new THREE.Vector3(ux, uy, uz));
      const delta = end.clone().sub(anchor), length = delta.length(); actuator.position.copy(anchor);
      actuator.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize()); piston.scale.y = length - 350; piston.position.y = 350 + (length - 350) / 2; for (const { c, s } of upClamp) c.position.z = s * (DRUM.envelopeR + 15 + (1 - clamp) * 110); },
    setDecap({ hx, hz, hy, spinBig, spinSmall, flash, clamp, table, caps }) {
      dBridge.position.z = DECAP.z + hz; dCar.position.x = up.x + hx; dZ.position.y = hy;
      spindles.big.rotation.y = spinBig * Math.PI * 2 * 2.5; spindles.small.rotation.y = spinSmall * Math.PI * 2 * 2.5;
      decapFlash.intensity = flash ? 900 : 0; ringLight.material = flash ? MAT.green : MAT.cap;
      for (const { c, s } of dcClamp) c.position.x = up.x + s * (DRUM.envelopeR + 20 + (1 - clamp) * 110);
      turntable.rotation.y = table * D2R;
      tableRollers.forEach(r => { r.rotation.x = 0; });
      capPile.forEach((c, i) => { c.visible = i < caps; });
    },
    setScale({ on, lift }) { scaleScreen.material = on ? MAT.green : MAT.screen; weigher.position.y = lift * WEIGH.stroke; },
    setTower(state) { lamps.forEach((l, i) => { l.material.emissiveIntensity = (state === ['fault', 'wait', 'run'][i]) ? 1.2 : .05; }); },
    socket: k => spindles[k],
  };
}
