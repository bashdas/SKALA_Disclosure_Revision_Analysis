import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

test('현재 화면에서 내 계정 모달을 열고 닫으며 권한 표시를 숨깁니다', async ({ page }) => {
  test.skip(!process.env.E2E_TOKEN_FILE, '로그인 토큰 파일이 필요합니다.')
  const { token } = JSON.parse(readFileSync(process.env.E2E_TOKEN_FILE!, 'utf8'))
  await page.addInitScript(
    (token) => sessionStorage.setItem('disclosure-check.token', token),
    token,
  )
  for (const width of [1720, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/companies/00126478')
    await expect(page.getByRole('heading', { name: '삼성중공업', exact: true })).toBeVisible()
    const url = page.url()
    const trigger = page.getByRole('button', { name: '내 계정', exact: true })
    await trigger.click()
    const dialog = page.getByRole('dialog', { name: '내 계정', exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog).not.toContainText(/권한:|ANALYST/)
    await dialog.getByLabel('현재 비밀번호', { exact: true }).fill('test-old-password')
    await dialog.getByLabel('새 비밀번호', { exact: true }).fill('test-new-password')
    await dialog.getByLabel('새 비밀번호 확인', { exact: true }).fill('test-other-password')
    await dialog.getByRole('button', { name: '비밀번호 변경', exact: true }).click()
    await expect(dialog.getByRole('alert')).toContainText('새 비밀번호가 일치하지 않습니다.')
    const box = await dialog.boundingBox()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await page.keyboard.press('Escape')
    await expect(dialog).not.toBeVisible()
    await expect(trigger).toBeFocused()
    expect(page.url()).toBe(url)
    await trigger.click()
    await expect(dialog.getByLabel('현재 비밀번호', { exact: true })).toHaveValue('')
    await dialog.getByRole('button', { name: '내 계정 닫기' }).click()
  }
  await page.goto('/account')
  await expect(page.getByRole('dialog', { name: '내 계정', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '내 계정 닫기' }).click()
  await expect(page).toHaveURL(/\/home$/)
})
