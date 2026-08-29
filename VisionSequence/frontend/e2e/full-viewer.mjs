/**
 * 模組 viewer：影像視窗（J）。J01–J08、J16 在編輯器；ROI（J09–J15）在工具頁的「執行前」視窗
 * （編輯器側欄已沒有參數欄位，ROI 編輯只在工具頁）。
 */
import { BASE } from './full-lib.mjs'

const IMG_W = 1280
const IMG_H = 960

/** 依「適合視窗」公式算影像 ⇄ 螢幕座標（呼叫前先按過適合視窗）。 */
async function mapping(page, sel, W = IMG_W, H = IMG_H) {
  const box = await page.locator(`${sel} canvas.touch-none`).boundingBox()
  const scale = Math.min((box.width - 32) / W, (box.height - 32) / H)
  const tx = (box.width - W * scale) / 2
  const ty = (box.height - H * scale) / 2
  return {
    box,
    scale,
    toScreen: (ix, iy) => ({ x: box.x + ix * scale + tx, y: box.y + iy * scale + ty }),
    toImage: (sx, sy) => [(sx - box.x - tx) / scale, (sy - box.y - ty) / scale],
  }
}

async function drag(page, from, to, { steps = 10, shift = false, button = 'left' } = {}) {
  if (shift) await page.keyboard.down('Shift')
  await page.mouse.move(from.x, from.y)
  await page.mouse.down({ button })
  await page.mouse.move(from.x + 2, from.y + 2, { steps: 2 })
  await page.mouse.move(to.x, to.y, { steps })
  await page.mouse.up({ button })
  if (shift) await page.keyboard.up('Shift')
  await page.waitForTimeout(250)
}

/** 取樣 overlay 層某點附近是否有非透明像素。 */
const overlayHit = (page, sel, sx, sy, radius = 8) =>
  page.evaluate(({ sel, sx, sy, radius }) => {
    const c = document.querySelector(`${sel} canvas.touch-none`)
    const rect = c.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    const ctx = c.getContext('2d')
    const x = Math.round((sx - rect.left) * dpr)
    const y = Math.round((sy - rect.top) * dpr)
    const r = Math.round(radius * dpr)
    const d = ctx.getImageData(Math.max(0, x - r), Math.max(0, y - r), r * 2, r * 2).data
    let hit = 0
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) hit += 1
    return hit
  }, { sel, sx, sy, radius })

const overlayPixels = (page, sel) =>
  page.evaluate((sel) => {
    const c = document.querySelector(`${sel} canvas.touch-none`)
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data
    let n = 0
    for (let i = 3; i < d.length; i += 4 * 13) if (d[i] > 0) n += 1
    return n
  }, sel)

const imageHash = (page, sel) =>
  page.evaluate((sel) => {
    const c = document.querySelector(`${sel} canvas`)
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data
    let h = 0
    for (let i = 0; i < d.length; i += 4 * 101) h = (h * 31 + d[i]) >>> 0
    return h
  }, sel)

export async function run(h) {
  await h.loginAdmin()
  const context = await h.newContext({ token: h.token })
  await context.addInitScript(() => localStorage.setItem('vs.editorLayout', JSON.stringify({ left: 200, right: 300, canvas: 0.3 })))
  const page = await h.newPage(context, '[viewer]')
  const flowId = await h.cloneDemo('E2E 影像視窗測試')
  await h.api.del(`/vision/flows/${flowId}/recent`)
  const MAIN = '[data-testid=viewer-main]'
  const open = async () => {
    await page.goto(`${BASE}/flows/${flowId}`)
    await page.locator('.react-flow__node').first().waitFor({ timeout: 15000 })
    await page.waitForTimeout(800)
  }
  const fitBtn = (sel) => page.locator(`${sel} button[title="適合視窗 (F)"]`)
  const scaleLabel = (sel) => page.locator(`${sel} span.font-mono`).first().innerText()
  const clickNode = async (id) => {
    await page.locator('.react-flow__panel button[title="符合視窗"]').click()
    await page.waitForTimeout(300)
    await page.locator(`.react-flow__node[data-id="${id}"]`).click()
    await page.waitForTimeout(300)
  }

  await open()
  await h.step('J01 空狀態', async () => {
    const txt = await page.locator(MAIN).innerText()
    const bottom = await page.locator('.absolute.bottom-2.left-2').innerText()
    await h.shot(page, 'viewer-empty')
    h.item('J01', txt.includes('尚無影像') && bottom.includes('按「試跑」產生'), `viewer=${txt.replace(/\n/g, '|')} bottom=${bottom.replace(/\n/g, '|')}`)
  })

  await h.step('J02 J06 試跑後影像與 badge', async () => {
    await page.getByTestId('btn-preview').click()
    await h.toast(page, /試跑完成/)
    await page.waitForTimeout(800)
    const has = await h.viewerHasImage(page, MAIN)
    const badge = page.locator(`${MAIN} .pointer-events-none.absolute.top-8`)
    const btxt = await badge.innerText()
    const bg = await badge.getAttribute('class')
    await h.shot(page, 'viewer-preview')
    h.item('J02', has, '試跑後影像層仍為空')
    h.item('J06', /^(OK|NG) · \d+ ms · .+/.test(btxt) && (btxt.startsWith('OK') ? bg.includes('bg-green-600') : bg.includes('bg-red-600')), `badge=${btxt} bg=${bg}`)
  })

  await h.step('J03 工具列', async () => {
    await clickNode('blob')
    await fitBtn(MAIN).click()
    await page.waitForTimeout(200)
    const fit = await scaleLabel(MAIN)
    await page.locator(`${MAIN} button[title="1:1 (1)"]`).click()
    await page.waitForTimeout(200)
    const one = await scaleLabel(MAIN)
    await page.locator(`${MAIN} button[title="放大 (+)"]`).click()
    await page.waitForTimeout(200)
    const plus = await scaleLabel(MAIN)
    await page.locator(`${MAIN} button[title="縮小 (−)"]`).click()
    await page.waitForTimeout(200)
    const minus = await scaleLabel(MAIN)
    // 放大到 ≥8x 看格線
    for (let i = 0; i < 10; i += 1) await page.locator(`${MAIN} button[title="放大 (+)"]`).click()
    await page.waitForTimeout(300)
    const big = await scaleLabel(MAIN)
    const gridBtn = page.locator(`${MAIN} button[title^="像素格線"]`)
    const gridOn = await gridBtn.evaluate((el) => el.className.includes('bg-sky-500'))
    const h1 = await imageHash(page, MAIN)
    await gridBtn.click()
    await page.waitForTimeout(300)
    const h2 = await imageHash(page, MAIN)
    const gridOff = await gridBtn.evaluate((el) => !el.className.includes('bg-sky-500'))
    await h.shot(page, 'viewer-grid-zoomed')
    await gridBtn.click()
    await fitBtn(MAIN).click()
    await page.waitForTimeout(300)
    const ovBtn = page.locator(`${MAIN} button[title="顯示／隱藏工具結果"]`)
    const before = await overlayPixels(page, MAIN)
    await ovBtn.click()
    await page.waitForTimeout(300)
    const after = await overlayPixels(page, MAIN)
    await ovBtn.click()
    await page.waitForTimeout(200)
    h.item('J03', fit !== '100%' && one === '100%' && plus === '125%' && minus === '100%' && parseInt(big) >= 800 && gridOn && h1 !== h2 && gridOff && before > 0 && after === 0, `fit=${fit} 1:1=${one} +=${plus} -=${minus} big=${big} grid=${gridOn}/${gridOff} hashDiff=${h1 !== h2} overlays ${before}→${after}`)
  })

  await h.step('J04 像素座標與灰階值', async () => {
    await fitBtn(MAIN).click()
    await page.waitForTimeout(200)
    const m = await mapping(page, MAIN)
    const p = m.toScreen(640, 480)
    await page.mouse.move(p.x, p.y)
    await page.waitForTimeout(150)
    const label = await page.locator(`${MAIN} span.whitespace-pre`).innerText()
    await page.mouse.move(m.box.x + m.box.width - 2, m.box.y + 2)
    await page.mouse.move(10, 10)
    await page.waitForTimeout(150)
    const gone = await page.locator(`${MAIN} span.whitespace-pre`).innerText()
    const mm = /^(\d+), (\d+)\s+(≈?)(G|RGB) [\d,]+$/.exec(label)
    h.item('J04', Boolean(mm) && Math.abs(Number(mm[1]) - 640) <= 2 && Math.abs(Number(mm[2]) - 480) <= 2 && gone === '', `label=${label} afterLeave=${gone}`)
  })

  await h.step('J05 滾輪／拖曳／雙擊／快捷鍵', async () => {
    await fitBtn(MAIN).click()
    await page.waitForTimeout(200)
    const fit = await scaleLabel(MAIN)
    const m = await mapping(page, MAIN)
    const c = m.toScreen(640, 480)
    await page.mouse.move(c.x, c.y)
    await page.mouse.wheel(0, -300)
    await page.waitForTimeout(250)
    const wheeled = await scaleLabel(MAIN)
    const h0 = await imageHash(page, MAIN)
    await drag(page, c, { x: c.x + 120, y: c.y + 60 })
    const h1 = await imageHash(page, MAIN)
    await page.mouse.dblclick(c.x, c.y)
    await page.waitForTimeout(250)
    const dbl = await scaleLabel(MAIN)
    await page.locator(`${MAIN}`).locator('div[tabindex="0"]').focus()
    await page.keyboard.press('1')
    await page.waitForTimeout(150)
    const k1 = await scaleLabel(MAIN)
    await page.keyboard.press('+')
    await page.waitForTimeout(150)
    const kp = await scaleLabel(MAIN)
    await page.keyboard.press('-')
    await page.waitForTimeout(150)
    const km = await scaleLabel(MAIN)
    await page.keyboard.press('f')
    await page.waitForTimeout(150)
    const kf = await scaleLabel(MAIN)
    h.item('J05', parseInt(wheeled) > parseInt(fit) && h0 !== h1 && dbl === fit && k1 === '100%' && kp === '125%' && km === '100%' && kf === fit, `fit=${fit} wheel=${wheeled} panned=${h0 !== h1} dbl=${dbl} 1=${k1} +=${kp} -=${km} f=${kf}`)
  })

  await h.step('J07 底列選項', async () => {
    await clickNode('blob')
    const inBtn = page.getByRole('button', { name: '輸入', exact: true })
    const outBtn = page.getByRole('button', { name: '輸出', exact: true })
    const bothEnabled = !(await inBtn.isDisabled()) && !(await outBtn.isDisabled())
    const hIn = await imageHash(page, MAIN)
    await outBtn.click()
    // 輸出影像是另一個 URL，非同步載入；最多等 4 秒直到像素改變
    let hOut = hIn
    for (let i = 0; i < 20 && hOut === hIn; i += 1) {
      await page.waitForTimeout(200)
      hOut = await imageHash(page, MAIN)
    }
    const outActive = await outBtn.evaluate((el) => el.className.includes('bg-brand-soft'))
    await inBtn.click()
    await page.waitForTimeout(400)
    const ovBefore = await overlayPixels(page, MAIN)
    await page.getByRole('button', { name: '疊加所有步驟標記' }).click()
    await page.waitForTimeout(400)
    const ovAll = await overlayPixels(page, MAIN)
    await page.getByRole('button', { name: '疊加所有步驟標記' }).click()
    await page.getByTestId('btn-split').click()
    await page.waitForTimeout(800)
    const after = page.locator('[data-testid=viewer-after]')
    const splitShown = (await after.count()) === 1
    const afterHas = await h.viewerHasImage(page, '[data-testid=viewer-after]')
    const labels = (await page.locator('.absolute.left-2.top-8').allInnerTexts()).join('|')
    const disabledInSplit = (await inBtn.isDisabled()) && (await outBtn.isDisabled())
    await h.shot(page, 'viewer-split')
    await page.getByTestId('btn-split').click()
    await page.waitForTimeout(300)
    // 沒有輸出影像的步驟（cmp）：輸出 disabled
    await clickNode('cmp')
    const outDisabled = await outBtn.isDisabled()
    h.item('J07', bothEnabled && hIn !== hOut && outActive && ovAll >= ovBefore && splitShown && afterHas && labels.includes('執行前') && labels.includes('執行後') && disabledInSplit && outDisabled, `both=${bothEnabled} diff=${hIn !== hOut} outActive=${outActive} overlays ${ovBefore}→${ovAll} split=${splitShown} afterImg=${afterHas} labels=${labels} splitDisabled=${disabledInSplit} cmpOutDisabled=${outDisabled}`)
  })

  await h.step('J08 overlay 座標對齊', async () => {
    // 「執行一次」按鈕已移除：API 執行，結果由 SSE 進畫面
    await h.api.post(`/vision/flows/${flowId}/run`, { context: null, wait: true })
    await page.waitForTimeout(1000)
    const recent = await h.api.get(`/vision/flows/${flowId}/recent?limit=1`)
    const runRep = recent.items[0]
    const blob = runRep.nodes.blob
    const centers = blob.outputs.centers ?? []
    const overlays = blob.overlays ?? []
    await clickNode('blob')
    await page.getByRole('button', { name: '輸入', exact: true }).click()
    await fitBtn(MAIN).click()
    await page.waitForTimeout(300)
    const m = await mapping(page, MAIN, blob.outputs.mask?.width ?? IMG_W, blob.outputs.mask?.height ?? IMG_H)
    let hits = 0
    for (const [cx, cy] of centers.slice(0, 5)) {
      const p = m.toScreen(cx, cy)
      if ((await overlayHit(page, MAIN, p.x, p.y, 10)) > 0) hits += 1
    }
    // 對照：影像左上角落（沒有 blob 的地方）不該有 overlay
    const corner = m.toScreen(3, 3)
    const cornerHit = await overlayHit(page, MAIN, corner.x, corner.y, 2)
    await h.shot(page, 'viewer-overlay-align')
    h.item('J08', centers.length > 0 && hits === Math.min(5, centers.length) && cornerHit === 0 && overlays.length > 0, `centers=${centers.length} hits=${hits} cornerHit=${cornerHit} overlays=${overlays.length}`)
  })

  await h.step('J04b 縮圖下的 ≈ 取樣', async () => {
    const png = await h.makePng(page, { w: 2000, h: 1500, dots: 6 })
    await page.getByTestId('scratch-input').first().setInputFiles({ name: 'big.png', mimeType: 'image/png', buffer: png })
    await page.getByTestId('scratch-badge').waitFor({ timeout: 8000 })
    await page.getByTestId('btn-preview').click()
    await h.toast(page, /試跑完成/)
    await page.waitForTimeout(800)
    await clickNode('gray')
    await fitBtn(MAIN).click()
    await page.waitForTimeout(300)
    const m = await mapping(page, MAIN, 2000, 1500)
    const p = m.toScreen(1000, 750)
    await page.mouse.move(p.x, p.y)
    await page.waitForTimeout(150)
    const label = await page.locator(`${MAIN} span.whitespace-pre`).innerText()
    await page.getByTestId('scratch-clear').click()
    h.item('J04', /^(\d+), (\d+)\s+≈(G|RGB) /.test(label) && Math.abs(Number(/^(\d+)/.exec(label)?.[1]) - 1000) <= 3, `大圖 label=${label}`)
  })

  await h.step('J16 深淺色 viewer 背景', async () => {
    const light = await page.locator(MAIN).locator('div[tabindex="0"]').evaluate((el) => getComputedStyle(el).backgroundColor)
    await page.getByRole('button', { name: '切換深／淺色' }).click()
    await page.waitForTimeout(400)
    const dark = await page.locator(MAIN).locator('div[tabindex="0"]').evaluate((el) => getComputedStyle(el).backgroundColor)
    await h.shot(page, 'viewer-dark')
    await page.getByRole('button', { name: '切換深／淺色' }).click()
    await page.waitForTimeout(200)
    h.item('J16', light !== dark && light !== 'rgba(0, 0, 0, 0)', `light=${light} dark=${dark}`)
  })

  // ---------------- ROI（工具頁「執行前」視窗） ----------------
  const BEFORE = '[data-testid=tool-before]'
  const roiText = () => page.locator('[data-testid=tool-params] [data-param=roi] .font-mono').first().innerText()
  const parseRoi = async () => {
    const t = await roiText()
    const num = (k) => Number(new RegExp(`${k}=(-?[\\d.]+)`).exec(t)?.[1])
    if (t.startsWith('rect ')) return { shape: 'rect', x: num('x'), y: num('y'), w: num('w'), h: num('h'), raw: t }
    if (t.startsWith('rotated_rect')) {
      const m = /c=\((-?[\d.]+), (-?[\d.]+)\) (-?[\d.]+)×(-?[\d.]+) ∠(-?[\d.]+)°/.exec(t)
      return { shape: 'rotated_rect', cx: +m[1], cy: +m[2], w: +m[3], h: +m[4], angle: +m[5], raw: t }
    }
    if (t.startsWith('circle')) {
      const m = /c=\((-?[\d.]+), (-?[\d.]+)\) r=(-?[\d.]+)/.exec(t)
      return { shape: 'circle', cx: +m[1], cy: +m[2], r: +m[3], raw: t }
    }
    if (t.startsWith('annulus')) {
      const m = /c=\((-?[\d.]+), (-?[\d.]+)\) r=(-?[\d.]+)–(-?[\d.]+)/.exec(t)
      return { shape: 'annulus', cx: +m[1], cy: +m[2], r_inner: +m[3], r_outer: +m[4], raw: t }
    }
    if (t.startsWith('polygon')) return { shape: 'polygon', n: Number(/polygon (\d+)/.exec(t)?.[1]), raw: t }
    if (t.startsWith('line')) {
      const m = /\((-?[\d.]+), (-?[\d.]+)\) → \((-?[\d.]+), (-?[\d.]+)\)/.exec(t)
      return { shape: 'line', x1: +m[1], y1: +m[2], x2: +m[3], y2: +m[4], raw: t }
    }
    return { shape: 'none', raw: t }
  }
  const shapeBtn = (title) => page.locator(`${BEFORE} button[title="${title}"]`)
  const editBtn = () => page.locator('[data-testid=tool-params] [data-param=roi]').getByRole('button', { name: /在影像上編輯|完成/ })
  const clearBtn = () => page.locator('[data-testid=tool-params] [data-param=roi]').getByRole('button', { name: '清除' })

  // 加一個 ROI 跟隨（六種形狀）接在 src 後面
  const g = (await h.api.get(`/vision/flows/${flowId}`)).graph
  g.nodes.push({ id: 'fix', type: 'fixture_roi', label: 'ROI 跟隨', params: {}, position: { x: 400, y: 500 } })
  g.edges.push({ source: 'src', source_handle: 'image', target: 'fix', target_handle: 'image' })
  await h.api.patch(`/vision/flows/${flowId}`, { graph: g })

  const openTool = async () => {
    await page.goto(`${BASE}/flows/${flowId}/tools/fix`)
    await page.locator('[data-testid=tool-page]').waitFor({ timeout: 10000 })
    await page.locator('[data-testid=tool-updating]').waitFor({ state: 'detached', timeout: 15000 }).catch(() => null)
    await page.waitForTimeout(600)
  }
  let M = null
  const refit = async () => {
    await fitBtn(BEFORE).click()
    await page.waitForTimeout(250)
    M = await mapping(page, BEFORE)
  }
  const near = (a, b, tol) => Math.abs(a - b) <= tol

  await h.step('J09 繪製矩形', async () => {
    await openTool()
    const none = await roiText()
    await editBtn().click()
    await page.waitForTimeout(300)
    const hint = (await page.locator(BEFORE).innerText()).includes('拖曳以繪製 ROI')
    await refit()
    await drag(page, M.toScreen(300, 200), M.toScreen(700, 500))
    const r = await parseRoi()
    const hintGone = !(await page.locator(BEFORE).innerText()).includes('拖曳以繪製 ROI')
    await h.shot(page, 'roi-rect-drawn')
    h.item('J09', none.includes('尚未設定') && hint && r.shape === 'rect' && near(r.x, 300, 3) && near(r.y, 200, 3) && near(r.w, 400, 4) && near(r.h, 300, 4) && hintGone, `none=${none} hint=${hint} roi=${r.raw} hintGone=${hintGone}`)
  })

  await h.step('J11 J12 矩形把手與移動', async () => {
    let r = await parseRoi()
    // 右下角把手
    const br = M.toScreen(r.x + r.w, r.y + r.h)
    await drag(page, br, { x: br.x + 60, y: br.y + 40 })
    let r2 = await parseRoi()
    const cornerOk = near(r2.w, r.w + 60 / M.scale, 4) && near(r2.h, r.h + 40 / M.scale, 4) && r2.x === r.x
    // 右邊中點把手
    const rm = M.toScreen(r2.x + r2.w, r2.y + r2.h / 2)
    await drag(page, rm, { x: rm.x - 40, y: rm.y + 30 })
    let r3 = await parseRoi()
    const edgeOk = near(r3.w, r2.w - 40 / M.scale, 4) && r3.h === r2.h
    // 本體移動
    const c = M.toScreen(r3.x + r3.w / 2, r3.y + r3.h / 2)
    await page.mouse.move(c.x, c.y)
    await page.waitForTimeout(100)
    const cursorMove = await page.locator(`${BEFORE} canvas.touch-none`).evaluate((el) => el.style.cursor)
    await page.mouse.move(br.x, br.y)
    await page.waitForTimeout(100)
    await drag(page, c, { x: c.x + 50, y: c.y + 25 })
    const r4 = await parseRoi()
    const moveOk = near(r4.x, r3.x + 50 / M.scale, 4) && near(r4.y, r3.y + 25 / M.scale, 4) && r4.w === r3.w
    await h.shot(page, 'roi-rect-handles')
    h.item('J11', cornerOk && edgeOk, `corner=${cornerOk} edge=${edgeOk} ${r.raw} → ${r2.raw} → ${r3.raw}`)
    h.item('J12', moveOk && cursorMove === 'move', `move=${moveOk} cursor=${cursorMove} ${r3.raw} → ${r4.raw}`)
  })

  await h.step('J13 形狀切換與夾入', async () => {
    const r = await parseRoi()
    await shapeBtn('圓').click()
    await page.waitForTimeout(250)
    const c = await parseRoi()
    const circleOk = c.shape === 'circle' && near(c.cx, r.x + r.w / 2, 2) && near(c.cy, r.y + r.h / 2, 2)
    await shapeBtn('矩形').click()
    await page.waitForTimeout(250)
    const back = await parseRoi()
    // 拖出影像外再夾入
    const cc = M.toScreen(back.x + back.w / 2, back.y + back.h / 2)
    await drag(page, cc, M.toScreen(-100, -100))
    const out = await parseRoi()
    await page.locator(`${BEFORE} button[title="把 ROI 夾在影像範圍內"]`).click()
    await page.waitForTimeout(250)
    const clamped = await parseRoi()
    h.item('J13', circleOk && back.shape === 'rect' && (out.x < 0 || out.y < 0) && clamped.x === 0 && clamped.y === 0 && clamped.w === back.w, `circle=${c.raw} back=${back.raw} out=${out.raw} clamped=${clamped.raw}`)
  })

  await h.step('J10 六種形狀', async () => {
    const results = []
    for (const [title, shape] of [['旋轉矩形', 'rotated_rect'], ['圓', 'circle'], ['圓環', 'annulus'], ['多邊形', 'polygon'], ['線', 'line'], ['矩形', 'rect']]) {
      await clearBtn().click()
      await page.waitForTimeout(200)
      if (!(await editBtn().innerText()).includes('完成')) await editBtn().click()
      await page.waitForTimeout(200)
      await shapeBtn(title).click()
      await page.waitForTimeout(150)
      await drag(page, M.toScreen(400, 300), M.toScreen(600, 450))
      const r = await parseRoi()
      results.push(`${shape}:${r.shape}`)
      if (r.shape !== shape) results.push('MISMATCH')
      await h.shot(page, `roi-${shape}`)
    }
    h.item('J10', !results.includes('MISMATCH'), results.join(' '))
  })

  await h.step('J11b 旋轉矩形／圓／圓環／多邊形／線的把手', async () => {
    const notes = []
    // rotated_rect：旋轉把手在頂邊上方 28px
    await clearBtn().click()
    await editBtn().click()
    await shapeBtn('旋轉矩形').click()
    await drag(page, M.toScreen(400, 300), M.toScreen(640, 480))
    let rr = await parseRoi()
    let top = M.toScreen(rr.cx, rr.cy - rr.h / 2)
    let rot = { x: top.x, y: top.y - 28 }
    let cen = M.toScreen(rr.cx, rr.cy)
    await drag(page, rot, { x: cen.x + 150, y: cen.y })
    let rr2 = await parseRoi()
    const rotOk = rr2.shape === 'rotated_rect' && near(rr2.angle, 90, 3)
    notes.push(`rotate=${rr2.angle}`)
    // Shift 吸附 15°：把手現在在右側（角度 90），拖到約 100° 的方向 → 應吸附到 105 或 90
    top = M.toScreen(rr2.cx + (rr2.h / 2) * Math.sin((rr2.angle * Math.PI) / 180), rr2.cy - (rr2.h / 2) * Math.cos((rr2.angle * Math.PI) / 180))
    rot = { x: top.x + 28 * Math.sin((rr2.angle * Math.PI) / 180), y: top.y - 28 * Math.cos((rr2.angle * Math.PI) / 180) }
    await drag(page, rot, { x: cen.x + 150 * Math.cos((22 * Math.PI) / 180), y: cen.y + 150 * Math.sin((22 * Math.PI) / 180) }, { shift: true })
    const rr3 = await parseRoi()
    const snapOk = rr3.angle % 15 === 0
    notes.push(`shiftAngle=${rr3.angle}`)
    // circle：半徑把手 (cx+r, cy)
    await clearBtn().click()
    await editBtn().click()
    await shapeBtn('圓').click()
    await drag(page, M.toScreen(500, 400), M.toScreen(600, 400))
    let ci = await parseRoi()
    await drag(page, M.toScreen(ci.cx + ci.r, ci.cy), M.toScreen(ci.cx + ci.r + 80, ci.cy))
    const ci2 = await parseRoi()
    const radiusOk = ci2.shape === 'circle' && near(ci2.r, ci.r + 80, 3)
    notes.push(`r ${ci.r}→${ci2.r}`)
    // annulus：內／外把手
    await clearBtn().click()
    await editBtn().click()
    await shapeBtn('圓環').click()
    await drag(page, M.toScreen(500, 400), M.toScreen(660, 400))
    const an = await parseRoi()
    await drag(page, M.toScreen(an.cx + an.r_inner, an.cy), M.toScreen(an.cx + an.r_inner + 30, an.cy))
    const an2 = await parseRoi()
    await drag(page, M.toScreen(an2.cx + an2.r_outer, an2.cy), M.toScreen(an2.cx + an2.r_outer + 40, an2.cy))
    const an3 = await parseRoi()
    const annOk = near(an2.r_inner, an.r_inner + 30, 3) && an2.r_outer === an.r_outer && near(an3.r_outer, an2.r_outer + 40, 3) && an3.r_inner === an2.r_inner
    notes.push(`annulus ${an.raw} → ${an2.raw} → ${an3.raw}`)
    // polygon：頂點拖曳、雙擊邊新增、右鍵刪、Delete 刪
    await clearBtn().click()
    await editBtn().click()
    await shapeBtn('多邊形').click()
    await drag(page, M.toScreen(400, 300), M.toScreen(700, 500))
    const p0 = await parseRoi()
    await drag(page, M.toScreen(400, 300), M.toScreen(350, 250))
    const p1 = await parseRoi()
    const mid = M.toScreen(550, 500)
    await page.mouse.dblclick(mid.x, mid.y)
    await page.waitForTimeout(250)
    const p2 = await parseRoi()
    const v = M.toScreen(700, 300)
    await page.mouse.click(v.x, v.y, { button: 'right' })
    await page.waitForTimeout(250)
    const p3 = await parseRoi()
    const v2 = M.toScreen(700, 500)
    await page.mouse.click(v2.x, v2.y)
    await page.waitForTimeout(150)
    await page.keyboard.press('Delete')
    await page.waitForTimeout(250)
    const p4 = await parseRoi()
    const polyOk = p0.n === 4 && p1.n === 4 && p2.n === 5 && p3.n === 4 && p4.n === 3
    notes.push(`polygon n=${p0.n},${p1.n},${p2.n},${p3.n},${p4.n}`)
    await h.shot(page, 'roi-polygon-edited')
    // line：端點與 Shift 吸附
    await clearBtn().click()
    await editBtn().click()
    await shapeBtn('線').click()
    await drag(page, M.toScreen(400, 400), M.toScreen(700, 400))
    const l0 = await parseRoi()
    await drag(page, M.toScreen(l0.x2, l0.y2), M.toScreen(l0.x2, l0.y2 + 120))
    const l1 = await parseRoi()
    await drag(page, M.toScreen(l1.x2, l1.y2), M.toScreen(l1.x1 + 300, l1.y1 + 40), { shift: true })
    const l2 = await parseRoi()
    const ang = Math.round((Math.atan2(l2.y2 - l2.y1, l2.x2 - l2.x1) * 180) / Math.PI)
    const lineOk = near(l1.y2, l0.y2 + 120, 3) && l1.x1 === l0.x1 && Math.abs(ang % 15) <= 1
    notes.push(`line ${l0.raw} → ${l1.raw} → ${l2.raw} angle=${ang}`)
    h.item('J11', rotOk && snapOk && radiusOk && annOk && polyOk && lineOk, `rot=${rotOk} snap=${snapOk} radius=${radiusOk} annulus=${annOk} polygon=${polyOk} line=${lineOk} | ${notes.join(' | ')}`)
  })

  await h.step('J14 太小忽略與 Shift 正方形', async () => {
    await clearBtn().click()
    await editBtn().click()
    await shapeBtn('矩形').click()
    // 太小的判定是影像像素（<2px）；適合視窗時 1 螢幕 px 已超過 2 影像 px，先切到 1:1 再拖 1px
    await page.locator(`${BEFORE} button[title="1:1 (1)"]`).click()
    await page.waitForTimeout(250)
    const box = await page.locator(`${BEFORE} canvas.touch-none`).boundingBox()
    const a = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
    await page.mouse.move(a.x, a.y)
    await page.mouse.down()
    await page.mouse.move(a.x + 1, a.y + 1)
    await page.mouse.up()
    await page.waitForTimeout(250)
    const none = await roiText()
    await refit()
    await drag(page, M.toScreen(400, 300), M.toScreen(600, 350), { shift: true })
    const sq = await parseRoi()
    h.item('J14', none.includes('尚未設定') && sq.shape === 'rect' && sq.w === sq.h, `tiny=${none} square=${sq.raw}`)
  })

  await h.step('J15 清除／Esc／完成', async () => {
    const editing = (await editBtn().innerText()).includes('完成')
    await editBtn().click()
    const doneEnds = (await editBtn().innerText()).includes('在影像上編輯')
    await editBtn().click()
    await page.locator(BEFORE).locator('div[tabindex="0"]').focus()
    await page.keyboard.press('Escape')
    await page.waitForTimeout(200)
    const escEnds = (await editBtn().innerText()).includes('在影像上編輯')
    await clearBtn().click()
    await page.waitForTimeout(200)
    const cleared = (await roiText()).includes('尚未設定')
    const clearGone = (await clearBtn().count()) === 0
    h.item('J15', editing && doneEnds && cleared && clearGone && escEnds, `editing=${editing} done=${doneEnds} esc=${escEnds} cleared=${cleared} clearBtnGone=${clearGone}（「換選取步驟自動結束」為編輯器行為，編輯器已無 ROI 編輯入口，不適用）`)
  })

  h.nextDialog(page, true)
  await page.goto(`${BASE}/flows`)
  await page.waitForTimeout(400)
  await context.close()
}
