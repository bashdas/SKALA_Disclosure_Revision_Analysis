import MarkdownIt from 'markdown-it'

const parser = new MarkdownIt({ html: false, linkify: false }).disable('image')
// 본문의 텍스트 토큰만 바꿉니다. 코드와 기존 링크 안의 표기는 그대로 둡니다.
parser.core.ruler.after('inline', 'evidence_references', (state) => {
  const ids = new Set((state.env.evidenceIds ?? []) as readonly string[])
  for (const block of state.tokens) {
    if (block.type !== 'inline' || !block.children) continue
    let linkDepth = 0
    block.children = block.children.flatMap((token) => {
      if (token.type === 'link_open') linkDepth++
      if (token.type === 'link_close') linkDepth--
      if (token.type !== 'text' || linkDepth) return [token]
      const parts = []
      let start = 0
      for (const match of token.content.matchAll(/\[근거\s*(\d+)\]/gu)) {
        const id = `source-${Number(match[1]) - 1}`
        if (!ids.has(id)) continue
        const before = new state.Token('text', '', 0)
        before.content = token.content.slice(start, match.index)
        const citation = new state.Token('evidence_reference', 'button', 0)
        citation.content = match[0]
        citation.meta = { id, number: Number(match[1]) }
        parts.push(before, citation)
        start = match.index + match[0].length
      }
      const tail = new state.Token('text', '', 0)
      tail.content = token.content.slice(start)
      return [...parts, tail]
    })
  }
})
parser.renderer.rules.evidence_reference = (tokens, index) => {
  const token = tokens[index]!
  return `<button type="button" class="evidence-reference" data-evidence-id="${token.meta!.id}" aria-label="근거 ${token.meta!.number} 상세 보기">${parser.utils.escapeHtml(token.content)}</button>`
}
const linkOpen = parser.renderer.rules.link_open
parser.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index]!.attrSet('target', '_blank')
  tokens[index]!.attrSet('rel', 'noopener noreferrer')
  return linkOpen
    ? linkOpen(tokens, index, options, env, renderer)
    : renderer.renderToken(tokens, index, options)
}
parser.renderer.rules.table_open = () => '<div class="markdown-table"><table>'
parser.renderer.rules.table_close = () => '</table></div>'
export interface MarkdownRange {
  from: number
  to: number
}
export interface MarkdownSection {
  heading: string | null
  body: string
  range: MarkdownRange
}

// 문서 전체를 파싱하므로 다른 구역에 정의된 참조 링크도 보존됩니다.
export function splitMarkdownSections(content: string): MarkdownSection[] {
  const tokens = parser.parse(content, {})
  const lines = content.split(/\r?\n/)
  const starts = [
    0,
    ...tokens.flatMap((token, i) =>
      i > 0 && token.type === 'heading_open' && token.tag === 'h2' && token.level === 0 ? [i] : [],
    ),
  ]
  return starts
    .map((from, i) => {
      const to = starts[i + 1] ?? tokens.length
      const first = tokens[from]
      const isHeading = first?.type === 'heading_open' && first.tag === 'h2' && first.level === 0
      const heading = isHeading
        ? (tokens[from + 1]?.children?.map((t) => t.content).join('') ?? '')
        : null
      const lineStart = first?.map?.[0] ?? 0
      const lineEnd = tokens[to]?.map?.[0] ?? lines.length
      return {
        heading,
        body: lines
          .slice(isHeading ? first!.map![1] : lineStart, lineEnd)
          .join('\n')
          .trim(),
        range: { from, to },
      }
    })
    .filter((section) => section.range.from < section.range.to)
}

export function renderMarkdown(
  content: string,
  evidenceIds: readonly string[] = [],
  range?: MarkdownRange,
) {
  const env = { evidenceIds }
  const tokens = parser.parse(content, env)
  return parser.renderer.render(
    range ? tokens.slice(range.from, range.to) : tokens,
    parser.options,
    env,
  )
}
