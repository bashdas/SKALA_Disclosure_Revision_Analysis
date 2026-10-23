import { expect, it } from 'vitest'
import { evidenceTitle } from './evidence-title'

it.each([
  ['opendart:20251229800710:' + 'a'.repeat(64), 'DART 공시 원문'],
  ['rag:eebc531a-083f-43dc-b0dd-3e68a24d47f0:chunk:0', '검색 원문'],
  ['memo:internal-id:v1', '메모 원문'],
  ['sec:accession:document', 'SEC 공시 원문'],
  ['filing:receipt:chunk', '공시 원문'],
  ['2026년 3분기 실적 발표', '2026년 3분기 실적 발표'],
])('출처 표시 이름을 정리하고 일반 제목은 유지합니다: %s', (title, expected) => {
  expect(evidenceTitle(title)).toBe(expected)
})
