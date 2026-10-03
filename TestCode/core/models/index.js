// 共用模型清單：目錄頁（core/catalog）依此列出。新增模型時在這裡登記。
// 每個模型提供 meta（名稱、分類、可調參數、可動狀態、用法）與 create(params) → { root, set?(state) }。
import * as conveyor from './conveyor.js';
import * as gantry from './gantry.js';
import { motor, sensor, foot, gauge } from './hardware.js';
import * as agvForklift from './agv-forklift.js';
import * as drum200l from './drum-200l.js';

export const MODELS = [conveyor, gantry, agvForklift, drum200l, motor, sensor, foot, gauge];
