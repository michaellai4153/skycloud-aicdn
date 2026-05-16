"""Server-side rendered Q&A page.

We render full HTML on the server so the answer is visible in `view-source`
(important for SEO — bots like Googlebot index this).
"""
import html
import json
import re


def md_to_html(text):
    """Tiny Markdown subset: paragraphs, bold, italic, list, link.
    Keeps the page lightweight without adding a dependency."""
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)',
                  r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)

    lines = text.split('\n')
    out = []
    in_list = False
    para = []

    def flush_para():
        if para:
            out.append('<p>' + ' '.join(para) + '</p>')
            para.clear()

    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            flush_para()
            if in_list:
                out.append('</ul>')
                in_list = False
        elif stripped.startswith(('### ', '## ', '# ')):
            flush_para()
            if in_list:
                out.append('</ul>')
                in_list = False
            level = 3 if stripped.startswith('### ') else (2 if stripped.startswith('## ') else 1)
            content = stripped.lstrip('#').strip()
            out.append(f'<h{level + 2}>{content}</h{level + 2}>')  # offset so h1 → h3
        elif stripped.startswith(('- ', '* ')):
            flush_para()
            if not in_list:
                out.append('<ul>')
                in_list = True
            out.append('<li>' + stripped[2:].strip() + '</li>')
        else:
            if in_list:
                out.append('</ul>')
                in_list = False
            para.append(stripped)

    flush_para()
    if in_list:
        out.append('</ul>')
    return '\n'.join(out)


def render_qa_page(question, answer_html, *, slug, related, meta_description=''):
    """Return full HTML for a single QA page, styled to match the main site."""
    related_html = ''
    if related:
        items = ''.join(
            f'<a class="qa-related-item" href="/qa/{r["slug"]}">{html.escape(r["question"])}</a>'
            for r in related
        )
        related_html = (
            '<div class="qa-related">'
            '<div class="qa-related-title">其他常見問題</div>'
            f'{items}'
            '</div>'
        )

    safe_q = html.escape(question)
    desc = html.escape(meta_description or question)
    # Strip HTML tags from answer for schema.org plain-text answer
    import re as _re
    answer_text = _re.sub(r'<[^>]+>', ' ', answer_html)
    answer_text = ' '.join(answer_text.split())[:1500]
    schema = json.dumps({
        '@context': 'https://schema.org',
        '@type': 'QAPage',
        'mainEntity': {
            '@type': 'Question',
            'name': question,
            'acceptedAnswer': {
                '@type': 'Answer',
                'text': answer_text,
            },
        },
    }, ensure_ascii=False)
    return f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_q} ｜ AICDN AI 助手</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="https://www.aicdn.ai/qa/{html.escape(slug)}">
<meta property="og:title" content="{safe_q}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="https://www.aicdn.ai/qa/{html.escape(slug)}">
<meta property="og:type" content="article">
<script type="application/ld+json">{schema}</script>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root {{ --blue: #0057FF; --blue-dark: #002D8A; --blue-light: #E8F2FF;
           --cyan: #0099DD; --gray-50: #F8FAFC; --gray-100: #F0F4F8;
           --gray-200: #E2E8F0; --gray-500: #64748B; --gray-700: #334155;
           --gray-900: #0F172A; }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Noto Sans TC', sans-serif; background: var(--gray-50);
          color: var(--gray-900); line-height: 1.7; }}
  .topbar {{ background: white; border-bottom: 1px solid var(--gray-200);
             padding: 16px 32px; display: flex; align-items: center; }}
  .topbar a.brand {{ font-family: 'Space Mono', monospace; font-weight: 700;
                     color: var(--blue); text-decoration: none; font-size: 18px;
                     letter-spacing: 1px; }}
  .topbar a.brand small {{ color: var(--cyan); font-size: 10px; margin-left: 8px;
                            letter-spacing: 2px; text-transform: uppercase; }}
  .container {{ max-width: 720px; margin: 0 auto; padding: 48px 24px; }}
  .breadcrumb {{ font-size: 13px; color: var(--gray-500); margin-bottom: 20px; }}
  .breadcrumb a {{ color: var(--blue); text-decoration: none; }}
  .breadcrumb a:hover {{ text-decoration: underline; }}
  h1 {{ font-size: 28px; font-weight: 700; color: var(--gray-900);
        margin-bottom: 8px; line-height: 1.35; }}
  .ai-badge {{ display: inline-flex; align-items: center; gap: 6px;
               background: var(--blue-light); color: var(--blue);
               padding: 4px 12px; border-radius: 99px; font-size: 12px;
               font-weight: 600; margin-bottom: 24px; }}
  .answer {{ background: white; border-radius: 14px; padding: 32px;
             border: 1px solid var(--gray-200);
             box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
  .answer p {{ margin-bottom: 14px; color: var(--gray-700); }}
  .answer p:last-child {{ margin-bottom: 0; }}
  .answer ul {{ margin: 12px 0; padding-left: 24px; color: var(--gray-700); }}
  .answer li {{ margin-bottom: 6px; }}
  .answer h3 {{ font-size: 18px; font-weight: 700; color: var(--gray-900); margin: 20px 0 10px; }}
  .answer h4 {{ font-size: 16px; font-weight: 600; color: var(--gray-900); margin: 16px 0 8px; }}
  .answer h5 {{ font-size: 14px; font-weight: 600; color: var(--gray-900); margin: 12px 0 6px; }}
  .answer strong {{ color: var(--gray-900); }}
  .answer a {{ color: var(--blue); }}
  .actions {{ margin-top: 32px; display: flex; gap: 12px; flex-wrap: wrap; }}
  .btn {{ padding: 12px 24px; border-radius: 10px; font-size: 14px;
          font-weight: 500; text-decoration: none; transition: all 0.15s;
          display: inline-flex; align-items: center; gap: 6px; }}
  .btn-primary {{ background: var(--blue); color: white; }}
  .btn-primary:hover {{ background: var(--blue-dark); }}
  .btn-outline {{ background: white; color: var(--gray-700);
                  border: 1px solid var(--gray-200); }}
  .btn-outline:hover {{ border-color: var(--blue); color: var(--blue); }}
  .qa-related {{ margin-top: 48px; }}
  .qa-related-title {{ font-size: 13px; font-weight: 600; color: var(--gray-500);
                       letter-spacing: 0.5px; text-transform: uppercase;
                       margin-bottom: 12px; }}
  .qa-related-item {{ display: block; background: white; padding: 14px 18px;
                      border: 1px solid var(--gray-200); border-radius: 10px;
                      margin-bottom: 8px; color: var(--gray-700);
                      text-decoration: none; font-size: 14px;
                      transition: all 0.15s; }}
  .qa-related-item:hover {{ border-color: var(--blue); color: var(--blue);
                            transform: translateX(4px); }}
  .footer {{ text-align: center; padding: 24px; color: var(--gray-500);
             font-size: 12px; }}
  .footer a {{ color: var(--blue); text-decoration: none; }}
</style>
</head>
<body>

<header class="topbar">
  <a href="/" class="brand">SKYCLOUD<small>AICDN</small></a>
</header>

<main class="container">
  <nav class="breadcrumb"><a href="/">首頁</a> › <a href="/#faq">常見問題</a> › <span>問題詳情</span></nav>
  <h1>{safe_q}</h1>
  <div class="ai-badge">🤖 AI 助手回答 ｜ Powered by SkyCloud</div>
  <div class="answer">{answer_html}</div>
  <div class="actions">
    <a class="btn btn-outline" href="/#faq">← 返回常見問題</a>
    <a class="btn btn-primary" href="/#form">立即申請 →</a>
  </div>
  {related_html}
</main>

<footer class="footer">
  AI 回答僅供參考，正式條款請以業務人員提供之資訊為準。
  <br>© 騰雲運算 SkyCloud · <a href="/">www.aicdn.ai</a>
</footer>

</body>
</html>'''


def render_not_found():
    return '''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>找不到此問題 ｜ AICDN</title>
<style>
  body {{ font-family: -apple-system, sans-serif; text-align: center;
          padding: 100px 20px; color: #334; }}
  h1 {{ font-size: 22px; margin-bottom: 12px; }}
  a {{ display: inline-block; margin-top: 24px; padding: 12px 28px;
       background: #0057FF; color: white; text-decoration: none;
       border-radius: 8px; }}
</style>
</head>
<body>
  <h1>找不到此問題</h1>
  <p>這個問題可能已經過期或不存在了。</p>
  <a href="/#faq">返回常見問題</a>
</body>
</html>'''.replace('{{', '{').replace('}}', '}')
