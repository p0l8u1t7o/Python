// 工業設備共用細節；毫米制，固定種子貼圖，離線與 Node 驗證皆可用。
import * as THREE from 'three';
import { block, cylinder, plate, rod } from './shapes.js';
import { MAT } from './materials.js';

const housingCache = new Map();
export function housing(parent, w, h, d, material, x = 0, y = 0, z = 0, radius = 12) {
  // 有倒角的鈑金／鑄件外殼，邊緣在環境光下形成高光，而非鋒利方塊。
  const r = Math.min(radius, w / 8, h / 8, d / 8), key = [w,h,d,r].join(',');
  let geometry = housingCache.get(key);
  if (!geometry) {
    const s = new THREE.Shape(), a = w / 2 - r, b = h / 2 - r;
    s.moveTo(-a,-b); s.lineTo(a,-b); s.lineTo(a,b); s.lineTo(-a,b); s.closePath();
    geometry = new THREE.ExtrudeGeometry(s, {depth:d-2*r,bevelEnabled:true,bevelThickness:r,bevelSize:r,bevelSegments:3,steps:1});
    geometry.translate(0,0,-d/2+r); housingCache.set(key,geometry);
  }
  const mesh = new THREE.Mesh(geometry, material); mesh.position.set(x,y,z); mesh.castShadow = mesh.receiveShadow = true; parent.add(mesh); return mesh;
}

export function surfaceTexture(kind) {
  const n = 128, data = new Uint8Array(n * n * 4);
  let seed = 417;
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    seed = (1664525 * seed + 1013904223) >>> 0;
    const noise = seed / 4294967296;
    const v = kind === 'brush' ? 155 + 40 * Math.sin(y * 2.7) + noise * 30 : 160 + noise * 55;
    const i = (y * n + x) * 4; data.set([v, v, v, 255], i);
  }
  const t = new THREE.DataTexture(data, n, n); t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearMipmapLinearFilter;
  t.generateMipmaps = true; t.needsUpdate = true; return t;
}

export function finishMaterials(renderer) {
  const brushed = surfaceTexture('brush'), grain = surfaceTexture('grain');
  brushed.repeat.set(2, 5); grain.repeat.set(8, 8);
  for (const t of [brushed, grain]) t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  for (const key of ['steel', 'alu', 'roller']) { MAT[key].roughnessMap = brushed; MAT[key].bumpMap = brushed; MAT[key].bumpScale = .18; MAT[key].roughness = .44; }
  for (const key of ['drum', 'drumLid', 'pallet', 'palletEmpty', 'pu', 'floor']) {
    MAT[key].roughnessMap = grain; MAT[key].bumpMap = grain; MAT[key].bumpScale = key === 'floor' ? .8 : .12;
  }
  const floorGrain = grain.clone(); floorGrain.repeat.set(1 / 500, 1 / 500); floorGrain.needsUpdate = true;
  MAT.floor.bumpMap = MAT.floor.roughnessMap = floorGrain;
  for (const m of Object.values(MAT)) if ('envMapIntensity' in m) m.envMapIntensity = .8;
  // 網片 alphaTest：真的看得穿網孔，也能投射網格陰影，避免整片透明板排序。
  const n = 64, data = new Uint8Array(n * n * 4);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) data.set([255, 255, 255, x < 3 || y < 3 ? 255 : 0], (y * n + x) * 4);
  const mesh = new THREE.DataTexture(data, n, n); mesh.wrapS = mesh.wrapT = THREE.RepeatWrapping; mesh.repeat.set(22, 30);
  mesh.generateMipmaps = true; mesh.minFilter = THREE.LinearMipmapLinearFilter; mesh.magFilter = THREE.LinearFilter; mesh.anisotropy = 8; mesh.needsUpdate = true;
  Object.assign(MAT.mesh, { map: mesh, transparent: false, opacity: 1, alphaTest: .4, alphaToCoverage: true, depthWrite: true });
}

// 合併緊固件，避免每個螺栓增加一次 draw call。
export function bolts(parent, positions, r = 9, axis = 'y') {
  const mesh = new THREE.InstancedMesh(new THREE.CylinderGeometry(r, r, r * .8, 6), MAT.steel, positions.length);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(...(axis === 'x' ? [1, 0, 0] : axis === 'z' ? [0, 0, 1] : [0, 1, 0])));
  positions.forEach((p, i) => mesh.setMatrixAt(i, m.compose(new THREE.Vector3(...p), q, new THREE.Vector3(1, 1, 1))));
  mesh.castShadow = mesh.receiveShadow = true; parent.add(mesh); return mesh;
}
export function foot(parent, x, z, size = 160) {
  block(parent, [size, 16, size], [x, 8, z], MAT.steelDark);
  bolts(parent, [-1, 1].flatMap(a => [-1, 1].map(b => [x + a * size * .32, 22, z + b * size * .32])), 10);
}
export function motor(parent, x, y, z, scale = 1, yaw = 0) {
  const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = yaw; g.scale.setScalar(scale); parent.add(g);
  housing(g, 180, 140, 160, MAT.steelDark, 0, -10, -90, 10);
  cylinder(g, 75, 240, [0, 0, 100], MAT.steelBlue, 'z', 28);
  for (let i = 0; i < 8; i++) cylinder(g, 80, 7, [0, 0, i * 23 + 12], MAT.steelBlue, 'z', 20);
  cylinder(g, 76, 30, [0, 0, 238], MAT.black, 'z', 28);
  block(g, [70, 40, 75], [0, 88, 100], MAT.black);
  return g;
}
export function flange(parent, x, y, z, r = 45, axis = 'y') {
  cylinder(parent, r, 18, [x, y, z], MAT.steel, axis, 28);
  const pts = Array.from({ length: 6 }, (_, i) => { const a = i * Math.PI / 3, u = Math.cos(a) * r * .75, v = Math.sin(a) * r * .75; return axis === 'x' ? [x + 12, y + u, z + v] : axis === 'z' ? [x + u, y + v, z + 12] : [x + u, y + 12, z + v]; });
  bolts(parent, pts, 5, axis);
}
export function gauge(parent, x, y, z) {
  cylinder(parent, 48, 26, [x, y, z], MAT.steel, 'z', 28); cylinder(parent, 41, 2, [x, y, z - 14], MAT.cap, 'z', 28);
  rod(parent, [x, y, z - 17], [x - 23, y + 22, z - 17], 2.5, MAT.red, 6);
}
export function sensor(parent, x, y, z, yaw = 0) {
  const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = yaw; parent.add(g);
  block(g, [36, 58, 32], [0, 0, 0], MAT.black); cylinder(g, 10, 3, [0, 0, -17], MAT.red, 'z', 12);
  block(g, [50, 5, 50], [0, -32, 5], MAT.steel); return g;
}
export function cabinetDetails(parent, x0, z0, x1, z1, h) {
  const x = (x0 + x1) / 2, w = x1 - x0;
  block(parent, [w - 24, h - 70, 3], [x, h / 2, z0 - 2], MAT.alu);
  block(parent, [12, 130, 18], [x1 - 65, h * .55, z0 - 12], MAT.black);
  for (const y of [h * .25, h * .75]) block(parent, [22, 65, 14], [x0 + 32, y, z0 - 9], MAT.steelDark);
  for (let k = 0; k < 8; k++) block(parent, [w * .45, 6, 4], [x, 130 + k * 17, z0 - 5], MAT.black);
  plate(parent, ['⚡ 400 V'], 150, 90, [x1 - 120, h - 350, z0 - 7], Math.PI, { bg: '#f4c542', fg: '#161a20' });
}
