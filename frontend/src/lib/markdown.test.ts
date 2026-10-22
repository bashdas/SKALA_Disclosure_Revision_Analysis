import { expect, it } from 'vitest'
import { renderMarkdown } from './markdown'
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
