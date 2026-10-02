// 滾筒輸送線（參數化）：長度、寬度、高度、滾筒間距；state.s 為滾筒轉動距離（mm），用來表現輸送中。
import * as THREE from 'three';
import { MAT, box, cyl } from '../geom/parts.js';
import { foot } from '../geom/hardware.js';

export const meta = {
  id: 'conveyor', name: '滾筒輸送線', category: '輸送',
  params: {
    length: { value: 2400, min: 600, max: 8000, step: 100, unit: 'mm', label: '長度' },
    width: { value: 500, min: 200, max: 1200, step: 10, unit: 'mm', label: '滾筒長' },
    height: { value: 800, min: 300, max: 1200, step: 10, unit: 'mm', label: '輸送面高' },
    pitch: { value: 120, min: 60, max: 400, step: 10, unit: 'mm', label: '滾筒間距' },
    roller: { value: 30, min: 15, max: 60, step: 1, unit: 'mm', label: '滾筒半徑' },
  },
  states: { s: { value: 0, min: 0, max: 2000, unit: 'mm', label: '輸送距離' } },
  usage: "import { create as conveyor } from '@core/models/conveyor.js';\nconst c = conveyor({ length: 3000 }); scene.add(c.root); c.set({ s: 500 });",
};

// 原點：輸送線中心、地面；沿 +X 輸送；頂面（滾筒頂）高度 = height
export function create(p = {}) {
  const P = { ...Object.fromEntries(Object.entries(meta.params).map(([k, v]) => [k, v.value])), ...p };
  const root = new THREE.Group(); root.name = 'conveyor';
  const top = P.height, frameH = 150, side = P.width / 2 + 25;
  for (const s of [-1, 1]) box(root, P.length, frameH, 50, MAT.steel, 0, top - P.roller - frameH / 2 + 20, s * side);
  const legs = Math.max(2, Math.ceil(P.length / 1500) + 1);
  for (let i = 0; i < legs; i++) {
    const x = -P.length / 2 + 80 + i * (P.length - 160) / (legs - 1);
    for (const s of [-1, 1]) { const h = top - P.roller - frameH + 20; box(root, 60, h, 60, MAT.steelDark, x, h / 2, s * side); foot(root, x, s * side, 120); }
  }
  const rollers = [];
  for (let x = -P.length / 2 + P.pitch / 2; x <= P.length / 2 - P.pitch / 2 + 1e-6; x += P.pitch) {
    const r = cyl(root, P.roller, P.width, MAT.roller, x, top - P.roller, 0, 'z', 20); rollers.push(r);
  }
  return {
    root, params: P, top,
    set({ s = 0 } = {}) { for (const r of rollers) r.rotation.y = -s / P.roller; },
  };
}
