// 輸出給作業現場的成品：作業指導書（可列印成 PDF 的單一 HTML）與影片字卡繪製。
import { escapeHTML as h } from "./core.js";

/** 去掉實例編號（_1、_#2、 #3），同料號的零件才能合併計數。 */
export const baseName = (name) =>
  String(name || "零件")
    .replace(/(?:[_ ]#\d+|_\d+)+$/, "")
    .replace(/^BODY_/, "");

export function countNames(names) {
  const counts = new Map();
  for (const n of names) counts.set(baseName(n), (counts.get(baseName(n)) || 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

const splitTag = (name) => {
  const m = /^【(.+?)】(.*)$/.exec(name);
  return m ? { tag: m[1], title: m[2] } : { tag: "", title: name };
};

/**
 * @param {{station, project, steps: {index, step, image, parts: [string, number][]}[], cover, bom, generated}} data
 */
export function sopHtml({ station, project, steps, cover, bom, generated, total }) {
  const flagged = steps.filter((s) => s.step.auto?.forced).length;
  const reviewed = steps.filter((s) => s.step.reviewed).length;
  const rows = steps
    .map(({ index, step, image, parts }) => {
      const { tag, title } = splitTag(step.name);
      return `<section class="step${step.auto?.forced ? " warn" : ""}">
  <header><span class="no">${String(index + 1).padStart(2, "0")}</span><div>${tag ? `<em>${h(tag)}</em>` : ""}<h2>${h(title)}</h2></div><span class="state">${step.reviewed ? "已審核" : "待審核"}</span></header>
  <div class="body"><img src="${image}" alt="步驟 ${index + 1}"><div class="text"><p>${h(step.instruction)}</p><table><thead><tr><th>零件</th><th>數量</th></tr></thead><tbody>${parts.map(([n, c]) => `<tr><td>${h(n)}</td><td>${c}</td></tr>`).join("")}</tbody></table><div class="checks"><label>□ 作業完成</label><label>□ 自主檢查</label><label>簽名＿＿＿＿</label></div></div></div>
</section>`;
    })
    .join("\n");
  return `<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${h(station.name)} 組裝作業指導書</title>
<style>
:root{--ink:#1d2b33;--muted:#5d6f79;--line:#d5dee3;--accent:#c98a1a}
*{box-sizing:border-box}body{margin:0;background:#eef2f4;color:var(--ink);font:13px/1.55 "Microsoft JhengHei","Segoe UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px}
.cover,.step,.bom{background:#fff;border:1px solid var(--line);border-radius:6px;padding:18px 20px;margin-bottom:16px}
.cover h1{margin:0 0 4px;font-size:24px}.meta{color:var(--muted);margin:0 0 12px}
.cover img{width:100%;border:1px solid var(--line);border-radius:4px}
.summary{display:flex;flex-wrap:wrap;gap:8px 24px;margin:12px 0 0;padding:0;list-style:none}.summary b{font-size:18px;display:block}
.note{margin-top:12px;padding:8px 12px;background:#fbf3e2;border-left:4px solid var(--accent);color:#6b4d12}
table{width:100%;border-collapse:collapse;margin-top:8px;font-size:12px}th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left}th:last-child,td:last-child{text-align:right;width:56px}
.step header{display:flex;gap:12px;align-items:flex-start}.no{font:600 16px Consolas,monospace;border:2px solid var(--ink);border-radius:4px;padding:2px 8px}
.step h2{margin:0;font-size:16px}.step em{font-style:normal;font-size:11px;color:#8a6a22;background:#fbf3e2;padding:1px 6px;border-radius:3px}
.state{margin-left:auto;font-size:11px;color:var(--muted)}.step.warn{border-left:4px solid var(--accent)}
.body{display:grid;grid-template-columns:3fr 2fr;gap:16px;margin-top:12px}.body img{width:100%;border:1px solid var(--line);border-radius:4px}
.text p{margin:0;font-size:14px}.checks{display:flex;gap:16px;margin-top:12px;color:var(--muted)}
.toolbar{position:sticky;top:0;background:#1d2b33;color:#fff;padding:10px 16px;display:flex;gap:12px;align-items:center}.toolbar button{font:inherit;padding:6px 14px;border:0;border-radius:4px;background:#2a9e7f;color:#fff;cursor:pointer}
@media(max-width:700px){.body{grid-template-columns:1fr}}
@media print{body{background:#fff}.toolbar{display:none}main{padding:0;max-width:none}.cover,.step,.bom{border:0;border-bottom:1px solid var(--line);border-radius:0;break-inside:avoid;page-break-inside:avoid}.cover{page-break-after:always}}
</style></head><body>
<div class="toolbar"><strong>${h(station.name)} · 組裝作業指導書</strong><button onclick="print()">列印／另存 PDF</button></div>
<main>
<section class="cover"><h1>${h(station.name)} 組裝作業指導書</h1><p class="meta">${h(project.name)} · ${h(station.source || "")} · 產生於 ${h(generated)}</p><img src="${cover}" alt="完成組合圖">
<ul class="summary"><li><b>${steps.length}</b>本冊步驟${steps.length < total ? `（全部 ${total} 步）` : ""}</li><li><b>${station.parts.length}</b>零件數</li><li><b>${reviewed}</b>已審核步驟</li><li><b>${flagged}</b>標示 ⚠ 待確認</li></ul>
<p class="note">${station.planSource?.startsWith("geometry") ? "組裝順序由 CAD 階層與干涉檢查推論，" : ""}未審核的步驟為草稿；扭力、工具與檢驗標準以工程圖面及核准工法為準。</p></section>
${rows}
<section class="bom"><h2>零件清單（本站）</h2><table><thead><tr><th>零件</th><th>數量</th></tr></thead><tbody>${bom.map(([n, c]) => `<tr><td>${h(n)}</td><td>${c}</td></tr>`).join("")}</tbody></table></section>
</main></body></html>`;
}

/** 影片字卡：在畫面下方繪製步驟編號、名稱與說明。 */
export function drawCaption(ctx, { x, y, width, height, index, ratio, name, text, scale = 1 }) {
  ctx.fillStyle = "#14232d";
  ctx.fillRect(x, y, width, height);
  ctx.fillStyle = "#c98a1a";
  ctx.fillRect(x, y, 6 * scale, height);
  const pad = 20 * scale;
  ctx.fillStyle = "#e7b45a";
  ctx.font = `600 ${15 * scale}px Consolas, monospace`;
  ctx.textBaseline = "top";
  ctx.fillText(index, x + pad, y + 14 * scale);
  ctx.fillStyle = "#ffffff";
  ctx.font = `700 ${22 * scale}px "Microsoft JhengHei", sans-serif`;
  ctx.fillText(fit(ctx, name, width - pad * 2), x + pad, y + 36 * scale);
  ctx.fillStyle = "#c4d2da";
  ctx.font = `${16 * scale}px "Microsoft JhengHei", sans-serif`;
  wrap(ctx, text, width - pad * 2, 2).forEach((line, i) =>
    ctx.fillText(line, x + pad, y + (70 + i * 22) * scale),
  );
  if (ratio) {
    ctx.fillStyle = "#2a9e7f";
    ctx.fillRect(x, y + height - 4 * scale, width * ratio, 4 * scale);
  }
}

function fit(ctx, text, max) {
  if (ctx.measureText(text).width <= max) return text;
  let s = text;
  while (s.length > 1 && ctx.measureText(s + "…").width > max) s = s.slice(0, -1);
  return s + "…";
}

function wrap(ctx, text, max, lines) {
  const out = [];
  let line = "";
  for (const ch of String(text || "")) {
    if (ctx.measureText(line + ch).width > max) {
      out.push(line);
      line = ch;
      if (out.length === lines) break;
    } else line += ch;
  }
  if (out.length < lines && line) out.push(line);
  if (out.length === lines && out.join("").length < String(text).length)
    out[lines - 1] = fit(ctx, out[lines - 1] + "…", max);
  return out;
}
