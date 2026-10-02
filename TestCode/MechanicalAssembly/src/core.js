// 專案資料格式 v2：零件 → 組裝節點樹（root／unit／atomic）→ 時間軸步驟。
// 每個非 root 節點恰好在一個步驟安裝；子單元的預組步驟必須在它被裝上之前。
export const SCHEMA_VERSION = 2;
export const uid = () => crypto.randomUUID();
export const AXES = ["auto", "radial", "x", "-x", "y", "-y", "z", "-z"];
const DEFAULT_INSTRUCTION =
  "確認零件位置與裝配方向；請由工程師依實際工法編輯此步驟。";

/** 舊版草稿：依高度分成最多 12 群，全部掛在 root 底下（推論失敗時的備援）。 */
export function makePlan(parts) {
  if (!parts.length) return [];
  const count = Math.min(12, parts.length),
    size = Math.ceil(parts.length / count);
  return Array.from({ length: Math.ceil(parts.length / size) }, (_, i) => ({
    id: uid(),
    name: `組裝群組 ${String(i + 1).padStart(2, "0")}`,
    kind: "part",
    unitId: "root",
    nodeIds: parts.slice(i * size, (i + 1) * size).map((p) => p.nodeId || p.id),
    instruction: DEFAULT_INSTRUCTION,
    axis: "radial",
    distance: 1,
    reviewed: false,
  }));
}

/** 每個零件各自成為 root 底下的節點（節點 ID 與零件 ID 相同）。 */
export function flatNodes(parts, name = "總組裝") {
  for (const p of parts) p.nodeId = p.id;
  return [
    { id: "root", name, parentId: null, kind: "unit" },
    ...parts.map((p) => ({
      id: p.id,
      name: p.name,
      parentId: "root",
      kind: "atomic",
    })),
  ];
}

export function flatAssembly(station) {
  station.nodes = flatNodes(station.parts, station.name);
  station.plan = makePlan(station.parts);
  station.planSource = "height-draft";
  return station;
}

/** 由推論器結果（以網格順序對應）寫入站別。 */
export function applyPlannerResult(station, result, partIdsByIndex) {
  const byId = new Map(station.parts.map((p) => [p.id, p]));
  if (partIdsByIndex.length !== result.partNode.length)
    throw new Error("推論結果與模型零件數不一致。");
  partIdsByIndex.forEach((id, i) => {
    const part = byId.get(id);
    if (!part) throw new Error("推論結果包含未知零件。");
    part.nodeId = result.partNode[i];
  });
  station.nodes = result.nodes.map((n) => ({ ...n }));
  station.plan = result.plan.map((s) => ({ ...s, id: uid() }));
  station.planSource = "geometry";
  station.planStats = result.stats;
  return station;
}

/** 自動產生、從未編輯的舊草稿，可直接改用推論結果。 */
export function isUntouchedDraft(station) {
  return (
    !station.plan?.length ||
    (station.planSource !== "geometry" &&
      station.plan.every(
        (s) =>
          !s.reviewed &&
          /^組裝群組 \d+$/.test(s.name) &&
          s.instruction === DEFAULT_INSTRUCTION,
      ))
  );
}

/** v1 專案（plan[].partIds）轉成 v2：保留原本的分組、方向與審核狀態。 */
export function migrateStation(s) {
  if (Array.isArray(s.nodes) && s.plan.every((step) => step.nodeIds)) return s;
  s.nodes = flatNodes(s.parts, s.name);
  s.plan = s.plan.map((step) => {
    const { partIds = [], ...rest } = step;
    return {
      kind: "part",
      unitId: "root",
      ...rest,
      nodeIds: step.nodeIds || [...partIds],
    };
  });
  return s;
}

export function migrateProject(p) {
  if (p && p.schemaVersion === 1 && Array.isArray(p.stations)) {
    p.stations.forEach((s) => {
      if (Array.isArray(s.parts) && Array.isArray(s.plan)) migrateStation(s);
      if (s.variants)
        for (const v of Object.values(s.variants))
          if (Array.isArray(v.parts) && Array.isArray(v.plan)) migrateStation(v);
    });
    p.schemaVersion = SCHEMA_VERSION;
  }
  return p;
}

export function validateStationAssembly(s) {
  const nodes = new Map();
  for (const n of s.nodes) {
    if (!n || typeof n.id !== "string" || nodes.has(n.id))
      throw new Error("組裝節點 ID 重複或缺漏。");
    if (!["unit", "atomic"].includes(n.kind) || typeof n.name !== "string")
      throw new Error("組裝節點格式不正確。");
    nodes.set(n.id, n);
  }
  const root = nodes.get("root");
  if (!root || root.parentId !== null || root.kind !== "unit")
    throw new Error("組裝節點缺少 root。");
  const childCount = new Map();
  for (const n of nodes.values()) {
    if (n.id === "root") continue;
    const parent = nodes.get(n.parentId);
    if (!parent || parent.kind !== "unit")
      throw new Error("組裝節點的上層不存在。");
    childCount.set(parent.id, (childCount.get(parent.id) || 0) + 1);
  }
  const partsOf = new Map();
  for (const p of s.parts) {
    const n = nodes.get(p.nodeId);
    if (!n || n.kind !== "atomic")
      throw new Error("零件未對應到可安裝的組裝節點。");
    partsOf.set(n.id, (partsOf.get(n.id) || 0) + 1);
  }
  for (const n of nodes.values()) {
    if (n.kind === "atomic" && !partsOf.get(n.id))
      throw new Error("組裝節點沒有任何零件。");
    if (n.kind === "unit" && !childCount.get(n.id) && s.parts.length)
      throw new Error("組裝單元沒有任何子項。");
  }
  // 祖先鏈不可形成迴圈
  for (const n of nodes.values()) {
    const seen = new Set();
    for (let c = n; c && c.id !== "root"; c = nodes.get(c.parentId)) {
      if (seen.has(c.id)) throw new Error("組裝節點形成循環。");
      seen.add(c.id);
    }
  }
  const stepOf = new Map();
  const steps = new Set();
  s.plan.forEach((step, i) => {
    if (
      !step.id ||
      steps.has(step.id) ||
      typeof step.name !== "string" ||
      typeof step.instruction !== "string" ||
      !Array.isArray(step.nodeIds) ||
      !step.nodeIds.length ||
      !AXES.includes(step.axis) ||
      (step.axis === "auto" &&
        !(
          Array.isArray(step.dir) &&
          step.dir.length === 3 &&
          step.dir.every(Number.isFinite) &&
          step.dir.some((x) => x !== 0)
        )) ||
      !Number.isFinite(step.distance) ||
      step.distance < 0 ||
      step.distance > 5
    )
      throw new Error("組裝步驟格式不正確。");
    steps.add(step.id);
    for (const id of step.nodeIds) {
      if (!nodes.has(id) || id === "root") throw new Error("步驟含未知的零件或組件。");
      if (stepOf.has(id)) throw new Error("步驟含重複的零件或組件。");
      stepOf.set(id, i);
    }
  });
  for (const n of nodes.values()) {
    if (n.id === "root") continue;
    if (!stepOf.has(n.id))
      throw new Error("每個零件與預組件必須恰好指派至一個組裝步驟。");
    if (n.parentId !== "root" && stepOf.get(n.id) >= stepOf.get(n.parentId))
      throw new Error(
        `「${n.name}」必須在其預組件「${nodes.get(n.parentId).name}」安裝前完成。`,
      );
  }
  return s;
}

export function validateProject(p) {
  migrateProject(p);
  if (
    !p ||
    p.schemaVersion !== SCHEMA_VERSION ||
    typeof p.name !== "string" ||
    !Array.isArray(p.stations) ||
    !p.stations.length
  )
    throw new Error("專案格式不正確，需 schemaVersion: 2 與至少一個站別。");
  const stationIds = new Set();
  for (const s of p.stations) {
    if (
      !s.id ||
      stationIds.has(s.id) ||
      typeof s.name !== "string" ||
      !Array.isArray(s.parts) ||
      !Array.isArray(s.plan)
    )
      throw new Error("站別資料不完整或 ID 重複。");
    stationIds.add(s.id);
    const ids = new Set(s.parts.map((x) => x.id));
    if (
      ids.size !== s.parts.length ||
      s.parts.some(
        (x) => typeof x.id !== "string" || typeof x.name !== "string",
      )
    )
      throw new Error("零件資料不完整或 ID 重複。");
    if (!s.parts.length && !s.plan.length) continue;
    if (!Array.isArray(s.nodes)) throw new Error("站別缺少組裝節點。");
    validateStationAssembly(s);
  }
  return p;
}

/** 從站別移除零件；節點或預組件變空時一併移除，空步驟刪除。 */
export function removePart(station, partId) {
  const part = station.parts.find((p) => p.id === partId);
  if (!part) return;
  station.parts = station.parts.filter((p) => p.id !== partId);
  const nodes = new Map(station.nodes.map((n) => [n.id, n]));
  const used = new Set(station.parts.map((p) => p.nodeId));
  const removed = new Set();
  for (let n = nodes.get(part.nodeId); n && n.id !== "root"; n = nodes.get(n.parentId)) {
    const alive =
      n.kind === "atomic"
        ? used.has(n.id)
        : station.nodes.some((c) => c.parentId === n.id && !removed.has(c.id));
    if (alive) break;
    removed.add(n.id);
  }
  station.nodes = station.nodes.filter((n) => !removed.has(n.id));
  station.plan = station.plan
    .map((s) => ({
      ...s,
      nodeIds: s.nodeIds.filter((id) => !removed.has(id)),
      reviewed: false,
    }))
    .filter((s) => s.nodeIds.length);
}

/** 將零件以獨立節點加入 root，並在最後新增一步待審核。 */
export function appendPart(station, part) {
  if (!station.nodes?.length) station.nodes = flatNodes([], station.name);
  part.nodeId = part.id;
  station.parts.push(part);
  station.nodes.push({
    id: part.id,
    name: part.name,
    parentId: "root",
    kind: "atomic",
  });
  station.plan.push({
    id: uid(),
    name: "移入零件",
    kind: "part",
    unitId: "root",
    nodeIds: [part.id],
    instruction: "請確認零件的新站別與裝配順序。",
    axis: "radial",
    distance: 1,
    reviewed: false,
  });
}

/** 檢視器用：每個節點的安裝步驟、每個零件由內而外的節點鏈。 */
export function assemblyIndex(station) {
  const nodes = new Map(station.nodes.map((n) => [n.id, n]));
  const stepOf = new Map();
  station.plan.forEach((s, i) => s.nodeIds.forEach((id) => stepOf.set(id, i)));
  const chains = new Map();
  for (const p of station.parts) {
    const chain = [];
    for (
      let n = nodes.get(p.nodeId);
      n && n.id !== "root";
      n = nodes.get(n.parentId)
    )
      chain.push(n.id);
    chains.set(p.id, chain);
  }
  const partsOf = new Map();
  for (const p of station.parts)
    for (const id of chains.get(p.id)) {
      if (!partsOf.has(id)) partsOf.set(id, []);
      partsOf.get(id).push(p.id);
    }
  return { nodes, stepOf, chains, partsOf };
}

// 每步的時間配置：前段淡入、中段移動、後段停留讓作業員閱讀
export const STEP_TIMING = Object.freeze({ start: 0.12, end: 0.72 });

/** 第 step 步在進度 progress 時的安裝比例（0 = 尚在展開位置，1 = 已就定位）。 */
export function installAmount(step, progress) {
  const t = (progress - step - STEP_TIMING.start) / (STEP_TIMING.end - STEP_TIMING.start);
  const c = Math.max(0, Math.min(1, t));
  return c * c * (3 - 2 * c);
}

/** 舊介面相容：回傳每個零件「尚未安裝」的比例（1 = 完全展開）。 */
export function partProgress(station, progress) {
  const { stepOf, chains } = assemblyIndex(station);
  const result = new Map();
  for (const [partId, chain] of chains) {
    const own = chain.length ? stepOf.get(chain[0]) : undefined;
    result.set(partId, own === undefined ? 0 : 1 - installAmount(own, progress));
  }
  return result;
}

export const escapeHTML = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
