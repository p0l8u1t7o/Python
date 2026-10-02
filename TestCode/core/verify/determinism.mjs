// 倒序／跳播一致性：同一時間點不論從哪裡跳過來，場景每個物件的世界矩陣與可見性都必須相同。
// 拖曳時間軸、倒退播放、截圖與檢查程式都依賴這個性質。
import * as THREE from 'three';

export function verifyDeterminism(project, scene, { samples = 40, tol = 1e-3 } = {}) {
  const total = project.total;
  const times = Array.from({ length: samples }, (_, i) => +(total * (i + .37) / samples).toFixed(4));
  const objs = []; scene.traverse(o => objs.push(o));
  const snap = t => { project.apply(t); scene.updateMatrixWorld(true); return objs.map(o => [o.matrixWorld.elements.slice(), visibleOf(o)]); };
  const visibleOf = o => { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; };
  const forward = times.map(snap);
  const failures = [];
  // 倒序取樣、再從結尾跳回每個時間點
  [...times].reverse().forEach((t, i) => {
    const k = times.length - 1 - i, got = snap(t), ref = forward[k];
    for (let j = 0; j < objs.length && failures.length < 20; j++) {
      const [m, v] = got[j], [m0, v0] = ref[j];
      if (!v && !v0) continue;                       // 看不到的物件位置不影響畫面
      const d = Math.max(...m.map((x, q) => Math.abs(x - m0[q])));
      if (d > tol || v !== v0) { failures.push({ t, object: label(objs[j]), maxDiff: +d.toFixed(4), visible: [v0, v] }); break; }
    }
  });
  return { ok: !failures.length, objects: objs.length, samples, failures };
}
const label = o => { const path = []; for (let p = o; p && p.parent; p = p.parent) path.unshift(p.name || p.type); return path.slice(-4).join('/'); };
