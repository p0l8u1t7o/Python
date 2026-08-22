import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

import { open } from './helpers'

/**
 * MQTT -> screen latency, measured on the real stack.
 *
 * A helper script publishes one reading for the probe device and prints the
 * publish timestamp; the test watches the device page until the new number
 * is on screen. The difference is what an operator experiences. The live
 * feed is meant to keep it well under a second; without it the figure is the
 * page's poll interval.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..')
const PYTHON = path.join(ROOT, '.venv', 'Scripts', 'python.exe')
const SCRIPT = path.join(ROOT, 'scripts', 'latency_probe.py')

function publish(kind: string, value: string): number {
  const out = execFileSync(PYTHON, [SCRIPT, kind, value], {
    cwd: ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    timeout: 60_000,
  })
  const lines = out.toString().trim().split(/\r?\n/)
  return Number(lines[lines.length - 1])
}

test.describe('mqtt to screen latency', () => {
  test('a new reading, an alarm event and a node death reach the page fast', async ({ page }) => {
    test.setTimeout(180_000)
    // Warm-up publish: registers the probe's node and device on a fresh
    // database, and brings the gateway online before anything is measured.
    publish('value', '1000')
    await open(page, '/devices')
    await page.waitForTimeout(1500)
    await page.locator('tbody tr').filter({ hasText: 'LAT-PROBE-0001' }).first().click()
    await page.waitForTimeout(2500)

    // ---- telemetry value -------------------------------------------------
    const kw = 400 + Math.floor(Math.random() * 500)
    const t0 = publish('value', String(kw * 1000))
    const shown = page.getByText(new RegExp(`\\b${kw}(\\.0+)?\\b`)).first()
    await expect(shown).toBeVisible({ timeout: 20_000 })
    const valueMs = Date.now() - t0
    console.log(`telemetry -> screen: ${valueMs} ms`)

    // ---- alarm -> device event on the page -------------------------------
    // Device events are listed on the fleet event log page.
    await open(page, '/events')
    await page.waitForTimeout(1500)
    const code = `WEB${Date.now() % 100000}`
    const t1 = publish('alarm', code)
    await expect(page.locator('tbody').getByText(code).first()).toBeVisible({ timeout: 20_000 })
    const alarmMs = Date.now() - t1
    console.log(`alarm event -> screen: ${alarmMs} ms`)

    // ---- node death -> offline badge -------------------------------------
    await open(page, '/devices')
    await page.waitForTimeout(1500)
    await page.locator('tbody tr').filter({ hasText: 'LAT-PROBE-0001' }).first().click()
    await page.waitForTimeout(2000)
    const t2 = publish('death', '')
    await expect(page.getByText(/離線|离线|offline/i).first()).toBeVisible({ timeout: 20_000 })
    const deathMs = Date.now() - t2
    console.log(`death -> offline on screen: ${deathMs} ms`)

    // Bring the device back so the fleet is not left with a dead probe.
    publish('value', String(kw * 1000))

    // Budget: the live feed polls at 0.5 s and the page refetches at once.
    expect(valueMs).toBeLessThan(3000)
    expect(alarmMs).toBeLessThan(3000)
    expect(deathMs).toBeLessThan(3000)
  })
})
