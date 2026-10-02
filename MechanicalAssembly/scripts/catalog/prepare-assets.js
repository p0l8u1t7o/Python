import fs from "node:fs";
fs.mkdirSync("public/vendor", { recursive: true });
for (const file of ["occt-import-js.js", "occt-import-js.wasm"])
  fs.copyFileSync(
    `node_modules/occt-import-js/dist/${file}`,
    `public/vendor/${file}`,
  );
fs.copyFileSync("src/cad/cad-worker.js", "public/cad-worker.js");
