// 專案介面（core 統一檢查與 main.js 共用）：建立整條 QC 線、產品、手臂與動作序列，apply(t) 把場景放到時間 t。
// 規格見 core/README.md「專案介面」。燈光、相機、HUD、標籤等瀏覽器專用物件留在 main.js。
import * as THREE from 'three';
import { createNotebook, NB, SKUS, selectSku } from './notebook.js';
import { createRobot } from './robot.js';
import { createCell, createPallet, LAYOUT } from './cell.js';
import { createSequence, smooth } from './sequence.js';

export const DEFAULT_SKU = 'V110-STND';

// 參數（與 core project.json 的 variants.params 相同，直接展開在第一層）：sku = 'V110-STND'（預設）或 'V110-RF'
export function createProject({ scene, headless = false, sku: wanted } = {}) {
  // SKU 決定護蓋配置；必須在建立任何筆電模型之前選定
  const sku = wanted && SKUS[wanted] ? wanted : DEFAULT_SKU;
  selectSku(sku);

  // ---------------------------------------------------------------- 設備與產品
  const cell = createCell(scene);
  const nb = createNotebook();
  const notebook = nb.root;
  // 載體（carrier）：機台的實際位置／翻轉由它決定（載具上、升降、翻轉治具中）
  const carrier = new THREE.Group(); scene.add(carrier); carrier.add(notebook);
  notebook.position.set(0, -NB.H / 2, 0);
  const robot = createRobot();
  robot.root.position.set(0, 0, LAYOUT.railZ);
  scene.add(robot.root);

  // 堆料架內的載具堆（進料 5 台待檢、出料 2 台已檢）
  const stackIn = [], stackOut = [];
  function stackedUnit() { const p = createPallet(true); p.setClamp(1); const n = createNotebook().root; n.position.y = LAYOUT.palletH + LAYOUT.padH + LAYOUT.footOffset; p.group.add(n); return p.group; }
  for (let i = 0; i < 5; i++) { const u = stackedUnit(); cell.stackerIn.group.add(u); stackIn.push(u); }
  for (let i = 0; i < 2; i++) { const u = stackedUnit(); cell.stackerOut.group.add(u); stackOut.push(u); }

  // ---------------------------------------------------------------- 非實體輔助（防撞區、ROI 框、接縫雷射線、TCP 軌跡）
  const zoneMat = new THREE.MeshBasicMaterial({ color: 0x4aa8ff, transparent: true, opacity: 0.08, depthWrite: false });
  const zoneEdge = new THREE.LineBasicMaterial({ color: 0x4aa8ff, transparent: true, opacity: 0.35 });
  const zoneSlow = new THREE.Mesh(new THREE.BoxGeometry(NB.W + 200, NB.H + 200, NB.D + 200), zoneMat); zoneSlow.position.y = NB.H / 2;
  const zoneSlowE = new THREE.LineSegments(new THREE.EdgesGeometry(zoneSlow.geometry), zoneEdge); zoneSlowE.position.y = NB.H / 2;
  const zoneKeep = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(NB.W + 60, NB.H + 60, NB.D + 60)), new THREE.LineBasicMaterial({ color: 0xff4d4d, transparent: true, opacity: 0.5 })); zoneKeep.position.y = NB.H / 2;
  notebook.add(zoneSlow, zoneSlowE, zoneKeep);

  const roiMat = new THREE.LineBasicMaterial({ color: 0x3dd68c, transparent: true, opacity: 0.0 });
  const roiBox = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), roiMat); scene.add(roiBox);
  function showROIObj(obj, pad = 6) {
    scene.updateMatrixWorld(true);
    const b = new THREE.Box3().setFromObject(obj);
    roiBox.position.copy(b.getCenter(new THREE.Vector3())); roiBox.scale.copy(b.getSize(new THREE.Vector3()).addScalar(pad)); roiBox.quaternion.identity(); roiMat.opacity = 1;
  }

  // A 面接縫雷射線
  const seamLaser = new THREE.Mesh(new THREE.PlaneGeometry(3, 16), new THREE.MeshBasicMaterial({ color: 0xff2a2a, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
  seamLaser.rotation.x = -Math.PI / 2; scene.add(seamLaser);

  // 手臂路徑（播放時由 main.js 累積，跳播時清空）
  const trailN = 500, trailPos = new Float32Array(trailN * 3);
  const trailGeo = new THREE.BufferGeometry(); trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPos, 3)); trailGeo.setDrawRange(0, 0);
  const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0x7fd4ff, transparent: true, opacity: 0.6 })); scene.add(trail);

  // ---------------------------------------------------------------- 狀態 → 場景
  const top = LAYOUT.conveyorTop + 6 + LAYOUT.palletH + LAYOUT.padH + LAYOUT.footOffset;
  let S = null;
  function applyState(s) {
    S = s;
    cell.pallet.group.position.set(s.palletX, LAYOUT.conveyorTop + 6 + s.palletLift, 0);
    carrier.position.set(s.palletX, top + s.palletLift + s.lift + NB.H / 2, 0); carrier.rotation.x = Math.PI * s.flip;
    cell.pallet.setClamp(s.clamp); nb.doors.forEach((d, i) => d.set(s.doors[i].open, s.doors[i].latch));
    const inBase = LAYOUT.conveyorTop + 6;
    cell.stackerIn.lift.position.y = inBase - 20 + s.inLift;
    stackIn.forEach((u, i) => u.position.set(0, inBase + (i + 1) * LAYOUT.palletPitch + s.inStackY, 0));
    cell.stackerOut.lift.position.y = inBase - 20 + s.outLift;
    stackOut.forEach((u, i) => u.position.set(0, inBase + (i + 1) * LAYOUT.palletPitch + s.outStackY, 0));
    cell.stackerIn.setPush(s.pushIn); cell.stackerOut.setPush(s.pushOut); cell.stackerIn.setForks(s.inFork); cell.stackerOut.setForks(s.outFork);
    cell.cradle.lift.position.y = top + NB.H / 2 + s.cradleLift; cell.cradle.rot.rotation.x = Math.PI * s.flip; cell.cradle.setClamp(s.cradleClamp);
    cell.updateTransport(s.palletX, s.located); cell.setHead(s.s1Head);
    scene.updateMatrixWorld(true);
  }
  const sequence = createSequence({ nb, robot, apply: applyState });

  // 手臂是否到位（曝光、力值顯示的條件；與 main.js 播放時的判斷相同）
  function arrived(current) { const e = robot.error(); return e.position < (current.step.contact ? 1 : 2) && e.angle < 3 && e.rail < 2; }
  // 取像光源、雷射、ROI 框、接縫雷射線、力覺色環、三色燈：依目前步驟與「是否到位」決定
  function effects(current, { arrived: ok = arrived(current), capture = false, result = 'OK', fault = '' } = {}) {
    const s = current.state, illuminated = ok || capture;
    robot.setFlash(s.flashTool > 0 && illuminated); robot.setLaser(s.laserTool > 0 && illuminated);
    cell.topFlash.intensity = s.flashTop * 2000; cell.snFlash.intensity = s.flashSn * 800;
    const activeDoor = nb.doors.find(d => s.action.startsWith(d.def.id + ' '));
    roiBox.visible = !!(s.flashTool && illuminated);
    if (roiBox.visible) showROIObj(activeDoor ? activeDoor.portGroup : s.action.includes('Docking') ? nb.dock : s.action.includes('法規') ? nb.printing : nb.labels.sn, 3);
    robot.setForceColor(ok ? s.force : 0);
    cell.tower.set(fault ? 'red' : s.station === 4 ? (result === 'NG' ? 'red' : 'green') : 'yellow');
    seamLaser.material.opacity = s.seamLaser >= 0 && illuminated ? .7 : 0;
    seamLaser.position.set(s.palletX - 125 + 250 * smooth(current.t), top + NB.H + 1, -94);
  }
  // 只取樣序列（設定機構狀態與手臂目標，手臂不跳到位）：播放時由 robot.update 逐步追上
  function sample(t) { return sequence.sample(t); }
  // 跳到時間 t：機構狀態、手臂直接到位、光源與輔助線；只依 t 決定
  function apply(t, opts = {}) { const current = sequence.sample(t); robot.snap(); effects(current, opts); scene.updateMatrixWorld(true); return current; }

  // ---------------------------------------------------------------- 全場檢查設定
  const helpers = new Set([zoneSlow, seamLaser]);
  const isUnder = (o, root) => { for (let p = o; p; p = p.parent) if (p === root) return true; return false; };
  const pairOf = (a, b, f, g) => (f(a) && g(b)) || (f(b) && g(a));
  const doorGroups = nb.doors.map(d => d.hinge);
  const onDoor = m => doorGroups.some(h => isUnder(m, h));
  const moduleOf = m => {
    if (isUnder(m, robot.root)) return 'robot';
    if (isUnder(m, carrier)) return 'product';
    if (isUnder(m, cell.pallet.group)) return 'pallet';
    if (isUnder(m, cell.cradle.group)) return 'cradle';
    if (isUnder(m, cell.stackerIn.group) || isUnder(m, cell.stackerOut.group)) return 'stacker';
    let p = m; while (p.parent && p.parent !== scene) p = p.parent; return p.name || 'misc';
  };

  // ---------------------------------------------------------------- 空間檢核（由實際網格量測，不寫死數值）
  function layoutChecks() {
    const box = o => new THREE.Box3().setFromObject(o), rows = [];
    const row = (group, name, value, ok, note) => rows.push({ group, name, ok, value: +value.toFixed(1), note });
    apply(0);
    // 托叉伸出時，載具推出／拉入的堆疊柱不得穿過托叉（z 向錯開）
    const posts = cell.pallet.group.children.filter(m => m.geometry?.parameters?.height === LAYOUT.palletPitch - LAYOUT.palletH);
    const postZ = Math.max(...posts.map(m => box(m).max.z)), fork = cell.stackerIn.forks.find(f => f.sz > 0).fork;
    cell.stackerIn.setForks(1); scene.updateMatrixWorld(true);
    row('堆料架', '堆疊柱與托叉 z 間隙', box(fork).min.z - postZ, box(fork).min.z - postZ > 1, 'mm，托叉伸出時');
    // 升降平台上升到托叉高度時不得碰托叉
    const platform = cell.stackerIn.lift.children[0];
    row('堆料架', '平台與托叉 z 間隙', box(fork).min.z - box(platform).max.z, box(fork).min.z - box(platform).max.z > 1, 'mm');
    // S3 龍門立柱不得壓到輸送線前側線槽
    const s3post = cell.keepout.find(m => m.name === 'S3 左立柱'), tray = cell.group.getObjectByName('CELL / segregated field wiring');
    if (tray) row('S3', '龍門立柱與線槽間隙', box(tray).min.z - box(s3post).max.z, box(tray).min.z - box(s3post).max.z > 1, 'mm');
    // 後圍籬在手臂掃掠外（每 1 s 取樣，待命與 PTP 姿態）
    const fence = cell.occluders.children.find(m => m.geometry?.parameters?.width > 5000), parts = [];
    robot.root.traverse(o => { if (o.isMesh && !(o.material.transparent && o.material.depthWrite === false)) parts.push(o); });
    let minZ = Infinity;
    for (let t = 0; t <= sequence.total; t += 1) { apply(t); for (const m of parts) minZ = Math.min(minZ, box(m).min.z); }
    row('圍籬', '後圍籬與手臂掃掠間隙', minZ - box(fence).max.z, minZ - box(fence).max.z > 20, 'mm，手臂外框取樣（保守）');
    apply(0);
    return rows;
  }

  return {
    total: sequence.total, sku, sequence, layoutChecks, cell, nb, notebook, carrier, robot, stackIn, stackOut,
    zones: [zoneSlow, zoneSlowE, zoneKeep], roiBox, seamLaser, trail, trailGeo, trailPos, trailN,
    top, get state() { return S; },
    sample, apply, effects, arrived,
    verify: {
      // 防撞區、雷射平面等半透明效果不是實體
      skip: o => helpers.has(o) || (o.isMesh && o.material?.transparent && o.material.depthWrite === false),
      moduleOf,
      allow: [
        // 只放行夾墊對護角；夾墊壓到側門面板仍會列出
        { why: '載具四角側夾的 PU 夾墊夾住筆電橡膠護角（夾緊預壓）', test: (a, b) => pairOf(a, b, m => m.name === 'pallet clamp pad', m => m.name === 'corner guard') },
        { why: 'S3 翻轉夾臂的 PU 夾墊夾住筆電橡膠護角（夾緊預壓）', test: (a, b) => pairOf(a, b, m => m.name === 'cradle clamp pad', m => m.name === 'corner guard') },
        // 只放行鉤爪尖端／壓頭對護蓋（門板、門扣）；工具其他部位碰到產品仍會列出
        { why: '鉤爪尖端／PU 壓頭在力控接觸步驟勾起門扣、帶動護蓋開關與按壓鎖定（力值見 sequence.js）', test: (a, b) => pairOf(a, b, m => m.name === 'hook-tip' || m.name === 'press-pad', onDoor) },
      ],
      envelope: ['robot'],
    },
  };
}
