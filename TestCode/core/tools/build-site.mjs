// GitHub Pages 建置：網址配置與本機 serve.mjs 相同。
//   node TestCode/core/tools/build-site.mjs <輸出資料夾，預設 _site>
//   /index.html 首頁、/core/ 共用（不含 tools 與文件）、/<專案>/ 各專案 web/ 全部內容
import { cpSync, mkdirSync, writeFileSync, existsSync, rmSync, readdirSync, statSync } from 'node:fs';
import { join, resolve, relative, sep } from 'node:path';
import { CORE, listProjects } from './projects.mjs';
import { galleryHtml } from './site.mjs';

const OUT = resolve(process.argv[2] || '_site');
if (existsSync(OUT) && readdirSync(OUT).length) throw new Error(`輸出資料夾不是空的：${OUT}`);
mkdirSync(OUT, { recursive: true });

const SKIP_CORE = new Set(['tools', 'template', 'verify', 'review']);   // 只在 Node 端用的檢查與報告不發布
cpSync(CORE, join(OUT, 'core'), {
  recursive: true,
  filter: src => { const rel = relative(CORE, src).split(sep); return !(SKIP_CORE.has(rel[0]) || /\.md$/i.test(src)); },
});
const projects = listProjects();
for (const p of projects) cpSync(p.web, join(OUT, p.id), { recursive: true });
const hasCatalog = existsSync(join(CORE, 'catalog', 'index.html'));
writeFileSync(join(OUT, 'index.html'), galleryHtml(projects, { catalog: hasCatalog }));
writeFileSync(join(OUT, '.nojekyll'), '');

let files = 0, bytes = 0;
const walk = d => { for (const e of readdirSync(d)) { const f = join(d, e), s = statSync(f); if (s.isDirectory()) walk(f); else { files++; bytes += s.size; } } };
walk(OUT);
console.log(`Prepared ${projects.length} demos in ${OUT}: ${files} files, ${(bytes / 1048576).toFixed(1)} MB`);
