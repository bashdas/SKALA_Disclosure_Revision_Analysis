import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('기업 검색과 추가 목록에서 실제 종목 시세를 조회합니다', async ({ page }) => {
  test.skip(!process.env.E2E_TOKEN_FILE, '로그인 토큰 파일이 필요합니다.')
  test.setTimeout(120000)
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript(
    (token) => sessionStorage.setItem('disclosure-check.token', token),
    token,
  )
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/companies')
  const rows = page.locator('.company-row')
  await expect(rows.first().locator('.quote-price')).toContainText('원', { timeout: 20000 })
  if (process.env.E2E_ARTIFACT_DIR)
    await page.screenshot({ path: process.env.E2E_ARTIFACT_DIR + '/기업시세목록.png' })
  await expect(rows.first().locator('.directory-last-update')).toContainText('최근 업데이트', {
    timeout: 45000,
  })
  await expect(rows.first().locator('.watchlist-sector')).not.toHaveText(
    /조회 중|조회 실패|분류 없음/,
    { timeout: 45000 },
  )
  await expect(rows.first().locator('.directory-update').first()).not.toHaveText(
    /공시 0|조회 중|조회 실패/,
  )
  const initial = await rows.count()
  await rows.last().scrollIntoViewIfNeeded()
  await expect.poll(() => rows.count()).toBeGreaterThan(initial)
  await expect(rows.nth(initial).locator('.quote-price')).not.toContainText('조회 중', {
    timeout: 20000,
  })
  const search = page.getByPlaceholder('기업명 또는 종목코드 검색')
  await search.fill('005930')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('삼성전자')
  await expect(rows.first().locator('.quote-price')).toContainText('원', { timeout: 20000 })
  await expect(rows.first().locator('.watchlist-sector')).toHaveText('반도체와반도체장비', {
    timeout: 45000,
  })
  await expect(rows.first().locator('.directory-last-update')).toContainText('최근 업데이트', {
    timeout: 45000,
  })
  const publicCount = Number(
    (await rows.first().locator('.directory-update span').first().textContent())?.trim(),
  )
  expect(publicCount).toBeGreaterThan(0)
  const cells = rows.first().locator('td.numeric')
  await expect(cells.nth(1)).toContainText('%')
  await expect(cells.nth(2)).toContainText('원')
  await expect(cells.nth(3)).toContainText('원')
  await page.goto('/')
  const favorites = page.locator('.watchlist-row')
  await expect(
    favorites
      .filter({ has: page.locator('.watchlist-code', { hasText: /^[0-9]{6}$/ }) })
      .first()
      .locator('.quote-price'),
  ).toContainText('원', { timeout: 20000 })
  expect(await page.locator('.topbar').evaluate(el => el.getBoundingClientRect().height)).toBe(60)
  const searchFavorites = page.getByRole('searchbox', { name: '관심종목 검색' })
  const domestic = favorites.filter({ has: page.locator('.watchlist-code', { hasText: /^[0-9]{6}$/ }) }).first()
  const code = await domestic.locator('.watchlist-code').textContent()
  await searchFavorites.fill(code!.trim())
  await expect(favorites).toHaveCount(1)
  await searchFavorites.fill('없는 관심종목')
  await expect(favorites).toHaveCount(0)
  await expect(page.getByText('검색 결과가 없습니다', { exact: true })).toBeVisible()
  await searchFavorites.fill('')
  await expect(favorites.first()).toBeVisible()
  expect(errors).toEqual([])
})
