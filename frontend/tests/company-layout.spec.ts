import { test, expect } from '@playwright/test'
import { readFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'

test('기업 상세의 배경과 필터, 세 목록의 오른쪽 버튼 정렬을 확인합니다', async ({ page }) => {
  test.skip(!process.env.E2E_TOKEN_FILE, '로그인 토큰 파일이 필요합니다.')
  test.setTimeout(120000)
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript(
    (token) => sessionStorage.setItem('disclosure-check.token', token),
    token,
  )
  const company = process.env.E2E_COMPANY_CODE ?? '00126478'
  const output = process.env.E2E_ARTIFACT_DIR
  if (output) mkdirSync(output, { recursive: true })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))

  for (const width of [1720, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    await page.goto(`/companies/${company}`)
    await expect(page.locator('.filing-filters')).toBeVisible()
    await expect(page.locator('.tabs a')).toHaveCount(3)
    await expect(page.locator('.tabs')).not.toContainText('분석 이력')
    for (const theme of ['dark', 'light']) {
      const toggle = page.getByRole('button', {
        name: theme === 'dark' ? '다크 모드로 전환' : '라이트 모드로 전환',
      })
      if (await toggle.count()) await toggle.click()
      else await page.evaluate((theme) => (document.documentElement.dataset.theme = theme), theme)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      const backgrounds = await page.evaluate(() =>
        [
          document.body,
          document.querySelector('.company-workspace')!,
          document.querySelector('.topbar')!,
          document.querySelector('.company-tools')!,
        ]
          .filter(Boolean)
          .map((el) => getComputedStyle(el).backgroundColor),
      )
      expect(new Set(backgrounds).size).toBe(1)
      const inputs = page.locator('.filing-filters input, .ui-date > button')
      const boxes = await inputs.evaluateAll((nodes) =>
        nodes.map((node) => {
          const r = node.getBoundingClientRect()
          return { y: r.y, height: r.height, right: r.right }
        }),
      )
      expect(boxes.every((b) => b.height === 44)).toBe(true)
      if (width > 1150) expect(new Set(boxes.map((b) => Math.round(b.y))).size).toBe(1)
      expect(Math.abs(boxes[1]!.y - boxes[2]!.y)).toBeLessThan(1)

      for (let tab = 0; tab < 3; tab++) {
        await page.locator('.tabs a').nth(tab).click()
        await expect(page).toHaveURL(
          new RegExp('tab=' + ['filings', 'memos', 'reports'][tab]),
        )
        await expect(page.locator('.company-tools')).toHaveCount(0)
        const rows = page.locator(
          '.company-workspace .document-row, .company-workspace .analysis-row',
        )
        await expect(
          page
            .locator(
              '.document-section .document-row, .document-section .analysis-row, .document-section .empty-state',
            )
            .first(),
        ).toBeVisible()
        const alignment = await rows.evaluateAll((rows) =>
          rows.map((row) => {
            const actions = row.querySelector('.document-actions')!
            const r = row.getBoundingClientRect(),
              a = actions.getBoundingClientRect()
            const buttons = [...actions.children].map((b) => b.getBoundingClientRect())
            return {
              right: Math.abs(r.right - parseFloat(getComputedStyle(row).paddingRight) - a.right),
              sameLine: buttons.every((b) => Math.abs(b.y + b.height / 2 - buttons[0]!.y - buttons[0]!.height / 2) < 1),
              inside: a.left >= r.left && a.right <= r.right,
            }
          }),
        )
        expect(alignment.every((a) => a.right < 2 && a.sameLine && a.inside)).toBe(true)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        )
        if (tab === 0) {
          const ordinary = rows.filter({ has: page.locator('.tag', { hasText: '신규공시' }) })
          expect(await ordinary.count()).toBeGreaterThan(0)
          await expect(
            ordinary.getByRole('button', { name: '분석하기', exact: true }),
          ).toHaveCount(0)
        }
        if (
          output &&
          ((width === 1720 && theme === 'dark') || (width === 390 && theme === 'light'))
        )
          await page.screenshot({ path: join(output, `기업상세_${width}_${theme}_${tab}.png`) })
      }
      await page.locator('.tabs a').first().click()
    }
  }

  await page.setViewportSize({ width: 1720, height: 1100 })
  await page.getByLabel('공시 검색', { exact: true }).fill('정정')
  await expect(page.locator('.document-row').first()).toContainText('정정공시')
  const corrections = page
    .locator('.document-row')
    .filter({ has: page.locator('.tag', { hasText: '정정공시' }) })
  expect(await corrections.count()).toBeGreaterThan(0)
  await expect(
    corrections.first().getByRole('button', { name: '분석하기', exact: true }),
  ).toBeEnabled()
  const date = page.locator('.ui-date').first()
  const queried = page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/v1/disclosures' && url.searchParams.get('query') === '정정'
  })
  await date.getByRole('button', { name: '시작일', exact: true }).click()
  await page.locator('[data-slot=calendar-cell-trigger]:not([data-disabled]):not([data-selected])').first().click()
  expect((await queried).status()).toBe(200)
  expect(errors).toEqual([])
})
