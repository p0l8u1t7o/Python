import { test as setup } from '@playwright/test'

import { AUTH_STATE, signIn } from './helpers'

/**
 * Sign in once for the whole run.
 *
 * Not an optimisation. `POST /auth/login` is throttled to ten attempts per
 * five minutes per address, which is correct - and which a suite that logged
 * in per test would trip on its eleventh test, reporting a wall of failures
 * that have nothing to do with the code under test.
 *
 * The session lives in localStorage, which `storageState` captures, so every
 * later test starts already authenticated.
 */
setup('authenticate', async ({ page }) => {
  await signIn(page)
  await page.context().storageState({ path: AUTH_STATE })
})
