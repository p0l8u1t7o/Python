// 將 CAD 的節點階層整理成「組裝單元」樹：
// - unit：子組合件，內部先預組，再整組裝上父層
// - atomic：一次搬動的剛體（單一零件、多實體零件或購入品）

const GENERIC = /^(|\?|auxscene|scene|assembly|root|group|object3d|part[ _]\d+|零件 \d+)$/i;
const VENDOR =
  /^(MISUMI|SMC|THK|HIWIN|IKO|NSK|NTN|OMRON|KEYENCE|FESTO|CKD|ORIENTAL|PANASONIC|MITSUBISHI|AIRTAC|SICK|IAI|YASKAWA|TOYO|KHK|OILES|IGUS|PISCO|KOGANEI|AUTONICS)[_\- ]/i;
// 多實體購入品常被拆成「BODY_料號」「COVER_料號」這類同層網格
const BODY_PREFIX = /^([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)_(.+)$/;
const MULTI_BODY_LIMIT = 4;
const PURCHASED_LIMIT = 60;

export function isGenericName(name) {
  return GENERIC.test(String(name || "").trim());
}

export function buildEntityTree(data) {
  const { nodes } = data;
  const counts = new Array(nodes.length).fill(0);
  const countUnder = (i) => {
    let n = nodes[i].mesh >= 0 ? 1 : 0;
    for (const c of nodes[i].children) n += countUnder(c);
    counts[i] = n;
    return n;
  };
  const topIndex = nodes.findIndex((n) => n.parent < 0);
  countUnder(topIndex);
  const meshesUnder = (i, out = []) => {
    if (nodes[i].mesh >= 0) out.push(nodes[i].mesh);
    for (const c of nodes[i].children) meshesUnder(c, out);
    return out;
  };
  let serial = 0;
  const make = (kind, name, meshes, children = [], extra = {}) => ({
    id: kind === "unit" ? `u${serial++}` : `a${serial++}`,
    kind,
    name,
    meshes,
    children,
    ...extra,
  });
  const leafMesh = (i) => {
    // 單一網格外包一層群組時，視為同一個零件
    let j = i;
    while (nodes[j].mesh < 0) {
      const kids = nodes[j].children.filter((c) => counts[c] > 0);
      if (kids.length !== 1) return -1;
      j = kids[0];
    }
    return counts[j] === 1 ? nodes[j].mesh : -1;
  };
  const build = (start) => {
    const chain = [start];
    let i = start;
    while (nodes[i].mesh < 0) {
      const kids = nodes[i].children.filter((c) => counts[c] > 0);
      if (kids.length !== 1) break;
      i = kids[0];
      chain.push(i);
    }
    const name =
      chain.map((c) => nodes[c].name).find((n) => !isGenericName(n)) ||
      nodes[i].name ||
      "";
    const meshes = meshesUnder(i);
    if (meshes.length === 1) return make("atomic", name, meshes);
    const kids = nodes[i].children.filter((c) => counts[c] > 0);
    const ownMesh = nodes[i].mesh >= 0;
    // 最上層一律視為組裝，不套用多實體／購入品規則
    const top = start === topIndex;
    if (top) {
      const entities = groupBodies(kids.map(build), make);
      if (entities.length === 1 && entities[0].kind === "unit") return entities[0];
      return make("unit", name, meshes, entities);
    }
    if (
      ownMesh ||
      (kids.length <= MULTI_BODY_LIMIT &&
        kids.every((c) => leafMesh(c) >= 0) &&
        kids.every((c) => nodes[c].children.length === 0))
    )
      return make("atomic", name, meshes, [], { multiBody: true });
    if (VENDOR.test(name) && meshes.length <= PURCHASED_LIMIT)
      return make("atomic", name, meshes, [], { purchased: true });
    let entities = kids.map(build);
    entities = groupBodies(entities, make);
    if (entities.length === 1) return entities[0];
    return make("unit", name, meshes, entities);
  };
  const tree = build(topIndex);
  if (tree.kind === "atomic") return make("unit", tree.name, tree.meshes, [tree]);
  return tree;
}

function groupBodies(entities, make) {
  const groups = new Map();
  for (const e of entities) {
    if (e.kind !== "atomic" || e.meshes.length !== 1) continue;
    const m = BODY_PREFIX.exec(e.name);
    if (!m) continue;
    const suffix = m[2];
    if (suffix.length < 6 || !/[0-9]/.test(suffix) || !/[-_]/.test(suffix))
      continue;
    if (!groups.has(suffix)) groups.set(suffix, []);
    groups.get(suffix).push(e);
  }
  const merged = new Map();
  for (const [suffix, members] of groups) {
    if (members.length < 2) continue;
    const atomic = make(
      "atomic",
      suffix,
      members.flatMap((m) => m.meshes),
      [],
      { multiBody: true, purchased: VENDOR.test(suffix) },
    );
    for (const m of members) merged.set(m, atomic);
  }
  if (!merged.size) return entities;
  const out = [];
  const seen = new Set();
  for (const e of entities) {
    const target = merged.get(e) || e;
    if (seen.has(target)) continue;
    seen.add(target);
    out.push(target);
  }
  return out;
}

export function walkEntities(tree, fn, parent = null, depth = 0) {
  fn(tree, parent, depth);
  for (const c of tree.children) walkEntities(c, fn, tree, depth + 1);
}
