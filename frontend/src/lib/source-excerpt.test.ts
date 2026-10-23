import { expect, it } from 'vitest'
import { restoreExcerptWhitespace } from './source-excerpt'

it('원문과 일치하는 인용문의 줄바꿈·탭·빈 줄을 표시 범위까지만 복원합니다', () => {
  const quote =
    '투자판단 관련 주요경영사항\n\n1. 제목\t계약금액 변경\n2. 주요내용\t1. 정정사항\n\n -. 계약금액: 3,834,738,508,160원 → 9,730,316원\n3. 확인일\t2025-12-29\n표시하지 않은 뒷부분'
  const excerpt = quote.replace(/\s+/g, ' ').slice(0, 90)
  const restored = restoreExcerptWhitespace(quote, excerpt)!
  expect(restored).toContain('\n\n1. 제목\t계약금액 변경\n2. 주요내용')
  expect(restored.replace(/\s+/g, ' ')).toBe(excerpt.trim())
  expect(restored).not.toContain('표시하지 않은 뒷부분')
})

it('금액·날짜·다른 계약의 내용이 다르면 줄바꿈을 추측해 붙이지 않습니다', () => {
  for (const excerpt of ['계약금액 1,000원', '2025-12-30', '다른 계약'])
    expect(restoreExcerptWhitespace('계약금액\t9,730,316원\n2025-12-29', excerpt)).toBeNull()
  expect(restoreExcerptWhitespace('원문', '')).toBeNull()
})

it('CRLF와 공백, 유니코드 문자가 있어도 같은 글자 범위를 유지합니다', () => {
  const quote = '  제목\r\n가정 🧪\t조건\r\n\r\n잔금 회수\n뒷부분  '
  const restored = restoreExcerptWhitespace(quote, '제목 가정 🧪 조건 잔금')!
  expect(restored).toBe('제목\r\n가정 🧪\t조건\r\n\r\n잔금')
})
