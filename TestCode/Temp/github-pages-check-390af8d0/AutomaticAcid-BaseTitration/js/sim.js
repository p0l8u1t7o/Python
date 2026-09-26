// 把排程在任一時間的狀態套到場景（畫面與驗證共用）
import { createRobot } from './robot.js';
import { createLab } from './lab.js';
import { buildPlan, titrationCurve, dosedVolume } from './plan.js';
import { ST } from './layout.js';

export function createSim(scene) {
  const robot = createRobot(); robot.root.position.set(ST.robot.x, 850, ST.robot.z); scene.add(robot.root); robot.apply();
  const lab = createLab(scene);
  const plan = buildPlan(robot);
  const curves = new Map(plan.jobs.map(j => [j.k, titrationCurve(j)]));

  /** 套用時間 T 的狀態，回傳 HUD 需要的資訊 */
  function apply(T) {
    const f = plan.sample(T), s = f.state, smp = plan.sampler(T);
    robot.setPose(f.pose); robot.snap(); robot.setGripper(s.grip);
    // 進樣器上的杯子：加水、滴定液體積（隨時間）
    s.water = {}; s.titrated = {};
    for (const j of plan.jobs) {
      if (T < j.start) continue;
      const id = `beaker${j.beaker}`, w = Math.min(1, (T - j.start) / 15) * j.waterMl, v = dosedVolume(j, T);
      s.vol[id] += w + v; if (w > 1) s.water[id] = true; if (v > j.veq) s.titrated[id] = true;
    }
    const reading = s.balPan - s.balTare + s.balJit;
    s.balText = `${reading.toFixed(4)} g`;
    lab.setState(s, { robot, rackAngle: smp.angle, headDrop: smp.drop, stir: smp.stir, scanning: f.step.sig === 'scan', time:T, job:smp.job, spray:smp.spray, step:f.step, progress:f.e });
    // 樣品表（整合軟體）：秤重來自狀態快照，滴定結果來自排程
    const table = s.rec.map((r, k) => {
      const j = plan.jobs.find(x => x.k === k);
      let status = r.status || '等待';
      if (j && T >= j.placeT) status = T < j.start ? '排隊' : T < j.end ? '滴定中' : r.removed ? '完成・已取出' : '完成';
      return { ...r, k, status, result: j && T >= j.end ? j.result : null, veq: j && T >= j.end ? j.veq : null, slot: r.slot };
    });
    const cur = smp.job;
    const curve = cur && T >= cur.start ? { job: cur, v: dosedVolume(cur, T), f: curves.get(cur.k) } : null;
    const sig = {
      door: s.door > 0.02, stable: s.balStable && s.balPan > 0, clamp: s.clampGap < 140, tip: !!s.sig.tip,
      pip: f.step.label.startsWith('吸 ') || f.step.label.startsWith('吐出'), cup: plan.msgs.some(m => m.text.startsWith('杯子到位') && T >= m.t && T < m.t + 3),
      titrating: smp.drop === 1 && !!cur && T >= cur.start && T < cur.end, done: plan.jobs.some(j => T >= j.end && T < j.end + 4), rotating: smp.rotating,
      cycle: T >= plan.total - 10, zone: f.step.zone === 'sampler',
    };
    return { step: f.step, e: f.e, state: s, sampler: smp, table, curve, sig };
  }
  return { robot, lab, plan, apply };
}
