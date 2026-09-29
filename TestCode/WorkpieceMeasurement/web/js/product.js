// 工件：依剖面車出的薄壁鋁殼（實際尺寸）
import * as THREE from 'three';
import { profile } from './spec.js';

let drawTexture;
// 引伸拉紋：細密的軸向條紋，讓旋轉看得出來
function drawLines() {
  if (drawTexture) return drawTexture;
  const c = document.createElement('canvas'); c.width = 512; c.height = 64; const g = c.getContext('2d');
  g.fillStyle = '#c9ced4'; g.fillRect(0, 0, 512, 64);
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let x = 0; x < 512; x++) { const v = 190 + Math.floor(rnd() * 50); g.fillStyle = `rgb(${v},${v + 3},${v + 8})`; g.fillRect(x, 0, 1, 64); }
  g.fillStyle = '#5d6c7c'; g.fillRect(0, 0, 5, 64);                       // 角度基準線（示意）
  drawTexture = new THREE.CanvasTexture(c); drawTexture.wrapS = THREE.RepeatWrapping; drawTexture.colorSpace = THREE.SRGBColorSpace; drawTexture.anisotropy = 8;
  return drawTexture;
}
const geoCache = new Map();
export function partGeometry(s) {
  if (!geoCache.has(s.id)) geoCache.set(s.id, new THREE.LatheGeometry(profile(s).map(([r, y]) => new THREE.Vector2(Math.max(r, 1e-4), y)), 72));
  return geoCache.get(s.id);
}
export function partMaterial(tint) {
  const m = new THREE.MeshStandardMaterial({ color: tint || 0xffffff, metalness: 0.85, roughness: 0.34, side: THREE.DoubleSide });
  if (typeof document !== 'undefined') m.map = drawLines();
  return m;
}
export function createPart(s, tint) {
  const mesh = new THREE.Mesh(partGeometry(s), partMaterial(tint)); mesh.castShadow = mesh.receiveShadow = true; return mesh;
}
