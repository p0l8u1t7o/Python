// 全場干涉與閃爍檢查（所有專案共用）：直接用網頁同一份場景（web/js/project.js）。
// 1. 動態：沿動畫取樣，世界位置會變的零件對固定零件與其他會動零件做有向包圍盒（OBB）分離軸檢查。
//    同一剛體、直接相連的上下游關節、伸縮件、套筒、導軌滑座視為安裝關係不檢查。
// 2. 靜態：不同模組（或同模組不同工位）的固定零件互相穿插 → 架設位置相撞。
// 3. 重合面：兩零件有同向、同平面且面積重疊的面 → 深度互搶造成閃爍（對數深度緩衝也無法解決）。
// OBB 對圓柱、球為保守外框，曲面另以頂點射線複核；穿插門檻 2 mm。不是連續碰撞證明。
import * as THREE from 'three';

export const TOL = 2;                       // 預設穿插門檻 mm（設備尺度）
export const ZF = { dist: .6, area: 25 };    // 預設重合面：距離 mm、重疊面積 mm²

// 專案可在 verify 設定裡標記：
//   物件 userData.fx         效果（噴霧、光束），不是實體
//   物件 userData.guide = id 導軌；移動件 userData.on = id 在其上滑行
//   物件 userData.nested = 另一個關節物件：套筒式伸縮（內外管）
export function verifyScene(project, scene, {
  dt, probes: nProbes = 60, zfightTimes = 11, report = () => { },
} = {}) {
  const cfg = project.verify || {}, total = project.total;
  const DT = dt ?? cfg.dt ?? Math.max(.05, +(total / 400).toPrecision(2));
  const sample = t => { project.apply(t); scene.updateMatrixWorld(true); };
  const skip = cfg.skip || (() => false);

  // ---------------------------------------------------------------- 零件清單與分類
  const meshes = [];
  scene.traverse(o => {
    if (!o.isMesh || o.isInstancedMesh || !o.geometry) return;
    for (let p = o; p; p = p.parent) if (p.userData.fx || skip(p)) return;
    meshes.push(o);
  });
  const topModule = o => { let p = o; while (p.parent && p.parent !== scene) p = p.parent; return p.name || 'misc'; };
  const moduleOf = o => cfg.moduleOf?.(o) ?? topModule(o);
  sample(0);
  const info = new Map(meshes.map(m => [m, { module: moduleOf(m), station: cfg.stationOf?.(m) ?? 'misc' }]));

  // 關節：局部矩陣在動畫中會變的物件；剛體 = 最近的關節祖先
  const objs = []; scene.traverse(o => objs.push(o));
  const local0 = new Map(objs.map(o => [o, o.matrix.clone()])), joints = new Set();
  const probes = Array.from({ length: nProbes }, (_, i) => total * (i + .5) / nProbes);
  for (const t of probes) { sample(t); for (const o of objs) if (!joints.has(o) && !o.matrix.equals(local0.get(o))) joints.add(o); }
  // 只在原地自轉的軸對稱零件（滾輪、輪轂）：世界中心與軸向都不變，視為固定。
  // 軸向也要比：繞別的軸公轉的關節殼（例如中心剛好在 J1 軸上的 J2 殼）中心不動但軸向會轉，它屬於上游剛體。
  const AXI = new Set(['CylinderGeometry', 'LatheGeometry', 'SphereGeometry', 'TorusGeometry']);
  const AXIS_COL = { CylinderGeometry: 1, LatheGeometry: 1, TorusGeometry: 2 };
  const axisOf = m => AXIS_COL[m.geometry.type] == null ? null : new THREE.Vector3().setFromMatrixColumn(m.matrixWorld, AXIS_COL[m.geometry.type]).normalize();
  const moved = new Set(), stretch = new Set(), c0 = new Map(), a0 = new Map();
  sample(0); for (const m of meshes) { c0.set(m, new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3())); if (AXI.has(m.geometry.type)) a0.set(m, axisOf(m)); }
  const s0 = new Map(objs.map(o => [o, o.scale.clone()]));
  for (const t of probes) {
    sample(t);
    for (const m of meshes) {
      if (!AXI.has(m.geometry.type) || moved.has(m)) continue;
      const a = a0.get(m), turned = a && Math.abs(axisOf(m).dot(a)) < .9999;
      if (turned || new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3()).distanceTo(c0.get(m)) > .5) moved.add(m);
    }
    for (const o of objs) if (!o.scale.equals(s0.get(o))) stretch.add(o);
  }
  const spinner = new Set(meshes.filter(m => AXI.has(m.geometry.type) && !moved.has(m)));
  // 快取：大型場景（數千個會動零件）每次重走子樹會讓檢查跑上數小時
  const sjCache = new Map(), bodyCache = new Map();
  const spinnerJoint = p => { if (sjCache.has(p)) return sjCache.get(p); let only = true; p.traverse(c => { if (c.isMesh && !spinner.has(c)) only = false; }); sjCache.set(p, only); return only; };
  // 自轉件本身不算關節，但仍屬於它所在的會動群組（例如繞自身軸轉的肩部屬於 J1）；只在固定群組裡的自轉件（滾輪）才是固定件
  const bodyOf = o => { if (!o) return null; if (bodyCache.has(o)) return bodyCache.get(o); let r = null; for (let p = spinner.has(o) ? o.parent : o; p && p !== scene; p = p.parent) if (joints.has(p) && !spinnerJoint(p)) { r = p; break; } bodyCache.set(o, r); return r; };
  const parentBody = b => bodyOf(b.parent);
  const movingSet = new Set(meshes.filter(m => bodyOf(m) && !spinner.has(m)));
  const moving = [...movingSet], fixed = meshes.filter(m => !bodyOf(m) || spinner.has(m));   // 自轉件外框不變，以固定件取樣即可
  const visible = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
  const ctx = { info, bodyOf, parentBody, moduleOf: m => info.get(m).module, scene };
  // 門檻可依模組調整（例如精密產品用 0.01 mm）：verify.thresholds = { 模組名: { tol, dist, area } }；兩零件取較嚴者
  const TH = cfg.thresholds || {};
  const th = m => TH[info.get(m)?.module] || {};
  const pair = (a, b) => { const A = th(a), B = th(b); return { tol: Math.min(A.tol ?? TOL, B.tol ?? TOL), dist: Math.min(A.dist ?? ZF.dist, B.dist ?? ZF.dist), area: Math.min(A.area ?? ZF.area, B.area ?? ZF.area) }; };

  // ---------------------------------------------------------------- 允許的接觸（逐條說明原因）
  // 線材群組（cable-routing 的 userData.cable）：端點 30 mm 內落在對方外框裡就是接入
  const cableOf = m => { for (let p = m; p; p = p.parent) if (p.userData.cable) return p; return null; };
  // 只放行小型安裝五金本身（線夾、格蘭頭、護套、支撐柱）；線材外皮、線槽、拖鏈照常檢查
  const MOUNT = new Set(['clamp', 'gland', 'strain-relief', 'support']);
  const hardwareOf = m => MOUNT.has(m.userData.routingHardware) ? m : null;
  function cableEndIn(a, b) {
    const c = cableOf(a); if (!c) return false;
    const pts = c.userData.cable.points, r = (c.userData.cable.radius || 3) + 30;
    const box = new THREE.Box3().setFromObject(b).expandByScalar(r);
    return [pts[0], pts.at(-1)].some(q => box.containsPoint(new THREE.Vector3(...q).applyMatrix4(c.matrixWorld)));
  }
  // 固定件的 bodyOf 為 null：「同一剛體」必須是同一個非 null 關節，否則固定件之間、頂層移動件對所有固定件都會被放行。
  // 移動件只對「安裝它的上游零件」放行：上游剛體相同，且該零件就在移動件的父群組底下（同一台設備）。
  const inside = (o, root) => { for (let p = o; p; p = p.parent) if (p === root) return true; return false; };
  const mountedOn = (A, m) => bodyOf(m) === parentBody(A) && inside(m, A.parent);
  const sameMount = (A, B) => parentBody(A) === parentBody(B) && (parentBody(A) !== null || A.parent === B.parent);
  const ALLOW = [
    { why: '同一剛體或直接相連的關節（導軌、滑座、轉軸裝在上游零件上）', test: (a, b) => { const A = bodyOf(a), B = bodyOf(b); return (A && A === B) || (A && mountedOn(A, b)) || (B && mountedOn(B, a)); } },
    { why: '伸縮連桿（鏈條、活塞桿等長度會變的零件）與同一載體上的零件相接', test: (a, b) => { const A = bodyOf(a), B = bodyOf(b); return (A && stretch.has(A) && (mountedOn(A, b) || (B && sameMount(A, B)))) || (B && stretch.has(B) && (mountedOn(B, a) || (A && sameMount(A, B)))); } },
    { why: '線材（core/electrical cable）端點接入接頭、端子或格蘭頭；線材沿線間隙由各專案的配線檢查負責', test: (a, b) => cableEndIn(a, b) || cableEndIn(b, a) },
    { why: '線夾、格蘭頭、護套、支撐柱等小型配線五金（userData.routingHardware）夾在安裝面上', test: (a, b) => !!(hardwareOf(a) || hardwareOf(b)) },
    { why: '套筒式伸縮軸：外管與內管標記為 nested', test: (a, b) => { const A = bodyOf(a), B = bodyOf(b); return !!(A && B && (A.userData.nested === B || B.userData.nested === A)); } },
    { why: '移動件在指定導軌上滑行（導軌 userData.guide，移動件 userData.on）', test: (a, b) => { const A = bodyOf(a), B = bodyOf(b); return (A && A.userData.on && b.userData.guide === A.userData.on) || (B && B.userData.on && a.userData.guide === B.userData.on); } },
    ...(cfg.allow || []).map(r => ({ why: r.why, test: (a, b) => r.test(a, b, ctx) })),
  ];
  const allowed = (a, b) => ALLOW.find(r => r.test(a, b));

  // ---------------------------------------------------------------- 1. 動態
  report(`動態：${meshes.length} 個零件、${moving.length} 個會動、${joints.size} 個關節，每 ${DT} s 取樣`);
  const dyn = new Map(); let samples = 0;
  sample(0); const fixedObbs = fixed.filter(visible).flatMap(toObbs), fixedGrid = grid(fixedObbs);
  const desc = o => { const i = info.get(o.m); return `${i.module}${i.station !== 'misc' ? '/' + i.station : ''}/${o.m.name ? o.m.name + ':' : ''}${o.m.geometry.type.replace('Geometry', '')}@(${o.center.toArray().map(Math.round).join(',')}) ${o.half.map(h => Math.round(h * 2)).join('×')}`; };
  for (let t = 0; t <= total + 1e-9; t += DT) {
    sample(t); samples++;
    const mov = moving.filter(visible).flatMap(toObbs), movGrid = grid(mov);
    for (const a of mov) for (const b of [...fixedGrid.near(a), ...movGrid.near(a)]) {
      if (b.m === a.m || (movingSet.has(b.m) && b.m.id < a.m.id)) continue;   // 會動對會動只算一次
      if (!aabbHit(a, b) || allowed(a.m, b.m)) continue;
      const P = pair(a.m, b.m), g = gap(a, b); if (g >= -P.tol) continue;
      if (curved(a.m, b.m) && !vertexInside(a.m, b.m, P.tol)) continue;              // 曲面件的外框偏保守，一律以實際頂點複核
      const key = a.m.id + '|' + b.m.id, cur = dyn.get(key);
      if (!cur) dyn.set(key, { first: +t.toFixed(2), last: +t.toFixed(2), worst: g, a: desc(a), b: desc(b), count: 1 });
      else { cur.last = +t.toFixed(2); cur.count++; if (g < cur.worst) cur.worst = g; }
    }
  }

  // ---------------------------------------------------------------- 2. 靜態（不同模組或同模組不同工位）
  sample(0);
  const stat = [];
  for (const a of fixedObbs) for (const b of fixedGrid.near(a)) {
    if (b.m.id <= a.m.id || !aabbHit(a, b)) continue;
    const ia = info.get(a.m), ib = info.get(b.m);
    const different = ia.module !== ib.module || (ia.station !== ib.station && ia.station !== 'misc' && ib.station !== 'misc');
    if (!different || allowed(a.m, b.m)) continue;
    const P = pair(a.m, b.m), g = gap(a, b); if (g >= -P.tol) continue;
    if (curved(a.m, b.m) && !vertexInside(a.m, b.m, P.tol)) continue;
    stat.push({ worst: +g.toFixed(1), a: desc(a), b: desc(b) });
  }

  // ---------------------------------------------------------------- 3. 重合面（閃爍）
  const zf = new Map();
  const look = m => { const t = m.material; return t ? [t.color?.getHexString(), t.map?.uuid, t.emissive?.getHexString(), t.opacity].join('|') : ''; };
  const zTimes = Array.from({ length: zfightTimes }, (_, i) => total * i / Math.max(1, zfightTimes - 1));
  for (const t of zTimes) {
    sample(t);
    const all = meshes.filter(visible).filter(m => !(m.material?.transparent && m.material.depthWrite === false)).map(m => ({ ...obb(m), F: faces(m) })).filter(o => o.F.length);
    const gd = grid(all, 400);
    for (const a of all) for (const b of gd.near(a)) {
      if (b.m.id <= a.m.id || !aabbHit(a, b, 1) || a.m.material === b.m.material || look(a.m) === look(b.m)) continue;   // 外觀相同的面重合看不出差異
      for (const f of a.F) for (const g of b.F) {
        const dot = f.N.dot(g.N); if (Math.abs(dot) < .9999) continue;
        if (f.N.y < -.99 && f.C.y < 6) continue;              // 貼地朝下的底面看不到
        const P = pair(a.m, b.m);
        if (Math.abs(g.C.clone().sub(f.C).dot(f.N)) > P.dist) continue;
        if (dot < 0 && !f.both && !g.both) continue;          // 背對背的面不會同時畫出
        const area = overlapArea(f, g); if (area < P.area) continue;
        const key = a.m.id + '|' + b.m.id;
        if (!zf.has(key)) zf.set(key, { t: +t.toFixed(2), area: Math.round(area), a: desc(a), b: desc(b) });
      }
    }
  }

  // ---------------------------------------------------------------- 外圍（例如手臂掃掠，用來配置圍籬）
  const envelope = {};
  for (const mod of cfg.envelope || []) {
    const r = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity, minZ: Infinity, maxZ: -Infinity };
    for (let t = 0; t <= total; t += Math.max(DT, total / 600)) {
      sample(t);
      for (const m of meshes) if (info.get(m).module === mod && visible(m)) { const b = new THREE.Box3().setFromObject(m); r.minX = Math.min(r.minX, b.min.x); r.maxX = Math.max(r.maxX, b.max.x); r.minY = Math.min(r.minY, b.min.y); r.maxY = Math.max(r.maxY, b.max.y); r.minZ = Math.min(r.minZ, b.min.z); r.maxZ = Math.max(r.maxZ, b.max.z); }
    }
    envelope[mod] = Object.fromEntries(Object.entries(r).map(([k, v]) => [k, Math.round(v)]));
  }

  return {
    ok: dyn.size === 0 && stat.length === 0 && zf.size === 0,
    meshes: meshes.length, moving: moving.length, joints: joints.size, samples, dt: DT, total,
    dynamic: [...dyn.values()].sort((a, b) => a.worst - b.worst).map(d => ({ ...d, worst: +d.worst.toFixed(1) })),
    static: stat.sort((a, b) => a.worst - b.worst),
    zfight: [...zf.values()],
    envelope,
    allowances: ALLOW.map(r => r.why),
    thresholds: TH,
    scope: `OBB 分離軸（穿插門檻 ${TOL} mm，可依模組調整，圓柱為保守外框、曲面以頂點複核）；動態每 ${DT} s 取樣；重合面檢查盒、倒角外殼、圓柱端面與平面，距離 < 0.6 mm、重疊 > 25 mm²、外觀不同者，取 ${zfightTimes} 個時刻。不是連續碰撞證明。`,
  };
}

export function sceneText(r) {
  return [...r.dynamic.map(d => `DYN ${d.worst} ${d.first}-${d.last}s ${d.a} <> ${d.b}`), ...r.static.map(d => `STA ${d.worst} ${d.a} <> ${d.b}`), ...r.zfight.map(z => `ZF ${z.area}mm2 t=${z.t} ${z.a} <> ${z.b}`)].join('\n');
}

// ---------------------------------------------------------------- 幾何工具
export function obb(m) {
  if (!m.geometry.boundingBox) m.geometry.computeBoundingBox();
  const b = m.geometry.boundingBox, center = b.getCenter(new THREE.Vector3()).applyMatrix4(m.matrixWorld);
  const half = b.getSize(new THREE.Vector3()).multiplyScalar(.5).toArray();
  const axes = [0, 1, 2].map(i => new THREE.Vector3().setFromMatrixColumn(m.matrixWorld, i));
  axes.forEach((a, i) => { half[i] *= a.length(); a.normalize(); });
  const ext = [0, 1, 2].map(k => axes.reduce((s, a, i) => s + half[i] * Math.abs(a.getComponent(k)), 0));
  return { m, center, half, axes, min: center.toArray().map((c, k) => c - ext[k]), max: center.toArray().map((c, k) => c + ext[k]) };
}
const _ax = new THREE.Vector3();
export function gap(a, b) {
  const d = b.center.clone().sub(a.center); let g = -Infinity;
  const test = axis => { if (axis.lengthSq() < 1e-10) return; axis.normalize(); const r = o => o.axes.reduce((s, v, i) => s + o.half[i] * Math.abs(v.dot(axis)), 0); g = Math.max(g, Math.abs(d.dot(axis)) - r(a) - r(b)); };
  for (const x of a.axes) test(x.clone()); for (const y of b.axes) test(y.clone());
  for (const x of a.axes) for (const y of b.axes) test(_ax.crossVectors(x, y).clone());
  return g;
}
// 配管（TubeGeometry）沿折線很長，整體外框會誤判；改成每一直管段一個 OBB
function pipeObbs(m) {
  const path = m.geometry.parameters.path, r = m.geometry.parameters.radius, out = [];
  const pts = path.curves ? path.curves.flatMap(c => c.isLineCurve3 ? [[c.v1, c.v2]] : c.getPoints(8).slice(1).map((q, i, a) => [i ? a[i - 1] : c.getPoint(0), q])) : path.getPoints(16).slice(1).map((q, i, a) => [i ? a[i - 1] : path.getPoint(0), q]);
  for (const [v1, v2] of pts) {
    const A = v1.clone().applyMatrix4(m.matrixWorld), B = v2.clone().applyMatrix4(m.matrixWorld), d = B.clone().sub(A), L = d.length(); if (L < 1) continue;
    const ax = d.normalize(), p1 = Math.abs(ax.y) < .9 ? new THREE.Vector3(0, 1, 0).cross(ax).normalize() : new THREE.Vector3(1, 0, 0).cross(ax).normalize(), p2 = ax.clone().cross(p1);
    const center = A.clone().add(B).multiplyScalar(.5), half = [L / 2, r, r], axes = [ax, p1, p2];
    const ext = [0, 1, 2].map(k => axes.reduce((s, v, i) => s + half[i] * Math.abs(v.getComponent(k)), 0));
    out.push({ m, center, half, axes, min: center.toArray().map((c, k) => c - ext[k]), max: center.toArray().map((c, k) => c + ext[k]) });
  }
  return out;
}
const toObbs = m => m.geometry.type === 'TubeGeometry' && m.geometry.parameters?.path ? pipeObbs(m) : [obb(m)];
const aabbHit = (a, b, pad = 0) => [0, 1, 2].every(k => a.min[k] - pad < b.max[k] && b.min[k] - pad < a.max[k]);
function grid(list, cell = 600) {
  const g = new Map();
  for (const o of list) for (let x = Math.floor(o.min[0] / cell); x <= Math.floor(o.max[0] / cell); x++) for (let z = Math.floor(o.min[2] / cell); z <= Math.floor(o.max[2] / cell); z++) { const k = x + ',' + z; if (!g.has(k)) g.set(k, []); g.get(k).push(o); }
  return { near(o) { const out = new Set(); for (let x = Math.floor(o.min[0] / cell); x <= Math.floor(o.max[0] / cell); x++) for (let z = Math.floor(o.min[2] / cell); z <= Math.floor(o.max[2] / cell); z++) for (const c of g.get(x + ',' + z) || []) out.add(c); return out; } };
}
// 曲面零件的 OBB 偏保守：外框重疊不深時，改以實際頂點是否落在對方封閉網格內複核（射線奇偶判定）
const isBox = m => ['BoxGeometry', 'ExtrudeGeometry'].includes(m.geometry.type);
const holed = m => m.geometry.type === 'ExtrudeGeometry' && [m.geometry.parameters.shapes].flat().some(sh => sh?.holes?.length);
const curved = (a, b) => !isBox(a) || !isBox(b) || holed(a) || holed(b);   // 曲面件與有開孔的擠出件：外框偏保守，以頂點複核
const ray = new THREE.Raycaster(), dirs = [new THREE.Vector3(1, .013, .007).normalize(), new THREE.Vector3(-.011, 1, .017).normalize()];
function inside(p, target, tol = TOL) {
  if (target.geometry.type === 'BoxGeometry') { const l = target.worldToLocal(p.clone()), q = target.geometry.parameters; return Math.abs(l.x) < q.width / 2 - tol && Math.abs(l.y) < q.height / 2 - tol && Math.abs(l.z) < q.depth / 2 - tol; }
  const mat = Array.isArray(target.material) ? target.material[0] : target.material, side = mat.side; mat.side = THREE.DoubleSide;
  let odd = true; for (const d of dirs) { ray.set(p, d); if (ray.intersectObject(target, false).length % 2 === 0) odd = false; }
  mat.side = side; return odd;
}
function vertexInside(a, b, tol = TOL) {
  for (const [m, t] of [[a, b], [b, a]]) {
    if (t.geometry.parameters?.openEnded || t.geometry.type === 'PlaneGeometry') continue;   // 開放殼不是封閉體
    const pos = m.geometry.attributes.position; if (!pos) continue;
    const step = Math.max(1, Math.floor(pos.count / 400));
    for (let i = 0; i < pos.count; i += step) if (inside(new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld), t, tol)) return true;
  }
  return false;
}
function faces(m) {
  const g = m.geometry, p = g.parameters || {}, out = [];
  const M = m.matrixWorld, add = (c, n, u, v, hu, hv, both = false) => {
    const C = c.clone().applyMatrix4(M), N = n.clone().transformDirection(M), U = u.clone().transformDirection(M), Vv = v.clone().transformDirection(M);
    const s = new THREE.Vector3().setFromMatrixScale(M), su = u.clone().multiply(s).length(), sv = v.clone().multiply(s).length();
    out.push({ C, N, U, V: Vv, hu: hu * su, hv: hv * sv, both });
  };
  const mat = Array.isArray(m.material) ? m.material[0] : m.material, ds = mat?.side === THREE.DoubleSide;
  if (g.type === 'BoxGeometry') {
    const [w, h, d] = [p.width / 2, p.height / 2, p.depth / 2], X = new THREE.Vector3(1, 0, 0), Y = new THREE.Vector3(0, 1, 0), Z = new THREE.Vector3(0, 0, 1);
    for (const s of [-1, 1]) { add(X.clone().multiplyScalar(s * w), X.clone().multiplyScalar(s), Y, Z, h, d, ds); add(Y.clone().multiplyScalar(s * h), Y.clone().multiplyScalar(s), X, Z, w, d, ds); add(Z.clone().multiplyScalar(s * d), Z.clone().multiplyScalar(s), X, Y, w, h, ds); }
  } else if (g.type === 'ExtrudeGeometry') {        // 倒角外殼：平面區域內縮倒角半徑
    if (!g.boundingBox) g.computeBoundingBox();
    const b = g.boundingBox, c = b.getCenter(new THREE.Vector3()), hs = b.getSize(new THREE.Vector3()).multiplyScalar(.5), r = g.parameters.options?.bevelEnabled === false ? 0 : g.parameters.options?.bevelSize || 0;
    const A = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)], H = hs.toArray();
    for (let i = 0; i < 3; i++) for (const s of [-1, 1]) { const j = (i + 1) % 3, k = (i + 2) % 3; add(c.clone().addScaledVector(A[i], s * H[i]), A[i].clone().multiplyScalar(s), A[j], A[k], H[j] - r, H[k] - r, ds); }
  } else if (g.type === 'CylinderGeometry' && !p.openEnded) {   // 圓柱端面（以內接正方形近似）
    const Y = new THREE.Vector3(0, 1, 0);
    for (const [s, r] of [[1, p.radiusTop], [-1, p.radiusBottom]]) if (r > 0) add(Y.clone().multiplyScalar(s * p.height / 2), Y.clone().multiplyScalar(s), new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, 1), r * .7, r * .7, ds);
  } else if (g.type === 'PlaneGeometry') {
    add(new THREE.Vector3(), new THREE.Vector3(0, 0, 1), new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), p.width / 2, p.height / 2, ds);
  }
  return out;
}
// 同平面兩矩形的重疊面積（凸多邊形裁切）
function overlapArea(f, g) {
  const proj = q => { const d = q.clone().sub(f.C); return [d.dot(f.U), d.dot(f.V)]; };
  const corners = h => [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([a, b]) => h.C.clone().addScaledVector(h.U, a * h.hu).addScaledVector(h.V, b * h.hv));
  const ccw = pts => { let s = 0; for (let i = 0; i < pts.length; i++) { const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length]; s += x1 * y2 - x2 * y1; } return s >= 0 ? pts : pts.slice().reverse(); };
  let poly = ccw(corners(f).map(proj)); const cl = ccw(corners(g).map(proj));
  for (let i = 0; i < cl.length && poly.length; i++) {
    const [ax, ay] = cl[i], [bx, by] = cl[(i + 1) % cl.length], inside = ([x, y]) => (bx - ax) * (y - ay) - (by - ay) * (x - ax) >= 0;
    const next = [];
    for (let j = 0; j < poly.length; j++) {
      const P = poly[j], Q = poly[(j + 1) % poly.length], ip = inside(P), iq = inside(Q);
      if (ip) next.push(P);
      if (ip !== iq) { const dx = Q[0] - P[0], dy = Q[1] - P[1], den = (bx - ax) * dy - (by - ay) * dx; const t = den ? ((ax - P[0]) * (by - ay) - (ay - P[1]) * (bx - ax)) / -den : 0; next.push([P[0] + dx * t, P[1] + dy * t]); }
    }
    poly = next;
  }
  let a = 0; for (let i = 0; i < poly.length; i++) { const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length]; a += x1 * y2 - x2 * y1; } return Math.abs(a) / 2;
}
