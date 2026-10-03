// 產線設備：棧板站、三軸龍門＋翻轉夾爪、橫躺輸送、貼標讀碼站、翻桶機、立放直線輸送（開蓋→清洗→裝填區）、圍籬與控制櫃。
import * as THREE from 'three';
import { PALLET_STATION, PALLET, GANTRY, LYING, LABEL, UPENDER, UPRIGHT, DECAP, DRUM, FENCE, FENCE_GATES, GANTRY_FENCE, FOOTPRINTS, ROOM, WEIGH } from './layout.js';
import { D2R, block, blockBetween, cylinder, plate, rod } from '@core/geom/shapes.js';
import { MAT } from '@core/geom/materials.js';
import { drumJaws } from './drum.js';
import { bolts, foot, motor, sensor, cabinetDetails } from '@core/geom/hardware.js';

export function createLine(scene) {
  const group = new THREE.Group(); group.name = 'line'; scene.add(group);
  // 工位標記：每段建立的零件記下所屬工位（userData.station），統一檢查依此判斷「不同工位的架設相撞」
  const sections = [];
  const section = name => sections.push([group.children.length, name]);
  const fences = new THREE.Group(); group.add(fences);

  section('pallet');
  // ---------------------------------------------------------------- 棧板站
  const ps = PALLET_STATION;
  block(group, [1300, ps.stand, 1300], [ps.x, ps.stand / 2, ps.z], MAT.steelDark);
  for (const [dx, dz] of [[-660, 300], [660, 300], [-660, -300], [660, -300]]) block(group, [40, 200, 300], [ps.x + dx, ps.stand + 100, ps.z + dz], MAT.yellow);
  block(group, [260, 30, 30], [ps.x, ps.stand + 17, ps.z + PALLET.W / 2 + 20], MAT.steelOrange);   // 後止擋：橫跨棧板中樑，距棧板南端 5 mm

  section('gantry');
  // ---------------------------------------------------------------- 龍門（雙 X 樑 → 橫樑沿 X → 台車沿 Z → 兩段伸縮 Z → 翻轉軸 → 夾爪）
  const g = GANTRY, [p0, p1, p2] = g.posts;
  for (const [x, z] of g.posts) block(group, [200, g.beamY + 100, 200], [x, (g.beamY + 100) / 2, z], MAT.steelBlue);
  for (const z of [p0[1], p2[1]]) block(group, [p1[0] - p0[0] + 200, 220, 200], [(p0[0] + p1[0]) / 2, g.beamY + 210, z], MAT.steelBlue);
  for (const z of [p0[1], p2[1]]) block(group, [p1[0] - p0[0], 40, 60], [(p0[0] + p1[0]) / 2, g.beamY + 340, z], MAT.steel);
  // 橫樑為雙樑（中心距 400，間隙 300），Z 軸伸縮管從兩樑之間穿下
  const bridge = new THREE.Group(); group.add(bridge);
  for (const s of [-1, 1]) block(bridge, [100, 200, p2[1] - p0[1] + 200], [s * 200, g.beamY + 460, (p0[1] + p2[1]) / 2], MAT.steelOrange);
  const trolley = new THREE.Group(); bridge.add(trolley);
  block(trolley, [560, 60, 360], [0, g.beamY + 590, 0], MAT.steelDark);                         // 跨在雙樑上的台車板
  for (const s of [-1, 1]) block(trolley, [30, 210, 300], [s * 130, g.beamY + 455, 0], MAT.steelDark);   // 穿過間隙的吊板
  block(trolley, [420, 300, 360], [0, g.beamY + 200, 0], MAT.steelDark);                       // 樑下導向座
  block(trolley, [240, 300, 240], [0, g.beamY + 770, -300], MAT.black);                        // Z 軸馬達（避開伸縮管）
  const z1 = new THREE.Group(), z2 = new THREE.Group(); trolley.add(z1); trolley.add(z2); z2.userData.nested = z1;   // 兩段伸縮：內管套在外管內
  block(z1, [220, 1300, 220], [0, 650, 0], MAT.alu);
  block(z2, [160, 1300, 160], [0, 800, 0], MAT.steel);
  const tilt = new THREE.Group(); z2.add(tilt);                                          // 翻轉軸（世界 Z 向）
  cylinder(z2, 140, 360, [0, -40, 0], MAT.black, 'z', 28);
  block(z2, [260, 120, 300], [0, 40, 0], MAT.steelDark);
  block(tilt, [420, 60, 760], [0, -100, 0], MAT.steelDark);
  for (const s of [-1, 1]) block(tilt, [60, 250, 60], [0, -235, s * 360], MAT.steelDark);   // 吊板止於夾爪頂端之上 10 mm，夾爪全開時背板不會撞到
  const jawFrame = new THREE.Group(); jawFrame.position.y = -g.hang; jawFrame.rotation.y = Math.PI / 2; tilt.add(jawFrame);   // 爪在 ±Z（局部 ±X）
  const gJaws = drumJaws(jawFrame, null, g.jawOpen);
  const gantryPivot = new THREE.Object3D(); tilt.add(gantryPivot);
  // 拖鏈
  block(group, [p1[0] - p0[0], 80, 160], [(p0[0] + p1[0]) / 2, g.beamY + 420, p0[1] - 220], MAT.black);

  section('lying');
  // ---------------------------------------------------------------- 橫躺輸送：水平沙漏形（V 槽）滾輪，滾輪軸橫跨輸送方向
  // 桶身落在 V 槽兩側斜面（半角 LYING.vee）；切點 z = R·sinα，由此反推滾輪軸高
  const rollers = [], ly = LYING, va = ly.vee * D2R, r0 = 40, halfL = 260;
  const axisY = ly.y - DRUM.envelopeR * Math.cos(va) - (DRUM.envelopeR * Math.sin(va)) * Math.tan(va) - r0;
  const hourglass = new THREE.LatheGeometry([[0, -halfL], [r0 + halfL * Math.tan(va), -halfL], [r0, 0], [r0 + halfL * Math.tan(va), halfL], [0, halfL]].map(([r, y]) => new THREE.Vector2(r, y)), 28);
  for (let x = ly.x0 + 200; x + 170 <= ly.x1; x += 330) {   // 第一支避開龍門翻轉頂板（放料時翻轉軸在 X 5283）
    if (Math.abs(x - LABEL.x) < 620) continue;              // 標籤站改用旋轉輥
    const r = new THREE.Mesh(hourglass, MAT.roller); r.rotation.x = Math.PI / 2; r.position.set(x, axisY, ly.z); r.castShadow = r.receiveShadow = true; group.add(r); rollers.push({ mesh: r, axis: 'z', radius: 100, along: x });
    for (const s of [-1, 1]) cylinder(group, 12, 60, [x, axisY, ly.z + s * (halfL + 30)], MAT.steelDark, 'z', 8);
  }
  for (const s of [-1, 1]) block(group, [ly.x1 - ly.x0, 140, 50], [(ly.x0 + ly.x1) / 2, axisY, ly.z + s * (halfL + 60)], MAT.steel);
  for (let x = ly.x0 + 100; x <= ly.x1; x += 1150) for (const s of [-1, 1]) block(group, [70, axisY - 70, 70], [x, (axisY - 70) / 2, ly.z + s * (halfL + 60)], MAT.steelDark);
  block(group, [ly.x1 - ly.x0, 18, 120], [(ly.x0 + ly.x1) / 2, axisY - 100, ly.z + halfL + 160], MAT.yellow);
  // 標籤站旋轉輥（取代該段 V 輥，兩支主動輥平行於桶軸）
  const lab = LABEL;
  const rotRollers = [];
  for (const s of [-1, 1]) { const r = cylinder(group, 70, 1100, [lab.x, ly.y - Math.sqrt((DRUM.envelopeR + 70) ** 2 - 220 ** 2), ly.z + s * 220], MAT.belt, 'x', 20); rotRollers.push(r); }
  block(group, [1200, 120, 700], [lab.x, ly.y - DRUM.R - 140, ly.z], MAT.steelDark);

  section('label');
  // ---------------------------------------------------------------- 貼標機（印字貼標頭，南側推出貼附）＋讀碼相機
  const st = new THREE.Group(); st.position.set(lab.x, 0, lab.standZ); group.add(st);
  block(st, [600, 900, 500], [0, 450, 200], MAT.cabinet);
  block(st, [560, 420, 440], [0, 1110, 160], MAT.steelDark);                                  // 印字引擎
  block(st, [30, 250, 300], [290, 1150, 160], MAT.screen);
  cylinder(st, 120, 80, [-200, 1200, 340], MAT.cap, 'x', 28);                                     // 標籤捲
  const padRail = block(st, [80, 60, 480], [0, ly.y, -120], MAT.alu);
  const pad = new THREE.Group(); st.add(pad);
  block(pad, [140, 180, 30], [0, ly.y, 0], MAT.black);
  const padLabel = block(pad, [100, 150, 4], [0, ly.y, -17], MAT.cap); padLabel.visible = false;
  // 讀碼／定位相機：桶頂端西側斜上方，同一張影像看到兩個桶塞（定位）與桶身上方的標籤（貼後檢查）
  const [cx, cy, cz] = lab.cam.pos, camTarget = new THREE.Vector3(...lab.cam.target);
  const camLabel = new THREE.Group(); camLabel.position.set(cx, cy, cz); camLabel.lookAt(camTarget); group.add(camLabel);
  block(camLabel, [90, 90, 140], [0, 0, 0], MAT.black);
  cylinder(camLabel, 30, 70, [0, 0, 100], MAT.steelDark, 'z', 28);
  const barLight = block(camLabel, [520, 40, 80], [0, -110, 60], MAT.cap);                  // 側打條形光，避免標籤反光
  // 支架立在龍門圍籬外（X > 6700），避開龍門東側立柱與翻桶擺動範圍
  rod(group, [cx + 100, 0, cz - 520], [cx + 100, cy + 150, cz - 520], 45, MAT.alu);
  blockBetween(group, [cx + 60, cy + 110, cz - 520], [cx + 140, cy + 170, cz], MAT.alu);
  rod(group, [cx + 100, cy + 140, cz], [cx, cy, cz], 25, MAT.alu);
  // 虛擬相機放在鏡頭前緣（機身中心往目標 150 mm），否則子畫面會拍到自己的鏡筒
  const labelCam = new THREE.PerspectiveCamera(lab.cam.fov, 1.5, 50, 6000);
  labelCam.position.set(cx, cy, cz).addScaledVector(camTarget.clone().sub(labelCam.position).normalize(), 150); labelCam.lookAt(camTarget); group.add(labelCam);
  const labelFlash = new THREE.SpotLight(0xffffff, 0, 3000, .7, .5, 1); labelFlash.position.set(cx, cy, cz); labelFlash.target.position.copy(camTarget); group.add(labelFlash, labelFlash.target);

  section('upender');
  // ---------------------------------------------------------------- 翻桶機
  const [ux, uy, uz] = UPENDER.pivot;
  block(group, [1600, 220, 900], [ux - 300, 110, uz], MAT.steelDark);
  for (const s of [-1, 1]) cylinder(group, 90, 120, [ux, uy, uz + s * 420], MAT.steelBlue, 'z', 28);
  for (const s of [-1, 1]) block(group, [120, uy, 120], [ux, uy / 2, uz + s * 420], MAT.steelBlue);
  const cradle = new THREE.Group(); cradle.position.set(ux, uy, uz); group.add(cradle);
  block(cradle, [1000, 40, 640], [-500, -27, 0], MAT.steel);                                   // 床面（桶身下方）
  // 兩條窄墊塊與桶外環相切，避免原寬墊塊插入桶身。
  const supportZ = 230, supportHalf = 12;
  const supportTop = DRUM.R - Math.sqrt(DRUM.envelopeR ** 2 - (supportZ - supportHalf) ** 2);
  for (const s of [-1, 1]) block(cradle, [980, 30, supportHalf * 2], [-500, supportTop - 15, s * supportZ], MAT.pu);
  block(cradle, [40, 640, 760], [82, 320, 0], MAT.steel);                                      // 桶底靠板（翻後成為承載面）
  for (let k = 0; k < 4; k++) cylinder(cradle, 30, 700, [30, 80 + k * 150, 0], MAT.roller, 'z', 12);
  const upClamp = [];
  for (const s of [-1, 1]) { const c = block(cradle, [700, 160, 30], [-500, DRUM.R, s * (DRUM.R + 60)], MAT.yellow); upClamp.push({ c, s }); }
  // 侧置液壓缸，活塞端隨翻轉台轉動，避開桶與承載床。
  const actuator = new THREE.Group(); group.add(actuator);
  cylinder(actuator, 46, 420, [0, 210, 0], MAT.steelDark, 'y', 28);
  const piston = cylinder(actuator, 24, 1, [0, 420, 0], MAT.steel, 'y', 28);
  const anchor = new THREE.Vector3(ux - 800, 230, uz - 570);
  cylinder(group, 65, 110, [anchor.x, anchor.y, anchor.z], MAT.steelDark, 'z', 28);

  section('upright');
  // ---------------------------------------------------------------- 立放輸送：一路往南，取桶位與放回位不設側導引
  const up = UPRIGHT;
  const uprightRollers = [];
  const frame0 = up.z0 + 500, roll0 = up.z0 + 570;                                       // 輸送架從翻桶機南側軸承座之後開始
  for (let z = roll0; z < up.z1; z += 120) {
    if (Math.abs(z - DECAP.z) < 370) continue;
    const r = cylinder(group, 30, 700, [up.x, up.top - 30, z], MAT.roller, 'x', 20);
    uprightRollers.push(r); rollers.push({ mesh: r, axis: 'x', radius: 30, along: z });
    for (const s of [-1, 1]) block(group, [26, 68, 70], [up.x + s * 357, up.top - 36, z], MAT.steelDark);
  }
  for (const s of [-1, 1]) block(group, [50, 150, up.z1 - frame0], [up.x + s * 380, up.top - 70, (frame0 + up.z1) / 2], MAT.steel);
  for (let z = up.z0 + 600; z < up.z1; z += 900) for (const s of [-1, 1]) block(group, [60, up.top - 140, 60], [up.x + s * 380, (up.top - 140) / 2, z], MAT.steelDark);
  for (const [z0, z1] of [[frame0, up.pick - 350], [up.pick + 350, up.place - 350], [up.place + 350, up.z1]])
    for (const s of [-1, 1]) block(group, [30, 120, z1 - z0], [up.x + s * 340, up.top + 160, (z0 + z1) / 2], MAT.yellow);
  for (const z of [up.pick + DRUM.R + 20, up.place + DRUM.R + 20]) block(group, [120, 60, 40], [up.x + 300, up.top + 40, z], MAT.steelOrange);   // 定位擋塊
  // 放回位頂升秤台：梳齒在滾筒縫隙間，平時低於滾筒面；氣缸頂升時把桶托離滾筒，荷重元只承受秤台＋桶
  const weigher = new THREE.Group(); group.add(weigher);
  const gaps = []; for (let z = roll0 + 60; z < up.z1; z += 120) if (Math.abs(z - up.place) < 300) gaps.push(z);
  for (const z of gaps) {
    block(weigher, [560, 40, 26], [up.x, up.top - 15 - 20, z], MAT.pu);                    // 梳齒（頂面平時低於滾筒面 15 mm）
    block(weigher, [30, 120, 22], [up.x, up.top - 95, z], MAT.steelDark);
  }
  block(weigher, [600, 30, gaps.at(-1) - gaps[0] + 60], [up.x, up.top - 165, (gaps[0] + gaps.at(-1)) / 2], MAT.steelDark);
  for (const [dx, dz] of [[-240, -180], [240, -180], [-240, 180], [240, 180]]) cylinder(weigher, 35, 50, [up.x + dx, up.top - 205, up.place + dz], MAT.steelBlue, 'y', 28);   // 荷重元
  block(group, [640, 30, 520], [up.x, up.top - 245, up.place], MAT.steel);                    // 頂升板
  cylinder(group, 55, up.top - 280, [up.x, (up.top - 280) / 2, up.place], MAT.alu, 'y', 28);           // 頂升氣缸
  const scaleScreen = block(group, [40, 200, 320], [up.x + 520, 1150, up.place], MAT.screen); block(group, [60, 1050, 60], [up.x + 520, 525, up.place], MAT.steelDark);
  block(group, [700, 40, 40], [up.x, up.top + 40, up.z1 - 20], MAT.steelOrange);
  // 站名牌貼在輸送架西側下方：夾爪兩側導軌在桶身高度會掃過 up.x ± 420，牌子不能放在那裡
  plate(group, ['取桶位'], 420, 110, [up.x - 420, up.top - 230, up.pick], -Math.PI / 2, { w: 512, h: 130 });
  plate(group, ['放回位＋頂升秤台'], 560, 110, [up.x - 420, up.top - 230, up.place], -Math.PI / 2, { w: 512, h: 110 });
  plate(group, ['→ 裝填區（下一站）'], 900, 160, [up.x - 420, 1150, up.handoff - 200], -Math.PI / 2, { w: 640, h: 110 });

  section('decap');
  // ---------------------------------------------------------------- 自動開蓋站（相機定位 → 旋轉台對位 → 伺服鎖付軸反轉拆蓋）
  const dc = DECAP;
  for (const [dx, dz] of [[-650, -400], [650, -400], [-650, 400], [650, 400]]) block(group, [100, 2600, 100], [up.x + dx, 1300, dc.z + dz], MAT.steelBlue);
  for (const dz of [-400, 400]) block(group, [1400, 120, 100], [up.x, 2560, dc.z + dz], MAT.steelBlue);
  const turntable = new THREE.Group(); turntable.position.set(up.x, 0, dc.z); group.add(turntable);
  cylinder(turntable, 330, 30, [0, up.top - 85, 0], MAT.steelDark, 'y', 48);
  const tableRollers = [];
  for (let dx = -270; dx <= 270; dx += 90) for (let dz = -270; dz <= 270; dz += 90) {
    if (Math.hypot(dx, dz) > 300) continue;
    cylinder(turntable, 29, 30, [dx, up.top - 40, dz], MAT.steelDark, 'y', 28);
    const r = new THREE.Mesh(new THREE.SphereGeometry(24, 16, 10), MAT.roller); r.position.set(dx, up.top - 24, dz); r.castShadow = true; turntable.add(r); tableRollers.push(r);
  }
  cylinder(group, 180, 90, [up.x, up.top - 145, dc.z], MAT.steelBlue, 'y', 28);
  motor(group, up.x + 225, 180, dc.z, .65);
  for (const s of [-1, 1]) block(group, [40, 120, 500], [up.x + s * (DRUM.R + 110), up.top + 300, dc.z], MAT.yellow);
  const dcClamp = [];
  for (const s of [-1, 1]) { const c = cylinder(group, 20, 160, [up.x + s * (DRUM.R + 70), up.top + 302, dc.z], MAT.pu, 'y', 28); dcClamp.push({ c, s }); }
  // XY 模組：Z 向導軌在框架兩側，橫樑偏在台車北側，Z 軸立柱不穿過橫樑
  for (const s of [-1, 1]) { const rail = block(group, [60, 40, 900], [up.x + s * dc.rail, 2510, dc.z], MAT.steel); rail.userData.guide = 'decap-y'; }
  const dBridge = new THREE.Group(); dBridge.userData.on = 'decap-y'; group.add(dBridge);
  block(dBridge, [dc.rail * 2 + 60, 100, 160], [up.x, 2440, -150], MAT.alu);
  const dCar = new THREE.Group(); dBridge.add(dCar);
  block(dCar, [260, 220, 220], [0, 2440, 0], MAT.steelDark);
  const dZ = new THREE.Group(); dCar.add(dZ);
  block(dZ, [120, 898, 120], [0, 451, 0], MAT.alu);
  const spindles = {};
  for (const [k, dx, r] of [['big', -90, DRUM.big.r + 8], ['small', 90, DRUM.small.r + 8]]) {
    cylinder(dZ, 55, 200, [dx, 120, 0], MAT.black, 'y', 28);
    const sock = new THREE.Group(); sock.position.set(dx, 0, 0); dZ.add(sock);
    cylinder(sock, r, 60, [0, 30, 0], MAT.steel, 'y', 18);
    for (let i = 0; i < 4; i++) block(sock, [8, 50, 14], [r * Math.cos(i * Math.PI / 2), 30, r * Math.sin(i * Math.PI / 2)], MAT.black);
    spindles[k] = sock;
  }
  // 頂視相機：吊在框架北側橫樑外，斜拍桶頂，完全避開 XY 模組行程（橫樑 Z 範圍約 dc.z −430～+130）
  const camPos = new THREE.Vector3(up.x, 2150, dc.z - 600), camAim = new THREE.Vector3(up.x, up.top + DRUM.H, dc.z);
  block(group, [80, 60, 200], [up.x, 2650, dc.z - 510], MAT.alu);
  rod(group, [up.x, 2620, dc.z - 600], [up.x, 2230, dc.z - 600], 22, MAT.alu);
  const camDecap = new THREE.Group(); camDecap.position.copy(camPos); camDecap.lookAt(camAim); group.add(camDecap);
  block(camDecap, [90, 90, 140], [0, 0, 0], MAT.black);
  const ringLight = new THREE.Mesh(new THREE.TorusGeometry(70, 14, 8, 30), MAT.cap); ringLight.position.z = 90; camDecap.add(ringLight);
  const decapCam = new THREE.PerspectiveCamera(36, 1.5, 50, 6000); decapCam.position.copy(camPos); decapCam.lookAt(camAim); group.add(decapCam);
  const decapFlash = new THREE.SpotLight(0xffffff, 0, 2500, .5, .5, 1); decapFlash.position.copy(decapCam.position); decapFlash.target.position.set(up.x, up.top + DRUM.H, dc.z); group.add(decapFlash, decapFlash.target);
  // 桶蓋收集桶（斜槽）
  const bin = new THREE.Group(); bin.position.set(dc.bin.x, 0, dc.bin.z); group.add(bin);
  // 桶高 560：桶口低於立放輸送側導引（底面 y 607）
  cylinder(bin, 230, 560, [0, 280, 0], MAT.ppSolid, 'y', 24, 200);
  cylinder(bin, 210, 10, [0, 562, 0], MAT.hole, 'y', 28);
  const capPile = []; for (let i = 0; i < 8; i++) { const c = cylinder(bin, i % 2 ? 18 : 36, 16, [(i % 3 - 1) * 70, 500 + Math.floor(i / 3) * 18, ((i * 7) % 5 - 2) * 40], MAT.cap, 'y', 28); c.visible = false; capPile.push(c); }
  plate(group, ['桶蓋收集'], 380, 110, [dc.bin.x, 460, dc.bin.z + 222], 0, { w: 512, h: 150 });

  section('fence');
  // ---------------------------------------------------------------- 圍籬
  // 圍籬：gaps 為 [x, z, 開口寬]，在所在邊上精確切出開口（寬度依通過的設備與光柵決定），其餘每段約 1.5 m 一片網
  const posts = new Set();
  const post = (x, z) => { const k = Math.round(x) + ',' + Math.round(z); if (posts.has(k)) return; posts.add(k); block(fences, [60, 2000, 60], [x, 1000, z], MAT.fence); };
  const fencePath = (pts, closed, gaps = []) => {
    const list = closed ? [...pts, pts[0]] : pts;
    for (let i = 1; i < list.length; i++) {
      const [ax, az] = list[i - 1], [bx, bz] = list[i], L = Math.hypot(bx - ax, bz - az), ux = (bx - ax) / L, uz = (bz - az) / L;
      // 這條邊上的開口（沿邊距離區間）
      const cuts = gaps.map(([gx, gz, w]) => { const t = (gx - ax) * ux + (gz - az) * uz, off = Math.abs((gx - ax) * uz - (gz - az) * ux); return off < 1 && t > 0 && t < L ? [t - w / 2, t + w / 2] : null; }).filter(Boolean).sort((p, q) => p[0] - q[0]);
      const pieces = []; let t = 0;
      for (const [c0, c1] of cuts) { if (c0 > t) pieces.push([t, c0]); t = Math.max(t, c1); }
      if (t < L) pieces.push([t, L]);
      for (const [p0, p1] of pieces) {
        const n = Math.max(1, Math.round((p1 - p0) / 1500));
        for (let k = 0; k < n; k++) {
          const s0 = p0 + (p1 - p0) * k / n, s1 = p0 + (p1 - p0) * (k + 1) / n, seg = s1 - s0, mid = (s0 + s1) / 2;
          const mx = ax + ux * mid, mz = az + uz * mid, yaw = Math.atan2(-uz, ux);
          if (seg > 80) {
            const panel = new THREE.Mesh(new THREE.PlaneGeometry(seg - 60, 1800), MAT.mesh); panel.position.set(mx, 1000, mz); panel.rotation.y = yaw; fences.add(panel);
            const frame = block(fences, [seg - 60, 30, 30], [mx, 1900, mz], MAT.fence); frame.rotation.y = yaw;
          }
          post(ax + ux * s0, az + uz * s0); post(ax + ux * s1, az + uz * s1);
        }
      }
    }
  };
  // 開口寬：立放輸送架 ±405、光柵 ±450 → 1060；龍門北側 AGV 送棧板（1200 寬）、光柵 ±700 → 1520；
  // 龍門東側橫躺輸送（含南側底板到 +480）、光柵 ±550 → 1220
  fencePath(FENCE, false, [[...FENCE_GATES.in, 1060], [...FENCE_GATES.out, 1060]]);
  fencePath(GANTRY_FENCE, true, [[PALLET_STATION.x, 8950, 1520], [6700, LYING.z, 1220]]);
  // 光柵（入口）
  for (const [x, z, w, ax] of [[PALLET_STATION.x, 8950, 1400, 'x'], [...FENCE_GATES.in, 900, 'x'], [...FENCE_GATES.out, 900, 'x'], [6700, LYING.z, 1100, 'z']])
    for (const s of [-1, 1]) block(fences, [50, 1700, 50], [ax === 'x' ? x + s * w / 2 : x, 850, ax === 'x' ? z : z + s * w / 2], MAT.amber);

  section('cabinet');
  // ---------------------------------------------------------------- 控制櫃與人機
  const cab = (key, color, name) => { const [x0, z0, x1, z1, h] = FOOTPRINTS[key]; block(group, [x1 - x0, h, z1 - z0], [(x0 + x1) / 2, h / 2, (z0 + z1) / 2], color); plate(group, name, Math.min(700, x1 - x0 - 60), 160, [(x0 + x1) / 2, h - 150, z0 - 2], Math.PI, { w: 512, h: 120 }); };
  cab('robotCtrl', MAT.cabinet, ['R-30iB Plus']);
  cab('panel', MAT.cabinet, ['主控盤 PLC']);
  const [hx0, hz0, hx1, hz1] = FOOTPRINTS.hmi;
  block(group, [150, 1100, 150], [(hx0 + hx1) / 2, 550, (hz0 + hz1) / 2], MAT.steelDark);
  const hmi = block(group, [380, 280, 50], [(hx0 + hx1) / 2, 1250, (hz0 + hz1) / 2], MAT.screen); hmi.rotation.x = -.35;
  // 三色燈
  const tower = new THREE.Group(); tower.position.set(FENCE[1][0] + 100, 2000, FENCE[1][1] + 100); group.add(tower);
  const lamps = [MAT.red, MAT.amber, MAT.green].map((m, i) => cylinder(tower, 45, 90, [0, 200 - i * 95, 0], m.clone(), 'y', 28));
  rod(group, [FENCE[1][0] + 100, 0, FENCE[1][1] + 100], [FENCE[1][0] + 100, 1950, FENCE[1][1] + 100], 25, MAT.steel);

  // 緊固、驅動、光電、櫃門、導軌與軸承細節均在既有設備範圍內。
  section('gantry');
  for (const [x, z] of g.posts) foot(group, x, z, 280);
  section('decap');
  for (const [dx, dz] of [[-650, -400], [650, -400], [-650, 400], [650, 400]]) foot(group, up.x + dx, dc.z + dz, 160);
  section('cabinet');
  for (const key of ['panel', 'robotCtrl']) cabinetDetails(group, ...FOOTPRINTS[key]);
  section('lying');
  motor(group, ly.x0 + 380, axisY - 100, ly.z + 475, .65);
  section('upright');
  motor(group, up.x + 520, 220, up.z1 - 500, .7, Math.PI / 2);
  motor(bridge, 0, g.beamY + 480, p0[1], .65);
  section('upright');
  for (const z of [up.decap - 410, up.pick - 260, up.place + 300, up.z1 - 300]) sensor(group, up.x + 340, up.top + 90, z, Math.PI / 2);
  section('lying');
  for (const x of [ly.place, ly.label, ly.buffer]) sensor(group, x, axisY + 40, ly.z + 330);   // 低於夾爪下緣，避開龍門張開的夾爪
  for (const s of [-1, 1]) { block(z1, [20, 1240, 12], [s * 85, 650, 117], MAT.steelDark); block(trolley, [32, 220, 32], [s * 130, g.beamY + 150, 160], MAT.steel); }
  bolts(bridge, [-1, 1].flatMap(s => [-1, 1].map(k => [s * 200, g.beamY + 565, (p0[1] + p2[1]) / 2 + k * 600])), 14);
  sections.push([group.children.length, null]);
  for (let i = 0; i + 1 < sections.length; i++) for (const c of group.children.slice(sections[i][0], sections[i + 1][0])) c.userData.station ??= sections[i][1];
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
