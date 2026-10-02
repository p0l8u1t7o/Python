// 專案介面：網頁（main.js）與 core 統一檢查共用。規格見 core/README.md「專案介面」。
// 範例：輸送帶把工件送到取料位，龍門 Z 軸下降夾取，移到出料台放下。
import * as THREE from 'three';
import { MAT, box, cyl, plate } from '@core/geom/parts.js';
import { foot, motor, sensor } from '@core/geom/hardware.js';
import { createTimeline } from '@core/anim/track.js';

// ---------------------------------------------------------------- 配置（單位 mm；X 往東、Y 往上、Z 往南）
export const LAYOUT = {
  conveyor: { x0: -1400, x1: 200, z: 0, top: 800, width: 360 },
  pick: { x: 0, z: 0 },
  place: { x: 700, z: 0, top: 800 },
  gantry: { y: 1700, x0: -100, x1: 800, safeY: 1250 },
  part: [200, 120, 160],                      // 工件 長×高×寬
};

export function createProject({ scene }) {
  const L = LAYOUT, c = L.conveyor, [pl, ph, pw] = L.part;

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(4000, 3000), MAT.floor); floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; floor.name = 'floor'; scene.add(floor);

  // ---- 輸送帶
  const conveyor = new THREE.Group(); conveyor.name = 'conveyor'; scene.add(conveyor);
  box(conveyor, c.x1 - c.x0, 40, c.width, MAT.alu, (c.x0 + c.x1) / 2, c.top - 20, c.z);
  for (const x of [c.x0 + 80, c.x1 - 80]) for (const s of [-1, 1]) { box(conveyor, 50, c.top - 40, 50, MAT.steelDark, x, (c.top - 40) / 2, c.z + s * (c.width / 2 - 40)); foot(conveyor, x, c.z + s * (c.width / 2 - 40), 110); }
  sensor(conveyor, L.pick.x + 140, c.top + 34, c.z - c.width / 2 - 20);         // 支架底面高於輸送面 1.5 mm，不共面

  // ---- 出料台
  const table = new THREE.Group(); table.name = 'table'; scene.add(table);
  box(table, 400, L.place.top, 400, MAT.steelBlue, L.place.x, L.place.top / 2, L.place.z);

  // ---- 龍門（X 樑＋Z 軸＋夾爪）
  const gantry = new THREE.Group(); gantry.name = 'gantry'; scene.add(gantry);
  const g = L.gantry;
  for (const x of [g.x0 - 150, g.x1 + 150]) { box(gantry, 80, g.y, 80, MAT.steelOrange, x, g.y / 2, -300); foot(gantry, x, -300, 160); }
  box(gantry, g.x1 - g.x0 + 380, 100, 100, MAT.steelOrange, (g.x0 + g.x1) / 2, g.y + 50, -300);
  const carriage = new THREE.Group(); gantry.add(carriage);
  box(carriage, 160, 160, 120, MAT.steelDark, 0, g.y + 50, -190);
  motor(carriage, 0, g.y + 180, -190, .6);
  const bracket = box(carriage, 100, 80, 220, MAT.steelDark, 0, g.y - 20, -80);   // Z 軸導向座：伸到輸送線中心上方
  bracket.userData.guide = 'z-axis';
  const zAxis = new THREE.Group(); zAxis.userData.on = 'z-axis'; carriage.add(zAxis);  // 原點＝夾爪中心
  box(zAxis, 50, 1000, 50, MAT.alu, 0, 575, 0);                                   // 底端埋進橫板；最低位時頂端仍穿過導向座
  box(zAxis, 300, 30, 90, MAT.steelDark, 0, 75, 0);
  const jaws = [-1, 1].map(() => box(zAxis, 20, 120, 80, MAT.yellow, 0, 0, 0));

  // ---- 工件
  const part = new THREE.Group(); part.name = 'part'; scene.add(part);
  box(part, pl, ph, pw, MAT.pu, 0, ph / 2, 0);

  plate(scene, ['取料位'], 260, 70, [L.pick.x, 30, c.z + c.width / 2 + 80], 0);

  // ---------------------------------------------------------------- 時間軸
  const tl = createTimeline();
  const gt = tl.track('gantry', { x: g.x0, y: g.safeY, jaw: 1 });            // y＝夾爪中心高度；jaw 1＝張開
  const pt = tl.track('part', { mode: 'conveyor', s: c.x0 + pl / 2 });
  const s1 = pt.add(3, { s: L.pick.x }, { action: '輸送到取料位', sub: '光電感測到位停止' });
  gt.add(1.5, { x: L.pick.x }, { action: '龍門移到取料位', at: 0 });
  gt.add(1, { y: c.top + ph / 2 }, { action: 'Z 軸下降', at: s1.start + s1.dur });
  const grip = gt.add(.5, { jaw: 0 }, { action: '夾爪夾持' });
  pt.add(0, { mode: 'held' }, { at: grip.start + grip.dur });
  gt.add(1, { y: g.safeY }, { action: 'Z 軸上升' });
  gt.add(1.5, { x: L.place.x }, { action: '移到出料台' });
  gt.add(1, { y: L.place.top + ph / 2 }, { action: '下降放料' });
  const rel = gt.add(.5, { jaw: 1 }, { action: '鬆開' });
  pt.add(0, { mode: 'placed' }, { at: rel.start });
  gt.add(1, { y: g.safeY }, { action: '回安全高度' });
  gt.add(1.5, { x: g.x0 }, { action: '回原點' });

  // ---------------------------------------------------------------- 套用時間 t
  function apply(t) {
    const st = tl.sample(t), G = st.gantry, P = st.part;
    carriage.position.x = G.x;
    zAxis.position.set(0, G.y, 0);
    jaws.forEach((j, k) => { j.position.x = (k ? 1 : -1) * (pl / 2 + 10 + 50 * G.jaw); });
    if (P.mode === 'conveyor') part.position.set(P.s, c.top, c.z);
    else if (P.mode === 'held') part.position.set(G.x, G.y - ph / 2, c.z);
    else part.position.set(L.place.x, L.place.top, L.place.z);
    return st;
  }

  return {
    total: tl.total, timeline: tl, apply,
    layoutChecks: () => [
      { group: '範例', name: '出料台在龍門行程內', ok: L.place.x <= g.x1, value: `${L.place.x} ≤ ${g.x1}` },
      { group: '範例', name: '安全高度：夾持工件底面高於輸送線與出料台 100 mm', ok: g.safeY - ph / 2 - Math.max(c.top, L.place.top) >= 100, value: `${g.safeY - ph / 2 - Math.max(c.top, L.place.top)} mm` },
    ],
    verify: {
      allow: [
        { why: '工件被輸送帶承載、被夾爪夾持或放在出料台上', test: (a, b, ctx) => [a, b].some(m => ctx.moduleOf(m) === 'part') },
      ],
      envelope: ['gantry'],
    },
  };
}
