import assert from 'node:assert/strict';
import * as THREE from 'three';
import { createStation } from '../web/js/station.js';
import { createSequence } from '../web/js/sequence.js';
import { RECIPES } from '../web/js/recipes.js';
import { cameraArmClearance } from './self-clearance.mjs';

globalThis.document = { createElement: () => ({ getContext: () => ({ fillRect() {}, fillText() {} }) }) };
const report = [];
for (const [key, recipe] of Object.entries(RECIPES)) {
  for (const insert of recipe.multiPad ? ['bar', 'single'] : ['single']) {
    const st = createStation(new THREE.Scene(), recipe, insert);
    const seq = createSequence({ ...st, recipe, insert });
    // Reproduce the reported defect so a missing geometry set or a broken
    // overlap calculation cannot silently turn this into an always-green test.
    seq.sample(0); st.robot.snap();
    const oldPark = st.robot.poseFor('press', st.robot.getTcpWorld('press'), new THREE.Vector3(0, 0, -1));
    st.robot.setPose(oldPark); st.robot.snap();
    const original = cameraArmClearance(st.robot);
    assert(original.gap < -20 && original.arm === 'J2', 'original inward park must reproduce shoulder interference');
    let closest = { gap: Infinity }, samples = 0;
    for (const step of seq.steps) {
      const count = Math.max(2, Math.ceil(step.dur / .025));
      for (let i = 0; i <= count; i++) {
        const time = step.start + step.dur * i / count;
        seq.sample(time); st.robot.snap();
        const clearance = cameraArmClearance(st.robot);
        if (clearance.gap < closest.gap) closest = { ...clearance, time, action: step.action };
        samples++;
      }
    }
    report.push({ recipe: key, insert, samples, ...closest });
  }
}
console.log(JSON.stringify({ clearanceMethod: 'conservative oriented mesh bounds; mm', maxSampleInterval: .025, report }, null, 2));
assert(report.every(r => r.gap >= 5), 'camera assembly must keep at least 5 mm from arm bounds throughout the cycle');
