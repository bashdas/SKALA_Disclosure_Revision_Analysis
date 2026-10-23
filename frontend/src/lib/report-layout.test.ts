import { expect, it } from 'vitest'
import { renderMarkdown, splitMarkdownSections } from './markdown'
import { reportLayout } from './report-layout'
import type { Perspective, ReviewReport } from '../types/domain'

const perspective: Perspective = {
  type: 'FINANCE',
  selected: true,
  selectionReason: '선택 이유',
  question: '재무 영향 여부',
  status: 'COMPLETED',
  result: '분석 결과',
}
const finding = {
  id: 'f1',
  beforeText: '기존 문장',
  reason: '판단 이유',
  newFact: '확인한 사실',
  suggestion: '수정 문장',
  impactType: 'FACT_UPDATE',
  evidenceIds: ['source-5'],
  memoParagraph: null,
} as ReviewReport['findings'][number]
function report(content: string, extra: Partial<ReviewReport> = {}): ReviewReport {
  return {
    id: 'report',
    taskId: 'task',
    version: 1,
    title: '보고서',
    content,
    summary: '',
    findings: [],
    changes: [],
    evidence: [],
    generatedAt: '',
    savedAt: null,
    warnings: [],
    noAdditionalAnalysisReason: null,
    ...extra,
  }
}
function displayedMarkdown(value: ReviewReport, perspectives: Perspective[] = []) {
  const layout = reportLayout(value, perspectives)
  return {
    layout,
    html: layout.blocks
      .flatMap((b) =>
        b.type === 'markdown'
          ? [renderMarkdown(value.content, ['source-0', 'source-5'], b.range)]
          : b.type === 'perspective-analysis'
            ? b.ranges.map((range) => renderMarkdown(value.content, ['source-0', 'source-5'], range))
          : [],
      )
      .join(''),
  }
}

it('대체 가능한 선택 이유와 수정 제안만 제외하고 카드와 분석 결과를 본문 순서에 넣습니다', () => {
  const value = report(
    '# 보고서\n\n## 추가 분석을 선택한 이유\n\n선택 이유\n\n## 핵심 요약\n\n요약 [근거6]\n\n## 확인된 공시 내용\n\n변경 내용 [근거 1]\n\n## 메모 영향\n\n판단 이유\n\n## 메모 수정 제안\n\n기존 문장 → 수정 문장\n\n## 관점별 분석\n\n분석 결과\n\n## 향후 영향과 조건\n\n향후 조건\n\n## 별도 검토 사항\n\n남겨야 하는 내용',
    { findings: [finding] },
  )
  const { layout, html } = displayedMarkdown(value, [perspective])
  expect(layout.blocks.map((b) => (b.type === 'markdown' ? b.heading : b.type))).toEqual([
    null,
    '핵심 요약',
    '확인된 공시 내용',
    'perspective-analysis',
    '향후 영향과 조건',
    'memo-proposals',
    '별도 검토 사항',
  ])
  expect(html).not.toContain('선택 이유')
  expect(html).not.toContain('판단 이유')
  expect(html).not.toContain('수정 문장')
  expect(html).toContain('분석 결과')
  expect(html).toContain('남겨야 하는 내용')
  expect(html).toContain('data-evidence-id="source-5"')
  expect(html).toContain('data-evidence-id="source-0"')
  expect(layout.fallbackResults).toEqual([])
})

it('선택 이유는 제외하고 대체 데이터가 없는 메모 검토는 보존합니다', () => {
  const value = report(
    '## 추가 분석을 선택한 이유\n\n예전 선택 이유\n\n## 메모 영향\n\n예전 판단 이유\n\n## 메모 수정 제안\n\n예전 수정 제안',
  )
  for (const findings of [[], [{ ...finding, reason: '' }]]) {
    const { layout, html } = displayedMarkdown({ ...value, findings })
    expect(layout.blocks.filter((b) => b.type === 'perspective-analysis')).toHaveLength(1)
    expect(html).not.toContain('예전 선택 이유')
    expect(html).toContain('예전 판단 이유')
    expect(html).toContain('예전 수정 제안')
  }
  expect(displayedMarkdown(value, [{ ...perspective, selectionReason: '' }]).html).not.toContain(
    '예전 선택 이유',
  )
})

it.each(['메모 수정 제안', '메모 유지 및 수정 제안'])(
  '%s 구역은 대체 카드가 있을 때만 제외합니다',
  (heading) => {
    const value = report(
      `## 확인된 공시 내용\n\n변경 내용\n\n## ${heading}\n\n유지 또는 수정 원문\n\n## 관점별 분석\n\n분석 결과`,
    )
    const replaced = displayedMarkdown({ ...value, findings: [finding] })
    expect(replaced.layout.blocks.filter((b) => b.type === 'memo-proposals')).toHaveLength(1)
    expect(replaced.html).not.toContain('유지 또는 수정 원문')
    expect(replaced.html).toContain('분석 결과')
    for (const findings of [[], [{ ...finding, reason: '' }]]) {
      const preserved = displayedMarkdown({ ...value, findings })
      expect(preserved.html).toContain(heading)
      expect(preserved.html).toContain('유지 또는 수정 원문')
    }
  },
)

it('본문에서 빠진 요약·변경 내용·관점 결과도 구조화된 데이터가 있으면 보여줍니다', () => {
  const value = report(
    '## 기타 내용\n\n기존 형식의 본문\n\n## 확인 범위와 남은 질문\n\n남은 질문',
    {
      summary: '저장된 요약',
      changes: [{ label: '금액', before: '10', after: '20' }],
      findings: [finding],
    },
  )
  const { layout, html } = displayedMarkdown(value, [perspective])
  expect(layout.blocks.map((b) => b.type)).toEqual([
    'summary',
    'markdown',
    'changes',
    'perspective-analysis',
    'memo-proposals',
    'markdown',
  ])
  expect(layout.fallbackResults).toEqual([perspective])
  expect(html).toContain('기존 형식의 본문')
  expect(html).toContain('남은 질문')
})

it('비교 카드가 없는 이전 보고서도 분석과 향후 영향을 메모 제안 위로 옮기고 원문을 보존합니다', () => {
  const value = report(
    '## 메모 수정 제안\n\n보존할 제안 [근거 1]\n\n## 향후 영향과 조건\n\n조건: 이행. 예상 영향: 확인.\n\n## 관점별 분석\n\n보존할 분석 [근거6]\n\n## 확인 범위와 남은 질문\n\n남은 질문',
  )
  const { layout, html } = displayedMarkdown(value)
  expect(layout.blocks.map((b) => (b.type === 'markdown' ? b.heading : b.type))).toEqual([
    'perspective-analysis',
    '향후 영향과 조건',
    '메모 수정 제안',
    '확인 범위와 남은 질문',
  ])
  for (const text of ['보존할 제안', '보존할 분석', '남은 질문']) expect(html).toContain(text)
  expect(html).toContain('data-evidence-id="source-0"')
  expect(html).toContain('data-evidence-id="source-5"')
})

it('코드·인용문 속 제목을 구역으로 오인하지 않고 구역 밖의 참조 링크도 유지합니다', () => {
  const content =
    '## 핵심 요약\n\n[원문][source] [근거 6]\n\n```md\n## 메모 영향\n코드 예시\n```\n\n> ## 메모 수정 제안\n> 인용문 내용\n\n## 확인 범위와 남은 질문\n\n검토 중\n\n[source]: https://example.com/original'
  expect(splitMarkdownSections(content).map((s) => s.heading)).toEqual([
    '핵심 요약',
    '확인 범위와 남은 질문',
  ])
  const { html } = displayedMarkdown(report(content, { findings: [finding] }))
  expect(html).toContain('href="https://example.com/original"')
  expect(html).toContain('코드 예시')
  expect(html).toContain('인용문 내용')
  expect(html).toContain('data-evidence-id="source-5"')
})

it('선택 관점과 수정 제안이 없어도 판단 기록을 위한 통합 구역을 요약 뒤에 추가합니다', () => {
  const value = report('## 핵심 요약\n\n추가 수정이 필요하지 않습니다.')
  const layout = reportLayout(value, [])
  expect(layout.blocks.map((b) => b.type)).toEqual(['markdown', 'perspective-analysis'])
  expect(layout.fallbackResults).toEqual([])
})

it('출처 구역의 원문은 토글용으로 보존하고 선택 이유는 제외합니다', () => {
  const value = report(
    '## 선택한 분석 관점\n\n예전 선택 이유\n\n## 핵심 요약\n\n요약\n\n## 출처와 원문 인용\n\n### 근거 1\n\n[출처][original]\n\n> 전체 인용\n\n[original]: https://example.com/source',
  )
  const layout = reportLayout(value, [])
  const sources = layout.blocks.find((b) => b.type === 'sources')!
  expect(sources.type).toBe('sources')
  if (sources.type !== 'sources') throw new Error('출처 구역 누락')
  const html = renderMarkdown(value.content, [], sources.range)
  expect(html).not.toContain('출처와 원문 인용')
  expect(html).toContain('전체 인용')
  expect(html).toContain('href="https://example.com/source"')
  expect(layout.blocks.at(-1)).toMatchObject({ type: 'sources' })
  expect(displayedMarkdown(value).html).not.toContain('예전 선택 이유')
})

it('재검토 관점은 수정 제안이 없어도 공시 사실보다 먼저 표시하고 중복 본문을 대체합니다', () => {
  const point = { perspectiveType: 'FINANCE' as const, title: '성장 가정 재검토',
    memoView: '기존 성장 가정', disclosureFact: '새로운 계약 조건', reason: '반영 범위 확인',
    question: '기존 전망에 반영됐습니까?', checkItems: ['계약 조건'], evidenceIds: ['source-0'] }
  const value = report('## 핵심 요약\n\n요약\n\n## 새롭게 고찰할 관점\n\n원문 관점\n\n## 확인된 공시 내용\n\n공시 사실', {
    reviewPoints: [point],
  })
  const { layout, html } = displayedMarkdown(value)
  expect(layout.blocks.map((b) => b.type === 'markdown' ? b.heading : b.type)).toEqual([
    '핵심 요약', 'review-points', '확인된 공시 내용', 'perspective-analysis',
  ])
  expect(html).not.toContain('원문 관점')
  const incomplete = displayedMarkdown({ ...value, reviewPoints: [{ ...point, reason: '' }] })
  expect(incomplete.html).toContain('원문 관점')
  expect(incomplete.layout.blocks.some((b) => b.type === 'review-points')).toBe(false)
})

it('메모가 null인 새 관점도 공통 카드로 표시해 Markdown 중복을 없앱니다', () => {
  const value = report('## 새롭게 고찰할 관점\n\n중복 원문\n\n## 향후 영향과 조건\n\n이전 구역', {
    reviewPoints: [{ viewType: 'DISCLOSURE_REVIEW', perspectiveType: 'FX_HEDGE', title: '만기 대조',
      memoView: null, condition: '환헤지 보유 시', disclosureFact: '지급일 연기', reason: '일정 대응',
      question: '만기가 대응합니까?', checkItems: ['만기 확인'], evidenceIds: ['source-0'] }],
  })
  const displayed = displayedMarkdown(value)
  expect(displayed.layout.blocks.filter((b) => b.type === 'review-points')).toHaveLength(1)
  expect(displayed.html).not.toContain('중복 원문')
  expect(displayed.html).not.toContain('이전 구역')
  expect(value.content).toContain('중복 원문')
})

it('화면에 재검토 관점이 있으면 향후 영향은 숨기고 저장 원문은 보존합니다', () => {
  const content = '## 새롭게 고찰할 관점\n\n기존 가정의 반영 여부를 확인합니다.\n\n## 향후 영향과 조건\n\n조건부 시나리오 [근거 1]\n\n## 확인 범위와 남은 질문\n\n개별 계약 조건은 미확인입니다.'
  const value = report(content)
  const displayed = displayedMarkdown(value)
  expect(displayed.html).toContain('기존 가정의 반영 여부')
  expect(displayed.html).not.toContain('조건부 시나리오')
  expect(displayed.html).toContain('개별 계약 조건은 미확인')
  expect(value.content).toBe(content)
})

it('본문 제목이 없어도 유효한 재검토 카드가 있으면 향후 영향을 숨깁니다', () => {
  const value = report('## 향후 영향과 조건\n\n시나리오 원문', {
    reviewPoints: [{ perspectiveType: 'FINANCE', title: '회수 조건 재검토',
      memoView: '성장 가정', disclosureFact: '계약 축소', reason: '반영 여부 미확인',
      question: '반영됐습니까?', checkItems: ['회수 일정'], evidenceIds: ['source-0'] }],
  })
  const displayed = displayedMarkdown(value)
  expect(displayed.layout.blocks.filter((b) => b.type === 'review-points')).toHaveLength(1)
  expect(displayed.html).not.toContain('시나리오 원문')
  const incomplete = displayedMarkdown({ ...value, reviewPoints: [{ ...value.reviewPoints![0]!, reason: '' }] })
  expect(incomplete.html).toContain('시나리오 원문')
})

it('재검토 관점이 없는 이전 보고서의 향후 영향은 계속 표시합니다', () => {
  const value = report('## 새롭게 고찰할 관점\n\n## 향후 영향과 조건\n\n조건부 시나리오')
  expect(displayedMarkdown(value).html).toContain('조건부 시나리오')
})

it('Markdown 분석이 없으면 통합 구역을 공시 사실 뒤에 배치합니다', () => {
  const value = report('## 핵심 요약\n\n요약\n\n## 확인된 공시 내용\n\n사실\n\n## 메모 수정 제안\n\n제안\n\n## 확인 범위와 남은 질문\n\n미확인')
  const layout = reportLayout(value, [perspective])
  expect(layout.blocks.map((b) => b.type === 'markdown' ? b.heading : b.type)).toEqual([
    '핵심 요약', '확인된 공시 내용', 'perspective-analysis', '메모 수정 제안', '확인 범위와 남은 질문',
  ])
  expect(layout.fallbackResults).toEqual([perspective])
})

it('공시 구역이 없으면 재검토 관점 뒤에 통합 구역을 넣고 원래 본문은 바꾸지 않습니다', () => {
  const content = '## 핵심 요약\n\n요약\n\n## 새롭게 고찰할 관점\n\n관점\n\n## 확인 범위와 남은 질문\n\n미확인'
  const value = report(content)
  const layout = reportLayout(value, [])
  expect(layout.blocks.map((b) => b.type === 'markdown' ? b.heading : b.type)).toEqual([
    '핵심 요약', '새롭게 고찰할 관점', 'perspective-analysis', '확인 범위와 남은 질문',
  ])
  expect(value.content).toBe(content)
})

it('관점별 분석 구역이 여러 개여도 제목은 하나로 모으고 각 본문·근거를 보존합니다', () => {
  const value = report('## 관점별 분석\n\n### 재무\n\n첫 분석 [근거 1]\n\n## 별도 내용\n\n보존할 내용\n\n## 관점별 분석\n\n### 산업\n\n둘째 분석 [근거6]')
  const { layout, html } = displayedMarkdown(value)
  const analyses = layout.blocks.filter((b) => b.type === 'perspective-analysis')
  expect(analyses).toHaveLength(1)
  expect(analyses[0]!.ranges).toHaveLength(2)
  for (const text of ['첫 분석', '둘째 분석', '보존할 내용', 'source-0', 'source-5'])
    expect(html).toContain(text)
})
