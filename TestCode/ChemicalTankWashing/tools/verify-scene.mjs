// 全場干涉與閃爍檢查（用畫面同一份幾何，見 web/js/plant.js）：
//   node --no-warnings --experimental-loader ./tools/three-loader.mjs tools/verify-scene.mjs
// 1. 動態：沿整段動畫取樣，凡世界位置會變的零件，都與固定零件及其他會動零件做有向包圍盒（OBB）分離軸檢查。
//    同一剛體、直接相連的上下游關節視為安裝關係不檢查；桶與 AGV 另有專門驗證（verify.mjs），此處排除。
// 2. 靜態：不同設備模組（或產線內不同工位）的固定零件互相穿插 → 架設位置相撞。
// 3. 重合面：兩零件有同向、同平面且面積重疊的面 → 深度互搶造成閃爍（對數深度緩衝也無法解決）。
// OBB 對圓柱、球為保守外框；判定穿插的門檻 2 mm。結果寫入 review/scene-verification.json。
import * as THREE from 'three';
import { writeFileSync } from 'node:fs';
import { buildPlant, applyPlant } from '../web/js/plant.js';
import { createSequence } from '../web/js/sequence.js';
import { FOOTPRINTS } from '../web/js/layout.js';

const TOL = 2, DT = Number(process.argv.find(a => a.startsWith('--dt='))?.slice(5) ?? .5);
const scene = new THREE.Scene(), plant = buildPlant(scene), seq = createSequence({ robot: plant.robot });
const skipRoots = new Set([plant.building.zones, plant.building.dims, plant.building.ceiling]);
const sample = t => { applyPlant(plant, seq.sample(t)); scene.updateMatrixWorld(true); };

// ---------------------------------------------------------------- 零件清單與分類
const meshes = [];
scene.traverse(o => {
  if (!o.isMesh || o.isInstancedMesh || !o.geometry) return;
  for (let p = o; p; p = p.parent) if (skipRoots.has(p) || p.userData.fx) return;   // 噴霧、水柱、氣流等效果不是實體
  meshes.push(o);
});
const moduleOf = o => { for (let p = o; p; p = p.parent) if (p.name?.startsWith('drum ')) return 'drum'; let p = o; while (p.parent && p.parent !== scene) p = p.parent; return p.name || 'misc'; };
sample(0);
const stationOf = o => {
  const c = new THREE.Box3().setFromObject(o).getCenter(new THREE.Vector3());
  const hit = Object.entries(FOOTPRINTS).find(([, r]) => c.x >= r[0] - 150 && c.x <= r[2] + 150 && c.z >= r[1] - 150 && c.z <= r[3] + 150);
  return hit ? hit[0] : 'misc';
};
const info = new Map(meshes.map(m => [m, { module: moduleOf(m), station: stationOf(m) }]));
// 關節：局部矩陣在動畫中會變的物件；剛體 = 最近的關節祖先
const objs = []; scene.traverse(o => objs.push(o));
const local0 = new Map(objs.map(o => [o, o.matrix.clone()])), joints = new Set();
const probes = Array.from({ length: 60 }, (_, i) => seq.total * (i + .5) / 60);
for (const t of probes) { sample(t); for (const o of objs) if (!joints.has(o) && !o.matrix.equals(local0.get(o))) joints.add(o); }
// 只在原地自轉的軸對稱零件（滾輪、輪轂）：世界中心不變，外框不代表實體，視為固定
const AXI = new Set(['CylinderGeometry', 'LatheGeometry', 'SphereGeometry', 'TorusGeometry']);
const spinner = new Set(), stretch = new Set(), c0 = new Map();
sample(0); for (const m of meshes) c0.set(m, new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3()));
const s0 = new Map(objs.map(o => [o, o.scale.clone()]));
for (const t of probes) { sample(t); for (const m of meshes) if (AXI.has(m.geometry.type) && !spinner.has(m) && new THREE.Box3().setFromObject(m).getCenter(new THREE.Vector3()).distanceTo(c0.get(m)) > .5) spinner.add(m); for (const o of objs) if (!o.scale.equals(s0.get(o))) stretch.add(o); }
for (const m of meshes) if (AXI.has(m.geometry.type)) { if (spinner.has(m)) spinner.delete(m); else spinner.add(m); }   // 留下「中心不動」者
const bodyOf = o => { if (spinner.has(o)) return null; for (let p = o; p && p !== scene; p = p.parent) if (joints.has(p) && !spinnerJoint(p)) return p; return null; };
function spinnerJoint(p) { let only = true; p.traverse(c => { if (c.isMesh && !spinner.has(c)) only = false; }); return only; }
const parentBody = b => bodyOf(b.parent);
const moving = meshes.filter(m => bodyOf(m)), fixed = meshes.filter(m => !bodyOf(m));
const visible = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };

// ---------------------------------------------------------------- OBB
function obb(m) {
  if (!m.geometry.boundingBox) m.geometry.computeBoundingBox();
  const b = m.geometry.boundingBox, center = b.getCenter(new THREE.Vector3()).applyMatrix4(m.matrixWorld);
  const half = b.getSize(new THREE.Vector3()).multiplyScalar(.5).toArray();
  const axes = [0, 1, 2].map(i => new THREE.Vector3().setFromMatrixColumn(m.matrixWorld, i));
  axes.forEach((a, i) => { half[i] *= a.length(); a.normalize(); });
  const ext = [0, 1, 2].map(k => axes.reduce((s, a, i) => s + half[i] * Math.abs(a.getComponent(k)), 0));
  return { m, center, half, axes, min: center.toArray().map((c, k) => c - ext[k]), max: center.toArray().map((c, k) => c + ext[k]) };
}
const _ax = new THREE.Vector3();
function gap(a, b) {
  const d = b.center.clone().sub(a.center); let g = -Infinity;
  const test = axis => { if (axis.lengthSq() < 1e-10) return; axis.normalize(); const r = o => o.axes.reduce((s, v, i) => s + o.half[i] * Math.abs(v.dot(axis)), 0); g = Math.max(g, Math.abs(d.dot(axis)) - r(a) - r(b)); };
  for (const x of a.axes) test(x.clone()); for (const y of b.axes) test(y.clone());
  for (const x of a.axes) for (const y of b.axes) test(_ax.crossVectors(x, y).clone());
  return g;
}
// 配管（TubeGeometry）沿折線很長，整體外框會誤判；改成每一直管段一個 OBB
function pipeObbs(m) {
  const path = m.geometry.parameters.path, r = m.geometry.parameters.radius, out = [];
  // 直角配管為 CurvePath（逐段直線）；軟管等曲線改以 16 段折線近似
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
const toObbs = m => m.geometry.type === 'TubeGeometry' ? pipeObbs(m) : [obb(m)];
const aabbHit = (a, b, pad = 0) => [0, 1, 2].every(k => a.min[k] - pad < b.max[k] && b.min[k] - pad < a.max[k]);
function grid(list, cell = 600) {
  const g = new Map();
  for (const o of list) for (let x = Math.floor(o.min[0] / cell); x <= Math.floor(o.max[0] / cell); x++) for (let z = Math.floor(o.min[2] / cell); z <= Math.floor(o.max[2] / cell); z++) { const k = x + ',' + z; if (!g.has(k)) g.set(k, []); g.get(k).push(o); }
  return { near(o) { const out = new Set(); for (let x = Math.floor(o.min[0] / cell); x <= Math.floor(o.max[0] / cell); x++) for (let z = Math.floor(o.min[2] / cell); z <= Math.floor(o.max[2] / cell); z++) for (const c of g.get(x + ',' + z) || []) out.add(c); return out; } };
}
const r0 = v => Math.round(v);
const desc = o => { const i = info.get(o.m); return `${i.module}/${i.station}/${o.m.geometry.type.replace('Geometry', '')}@(${o.center.toArray().map(r0).join(',')}) ${o.half.map(h => r0(h * 2)).join('×')}`; };

// ---------------------------------------------------------------- 明確允許的安裝／滑動接觸（逐條說明原因）
const ALLOW = [
  { why: '桶由各站支撐、夾持或噴槍伸入，桶的干涉另由 verify.mjs 檢查', test: (a, b) => info.get(a).module === 'drum' || info.get(b).module === 'drum' },
  { why: 'AGV 與棧板、貨架以 2D 車身多邊形另行驗證（verify.mjs），叉子插入棧板屬正常', test: (a, b) => [a, b].some(m => info.get(m).module === 'agv') && [a, b].some(m => ['storage', 'agv'].includes(info.get(m).module)) },
  { why: '同一剛體或直接相連的關節（導軌、滑座、轉軸）', test: (a, b) => { const A = bodyOf(a), B = bodyOf(b); return A === B || (A && parentBody(A) === B) || (B && parentBody(B) === A); } },
  { why: '伸縮連桿（鏈條、活塞桿等長度會變的零件）與同一載體上的零件相接', test: (a, b) => { const A = bodyOf(a), B = bodyOf(b); return (A && stretch.has(A) && (parentBody(A) === B || (B && parentBody(B) === parentBody(A)))) || (B && stretch.has(B) && (parentBody(B) === A || (A && parentBody(A) === parentBody(B)))); } },
  { why: '套筒式伸縮軸：外管與內管標記為 nested', test: (a, b) => { const A = bodyOf(a), B = bodyOf(b); return !!(A && B && (A.userData.nested === B || B.userData.nested === A)); } },
  { why: '移動件在指定導軌上滑行（導軌標記 userData.guide，移動件標記 userData.on）', test: (a, b) => { const A = bodyOf(a), B = bodyOf(b); return (A && A.userData.on && b.userData.guide === A.userData.on) || (B && B.userData.on && a.userData.guide === B.userData.on); } },
  { why: '手臂本體與夾爪內部零件為廠商／夾爪模型，自身干涉另見 verify-gripper.mjs', test: (a, b) => info.get(a).module === 'robot' && info.get(b).module === 'robot' },
];
const allowed = (a, b) => ALLOW.find(r => r.test(a, b));

// 曲面零件的 OBB 偏保守：外框重疊不深時，改以實際頂點是否落在對方封閉網格內複核（射線奇偶判定）
const isBox = m => ['BoxGeometry', 'ExtrudeGeometry'].includes(m.geometry.type);
const curved = (a, b) => !isBox(a) || !isBox(b);
const ray = new THREE.Raycaster(), dirs = [new THREE.Vector3(1, .013, .007).normalize(), new THREE.Vector3(-.011, 1, .017).normalize()];
function inside(p, target) {
  if (target.geometry.type === 'BoxGeometry') { const l = target.worldToLocal(p.clone()), q = target.geometry.parameters; return Math.abs(l.x) < q.width / 2 - TOL && Math.abs(l.y) < q.height / 2 - TOL && Math.abs(l.z) < q.depth / 2 - TOL; }
  const mat = target.material, side = mat.side; mat.side = THREE.DoubleSide;
  let odd = true; for (const d of dirs) { ray.set(p, d); if (target.raycast.length && ray.intersectObject(target, false).length % 2 === 0) odd = false; }
  mat.side = side; return odd;
}
function vertexInside(a, b) {
  for (const [m, t] of [[a, b], [b, a]]) {
    if (t.geometry.parameters?.openEnded || t.geometry.type === 'PlaneGeometry') continue;   // 開放殼不是封閉體
    const pos = m.geometry.attributes.position, step = Math.max(1, Math.floor(pos.count / 400));
    for (let i = 0; i < pos.count; i += step) if (inside(new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld), t)) return true;
  }
  return false;
}

// ---------------------------------------------------------------- 1. 動態檢查
const dyn = new Map(); let samples = 0;
sample(0); const fixedObbs = fixed.filter(visible).flatMap(toObbs), fixedGrid = grid(fixedObbs);
for (let t = 0; t <= seq.total + 1e-9; t += DT) {
  sample(t); samples++;
  const mov = moving.filter(visible).flatMap(toObbs), movGrid = grid(mov);
  for (const a of mov) {
    if (info.get(a.m).module === 'drum') continue;
    for (const b of [...fixedGrid.near(a), ...movGrid.near(a)]) {
      if (b.m === a.m || (bodyOf(b.m) && b.m.id < a.m.id && info.get(b.m).module !== 'drum')) continue;   // 會動對會動只算一次
      if (!aabbHit(a, b) || allowed(a.m, b.m)) continue;
      const g = gap(a, b); if (g >= -TOL) continue;
      if (curved(a.m, b.m) && g > -40 && !vertexInside(a.m, b.m)) continue;   // 曲面零件以實際頂點複核
      const key = a.m.id + '|' + b.m.id, cur = dyn.get(key);
      if (!cur) dyn.set(key, { first: +t.toFixed(2), last: +t.toFixed(2), worst: g, a: desc(a), b: desc(b), count: 1 });
      else { cur.last = +t.toFixed(2); cur.count++; if (g < cur.worst) cur.worst = g; }
    }
  }
}

// ---------------------------------------------------------------- 2. 靜態架設檢查（不同模組或不同工位）
sample(0);
const stat = [];
for (const a of fixedObbs) for (const b of fixedGrid.near(a)) {
  if (b.m.id <= a.m.id || !aabbHit(a, b)) continue;
  const ia = info.get(a.m), ib = info.get(b.m);
  const different = ia.module !== ib.module || (ia.module === 'line' && ia.station !== ib.station && ia.station !== 'misc' && ib.station !== 'misc');
  if (!different || allowed(a.m, b.m)) continue;
  const g = gap(a, b); if (g < -TOL) stat.push({ worst: +g.toFixed(1), a: desc(a), b: desc(b) });
}

// ---------------------------------------------------------------- 3. 重合面（閃爍）
function faces(m) {
  const g = m.geometry, p = g.parameters || {}, out = [];
  const M = m.matrixWorld, add = (c, n, u, v, hu, hv, both = false) => {
    const C = c.clone().applyMatrix4(M), N = n.clone().transformDirection(M), U = u.clone().transformDirection(M), Vv = v.clone().transformDirection(M);
    const s = new THREE.Vector3().setFromMatrixScale(M), su = u.clone().multiply(s).length(), sv = v.clone().multiply(s).length();
    out.push({ C, N, U, V: Vv, hu: hu * su, hv: hv * sv, both });
  };
  const ds = m.material?.side === THREE.DoubleSide;
  if (g.type === 'BoxGeometry') {
    const [w, h, d] = [p.width / 2, p.height / 2, p.depth / 2], X = new THREE.Vector3(1, 0, 0), Y = new THREE.Vector3(0, 1, 0), Z = new THREE.Vector3(0, 0, 1);
    for (const s of [-1, 1]) { add(X.clone().multiplyScalar(s * w), X.clone().multiplyScalar(s), Y, Z, h, d, ds); add(Y.clone().multiplyScalar(s * h), Y.clone().multiplyScalar(s), X, Z, w, d, ds); add(Z.clone().multiplyScalar(s * d), Z.clone().multiplyScalar(s), X, Y, w, h, ds); }
  } else if (g.type === 'ExtrudeGeometry') {        // 倒角外殼：平面區域內縮倒角半徑
    if (!g.boundingBox) g.computeBoundingBox();
    const b = g.boundingBox, c = b.getCenter(new THREE.Vector3()), hs = b.getSize(new THREE.Vector3()).multiplyScalar(.5), r = g.parameters.options.bevelSize || 0;
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
  const proj = (q, F) => { const d = q.clone().sub(F.C); return [d.dot(F.U), d.dot(F.V)]; };
  const corners = h => [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([a, b]) => h.C.clone().addScaledVector(h.U, a * h.hu).addScaledVector(h.V, b * h.hv));
  let poly = corners(f).map(q => proj(q, f));
  const clip = corners(g).map(q => proj(q, f));
  const ccw = pts => { let s = 0; for (let i = 0; i < pts.length; i++) { const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length]; s += x1 * y2 - x2 * y1; } return s >= 0 ? pts : pts.slice().reverse(); };
  poly = ccw(poly); const cl = ccw(clip);
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
const zf = new Map();
function zfightAt(t) {
  sample(t);
  const all = meshes.filter(visible).filter(m => !(m.material?.transparent && m.material.depthWrite === false)).map(m => ({ ...obb(m), F: faces(m) })).filter(o => o.F.length);
  const gd = grid(all, 400);
  // 相同外觀（同材質、或同色同貼圖）的面重合時畫面看不出差異，不會閃爍
  const look = m => { const t = m.material; return t ? [t.color?.getHexString(), t.map?.uuid, t.emissive?.getHexString(), t.opacity].join('|') : ''; };
  for (const a of all) for (const b of gd.near(a)) {
    if (b.m.id <= a.m.id || !aabbHit(a, b, 1) || a.m.material === b.m.material || look(a.m) === look(b.m)) continue;
    for (const f of a.F) for (const g of b.F) {
      const dot = f.N.dot(g.N); if (Math.abs(dot) < .9999) continue;
      if (f.N.y < -.99 && f.C.y < 6) continue;              // 貼地朝下的底面看不到
      if (Math.abs(g.C.clone().sub(f.C).dot(f.N)) > .6) continue;
      if (dot < 0 && !f.both && !g.both) continue;          // 背對背的面不會同時畫出
      const area = overlapArea(f, g); if (area < 25) continue;
      const key = a.m.id + '|' + b.m.id;
      if (!zf.has(key)) zf.set(key, { t: +t.toFixed(1), area: r0(area), a: desc(a), b: desc(b) });
    }
  }
}
for (const t of [0, ...probes.filter((_, i) => i % 6 === 0)]) zfightAt(t);

// 手臂（含夾爪）沿動畫的外圍：用來配置圍籬
const reach = { minX: Infinity, maxX: -Infinity, minZ: Infinity, maxZ: -Infinity };
for (let t = 0; t <= seq.total; t += 1) { sample(t); for (const m of meshes) if (info.get(m).module === 'robot' && visible(m)) { const b = new THREE.Box3().setFromObject(m); reach.minX = Math.min(reach.minX, b.min.x); reach.maxX = Math.max(reach.maxX, b.max.x); reach.minZ = Math.min(reach.minZ, b.min.z); reach.maxZ = Math.max(reach.maxZ, b.max.z); } }
const result = {
  robotEnvelope: Object.fromEntries(Object.entries(reach).map(([k, v]) => [k, Math.round(v)])),
  ok: dyn.size === 0 && stat.length === 0 && zf.size === 0,
  meshes: meshes.length, moving: moving.length, joints: joints.size, samples, dt: DT,
  dynamic: [...dyn.values()].sort((a, b) => a.worst - b.worst).map(d => ({ ...d, worst: +d.worst.toFixed(1) })),
  static: stat.sort((a, b) => a.worst - b.worst),
  zfight: [...zf.values()],
  allowances: ALLOW.map(r => r.why),
  scope: `OBB 分離軸（穿插門檻 ${TOL} mm，圓柱為保守外框）；動態每 ${DT} s 取樣；重合面檢查盒、倒角外殼、圓柱端面與平面，距離 < 0.6 mm 且重疊 > 25 mm²。不是連續碰撞證明。`,
};
writeFileSync(new URL('../review/scene-verification.json', import.meta.url), JSON.stringify(result, null, 2));
writeFileSync(new URL('../review/scene-verification.txt', import.meta.url), [...result.dynamic.map(d => `DYN ${d.worst} ${d.first}-${d.last}s ${d.a} <> ${d.b}`), ...result.static.map(d => `STA ${d.worst} ${d.a} <> ${d.b}`), ...result.zfight.map(z => `ZF ${z.area}mm2 ${z.a} <> ${z.b}`)].join(String.fromCharCode(10)));
console.log('robot envelope', JSON.stringify(result.robotEnvelope));
console.log(JSON.stringify({ ok: result.ok, meshes: result.meshes, moving: result.moving, joints: result.joints, samples, dynamic: result.dynamic.length, static: result.static.length, zfight: result.zfight.length }));
for (const d of result.dynamic.slice(0, 40)) console.log('DYN', d.worst, d.first + '-' + d.last + 's', d.a, '<>', d.b);
for (const s of result.static.slice(0, 40)) console.log('STA', s.worst, s.a, '<>', s.b);
for (const z of result.zfight.slice(0, 60)) console.log('ZF ', z.area + 'mm²', z.a, '<>', z.b);
process.exit(result.ok ? 0 : 1);
