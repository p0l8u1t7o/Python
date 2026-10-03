// 專案介面：網頁（main.js）與 core 統一檢查共用。規格見 core/README.md「專案介面」。
// 範例：輸送帶把工件送到取料位，龍門 Z 軸下降夾取，移到出料台放下。
// 輸送線與龍門取自共用模型庫（core/models，目錄頁 /core/catalog/）；專案特有的東西（出料台、工件）在這裡建。
import * as THREE from 'three';
import { block, plate } from '@core/geom/shapes.js';
import { MAT } from '@core/geom/materials.js';
import { sensor } from '@core/geom/hardware.js';
import { createTimeline } from '@core/anim/track.js';
import { floor } from '@core/geom/environment.js';
import { create as createConveyor } from '@core/models/conveyor.js';
import { create as createGantry } from '@core/models/gantry.js';

// ---------------------------------------------------------------- 配置（單位 mm；X 往東、Y 往上、Z 往南）
export const LAYOUT = {
  conveyor: { x0: -1400, x1: 200, z: 0, top: 800, width: 360 },
  pick: { x: 0, z: 0 },
  place: { x: 700, z: 0, top: 800 },
  gantry: { cx: 350, span: 1300, height: 1700, offset: 400, safeY: 1250 },   // offset 400：龍門腳座退到輸送線腳座北側（300 時兩者腳座重疊）
  part: [200, 120, 160],                      // 工件 長×高×寬
};
// 站別（頂部列的站別按鈕）：時間軸步驟以 station 標記所屬站別
export const STATIONS = ['輸送進料', '取料', '放料', '回原點'];

export function createProject({ scene }) {
  const L = LAYOUT, c = L.conveyor, g = L.gantry, [pl, ph, pw] = L.part;

  floor(scene, { size: [4000, 3000], cell: 200 });                            // 共用地坪＋格線（core/geom/environment.js）

  // ---- 輸送線（共用模型）
  const conveyor = createConveyor({ length: c.x1 - c.x0, width: c.width, height: c.top });
  conveyor.root.position.set((c.x0 + c.x1) / 2, 0, c.z); scene.add(conveyor.root);
  sensor(conveyor.root, L.pick.x - (c.x0 + c.x1) / 2 + 140, c.top + 34, -c.width / 2 - 60);

  // ---- 出料台
  const table = new THREE.Group(); table.name = 'table'; scene.add(table);
  block(table, [400, L.place.top, 400], [L.place.x, L.place.top / 2, L.place.z], MAT.steelBlue);

  // ---- 龍門（共用模型）：樑在輸送線北側，夾爪伸到輸送線中心
  const gantry = createGantry({ span: g.span, height: g.height, offset: g.offset, grip: pl });
  gantry.root.position.set(g.cx, 0, c.z - g.offset); scene.add(gantry.root);

  // ---- 工件
  const part = new THREE.Group(); part.name = 'part'; scene.add(part);
  block(part, [pl, ph, pw], [0, ph / 2, 0], MAT.pu);

  plate(scene, ['取料位'], 260, 70, [L.pick.x, 30, c.z + c.width / 2 + 120], 0);

  // ---------------------------------------------------------------- 時間軸
  const home = g.cx - g.span / 2 + 100;                                       // 龍門原點：行程西端內縮 100 mm
  const tl = createTimeline();
  const gt = tl.track('gantry', { x: home, y: g.safeY, jaw: 1 });       // x 世界座標；y＝夾爪中心高度；jaw 1＝張開
  const pt = tl.track('part', { mode: 'conveyor', s: c.x0 + pl / 2 });
  const s1 = pt.add(3, { s: L.pick.x }, { action: '輸送到取料位', sub: '光電感測到位停止', station: 0 });
  gt.add(1.5, { x: L.pick.x }, { action: '龍門移到取料位', at: 0, station: 0 });
  gt.add(1, { y: c.top + ph / 2 }, { action: 'Z 軸下降', at: s1.start + s1.dur, station: 1 });
  const grip = gt.add(.5, { jaw: 0 }, { action: '夾爪夾持', station: 1 });
  pt.add(0, { mode: 'held' }, { at: grip.start + grip.dur });
  gt.add(1, { y: g.safeY }, { action: 'Z 軸上升', station: 1 });
  gt.add(1.5, { x: L.place.x }, { action: '移到出料台', station: 2 });
  gt.add(1, { y: L.place.top + ph / 2 }, { action: '下降放料', station: 2 });
  const rel = gt.add(.5, { jaw: 1 }, { action: '鬆開', station: 2 });
  pt.add(0, { mode: 'placed' }, { at: rel.start });
  gt.add(1, { y: g.safeY }, { action: '回安全高度', station: 3 });
  gt.add(1.5, { x: home }, { action: '回原點', station: 3 });

  // ---------------------------------------------------------------- 套用時間 t
  function apply(t) {
    const st = tl.sample(t), G = st.gantry, P = st.part;
    gantry.set({ x: G.x - g.cx, y: G.y, jaw: G.jaw });
    conveyor.set({ s: P.mode === 'conveyor' ? P.s - (c.x0 + pl / 2) : L.pick.x - (c.x0 + pl / 2) });
    if (P.mode === 'conveyor') part.position.set(P.s, c.top, c.z);
    else if (P.mode === 'held') part.position.set(G.x, G.y - ph / 2, c.z);
    else part.position.set(L.place.x, L.place.top, L.place.z);
    return st;
  }
  // 各站第一個步驟的開始時間（站別按鈕跳到這裡）
  const stationStart = STATIONS.map((_, k) => Math.min(...tl.events.filter(e => e.station === k).map(e => e.start)));

  return {
    total: tl.total, timeline: tl, apply, stationStart, part,
    layoutChecks: () => [
      { group: '範例', name: '取放位在龍門行程內', ok: [L.pick.x, L.place.x, g.cx - g.span / 2 + 100].every(x => Math.abs(x - g.cx) <= g.span / 2), value: `±${g.span / 2} mm` },
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
