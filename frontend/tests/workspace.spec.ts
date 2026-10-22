import { test, expect } from '@playwright/test'

test('인증이 없으면 로그인 화면으로 이동합니다', async ({ page }) => {
  await page.goto('/companies')
  await expect(page.getByRole('heading', { name: '공시체크 로그인' })).toBeVisible()
  await expect(page).toHaveURL(/\/login$/)
})

test('메인 UI에서 기업 검색, 즐겨찾기, 정정공시 분석을 연결합니다', async ({ page }) => {
  test.setTimeout(240000)
  page.setDefaultTimeout(15000)
  test.skip(
    !process.env.E2E_EMAIL || !process.env.E2E_PASSWORD || !process.env.E2E_COMPANY_CODE,
    '검사 계정과 기업이 필요합니다.',
  )
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.setViewportSize({ width: 1720, height: 1100 })
  await page.goto('/login')
  await page.getByLabel('이메일', { exact: true }).fill(process.env.E2E_EMAIL!)
  await page.getByLabel('비밀번호', { exact: true }).fill(process.env.E2E_PASSWORD!)
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await expect(page.getByRole('heading', { name: /리서치 홈/ })).toBeVisible()
  const homeLeft = (await page.locator('.home-heading').boundingBox())!.x
  expect(Math.abs((await page.locator('.brand').boundingBox())!.x - homeLeft)).toBeLessThan(2)
  await page.screenshot({
    path: '/tmp/disclosure-web-validation/restored-home.png',
    fullPage: true,
  })
  await page
    .getByRole('navigation', { name: '주 메뉴' })
    .getByRole('link', { name: '기업 목록', exact: true })
    .click()
  const rows = page.locator('tr.company-row')
  await expect(rows.first()).toBeVisible({ timeout: 60000 })
  const count = await rows.count()
  await rows.last().scrollIntoViewIfNeeded()
  await expect.poll(() => rows.count(), { timeout: 60000 }).toBeGreaterThan(count)
  await page.getByLabel('기업 검색', { exact: true }).fill(process.env.E2E_COMPANY_CODE!)
  const row = page.getByTestId(`company-${process.env.E2E_COMPANY_CODE}`)
  await expect(row).toBeVisible({ timeout: 60000 })
  const star = row.getByRole('button', { name: /관심종목/ })
  if ((await star.getAttribute('aria-pressed')) === 'true') await star.click()
  await expect(star).toHaveAttribute('aria-pressed', 'false')
  await star.click()
  await expect(star).toHaveAttribute('aria-pressed', 'true', { timeout: 60000 })
  await page.screenshot({
    path: '/tmp/disclosure-web-validation/restored-companies.png',
    fullPage: true,
  })
  await page
    .getByRole('navigation', { name: '주 메뉴' })
    .getByRole('link', { name: '내 페이지', exact: true })
    .click()
  const favorite = page.getByTestId(`favorite-${process.env.E2E_COMPANY_CODE}`)
  await expect(favorite).toBeVisible()
  await favorite.getByRole('link', { name: process.env.E2E_COMPANY_NAME!, exact: true }).click()
  await expect(
    page.getByRole('heading', { name: process.env.E2E_COMPANY_NAME!, exact: true }),
  ).toBeVisible()
  expect(
    Math.abs((await page.locator('.company-market-name').boundingBox())!.x - homeLeft),
  ).toBeLessThan(2)
  const filings = page.locator('article.document-row')
  await expect(filings.first()).toBeVisible({ timeout: 60000 })
  const ordinary = filings.filter({ has: page.locator('.tag', { hasText: '신규공시' }) }).first()
  if (await ordinary.count())
    await expect(ordinary.getByRole('button', { name: '분석하기' })).toHaveCount(0)
  await page.getByRole('link', { name: /^메모 관리/ }).click()
  await page.getByRole('button', { name: '메모 추가', exact: true }).click()
  const title = `실제 연동 검사 ${Date.now()}`
  await page.getByLabel('메모 파일').setInputFiles({
    name: 'memo.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(
      `${process.env.E2E_COMPANY_NAME} 기업분석 메모. 기존 계약금액과 기간이 유지된다는 가정으로 실적을 검토했습니다. 정정공시의 변경 내역을 확인해야 합니다.`,
    ),
  })
  await page.getByLabel(/메모 제목/).fill(title)
  await page.getByRole('button', { name: '메모 업로드', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('메모를 추가했습니다')
  await page.reload()
  await page.getByRole('button', { name: title, exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('기존 계약금액과 기간')
  await page.getByRole('button', { name: '원문 닫기' }).click()
  await page.getByRole('button', { name: '메모 추가', exact: true }).click()
  await page.getByRole('tab', { name: '작성', exact: true }).click()
  const save = page.getByRole('button', { name: '저장', exact: true })
  await expect(save).toBeDisabled()
  await page.getByLabel('메모 내용', { exact: true }).fill('   ')
  await expect(save).toBeDisabled()
  const writtenTitle = `직접 작성 검사 ${Date.now()}`
  const writtenBody = ' 첫 문단의 가정을 보존합니다.\n\n입찰 참여 가정을 정정공시와 비교합니다. '
  await page.getByLabel(/메모 제목/).fill(writtenTitle)
  await page.getByLabel('메모 내용', { exact: true }).fill(writtenBody)
  const saved = page.waitForResponse(
    (r) => r.url().endsWith('/api/v1/memos') && r.request().method() === 'POST',
  )
  await page.screenshot({ path: '/tmp/disclosure-web-validation/memo-editor.png', fullPage: true })
  await save.click()
  const savedResponse = await saved
  expect(savedResponse.status()).toBe(201)
  const written = await savedResponse.json()
  const bodyResponse = await page.request.get(`/api/v1/memos/${written.id}/versions/1`, {
    headers: { Authorization: savedResponse.request().headers()['authorization']! },
  })
  expect((await bodyResponse.json()).content).toBe(writtenBody)
  await page.reload()
  await page.getByRole('button', { name: writtenTitle, exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('입찰 참여 가정을 정정공시와 비교합니다.')
  await page.getByRole('button', { name: '원문 닫기' }).click()

  await page
    .getByRole('navigation', { name: '기업 자료 종류' })
    .getByRole('link', { name: /^공시/ })
    .click()
  const correction = filings
    .filter({
      has: page.getByRole('link', { name: process.env.E2E_CORRECTION_TITLE!, exact: true }),
    })
    .first()
  await expect(correction).toBeVisible({ timeout: 60000 })
  await correction.getByRole('button', { name: '분석하기', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '공시 분석', exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '기준 메모', exact: true }).click()
  await page.getByRole('option', { name: writtenTitle, exact: true }).click()
  await page.screenshot({
    path: '/tmp/disclosure-web-validation/restored-company.png',
    fullPage: true,
  })
  const accepted = page.waitForResponse(
    (r) => r.url().endsWith('/api/v1/analyses') && r.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '분석 시작', exact: true }).click()
  const response = await accepted
  expect(response.status()).toBe(202)
  const task = await response.json()
  await expect(page).toHaveURL(new RegExp(`/analyses/${task.task_id}$`))
  await expect(
    page.getByRole('heading', { name: '공시 영향 분석 보고서', exact: true }),
  ).toBeVisible({
    timeout: 150000,
  })
  await page.reload()
  await expect(
    page.getByRole('heading', { name: '공시 영향 분석 보고서', exact: true }),
  ).toBeVisible({
    timeout: 30000,
  })
  const blocks = await page
    .locator('.progress-section,.unified-report')
    .evaluateAll((nodes) => nodes.map((n) => n.className))
  expect(blocks.map((name) => name.replace('surface', '').trim())).toEqual(['unified-report'])
  await expect(page.locator('.markdown-body h1')).toHaveCount(0)
  await expect(page.locator('.markdown-body table').first()).toBeVisible()
  for (const extension of ['md', 'pdf']) {
    const file = page.waitForEvent('download')
    await page
      .getByRole('button', {
        name: extension === 'pdf' ? 'PDF 다운로드' : 'MD 다운로드',
        exact: true,
      })
      .click()
    const download = await file
    expect(download.suggestedFilename()).toBe(`report-${task.task_id}.${extension}`)
    await download.saveAs(`/tmp/disclosure-web-validation/browser-report.${extension}`)
  }
  await page.goto(`/companies/${process.env.E2E_COMPANY_CODE}?tab=memos`)
  page.once('dialog', (dialog) => dialog.accept())
  const deleted = page.waitForResponse(
    (r) => r.url().endsWith(`/memos/${written.id}`) && r.request().method() === 'DELETE',
  )
  await page.getByRole('button', { name: `${writtenTitle} 삭제`, exact: true }).click()
  expect((await deleted).status()).toBe(204)
  await expect(page.getByRole('button', { name: writtenTitle, exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('button', { name: writtenTitle, exact: true })).toHaveCount(0)
  await page.goto(`/analyses/${task.task_id}`)
  await page.locator('.report-context button').click()
  await expect(page.getByRole('dialog')).toContainText('입찰 참여 가정을 정정공시와 비교합니다.')
  expect(errors).toEqual([])
})

test('회원가입과 비밀번호 변경 후 새 비밀번호로 로그인합니다', async ({ page }, testInfo) => {
  test.skip(!process.env.E2E_EMAIL, '실제 검사 서버가 필요합니다.')
  const email = `ui-${Date.now()}-${testInfo.project.name}@example.com`
  const password = 'ui-integration-password-123!'
  await page.goto('/login')
  await page.getByRole('button', { name: '회원가입', exact: true }).click()
  await page.getByLabel('조직 이름').fill('화면 연동 검사 조직')
  await page.getByLabel('이메일', { exact: true }).fill(email)
  await page.getByLabel('비밀번호', { exact: true }).fill(password)
  await page.getByRole('button', { name: '회원가입', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('회원가입을 완료했습니다')
  await page.getByLabel('비밀번호', { exact: true }).fill(password)
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await page.getByRole('button', { name: '내 계정', exact: true }).click()
  await page.getByLabel('현재 비밀번호', { exact: true }).fill(password)
  await page.getByLabel('새 비밀번호', { exact: true }).fill(password + 'new')
  await page.getByLabel('새 비밀번호 확인', { exact: true }).fill(password + 'new')
  await page.getByRole('button', { name: '비밀번호 변경', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('이메일', { exact: true }).fill(email)
  await page.getByLabel('비밀번호', { exact: true }).fill(password + 'new')
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await expect(page.getByRole('heading', { name: /리서치 홈/ })).toBeVisible()
})
