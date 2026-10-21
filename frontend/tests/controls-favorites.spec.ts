import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('선택 입력과 달력, 기업 이미지, 오른쪽 즐겨찾기와 고정 헤더를 확인합니다', async ({
  page,
}) => {
  test.setTimeout(60000)
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript((t) => sessionStorage.setItem('disclosure-check.token', t), token)
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  for (const width of [1720, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/home')
    const table = page.locator('.watchlist-table')
    await expect(table).toBeVisible()
    const row = table
      .locator('tbody tr')
      .filter({ has: page.locator('.watchlist-code', { hasText: /^[0-9]{6}$/ }) })
      .first()
    await expect(row.locator('th .company-logo img')).toHaveCount(1)
    await expect(row.locator('td:last-child .favorite-button')).toHaveCount(1)
    await page.goto('/companies')
    const companyRow = page.locator('.company-directory-table tbody tr').first()
    await expect(companyRow.locator('th .company-logo')).toBeVisible()
    await expect(companyRow.locator('td:last-child .favorite-button')).toHaveCount(1)
    await page.goto('/companies/00126478')
    await expect(page.locator('.company-market-name .favorite-button')).toBeVisible()
    await expect(page.locator('.company-market-panel .skeleton-state')).toHaveCount(0, {
      timeout: 30000,
    })
    const chart = await page.locator('.company-price-chart svg.market-sparkline').boundingBox()
    expect(chart!.width).toBeGreaterThan(0)
    const content = await page.locator('.company-market').boundingBox()
    await expect(page.locator('.company-workspace .document-row').first()).toBeVisible()
    for (const selector of ['.company-workspace > .tabs', '.filing-filters', '.company-workspace .document-row']) {
      const edge = await page.locator(selector).first().boundingBox()
      expect(Math.abs(edge!.x - content!.x)).toBeLessThan(2)
      expect(Math.abs(edge!.x + edge!.width - content!.x - content!.width)).toBeLessThan(2)
    }
    const date = page.locator('.ui-date').first()
    await date.getByRole('button', { name: '시작일', exact: true }).click()
    const calendar = page.locator('[data-slot=popover-content]')
    await expect(calendar).toBeVisible()
    const box = await calendar.boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await calendar.locator('[data-slot=calendar-cell-trigger]:not([data-disabled]):not([data-selected])').first().click()
    await expect(calendar).not.toBeVisible()
    if (process.env.E2E_ARTIFACT_DIR)
      await page.screenshot({ path: `${process.env.E2E_ARTIFACT_DIR}/기업상단_${width}.png` })
    await page.locator('.tabs a').last().click()
    const select = page.locator('.document-section .ui-select')
    await expect(page.locator('.company-market-panel .skeleton-state')).toHaveCount(0)
    await select.scrollIntoViewIfNeeded()
    const before = await select.boundingBox()
    await select.click()
    const after = await select.boundingBox()
    expect(Math.abs(before!.x - after!.x)).toBeLessThan(1)
    expect(Math.abs(before!.y - after!.y)).toBeLessThan(1)
    await expect(page.getByRole('option', { name: '분석 중', exact: true })).toBeVisible()
    const gap = await select.evaluate((el) => {
      const a = el.getBoundingClientRect(),
        b = el.querySelector('svg')!.getBoundingClientRect()
      return a.right - b.right
    })
    expect(gap).toBeGreaterThanOrEqual(14)
    await page.getByRole('option', { name: '분석 중', exact: true }).click()
    await expect(select).toContainText('분석 중')
    await page.evaluate(() => scrollTo(0, document.body.scrollHeight))
    expect((await page.locator('.topbar').boundingBox())!.y).toBe(0)
    expect(
      await page.evaluate(() => getComputedStyle(document.documentElement).overscrollBehavior),
    ).toBe('none')
    if (process.env.E2E_ARTIFACT_DIR)
      await page.screenshot({ path: `${process.env.E2E_ARTIFACT_DIR}/선택입력_${width}.png` })
    await page.locator('.tabs a').first().click()
    await expect(page.getByRole('button', { name: '뒤로가기', exact: true })).toHaveCount(0)
  }
  expect(errors).toEqual([])
})

test('기업 상세 스켈레톤과 실제 화면의 좌우 기준선이 일치합니다', async ({ page }) => {
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript(t => sessionStorage.setItem('disclosure-check.token', t), token)
  for (const width of [1720, 900, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    await page.route('**/api/v1/users/me', async route => { await gate; await route.continue() }, { times: 1 })
    await page.goto('/companies/00126478')
    const skeleton = page.locator('.skeleton-company').first()
    await expect(skeleton).toBeVisible()
    const skeletonLeft = (await skeleton.locator('.sk-company-name').boundingBox())!.x
    if (process.env.E2E_ARTIFACT_DIR) await page.screenshot({ path: `${process.env.E2E_ARTIFACT_DIR}/스켈레톤_${width}.png` })
    release()
    await expect(page.locator('.company-market-name')).toBeVisible()
    const actualLeft = (await page.locator('.company-market-name').boundingBox())!.x
    expect(Math.abs(skeletonLeft - actualLeft)).toBeLessThan(2)
    await expect(page.getByRole('button', { name: '뒤로가기', exact: true })).toHaveCount(0)
  }
})
