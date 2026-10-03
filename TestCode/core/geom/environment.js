// 場景地面：深色地坪＋格線（多數工作站共用的樣子）。放在專案自己的場景樹裡（project.js 建），檢查與截圖都看得到。
//
//   import { floor } from '@core/geom/environment.js';
//   floor(g, { size: [9000, 6000], cell: 200 });          // 9 × 6 m 地坪、200 mm 格
//
// grid：格線為正方形（邊長 gridSize，預設取 size 較長邊），中心與地坪相同；false 不畫格線
import * as THREE from 'three';

export const FLOOR = { color: 0x1b2027, roughness: .95, grid: [0x2c3540, 0x222a33] };

export function floor(parent, { size = [9000, 6000], center = [0, 0], cell = 200, color = FLOOR.color, roughness = FLOOR.roughness, grid = FLOOR.grid, gridSize = Math.max(size[0], size[1]), gridY = .5, material = null } = {}) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size[0], size[1]), material || new THREE.MeshStandardMaterial({ color, roughness }));
  mesh.rotation.x = -Math.PI / 2; mesh.position.set(center[0], 0, center[1]); mesh.receiveShadow = true; mesh.name = 'floor'; parent.add(mesh);
  let lines = null;
  if (grid) {
    lines = new THREE.GridHelper(gridSize, Math.round(gridSize / cell), grid[0], grid[1]);
    lines.position.set(center[0], gridY, center[1]); lines.name = 'floor-grid'; parent.add(lines);
  }
  return { mesh, grid: lines };
}
