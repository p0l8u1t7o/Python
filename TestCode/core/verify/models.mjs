// 共用模型檢查：每個登記在 core/models/index.js 的模型，用預設參數建立，狀態從最小到最大走一遍，
// 做與專案相同的全場檢查（會動零件干涉、重合面閃爍），並確認 create／set 在 Node 端可執行。
//   node --import ./tools/register.mjs verify/models.mjs      （在 core 資料夾）
import './dom-stub.mjs';
import * as THREE from 'three';
import { writeFileSync, mkdirSync } from 'node:fs';
import { MODELS } from '../models/index.js';
import { verifyScene } from './scene.mjs';

const results = [];
for (const m of MODELS) {
  const id = m.meta.id, row = { id, name: m.meta.name };
  try {
    const scene = new THREE.Scene(), inst = m.create({}); scene.add(inst.root);
    const states = Object.entries(m.meta.states || {});
    const project = {
      total: 1,
      apply(t) { if (inst.set) inst.set(Object.fromEntries(states.map(([k, s]) => [k, s.min + (s.max - s.min) * t]))); },
      verify: { dt: .02, ...(m.meta.verify || {}) },
    };
    const r = verifyScene(project, scene, { probes: 20, zfightTimes: 5 });
    Object.assign(row, { ok: r.ok, meshes: r.meshes, dynamic: r.dynamic, zfight: r.zfight });
  } catch (e) { Object.assign(row, { ok: false, error: String(e.stack || e).split('\n').slice(0, 3).join(' | ') }); }
  results.push(row);
  console.log(`${row.ok ? '✓' : '✗'} ${id}（${row.name}）${row.error ? '：' + row.error : `：${row.meshes} 個零件，干涉 ${row.dynamic.length}、重合面 ${row.zfight.length}`}`);
  for (const d of row.dynamic || []) console.log('   DYN', d.worst, d.a, '<>', d.b);
  for (const z of row.zfight || []) console.log('   ZF ', z.area + 'mm²', z.a, '<>', z.b);
}
mkdirSync(new URL('../review/', import.meta.url), { recursive: true });
writeFileSync(new URL('../review/models.json', import.meta.url), JSON.stringify(results, null, 2));
process.exit(results.every(r => r.ok) ? 0 : 1);
