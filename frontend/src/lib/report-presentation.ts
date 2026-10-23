import type { Perspective, ReviewReport } from '../types/domain'
import { reportHeading, reportLayout, type ReportBlock } from './report-layout'

export const reportSections = [
  { id: 'summary', title: '핵심 요약', collapsed: false },
  { id: 'reviews', title: '새롭게 고찰할 관점', collapsed: false },
  { id: 'analysis', title: '관점별 분석', collapsed: false },
  { id: 'facts', title: '확인된 공시 내용', collapsed: true },
  { id: 'limits', title: '확인 범위와 남은 질문', collapsed: true },
  { id: 'sources', title: '출처와 원문 인용', collapsed: true },
  { id: 'history', title: '조회한 과거 공시와 비교 범위', collapsed: true },
] as const
type SectionId = (typeof reportSections)[number]['id']
export type PresentationBlock = { block: ReportBlock; keepHeading: boolean }

function sectionId(block: ReportBlock): SectionId | null {
  if (block.type === 'perspective-analysis') return 'analysis'
  if (block.type === 'summary') return 'summary'
  if (block.type === 'review-points' || block.type === 'memo-proposals') return 'reviews'
  if (block.type === 'changes') return 'facts'
  if (block.type === 'sources') return 'sources'
  if (block.type !== 'markdown') return null
  switch (reportHeading(block.heading)) {
    case '핵심요약':
      return 'summary'
    case '새롭게고찰할관점':
    case '메모영향':
    case '메모수정제안':
    case '메모유지및수정제안':
    case '향후영향과조건':
      return 'reviews'
    case '확인된공시내용':
      return 'facts'
    case '확인범위와남은질문':
      return 'limits'
    case '조회한과거공시와비교범위':
      return 'history'
    default:
      return null
  }
}

export function reportPresentation(report: ReviewReport, perspectives: Perspective[]) {
  const layout = reportLayout(report, perspectives)
  const sections = reportSections.map((section) => ({
    ...section,
    blocks: [] as PresentationBlock[],
  }))
  const intro: ReportBlock[] = []
  for (const block of layout.blocks) {
    if (block.type === 'markdown' && block.heading === null) {
      if (/^#\s+공시 영향 분석 보고서\s*$/m.test(report.content)) intro.push(block)
      else
        sections
          .find((section) => section.id === 'facts')!
          .blocks.push({ block, keepHeading: true })
      continue
    }
    const id = sectionId(block)
    if (
      id &&
      ((block.type === 'markdown' && block.range.from + 3 >= block.range.to) ||
        (block.type === 'sources' && block.range.from >= block.range.to))
    )
      continue
    // 알 수 없는 이전 구역도 버리지 않고 공시 내용 안에서 원래 제목과 함께 보존합니다.
    sections
      .find((section) => section.id === (id ?? 'facts'))!
      .blocks.push({
        block,
        keepHeading:
          id === null ||
          (block.type === 'markdown' &&
            ['메모영향', '메모수정제안', '메모유지및수정제안', '향후영향과조건'].includes(
              reportHeading(block.heading),
            )),
      })
  }
  const summary = sections.find((section) => section.id === 'summary')!
  if (!summary.blocks.length && report.summary.trim())
    summary.blocks.push({ block: { type: 'summary' }, keepHeading: false })
  return { sections, intro, fallbackResults: layout.fallbackResults }
}
