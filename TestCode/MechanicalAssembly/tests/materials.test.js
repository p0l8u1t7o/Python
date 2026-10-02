import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { displayMaterial } from "../src/materials.js";

test("recover missing catalog CAD finish without replacing imported PBR", () => {
  const source = new THREE.MeshStandardMaterial({ metalness: 1, roughness: 1 });
  const recovered = displayMaterial(source, "shaft", "auto", {
    cadSource: true,
  });
  assert.ok(recovered.roughness < 0.4);
  assert.equal(recovered.userData.appearanceSource, "inferred");
  const imported = displayMaterial(source, "shaft");
  assert.equal(imported.roughness, 1);
  assert.equal(imported.color.getHex(), 0xffffff);
  assert.equal(imported.userData.appearanceSource, "source");
  source.roughnessMap = new THREE.Texture();
  const textured = displayMaterial(source, "shaft", "auto", {
    cadSource: true,
  });
  assert.equal(textured.roughnessMap, source.roughnessMap);
  assert.equal(textured.roughness, 1);
  assert.equal(source.color.getHex(), 0xffffff);
});

test("CAD face colors and transparency survive inferred finish and override reset", () => {
  const source = new THREE.MeshStandardMaterial({
    color: "#d94126",
    transparent: true,
    opacity: 0.6,
    depthWrite: false,
  });
  source.userData.materialSource = "cad-color";
  const automatic = displayMaterial(source, "shaft");
  assert.equal(automatic.color.getHex(), source.color.getHex());
  assert.equal(automatic.opacity, 0.6);
  assert.equal(automatic.transparent, true);
  assert.equal(automatic.depthWrite, false);
  const rubber = displayMaterial(source, "shaft", "rubber");
  assert.equal(rubber.metalness, 0);
  assert.ok(rubber.roughness > 0.8);
  assert.equal(rubber.opacity, 1);
  assert.equal(rubber.transparent, false);
  const restored = displayMaterial(source, "shaft");
  assert.equal(restored.color.getHex(), source.color.getHex());
  assert.equal(restored.opacity, 0.6);
  assert.equal(source.roughness, 1);
});

test("unspecified CAD receives distinct metal, polymer and transparent finishes", () => {
  const source = new THREE.MeshStandardMaterial();
  source.userData.materialSource = "unspecified";
  const metal = displayMaterial(source, "shaft");
  const rubber = displayMaterial(source, "rubber seal");
  const glass = displayMaterial(source, "acrylic cover");
  assert.equal(metal.metalness, 1);
  assert.equal(rubber.metalness, 0);
  assert.ok(rubber.roughness > metal.roughness);
  assert.ok(glass.transmission > 0.8);
  assert.equal(glass.depthWrite, false);
  assert.equal(source.metalness, 0);
  assert.equal(source.transparent, false);
});
