/** 模組 editor：頂列（F）、工具箱（G）、步驟清單（H）、側欄（K）、結果分頁（L）、範本載入／存為範本（E07–E09）。 */
import { BASE } from './full-lib.mjs'

export async function run(h) {
  await h.loginAdmin()
  const context = await h.newContext({ token: h.token })
  const page = await h.newPage(context, '[editor]')
  const flowId = await h.cloneDemo('E2E 編輯器測試')
  const flow = await h.api.get(`/vision/flows/${flowId}`)
  const nodeCount = flow.graph.nodes.length
  const url = `${BASE}/flows/${flowId}`
  const open = async () => {
    await page.goto(url)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(800)
  }
  const toolbar = () => page.locator('[data-testid=editor-toolbar]')
  /** 先符合視窗再點節點：畫布只佔中欄 40%，節點常在視窗外。 */
  const clickNode = async (id, opts = {}) => {
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(350)
    await page.locator(`.react-flow__node[data-id="${id}"]`).click(opts)
  }
  const nodes = () => page.locator('.react-flow__node')
  const inspector = () => page.locator('[data-testid=inspector-pane]')
  /** 工具箱一律拖曳新增：直接對畫布 dispatch dragover／drop（Playwright 的 HTML5 拖放不穩）。 */
  const dropTool = async (key, fx = 0.6, fy = 0.6) => {
    await page.evaluate(({ key, fx, fy }) => {
      const pane = document.querySelector('.react-flow__pane')
      const r = pane.getBoundingClientRect()
      const x = r.left + r.width * fx
      const y = r.top + r.height * fy
      const dt = new DataTransfer()
      dt.setData('application/x-vs-tool', key)
      pane.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }))
      pane.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }))
    }, { key, fx, fy })
    await page.waitForTimeout(150)
  }

  await open()
  await h.shot(page, 'editor')

  // ============ F. 頂列 ============
  await h.step('F14 badge 與容量', async () => {
    const txt = await toolbar().innerText()
    h.item('F14', txt.includes('即時') && /\d+\/\d+ 忙碌/.test(txt), `toolbar=${txt.replace(/\n/g, '|')}`)
  })

  await h.step('F13 選取／平移（畫布右上角）', async () => {
    // 改版後切換鈕在畫布右上角的 React Flow Panel，不在頂列
    const panel = page.locator('.react-flow__panel.top.right[data-testid=canvas-mode]')
    const inPanel = (await panel.count()) === 1
    const notInToolbar = (await toolbar().getByRole('button', { name: '平移' }).count()) === 0
    const pan = panel.getByRole('button', { name: '平移' })
    const sel = panel.getByRole('button', { name: '選取' })
    await pan.click()
    const a = (await pan.getAttribute('aria-pressed')) === 'true' && (await sel.getAttribute('aria-pressed')) === 'false'
    await sel.click()
    const b = (await sel.getAttribute('aria-pressed')) === 'true'
    // 與縮放滑桿同風格：同樣有邊框與白底
    const style = await page.evaluate(() => {
      const a = getComputedStyle(document.querySelector('.react-flow__panel.top.right[data-testid=canvas-mode]'))
      const b = getComputedStyle(document.querySelector('.react-flow__panel.bottom'))
      return { same: a.backgroundColor === b.backgroundColor && a.borderColor === b.borderColor, bg: a.backgroundColor }
    })
    await h.shot(page, 'canvas-mode-panel')
    h.item('F13', inPanel && notInToolbar && a && b && style.same, `inPanel=${inPanel} notInToolbar=${notInToolbar} pan=${a} select=${b} style=${JSON.stringify(style)}`)
  })

  await h.step('F01-F02 名稱與儲存', async () => {
    const name = toolbar().getByRole('textbox', { name: '名稱' })
    await name.fill('E2E 編輯器測試 改名')
    const txt = await toolbar().innerText()
    const saveBtn = toolbar().getByRole('button', { name: /^儲存$/ })
    const primary = await saveBtn.evaluate((el) => el.className.includes('bg-brand'))
    h.item('F01', txt.includes('有未儲存的變更') && primary, `dirty=${txt.includes('有未儲存的變更')} primary=${primary}`)
    const v0 = (await h.api.get(`/vision/flows/${flowId}`)).version
    await saveBtn.click()
    const t1 = await h.toast(page, /流程已儲存/)
    await page.waitForTimeout(500)
    const v1 = (await h.api.get(`/vision/flows/${flowId}`)).version
    const savedLabel = (await toolbar().innerText()).includes('已儲存')
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    await name.fill('E2E 編輯器測試')
    await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
    await page.keyboard.press('Control+s')
    const t2 = await h.toast(page, /流程已儲存/)
    await page.waitForTimeout(500)
    const v2 = (await h.api.get(`/vision/flows/${flowId}`)).version
    h.item('F02', Boolean(t1) && v1 === v0 + 1 && savedLabel && Boolean(t2) && v2 === v1 + 1, `t1=${t1} v ${v0}→${v1}→${v2} label=${savedLabel} t2=${t2}`)
  })

  await h.step('F03 範本下拉', async () => {
    await page.getByTestId('btn-templates').click()
    const menu = page.getByTestId('menu-templates').locator('[role=menu]')
    const items = await menu.locator('[role=menuitem]').allInnerTexts()
    await page.keyboard.press('Escape')
    const escClosed = (await menu.count()) === 0
    await page.getByTestId('btn-templates').click()
    await page.mouse.click(700, 600)
    const outsideClosed = (await menu.count()) === 0
    h.item('F03', items.length === 2 && items.join('|').includes('載入範本') && items.join('|').includes('存為範本') && escClosed && outsideClosed, `items=${items.join('|')} esc=${escClosed} outside=${outsideClosed}`)
  })

  await h.step('F18 說明下拉', async () => {
    await page.getByTestId('menu-help').locator('button').click()
    const menu = page.getByTestId('menu-help').locator('[role=menu]')
    const items = await menu.locator('[role=menuitem]').allInnerTexts()
    const hrefs = await menu.locator('[role=menuitem]').evaluateAll((els) => els.map((e) => e.getAttribute('href')))
    await h.shot(page, 'editor-help-menu')
    await menu.locator('[role=menuitem]').nth(1).click()
    await page.waitForURL(/\/help\?tab=shortcuts/, { timeout: 5000 })
    const ok = await page.locator('[data-testid=help-shortcuts]').waitFor({ timeout: 5000 }).then(() => true).catch(() => false)
    h.item('F18', items.length === 3 && hrefs.join('|') === '/help|/help?tab=shortcuts|/integration' && ok, `items=${items.join('|')} hrefs=${hrefs.join('|')} url=${page.url()}`)
    await open()
  })

  await h.step('F17 統計連結', async () => {
    await page.getByTestId('btn-stats').click()
    await page.waitForURL(/\/stats$/, { timeout: 5000 })
    h.item('F17', /\/stats$/.test(page.url()), `url=${page.url()}`)
    await open()
  })

  // ============ G. 工具箱 ============
  const palette = () => page.locator('aside').first()
  await h.step('G01 搜尋', async () => {
    const box = palette().locator('input[placeholder^="搜尋"]')
    const before = await palette().locator('[data-testid=palette-tool]').count()
    await box.fill('blob')
    await page.waitForTimeout(200)
    const after = await palette().locator('[data-testid=palette-tool]').count()
    const labels = await palette().locator('[data-testid=palette-tool]').allInnerTexts()
    const favHidden = (await page.getByTestId('palette-favorites').count()) === 0
    await h.shot(page, 'palette-search')
    await box.fill('')
    await page.waitForTimeout(200)
    const restored = await palette().locator('[data-testid=palette-tool]').count()
    h.item('G01', before > 30 && after >= 1 && after < 5 && labels.join('|').includes('Blob') && favHidden && restored === before, `before=${before} after=${after} labels=${labels.join('|')} favHidden=${favHidden} restored=${restored}`)
  })

  await h.step('G02 分類收合', async () => {
    const section = page.getByTestId('palette-preprocess')
    const header = section.locator('button').first()
    const countLabel = await header.locator('.tabular-nums').innerText()
    const itemsBefore = await section.locator('[data-testid=palette-tool]').count()
    await header.click()
    const collapsed = await section.locator('[data-testid=palette-tool]').count()
    await header.click()
    const expanded = await section.locator('[data-testid=palette-tool]').count()
    h.item('G02', Number(countLabel) === itemsBefore && collapsed === 0 && expanded === itemsBefore, `count=${countLabel} items=${itemsBefore} collapsed=${collapsed} expanded=${expanded}`)
  })

  await h.step('G03 收藏', async () => {
    await page.evaluate(() => localStorage.removeItem('vs.favoriteTools'))
    await open()
    const favEmpty = await page.getByTestId('palette-favorites').innerText()
    const tool = page.locator('[data-tool-key="blob"]').last()
    const star = tool.getByTestId('palette-star')
    const opacityBefore = await star.evaluate((el) => getComputedStyle(el).opacity)
    await tool.hover()
    await page.waitForTimeout(200)
    const opacityHover = await star.evaluate((el) => getComputedStyle(el).opacity)
    await star.click()
    await page.waitForTimeout(200)
    const favCount = await page.getByTestId('palette-favorites').locator('[data-testid=palette-tool]').count()
    const stored = await page.evaluate(() => localStorage.getItem('vs.favoriteTools'))
    await h.shot(page, 'palette-favorite')
    await page.getByTestId('palette-favorites').getByTestId('palette-star').click()
    await page.waitForTimeout(200)
    const favAfter = await page.getByTestId('palette-favorites').locator('[data-testid=palette-tool]').count()
    h.item('G03', favEmpty.includes('按工具旁的星號') && opacityBefore === '0' && opacityHover === '1' && favCount === 1 && stored?.includes('blob') && favAfter === 0, `empty=${favEmpty} op=${opacityBefore}/${opacityHover} fav=${favCount} stored=${stored} after=${favAfter}`)
  })

  await h.step('G05 G07 點擊不新增（一律拖曳）、無最近使用', async () => {
    await page.evaluate(() => localStorage.setItem('vs.recentTools', JSON.stringify(['blur'])))
    await open()
    const before = await nodes().count()
    const tool = page.locator('[data-tool-key="grayscale"]').last()
    const title = await tool.locator('button').first().getAttribute('title')
    await tool.locator('button').first().click()
    await page.waitForTimeout(400)
    const afterClick = await nodes().count()
    const dirtyAfterClick = (await toolbar().innerText()).includes('有未儲存的變更')
    const noRecent = (await page.getByTestId('palette-recent').count()) === 0
    const paletteHead = await page.locator('aside').first().innerText()
    const hint = paletteHead.includes('拖到畫布新增') && !paletteHead.includes('點擊')
    h.item('G05', afterClick === before && !dirtyAfterClick && hint, `click: count ${before}→${afterClick} dirty=${dirtyAfterClick} hint=${hint}`)
    h.item('G07', Boolean(title) && title.includes('拖到畫布新增') && title.split('\n')[0].length > 2, `title=${title}`)
    h.skip('G04', '已移除：工具箱「最近使用」（vs.recentTools）')
    h.item('G08', noRecent && (await page.locator('aside').first().innerText()).includes('收藏'), `noRecentSection=${noRecent}`)
    // 拖曳新增 6 個 → 逐一 Delete
    let i = 0
    for (const key of ['blur', 'threshold', 'morphology', 'resize', 'edges', 'hist_eq']) {
      await dropTool(key, 0.2 + (i % 3) * 0.25, 0.3 + Math.floor(i / 3) * 0.35)
      i += 1
    }
    await page.waitForTimeout(300)
    const afterDrop = await nodes().count()
    await page.keyboard.press('Escape')
    for (const id of ['blur-1', 'threshold-1', 'morphology-1', 'resize-1', 'edges-1', 'hist_eq-1']) {
      await page.locator(`.react-flow__node[data-id="${id}"]`).click()
      await page.keyboard.press('Delete')
    }
    await page.waitForTimeout(300)
    h.item('I14', afterDrop === before + 6 && (await nodes().count()) === before, `拖曳後=${afterDrop}（預期 ${before + 6}）Delete 後節點數=${await nodes().count()}（預期 ${before}）`)
  })

  await h.step('G06 拖放插入', async () => {
    const before = await nodes().count()
    const tool = page.locator('[data-tool-key="blur"]').last().locator('button').first()
    const pane = page.locator('.react-flow__pane')
    const box = await pane.boundingBox()
    const target = { x: box.x + box.width * 0.7, y: box.y + box.height * 0.8 }
    await tool.dragTo(pane, { targetPosition: { x: box.width * 0.7, y: box.height * 0.8 } })
    await page.waitForTimeout(500)
    let after = await nodes().count()
    if (after === before) {
      // Playwright 的 HTML5 拖放在某些版本沒有 dataTransfer，改用手動事件
      await page.evaluate(({ key, x, y }) => {
        const dt = new DataTransfer()
        dt.setData('application/x-vs-tool', key)
        const pane = document.querySelector('.react-flow__pane')
        pane.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }))
        pane.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }))
      }, { key: 'blur', x: target.x, y: target.y })
      await page.waitForTimeout(500)
      after = await nodes().count()
    }
    const node = page.locator('.react-flow__node[data-id="blur-1"]')
    const nb = await node.boundingBox()
    const near = nb ? Math.abs(nb.x - target.x) < 60 && Math.abs(nb.y - target.y) < 60 : false
    await h.shot(page, 'palette-drop')
    h.item('G06', after === before + 1 && near, `count ${before}→${after} nodeAt=${nb ? `${Math.round(nb.x)},${Math.round(nb.y)}` : 'none'} target=${Math.round(target.x)},${Math.round(target.y)}`)
    await node.click()
    await page.keyboard.press('Delete')
  })

  // ============ H. 步驟清單 ============
  await h.step('H01 H03 H04 步驟清單', async () => {
    const list = page.getByTestId('node-list')
    const items = await list.locator('button').count()
    const title = await page.locator('aside').first().locator('p', { hasText: '步驟清單' }).innerText()
    const before = await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)
    // 步驟多時清單要能捲動（之前 NodeList 沒有 h-full，overflow-hidden 會把下面的步驟吃掉）
    const scrollable = await list.evaluate((el) => el.scrollHeight <= el.clientHeight || getComputedStyle(el).overflowY === 'auto')
    await list.locator('[data-node-id="blob"]').scrollIntoViewIfNeeded()
    await list.locator('[data-node-id="blob"]').click()
    await page.waitForTimeout(700)
    const after = await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)
    const selected = (await page.locator('.react-flow__node[data-id="blob"].selected').count()) === 1
    const highlighted = await list.locator('[data-node-id="blob"]').evaluate((el) => el.className.includes('bg-brand-soft'))
    h.item('H01', items === nodeCount && title.includes(`(${nodeCount})`) && scrollable, `items=${items} title=${title} scrollable=${scrollable}`)
    h.item('H03', selected && before !== after && highlighted, `selected=${selected} moved=${before !== after} highlighted=${highlighted}`)
    // H04 停用：右鍵停用 blob
    await clickNode('blob', { button: 'right' })
    await page.getByRole('menuitem', { name: '停用' }).click()
    await page.waitForTimeout(200)
    const dim = await list.locator('[data-node-id="blob"]').evaluate((el) => el.className.includes('opacity-50'))
    const dashed = await page.locator('.react-flow__node[data-id="blob"] > div').first().evaluate((el) => el.className.includes('border-dashed'))
    await h.shot(page, 'node-disabled')
    await clickNode('blob', { button: 'right' })
    await page.getByRole('menuitem', { name: '啟用' }).click()
    await page.waitForTimeout(200)
    const restored = await list.locator('[data-node-id="blob"]').evaluate((el) => !el.className.includes('opacity-50'))
    h.item('H04', dim && restored, `dim=${dim} restored=${restored}`)
    h.item('I25', dashed, '停用節點未顯示虛線框')
  })

  // ============ F05-F07 試跑、重跑、暫存影像 ============
  await h.step('F05-F06 試跑與重跑', async () => {
    const reuse = page.getByTestId('reuse-image')
    const disabledBefore = await reuse.isDisabled()
    await page.getByTestId('btn-preview').click()
    const t = await h.toast(page, /試跑完成：(OK|NG|失敗)（\d+ ms）/)
    await page.waitForTimeout(800)
    const hasImage = await h.viewerHasImage(page, '[data-testid=viewer-main]')
    const badge = await page.locator('[data-testid=viewer-main] .pointer-events-none.absolute.top-8').innerText().catch(() => '')
    await h.shot(page, 'editor-preview')
    h.item('F05', Boolean(t) && hasImage && /(OK|NG) · \d+ ms/.test(badge), `toast=${t} image=${hasImage} badge=${badge}`)
    const enabledAfter = !(await reuse.isDisabled())
    await reuse.check()
    const wait = page.waitForRequest((r) => r.url().includes('/preview') && r.method() === 'POST', { timeout: 5000 })
    await page.getByTestId('btn-preview').click()
    const req = await wait.catch(() => null)
    const body = req ? JSON.parse(req.postData() || '{}') : {}
    await h.toast(page, /試跑完成/)
    h.item('F06', disabledBefore && enabledAfter && typeof body.reuse_image_ref === 'string' && body.reuse_image_ref.length > 0, `before=${disabledBefore} after=${enabledAfter} reuse_ref=${body.reuse_image_ref}`)
    const dotClass = await page.getByTestId('node-list').locator('[data-node-id="blob"] span').first().getAttribute('class')
    h.item('H02', /bg-ok|bg-warning/.test(dotClass ?? ''), `狀態點 class=${dotClass}`)
  })

  await h.step('F07 暫存影像', async () => {
    const png = await h.makePng(page, { w: 640, h: 480, dots: 5 })
    await page.getByTestId('scratch-input').first().setInputFiles({ name: 'scratch-e2e.png', mimeType: 'image/png', buffer: png })
    const t = await h.toast(page, /已上傳暫存影像「scratch-e2e.png」（640×480）/)
    await page.getByTestId('scratch-badge').waitFor({ timeout: 8000 })
    const badge = await page.getByTestId('scratch-badge').innerText()
    const reuseDisabled = await page.getByTestId('reuse-image').isDisabled()
    await h.shot(page, 'editor-scratch')
    await page.getByTestId('scratch-clear').click()
    const cleared = (await page.getByTestId('scratch-badge').count()) === 0 && (await page.getByTestId('btn-scratch').count()) === 1
    h.item('F07', Boolean(t) && badge.includes('scratch-e2e.png') && badge.includes('640×480') && reuseDisabled && cleared, `toast=${t} badge=${badge} reuseDisabled=${reuseDisabled} cleared=${cleared}`)
  })

  await h.step('F04 問題計數', async () => {
    await dropTool('crop', 0.7, 0.7)
    await page.waitForTimeout(300)
    const txt = await toolbar().innerText()
    const nodeProblem = await page.locator('.react-flow__node[data-id="crop-1"]').innerText()
    const insp = await inspector().innerText()
    await h.shot(page, 'editor-problems')
    h.item('F04', /\d+ 個問題/.test(txt), `toolbar=${txt.replace(/\n/g, '|').slice(0, 100)}`)
    h.item('I20', nodeProblem.includes('必填') || nodeProblem.includes('尚未連線'), `node=${nodeProblem.replace(/\n/g, '|')}`)
    h.item('K03', insp.includes('參數問題'), `inspector=${insp.slice(0, 200).replace(/\n/g, '|')}`)
    await page.keyboard.press('Control+s')
    const t = await h.toast(page, /有 \d+ 個步驟的參數有問題/)
    h.item('F04', Boolean(t), '存檔時未顯示參數問題 warning')
    await page.keyboard.press('Delete')
    await page.waitForTimeout(200)
    await page.keyboard.press('Control+s')
    await h.toast(page, /流程已儲存/)
  })

  // ============ K. 側欄 ============
  await h.step('K01 無選取', async () => {
    await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
    await page.waitForTimeout(200)
    const txt = await inspector().innerText()
    const desc = inspector().getByLabel('描述')
    await desc.fill('E2E 描述')
    const dirty = (await toolbar().innerText()).includes('有未儲存的變更')
    const interval = inspector().getByLabel('連續執行間隔（ms）')
    await interval.fill('250')
    await page.waitForTimeout(800)
    const saved = (await h.api.get(`/vision/flows/${flowId}`)).continuous_interval_ms
    h.item('K01', txt.includes('選取畫布上的步驟') && dirty && saved === 250, `hint=${txt.includes('選取畫布上的步驟')} dirty=${dirty} interval=${saved}`)
    await page.keyboard.press('Control+s')
    await h.toast(page, /流程已儲存/)
  })

  await h.step('K02 選取工具', async () => {
    await clickNode('blob')
    await page.waitForTimeout(300)
    const insp = inspector()
    const txt = await insp.innerText()
    const iconLink = await insp.getByTestId('open-tool-page-icon').getAttribute('href')
    const btnLink = await insp.getByTestId('open-tool-page').getAttribute('href')
    const nameInput = insp.getByLabel('名稱')
    const ph = await nameInput.getAttribute('placeholder')
    await nameInput.fill('孔 blob（改）')
    const nodeLabel = await page.locator('.react-flow__node[data-id="blob"]').innerText()
    await insp.getByLabel('備註').fill('備註內容')
    const colorBtns = await insp.locator('button[aria-label^="#"]').count()
    await insp.locator('button[aria-label="#be123c"]').click()
    await page.waitForTimeout(200)
    const bg = await page.locator('.react-flow__node[data-id="blob"] > div').first().evaluate((el) => el.style.background)
    const fg = await page.locator('.react-flow__node[data-id="blob"] > div').first().evaluate((el) => el.style.color)
    await h.shot(page, 'inspector-color')
    await insp.getByRole('button', { name: '還原' }).click()
    const bgReset = await page.locator('.react-flow__node[data-id="blob"] > div').first().evaluate((el) => el.style.background)
    const colorInput = insp.locator('input[type=color]')
    await colorInput.evaluate((el) => {
      // React 受控輸入：要用原生 setter 才會觸發 onChange
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, '#ffffff')
      el.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await page.waitForTimeout(200)
    const fgWhiteBg = await page.locator('.react-flow__node[data-id="blob"] > div').first().evaluate((el) => el.style.color)
    await insp.getByRole('button', { name: '還原' }).click()
    const checks = insp.getByRole('checkbox')
    const enabledLabel = await insp.getByLabel('啟用此步驟').isChecked()
    await insp.getByLabel('出錯時繼續').check()
    const coe = (await h.api.get(`/vision/flows/${flowId}`)).graph.nodes.find((n) => n.id === 'blob').continue_on_error
    h.item('K02', iconLink === `/flows/${flowId}/tools/blob` && btnLink === iconLink && ph === 'Blob 分析' && nodeLabel.includes('孔 blob（改）') && colorBtns === 8 && bg.includes('190, 18, 60') && fg.includes('248, 250, 252') && bgReset === '' && fgWhiteBg.includes('15, 23, 42') && (await checks.count()) === 2 && enabledLabel && txt.includes('輸入：') && txt.includes('輸出：') && txt.includes('id: blob') && (await insp.getByRole('button', { name: '刪除步驟' }).count()) === 1, `icon=${iconLink} ph=${ph} label=${nodeLabel.includes('孔 blob（改）')} colors=${colorBtns} bg=${bg} fg=${fg} reset=${bgReset} fgWhite=${fgWhiteBg} coe(unsaved)=${coe}`)
    h.item('I22', fg.includes('248, 250, 252') && fgWhiteBg.includes('15, 23, 42'), `深底字色=${fg} 淺底字色=${fgWhiteBg}`)
    await insp.getByLabel('出錯時繼續').uncheck()
    await insp.getByLabel('名稱').fill('孔 blob')
  })

  await h.step('K04 I21 註解', async () => {
    await clickNode('n1')
    await page.waitForTimeout(300)
    const insp = inspector()
    const txt = await insp.innerText()
    const noTool = (await insp.getByTestId('open-tool-page').count()) === 0
    const rows = await insp.getByLabel('備註').getAttribute('rows')
    const noChecks = (await insp.getByRole('checkbox').count()) === 0
    h.item('K04', noTool && rows === '5' && noChecks && !txt.includes('輸入：'), `noTool=${noTool} rows=${rows} noChecks=${noChecks}`)
    const resizer = page.locator('.react-flow__node[data-id="n1"] .react-flow__resize-control.bottom-right, .react-flow__node[data-id="n1"] .react-flow__resize-control.handle.bottom.right')
    const handles = await page.locator('.react-flow__node[data-id="n1"] .react-flow__resize-control').count()
    const before = await page.locator('.react-flow__node[data-id="n1"]').boundingBox()
    const hb = await resizer.first().boundingBox()
    if (hb) {
      await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2)
      await page.mouse.down()
      await page.mouse.move(hb.x + 60, hb.y + 40, { steps: 6 })
      await page.mouse.up()
    }
    await page.waitForTimeout(300)
    const after = await page.locator('.react-flow__node[data-id="n1"]').boundingBox()
    await insp.getByLabel('備註').fill('多行\n第二行\n第三行')
    const noteTxt = await page.locator('.react-flow__node[data-id="n1"]').innerText()
    await h.shot(page, 'note-resized')
    h.item('I21', handles > 0 && after && before && after.width > before.width + 20 && noteTxt.includes('第三行'), `handles=${handles} w ${before?.width}→${after?.width} text=${noteTxt.replace(/\n/g, '|')}`)
    await page.keyboard.press('Control+z')
    await page.keyboard.press('Escape')
  })

  // ============ F15-F16 復原／自動排列 ============
  await h.step('F15 F16 I23 復原與自動排列', async () => {
    await page.keyboard.press('Escape')
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(350)
    const node = page.locator('.react-flow__node[data-id="gray"]')
    const b0 = await node.boundingBox()
    await page.mouse.move(b0.x + 30, b0.y + 12)
    await page.mouse.down()
    await page.mouse.move(b0.x + 130, b0.y + 92, { steps: 8 })
    await page.mouse.up()
    await page.waitForTimeout(300)
    const b1 = await node.boundingBox()
    const moved = Math.abs(b1.x - b0.x) > 50
    const dirty = (await toolbar().innerText()).includes('有未儲存的變更')
    h.item('I23', moved && dirty, `moved=${moved} dirty=${dirty}`)
    await toolbar().getByRole('button', { name: '復原（Ctrl+Z）' }).click()
    await page.waitForTimeout(300)
    const b2 = await node.boundingBox()
    h.item('F15', Math.abs(b2.x - b0.x) < 5 && Math.abs(b2.y - b0.y) < 5, `undo → ${Math.round(b2.x)},${Math.round(b2.y)} (原 ${Math.round(b0.x)},${Math.round(b0.y)})`)
    const posBefore = await nodes().evaluateAll((els) => els.map((e) => e.style.transform).join(';'))
    await toolbar().getByRole('button', { name: '依資料流從左到右分層排列' }).click()
    await page.waitForTimeout(600)
    const posAfter = await nodes().evaluateAll((els) => els.map((e) => e.style.transform).join(';'))
    await h.shot(page, 'editor-autolayout')
    h.item('F16', posBefore !== posAfter && (await toolbar().innerText()).includes('有未儲存的變更'), `changed=${posBefore !== posAfter}`)
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(300)
  })

  // ============ F09-F12 執行 ============
  await h.step('F09 F10 執行一次／上傳影像執行已移除', async () => {
    const txt = await toolbar().innerText()
    const noRun = (await page.getByTestId('btn-run').count()) === 0 && (await page.getByTestId('btn-run-file').count()) === 0 && !txt.includes('執行一次') && !txt.includes('上傳影像執行')
    // 頂列只剩一個隱藏 file input（上傳暫存影像）
    const fileInputs = await toolbar().locator('input[type=file]').count()
    const rows = await toolbar().locator('[data-testid^=toolbar-row-]').count()
    h.item('F24', noRun && fileInputs === 1 && rows === 2 && txt.includes('試跑') && txt.includes('上傳暫存影像'), `noRun=${noRun} fileInputs=${fileInputs} rows=${rows} toolbar=${txt.replace(/\n/g, '|')}`)
    h.skip('F09', '已移除：「執行一次」按鈕（整合方走 API／整合頁）')
    h.skip('F10', '已移除：「上傳影像執行」按鈕（只保留「上傳暫存影像」）')
  })

  await h.step('F25 頂列兩列在 1280／1440／1920 換行不重疊、無水平捲軸', async () => {
    const notes = []
    let ok = true
    for (const [w, hgt] of [[1280, 800], [1440, 900], [1920, 1080]]) {
      await page.setViewportSize({ width: w, height: hgt })
      await page.waitForTimeout(500)
      const info = await page.evaluate(() => {
        const bar = document.querySelector('[data-testid=editor-toolbar]')
        const els = [...bar.querySelectorAll('button, input:not([type=file]), select, a, label, [data-testid=scratch-badge]')].filter((e) => !e.closest('[role=menu]'))
        const boxes = els.map((e) => e.getBoundingClientRect()).filter((r) => r.width > 0 && r.height > 0)
        let overlap = 0
        for (let i = 0; i < boxes.length; i += 1)
          for (let j = i + 1; j < boxes.length; j += 1) {
            const a = boxes[i]
            const b = boxes[j]
            // 巢狀元素（label 裡的 checkbox）不算重疊
            if (els[i].contains(els[j]) || els[j].contains(els[i])) continue
            if (a.x < b.x + b.width - 1 && b.x < a.x + a.width - 1 && a.y < b.y + b.height - 1 && b.y < a.y + a.height - 1) overlap += 1
          }
        const inside = boxes.every((r) => r.x >= 0 && r.x + r.width <= window.innerWidth + 1)
        return { overlap, inside, hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth || document.body.scrollWidth > window.innerWidth, barH: bar.getBoundingClientRect().height, n: boxes.length }
      })
      await h.shot(page, `toolbar-${w}`)
      if (info.overlap || !info.inside || info.hscroll) ok = false
      notes.push(`${w}:${JSON.stringify(info)}`)
    }
    await page.setViewportSize({ width: 1600, height: 1000 })
    await page.waitForTimeout(300)
    h.item('F25', ok, notes.join(' '))
  })

  await h.step('F11 連續執行', async () => {
    await page.getByTestId('btn-continuous').click()
    const t1 = await h.toast(page, /已啟動連續執行/)
    await page.waitForTimeout(2500)
    const btn = page.getByTestId('btn-continuous')
    const label = await btn.innerText()
    const active = (await btn.getAttribute('aria-pressed')) === 'true'
    const txt = await toolbar().innerText()
    const fps = /\d+(\.\d+)? fps/.test(txt) || /· \d+ ms/.test(txt)
    await h.shot(page, 'editor-continuous')
    await btn.click()
    const t2 = await h.toast(page, /已停止連續執行/)
    await page.waitForTimeout(800)
    const cont = (await h.api.get(`/vision/flows/${flowId}`)).continuous
    h.item('F11', Boolean(t1) && label.includes('連續執行中') && active && fps && Boolean(t2) && !cont, `t1=${t1} label=${label} active=${active} fps=${fps} t2=${t2} cont=${cont}`)
  })

  // ============ L. 結果分頁 ============
  await h.step('L01 L03 L04 L05 結果分頁', async () => {
    await page.getByRole('tab', { name: /結果/ }).click()
    await page.waitForTimeout(400)
    const tabBadge = await page.getByRole('tab', { name: /結果/ }).innerText()
    const table = inspector().locator('table').first()
    const head = await table.locator('thead').innerText()
    const rows = await table.locator('tbody tr').count()
    await table.locator('tbody tr').nth(1).click()
    await page.waitForTimeout(500)
    const latestBtn = page.getByRole('button', { name: '最新' })
    const pinned = (await latestBtn.count()) === 1
    const selectedRow = await table.locator('tbody tr').nth(1).evaluate((el) => el.className.includes('bg-brand-soft'))
    await h.shot(page, 'results-pinned')
    await latestBtn.click()
    await page.waitForTimeout(300)
    const unpinned = (await latestBtn.count()) === 0
    h.item('L01', /OK|NG|失敗/.test(tabBadge), `tab=${tabBadge}`)
    h.item('L03', ['時間', '狀態', 'ms', '觸發', '輸出摘要'].every((k) => head.toLowerCase().includes(k.toLowerCase())) && rows >= 3 && pinned && selectedRow && unpinned, `head=${head.replace(/\n/g, '|')} rows=${rows} pinned=${pinned} selected=${selectedRow} unpinned=${unpinned}`)
    await clickNode('blob')
    await page.waitForTimeout(300)
    const txt = await inspector().innerText()
    h.item('L04', ['狀態', '耗時', '標記', '輸出', 'count', 'image', 'blobs'].every((k) => txt.includes(k)) && /\d+\.\d ms/.test(txt), `result=${txt.slice(0, 300).replace(/\n/g, '|')}`)
    h.item('L05', txt.includes('流程輸出') && txt.includes('hole_count'), '流程輸出表缺失')
    await clickNode('n1')
    await page.getByRole('tab', { name: /結果/ }).click()
    await page.waitForTimeout(300)
    const noRes = (await inspector().innerText()).includes('此步驟尚無結果')
    h.item('L06', noRes, '選取無結果的步驟未顯示「此步驟尚無結果」')
    await page.getByRole('tab', { name: /設定/ }).click()
  })

  await h.step('I18 雙擊步驟開工具頁（草稿帶過去）', async () => {
    // 改版後：雙擊步驟卡片直接開工具頁；未儲存的改名要一起帶過去、返回後仍 dirty
    // 先試跑一次：F11 連續執行跑了 >8 次，舊試跑的影像已被淘汰（KEEP_RUN_IMAGES），工具頁掛載時會先拿舊 ref → 404
    await page.getByTestId('btn-preview').click()
    await h.toast(page, /試跑完成/, 15000)
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(350)
    await page.locator('.react-flow__node[data-id="blob"]').click()
    const name = inspector().getByLabel('名稱')
    await name.fill('Blob 雙擊')
    await page.locator('.react-flow__node[data-id="blob"]').dblclick()
    await page.waitForURL(/\/tools\/blob$/, { timeout: 5000 })
    await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
    const hdr = await page.locator('[data-testid=tool-page] header').innerText()
    const dirtyOnTool = hdr.includes('有未儲存的變更') && hdr.includes('Blob 雙擊')
    await page.getByTestId('btn-back').click()
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(400)
    const editorDirty = (await toolbar().innerText()).includes('有未儲存的變更')
    const kept = (await page.locator('.react-flow__node[data-id="blob"]').innerText()).includes('Blob 雙擊')
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(350)
    await page.locator('.react-flow__node[data-id="blob"]').click()
    await inspector().getByLabel('名稱').fill('')
    await page.keyboard.press('Control+s')
    await h.toast(page, /流程已儲存/)
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    h.item('I18', dirtyOnTool && editorDirty && kept, `toolHeader=${hdr.replace(/\n/g, '|').slice(0, 80)} editorDirty=${editorDirty} kept=${kept}`)
  })

  // ============ 錯誤節點（I19 L02） ============
  await h.step('I19 L02 錯誤節點', async () => {
    const g = (await h.api.get(`/vision/flows/${flowId}`)).graph
    g.nodes.find((n) => n.id === 'src').params = { source_id: 1, mode: 'input' }
    await h.api.patch(`/vision/flows/${flowId}`, { graph: g })
    await open()
    await page.getByTestId('btn-preview').click()
    await h.toast(page, /試跑完成：失敗/, 10000)
    await page.waitForTimeout(600)
    const err = await page.getByTestId('node-error').innerText().catch(() => '')
    const ring = await page.locator('.react-flow__node[data-id="src"] > div').first().evaluate((el) => el.className.includes('border-critical'))
    const skipped = await page.locator('.react-flow__node[data-id="gray"] > div').first().evaluate((el) => el.className.includes('opacity-60'))
    const ms = await page.locator('.react-flow__node[data-id="src"]').innerText()
    await h.shot(page, 'editor-error-node')
    h.item('I19', err.includes('暫存影像') && ring && skipped && /\d+ ms/.test(ms), `err=${err} ring=${ring} skipped=${skipped}`)
    await page.getByRole('tab', { name: /結果/ }).click()
    const block = page.getByTestId('run-error')
    const btxt = await block.innerText()
    await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
    await page.getByTestId('goto-failed-node').click()
    await page.waitForTimeout(400)
    const selected = (await page.locator('.react-flow__node[data-id="src"].selected').count()) === 1
    const runErr = (await inspector().innerText()).includes('暫存影像')
    h.item('L02', btxt.includes('執行失敗') && btxt.includes('暫存影像') && selected && runErr, `block=${btxt.replace(/\n/g, '|')} selected=${selected}`)
    g.nodes.find((n) => n.id === 'src').params = { source_id: 1 }
    await h.api.patch(`/vision/flows/${flowId}`, { graph: g })
  })

  // ============ F12 重置 ============
  await h.step('F12 重置', async () => {
    await open()
    await page.getByTestId('btn-preview').click()
    await h.toast(page, /試跑完成/)
    await page.getByTestId('btn-reset').click()
    const dlg = h.dialog(page)
    const msg = await dlg.innerText()
    await dlg.getByRole('button', { name: '重置' }).click()
    const t = await h.toast(page, /已重置/)
    await page.waitForTimeout(800)
    await page.getByRole('tab', { name: /結果/ }).click()
    const txt = await inspector().innerText()
    const noImage = !(await h.viewerHasImage(page, '[data-testid=viewer-main]'))
    const viewerEmpty = (await page.locator('[data-testid=viewer-main]').innerText()).includes('尚無影像')
    await h.shot(page, 'editor-after-reset')
    h.item('F12', msg.includes('確定要重置') && Boolean(t) && txt.includes('還沒有執行記錄') && noImage && viewerEmpty, `msg=${msg.slice(0, 40)} toast=${t} noRuns=${txt.includes('還沒有執行記錄')} noImage=${noImage}`)
    h.item('J01', viewerEmpty, '重置後影像視窗未顯示「尚無影像」')
    h.item('L06', txt.includes('還沒有執行記錄'), '重置後未顯示「還沒有執行記錄」')
    await page.getByRole('tab', { name: /設定/ }).click()
  })

  // ============ E07-E09 範本 ============
  await h.step('E08 存為範本', async () => {
    await page.getByTestId('btn-templates').click()
    await page.getByTestId('menu-save-template').click()
    const dlg = h.dialog(page)
    const def = await page.getByTestId('save-template-name').inputValue()
    const cats = await dlg.locator('select option').allInnerTexts()
    await page.getByTestId('save-template-name').fill('E2E 自訂範本')
    await dlg.getByLabel('描述').fill('測試用')
    await dlg.locator('select').selectOption('count')
    await page.getByTestId('save-template-confirm').click()
    const t1 = await h.toast(page, /已存為範本「E2E 自訂範本」/)
    await h.waitGone(page.locator('[role=dialog]'))
    const un = h.allowStatus(/4\d\d POST .*\/api\/vision\/templates/)
    await page.getByTestId('btn-templates').click()
    await page.getByTestId('menu-save-template').click()
    await page.getByTestId('save-template-name').fill('E2E 自訂範本')
    await page.getByTestId('save-template-confirm').click()
    const t2 = await h.toast(page, /已有同名範本|同名/)
    un()
    await page.keyboard.press('Escape')
    await h.waitGone(page.locator('[role=dialog]'))
    h.item('E08', def === 'E2E 編輯器測試' && cats.length === 6 && Boolean(t1) && Boolean(t2), `default=${def} cats=${cats.join('|')} t1=${t1} t2=${t2}`)
  })

  await h.step('E07 載入範本', async () => {
    await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
    await inspector().getByLabel('描述').fill('dirty 一下')
    await page.getByTestId('btn-templates').click()
    await page.getByTestId('menu-load-template').click()
    await page.getByTestId('template-card').first().waitFor()
    await page.locator('[data-template-id="builtin:exposure"]').click()
    h.nextDialog(page, false)
    await page.getByTestId('template-confirm').click()
    await page.waitForTimeout(500)
    const stillOpen = (await page.locator('[role=dialog]').count()) === 1
    const stillSelected = !(await page.getByTestId('template-confirm').isDisabled())
    const countBefore = await nodes().count()
    h.nextDialog(page, true)
    await page.getByTestId('template-confirm').click()
    const t = await h.toast(page, /已載入範本/)
    await page.waitForTimeout(800)
    const ids = await nodes().evaluateAll((els) => els.map((e) => e.getAttribute('data-id')))
    await h.shot(page, 'editor-template-loaded')
    h.item('E07', stillOpen && stillSelected && Boolean(t) && ids.every((id) => id.startsWith('t1_')) && ids.length !== countBefore, `cancelKept=${stillOpen} selectionKept=${stillSelected} toast=${t} ids=${ids.join(',')}`)
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(300)
    await page.keyboard.press('Control+s')
    await h.toast(page, /流程已儲存/)
  })

  await h.step('E09 刪除自訂範本', async () => {
    await page.getByTestId('btn-templates').click()
    await page.getByTestId('menu-load-template').click()
    await page.getByTestId('template-card').first().waitFor()
    const custom = page.getByTestId('template-card').filter({ hasText: 'E2E 自訂範本' })
    const builtinDel = await page.locator('[data-template-id="builtin:exposure"]').getByTestId('template-delete').count()
    const badge = (await custom.innerText()).includes('自訂')
    await custom.getByTestId('template-delete').click()
    const dlg = h.dialog(page)
    const msg = await dlg.innerText()
    await dlg.getByRole('button', { name: '刪除' }).click()
    const t = await h.toast(page, /已刪除範本/)
    await page.waitForTimeout(500)
    const gone = (await page.getByTestId('template-card').filter({ hasText: 'E2E 自訂範本' }).count()) === 0
    await page.keyboard.press('Escape')
    await h.waitGone(page.locator('[role=dialog]'))
    h.item('E09', builtinDel === 0 && badge && msg.includes('E2E 自訂範本') && Boolean(t) && gone, `builtinDel=${builtinDel} badge=${badge} msg=${msg.slice(0, 40)} toast=${t} gone=${gone}`)
  })

  // ============ F23 停用流程 ============
  await h.step('F23 停用流程的頂列', async () => {
    await h.api.patch(`/vision/flows/${flowId}`, { is_enabled: false })
    await open()
    const badge = (await page.getByTestId('flow-disabled-badge').count()) === 1
    const contDis = await page.getByTestId('btn-continuous').isDisabled()
    const previewOk = !(await page.getByTestId('btn-preview').isDisabled())
    await h.shot(page, 'editor-flow-disabled')
    await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
    await inspector().getByLabel('啟用（允許外部觸發）').click()
    await page.waitForTimeout(800)
    const enabled = (await h.api.get(`/vision/flows/${flowId}`)).is_enabled === true
    const badgeGone = (await page.getByTestId('flow-disabled-badge').count()) === 0
    h.item('F23', badge && contDis && previewOk && enabled && badgeGone, `badge=${badge} cont=${contDis} preview=${previewOk} enabled=${enabled} badgeGone=${badgeGone}`)
  })

  // ============ F21 離開攔截 ============
  await h.step('F21 離開攔截', async () => {
    await page.locator('.react-flow__pane').click({ position: { x: 5, y: 5 } })
    await inspector().getByLabel('描述').fill('未存')
    // 到參數卡不算離開（草稿帶過去）：不會問；回到編輯器仍是 dirty
    let asked = 0
    page.__dialog = (d) => {
      asked += 1
      d.dismiss()
    }
    await page.getByTestId('btn-teach').click()
    await page.waitForURL(/\/teach$/, { timeout: 5000 })
    await page.getByTestId('teach-group').first().waitFor({ timeout: 15000 })
    const teachNoAsk = asked === 0 && /\/teach$/.test(page.url())
    await page.getByTestId('btn-back').click()
    await page.waitForURL(new RegExp(`/flows/${flowId}$`), { timeout: 5000 })
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(400)
    const stillDirty = (await toolbar().innerText()).includes('有未儲存的變更')
    page.__dialog = null
    // 到總覽／流程列表（其他路由）要問：取消留在頁面
    h.nextDialog(page, false)
    await page.getByTestId('nav-dashboard').click()
    await page.waitForTimeout(600)
    const stayedDash = new RegExp(`/flows/${flowId}$`).test(page.url())
    h.nextDialog(page, false)
    await page.getByTestId('nav-flows').click()
    await page.waitForTimeout(600)
    const stayed = new RegExp(`/flows/${flowId}$`).test(page.url())
    h.nextDialog(page, true)
    await page.getByTestId('nav-flows').click()
    await page.waitForURL(/\/flows$/, { timeout: 5000 })
    h.item('F21', teachNoAsk && stillDirty && stayedDash && stayed && /\/flows$/.test(page.url()), `teachNoAsk=${teachNoAsk} stillDirty=${stillDirty} stayedDash=${stayedDash} stayed=${stayed} url=${page.url()}`)
  })

  await context.close()
}
