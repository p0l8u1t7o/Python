// Geometry regression: true holes, layered thickness, bevel envelope and dynamic instance visibility.
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { createBoard, coinGeometry } from '../web/js/board.js';
import { PRODUCT, HOLES, RECIPES, setRecipe } from '../web/js/layout.js';
for (const recipe of Object.keys(RECIPES)) {
  setRecipe(recipe);
  const geo = coinGeometry(); geo.computeBoundingBox();
  const bounds = geo.boundingBox, size = bounds.getSize(new THREE.Vector3());
  assert.ok(Math.abs(size.x - PRODUCT.coin.w) < .001, 'bevel must preserve width');
  assert.ok(Math.abs(size.z - PRODUCT.coin.l) < .001, 'bevel must preserve length');
  assert.ok(Math.abs(bounds.min.y) < .00001 && Math.abs(bounds.max.y - PRODUCT.coin.t) < .00001, 'bottom/top datum');
  const b = createBoard(), coins = b.group.getObjectByName('inserted-copper');
  b.group.updateMatrixWorld(true);
  const ray = new THREE.Raycaster();
  const hit = (x, z) => {
    ray.set(new THREE.Vector3(x, 10, z), new THREE.Vector3(0, -1, 0));
    return ray.intersectObject(b.group, true)[0];
  };
  const first = HOLES[0], last = HOLES.at(-1);
  assert.equal(hit(first.x, first.z).object.name, 'adhesive', 'empty hole must expose backing');
  assert.equal(hit(0, 0).object.name, 'top-copper');
  assert.ok(Math.abs(hit(0, 0).point.y - PRODUCT.board.t - PRODUCT.board.adhesive) < .00001);
  assert.ok(coins.boundingSphere.radius > 150, 'bounds must include all inserts before count increases');
  b.setCoins(1);
  assert.equal(hit(first.x, first.z).object.name, 'inserted-copper');
  assert.ok(Math.abs(hit(first.x, first.z).point.y - PRODUCT.coin.t - PRODUCT.board.adhesive) < .00001);
  assert.equal(hit(last.x, last.z).object.name, 'adhesive');
  b.setCoins(HOLES.length);
  assert.equal(hit(last.x, last.z).object.name, 'inserted-copper');
  const camera = new THREE.PerspectiveCamera(40, 1.5, .1, 1000);
  camera.position.set(last.x + 6, 15, last.z + 20); camera.lookAt(last.x, 1, last.z); camera.updateMatrixWorld(true);
  const frustum = new THREE.Frustum().setFromProjectionMatrix(new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
  assert.ok(frustum.intersectsObject(coins), 'camera must not cull inserts after initially empty board');
  b.setCoins(0); assert.equal(hit(first.x, first.z).object.name, 'adhesive', 'reverse seeking clears inserts');
  console.log(`${recipe}: bevel dimensions, true holes, layer thickness, seated height, instance bounds and reverse seek passed`);
}
