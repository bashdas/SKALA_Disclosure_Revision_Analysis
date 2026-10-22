import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('분석 선택 모달 열기와 닫기는 공시를 등록하지 않습니다', async ({ page }) => {
  test.skip(!process.env.E2E_TOKEN_FILE, '로그인 토큰 파일이 필요합니다.')
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript(
    (token) => sessionStorage.setItem('disclosure-check.token', token),
    token,
  )
  const writes: string[] = []
  page.on('request', (request) => {
    if (
      request.method() === 'POST' &&
      /\/api\/v1\/(filings|analyses)$/.test(new URL(request.url()).pathname)
    )
      writes.push(request.url())
  })
  for (const width of [1720, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/companies/00126478')
    await page.getByLabel('공시 검색', { exact: true }).fill('정정')
    const action = page.getByRole('button', { name: '분석하기', exact: true }).first()
    await expect(action).toBeVisible({ timeout: 30000 })
    await expect(page.locator('.company-tools')).toHaveCount(0)
    await expect(page.getByRole('link', { name: '내용 확인', exact: true })).toHaveCount(0)
    await action.click()
    const dialog = page.getByRole('dialog', { name: '공시 분석', exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('.analysis-target')).not.toBeEmpty()
    await expect(dialog.getByRole('button', { name: '분석 시작', exact: true })).toBeDisabled()
    const memo = dialog.getByRole('combobox', { name: '기준 메모', exact: true })
    await memo.click()
    const options = dialog.getByRole('option')
    if (await options.count()) {
      await options.first().click()
      await expect(dialog.getByRole('combobox', { name: '기준 버전' })).toBeVisible()
      await expect(dialog.getByRole('button', { name: '분석 시작', exact: true })).toBeEnabled()
    } else {
      await page.keyboard.press('Escape')
      await expect(dialog.getByRole('listbox')).toHaveCount(0)
    }
    const box = await dialog.boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await page.keyboard.press('Escape')
    await expect(dialog).not.toBeVisible()
    await expect(action).toBeFocused()
  }
  expect(writes).toEqual([])
})
