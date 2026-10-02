import { looseName } from "../project/names.js";
// 將 CAD 的節點階層整理成「組裝單元」樹：
// - unit：子組合件，內部先預組，再整組裝上父層
// - atomic：一次搬動的剛體（單一零件、多實體零件或購入品）

const GENERIC = /^(|\?|auxscene|scene|assembly|root|group|object3d|part[ _]\d+|零件 \d+)$/i;
const VENDOR =
  /^(MISUMI|SMC|THK|HIWIN|IKO|NSK|NTN|OMRON|KEYENCE|FESTO|CKD|ORIENTAL|PANASONIC|MITSUBISHI|AIRTAC|SICK|IAI|YASKAWA|TOYO|KHK|OILES|IGUS|PISCO|KOGANEI|AUTONICS)[_\- ]/i;
// 多實體購入品常被拆成「BODY_料號」「COVER_料號」這類同層網格
const BODY_PREFIX = /^([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)_(.+)$/;
const FASTENER =
  /(screw|bolt|(^|[_\s-])nut([_\s-]|$)|hexagon_nut|washer|rivet|retaining[_\s-]?ring|snap[_\s-]?ring|circlip|(^|_)pin(_|$)|dowel|螺絲|螺栓|螺帽|螺母|墊圈|華司|鉚釘|扣環|定位銷|平行銷|SET-SCREW|SHCS|BHCS|FHCS|JIS_B_1(1|2)\d\d|JIS_B_2804|DIN[ _-]?(912|933|934|125|7991|7985|985|471|472)|ISO[ _-]?(4762|4017|4032|7380|10642|7089)|(^|_)NAT-M\d|(^|_)HZGN-M\d|(^|[_\s])M\d{1,2}(\.\d)?[xX×]\d+)/i;

// 可撓件：皮帶、鏈條、線材、氣管，剛體拆卸判斷不適用，於相接零件就位後再安裝
const FLEXIBLE =
  /(belt|chain|cable|wire|hose|tube|皮帶|鏈條|電纜|線材|配線|氣管|軟管|管線)/i;

export function isFastenerName(name) {
  return FASTENER.test(String(name || "")) || FASTENER.test(looseName(String(name || "")));
}
export function isFlexibleName(name) {
  return FLEXIBLE.test(String(name || "")) || FLEXIBLE.test(looseName(String(name || "")));
}

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
    // 購入品由銷＋擋圈等多個實體組成時，拆開交由父層排序（擋圈先拆、銷沿軸抽出）
    const bodyNames = kids.map((c) => data.meshes[leafMesh(c)]?.name || "");
    const loose = bodyNames.filter((n) => isFastenerName(n)).length;
    if (
      start !== topIndex &&
      !ownMesh &&
      kids.every((c) => leafMesh(c) >= 0) &&
      kids.length > 1 &&
      loose > 0
    )
      return { flatten: kids.map(build) };
    // 最上層一律視為組裝，不套用多實體／購入品規則
    const top = start === topIndex;
    if (top) {
      const entities = groupBodies(
        kids.flatMap((c) => {
          const e = build(c);
          return e.flatten || [e];
        }),
        make,
      );
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
    let entities = kids.flatMap((c) => {
      const e = build(c);
      return e.flatten || [e];
    });
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
