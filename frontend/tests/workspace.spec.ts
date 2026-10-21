import { test, expect } from '@playwright/test'

test('기업 목록 표·배지 이동과 문서·버전별 읽음 상태', async ({ page }, testInfo) => {
  await page.goto('/companies')
  await expect(page.getByTestId('company-lnf')).toBeVisible()
  await expect(page.getByTestId('company-shi')).toBeVisible()
  await page.screenshot({
    path: `test-results/companies-${testInfo.project.name}.png`,
    fullPage: true,
  })
  await expect(page.getByTestId('lnf-filing-badge')).toHaveAccessibleName(
    '엘앤에프 공시 업데이트 1건',
  )
  await page.getByTestId('lnf-filing-badge').click()
  await expect(page).toHaveURL(/tab=filings/)
  await page.getByRole('link', { name: '기업 목록', exact: true }).first().click()
  await expect(page.getByTestId('lnf-filing-badge')).toHaveAccessibleName(
    '엘앤에프 공시 업데이트 1건',
  )
  await page.getByTestId('lnf-filing-badge').click()
  await page.getByRole('button', { name: '[기재정정] 단일판매·공급계약체결', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('dialog')).toContainText('9,730,316원')
  await page.getByRole('button', { name: '원문 닫기' }).click()
  await page.getByRole('link', { name: '기업 목록', exact: true }).first().click()
  await expect(page.getByTestId('lnf-filing-badge')).toHaveAccessibleName(
    '엘앤에프 공시 업데이트 0건',
  )
  await expect(page.getByTestId('lnf-memo-badge')).toHaveAccessibleName(
    '엘앤에프 메모 업데이트 1건',
  )
  await expect(page.getByTestId('shi-filing-badge')).toHaveAccessibleName(
    '삼성중공업 공시 업데이트 2건',
  )
  await page.reload()
  await expect(page.getByTestId('lnf-filing-badge')).toHaveAccessibleName(
    '엘앤에프 공시 업데이트 0건',
  )
})

test('버전별 열람 기록을 각각 유지한다', async ({ page }) => {
  await page.goto('/analyses/sample-lnf')
  await page.getByRole('button', { name: /테슬라향 공급과 양극재 성장 가정 · v2/ }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByLabel('문서 버전').selectOption('1')
  await expect(page.getByRole('dialog')).toContainText('중장기 성장의 근거')
  await page.getByRole('button', { name: '원문 닫기' }).click()
  await page.getByRole('link', { name: '기업 목록', exact: true }).first().click()
  const keys = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('disclosure-check.reads.v1') || '[]'),
  )
  expect(keys).toContain('demo-ra:memo:memo-lnf:v1')
  expect(keys).toContain('demo-ra:memo:memo-lnf:v2')
})

test('엘앤에프 분석은 선택한 v1을 고정하고 보고서와 근거를 제공한다', async ({ page }) => {
  await page.goto('/companies/lnf')
  await expect(page.getByRole('button', { name: '영향 분석 시작' })).toBeDisabled()
  await page.getByLabel('대상 공시').selectOption('filing-lnf')
  await page.getByLabel('기준 메모', { exact: true }).selectOption('memo-lnf')
  await page.getByLabel('기준 버전').selectOption('1')
  await page.getByRole('button', { name: '영향 분석 시작' }).click()
  await expect(page).toHaveURL(/\/analyses\//)
  await expect(page.getByText('기준 메모 v1와 비교')).toBeVisible()
  await expect(
    page.getByText('계약금액 감소분 전체를 당기 매출·이익 감소액으로 적용하지 않으며', {
      exact: false,
    }),
  ).toBeVisible()
  await expect(page.locator('.report-heading .status-pill')).toContainText('주의사항 있음')
  await expect(page.getByText('선택 안 함', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '원문 문맥 확인' }).first().click()
  await expect(page.locator('#source-paragraph-0')).toHaveClass('highlighted')
  await expect(page.getByRole('dialog')).toContainText('중장기 성장의 근거')
  await page.getByRole('button', { name: '원문 닫기' }).click()
  await expect(page.locator('.report-preserve')).toContainText('변경되지 않았습니다')
  await page.getByRole('link', { name: '기업 목록', exact: true }).first().click()
  await expect(page.getByTestId('lnf-memo-badge')).toHaveAccessibleName(
    '엘앤에프 메모 업데이트 1건',
  )
})

test('삼성중공업은 관련 공시와 기반영 손실·추가 부담을 구분한다', async ({ page }) => {
  await page.goto('/companies/shi')
  await expect(page.getByText('20250618800387', { exact: false })).toBeVisible()
  await expect(page.getByText('20250618800388', { exact: false })).toBeVisible()
  await page.getByLabel('대상 공시').selectOption('filing-shi-1')
  await page.getByLabel('기준 메모', { exact: true }).selectOption('memo-shi')
  await page.getByRole('button', { name: '영향 분석 시작' }).click()
  await expect(page.locator('.report-heading .status-pill')).toContainText('주의사항 있음')
  await expect(
    page.getByText(
      '이미 반영한 손실은 다시 차감하지 않고 추가 손익·현금 부담을 별도로 검토합니다.',
      { exact: true },
    ),
  ).toBeVisible()
  await expect(page.getByRole('heading', { name: '외부 환경·위험', exact: true })).toBeVisible()
  await expect(
    page.getByText('선수금 반환 요구와 최종 지급 의무는 다릅니다.', { exact: false }),
  ).toBeVisible()
})

test('저장 실패에서 생성 내용은 유지되고 저장만 재시도된다', async ({ page }) => {
  await page.goto('/analyses/sample-save-failed')
  await expect(page.getByText('보고서가 아직 저장되지 않았습니다', { exact: true })).toBeVisible()
  await expect(page.locator('.report-title-row')).toContainText('미저장')
  const finding = await page.locator('.finding-card').first().innerText()
  await page.getByRole('button', { name: '보고서 저장 재시도' }).click()
  await expect(page.locator('.report-heading .status-pill')).toContainText('주의사항 있음')
  await expect(page.locator('.saved-label')).toBeVisible()
  expect(await page.locator('.finding-card').first().innerText()).toBe(finding)
  await expect(page.getByRole('button', { name: '보고서 저장 재시도' })).toHaveCount(0)
})

test('근거 부족과 분석 실패는 성공으로 둔갑하지 않는다', async ({ page }) => {
  await page.goto('/analyses/sample-shi')
  await expect(page.locator('.impact-tag.hold')).toBeVisible()
  await expect(
    page.locator('.perspective-card').filter({ hasText: '외부 환경·위험' }),
  ).toContainText('근거 부족')
  await page.goto('/analyses/sample-analysis-failed')
  await expect(page.getByText('분석을 완료하지 못했습니다', { exact: true })).toBeVisible()
  await expect(page.locator('.report-summary')).toHaveCount(0)
})

test('종목 안에서 메모를 추가하고 다른 종목과 분리한다', async ({ page }) => {
  await page.goto('/companies/lnf?tab=memos')
  await page
    .getByLabel('메모 파일')
    .setInputFiles({ name: 'empty.txt', mimeType: 'text/plain', buffer: Buffer.from(' \n ') })
  await page.getByRole('button', { name: '메모 업로드', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('비어')
  await page.getByLabel('메모 파일').setInputFiles({
    name: 'sample.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('새로운 검토 가정\n\n두 번째 문단'),
  })
  await page.getByRole('button', { name: '메모 업로드', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('엘앤에프 · v1')
  await page.getByRole('button', { name: 'sample', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('새로운 검토 가정')
  await page.getByRole('button', { name: '원문 닫기' }).click()
  await page.getByRole('link', { name: '기업 목록', exact: true }).first().click()
  await page.getByTestId('shi-memo-badge').click()
  await expect(page.getByRole('button', { name: 'sample', exact: true })).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: '러시아 프로젝트와 수주·환헤지 점검', exact: true }),
  ).toBeVisible()
  await page.getByRole('link', { name: '기업 목록', exact: true }).first().click()
  await page.getByTestId('lnf-memo-badge').click()
  await expect(page.getByRole('button', { name: 'sample', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: 'sample', exact: true })).toHaveCount(0)
})

test('빈 목록·조회 실패·없는 작업을 안내한다', async ({ page }) => {
  await page.goto('/companies?demo=empty')
  await expect(page.getByText('등록된 기업이 없습니다', { exact: true })).toBeVisible()
  await page.goto('/companies?demo=error')
  await expect(page.getByRole('alert')).toContainText('자료를 불러오지 못했어요')
  await page.goto('/analyses/unknown-task')
  await expect(page.getByText('분석 작업을 찾을 수 없습니다', { exact: true })).toBeVisible()
})

test('주요 화면에 가로 넘침이나 브라우저 오류가 없다', async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  for (const url of [
    '/home',
    '/login',
    '/companies',
    '/companies/shi',
    '/companies/lnf?tab=memos',
    '/companies/lnf?tab=history',
    '/analyses/sample-shi',
  ]) {
    await page.goto(url)
    await expect(page.locator('h1')).toBeVisible()
    const sizes = await page.evaluate(() => ({
      content: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
    }))
    expect(sizes.content).toBeLessThanOrEqual(sizes.viewport)
  }
  await page.screenshot({
    path: `test-results/report-${testInfo.project.name}.png`,
    fullPage: true,
  })
  expect(errors).toEqual([])
})

test('메모와 분석 이력은 종목 상세에서만 관리하고 이력의 상태를 구분한다', async ({
  page,
}, testInfo) => {
  await page.goto('/companies')
  await expect(
    page.locator('.topnav').getByRole('link', { name: '메모 관리', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.locator('.topnav').getByRole('link', { name: '분석 이력', exact: true }),
  ).toHaveCount(0)
  await page.getByRole('link', { name: '엘앤에프', exact: true }).click()
  await page
    .getByRole('navigation', { name: '기업 자료 종류' })
    .getByRole('link', { name: /분석 이력/ })
    .click()
  await expect(page.locator('.analysis-row')).toHaveCount(2)
  await expect(page.locator('.analysis-list')).not.toContainText('삼성중공업')
  await page.getByLabel('분석 상태').selectOption('FAILED')
  await expect(page.locator('.analysis-row')).toHaveCount(1)
  await expect(page.locator('.analysis-row .status-pill')).toContainText('분석 실패')
  await page.locator('.analysis-row').click()
  await expect(page.getByText('분석을 완료하지 못했습니다', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: '기업 목록', exact: true }).first().click()
  await page.getByRole('link', { name: '삼성중공업', exact: true }).click()
  await page
    .getByRole('navigation', { name: '기업 자료 종류' })
    .getByRole('link', { name: /분석 이력/ })
    .click()
  await expect(page.locator('.analysis-row')).toHaveCount(2)
  await expect(page.locator('.analysis-list')).not.toContainText('엘앤에프')
  await page.screenshot({
    path: `test-results/company-history-${testInfo.project.name}.png`,
    fullPage: true,
  })
  await page.getByLabel('분석 상태').selectOption('SAVE_FAILED')
  await expect(page.locator('.analysis-row')).toHaveCount(1)
  await expect(page.locator('.analysis-row .status-pill')).toContainText('저장 실패')
  await page
    .getByRole('navigation', { name: '기업 자료 종류' })
    .getByRole('link', { name: /메모 관리/ })
    .click()
  await page.screenshot({
    path: `test-results/company-memos-${testInfo.project.name}.png`,
    fullPage: true,
  })
  for (const legacy of ['/memos', '/analyses']) {
    await page.goto(legacy)
    await expect(page).toHaveURL(/\/companies$/)
  }
})

test('데모 로그인 후 개인 홈에서 관심종목과 예시 시장 정보를 확인한다', async ({
  page,
}, testInfo) => {
  await page.goto('/login')
  await page.getByLabel('데모 사용자', { exact: true }).selectOption('shipbuilding-ra')
  await page.getByRole('button', { name: '데모 로그인', exact: true }).click()
  await expect(page).toHaveURL(/\/home$/)
  await expect(page.getByRole('heading', { name: '김도윤님의 리서치 홈' })).toBeVisible()
  await expect(page.locator('.coverage-card')).toHaveCount(0)
  await expect(page.locator('.brand-mark')).toHaveCount(0)
  expect((await page.locator('.topbar').boundingBox())!.height).toBeLessThanOrEqual(52)
  await expect(page.getByTestId('favorite-shi')).toBeVisible()
  const watchlist = page.getByRole('table', { name: '관심종목 시세 예시' })
  for (const name of ['현재가', '등락률', '거래대금', '시가총액', '산업군']) {
    await expect(watchlist.getByRole('columnheader', { name, exact: true })).toBeVisible()
  }
  const row = page.getByTestId('favorite-shi')
  await expect(row).toContainText('24,500원')
  await expect(row).toContainText('-0.81%')
  await expect(row).toContainText('427억원')
  await expect(row).toContainText('21.5조원')
  await expect(row).toContainText('조선·해양')
  await expect(row.locator('.quote-change')).toHaveClass(/down/)
  expect((await row.boundingBox())!.height).toBeLessThanOrEqual(56)
  if ((page.viewportSize()?.width ?? 1440) < 650) {
    const tableScroll = page.getByRole('region', { name: '관심종목 시세 목록' })
    await tableScroll.evaluate((el) => {
      el.scrollLeft = el.scrollWidth
    })
    const industry = (await row.locator('.watchlist-sector').boundingBox())!
    const name = (await row.getByRole('rowheader').boundingBox())!
    const bounds = (await tableScroll.boundingBox())!
    expect(industry.x).toBeGreaterThanOrEqual(name.x + name.width)
    expect(industry.x + industry.width).toBeLessThanOrEqual(bounds.x + bounds.width)
    await tableScroll.evaluate((el) => {
      el.scrollLeft = 0
    })
  }
  await expect(page.getByTestId('favorite-lnf')).toHaveCount(0)
  await expect(page.locator('.market-item')).toHaveCount(12)
  expect((await page.locator('.market-rail').boundingBox())!.height).toBeLessThan(320)
  await expect(page.locator('.market-sparkline')).toHaveCount(12)
  await expect(page.locator('.market-featured')).toContainText('코스피')
  await expect(
    page
      .getByRole('navigation', { name: '주 메뉴' })
      .getByRole('link', { name: '홈', exact: true }),
  ).toHaveClass(/active/)
  await page.screenshot({ path: `test-results/home-${testInfo.project.name}.png`, fullPage: true })
  const strip = page.getByRole('region', { name: '시장 지표', exact: true })
  await strip.getByRole('button', { name: '환율·금리', exact: true }).click()
  await expect(strip.locator('.market-item')).toHaveCount(3)
  await expect(strip.getByRole('heading', { name: 'DXY', exact: true })).toBeVisible()
  await strip.getByRole('button', { name: '원자재', exact: true }).click()
  await expect(strip.locator('.market-item')).toHaveCount(3)
  await expect(strip.getByRole('heading', { name: 'WTI', exact: true })).toBeVisible()
  await strip.getByRole('button', { name: '전체', exact: true }).click()
  await expect(strip.locator('.market-item')).toHaveCount(12)
  await expect(strip.getByRole('button', { name: '다음 지표', exact: true })).toHaveCount(0)
  const rail = strip.locator('.market-rail')
  expect(await rail.evaluate((el) => getComputedStyle(el).scrollbarWidth)).toBe('none')
  const overflows = await rail.evaluate((el) => el.scrollWidth > el.clientWidth)
  if (overflows) {
    await rail.hover()
    const pageScroll = await page.evaluate(() => window.scrollY)
    await page.mouse.wheel(0, 320)
    await expect.poll(() => rail.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0)
    expect(await page.evaluate(() => window.scrollY)).toBe(pageScroll)
    await page.mouse.wheel(0, -320)
    await expect.poll(() => rail.evaluate((el) => el.scrollLeft)).toBe(0)
  }
  await page
    .getByTestId('favorite-shi')
    .getByRole('link', { name: '삼성중공업', exact: false })
    .first()
    .click()
  await expect(page.getByRole('heading', { name: '삼성중공업', exact: true })).toBeVisible()
})

test('관심종목은 사용자별로 분리되고 새로고침 후에도 빈 목록까지 유지한다', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/home$/)
  await expect(page.getByTestId('favorite-lnf')).toBeVisible()
  await page
    .getByRole('navigation', { name: '주 메뉴' })
    .getByRole('link', { name: '기업 목록', exact: true })
    .click()
  await page.getByRole('button', { name: '삼성중공업 관심종목 추가', exact: true }).click()
  await expect(
    page.getByRole('button', { name: '삼성중공업 관심종목 해제', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('link', { name: '홈', exact: true }).click()
  await expect(page.getByTestId('favorite-lnf')).toBeVisible()
  await expect(page.getByTestId('favorite-shi')).toBeVisible()
  await page.getByLabel('데모 사용자 전환', { exact: true }).selectOption('shipbuilding-ra')
  await expect(page.getByTestId('favorite-lnf')).toHaveCount(0)
  await expect(page.getByTestId('favorite-shi')).toBeVisible()
  await page.getByRole('button', { name: '삼성중공업 관심종목 해제', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '관심종목을 추가해 보세요', exact: true }),
  ).toBeVisible()
  await page.getByLabel('데모 사용자 전환', { exact: true }).selectOption('battery-ra')
  await expect(page.getByTestId('favorite-lnf')).toBeVisible()
  await expect(page.getByTestId('favorite-shi')).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: '이지원님의 리서치 홈' })).toBeVisible()
  await expect(page.getByTestId('favorite-shi')).toBeVisible()
  await page.getByLabel('데모 사용자 전환', { exact: true }).selectOption('shipbuilding-ra')
  await expect(
    page.getByRole('heading', { name: '관심종목을 추가해 보세요', exact: true }),
  ).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: '김도윤님의 리서치 홈' })).toBeVisible()
  await expect(
    page.getByRole('heading', { name: '관심종목을 추가해 보세요', exact: true }),
  ).toBeVisible()
})

test('홈 업데이트는 관심종목 배지로만 표시하고 열람한 항목만 숨긴다', async ({ page }) => {
  await page.goto('/home')
  const favorite = page.getByTestId('favorite-lnf')
  await expect(page.getByRole('heading', { name: '관심종목 업데이트', exact: true })).toHaveCount(0)
  await expect(favorite.getByRole('link', { name: '공시 1', exact: true })).toBeVisible()
  await expect(favorite.getByRole('link', { name: 'AI 보고서 1', exact: true })).toBeVisible()
  await favorite.getByRole('link', { name: '공시 1', exact: true }).click()
  await expect(page).toHaveURL(/tab=filings/)
  await page.getByRole('button', { name: '[기재정정] 단일판매·공급계약체결', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: '원문 닫기', exact: true }).click()
  await page.getByRole('link', { name: '홈', exact: true }).click()
  await expect(favorite.getByRole('link', { name: /^공시/ })).toHaveCount(0)
  await expect(favorite.getByRole('link', { name: 'AI 보고서 1', exact: true })).toBeVisible()
  await favorite.getByRole('link', { name: 'AI 보고서 1', exact: true }).click()
  await expect(page).toHaveURL(/tab=reports/)
  await page.locator('.document-section .document-title').first().click()
  await expect(page.locator('.report-summary')).toBeVisible()
  await page.getByRole('link', { name: '홈', exact: true }).click()
  await expect(favorite.locator('.watchlist-updates')).toHaveCount(0)
  await expect(favorite.getByRole('link', { name: /AI 보고서/ })).toHaveCount(0)
})

test('코스피 샘플 기업을 12개 표시하고 새 기업의 빈 자료와 관심종목을 연결한다', async ({
  page,
}) => {
  await page.goto('/companies')
  await expect(page.locator('.company-row')).toHaveCount(12)
  const directory = page.getByRole('table', { name: '기업 목록 시세 예시' })
  for (const name of ['현재가', '등락률', '거래대금', '시가총액', '업데이트', '산업군']) {
    await expect(directory.getByRole('columnheader', { name, exact: true })).toBeVisible()
  }
  const heights = await page
    .locator('.company-row')
    .evaluateAll((rows) => rows.map((row) => row.getBoundingClientRect().height))
  expect(heights.every((height) => height <= 56)).toBe(true)
  const company = page.getByTestId('company-samsung-electronics')
  await expect(company.getByRole('heading', { name: '삼성전자', exact: true })).toBeVisible()
  await expect(company).toContainText('005930')
  await expect(company).toContainText('78,500원')
  await expect(company).toContainText('+1.42%')
  await expect(company).toContainText('등록된 자료 없음')
  await expect(page.getByTestId('samsung-electronics-filing-badge')).toHaveAccessibleName(
    '삼성전자 공시 업데이트 0건',
  )
  await page.getByRole('button', { name: '삼성전자 관심종목 추가', exact: true }).click()
  await page.getByRole('link', { name: '홈', exact: true }).click()
  const favorite = page.getByTestId('favorite-samsung-electronics')
  await expect(favorite).toBeVisible()
  await expect(favorite.locator('.watchlist-updates')).toHaveCount(0)
  await favorite.getByRole('link', { name: '삼성전자', exact: false }).first().click()
  await expect(page.getByRole('heading', { name: '삼성전자', exact: true })).toBeVisible()
  await expect(
    page.getByRole('heading', { name: '등록된 공시가 없습니다', exact: true }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: '영향 분석 시작', exact: true })).toBeDisabled()
  await page
    .getByRole('navigation', { name: '기업 자료 종류' })
    .getByRole('link', { name: /AI 보고서/ })
    .click()
  await expect(
    page.getByRole('heading', { name: '저장된 보고서가 없습니다', exact: true }),
  ).toBeVisible()
  await page
    .getByRole('navigation', { name: '기업 자료 종류' })
    .getByRole('link', { name: /분석 이력/ })
    .click()
  await expect(
    page.getByRole('heading', { name: '해당하는 분석이 없습니다', exact: true }),
  ).toBeVisible()
})
