import { type Page, expect } from '@playwright/test'

export async function loginDemo(page: Page) {
  await page.goto('/login')
  await page.getByRole('button', { name: 'Open the demo workspace' }).click()
  await page.waitForURL((u) => !u.pathname.startsWith('/login'))
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

export async function csrf(page: Page): Promise<string> {
  const cookies = await page.context().cookies()
  return cookies.find((c) => c.name === 'tl_csrf')?.value ?? ''
}
