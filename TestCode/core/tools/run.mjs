// 在專案資料夾內以統一 loader 執行 Node 腳本（不必記 --import 路徑）。
//   node core/tools/run.mjs <專案> <腳本> [參數…]
//   例：node core/tools/run.mjs Chemical tools/verify-scene.mjs --dt=0.5
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { CORE, pickProjects } from './projects.mjs';

export const REGISTER = pathToFileURL(join(CORE, 'tools', 'register.mjs')).href;

// 回傳 Promise<{ code, out }>；echo 為 true 時同步輸出到終端機
export function runScript(project, script, args = [], { echo = true, env = {} } = {}) {
  return new Promise(ok => {
    const child = spawn(process.execPath, ['--no-warnings', '--import', REGISTER, script, ...args], { cwd: project.dir, windowsHide: true, env: { ...process.env, ...env } });
    let out = '';
    for (const s of [child.stdout, child.stderr]) s.on('data', d => { out += d; if (echo) process.stdout.write(d); });
    child.on('close', code => ok({ code, out }));
  });
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [name, script, ...args] = process.argv.slice(2);
  if (!name || !script) { console.log('用法：node core/tools/run.mjs <專案> <腳本> [參數…]'); process.exit(2); }
  const { code } = await runScript(pickProjects([name])[0], script, args);
  process.exit(code);
}
