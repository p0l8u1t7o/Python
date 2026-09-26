// 把排程在時間 T 的狀態套到整台機台（主程式與驗證共用）
import * as THREE from 'three';
import { LAYOUT, PRODUCT, BOARD_TOP } from './layout.js';
import { buildPlan } from './plan.js';
import { createMachine } from './machine.js';
import { createBoard } from './board.js';

const ST = LAYOUT.stations, G = LAYOUT.gantry, THICK = PRODUCT.board.t + PRODUCT.board.adhesive, PITCH = 1.9;
const STACK = { in: 20, out: 12, base: 830 };

export function createSim(scene) {
  const plan = buildPlan(), m = createMachine(scene);
  const byT = key => [...plan.holes].sort((a, b) => a[key] - b[key]);
  const placedOrder = byT('placeT'), mapOrder = byT('mapT'), inspOrder = byT('inspT');
  const opts = { placedOrder, mapOrder, inspOrder, pose: h => ({ x: h.lx + h.ex, z: h.lz + h.ez, a: h.angle + h.et }) };
  const boards = { s0: createBoard(opts), s1: createBoard(opts), s2: createBoard(opts), s3: createBoard(opts), fresh: createBoard(opts) };
  for (const b of Object.values(boards)) scene.add(b.group);
  const N = plan.holes.length; boards.s2.setCoins(N); boards.s3.setCoins(N); boards.s2.setMapped(0);
  // 料倉：上料剩餘（不含最上面那片）、收料已疊
  for (const [key, n] of [['S0', STACK.in - 1], ['S4', STACK.out]]) { const s = m.stacks[key].stack; s.scale.y = n * PITCH; s.position.y = STACK.base + n * PITCH / 2; }
  const count = (list, key, T) => { let n = 0; for (const h of list) if (h[key] <= T) n++; else break; return n; };
  const upcamEv = { A: plan.events.filter(e => e.type === 'upcam' && e.H === 'A').map(e => e.t), B: plan.events.filter(e => e.type === 'upcam' && e.H === 'B').map(e => e.t) };
  const near = (list, T, w = 0.03) => list.some(t => Math.abs(t - T) < w);
  const status = {};

  /** 上下料機構：回傳吸盤底高度與是否夾持 */
  function loaderPose(key, T) {
    const s = plan[key === 'S0' ? 's0' : 's4'].sample(T), p = s.pose, L = m.loaders[key];
    const stackTop = key === 'S0' ? STACK.base + (STACK.in - 1) * PITCH + THICK : STACK.base + STACK.out * PITCH + (p.grip ? THICK : 0);
    const surface = p.z > LAYOUT.stackZ / 2 ? stackTop : BOARD_TOP;
    const cupY = surface + (1180 - surface) * p.y;
    L.car.position.z = p.z; L.zAxis.position.y = cupY;
    status[key] = s.label;
    return { cupY, z: p.z, grip: p.grip > 0.5, x: key === 'S0' ? ST[0] : ST[4] };
  }

  function apply(T) {
    const cv = plan.conveyor.sample(T).pose, shift = cv.shift, k = shift / 700;
    status.conveyor = plan.conveyor.sample(T).label;
    m.lifts.forEach(l => { l.position.y = (cv.lift - 1) * 6; }); m.stops.forEach(s => { s.position.y = (cv.lift - 1) * 24; });
    m.beltMarks.position.x = shift % 60;
    // 基板：S0→S1（掃描）、S1→S2（放置）、S2→S3（檢查）、S3→S4（下料）
    const y0 = LAYOUT.conveyorTop;
    boards.s0.group.position.set(ST[0] + shift, y0, 0); boards.s0.setMapped(count(mapOrder, 'mapT', T)); boards.s0.setCoins(0);
    boards.s1.group.position.set(ST[1] + shift + plan.place.dx * k, y0, plan.place.dz * k); boards.s1.group.rotation.y = -plan.place.rot * k;
    boards.s1.setCoins(count(placedOrder, 'placeT', T)); boards.s1.setMapped(k > 0.999 ? 0 : N);
    boards.s2.group.position.set(ST[2] + shift, y0, 0); boards.s2.setInspected(count(inspOrder, 'inspT', T));
    const un = loaderPose('S4', T), ld = loaderPose('S0', T);
    const gripT4 = plan.s4.segs.find(x => x.to.grip === 1)?.t1 ?? Infinity, relT4 = plan.s4.segs.find(x => x.from.grip === 1 && x.to.grip === 0)?.t1 ?? Infinity;
    if (T < gripT4) boards.s3.group.position.set(ST[3] + shift, y0, 0);
    else if (T < relT4) boards.s3.group.position.set(ST[4], un.cupY - THICK, un.z);
    else boards.s3.group.position.set(ST[4], STACK.base + STACK.out * PITCH, LAYOUT.stackZ);
    const gripT0 = plan.s0.segs.find(x => x.to.grip === 1)?.t1 ?? Infinity, relT0 = plan.s0.segs.find(x => x.from.grip === 1 && x.to.grip === 0)?.t1 ?? Infinity;
    if (T < gripT0) boards.fresh.group.position.set(ST[0], STACK.base + (STACK.in - 1) * PITCH, LAYOUT.stackZ);
    else if (T < relT0) boards.fresh.group.position.set(ST[0], ld.cupY - THICK, ld.z);
    else boards.fresh.group.position.set(ST[0], y0, 0);
    boards.fresh.setMapped(0); boards.fresh.setCoins(0);
    // S1／S3 相機龍門
    for (const [key, tr] of [['S1', plan.s1.tr], ['S3', plan.s3.tr]]) {
      const s = tr.sample(T), sc = m.scanners[key];
      sc.beam.position.z = s.pose.z; sc.car.position.x = sc.x0 + s.pose.x; sc.cam.flash(!!(s.seg?.flash && !s.done)); status[key] = s.label;
    }
    // S2 龍門與吸嘴
    for (const H of ['A', 'B']) {
      const h = plan.heads[H], s = h.tr.sample(T), p = s.pose, hd = m.heads[H];
      hd.beam.position.z = p.nz + hd.side * G.overhang; hd.head.position.x = p.x;
      hd.nozzles.forEach((nz, i) => {
        nz.spindle.position.y = p[`y${i}`]; nz.spindle.rotation.y = p[`t${i}`] * Math.PI / 180;
        const hold = h.hold[i].find(x => x.t0 <= T && T < (x.t1 ?? Infinity));
        nz.coin.visible = !!hold;
        if (hold) { const o = hold.coin.pickOffset; nz.coin.position.set(o.dx, -PRODUCT.coin.t, o.dz); nz.coin.rotation.y = o.dt * Math.PI / 180; }
      });
      hd.downCam.flash(!!(s.seg?.flash && !s.done)); status['S2' + H] = s.label;
      m.upCams[H].flash(near(upcamEv[H], T));
      // 供料盤
      const f = plan.feeders[H], fm = m.feeders[H], fs = f.tr.sample(T);
      let gi = 0, bi = 0;
      for (const c of f.coins) {
        if (!(c.t0 <= T && T < c.t1)) continue;
        const mesh = c.good ? fm.coins[gi++] : fm.backs[bi++]; if (!mesh) continue;
        const vib = !c.pickedBy && T > c.t1 - 0.6 ? Math.sin(T * 70 + c.id) * 1.5 : 0;
        mesh.visible = true; mesh.position.set(c.x + vib, LAYOUT.feeder.top, c.z + vib * 0.6); mesh.rotation.y = c.theta * Math.PI / 180;
      }
      for (let i = gi; i < fm.coins.length; i++) fm.coins[i].visible = false;
      for (let i = bi; i < fm.backs.length; i++) fm.backs[i].visible = false;
      fm.cam.flash(!!(fs.seg?.flash && !fs.done)); status['feeder' + H] = fs.label;
    }
    scene.updateMatrixWorld(true);
    const placed = { A: plan.heads.A.hold.flat().filter(x => x.t1 <= T).length, B: plan.heads.B.hold.flat().filter(x => x.t1 <= T).length };
    const done = plan.holes.filter(h => h.placeT <= T);
    return { placed, maxErr: done.reduce((a, h) => Math.max(a, h.err), 0), mapped: count(mapOrder, 'mapT', T), inspected: count(inspOrder, 'inspT', T), status };
  }
  return { plan, machine: m, boards, apply };
}
