// 專案介面（core 統一檢查與 main.js 共用）：建立實驗桌、手臂、器皿與排程，apply(t) 把整個場景放到時間 t。
// 規格見 core/README.md「專案介面」。場景與時間狀態由 sim.js 建立與套用（本專案自有驗證 tools/verify*.mjs 也用它），
// 所以網頁、統一檢查與自有驗證看到的是同一份幾何。
import * as THREE from 'three';
import { createSim } from './sim.js';

export function createProject({ scene }) {
  const sim = createSim(scene), { robot, lab, plan } = sim;
  let info = null;                                   // 最近一次 apply 的狀態（允許規則依目前步驟判斷）

  // ---------------------------------------------------------------- 檢查用的對照表
  const itemOf = new Map();                          // 網格 → 器皿 id（bottle0、cap0、beaker0、tip0、pip）
  for (const [id, g] of Object.entries(lab.items)) g.traverse(m => itemOf.set(m, id));
  const fingerMeshes = new Set();                    // 夾爪手指與指墊
  for (const f of robot.fingers) f.traverse(m => fingerMeshes.add(m));
  const stationOf = new Map();                       // 網格 → 設備（天平、瓶座、進樣器…）
  for (const [name, g] of Object.entries(lab.stations)) g.traverse(m => stationOf.set(m, name));
  const under = (m, root) => { for (let p = m; p; p = p.parent) if (p === root) return true; return false; };
  const nonPhysical = new Set([lab.floor, ...lab.zones]);
  // 印刷標示（設備標籤、瓶身條碼、刻度）：貼圖平面以 polygonOffset／不寫深度繪製，不是實體
  const isLabel = o => o.isMesh && !!o.material?.map && (o.material.polygonOffset || o.material.depthWrite === false);
  // 零件外框的 8 個角是否全落在環形件內孔（ring() 建立的環：局部 y 為軸，userData.bore 為內孔半徑）
  const _p = new THREE.Vector3();
  const insideBore = (ring, m) => {
    if (!m.geometry.boundingBox) m.geometry.computeBoundingBox();
    const b = m.geometry.boundingBox;
    for (let k = 0; k < 8; k++) {
      _p.set(k & 1 ? b.max.x : b.min.x, k & 2 ? b.max.y : b.min.y, k & 4 ? b.max.z : b.min.z).applyMatrix4(m.matrixWorld);
      ring.worldToLocal(_p); if (Math.hypot(_p.x, _p.z) >= ring.userData.bore) return false;
    }
    return true;
  };

  return {
    total: plan.total, sim, robot, lab, plan,
    /** 把場景放到時間 t（只依 t 決定，與先前跳到哪裡無關），回傳 HUD 用的狀態 */
    apply(t) { info = sim.apply(t); return info; },
    verify: {
      skip: o => nonPhysical.has(o) || isLabel(o),
      stationOf: m => stationOf.get(m) ?? 'misc',
      allow: [
        {
          why: '夾爪指墊夾持器皿：正被夾著或本步驟要夾／放的瓶、杯、瓶蓋、移液模組（夾緊時指墊壓入 1 mm，瓶蓋止滑紋凸出，壓入約 2.3 mm）',
          test: (a, b) => {
            const [f, o] = fingerMeshes.has(a) ? [a, b] : [b, a], id = itemOf.get(o);
            if (!fingerMeshes.has(f) || !id || !info) return false;
            return !!info.state.loc[id]?.g || !!info.step.touch?.includes(id);
          },
        },
        {
          why: '瓶蓋鎖在自己的瓶口上（含開蓋／關蓋旋轉時）：瓶口螺紋與口緣伸入蓋內',
          test: (a, b) => {
            const ia = itemOf.get(a), ib = itemOf.get(b); if (!ia || !ib || !info) return false;
            const [cap, bottle] = ia.startsWith('cap') ? [ia, ib] : [ib, ia];
            if (!cap.startsWith('cap') || bottle !== 'bottle' + cap.slice(3)) return false;
            const L = info.state.loc[cap];
            return L?.on === bottle || (!!L?.g && !!info.step.touch?.includes(bottle));
          },
        },
        {
          why: '零件整個落在環形件的內孔裡（例如攪拌槳在轉盤杯位環內的滴定杯中）；外框檢查把環形件當成實心，實際不接觸',
          test: (a, b) => (!!a.userData.bore && insideBore(a, b)) || (!!b.userData.bore && insideBore(b, a)),
        },
        {
          why: '手臂肩部外殼（J1 上的軸對稱件，繞自身軸轉而被判為固定）與裝在它上面的 J2 關節殼、上臂根部：相鄰關節的安裝關係',
          test: (a, b) => {
            const [s, o] = a.name === 'shoulder' ? [a, b] : [b, a];
            return s.name === 'shoulder' && under(s, robot.root) && o.parent?.parent === s.parent;
          },
        },
      ],
      envelope: ['robot'],
    },
  };
}
