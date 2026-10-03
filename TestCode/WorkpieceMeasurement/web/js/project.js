// 專案介面（core 統一檢查與 main.js 共用）：建立地面與整台機台，apply(t) 把場景放到時間 t。
// 規格見 core/README.md「專案介面」。規格／情境由 main.js 依網址參數傳入，預設 B／OK（不加參數時的畫面）。
import * as THREE from 'three';
import { SPECS, SCENARIOS, measurement } from './spec.js';
import { createSequence } from './sequence.js';
import { createMachine } from './machine.js';
import { surfaceTexture } from './render-finishes.js';
import { floor as floorPlane } from '@core/geom/environment.js';

// 固定機構依 spec.js 的 id 分工位：底座（花崗岩、X 軸、梭台軸）、ST1、ST2
const BASE = new Set(['granite', 'xaxis', 'shuttleIn', 'shuttleOut']);
const ST2 = /^(bridge|stage|pillar|adapter|ring$|rstage|colC|armUp|armDn|sensorDn|zadj|sensorUp)/;
// 移動線材（wiring-plan.js movingRoutes 的 id）→ 它終止的接頭座（movingSupports 的名稱）
const TERMINALS = { 'Z-TO-VALVE': 'valve / vacuum manifold', 'TOOL-HOSE': 'hose anchor' };
// 穿過桌板的現場線束與夾住它的線夾（equipment-detail.js）；固定線材（wiring-plan.js STATIC_ROUTES）終點在 (±290, 850～865, 231) 匯入
const BUNDLE = /^(field harness through deck gland|split saddle \/ clear cable bore)$/;
const intoBundle = (sleeve, bundle) => {
  const end = sleeve.userData.wiring?.points?.at(-1); if (!end || !/fixed protective sleeve$/.test(sleeve.name)) return false;
  const bx = bundle.userData.route ? bundle.userData.route[0][0] : bundle.position.x;
  return Math.abs(end[0] - bx) < 10 && Math.abs(end[2] - 231) < 1 && end[1] >= 845 && end[1] <= 870;
};

export function createProject({ scene, headless = false, spec = 'B', scenario = 'OK' } = {}) {
  const specId = SPECS[spec] ? spec : 'B', scenarioId = SCENARIOS[scenario] ? scenario : 'OK';
  const s = SPECS[specId], sc = SCENARIOS[scenarioId], m = measurement(s, scenarioId);

  // ---------------------------------------------------------------- 地面（非實體：不列入干涉）
  // 共用 floor()：100 m 見方的展示地面（灰藍粉體塗裝紋理，邊緣隱入霧中）＋ 6 m、100 mm 格的格線（預設隱藏，?grid 顯示）
  const floorFinish = surfaceTexture('powder').clone(); floorFinish.repeat.set(240, 240); floorFinish.needsUpdate = true;
  const { mesh: floor, grid } = floorPlane(scene, {
    size: [100000, 100000], material: new THREE.MeshStandardMaterial({ color: 0x29323a, roughness: .86, roughnessMap: floorFinish, metalness: 0 }),
    gridSize: 6000, cell: 100, grid: [0x2a3644, 0x1c2530],
  });
  grid.visible = false;

  // ---------------------------------------------------------------- 機台與動作序列
  const machine = createMachine(scene, s);
  machine.root.name = 'machine';
  const sequence = createSequence({ spec: specId, scenario: scenarioId, apply: x => machine.apply(x) });
  const total = sequence.total;

  // 畫面上依時間決定、但不屬於 machine.apply 的部分：三色燈、外罩、光束顯示
  function display(cur, { playing = false, hood = true, beams = true } = {}) {
    const done = cur.completed, judged = done.has('judge'), t = cur.state.time;
    machine.setTower(judged && m.result !== 'OK' ? sc.tower : done.has('err0') ? 'yellow' : playing || t >= total ? 'green' : 'yellow');
    machine.hood.visible = hood;
    if (!beams) machine.root.traverse(o => { if (o.material && o.material.blending === THREE.AdditiveBlending) o.visible = false; });
  }
  function apply(t, opts = {}) {
    const cur = sequence.sample(Number.isFinite(t) ? THREE.MathUtils.clamp(t, 0, total) : 0);
    display(cur, opts);
    return cur;
  }

  // ---------------------------------------------------------------- 統一檢查：模組與工位
  const tag = new Map();                                  // 物件 → [模組, 工位]
  const mark = (o, mod, st = 'misc') => { if (o) tag.set(o, [mod, st]); };
  mark(machine.part, 'part');
  for (const [id, t] of Object.entries(machine.trays)) mark(t.grp, 'trays', id);
  for (const [id, g] of Object.entries(machine.tables)) mark(g, 'trays', 'table-' + id);
  mark(machine.transferGroups.x, 'transfer');
  mark(machine.hood, 'hood'); mark(machine.deco, 'cabinet');
  mark(machine.details.electrical, 'electrical'); mark(machine.details.wiring.group, 'wiring');
  mark(machine.rotor1, 'machine', 'st1'); mark(machine.ringLight, 'machine', 'st1');
  mark(machine.rotor2, 'machine', 'st2'); mark(machine.cframe, 'machine', 'st2');
  for (const [id, o] of Object.entries(machine.byId)) if (!tag.has(o)) mark(o, 'machine', BASE.has(id) ? 'base' : ST2.test(id) ? 'st2' : 'st1');
  const tagOf = o => { for (let p = o; p; p = p.parent) if (tag.has(p)) return tag.get(p); return ['machine', 'misc']; };
  const nonPhysical = new Set([floor, grid, machine.beams]);

  return {
    total, apply, display, machine, sequence, spec: s, specId, scenario: sc, scenarioId, measurement: m, floor, grid,
    verify: {
      skip: o => nonPhysical.has(o),
      moduleOf: o => tagOf(o)[0],
      stationOf: o => tagOf(o)[1],
      allow: [
        {
          why: '固定線材在 x ±290 匯入穿過桌板護口的現場線束：線束管代表合併後的整束電纜，split saddle 夾住整束；各線在匯入段與線束、線夾重疊是束線表示法，不是實體干涉。只放行終點落在同側線束上的固定線材',
          test: (a, b) => [[a, b], [b, a]].some(([bundle, sleeve]) => BUNDLE.test(bundle.name) && intoBundle(sleeve, bundle)),
        },
        {
          why: '移動線材的端點接入自己的接頭座（Z-TO-VALVE 接真空閥座、TOOL-HOSE 由軟管固定座夾持），屬安裝關係；線材沿線對機構的間隙由 verify-wiring.mjs 每 40 ms 另行檢查',
          test: (a, b) => TERMINALS[a.name] === b.name || TERMINALS[b.name] === a.name,
        },
      ],
    },
  };
}
