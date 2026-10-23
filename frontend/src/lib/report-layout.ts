import { splitMarkdownSections, type MarkdownRange } from './markdown'
import type { Perspective, ReviewReport } from '../types/domain'

export type ReportBlock =
  | { type: 'markdown' | 'sources'; heading: string | null; range: MarkdownRange }
  | { type: 'summary' | 'review-points' | 'changes' | 'memo-proposals' | 'perspective-results' }

const key = (heading: string | null) => heading?.replace(/\s+/g, '') ?? ''
const memoHeadings = new Set(['메모영향', '메모수정제안', '메모유지및수정제안'])
const lateHeadings = new Set([
  '관점별분석',
  '향후영향과조건',
  '확인범위와남은질문',
  '출처와원문인용',
])
const selectionHeadings = new Set(['추가분석을선택한이유', '선택한분석관점', '추가분석을선택하지않은이유', '관점선택과이유'])

export function reportLayout(report: ReviewReport, perspectives: Perspective[]) {
  const sections = splitMarkdownSections(report.content)
  const hasSection = (headings: Set<string>) =>
    sections.some((s) => headings.has(key(s.heading)) && s.body)
  const selected = perspectives.filter((p) => p.selected)
  const hasResults = hasSection(new Set(['관점별분석']))
  const fallbackResults = hasResults ? [] : selected.filter((p) => p.result?.trim())
  const replaceMemo =
    report.findings.length > 0 &&
    report.findings.every((f) => f.beforeText?.trim() && f.reason?.trim())
  const replaceReviews = !!report.reviewPoints?.length && report.reviewPoints.every(
    (p) => p.title.trim() && p.memoView.trim() && p.disclosureFact.trim() && p.reason.trim()
      && p.question.trim() && p.checkItems.length && p.evidenceIds.length,
  )
  const fallbackSummary =
    !hasSection(new Set(['핵심요약'])) &&
    !!report.summary.trim() &&
    !report.content.includes(report.summary.trim())
  const fallbackChanges = !hasSection(new Set(['확인된공시내용'])) && report.changes.length > 0
  const blocks: ReportBlock[] = []
  let memoAdded = false,
    resultsAdded = false,
    summaryAdded = false,
    changesAdded = false
  let reviewsAdded = false

  function addSummary() {
    if (fallbackSummary && !summaryAdded) {
      blocks.push({ type: 'summary' })
      summaryAdded = true
    }
  }
  function addChanges() {
    if (fallbackChanges && !changesAdded) {
      blocks.push({ type: 'changes' })
      changesAdded = true
    }
  }
  function addReviews() {
    if (replaceReviews && !reviewsAdded) {
      blocks.push({ type: 'review-points' })
      reviewsAdded = true
    }
  }
  function addMemo() {
    if (replaceMemo && !memoAdded) {
      blocks.push({ type: 'memo-proposals' })
      memoAdded = true
    }
  }
  function addResults() {
    if (fallbackResults.length && !resultsAdded) {
      blocks.push({ type: 'perspective-results' })
      resultsAdded = true
    }
  }
  for (const section of sections) {
    const heading = key(section.heading)
    if (selectionHeadings.has(heading)) continue
    if (heading) addSummary()
    if (heading && heading !== '핵심요약') addReviews()
    if (heading === '새롭게고찰할관점' && replaceReviews) continue
    if (memoHeadings.has(heading) || lateHeadings.has(heading)) addChanges()
    if (replaceMemo && memoHeadings.has(heading)) {
      addMemo()
      continue
    }
    if (lateHeadings.has(heading)) {
      addMemo()
      addResults()
    }
    // 데이터로 대체할 수 없는 구역과 알 수 없는 제목은 그대로 표시합니다.
    if (
      !section.body &&
      ((heading === '핵심요약' && fallbackSummary) ||
        (heading === '확인된공시내용' && fallbackChanges))
    )
      continue
    blocks.push(
      heading === '출처와원문인용'
        ? {
            type: 'sources',
            heading: section.heading,
            range: { from: section.range.from + 3, to: section.range.to },
          }
        : { type: 'markdown', heading: section.heading, range: section.range },
    )
  }
  addSummary()
  addReviews()
  addChanges()
  addMemo()
  addResults()
  const isMemo = (block: ReportBlock) =>
    block.type === 'memo-proposals' ||
    (block.type === 'markdown' && memoHeadings.has(key(block.heading)))
  if (blocks.some(isMemo)) {
    const isPerspective = (block: ReportBlock) =>
      block.type === 'perspective-results' ||
      (block.type === 'markdown' && key(block.heading) === '관점별분석')
    const isFuture = (block: ReportBlock) =>
      block.type === 'markdown' && key(block.heading) === '향후영향과조건'
    const analysis = [...blocks.filter(isPerspective), ...blocks.filter(isFuture)]
    const remaining = blocks.filter((block) => !isPerspective(block) && !isFuture(block))
    remaining.splice(remaining.findIndex(isMemo), 0, ...analysis)
    return { blocks: remaining, fallbackResults }
  }
  return { blocks, fallbackResults }
}
