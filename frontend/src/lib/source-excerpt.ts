// 공백을 합친 보고서 인용문과 원문이 일치할 때만 원래 공백·줄바꿈을 복원합니다.
// 표시된 글자 범위는 유지하며 잘린 뒷부분을 추가하거나 항목 경계를 추측하지 않습니다.
export function restoreExcerptWhitespace(quote: string, excerpt: string): string | null {
  const source = quote.trim()
  const expected = excerpt.replace(/\s+/gu, ' ').trim()
  if (!expected || !source.replace(/\s+/gu, ' ').startsWith(expected)) return null
  let length = 0
  for (const match of source.matchAll(/\s+|\S/gu)) {
    length += /^\s/u.test(match[0]) ? 1 : match[0].length
    if (length === expected.length) return source.slice(0, match.index + match[0].length)
    if (length > expected.length) return null
  }
  return null
}
