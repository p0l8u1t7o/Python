import { expect, type ConsoleMessage, type Page, type TestInfo } from '@playwright/test'

export const CREDENTIALS = {
  email: 'admin@example.com',
  password: 'ChangeMe-2026!',
}

/** Where the shared signed-in session is kept between projects. */
export const AUTH_STATE = 'e2e/.auth/user.json'

/**
 * Console and page errors collected while a test runs.
 *
 * The point of driving a real browser is to see the failures that never reach
 * a type checker: a hook called conditionally, a read off undefined during
 * render, a Leaflet container measured before it has a size. All of those
 * surface here and nowhere else.
 */
export interface Watcher {
  errors: string[]
  /** Missing i18n keys render as the key itself - a visible, silent failure. */
  missingKeys: string[]
  /** `status url` for every 4xx/5xx, because the console omits the URL. */
  failedRequests: string[]
}

/** Noise from the environment rather than from the application. */
const IGNORED = [
  // Vite's dev client and HMR chatter.
  /\[vite\]/i,
  // Tile servers rate-limit or drop requests; not our correctness.
  /tile\.openstreetmap\.org/i,
  // React DevTools nag.
  /Download the React DevTools/i,
]

/**
 * Requests that are *supposed* to 404.
 *
 * The browser logs every 4xx to the console whether or not the application
 * expected it, so a deliberate "this does not exist" is indistinguishable from
 * a mistake unless it is named here.
 *
 * `/declaration` is the only one: a device that has never described itself has
 * no declaration, and `useDeviceDeclaration` treats the 404 as that answer
 * rather than as a failure. It is arguable that the endpoint should return an
 * empty body instead, so that a device detail page leaves a clean console -
 * but that is a change to the API's meaning, not to this suite.
 */
const EXPECTED_404 = [/\/devices\/[^/]+\/declaration$/]

export function watch(page: Page): Watcher {
  const watcher: Watcher = { errors: [], missingKeys: [], failedRequests: [] }

  // Tracks the URL of the most recent expected-404, so the console line that
  // follows it can be matched up and discounted.
  let expectedNotFound = 0

  const record = (text: string) => {
    if (IGNORED.some((pattern) => pattern.test(text))) return
    if (expectedNotFound > 0 && /404/.test(text)) {
      expectedNotFound -= 1
      return
    }
    watcher.errors.push(text)
  }

  page.on('console', (message: ConsoleMessage) => {
    if (message.type() === 'error') record(message.text())
    // i18next logs this rather than throwing, so a missing translation is
    // otherwise invisible until somebody reads the screen.
    if (/missingKey|i18next::translator/.test(message.text())) {
      watcher.missingKeys.push(message.text())
    }
  })
  page.on('pageerror', (error) => record(`${error.name}: ${error.message}`))

  // A bare "Failed to load resource: 404" on the console names nothing, which
  // makes it unactionable. Record the URL alongside it.
  page.on('response', (response) => {
    if (response.status() < 400) return
    const url = response.url()
    if (IGNORED.some((pattern) => pattern.test(url))) return
    if (response.status() === 404 && EXPECTED_404.some((p) => p.test(url))) {
      expectedNotFound += 1
      return
    }
    watcher.failedRequests.push(`${response.status()} ${url}`)
  })

  return watcher
}

/**
 * Open a route with the session already restored from `storageState`.
 *
 * Tests must not call {@link signIn} themselves: login is rate-limited to ten
 * attempts per five minutes, so a per-test sign-in turns the eleventh test
 * onward into noise.
 */
export async function open(page: Page, path: string): Promise<void> {
  await page.goto(path)
  await expect(page.getByRole('navigation')).toBeVisible({ timeout: 20_000 })
}

export async function signIn(page: Page): Promise<void> {
  await page.goto('/login')
  // By input type, not by label: the labels are translated, and the suite runs
  // in three languages.
  await page.locator('input[type="email"]').fill(CREDENTIALS.email)
  await page.locator('input[type="password"]').fill(CREDENTIALS.password)
  await page.locator('form button[type="submit"]').click()
  // The shell renders the sidebar once a session exists.
  await expect(page.getByRole('navigation')).toBeVisible({ timeout: 20_000 })
}

/**
 * A key rendered instead of its translation.
 *
 * i18next falls back to the key when one is missing, so `help.steps.site.title`
 * appears on screen looking almost like content. Scanning the text for the
 * shape of a key catches it; scanning for the *absence* of one would not.
 */
export async function untranslatedKeys(page: Page): Promise<string[]> {
  const text = (await page.locator('body').innerText()) ?? ''
  const pattern = /\b[a-z][a-zA-Z0-9]*(?:\.[a-z][a-zA-Z0-9_]*){2,}\b/g
  return [...new Set(text.match(pattern) ?? [])].filter(
    // File names, metric keys and dotted identifiers that are legitimately on
    // screen. i18n keys always start with a known namespace.
    (candidate) =>
      /^(common|nav|auth|theme|language|status|severity|role|range|dashboard|devices|map|alerts|storage|telemetry|sites|policies|rules|audit|settings|errors|commands|events|help|tariffs|ems)\./.test(
        candidate,
      ),
  )
}

/** Save a full-page screenshot so the rendered result can actually be looked at. */
export async function shoot(page: Page, info: TestInfo, name: string): Promise<string> {
  const file = info.outputPath(`${name}.png`)
  await page.screenshot({ path: file, fullPage: true })
  await info.attach(name, { path: file, contentType: 'image/png' })
  return file
}
