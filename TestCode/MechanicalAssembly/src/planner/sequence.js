// 組裝順序推論：在每個組裝單元內，以「可拆卸方向」建立方向阻擋圖，
// 由外往內逐件拆下，反轉後即為組裝順序；緊固件插回它所鎖固零件之後。
import { Vector3 } from "three";
import { GeometryStore } from "./geometry.js";
import {
  buildEntityTree,
  isGenericName,
  isFastenerName,
  isFlexibleName,
  walkEntities,
} from "./hierarchy.js";

export { isFastenerName, isFlexibleName };

export const PLANNER_VERSION = 2;

const AXES = [
  new Vector3(1, 0, 0),
  new Vector3(-1, 0, 0),
  new Vector3(0, 1, 0),
  new Vector3(0, -1, 0),
  new Vector3(0, 0, 1),
  new Vector3(0, 0, -1),
];

/**
 * @param {{nodes, meshes, geometries}} data extractAssembly() 的結果
 * @param {{up?: number[], onProgress?: (done:number,total:number,label:string)=>void}} options
 */
export function planAssembly(data, options = {}) {
  const started = Date.now();
  const store = new GeometryStore(data);
  const tree = buildEntityTree(data);
  const up = new Vector3(...(options.up || [0, 1, 0])).normalize();
  const all = store.box(tree);
  const diag = all.getSize(new Vector3()).length() || 1;
  // 內縮公差需大於細分弦差（0.08 mm），且隨模型尺寸放大
  const tol = Math.max(0.25, diag * 2e-4);
  const units = [];
  walkEntities(tree, (e) => e.kind === "unit" && units.push(e));
  const totalWork = units.reduce((n, u) => n + u.children.length, 0) || 1;
  let done = 0;
  const report = (label) => options.onProgress?.(done, totalWork, label);
  const stats = { units: units.length, forced: 0, rays: 0, groups: 0 };
  const unitPlans = new Map();
  const ctx = {
    up,
    tol,
    diag,
    stats,
    debug: options.debug,
    cache: new Map(),
    unitPlans,
    serial: 0,
  };
  // 由下往上規劃：子單元先完成
  for (const unit of [...units].reverse()) {
    report(unit.name);
    planUnit(unit, store, ctx);
    done += unit.children.length;
  }
  report("完成");
  const result = emit(tree, unitPlans, data, up);
  result.stats = {
    ...stats,
    parts: data.meshes.length,
    nodes: result.nodes.length,
    steps: result.plan.length,
    milliseconds: Date.now() - started,
  };
  return result;
}

function candidateDirections(features, fastener = false) {
  const dirs = AXES.map((v) => ({ v, feature: false }));
  const extras = [features.axis, features.plate];
  if (fastener) extras.push(features.symmetry);
  for (const extra of extras) {
    if (!extra) continue;
    // 與座標軸幾乎平行時不重複加入，只標記為特徵方向
    for (const sign of [1, -1]) {
      const v = extra.clone().multiplyScalar(sign);
      const same = dirs.find((d) => d.v.dot(v) > 0.996);
      if (same) same.feature = true;
      else dirs.push({ v, feature: true });
    }
  }
  return dirs;
}

// 粗篩：j 沿 d 移動時，i 是否可能落在掃掠範圍內
function maybeInPath(store, j, i, d, tol) {
  const bj = store.box(j),
    bi = store.box(i);
  const u = Math.abs(d.x) < 0.9 ? new Vector3(1, 0, 0) : new Vector3(0, 1, 0);
  u.sub(d.clone().multiplyScalar(u.dot(d))).normalize();
  const w = new Vector3().crossVectors(d, u);
  const project = (box, axis) => {
    let min = Infinity,
      max = -Infinity;
    for (let k = 0; k < 8; k++) {
      const x = k & 1 ? box.max.x : box.min.x,
        y = k & 2 ? box.max.y : box.min.y,
        z = k & 4 ? box.max.z : box.min.z;
      const value = axis.x * x + axis.y * y + axis.z * z;
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
    return [min, max];
  };
  const overlap = (a, b) => a[0] < b[1] - tol && b[0] < a[1] - tol;
  if (!overlap(project(bj, u), project(bi, u))) return false;
  if (!overlap(project(bj, w), project(bi, w))) return false;
  return project(bi, d)[1] > project(bj, d)[0] + tol;
}

/**
 * 規劃一個單元；遇到互鎖時若找到「可一起移出的一群零件」（例如軸＋軸承），
 * 把它們包成臨時預組件，先組好再整組裝入，然後重新規劃本單元。
 */
function planUnit(unit, store, ctx) {
  for (;;) {
    const result = sequenceUnit(unit, store, ctx);
    if (!result.group) {
      ctx.unitPlans.set(unit, result);
      return;
    }
    const members = result.group.map((i) => unit.children[i]);
    const largest = members.reduce((a, b) =>
      store.analyze(a, ctx.tol, 360).volume >= store.analyze(b, ctx.tol, 360).volume ? a : b,
    );
    const virtual = {
      id: `v${ctx.serial++}`,
      kind: "unit",
      virtual: true,
      name: `${cleanName(largest.name)} 組件`,
      meshes: members.flatMap((m) => m.meshes),
      children: members,
    };
    const at = unit.children.indexOf(members[0]);
    unit.children = unit.children.filter((c) => !members.includes(c));
    unit.children.splice(Math.min(at, unit.children.length), 0, virtual);
    ctx.stats.groups++;
    planUnit(virtual, store, ctx);
  }
}

/** j 沿 v 移出時是否會撞到 i（雙向射線），結果依實體與方向快取。 */
function isBlocked(store, ctx, a, b, v) {
  const key = `${a.e.id}|${b.e.id}|${v.x.toFixed(4)},${v.y.toFixed(4)},${v.z.toFixed(4)}`;
  if (ctx.cache.has(key)) return ctx.cache.get(key);
  const limit = (f) => Math.max(2, Math.ceil(f.points.length / 100));
  let blocked = false;
  if (maybeInPath(store, a.e, b.e, v, ctx.tol)) {
    ctx.stats.rays += a.f.points.length;
    blocked = store.enteringHits(a.f.points, v, b.e, limit(a.f)) >= limit(a.f);
    if (!blocked) {
      ctx.stats.rays += b.f.points.length;
      blocked =
        store.enteringHits(b.f.points, v.clone().negate(), a.e, limit(b.f)) >= limit(b.f);
    }
  }
  ctx.cache.set(key, blocked);
  return blocked;
}

// Tarjan 強連通分量；edges(j) 回傳 j 會撞到的節點
function stronglyConnected(nodes, edges) {
  let index = 0;
  const order = new Map(),
    low = new Map(),
    stack = [],
    onStack = new Set(),
    out = [];
  const visit = (v) => {
    order.set(v, index);
    low.set(v, index++);
    stack.push(v);
    onStack.add(v);
    for (const w of edges(v)) {
      if (!order.has(w)) {
        visit(w);
        low.set(v, Math.min(low.get(v), low.get(w)));
      } else if (onStack.has(w)) low.set(v, Math.min(low.get(v), order.get(w)));
    }
    if (low.get(v) === order.get(v)) {
      const component = [];
      let w;
      do {
        w = stack.pop();
        onStack.delete(w);
        component.push(w);
      } while (w !== v);
      out.push(component);
    }
  };
  for (const v of nodes) if (!order.has(v)) visit(v);
  return out;
}

function removableGroup(info, blockers, present, base, up) {
  let best = null;
  AXES.forEach((axis, k) => {
    const nodes = [...present];
    const edges = (j) => blockers[j][k].filter((i) => present.has(i));
    for (const component of stronglyConnected(nodes, edges)) {
      if (component.length < 2 || component.includes(base)) continue;
      const inside = new Set(component);
      if (component.some((j) => edges(j).some((i) => !inside.has(i)))) continue;
      const volume = component.reduce((n, j) => n + info[j].f.volume, 0);
      const vertical = axis.dot(up);
      const score = component.length * 1e12 + volume - (vertical > 0.9 ? 1 : 0);
      if (!best || score < best.score) best = { score, component };
    }
  });
  return best?.component || null;
}

function sequenceUnit(unit, store, ctx) {
  const { tol, up, stats } = ctx;
  const children = unit.children;
  const info = children.map((e) => {
    const f = store.analyze(e, tol, 360);
    const names = [
      e.name,
      ...(e.meshes.length === 1 ? [store.meshes[e.meshes[0]].name] : []),
    ];
    // 擋圈、墊圈等薄環可變形或最後裝入，即使名稱未標示也以幾何辨識
    const ring = e.kind === "atomic" && store.isThinRing(e, f);
    const flexible = e.kind === "atomic" && names.some(isFlexibleName);
    const fastener =
      !flexible && e.kind === "atomic" && (names.some(isFastenerName) || ring);
    return {
      e,
      f,
      fastener: fastener || flexible,
      flexible,
      ring,
      dirs: candidateDirections(f, fastener || flexible),
      size: store.box(e).getSize(new Vector3()).length(),
    };
  });
  // blockers[j][k] = 沿第 k 個候選方向移出 j 時會撞到的兄弟索引
  const blockers = info.map((a, j) =>
    a.dirs.map(({ v }) =>
      info.flatMap((b, i) => (i !== j && isBlocked(store, ctx, a, b, v) ? [i] : [])),
    ),
  );
  const preference = (a, k) => {
    const { v, feature } = a.dirs[k];
    const vertical = v.dot(up);
    let score = vertical > 0.9 ? 3 : vertical < -0.9 ? 1 : 2;
    if (feature) score += a.fastener ? 2 : 0.5;
    return score;
  };
  const freeDirection = (j, present) => {
    let best = -1,
      bestScore = -Infinity;
    blockers[j].forEach((set, k) => {
      if (set.some((i) => present.has(i))) return;
      const score = preference(info[j], k);
      if (score > bestScore) {
        best = k;
        bestScore = score;
      }
    });
    return best;
  };
  // 結構件：反覆拆下目前可自由移出的零件，小件優先；最後剩下的就是基座
  let structural = info.map((_, i) => i).filter((i) => !info[i].fastener);
  let fasteners = info.map((_, i) => i).filter((i) => info[i].fastener);
  if (!structural.length) [structural, fasteners] = [fasteners, []];
  // 基座先決定：體積最大的結構件（機架、底板），拆卸過程中不移除
  const base = structural.reduce(
    (best, i) => (best < 0 || info[i].f.volume > info[best].f.volume ? i : best),
    -1,
  );
  const present = new Set(structural);
  const removal = [];
  let lastKey = null;
  while (present.size > 1) {
    let pick = -1,
      pickDir = -1,
      pickScore = Infinity;
    for (const j of present) {
      if (j === base) continue;
      const k = freeDirection(j, present);
      if (k < 0) continue;
      // 小件先拆；同形狀的零件連續處理，組裝時才能合併成一步
      const score = info[j].f.volume * (info[j].f.key === lastKey ? 1e-6 : 1);
      if (score < pickScore) {
        pick = j;
        pickDir = k;
        pickScore = score;
      }
    }
    let forced = false;
    if (pick < 0) {
      // 互鎖：找一群可沿同一方向一起移出的零件（方向阻擋圖中的匯點強連通分量）
      const group = removableGroup(info, blockers, present, base, up);
      if (group) return { group };
    }
    if (pick < 0) {
      // 仍無解（封閉、干涉）：取阻擋最少者，標記需工程審核
      let fewest = Infinity;
      for (const j of present) {
        if (j === base) continue;
        blockers[j].forEach((set, k) => {
          const n = set.filter((i) => present.has(i)).length;
          const score =
            n * 1e3 - preference(info[j], k) + (info[j].f.key === lastKey ? -0.5 : 0);
          if (score < fewest || (score === fewest && info[j].f.volume < info[pick].f.volume)) {
            fewest = score;
            pick = j;
            pickDir = k;
          }
        });
      }
      forced = true;
      stats.forced++;
    }
    if (forced && ctx.debug)
      ctx.debug.push({
        unit: unit.name,
        name: info[pick].e.name,
        dirs: blockers[pick].map((set, k) => ({
          dir: info[pick].dirs[k].v.toArray().map((x) => +x.toFixed(2)),
          by: set.filter((i) => present.has(i)).map((i) => info[i].e.name),
        })),
      });
    removal.push({ index: pick, dir: pickDir, forced });
    present.delete(pick);
    lastKey = info[pick].f.key;
  }
  const order = [];
  if (base >= 0)
    order.push({ index: base, dir: freeDirection(base, new Set()), base: true });
  for (const r of removal.reverse()) order.push(r);
  // 緊固件：接觸到的結構件都裝上之後才鎖入
  const contactLimit = 2;
  const nearDistance = tol * 4 + 0.1;
  const position = new Map(order.map((o, n) => [o.index, n]));
  const inserts = new Map();
  for (const f of fasteners) {
    const touching = structural.filter(
      (s) =>
        store.box(info[s].e).clone().expandByScalar(nearDistance).intersectsBox(store.box(info[f].e)) &&
        store.nearPoints(info[f].f.points, info[s].e, nearDistance, contactLimit) >= contactLimit,
    );
    const after = touching.length
      ? Math.max(...touching.map((s) => position.get(s)))
      : order.length - 1;
    if (!inserts.has(after)) inserts.set(after, []);
    inserts.get(after).push({ index: f, targets: touching });
  }
  const sequence = [];
  const installed = new Set();
  order.forEach((o, n) => {
    sequence.push({ ...o, kind: o.base ? "base" : "part" });
    installed.add(o.index);
    const group = inserts.get(n) || [];
    for (const g of group) {
      let k = freeDirection(g.index, installed);
      let forced = false;
      const axisDirs = info[g.index].dirs
        .map((d, kk) => (d.feature ? kk : -1))
        .filter((kk) => kk >= 0);
      if (k < 0 && axisDirs.length) {
        // 螺紋段與孔重疊是 CAD 常態：有軸向的緊固件一律沿軸向鎖入，不列為待確認
        k = axisDirs.reduce((best, kk) =>
          blockers[g.index][kk].filter((i) => installed.has(i)).length <
          blockers[g.index][best].filter((i) => installed.has(i)).length
            ? kk
            : best,
        );
      } else if (k < 0) {
        k = 0;
        let fewest = Infinity;
        blockers[g.index].forEach((set, kk) => {
          const count = set.filter((i) => installed.has(i)).length;
          if (count < fewest) {
            fewest = count;
            k = kk;
          }
        });
        forced = true;
        stats.forced++;
      }
      sequence.push({
        index: g.index,
        dir: k,
        kind: info[g.index].flexible ? "flexible" : "fasten",
        targets: g.targets,
        // 可撓件與擋圈不受剛體干涉限制，不標示為待確認
        forced: forced && !info[g.index].flexible && !info[g.index].ring,
      });
      installed.add(g.index);
    }
  });
  return { info, sequence };
}

const round = (v) => v.toArray().map((x) => Math.round(x * 1e6) / 1e6);

function directionText(v, up) {
  const vertical = v.dot(up);
  if (vertical > 0.9) return "由上方往下放入";
  if (vertical < -0.9) return "由下方往上裝入";
  const axes = [
    ["+X", 1, 0, 0],
    ["−X", -1, 0, 0],
    ["+Y", 0, 1, 0],
    ["−Y", 0, -1, 0],
    ["+Z", 0, 0, 1],
    ["−Z", 0, 0, -1],
  ];
  const named = axes.find(([, x, y, z]) => v.x * x + v.y * y + v.z * z > 0.996);
  return named ? `由 ${named[0]} 側推入` : "沿特徵軸向插入";
}

const cleanName = (name) =>
  String(name || "零件")
    // 去掉實例編號：_1、_#2、 #3（SolidWorks／STEP 的重複實例）
    .replace(/(?:[_ ]#\d+|_\d+)+$/, "")
    .replace(/^BODY_/, "");

// 將每個單元的順序展開成時間軸步驟：子單元的預組步驟排在該單元安裝前
function emit(tree, unitPlans, data, up) {
  const nodes = [];
  const partNode = new Array(data.meshes.length);
  const ids = new Map();
  let serial = 0;
  const register = (e, parentId, parentName = "", ordinal = 0) => {
    const id = e === tree ? "root" : `n${serial++}`;
    ids.set(e, id);
    // 來源未命名的實體以「所屬單元 零件 N」顯示
    if (isGenericName(e.name)) {
      e.unnamed = true;
      e.name = e === tree ? "總組裝" : `${parentName} 零件 ${ordinal}`;
    }
    const node = { id, name: e.name, parentId, kind: e.kind };
    if (e._features) node.geomKey = e._features.key;
    if (e.purchased) node.purchased = true;
    if (e.virtual) node.virtual = true;
    nodes.push(node);
    if (e.kind === "atomic") for (const m of e.meshes) partNode[m] = id;
    let unnamed = 0;
    for (const c of e.children)
      register(c, id, cleanName(e.name), isGenericName(c.name) ? ++unnamed : 0);
  };
  register(tree, null);
  const plan = [];
  const stepFor = (unit, items, kind, dir, extra) => ({
    unitId: ids.get(unit),
    nodeIds: items.map((x) => ids.get(x.e)),
    kind,
    axis: "auto",
    dir: kind === "base" ? round(up) : round(dir),
    distance: kind === "base" ? 0 : 1,
    ...extra,
  });
  const describe = (unit, items, kind, dir, targets, forced) => {
    const first = items[0].e;
    const label = cleanName(first.name);
    const count = items.length > 1 ? ` ×${items.length}` : "";
    const where = unit === tree ? "" : `【預組 ${cleanName(unit.name)}】`;
    let name, instruction;
    if (kind === "base") {
      name = `${where}放置基座 ${label}`;
      instruction = `將「${label}」放置於作業台面作為定位基準，確認方向與基準面。`;
    } else if (kind === "flexible") {
      const target = targets.length ? `「${cleanName(targets[0])}」等零件` : "相關零件";
      name = `${where}安裝 ${label}${count}`;
      instruction = `待${target}就位後，套上／佈設「${label}」${count ? `共 ${items.length} 件` : ""}，並依規格調整張力或固定。`;
    } else if (kind === "fasten" && items[0].ring) {
      const target = targets.length ? `「${cleanName(targets[0])}」` : "相關零件";
      name = `${where}裝上 ${label}${count}`;
      instruction = `${target}就位後裝上「${label}」${count ? `共 ${items.length} 件` : ""}（擋圈／墊圈），確認確實卡入槽內或貼合。`;
    } else if (kind === "fasten") {
      const target = targets.length ? `「${cleanName(targets[0])}」` : "相關零件";
      name = `${where}鎖固 ${label}${count}`;
      instruction = `以${count ? ` ${items.length} 支` : ""}「${label}」鎖固${target}，${directionText(dir, up)}；依圖面扭力鎖緊。`;
    } else if (first.virtual) {
      // 推論出的組件：CAD 沒有這一層，因互鎖必須先組合再一起裝入
      const parts = [...new Set(first.children.map((c) => cleanName(c.name)))];
      const list = parts.slice(0, 3).join("、") + (parts.length > 3 ? " 等" : "");
      name = `${where}安裝 ${label}${count}（先組合再裝入）`;
      instruction = `「${list}」彼此卡住，無法單獨裝入：請先將它們組合成「${label}」，再整組${directionText(dir, up)}。`;
    } else if (first.kind === "unit") {
      name = `${where}安裝 ${label}${count}（預組件）`;
      instruction = `將已預組完成的「${label}」${count ? `共 ${items.length} 組，` : ""}整組${directionText(dir, up)}，對準定位後固定。`;
    } else {
      name = `${where}安裝 ${label}${count}`;
      instruction = `將「${label}」${count ? `共 ${items.length} 件，` : ""}${directionText(dir, up)}至定位。`;
    }
    if (forced)
      instruction += " ⚠ 推論時找不到完全無干涉的方向，請工程師確認此步驟。";
    return { name, instruction };
  };
  const expand = (unit) => {
    const out = [];
    const push = (step) => out.push(step);
    const { info, sequence } = unitPlans.get(unit);
    // 相鄰、同形狀、同方向的零件合併為一步（例如 4 個腳輪、8 支螺絲）
    const groups = [];
    for (const s of sequence) {
      const a = info[s.index];
      const dir = a.dirs[s.dir]?.v || up;
      const last = groups.at(-1);
      const sameTarget =
        !last ||
        s.kind !== "fasten" ||
        String(last.targets?.[0] ?? "") === String(s.targets?.[0] ?? "");
      if (
        last &&
        last.kind === s.kind &&
        s.kind !== "base" &&
        last.key === a.f.key &&
        // 未命名實體只比形狀；有料號者需同名（避免左右對稱件被合併）
        (last.unnamed && a.e.unnamed
          ? true
          : last.label === cleanName(a.e.name)) &&
        last.dir.dot(dir) > 0.996 &&
        sameTarget
      ) {
        last.items.push(a);
        last.forced ||= s.forced;
      } else
        groups.push({
          kind: s.kind,
          key: a.f.key,
          label: cleanName(a.e.name),
          unnamed: !!a.e.unnamed,
          dir,
          items: [a],
          forced: !!s.forced,
          targets: s.targets,
          targetNames: (s.targets || []).map((t) => info[t].e.name),
        });
    }
    for (const g of groups) {
      // 子單元：先展開其預組步驟；同形狀多組時逐步合併成「×N」
      const subunits = g.items.filter((x) => x.e.kind === "unit");
      if (subunits.length) {
        const expanded = subunits.map((x) => expand(x.e));
        const same =
          expanded.every((list) => list.length === expanded[0].length) &&
          expanded[0].every((step, n) =>
            expanded.every((list) => list[n].signature === step.signature),
          );
        if (same && expanded.length > 1)
          expanded[0].forEach((_, n) => {
            const merged = { ...expanded[0][n] };
            merged.nodeIds = expanded.flatMap((list) => list[n].nodeIds);
            merged.name = merged.name.replace(/^【預組 (.+?)】/, `【預組 $1 ×${expanded.length} 組】`);
            push(merged);
          });
        else expanded.flat().forEach(push);
      }
      const text = describe(unit, g.items, g.kind, g.dir, g.targetNames, g.forced);
      push({
        ...stepFor(unit, g.items, g.kind, g.dir, {}),
        ...text,
        auto: { forced: g.forced },
        signature: `${g.kind}|${g.key}|${g.items.length}|${round(g.dir).join(",")}`,
      });
    }
    return out;
  };
  expand(tree).forEach((s, n) => {
    const { signature, ...rest } = s;
    plan.push({ id: `s${n + 1}`, reviewed: false, ...rest });
  });
  return { nodes, partNode, plan };
}
