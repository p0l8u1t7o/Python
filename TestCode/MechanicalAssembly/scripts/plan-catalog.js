// 建庫時預先推論各 CAD 模型的組裝順序，存成 public/data/plans/<assetId>.json。
// 瀏覽器開啟站別時直接讀取；模型或推論器版本不同時會改為即時推論。
// 用法：node --max-old-space-size=8192 scripts/plan-catalog.js [--all] [--limit=3000] [assetId...]
import fs from "node:fs";
import path from "node:path";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { normalizeGltf, describeParts, orientRoot } from "../src/importer.js";
import { extractAssembly } from "../src/planner/extract.js";
import { planAssembly, PLANNER_VERSION } from "../src/planner/sequence.js";
import { meshNameSignature } from "../src/planner-client.js";
import { catalogAssets } from "../src/catalog.js";

const args = process.argv.slice(2);
const all = args.includes("--all");
const limit = Number(args.find((a) => a.startsWith("--limit="))?.split("=")[1] || 3000);
const only = args.filter((a) => !a.startsWith("--"));
const catalog = JSON.parse(fs.readFileSync("public/data/cad-catalog.json", "utf8"));
const orientation = fs.existsSync("public/data/orientation.json")
  ? JSON.parse(fs.readFileSync("public/data/orientation.json", "utf8")).assets
  : {};
const assets = catalogAssets(catalog).filter((a) => a.url);
const defaults = new Set(catalog.stations.map((s) => s.defaultAsset));
const chosen = assets.filter((a) =>
  only.length ? only.includes(a.id) : all || defaults.has(a.id) || catalog.assemblies?.includes(a),
);
const outDir = "public/data/plans";
fs.mkdirSync(outDir, { recursive: true });
const indexFile = path.join(outDir, "index.json");
const index = fs.existsSync(indexFile)
  ? JSON.parse(fs.readFileSync(indexFile, "utf8"))
  : { plannerVersion: PLANNER_VERSION, assets: {} };
if (index.plannerVersion !== PLANNER_VERSION)
  Object.assign(index, { plannerVersion: PLANNER_VERSION, assets: {} });

for (const [n, asset] of chosen.entries()) {
  if ((asset.parts || 0) > limit) {
    console.log(`skip ${asset.id} ${asset.name}: ${asset.parts} parts > ${limit}`);
    continue;
  }
  const started = Date.now();
  try {
    const bytes = fs.readFileSync("public/" + asset.url);
    const scene = normalizeGltf(
      await new GLTFLoader().parseAsync(
        bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
        "",
      ),
    );
    // 與瀏覽器 loadSample() 相同的座標轉換（含逐一檢查後的朝上軸）
    const up = orientation[asset.id] || asset.upAxis || "y";
    orientRoot(scene, up);
    describeParts(scene, "catalog");
    const result = planAssembly(extractAssembly(scene));
    const file = path.join(outDir, `${asset.id}.json`);
    const record = {
      plannerVersion: PLANNER_VERSION,
      assetId: asset.id,
      source: asset.source,
      up,
      partCount: result.partNode.length,
      signature: meshNameSignature(scene),
      result,
    };
    fs.writeFileSync(file, JSON.stringify(record));
    index.assets[asset.id] = {
      steps: result.plan.length,
      forced: result.plan.filter((s) => s.auto?.forced).length,
      parts: result.partNode.length,
    };
    fs.writeFileSync(indexFile, JSON.stringify(index, null, 1));
    console.log(
      `${n + 1}/${chosen.length} ${asset.id} ${asset.name}: ${result.partNode.length} parts → ${result.plan.length} steps (${index.assets[asset.id].forced} flagged) ${Date.now() - started} ms`,
    );
  } catch (e) {
    console.log(`fail ${asset.id} ${asset.name}: ${e.message}`);
  }
}
