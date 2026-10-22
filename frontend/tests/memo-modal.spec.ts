import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('메모 검색 옆에서 모달을 열고 업로드와 작성 탭을 전환합니다', async ({ page }) => {
  test.skip(!process.env.E2E_TOKEN_FILE, '로그인 토큰 파일이 필요합니다.')
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript(
    (token) => sessionStorage.setItem('disclosure-check.token', token),
    token,
  )
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  for (const width of [1720, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/companies/00126478?tab=memos')
    await expect(page.locator('.company-tools')).toHaveCount(0)
    const trigger = page.getByRole('button', { name: '메모 추가', exact: true })
    await trigger.click()
    const dialog = page.getByRole('dialog', { name: '메모 추가', exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('tab', { name: '파일 업로드' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await dialog.getByLabel('메모 파일').setInputFiles({
      name: '검증메모.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('기준 메모'),
    })
    await expect(dialog).toContainText('검증메모.txt')
    await dialog.getByRole('tab', { name: '작성', exact: true }).click()
    await dialog.getByLabel('메모 내용').fill('작성 중인 메모')
    await expect(dialog.getByRole('button', { name: '저장', exact: true })).toBeEnabled()
    await dialog.getByRole('tab', { name: '작성', exact: true }).press('ArrowLeft')
    await expect(dialog.getByRole('tab', { name: '파일 업로드' })).toBeFocused()
    await expect(dialog).toContainText('검증메모.txt')
    await dialog.getByRole('tab', { name: '파일 업로드' }).press('ArrowRight')
    await expect(dialog.getByLabel('메모 내용')).toHaveValue('작성 중인 메모')
    const box = await dialog.boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await page.keyboard.press('Escape')
    await expect(dialog).not.toBeVisible()
    await expect(trigger).toBeFocused()
    await trigger.click()
    await expect(dialog.getByLabel('메모 내용')).toHaveValue('작성 중인 메모')
    await dialog.getByRole('button', { name: '메모 추가 닫기' }).click()
    await expect(dialog).not.toBeVisible()
  }
  expect(errors).toEqual([])
})

test('메모 본문은 화면 가운데 모달에서 읽고 닫습니다', async ({ page }) => {
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript(t => sessionStorage.setItem('disclosure-check.token', t), token)
  const memo = { id: 'reader-preview', company_name: '삼성중공업', title: '모달 읽기 검증', current_version: 1, created_at: '2026-10-21T00:00:00Z', updated_at: '2026-10-21T00:00:00Z' }
  await page.route('**/api/v1/memos**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/versions/1')) return route.fulfill({ json: { version: 1, content: '모달 본문 확인', created_at: memo.created_at } })
    if (path.endsWith('/versions')) return route.fulfill({ json: [{ version: 1, created_at: memo.created_at }] })
    return route.fulfill({ json: path.endsWith('/reader-preview') ? memo : [memo] })
  })
  for (const width of [1720, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/companies/00126478?tab=memos')
    const trigger = page.getByRole('button', { name: memo.title, exact: true })
    await trigger.click()
    const modal = page.locator('dialog.memo-reader')
    await expect(modal).toBeVisible()
    await expect(modal).toContainText('모달 본문 확인')
    const box = await modal.boundingBox()
    expect(Math.abs(box!.x + box!.width / 2 - width / 2)).toBeLessThan(1)
    expect(Math.abs(box!.y + box!.height / 2 - 500)).toBeLessThan(1)
    await page.keyboard.press('Escape')
    await expect(modal).not.toBeVisible()
    await expect(trigger).toBeFocused()
  }
})
