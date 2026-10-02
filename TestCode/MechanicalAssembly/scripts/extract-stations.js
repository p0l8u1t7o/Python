// Preserve actual STEP placements while exposing its named station assemblies.
import fs from "node:fs";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { normalizeGltf } from "../src/importer.js";
globalThis.FileReader = class {
  async readAsArrayBuffer(blob) {
    this.result = await blob.arrayBuffer();
    this.onloadend?.();
  }
  async readAsDataURL(blob) {
    this.result =
      "data:application/octet-stream;base64," +
      Buffer.from(await blob.arrayBuffer()).toString("base64");
    this.onloadend?.();
  }
};
const catalog = JSON.parse(
  fs.readFileSync("public/data/cad-catalog.json", "utf8"),
);
const extracted = [];
fs.mkdirSync("public/models/stations", { recursive: true });
for (const source of catalog.items.filter(
  (a) =>
    ["LOAD", "UNLOAD"].includes(a.stationId) &&
    a.geometrySource === "cad-tessellation",
)) {
  const bytes = fs.readFileSync("public/" + source.url);
  const scene = normalizeGltf(
    await new GLTFLoader().parseAsync(
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
      "",
    ),
  );
  scene.updateMatrixWorld(true);
  const groups = new Map();
  const walk = (node) => {
    const match = /^202401-([A-J])A\d\d(?:$|[^0-9])/.exec(node.name);
    if (match && node.children.length) {
      const id = `202401-${match[1]}A00`;
      if (!groups.has(id)) groups.set(id, []);
      groups.get(id).push(node);
      return;
    }
    for (const child of node.children) walk(child);
  };
  walk(scene);
  for (const [stationId, nodes] of groups) {
    const root = new THREE.Group();
    root.name = stationId;
    let parts = 0,
      triangles = 0;
    for (const original of nodes) {
      const clone = original.clone(true);
      original.matrixWorld.decompose(
        clone.position,
        clone.quaternion,
        clone.scale,
      );
      root.add(clone);
    }
    root.traverse((o) => {
      if (o.isMesh) {
        parts++;
        triangles +=
          (o.geometry.index?.count || o.geometry.attributes.position.count) / 3;
      }
    });
    if (!parts) continue;
    const id = `${source.id}-${stationId}`,
      url = `models/stations/${id}.glb`;
    const binary = await new GLTFExporter().parseAsync(root, {
      binary: true,
      onlyVisible: false,
    });
    fs.writeFileSync("public/" + url, Buffer.from(binary));
    extracted.push({
      id,
      stationId,
      name: `${stationId} · ${source.stationId === "LOAD" ? "上料機" : "下料機"} STEP 分站`,
      source: source.source,
      sourceAsset: source.id,
      assemblyNames: nodes.map((n) => n.name),
      format: "step",
      parts,
      triangles,
      bytes: binary.byteLength,
      url,
      upAxis: "y",
      quality: source.quality,
      geometrySource: "cad-tessellation",
      scope: "設備 STEP 分站模型",
      status: "ready",
      diagnostics: [],
    });
    console.log(
      stationId,
      source.stationId,
      parts,
      "parts",
      triangles,
      "triangles",
    );
  }
}
fs.writeFileSync(
  "public/data/station-models.json",
  JSON.stringify(extracted, null, 2),
);
