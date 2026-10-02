import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { AssemblyViewer } from "../src/scene-viewer.js";

test("camera frames an isolated small part without including hidden assembly bounds", () => {
  const part = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.2, 0.1));
  part.position.set(4, -2, 3);
  part.geometry.computeBoundingBox();
  const hidden = new THREE.Mesh(new THREE.BoxGeometry(100, 100, 100));
  hidden.geometry.computeBoundingBox();
  hidden.visible = false;
  const camera = new THREE.PerspectiveCamera(36, 0.6, 0.01, 500);
  const controls = {
    target: new THREE.Vector3(),
    update() {
      camera.lookAt(this.target);
      camera.updateMatrixWorld();
    },
  };
  const viewer = { meshes: [part, hidden], camera, controls };
  AssemblyViewer.prototype.fit.call(viewer);
  assert.ok(controls.target.distanceTo(part.position) < 1e-6);
  assert.ok(camera.position.distanceTo(controls.target) < 2);
  for (const x of [-0.05, 0.05])
    for (const y of [-0.1, 0.1])
      for (const z of [-0.05, 0.05]) {
        const p = new THREE.Vector3(x, y, z).add(part.position).project(camera);
        assert.ok(Math.abs(p.x) < 1 && Math.abs(p.y) < 1);
        assert.ok(p.z > -1 && p.z < 1);
      }
  hidden.visible = true;
  AssemblyViewer.prototype.fit.call(viewer);
  assert.ok(camera.position.distanceTo(controls.target) > 100);
  part.geometry.dispose();
  hidden.geometry.dispose();
  part.material.dispose();
  hidden.material.dispose();
});
