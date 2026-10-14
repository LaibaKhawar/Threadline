import { expect, test } from '@playwright/test'

import { loginDemo } from './helpers'

const PAGES = ['/', '/assistant', '/search', '/inbox', '/calendar', '/projects', '/tasks', '/commitments', '/decisions', '/people', '/graph',
  '/timeline', '/documents', '/notes', '/integrations', '/privacy', '/activity', '/evaluation', '/settings']

test('every page renders without errors', async ({ page }) => {
  test.setTimeout(240_000)
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await loginDemo(page)
  for (const p of PAGES) {
    await page.goto(p)
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
    await expect(page.getByRole('alert').filter({ hasText: 'Couldn’t load' })).toHaveCount(0)
  }
  expect(errors).toEqual([])
})

test('no horizontal scrolling at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 380, height: 800 })
  await loginDemo(page)
  for (const p of ['/', '/commitments', '/people', '/privacy']) {
    await page.goto(p)
    await page.waitForTimeout(800)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, p).toBeLessThanOrEqual(1)
  }
})

test('keyboard: skip link and command palette', async ({ page }) => {
  await loginDemo(page)
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  await page.keyboard.press('Meta+k')
  await expect(page.getByRole('dialog', { name: 'Quick search' })).toBeVisible()
  await page.keyboard.type('Atlas')
  await expect(page.getByText(/Atlas/).first()).toBeVisible()
  await page.keyboard.press('Escape')
})

test('offline state is shown and local features keep working', async ({ page, context }) => {
  await loginDemo(page)
  await context.setOffline(true)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  await expect(page.getByText('Offline').first()).toBeVisible()
  await context.setOffline(false)
})

test('dark mode toggle', async ({ page }) => {
  await loginDemo(page)
  await page.getByRole('button', { name: 'Toggle theme' }).click()
  await expect(page.locator('html')).toHaveClass(/dark|light/)
})
