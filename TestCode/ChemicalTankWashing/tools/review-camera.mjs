// 焦點追隨與相機子畫面的互動檢查（core/ui/viewer-workspace.js 的 ◎ 追隨、相機視窗與來源選單＋本專案的焦點選單）。
// 只用 DevTools Protocol（Runtime.evaluate、Input.dispatchMouseEvent），可由 core/tools/cdp.mjs 的 openBrowser() 或 Browser 技能的 tab 呼叫：
//   import { openBrowser } from '../../core/tools/cdp.mjs';
//   const b = await openBrowser(); await b.goto('http://127.0.0.1:8770/ChemicalTankWashing/?pause');
//   await runCameraReview(b, null, 'review/camera');
// 直接執行（自行啟動本機伺服器與無頭瀏覽器，結果寫到 review/camera/camera-review.json）：
//   node tools/review-camera.mjs [--port 8770]
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SOURCE = '#pipFrame select[aria-label="相機來源"]';   // viewer-workspace.setSources 建立的來源選單

export async function runCameraReview(cdp, tab, out) {
  mkdirSync(out, { recursive: true }); const checks = [];
  const evaluate = async expression => {
    const r = await cdp.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    const ex = r.exceptionDetails || r.result?.exceptionDetails; if (ex) throw Error(JSON.stringify(ex));
    return (r.result?.result ?? r.result)?.value;
  };
  const check = (name, ok, detail) => checks.push({ name, ok: !!ok, detail });
  const settle = () => evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(true))))');
  const state = () => evaluate('({focus:sim.focus.enabled,target:sim.focus.target,camera:sim.camera.position.toArray(),look:sim.controls.target.toArray(),pip:sim.cameraWindow.state})');
  const select = (id, value) => evaluate(`(()=>{const s=document.querySelector(${JSON.stringify(id.startsWith('#') ? id : '#' + id)});s.value=${JSON.stringify(value)};s.dispatchEvent(new Event('change',{bubbles:true}));return s.value;})()`);
  const click = selector => evaluate(`(document.querySelector(${JSON.stringify(selector)}).click(),true)`);
  const byLabel = label => `[aria-label="${label}"]`;
  const rect = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect().toJSON()`);
  const mouse = (type, x, y) => cdp.send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1 });
  async function drag(x0, y0, dx, dy) { await mouse('mousePressed', x0, y0); for (let k = 1; k <= 4; k++) await mouse('mouseMoved', x0 + dx * k / 4, y0 + dy * k / 4); await mouse('mouseReleased', x0 + dx, y0 + dy); }
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  await evaluate('sim.pause();sim.seekTo(0);sim.setView("iso",true)'); await settle();
  await select('focusTarget', 'agv'); await click('#focusNow');
  check('全景可單次對準並拉近目標', await evaluate('!sim.focus.enabled&&sim.controls.target.distanceTo(sim.focusPosition("agv"))<.01&&sim.camera.position.distanceTo(sim.controls.target)<6000'));
  await click('#followProduct');
  check('◎ 開始追隨焦點', (await state()).focus);
  for (const key of ['agv', 'gantry', 'drum0', 'drum1', 'drum2', 'drum3', 'auto', 'gripper']) {
    await evaluate('sim.seekTo(140)'); await select('focusTarget', key);
    const before = await evaluate('sim.camera.position.clone().sub(sim.controls.target).toArray()');
    await evaluate('sim.seekTo(145)');
    check('追蹤及跳轉 · ' + key, await evaluate(`sim.focus.enabled&&sim.controls.target.distanceTo(sim.focusPosition(${JSON.stringify(key)}))<.01&&sim.camera.position.clone().sub(sim.controls.target).distanceTo({x:${before[0]},y:${before[1]},z:${before[2]}})<.01`));
  }
  await click('#followProduct'); const stopped = await state(); await evaluate('sim.seekTo(150)');
  check('停止追隨後跳轉不移動相機', !stopped.focus && same((await state()).camera, stopped.camera));
  await select('focusTarget', 'drum0'); await click('#followProduct');
  const beforeGone = await state(); await evaluate('sim.seekTo(sim.total)'); await settle();
  check('桶離線時保留視角並提示', same((await state()).camera, beforeGone.camera) && await evaluate('document.getElementById("focusStatus").textContent') === '目標已離開產線');
  await evaluate('sim.seekTo(140)'); check('倒退跳轉恢復追蹤', await evaluate('sim.controls.target.distanceTo(sim.focusPosition("drum0"))<.01'));
  await click('.views button[data-view="gripper"]'); await evaluate('sim.setView("gripper",true)');
  check('預設視角可退出追隨', !(await state()).focus);
  await evaluate('sim.seekTo(sim.total);sim.setView("iso",true)'); await select('focusTarget', 'drum0');
  const absentStart = await state(); await click('#focusNow');
  check('對準已離線目標不改變相機位置', same((await state()).camera, absentStart.camera));
  await click('#followProduct');
  check('從全景追隨已離線目標不突然拉近', same((await state()).camera, absentStart.camera) && (await state()).focus);
  await click('#followProduct');

  // ---------------------------------------------------------------- 相機視窗
  await evaluate('sim.seekTo(140);sim.setView("gripper",true)'); await settle();
  check('相機視窗預設顯示', await evaluate('sim.cameraWindow.visible'));
  const initial = await state(), title = await rect('#pipTitle');
  await drag(title.x + 40, title.y + 15, 140, 60); await settle();
  const moved = await state();
  check('標題列可拖曳且不旋轉主相機', moved.pip.x > initial.pip.x + 100 && moved.pip.y > initial.pip.y + 40 && same(moved.camera, initial.camera), moved.pip);
  await evaluate('document.getElementById("pipTitle").focus()');
  await cdp.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 });
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39 });
  check('鍵盤可移動視窗', Math.abs((await state()).pip.x - moved.pip.x - 12) < 1);
  await click(byLabel('放大／縮小相機視窗')); await settle();
  const big = await state(); check('放大視窗', big.pip.expanded && big.pip.w > moved.pip.w + 100, big.pip);
  await click(byLabel('放大／縮小相機視窗')); await settle(); check('還原大小', !(await state()).pip.expanded);
  await click('#pipFrame ' + byLabel('隱藏相機視窗')); await settle();
  check('隱藏與顯示設定同步', !(await evaluate('sim.cameraWindow.visible')) && !(await evaluate('document.getElementById("showPip").checked')));
  await click(byLabel('顯示／隱藏相機視窗')); await settle();
  check('工具列一鍵恢復視窗', await evaluate('!document.getElementById("pipFrame").hidden&&sim.cameraWindow.visible'));
  await evaluate('(()=>{const c=document.getElementById("showPip");c.checked=false;c.dispatchEvent(new Event("change",{bubbles:true}));})()'); await settle();
  const offByOption = !(await evaluate('sim.cameraWindow.visible'));
  await evaluate('(()=>{const c=document.getElementById("showPip");c.checked=true;c.dispatchEvent(new Event("change",{bubbles:true}));})()'); await settle();
  check('側欄「相機子畫面」勾選控制視窗', offByOption && await evaluate('sim.cameraWindow.visible'));
  check('來源選單：自動＋三個來源', same(await evaluate(`[...document.querySelector(${JSON.stringify(SOURCE)}).options].map(o=>o.value)`), ['auto', 'label', 'decap', 'gripper']));
  for (const [source, name, t] of [['gripper', '清洗夾具'], ['label', '貼標相機'], ['decap', '桶口相機'], ['auto', '貼標相機', 0]]) {
    if (t != null) await evaluate(`sim.seekTo(${t})`);
    await select(SOURCE, source); await evaluate('sim.seekTo(sim.T)'); await settle();
    check('相機來源 · ' + source, (await evaluate('document.getElementById("pipTitle").textContent')).includes(name));
  }
  // 自動切換：桶口相機取像後切到桶口相機
  const decapShot = await evaluate('sim.seq.tracks.decap.steps.find(s=>s.end.flash&&!s.initial.flash).start');
  await evaluate(`sim.seekTo(${decapShot + .5})`); await settle();
  check('自動切換到取像中的相機', (await evaluate('document.getElementById("pipTitle").textContent')).includes('桶口相機') && await evaluate('+document.querySelector(".vision-overlay").dataset.count>0'));
  await select(SOURCE, 'auto'); await evaluate('sim.seekTo(0);sim.setView("iso",true)');
  const report = { ok: checks.every(c => c.ok), checks };
  writeFileSync(join(out, 'camera-review.json'), JSON.stringify(report, null, 2)); return report;
}

// 直接執行：啟動 core 的本機伺服器與無頭瀏覽器，跑完整份檢查，並把主控台錯誤算進結果
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const { startServer } = await import('../../core/tools/serve.mjs');
  const { openBrowser } = await import('../../core/tools/cdp.mjs');
  const i = process.argv.indexOf('--port'), port = i > 0 ? +process.argv[i + 1] : 8770;
  const server = await startServer({ port, quiet: true }), b = await openBrowser();
  try {
    if (!await b.goto(`http://127.0.0.1:${port}/ChemicalTankWashing/?pause`)) throw new Error('頁面未就緒 ' + b.errors.join(' | '));
    const report = await runCameraReview(b, null, join(root, 'review/camera'));
    report.consoleErrors = [...b.errors]; report.ok &&= !b.errors.length;
    writeFileSync(join(root, 'review/camera/camera-review.json'), JSON.stringify(report, null, 2));
    for (const c of report.checks) console.log(c.ok ? '✓' : '✗', c.name, c.ok ? '' : JSON.stringify(c.detail ?? ''));
    console.log(report.ok ? `通過 ${report.checks.length} 項，無主控台錯誤` : `未通過；主控台錯誤 ${b.errors.length} 筆`, b.errors.slice(0, 5));
    process.exitCode = report.ok ? 0 : 1;
  } finally { await b.close(); server.close(); }
}
