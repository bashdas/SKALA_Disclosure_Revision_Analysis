import { expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import AnalysisView from './AnalysisView.vue'
import { useWorkspace } from '../stores/workspace'
import { downloadReport } from '../services/http'
import type { AnalysisTask, ReviewReport } from '../types/domain'
vi.mock('../services', () => ({ services: {} }))
vi.mock('../services/http', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/http')>()),
  downloadReport: vi.fn(async () => {}),
}))

const baseTask = {
  id: 'task',
  memoId: 'memo',
  baseMemoVersion: 2,
  status: 'COMPLETED',
  currentStage: 'REPORT_SAVE',
  perspectives: [
    {
      type: 'FINANCE',
      selected: true,
      selectionReason: '재무 영향 확인',
      status: 'COMPLETED',
      result: '추가 재무 검토 완료',
    },
  ],
  asOf: '2026-10-21T00:00:00Z',
} as unknown as AnalysisTask
const baseReport = {
  id: 'report',
  taskId: 'task',
  title: '검토 결과',
  summary: '요약',
  content:
    '# 본문\n\n## 추가 분석을 선택한 이유\n\n재무 영향 확인\n\n## 핵심 요약\n\n요약 [근거1]\n\n## 메모 영향\n\n매출 영향 검토가 필요합니다.\n\n## 메모 수정 제안\n\n기존 문장 → 수정 제안\n\n## 관점별 분석\n\n추가 재무 검토 완료',
  changes: [],
  findings: [
    {
      id: 'finding',
      beforeText: '기존 문장',
      newFact: '근거 인용문',
      reason: '매출 영향 검토가 필요합니다.',
      suggestion: '수정 제안',
      impactType: 'FACT_UPDATE',
      evidenceIds: ['source-0'],
      memoParagraph: null,
    },
  ],
  evidence: [
    {
      id: 'source-0',
      title: '공시 원문',
      quote: '근거 인용문',
      context: '근거 인용문',
      location: '3쪽',
      url: 'https://example.com/filing',
    },
  ],
  warnings: [],
  savedAt: null,
} as unknown as ReviewReport
async function view(
  task = structuredClone(baseTask),
  report: ReviewReport | null = structuredClone(baseReport),
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useWorkspace()
  store.tasks = [task]
  store.reports = report ? [report] : []
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/analyses/:taskId', component: AnalysisView },
      { path: '/companies', component: { template: '<div />' } },
    ],
  })
  await router.push('/analyses/task')
  return { store, wrapper: mount(AnalysisView, { global: { plugins: [pinia, router] } }) }
}

it('요약과 관점 분석을 유지하고 기존 메모 수정 제안은 표시하지 않습니다', async () => {
  const { store, wrapper } = await view()
  expect(wrapper.find('.unified-report .analysis-perspectives').exists()).toBe(true)
  expect(wrapper.text()).toContain('재무 영향 확인')
  expect(wrapper.text().split('추가 재무 검토 완료')).toHaveLength(2)
  for (const text of ['기존 문장', '매출 영향 검토가 필요합니다.', '메모 영향 판단 보류'])
    expect(wrapper.text()).not.toContain(text)
  expect(
    wrapper.find('.source-list, .findings-section, .report-summary, .report-body').exists(),
  ).toBe(false)
  expect(wrapper.find('.memo-proposals').exists()).toBe(false)
  const openMemo = vi.spyOn(store, 'openMemo').mockResolvedValue()
  await wrapper.get('.report-context button').trigger('click')
  expect(openMemo).toHaveBeenCalledWith('memo', 2)
  await wrapper.get('.evidence-reference').trigger('click')
  expect(store.drawer?.content).toBe('근거 인용문')
  expect(store.drawer?.url).toBe('https://example.com/filing')
  expect(wrapper.findAll('[data-slot=collapsible-trigger]')).toHaveLength(4)
  expect(wrapper.get('.unified-report .report-fold-heading h2').text()).toBe(
    '공시 영향 분석 보고서',
  )
  wrapper.unmount()
})

it.each(['COMPLETED', 'COMPLETED_WITH_WARNINGS'] as const)(
  '%s 보고서는 진행 기록을 숨기고 관점 판단을 표시합니다',
  async (status) => {
    const { wrapper } = await view({ ...baseTask, status })
    expect(wrapper.find('.progress-section').exists()).toBe(false)
    expect(wrapper.find('.report-analysis .analysis-perspectives').exists()).toBe(true)
    wrapper.unmount()
  },
)

it('긴 근거 식별자는 번호로 표시하고 같은 자료의 상세를 엽니다', async () => {
  const evidence = [
    { ...baseReport.evidence[0]!, title: 'opendart:20260203800709:' + 'a'.repeat(64) },
    { ...baseReport.evidence[0]!, id: 'source-1', title: 'memo:long-identifier:v1' },
  ]
  const { store, wrapper } = await view(baseTask, {
    ...baseReport,
    evidence,
    reviewPoints: [{ perspectiveType: 'FINANCE', title: '성장 가정 확인', memoView: '기존 성장 가정',
      disclosureFact: '계약 물량 변경', reason: '반영 여부 미확인', question: '반영됐습니까?',
      checkItems: ['이행 조건'], evidenceIds: ['source-1', 'source-0'] }],
  })
  const chips = wrapper.findAll('.evidence-chips button')
  expect(chips.map((chip) => chip.text())).toEqual(['근거 2', '근거 1'])
  expect(chips[1]!.attributes('title')).toBe('DART 공시 원문')
  await chips[0]!.trigger('click')
  expect(store.drawer?.title).toBe('메모 원문')
  expect(store.drawer?.content).toBe(evidence[1]!.quote)
  wrapper.unmount()
})

it('출처와 원문 인용은 닫힌 토글로 보존하고 펼치면 원문 링크가 표시됩니다', async () => {
  const { wrapper } = await view(baseTask, {
    ...baseReport,
    content:
      baseReport.content +
      '\n\n## 출처와 원문 인용\n\n### 근거 1\n\n[원문](https://example.com/filing)\n\n> 원문 인용 전체',
  })
  const toggle = wrapper.get('.report-sources .report-fold-trigger')
  expect(toggle.text()).toBe('출처와 원문 인용')
  expect(toggle.attributes('aria-expanded')).toBe('false')
  expect(wrapper.find('.report-sources .markdown-body').exists()).toBe(false)
  await toggle.trigger('click')
  await flushPromises()
  expect(toggle.attributes('aria-expanded')).toBe('true')
  expect(wrapper.get('.report-sources .markdown-body').text()).toContain('원문 인용 전체')
  expect(wrapper.get('.report-sources a').attributes('href')).toBe('https://example.com/filing')
  expect(wrapper.get('.report-sources').text().split('출처와 원문 인용')).toHaveLength(2)
  wrapper.unmount()
})

it('통합 헤더에서 기존 MD·PDF 다운로드를 호출하고 실패를 알립니다', async () => {
  const { wrapper } = await view()
  const buttons = wrapper.findAll('.unified-report .row-actions button')
  await buttons[0]!.trigger('click')
  await flushPromises()
  expect(downloadReport).toHaveBeenLastCalledWith('task', 'md')
  await buttons[1]!.trigger('click')
  await flushPromises()
  expect(downloadReport).toHaveBeenLastCalledWith('task', 'pdf')
  vi.mocked(downloadReport).mockRejectedValueOnce(new Error('다운로드 실패'))
  await buttons[0]!.trigger('click')
  await flushPromises()
  expect(wrapper.get('[role=alert]').text()).toBe('다운로드 실패')
  wrapper.unmount()
})

it.each(['RUNNING', 'FAILED', 'SAVE_FAILED'] as const)(
  '보고서가 없는 %s 분석에서 진행·실패 안내와 관점을 유지합니다',
  async (status) => {
    const { wrapper } = await view(
      { ...baseTask, status, currentStage: 'PERSPECTIVE_ANALYSIS' },
      null,
    )
    expect(wrapper.find('.unified-report').exists()).toBe(false)
    expect(wrapper.find('.progress-section').exists()).toBe(true)
    expect(wrapper.get('.perspectives-section').text()).toContain('재무 영향 확인')
    if (status === 'RUNNING')
      expect(wrapper.get('.analysis-wait').text()).toContain('비교하고 있어요')
    else expect(wrapper.find('[role=alert]').exists()).toBe(true)
    wrapper.unmount()
  },
)

it('관점 및 수정 제안이 없으면 판단 기록과 기본 검토 이유를 표시합니다', async () => {
  const { wrapper } = await view(
    { ...baseTask, perspectives: [] },
    {
      ...baseReport,
      findings: [],
      content: '## 핵심 요약\n\n추가 수정 없음',
      summary: '추가 수정 없음',
      noAdditionalAnalysisReason: '기본 검토만으로 판단할 수 있습니다.',
    },
  )
  expect(wrapper.findAll('.analysis-perspectives .perspective-card')).toHaveLength(4)
  expect(wrapper.text()).toContain('기본 검토만으로 판단할 수 있습니다.')
  expect(wrapper.find('.memo-proposals').exists()).toBe(false)
  wrapper.unmount()
})

it('빈 제안의 유지 또는 보류 판단은 화면에 추가하지 않고 저장 데이터를 보존합니다', async () => {
  const { store, wrapper } = await view(baseTask, { ...baseReport, findings: [] })
  expect(wrapper.find('[data-testid=memo-review-decision]').exists()).toBe(false)
  for (const status of ['KEEP', 'HOLD'] as const) {
    store.reports[0]!.memoReview = { status, reason: '공시와 메모를 대조한 판단 이유입니다.', evidenceIds: ['source-0'] }
    await flushPromises()
    expect(wrapper.find('[data-testid=memo-review-decision]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('공시와 메모를 대조한 판단 이유입니다.')
    expect(store.reports[0]!.memoReview?.status).toBe(status)
  }
  wrapper.unmount()
})

it('수정 문장이 없어도 재검토 관점을 중심에 표시하고 원문 근거를 엽니다', async () => {
  const { store, wrapper } = await view(baseTask, {
    ...baseReport, findings: [],
    content: '## 핵심 요약\n\n가정을 다시 확인합니다.\n\n## 새롭게 고찰할 관점\n\n중복 표시하면 안 되는 본문',
    reviewPoints: [{ perspectiveType: 'FINANCE', title: '로열티 성장 가정 재검토',
      memoView: '기존 SC 전환 확대 가정입니다.', disclosureFact: '적용 제품 범위가 확대됐습니다.',
      reason: '기존 전망의 적용 범위를 확인해야 합니다.', question: '확대 제품이 전망에 반영됐습니까?',
      checkItems: ['제품별 계약 조건을 확인합니다.'], evidenceIds: ['source-0'] }],
  })
  expect(wrapper.find('[data-testid=memo-review-decision]').exists()).toBe(false)
  expect(wrapper.find('.memo-proposals').exists()).toBe(false)
  expect(wrapper.findAll('.review-points')).toHaveLength(1)
  expect(wrapper.text()).not.toContain('중복 표시하면 안 되는 본문')
  for (const text of ['기존 SC 전환 확대 가정입니다.', '확대 제품이 전망에 반영됐습니까?', '제품별 계약 조건을 확인합니다.']) {
    expect(wrapper.text()).toContain(text)
  }
  await wrapper.get('.review-points .evidence-chips button').trigger('click')
  expect(store.drawer?.content).toBe('근거 인용문')
  expect(store.drawer?.url).toBe('https://example.com/filing')
  wrapper.unmount()
})

it('관점 선택 카드와 상세 분석은 같은 구역에서 항상 표시됩니다', async () => {
  const { wrapper } = await view(baseTask, { ...baseReport,
    content: baseReport.content + '\n\n## 확인 범위와 남은 질문\n\n남은 질문\n\n## 출처와 원문 인용\n\n원문 출처',
  })
  const analysis = wrapper.get('.report-analysis')
  expect(wrapper.findAll('.report-analysis')).toHaveLength(1)
  expect(wrapper.find('.report-perspectives').exists()).toBe(false)
  expect(analysis.find('.report-fold-trigger').exists()).toBe(false)
  expect(analysis.get('h2').text()).toBe('관점별 분석')
  expect(analysis.findAll('h2')).toHaveLength(1)
  expect(analysis.findAll('.perspective-card')).toHaveLength(4)
  expect(analysis.text()).toContain('재무 영향 확인')
  expect(analysis.text()).toContain('추가 재무 검토 완료')
  expect(analysis.text().indexOf('재무 영향 확인')).toBeLessThan(analysis.text().indexOf('추가 재무 검토 완료'))
  expect(wrapper.text()).not.toContain('관점 선택과 이유')
  expect(wrapper.get('.report-sources .report-fold-trigger').attributes('aria-expanded')).toBe('false')
  wrapper.unmount()
})

it('구조화된 분석은 항상 표시하고 공시 내용과 확인 범위는 하단에 접습니다', async () => {
  const { wrapper } = await view(baseTask, { ...baseReport,
    content: '## 핵심 요약\n\n요약\n\n## 확인된 공시 내용\n\n계약 축소 사실\n\n## 확인 범위와 남은 질문\n\n조건 미확인',
  })
  const analysis = wrapper.get('.report-analysis')
  expect(analysis.text()).toContain('추가 재무 검토 완료')
  expect(analysis.find('.report-fold-trigger').exists()).toBe(false)
  const text = wrapper.get('.unified-report-content').text()
  expect(text.indexOf('관점별 분석')).toBeLessThan(text.indexOf('확인된 공시 내용'))
  expect(text.indexOf('확인된 공시 내용')).toBeLessThan(text.indexOf('확인 범위와 남은 질문'))
  for (const [kind, content] of [['facts', '계약 축소 사실'], ['limits', '조건 미확인']]) {
    const section = wrapper.get(`.report-${kind}`)
    const toggle = section.get('.report-fold-trigger')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(section.text()).not.toContain(content)
    await toggle.trigger('click')
    expect(section.text()).toContain(content)
    expect(section.findAll('h2')).toHaveLength(1)
  }
  wrapper.unmount()
})

it('정정 비교표·근거·원문을 보존하고 하단 네 구역의 순서를 고정합니다', async () => {
  const content = '## 출처와 원문 인용\n\n출처 본문\n\n## 조회한 과거 공시와 비교 범위\n\n과거 공시\n\n## 확인 범위와 남은 질문\n\n조건 미확인\n\n## 확인된 공시 내용\n\n| 항목 | 정정 전 | 정정 후 | 근거 |\n| --- | --- | --- | --- |\n| 계약 물량 | 3척 | 2척 | [근거 1] |\n\n## 관점별 분석\n\n상세 분석'
  const { store, wrapper } = await view(baseTask, { ...baseReport, content })
  const details = wrapper.findAll('.report-detail')
  expect(details.map((section) => section.get('h2').text())).toEqual([
    '확인된 공시 내용', '확인 범위와 남은 질문', '출처와 원문 인용', '조회한 과거 공시와 비교 범위',
  ])
  expect(details.every((section) => section.get('button').attributes('aria-expanded') === 'false')).toBe(true)
  const facts = wrapper.get('.report-facts')
  expect(facts.find('table').exists()).toBe(false)
  await facts.get('.report-fold-trigger').trigger('click')
  expect(facts.findAll('tbody td').map((cell) => cell.text())).toEqual(['계약 물량', '3척', '2척', '[근거 1]'])
  await facts.get('.evidence-reference').trigger('click')
  expect(store.drawer?.url).toBe('https://example.com/filing')
  await facts.get('.report-fold-trigger').trigger('click')
  expect(facts.find('table').exists()).toBe(false)
  expect(store.reports[0]!.content).toBe(content)
  wrapper.unmount()
})

it('Markdown 공시 내용이 없으면 구조화된 변경 내용도 닫힌 토글 안에 보완합니다', async () => {
  const { wrapper } = await view(baseTask, { ...baseReport,
    changes: [{ label: '계약 물량', before: '3척', after: '2척' }],
  })
  const facts = wrapper.get('.report-facts')
  expect(facts.find('.change-grid').exists()).toBe(false)
  await wrapper.get('.report-limits .report-fold-trigger').trigger('click')
  expect(wrapper.get('.report-limits').text()).toContain('저장된 확인 범위와 질문이 없습니다.')
  await facts.get('.report-fold-trigger').trigger('click')
  expect(facts.get('.change-grid').text()).toContain('계약 물량3척2척')
  expect(facts.findAll('h2')).toHaveLength(1)
  wrapper.unmount()
})

it('상세 결과가 없는 이전 보고서는 선택 이유와 기록 누락만 표시합니다', async () => {
  const { wrapper } = await view({ ...baseTask, perspectives: [] }, {
    ...baseReport, content: '## 핵심 요약\n\n요약', findings: [],
    perspectiveDecisions: [{ type: 'FINANCE', selected: false, reason: '추가 분석이 필요하지 않습니다.' }],
  })
  const analysis = wrapper.get('.report-analysis')
  expect(analysis.text()).toContain('추가 분석이 필요하지 않습니다.')
  expect(analysis.text()).toContain('판단 기록 없음')
  expect(analysis.find('.perspective-analysis-body').exists()).toBe(false)
  expect(wrapper.get('.unified-report-content').text().indexOf('요약')).toBeLessThan(wrapper.get('.unified-report-content').text().indexOf('관점별 분석'))
  wrapper.unmount()
})

it('과거 공시 비교 범위를 맨 아래의 닫힌 토글로 옮기고 원문과 근거를 보존합니다', async () => {
  const content = baseReport.content + '\n\n## 조회한 과거 공시와 비교 범위\n\n### 최초 공시 20201012800214\n\n[DART 연결 목록](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20220518800001) [근거 1]\n\n원문 확보와 비교 완료를 구분합니다.\n\n## 확인 범위와 남은 질문\n\n계약별 이행 여부는 미확인입니다.'
  const { store, wrapper } = await view(baseTask, { ...baseReport, content })
  const history = wrapper.get('.report-history')
  const toggle = history.get('.report-fold-trigger')
  expect(toggle.attributes('aria-expanded')).toBe('false')
  expect(history.find('.markdown-body').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('최초 공시 20201012800214')
  expect(wrapper.get('.unified-report-content').element.lastElementChild).toBe(history.element)
  await toggle.trigger('click')
  await flushPromises()
  expect(history.text()).toContain('최초 공시 20201012800214')
  expect(history.get('a').attributes('href')).toContain('rcpNo=20220518800001')
  expect(history.findAll('h2')).toHaveLength(1)
  await history.get('.evidence-reference').trigger('click')
  expect(store.drawer?.content).toBe('근거 인용문')
  expect(store.reports[0]!.content).toBe(content)
  wrapper.unmount()
})
