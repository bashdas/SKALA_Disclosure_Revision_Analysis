import { expect, test } from '@playwright/test'

for (const role of ['ANALYST', 'RA'] as const) {
  test(`${role}의 내부 리포트 화면 접근을 통합 후에도 유지합니다`, async ({ page }) => {
    await page.addInitScript(() =>
      sessionStorage.setItem('disclosure-check.token', 'local-role-fixture'),
    )
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
      const body =
        path === '/users/me'
          ? { id: 'fixture-user', email: 'fixture@example.com', name: '권한 검증', role }
          : []
      await route.fulfill({ json: body })
    })
    await page.goto('/internal-reports')
    const menu = page
      .getByRole('navigation', { name: '주 메뉴' })
      .getByRole('link', { name: '내부 리포트', exact: true })
    if (role === 'ANALYST') {
      await expect(menu).toBeVisible()
      await expect(page.getByRole('heading', { name: '내부 리포트', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '리포트 등록', exact: true })).toBeVisible()
    } else {
      await expect(page).toHaveURL(/\/home$/)
      await expect(menu).toHaveCount(0)
      await expect(page.getByRole('button', { name: '리포트 등록', exact: true })).toHaveCount(0)
    }
  })

  test(`${role} 회원가입은 조직 없이 선택한 역할을 전달합니다`, async ({ page }) => {
    let submitted: unknown
    await page.route('**/api/v1/auth/signup', async (route) => {
      submitted = route.request().postDataJSON()
      await route.fulfill({ status: 201, json: { id: 'fixture-user', role } })
    })
    await page.goto('/login')
    await page.getByRole('button', { name: '회원가입', exact: true }).click()
    await page.getByLabel('이름', { exact: true }).fill('역할 검증')
    await page.getByRole('combobox', { name: /^역할/ }).selectOption(role)
    await page.getByLabel('이메일', { exact: true }).fill('fixture@example.com')
    await page.getByLabel('비밀번호', { exact: true }).fill('Synthetic-test-only-2026!')
    await page.getByRole('button', { name: '회원가입', exact: true }).click()
    await expect(page.getByRole('heading', { name: '공시체크 로그인', exact: true })).toBeVisible()
    expect(submitted).toEqual({
      email: 'fixture@example.com',
      password: 'Synthetic-test-only-2026!',
      name: '역할 검증',
      role,
    })
  })
}
