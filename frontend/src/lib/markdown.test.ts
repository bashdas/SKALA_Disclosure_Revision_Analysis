import { expect, it } from 'vitest'
import { renderMarkdown, splitMarkdownSections } from './markdown'
it('제목과 표를 표시하고 HTML과 위험한 URL을 실행하지 않습니다', () => {
  const html = renderMarkdown(
    '# 보고서\n\n| 항목 | 값 |\n| --- | --- |\n| 기간 | 3개월 |\n\n<script>alert(1)</script>\n\n[위험](javascript:alert(1))\n\n![원격](https://example.com/tracker.png)',
  )
  expect(html).toContain('<h1>보고서</h1>')
  expect(html).toContain('<table>')
  expect(html).toContain('<td>3개월</td>')
  expect(html).not.toContain('<script>')
  expect(html).not.toContain('href="javascript:')
  expect(html).not.toContain('<img')
})

it('본문과 표의 근거 번호를 저장된 순서에 연결하며 반복·공백 없는 표기를 지원합니다', () => {
  const html = renderMarkdown(
    '## 핵심 요약\n\n주장 [근거6] [근거 1] [근거6]\n\n| 근거 |\n| --- |\n| [근거 1] |',
    ['source-0', 'source-5'],
  )
  expect(html.match(/data-evidence-id="source-5"/g)).toHaveLength(2)
  expect(html.match(/data-evidence-id="source-0"/g)).toHaveLength(2)
  expect(html).toContain('aria-label="근거 6 상세 보기"')
})

it('없는 번호, 코드, 기존 링크에는 근거 버튼을 만들지 않고 다른 보고서로 연결을 넘기지 않습니다', () => {
  const html = renderMarkdown(
    '[근거 0] [근거 9] `코드 [근거 1]`\n\n```\n[근거 1]\n```\n\n[[근거 1]](https://example.com)',
    ['source-0'],
  )
  expect(html).not.toContain('<button')
  expect(html).toContain('[근거 9]')
  expect(renderMarkdown('[근거 1]', ['source-0'])).toContain('<button')
  expect(renderMarkdown('[근거 1]')).not.toContain('<button')
})

it.each([
  '조건: 계약이 이행되는 경우입니다. 예상 영향: 회수 일정을 재검토합니다. [근거 1]',
  '조건: 계약이 이행되는 경우입니다. 예상영향: 회수 일정을 재검토합니다. [근거 1]',
  '조건: 계약이 이행되는 경우입니다.\n  예상 영향: 회수 일정을 재검토합니다. [근거 1]',
  '조건: 계약이 이행되는 경우입니다.  \n  예상 영향: 회수 일정을 재검토합니다. [근거 1]',
  '**조건:** 계약이 이행되는 경우입니다. **예상 영향:** 회수 일정을 재검토합니다. [근거 1]',
])('조건과 예상 영향은 화면에서 줄을 나누고 근거를 유지합니다: %s', (item) => {
  const content = `## 향후 영향과 조건\n\n- ${item}\n\n## 출처와 원문 인용\n\n원문 유지`
  const section = splitMarkdownSections(content)[0]!
  const html = renderMarkdown(content, ['source-0'], section.range)
  expect(html.match(/<br>/g)).toHaveLength(1)
  expect(html).toMatch(/<br>\n?예상\s*영향:/u)
  expect(html).toContain('계약이 이행되는 경우입니다.')
  expect(html).toContain('data-evidence-id="source-0"')
  expect(html).not.toContain('출처와 원문 인용')
})

it('다른 구역과 코드·링크의 예상 영향 표기는 변경하지 않습니다', () => {
  const content =
    '## 핵심 요약\n\n조건: 확인. 예상 영향: 원문 그대로\n\n## 향후 영향과 조건\n\n- 조건: `예상 영향: 코드` [예상 영향: 링크](https://example.com)\n\n## 확인 범위와 남은 질문\n\n조건: 확인. 예상 영향: 원문 그대로'
  const html = renderMarkdown(content)
  expect(html).not.toContain('<br>')
  expect(html).toContain('<code>예상 영향: 코드</code>')
  expect(html).toContain('>예상 영향: 링크</a>')
})

it('화면에서는 중복 보고서 제목만 숨기고 기업 정보와 구역·근거 연결을 유지합니다', () => {
  const content =
    '# 공시 영향 분석 보고서\n\n**기업:** 삼성중공업\n\n**공시 접수번호:** 20260203800709\n\n## 핵심 요약\n\n[출처][source] [근거 1]\n\n[source]: https://example.com/original'
  const sections = splitMarkdownSections(content)
  const html = sections
    .map((section) => renderMarkdown(content, ['source-0'], section.range, true))
    .join('')
  expect(html).not.toContain('<h1>')
  expect(html).toContain('삼성중공업')
  expect(html).toContain('20260203800709')
  expect(html).toContain('<h2>핵심 요약</h2>')
  expect(html).toContain('data-evidence-id="source-0"')
  expect(html).toContain('href="https://example.com/original"')
  expect(renderMarkdown(content)).toContain('<h1>공시 영향 분석 보고서</h1>')
  expect(renderMarkdown('# 별도 제목', [], undefined, true)).toContain('<h1>별도 제목</h1>')
})
