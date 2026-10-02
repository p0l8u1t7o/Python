// 推算每個 CAD 模型「哪一軸朝上」，寫入 public/data/orientation.json。
// 做法：從目視確認方向的總裝（seeds）出發，讀取每個引用零件／子組合件在總裝中的擺放旋轉，
// 反推它自身座標中的朝上軸；多處引用以多數決，再以新確定的組合件繼續往下推。
// 用法：node --max-old-space-size=8192 scripts/orient-catalog.js
import fs from "node:fs";
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { normalizeGltf, orientRoot } from "../src/importer.js";
import { catalogAssets } from "../src/catalog.js";

// 逐一目視檢查確認的模型（2026-10-02）：底面朝下、風扇過濾機組與燈號在上方
const VERIFIED = {
  "58fe07a480fbe9a1": "z", // 自動線規劃_240503.SLDASM：屋頂 FFU 在上
  "877d78ae26925422": "-z", // 入水站.SLDASM：腳座在 +Z 側
  "4c566f17b1d87118": "z", // 202401-EA00.SLDASM：立柱腳座朝下
  c0ed5e66385aba0c: "y", // 202401-GA00.SLDASM
  "1aa9432d8a8b8820": "z", // Tray盤組件-5.STEP：托盤平放
  "fe17654aeb3e4d96": "y", // Load machine_240608.STEP
  "9f33ecc4997ff6dc": "y", // UnLoad machine_240608.STEP
  "6f9a499bfbeeca04": "y", // 202401-BA00(Magzin).STEP：腳輪朝下
  "5a8b8d585d136e53": "z", // JM0004-AMS 晶片：平放，比照同系列 JM0004-POS 在總裝中的擺放
  "50811ff9e889803f": "y", // 202401-IA00.SLDASM：未出現在總裝，比照新版 IA01／IA02（總裝中為 y）
};
const AXES = [
  ["y", 0, 1, 0],
  ["-y", 0, -1, 0],
  ["z", 0, 0, 1],
  ["-z", 0, 0, -1],
  ["x", 1, 0, 0],
  ["-x", -1, 0, 0],
];
const catalog = JSON.parse(fs.readFileSync("public/data/cad-catalog.json", "utf8"));
const assets = catalogAssets(catalog).filter((a) => a.url);
const bySource = new Map();
for (const a of assets) {
  if (a.geometrySource !== "saved-display") continue;
  if (!bySource.has(a.source)) bySource.set(a.source, []);
  bySource.get(a.source).push(a);
}
const byId = new Map(assets.map((a) => [a.id, a]));
const decided = new Map(Object.entries(VERIFIED).map(([id, up]) => [id, { up, from: "目視確認" }]));
const votes = new Map();
const processed = new Set();

async function load(asset) {
  const bytes = fs.readFileSync("public/" + asset.url);
  return normalizeGltf(
    await new GLTFLoader().parseAsync(
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
      "",
    ),
  );
}
function axisOf(v) {
  let best = null,
    dot = -2;
  for (const [name, x, y, z] of AXES) {
    const d = v.x * x + v.y * y + v.z * z;
    if (d > dot) [best, dot] = [name, d];
  }
  return dot > 0.98 ? best : null;
}
async function propagate(asset) {
  processed.add(asset.id);
  const root = orientRoot(await load(asset), decided.get(asset.id).up);
  const own = asset.source;
  const q = new THREE.Quaternion(),
    p = new THREE.Vector3(),
    s = new THREE.Vector3();
  root.traverse((o) => {
    const source = o.userData?.sourcePath;
    if (!source || source === own || !bySource.has(source)) return;
    o.matrixWorld.decompose(p, q, s);
    // 世界上方 (+Y) 轉回此引用的自身座標
    const local = axisOf(new THREE.Vector3(0, 1, 0).applyQuaternion(q.invert()));
    if (!local) return;
    for (const target of bySource.get(source)) {
      if (!votes.has(target.id)) votes.set(target.id, new Map());
      const v = votes.get(target.id);
      v.set(local, (v.get(local) || 0) + 1);
    }
  });
}

for (let round = 0; round < 6; round++) {
  const pending = [...decided.keys()].filter(
    (id) => !processed.has(id) && byId.get(id)?.geometrySource === "saved-display",
  );
  if (!pending.length) break;
  for (const id of pending) await propagate(byId.get(id));
  for (const [id, v] of votes) {
    if (decided.has(id)) continue;
    const [up, count] = [...v].sort((a, b) => b[1] - a[1])[0];
    const total = [...v.values()].reduce((a, b) => a + b, 0);
    decided.set(id, { up, from: `總裝引用 ${count}/${total}` });
  }
  console.log(`round ${round + 1}: ${decided.size} assets decided`);
}

// 往上推：尚未判定的組合件，由已判定的子件在其中的擺放反推自身朝上軸
for (const asset of assets) {
  if (decided.has(asset.id) || asset.geometrySource !== "saved-display" || !/\.sldasm$/i.test(asset.source))
    continue;
  const root = await load(asset);
  root.updateMatrixWorld(true);
  const tally = new Map();
  const q = new THREE.Quaternion(),
    p = new THREE.Vector3(),
    s = new THREE.Vector3();
  root.traverse((o) => {
    const source = o.userData?.sourcePath;
    if (!source || source === asset.source) return;
    const child = (bySource.get(source) || []).find((c) => decided.has(c.id));
    if (!child) return;
    const [, x, y, z] = AXES.find(([n]) => n === decided.get(child.id).up);
    o.matrixWorld.decompose(p, q, s);
    const up = axisOf(new THREE.Vector3(x, y, z).applyQuaternion(q));
    if (up) tally.set(up, (tally.get(up) || 0) + 1);
  });
  if (!tally.size) continue;
  const [up, count] = [...tally].sort((a, b) => b[1] - a[1])[0];
  const total = [...tally.values()].reduce((a, b) => a + b, 0);
  decided.set(asset.id, { up, from: `子件反推 ${count}/${total}` });
}
// STEP 由整機分出的分站模型沿用整機方向；同名原生零件已判定者，STEP 版本比照
for (const asset of assets) {
  if (decided.has(asset.id)) continue;
  if (asset.sourceAsset && decided.has(asset.sourceAsset)) {
    decided.set(asset.id, { up: decided.get(asset.sourceAsset).up, from: "沿用整機 STEP" });
    continue;
  }
  if (asset.geometrySource !== "cad-tessellation") continue;
  const stem = asset.source.split("/").pop().replace(/\.(step|stp|igs|iges)$/i, "").toLowerCase();
  const twin = assets.find(
    (n) =>
      n.geometrySource === "saved-display" &&
      decided.has(n.id) &&
      n.source.split("/").pop().replace(/\.(sldprt|sldasm)$/i, "").toLowerCase() === stem,
  );
  if (twin) decided.set(asset.id, { up: decided.get(twin.id).up, from: `比照同名原生檔 ${twin.source}` });
}

const out = { revision: "2026-10-02", note: "模型自身座標中朝上的軸；未列出者為 y", assets: {}, evidence: {} };
for (const [id, { up, from }] of decided) {
  if (up !== "y") out.assets[id] = up;
  out.evidence[id] = { up, from, source: byId.get(id)?.source };
}
fs.writeFileSync("public/data/orientation.json", JSON.stringify(out, null, 1));
const tally = {};
for (const { up } of decided.values()) tally[up] = (tally[up] || 0) + 1;
console.log("decided", decided.size, "of", assets.length, tally);
