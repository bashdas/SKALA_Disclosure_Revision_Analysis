import MarkdownIt from 'markdown-it'

const parser = new MarkdownIt({ html: false, linkify: false }).disable('image')
const linkOpen = parser.renderer.rules.link_open
parser.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index]!.attrSet('target', '_blank')
  tokens[index]!.attrSet('rel', 'noopener noreferrer')
  return linkOpen ? linkOpen(tokens, index, options, env, renderer) : renderer.renderToken(tokens, index, options)
}
parser.renderer.rules.table_open = () => '<div class="markdown-table"><table>'
parser.renderer.rules.table_close = () => '</table></div>'
export const renderMarkdown = (content: string) => parser.render(content)
