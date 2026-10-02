import test from "node:test";
import assert from "node:assert/strict";
import { baseName, countNames, sopHtml } from "../../src/project/exporters.js";

test("part counts merge instance suffixes from STEP and SolidWorks", () => {
  assert.equal(baseName("MISUMI_HFCL8-4040-B_NEW_3"), "MISUMI_HFCL8-4040-B_NEW");
  assert.equal(baseName("202401-ED07_#3"), "202401-ED07");
  assert.deepEqual(countNames(["A_1", "A_2", "B", "A"]), [
    ["A", 3],
    ["B", 1],
  ]);
});

test("work instructions escape CAD names and mark steps needing review", () => {
  const html = sopHtml({
    station: { name: "台車<script>", parts: [{}, {}], source: "x.STEP", planSource: "geometry" },
    project: { name: "P" },
    steps: [
      {
        index: 0,
        step: { name: "【預組 U】安裝 <b>", instruction: "由上方往下放入", reviewed: false, auto: { forced: true } },
        image: "data:image/jpeg;base64,AA",
        parts: [["<b>", 2]],
      },
    ],
    cover: "data:image/jpeg;base64,AA",
    bom: [["<b>", 2]],
    generated: "2026/10/2",
    total: 5,
  });
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("台車&lt;script&gt;"));
  assert.match(html, /class="step warn"/);
  assert.match(html, /全部 5 步/);
  assert.match(html, /預組 U/);
});
