// 200 L 閉口 HDPE 桶：本體（L 環、兩道滾箍）、2" 與 3/4" 螺塞、識別標籤、桶內液量。共用模型，原用於 ChemicalTankWashing。
// 局部座標：原點在桶中心，+Y 為桶頂；2" 螺塞在 +X、3/4" 在 −X。
import * as THREE from 'three';
import { MAT, HAS_DOM, box } from '../geom/parts.js';

// 規格（mm、kg）：R 本體半徑、envelopeR 含滾箍外徑、H 總高、bungR 螺塞距中心、big／small 為 2" 與 3/4" 螺塞
export const DRUM = { R: 292.5, envelopeR: 298, H: 935, bungR: 200, big: { r: 36, h: 24, hole: 27 }, small: { r: 18, h: 18, hole: 12 }, kg: 8.5 };

const HEAD = DRUM.H / 2 - 12.5;          // 桶頂板（凹在 L 環內）
const NECK = 8;
const profile = [
  [0, -HEAD], [275, -HEAD], [283, -467.5], [293, -467.5], [297, -460], [297, -430], [292.5, -415],
  [292.5, -195], [298, -180], [298, -140], [292.5, -125],
  [292.5, 125], [298, 140], [298, 180], [292.5, 195],
  [292.5, 415], [297, 430], [297, 460], [293, 467.5], [283, 467.5], [275, HEAD],
].map(([r, y]) => new THREE.Vector2(r, y));
export const DRUM_GEO = new THREE.LatheGeometry(profile, 44);
// 桶頂真的開雙孔，剖視時可見噴槍穿過開口；頸圈也保留中空。
const headShape = new THREE.Shape(); headShape.absarc(0, 0, 275, 0, Math.PI * 2, false);
for (const [x, r] of [[DRUM.bungR, DRUM.big.hole], [-DRUM.bungR, DRUM.small.hole]]) {
  const hole = new THREE.Path(); hole.absarc(x, 0, r, 0, Math.PI * 2, true); headShape.holes.push(hole);
}
const HEAD_GEO = new THREE.ShapeGeometry(headShape, 36); HEAD_GEO.rotateX(-Math.PI / 2); HEAD_GEO.translate(0, HEAD, 0);
const BIG_NECK = new THREE.CylinderGeometry(DRUM.big.r + 4, DRUM.big.r + 6, NECK, 24, 1, true);
const SMALL_NECK = new THREE.CylinderGeometry(DRUM.small.r + 4, DRUM.small.r + 6, NECK, 18, 1, true);
export const BIG_CAP = new THREE.CylinderGeometry(DRUM.big.r, DRUM.big.r, DRUM.big.h * .5, 24);
export const SMALL_CAP = new THREE.CylinderGeometry(DRUM.small.r, DRUM.small.r, DRUM.small.h * .6, 18);
const HOLE_BIG = new THREE.CircleGeometry(DRUM.big.hole, 20), HOLE_SMALL = new THREE.CircleGeometry(DRUM.small.hole, 16);
const LABEL_W = 100, LABEL_H = 150, LABEL_ANG = LABEL_W / DRUM.R;
const LABEL_GEO = new THREE.CylinderGeometry(DRUM.R + 1.6, DRUM.R + 1.6, LABEL_H, 10, 1, true, -LABEL_ANG / 2, LABEL_ANG);
const WATER_GEO = new THREE.CylinderGeometry(284, 284, 1, 36);

export const CAP_Y = HEAD + NECK;          // 螺塞座頂面（桶中心起算）
export const BUNG = { big: new THREE.Vector3(DRUM.bungR, CAP_Y, 0), small: new THREE.Vector3(-DRUM.bungR, CAP_Y, 0) };

// 簡化的 QR 圖樣＋桶號，用同一個種子產生，讓同一桶在相機畫面上看起來一致
function labelTexture(id) {
  if (!HAS_DOM) return null;
  const c = document.createElement('canvas'); c.width = 256; c.height = 384; const g = c.getContext('2d');
  g.fillStyle = '#fbfbf7'; g.fillRect(0, 0, 256, 384);
  g.fillStyle = '#111'; g.font = 'bold 30px "Noto Sans TC","Microsoft JhengHei",sans-serif'; g.textAlign = 'center';
  g.fillText('CTW 洗桶', 128, 40);
  let seed = [...id].reduce((s, ch) => s * 31 + ch.charCodeAt(0), 7) >>> 0;
  const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32;
  const N = 21, s = 8, x0 = 44, y0 = 64;
  for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
    const finder = (a, b) => i >= a && i < a + 7 && j >= b && j < b + 7;
    let on = rnd() > .5;
    for (const [a, b] of [[0, 0], [0, 14], [14, 0]]) if (finder(a, b)) { const u = i - a, v = j - b; on = u === 0 || u === 6 || v === 0 || v === 6 || (u > 1 && u < 5 && v > 1 && v < 5); }
    if (on) g.fillRect(x0 + i * s, y0 + j * s, s, s);
  }
  g.font = 'bold 28px Consolas,monospace'; g.fillText(id, 128, 270);
  g.font = '22px "Noto Sans TC","Microsoft JhengHei",sans-serif'; g.fillText('200L HDPE · 酸鹼', 128, 310); g.fillText('待清洗', 128, 344);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}

export function createDrum(id) {
  const root = new THREE.Group(); root.name = 'drum ' + id;
  const bodyMat = MAT.drum.clone();
  const body = new THREE.Mesh(DRUM_GEO, bodyMat); body.castShadow = body.receiveShadow = true; root.add(body);
  const head = new THREE.Mesh(HEAD_GEO, bodyMat); head.castShadow = head.receiveShadow = true; root.add(head);
  const parts = {};
  for (const [key, neckGeo, capGeo, holeGeo, x] of [['big', BIG_NECK, BIG_CAP, HOLE_BIG, DRUM.bungR], ['small', SMALL_NECK, SMALL_CAP, HOLE_SMALL, -DRUM.bungR]]) {
    const neck = new THREE.Mesh(neckGeo, bodyMat); neck.position.set(x, HEAD + NECK / 2, 0); root.add(neck);
    const lip = new THREE.Mesh(new THREE.RingGeometry(key === 'big' ? DRUM.big.hole : DRUM.small.hole, key === 'big' ? DRUM.big.r + 4 : DRUM.small.r + 4, 28), bodyMat);
    lip.rotation.x = -Math.PI / 2; lip.position.set(x, CAP_Y, 0); root.add(lip);
    const hole = new THREE.Mesh(holeGeo, MAT.hole); hole.rotation.x = -Math.PI / 2; hole.position.set(x, CAP_Y + .5, 0); hole.visible = false; root.add(hole);
    const cap = new THREE.Mesh(capGeo, MAT.cap); cap.castShadow = true; cap.position.set(x, CAP_Y + capGeo.parameters.height / 2, 0); root.add(cap);
    for (const side of [-1, 1]) box(cap, key === 'big' ? 48 : 23, 5, 5, MAT.cap, 0, capGeo.parameters.height / 2 + 2, side * (key === 'big' ? 9 : 5));
    parts[key] = { cap, hole };
  }
  const tex = labelTexture(id);
  const label = new THREE.Mesh(LABEL_GEO, new THREE.MeshStandardMaterial({ map: tex, color: tex ? 0xffffff : 0xf4f4ee, roughness: .7, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2 }));
  const labelPivot = new THREE.Group(); labelPivot.add(label); label.position.y = 20; labelPivot.visible = false; root.add(labelPivot);
  const water = new THREE.Mesh(WATER_GEO, MAT.water); water.visible = false; water.renderOrder = 3; root.add(water);
  let xray = false, liters = 0;
  function updateWater() {
    const h = liters * 1e6 / (Math.PI * 284 * 284);
    water.visible = xray && h > .5; water.scale.y = Math.max(h, .01); water.position.y = -HEAD + h / 2;
  }
  return {
    id, root, label: labelPivot, tex,
    setCaps(big, small) { parts.big.cap.visible = big; parts.big.hole.visible = !big; parts.small.cap.visible = small; parts.small.hole.visible = !small; },
    // angle：標籤法向在桶局部 XZ 平面的方位（0 = +Z）
    setLabel(on, angle = 0) { labelPivot.visible = on; labelPivot.rotation.y = angle; },
    setWater(l) { liters = l; updateWater(); },
    setXray(on) { xray = on; bodyMat.transparent = on; bodyMat.opacity = on ? .32 : 1; bodyMat.depthWrite = !on; bodyMat.needsUpdate = true; updateWater(); },
    // 世界座標中的螺塞口位置
    bungWorld(kind, out = new THREE.Vector3()) { return out.copy(BUNG[kind]).applyMatrix4(root.matrixWorld); },
    capMesh: k => parts[k].cap,
  };
}

// 倉儲架上的靜態桶槽：用 InstancedMesh 降低繪製成本
export function createDrumInstances(count) {
  const group = new THREE.Group();
  const body = new THREE.InstancedMesh(DRUM_GEO, MAT.drum, count);
  const head = new THREE.InstancedMesh(HEAD_GEO, MAT.drum, count);
  const big = new THREE.InstancedMesh(BIG_CAP, MAT.cap, count), small = new THREE.InstancedMesh(SMALL_CAP, MAT.cap, count);
  for (const m of [body, head, big, small]) { m.castShadow = true; m.receiveShadow = true; group.add(m); }
  const off = new THREE.Matrix4(), tmp = new THREE.Matrix4();
  let n = 0;
  return {
    group,
    add(matrix) {
      body.setMatrixAt(n, matrix);
      head.setMatrixAt(n, matrix);
      big.setMatrixAt(n, tmp.multiplyMatrices(matrix, off.makeTranslation(DRUM.bungR, CAP_Y + DRUM.big.h * .25, 0)));
      small.setMatrixAt(n, tmp.multiplyMatrices(matrix, off.makeTranslation(-DRUM.bungR, CAP_Y + DRUM.small.h * .3, 0)));
      n++;
    },
    done() { for (const m of [body, head, big, small]) { m.count = n; m.instanceMatrix.needsUpdate = true; m.computeBoundingSphere(); } },
  };
}

// 夾桶爪：兩片弧形 PU 爪由局部 ±X 側夾住桶身；局部 +Y 為桶軸、原點在桶中心。
// armTo：手臂夾爪的連桿往局部 −Z 接回本體（龍門夾爪由上方吊桿連接，不需要）。
export function drumJaws(parent, armTo = null, stroke = 130) {
  const jaws = [];
  for (const s of [-1, 1]) {
    const g = new THREE.Group(); parent.add(g);
    const a0 = s > 0 ? Math.PI / 2 - .7 : -Math.PI / 2 - .7;
    const pad = new THREE.Mesh(new THREE.CylinderGeometry(DRUM.R + 12, DRUM.R + 12, 420, 20, 1, true, a0, 1.4), MAT.pu);
    pad.material.side = THREE.DoubleSide; pad.castShadow = true; g.add(pad);
    const back = new THREE.Mesh(new THREE.CylinderGeometry(DRUM.R + 32, DRUM.R + 32, 440, 20, 1, true, a0 - .02, 1.44), MAT.steel);
    back.castShadow = true; g.add(back);
    if (armTo !== null) for (const y of [-150, 150]) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(40, 70, -armTo), MAT.steel); arm.castShadow = true;
      arm.position.set(s * (DRUM.R + 40), y, armTo / 2); g.add(arm);
    }
    jaws.push({ g, s });
  }
  return { set(v) { for (const { g, s } of jaws) g.position.x = s * (1 - v) * stroke; } };
}

// ---------------------------------------------------------------- 模型目錄
export const meta = {
  id: 'drum-200l', name: '200 L 閉口 HDPE 桶', category: '工件', source: 'ChemicalTankWashing',
  params: {},
  states: {
    liters: { value: 0, min: 0, max: 200, unit: 'L', label: '桶內液量（透視時可見）' },
    label: { value: 0, min: 0, max: 360, unit: '°', label: '標籤方位' },
  },
  usage: "import { createDrum, DRUM, drumJaws } from '@core/models/drum-200l.js';\nconst d = createDrum('CTW-0001'); scene.add(d.root);\nd.setCaps(true, true); d.setLabel(true, angle); d.setWater(liters); d.setXray(on);",
};
export function create() {
  const d = createDrum('CTW-0001'); d.root.position.y = DRUM.H / 2;
  const root = new THREE.Group(); root.name = 'drum-200l'; root.add(d.root);
  d.setXray(true);
  return { root, set({ liters = 0, label = 0 } = {}) { d.setWater(liters); d.setLabel(true, label * Math.PI / 180); } };
}
