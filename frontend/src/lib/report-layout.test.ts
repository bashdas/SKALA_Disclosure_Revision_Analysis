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
  expect(layout.showPerspectives).toBe(true)
  expect(layout.blocks.map((b) => (b.type === 'markdown' ? b.heading : b.type))).toEqual([
    null,
    '핵심 요약',
    '확인된 공시 내용',
    'memo-proposals',
    '관점별 분석',
    '향후 영향과 조건',
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

it('대체 데이터가 없거나 불완전한 보고서에서는 원래 선택 이유와 메모 검토를 보존합니다', () => {
  const value = report(
    '## 추가 분석을 선택한 이유\n\n예전 선택 이유\n\n## 메모 영향\n\n예전 판단 이유\n\n## 메모 수정 제안\n\n예전 수정 제안',
  )
  for (const findings of [[], [{ ...finding, reason: '' }]]) {
    const { layout, html } = displayedMarkdown({ ...value, findings })
    expect(layout.showPerspectives).toBe(false)
    expect(layout.blocks.every((b) => b.type === 'markdown')).toBe(true)
    expect(html).toContain('예전 선택 이유')
    expect(html).toContain('예전 판단 이유')
    expect(html).toContain('예전 수정 제안')
  }
  expect(
    displayedMarkdown(value, [{ ...perspective, selectionReason: '' }]).layout.showPerspectives,
  ).toBe(false)
})

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
    'memo-proposals',
    'perspective-results',
    'markdown',
  ])
  expect(layout.fallbackResults).toEqual([perspective])
  expect(html).toContain('기존 형식의 본문')
  expect(html).toContain('남은 질문')
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

it('선택 관점과 수정 제안이 없는 보고서에는 빈 카드 영역을 추가하지 않습니다', () => {
  const value = report('## 핵심 요약\n\n추가 수정이 필요하지 않습니다.')
  const layout = reportLayout(value, [])
  expect(layout.showPerspectives).toBe(true)
  expect(layout.blocks.every((b) => b.type === 'markdown')).toBe(true)
})

it('출처 구역의 원문은 토글용으로 보존하고 대체할 수 없는 선택 이유도 마지막에 둡니다', () => {
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
  expect(layout.blocks.at(-1)).toMatchObject({ type: 'markdown', heading: '선택한 분석 관점' })
})
