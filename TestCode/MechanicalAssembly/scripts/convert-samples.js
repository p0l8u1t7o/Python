import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import * as THREE from "three";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
const require = createRequire(import.meta.url);
const occt = await require("occt-import-js")();
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
const source = path.resolve("../Temp/自動爆炸圖與拆圖CAD設計");
const picks = [
  ["202401-AA00", "202401-AA00 機架外罩/202401-AD01.STEP", "局部機架"],
  ["202401-BA00", "202401-BA00 台車/202401-BA00(Magzin).STEP", "台車組合件"],
  ["202401-CA00", "202401-CA00 conveyorⅡ/202401-CD80.STEP", "局部輸送部件"],
  [
    "202401-DA00",
    "202401-DA00 升降/RA065-1A-G10-HD-R2020-L550.stp",
    "局部升降模組",
  ],
  [
    "202401-EA00",
    "202401-EA00 入水除泡/注水/ABNZN5-1.0-100.stp",
    "局部注水部件",
  ],
  ["202401-HA00", "202401-HA00 NG排除/202401-HD02.STEP", "局部排除部件"],
  ["202401-IA00", "202401-IA00 水下移載/202401-ID68.STEP", "局部移載部件"],
];
fs.mkdirSync("public/models", { recursive: true });
const manifest = {};
for (const [id, file, scope] of picks) {
  console.log("Reading", id, file);
  const result = occt.ReadStepFile(fs.readFileSync(path.join(source, file)), {
    linearUnit: "millimeter",
    linearDeflectionType: "bounding_box_ratio",
    linearDeflection: 0.002,
    angularDeflection: 0.5,
  });
  if (!result.success || !result.meshes.length)
    throw new Error("Cannot read " + file);
  const root = new THREE.Group();
  root.name = id;
  result.meshes.forEach((m, i) => {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(m.attributes.position.array, 3),
    );
    if (m.attributes.normal)
      geometry.setAttribute(
        "normal",
        new THREE.Float32BufferAttribute(m.attributes.normal.array, 3),
      );
    geometry.setIndex(m.index.array);
    if (!m.attributes.normal) geometry.computeVertexNormals();
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({
        color: m.color
          ? new THREE.Color(...m.color)
          : new THREE.Color("#b7c6d0"),
        metalness: 0.3,
        roughness: 0.5,
      }),
    );
    mesh.name = m.name || `Part ${i + 1}`;
    mesh.userData = { sourceIndex: i };
    root.add(mesh);
  });
  const buffer = await new GLTFExporter().parseAsync(root, { binary: true });
  fs.writeFileSync(`public/models/${id}.glb`, Buffer.from(buffer));
  manifest[id] = {
    url: `models/${id}.glb`,
    source: file,
    scope,
    parts: result.meshes.length,
    hierarchy: result.root,
  };
  console.log(
    "Saved",
    id,
    result.meshes.length,
    "parts",
    buffer.byteLength,
    "bytes",
  );
}
fs.writeFileSync(
  "public/data/model-manifest.json",
  JSON.stringify(manifest, null, 2),
);
