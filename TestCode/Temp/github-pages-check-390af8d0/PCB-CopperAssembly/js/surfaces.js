// Offline deterministic copper finish; visual reference, not inspection imagery.
import * as THREE from 'three';
const size = 512, colour = new Uint8Array(size * size * 4), relief = new Uint8Array(colour.length);
let seed = 73021;
const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
const rows = Array.from({ length: size }, random);
for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
  const i = (y * size + x) * 4, a = x / size * Math.PI * 2, b = y / size * Math.PI * 2;
  const stain = Math.sin(a + Math.sin(b * 2)) * Math.cos(b - a * 2);
  const grain = (rows[y] - .5) * 11 + (random() - .5) * 5;
  colour[i] = 192 + stain * 5 + grain; colour[i + 1] = 125 + stain * 4 + grain;
  colour[i + 2] = 96 + stain * 4 + grain; colour[i + 3] = 255;
  const v = 155 + grain * 1.1 + stain * 3;
  relief[i] = relief[i + 1] = relief[i + 2] = v; relief[i + 3] = 255;
}
for (let s = 0; s < 95; s++) {
  const x0 = random() * size, y0 = random() * size, len = 12 + random() * 100, slope = (random() - .5) * .22;
  for (let d = 0; d < len; d++) {
    const x = Math.floor(x0 + d) % size, y = Math.floor(y0 + d * slope + size) % size, i = (y * size + x) * 4;
    const fade = Math.sin(d / len * Math.PI) * 12;
    for (let c = 0; c < 3; c++) { colour[i + c] += fade; relief[i + c] -= fade; }
  }
}
function texture(data, srgb = false) {
  const t = new THREE.DataTexture(data, size, size);
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.magFilter = THREE.LinearFilter;
  t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true; t.anisotropy = 8;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.needsUpdate = true; return t;
}
const map = texture(colour, true), bumpMap = texture(relief);
export const matCopper = new THREE.MeshStandardMaterial({ map, bumpMap, bumpScale: .004, roughnessMap: bumpMap, roughness: .64, metalness: .88 });
export const matCoin = new THREE.MeshStandardMaterial({ map, bumpMap, bumpScale: .009, color: 0xdad1c7, roughnessMap: bumpMap, roughness: .77, metalness: .9 });
export const matCoinEdge = new THREE.MeshStandardMaterial({ color: 0xbe8a65, roughness: .36, metalness: .88 });
export const matCoinBack = new THREE.MeshStandardMaterial({ map, bumpMap, bumpScale: .016, color: 0x947b6b, roughness: .64, metalness: .8 });
export function surfaceUV(geometry, mmPerTile) {
  const p = geometry.attributes.position, uv = geometry.attributes.uv;
  for (let i = 0; i < p.count; i++) uv.setXY(i, p.getX(i) / mmPerTile, p.getZ(i) / mmPerTile);
  uv.needsUpdate = true; return geometry;
}
