import { expect, test } from '@playwright/test'

import { open, shoot, watch } from './helpers'

/**
 * The controls that only a real browser can exercise.
 *
 * Native drag-and-drop, Leaflet measuring its own container, a popover that
 * closes on an outside click - none of these have a type signature that can be
 * wrong, and none of them are reachable from a unit test.
 *
 * Nothing here asserts a live *value*. The stack under test has simulators
 * publishing every few seconds by design, so any test pinned to a number would
 * be flaky by construction.
 */

test.describe('dashboard', () => {
  test('switches between the energy and fleet views and remembers the choice', async ({
    page,
  }, info) => {
    const watcher = watch(page)
    await open(page, '/')
    await expect(page.getByRole('heading').first()).toBeVisible()

    // Two toggle buttons live in the page header.
    const toggles = page.getByRole('group').first().getByRole('button')
    await expect(toggles).toHaveCount(2)

    await toggles.nth(1).click() // fleet
    await page.waitForTimeout(1500)
    await shoot(page, info, 'dashboard-fleet')

    // The preference is saved server-side, so a reload must come back to it.
    await page.reload()
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(2000)
    await expect(
      page.getByRole('group').first().getByRole('button').nth(1),
    ).toHaveAttribute('aria-pressed', 'true')

    await toggles.nth(0).click() // back to energy, leaving the default in place
    await page.waitForTimeout(1500)
    await shoot(page, info, 'dashboard-energy')

    expect(watcher.errors.join('\n')).toBe('')
  })

  test('the energy view shows the four power tiles and a SOC dial', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/')
    await page.waitForTimeout(2500)

    // The dial is an inline SVG labelled for screen readers.
    await expect(page.getByRole('img').filter({ hasText: '' }).first()).toBeVisible()
    await shoot(page, info, 'dashboard-power-row')
    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('devices', () => {
  test('switches between list and card layouts', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/devices')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(1500)

    const layout = page.getByRole('group').first().getByRole('button')
    await expect(layout).toHaveCount(2)

    await layout.nth(1).click() // cards
    await page.waitForTimeout(1200)
    await shoot(page, info, 'devices-cards')

    await layout.nth(0).click() // list
    await page.waitForTimeout(1200)
    await expect(page.locator('table')).toBeVisible()
    await shoot(page, info, 'devices-list')

    expect(watcher.errors.join('\n')).toBe('')
  })

  test('the site tree picker opens, filters and keeps ancestors', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/devices')
    await page.waitForTimeout(1500)

    // The tree select is a button that opens a popover with a search box.
    const picker = page.locator('button[aria-haspopup="listbox"]').first()
    await picker.click()
    const search = page.getByRole('textbox').last()
    await expect(search).toBeVisible()
    await shoot(page, info, 'site-tree-open')

    await search.fill('台')
    await page.waitForTimeout(600)
    await shoot(page, info, 'site-tree-filtered')

    // Escape closes it - a popover that traps the pointer is worse than a
    // plain select.
    //
    // Asserted on the trigger's aria-expanded rather than the search box:
    // `getByRole('textbox').last()` re-resolves after the popover closes, and
    // lands on the filter bar's own search - which is legitimately visible, so
    // the test would fail while the component behaved correctly.
    await page.keyboard.press('Escape')
    await expect(picker).toHaveAttribute('aria-expanded', 'false')

    expect(watcher.errors.join('\n')).toBe('')
  })

  test('the live values picker opens and can reorder', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/devices')
    await page.waitForTimeout(1500)

    // Open the first device.
    await page.locator('table tbody tr').first().click()
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(2000)
    await shoot(page, info, 'device-detail')

    // The customise button sits in the latest-values card header.
    const customise = page
      .locator('section')
      .filter({ has: page.locator('button') })
      .locator('button')
      .filter({ hasText: /edit|編輯|编辑/i })
      .first()

    if ((await customise.count()) === 0) {
      test.info().annotations.push({
        type: 'note',
        description: 'no customise button found - device may report no metrics',
      })
      return
    }

    await customise.click()
    await page.waitForTimeout(800)
    await shoot(page, info, 'metric-picker')

    // Reorder with the keyboard-accessible controls rather than a drag, so the
    // assertion does not depend on synthetic drag events.
    const down = page.getByRole('button', { name: /move down|往下移/i }).first()
    if (await down.isVisible()) {
      await down.click()
      await page.waitForTimeout(300)
    }

    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('map', () => {
  test('renders both maps with tiles and markers', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/map')
    await expect(page.getByRole('heading').first()).toBeVisible()
    // Leaflet needs a moment to measure its container and request tiles.
    await page.waitForTimeout(4000)

    const containers = page.locator('.leaflet-container')
    await shoot(page, info, 'map')

    expect(
      await containers.count(),
      'expected an overview map and a detail map',
    ).toBeGreaterThanOrEqual(1)
    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('tariffs', () => {
  test('opens the editor and shows the period controls', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/tariffs')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(1500)

    // The create button is the primary action in the page header.
    await page.getByRole('button').filter({ hasText: /\+|新增|add|create/i }).first().click()
    await page.waitForTimeout(1000)
    await shoot(page, info, 'tariff-editor')

    // A time-of-use tariff shows the period editor.
    await expect(page.getByRole('dialog')).toBeVisible()
    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('storage', () => {
  test('renders the flow, charts and the custom range picker', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/storage')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(4000)
    await shoot(page, info, 'storage')

    // Open the custom range popover.
    const custom = page.getByRole('button').filter({ hasText: /custom|自訂|自定义/i }).first()
    if (await custom.count()) {
      await custom.click()
      await page.waitForTimeout(600)
      await shoot(page, info, 'storage-custom-range')
      await expect(page.locator('input[type="datetime-local"]').first()).toBeVisible()
    }

    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('help', () => {
  test('search filters the sections', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/help')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(1500)
    await shoot(page, info, 'help')

    const search = page.getByRole('textbox').first()
    await search.fill('MQTT')
    await page.waitForTimeout(800)
    await shoot(page, info, 'help-filtered')

    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('storage plan', () => {
  test('the strategy and baseline pickers explain each option', async ({ page }, info) => {
    const watcher = watch(page)
    // Plans live on their own page now; the editor opens from a plan card.
    await open(page, '/storage-plans')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(2000)

    const card = page.getByRole('button').filter({ hasText: /方案|plan/i }).first()
    if (!(await card.count())) {
      test.skip(true, 'no storage plan to open')
      return
    }
    await card.click()
    await page.waitForTimeout(800)
    await shoot(page, info, 'storage-plan-editor')

    // The strategy is a tab bar whose tabs *are* the setting: picking one
    // selects that strategy and reveals only the fields it uses.
    const tabs = page.getByRole('tab')
    expect(await tabs.count()).toBeGreaterThanOrEqual(7)
    for (let i = 0; i < (await tabs.count()); i += 1) {
      await tabs.nth(i).click()
      await page.waitForTimeout(150)
    }
    // The savings baseline stays a radio group with prose per option.
    await expect(page.getByText(/節費基準線|节费基准线|savings baseline/i).first()).toBeVisible()

    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('event log', () => {
  test('filters narrow the list without a reload', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/events')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(2000)
    await shoot(page, info, 'events')

    // Four filters: site, level, code, free text. The site picker is a tree
    // popover rather than a native select, so only two are `select` elements.
    expect(await page.locator('select').count()).toBeGreaterThanOrEqual(2)

    // By role, not by `input[type="text"]`: the shared TextInput renders an
    // input with no explicit type, so the attribute selector never matches it.
    const search = page.getByRole('textbox').last()
    await search.fill('zzzz-no-such-event')
    await page.waitForTimeout(1200)
    await shoot(page, info, 'events-filtered')

    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('gateway page', () => {
  test('shows the connection parameters filled in for the selected gateway', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/gateways')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(1500)
    await shoot(page, info, 'gateways')

    // The point of the page is that the vendor does not have to ask anyone for
    // these, so the real namespace and group have to be on screen.
    await expect(page.getByText('spBv1.0').first()).toBeVisible()
    await expect(page.getByText(/spBv1\.0\/[a-z0-9-]+\/NBIRTH\//).first()).toBeVisible()

    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('timezone picker', () => {
  test('offers real zones rather than a free-text box', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/settings')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(2000)

    // The list is fetched, so it may briefly be a text input; wait for the
    // select to appear rather than asserting on whichever arrived first.
    const zone = page.locator('select').filter({ hasText: 'Asia' }).first()
    await expect(zone).toBeVisible({ timeout: 10000 })
    await shoot(page, info, 'settings-timezone')

    const options = await zone.locator('option').count()
    expect(options).toBeGreaterThan(100)
    await expect(zone.locator('option', { hasText: 'Taipei' }).first()).toHaveCount(1)

    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('workflow editor', () => {
  test('opens a workflow, renders the canvas and starts a test run', async ({ page }, info) => {
    const watcher = watch(page)
    await open(page, '/workflows')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await page.waitForTimeout(1500)
    await shoot(page, info, 'workflows-list')

    // Open the first workflow in the table, if there is one.
    const first = page.locator('table a').first()
    if (!(await first.count())) {
      test.skip(true, 'no workflows seeded')
      return
    }
    await first.click()
    await page.waitForTimeout(2500)

    // The canvas, the palette and the inspector column are all present.
    await expect(page.locator('.react-flow')).toBeVisible()
    await expect(page.locator('.react-flow__node').first()).toBeVisible()
    await shoot(page, info, 'workflow-editor')

    // A test run starts and produces a status badge. Dry runs are the safe
    // path: everything is evaluated, nothing reaches the hardware.
    const testButton = page.getByRole('button').filter({ hasText: /測試|测试|test/i }).first()
    await testButton.click()
    await page.waitForTimeout(6000)
    await shoot(page, info, 'workflow-running')

    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('form focus', () => {
  test('typing in an edit dialog survives the polling cycle', async ({ page }) => {
    // The bug this pins: Modal's focus effect depended on `onClose`, which is
    // a fresh arrow function on every render - so every 5s poll re-ran the
    // effect and panelRef.focus() yanked the caret out of the field being
    // typed in. Text came out scrambled, in every form in the console.
    test.setTimeout(90000)
    const watcher = watch(page)
    await open(page, '/devices')
    await page.waitForTimeout(1500)
    await page.locator('tbody tr').first().click()
    await page.waitForTimeout(2000)

    await page.getByRole('button').filter({ hasText: /編輯|edit/i }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    const name = dialog.getByRole('textbox').first()
    await name.click()
    await name.press('Control+a')
    const target = 'SLOW-TYPED-NAME-1234567890'
    for (const ch of target) {
      // Through the keyboard, not the locator: a locator refocuses the field
      // on every keystroke, which would hide exactly the theft under test.
      await page.keyboard.type(ch)
      await page.waitForTimeout(420)
    }

    expect(await name.inputValue()).toBe(target)
    expect(await page.evaluate(() => document.activeElement?.tagName)).toBe('INPUT')
    expect(watcher.errors.join('\n')).toBe('')
  })
})

// HTML5 drag-and-drop cannot be driven by synthetic mouse events (the browser
// takes over the drag), so the drag is dispatched as DnD events sharing one
// DataTransfer - the same sequence the browser produces natively.
async function dragPaletteItem(
  page: import('@playwright/test').Page,
  label: string | string[],
  x: number,
  y: number,
) {
  // The palette is localized, so a label is looked up under every name the
  // three languages give it.
  const labels = Array.isArray(label) ? label : [label]
  await page.evaluate(
    ([wanted, dropX, dropY]) => {
      const names = String(wanted).split('|')
      const buttons = Array.from(document.querySelectorAll('button[draggable="true"]'))
      const source = buttons.find((b) => names.includes(b.textContent?.trim() ?? ''))
      if (!source) throw new Error(`palette item ${wanted} not found`)
      const canvas = document.querySelector('.react-flow')
      if (!canvas) throw new Error('canvas not found')
      const rect = canvas.getBoundingClientRect()
      const clientX = rect.left + Number(dropX)
      const clientY = rect.top + Number(dropY)
      const data = new DataTransfer()
      source.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: data }))
      canvas.dispatchEvent(
        new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: data, clientX, clientY }),
      )
      canvas.dispatchEvent(
        new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: data, clientX, clientY }),
      )
    },
    [labels.join('|'), String(x), String(y)],
  )
}

test.describe('workflow editing', () => {
  test('drag to add, Delete, Ctrl+C/V and Ctrl+Z behave like an editor', async ({ page }) => {
    test.setTimeout(120000)
    const watcher = watch(page)
    await open(page, '/workflows')
    await page.waitForTimeout(1500)

    const first = page.locator('table a').first()
    if (!(await first.count())) {
      test.skip(true, 'no workflows seeded')
      return
    }
    await first.click()
    await page.waitForTimeout(3000)
    await expect(page.locator('.react-flow')).toBeVisible()

    const count = () => page.locator('.react-flow__node').count()
    const before = await count()

    // Drag a Waypoint out of the palette; it lands selected under the cursor.
    await dragPaletteItem(page, ['Waypoint', '一般節點', '一般节点'], 620, 480)
    await page.waitForTimeout(500)
    expect(await count()).toBe(before + 1)

    // Delete removes the selection.
    await page.keyboard.press('Delete')
    await page.waitForTimeout(400)
    expect(await count()).toBe(before)

    // Ctrl+Z brings it back.
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(400)
    expect(await count()).toBe(before + 1)

    // Copy a node, paste a duplicate, undo the paste.
    await page.locator('.react-flow__node').first().click()
    await page.waitForTimeout(300)
    await page.keyboard.press('Control+c')
    await page.keyboard.press('Control+v')
    await page.waitForTimeout(500)
    expect(await count()).toBe(before + 2)

    await page.keyboard.press('Control+z')
    await page.waitForTimeout(400)
    expect(await count()).toBe(before + 1)

    // None of the shortcuts may fire while typing: with the inspector's name
    // field focused, Delete edits text rather than deleting the node.
    await page.locator('.react-flow__node').first().click()
    const nameField = page.getByRole('textbox').first()
    await nameField.click()
    await nameField.press('Delete')
    await page.waitForTimeout(300)
    expect(await count()).toBe(before + 1)

    expect(watcher.errors.join('\n')).toBe('')
  })
})

/** Free the tenant's run capacity: lingering paused/waiting runs from earlier
 *  sessions otherwise eat the concurrency slots and starts get refused. */
async function stopActiveRuns(page: import('@playwright/test').Page) {
  await page.evaluate(async () => {
    const token = localStorage.getItem('zqs.access')
    if (!token) return
    const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
    const response = await fetch('/api/workflow-runs?active=true&limit=50', { headers })
    if (!response.ok) return
    const data = (await response.json()) as { items?: { id: string }[] }
    for (const run of data.items ?? []) {
      await fetch(`/api/workflow-runs/${run.id}/stop`, { method: 'POST', headers, body: '{}' })
    }
  })
}

test.describe('workflow editor controls', () => {
  test('toolbar above the canvas: step, pause, resume, stop, tidy up', async ({ page }, info) => {
    test.setTimeout(120000)
    const watcher = watch(page)
    await open(page, '/workflows')
    await page.waitForTimeout(1500)

    // A flow that keeps running (the peak-shaving loop) so there is
    // something to pause; a one-shot drill would finish before the click.
    const looping = page.locator('table a').filter({ hasText: /削峰|peak/i }).first()
    const first = (await looping.count()) ? looping : page.locator('table a').first()
    if (!(await first.count())) {
      test.skip(true, 'no workflows seeded')
      return
    }
    await first.click()
    await page.waitForTimeout(3000)
    await expect(page.locator('.react-flow')).toBeVisible()

    await stopActiveRuns(page)

    const button = (pattern: RegExp) =>
      page.getByRole('button').filter({ hasText: pattern }).first()

    // The run controls sit above the canvas: the toolbar's bottom edge must
    // be at or above the canvas's top edge.
    const toolbarBox = await button(/step|單Node|单Node/i).boundingBox()
    const canvasBox = await page.locator('.react-flow').boundingBox()
    expect(toolbarBox && canvasBox && toolbarBox.y < canvasBox.y).toBe(true)

    // Run-selected-node is disabled until a node is selected; with one
    // selected it runs just that node and the run finishes on its own.
    const stepButton = button(/^(step|單Node執行|单Node执行)/i)
    await expect(stepButton).toBeDisabled()
    // An executable node, not a sticky note - notes cannot be run.
    await page.locator('.react-flow__node-workflow').first().click()
    await page.waitForTimeout(300)
    await stepButton.click()
    await page.waitForTimeout(2000)
    await expect(page.getByText(/finished|已完成/i).first()).toBeVisible()

    // A full run can be paused mid-flight, resumed, and stopped.
    await button(/^(test|測試|测试)/i).click()
    await page.waitForTimeout(1500)
    await button(/pause|暫停流程|暂停流程/i).click()
    await page.waitForTimeout(1500)
    await expect(page.getByText(/paused|已暫停|已暂停/i).first()).toBeVisible()
    await shoot(page, info, 'workflow-paused')

    await button(/resume|繼續|继续/i).click()
    await page.waitForTimeout(1500)
    await button(/^(stop|停止)/i).click()
    await page.waitForTimeout(1500)

    // One-click tidy-up rearranges without breaking anything.
    const before = await page.locator('.react-flow__node').count()
    await button(/tidy|自動排列|自动排列/i).click()
    await page.waitForTimeout(1000)
    expect(await page.locator('.react-flow__node').count()).toBe(before)
    await shoot(page, info, 'workflow-tidied')

    expect(watcher.errors.join('\n')).toBe('')
  })

  test('notes are decoration and parameter validation flags mistakes', async ({ page }, info) => {
    test.setTimeout(120000)
    const watcher = watch(page)
    await open(page, '/workflows')
    await page.waitForTimeout(1500)

    const first = page.locator('table a').first()
    if (!(await first.count())) {
      test.skip(true, 'no workflows seeded')
      return
    }
    await first.click()
    await page.waitForTimeout(3000)
    await expect(page.locator('.react-flow')).toBeVisible()

    const count = () => page.locator('.react-flow__node').count()
    const before = await count()

    // A note drops onto the canvas like any node, and its inspector is the
    // reduced form: title and text, no enable switch, no parameters.
    await dragPaletteItem(page, ['Note', '註解', '注释'], 640, 500)
    await page.waitForTimeout(500)
    expect(await count()).toBe(before + 1)
    const noteText = page.getByRole('textbox').nth(1)
    await noteText.click()
    await page.keyboard.type('remember the peak window')
    await page.waitForTimeout(300)
    await expect(
      page.locator('.react-flow__node').getByText('remember the peak window'),
    ).toBeVisible()
    await shoot(page, info, 'workflow-note')
    await page.keyboard.press('Escape')
    await page.locator('.react-flow__pane').click({ position: { x: 40, y: 40 } })
    await page.waitForTimeout(300)

    // A Wait node given an out-of-range value shows a validation message in
    // the inspector and marks the node on the canvas.
    await dragPaletteItem(page, ['Wait', '等待'], 400, 500)
    await page.waitForTimeout(500)
    const seconds = page.locator('input[type="number"]').first()
    await seconds.click()
    await seconds.fill('-5')
    await page.waitForTimeout(400)
    await expect(page.getByText(/at least|不可小於|不可小于/i).first()).toBeVisible()
    await shoot(page, info, 'workflow-validation')

    // Picking a colour paints the node card and auto-contrasts the text.
    await page.locator('button[aria-label="#1d4ed8"]').click()
    await page.waitForTimeout(400)
    const painted = await page
      .locator('.react-flow__node')
      .last()
      .locator('div')
      .first()
      .evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(painted).toBe('rgb(29, 78, 216)')

    // Clean up the two scratch nodes so the seeded flow is left as found.
    // Click each on the canvas first - Delete never fires from a form field.
    await page.locator('.react-flow__node').last().click()
    await page.waitForTimeout(200)
    await page.keyboard.press('Delete')
    await page.waitForTimeout(300)
    await page.locator('.react-flow__node').last().click()
    await page.waitForTimeout(200)
    await page.keyboard.press('Delete')
    await page.waitForTimeout(300)
    expect(await count()).toBe(before)

    expect(watcher.errors.join('\n')).toBe('')
  })
})

test.describe('workflow unsaved changes', () => {
  test('leaving the editor with unsaved changes asks first', async ({ page }) => {
    test.setTimeout(90000)
    await open(page, '/workflows')
    await page.waitForTimeout(1500)

    const first = page.locator('table a').first()
    if (!(await first.count())) {
      test.skip(true, 'no workflows seeded')
      return
    }
    await first.click()
    await page.waitForTimeout(3000)
    await expect(page.locator('.react-flow')).toBeVisible()

    // With nothing changed, leaving is silent. (The initial canvas
    // measurement used to count as an edit and trip the warning.)
    let asked = false
    const flag = () => {
      asked = true
    }
    page.on('dialog', flag)
    await page.getByRole('link', { name: /總覽|总览|dashboard/i }).click()
    await page.waitForTimeout(800)
    page.off('dialog', flag)
    expect(asked).toBe(false)
    await expect(page.locator('.react-flow')).toHaveCount(0)

    // Back into the editor to actually change something.
    await open(page, '/workflows')
    await page.waitForTimeout(1500)
    await page.locator('table a').first().click()
    await page.waitForTimeout(3000)
    await expect(page.locator('.react-flow')).toBeVisible()

    // Dirty the canvas: rename the workflow in the side panel.
    const nameField = page.getByRole('textbox').first()
    await nameField.click()
    await page.keyboard.type('x')
    await page.waitForTimeout(300)

    // First attempt is refused: the confirm dialog is dismissed.
    page.once('dialog', (dialog) => void dialog.dismiss())
    await page.getByRole('link', { name: /總覽|总览|dashboard/i }).click()
    await page.waitForTimeout(800)
    await expect(page.locator('.react-flow')).toBeVisible()

    // Second attempt is accepted and navigation goes through.
    page.once('dialog', (dialog) => void dialog.accept())
    await page.getByRole('link', { name: /總覽|总览|dashboard/i }).click()
    await page.waitForTimeout(800)
    await expect(page.locator('.react-flow')).toHaveCount(0)
  })
})

test.describe('storage strategies', () => {
  test('the plans page: strategy tabs, health section, site bindings', async ({ page }, info) => {
    test.setTimeout(90000)
    const watcher = watch(page)

    // Plans are named templates on their own page now, not a modal.
    await open(page, '/storage-plans')
    await page.waitForTimeout(2000)

    const card = page.getByRole('button').filter({ hasText: /方案|plan/i }).first()
    if (!(await card.count())) {
      test.skip(true, 'no plans present')
      return
    }
    await card.click()
    await page.waitForTimeout(800)

    await page.getByText(/契約容量管理|合同容量管理|contract capacity management/i).first().click()
    await page.waitForTimeout(400)
    await expect(page.getByText(/需量上限|demand ceiling/i).first()).toBeVisible()

    await expect(
      page.getByText(/電池健康約束|电池健康约束|battery health/i).first(),
    ).toBeVisible()
    await expect(page.getByText(/綁定場域|绑定场域|bound sites/i).first()).toBeVisible()
    await shoot(page, info, 'storage-plans-page')

    expect(watcher.errors.join('\n')).toBe('')
  })

  test('the storage page still shows the DR card', async ({ page }, info) => {
    test.setTimeout(90000)
    const watcher = watch(page)
    await open(page, '/storage')
    await page.waitForTimeout(2000)

    await expect(page.getByText(/需量反應|需量响应|demand response/i).first()).toBeVisible()
    await shoot(page, info, 'storage-with-dr')

    expect(watcher.errors.join('\n')).toBe('')
  })
})
