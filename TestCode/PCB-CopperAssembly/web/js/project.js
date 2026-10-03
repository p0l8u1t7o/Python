// 專案介面（core 統一檢查與 main.js 共用）：建立整台機台、五片基板與一個節拍的排程，apply(t) 把場景放到時間 t。
// 規格見 core/README.md「專案介面」。機種配方由 recipe 指定（網頁取自 ?recipe=，未指定＝預設長圓孔 138）。
import { LAYOUT, PRODUCT, RECIPES, setRecipe } from './layout.js';
import { createSim } from './sim.js';

export function createProject({ scene, headless = false, recipe } = {}) {
  setRecipe(recipe);                                      // 先套配方（未指定＝預設），再建機台與排程
  const sim = createSim(scene), plan = sim.plan, machine = sim.machine, boards = sim.boards;
  const G = LAYOUT.gantry;

  // 非實體：地面、板面標示（貼圖文字平面）
  const isDecal = o => o.isMesh && o.geometry?.type === 'PlaneGeometry' && o.material?.map;
  const floor = machine.floor;                             // core floor() 建的地坪（name 'floor'）

  return {
    // 標準排程介面：timeline（core createTimeline）、events（各站與每一趟的節點）、stationStart（S0–S4 開始作業時間）
    total: plan.total, timeline: plan.timeline, events: plan.events, stationStart: plan.stationStart, sim, plan, machine, boards, headless,
    /** 整台場景放到時間 t（只依 t 決定）；playing 只影響三色燈顏色 */
    apply(t, { playing = false } = {}) {
      const info = sim.apply(t);
      machine.tower.set(playing ? 'green' : 'yellow');
      return info;
    },
    layoutChecks() {
      const rows = [], add = (name, ok, value, note) => rows.push({ group: PRODUCT.recipe, name, ok, value, note });
      add('節拍 ≤ 60 s', plan.cycle <= 60, +plan.cycle.toFixed(2), 's');
      add('最大放置誤差 ≤ ±6 mil', plan.stats.maxErr <= PRODUCT.spec, +plan.stats.maxErr.toFixed(4), 'mm');
      add('孔數＝排程放置數', plan.log.filter(e => e.type === 'place').length === plan.holes.length, plan.holes.length);
      for (const H of ['A', 'B']) {
        const f = LAYOUT.feeder[H], u = LAYOUT.upCam[H];
        add(`供料盤 ${H} 在龍門 X 行程內`, Math.abs(f.x) + LAYOUT.feeder.w / 2 < G.railX - 35, f.x, 'mm');
        add(`仰視相機 ${H} 在龍門 X 行程內`, Math.abs(u.x) + LAYOUT.upCam.flySpan / 2 < G.railX - 35, u.x, 'mm');
      }
      add('配方存在', !!RECIPES[PRODUCT.recipe], PRODUCT.recipe);
      return rows;
    },
    verify: {
      skip: o => o === floor || isDecal(o),
      // 不另加 allow：拖鏈固定座與進線、主軸穿過鏜孔分別由 core 內建規則與 guide／on 標記處理
    },
  };
}
