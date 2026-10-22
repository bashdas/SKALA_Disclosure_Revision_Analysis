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

it('하나의 보고서에 요약·관점 결과·메모수정 제안을 중복 없이 표시합니다', async () => {
  const { store, wrapper } = await view()
  expect(wrapper.find('.unified-report .analysis-perspectives').exists()).toBe(true)
  expect(wrapper.text()).toContain('재무 영향 확인')
  for (const text of ['추가 재무 검토 완료', '기존 문장', '매출 영향 검토가 필요합니다.']) {
    expect(wrapper.text().split(text)).toHaveLength(2)
  }
  expect(
    wrapper.find('.source-list, .findings-section, .report-summary, .report-body').exists(),
  ).toBe(false)
  expect(wrapper.get('.memo-proposals > h2').text()).toBe('메모수정 제안 1')
  expect(wrapper.get('.unified-report .memo-proposals').isVisible()).toBe(true)
  const openMemo = vi.spyOn(store, 'openMemo').mockResolvedValue()
  await wrapper.get('.memo-proposals .text-button').trigger('click')
  expect(openMemo).toHaveBeenCalledWith('memo', 2, null)
  await wrapper.get('.evidence-reference').trigger('click')
  expect(store.drawer?.content).toBe('근거 인용문')
  expect(store.drawer?.url).toBe('https://example.com/filing')
  expect(wrapper.findAll('[data-slot=collapsible-trigger]')).toHaveLength(0)
  expect(wrapper.get('.unified-report .report-fold-heading h2').text()).toBe(
    '공시 영향 분석 보고서',
  )
  expect(wrapper.get('.memo-proposals').isVisible()).toBe(true)
  wrapper.unmount()
})

it.each(['COMPLETED', 'COMPLETED_WITH_WARNINGS'] as const)(
  '%s 보고서는 진행 기록을 숨기고 관점 판단을 표시합니다',
  async (status) => {
    const { wrapper } = await view({ ...baseTask, status })
    expect(wrapper.find('.progress-section').exists()).toBe(false)
    expect(wrapper.find('.report-perspectives').exists()).toBe(true)
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
    findings: [{ ...baseReport.findings[0]!, evidenceIds: ['source-1', 'source-0'] }],
  })
  const chips = wrapper.findAll('.evidence-chips button')
  expect(chips.map((chip) => chip.text())).toEqual(['근거 2', '근거 1'])
  expect(chips[1]!.attributes('title')).toBe(evidence[0]!.title)
  await chips[0]!.trigger('click')
  expect(store.drawer?.title).toBe(evidence[1]!.title)
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
  expect(wrapper.findAll('.analysis-perspectives .perspective-card')).toHaveLength(3)
  expect(wrapper.text()).toContain('기본 검토만으로 판단할 수 있습니다.')
  expect(wrapper.find('.memo-proposals').exists()).toBe(false)
  wrapper.unmount()
})

it('빈 제안의 유지 또는 보류 판단과 이유를 표시합니다', async () => {
  const { store, wrapper } = await view(baseTask, { ...baseReport, findings: [] })
  expect(wrapper.get('[data-testid=memo-review-decision]').text()).toContain('메모 영향 판단 보류')
  for (const status of ['KEEP', 'HOLD'] as const) {
    store.reports[0]!.memoReview = { status, reason: '공시와 메모를 대조한 판단 이유입니다.', evidenceIds: ['source-0'] }
    await flushPromises()
    const decision = wrapper.get('[data-testid=memo-review-decision]')
    expect(decision.text()).toContain(status === 'KEEP' ? '기존 메모 유지' : '메모 영향 판단 보류')
    expect(decision.text()).toContain('공시와 메모를 대조한 판단 이유입니다.')
    await decision.get('button').trigger('click')
    expect(store.drawer?.content).toBe('근거 인용문')
  }
  wrapper.unmount()
})
