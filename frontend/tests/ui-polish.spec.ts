import { expect, test, type Page } from '@playwright/test'

const company = { corp_code: '00398701', company_name: '화면 검증 기업', stock_code: '066970' }
const timestamp = '2026-10-23T06:00:00Z'
const filings = ['[기재정정]단일판매·공급계약체결', '기업설명회 개최 안내'].map((title, index) => ({
  id: `filing-${index}`,
  corp_code: company.corp_code,
  company_name: company.company_name,
  receipt_no: `2026102300000${index}`,
  title,
  filing_type: index ? '신규공시' : '정정공시',
  filed_at: timestamp,
  is_correction: !index,
}))

async function fixtures(page: Page) {
  const state = { writes: 0, deletes: 0, failUpload: false }
  const memo = (id = 'memo') => ({
    id,
    company_name: company.company_name,
    title: id === 'memo' ? '검증 메모' : '추가 메모',
    current_version: 1,
    created_at: timestamp,
    updated_at: timestamp,
  })
  const memos = [memo()]
  const tasks = filings.map((filing, index) => ({
    task_id: `task-${index}`,
    memo_id: 'memo',
    base_memo_version: 1,
    disclosure_receipt_no: filing.receipt_no,
    company_name_snapshot: company.company_name,
    status: 'COMPLETED_WITH_WARNINGS',
    current_stage: 'REPORT_SAVE',
    created_at: timestamp,
    started_at: timestamp,
    completed_at: timestamp,
    updated_at: timestamp,
    has_warnings: true,
    error_stage: null,
    error_code: null,
  }))
  await page.addInitScript(() =>
    sessionStorage.setItem('disclosure-check.token', 'local-ui-polish-fixture'),
  )
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    const method = route.request().method()
    let body: unknown = []
    if (path === '/users/me')
      body = {
        id: 'fixture-user',
        email: 'fixture@example.com',
        name: '화면 검증',
        role: 'ANALYST',
      }
    else if (path === '/favorites') body = [company]
    else if (path === '/filings') body = filings
    else if (/^\/filings\/[^/]+\/versions$/.test(path))
      body = [{ version: 1, created_at: timestamp }]
    else if (/^\/filings\/[^/]+\/versions\/1$/.test(path))
      body = { version: 1, raw_content: '공시에서 확인한 사실입니다.', created_at: timestamp }
    else if (path === '/memos' && method === 'POST') {
      if (state.failUpload) {
        await route.fulfill({ status: 503, json: { detail: '검증용 저장 실패' } })
        return
      }
      state.writes++
      const created = memo('new-' + state.writes)
      memos.unshift(created)
      await route.fulfill({ status: 201, json: created })
      return
    } else if (/^\/memos\/[^/]+$/.test(path) && method === 'DELETE') {
      state.deletes++
      const index = memos.findIndex((m) => m.id === path.split('/').at(-1))
      if (index >= 0) memos.splice(index, 1)
      await route.fulfill({ status: 204 })
      return
    } else if (path === '/memos') body = memos
    else if (/^\/memos\/[^/]+\/versions$/.test(path)) body = [{ version: 1, created_at: timestamp }]
    else if (/^\/memos\/[^/]+\/versions\/1$/.test(path))
      body = { version: 1, content: '확인할 메모 본문입니다.', created_at: timestamp }
    else if (path === '/analyses') body = tasks
    else if (/^\/analyses\/[^/]+\/report$/.test(path)) {
      const taskId = path.split('/')[2]
      body = {
        id: 'report-' + taskId,
        analysis_task_id: taskId,
        generated_at: timestamp,
        saved_at: timestamp,
        content:
          '## 핵심 요약\n\n공시 사실을 확인했습니다.\n\n## 관점별 분석\n\n계약 이행 범위를 확인합니다.',
        report_json: {
          sources: [],
          base: {
            selected: [
              {
                perspective_type: 'INDUSTRY_CONTRACT',
                selection_reason: '계약 이행 범위를 확인합니다.',
              },
            ],
            not_selected: [{ perspective_type: 'FINANCE', reason: '금액 영향 근거가 없습니다.' }],
          },
        },
      }
    } else if (path === '/disclosures/companies')
      body = { items: [company], total_count: 1, has_more: false }
    else if (path === '/disclosures')
      body = {
        items: filings.map((f) => ({ ...f, report_name: f.title })),
        total_count: 2,
        has_more: false,
      }
    else if (path === '/market/indices')
      body = { items: [], fetched_at: timestamp, source: 'fixture' }
    else if (path === '/market/stocks')
      body = {
        items: {
          '066970': {
            price: 85000,
            changePercent: -1,
            tradingValue: 3e10,
            marketCap: 3e12,
            openPrice: 86000,
            highPrice: 87000,
            lowPrice: 84000,
            volume: 1000,
          },
        },
      }
    else if (path === '/market/sectors')
      body = { items: { '066970': { sector: '전기제품', status: 'available' } } }
    else if (path.startsWith('/market/history/'))
      body = {
        series: [80000, 87000, 85000],
        previous_close: 86000,
        start_date: '20260923',
        end_date: '20261023',
      }
    await route.fulfill({ json: body })
  })
  return state
}

test('관심종목도 기업 목록과 같은 업데이트 열을 사용합니다', async ({ page }, testInfo) => {
  if (testInfo.project.name === 'desktop') await page.setViewportSize({ width: 1059, height: 849 })
  await fixtures(page)
  await page.goto('/home')
  const row = page.locator('.watchlist-row').first()
  await expect(row.locator('.directory-update')).toHaveCount(3)
  await expect(row.locator('th .watchlist-updates')).toHaveCount(0)
  await expect(row.locator('.directory-last-update')).toContainText('최근 업데이트')
  const headers = await page.locator('.watchlist-table thead th').allTextContents()
  for (const header of await page.locator('.watchlist-table thead th').all())
    await expect(header).toHaveCSS('text-align', 'center')
  await expect(row.locator('.company-updates-cell')).toHaveCSS('text-align', 'center')
  await expect(row.locator('.company-sector-cell')).toHaveCSS('text-align', 'center')
  const tableScroll = page.getByRole('region', { name: '관심종목 시세 목록' })
  if (testInfo.project.name === 'desktop') {
    for (const width of [1000, 1059, 1210, 1440]) {
      await page.setViewportSize({ width, height: 849 })
      expect(await tableScroll.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
      await expect(row.locator('td:last-child .favorite-button')).toBeInViewport()
      for (const link of await row.locator('.directory-update').all())
        await expect(link).toBeInViewport()
    }
    await page.setViewportSize({ width: 1210, height: 849 })
  }
  await tableScroll.evaluate((el) => {
    el.scrollLeft = el.scrollWidth
  })
  await expect(row.locator('td:last-child .favorite-button')).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await tableScroll.evaluate((el) => {
    el.scrollLeft = 0
  })
  await page.screenshot({ path: testInfo.outputPath('watchlist.png'), fullPage: true })
  await page.goto('/companies')
  await expect(page.locator('.company-row')).toHaveCount(1)
  expect(await page.locator('.watchlist-table thead th').allTextContents()).toEqual(headers)
  if (testInfo.project.name === 'desktop')
    expect(
      await page
        .getByRole('region', { name: '기업 시세 목록' })
        .evaluate((el) => el.scrollWidth <= el.clientWidth),
    ).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('보고서의 공시 제목과 열기 링크를 유지하고 선택 상태를 구분합니다', async ({
  page,
}, testInfo) => {
  await fixtures(page)
  await page.goto(`/companies/${company.corp_code}?tab=reports`)
  const rows = page.locator('.analysis-row')
  await expect(rows).toHaveCount(2)
  await expect(rows.locator('.document-title')).toHaveText(filings.map((f) => f.title))
  await expect(rows.locator('.status-pill')).toHaveCount(0)
  expect(await rows.allTextContents()).not.toContain('보고서 보기')
  await rows
    .first()
    .getByRole('link', { name: /보고서 열기$/ })
    .click()
  await expect(page).toHaveURL(/\/analyses\/task-0$/)
  const selected = page.locator('.analysis-perspectives .selected')
  const unselected = page.locator('.analysis-perspectives .unselected')
  await expect(selected.locator('.perspective-selection')).toHaveText('선택')
  await expect(unselected.locator('.perspective-selection')).toHaveText('미선택')
  for (const theme of ['light', 'dark']) {
    await page.evaluate((value) => (document.documentElement.dataset.theme = value), theme)
    const colors = await Promise.all(
      [selected, unselected].map((card) =>
        card.evaluate((el) => getComputedStyle(el).backgroundColor),
      ),
    )
    expect(colors[0]).not.toBe(colors[1])
    await expect(selected.locator('svg')).toBeVisible()
  }
  await page.screenshot({ path: testInfo.outputPath('selection-dark.png'), fullPage: true })
})

test('메모는 제목으로 열고 더 보기 메뉴에서 삭제를 취소하거나 실행합니다', async ({ page }) => {
  const state = await fixtures(page)
  await page.goto(`/companies/${company.corp_code}?tab=memos`)
  await expect(page.getByText('본문,버전 확인', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('menuitem', { name: '삭제' })).toHaveCount(0)
  await page.getByRole('button', { name: '검증 메모', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('확인할 메모 본문입니다.')
  await page.getByRole('button', { name: '원문 닫기', exact: true }).click()
  const trigger = page.getByRole('button', { name: '검증 메모 더 보기', exact: true })
  await trigger.click()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await trigger.press('ArrowDown')
  await expect(page.getByRole('menuitem', { name: '삭제', exact: true })).toBeFocused()
  page.once('dialog', (dialog) => dialog.dismiss())
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '검증 메모', exact: true })).toBeVisible()
  expect(state.deletes).toBe(0)
  await trigger.click()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('menuitem', { name: '삭제', exact: true }).click()
  await expect(page.getByRole('button', { name: '검증 메모', exact: true })).toHaveCount(0)
  expect(state.deletes).toBe(1)
})

test('작성·파일 저장이 끝나면 창을 닫고 실패하면 입력을 보존합니다', async ({ page }) => {
  const state = await fixtures(page)
  await page.goto(`/companies/${company.corp_code}?tab=memos`)
  const open = page.getByRole('button', { name: '메모 추가', exact: true })
  await open.click()
  const dialog = page.getByRole('dialog', { name: '메모 추가', exact: true })
  await dialog.getByRole('tab', { name: '작성', exact: true }).click()
  await dialog.getByLabel('메모 내용', { exact: true }).fill('새로운 검토 관점입니다.')
  await dialog.getByRole('button', { name: '저장', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  expect(state.writes).toBe(1)
  await open.click()
  await dialog.getByRole('tab', { name: '파일 업로드', exact: true }).click()
  await dialog.getByLabel('메모 파일').setInputFiles({
    name: 'fixture.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('파일 메모 내용입니다.'),
  })
  await dialog.getByRole('button', { name: '메모 업로드', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  expect(state.writes).toBe(2)
  state.failUpload = true
  await open.click()
  await dialog.getByRole('tab', { name: '작성', exact: true }).click()
  await dialog.getByLabel('메모 내용', { exact: true }).fill('실패해도 보존합니다.')
  await dialog.getByRole('button', { name: '저장', exact: true }).click()
  await expect(dialog.getByRole('alert')).toBeVisible()
  await expect(dialog.getByLabel('메모 내용', { exact: true })).toHaveValue('실패해도 보존합니다.')
  expect(state.writes).toBe(2)
})

test('설정 창은 이전 최대 높이의 3분의 2로 줄이고 하단 기능까지 스크롤합니다', async ({
  page,
}, testInfo) => {
  await fixtures(page)
  await page.goto(`/companies/${company.corp_code}?tab=memos`)
  await page.getByRole('button', { name: '화면 검증', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '설정', exact: true })
  const box = (await dialog.boundingBox())!
  expect(box.height).toBeLessThanOrEqual(((page.viewportSize()!.height - 40) * 2) / 3 + 2)
  expect(box.x).toBeGreaterThanOrEqual(15)
  await page.screenshot({ path: testInfo.outputPath('settings.png') })
  await dialog.getByRole('button', { name: '로그아웃', exact: true }).scrollIntoViewIfNeeded()
  await expect(dialog.getByRole('button', { name: '로그아웃', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
})
