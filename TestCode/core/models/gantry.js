// 兩軸龍門（X 橫移＋Z 升降）附平行夾爪（參數化）。state：x（沿樑位置）、y（夾爪中心高度）、jaw（0 夾緊～1 張開）。
// Z 軸穿過導向座以 userData.guide／on 標記，core 全場檢查會視為滑動配合。
import * as THREE from 'three';
import { block } from '../geom/shapes.js';
import { MAT } from '../geom/materials.js';
import { foot, motor } from '../geom/hardware.js';

export const meta = {
  id: 'gantry', name: '兩軸龍門＋平行夾爪', category: '搬運',
  params: {
    span: { value: 1200, min: 400, max: 4000, step: 50, unit: 'mm', label: '橫樑跨距' },
    height: { value: 1700, min: 1000, max: 3500, step: 50, unit: 'mm', label: '橫樑底高' },
    offset: { value: 300, min: 150, max: 800, step: 10, unit: 'mm', label: '夾爪伸出（樑到夾爪中心）' },
    stroke: { value: 1000, min: 300, max: 2500, step: 50, unit: 'mm', label: 'Z 軸長' },
    grip: { value: 200, min: 40, max: 600, step: 10, unit: 'mm', label: '夾持寬度' },
  },
  states: {
    x: { value: 0, min: -500, max: 500, unit: 'mm', label: 'X 位置' },
    y: { value: 1200, min: 700, max: 1600, unit: 'mm', label: '夾爪中心高' },
    jaw: { value: 1, min: 0, max: 1, label: '夾爪開度' },
  },
  usage: "import { create as gantry } from '@core/models/gantry.js';\nconst g = gantry({ span: 1500 }); scene.add(g.root); g.set({ x: 200, y: 900, jaw: 0 });",
};

// 原點：跨距中心、地面、樑的正下方；夾爪在 +Z 方向 offset 處
export function create(p = {}) {
  const P = { ...Object.fromEntries(Object.entries(meta.params).map(([k, v]) => [k, v.value])), ...p };
  const root = new THREE.Group(); root.name = 'gantry';
  const H = P.height;
  for (const x of [-P.span / 2 - 190, P.span / 2 + 190]) { block(root, [80, H, 80], [x, H / 2, 0], MAT.steelOrange); foot(root, x, 0, 160); }
  block(root, [P.span + 460, 100, 100], [0, H + 50, 0], MAT.steelOrange);
  const carriage = new THREE.Group(); root.add(carriage);
  block(carriage, [160, 160, 120], [0, H + 50, 110], MAT.steelDark);
  motor(carriage, 0, H + 180, 110, .6);
  // Z 軸導向座：從台車前緣（z 150）伸到 Z 軸外側（offset + 30）
  const bracket = block(carriage, [100, 80, P.offset + 30 - 150], [0, H - 20, (150 + P.offset + 30) / 2], MAT.steelDark);
  bracket.userData.guide = 'gantry-z';
  const zAxis = new THREE.Group(); zAxis.userData.on = 'gantry-z'; zAxis.position.z = P.offset; carriage.add(zAxis);   // 原點＝夾爪中心
  block(zAxis, [50, P.stroke, 50], [0, 75 + P.stroke / 2, 0], MAT.alu);
  block(zAxis, [P.grip + 100, 30, 90], [0, 75, 0], MAT.steelDark);
  const jaws = [-1, 1].map(() => block(zAxis, [20, 120, 80], [0, 0, 0], MAT.yellow));
  return {
    root, params: P,
    set({ x = 0, y = H - 500, jaw = 1 } = {}) {
      carriage.position.x = x; zAxis.position.y = y;
      jaws.forEach((j, k) => { j.position.x = (k ? 1 : -1) * (P.grip / 2 + 10 + 50 * jaw); });
    },
  };
}
