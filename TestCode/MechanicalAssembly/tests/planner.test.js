import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { describeParts } from "../src/importer.js";
import { extractAssembly } from "../src/planner/extract.js";
import { planAssembly } from "../src/planner/sequence.js";
import { buildEntityTree } from "../src/planner/hierarchy.js";
import { GeometryStore } from "../src/planner/geometry.js";
import { applyPlannerResult, flatAssembly, validateProject } from "../src/core.js";
import { repairName } from "../src/names.js";

const material = new THREE.MeshStandardMaterial();
const box = (w, h, d, x = 0, y = 0, z = 0) =>
  new THREE.BoxGeometry(w, h, d).translate(x, y, z);
const mesh = (name, geometry) => {
  const m = new THREE.Mesh(geometry, material);
  m.name = name;
  return m;
};
// 開口朝上的盒子（單位 mm）：底板＋四面牆，內部 80×60×80
const housing = () =>
  mesh(
    "Housing",
    mergeGeometries([
      box(100, 10, 100, 0, 5, 0),
      box(10, 60, 100, -45, 40, 0),
      box(10, 60, 100, 45, 40, 0),
      box(80, 60, 10, 0, 40, -45),
      box(80, 60, 10, 0, 40, 45),
    ]),
  );
const planScene = (root) => {
  const parts = describeParts(root, "t");
  const result = planAssembly(extractAssembly(root));
  const ids = [];
  root.traverse((o) => o.isMesh && ids.push(o.userData.partId));
  const station = flatAssembly({ id: "t", name: "T", parts });
  applyPlannerResult(station, result, ids);
  validateProject({ schemaVersion: 2, name: "p", stations: [station] });
  const nodeName = new Map(station.nodes.map((n) => [n.id, n.name]));
  const steps = station.plan.map((s) => ({
    ...s,
    names: s.nodeIds.map((id) => nodeName.get(id)),
  }));
  return { station, result, steps };
};

test("parts enclosed by a lid are installed before the lid, and only from the open side", () => {
  const root = new THREE.Group();
  root.add(housing());
  root.add(mesh("Block", box(40, 20, 40, 0, 20, 0)));
  root.add(mesh("Lid", box(100, 5, 100, 0, 72.5, 0)));
  const { steps } = planScene(root);
  const order = steps.flatMap((s) => s.names);
  assert.deepEqual(order, ["Housing", "Block", "Lid"]);
  assert.equal(steps[0].kind, "base");
  // 方塊只能從上方放入：展開方向為 +Y
  assert.deepEqual(steps[1].dir.map(Math.round), [0, 1, 0]);
  assert.ok(steps.every((s) => !s.auto?.forced));
});

test("screws are fastened right after the parts they clamp", () => {
  const root = new THREE.Group();
  root.add(housing());
  // 上蓋在 (±45, 30) 各留 6×6 的穿孔
  root.add(
    mesh(
      "Lid",
      mergeGeometries([
        box(100, 5, 77, 0, 72.5, -11.5),
        box(100, 5, 17, 0, 72.5, 41.5),
        box(2, 5, 6, -49, 72.5, 30),
        box(84, 5, 6, 0, 72.5, 30),
        box(2, 5, 6, 49, 72.5, 30),
      ]),
    ),
  );
  // 螺絲穿過上蓋鎖入牆面（螺牙段與牆重疊，模擬未建螺紋孔的 CAD）
  for (const [x, z] of [
    [45, 30],
    [-45, 30],
  ]) {
    const screw = new THREE.CylinderGeometry(2.5, 2.5, 14, 24).translate(x, 70, z);
    root.add(mesh("M5x14 screw", screw));
  }
  root.add(mesh("Block", box(40, 20, 40, 0, 20, 0)));
  const { steps } = planScene(root);
  assert.deepEqual(
    steps.map((s) => [s.kind, s.names[0], s.names.length]),
    [
      ["base", "Housing", 1],
      ["part", "Block", 1],
      ["part", "Lid", 1],
      ["fasten", "M5x14 screw", 2],
    ],
  );
  assert.match(steps[3].instruction, /鎖固/);
  assert.deepEqual(steps[3].dir.map(Math.round), [0, 1, 0]);
});

test("captive parts are flagged for engineering review instead of guessed silently", () => {
  const root = new THREE.Group();
  root.add(housing());
  // 完全封閉的盒中零件：上蓋與盒子併成同一件時，任何方向都拿不出來
  const closed = housing();
  closed.geometry = mergeGeometries([closed.geometry, box(100, 5, 100, 0, 72.5, 0)]);
  closed.name = "Closed housing";
  const scene = new THREE.Group();
  scene.add(closed);
  scene.add(mesh("Trapped", box(20, 20, 20, 0, 30, 0)));
  const { steps } = planScene(scene);
  assert.equal(steps[1].names[0], "Trapped");
  assert.equal(steps[1].auto.forced, true);
  assert.match(steps[1].instruction, /⚠/);
});

test("sub-assemblies are pre-assembled first, then installed as one unit", () => {
  const root = new THREE.Group();
  root.name = "Machine";
  root.add(mesh("Frame", box(200, 10, 200, 0, 5, 0)));
  const sub = new THREE.Group();
  sub.name = "Bracket assembly";
  sub.add(mesh("Bracket", box(40, 10, 40, 0, 15, 0)));
  sub.add(mesh("Post", box(10, 40, 10, 0, 40, 0)));
  sub.add(mesh("Cap", box(20, 4, 20, 0, 62, 0)));
  sub.add(mesh("Sensor", box(8, 8, 8, 15, 24, 15)));
  sub.add(mesh("Label", box(8, 1, 8, -15, 20.5, -15)));
  root.add(sub);
  const { steps, station } = planScene(root);
  const unit = station.nodes.find((n) => n.name === "Bracket assembly");
  assert.equal(unit.kind, "unit");
  const install = steps.findIndex((s) => s.nodeIds.includes(unit.id));
  const inside = steps.filter((s) =>
    s.nodeIds.some((id) => station.nodes.find((n) => n.id === id).parentId === unit.id),
  );
  assert.ok(inside.length >= 4);
  assert.ok(inside.every((s) => steps.indexOf(s) < install));
  assert.ok(inside.every((s) => s.name.startsWith("【預組 Bracket assembly】")));
  assert.equal(steps[install].names[0], "Bracket assembly");
});

test("thin rings with a through hole are recognised, solid discs are not", () => {
  const washer = new THREE.LatheGeometry(
    [
      new THREE.Vector2(5, 0),
      new THREE.Vector2(10, 0),
      new THREE.Vector2(10, 1),
      new THREE.Vector2(5, 1),
      new THREE.Vector2(5, 0),
    ],
    48,
  );
  const disc = new THREE.CylinderGeometry(10, 10, 1, 48);
  const root = new THREE.Group();
  root.add(mesh("W", washer));
  root.add(mesh("D", disc.translate(40, 0, 0)));
  describeParts(root, "r");
  const data = extractAssembly(root);
  const store = new GeometryStore(data);
  const tree = buildEntityTree(data);
  const result = Object.fromEntries(
    tree.children.map((e) => [e.name, store.isThinRing(e, store.analyze(e, 0.25, 360))]),
  );
  assert.deepEqual(result, { W: true, D: false });
});

test("Big5 part names mis-decoded as UTF-8 are restored, others untouched", () => {
  assert.equal(repairName("®ɳW¥ֱa_T10(C_835)"), "時規皮帶_T10(C_835)");
  assert.equal(repairName("SMC_®ø­µ¾¹-AN20-02"), "SMC_消音器-AN20-02");
  assert.equal(repairName("Tray½L²ե"), "Tray盤組");
  assert.equal(repairName("MISUMI_HFCL8-4040-B_NEW"), "MISUMI_HFCL8-4040-B_NEW");
  assert.equal(repairName("Café"), "Café");
});
