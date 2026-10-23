import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ReportBody from './ReportBody.vue'
import { reportSections } from '../lib/report-presentation'
import type { ReviewReport } from '../types/domain'

function report(extra: Partial<ReviewReport> = {}): ReviewReport {
  return {
    id: 'report',
    taskId: 'task',
    version: 1,
    title: '보고서',
    content: '',
    summary: '',
    findings: [],
    changes: [],
    evidence: [],
    warnings: [],
    generatedAt: '',
    savedAt: null,
    noAdditionalAnalysisReason: null,
    ...extra,
  }
}
const props = (value: ReviewReport) => ({ report: value, perspectives: [] })
const titles = (wrapper: ReturnType<typeof mount>) =>
  wrapper
    .findAll('.unified-report-content > section > .report-fold-heading > h2, .report-analysis > h2')
    .map((heading) => heading.text().replace(/\s+/g, ' ').trim())

it.each([
  ['신규', '## 확인된 공시 내용\n\n신규 계약 체결 [근거 1]\n\n## 핵심 요약\n\n신규 요약'],
  [
    '정정',
    '## 분석한계\n\n조건 미확인\n\n## 2. 정정 전후 비교\n\n| 항목 | 전 | 후 |\n| --- | --- | --- |\n| 물량 | 3척 | 2척 |\n\n## 1. 요약\n\n정정 요약',
  ],
  [
    '이전',
    '## 출처 및 근거\n\n[원문][source]\n\n## 심화 분석\n\n기존 상세 분석 [근거 1]\n\n## 재검토 관점\n\n성장 가정 재검토\n\n## 요약\n\n이전 요약\n\n[source]: https://example.com/source',
  ],
])('%s 보고서는 Markdown 순서·제목과 무관하게 같은 양식으로 표시합니다', async (_, content) => {
  const value = report({
    content,
    evidence: [
      {
        id: 'source-0',
        title: '원문',
        quote: '인용문',
        context: '',
        url: 'https://example.com/source',
        kind: 'filing',
        publishedAt: '',
        documentId: 'd',
        version: null,
        paragraph: null,
        location: '1쪽',
      },
    ],
  })
  const wrapper = mount(ReportBody, { props: props(value) })
  expect(titles(wrapper)).toEqual(reportSections.map((section) => section.title))
  expect(wrapper.findAll('.report-analysis .perspective-card')).toHaveLength(4)
  expect(wrapper.findAll('.report-detail')).toHaveLength(4)
  for (const detail of wrapper.findAll('.report-detail'))
    expect(detail.get('button').attributes('aria-expanded')).toBe('false')
  expect(wrapper.find('.report-analysis .report-fold-trigger').exists()).toBe(false)
  if (content.includes('정정')) {
    await wrapper.get('.report-facts .report-fold-trigger').trigger('click')
    expect(wrapper.get('table').text()).toContain('3척')
    expect(wrapper.get('table').text()).toContain('2척')
    expect(wrapper.findAll('.report-facts h2')).toHaveLength(1)
  }
  if (content.includes('이전 요약')) {
    expect(wrapper.get('.report-reviews').text()).toContain('성장 가정 재검토')
    expect(wrapper.get('.report-analysis').text()).toContain('기존 상세 분석')
    await wrapper.get('.report-sources .report-fold-trigger').trigger('click')
    expect(wrapper.get('.report-sources a').attributes('href')).toBe('https://example.com/source')
    await wrapper.get('.report-analysis .evidence-reference').trigger('click')
    expect(wrapper.emitted('openEvidence')?.[0]?.[0]).toEqual(value.evidence[0])
  }
  expect(value.content).toBe(content)
  wrapper.unmount()
})

it.each([false, true])(
  '재검토 관점 유무(%s)와 관계없이 이전 판단·시나리오·수정 제안 구역을 숨깁니다',
  (hasReviews) => {
    const content =
      '## 핵심 요약\n\n요약\n\n## 메모 영향 판단 보류\n\n숨길 판단\n\n## 향후 영향과 조건\n\n숨길 시나리오\n\n## 메모 유지 및 수정 제안\n\n숨길 수정안'
    const value = report({
      content,
      memoReview: { status: 'HOLD', reason: '숨길 판단', evidenceIds: [] },
      reviewPoints: hasReviews
        ? [
            {
              perspectiveType: 'FINANCE',
              title: '실제 재검토 질문',
              memoView: '가정',
              disclosureFact: '사실',
              reason: '이유',
              question: '질문',
              checkItems: ['조건'],
              evidenceIds: ['source-0'],
            },
          ]
        : [],
    })
    const wrapper = mount(ReportBody, { props: props(value) })
    for (const text of [
      '메모 영향 판단 보류',
      '향후 영향과 조건',
      '메모 유지 및 수정 제안',
      '숨길 판단',
      '숨길 시나리오',
      '숨길 수정안',
    ])
      expect(wrapper.text()).not.toContain(text)
    expect(wrapper.find('.memo-proposals').exists()).toBe(false)
    expect(wrapper.find('.review-points').exists()).toBe(hasReviews)
    expect(value.content).toBe(content)
    wrapper.unmount()
  },
)

it('출처 제목의 내부 식별자를 숨기되 같은 원문의 근거 번호와 링크를 유지합니다', async () => {
  const value = report({
    evidence: [
      {
        id: 'source-0',
        title: 'opendart:20251229800710:' + 'a'.repeat(64),
        quote: '계약 감액',
        context: '계약 감액',
        url: 'https://example.com/filing',
      },
      {
        id: 'source-1',
        title: 'rag:long-uuid:chunk:0',
        quote: '메모 가정',
        context: '메모 가정',
        url: null,
      },
    ] as ReviewReport['evidence'],
  })
  const wrapper = mount(ReportBody, { props: props(value) })
  await wrapper.get('.report-sources .report-fold-trigger').trigger('click')
  expect(wrapper.text()).not.toMatch(/opendart:|rag:/)
  expect(wrapper.get('.report-sources').text()).toContain('근거 1 · DART 공시 원문')
  expect(wrapper.get('.report-sources').text()).toContain('근거 2 · 검색 원문')
  await wrapper.get('.report-sources .text-button').trigger('click')
  expect(wrapper.emitted('openEvidence')?.[0]?.[0]).toEqual(value.evidence[0])
  expect(wrapper.get('.report-sources a').attributes('href')).toBe('https://example.com/filing')
  wrapper.unmount()
})

it('자료가 전혀 없는 보고서도 같은 제목을 사용하며 내용을 생성하지 않습니다', async () => {
  const wrapper = mount(ReportBody, { props: props(report()) })
  expect(titles(wrapper)).toEqual(reportSections.map((section) => section.title))
  expect(wrapper.text()).toContain('저장된 핵심 요약이 없습니다.')
  expect(wrapper.text()).toContain('별도의 재검토 관점이 저장되지 않았습니다.')
  expect(wrapper.find('.review-points').exists()).toBe(false)
  expect(wrapper.find('.perspective-analysis-body').exists()).toBe(false)
  for (const kind of ['facts', 'limits', 'sources', 'history']) {
    await wrapper.get(`.report-${kind} .report-fold-trigger`).trigger('click')
    expect(wrapper.get(`.report-${kind} .report-empty`).text()).toContain('저장된')
    expect(wrapper.find(`.report-${kind} .evidence-reference`).exists()).toBe(false)
  }
  wrapper.unmount()
})

it('이전 본문과 모르는 구역을 보존하고 빠진 요약·주의사항·출처는 저장 데이터로 보완합니다', async () => {
  const value = report({
    content: '예전 본문\n\n## 별도 기록\n\n추가 사실 [근거 1]',
    summary: '저장된 요약',
    warnings: ['조회 시간 초과'],
    evidence: [
      {
        id: 'source-0',
        title: '공시',
        quote: '실제 원문',
        context: '',
        url: 'https://example.com/filing',
        kind: 'filing',
        publishedAt: '',
        documentId: 'doc',
        version: null,
        paragraph: null,
        location: '2쪽',
      },
    ],
  })
  const wrapper = mount(ReportBody, { props: props(value) })
  expect(wrapper.get('.report-summary-section').text()).toContain('저장된 요약')
  expect(wrapper.text()).not.toContain('예전 본문')
  await wrapper.get('.report-facts .report-fold-trigger').trigger('click')
  expect(wrapper.get('.report-facts').text()).toContain('예전 본문')
  expect(wrapper.get('.report-facts').text()).toContain('별도 기록')
  expect(wrapper.get('.report-facts').text()).toContain('추가 사실')
  await wrapper.get('.report-limits .report-fold-trigger').trigger('click')
  expect(wrapper.get('.report-limits').text()).toContain('조회 시간 초과')
  await wrapper.get('.report-sources .report-fold-trigger').trigger('click')
  expect(wrapper.get('.report-sources').text()).toContain('실제 원문')
  expect(wrapper.get('.report-sources a').attributes('href')).toBe('https://example.com/filing')
  await wrapper.get('.report-sources .text-button').trigger('click')
  expect(wrapper.emitted('openEvidence')?.[0]?.[0]).toEqual(value.evidence[0])
  expect(wrapper.findAll('.report-sources h2')).toHaveLength(1)
  wrapper.unmount()
})
