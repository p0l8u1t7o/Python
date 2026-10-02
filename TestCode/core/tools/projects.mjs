// 專案清單：TestCode 底下有 web/index.html 的資料夾即為一個 3D 動畫專案，說明寫在 project.json。
import { readdirSync, existsSync, readFileSync } from 'node:fs';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

export const CORE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const ROOT = resolve(CORE, '..');

export function listProjects() {
  return readdirSync(ROOT, { withFileTypes: true })
    .filter(d => d.isDirectory() && existsSync(join(ROOT, d.name, 'web', 'index.html')))
    .map(d => loadProject(d.name))
    .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
}

export function loadProject(id) {
  const dir = join(ROOT, id), file = join(dir, 'project.json');
  const meta = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
  return { id, dir, web: join(dir, 'web'), title: meta.title || id, summary: meta.summary || '', order: meta.order ?? 99, ...meta };
}

// 命令列可用資料夾名稱或其開頭字串指定專案（大小寫不分）
export function pickProjects(names) {
  const all = listProjects();
  if (!names.length) return all;
  return names.map(n => {
    const hit = all.find(p => p.id === n) || all.find(p => p.id.toLowerCase().startsWith(n.toLowerCase()));
    if (!hit) throw new Error(`找不到專案：${n}（可用：${all.map(p => p.id).join('、')}）`);
    return hit;
  });
}
