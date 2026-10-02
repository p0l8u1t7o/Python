// 專案介面（core 統一檢查與 main.js 共用）：依配方建立整站與單盤流程，apply(t) 把場景放到時間 t。
// 規格見 core/README.md「專案介面」。配方、壓墊、示意 NG 由 main.js 依網址參數傳入；不傳時與網頁預設相同。
import * as THREE from 'three';
import { createStation } from './station.js';
import { createSequence } from './sequence.js';
import { RECIPES, DEFAULT_RECIPE } from './recipes.js';
import { LAYOUT } from './cell.js';

/** 網址參數 → 配方鍵與壓墊（main.js 與檢查共用同一規則） */
export function resolveRecipe(recipeKey, insert) {
  const key = RECIPES[recipeKey] ? recipeKey : DEFAULT_RECIPE, recipe = RECIPES[key];
  // 壓墊預設取配方的標準；有整排接頭的機種可切換單點逐顆作比較
  const kind = insert === 'single' ? 'single' : insert === 'bar' && recipe.multiPad ? 'bar' : recipe.insert;
  return { key, recipe, insert: kind };
}

export function createProject({ scene, headless = false, recipe: recipeKey, insert: insertArg, ngHold = false } = {}) {
  const { key, recipe, insert } = resolveRecipe(recipeKey, insertArg);
  const st = createStation(scene, recipe, insert);
  const { cell, robot, product } = st;
  st.opts.ngHold = ngHold;

  // ROI 框（取像、全局辨識）：只是標示，不是實體
  const roiMats = [], roiBoxes = [];
  for (let k = 0; k < product.ids.length; k++) {
    const m = new THREE.LineBasicMaterial({ color: 0x3dd68c, transparent: true, opacity: 0.95 });
    const b = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), m);
    b.visible = false; scene.add(b); roiMats.push(m); roiBoxes.push(b);
  }
  function showROI(k, id, color) {
    const b = new THREE.Box3().setFromObject(product.conns[id].pivot);
    roiBoxes[k].position.copy(b.getCenter(new THREE.Vector3())); roiBoxes[k].scale.copy(b.getSize(new THREE.Vector3()).addScalar(2.5));
    roiMats[k].color.setHex(color); roiBoxes[k].visible = true;
  }

  const sequence = createSequence({ robot, product, apply: st.apply, recipe, insert });
  const total = sequence.total, shots = sequence.shots, stub = recipe.stubborn.id;
  let current = null;

  /** 流程取樣：設備、載盤、接頭狀態與手臂目標（不移動手臂關節；播放時由 robot.update 追蹤） */
  function sample(t) { current = sequence.sample(t); return current; }
  /** 手臂到達目前步驟的目標（取像閃光與相機來源用） */
  function arrived(c = current) { const e = robot.error(); return e.position < (c.step.contact ? 1 : 2) && e.angle < 2; }
  function shotIds(S = current.state) { if (!S.shot) return []; return S.shot === 'R' ? [stub] : shots[+S.shot].map(c => c.id); }
  /** 依目前狀態與手臂實際姿態更新燈號、力值顏色、取像閃光與 ROI 框（網頁每一幀與 apply 共用） */
  function show(c = current, { time = c.step.start + c.t * c.step.dur, playing = false, fault = '' } = {}) {
    const S = c.state, ps = st.state;
    robot.setFlash(S.flashTool > 0 && arrived(c)); robot.setForceColor(ps.force);
    const ids = S.flashTool > 0 ? shotIds(S) : [];
    roiBoxes.forEach(b => { b.visible = false; });
    if (S.station === 1 && S.detected > 0) product.ids.forEach((id, k) => showROI(k, id, 0x4aa8ff));
    else ids.forEach((id, k) => showROI(k, id, ps.gap[id] <= recipe.gapLimit ? 0x3dd68c : 0xff4d4d));
    cell.tower.set(fault ? 'red' : time >= total - 1e-6 ? 'green' : S.station === 4 && !c.completed.has('recheck') ? 'yellow' : playing ? 'green' : 'yellow');
  }
  /** 把整個場景放到時間 t：流程狀態＋手臂直接到位（跳播、截圖、檢查都用這個） */
  function apply(t, { playing = false, fault = '' } = {}) {
    const time = Number.isFinite(t) ? THREE.MathUtils.clamp(t, 0, total) : 0;
    sample(time); robot.snap(); show(current, { time, playing, fault });
    scene.updateMatrixWorld(true);
    return current;
  }
  apply(0);

  // 前一盤／下一盤與本站載盤的根物件名稱都是 product；檢查時分開成不同模組
  const modules = new Map([[product.root, 'product'], [st.prev?.root, 'prevPallet'], [st.next?.root, 'nextPallet']]);
  const topOf = o => { let p = o; while (p.parent && p.parent !== scene) p = p.parent; return p; };
  const moduleOf = m => { const t = topOf(m); return modules.get(t) ?? (t.name || 'misc'); };

  return {
    total, apply, sample, show, arrived, shotIds,
    station: st, cell, robot, product, sequence, recipe, recipeKey: key, insert, roiBoxes,
    get current() { return current; },
    layoutChecks() {
      const rows = [], place = st.place, { w, d, t: pt } = recipe.pallet;
      rows.push({ group: '輸送', name: '載盤前緣靠止擋面', ok: Math.abs(place.x + w / 2 - LAYOUT.stopFace) < 1e-6, value: +(place.x + w / 2).toFixed(1), note: `止擋面 x=${LAYOUT.stopFace}` });
      rows.push({ group: '輸送', name: '載盤後緣貼後軌基準邊', ok: Math.abs(place.z - d / 2 - LAYOUT.rearInner) < 1e-6, value: +(place.z - d / 2).toFixed(1) });
      // 全局相機：頂升後整盤（含接頭高度）都在視野內
      const cam = cell.globalCam; cam.aspect = 1.5; cam.updateProjectionMatrix(); cam.updateMatrixWorld(true);
      const y = LAYOUT.conveyorTop + LAYOUT.liftStroke, corners = [];
      for (const sx of [-1, 1]) for (const sz of [-1, 1]) for (const dy of [0, pt + 12]) corners.push(new THREE.Vector3(place.x + sx * w / 2, y + dy, place.z + sz * d / 2).project(cam));
      const margin = Math.max(...corners.map(p => Math.max(Math.abs(p.x), Math.abs(p.y))));
      rows.push({ group: '視覺', name: '全局相機涵蓋整盤', ok: margin < 1, value: +margin.toFixed(3), note: '投影座標最大絕對值，< 1 表示在畫面內' });
      return rows;
    },
    verify: {
      dt: .1,
      // 非實體：地面與地面黃色標線（cell 底下 y ≤ 1 mm 的平面／薄片）
      skip: o => o.isMesh && o.parent === cell.group && o.position.y <= 1,
      moduleOf,
      envelope: ['robot'],
    },
  };
}
