import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { occtMesh, occtScene } from "../../src/cad/cad-geometry.js";
import { normalizeGltf, describeParts } from "../../src/cad/importer.js";
import { displayMaterial } from "../../src/viewer/materials.js";
import { sourceProject, catalogAssets } from "../../src/ui/catalog.js";
import {
  flatAssembly,
  applyPlannerResult,
  validateProject,
} from "../../src/project/core.js";
import { meshNameSignature } from "../../src/planner/client.js";
const read = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
const catalog = read("public/data/cad-catalog.json");
const fixture = {
  name: "two color part",
  attributes: { position: { array: [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0] } },
  index: { array: [0, 1, 2, 1, 3, 2] },
  brep_faces: [
    { first: 0, last: 0, color: [1, 0, 0] },
    { first: 1, last: 1, color: [0, 0, 1] },
  ],
};
test("face colors preserve all triangles without splitting a mechanical part", () => {
  const mesh = occtMesh(fixture, 0);
  assert.equal(mesh.geometry.index.count, 6);
  assert.equal(mesh.geometry.groups.length, 2);
  const colors = mesh.geometry.groups.map((g) =>
    mesh.material[g.materialIndex].color.toArray(),
  );
  assert.deepEqual(colors, [
    [1, 0, 0],
    [0, 0, 1],
  ]);
  const root = occtScene({
    success: true,
    root: { name: "root", meshes: [0] },
    meshes: [fixture, { ...fixture, name: "unreferenced" }],
  });
  const parts = describeParts(root, "fixture");
  assert.equal(parts.length, 2);
  assert.ok(parts.some((p) => p.name === "unreferenced"));
  assert.throws(
    () =>
      occtScene({
        success: true,
        meshes: [
          { attributes: { position: { array: [] } }, index: { array: [] } },
        ],
      }),
    /三角網格/,
  );
});
test("display materials preserve supplied colors, transparency and maps; overrides are reversible", () => {
  const source = new THREE.MeshPhysicalMaterial({
    color: "#b35628",
    roughness: 0.27,
    metalness: 0.72,
    transparent: true,
    opacity: 0.4,
    clearcoat: 0.2,
  });
  source.normalMap = new THREE.Texture();
  source.normalScale.set(0.3, 0.8);
  const shown = displayMaterial(source, "rubber");
  assert.deepEqual(shown.color.toArray(), source.color.toArray());
  assert.equal(shown.opacity, 0.4);
  assert.equal(shown.normalMap, source.normalMap);
  assert.equal(shown.roughness, 0.27);
  assert.deepEqual(shown.normalScale.toArray(), source.normalScale.toArray());
  const override = displayMaterial(source, "part", "rubber");
  assert.equal(override.metalness, 0);
  assert.equal(override.opacity, 1);
  assert.equal(source.opacity, 0.4);
  assert.deepEqual(
    displayMaterial(source, "part").color.toArray(),
    source.color.toArray(),
  );
});
test("catalog covers every CAD file exactly once and all ten original stations plus root assemblies", () => {
  const inventory = read("public/data/source-inventory.json");
  const formats = new Set([
    "sldasm",
    "sldprt",
    "step",
    "stp",
    "igs",
    "iges",
    "brep",
    "x_t",
    "dwg",
    "slddrw",
    "smg",
  ]);
  const paths = inventory.files
    .filter((f) => formats.has(f.format))
    .map((f) => f.path)
    .sort();
  assert.deepEqual(catalog.items.map((a) => a.source).sort(), paths);
  assert.equal(new Set(catalog.items.map((a) => a.id)).size, paths.length);
  for (const s of inventory.stations)
    assert.ok(catalog.stations.some((x) => x.id === s.id));
  for (const id of ["LOAD", "UNLOAD", "WET", "LINE", "TRAY", "CHIP"])
    assert.ok(catalog.stations.some((s) => s.id === id));
  for (const a of catalog.items) {
    if (a.url) assert.ok(fs.existsSync("public/" + a.url), a.source);
    else assert.ok(a.diagnostics.length, a.source);
  }
  validateProject(sourceProject(catalog, "test"));
  const fa = catalog.items.find((a) => a.name === "202401-FA00.SLDASM");
  assert.equal(fa.parts, 0);
  assert.equal(fa.counts.suppressed, 6);
  assert.ok(!fa.url);
});
test("all catalog GLBs decode with finite placements, valid indices and the documented occurrence count", async () => {
  let files = 0,
    parts = 0;
  for (const asset of catalogAssets(catalog).filter((a) => a.url)) {
    const bytes = fs.readFileSync("public/" + asset.url),
      buffer = bytes.buffer.slice(
        bytes.byteOffset,
        bytes.byteOffset + bytes.byteLength,
      );
    const root = normalizeGltf(await new GLTFLoader().parseAsync(buffer, ""));
    root.updateMatrixWorld(true);
    let count = 0;
    const checked = new Set();
    root.traverse((o) => {
      if (!o.isMesh) return;
      count++;
      assert.ok(o.matrixWorld.elements.every(Number.isFinite), asset.source);
      if (checked.has(o.geometry)) return;
      checked.add(o.geometry);
      const geometry = o.geometry,
        p = geometry.attributes.position;
      assert.ok(p?.count > 0, asset.source);
      assert.ok(Array.from(p.array).every(Number.isFinite), asset.source);
      if (geometry.index) {
        assert.equal(geometry.index.count % 3, 0);
        for (const index of geometry.index.array)
          assert.ok(index < p.count, asset.source);
      }
      if (Array.isArray(o.material)) {
        assert.equal(
          geometry.groups.reduce((n, g) => n + g.count, 0),
          geometry.index?.count || p.count,
          asset.source,
        );
        for (const g of geometry.groups)
          assert.ok(o.material[g.materialIndex], asset.source);
      }
    });
    assert.equal(count, asset.parts, asset.source);
    files++;
    parts += count;
    if (catalog.stations.some((s) => s.defaultAsset === asset.id)) {
      const described = describeParts(root, asset.stationId);
      const station = flatAssembly({
        id: asset.stationId,
        name: asset.name,
        parts: described,
      });
      validateProject({ schemaVersion: 2, name: "fixture", stations: [station] });
      // 預先推論的組裝順序必須對得上目前的模型，且符合預組先後規則
      const planFile = `public/data/plans/${asset.id}.json`;
      if (fs.existsSync(planFile)) {
        const saved = read(planFile);
        assert.equal(saved.partCount, count, asset.source);
        assert.equal(saved.signature, meshNameSignature(root), asset.source);
        const ids = [];
        root.traverse((o) => o.isMesh && ids.push(o.userData.partId));
        applyPlannerResult(station, saved.result, ids);
        validateProject({ schemaVersion: 2, name: "plan", stations: [station] });
      }
    }
  }
  console.log(`Verified ${files} GLB files and ${parts} mesh occurrences.`);
});
