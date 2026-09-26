// Run from any directory with Node.js 22+. No npm packages required.
import { spawn } from 'node:child_process';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const projects = {
  'AutomaticAcid-BaseTitration': ['verify.mjs', 'verify-clearance.mjs', 'verify-self-clearance.mjs', 'verify-render.mjs'],
  'MilitaryGradePC': ['verify.mjs', 'verify-clearance.mjs', 'verify-self-clearance.mjs', 'verify-camera.mjs'],
  'PCB-CopperAssembly': ['verify.mjs', 'verify-clearance.mjs', 'verify-geometry.mjs'],
  'RobotArmPressSSD': ['verify.mjs', 'verify-clearance.mjs', 'verify-self-clearance.mjs', 'verify-camera.mjs', 'verify-vision.mjs'],
};
const selected = process.argv.slice(2);
if (selected.some(p => !Object.hasOwn(projects, p))) {
  console.error('Usage: node tools/verify-interference.mjs [project ...]\nProjects: ' + Object.keys(projects).join(', '));
  process.exit(2);
}
const targets = selected.length ? [...new Set(selected)] : Object.keys(projects);
async function sourceHash(project) {
  const hash = createHash('sha256');
  const files = [];
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) await walk(path);
      else if (/\.(?:js|mjs)$/.test(entry.name)) files.push(path);
    }
  }
  await walk(join(root, project, 'web', 'js')); await walk(join(root, project, 'tools'));
  files.push(join(root, 'tools', 'geometry-clearance.mjs'),join(root,project,'web','vendor','three.module.js'));
  for (const path of files.sort()) hash.update(relative(root, path)).update(await readFile(path));
  return hash.digest('hex');
}
async function run(project, script) {
  const start = Date.now();
  const result = await new Promise(resolve => {
    const child = spawn(process.execPath, ['--no-warnings', '--experimental-loader', './tools/three-loader.mjs', './tools/' + script],
      { cwd: join(root, project), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '', settled = false;
    child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', error => { if (!settled) { settled = true; resolve({ code: null, stdout, stderr: stderr + error.message }); } });
    child.on('close', code => { if (!settled) { settled = true; resolve({ code, stdout, stderr }); } });
  });
  const log = join(root, project, 'review', 'checks', script.replace('.mjs', '.log'));
  await mkdir(dirname(log), { recursive: true });
  await writeFile(log, result.stdout + (result.stderr ? '\nSTDERR:\n' + result.stderr : ''));
  const passed = result.code === 0;
  // Refresh the existing machine-readable reports only after a successful run.
  if (passed && script === 'verify.mjs' && project !== 'AutomaticAcid-BaseTitration') {
    try { const data = JSON.parse(result.stdout); await writeFile(join(root, project, 'review', 'verification.json'), JSON.stringify(data, null, 2) + '\n'); } catch {}
  }
  console.log(`${passed ? 'PASS' : 'FAIL'} ${project}/${script} (${((Date.now() - start) / 1000).toFixed(1)} s)`);
  if (!passed) console.error((result.stderr || result.stdout).slice(-2500));
  return { script, passed, exitCode: result.code, seconds: (Date.now() - start) / 1000, log: relative(root, log).replaceAll('\\', '/') };
}

const startedAt = new Date().toISOString();
// Different projects may run together; tests within each project stay serial.
const results = await Promise.all(targets.map(async project => {
  const before = await sourceHash(project), checks = [];
  for (const script of projects[project]) checks.push(await run(project, script));
  const after = await sourceHash(project);
  return { project, sourceHash: after, sourceChangedDuringRun: before !== after, passed: before === after && checks.every(c => c.passed), checks };
}));
const report = { startedAt, finishedAt: new Date().toISOString(), scope: 'sampled animation geometry, kinematics and camera regression; not real-machine collision certification', passed: results.every(r => r.passed), results };
await mkdir(join(root, 'review'), { recursive: true });
await writeFile(join(root, 'review', 'interference-checks.json'), JSON.stringify(report, null, 2) + '\n');
console.log(`${report.passed ? 'ALL CHECKS PASSED' : 'CHECKS FAILED / SOURCES CHANGED'}; report: review/interference-checks.json`);
if (!report.passed) process.exitCode = 1;
