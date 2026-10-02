// Copper skins, laminate hole walls and adhesive backing use true through-hole geometry.
import * as THREE from 'three';
import { PRODUCT, HOLES } from './layout.js';
import { matCopper, matCoin, matCoinBack, matCoinEdge, surfaceUV } from './surfaces.js';
export { matCopper, matCoinBack } from './surfaces.js';
const B = PRODUCT.board;
// 銅箔（約 0.035 mm）遠薄於深度緩衝精度，做成實體只會與芯材、黏紙、輸送皮帶面互搶深度；
// 改為零厚度表皮：上銅箔朝上、下銅箔朝下（BackSide），芯材上下蓋面不繪製，只留孔壁與板邊。
const matAdhesive = new THREE.MeshStandardMaterial({ color: 0x9ca99b, roughness: .95 });
const matCore = new THREE.MeshStandardMaterial({ color: 0x4b5134, roughness: .87 });
const matCopperBelow = matCopper.clone(); matCopperBelow.side = THREE.BackSide;
// Copper covers the core caps; omitting those hidden faces avoids depth fighting at overview distances.
const hiddenCoreCap = new THREE.MeshBasicMaterial({ visible: false });
const CORE_INSET = .01;   // 芯材蓋面略縮進表皮內，射線與排序永遠先碰到銅箔表皮
/** Rounded rectangle; photo shows straight ends with corner radii. Shape y maps to -z. */
export function obround(w, l, cx = 0, cz = 0, path = new THREE.Shape(), radius = w / 2) {
  const r = Math.min(radius, w / 2, l / 2), x = cx - w / 2, y = -cz - l / 2;
  path.moveTo(x + r, y); path.lineTo(x + w - r, y);
  path.absarc(x + w - r, y + r, r, -Math.PI / 2, 0);
  path.lineTo(x + w, y + l - r); path.absarc(x + w - r, y + l - r, r, 0, Math.PI / 2);
  path.lineTo(x + r, y + l); path.absarc(x + r, y + l - r, r, Math.PI / 2, Math.PI);
  path.lineTo(x, y + r); path.absarc(x + r, y + r, r, Math.PI, Math.PI * 1.5); path.closePath(); return path;
}
function outline(spec, cx = 0, cz = 0, path = new THREE.Shape()) {
  if (spec.shape === 'round') { path.absarc(cx, -cz, spec.w / 2, 0, Math.PI * 2); return path; }
  return obround(spec.w, spec.l, cx, cz, path, spec.radius ?? spec.w / 2);
}
const cache = new Map();
const cached = (key, make) => { const k = PRODUCT.recipe + ':' + key; if (!cache.has(k)) cache.set(k, make()); return cache.get(k); };
export function coinGeometry() {
  return cached('coin', () => {
    const co = PRODUCT.coin, bevel = .045;
    // Inset first: bevel expansion must not change the nominal width/length/thickness.
    const spec = { ...co, w: co.w - bevel * 2, l: co.l - bevel * 2, radius: (co.radius ?? co.w / 2) - bevel };
    const g = new THREE.ExtrudeGeometry(outline(spec), { depth: co.t - bevel * 2, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments: 2, curveSegments: 24, steps: 1 });
    g.rotateX(-Math.PI / 2); g.translate(0, bevel, 0); return surfaceUV(g, 12);
  });
}
function boardShape() {
  const s = obround(B.w, B.d, 0, 0, new THREE.Shape(), .6);
  for (const h of HOLES) s.holes.push(outline(PRODUCT.hole, h.x, h.z, new THREE.Path()));
  for (const [x, z] of PRODUCT.fiducials) { const p = new THREE.Path(); p.absarc(x, -z, 1.5, 0, Math.PI * 2); s.holes.push(p); } return s;
}
function layerGeometry(depth) {
  return cached('layer:' + depth, () => {
    const g = new THREE.ExtrudeGeometry(boardShape(), { depth, bevelEnabled: false, curveSegments: 16 });
    g.rotateX(-Math.PI / 2); return surfaceUV(g, 70);
  });
}
/** 銅箔表皮：與芯材同一個外形與孔位，法向朝上 */
function skinGeometry() {
  return cached('skin', () => {
    const g = new THREE.ShapeGeometry(boardShape(), 16);
    g.rotateX(-Math.PI / 2); return surfaceUV(g, 70);
  });
}
export function createBoard({ placedOrder = HOLES, pose = h => ({ x: h.x, z: h.z, a: 0 }), mapOrder = HOLES, inspOrder = HOLES } = {}) {
  const group = new THREE.Group(); group.name = 'copper-clad-board';
  // 黏紙：只在孔底看得到，以朝上的面放在黏紙上表面（銅片落座高度）；z 向留在輸送皮帶（|z| ≥ 170）內側
  const adhesive = new THREE.Mesh(new THREE.PlaneGeometry(B.w - 2, B.d - 14), matAdhesive);
  adhesive.name = 'adhesive'; adhesive.rotation.x = -Math.PI / 2; adhesive.position.y = B.adhesive; adhesive.receiveShadow = true; group.add(adhesive);
  for (const [name, geometry, y, material] of [
    ['bottom-copper', skinGeometry(), B.adhesive, matCopperBelow],
    ['laminate-core', layerGeometry(B.t - CORE_INSET * 2), B.adhesive + CORE_INSET, [hiddenCoreCap, matCore]],
    ['top-copper', skinGeometry(), B.adhesive + B.t, matCopper],
  ]) {
    const layer = new THREE.Mesh(geometry, material); layer.name = name;
    layer.position.y = y; layer.castShadow = layer.receiveShadow = true; group.add(layer);
  }
  const coins = new THREE.InstancedMesh(coinGeometry(), [matCoin, matCoinEdge], placedOrder.length);
  coins.name = 'inserted-copper'; coins.castShadow = coins.receiveShadow = true;
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0), one = new THREE.Vector3(1, 1, 1);
  placedOrder.forEach((h, i) => {
    const p = pose(h); coins.setMatrixAt(i, m.compose(new THREE.Vector3(p.x, B.adhesive, p.z), q.setFromAxisAngle(up, p.a * Math.PI / 180), one));
    const shade = .89 + ((h.id * 37 + 11) % 101) / 101 * .11;
    coins.setColorAt(i, new THREE.Color(shade, shade, shade));
  });
  // Bound all instances before count=0; otherwise the first render can cache an empty sphere.
  coins.computeBoundingSphere(); coins.count = 0; group.add(coins);
  const rr = Math.max(PRODUCT.hole.w, PRODUCT.hole.l) / 2 + 1;
  const ring = new THREE.RingGeometry(rr, rr + .45, 40); ring.rotateX(-Math.PI / 2);
  const mk = (color, order) => {
    const inst = new THREE.InstancedMesh(ring, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: .65, depthWrite: false }), order.length);
    order.forEach((h, i) => inst.setMatrixAt(i, m.makeTranslation(h.x, B.adhesive + B.t + .3, h.z)));
    inst.computeBoundingSphere(); inst.count = 0; group.add(inst); return inst;
  };
  const mapMarks = mk(0x4ad8ff, mapOrder), inspMarks = mk(0x3dd68c, inspOrder);
  return { group,
    setAnnotations(show) { mapMarks.visible = inspMarks.visible = show; },
    setCoins(n) { coins.count = Math.max(0, Math.min(placedOrder.length, n)); },
    setMapped(n) { mapMarks.count = Math.max(0, Math.min(mapOrder.length, n)); },
    setInspected(n) { inspMarks.count = Math.max(0, Math.min(inspOrder.length, n)); },
  };
}
export function createCoin(back = false) {
  const c = new THREE.Mesh(coinGeometry(), [back ? matCoinBack : matCoin, matCoinEdge]); c.castShadow = c.receiveShadow = true; return c;
}
