import { test, expect, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

test.beforeEach(async ({ page }, testInfo) => {
  await page.setViewportSize({
    width: testInfo.project.name === 'mobile' ? 390 : 1161,
    height: 849,
  })
  await page.addInitScript(() =>
    sessionStorage.setItem('disclosure-check.token', 'date-picker-ui-fixture'),
  )
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const company = { corp_code: '00398701', company_name: '날짜 검증 기업', stock_code: '066970' }
    let body: unknown = []
    if (path === '/users/me')
      body = { id: 'date-user', organization_id: 'org', name: '화면 검증', role: 'ANALYST' }
    if (path === '/favorites') body = [company]
    if (path === '/disclosures/companies') body = { items: [company], has_more: false }
    if (path === '/disclosures') body = { items: [], total_count: 0, has_more: false }
    if (path === '/market/stocks' || path === '/market/stock-history') body = { items: {} }
    if (path === '/market/sectors') body = { items: {} }
    await route.fulfill({ json: body })
  })
  await page.goto('/companies/00398701?tab=filings')
  await expect(page.locator('.filing-filters')).toBeVisible()
})

async function chooseDate(page: Page, label: string, year: string, month: string, day: number) {
  const trigger = page.getByRole('button', { name: label, exact: true })
  await trigger.click()
  const calendar = page.locator('[data-slot=popover-content]')
  await expect(calendar).toBeVisible()
  await calendar.getByRole('combobox', { name: '연도 선택' }).selectOption(year)
  await calendar.getByRole('combobox', { name: '월 선택' }).selectOption(month)
  await expect(calendar.getByRole('combobox', { name: '연도 선택' })).toHaveValue(year)
  await expect(calendar.getByRole('combobox', { name: '월 선택' })).toHaveValue(month)
  await calendar
    .locator('[data-slot=calendar-cell-trigger]:not([data-outside-view])')
    .filter({ hasText: new RegExp(`^${day}$`) })
    .click()
  await expect(calendar).toBeHidden()
  await expect(trigger).toHaveText(
    `${year}. ${month.padStart(2, '0')}. ${String(day).padStart(2, '0')}.`,
  )
}

test('연월을 직접 선택하고 양쪽 초기화 버튼을 입력칸 안에 유지합니다', async ({
  page,
}, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await chooseDate(page, '시작일', '2025', '11', 20)
  const searched = page.waitForRequest((request) => {
    const url = new URL(request.url())
    return (
      url.pathname === '/api/v1/disclosures' &&
      url.searchParams.get('start_date') === '2025-11-20' &&
      url.searchParams.get('end_date') === '2025-12-31'
    )
  })
  await chooseDate(page, '종료일', '2025', '12', 31)
  await searched
  const filters = page.locator('.filing-filters')
  for (const theme of ['light', 'dark']) {
    await page.evaluate((theme) => {
      document.documentElement.dataset.theme = theme
    }, theme)
    for (const label of ['시작일', '종료일']) {
      const trigger = filters.getByRole('button', { name: label, exact: true })
      const clear = filters.getByRole('button', { name: `${label} 초기화`, exact: true })
      const fieldBox = (await trigger.boundingBox())!
      const clearBox = (await clear.boundingBox())!
      expect(fieldBox.height).toBe(44)
      expect(clearBox.y).toBe(fieldBox.y)
      expect(clearBox.y + clearBox.height).toBeLessThanOrEqual(fieldBox.y + fieldBox.height)
      expect(clearBox.x).toBeGreaterThan(fieldBox.x)
      expect(clearBox.x + clearBox.width).toBeLessThanOrEqual(fieldBox.x + fieldBox.width)
      expect(await trigger.locator('span').evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(
        true,
      )
    }
    const start = (await filters
      .getByRole('button', { name: '시작일', exact: true })
      .boundingBox())!
    const end = (await filters.getByRole('button', { name: '종료일', exact: true }).boundingBox())!
    expect(start.y).toBe(end.y)
    if (testInfo.project.name === 'desktop') {
      const search = (await filters.getByRole('searchbox').boundingBox())!
      expect(search.y).toBe(start.y)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (process.env.E2E_ARTIFACT_DIR) {
      mkdirSync(process.env.E2E_ARTIFACT_DIR, { recursive: true })
      await filters.screenshot({
        path: join(process.env.E2E_ARTIFACT_DIR, `dates-${testInfo.project.name}-${theme}.png`),
      })
    }
  }
  const cleared = page.waitForRequest((request) => {
    const url = new URL(request.url())
    return (
      url.pathname === '/api/v1/disclosures' &&
      !url.searchParams.has('start_date') &&
      url.searchParams.get('end_date') === '2025-12-31'
    )
  })
  const startClear = filters.getByRole('button', { name: '시작일 초기화' })
  await startClear.focus()
  await startClear.press('Enter')
  await cleared
  await expect(filters.getByRole('button', { name: '시작일', exact: true })).toHaveText('전체 기간')
  await expect(filters.getByRole('button', { name: '종료일', exact: true })).toHaveText(
    '2025. 12. 31.',
  )
  await filters.getByRole('button', { name: '종료일 초기화' }).click()
  await expect(filters.getByRole('button', { name: '종료일', exact: true })).toHaveText('전체 기간')
  await expect(page.locator('[data-slot=popover-content]')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('연월 이동 후에도 시작일·종료일 범위와 키보드 닫기를 유지합니다', async ({
  page,
}, testInfo) => {
  await chooseDate(page, '시작일', '2024', '2', 29)
  await chooseDate(page, '종료일', '2024', '3', 15)
  const start = page.getByRole('button', { name: '시작일', exact: true })
  await start.click()
  const calendar = page.locator('[data-slot=popover-content]')
  await calendar.getByRole('combobox', { name: '월 선택' }).selectOption('3')
  const day = (number: number) =>
    calendar
      .locator('[data-slot=calendar-cell-trigger]:not([data-outside-view])')
      .filter({ hasText: new RegExp(`^${number}$`) })
  await expect(day(16)).toBeDisabled()
  await expect(day(15)).toBeEnabled()
  const bounds = (await calendar.boundingBox())!
  expect(bounds.x).toBeGreaterThanOrEqual(0)
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  if (process.env.E2E_ARTIFACT_DIR) {
    mkdirSync(process.env.E2E_ARTIFACT_DIR, { recursive: true })
    await calendar.screenshot({
      path: join(process.env.E2E_ARTIFACT_DIR, `calendar-${testInfo.project.name}.png`),
    })
  }
  await page.keyboard.press('Escape')
  await expect(calendar).toBeHidden()
  await expect(start).toBeFocused()
  await expect(start).toHaveText('2024. 02. 29.')
  await page.getByRole('button', { name: '종료일', exact: true }).click()
  await calendar.getByRole('combobox', { name: '월 선택' }).selectOption('2')
  await expect(day(28)).toBeDisabled()
  await expect(day(29)).toBeEnabled()
})
