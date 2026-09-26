// 實驗桌、設備與器皿（樣品瓶、瓶蓋、滴定杯、移液模組、吸頭）
import * as THREE from 'three';
import { cable, cableTray, carrier, CABLE } from './cable-routing.js';
import { finish } from './finish.js';
import { perforated } from './perforated.js';
import { block, cylinder, decal, tube } from './detail.js';
import { Y0, BENCH, ST, BEAKER, BOTTLES, CAP, PIPETTE, SAMPLES } from './layout.js';
import { glass, glassRim, liquidMaterial, glassVessel, glassBottle, graduations, createLiquid, rim, screw, flowLine, tipFillHeight } from './render-details.js';

const M = {
  bench: new THREE.MeshStandardMaterial({ color: 0x3a4048, roughness: 0.75, metalness: 0.1 }),
  benchTop: new THREE.MeshStandardMaterial({ color: 0xd9dcd6, roughness: 0.6 }),          // 耐酸鹼實驗桌面
  frame: new THREE.MeshStandardMaterial({ color: 0x5b6470, roughness: 0.5, metalness: 0.6 }),
  steel: new THREE.MeshStandardMaterial({ color: 0xb8bec5, roughness: 0.3, metalness: 0.85 }),
  white: new THREE.MeshStandardMaterial({ color: 0xeef0ee, roughness: 0.45 }),
  grey: new THREE.MeshStandardMaterial({ color: 0x8c949c, roughness: 0.5, metalness: 0.2 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x23272c, roughness: 0.55, metalness: 0.3 }),
  metrohm: new THREE.MeshStandardMaterial({ color: 0xd8dde2, roughness: 0.4, metalness: 0.1 }),
  metrohmDark: new THREE.MeshStandardMaterial({ color: 0x33414f, roughness: 0.45, metalness: 0.2 }),
  pom: new THREE.MeshStandardMaterial({ color: 0xf4f1e8, roughness: 0.6 }),
  blue: new THREE.MeshStandardMaterial({ color: 0x2f6fb5, roughness: 0.5 }),
  cap: new THREE.MeshStandardMaterial({ color: 0x2c6fcf, roughness: 0.55 }),
  capRed: new THREE.MeshStandardMaterial({ color: 0xd24a3c, roughness: 0.55 }),
  glass,
  shield: new THREE.MeshPhysicalMaterial({ color: 0xcfe6ff, roughness: 0.05, transparent: true, opacity: 0.18, depthWrite: false }),
  tip: new THREE.MeshPhysicalMaterial({ color: 0xe5eeee, roughness: .21, clearcoat: .6, transparent: true, opacity: .28, depthWrite: false, side: THREE.DoubleSide }),
  liquid: liquidMaterial,
  laser: new THREE.MeshBasicMaterial({ color: 0xff3030, transparent: true, opacity: 0.8 }),
  zoneWarn: new THREE.MeshBasicMaterial({ color: 0xffb020, transparent: true, opacity: 0.1, depthWrite: false, side: THREE.DoubleSide }),
  zoneStop: new THREE.MeshBasicMaterial({ color: 0xff4d4d, transparent: true, opacity: 0.12, depthWrite: false, side: THREE.DoubleSide }),
  screen: new THREE.MeshBasicMaterial({ color: 0x0b1220 }),
  led: new THREE.MeshStandardMaterial({ color: 0x3dd68c, emissive: 0x3dd68c, emissiveIntensity: 0.9 }),
};

for (const name of ['white','grey','metrohm','metrohmDark','pom','cap','capRed']) finish(M[name],'polymer',.02);
finish(M.steel,'metal',.008); finish(M.benchTop,'polymer',.035);
// 空心圓筒（器皿壁）
function vessel(parent, r, h, material, bottom = 2) {
  if (material === M.glass) return glassVessel(parent, r, h, bottom);
  const g = new THREE.Group(); parent.add(g);
  const wall = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 36, 1, true), material); wall.position.y = h / 2; g.add(wall);
  const floor = new THREE.Mesh(new THREE.CylinderGeometry(r, r, bottom, 36), material); floor.position.y = bottom / 2; g.add(floor);
  return g;
}
function ring(parent, rIn, rOut, h, pos, material) {
  const shape = new THREE.Shape(); shape.absarc(0, 0, rOut, 0, Math.PI * 2);
  const hole = new THREE.Path(); hole.absarc(0, 0, rIn, 0, Math.PI * 2, true); shape.holes.push(hole);
  const geo = new THREE.ExtrudeGeometry(shape, { depth: h, bevelEnabled: false, curveSegments: 36 }); geo.rotateX(-Math.PI / 2);
  const m = new THREE.Mesh(geo, material); m.position.set(...pos); m.castShadow = m.receiveShadow = true; parent.add(m); return m;
}
// 動態文字貼圖（天平讀值、螢幕）：Node 驗證環境沒有真正的 canvas，只建立空殼
function liveText(w, h, pxW = 512, pxH = 160) {
  const real = typeof window !== 'undefined';
  const c = real ? document.createElement('canvas') : null; if (c) { c.width = pxW; c.height = pxH; }
  const tex = c ? new THREE.CanvasTexture(c) : null; if (tex) tex.colorSpace = THREE.SRGBColorSpace;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), tex ? new THREE.MeshBasicMaterial({ map: tex }) : M.screen);
  let last = '';
  function draw(key, fn) { if (!c || key === last) return; last = key; const ctx = c.getContext('2d'); fn(ctx, pxW, pxH); tex.needsUpdate = true; }
  return { mesh, draw };
}

export function createLab(scene) {
  const root = new THREE.Group(); root.name = 'lab'; scene.add(root);
  const keepout = [];                                 // { name, mesh } 固定結構（驗證用）
  const K = (name, mesh) => { mesh.userData.keep = name; keepout.push({ name, mesh }); return mesh; };
  const W = (x, y, z) => [x, Y0 + y, z];

  // ---------------------------------------------------------------- 地面與實驗桌
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(9000, 7000), new THREE.MeshStandardMaterial({ color: 0x1a1f26, roughness: 0.95 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; root.add(floor);
  const grid = new THREE.GridHelper(9000, 90, 0x2c3440, 0x222831); grid.position.y = 1; root.add(grid);
  const [bx0, bx1] = BENCH.x, [bz0, bz1] = BENCH.z, bw = bx1 - bx0, bd = bz1 - bz0;
  const bench=perforated(root,[bw,40,bd],[0,Y0-20,0],[[ST.dock.x,ST.dock.z,22],[ST.tipChute.x,ST.tipChute.z,34],[ST.funnel.x,ST.funnel.z,10],[-165,0,14]],M.benchTop);bench.name='bench-with-service-bores';K('bench',bench);
  perforated(root, [bw - 40, 30, bd - 40], [0, Y0 - 55, 0], [[-165,0,14]], M.frame);
  for (const x of [bx0 + 40, 0, bx1 - 40]) for (const z of [bz0 + 40, bz1 - 40]) block(root, [50, Y0 - 70, 50], [x, (Y0 - 70) / 2, z], M.frame);
  block(root, [bw - 80, 20, bd - 120], [0, 180, 0], M.frame);                                   // 下層板
  // 桌下：手臂控制器、I/O、廢液桶
  block(root, [430, 190, 360], [-300, 285, 0], M.dark); decal(root, 180, 40, [-300, 300, 181], [0, 0, 0], 'DENSO RC9', { color: '#e6edf3', center: true, bold: true });
  block(root, [360, 300, 320], [260, 340, 30], M.grey); decal(root, 200, 50, [260, 400, 191], [0, 0, 0], ['整合控制盤', 'I/O・安全模組'], { color: '#20242a', center: true });
  const jerry = block(root, [260, 330, 200], [60, 355, -340], new THREE.MeshStandardMaterial({ color: 0xe3e6d9, roughness: 0.6 }));
  decal(root, 150, 60, [60, 420, -239], [0, 0, 0], ['廢液桶', '液位開關'], { color: '#b33', center: true, bold: true });
  cylinder(root, 12, Y0 - 540, [100, (Y0 + 520) / 2, -345], M.pom);                           // 漏斗排液管
  tube(root, [[100, 520, -345], [80, 510, -345], [60, 525, -330]], 10, M.pom);

  // ---------------------------------------------------------------- 分析天平（上方滑門，由手臂推開）
  const B = ST.balance, ch = B.chamber, cx = (ch.x[0] + ch.x[1]) / 2, cz = (ch.z[0] + ch.z[1]) / 2, cw = ch.x[1] - ch.x[0], cd = ch.z[1] - ch.z[0];
  const balance = new THREE.Group(); root.add(balance);
  K('balance', block(balance, [ch.x[1] - ch.x[0] + 30, ch.y[0], cd + 50], [cx, Y0 + ch.y[0] / 2, cz], M.white));
  K('balance', block(balance, [80, 40, 180], [ch.x[1] + 50, Y0 + 20, cz], M.white));            // 前方操作面板
  const panel = liveText(64, 30, 320, 150); panel.mesh.position.set(ch.x[1] + 70, Y0 + 41, cz); panel.mesh.rotation.set(-Math.PI / 2 + 0.35, Math.PI / 2, 0, 'YXZ'); balance.add(panel.mesh);
  cylinder(balance, 45, 3, [B.x, Y0 + B.pan - 1.5, B.z], M.steel, 'y', 36);                     // 秤盤 Ø90
  cylinder(balance, 8, B.pan - ch.y[0], [B.x, Y0 + (B.pan + ch.y[0]) / 2, B.z], M.steel);
  rim(balance, 43.5, Y0 + B.pan, M.steel, .5).position.set(B.x, Y0+B.pan, B.z);
  for (const x of [ch.x[0]+15,ch.x[1]-15]) for (const z of [ch.z[0]+15,ch.z[1]-15]) screw(balance,x,Y0+ch.y[0]+.6,z,M.steel);
  const hWall = ch.y[1] - ch.y[0], wy = Y0 + (ch.y[0] + ch.y[1]) / 2;
  // 防風罩：前後左右玻璃＋框（手臂從上方進出）
  K('balance-wall', block(balance, [6, hWall, cd], [ch.x[0], wy, cz], M.shield));
  K('balance-wall', block(balance, [6, hWall, cd], [ch.x[1], wy, cz], M.shield));
  K('balance-wall', block(balance, [cw, hWall, 6], [cx, wy, ch.z[0]], M.shield));
  K('balance-wall', block(balance, [cw, hWall, 6], [cx, wy, ch.z[1]], M.shield));
  for (const x of ch.x) for (const z of ch.z) block(balance, [10, hWall, 10], [x, wy, z], M.grey);
  for (const z of ch.z) block(balance, [cw + 260, 8, 12], [cx - 130, Y0 + ch.y[1] + 4, z], M.grey);   // 滑門導軌（往後延伸）
  const door = new THREE.Group(); balance.add(door);                                              // 上方滑門
  K('balance-door', block(door, [cw - 6, 5, cd - 4], [cx, Y0 + ch.y[1] + 10, cz], M.shield));
  K('balance-door', block(door, [8, 22, 40], [B.tab, Y0 + ch.y[1] + 23, cz], M.grey));          // 推把
  for (const z of [ch.z[0] + 5, ch.z[1] - 5]) block(door, [cw - 6, 7, 8], [cx, Y0 + ch.y[1] + 11, z], M.grey);        // 門框
  for (const x of [ch.x[0] + 6, ch.x[1] - 6]) block(door, [8, 7, cd - 4], [x, Y0 + ch.y[1] + 11, cz], M.grey);
  decal(balance, 120, 26, [ch.x[1] + 3.5, Y0 + ch.y[0] - 25, cz], [0, Math.PI / 2, 0], '0.1 mg 分析天平', { color: '#39414a', center: true, bold: true });

  // ---------------------------------------------------------------- 樣品瓶座＋開蓋區（氣動自定心 V 型夾座）
  const C = ST.clamp, clamp = new THREE.Group(); clamp.position.set(C.x, Y0, C.z); root.add(clamp);
  K('clamp', block(clamp, [230, C.base, 190], [0, C.base / 2, 0], M.steel));
  const jaws = [];
  for (const s of [-1, 1]) {
    const jg = new THREE.Group(); clamp.add(jg);
    K('clamp', block(jg, [120, 36, 26], [0, C.base + 26, 0], M.pom));                          // V 型夾爪（示意為平面）
    block(jg, [60, 30, 40], [0, C.base + 22, s * 34], M.steel);
    jg.userData.side = s; jaws.push(jg);
  }
  for (const s of [-1, 1]) K('clamp', block(clamp, [70, 44, 50], [0, C.base + 22, s * 88], M.grey));   // 氣缸
  decal(clamp, 110, 20, [0, C.base + 0.6, 80], [-Math.PI / 2, 0, 0], '樣品瓶座 / 開蓋', { color: '#20242a', center: true, bold: true });
  const capRest = new THREE.Group(); capRest.position.set(ST.capRest.x, Y0, ST.capRest.z); root.add(capRest);
  K('caprest', cylinder(capRest, 38, ST.capRest.base, [0, ST.capRest.base / 2, 0], M.pom, 'y', 32));
  ring(capRest, 28, 34, 6, [0, ST.capRest.base, 0], M.pom);
  const holder = new THREE.Group(); holder.position.set(ST.holder.x, Y0, ST.holder.z); root.add(holder);
  K('holder', cylinder(holder, 55, 6, [0, 3, 0], M.steel, 'y', 36));
  ring(holder, BEAKER.d / 2 + 2, BEAKER.d / 2 + 10, ST.holder.base + 12, [0, 0, 0], M.pom);
  decal(holder, 80, 16, [0, 6.6, 45], [-Math.PI / 2, 0, 0], '滴定杯座', { color: '#20242a', center: true, bold: true });

  // ---------------------------------------------------------------- 移液區：廢液漏斗、吸頭廢料口、吸頭架、移液模組停放座
  const F = ST.funnel;
  const funnel = new THREE.Mesh(new THREE.CylinderGeometry(52, 10, F.top - 10, 32, 1, true), new THREE.MeshStandardMaterial({ color: 0xf4f1e8, roughness: 0.6, side: THREE.DoubleSide }));
  funnel.position.set(F.x, Y0 + 10 + (F.top - 10) / 2, F.z); root.add(K('funnel', funnel));
  ring(root,10,60,10,[F.x,Y0,F.z],M.steel);
  const S = ST.tipChute, strip = new THREE.Group(); strip.position.set(S.x, Y0, S.z); root.add(strip);
  // 局部 +Z 朝手臂：支柱在遠端，叉口開向手臂
  ring(strip, 34, 44, 5, [0, 0, 0], M.dark); // 真正落料孔，不以實心黑片封住
  K('chute', ring(strip, 44, 48, 12, [0, 0, 0], M.steel));
  decal(strip, 70, 16, [0, 1, 62], [-Math.PI / 2, 0, 0], '吸頭廢料口', { color: '#e6edf3', center: true, bold: true });
  const TR = ST.tipRack, tipRack = new THREE.Group(); root.add(tipRack);
  const trx = TR.x0 + (TR.n - 1) * TR.pitch / 2, trz = (TR.z[0] + TR.z[1]) / 2;
  const tipHoles=TR.z.flatMap(z=>Array.from({length:TR.n},(_,i)=>[TR.x0+i*TR.pitch-trx,z-trz,PIPETTE.tipR+.6]));
  const rackBody=perforated(tipRack,[TR.n*TR.pitch+16,TR.top-35,70],[trx,Y0+15+(TR.top-35)/2,trz],tipHoles,M.blue);rackBody.name='tiprack-bored-body';K('tiprack',rackBody);
  block(tipRack,[TR.n*TR.pitch+16,15,70],[trx,Y0+7.5,trz],M.blue);
  perforated(tipRack,[TR.n*TR.pitch+16,6,70],[trx,Y0+TR.top-17,trz],tipHoles,M.white);
  const D = ST.dock, dock = new THREE.Group(); dock.position.set(D.x, Y0, D.z); root.add(dock);
  const ddir = new THREE.Vector3(D.x, 0, D.z).normalize();
  ring(dock,22,26,4,[0,0,0],M.dark); // 吸頭可穿過桌面孔
  K('dock', block(dock, [30, D.collar - 6, 30], [ddir.x * 55, (D.collar - 6) / 2, ddir.z * 55], M.steel));
  const fork = ring(dock, 21, 34, 8, [0, D.collar - 23, 0], M.pom); K('dock', fork);
  decal(dock, 70, 16, [ddir.x * 55 - ddir.z * 16, 120, ddir.z * 55 + ddir.x * 16], [0, Math.atan2(-ddir.z, ddir.x), 0], '移液模組座', { color: '#e6edf3', center: true, bold: true });

  // ---------------------------------------------------------------- 條碼讀取器（固定式，手臂把瓶子送到讀取點旋轉）
  const SC = ST.scanner, scanner = new THREE.Group(); scanner.position.set(SC.x, Y0, SC.z); root.add(scanner);
  K('scanner', block(scanner, [40, SC.h - 20, 40], [0, (SC.h - 20) / 2, -20], M.dark));
  K('scanner', block(scanner, [60, 40, 70], [0, SC.h, 0], M.dark));
  const beam = new THREE.Mesh(new THREE.PlaneGeometry(70, 100), M.laser); beam.rotation.x = -Math.PI / 2; beam.position.set(0, SC.h, 85); beam.visible = false; scanner.add(beam);
  const beamPlane = new THREE.Mesh(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 35), new THREE.Vector3(-40, 0, 125), new THREE.Vector3(40, 0, 125)]), M.laser);
  beamPlane.geometry.setIndex([0, 1, 2]); beamPlane.position.y = SC.h - 20; beamPlane.material.side = THREE.DoubleSide; beamPlane.visible = false; scanner.add(beamPlane);

  // ---------------------------------------------------------------- 料架：待處理杯區、待驗樣品瓶區、完成樣品瓶區、完成滴定杯區
  const rackPlate = (name, cols, rows, base, pitchX, pitchZ, hole) => {
    const xs = cols, zs = rows, x0 = Math.min(...xs) - pitchX / 2, x1 = Math.max(...xs) + pitchX / 2, z0 = Math.min(...zs) - pitchZ / 2, z1 = Math.max(...zs) + pitchZ / 2;
    K(name, block(root, [x1 - x0, base, z1 - z0], [(x0 + x1) / 2, Y0 + base / 2, (z0 + z1) / 2], M.pom));
    for (const x of xs) for (const z of zs) ring(root, hole, hole + 5, 10, [x, Y0 + base, z], M.pom);
  };
  const ER = ST.emptyRack; rackPlate('rack-empty', ER.cols, ER.rows, ER.base, 100, 80, BEAKER.d / 2 + 2);
  const DR = ST.doneRack; rackPlate('rack-done', DR.cols, DR.rows, DR.base, 100, 80, BEAKER.d / 2 + 2);
  for (const rk of [ST.sampleRack, ST.doneBottleRack]) {
    const zs = [rk.rows[500], rk.rows[100]], name = rk === ST.sampleRack ? 'rack-sample' : 'rack-donebottle';
    K(name, block(root, [3 * rk.pitch, rk.base, 250], [(rk.cols[0] + rk.cols[2]) / 2, Y0 + rk.base / 2, (zs[0] + zs[1]) / 2], M.pom));
    for (const x of rk.cols) { ring(root, BOTTLES[500].d / 2 + 2, BOTTLES[500].d / 2 + 7, 12, [x, Y0 + rk.base, zs[0]], M.pom); ring(root, BOTTLES[100].d / 2 + 2, BOTTLES[100].d / 2 + 7, 12, [x, Y0 + rk.base, zs[1]], M.pom); }
  }
  const tagPos = [[ER.cols[1], ER.rows[0] - 55, '待處理杯區'], [DR.cols[1], DR.rows[3] + 50, '完成滴定杯區'], [ST.sampleRack.cols[1], ST.sampleRack.rows[100] + 58, '待驗樣品瓶區'], [ST.doneBottleRack.cols[1], ST.doneBottleRack.rows[100] + 58, '完成樣品瓶區']];
  for (const [x, z, t] of tagPos) decal(root, 120, 24, [x, Y0 + 0.6, z], [-Math.PI / 2, 0, 0], t, { color: '#c9d1d9', center: true, bold: true });

  // ---------------------------------------------------------------- Metrohm 自動進樣器（轉盤＋滴定頭）＋滴定儀＋電腦
  const SP = ST.sampler, H = SP.housing, sampler = new THREE.Group(); root.add(sampler);
  K('sampler', block(sampler, [H.x[1] - H.x[0], H.h, H.z[1] - H.z[0]], [(H.x[0] + H.x[1]) / 2, Y0 + H.h / 2, (H.z[0] + H.z[1]) / 2], M.metrohm));
  decal(sampler, 150, 26, [(H.x[0] + H.x[1]) / 2, Y0 + 40, H.z[1] + 0.6], [0, 0, 0], 'Metrohm', { color: '#1b4f8a', center: true, bold: true });
  const rack = new THREE.Group(); rack.position.set(SP.x, Y0, SP.z); sampler.add(rack);
  for (const x of [H.x[0]+16,H.x[1]-16]) for (const z of [H.z[0]+16,H.z[1]-16]) screw(sampler,x,Y0+H.h+.7,z,M.steel);
  K('sampler', cylinder(rack, 205, SP.plate - H.h, [0, H.h + (SP.plate - H.h) / 2, 0], M.metrohmDark, 'y', 64));
  cylinder(rack,24,8,[0,SP.plate+4,0],M.steel,'y',48);
  for(let i=0;i<6;i++){const a=i*Math.PI/3;screw(rack,Math.cos(a)*17,SP.plate+8.6,Math.sin(a)*17,M.steel);}
  const slotPos = s => { const a = s * 2 * Math.PI / SP.slots; return [Math.cos(a) * SP.r, Math.sin(a) * SP.r]; };
  for (let s = 0; s < SP.slots; s++) {
    const [lx, lz] = slotPos(s); ring(rack, BEAKER.d / 2 + 2, BEAKER.d / 2 + 8, 26, [lx, SP.plate, -lz], M.pom);
    decal(rack, 22, 16, [lx * 1.36, SP.plate + 0.6, -lz * 1.36], [-Math.PI / 2, 0, 0], String(s + 1), { color: '#e6edf3', center: true, bold: true });
  }
  const towerX = SP.towerX;
  K('sampler-tower', cylinder(sampler, 36, 700 - H.h, [towerX, Y0 + H.h + (700 - H.h) / 2, SP.z], M.metrohm, 'y', 32));
  const head = new THREE.Group(); head.position.y = Y0; sampler.add(head);                       // 滴定頭（升降；局部 y 相對桌面）
  const headX = SP.x + SP.r, headDown = SP.plate + 12;                                         // 下降時元件底端在杯底上 12 mm
  K('sampler-head', block(head, [towerX - headX + 40, 36, 60], [(towerX + headX) / 2, headDown + 210, SP.z], M.metrohm));
  K('sampler-head', cylinder(head, 36, 60, [headX, headDown + 180, SP.z], M.metrohmDark, 'y', 28));
  const probes = [['電極', 6, 0, -14, 0x9fb6c8], ['滴定管尖', 2, 14, 8, 0xe8e8e8], ['加水管', 2, -12, 10, 0xe8e8e8], ['噴洗嘴', 3, -16, -14, 0xbfc6cc]];
  for (const [name, r, dx, dz, c] of probes) {const m=cylinder(head, r, 170, [headX + dx, headDown + 85 + (r === 6 ? 0 : 20), SP.z + dz], new THREE.MeshStandardMaterial({ color: c, roughness: 0.3 }));m.name='probe-'+name;}
  const bulb = new THREE.Mesh(new THREE.SphereGeometry(5.5,24,16),glassRim);bulb.position.set(headX,headDown+4,SP.z-14);head.add(bulb);
  for (const [name,r,dx,dz] of probes) cylinder(head,r+1.4,8,[headX+dx,headDown+160,SP.z+dz],M.dark,'y',24).name='probe-collar-'+name;
  // Separate colour coded fluid lines and electrode cable, attached to the moving head.
  const tubing=[[-12,10,0xd5e7ef],[14,8,0xf0e7c6],[0,-14,0x41484e]];
  for(const [i,[dx,dz,color]] of tubing.entries()) cable(head,'HEAD / probe line '+i,[[headX+dx,headDown+232,SP.z+dz],[headX+dx-20,headDown+275,SP.z+60],[headX,headDown+300,SP.z+100],[towerX+130,headDown+330,SP.z+100+(i-1)*8.32]],{radius:2,color,clips:2});
  cylinder(head, 2.5, 172, [headX + 12, headDown + 84, SP.z + 14], M.steel).name='stirrer-shaft'; // 延伸到浸入液體的槳葉
  const prop = block(head, [22, 3, 6], [headX + 12, headDown - 2, SP.z + 14], M.steel);
  // 滴定儀（Titrando 級）＋ 2 支 Dosino（NaOH 滴定液、純水）＋液瓶
  const T = ST.titrator, titr = new THREE.Group(); titr.position.set(T.x, Y0, T.z); root.add(titr);
  K('titrator', block(titr, [170, 120, 290], [0, 60, 0], M.metrohm));
  const tscreen = liveText(120, 70, 360, 210); tscreen.mesh.position.set(0, 121, 70); tscreen.mesh.rotation.x = -Math.PI / 2; titr.add(tscreen.mesh);
  decal(titr, 110, 22, [0, 60, 145.6], [0, 0, 0], 'Titrando', { color: '#1b4f8a', center: true, bold: true });
  for (const [i, dz, lab] of [[0, -80, 'NaOH 0.1 mol/L'], [1, 30, 'H₂O']]) {
    const bottle = vessel(titr, 48, 190, i ? M.glass : new THREE.MeshPhysicalMaterial({ color: 0xa06a3a, transparent: true, opacity: 0.5, roughness: 0.1 }));
    bottle.position.set(-40, 120, dz);
    K('titrator', cylinder(titr, 34, 110, [-40, 120 + 190 + 55, dz], M.metrohm, 'y', 24));
    decal(titr, 90, 20, [-40, 200, dz + 49], [0, 0, 0], lab, { color: '#e6edf3', center: true, bold: true });
  }
  for(const [i,dz] of [-80,30].entries())cable(root,'DOSE / separate fluid line '+i,[[T.x-40,Y0+420,T.z+dz],[T.x-40,Y0+620,T.z+dz],[towerX+50,Y0+760,SP.z+100+(i-1)*8.32],[towerX+50,Y0+700,SP.z+100+(i-1)*8.32]],{radius:2,color:i?0xd5e7ef:0xf0e7c6,clips:3});
  // 電腦（整合軟體＋Metrohm 軟體）
  const P = ST.pc, pc = new THREE.Group(); pc.position.set(P.x, Y0, P.z); root.add(pc);
  block(pc, [160, 10, 120], [0, 5, -20], M.dark); block(pc, [30, 280, 20], [0, 150, -40], M.dark);
  K('pc', block(pc, [400, 250, 24], [0, 300, -30], M.dark));
  const screen = liveText(384, 234, 1000, 610); screen.mesh.position.set(0, 300, -17.5); pc.add(screen.mesh);
  block(pc, [300, 12, 90], [-20, 6, 45], M.dark);
  for(let row=0;row<4;row++) for(let col=0;col<14;col++) block(pc,[16,1.2,14],[-153+col*20,12.5,15+row*19],M.grey);
  // 安全雷射掃描器（地面）＋減速區／停止區
  const scan = new THREE.Group(); scan.position.set(0, 0, bz1 + 60); root.add(scan);
  block(scan, [110, 150, 110], [0, 75, 0], new THREE.MeshStandardMaterial({ color: 0xf2c200, roughness: 0.5 }));
  const zoneW = new THREE.Mesh(new THREE.RingGeometry(0, 1500, 48, 1, 0, Math.PI), M.zoneWarn); zoneW.rotation.x = Math.PI / 2; zoneW.position.y = 3; scan.add(zoneW);   // 半圓朝操作員側（+Z）
  const zoneS = new THREE.Mesh(new THREE.RingGeometry(0, 700, 48, 1, 0, Math.PI), M.zoneStop); zoneS.rotation.x = Math.PI / 2; zoneS.position.y = 4; scan.add(zoneS);

  // ---------------------------------------------------------------- 器皿
  const items = {};
  function bottleMesh(i) {
    const s = SAMPLES[i], b = BOTTLES[s.size], g = new THREE.Group(); root.add(g);
    glassBottle(g,b);
    const fluid = createLiquid(g,b.d/2-3,4), liquid=fluid.body;
    graduations(g,b.d/2,b.h-30,4,b.d/2-3,s.size===500?50:10,s.size);
    const label = decal(g, Math.min(70, b.d * 0.8), b.h * 0.42, [0, b.h * 0.42, b.d / 2 + 0.8], [0, 0, 0], [s.barcode, `樣品 ${i + 1}`], { color: '#111', bg: '#f4f4ee', center: true, barcode: true });
    label.material.transparent = false;
    const labelArc=Math.min(70,b.d*.8)/(b.d/2+.4);
    label.geometry.dispose();label.geometry=new THREE.CylinderGeometry(b.d/2+.4,b.d/2+.4,b.h*.42,40,1,true,-labelArc/2,labelArc);label.position.z=0;label.renderOrder=5;
    g.userData = { kind: 'bottle', i, liquid, fluid, r: b.d / 2 - 3, capY: b.h + b.neckH - CAP.h + 4 };
    return g;
  }
  function capMesh(i) {
    const g = new THREE.Group(); root.add(g);
    const c = cylinder(g, CAP.d / 2, CAP.h, [0, CAP.h / 2, 0], i < 3 ? M.cap : M.capRed, 'y', 28);
    for (let k = 0; k < 18; k++) { const a = k / 18 * Math.PI * 2; block(g, [2, CAP.h - 4, 3], [Math.cos(a) * CAP.d / 2, CAP.h / 2, Math.sin(a) * CAP.d / 2], c.material).rotation.y = -a; }
    g.userData = { kind: 'cap', i }; return g;
  }
  function beakerMesh(k) {
    const g = new THREE.Group(); root.add(g);
    const vessel=glassVessel(g, BEAKER.d / 2, BEAKER.h, 3, true),lip=vessel.children[1];
    const fluid = createLiquid(g,BEAKER.d/2-2,3), liquid=fluid.body;
    graduations(g,BEAKER.d/2,BEAKER.h,3,BEAKER.d/2-2,25,200);
    const label=decal(g,34,12,[0,55,0],[0,0,0],`#${k+1}`,{color:'#1b2a3a',bg:'#ffffffcc',center:true,bold:true});
    const rr=BEAKER.d/2+.2,arc=34/rr;label.geometry.dispose();label.geometry=new THREE.CylinderGeometry(rr,rr,12,32,1,true,-arc/2,arc);label.renderOrder=5;
    g.userData = { kind: 'beaker', k, liquid, fluid, r: BEAKER.d / 2 - 2, lip }; return g;
  }
  function pipetteMesh() {
    const g = new THREE.Group(); root.add(g); const p = PIPETTE;
    const nose = new THREE.Mesh(new THREE.CylinderGeometry(9, 5.5, p.nose, 20), M.white); nose.position.y = p.nose / 2; g.add(nose);
    const ej = cylinder(g, 12, 20, [0, p.nose + 10, 0], M.grey, 'y', 20);
    const body = new THREE.Mesh(new THREE.CylinderGeometry(p.r, 14, p.collar - p.nose - 40, 28), M.grey); body.position.y = (p.collar + p.nose - 20) / 2; g.add(body);
    cylinder(g, p.r + 0.6, 10, [0, p.collar - 70, 0], M.blue, 'y', 28);                                  // 模組識別環
    block(g, [40, 30, 40], [0, p.collar, 0], M.dark);                                                   // 夾持環（夾爪夾這裡）
    const head = new THREE.Mesh(new THREE.CylinderGeometry(20, p.r, p.top - p.collar - 15, 28), M.white); head.position.y = (p.top + p.collar + 15) / 2; g.add(head);
    const led = block(g, [6, 6, 3], [0, p.collar - 45, p.r - 1], M.led); void led;
    cylinder(g, 5, 30, [0, p.top + 12, 0], M.dark, 'y', 12);                                         // RS-485／電源線接頭（線沿手臂走）
    decal(g, 26, 60, [0, p.collar - 120, p.r + 0.5], [0, 0, 0], ['rLINE', '5 mL'], { color: '#e6edf3', center: true, bold: true });
    g.userData = { kind: 'pipette' }; return g;
  }
  function tipMesh(i) {
    const g = new THREE.Group(); root.add(g); const p = PIPETTE;
    const cone = new THREE.Mesh(new THREE.CylinderGeometry(p.tipR - 1, 1.2, p.tipLen - 20, 20, 1, true), M.tip); cone.position.y = -20 - (p.tipLen - 20) / 2; g.add(cone);
    const collar = new THREE.Mesh(new THREE.CylinderGeometry(p.tipR, p.tipR - 1, 20, 20, 1, true), M.tip); collar.position.y = -10; g.add(collar);
    const liquid = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 14), M.liquid); liquid.visible = false; g.add(liquid);
    cone.renderOrder=collar.renderOrder=3;liquid.renderOrder=2;
    g.userData = { kind: 'tip', i, liquid, unitVertices: liquid.geometry.attributes.position.array.slice() }; return g;
  }
  SAMPLES.forEach((s, i) => { items[`bottle${i}`] = bottleMesh(i); items[`cap${i}`] = capMesh(i); });
  for (let t = 0; t < 12; t++) items[`tip${t}`] = tipMesh(t);
  for (let k = 0; k < 12; k++) items[`beaker${k}`] = beakerMesh(k);
  items.pip = pipetteMesh();
  const pipFlow=flowLine(root,.6),waterFlow=flowLine(root,.8);
  const doseDrop=new THREE.Mesh(new THREE.SphereGeometry(.85,16,12),liquidMaterial);doseDrop.renderOrder=2;root.add(doseDrop);
  const sprayLines=Array.from({length:3},()=>flowLine(root,.25));
  const headHarness=carrier(root,'SAMPLER / electrode and fluid service',{origin:[towerX+50,Y0+headDown+330,SP.z+100],axis:[0,1,0],rise:[1,0,0],fixed:248,min:0,max:190,radius:40,width:32,pitch:16,colors:[0xd5e7ef,0xf0e7c6,CABLE.signal]});
  cableTray(root,'BENCH / dry electrical distribution',[-1100,710,390],[1100,710,390],{width:52});
  cable(root,'ROBOT / cabinet to sealed bench bore',[[-300,380,0],[-230,470,0],[-165,650,0],[-165,Y0,0]],{radius:6,color:CABLE.power,clips:3});
  cable(root,'BALANCE / rear signal',[[-700,Y0+40,20],[-750,Y0+30,20],[-760,Y0+20,525],[-760,750,525],[-760,710,405]],{radius:2.5,color:CABLE.signal,clips:3});
  cable(pc,'PC / protected rear data',[[35,300,-42],[45,250,-65],[45,50,-65],[60,15,-100]],{radius:2.5,color:CABLE.signal,clips:3});
  cable(root,'PC / bench-edge service',[[1060,Y0+15,300],[1230,Y0+20,350],[1230,760,400],[1100,710,405]],{radius:3,color:CABLE.signal,clips:2});
  cable(root,'SAMPLER / dry electrode feed',[[T.x+85,Y0+60,T.z],[1140,Y0+180,-210],[1140,Y0+690,100],[towerX+50,Y0+700,SP.z+108.32]],{radius:2.2,color:CABLE.signal,clips:4});

  // ---------------------------------------------------------------- 狀態套用
  const _v = new THREE.Vector3(), _q = new THREE.Quaternion(), _q2 = new THREE.Quaternion(), UP = new THREE.Vector3(0, 1, 0);
  function worldOf(id, locs, ctx, out = { p: new THREE.Vector3(), q: new THREE.Quaternion() }) {
    const L = locs[id];
    if (L.w) { out.p.set(...L.w); out.q.setFromAxisAngle(UP, L.yaw || 0); }
    else if (L.g) { ctx.robot.getTcpWorld('grip', out.p); ctx.robot.tool.getWorldQuaternion(_q); out.p.add(_v.set(...L.g).applyQuaternion(_q)); out.q.copy(_q).multiply(_q2.set(...L.q)); }
    else if (L.on) { const par = worldOf(L.on, locs, ctx, { p: new THREE.Vector3(), q: new THREE.Quaternion() }); out.p.copy(par.p).add(_v.set(...L.off).applyQuaternion(par.q)); out.q.copy(par.q).multiply(_q2.setFromAxisAngle(UP, L.yaw || 0)); }
    else if (L.as !== undefined) { const a = ctx.rackAngle + L.as * 2 * Math.PI / SP.slots; out.p.set(SP.x + Math.cos(a) * SP.r, Y0 + SP.plate, SP.z - Math.sin(a) * SP.r); out.q.setFromAxisAngle(UP, a + (L.yaw || 0)); }
    return out;
  }
  const tmp = { p: new THREE.Vector3(), q: new THREE.Quaternion() };
  /** 依排程狀態擺放器皿與設備；ctx = { robot, rackAngle, headDrop, stir, scanning } */
  function setState(s, ctx) {
    for (const id in items) {
      const g = items[id], L = s.loc[id];
      g.visible = !!L && !L.gone; if (!g.visible) continue;
      worldOf(id, s.loc, ctx, tmp); g.position.copy(tmp.p); g.quaternion.copy(tmp.q);
      const u = g.userData;
      if (u.kind === 'bottle' || u.kind === 'beaker') {
        u.fluid.set(s.vol[id]||0,ctx.time,ctx.stir&&id===`beaker${ctx.job?.beaker}`);
      }
      if (u.kind === 'tip') {
        const v=s.tipVol?.[id]||0;u.liquid.visible=v>.01;
        if(u.lastVolume!==v){u.lastVolume=v;const h=tipFillHeight(v),p=u.liquid.geometry.attributes.position;
          for(let n=0;n<p.count;n++){const y=u.unitVertices[n*3+1]+.5,r=.7+7.5*y*h/140;
            p.setXYZ(n,u.unitVertices[n*3]*r,y*h,u.unitVertices[n*3+2]*r);}
          p.needsUpdate=true;u.liquid.geometry.computeVertexNormals();u.liquid.geometry.computeBoundingSphere();}
        u.liquid.position.y=-PIPETTE.tipLen+2;
      }
    }
    door.position.x = -B.doorTravel * s.door;
    for (const jg of jaws) jg.position.z = jg.userData.side * (s.clampGap / 2 + 13);
    rack.rotation.y = ctx.rackAngle;
    head.position.y = Y0 + 190 * (1 - ctx.headDrop);
    prop.rotation.y = ctx.stir ? (ctx.time-ctx.job.start) * 12 : 0;
    headHarness.set(head.position.y-Y0);
    root.updateMatrixWorld(true);
    pipFlow.mesh.visible=waterFlow.mesh.visible=doseDrop.visible=false;sprayLines.forEach(l=>l.mesh.visible=false);
    if(ctx.step.label.startsWith('吐出')&&ctx.progress<1){
      const tipId=ctx.step.touch?.find(id=>id.startsWith('tip')&&items[id]),tip=items[tipId];
      if(tip?.visible){const a=tip.localToWorld(new THREE.Vector3(0,-PIPETTE.tipLen,0)),b=a.clone();
        const beakerId=ctx.step.touch?.find(id=>id.startsWith('beaker'));
        b.y=beakerId?items[beakerId].position.y+items[beakerId].userData.fluid.surface.position.y:Y0+15;
        pipFlow.set(a,b,a.y>b.y);}}
    if(ctx.job){
      const cup=items[`beaker${ctx.job.beaker}`],surfaceY=cup.position.y+cup.userData.fluid.surface.position.y;
      const a=new THREE.Vector3(headX-12,head.position.y+headDown+20,SP.z+10);
      waterFlow.set(a,new THREE.Vector3(a.x,surfaceY,a.z),ctx.time>=ctx.job.start&&ctx.time<ctx.job.start+15);
      if(ctx.time>=ctx.job.start+35&&ctx.time<ctx.job.end-20){
        const top=head.position.y+headDown+20,phase=((ctx.time-ctx.job.start)*2)%1;
        doseDrop.visible=top>surfaceY;doseDrop.position.set(headX+14,top-(top-surfaceY)*phase*phase,SP.z+8);doseDrop.scale.set(.7,1.3,.7);}
      if(ctx.spray)for(let i=0;i<3;i++){
        const from=new THREE.Vector3(headX-16,head.position.y+headDown+20,SP.z-14),to=new THREE.Vector3(headX+(i-1)*3,head.position.y+headDown+3,SP.z-14);
        sprayLines[i].set(from,to,true);}}
    beam.visible = beamPlane.visible = !!ctx.scanning;
    panel.draw(s.balText, (g, w, h) => { g.fillStyle = '#0a1a10'; g.fillRect(0, 0, w, h); g.fillStyle = s.balStable ? '#6dff9c' : '#c9f7d5'; g.font = 'bold 64px Consolas, monospace'; g.textAlign = 'right'; g.fillText(s.balText, w - 16, 92); g.font = '28px Arial'; g.textAlign = 'left'; g.fillText(s.balStable ? '穩定' : '', 14, 138); });
  }
  return { root, items, keepout, setState, worldOf, screen, tscreen, slotPos, headX, head, prop, pipFlow, waterFlow, doseDrop, sprayLines, balanceDoor: door, jaws, zones: [zoneW, zoneS] };
}
