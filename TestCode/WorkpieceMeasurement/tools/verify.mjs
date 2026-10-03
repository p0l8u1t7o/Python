// 流程／幾何／運動驗證：node ../core/tools/run.mjs WorkpieceMeasurement tools/verify.mjs（sequence.js 引用 @core/，需共用 loader）
// 三種規格 × 五種情境：狀態一致性、工件位置連續、軸速限、移載對固定機構與托盤的最小間隙、光錐可及性。
import { writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { SPECS, SCENARIOS, LIMIT, DEMO, YT, YS, fixedBodies, transferBodies, trayBodies, partPose, pocket, measurement, inTol } from '../web/js/spec.js';
import { createSequence } from '../web/js/sequence.js';
import { clearance } from '../web/js/collision.js';

const MIN_GAP = 0.2, DT = 0.02, failures = [], report = { generated: new Date().toISOString(), minGap: MIN_GAP, cases: [] };
const fail = (where, msg) => { failures.push(`${where}: ${msg}`); };
const held = (st, s) => { const p = partPose(st, s); return { id: 'heldPart', kind: 'cyl', p0: [p.x, p.y, p.z], p1: [p.x, p.y + s.len, p.z], r: s.od / 2 + (s.flare ? s.flare.dr : 0) }; };

for (const spec of Object.keys(SPECS)) for (const scenario of Object.keys(SCENARIOS)) {
  const s = SPECS[spec], sc = SCENARIOS[scenario], tag = `${spec}/${scenario}`, seq = createSequence({ spec, scenario });
  const fixed = fixedBodies(s).filter(b => !['xaxis'].includes(b.id));
  const c = { spec, scenario, steps: seq.steps.length, total: +seq.total.toFixed(3), uph: Math.round(3600 / seq.total) };

  // 1. 結束狀態與分流
  const end = seq.sample(seq.total), expect = sc.out === 'IN' ? 'back' : 'out:' + sc.out;
  if (end.state.loc !== expect) fail(tag, `結束時工件在 ${end.state.loc}，應為 ${expect}`);
  for (const id of ['clamp', 'scanA', 'shotB3', 'shotC', 'spiral0', 'judge', 'out', 'home']) if (!end.completed.has(id)) fail(tag, `未完成 ${id}`);
  if (sc.id === 'ERR' !== end.completed.has('spiral1')) fail(tag, '重測次數與情境不符');
  if (Math.abs(end.state.a - 6) > 1e-6 || end.state.vac || end.state.jaw < 0.99) fail(tag, '結束時吸嘴／夾頭未回安全狀態');

  // 2. 任意跳站與倒退一致：同一時刻取樣結果相同
  const probe = [0.37, 0.61, 0.13, 0.92, 0.5].map(k => k * seq.total);
  const first = probe.map(T => JSON.stringify(seq.sample(T).state));
  [...probe].reverse().forEach((T, i) => { if (JSON.stringify(seq.sample(T).state) !== first[probe.length - 1 - i]) fail(tag, `t=${T.toFixed(2)} 倒退取樣不一致`); });

  // 3. 連續取樣：位置連續、軸速限、夾持交接、間隙
  let prev = null, maxJump = 0, vmax = { tx: 0, zt: 0, inZ: 0, outZ: 0 }, gap = { d: Infinity }, gapJaw = { d: Infinity }, gapTray = { d: Infinity };
  const jaws = fixed.filter(b => b.rotor === 1), statics = fixed.filter(b => !b.rotor || b.rotor === 2);
  for (let T = 0; T <= seq.total + 1e-9; T += DT) {
    const { state: st } = seq.sample(T), p = partPose(st, s);
    if (prev) {
      maxJump = Math.max(maxJump, Math.hypot(p.x - prev.p.x, p.y - prev.p.y, p.z - prev.p.z) - (Math.abs(st.tx - prev.st.tx) + Math.abs(st.zt - prev.st.zt) + Math.abs(st.a - prev.st.a) + Math.abs(st.inZ - prev.st.inZ) + Math.abs(st.outZ - prev.st.outZ)));
      for (const k of Object.keys(vmax)) vmax[k] = Math.max(vmax[k], Math.abs(st[k] - prev.st[k]) / DT);
      if (st.vac && st.loc !== 'noz' && prev.st.loc === 'noz') fail(tag, `t=${T.toFixed(2)} 放料時真空未解除`);
    }
    // 約束：吸附中才可移動工件；夾頭夾持時工件在夾頭或吸嘴貼靠中
    if (st.loc === 'noz' && !st.vac) fail(tag, `t=${T.toFixed(2)} 吸附中但真空為 0`);
    if (st.loc === 'chuck' && st.jaw > 0.01) fail(tag, `t=${T.toFixed(2)} 夾頭未夾緊但工件掛在夾頭`);
    if (st.optic === 'CF' && (Math.abs(st.tx - prev?.st.tx) > 1e-9 || Math.abs(st.zt - prev?.st.zt) > 1e-9)) fail(tag, `t=${T.toFixed(2)} ST2 掃描中移載仍在動作`);
    if ((st.optic === 'A' || st.th1 !== (prev?.st.th1 ?? st.th1)) && st.zt > YT + 17) fail(tag, `t=${T.toFixed(2)} θ 旋轉時吸嘴未下降避讓`);
    const moving = transferBodies(st, s).filter(b => b.id !== 'carriage' && b.id !== 'zcol');
    const arm = moving.filter(b => b.id === 'blade' || b.id === 'armBody');
    if (st.loc === 'noz') moving.push(held(st, s));
    // 工件落座或夾持時，接觸的那個機構不算干涉
    const touching = st.loc === 'noz' && st.jaw < 0.99 ? ['jaw0', 'jaw1', 'jaw2', 'chuck'] : [];
    const seatTouch = st.loc === 'noz' && Math.abs(st.zt - YS) < 0.5 && Math.abs(st.tx - 215) < 0.5 ? ['ring'] : [];
    const dynamicStatics = statics.map(b => {
      if (!b.cframe) return b;
      const dy = b.id === 'sensorUp' ? st.headLift : 0;
      return b.kind === 'box' ? {...b,min:[b.min[0]+st.r2,b.min[1]+dy,b.min[2]],max:[b.max[0]+st.r2,b.max[1]+dy,b.max[2]]}
        : {...b,p0:[b.p0[0]+st.r2,b.p0[1]+dy,b.p0[2]],p1:[b.p1[0]+st.r2,b.p1[1]+dy,b.p1[2]]};
    });
    if (st.loc === 'noz' && Math.abs(st.tx-215)<20 && st.headLift<29.9) fail(tag, '上頭未退回，移載已進入 ST2');
    if (st.optic === 'CF' && st.headLift > .001) fail(tag, '上頭未到量測位置');
    const g = clearance(moving, dynamicStatics.filter(b => !seatTouch.includes(b.id) && !touching.includes(b.id)), 2.5);
    if (g.d < gap.d) gap = { ...g, t: +T.toFixed(2) };
    const gj = clearance(arm, jaws, 1); if (gj.d < gapJaw.d) gapJaw = { ...gj, t: +T.toFixed(2) };
    // 托盤：吸附中的工件不與自己比；放在穴內時穴位本身不算
    // 托盤：正在取放的那一穴是吸嘴的接觸對象，不算干涉；工件在穴內時也不與托盤本體比
    const atPocket = Math.abs(st.zt - YT) < 2.5, target = st.tx < -200 ? `partIN${DEMO.k}` : sc.out === 'IN' ? '' : `part${sc.out}${DEMO.filled[sc.out]}`;
    const trays = trayBodies(st, s).filter(b => !(atPocket && (b.id === target || (st.loc === 'noz' && b.id.startsWith('tray')))));
    const gt = clearance(atPocket && st.loc === 'noz' ? arm : moving, trays, 2.5); if (gt.d < gapTray.d) gapTray = { ...gt, t: +T.toFixed(2) };
    prev = { st, p };
  }
  if (maxJump > 0.02) fail(tag, `工件位置不連續 ${maxJump.toFixed(3)} mm`);
  if (vmax.tx > LIMIT.vx * 1.02) fail(tag, `X 軸 ${vmax.tx.toFixed(0)} mm/s 超過 ${LIMIT.vx}`);
  if (vmax.zt > LIMIT.vz * 1.02) fail(tag, `Z 軸 ${vmax.zt.toFixed(0)} mm/s 超過 ${LIMIT.vz}`);
  for (const [name, g] of [['固定機構', gap], ['夾爪', gapJaw], ['托盤', gapTray]]) if (g.d < MIN_GAP) fail(tag, `移載對${name}間隙 ${g.d.toFixed(2)} mm（${g.moving} ↔ ${g.fixed}，t=${g.t}）`);

  // 4. 托盤規則：吸嘴側（−Z）的列必須是空的
  const pin = pocket('IN', DEMO.k); if (pin.row > 0 && DEMO.k - pin.col - 1 < 0) fail(tag, '入料順序不符');
  // 5. 模擬量測值與情境一致
  const m = measurement(s, scenario), okDim = m.od.every(v => inTol(v, s.criteria.od)) && inTol(m.length, s.criteria.length) && inTol(m.idLip, s.criteria.idLip);
  const okThk = m.thkMean === null || (inTol(m.thkMean, s.criteria.thk) && m.thkTir <= s.criteria.tir);
  if (okDim === (scenario === 'NG-D')) fail(tag, '尺寸模擬值與情境不符');
  if (okThk === (scenario === 'NG-T')) fail(tag, '底厚模擬值與情境不符');
  Object.assign(c, { vmax: Object.fromEntries(Object.entries(vmax).map(([k, v]) => [k, Math.round(v)])), gapFixed: gap, gapJaw, gapTray, maxJump: +maxJump.toFixed(4) });
  report.cases.push(c);
  console.log(`${tag.padEnd(7)} ${String(c.steps).padStart(2)} 步 ${c.total.toFixed(2)} s ${c.uph} UPH｜間隙 固定 ${gap.d.toFixed(2)}（${gap.moving}↔${gap.fixed}） 夾爪 ${gapJaw.d.toFixed(2)} 托盤 ${gapTray.d.toFixed(2)}（${gapTray.moving}↔${gapTray.fixed}）`);
}

// KEYENCE quotation/spec sheet does not give the aperture cone; do not reuse the old sensor's NA.
report.cone = Object.values(SPECS).map(s => ({spec:s.id,sensor:'CL-S015',referenceDistance:15,verified:false,status:'待原廠光路圖與實物可及性驗證'}));
report.scope='離散幾何與狀態檢查；不包含光學可及性、精度或現場安全認證';

report.failures = failures; report.pass = failures.length === 0;
const out = join(dirname(fileURLToPath(import.meta.url)), '..', 'review'); mkdirSync(out, { recursive: true });
writeFileSync(join(out, 'verification.json'), JSON.stringify(report, null, 2));
if (failures.length) { console.error(`\n✗ ${failures.length} 項不符：\n` + failures.map(f => '  - ' + f).join('\n')); process.exit(1); }
console.log(`\n✓ ${report.cases.length} 個組合全部通過（最小間隙門檻 ${MIN_GAP} mm）`);
