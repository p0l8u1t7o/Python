/** 模組 canvas：畫布（I）——節點呈現、連線與拒絕、框選、多選、右鍵選單、快捷鍵、縮放、小地圖。 */
import { BASE } from './full-lib.mjs'

export async function run(h) {
  await h.loginAdmin()
  const context = await h.newContext({ token: h.token })
  // 畫布佔中欄 70%，節點才夠大好拖。
  await context.addInitScript(() => localStorage.setItem('vs.editorLayout', JSON.stringify({ left: 220, right: 320, canvas: 0.7 })))
  // 改版後畫布預設「平移」；框選相關（I08／I10／I12）在 open() 先切到「選取」模式，I09 再驗證預設平移＋Shift 框選
  // 選取／平移切換鈕在畫布右上角（.react-flow__panel.top.right[data-testid=canvas-mode]），不在頂列
  const page = await h.newPage(context, '[canvas]')

  const graph = {
    nodes: [
      { id: 'src', type: 'image_source', label: '取像', params: { source_id: 1 }, position: { x: 40, y: 40 } },
      { id: 'A', type: 'grayscale', label: 'A 灰階', params: {}, position: { x: 360, y: 40 } },
      { id: 'B', type: 'grayscale', label: 'B 灰階', params: {}, position: { x: 680, y: 40 } },
      { id: 'C', type: 'grayscale', label: 'C 灰階', params: {}, position: { x: 360, y: 260 } },
      { id: 'blob', type: 'blob', label: 'Blob', params: { min_area: 300 }, position: { x: 680, y: 260 } },
      { id: 'cmp', type: 'if_number', label: '比較', params: { operator: 'eq', threshold: 5 }, position: { x: 1000, y: 260 } },
      { id: 'n1', type: 'note', label: '註解', description: '這是註解', params: {}, position: { x: 1000, y: 40 } },
    ],
    edges: [],
  }
  const created = await h.api.post('/vision/flows', { name: 'E2E 畫布測試', description: '', graph })
  const flowId = created.id
  const modeBtn = (name) => page.locator('.react-flow__panel.top.right[data-testid=canvas-mode]').getByRole('button', { name })
  const open = async ({ mode = 'select' } = {}) => {
    await page.goto(`${BASE}/flows/${flowId}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(600)
    if (mode === 'select' && (await modeBtn('選取').getAttribute('aria-pressed')) !== 'true') await modeBtn('選取').click()
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(500)
  }
  const nodes = () => page.locator('.react-flow__node')
  const edges = () => page.locator('.react-flow__edge')
  const node = (id) => page.locator(`.react-flow__node[data-id="${id}"]`)
  const handle = (id, hid, type) => page.locator(`.react-flow__node[data-id="${id}"] .react-flow__handle.${type}[data-handleid="${hid}"]`)
  const center = async (loc) => {
    const b = await loc.boundingBox()
    if (!b) throw new Error('no bounding box')
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 }
  }
  const drag = async (from, to, steps = 12) => {
    await page.mouse.move(from.x, from.y)
    await page.mouse.down()
    await page.mouse.move(from.x + 5, from.y + 5, { steps: 2 })
    await page.mouse.move(to.x, to.y, { steps })
    await page.mouse.up()
    await page.waitForTimeout(250)
  }
  const connect = async (a, ah, b, bh) => {
    const from = await center(handle(a, ah, 'source'))
    const to = await center(handle(b, bh, 'target'))
    const before = await edges().count()
    await drag(from, to)
    return (await edges().count()) - before
  }
  /** 點在邊的路徑中點上（邊的 bounding box 中心常常不在線上）。 */
  const clickEdge = async (idPrefix) => {
    await page.keyboard.press('Escape')
    for (const frac of [0.5, 0.3, 0.7]) {
      const pt = await page.evaluate(({ prefix, frac }) => {
        const g = document.querySelector(`.react-flow__edge[data-id^="${prefix}"]`)
        const path = g?.querySelector('path.react-flow__edge-path')
        if (!path) return null
        const p = path.getPointAtLength(path.getTotalLength() * frac)
        const m = path.getScreenCTM()
        return { x: p.x * m.a + p.y * m.c + m.e, y: p.x * m.b + p.y * m.d + m.f }
      }, { prefix: idPrefix, frac })
      if (!pt) throw new Error(`edge ${idPrefix} not found`)
      await page.mouse.click(pt.x, pt.y)
      await page.waitForTimeout(200)
      if ((await page.locator(`.react-flow__edge.selected[data-id^="${idPrefix}"]`).count()) === 1) return true
    }
    h.note(`edge ${idPrefix} could not be selected by clicking`)
    return false
  }
  const dirty = async () => (await page.locator('[data-testid=editor-toolbar]').innerText()).includes('有未儲存的變更')

  await open()
  await h.shot(page, 'canvas')

  await h.step('I01 節點呈現', async () => {
    const blob = node('blob')
    const txt = await blob.innerText()
    const diamond = await blob.locator('.react-flow__handle[data-handleid="_flow"]').evaluate((el) => el.className.includes('rotate-45'))
    const required = await blob.locator('.text-critical').count()
    const overlays = await blob.locator('.react-flow__handle[data-handleid="_overlays"]').evaluate((el) => el.className.includes('size-2') && !el.className.includes('size-2.5'))
    const flowOut = await blob.locator('.react-flow__handle.source[data-handleid="found"]').evaluate((el) => el.className.includes('rotate-45'))
    const icon = (await blob.locator('svg').count()) > 0
    h.item('I01', txt.includes('Blob') && txt.includes('Blob 分析') && diamond && required >= 1 && overlays && flowOut && icon, `text=${txt.replace(/\n/g, '|')} diamond=${diamond} required=${required} implicit=${overlays} flowOut=${flowOut}`)
  })

  await h.step('I02 連線成功', async () => {
    const added = await connect('src', 'image', 'A', 'image')
    const added2 = await connect('A', 'image', 'B', 'image')
    const edgeColor = await edges().first().locator('path.react-flow__edge-path').evaluate((el) => getComputedStyle(el).stroke)
    await h.shot(page, 'canvas-connected')
    h.item('I02', added === 1 && added2 === 1 && (await dirty()) && edgeColor.includes('59, 130, 246'), `added=${added},${added2} dirty=${await dirty()} stroke=${edgeColor}`)
  })

  await h.step('I06 迴圈拒絕', async () => {
    await connect('src', 'image', 'blob', 'image')
    await connect('blob', 'count', 'cmp', 'value')
    const before = await edges().count()
    // B.image → C.image → 再 C.image → A.image 會形成 src→A→B→C→A 迴圈
    await connect('B', 'image', 'C', 'image')
    await h.waitGone(page.locator('[role=status] .card'), 3000)
    const from = await center(handle('C', 'image', 'source'))
    const to = await center(handle('A', 'image', 'target'))
    await drag(from, to)
    // A.image 已接 src → singleInput 先擋；改用 A 的控制輸入不行（型別不同）。改測：C.image→B.image？B 已接。
    // 所以把 B←A 那條先刪掉：選邊後 Delete
    const t0 = await h.toast(page, /只能接一條線|迴圈/, 2000)
    const after = await edges().count()
    h.item('I05', Boolean(t0) && t0.includes('只能接一條線') && after === before + 1, `toast=${t0} edges ${before}→${after}`)
    // 刪除 src→A，讓 A.image 空出來，再 C→A 形成迴圈 A→B→C→A
    const srcA = page.locator('.react-flow__edge').filter({ has: page.locator('[data-id]') })
    void srcA
    await clickEdge('xy-edge__srcimage-Aimage')
    await page.keyboard.press('Delete')
    await page.waitForTimeout(200)
    const removed = await edges().count()
    await h.waitGone(page.locator('[role=status] .card'), 3000)
    const edgeIds = await edges().evaluateAll((els) => els.map((e) => e.getAttribute('data-id')))
    await drag(await center(handle('C', 'image', 'source')), await center(handle('A', 'image', 'target')))
    const t1 = await h.toast(page, /迴圈|只能接一條線|不能連到/, 2000)
    await h.shot(page, 'canvas-cycle')
    h.item('I06', Boolean(t1) && t1.includes('迴圈') && (await edges().count()) === removed, `toast=${t1} edges=${await edges().count()} (expected ${removed}) edgeIds=${edgeIds.join(',')}`)
    h.item('I15', removed === after - 1, `選邊 Delete 後 edges ${after}→${removed}`)
    await connect('src', 'image', 'A', 'image')
  })

  await h.step('I03 I04 型別不相容／分支把手', async () => {
    await h.waitGone(page.locator('[role=status] .card'), 3000)
    const before = await edges().count()
    await drag(await center(handle('blob', 'count', 'source')), await center(handle('C', 'image', 'target')))
    const t1 = await h.toast(page, /不能連到/, 2000)
    await h.shot(page, 'canvas-incompatible-toast')
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    await drag(await center(handle('cmp', 'true', 'source')), await center(handle('C', 'image', 'target')))
    const t2 = await h.toast(page, /分支把手只能接到/, 2000)
    await h.waitGone(page.locator('[role=status] .card'), 4000)
    const flowOk = await connect('cmp', 'true', 'C', '_flow')
    h.item('I03', Boolean(t1) && (await edges().count()) === before + 1, `toast=${t1}`)
    h.item('I04', Boolean(t2) && flowOk === 1, `toast=${t2} flow→控制輸入 added=${flowOk}`)
  })

  h.skip('I07', '註解節點沒有輸入把手，UI 上拉不到線；規則由 graphValidation.checkConnection 的 noteTarget 涵蓋')

  await h.step('I08 I10 框選與多選', async () => {
    await page.keyboard.press('Escape')
    const a = await node('A').boundingBox()
    const b = await node('B').boundingBox()
    const x0 = Math.min(a.x, b.x) - 30
    const y0 = Math.min(a.y, b.y) - 30
    const x1 = Math.max(a.x + a.width, b.x + b.width) + 30
    const y1 = Math.max(a.y + a.height, b.y + b.height) + 30
    await drag({ x: x0, y: y0 }, { x: x1, y: y1 })
    const n = await page.locator('.react-flow__node.selected').count()
    const multi = await page.getByTestId('multi-select').innerText().catch(() => '')
    const modeInCanvas = (await page.locator('.react-flow__panel.top.right[data-testid=canvas-mode] button').count()) === 2 && (await page.locator('[data-testid=editor-toolbar]').getByRole('button', { name: '選取' }).count()) === 0
    await h.shot(page, 'canvas-box-select')
    h.item('I08', n === 2 && multi.includes('已選取 2 個步驟') && modeInCanvas, `selected=${n} multi=${multi.replace(/\n/g, '|')} modeInCanvas=${modeInCanvas}`)
    h.item('K05', multi.includes('刪除這 2 個步驟'), '多選摘要缺刪除按鈕')
    // 多選拖曳
    const a0 = await node('A').boundingBox()
    const b0 = await node('B').boundingBox()
    await drag({ x: a0.x + 40, y: a0.y + 12 }, { x: a0.x + 40, y: a0.y + 112 }, 8)
    const a1 = await node('A').boundingBox()
    const b1 = await node('B').boundingBox()
    const bothMoved = a1.y - a0.y > 60 && b1.y - b0.y > 60
    const count = await nodes().count()
    await page.keyboard.press('Delete')
    await page.waitForTimeout(200)
    const afterDel = await nodes().count()
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(300)
    const restored = await nodes().count()
    await drag({ x: x0, y: y0 }, { x: x1, y: y1 + 100 })
    const selAgain = await page.locator('.react-flow__node.selected').count()
    await page.getByRole('button', { name: /刪除這 \d+ 個步驟/ }).click()
    await page.waitForTimeout(200)
    const afterBtn = await nodes().count()
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(300)
    const finalCount = await nodes().count()
    // 再復原一次把 A／B 移回原位（拖曳也有進歷史）
    await page.keyboard.press('Escape')
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(300)
    h.item('I10', bothMoved && afterDel === count - 2 && restored === count && afterBtn === count - selAgain && finalCount === count, `bothMoved=${bothMoved} del ${count}→${afterDel} undo=${restored} btn=${afterBtn} final=${await nodes().count()}`)
    h.item('I13', restored === count, 'Ctrl+Z 未還原刪除')
  })

  await h.step('I12 複製貼上', async () => {
    await page.keyboard.press('Escape')
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(400)
    const a = await node('A').boundingBox()
    const b = await node('B').boundingBox()
    await drag({ x: Math.min(a.x, b.x) - 30, y: Math.min(a.y, b.y) - 30 }, { x: Math.max(a.x + a.width, b.x + b.width) + 30, y: Math.max(a.y + a.height, b.y + b.height) + 30 })
    const n0 = await nodes().count()
    const e0 = await edges().count()
    await page.keyboard.press('Control+c')
    await page.keyboard.press('Control+v')
    await page.waitForTimeout(400)
    const n1 = await nodes().count()
    const e1 = await edges().count()
    const sel = await page.locator('.react-flow__node.selected').evaluateAll((els) => els.map((e) => e.getAttribute('data-id')))
    const g = await page.evaluate(() => null)
    void g
    const a2 = await node('grayscale-1').boundingBox().catch(() => null)
    await h.shot(page, 'canvas-pasted')
    h.item('I12', n1 === n0 + 2 && e1 === e0 + 1 && sel.length === 2 && sel.every((id) => id.startsWith('grayscale-')) && a2 && a2.x > a.x && a2.y > a.y, `nodes ${n0}→${n1} edges ${e0}→${e1} selected=${sel.join(',')} pos=${a2 ? `${Math.round(a2.x - a.x)},${Math.round(a2.y - a.y)}` : 'none'}`)
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(300)
    h.item('I13', (await nodes().count()) === n0 && (await edges().count()) === e0, `Ctrl+Z 後 nodes=${await nodes().count()} edges=${await edges().count()}`)
  })

  await h.step('I11 右鍵選單', async () => {
    await page.keyboard.press('Escape')
    await node('blob').click({ button: 'right' })
    const menu = page.getByTestId('node-menu')
    await menu.waitFor({ timeout: 3000 })
    const items = await menu.locator('[role=menuitem]').allInnerTexts()
    const title = await menu.locator('p').first().innerText()
    const pasteDisabled = await menu.getByRole('menuitem', { name: '貼上參數' }).isDisabled()
    await h.shot(page, 'canvas-context-menu')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(200)
    const escClosed = (await menu.count()) === 0
    await node('blob').click({ button: 'right' })
    await page.mouse.click(30, 30)
    await page.waitForTimeout(200)
    const outsideClosed = (await page.getByTestId('node-menu').count()) === 0
    // 複製參數 → 貼到不同型別 disabled、同型別 enabled
    await node('blob').click({ button: 'right' })
    await page.getByRole('menuitem', { name: '複製參數' }).click()
    const t1 = await h.toast(page, /已複製「Blob」的參數/)
    await node('cmp').click({ button: 'right' })
    const pasteOther = await page.getByRole('menuitem', { name: '貼上參數' }).isDisabled()
    await page.keyboard.press('Escape')
    // 工具箱一律拖曳新增：直接對畫布 dispatch drop（放在中上方，避免被小地圖蓋住）
    await page.evaluate(() => {
      const pane = document.querySelector('.react-flow__pane')
      const r = pane.getBoundingClientRect()
      const dt = new DataTransfer()
      dt.setData('application/x-vs-tool', 'blob')
      const x = r.left + r.width * 0.5
      const y = r.top + r.height * 0.25
      pane.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }))
      pane.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }))
    })
    await page.waitForTimeout(300)
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(400)
    await node('blob-1').click({ button: 'right' })
    const pasteSame = await page.getByRole('menuitem', { name: '貼上參數' }).isDisabled()
    await page.getByRole('menuitem', { name: '貼上參數' }).click()
    const t2 = await h.toast(page, /已貼上參數/)
    // 複製（duplicate）
    const n0 = await nodes().count()
    await node('blob-1').click({ button: 'right' })
    await page.getByRole('menuitem', { name: '複製', exact: true }).click()
    await page.waitForTimeout(300)
    const n1 = await nodes().count()
    // 開啟工具頁（blob-2 疊在 blob-1 上，先用 blob-2）
    await node('blob-2').click({ button: 'right' })
    await page.getByRole('menuitem', { name: '開啟工具頁' }).click()
    await page.waitForURL(/\/tools\/blob-2$/, { timeout: 5000 })
    const toolUrl = page.url()
    await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
    await page.getByTestId('btn-back').click()
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(500)
    // 刪除
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(400)
    const n2 = await nodes().count()
    await node('blob-2').click({ button: 'right' })
    await page.getByRole('menuitem', { name: '刪除' }).click()
    await page.waitForTimeout(200)
    const n3 = await nodes().count()
    await node('blob-1').click({ button: 'right' })
    await page.getByRole('menuitem', { name: '刪除' }).click()
    await page.waitForTimeout(200)
    // 註解選單
    await node('n1').click({ button: 'right' })
    const noteItems = await page.getByTestId('node-menu').locator('[role=menuitem]').allInnerTexts()
    await page.keyboard.press('Escape')
    h.item('I11', title.includes('Blob') && items.join('|') === '開啟工具頁|複製|停用|複製參數|貼上參數|刪除' && pasteDisabled && escClosed && outsideClosed && Boolean(t1) && pasteOther && !pasteSame && Boolean(t2) && n1 === n0 + 1 && /\/tools\/blob-2$/.test(toolUrl) && n3 === n2 - 1 && noteItems.join('|') === '複製|刪除', `title=${title} items=${items.join('|')} pasteDisabled=${pasteDisabled} esc=${escClosed} outside=${outsideClosed} t1=${t1} pasteOther=${pasteOther} pasteSame=${pasteSame} t2=${t2} dup ${n0}→${n1} tool=${toolUrl} del ${n2}→${n3} note=${noteItems.join('|')}`)
  })

  await h.step('I14 Esc／Backspace', async () => {
    await node('C').click()
    const sel = await page.locator('.react-flow__node.selected').count()
    await page.keyboard.press('Escape')
    const none = await page.locator('.react-flow__node.selected').count()
    const n0 = await nodes().count()
    await node('C').click()
    await page.keyboard.press('Backspace')
    await page.waitForTimeout(200)
    const n1 = await nodes().count()
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(200)
    h.item('I14', sel === 1 && none === 0 && n1 === n0 - 1 && (await nodes().count()) === n0, `sel=${sel} afterEsc=${none} backspace ${n0}→${n1}`)
  })

  await h.step('I24 輸入框內快捷鍵不影響畫布', async () => {
    await node('C').click()
    const n0 = await nodes().count()
    const name = page.locator('[data-testid=inspector]').getByLabel('名稱')
    await name.fill('C 灰階X')
    await name.press('Delete')
    await name.press('Backspace')
    await name.press('Control+z')
    await page.waitForTimeout(200)
    h.item('I24', (await nodes().count()) === n0 && (await node('C').count()) === 1, `nodes=${await nodes().count()} (expected ${n0})`)
    await page.keyboard.press('Escape')
  })

  await h.step('I09 預設平移模式、Shift 框選、模式持久化', async () => {
    // 清掉模式 → 重新載入 → 預設是「平移」（aria-pressed）
    await page.evaluate(() => localStorage.removeItem('vs.canvasMode'))
    await open({ mode: null })
    const defaultPan = (await modeBtn('平移').getAttribute('aria-pressed')) === 'true'
    const before = await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)
    // 找一個沒有節點／面板的空白點
    const empty = await page.evaluate(() => {
      const pane = document.querySelector('.react-flow__pane').getBoundingClientRect()
      for (const [fx, fy] of [[0.15, 0.85], [0.5, 0.5], [0.85, 0.15], [0.15, 0.15], [0.3, 0.6], [0.6, 0.3]]) {
        const x = pane.left + pane.width * fx
        const y = pane.top + pane.height * fy
        const el = document.elementFromPoint(x, y)
        if (el && el.classList.contains('react-flow__pane')) return { x, y }
      }
      return null
    })
    if (!empty) throw new Error('no empty pane point')
    await page.mouse.click(empty.x, empty.y)
    await page.waitForTimeout(150)
    const beforePan = await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)
    await drag(empty, { x: empty.x + 100, y: empty.y - 60 })
    const after = await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)
    void before
    const panned = beforePan !== after && (await page.locator('.react-flow__node.selected').count()) === 0
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(400)
    const a = await node('A').boundingBox()
    const b = await node('B').boundingBox()
    await page.keyboard.down('Shift')
    await drag({ x: Math.min(a.x, b.x) - 30, y: Math.min(a.y, b.y) - 30 }, { x: Math.max(a.x + a.width, b.x + b.width) + 30, y: Math.max(a.y + a.height, b.y + b.height) + 30 })
    await page.keyboard.up('Shift')
    const n = await page.locator('.react-flow__node.selected').count()
    const notPannedBySelect = (await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)) !== undefined
    await page.keyboard.press('Escape')
    await h.shot(page, 'canvas-pan-shift-select')
    // 切到「選取」→ localStorage、重載仍是選取；再切回平移
    await modeBtn('選取').click()
    const stored = await page.evaluate(() => localStorage.getItem('vs.canvasMode'))
    await open({ mode: null })
    const persisted = (await modeBtn('選取').getAttribute('aria-pressed')) === 'true'
    await modeBtn('平移').click()
    const stored2 = await page.evaluate(() => localStorage.getItem('vs.canvasMode'))
    await modeBtn('選取').click()
    h.item('I09', defaultPan && panned && n === 2 && notPannedBySelect && stored === 'select' && persisted && stored2 === 'pan', `defaultPan=${defaultPan} panned=${panned} shiftSelect=${n} stored=${stored}/${stored2} persisted=${persisted}`)
  })

  await h.step('I26 工具箱點擊不新增、拖曳新增', async () => {
    const before = await nodes().count()
    await page.locator('[data-tool-key="blur"]').last().locator('button').first().click()
    await page.waitForTimeout(300)
    const afterClick = await nodes().count()
    await page.evaluate(() => {
      const pane = document.querySelector('.react-flow__pane')
      const r = pane.getBoundingClientRect()
      const dt = new DataTransfer()
      dt.setData('application/x-vs-tool', 'blur')
      const x = r.left + r.width * 0.5
      const y = r.top + r.height * 0.5
      pane.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }))
      pane.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }))
    })
    await page.waitForTimeout(300)
    const afterDrop = await nodes().count()
    const selected = await page.locator('.react-flow__node.selected').getAttribute('data-id').catch(() => null)
    await page.keyboard.press('Delete')
    await page.waitForTimeout(200)
    h.item('I26', afterClick === before && afterDrop === before + 1 && selected === 'blur-1' && (await nodes().count()) === before, `click ${before}→${afterClick} drop→${afterDrop} selected=${selected}`)
  })

  await h.step('I16 縮放滑桿', async () => {
    const panel = page.locator('.react-flow__panel.bottom')
    const pct = () => panel.locator('span.tabular-nums').innerText()
    await panel.locator('button[title="符合視窗"]').click()
    await page.waitForTimeout(400)
    const p0 = await pct()
    await panel.getByRole('button', { name: '放大' }).click()
    await page.waitForTimeout(300)
    const p1 = await pct()
    await panel.getByRole('button', { name: '縮小' }).click()
    await page.waitForTimeout(300)
    const p2 = await pct()
    await panel.locator('input[type=range]').evaluate((el) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
      setter.call(el, '1.5')
      el.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await page.waitForTimeout(300)
    const p3 = await pct()
    const posBefore = await nodes().evaluateAll((els) => els.map((e) => e.style.transform).join(';'))
    await panel.locator('button[title="依資料流從左到右分層排列"]').click()
    await page.waitForTimeout(600)
    const posAfter = await nodes().evaluateAll((els) => els.map((e) => e.style.transform).join(';'))
    await h.shot(page, 'canvas-zoom-layout')
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(300)
    h.item('I16', parseInt(p1) > parseInt(p0) && Math.abs(parseInt(p2) - parseInt(p0)) <= 2 && p3 === '150%' && posBefore !== posAfter, `fit=${p0} +=${p1} -=${p2} range=${p3} layout=${posBefore !== posAfter}`)
  })

  await h.step('I17 小地圖', async () => {
    const mm = page.locator('.react-flow__minimap')
    const exists = (await mm.count()) === 1
    const before = await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)
    const b = await mm.boundingBox()
    // pannable：在小地圖上拖曳可平移畫布
    await drag({ x: b.x + b.width / 2, y: b.y + b.height / 2 }, { x: b.x + b.width / 2 + 25, y: b.y + b.height / 2 + 10 }, 6)
    await page.waitForTimeout(300)
    const after = await page.evaluate(() => document.querySelector('.react-flow__viewport')?.style.transform)
    h.item('I17', exists && before !== after, `exists=${exists} moved=${before !== after}`)
  })

  // 不儲存離開
  h.nextDialog(page, true)
  await page.goto(`${BASE}/flows`)
  await page.waitForTimeout(500)
  await h.api.del(`/vision/flows/${flowId}`)
  await context.close()
}
