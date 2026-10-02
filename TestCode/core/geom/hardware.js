// 工業設備共用細節；毫米制，固定種子貼圖，離線與 Node 驗證皆可用。
import * as THREE from 'three';
import { MAT, box, cyl, rod, plate } from './parts.js';

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
  box(parent, size, 16, size, MAT.steelDark, x, 8, z);
  bolts(parent, [-1, 1].flatMap(a => [-1, 1].map(b => [x + a * size * .32, 22, z + b * size * .32])), 10);
}
export function motor(parent, x, y, z, scale = 1, yaw = 0) {
  const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = yaw; g.scale.setScalar(scale); parent.add(g);
  housing(g, 180, 140, 160, MAT.steelDark, 0, -10, -90, 10);
  cyl(g, 75, 240, MAT.steelBlue, 0, 0, 100, 'z');
  for (let i = 0; i < 8; i++) cyl(g, 80, 7, MAT.steelBlue, 0, 0, i * 23 + 12, 'z', 20);
  cyl(g, 76, 30, MAT.black, 0, 0, 238, 'z');
  box(g, 70, 40, 75, MAT.black, 0, 88, 100);
  return g;
}
export function flange(parent, x, y, z, r = 45, axis = 'y') {
  cyl(parent, r, 18, MAT.steel, x, y, z, axis);
  const pts = Array.from({ length: 6 }, (_, i) => { const a = i * Math.PI / 3, u = Math.cos(a) * r * .75, v = Math.sin(a) * r * .75; return axis === 'x' ? [x + 12, y + u, z + v] : axis === 'z' ? [x + u, y + v, z + 12] : [x + u, y + 12, z + v]; });
  bolts(parent, pts, 5, axis);
}
export function gauge(parent, x, y, z) {
  cyl(parent, 48, 26, MAT.steel, x, y, z, 'z'); cyl(parent, 41, 2, MAT.cap, x, y, z - 14, 'z');
  rod(parent, [x, y, z - 17], [x - 23, y + 22, z - 17], 2.5, MAT.red, 6);
}
export function sensor(parent, x, y, z, yaw = 0) {
  const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = yaw; parent.add(g);
  box(g, 36, 58, 32, MAT.black); cyl(g, 10, 3, MAT.red, 0, 0, -17, 'z', 12);
  box(g, 50, 5, 50, MAT.steel, 0, -32, 5); return g;
}
export function cabinetDetails(parent, x0, z0, x1, z1, h) {
  const x = (x0 + x1) / 2, w = x1 - x0;
  box(parent, w - 24, h - 70, 3, MAT.alu, x, h / 2, z0 - 2);
  box(parent, 12, 130, 18, MAT.black, x1 - 65, h * .55, z0 - 12);
  for (const y of [h * .25, h * .75]) box(parent, 22, 65, 14, MAT.steelDark, x0 + 32, y, z0 - 9);
  for (let k = 0; k < 8; k++) box(parent, w * .45, 6, 4, MAT.black, x, 130 + k * 17, z0 - 5);
  plate(parent, ['⚡ 400 V'], 150, 90, [x1 - 120, h - 350, z0 - 7], Math.PI, { bg: '#f4c542', fg: '#161a20' });
}
