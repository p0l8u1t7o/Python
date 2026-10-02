import fs from "node:fs";
import { createRequire } from "node:module";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { TESSELLATION, occtScene } from "../../src/cad/cad-geometry.js";
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
const [source, output] = process.argv.slice(2);
const require = createRequire(import.meta.url),
  occt = await require("occt-import-js")();
const result = occt[
  /\.i(gs|ges)$/i.test(source) ? "ReadIgesFile" : "ReadStepFile"
](fs.readFileSync(source), TESSELLATION);
const root = occtScene(result);
const binary = await new GLTFExporter().parseAsync(root, {
  binary: true,
  onlyVisible: false,
});
fs.writeFileSync(output, Buffer.from(binary));
let triangles = 0;
root.traverse((o) => {
  if (o.isMesh)
    triangles +=
      (o.geometry.index?.count || o.geometry.attributes.position.count) / 3;
});
fs.writeFileSync(
  output + ".meta.json",
  JSON.stringify({
    parts: result.meshes.length,
    triangles,
    bytes: binary.byteLength,
    quality: TESSELLATION,
    upAxis: "y",
  }),
);
console.log(
  JSON.stringify({
    source,
    parts: result.meshes.length,
    triangles,
    bytes: binary.byteLength,
  }),
);
