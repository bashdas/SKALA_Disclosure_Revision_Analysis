export function evidenceTitle(title: string): string {
  if (/^opendart:/i.test(title)) return 'DART 공시 원문'
  if (/^sec:/i.test(title)) return 'SEC 공시 원문'
  if (/^filing:/i.test(title)) return '공시 원문'
  if (/^rag:/i.test(title)) return '검색 원문'
  if (/^memo:/i.test(title)) return '메모 원문'
  return title
}
