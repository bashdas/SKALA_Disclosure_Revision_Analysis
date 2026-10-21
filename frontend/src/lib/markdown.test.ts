import { expect, it } from 'vitest'
import { renderMarkdown } from './markdown'
it('제목과 표를 표시하고 HTML과 위험한 URL을 실행하지 않습니다', () => {
  const html=renderMarkdown('# 보고서\n\n| 항목 | 값 |\n| --- | --- |\n| 기간 | 3개월 |\n\n<script>alert(1)</script>\n\n[위험](javascript:alert(1))\n\n![원격](https://example.com/tracker.png)')
  expect(html).toContain('<h1>보고서</h1>')
  expect(html).toContain('<table>')
  expect(html).toContain('<td>3개월</td>')
  expect(html).not.toContain('<script>')
  expect(html).not.toContain('href="javascript:')
  expect(html).not.toContain('<img')
})
