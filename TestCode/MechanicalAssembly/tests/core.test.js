import test from "node:test";
import assert from "node:assert/strict";
import {
  makePlan,
  flatAssembly,
  installAmount,
  partProgress,
  migrateProject,
  removePart,
  appendPart,
  validateProject,
  STEP_TIMING,
} from "../src/core.js";
import { safePath } from "../vite.config.js";
import path from "node:path";
const makeParts = () =>
  Array.from({ length: 153 }, (_, i) => ({ id: "p" + i, name: "Part " + i }));
const project = () => {
  const station = flatAssembly({ id: "s1", name: "Station", parts: makeParts() });
  return { schemaVersion: 2, name: "test", stations: [station] };
};
// 兩層：u1 預組件含 a、b，c 直接裝在 root
const nested = () => ({
  schemaVersion: 2,
  name: "nested",
  stations: [
    {
      id: "s",
      name: "S",
      parts: [
        { id: "a", name: "A", nodeId: "a" },
        { id: "b", name: "B", nodeId: "b" },
        { id: "c", name: "C", nodeId: "c" },
      ],
      nodes: [
        { id: "root", name: "S", parentId: null, kind: "unit" },
        { id: "u1", name: "U1", parentId: "root", kind: "unit" },
        { id: "a", name: "A", parentId: "u1", kind: "atomic" },
        { id: "b", name: "B", parentId: "u1", kind: "atomic" },
        { id: "c", name: "C", parentId: "root", kind: "atomic" },
      ],
      plan: [
        step("1", ["a"], "u1"),
        step("2", ["b"], "u1"),
        step("3", ["c"]),
        step("4", ["u1"]),
      ],
    },
  ],
});
function step(id, nodeIds, unitId = "root") {
  return {
    id,
    name: "step " + id,
    kind: "part",
    unitId,
    nodeIds,
    instruction: "",
    axis: "auto",
    dir: [0, 1, 0],
    distance: 1,
    reviewed: false,
  };
}
test("height draft covers every part once, with at most 12 groups", () => {
  const plan = makePlan(makeParts());
  assert.ok(plan.length <= 12);
  const ids = plan.flatMap((s) => s.nodeIds);
  assert.equal(ids.length, 153);
  assert.equal(new Set(ids).size, 153);
  assert.ok(plan.every((s) => !s.reviewed));
});
test("each step moves, then dwells so operators can read the instruction", () => {
  assert.equal(installAmount(2, 2), 0);
  assert.ok(installAmount(2, 2 + STEP_TIMING.start) < 1e-12);
  assert.equal(installAmount(2, 2 + STEP_TIMING.end), 1);
  assert.equal(installAmount(2, 2.99), 1);
  const mid = installAmount(2, 2 + (STEP_TIMING.start + STEP_TIMING.end) / 2);
  assert.ok(Math.abs(mid - 0.5) < 1e-9);
  const station = project().stations[0];
  const pending = partProgress(station, 1.5);
  assert.equal(pending.get(station.plan[0].nodeIds[0]), 0);
  assert.equal(pending.get(station.plan[2].nodeIds[0]), 1);
});
test("project validation rejects duplicate, omitted and unknown assignments", () => {
  validateProject(project());
  const p = project();
  p.stations[0].plan[0].nodeIds.push("p0");
  assert.throws(() => validateProject(p), /重複/);
  const missing = project();
  missing.stations[0].plan[0].nodeIds.shift();
  assert.throws(() => validateProject(missing), /恰好/);
  const unknown = project();
  unknown.stations[0].plan[0].nodeIds.push("unknown");
  assert.throws(() => validateProject(unknown), /未知/);
});
test("a sub-assembly must be complete before it is installed", () => {
  validateProject(nested());
  const p = nested();
  const plan = p.stations[0].plan;
  [plan[1], plan[3]] = [plan[3], plan[1]];
  assert.throws(() => validateProject(p), /預組件/);
});
test("project validation rejects unsupported schema and invalid directions", () => {
  const p = project();
  p.schemaVersion = 3;
  assert.throws(() => validateProject(p));
  const q = project();
  q.stations[0].plan[0].axis = "q";
  assert.throws(() => validateProject(q));
  const r = nested();
  r.stations[0].plan[0].dir = [0, 0, 0];
  assert.throws(() => validateProject(r), /格式/);
});
test("v1 projects keep their groups, directions and review marks", () => {
  const v1 = {
    schemaVersion: 1,
    name: "old",
    stations: [
      {
        id: "s",
        name: "S",
        parts: [
          { id: "x", name: "X" },
          { id: "y", name: "Y" },
        ],
        plan: [
          { id: "1", name: "G1", partIds: ["y"], instruction: "i", axis: "-z", distance: 2, reviewed: true },
          { id: "2", name: "G2", partIds: ["x"], instruction: "", axis: "radial", distance: 1, reviewed: false },
        ],
      },
    ],
  };
  const p = validateProject(migrateProject(v1));
  assert.equal(p.schemaVersion, 2);
  const [first] = p.stations[0].plan;
  assert.deepEqual(first.nodeIds, ["y"]);
  assert.equal(first.axis, "-z");
  assert.equal(first.reviewed, true);
});
test("moving a part out removes emptied sub-assemblies and steps", () => {
  const p = nested();
  const s = p.stations[0];
  removePart(s, "a");
  removePart(s, "b");
  assert.ok(!s.nodes.some((n) => n.id === "u1"));
  assert.deepEqual(
    s.plan.map((x) => x.nodeIds),
    [["c"]],
  );
  appendPart(s, { id: "z", name: "Z" });
  validateProject(p);
});
test("local CAD service confines source paths to its configured root", () => {
  const root = path.resolve("public");
  assert.equal(safePath(root, "models/a.glb"), path.join(root, "models/a.glb"));
  for (const input of ["../private", "../../a", "D:\\secrets", "x\0y"])
    assert.throws(() => safePath(root, input));
});
