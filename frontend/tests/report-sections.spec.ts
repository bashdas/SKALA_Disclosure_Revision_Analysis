import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

// API의 본문과 sources 순서를 고정해 근거 번호가 잘못 연결되는지도 확인합니다.
const timestamp = '2026-10-22T03:00:00Z'
const sources = Array.from({ length: 6 }, (_, index) => ({
  document_id: `자료-${index + 1}`,
  location: `${index + 1}쪽`,
  quote: `${index + 1}번 자료의 확인된 인용문입니다. `.repeat(20),
  published_at: timestamp,
  ...(index === 0 ? { url: 'https://example.com/original' } : {}),
}))
const task = {
  task_id: 'report-task',
  memo_id: 'memo',
  base_memo_version: 1,
  disclosure_receipt_no: '20261022000001',
  company_name_snapshot: '검증 기업',
  status: 'COMPLETED',
  current_stage: 'REPORT_SAVE',
  created_at: timestamp,
  started_at: timestamp,
  completed_at: timestamp,
  updated_at: timestamp,
  has_warnings: false,
  error_stage: null,
  error_code: null,
}
const beforeText = '계약금액은 기존 일정에 반영됩니다.'
const afterText = '변경된 계약금액을 반영해 일정을 재검토합니다.'
const reason = '계약 변경에 따라 매출 인식 가정이 달라집니다.'
const selectionReason = '계약 변경의 재무 영향을 확인합니다.'
const result = '매출 인식 시점에 대한 검토 결과입니다.'
const report = {
  id: 'report',
  analysis_task_id: task.task_id,
  generated_at: timestamp,
  saved_at: timestamp,
  no_additional_analysis_reason: null,
  content: `# 공시 영향 분석 보고서

## 추가 분석을 선택한 이유

| 관점 | 선택 이유 | 처리 결과 |
| --- | --- | --- |
| 재무와 실적 | ${selectionReason} | 작성 완료 |

## 핵심 요약

- 첫 번째 주장 [근거6] [근거 1]
- 반복 인용 [근거 1]
- 없는 근거 [근거 99]

## 확인된 공시 내용

| 항목 | 정정 전 | 정정 후 | 근거 |
| --- | --- | --- | --- |
| 계약 금액 | 100억원 | 200억원 | [근거6] |

## 메모 영향

${reason}

## 메모 수정 제안

기존: ${beforeText}

수정: ${afterText} [근거 1]

## 관점별 분석

### 재무와 실적

${result}

## 향후 영향과 조건

계약 이행 여부를 추가로 확인합니다.

## 확인 범위와 남은 질문

확인되지 않은 수치는 추정하지 않았습니다.

## 출처와 원문 인용

### 근거 1

출처: [공시 원문](https://example.com/original)

> 원문 인용 전체를 보존합니다.
`,
  report_json: {
    sources,
    summary_claims: [{ text: '첫 번째 주장' }],
    base: {
      proposals: [
        {
          claim_id: 'claim',
          impact_type: 'FACT_UPDATE',
          before_text: beforeText,
          after_text: afterText,
          reason,
          evidence: [sources[0]],
        },
      ],
    },
    corrections: [{ label: '계약 금액', before: '100억원', after: '200억원' }],
    warnings: [],
  },
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    sessionStorage.setItem('disclosure-check.token', 'local-ui-fixture'),
  )
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '')
    let body: unknown = []
    if (path === '/users/me')
      body = {
        id: 'user',
        organization_id: 'org',
        email: 'ui@example.com',
        name: '화면 검증',
        role: 'ANALYST',
      }
    if (path === '/analyses') body = [task]
    if (path === '/memos')
      body = [
        {
          id: 'memo',
          title: '기준 메모',
          company_name: '검증 기업',
          current_version: 1,
          created_at: timestamp,
          updated_at: timestamp,
        },
      ]
    if (path === '/memos/memo/versions') body = [{ version: 1, created_at: timestamp }]
    if (path === '/memos/memo/versions/1')
      body = { version: 1, created_at: timestamp, content: beforeText + '\n\n메모 원문 문맥' }
    if (path === '/analyses/report-task/report') body = report
    if (path === '/analyses/report-task/perspectives')
      body = [
        {
          perspective_type: 'FINANCE',
          selection_reason: selectionReason,
          question: '재무 영향',
          status: 'COMPLETED',
          result_json: { findings: result },
          failure_code: null,
        },
      ]
    await route.fulfill({ json: body })
  })
})

test('하나의 보고서 안에서 관점과 메모수정 제안을 중복 없이 읽고 접고 펼칩니다', async ({
  page,
}) => {
  await page.goto('/analyses/report-task')
  const reportView = page.locator('.unified-report')
  await expect(page.locator('.progress-section')).toHaveCount(0)
  await expect(reportView.getByRole('heading', { name: '선택한 분석 관점' })).toBeVisible()
  await expect(reportView.locator('.analysis-perspectives')).toContainText(selectionReason)
  await expect(reportView.locator('.analysis-perspectives')).not.toContainText(result)
  for (const text of [selectionReason, result, beforeText, afterText, reason])
    await expect(reportView.getByText(text, { exact: true })).toHaveCount(1)
  await expect(
    reportView.getByRole('heading', { name: '메모수정 제안 1', exact: true }),
  ).toHaveCount(1)
  await expect(reportView.getByRole('heading', { name: '메모 영향', exact: true })).toHaveCount(0)
  await expect(
    reportView.getByRole('heading', { name: '추가 분석을 선택한 이유', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.locator(
      '.source-list, .perspectives-section, .findings-section, .report-summary, .report-body',
    ),
  ).toHaveCount(0)
  await expect(reportView.locator('.unified-report-content > :last-child')).toHaveClass(
    /report-perspectives/,
  )
  const chip = reportView.locator('.evidence-chips button').first()
  await expect(chip).toHaveText('근거 1')
  await chip.click()
  const sourceDrawer = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: '자료-1' }) })
  await expect(sourceDrawer).toContainText(sources[0]!.quote)
  await sourceDrawer.getByRole('button', { name: '원문 닫기' }).click()
  const sourceToggle = reportView.getByRole('button', { name: '출처와 원문 인용', exact: true })
  await expect(sourceToggle).toHaveAttribute('aria-expanded', 'false')
  await expect(reportView.getByText('원문 인용 전체를 보존합니다.', { exact: true })).toHaveCount(0)
  await sourceToggle.focus()
  await page.keyboard.press('Enter')
  await expect(sourceToggle).toHaveAttribute('aria-expanded', 'true')
  await expect(reportView.getByText('원문 인용 전체를 보존합니다.', { exact: true })).toBeVisible()
  await expect(reportView.getByRole('link', { name: '공시 원문', exact: true })).toHaveAttribute(
    'href',
    'https://example.com/original',
  )
  await sourceToggle.click()
  const toggle = reportView.getByRole('button', { name: '검토 보고서', exact: true })
  await expect(toggle).toHaveCount(1)
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await reportView.getByRole('button', { name: '원문 문맥 확인' }).click()
  const memo = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: '기준 메모', exact: true }) })
  await expect(memo).toContainText('메모 원문 문맥')
  await memo.getByRole('button', { name: '원문 닫기' }).click()
  await page.getByRole('button', { name: '검토 보고서', exact: true }).focus()
  await page.evaluate(() => window.scrollTo(0, 0))
  for (const theme of ['light', 'dark']) {
    await page.evaluate((theme) => (document.documentElement.dataset.theme = theme), theme)
    await expect(reportView).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    if (process.env.E2E_ARTIFACT_DIR)
      await page.screenshot({
        path: `${process.env.E2E_ARTIFACT_DIR}/통합보고서-${page.viewportSize()!.width}-${theme}.png`,
        fullPage: true,
      })
  }
})

test('근거 미리보기, 키보드, 터치와 상세 패널을 정확한 자료에 연결합니다', async ({
  page,
  isMobile,
}) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/analyses/report-task')
  const first = page.getByRole('button', { name: '근거 1 상세 보기', exact: true }).first()
  const sixth = page.getByRole('button', { name: '근거 6 상세 보기', exact: true }).first()
  await expect(first).toBeVisible()
  await expect(page.locator('.evidence-reference')).toHaveCount(4)
  await expect(page.getByRole('button', { name: '근거 99 상세 보기' })).toHaveCount(0)
  if (!isMobile) {
    for (const theme of ['light', 'dark']) {
      await page.evaluate((theme) => (document.documentElement.dataset.theme = theme), theme)
      await sixth.hover()
      const preview = page.getByRole('tooltip')
      await expect(preview).toContainText('6번 자료의 확인된 인용문')
      await expect(sixth).toHaveAttribute(
        'aria-describedby',
        (await preview.getAttribute('id')) as string,
      )
      const box = await preview.boundingBox()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
      if (process.env.E2E_ARTIFACT_DIR)
        await page.screenshot({
          path: `${process.env.E2E_ARTIFACT_DIR}/보고서-미리보기-${theme}.png`,
        })
      await page.keyboard.press('Escape')
      await expect(preview).toHaveCount(0)
      await page.mouse.move(0, 0)
    }
    await first.focus()
    await expect(page.getByRole('tooltip')).toContainText('1번 자료의 확인된 인용문')
    await expect(first).toBeFocused()
    await page.keyboard.press('Enter')
  } else {
    await first.tap()
  }
  const drawer = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: '자료-1' }) })
  await expect(drawer).toBeVisible()
  await expect(drawer).toContainText(sources[0]!.quote)
  const original = drawer.getByRole('link', { name: '외부 원문 열기' })
  await expect(original).toHaveAttribute('href', 'https://example.com/original')
  await expect(original).toHaveAttribute('target', '_blank')
  await expect(page.getByRole('tooltip')).toHaveCount(0)
  if (process.env.E2E_ARTIFACT_DIR)
    await page.screenshot({
      path: `${process.env.E2E_ARTIFACT_DIR}/보고서-근거상세-${page.viewportSize()!.width}.png`,
    })
  await drawer.getByRole('button', { name: '원문 닫기' }).click()
  if (!isMobile) await expect(first).toBeFocused()
  await sixth.click()
  const noLink = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: '자료-6' }) })
  await expect(noLink).toContainText(sources[5]!.quote)
  await expect(noLink.getByRole('link', { name: '외부 원문 열기' })).toHaveCount(0)
  expect(errors).toEqual([])
})

test('통합 헤더의 MD·PDF 다운로드가 저장된 원본을 사용합니다', async ({ page }) => {
  await page.route('**/api/v1/analyses/report-task/report.md', (route) =>
    route.fulfill({
      body: report.content,
      contentType: 'text/markdown',
      headers: { 'Content-Disposition': 'attachment; filename=report.md' },
    }),
  )
  await page.route('**/api/v1/analyses/report-task/report.pdf', (route) =>
    route.fulfill({
      body: '%PDF-1.4\nfixture-original',
      contentType: 'application/pdf',
      headers: { 'Content-Disposition': 'attachment; filename=report.pdf' },
    }),
  )
  await page.goto('/analyses/report-task')
  for (const [name, extension] of [
    ['MD 다운로드', 'md'],
    ['PDF 다운로드', 'pdf'],
  ]) {
    const response = page.waitForResponse((r) => r.url().endsWith('/report.' + extension))
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: name!, exact: true }).click()
    expect((await response).status()).toBe(200)
    const file = await download
    expect(file.suggestedFilename()).toBe('report-report-task.' + extension)
    expect(await readFile((await file.path())!, 'utf8')).toBe(
      extension === 'md' ? report.content : '%PDF-1.4\nfixture-original',
    )
  }
})
