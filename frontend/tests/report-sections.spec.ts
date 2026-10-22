import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
test('보고서 영역은 펼쳐서 시작하고 각 제목으로 접고 펼칩니다', async ({ page }) => {
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript(t => sessionStorage.setItem('disclosure-check.token', t), token)
  const response = await page.request.get('/api/v1/analyses', { headers: { Authorization: `Bearer ${token}` } })
  const tasks = await response.json() as { task_id: string; status: string }[]
  const task = tasks.find(t => t.status === 'COMPLETED' || t.status === 'COMPLETED_WITH_WARNINGS')
  test.skip(!task, '완료된 검증 보고서가 필요합니다.')
  await page.goto('/analyses/' + task!.task_id)
  await expect(page.getByText('RESEARCH IMPACT REVIEW', { exact: true })).toHaveCount(0)
  for (const selector of ['.findings-section', '.perspectives-section']) {
    await expect(page.locator(selector)).toHaveClass(/surface/)
    expect(await page.locator(selector).evaluate(el => getComputedStyle(el).borderTopWidth)).toBe('1px')
  }
  const findings = await page.locator('.findings-section').boundingBox()
  const evidence = await page.locator('.source-list').boundingBox()
  expect(evidence!.y - findings!.y - findings!.height).toBeGreaterThanOrEqual(32)
  const toggles = page.locator('.report-fold-trigger')
  await expect(toggles).toHaveCount(5)
  for (const toggle of await toggles.all()) {
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  }
  expect(await page.locator('.perspectives-section').evaluate(el => parseFloat(getComputedStyle(el).marginTop))).toBeGreaterThanOrEqual(32)
  if (process.env.E2E_ARTIFACT_DIR) await page.screenshot({ path: `${process.env.E2E_ARTIFACT_DIR}/보고서접기.png` })
})
