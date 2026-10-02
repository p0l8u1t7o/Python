// 小型標準件（包裝 core/geom/hardware.js 的函式，讓目錄頁可預覽）：伺服馬達、光電感測器、腳座、壓力表。
import * as THREE from 'three';
import { motor as addMotor, sensor as addSensor, foot as addFoot, gauge as addGauge } from '../geom/hardware.js';

const group = name => { const g = new THREE.Group(); g.name = name; return g; };

export const motor = {
  meta: {
    id: 'motor', name: '伺服馬達', category: '標準件',
    params: { scale: { value: 1, min: .3, max: 2, step: .05, label: '比例' } },
    usage: "import { motor } from '@core/geom/hardware.js';\nmotor(parent, x, y, z, scale, yaw);",
  },
  create: (p = {}) => { const root = group('motor'); addMotor(root, 0, 120 * (p.scale ?? 1), 0, p.scale ?? 1); return { root }; },
};

export const sensor = {
  meta: {
    id: 'sensor', name: '光電感測器', category: '標準件', params: {},
    usage: "import { sensor } from '@core/geom/hardware.js';\nsensor(parent, x, y, z, yaw);",
  },
  create: () => { const root = group('sensor'); addSensor(root, 0, 40, 0); return { root }; },
};

export const foot = {
  meta: {
    id: 'foot', name: '腳座（含地腳螺栓）', category: '標準件',
    params: { size: { value: 160, min: 60, max: 400, step: 10, unit: 'mm', label: '邊長' } },
    usage: "import { foot } from '@core/geom/hardware.js';\nfoot(parent, x, z, size);   // 腳座要比立柱大，避免底面共面閃爍",
  },
  create: (p = {}) => { const root = group('foot'); addFoot(root, 0, 0, p.size ?? 160); return { root }; },
};

export const gauge = {
  meta: {
    id: 'gauge', name: '壓力表', category: '標準件', params: {},
    usage: "import { gauge } from '@core/geom/hardware.js';\ngauge(parent, x, y, z);",
  },
  create: () => { const root = group('gauge'); addGauge(root, 0, 80, 0); return { root }; },
};
