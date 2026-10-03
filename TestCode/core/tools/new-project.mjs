// 由 core/template 建立新專案：
//   node core/tools/new-project.mjs <資料夾名稱> "<中文標題>" ["首頁一句說明"]
// 建好後就能用 serve.mjs 開啟、check.mjs 檢查，推送後自動出現在 GitHub Pages 首頁。
import { cpSync, existsSync, readdirSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { CORE, ROOT } from './projects.mjs';

const [id, title, summary = ''] = process.argv.slice(2);
if (!id || !title) { console.log('用法：node core/tools/new-project.mjs <資料夾名稱> "<中文標題>" ["首頁一句說明"]'); process.exit(2); }
if (!/^[\w][\w .-]*$/.test(id)) throw new Error('資料夾名稱請用英數、空白、- 或 _');
const dest = join(ROOT, id);
if (existsSync(dest)) throw new Error(`已存在：${dest}`);

cpSync(join(CORE, 'template'), dest, { recursive: true });
const vars = { __ID__: id, __TITLE__: title, __SUMMARY__: summary || title, __URL__: encodeURIComponent(id) };
// 依檔案類型跳脫：JSON 字串（引號、反斜線）、HTML 文字（< > &）；範本的 index.html 版面骨架（#topbar／#side／#bottombar）只代換標題與說明
const escape = { json: v => JSON.stringify(v).slice(1, -1), html: v => v.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') };
const walk = d => { for (const e of readdirSync(d)) { const f = join(d, e); if (statSync(f).isDirectory()) walk(f); else if (/\.(js|mjs|json|html|css|md|bat)$/.test(e)) { const esc = escape[e.split('.').pop()] || (v => v); let s = readFileSync(f, 'utf8'); for (const [k, v] of Object.entries(vars)) s = s.split(k).join(esc(v)); writeFileSync(f, s); } } };
walk(dest);
console.log(`已建立 ${dest}
  開啟：node core/tools/serve.mjs "${id}"
  檢查：node core/tools/check.mjs "${id}"
  記得把 /${id}/docs/ 加進根目錄 .gitignore（使用者提供的圖面與規劃文件只留本機）`);
