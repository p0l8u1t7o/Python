// 平衡重式堆高 AGV：模型在共用模型庫（core/models/agv-forklift.js），這裡只套用本專案的尺寸。
import { AGV, FORK } from './layout.js';
import { create } from '@core/models/agv-forklift.js';

export function createAgv(scene) {
  const agv = create({
    rear: AGV.rear, halfW: AGV.halfW, mast: AGV.mast, mastLowered: AGV.mastLowered, backrest: AGV.backrest,
    forkStart: AGV.fork[0], forkEnd: AGV.fork[1], forkHalf: AGV.forkHalf, palletX: AGV.palletX, deck: FORK.deck,
  });
  scene.add(agv.root);
  return agv;
}
