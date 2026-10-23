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

[근거6]

## 향후 영향과 조건

- 조건: 계약 이행 여부가 확인되는 경우입니다. 예상 영향: 회수 일정을 재검토합니다. [근거6]

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
      selected: [{ perspective_type: 'FINANCE', selection_reason: selectionReason }],
      not_selected: [
        {
          perspective_type: 'INDUSTRY_CONTRACT',
          reason: '계약 조건의 추가 변경은 확인되지 않았습니다.',
        },
        { perspective_type: 'FX_HEDGE', reason: '환율과 헤지 관련 변경 근거가 없습니다.' },
      ],
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

test('보고서는 항상 펼치고 관점 판단과 분석 결과를 중복 없이 표시하며 출처 토글을 유지합니다', async ({
  page,
}) => {
  await page.goto('/analyses/report-task')
  const reportView = page.locator('.unified-report')
  await expect(page.locator('.progress-section')).toHaveCount(0)
  const title = reportView.getByRole('heading', { name: '공시 영향 분석 보고서', exact: true })
  await expect(title).toHaveCount(1)
  await expect(title.locator('.report-section-title')).toHaveCSS('font-size', '26px')
  await expect(reportView.locator('.markdown-body h1')).toHaveCount(0)
  expect(
    (await reportView.locator('.unified-report-content h2').allTextContents()).map((text) =>
      text.trim(),
    ),
  ).toEqual([
    '핵심 요약',
    '새롭게 고찰할 관점',
    '관점별 분석',
    '확인된 공시 내용',
    '확인 범위와 남은 질문',
    '출처와 원문 인용',
    '조회한 과거 공시와 비교 범위',
  ])
  await expect(reportView.getByRole('heading', { name: '선택한 분석 관점' })).toHaveCount(0)
  const analysis = reportView.locator('.report-analysis')
  await expect(analysis).toHaveCount(1)
  await expect(analysis.getByRole('heading', { name: '관점별 분석', exact: true })).toHaveCSS('font-size', '21px')
  await expect(reportView.getByRole('button', { name: '관점별 분석', exact: true })).toHaveCount(0)
  await expect(reportView.getByRole('button', { name: '관점 선택과 이유', exact: true })).toHaveCount(0)
  await expect(reportView.getByRole('heading', { name: '관점 선택과 이유', exact: true })).toHaveCount(0)
  const sourceToggle = reportView.getByRole('button', { name: '출처와 원문 인용', exact: true })
  await expect(sourceToggle).toHaveAttribute('aria-expanded', 'false')
  await expect(sourceToggle).toHaveCSS('font-size', '17px')
  for (const kind of ['facts', 'limits']) {
    const section = reportView.locator(`.report-${kind}`)
    const toggle = section.locator('.report-fold-trigger')
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await expect(toggle).toHaveCSS('font-size', '17px')
    await expect(section.locator('.markdown-body')).toHaveCount(0)
    await toggle.focus()
    await page.keyboard.press('Enter')
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(section.locator('.markdown-body')).toBeVisible()
    await expect(section.locator('h2')).toHaveCount(1)
    if (kind === 'facts') {
      await expect(section.locator('table')).toContainText('200')
      await section.getByRole('button', { name: '근거 6 상세 보기' }).click()
      await expect(page.getByRole('dialog')).toContainText(sources[5]!.quote)
      await page.getByRole('button', { name: '원문 닫기' }).click()
    }
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  }
  await expect(analysis.getByText(result, { exact: true })).toBeVisible()
  const decisions = analysis.locator('.analysis-perspectives')
  await expect(decisions).toHaveCount(1)
  await expect(decisions.locator('.perspective-card')).toHaveCount(4)
  const positions = await decisions.locator('.perspective-card').evaluateAll((cards) =>
    cards.map((card) => ({ top: card.getBoundingClientRect().top, left: card.getBoundingClientRect().left })),
  )
  if (page.viewportSize()!.width > 900) {
    expect(new Set(positions.map((p) => p.top)).size).toBe(1)
    expect(new Set(positions.map((p) => p.left)).size).toBe(4)
  }
  await expect(decisions.locator('.tag')).toHaveText(['미선택', '선택', '미선택', '판단 기록 없음'])
  await expect(reportView.getByText(selectionReason, { exact: true })).toHaveCount(1)
  for (const item of report.report_json.base.not_selected)
    await expect(decisions.getByText(item.reason, { exact: true })).toHaveCount(1)
  await expect(decisions.getByText(result, { exact: true })).toHaveCount(0)
  expect(await decisions.evaluate((el) => el.nextElementSibling?.classList.contains('perspective-analysis-body'))).toBe(true)
  if (process.env.E2E_ARTIFACT_DIR) {
    await analysis.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `${process.env.E2E_ARTIFACT_DIR}/관점통합-${page.viewportSize()!.width}.png`,
      fullPage: false,
    })
  }
  await expect(reportView.getByText(result, { exact: true })).toHaveCount(1)
  for (const text of [beforeText, afterText, reason])
    await expect(reportView.getByText(text, { exact: true })).toHaveCount(0)
  await analysis.getByRole('button', { name: '근거 6 상세 보기' }).click()
  await expect(page.getByRole('dialog')).toContainText(sources[5]!.quote)
  await page.getByRole('button', { name: '원문 닫기' }).click()
  await expect(
    reportView.getByRole('heading', { name: '메모수정 제안 1', exact: true }),
  ).toHaveCount(0)
  await expect(reportView.getByRole('heading', { name: '메모 영향', exact: true })).toHaveCount(0)
  await expect(
    reportView.getByRole('heading', { name: '추가 분석을 선택한 이유', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.locator(
      '.source-list, .perspectives-section, .findings-section, .report-summary, .report-body',
    ),
  ).toHaveCount(0)
  const scenario = reportView
    .locator('.markdown-body li')
    .filter({ hasText: '계약 이행 여부가 확인되는 경우입니다.' })
  await expect(scenario).toHaveCount(0)
  const chip = reportView.getByRole('button', { name: '근거 1 상세 보기', exact: true }).first()
  await chip.click()
  const sourceDrawer = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: '자료-1' }) })
  await expect(sourceDrawer).toContainText(sources[0]!.quote)
  await sourceDrawer.getByRole('button', { name: '원문 닫기' }).click()
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
  await expect(
    reportView.getByRole('button', { name: '공시 영향 분석 보고서', exact: true }),
  ).toHaveCount(0)
  await expect(
    reportView.getByRole('heading', { name: '공시 영향 분석 보고서', exact: true }),
  ).toBeVisible()
  await expect(reportView.getByRole('heading', { name: '핵심 요약', exact: true })).toBeVisible()
  await expect(analysis.getByText(result, { exact: true })).toBeVisible()
  await page.locator('.report-context button').click()
  const memo = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('heading', { name: '기준 메모', exact: true }) })
  await expect(memo).toContainText('메모 원문 문맥')
  await memo.getByRole('button', { name: '원문 닫기' }).click()
  await page.getByRole('button', { name: 'MD 다운로드', exact: true }).focus()
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

for (const hasResult of [true, false]) {
  test(`Markdown 분석이 없는 보고서도 ${hasResult ? '구조화 결과를' : '판단 기록 누락을'} 상시 표시합니다`, async ({ page }) => {
    await page.route('**/api/v1/analyses/report-task/report', (route) => route.fulfill({ json: {
      ...report,
      content: '## 핵심 요약\n\n요약\n\n## 확인된 공시 내용\n\n공시 사실\n\n## 확인 범위와 남은 질문\n\n추가 확인이 필요합니다.',
      report_json: { ...report.report_json,
        base: { ...report.report_json.base, selected: [], not_selected: [], proposals: [] } },
    } }))
    await page.route('**/api/v1/analyses/report-task/perspectives', (route) => route.fulfill({ json: hasResult ? [{
      perspective_type: 'FINANCE', selection_reason: selectionReason, question: '재무 영향은 무엇입니까?',
      status: 'COMPLETED', result_json: { findings: result }, failure_code: null,
    }] : [] }))
    await page.goto('/analyses/report-task')
    const analysis = page.locator('.report-analysis')
    await expect(analysis).toHaveCount(1)
    await expect(analysis.locator('.perspective-card')).toHaveCount(4)
    await expect(analysis.locator('.report-fold-trigger')).toHaveCount(0)
    if (hasResult) await expect(analysis.getByText(result, { exact: true })).toBeVisible()
    else {
      await expect(analysis.locator('.perspective-analysis-body')).toHaveCount(0)
      await expect(analysis.locator('.tag')).toHaveText(Array(4).fill('판단 기록 없음'))
    }
    expect((await page.locator('.unified-report-content > :not([data-testid="memo-review-decision"]) h2').allTextContents()).map((text) => text.trim()))
      .toEqual(['핵심 요약', '새롭게 고찰할 관점', '관점별 분석', '확인된 공시 내용', '확인 범위와 남은 질문', '출처와 원문 인용', '조회한 과거 공시와 비교 범위'])
    for (const [kind, content] of [['facts', '공시 사실'], ['limits', '추가 확인이 필요합니다.']]) {
      const section = page.locator(`.report-${kind}`)
      await expect(section.locator('.report-fold-trigger')).toHaveAttribute('aria-expanded', 'false')
      await expect(section.getByText(content, { exact: true })).toHaveCount(0)
      await section.locator('.report-fold-trigger').click()
      await expect(section.getByText(content, { exact: true })).toBeVisible()
    }
  })
}

test('과거 공시 조회 범위는 마지막의 닫힌 토글로 표시하고 출처와 근거를 유지합니다', async ({ page }) => {
  await page.route('**/api/v1/analyses/report-task/report', (route) => route.fulfill({ json: {
    ...report,
    content: report.content.replace('## 확인된 공시 내용',
      '## 조회한 과거 공시와 비교 범위\n\n### 최초 공시 20201012800214\n\n[DART 연결 목록](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220518800001) [근거 1]\n\n원문 확보와 비교 완료를 구분합니다.\n\n## 확인된 공시 내용'),
  } }))
  await page.goto('/analyses/report-task')
  const history = page.locator('.report-history')
  const toggle = history.getByRole('button', { name: '조회한 과거 공시와 비교 범위', exact: true })
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(toggle).toHaveCSS('font-size', '17px')
  expect(await history.evaluate((el) => el.parentElement?.lastElementChild === el)).toBe(true)
  await expect(history.getByRole('heading', { name: '최초 공시 20201012800214' })).toHaveCount(0)
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(history.getByRole('heading', { name: '최초 공시 20201012800214' })).toBeVisible()
  await expect(history.getByRole('link', { name: 'DART 연결 목록' })).toHaveAttribute('href',
    'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220518800001')
  await expect(history.getByRole('heading', { name: '조회한 과거 공시와 비교 범위', exact: true })).toHaveCount(1)
  await history.getByRole('button', { name: '근거 1 상세 보기' }).click()
  await expect(page.getByRole('dialog')).toContainText(sources[0]!.quote)
  await page.getByRole('button', { name: '원문 닫기' }).click()
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await expect(history.locator('.markdown-body')).toHaveCount(0)
})

for (const kind of ['신규', '정정', '이전 자료 누락']) {
  test(`${kind} 보고서도 같은 양식과 기본 접힘을 사용합니다`, async ({ page }) => {
    const empty = kind === '이전 자료 누락'
    const content = empty ? '' : `## 4. 출처 및 근거\n\n[원문][source]\n\n## 분석한계\n\n조건 미확인\n\n## ${kind === '정정' ? '정정 전후 비교' : '공시 내용'}\n\n${kind === '정정' ? '| 항목 | 전 | 후 |\n| --- | --- | --- |\n| 물량 | 3척 | 2척 |' : '신규 계약 체결 사실'}\n\n## 심화 분석\n\n분석 원문 [근거 1]\n\n## 요약\n\n요약 원문\n\n[source]: https://example.com/filing`
    await page.route('**/api/v1/analyses/report-task/report', (route) => route.fulfill({ json: {
      ...report, content,
      report_json: empty ? { sources: [], base: {}, warnings: [] } : {
        ...report.report_json,
        base: { ...report.report_json.base, proposals: [], review_points: [{
          perspective_type: 'FINANCE', title: '성장 가정 재검토', memo_view: '기존 성장 가정',
          disclosure_fact: '새로운 계약 조건', reason: '반영 범위 미확인', question: '추정에 반영됐습니까?',
          check_items: ['반영 범위'], evidence: [sources[0]],
        }] },
      },
    } }))
    await page.goto('/analyses/report-task')
    const root = page.locator('.unified-report-content')
    expect((await root.locator('h2').allTextContents()).map((text) => text.trim().replace(/\s*\d+$/, '')))
      .toEqual(['핵심 요약', '새롭게 고찰할 관점', '관점별 분석', '확인된 공시 내용', '확인 범위와 남은 질문', '출처와 원문 인용', '조회한 과거 공시와 비교 범위'])
    for (const title of ['핵심 요약', '새롭게 고찰할 관점', '관점별 분석']) {
      await expect(root.getByRole('heading', { name: new RegExp(`^${title}`) })).toHaveCSS('font-size', '21px')
      await expect(root.getByRole('button', { name: title, exact: true })).toHaveCount(0)
    }
    await expect(root.locator('.perspective-card')).toHaveCount(4)
    for (const section of await root.locator('.report-detail').all())
      await expect(section.locator('.report-fold-trigger')).toHaveAttribute('aria-expanded', 'false')
    if (empty) {
      await expect(root.getByText('저장된 핵심 요약이 없습니다.')).toBeVisible()
      await root.locator('.report-history .report-fold-trigger').click()
      await expect(root.getByText('저장된 과거 공시 조회 기록이 없습니다.')).toBeVisible()
      await root.locator('.report-history .report-fold-trigger').click()
    } else {
      await expect(root.getByText('성장 가정 재검토', { exact: true })).toBeVisible()
      await root.locator('.report-facts .report-fold-trigger').click()
      if (kind === '정정') await expect(root.locator('.report-facts table')).toContainText('3척')
      else await expect(root.getByText('신규 계약 체결 사실', { exact: true })).toBeVisible()
      await root.locator('.report-sources .report-fold-trigger').click()
      await expect(root.getByRole('link', { name: '원문', exact: true })).toHaveAttribute('href', 'https://example.com/filing')
      await root.locator('.report-facts .report-fold-trigger').click()
      await root.locator('.report-sources .report-fold-trigger').click()
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.getByRole('button', { name: 'MD 다운로드', exact: true }).focus()
    await page.evaluate(() => window.scrollTo(0, 0))
    if (process.env.E2E_ARTIFACT_DIR) await page.screenshot({
      path: `${process.env.E2E_ARTIFACT_DIR}/공통양식-${kind}-${page.viewportSize()!.width}.png`, fullPage: true, animations: 'disabled',
    })
  })
}

test('재검토 카드의 긴 제목과 본문에 여백을 두고 중복 시나리오는 숨깁니다', async ({ page }) => {
  const point = {
    perspective_type: 'FINANCE',
    title: '수주잔고 회복 가정에 반영된 계약 물량과 잔여 선박의 인도 및 대금 회수 조건을 다시 확인해야 합니다.',
    memo_view: '기존 메모는 수주잔고 회복을 성장 가정으로 두고 있습니다.',
    disclosure_fact: '공시에서 계약 대상의 축소를 확인했습니다.',
    reason: '계약 범위 변경이 기존 전망에 반영되었는지 확인해야 합니다.',
    question: '잔여 물량의 인도와 회수 조건이 확인됩니까?',
    check_items: ['선박별 인도 일정', '대금 회수 조건'],
    evidence: [sources[0]],
  }
  await page.route('**/api/v1/analyses/report-task/report', (route) => route.fulfill({ json: {
    ...report,
    content: report.content.replace('## 확인된 공시 내용', '## 새롭게 고찰할 관점\n\n중복 카드 본문\n\n## 확인된 공시 내용'),
    report_json: { ...report.report_json, base: { ...report.report_json.base, review_points: [point] } },
  } }))
  await page.goto('/analyses/report-task')
  const card = page.locator('.review-points .finding-card')
  await expect(card).toHaveCount(1)
  await expect(card.getByRole('heading', { name: point.title })).toBeVisible()
  await expect(page.getByRole('heading', { name: '향후 영향과 조건', exact: true })).toHaveCount(0)
  await expect(page.getByText('중복 카드 본문', { exact: true })).toHaveCount(0)
  const spacing = await card.evaluate((el) => {
    const bounds = el.getBoundingClientRect()
    const header = el.querySelector('.review-heading h3')!.getBoundingClientRect()
    const reason = el.querySelector('.review-reason p')!.getBoundingClientRect()
    return { titleLeft: header.left - bounds.left, titleRight: bounds.right - header.right,
      titleTop: header.top - bounds.top, textLeft: reason.left - bounds.left,
      textRight: bounds.right - reason.right, height: header.height,
      lineHeight: Number.parseFloat(getComputedStyle(el.querySelector('.review-heading h3')!).lineHeight) }
  })
  for (const gap of [spacing.titleLeft, spacing.titleRight, spacing.titleTop, spacing.textLeft, spacing.textRight])
    expect(gap).toBeGreaterThanOrEqual(16)
  if (page.viewportSize()!.width < 650) expect(spacing.height).toBeGreaterThan(spacing.lineHeight)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await card.getByRole('button', { name: '근거 1 상세 보기' }).click()
  await expect(page.getByRole('dialog')).toContainText(sources[0]!.quote)
})

test('제거한 메모 제안의 근거도 출처 구역에서 원문 줄바꿈과 빈 줄을 유지합니다', async ({ page }) => {
  const quote =
    '2. 계약금액(원)\t227,500,000,000\t114,800,000,000\n5. 계약기간 종료일\t2026-02-28\t-\n\n9. 기타 투자판단과 관련한 주요사항\n계약취소 권한을 행사했습니다.'
  const source = { ...sources[0]!, quote }
  await page.route('**/api/v1/analyses/report-task/report', (route) =>
    route.fulfill({
      json: {
        ...report,
        content: report.content.split('## 출처와 원문 인용')[0],
        report_json: {
          ...report.report_json,
          sources: [source, ...sources.slice(1)],
          base: {
            ...report.report_json.base,
            proposals: report.report_json.base.proposals.map((p) => ({ ...p, evidence: [source] })),
          },
        },
      },
    }),
  )
  await page.goto('/analyses/report-task')
  await expect(page.locator('.memo-proposals')).toHaveCount(0)
  await page.locator('.report-sources .report-fold-trigger').click()
  const fact = page.locator('.report-sources .report-evidence blockquote').first()
  await expect(fact).toBeVisible()
  expect(await fact.textContent()).toBe(quote)
  for (const theme of ['light', 'dark']) {
    await page.evaluate((theme) => (document.documentElement.dataset.theme = theme), theme)
    await expect(fact).toHaveCSS('white-space', 'pre-wrap')
    const lines = await fact.evaluate((element) => {
      const node = element.firstChild!
      const top = (label: string) => {
        const range = document.createRange()
        const start = node.textContent!.indexOf(label)
        range.setStart(node, start)
        range.setEnd(node, start + 1)
        return range.getBoundingClientRect().top
      }
      return [top('2. 계약금액'), top('5. 계약기간'), top('9. 기타')]
    })
    expect(lines[1]!).toBeGreaterThan(lines[0]!)
    expect(lines[2]!).toBeGreaterThan(lines[1]!)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  }
})

test('저장된 메모 유지 및 수정 제안은 카드나 본문으로 다시 표시하지 않습니다', async ({ page }) => {
  await page.route('**/api/v1/analyses/report-task/report', (route) =>
    route.fulfill({
      json: {
        ...report,
        content: report.content.replace('## 메모 수정 제안', '## 메모 유지 및 수정 제안'),
      },
    }),
  )
  await page.goto('/analyses/report-task')
  const reportView = page.locator('.unified-report')
  await expect(reportView.locator('.memo-proposals')).toHaveCount(0)
  await expect(reportView.getByText(afterText, { exact: true })).toHaveCount(0)
  await expect(reportView.getByText(beforeText, { exact: true })).toHaveCount(0)
  await expect(
    reportView.getByRole('heading', { name: '메모 유지 및 수정 제안', exact: true }),
  ).toHaveCount(0)
  await expect(
    reportView.getByRole('button', { name: '출처와 원문 인용', exact: true }),
  ).toHaveAttribute('aria-expanded', 'false')
  await expect(reportView.locator('.report-analysis .analysis-perspectives')).toHaveCount(1)
  await expect(reportView.getByText(selectionReason, { exact: true })).toHaveCount(1)
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

test('이전 판단 구역과 내부 출처 식별자를 숨기고 번호·원문 연결은 유지합니다', async ({ page }) => {
  const fixedSources = [
    { ...sources[0]!, document_id: 'opendart:20251229800710:' + 'a'.repeat(64) },
    { ...sources[1]!, document_id: 'rag:eebc531a-083f-43dc-b0dd-3e68a24d47f0:chunk:0' },
  ]
  await page.route('**/api/v1/analyses/report-task/report', (route) => route.fulfill({ json: {
    ...report,
    content: '## 핵심 요약\n\n계약 감액 확인 [근거 1] [근거 2]\n\n## 메모 영향 판단 보류\n\n숨길 판단\n\n## 향후 영향과 조건\n\n숨길 시나리오\n\n## 메모 유지 및 수정 제안\n\n숨길 제안',
    report_json: { sources: fixedSources, base: { proposals: [] }, warnings: [],
      memo_review: { status: 'HOLD', reason: '숨길 판단', evidence: fixedSources } },
  } }))
  await page.goto('/analyses/report-task')
  const root = page.locator('.unified-report-content')
  for (const text of ['메모 영향 판단 보류', '향후 영향과 조건', '메모 유지 및 수정 제안', '숨길 판단', '숨길 시나리오', '숨길 제안'])
    await expect(root.getByText(text, { exact: false })).toHaveCount(0)
  await expect(root.locator('.report-analysis')).toBeVisible()
  await root.locator('.report-sources .report-fold-trigger').click()
  await expect(root.getByRole('button', { name: '근거 1 · DART 공시 원문', exact: true })).toBeVisible()
  const ragButton = root.getByRole('button', { name: '근거 2 · 검색 원문', exact: true })
  await expect(ragButton).toBeVisible()
  await expect(root).not.toContainText('opendart:')
  await expect(root).not.toContainText('rag:')
  await ragButton.click()
  await expect(page.getByRole('dialog').getByRole('heading', { name: '검색 원문', exact: true })).toBeVisible()
  await expect(page.getByRole('dialog')).toContainText(fixedSources[1]!.quote)
  await page.getByRole('button', { name: '원문 닫기' }).click()
  const reference = root.getByRole('button', { name: '근거 1 상세 보기', exact: true })
  await reference.focus()
  await expect(page.getByRole('tooltip')).toContainText('DART 공시 원문')
  await expect(page.getByRole('tooltip')).not.toContainText('opendart:')
  await reference.click()
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'DART 공시 원문', exact: true })).toBeVisible()
  await expect(page.getByRole('dialog').getByRole('link', { name: '외부 원문 열기', exact: true })).toHaveAttribute('href', 'https://example.com/original')
})

for (const [name, quote, labels] of [
  ['일반 본문', '투자판단 관련 주요경영사항\n\n1. 제목\t계약금액 변경\n2. 주요내용\t1. 정정사항\n\n -. 계약금액: 3,834,738,508,160원\n → 9,730,316원\n3. 확인일\t2025-12-29\n4. 기타 사항\n후속 원문은 이 화면에 추가하지 않습니다.', ['1. 제목', '2. 주요내용', '3. 확인일']],
  ['번호 시작 본문', '1. 계약내역\t하이니켈 양극재 공급 계약\n2. 계약금액\t9,730,316원\n3. 계약기간\t2024-01-01 ~ 2025-12-29\n4. 기타 사항\n후속 원문은 이 화면에 추가하지 않습니다.', ['계약내역', '2. 계약금액', '3. 계약기간']],
] as const) {
  test(`${name} 공시 인용문의 줄바꿈·빈 줄·금액·근거를 공통으로 보존합니다`, async ({ page }) => {
    const excerpt = quote.replace(/\s+/g, ' ').split(' 4. 기타 사항')[0]!
    const fixedSource = { ...sources[0]!, quote }
    await page.route('**/api/v1/analyses/report-task/report', (route) => route.fulfill({ json: {
      ...report,
      content: `## 핵심 요약\n\n첫 번째 요약 줄\n두 번째 요약 줄\n\n## 확인된 공시 내용\n\n${excerpt} [근거 1]\n\n확인한 사실의 해석입니다. [근거 1]`,
      report_json: { sources: [fixedSource], base: { proposals: [] }, warnings: [] },
    } }))
    await page.goto('/analyses/report-task')
    await expect(page.locator('.report-summary-section br')).toHaveCount(1)
    const facts = page.locator('.report-facts')
    await facts.locator('.report-fold-trigger').click()
    const paragraph = facts.locator('.source-excerpt')
    await expect(paragraph).toHaveCSS('white-space', 'pre-wrap')
    await expect(paragraph).toContainText('9,730,316원')
    await expect(facts.getByText('확인한 사실의 해석입니다.', { exact: false })).toBeVisible()
    await expect(facts.getByText('후속 원문은 이 화면에 추가하지 않습니다.', { exact: false })).toHaveCount(0)
    const tops = await paragraph.evaluate((element, labels) => {
      const node = element.firstChild!
      return labels.map((label) => {
        const start = node.textContent!.indexOf(label)
        const range = document.createRange()
        range.setStart(node, start)
        range.setEnd(node, start + 1)
        return range.getBoundingClientRect().top
      })
    }, [...labels])
    expect(tops[1]!).toBeGreaterThan(tops[0]!)
    expect(tops[2]!).toBeGreaterThan(tops[1]!)
    await paragraph.getByRole('button', { name: '근거 1 상세 보기' }).click()
    await expect(page.getByRole('dialog')).toContainText('9,730,316원')
    await expect(page.getByRole('dialog')).toContainText('후속 원문은 이 화면에 추가하지 않습니다.')
    await expect(page.getByRole('link', { name: '외부 원문 열기' })).toHaveAttribute('href', 'https://example.com/original')
    await page.getByRole('button', { name: '원문 닫기' }).click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (process.env.E2E_ARTIFACT_DIR) {
      await facts.locator('.report-fold-trigger').focus()
      await page.mouse.move(0, 0)
      await expect(page.getByRole('tooltip')).toHaveCount(0)
      await facts.scrollIntoViewIfNeeded()
      await page.screenshot({ path: `${process.env.E2E_ARTIFACT_DIR}/공시줄바꿈-${name}-${page.viewportSize()!.width}.png`, animations: 'disabled' })
    }
  })
}

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
