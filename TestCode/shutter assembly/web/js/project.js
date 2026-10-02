// 專案介面（core 統一檢查與 main.js 共用）：建立整站設備、零件與動作序列，apply(t) 把場景放到時間 t。
// 規格見 core/README.md「專案介面」。網頁與檢查用同一份場景，所以檢查的就是畫面上的幾何。
import { createStation } from './station.js';
import { createSequence } from './sequence.js';

// 機台內再分工位：不同工位的固定件互相穿插也算架設相撞（其餘機台、線材、電盤為 misc）
const STATIONS = new Set(['nest', 'up-camera', 'ionizer', 'ng-bin', 'drawer-A', 'drawer-B', 'occluders']);

/**
 * @param scene    three.js 場景
 * @param headless Node 端檢查（不影響幾何）
 * @param ng       true＝「大葉片疊片 → 剔除重取」情境（網址 ?result=NG）；預設為網頁不帶參數時的 OK 流程
 */
export function createProject({ scene, headless = false, ng = false }) {
  void headless;
  const st = createStation(scene, { ng });
  const { cell, robot, parts } = st;
  // 抽屜狀態燈：A 供料中（綠）、B 滿料待命（藍）
  cell.setDrawers(0x3dd68c, 0x4aa8ff);
  let state = null, step = null;
  const sequence = createSequence({ robot, apply: s => { state = s; st.apply(s); }, ng });

  /**
   * 把整個場景放到時間 t：流程狀態 → 手臂目標 → 直接到位（snap）→ 零件依歸屬就位。
   * 靜止段（取像、吸取、保壓）的目標沒有參考姿態，原本以「目前關節」選肘部解與 J4 等價角，
   * 結果會受跳播前的姿態影響；這裡改以該步驟規劃好的終點關節為參考，只依 t 決定。
   */
  function apply(t) {
    const sm = sequence.sample(t); step = sm.step;
    if (!robot.goal.joints && !robot.goal.ref) robot.goal.ref = sm.step.pose1;
    robot.snap(); st.sync();
    return sm;
  }

  // 模組：手臂、產品（本體、葉片、上蓋、疊片）、機台（scene 第一層名稱 cell）
  const partSet = new Set(Object.values(parts));
  const within = (m, test) => { for (let p = m; p; p = p.parent) if (test(p)) return p; return null; };
  const moduleOf = m => within(m, p => partSet.has(p)) ? 'product' : within(m, p => p === robot.root) ? 'robot' : undefined;
  const stationOf = m => {
    if (within(m, p => p === robot.root || partSet.has(p))) return 'misc';
    const top = within(m, p => p.parent === cell.group);
    return top && STATIONS.has(top.name) ? top.name : 'misc';
  };
  const either = (a, b, f, g) => (f(a) && g(b)) || (f(b) && g(a));
  const partOf = m => { const p = within(m, o => partSet.has(o)); return p ? ids.get(p) : null; };
  const ids = new Map(Object.entries(parts).map(([id, p]) => [p, id]));
  // 本體各層是有開口（葉片腔、光圈、側邊避讓槽）的擠出件，OBB 外框會把開口也算成實體
  const bodyLayer = m => partOf(m) === 'base' && m.geometry.type === 'ExtrudeGeometry';
  // 零件已放在本體上，或正由吸嘴／吸盤在接近、接觸步驟中放進本體（放開前一刻歸屬仍在工具上）
  const onBody = id => state?.loc[id] === 'base' || (['T1', 'T2'].includes(state?.loc[id]) && !!(step?.near || step?.contact));

  return {
    total: sequence.total, apply, st, cell, robot, parts, sequence, ng,
    get state() { return state; },
    verify: {
      moduleOf,
      stationOf,
      // 產品是 0.06 mm 葉片、0.2 mm 上蓋：設備尺度的 2 mm 穿插、0.6 mm 重合面門檻不適用。
      // 對數深度在近看時解析度約 0.00002 mm，0.008 mm 以上的間隙不會閃爍；配合公差另由 tools/verify.mjs 以 0.005 mm 檢查
      thresholds: { product: { tol: .01, dist: .008, area: 1 } },
      // 線材端點接入、配線五金（拖鏈固定座、出線管口的接頭）已由 core 內建規則處理
      allow: [
        {
          why: '工具尖端（夾指、吸盤，userData.contact）伸入吸塑盤格孔取放料；片材的外框 OBB 把格孔開口也算成實體，實際杯壁與工具的間隙由 tools/verify-physics.mjs 逐格檢查',
          test: (a, b) => either(a, b, m => m.name === 'tray-sheet', m => !!m.userData.contact),
        },
        {
          why: '葉片放進本體葉片腔、套在樞軸銷上（已放下，或放料步驟中仍由吸嘴吸著）：只放行葉片對本體擠出層；葉片對本體實際輪廓由 tools/verify-product-detail.mjs 逐頂點檢查，孔位對銷由 tools/verify.mjs 以 0.005 mm 檢查',
          test: (a, b) => either(a, b, m => /^[SL][12]$/.test(partOf(m)) && onBody(partOf(m)), bodyLayer),
        },
        {
          why: '上蓋放上本體（已放下，或放上步驟中仍由吸盤吸著），卡勾與折彎橋落在本體側邊避讓槽內：只放行上蓋對本體擠出層；卡勾接近到扣合的 201 個位置由 tools/verify-product-detail.mjs 逐頂點檢查',
          test: (a, b) => either(a, b, m => partOf(m) === 'cover' && onBody('cover'), bodyLayer),
        },
        {
          why: '接近、接觸步驟中工具尖端（T1 吸嘴墊等，userData.contact）伸進本體葉片腔開口放料；吸嘴墊離腔壁約 0.5 mm',
          test: (a, b) => !!(step?.near || step?.contact) && either(a, b, m => !!m.userData.contact, bodyLayer),
        },
      ],
    },
  };
}
