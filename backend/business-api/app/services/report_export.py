"""저장된 Markdown 본문으로 다운로드 파일을 만듭니다."""
from markdown_it import MarkdownIt


def report_html(content: str) -> str:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table").disable("image")
    body = parser.render(content)
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>정정공시 분석 보고서</title>
<style>
@page {{ size: A4; margin: 18mm 16mm 20mm; @bottom-right {{ content: counter(page) " / " counter(pages); font-size: 9pt; color: #64748b; }} }}
body {{ font-family: "Noto Sans CJK KR", sans-serif; font-size: 10pt; line-height: 1.65; color: #1c2533; overflow-wrap: anywhere; }}
h1 {{ font-size: 21pt; margin: 0 0 18pt; }}
h2 {{ font-size: 15pt; margin: 24pt 0 10pt; break-after: avoid; }}
h3 {{ font-size: 12pt; margin: 18pt 0 8pt; break-after: avoid; }}
p, ul, ol {{ margin: 0 0 10pt; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 9pt; margin: 12pt 0; }}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; }}
th, td {{ border: 0.5pt solid #cbd5e1; padding: 6pt; text-align: left; vertical-align: top; overflow-wrap: anywhere; }}
th {{ background: #edf2f7; font-weight: 700; }}
a {{ color: #1e5ac9; text-decoration: none; overflow-wrap: anywhere; }}
blockquote {{ margin: 10pt 0; padding: 8pt 12pt; background: #f5f7fa; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
</style></head><body>{body}</body></html>'''


def render_pdf(content: str) -> bytes:
    from weasyprint import HTML

    def deny_resource(url, *args, **kwargs):
        # 본문에 포함된 외부 주소와 로컬 파일을 PDF 서버가 읽지 않도록 합니다.
        raise ValueError("External PDF resources are disabled")

    return HTML(string=report_html(content), url_fetcher=deny_resource).write_pdf()
