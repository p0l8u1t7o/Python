import { expect, test } from '@playwright/test'

import { open, shoot, untranslatedKeys, watch } from './helpers'

/**
 * Every route renders, in every language, with nothing on the console.
 *
 * This is the layer `tsc` cannot reach. A hook called conditionally, a read off
 * undefined during render, a chart handed a shape it did not expect - all of
 * them compile, and all of them show up here as a blank page and a console
 * error.
 */

const ROUTES = [
  { path: '/', name: 'dashboard' },
  { path: '/devices', name: 'devices' },
  { path: '/map', name: 'map' },
  { path: '/alerts', name: 'alerts' },
  { path: '/storage', name: 'storage' },
  { path: '/telemetry', name: 'telemetry' },
  { path: '/events', name: 'events' },
  { path: '/tariffs', name: 'tariffs' },
  { path: '/workflows', name: 'workflows' },
  { path: '/sites', name: 'sites' },
  { path: '/recording', name: 'recording' },
  { path: '/rules', name: 'rules' },
  { path: '/audit', name: 'audit' },
  { path: '/settings', name: 'settings' },
  { path: '/gateways', name: 'gateways' },
  { path: '/help', name: 'help' },
]

test.describe('every route', () => {
  for (const route of ROUTES) {
    test(`${route.name} renders without console errors`, async ({ page }, info) => {
      const watcher = watch(page)
      await open(page, route.path)
      // Wait for something real rather than a fixed delay: every page has a
      // heading, and it appears only once its first query has resolved or
      // failed.
      await expect(page.getByRole('heading').first()).toBeVisible()
      // Let deferred work (charts, Leaflet, lazy chunks) finish and blow up.
      await page.waitForTimeout(2500)

      await shoot(page, info, route.name)

      const keys = await untranslatedKeys(page)
      expect(
        watcher.errors,
        `console errors on ${route.path}:\n${watcher.errors.join('\n')}`,
      ).toEqual([])
      expect(
        keys,
        `untranslated i18n keys visible on ${route.path}: ${keys.join(', ')}`,
      ).toEqual([])
    })
  }
})

test.describe('translations', () => {
  for (const language of ['zh-Hant', 'zh-Hans', 'en'] as const) {
    test(`the console is complete in ${language}`, async ({ page }, info) => {
      const watcher = watch(page)
      // The app reads its language from localStorage on boot, in the Django
      // spelling.
      await page.addInitScript((code) => {
        window.localStorage.setItem('zqs.language', code)
      }, language.toLowerCase())

      await open(page, '/')

      const found: string[] = []
      for (const route of [
        '/',
        '/devices',
        '/storage',
        '/tariffs',
        '/events',
        '/gateways',
        '/help',
        '/settings',
      ]) {
        await page.goto(route)
        await expect(page.getByRole('heading').first()).toBeVisible()
        await page.waitForTimeout(1200)
        found.push(...(await untranslatedKeys(page)))
      }

      await shoot(page, info, `language-${language}`)
      expect(
        [...new Set(found)],
        `untranslated keys in ${language}`,
      ).toEqual([])
      expect(watcher.missingKeys, 'i18next reported missing keys').toEqual([])
    })
  }
})
