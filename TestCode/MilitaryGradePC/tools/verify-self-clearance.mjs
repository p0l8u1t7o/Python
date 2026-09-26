import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import * as THREE from 'three';
import { createNotebook, NB, selectSku } from '../web/js/notebook.js';
import { createCell, LAYOUT } from '../web/js/cell.js';
import { createRobot } from '../web/js/robot.js';
import { createSequence } from '../web/js/sequence.js';
import { minimumGap, sampleTimes } from '../../tools/geometry-clearance.mjs';

globalThis.document = { createElement: () => ({ getContext: () => ({ fillRect() {}, fillText() {} }) }) };
const report = [], failures = [];
for (const sku of ['V110-STND', 'V110-RF']) {
  selectSku(sku);
  const scene = new THREE.Scene(), nb = createNotebook(), cell = createCell(scene), robot = createRobot();
  scene.add(nb.root, robot.root); robot.root.position.z = LAYOUT.railZ;
  const carrier = new THREE.Group(); scene.add(carrier); carrier.add(nb.root); nb.root.position.y = -NB.H / 2;
  const top = LAYOUT.conveyorTop + 6 + LAYOUT.palletH + LAYOUT.padH + LAYOUT.footOffset;
  const apply = s => {
    carrier.position.set(s.palletX, top + s.palletLift + s.lift + NB.H / 2, 0); carrier.rotation.x = Math.PI * s.flip;
    nb.doors.forEach((d, i) => d.set(s.doors[i].open, s.doors[i].latch));
    cell.cradle.lift.position.y = top + NB.H / 2 + s.cradleLift;
    cell.cradle.rot.rotation.x = Math.PI * s.flip; cell.cradle.setClamp(s.cradleClamp);
    cell.setHead(s.s1Head); scene.updateMatrixWorld(true);
  };
  const seq = createSequence({ nb, robot, apply });
  const parts = robot.clearanceParts;
  const ring = parts.tool.find(m => m.name === 'ring-light'), profiler = parts.tool.find(m => m.name === 'profiler');
  const staticGap = minimumGap([ring], [profiler]);
  if (staticGap.gap < 5) failures.push({ sku, kind: 'tool-components', ...staticGap });
  let closest = { gap: Infinity }, productGap = { gap: Infinity }, cradleGap = { gap: Infinity }, samples = 0;
  const cradle = []; cell.cradle.lift.traverse(m => { if (m.isMesh) cradle.push(m); });
  // Solid chassis layers only: door contact by the hook/press pad is intended,
  // but the optical housings must never pass through the notebook chassis.
  const chassis = nb.root.children.slice(0, 3);
  for (const step of seq.steps) for (const time of sampleTimes(step.start, step.dur, .05)) {
    seq.sample(time); robot.snap();
    const self = minimumGap(parts.arm, parts.tool);
    if (self.gap < closest.gap) closest = { ...self, time, action: step.action };
    const product = minimumGap(parts.optics, chassis);
    if (product.gap < productGap.gap) productGap = { ...product, time, action: step.action };
    const movingFixture = minimumGap(parts.tool, cradle);
    if (movingFixture.gap < cradleGap.gap) cradleGap = { ...movingFixture, time, action: step.action };
    samples++;
  }
  if (closest.gap < 5) failures.push({ sku, kind: 'arm-tool', ...closest });
  if (productGap.gap < 2) failures.push({ sku, kind: 'optics-chassis', ...productGap });
  if (cradleGap.gap < 5) failures.push({ sku, kind: 'tool-flip-cradle', ...cradleGap });
  report.push({ sku, samples, ringProfiler: staticGap.gap, closest, productGap, cradleGap });
}
const result = { method: 'conservative oriented mesh bounds, mm; exact step endpoints and <= 50 ms intervals', report, failures };
writeFileSync(new URL('../review/self-clearance.json', import.meta.url), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
assert.equal(failures.length, 0, 'tool/arm or optical housing interference');
