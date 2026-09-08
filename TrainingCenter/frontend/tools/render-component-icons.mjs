import { createRequire } from 'node:module';
import { readFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const require = createRequire(import.meta.url);
// The renderer is a development tool; runtime pages need no Playwright.
const { chromium } = require('playwright-core');
const manifest = JSON.parse(await readFile(path.join(root, 'src/assets/component-visuals.json'), 'utf8'));
const executablePath = process.env.CHROMIUM_PATH;
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
try {
  const page = await browser.newPage({ viewport: { width: 640, height: 480 }, deviceScaleFactor: 1 });
  await page.goto(`${process.env.VITE_URL ?? 'http://127.0.0.1:5174'}/tools/render-components.html`);
  await page.waitForFunction(() => typeof window.renderModel === 'function');
  const out = path.join(root, 'public/component-visuals');
  await mkdir(out, { recursive: true });
  for (const name of manifest.models) {
    const info = await page.evaluate(name => window.renderModel(`/component-visuals/${name}.glb`), name);
    if (!info.triangles) throw new Error(`Empty model: ${name}`);
    await page.locator('canvas').screenshot({ path: path.join(out, `${name}.png`) });
    console.log(`${name}: ${info.triangles} triangles`);
  }
  console.log(`Rendered ${manifest.models.length} component icons.`);
} finally { await browser.close(); }
