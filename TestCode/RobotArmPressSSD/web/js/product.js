// 產品：依配方建出載盤、板子與接頭。接頭可翹起（以插頭尖端底緣為支點），銀腳端抬高即為未貼合。
// 座標：產品根節點在載盤底面中心；單位 mm。尺寸為照片目測或假設，實際以圖面校正。
import * as THREE from 'three';
import { block, decal } from './detail.js';
import { CONNECTOR_TYPES } from './recipes.js';

const D2R = Math.PI / 180;
const matPallet = new THREE.MeshStandardMaterial({ color: 0x35312e, roughness: 0.92, metalness: 0.05 });
const matPocket = new THREE.MeshStandardMaterial({ color: 0x24211f, roughness: 0.95 });
const matPcb = new THREE.MeshStandardMaterial({ color: 0x1d6a3a, roughness: 0.55, metalness: 0.05 });
const matRail = new THREE.MeshStandardMaterial({ color: 0x1a5a31, roughness: 0.6 });
const matGold = new THREE.MeshStandardMaterial({ color: 0xd8b04a, roughness: 0.3, metalness: 0.9 });
const matShell = new THREE.MeshStandardMaterial({ color: 0xc9cdd2, roughness: 0.28, metalness: 0.92 });
const matHole = new THREE.MeshStandardMaterial({ color: 0x15181b, roughness: 0.6 });
const matLead = new THREE.MeshStandardMaterial({ color: 0xe6e8ea, roughness: 0.2, metalness: 1 });
const COMP = {
  chip: new THREE.MeshStandardMaterial({ color: 0x1b1d20, roughness: 0.5 }),
  passive: new THREE.MeshStandardMaterial({ color: 0x8a6a4a, roughness: 0.5 }),
  cap: new THREE.MeshStandardMaterial({ color: 0x3a3f8a, roughness: 0.4, metalness: 0.3 }),
};

/** 單顆接頭：pivot 在插頭尖端底緣，旋轉 −tilt 讓後緣（銀腳）抬高 */
function buildConnector(T) {
  const pivot = new THREE.Group(), { w, h, l, sink } = T;
  // 以 pivot（尖端底緣）為原點：殼體 z ∈ [0, l]、y ∈ [0, h]；銀腳從後緣延伸到 PCB 焊墊上
  block(pivot, [w, 0.3, l], [0, h - 0.15, l / 2], matShell);
  block(pivot, [w, 0.3, l], [0, 0.15, l / 2], matShell);
  for (const s of [-1, 1]) block(pivot, [0.3, h, l], [s * (w / 2 - 0.15), h / 2, l / 2], matShell);
  block(pivot, [w - 1, Math.min(1.6, h * 0.4), l - 1.5], [0, h * 0.58, l / 2 - 0.3], new THREE.MeshStandardMaterial({ color: T.tongue, roughness: 0.6 }));
  if (T.holes) for (const s of [-1, 1]) block(pivot, [2.4, 0.1, 2.4], [s * 2.6, h + 0.02, 4], matHole);
  block(pivot, [w, h, 0.3], [0, h / 2, l - 0.15], matShell);
  for (let k = 0; k < T.leads; k++) {
    const x = (k - (T.leads - 1) / 2) * T.leadPitch;
    block(pivot, [Math.min(0.35, T.leadPitch * 0.6), 0.2, T.leadL + 0.6], [x, sink + 0.1, l + T.leadL / 2 - 0.3], matLead);
  }
  return pivot;
}

function buildBoard(parent, b, pcbTop) {
  const g = new THREE.Group(); g.position.set(b.x, 0, b.z); g.rotation.y = b.rot * D2R; parent.add(g);
  block(g, [b.w, b.t, b.d], [b.cx, pcbTop - b.t / 2, b.cz], matPcb);
  for (const c of b.comps || []) block(g, [c.w, c.h, c.d], [c.x, pcbTop + c.h / 2, c.z], COMP[c.kind]);
  return g;
}

export function createProduct(recipe) {
  const root = new THREE.Group(); root.name = 'product';
  const { w: PW, d: PD, t: PT, code } = recipe.pallet, pcbTop = PT + recipe.pcbT;
  block(root, [PW, PT, PD], [0, PT / 2, 0], matPallet);
  decal(root, 44, 11, [-PW / 2 + 32, PT + 0.06, -PD / 2 + 12], [-Math.PI / 2, 0, 0], code, { color: '#57514b', center: true, bold: true });
  const panel = new THREE.Group(); root.add(panel);
  for (const b of recipe.boards) buildBoard(panel, b, pcbTop);
  for (const r of recipe.rails) block(panel, [r.w, recipe.pcbT, r.d], [r.x, pcbTop - recipe.pcbT / 2, r.z], matRail);
  const conns = {};
  for (const c of recipe.connectors) {
    const T = CONNECTOR_TYPES[c.type];
    // mount：接頭參考框架（後緣中心、PCB 上表面），插頭朝本地 −z；不隨翹起轉動
    const mount = new THREE.Group(); mount.position.set(c.x, pcbTop, c.z); mount.rotation.y = c.rot * D2R; panel.add(mount);
    block(mount, [T.w + 3, 0.2, T.l + 4], [0, PT - pcbTop + 0.1, -T.l / 2], matPocket);                 // 載盤凹槽
    for (let k = 0; k < T.leads; k++) block(mount, [Math.min(0.55, T.leadPitch * 0.8), 0.05, T.leadL - 0.6], [(k - (T.leads - 1) / 2) * T.leadPitch, 0.03, T.leadL / 2], matGold);
    const pivot = buildConnector(T); pivot.position.set(0, -T.sink, -T.l); mount.add(pivot);
    conns[c.id] = { ...c, T, mount, pivot, tilt: 0 };
  }
  const v = new THREE.Vector3();
  function setTilt(id, deg) { const c = conns[id]; c.tilt = deg; c.pivot.rotation.x = -deg * D2R; }
  /** 貼平狀態下的壓點（殼頂、靠銀腳側）世界座標 */
  function pressPoint(id) { const c = conns[id]; return c.mount.localToWorld(v.set(0, c.T.h - c.T.sink, -c.T.l + c.T.pressFromTip).clone()); }
  /** 銀腳與焊墊交界（相機對焦點）世界座標 */
  function leadPoint(id) { return conns[id].mount.localToWorld(v.set(0, 0, 1.5).clone()); }
  /** 插頭指向（世界、水平） */
  function pointing(id) { const r = conns[id].rot * D2R; return new THREE.Vector3(-Math.sin(r), 0, -Math.cos(r)); }
  const gap = id => { const c = conns[id]; return (c.T.l + c.T.leadL) * Math.sin(c.tilt * D2R); };
  return { root, conns, ids: recipe.connectors.map(c => c.id), setTilt, pressPoint, leadPoint, pointing, gap };
}

/** 壓點抬高 h mm 時的翹起角（°） */
export const tiltForLift = (T, h) => Math.asin(Math.min(1, Math.max(0, h / T.pressFromTip))) / D2R;
/** 翹起角對應的壓點抬高量（mm） */
export const liftForTilt = (T, deg) => T.pressFromTip * Math.sin(deg * D2R);
export const gapForTilt = (T, deg) => (T.l + T.leadL) * Math.sin(deg * D2R);
