import assert from 'node:assert/strict';
import * as THREE from 'three';
import { createStation } from '../web/js/station.js';
import { createSequence } from '../web/js/sequence.js';
import { RECIPES } from '../web/js/recipes.js';
import { cameraSource, stationPreviewTime, sensorViewport, SENSOR_ASPECT } from '../web/js/camera-view.js';

globalThis.document = { createElement: () => ({ getContext: () => ({ fillRect() {}, fillText() {} }) }) };
let frames = 0;
for (const [key, recipe] of Object.entries(RECIPES)) {
  for (const insert of recipe.multiPad ? ['single', 'bar'] : ['single']) {
    const scene = new THREE.Scene(), st = createStation(scene, recipe, insert);
    const seq = createSequence({ ...st, recipe, insert });
    const preview = seq.sample(stationPreviewTime(seq, 3)); st.robot.snap();
    assert(preview.step.exposure, `${key}: station shortcut must land at exposure`);
    assert.equal(cameraSource(preview.state, preview.step, true), 'wrist');
    for (const step of seq.steps) {
      const { state } = seq.sample(step.start + step.dur / 2); st.robot.snap();
      if (step.station === 2 || step.motion) assert.equal(cameraSource(state, step, true), 'global');
      if (!step.exposure) continue;
      assert.equal(cameraSource(state, step, false), 'global', 'no wrist view before arrival');
      const cam = step.station === 1 ? st.cell.globalCam : st.robot.pipCam;
      cam.aspect = SENSOR_ASPECT; cam.updateProjectionMatrix(); cam.updateWorldMatrix(true, false);
      const ids = step.station === 1 ? st.product.ids : state.shot === 'R' ? [recipe.stubborn.id] : seq.shots[+state.shot].map(c => c.id);
      for (const id of ids) {
        const bounds = new THREE.Box3().setFromObject(st.product.conns[id].pivot);
        for (const x of [bounds.min.x,bounds.max.x]) for (const y of [bounds.min.y,bounds.max.y]) for (const z of [bounds.min.z,bounds.max.z]) {
          const p = new THREE.Vector3(x,y,z).project(cam);
          assert(Math.abs(p.x) < .98 && Math.abs(p.y) < .98 && p.z > -1 && p.z < 1,
            `${key}/${insert}: ${step.action} clips USB ${id}: ${p.toArray()}`);
        }
      }
      frames++;
    }
  }
}
// Responsive layouts must retain the full sensor, including all four USBs.
for (const [w,h] of [[360,205],[230,131],[240,110],[180,120],[80,40]]) {
  const v = sensorViewport(w,h);
  assert(Math.abs(v.width/v.height-SENSOR_ASPECT)<1e-10);
  assert(v.x>=0 && v.y>=0 && v.x+v.width<=w+1e-9 && v.y+v.height<=h+1e-9);
}
console.log(`PASS: ${frames} camera exposures contain complete USB geometry; station shortcuts, travel preview and responsive sensor framing verified.`);
