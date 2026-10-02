import { extractAssembly, serializeAssembly } from "./planner/extract.js";
import { PLANNER_VERSION } from "./planner/sequence.js";

/** 模型網格的零件 ID（與 extractAssembly 相同的走訪順序）。 */
export function meshPartIds(root) {
  const ids = [];
  root.traverse((o) => o.isMesh && ids.push(o.userData.partId));
  return ids;
}

export function meshNameSignature(root) {
  let hash = 2166136261;
  root.traverse((o) => {
    if (!o.isMesh) return;
    for (const ch of (o.userData.sourceName ?? o.name) + "|") {
      hash ^= ch.charCodeAt(0);
      hash = Math.imul(hash, 16777619) >>> 0;
    }
  });
  return hash.toString(16);
}

/** 在 Worker 中推論組裝順序；回傳推論結果與對應的零件 ID。 */
export function runPlanner(root, { onProgress, timeout = 600000 } = {}) {
  const partIds = meshPartIds(root);
  const { message, transfer } = serializeAssembly(extractAssembly(root));
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./planner-worker.js", import.meta.url), {
      type: "module",
    });
    const timer = setTimeout(() => {
      worker.terminate();
      reject(new Error("組裝順序推論超過時間上限，請按子組合件分站後再試。"));
    }, timeout);
    const end = () => {
      clearTimeout(timer);
      worker.terminate();
    };
    worker.onmessage = ({ data }) => {
      if (data.progress) return onProgress?.(data.progress);
      end();
      if (data.error) reject(new Error(data.error));
      else resolve({ result: data.result, partIds });
    };
    worker.onerror = (e) => {
      end();
      reject(new Error(e.message || "推論程式載入失敗。"));
    };
    worker.postMessage({ assembly: message }, transfer);
  });
}

let planIndex;
/** 讀取建庫時預先推論的結果；模型不一致時回傳 null。 */
export async function loadPrecomputedPlan(assetId, root) {
  if (!assetId) return null;
  try {
    planIndex ||= fetch("/data/plans/index.json")
      .then((r) => (r.ok ? r.json() : { assets: {} }))
      .catch(() => ({ assets: {} }));
    const available = await planIndex;
    if (available.plannerVersion !== PLANNER_VERSION || !available.assets?.[assetId])
      return null;
    const response = await fetch(`/data/plans/${assetId}.json`);
    if (!response.ok) return null;
    const saved = await response.json();
    const partIds = meshPartIds(root);
    if (
      saved.plannerVersion !== PLANNER_VERSION ||
      saved.partCount !== partIds.length ||
      saved.signature !== meshNameSignature(root)
    )
      return null;
    return { result: saved.result, partIds };
  } catch {
    return null;
  }
}
