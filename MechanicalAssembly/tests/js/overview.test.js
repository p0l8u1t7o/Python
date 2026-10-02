import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { overviewEntries } from "../../src/ui/overview-data.js";
import { sourceProject, catalogAssets } from "../../src/ui/catalog.js";

test("overview includes all stations, preserves absent geometry and marks partial line assembly", () => {
  const catalog = JSON.parse(
    fs.readFileSync("public/data/cad-catalog.json", "utf8"),
  );
  const project = sourceProject(catalog, "test");
  const before = JSON.stringify(project);
  const manifest = Object.fromEntries(
    catalogAssets(catalog).map((a) => [a.id, a]),
  );
  const entries = overviewEntries(project, manifest);
  assert.equal(entries.length, 17);
  assert.equal(new Set(entries.map((e) => e.station.id)).size, 17);
  assert.equal(entries.filter((e) => e.available).length, 16);
  assert.equal(
    entries.find((e) => e.station.id === "202401-FA00").status,
    "無可顯示幾何",
  );
  assert.equal(entries.find((e) => e.station.id === "LINE").status, "部分還原");
  assert.equal(JSON.stringify(project), before);
});

test("overview supports custom projects without inventing a LINE station", () => {
  const project = {
    stations: [
      { id: "custom", name: "自訂設備", parts: [], model: { object: {} } },
      { id: "pending", name: "待匯入", parts: [] },
    ],
  };
  const entries = overviewEntries(project, {});
  assert.deepEqual(
    entries.map((e) => e.station.id),
    ["custom", "pending"],
  );
  assert.equal(entries[0].available, true);
  assert.equal(entries[1].available, false);
});
