import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('기업 시총 정렬과 추가 로딩, 검색, 테마를 확인합니다', async ({ page }) => {
  test.skip(!process.env.E2E_TOKEN_FILE, '로그인 토큰 파일이 필요합니다.')
  test.setTimeout(120000)
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript(
    (token) => sessionStorage.setItem('disclosure-check.token', token),
    token,
  )
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const initialResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/disclosures/companies?') &&
      response.url().includes('sort=market_cap_desc') &&
      response.status() === 200,
  )
  await page.goto('/companies')
  const initial = await (await initialResponse).json()
  const rows = page.locator('.company-row')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/^\s*기업 /)
  await expect(page.getByRole('combobox', { name: '기업 정렬' })).toContainText('시가총액 높은 순')
  await expect(rows.first()).toContainText(initial.items[0].company_name)
  await expect(rows).toHaveCount(20)
  if (process.env.E2E_ARTIFACT_DIR)
    await page.screenshot({
      path: `${process.env.E2E_ARTIFACT_DIR}/기업목록-${page.viewportSize()!.width}.png`,
      animations: 'disabled',
    })
  const nextPage = page.waitForResponse(
    (response) =>
      response.url().includes('/disclosures/companies?') &&
      response.url().includes('offset=20') &&
      response.status() === 200,
  )
  await rows.last().scrollIntoViewIfNeeded()
  const nextResponse = await nextPage
  const next = await nextResponse.json()
  expect(nextResponse.url()).toContain('snapshot=' + initial.snapshot)
  expect(next.snapshot).toBe(initial.snapshot)
  await expect(rows).toHaveCount(40)
  expect(new Set([...initial.items, ...next.items].map((row) => row.corp_code)).size).toBe(40)
  await page.getByRole('heading', { level: 1 }).scrollIntoViewIfNeeded()
  await page.getByRole('combobox', { name: '기업 정렬' }).click()
  await page.getByRole('option', { name: '기업명순', exact: true }).click()
  await expect(page.getByRole('combobox', { name: '기업 정렬' })).toContainText('기업명순')
  const search = page.getByPlaceholder('기업명 또는 종목코드 검색')
  await search.fill('005930')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('삼성전자')
  await page.getByRole('combobox', { name: '기업 정렬' }).click()
  await page.getByRole('option', { name: '시가총액 낮은 순', exact: true }).click()
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('삼성전자')
  for (const theme of ['light', 'dark']) {
    await page.evaluate((theme) => (document.documentElement.dataset.theme = theme), theme)
    const sort = page.getByRole('combobox', { name: '기업 정렬' })
    await expect(sort).toBeVisible()
    const searchBounds = await search.boundingBox()
    const sortBounds = await sort.boundingBox()
    expect(Math.abs(searchBounds!.y - sortBounds!.y)).toBeLessThan(3)
    expect(sortBounds!.x + sortBounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
    await sort.click()
    await expect(page.getByRole('option', { name: '시가총액 높은 순', exact: true })).toBeVisible()
    if (process.env.E2E_ARTIFACT_DIR)
      await page.screenshot({
        path: `${process.env.E2E_ARTIFACT_DIR}/기업정렬-${page.viewportSize()!.width}-${theme}.png`,
        animations: 'disabled',
      })
    await page.keyboard.press('Escape')
  }
  expect(errors).toEqual([])
})
