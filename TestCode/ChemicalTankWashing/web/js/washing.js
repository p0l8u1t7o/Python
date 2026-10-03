// 沖洗站（PP 隔間、伸縮沖洗噴槍、集液漏斗、集液槽）與廢液回收系統（清水槽、回收沖洗水槽、廢液槽、泵、配管）。
import * as THREE from 'three';
import { BOOTH, WASTE, ROOM } from './layout.js';
import { block, blockBetween, cylinder, flowTexture, pipe, plate } from '@core/geom/shapes.js';
import { MAT } from '@core/geom/materials.js';
import { flange, gauge, bolts, motor } from '@core/geom/hardware.js';

export function createWashing(scene) {
  const group = new THREE.Group(); group.name = 'washing'; scene.add(group);
  const b = BOOTH, H = b.h, [ox0, ox1, oy0, oy1] = b.opening;
  // ---- 沖洗隔間：PP 板（半透明）＋不鏽鋼框 ----
  const walls = new THREE.Group(); group.add(walls);
  // 排液口穿牆套管：PP 板切出孔洞，管線不再穿過實心板。
  const sidePanel = (x, z, radius) => {
    const shape = new THREE.Shape(); shape.moveTo(0, 0); shape.lineTo(b.z1 - b.z0, 0); shape.lineTo(b.z1 - b.z0, H - 10); shape.lineTo(0, H - 10); shape.closePath();
    const opening = new THREE.Path(); opening.absarc(b.z1 - z, 120, radius, 0, Math.PI * 2, true); shape.holes.push(opening);
    const mesh = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: 20, bevelEnabled: false, curveSegments: 24 }), MAT.pp);
    mesh.rotation.y = Math.PI / 2; mesh.position.set(x, 0, b.z1); mesh.receiveShadow = mesh.castShadow = true; walls.add(mesh);
    // 中空套管環（不得用實心圓盤法蘭堵住排水）。
    const ring = new THREE.Mesh(new THREE.RingGeometry(radius - 3, radius + 14, 32), MAT.steel);
    ring.rotation.y = Math.PI / 2; ring.position.set(x - 1, 120, z); group.add(ring);
  };
  sidePanel(b.x0, (b.funnel.z0 + b.funnel.z1) / 2, 52);
  sidePanel(b.x1 - 20, 15150, 46);
  // PP 板頂緣埋進屋頂板、屋頂再低 2 mm：與框架頂面與屋頂設備底面都不共面
  blockBetween(walls, [b.x0, 0, b.z1 - 20], [b.x1, H - 10, b.z1], MAT.pp);
  const roofShape = new THREE.Shape(); roofShape.moveTo(b.x0, -b.z0); roofShape.lineTo(b.x1, -b.z0); roofShape.lineTo(b.x1, -b.z1); roofShape.lineTo(b.x0, -b.z1); roofShape.closePath();
  for (const [x, z, r] of [[...b.lance, 42], [...b.lance2, 20], [8900, 15250, 140]]) {
    const hole = new THREE.Path(); hole.absarc(x, -z, r, 0, Math.PI * 2, false); roofShape.holes.push(hole);
  }
  const roof = new THREE.Mesh(new THREE.ExtrudeGeometry(roofShape, {depth:20,bevelEnabled:false,curveSegments:24}), MAT.pp);
  roof.rotation.x = -Math.PI / 2; roof.position.y = H - 22; roof.castShadow = roof.receiveShadow = true; walls.add(roof);
  blockBetween(walls, [b.x0, 0, b.z0], [ox0, H - 10, b.z0 + 20], MAT.pp);
  blockBetween(walls, [ox1, 0, b.z0], [b.x1, H - 10, b.z0 + 20], MAT.pp);
  blockBetween(walls, [ox0, oy1, b.z0], [ox1, H - 10, b.z0 + 20], MAT.pp);
  blockBetween(walls, [ox0, 0, b.z0], [ox1, oy0, b.z0 + 20], MAT.pp);
  for (const [x, z] of [[b.x0, b.z0], [b.x1, b.z0], [b.x0, b.z1], [b.x1, b.z1], [ox0, b.z0], [ox1, b.z0]]) block(group, [60, H, 60], [x, H / 2, z], MAT.steel);
  for (const z of [b.z0, b.z1]) block(group, [b.x1 - b.x0 + 60, 60, 60], [(b.x0 + b.x1) / 2, H, z], MAT.steel);
  block(group, [ox1 - ox0 + 20, 50, 50], [(ox0 + ox1) / 2, oy1, b.z0], MAT.steel);
  // 開口兩側風刀：手臂帶桶退出時吹掉桶外表水珠
  const knives = [];
  for (const [x, s] of [[ox0 + 40, 1], [ox1 - 40, -1]]) {
    block(group, [60, 1700, 80], [x, 1350, b.z0 - 70], MAT.steel);
    const air = new THREE.Mesh(new THREE.PlaneGeometry(380, 1650), new THREE.MeshBasicMaterial({ color: 0xbfe8ff, transparent: true, opacity: .28, side: THREE.DoubleSide, depthWrite: false }));
    air.position.set(x + s * 190, 1350, b.z0 - 70); air.visible = false; air.userData.fx = true; group.add(air); knives.push(air);
  }
  // 開口上方的防濺簾（條狀 PVC）
  for (let x = ox0 + 60; x < ox1; x += 120) block(group, [100, 220, 4], [x, oy1 - 110, b.z0 + 40], MAT.pp);
  plate(group, ['沖洗站 · 酸鹼殘液'], 900, 160, [(b.x0 + b.x1) / 2, H + 140, b.z0 - 5], Math.PI, { w: 640, h: 110 });
  const lamp = new THREE.PointLight(0xdfefff, 0, 4000, 1); lamp.position.set(9400, 2300, 14700); group.add(lamp);

  // ---- 集液漏斗＋集液槽 ----
  const f = b.funnel, fw = f.x1 - f.x0, fd = f.z1 - f.z0, fx = (f.x0 + f.x1) / 2, fz = (f.z0 + f.z1) / 2;
  // 方錐漏斗：4 段圓錐轉 45° 成正方，再以群組縮放成長方開口
  const hopperG = new THREE.Group(); hopperG.position.set(fx, f.y - 200, fz); hopperG.scale.set(fw, 1, fd); group.add(hopperG);
  const hopper = new THREE.Mesh(new THREE.CylinderGeometry(Math.SQRT1_2, .1, 400, 4, 1, true), MAT.ppSolid.clone());
  hopper.material.side = THREE.DoubleSide; hopper.rotation.y = Math.PI / 4; hopper.receiveShadow = true; hopperG.add(hopper);
  for (const [x, z] of [[f.x0, f.z0], [f.x1, f.z0], [f.x0, f.z1], [f.x1, f.z1]]) block(group, [50, f.y, 50], [x, f.y / 2, z], MAT.steel);
  block(group, [600, 240, 600], [fx, 120, fz], MAT.ppDark);                                   // 集液槽 SUMP（漏斗正下方）
  const sumpLevel = block(group, [560, 1, 560], [fx, 10, fz], MAT.waste);
  const pool = new THREE.Mesh(new THREE.PlaneGeometry(fw * .55, fd * .55), MAT.water); pool.rotation.x = -Math.PI / 2; pool.position.set(fx, f.y - 230, fz); pool.visible = false; pool.userData.fx = true; group.add(pool);

  // ---- 沖洗噴槍：2" 旋轉噴頭（長行程，末道兼負壓抽液管）＋3/4" 直噴頭，皆由屋頂氣缸推出 ----
  const [lx, lz] = b.lance, [lx2, lz2] = b.lance2;
  const lanceY = ext => b.lanceUp + (b.lanceDown - b.lanceUp) * ext;   // 噴頭高度
  const LONG = 1750;                                                     // 2" 噴槍管長：伸到桶底時頂端仍在隔間內
  block(group, [90, 1500, 90], [lx + 110, H + 750, lz], MAT.alu);              // 長行程無桿氣缸導軌
  const guide = new THREE.Mesh(new THREE.CylinderGeometry(40, 40, 1300, 24, 1, true), MAT.ppSolid);
  guide.position.set(lx, H + 650, lz); group.add(guide);           // 中空屋頂導管
  cylinder(group, 50, 300, [lx2, H + 150, lz2], MAT.steel, 'y', 28);
  const lance = new THREE.Group(); group.add(lance);
  cylinder(lance, 16, LONG, [0, LONG / 2, 0], MAT.steel, 'y', 12);
  block(lance, [140, 60, 80], [60, LONG, 0], MAT.steelDark);                    // 氣缸滑塊
  cylinder(lance, 24, 60, [0, 20, 0], MAT.steelDark, 'y', 12);
  const lance2 = new THREE.Group(); group.add(lance2);
  cylinder(lance2, 9, 900, [0, 450, 0], MAT.steel, 'y', 10);
  cylinder(lance2, 10, 40, [0, 15, 0], MAT.steelDark, 'y', 10);
  const sprayMat = MAT.water.clone(); sprayMat.opacity = .35; sprayMat.side = THREE.DoubleSide;
  const spray = new THREE.Mesh(new THREE.ConeGeometry(240, 420, 24, 1, true), sprayMat); spray.position.y = -210; spray.visible = false; spray.userData.fx = true; lance.add(spray);
  const jet = new THREE.Mesh(new THREE.CylinderGeometry(14, 22, 700, 10, 1, true), sprayMat); jet.position.y = -350; jet.visible = false; jet.userData.fx = true; lance2.add(jet);
  // 熱風機 HB-1（屋頂）：鼓風機＋電熱器，經 3/4" 噴槍送入熱風
  block(group, [460, 340, 380], [9330, H + 170, 15150], MAT.steelOrange);
  plate(group, ['HB-1 熱風機 70°C'], 600, 120, [9330, H + 430, 14955], Math.PI, { w: 640, h: 110 });
  // 真空泵 VP-1（屋頂）：抽液管頂端軟管 → 真空泵 → 集液槽
  block(group, [520, 380, 420], [9850, H + 190, 15150], MAT.steelBlue);
  plate(group, ['VP-1 真空泵（負壓抽液）'], 700, 120, [9850, H + 480, 14935], Math.PI, { w: 640, h: 110 });

  // ---- 倒液水柱（每幀由桶口位置更新）----
  const streamTex = flowTexture(0x7fcfff); streamTex.repeat.set(1, 6); streamTex.wrapT = THREE.RepeatWrapping;
  const streamMat = new THREE.MeshStandardMaterial({ color: 0x9fdcff, map: streamTex, transparent: true, opacity: .75, emissive: 0x1d5f8f, emissiveIntensity: .5, depthWrite: false });
  const stream = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 12, 1, true), streamMat); stream.visible = false; stream.userData.fx = true; group.add(stream);

  // ---- 廢液回收（圍籬外西南側）：防溢堤＋三槽 ----
  const [bx0, bz0, bx1, bz1] = WASTE.bund;
  const bw = WASTE.wall;
  block(group, [bx1 - bx0 - 2 * bw, 40, bz1 - bz0 - 2 * bw], [(bx0 + bx1) / 2, 20, (bz0 + bz1) / 2], MAT.ppDark);   // 底板在堤牆內側
  for (const [w, d, x, z] of [[bx1 - bx0, bw, (bx0 + bx1) / 2, bz0 + bw / 2], [bx1 - bx0, bw, (bx0 + bx1) / 2, bz1 - bw / 2], [bw, bz1 - bz0, bx0 + bw / 2, (bz0 + bz1) / 2], [bw, bz1 - bz0, bx1 - bw / 2 - 40, (bz0 + bz1) / 2]]) block(group, [w, 300, d], [x, 150, z], MAT.steelOrange);   // 東堤牆內退 40 mm，讓出清洗區圍籬立柱
  const tanks = {};
  for (const [k, t] of Object.entries(WASTE.tanks)) {
    const shell = cylinder(group, t.r, t.h, [t.x, 40 + t.h / 2, t.z], MAT.tankW, 'y', 36); shell.castShadow = false;
    cylinder(group, t.r + 5, 30, [t.x, 40 + t.h + 15, t.z], MAT.ppSolid, 'y', 36);
    const liquid = cylinder(group, t.r - 25, 1, [t.x, 50, t.z], k === 'WA' ? MAT.tankWaste : k === 'WB' ? MAT.tankAlkali : k === 'R' ? MAT.tankClean : MAT.tankFresh, 'y', 32);
    plate(group, [t.name, `${t.cap} L`], Math.max(700, t.r * 1.8), 230, [t.x, t.h + 330, t.z - t.r - 10], Math.PI, { w: 640, h: 210 });
    // 外置液位視管，實物模式也能看液位；法蘭、維修蓋與束帶。
    const sight = cylinder(group, 12, 1, [t.x, 80, t.z - t.r - 18], k === 'WA' ? MAT.tankWaste : k === 'WB' ? MAT.tankAlkali : MAT.tankClean, 'y', 10);
    for (const yy of [95, t.h - 20]) cylinder(group, 21, 32, [t.x, yy, t.z - t.r - 18], MAT.steelDark, 'y', 28);
    for (let yy = 160; yy < t.h; yy += 200) block(group, [42, 4, 4], [t.x + 33, yy, t.z - t.r - 17], MAT.black);
    cylinder(group, Math.min(t.r * .45, 165), 45, [t.x - t.r * .35, t.h + 75, t.z], MAT.ppDark, 'y', 28);
    flange(group, t.x, t.h + 55, t.z, 58);
    for (const yy of [t.h * .28, t.h * .7]) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(t.r + 2, 7, 6, 48), MAT.ppDark); ring.rotation.x = Math.PI / 2; ring.position.set(t.x, yy + 40, t.z); group.add(ring);
    }
    tanks[k] = { t, liquid, sight };
  }
  // 泵：P-1 沖洗泵（多段離心，PVDF 接液）、P-2 氣動隔膜泵（集液槽送出）
  const [p1x, p1z] = WASTE.pumpRinse, [p2x, p2z] = WASTE.pumpDrain;
  block(group, [250, 120, 500], [p1x, 60, p1z], MAT.steelDark); cylinder(group, 100, 300, [p1x, 300, p1z + 60], MAT.steelBlue, 'z', 20); cylinder(group, 110, 120, [p1x, 300, p1z - 160], MAT.ppSolid, 'z', 20);
  block(group, [250, 420, 360], [p2x, 210, p2z], MAT.ppDark); cylinder(group, 140, 50, [p2x, 260, p2z - 200], MAT.ppSolid, 'z', 20); cylinder(group, 140, 50, [p2x, 260, p2z + 200], MAT.ppSolid, 'z', 20);
  plate(group, ['P-1 沖洗泵'], 420, 110, [p1x + 130, 560, p1z], Math.PI / 2, { w: 512, h: 130 });
  plate(group, ['P-2 隔膜泵'], 420, 110, [p2x + 130, 560, p2z], Math.PI / 2, { w: 512, h: 130 });
  const tA = WASTE.tanks.WA, tB = WASTE.tanks.WB, tR = WASTE.tanks.R, tF = WASTE.tanks.F;
  const pipes = {
    fromF: pipe(group, [[tF.x + tF.r, 150, tF.z], [p1x - 180, 150, tF.z], [p1x - 180, 150, p1z - 160], [p1x - 60, 300, p1z - 160]], 30, 0x8fd3ff),
    fromR: pipe(group, [[tR.x + tR.r, 150, tR.z], [p1x - 60, 150, tR.z], [p1x - 60, 300, p1z - 160]], 30, 0x58b6f2),
    supply: pipe(group, [[p1x, 420, p1z - 160], [p1x, 2800, p1z - 160], [lx, 2800, p1z - 160], [lx, 2800, lz - 300], [lx2, 2800, lz2 - 300], [lx2, H + 320, lz2 - 300], [lx2, H + 320, lz2]], 30, 0x4aa8ff),
    supply2: pipe(group, [[lx, 2800, lz - 300], [lx, 2800, lz - 150], [lx, H + 1350, lz - 150], [lx, H + 1350, lz]], 26, 0x4aa8ff),
    hot: pipe(group, [[9330, H + 340, 15150], [9330, H + 700, 15150], [lx2, H + 700, 15150], [lx2, H + 700, lz2 + 150], [lx2, H + 320, lz2 + 150], [lx2, H + 320, lz2 + 40]], 26, 0xff5a3c),
    vac: pipe(group, [[lx, H + 1350, lz + 120], [lx, H + 1350, 15150], [9850, H + 1350, 15150], [9850, H + 380, 15150]], 26, 0xb07cff),
    vacOut: pipe(group, [[10110, H + 100, 15150], [10150, H + 100, 15150], [10150, 120, 15150], [fx + 300, 120, 15150], [fx + 300, 120, fz + 300]], 30, 0xb07cff),
    sump: pipe(group, [[fx - 300, 120, fz], [b.x0 - 150, 120, fz], [b.x0 - 150, 120, p2z], [7200, 120, p2z], [7200, 2250, p2z], [p2x + 125, 2250, p2z], [p2x + 125, 420, p2z]], 36, 0xd88a3c),
    riser: pipe(group, [[p2x, 420, p2z], [p2x, 2100, p2z]], 34, 0xd88a3c),
    toWB: pipe(group, [[p2x, 2100, p2z], [tB.x, 2100, p2z], [tB.x, 2100, tB.z], [tB.x, 40 + tB.h, tB.z]], 34, 0xb07cff),
    toWA: pipe(group, [[p2x, 2100, p2z], [p2x, 2100, p2z + 200], [tA.x, 2100, p2z + 200], [tA.x, 2100, tA.z], [tA.x, 40 + tA.h, tA.z]], 34, 0xff7a45),
    toR: pipe(group, [[p2x, 2100, p2z], [p2x, 2100, tR.z], [tR.x, 2100, tR.z], [tR.x, 40 + tR.h, tR.z]], 34, 0x3dd68c),
    city: pipe(group, [[tF.x, 2400, ROOM.D], [tF.x, 2400, tF.z], [tF.x, 40 + tF.h, tF.z]], 26, 0x8fd3ff),
    outA: pipe(group, [[tA.x, 150, tA.z + tA.r], [tA.x, 150, bz1 - 100], [tA.x, 420, bz1 - 100], [tA.x, 420, ROOM.D - 60], [tA.x, 900, ROOM.D - 60]], 34, 0xff7a45),
    outB: pipe(group, [[tB.x, 150, tB.z + tB.r], [tB.x, 150, bz1 - 100], [tB.x, 420, bz1 - 100], [tB.x, 420, ROOM.D - 60], [tB.x, 900, ROOM.D - 60]], 34, 0xb07cff),
  };
  block(group, [180, 180, 180], [p2x, 2100, p2z], MAT.steelOrange);                         // V-3 三通切換閥
  for (const t of [tA, tB]) block(group, [260, 160, 120], [t.x, 900, ROOM.D - 70], MAT.steelOrange);   // 委外清運接頭（酸、鹼分開）
  block(group, [160, 160, 160], [p2x, 2100, p2z + 200], MAT.steelOrange);                     // V-4 酸／鹼切換閥
   // 排氣
  cylinder(group, 140, ROOM.H - H - 100, [8900, H + (ROOM.H - H - 100) / 2, 15250], MAT.ppSolid, 'y', 20);
  plate(group, ['排氣 → 廠務洗滌塔'], 900, 140, [9000, 3700, 14990], Math.PI, { w: 640, h: 100 });

  // 管線法蘭與泵壓表；屋頂機組散熱片。
  for (const z of [p1z - 160, p2z]) flange(group, p1x, 600, z, 48);
  gauge(group, p1x - 75, 650, p1z - 180);
  for (let i = 0; i < 9; i++) { block(group, [5, 190, 280], [9170 + i * 38, H + 210, 15150], MAT.steelDark); block(group, [400, 6, 4], [9850, H + 80 + i * 25, 14937], MAT.black); }
  const _a = new THREE.Vector3(), _b = new THREE.Vector3();
  return {
    group, walls, pipes, tanks, lance, lance2, lanceTip: () => new THREE.Vector3(lx, lanceY(lance.userData.ext || 0), lz),
    set({ knife = false, lance: ext = 0, lance2: ext2 = 0, spray: sp = false, pour = null, pool: pl = 0, sump = 0, tanks: lv = null, flows = {} }) {
      lance.position.set(lx, lanceY(ext), lz); lance.userData.ext = ext; lance2.position.set(lx2, lanceY(ext2), lz2);
      spray.visible = sp; jet.visible = sp; lamp.intensity = 500; for (const a of knives) a.visible = knife;
      if (pour) {
        _a.copy(pour); _b.set(pour.x, f.y - 120, pour.z);
        const L = _a.y - _b.y; stream.visible = L > 10; stream.position.set(_a.x, (_a.y + _b.y) / 2, _a.z); stream.scale.set(22, L, 22);
      } else stream.visible = false;
      pool.visible = pl > 0; pool.scale.setScalar(Math.max(.2, pl));
      sumpLevel.scale.y = Math.max(1, sump * 200); sumpLevel.position.y = 10 + sumpLevel.scale.y / 2;
      if (lv) for (const k of ['WA', 'WB', 'R', 'F']) { const { t, liquid, sight } = tanks[k], h = Math.max(1, (lv[k] / t.cap) * (t.h - 40)); liquid.scale.y = h; liquid.position.y = 50 + h / 2; sight.scale.y = Math.max(1, h - 40); sight.position.y = 80 + sight.scale.y / 2; }
      for (const [k, p] of Object.entries(pipes)) p.setFlow(!!flows[k]);
    },
    tick(time) { for (const p of Object.values(pipes)) p.tick(time); streamTex.offset.y = -time * 3; spray.rotation.y = time * 3; },
  };
}
