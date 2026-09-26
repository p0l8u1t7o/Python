import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import * as THREE from 'three';
import { createSim } from '../web/js/sim.js';
import { minimumGap, sampleTimes } from '../../tools/geometry-clearance.mjs';

globalThis.document = { createElement: () => ({ getContext: () => ({ fillRect() {}, fillText() {} }) }) };
const sim = createSim(new THREE.Scene()), { robot, plan } = sim;
let closest = { gap: Infinity }, samples = 0;
for (const step of plan.steps) {
  // The robot is stationary during waits; include both state boundaries.
  const times = sampleTimes(step.start, step.dur, step.kind === 'wait' ? step.dur || 1 : .05);
  for (const time of times) {
    sim.apply(time);
    const clearance = minimumGap(robot.clearanceParts.arm, robot.clearanceParts.tool);
    if (clearance.gap < closest.gap) closest = { ...clearance, time, action: step.label };
    samples++;
  }
}
const result = { method: 'conservative oriented mesh bounds, mm; <= 50 ms motion intervals and exact step endpoints', samples, closest };
writeFileSync(new URL('../review/self-clearance.json', import.meta.url), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
assert(closest.gap >= 5, 'gripper must stay at least 5 mm from arm bounds (mounting flange excluded)');
