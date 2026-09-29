// Presentation-only finishes. Seeded textures are stable across frames/reloads.
import * as THREE from 'three';

const cache = new Map();
export function surfaceTexture(kind) {
  if (cache.has(kind)) return cache.get(kind);
  const size = 256, pixels = new Uint8Array(size * size * 4);
  let seed = 2917;
  const random = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const stripes = Array.from({ length: size }, () => random());
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const n = random();
    const value = kind === 'stone' ? 115 + n * 95 + (n > .94 ? 30 : 0)
      : kind === 'brushed' ? 204 + stripes[x] * 20 + n * 7
        : 221 + n * 22;
    const i = (y * size + x) * 4;
    pixels[i] = pixels[i + 1] = pixels[i + 2] = value; pixels[i + 3] = 255;
  }
  const map = new THREE.DataTexture(pixels, size, size);
  map.wrapS = map.wrapT = THREE.RepeatWrapping;
  map.repeat.set(kind === 'stone' ? 9 : 3, kind === 'stone' ? 7 : 3);
  map.magFilter = THREE.LinearFilter; map.minFilter = THREE.LinearMipmapLinearFilter;
  map.generateMipmaps = true; map.anisotropy = 4; map.needsUpdate = true;
  cache.set(kind, map); return map;
}

export function applyFinishes(materials) {
  for (const key of ['frame', 'plate', 'steel', 'anodized']) {
    const material = materials[key];
    material.roughnessMap = surfaceTexture('brushed');
    material.roughness = Math.max(material.roughness, .34);
    material.envMapIntensity = .8;
  }
  Object.assign(materials.granite, {
    map: surfaceTexture('stone'), roughnessMap: surfaceTexture('stone'),
    roughness: .58, metalness: 0, bumpMap: surfaceTexture('stone'), bumpScale: .08,
  });
  materials.granite.color.setHex(0x393c3d);
  for (const key of ['cabinet', 'tray', 'axis', 'motor']) {
    materials[key].roughnessMap = surfaceTexture('powder');
    materials[key].bumpMap = surfaceTexture('powder'); materials[key].bumpScale = .035;
  }
  materials.cabinet.color.setHex(0xb7c1c5);
  materials.cabinet.metalness = .12;
  materials.glass.color.setHex(0xd4e9e7);
  materials.glass.opacity = .065;
  materials.glass.roughness = .16;
}

// Flat graphic finish on an existing cabinet door; no functional geometry.
export function cabinetDoorMaterial() {
  const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 1024;
  const g = canvas.getContext('2d');
  g.fillStyle = '#aeb9be'; g.fillRect(0, 0, 512, 1024);
  g.strokeStyle = '#d5dde0'; g.lineWidth = 3; g.strokeRect(5, 5, 502, 1014);
  g.fillStyle = '#586771';
  for (let y = 780; y < 912; y += 16) {
    g.fillRect(100, y, 312, 5); g.fillStyle = '#d0d9dc'; g.fillRect(100, y + 5, 312, 2); g.fillStyle = '#586771';
  }
  g.fillStyle = '#263540'; g.fillRect(40, 70, 235, 64);
  g.fillStyle = '#dfe8ec'; g.font = '18px sans-serif'; g.fillText('WORKPIECE', 54, 96);
  g.font = '12px sans-serif'; g.fillText('MEASUREMENT  /  VISUALIZATION', 54, 119);
  const map = new THREE.CanvasTexture(canvas); map.colorSpace = THREE.SRGBColorSpace; map.anisotropy = 4;
  return new THREE.MeshStandardMaterial({ map, metalness: .12, roughness: .57,
    roughnessMap: surfaceTexture('powder'), bumpMap: surfaceTexture('powder'), bumpScale: .025 });
}

export function overviewFrame(root, camera) {
  root.updateMatrixWorld(true);
  const bounds = new THREE.Box3().setFromObject(root);
  const center = bounds.getCenter(new THREE.Vector3()), size = bounds.getSize(new THREE.Vector3());
  const direction = new THREE.Vector3(-1.05, .65, 1.4).normalize();
  const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), direction).normalize();
  const up = new THREE.Vector3().crossVectors(direction, right).normalize();
  const tan = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  let distance = 0;
  for (const x of [-.5, .5]) for (const y of [-.5, .5]) for (const z of [-.5, .5]) {
    const p = new THREE.Vector3(size.x * x, size.y * y, size.z * z);
    distance = Math.max(distance, p.dot(direction) + Math.max(Math.abs(p.dot(up)) / tan, Math.abs(p.dot(right)) / (tan * camera.aspect)) * 1.14);
  }
  return [center.clone().addScaledVector(direction, distance).toArray(), center.toArray()];
}
