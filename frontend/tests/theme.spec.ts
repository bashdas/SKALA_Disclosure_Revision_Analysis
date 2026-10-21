import { test, expect } from '@playwright/test'
for (const theme of ['light', 'dark']) {
  test(`${theme} 테마가 로그인 화면과 새로고침에서 유지됩니다`, async ({ page }) => {
    await page.addInitScript(
      (value) => localStorage.setItem('disclosure-check.theme.v1', value),
      theme,
    )
    await page.goto('/login')
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    await expect(page.getByRole('heading', { name: '공시체크 로그인' })).toBeVisible()
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}
