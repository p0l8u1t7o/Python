import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
const source = path.resolve("../Temp/自動爆炸圖與拆圖CAD設計");
const inventory = JSON.parse(
  fs.readFileSync("public/data/source-inventory.json", "utf8"),
);
const native = Object.values(
  JSON.parse(fs.readFileSync("public/data/native-manifest.json", "utf8")),
);
const nativeByPath = new Map(native.map((x) => [x.source, x]));
fs.mkdirSync("public/models/cad", { recursive: true });
const cadFormats = [
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
];
const extra = [
  { id: "LOAD", name: "上料機", folder: "Load machine" },
  { id: "UNLOAD", name: "下料機", folder: "UnLoad machine" },
  { id: "WET", name: "入水設備", folder: "入水站" },
  { id: "LINE", name: "自動線總裝", folder: "自動線規劃" },
  { id: "TRAY", name: "Tray 盤與治具", folder: "Tray盤" },
  { id: "CHIP", name: "晶片與待測物", folder: "晶片3D_250312" },
  { id: "SHARED", name: "共用件與 2D 圖面", folder: "" },
];
const stations = [
  ...inventory.stations.map(({ id, name, folder }) => ({ id, name, folder })),
  ...extra,
];
const locate = (file) =>
  inventory.stations.find((s) => file.path.startsWith(s.folder + "/"))?.id ||
  extra.find(
    (s) =>
      s.folder && file.path.toLowerCase().startsWith(s.folder.toLowerCase()),
  )?.id ||
  "SHARED";
const items = [];
for (const [index, file] of inventory.files
  .filter((f) => cadFormats.includes(f.format))
  .entries()) {
  const id = createHash("sha1").update(file.path).digest("hex").slice(0, 16);
  let item = {
    id,
    source: file.path,
    name: file.name,
    format: file.format,
    bytes: file.bytes,
    stationId: locate(file),
    scope: "待轉換",
    parts: 0,
    status: "unsupported",
    diagnostics: [],
  };
  const n = nativeByPath.get(file.path);
  if (n) {
    item = { ...item, ...n, status: n.url ? "ready" : "unavailable" };
    if (n.counts?.missing || n.counts?.unsupported || n.counts?.rejectedFaces)
      item.scope += " · 部分還原";
  }
  if (["step", "stp", "igs", "iges"].includes(file.format)) {
    const out = `public/models/cad/${id}.glb`,
      meta = out + ".meta.json";
    if (
      !fs.existsSync(out) ||
      !fs.existsSync(meta) ||
      !JSON.parse(fs.readFileSync(meta)).triangles
    ) {
      console.log("Converting", file.path);
      let result = spawnSync(
        process.execPath,
        [
          "--max-old-space-size=8192",
          "scripts/convert-cad-file.js",
          path.join(source, file.path),
          out,
        ],
        { encoding: "utf8", timeout: 240000, maxBuffer: 1024 * 1024 },
      );
      if (result.status !== 0 && ["step", "stp"].includes(file.format)) {
        console.log("Trying desktop OpenCascade", file.path);
        result = spawnSync(
          "python",
          ["scripts/convert-step-native.py", path.join(source, file.path), out],
          { encoding: "utf8", timeout: 600000, maxBuffer: 1024 * 1024 },
        );
      }
      if (result.status !== 0) {
        item.diagnostics.push(
          (result.error?.message || result.stderr || "CAD 轉換失敗").slice(
            -1200,
          ),
        );
        console.log("Failed", file.path);
      }
    }
    if (
      fs.existsSync(out) &&
      fs.existsSync(meta) &&
      JSON.parse(fs.readFileSync(meta)).triangles > 0
    ) {
      item = {
        ...item,
        ...JSON.parse(fs.readFileSync(meta)),
        url: out.replace("public/", ""),
        scope: "精細 CAD 網格",
        geometrySource: "cad-tessellation",
        status: "ready",
      };
    }
  }
  if (!item.url && !item.diagnostics.length)
    item.diagnostics.push(
      file.format === "x_t"
        ? "Parasolid 需經授權 CAD 軟體轉成 STEP。"
        : ["dwg", "slddrw"].includes(file.format)
          ? "此檔為工程圖面，不等同 3D 組合件。"
          : "未能從來源取得支援的幾何。",
    );
  items.push(item);
}
const preferred = {
  "202401-AA00": "202401-AA01.SLDASM",
  "202401-BA00": "202401-BA00(Magzin).STEP",
  "202401-CA00": "202401-CA01.SLDASM",
  "202401-DA00": "202401-DA01.SLDASM",
  "202401-EA00": "202401-EA00.SLDASM",
  "202401-FA00": "202401-FA00.SLDASM",
  "202401-GA00": "202401-GA00.SLDASM",
  "202401-HA00": "202401-HA00.SLDASM",
  "202401-IA00": "202401-IA00.SLDASM",
  "202401-JA00": "202401-JA00.SLDASM",
  LOAD: "Load machine_240608.STEP",
  UNLOAD: "UnLoad machine_240608.STEP",
  WET: "入水站.SLDASM",
  LINE: "自動線規劃_240503.SLDASM",
  TRAY: "Tray盤組件-5.STEP",
};
const assemblies = fs.existsSync("public/data/station-models.json")
  ? JSON.parse(fs.readFileSync("public/data/station-models.json", "utf8"))
  : [];
for (const s of stations) {
  const entries = items.filter((i) => i.stationId === s.id);
  s.itemIds = entries.map((i) => i.id);
  s.ready = entries.filter((i) => i.url).length;
  s.defaultAsset =
    entries.find((i) => i.name === preferred[s.id])?.id ||
    entries.find((i) => i.url)?.id ||
    entries[0]?.id;
  if (
    ["202401-AA00", "202401-CA00", "202401-DA00", "202401-HA00"].includes(s.id)
  ) {
    const detailed = assemblies
      .filter((a) => a.stationId === s.id)
      .sort((a, b) => b.parts - a.parts)[0];
    if (detailed) s.defaultAsset = detailed.id;
  }
}
const catalog = {
  revision: "2026-10-02-v2",
  stations,
  items,
  assemblies,
  summary: {
    files: inventory.files.length,
    cadFiles: items.length,
    ready: items.filter((i) => i.url).length,
    remaining: items.filter((i) => !i.url).length,
  },
};
fs.writeFileSync(
  "public/data/cad-catalog.json",
  JSON.stringify(catalog, null, 2),
);
console.log("CATALOG", JSON.stringify(catalog.summary));
