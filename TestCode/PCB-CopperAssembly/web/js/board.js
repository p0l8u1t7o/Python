// 銅箔基板（依配方的長圓孔或圓孔＋底部黏紙）與散熱銅片。銅片以 InstancedMesh 依放置順序顯示，count 即已放數量。
import * as THREE from 'three';
import { PRODUCT, HOLES } from './layout.js';

const B = PRODUCT.board;
export const matCopper = new THREE.MeshStandardMaterial({ color: 0xc27a52, roughness: 0.38, metalness: 0.85 });
const matCoin = new THREE.MeshStandardMaterial({ color: 0xf2b27e, roughness: 0.22, metalness: 0.9, emissive: 0x3a1a08, emissiveIntensity: 0.4 });   // 比板面亮，方便辨識已放的銅片
export const matCoinBack = new THREE.MeshStandardMaterial({ color: 0x7a4a33, roughness: 0.6, metalness: 0.5 });
const matAdhesive = new THREE.MeshStandardMaterial({ color: 0x9fb0a8, roughness: 0.8 });
const matCore = new THREE.MeshStandardMaterial({ color: 0x3d4a2f, roughness: 0.7 });

/** 長圓形（stadium）外形：寬 w、長 l（長軸沿本地 z） */
export function obround(w, l, cx = 0, cz = 0, path = new THREE.Shape()) {
  const r = w / 2, h = l / 2 - r;
  path.moveTo(cx - r, -(cz - h));
  path.absarc(cx, -(cz + h), r, Math.PI, 2 * Math.PI, false);   // Shape 的 y 對應 −z
  path.lineTo(cx + r, -(cz - h));
  path.absarc(cx, -(cz - h), r, 0, Math.PI, false);
  return path;
}
/** 依形狀產生外形：obround（長圓）或 round（圓） */
function outline(shape, w, l, cx = 0, cz = 0, path = new THREE.Shape()) {
  if (shape === 'round') { path.absarc(cx, -cz, w / 2, 0, Math.PI * 2, false); return path; }
  return obround(w, l, cx, cz, path);
}
// 幾何依配方快取（切換配方會重建頁面，但驗證可能在同一程序內切換）
const cache = new Map();
const cached = (key, make) => { const k = PRODUCT.recipe + ':' + key; if (!cache.has(k)) cache.set(k, make()); return cache.get(k); };
/** 銅片幾何：底面在 y=0、長軸沿本地 z */
export function coinGeometry() {
  return cached('coin', () => {
    const CO = PRODUCT.coin, g = new THREE.ExtrudeGeometry(outline(CO.shape, CO.w, CO.l), { depth: CO.t, bevelEnabled: false, curveSegments: 16 });
    g.rotateX(-Math.PI / 2); return g;
  });
}

function boardGeometry() {
  return cached('board', () => {
  const HO = PRODUCT.hole;
  const s = new THREE.Shape(); s.moveTo(-B.w / 2, -B.d / 2); s.lineTo(B.w / 2, -B.d / 2); s.lineTo(B.w / 2, B.d / 2); s.lineTo(-B.w / 2, B.d / 2); s.closePath();
  for (const h of HOLES) s.holes.push(outline(HO.shape, HO.w, HO.l, h.x, h.z, new THREE.Path()));
  for (const [x, z] of PRODUCT.fiducials) { const p = new THREE.Path(); p.absarc(x, -z, 1.5, 0, Math.PI * 2, false); s.holes.push(p); }
  const geo = new THREE.ExtrudeGeometry(s, { depth: B.t, bevelEnabled: false, curveSegments: 8 });
  geo.rotateX(-Math.PI / 2); return geo;
  });
}

/**
 * 一片基板：原點在黏紙底面中心。
 * placedOrder：銅片實例的排列（依放置時間），pose(h) 回傳該孔銅片在板上的位置與角度。
 */
export function createBoard({ placedOrder = HOLES, pose = h => ({ x: h.x, z: h.z, a: 0 }), mapOrder = HOLES, inspOrder = HOLES } = {}) {
  const group = new THREE.Group();
  const adhesive = new THREE.Mesh(new THREE.BoxGeometry(B.w - 2, B.adhesive, B.d - 2), matAdhesive); adhesive.position.y = B.adhesive / 2; group.add(adhesive);
  const board = new THREE.Mesh(boardGeometry(), [matCopper, matCore]); board.position.y = B.adhesive; board.castShadow = board.receiveShadow = true; group.add(board);
  // 銅片（依放置順序）
  const coins = new THREE.InstancedMesh(coinGeometry(), matCoin, placedOrder.length); coins.castShadow = true;
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0), one = new THREE.Vector3(1, 1, 1);
  placedOrder.forEach((h, i) => { const p = pose(h); coins.setMatrixAt(i, m.compose(new THREE.Vector3(p.x, B.adhesive, p.z), q.setFromAxisAngle(up, p.a * Math.PI / 180), one)); });
  coins.count = 0; group.add(coins);
  // S1 量測標記（青色）、S3 檢查標記（綠色）
  const rr = Math.max(PRODUCT.hole.w, PRODUCT.hole.l) / 2 + 1, ring = new THREE.RingGeometry(rr, rr + 0.8, 28); ring.rotateX(-Math.PI / 2);
  const mk = (color, order) => {
    const inst = new THREE.InstancedMesh(ring, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9, depthWrite: false }), order.length);
    order.forEach((h, i) => inst.setMatrixAt(i, m.makeTranslation(h.x, B.adhesive + B.t + 0.3, h.z))); inst.count = 0; group.add(inst); return inst;
  };
  const mapMarks = mk(0x4ad8ff, mapOrder), inspMarks = mk(0x3dd68c, inspOrder);
  return {
    group,
    setCoins(n) { coins.count = Math.max(0, Math.min(placedOrder.length, n)); },
    setMapped(n) { mapMarks.count = Math.max(0, Math.min(mapOrder.length, n)); },
    setInspected(n) { inspMarks.count = Math.max(0, Math.min(inspOrder.length, n)); },
  };
}
/** 單顆銅片（吸嘴上、供料盤上用） */
export function createCoin(back = false) { const c = new THREE.Mesh(coinGeometry(), back ? matCoinBack : matCoin); c.castShadow = true; return c; }
