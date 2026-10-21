import { test, expect } from '@playwright/test'

for (const theme of ['light', 'dark'] as const) {
  test(`${theme}: 주요 화면·문서 패널의 가독성과 모바일 배치`, async ({ page }, testInfo) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.addInitScript(
      (value) => localStorage.setItem('disclosure-check.theme.v1', value),
      theme,
    )
    for (const url of [
      '/home',
      '/companies',
      '/companies/shi',
      '/companies/lnf?tab=memos',
      '/companies/lnf?tab=history',
      '/analyses/sample-shi',
      '/login',
    ]) {
      await page.goto(url)
      await expect(page.locator('h1')).toBeVisible()
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      const measurements = await page.evaluate(() => ({
        page: document.documentElement.scrollWidth,
        viewport: innerWidth,
        heading: getComputedStyle(document.querySelector('h1')!).fontSize,
        background: getComputedStyle(document.body).backgroundColor,
      }))
      expect(measurements.page).toBeLessThanOrEqual(measurements.viewport)
      expect(measurements.heading).toBe(url === '/companies' ? '17px' : '24px')
      expect(measurements.background).toBe(
        theme === 'dark' ? 'rgb(23, 23, 28)' : 'rgb(255, 255, 255)',
      )
      await page.screenshot({
        path: `test-results/theme-${theme}-${url.split('/')[1]}-${testInfo.project.name}-${url.includes('?') ? url.split('=')[1] : url.split('/')[2] || 'index'}.png`,
        fullPage: true,
      })
    }
    await page.goto('/analyses/sample-shi')
    await page.getByRole('button', { name: /러시아 프로젝트와 수주·환헤지 점검 · v1/ }).click()
    const drawer = page.getByRole('dialog')
    await expect(drawer).toBeVisible()
    const drawerWidth = await drawer.evaluate((node) => ({
      content: node.scrollWidth,
      viewport: node.clientWidth,
    }))
    expect(drawerWidth.content).toBeLessThanOrEqual(drawerWidth.viewport)
    await expect(drawer.locator('.source-content')).toHaveCSS('font-size', '15px')
    await expect(drawer).toHaveCSS(
      'background-color',
      theme === 'dark' ? 'rgb(30, 30, 36)' : 'rgb(255, 255, 255)',
    )
    await page.screenshot({
      path: `test-results/theme-${theme}-drawer-${testInfo.project.name}.png`,
      fullPage: true,
    })
    await page.getByRole('button', { name: '원문 닫기' }).click()
    expect(errors).toEqual([])
  })
}

test('테마 전환은 새로고침·사용자 전환 후에도 유지된다', async ({ page }) => {
  await page.goto('/home')
  await page.getByRole('button', { name: '다크 모드로 전환' }).click()
  await expect(page.getByRole('button', { name: '라이트 모드로 전환' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByLabel('데모 사용자 전환').selectOption('shipbuilding-ra')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('button', { name: '라이트 모드로 전환' }).click()
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})

test('Vue가 실행되기 전에도 저장된 다크 테마를 적용한다', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('disclosure-check.theme.v1', 'dark'))
  await page.route('**/*', (route) => {
    const request = route.request()
    if (request.resourceType() === 'script' && !request.url().endsWith('/theme-init.js'))
      return route.abort()
    return route.continue()
  })
  await page.goto('/home')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.locator('html')).toHaveCSS('background-color', 'rgb(23, 23, 28)')
  await expect(page.locator('#app')).toBeEmpty()
})

test('테마 저장이 차단돼도 화면과 테마 전환을 사용할 수 있다', async ({ page }) => {
  await page.addInitScript(() => {
    const read = Storage.prototype.getItem
    const write = Storage.prototype.setItem
    Storage.prototype.getItem = function (key) {
      if (key === 'disclosure-check.theme.v1') throw new Error('blocked')
      return read.call(this, key)
    }
    Storage.prototype.setItem = function (key, value) {
      if (key === 'disclosure-check.theme.v1') throw new Error('blocked')
      write.call(this, key, value)
    }
  })
  await page.goto('/home')
  await expect(page.locator('h1')).toBeVisible()
  await page.getByRole('button', { name: '다크 모드로 전환' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})

test('잘못된 저장값과 폰트 CDN 실패에도 라이트 화면을 사용할 수 있다', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('disclosure-check.theme.v1', 'invalid'))
  await page.route('https://cdn.jsdelivr.net/**', (route) => route.abort())
  await page.goto('/companies')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await expect(page.getByTestId('company-lnf')).toBeVisible()
  await expect(page.getByRole('button', { name: '다크 모드로 전환' })).toBeVisible()
})
