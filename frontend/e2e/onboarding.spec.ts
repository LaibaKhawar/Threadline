import { expect, test } from '@playwright/test'

test('a new user registers, picks privacy mode, imports the demo workspace and lands on the dashboard', async ({ page }) => {
  test.setTimeout(300_000)
  const email = `e2e-${Date.now()}@example.com`
  await page.goto('/login')
  await page.getByRole('button', { name: /Create a local account/ }).click()
  await page.getByLabel('Your name').fill('Test User')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('a-long-test-password')
  await page.getByRole('button', { name: 'Create account' }).click()
  await page.waitForURL(/\/onboarding/)
  // walk the steps; import the demo workspace and wait for the memory build
  for (let i = 0; i < 4; i++) {
    const importBtn = page.getByRole('button', { name: /Import the demo workspace/i })
    if (await importBtn.isVisible().catch(() => false)) break
    await page.getByRole('button', { name: /^(Next|Continue|Get started)/ }).first().click()
  }
  await page.getByRole('button', { name: /Import the demo workspace/i }).click()
  await expect(page.getByText('Succeeded', { exact: true }).first()).toBeVisible({ timeout: 240_000 })
  const open = page.getByRole('button', { name: /Open Threadline/ })
  for (let i = 0; i < 4 && !(await open.isVisible().catch(() => false)); i++) {
    const next = page.getByRole('button', { name: /^Next/ })
    await expect(next).toBeEnabled({ timeout: 120_000 }) // the Memory step waits for queued items to be processed
    await next.click()
  }
  await open.click()
  await page.waitForURL((u) => u.pathname === '/')
  await expect(page.getByRole('heading', { name: /Good (morning|afternoon|evening)/ })).toBeVisible()
  // clean up: delete everything for this test account
  const token = (await page.context().cookies()).find((c) => c.name === 'tl_csrf')?.value ?? ''
  await page.request.post('/api/privacy/clear', { data: { scope: 'everything', confirm: 'DELETE' }, headers: { 'x-csrf-token': token } })
})
