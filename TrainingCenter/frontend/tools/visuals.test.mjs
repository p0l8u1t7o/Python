import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import * as THREE from 'three';
import { advanceTime, cyclePosition } from '../src/three/animationTime.ts';
import { rotateAroundPivot, translateAlongAxis } from '../src/three/modelAnimation.ts';
import { prepareModel } from '../src/three/modelMaterials.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const readJson = rel => JSON.parse(readFileSync(path.join(root, rel), 'utf8'));

test('every seeded component/card resolves to a nonempty GLB and PNG, including clean checkouts', () => {
  const manifest = readJson('frontend/src/assets/component-visuals.json');
  const components = ['aoi', 'fuel-cell', 'robot-cell', 'transfer'].flatMap(slug => readJson(`backend/catalog/seed/${slug}.json`).modules.flatMap(m => m.components));
  for (const c of components) assert.ok(manifest.components[c.slug], c.slug);
  for (const c of readJson('backend/training/seed/knowledge_cards.json')) assert.ok(manifest.cards[c.code], c.code);
  for (const model of new Set([...Object.values(manifest.components), ...Object.values(manifest.cards)])) {
    const base = path.join(root, 'frontend/public/component-visuals', model);
    assert.ok(existsSync(`${base}.png`), `${model} thumbnail missing`);
    const glb = readFileSync(`${base}.glb`);
    assert.equal(glb.toString('ascii', 0, 4), 'glTF');
    assert.equal(glb.readUInt32LE(8), glb.length);
    const json = JSON.parse(glb.toString('utf8', 20, 20 + glb.readUInt32LE(12)));
    assert.ok(json.meshes?.length > 0, model);
    const png = readFileSync(`${base}.png`);
    assert.equal(png.readUInt32BE(16), 640);
    assert.equal(png.readUInt32BE(20), 480);
  }
});

test('pause excludes wall-clock time; speed changes preserve phase; stalls are capped', () => {
  let t = advanceTime(2, 1 / 60, true);
  t = advanceTime(t, 40, false);
  assert.equal(t, 2 + 1 / 60);
  assert.equal(advanceTime(t, 1 / 60, true, 2), t + 1 / 30);
  assert.equal(advanceTime(0, 8, true), 0.1);
  const steps = [{ name: 'feed', dur: 2 }, { name: 'inspect', dur: 3 }];
  assert.deepEqual(cyclePosition(7, steps), { i: 1, p: 0, name: 'inspect', round: 1 });
  assert.deepEqual(cyclePosition(10, steps), { i: 0, p: 0, name: 'feed', round: 2 });
});

test('CAD rotation retains authored offset and orientation; repeated frames do not drift', () => {
  const node = new THREE.Object3D();
  const position = new THREE.Vector3(5, 2, 0);
  const rest = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), 0.3);
  const pivot = new THREE.Vector3(3, 2, 0);
  const rotation = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2);
  for (let i = 0; i < 100; i++) rotateAroundPivot(node, position, rest, pivot, rotation);
  assert.ok(node.position.distanceTo(new THREE.Vector3(3, 4, 0)) < 1e-10);
  assert.ok(node.quaternion.angleTo(rotation.clone().multiply(rest)) < 1e-7);
  translateAlongAxis(node, position, new THREE.Vector3(0, 1, 0), 0.03);
  assert.equal(node.position.x, 5);
  assert.equal(node.position.y, 2.03);
});

test('instances keep independent transforms/material arrays and retain shared geometry', () => {
  const source = new THREE.Group();
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(), [new THREE.MeshStandardMaterial({ color: '#123456' }), new THREE.MeshStandardMaterial({ color: '#aaaaaa' })]);
  source.add(mesh);
  const a = prepareModel(source), b = prepareModel(source);
  a.children[0].material[0].color.set('#ff0000');
  a.position.x = 99;
  assert.equal(source.position.x, 0);
  assert.equal(b.position.x, 0);
  assert.equal(mesh.material[0].color.getHexString(), '123456');
  assert.equal(b.children[0].material[0].color.getHexString(), '123456');
  assert.equal(a.children[0].geometry, mesh.geometry);
});
