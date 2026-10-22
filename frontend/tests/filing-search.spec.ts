import { test, expect } from '@playwright/test'

test('공시번호를 서버에 전달하고 뒤쪽 페이지 결과와 기존 공시명 검색을 표시합니다', async ({
  page,
}) => {
  const receipt = '20251014800059'
  const company = { corp_code: '00398701', company_name: '검색 검증 기업', stock_code: '066970' }
  const filing = {
    receipt_no: receipt,
    corp_code: company.corp_code,
    company_name: company.company_name,
    report_name: '풍문또는보도에대한해명',
    filed_at: '2025-10-14',
    is_correction: false,
    has_corrections: false,
  }
  const receiptPages: number[] = []
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() =>
    sessionStorage.setItem('disclosure-check.token', 'receipt-search-ui-fixture'),
  )
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace('/api/v1', '')
    let body: unknown = []
    if (path === '/users/me')
      body = { id: 'search-user', organization_id: 'org', name: '화면 검증', role: 'ANALYST' }
    if (path === '/favorites') body = [company]
    if (path === '/disclosures/companies') body = { items: [company], has_more: false }
    if (path.startsWith('/market/')) body = { items: {} }
    if (path === '/disclosures') {
      const query = url.searchParams.get('query')
      const currentPage = Number(url.searchParams.get('page'))
      if (query === receipt) {
        receiptPages.push(currentPage)
        body =
          currentPage === 1
            ? { items: [], total_count: null, has_more: true, next_page: 2 }
            : { items: [filing], total_count: 1, has_more: false }
      } else {
        const matches = query === '풍문' ? [filing] : []
        body = { items: matches, total_count: matches.length, has_more: false }
      }
    }
    await route.fulfill({ json: body })
  })
  await page.goto('/companies/00398701?tab=filings')
  const search = page.getByPlaceholder('공시명 또는 공시번호로 검색')
  await search.fill(receipt)
  await expect(page.locator('.document-row')).toHaveCount(1)
  await expect(page.locator('.document-row')).toContainText(receipt)
  expect(receiptPages).toEqual([1, 2])
  await search.fill('풍문')
  await expect(page.locator('.document-row')).toHaveCount(1)
  await expect(page.locator('.document-row')).toContainText('풍문또는보도에대한해명')
  await search.fill('없는공시')
  await expect(page.locator('.document-row')).toHaveCount(0)
  await expect(page.locator('.document-section .empty-state')).toBeVisible()
  expect(errors).toEqual([])
})
