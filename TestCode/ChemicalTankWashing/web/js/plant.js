// 全廠設備建立與狀態套用：網頁主程式與 tools/verify-scene.mjs 共用同一份邏輯，檢查的就是畫面上的幾何。
import * as THREE from 'three';
import { MAT, D2R } from '@core/geom/parts.js';
import { createBuilding } from './building.js';
import { createStorage } from './storage.js';
import { createAgv } from './agv.js';
import { createLine } from './line.js';
import { createRobot } from './robot.js';
import { createWashing } from './washing.js';
import { createInbound } from './inbound.js';
import { createDrum, BIG_CAP, SMALL_CAP } from './drum.js';
import { drumWorld, palletWorld, DRUM_IDS, IN_IDS, DRUM_KEYS } from './sequence.js';

export function buildPlant(scene) {
  const building = createBuilding(scene);
  const storage = createStorage(scene, id => createDrum(id));
  const agv = createAgv(scene);
  const line = createLine(scene);
  const robot = createRobot(); scene.add(robot.root);
  const washing = createWashing(scene);
  const inbound = createInbound(scene);
  const drums = [...DRUM_IDS, ...IN_IDS].map(id => { const d = createDrum(id); scene.add(d.root); return d; });
  const held = { big: new THREE.Mesh(BIG_CAP, MAT.cap), small: new THREE.Mesh(SMALL_CAP, MAT.cap) };
  for (const k of ['big', 'small']) { held[k].position.y = 8; line.socket(k).add(held[k]); }
  return { building, storage, agv, line, robot, washing, inbound, drums, held, demoPallet: storage.demo[0].group };
}

// 依取樣結果擺放所有設備與桶（不含 UI）
export function applyPlant(p, sm, { playing = false } = {}) {
  const st = sm.st, { agv, storage, line, robot, inbound, drums, held, washing, demoPallet } = p;
  agv.set({ ...st.agv, time: sm.time });
  storage.setDemo([null, st.pal1, st.pal2, st.pal3], st.shuttle);
  const pw = palletWorld(st.pallet, st.agv); demoPallet.position.copy(pw.pos); demoPallet.rotation.y = pw.yaw * D2R;
  line.setGantry(st.gantry); line.setLabeler(st.labeler); line.setUpender(st.upender); line.setDecap(st.decap);
  held.big.visible = st.decap.heldBig; held.small.visible = st.decap.heldSmall;
  robot.setJaw(st.grip.jaw); robot.root.updateMatrixWorld(true);
  inbound.set({ dollyX: st.dolly.x, a: st.jib.a, r: st.jib.r, y: st.jib.y, clamp: st.jib.clamp });
  drums.forEach((d, k) => {
    const key = DRUM_KEYS[k], s = st[key], w = drumWorld(key, st, robot.tcp.matrixWorld);
    d.root.visible = !w.hidden; if (w.hidden) return;
    d.root.position.copy(w.pos); d.root.quaternion.copy(w.q); d.root.updateMatrixWorld(true);
    d.setCaps(s.capBig, s.capSmall); d.setLabel(s.label, s.labelAng * D2R); d.setWater(s.water);
  });
  const b = st.booth, sp = st.sump;
  washing.set({
    knife: b.knife, lance: b.lance, lance2: b.lance2, spray: b.spray, pool: b.pool, sump: sp.level, tanks: st.tanks,
    pour: b.pour !== '' ? drums[+b.pour].bungWorld('big') : null,
    flows: { hot: b.hot, vac: b.vac, vacOut: b.vac, supply: b.spray, supply2: b.spray, fromF: b.spray && b.src === 'F', fromR: b.spray && b.src === 'R', sump: sp.pump, riser: sp.pump, toWA: sp.pump && sp.dest === 'WA', toWB: sp.pump && sp.dest === 'WB', toR: sp.pump && sp.dest === 'R', city: st.makeup.on },
  });
  line.setScale(st.scale);
  line.setTower(playing ? 'run' : 'wait');
  line.animate(sm.time, st);
}
