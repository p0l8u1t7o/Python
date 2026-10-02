// 靜態 import 路徑檢查：從各專案 index.html 的 module script 出發，依 importmap 走遍 import 圖，
// 列出找不到的檔案（相對路徑、@core/、three/addons/）。也檢查 index.html 引用的 css／圖片。
// 部署前的第一道關卡；不需瀏覽器。
//   node core/tools/check-imports.mjs [專案…]
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { pickProjects, CORE } from './projects.mjs';

const IMPORT_RE = /(?:^|[;\n}\s])(?:import|export)\s+(?:[^'"`;]*?\s+from\s+)?['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)/g;

// 網址空間：/core/… 與 /<專案>/…，對應到磁碟
function toDisk(url, project) {
  const parts = url.split('/').filter(Boolean);
  if (parts[0] === 'core') return join(CORE, ...parts.slice(1));
  if (decodeURIComponent(parts[0]) === project.id) return join(project.web, ...parts.slice(1).map(decodeURIComponent));
  return null;
}
const strip = src => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

export function checkProject(p) {
  const html = readFileSync(join(p.web, 'index.html'), 'utf8'), base = `/${encodeURIComponent(p.id)}/`;
  const map = JSON.parse(/<script type="importmap">([\s\S]*?)<\/script>/.exec(html)?.[1] || '{"imports":{}}').imports;
  const abs = (spec, from) => new URL(spec, 'http://x' + from).pathname;
  const resolveSpec = (spec, from) => {
    if (spec.startsWith('.') || spec.startsWith('/')) return abs(spec, from);
    for (const [k, v] of Object.entries(map)) if (k.endsWith('/') ? spec.startsWith(k) : spec === k) return abs(v + (k.endsWith('/') ? spec.slice(k.length) : ''), base);
    return { bare: spec };
  };
  const missing = [], seen = new Set(), queue = [];
  for (const m of html.matchAll(/<script[^>]*type="module"[^>]*src="([^"]+)"/g)) queue.push([abs(m[1], base), 'index.html']);
  for (const m of html.matchAll(/<script type="module">([\s\S]*?)<\/script>/g)) for (const i of strip(m[1]).matchAll(IMPORT_RE)) { const r = resolveSpec(i[1] || i[2], base); typeof r === 'string' ? queue.push([r, 'index.html']) : missing.push(`index.html：無法解析 ${r.bare}`); }
  for (const m of html.matchAll(/<link[^>]+href="([^"]+)"/g)) if (!/^https?:|^data:/.test(m[1])) { const f = toDisk(abs(m[1], base), p); if (!f || !existsSync(f)) missing.push(`index.html：${m[1]}`); }
  while (queue.length) {
    const [url, from] = queue.pop(); if (seen.has(url)) continue; seen.add(url);
    const file = toDisk(url, p);
    if (!file || !existsSync(file)) { missing.push(`${from}：${url}`); continue; }
    if (!/\.m?js$/.test(file)) continue;
    for (const i of strip(readFileSync(file, 'utf8')).matchAll(IMPORT_RE)) {
      const spec = i[1] || i[2], r = resolveSpec(spec, url);
      if (typeof r === 'string') queue.push([r, url]); else missing.push(`${url}：無法解析 ${r.bare}`);
    }
  }
  return { modules: seen.size, missing };
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  let bad = 0;
  for (const p of pickProjects(process.argv.slice(2))) {
    const r = checkProject(p); bad += r.missing.length;
    console.log(`${r.missing.length ? '✗' : '✓'} ${p.id}：${r.modules} 個模組${r.missing.length ? `，缺 ${r.missing.length}` : ''}`);
    for (const m of r.missing) console.log('   ' + m);
  }
  process.exit(bad ? 1 : 0);
}
