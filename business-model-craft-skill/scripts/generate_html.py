#!/usr/bin/env python3
"""
business-model-craft-skill 本地 HTML 生成器
将三件套中的 JSON 和 Markdown 文件拼接成一个本地可预览的网页，
样式对标 businessmodelcraft.com 案例页。
"""

import json
import re
import sys
import os
from pathlib import Path

# ─────────────────────────────────────────────
# Markdown → HTML 简易转换（仅处理报告中实际用到的格式）
# ─────────────────────────────────────────────

def md_to_html(md: str) -> str:
    """将 Markdown 文本转换为 HTML 片段（不含 <html>/<body> 等外层标签）"""
    lines = md.split('\n')
    html_lines = []
    in_blockquote = False
    in_ul = False
    i = 0

    while i < len(lines):
        line = lines[i]

        # 处理引用块
        if line.startswith('>'):
            if not in_blockquote:
                if in_ul:
                    html_lines.append('</ul>')
                    in_ul = False
                html_lines.append('<blockquote>')
                in_blockquote = True
            # 去掉 '>' 前缀
            content = re.sub(r'^>\s?', '', line)
            # 处理引用块内的加粗
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
            # 处理引用块内的表格行（业务快照）
            if content.startswith('|') and content.endswith('|'):
                # 是表格行，跳过（收集后统一处理）
                table_lines = []
                while i < len(lines) and lines[i].startswith('>'):
                    row = re.sub(r'^>\s?', '', lines[i])
                    if row.strip():
                        table_lines.append(row)
                    i += 1
                # 转换表格
                html_lines.append(_md_table_to_html(table_lines))
                continue
            # 处理引用块内的列表
            if content.startswith('*') or content.startswith('-'):
                content = '<li>' + content[1:].strip() + '</li>'
            elif content.strip():
                content = '<p>' + content + '</p>'
            html_lines.append(content)
            i += 1
            continue
        else:
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False

        # H2 标题
        if line.startswith('## '):
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            text = line[3:].strip()
            html_lines.append(f'<h2>{text}</h2>')
            i += 1
            continue

        # H3 标题
        if line.startswith('### '):
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            text = line[4:].strip()
            html_lines.append(f'<h3>{text}</h3>')
            i += 1
            continue

        # 无序列表
        if line.startswith('- ') or line.startswith('* '):
            if not in_ul:
                html_lines.append('<ul>')
                in_ul = True
            content = line[2:].strip()
            content = _inline_md(content)
            html_lines.append(f'<li>{content}</li>')
            i += 1
            continue
        else:
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False

        # 表格
        if line.startswith('|'):
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            table_lines = []
            while i < len(lines) and lines[i].startswith('|'):
                table_lines.append(lines[i])
                i += 1
            html_lines.append(_md_table_to_html(table_lines))
            continue

        # 空行
        if line.strip() == '':
            i += 1
            continue

        # 普通段落
        content = _inline_md(line)
        if content.strip():
            html_lines.append(f'<p>{content}</p>')
        i += 1

    if in_blockquote:
        html_lines.append('</blockquote>')
    if in_ul:
        html_lines.append('</ul>')

    return '\n'.join(html_lines)


def _inline_md(text: str) -> str:
    """处理行内 Markdown 格式"""
    # 加粗
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 斜体
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # 行内代码
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    # 链接
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank">\1</a>', text)
    return text


def _md_table_to_html(table_lines: list) -> str:
    """将 Markdown 表格行列表转换为 HTML 表格"""
    if not table_lines:
        return ''
    rows = []
    for line in table_lines:
        # 跳过分隔行 (|---|---|)
        if re.match(r'^\|[\s\-:|]+\|$', line.strip()):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        rows.append(cells)

    if not rows:
        return ''

    html = ['<table>']
    for idx, row in enumerate(rows):
        tag = 'th' if idx == 0 else 'td'
        html.append('<tr>')
        for cell in row:
            cell = _inline_md(cell)
            html.append(f'<{tag}>{cell}</{tag}>')
        html.append('</tr>')
    html.append('</table>')
    return '\n'.join(html)


# ─────────────────────────────────────────────
# 画布九宫格渲染
# ─────────────────────────────────────────────

def render_canvas_cell(title: str, content: str, lang: str) -> str:
    """渲染单个画布格子，content 中 • 开头的行渲染为列表"""
    items = []
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('•'):
            items.append('<li>' + _inline_md(line[1:].strip()) + '</li>')
        elif line:
            items.append('<li>' + _inline_md(line) + '</li>')

    list_html = '<ul>' + ''.join(items) + '</ul>' if items else ''
    return f'''<div class="bmc-cell">
  <h3>{title}</h3>
  {list_html}
</div>'''


CANVAS_LABELS_EN = {
    'keyPartners': 'Key Partners',
    'keyActivities': 'Key Activities',
    'keyResources': 'Key Resources',
    'valuePropositions': 'Value Propositions',
    'customerRelationships': 'Customer Relationships',
    'channels': 'Channels',
    'customerSegments': 'Customer Segments',
    'costStructure': 'Cost Structure',
    'revenueStreams': 'Revenue Streams',
}

CANVAS_LABELS_ZH = {
    'keyPartners': '重要合作伙伴',
    'keyActivities': '关键业务',
    'keyResources': '核心资源',
    'valuePropositions': '价值主张',
    'customerRelationships': '客户关系',
    'channels': '渠道通路',
    'customerSegments': '客户细分',
    'costStructure': '成本结构',
    'revenueStreams': '收入来源',
}


def render_bmc_grid(canvas: dict, lang: str) -> str:
    """渲染完整的 BMC 九宫格（与 businessmodelcraft.com 布局一致）"""
    labels = CANVAS_LABELS_EN if lang == 'en' else CANVAS_LABELS_ZH

    def cell(key):
        return render_canvas_cell(labels[key], canvas.get(key, ''), lang)

    return f'''<div class="bmc-grid">
  <div class="bmc-row bmc-row-top">
    <div class="bmc-col bmc-col-kp">{cell('keyPartners')}</div>
    <div class="bmc-col bmc-col-ka-kr">
      {cell('keyActivities')}
      {cell('keyResources')}
    </div>
    <div class="bmc-col bmc-col-vp">{cell('valuePropositions')}</div>
    <div class="bmc-col bmc-col-cr-ch">
      {cell('customerRelationships')}
      {cell('channels')}
    </div>
    <div class="bmc-col bmc-col-cs">{cell('customerSegments')}</div>
  </div>
  <div class="bmc-row bmc-row-bottom">
    <div class="bmc-col bmc-col-cost">{cell('costStructure')}</div>
    <div class="bmc-col bmc-col-rev">{cell('revenueStreams')}</div>
  </div>
</div>'''


# ─────────────────────────────────────────────
# 主 HTML 页面生成
# ─────────────────────────────────────────────

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="{lang_attr}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    /* ── Reset & Base ── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ font-size: 16px; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC",
                   "Helvetica Neue", Arial, sans-serif;
      background: #f8f8f6;
      color: #1a1a1a;
      line-height: 1.7;
    }}
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* ── Top Nav ── */
    .site-nav {{
      background: #fff;
      border-bottom: 1px solid #e5e5e5;
      padding: 0 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 56px;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    .site-nav .logo {{
      font-weight: 700;
      font-size: 1rem;
      color: #1a1a1a;
      letter-spacing: -0.02em;
    }}
    .site-nav .nav-links {{
      display: flex;
      gap: 24px;
      align-items: center;
      font-size: 0.875rem;
      color: #555;
    }}
    .site-nav .nav-links a {{ color: #555; }}
    .site-nav .nav-links a:hover {{ color: #1a1a1a; }}
    .lang-btn {{
      background: #f3f4f6;
      border: 1px solid #e5e5e5;
      border-radius: 6px;
      padding: 4px 12px;
      font-size: 0.8125rem;
      cursor: pointer;
      color: #555;
      transition: background 0.15s;
      font-family: inherit;
    }}
    .lang-btn:hover {{ background: #e5e7eb; color: #1a1a1a; }}

    /* ── Header ── */
    .case-header {{
      background: #fff;
      border-bottom: 1px solid #e5e5e5;
      padding: 40px 0 32px;
    }}
    .case-header .container {{
      max-width: 960px;
      margin: 0 auto;
      padding: 0 32px;
    }}
    .industry-tag {{
      display: inline-block;
      font-size: 0.75rem;
      font-weight: 600;
      color: #6b7280;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 12px;
    }}
    .case-header h1 {{
      font-size: 2rem;
      font-weight: 800;
      letter-spacing: -0.03em;
      line-height: 1.25;
      color: #111;
      margin-bottom: 16px;
    }}
    .case-intro {{
      font-size: 1.0625rem;
      color: #444;
      line-height: 1.75;
      max-width: 700px;
    }}

    /* ── BMC Grid ── */
    .bmc-section {{
      background: #fff;
      border-bottom: 1px solid #e5e5e5;
      padding: 40px 0;
    }}
    .bmc-section .container {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 0 24px;
    }}
    .bmc-section h2 {{
      font-size: 1.125rem;
      font-weight: 700;
      color: #111;
      margin-bottom: 20px;
    }}
    .bmc-grid {{
      border: 1px solid #d1d5db;
      border-radius: 8px;
      overflow: hidden;
      font-size: 0.8125rem;
    }}
    .bmc-row {{ display: flex; }}
    .bmc-row-top {{ border-bottom: 1px solid #d1d5db; min-height: 220px; }}
    .bmc-row-bottom {{ min-height: 120px; }}
    .bmc-col {{
      border-right: 1px solid #d1d5db;
      padding: 14px 16px;
      flex: 1;
    }}
    .bmc-col:last-child {{ border-right: none; }}
    .bmc-col-kp {{ flex: 1.1; }}
    .bmc-col-ka-kr {{ flex: 1.1; display: flex; flex-direction: column; gap: 0; }}
    .bmc-col-ka-kr .bmc-cell:first-child {{
      border-bottom: 1px solid #d1d5db;
      padding-bottom: 12px;
      margin-bottom: 12px;
    }}
    .bmc-col-vp {{ flex: 1.3; background: #fafaf9; }}
    .bmc-col-cr-ch {{ flex: 1.1; display: flex; flex-direction: column; }}
    .bmc-col-cr-ch .bmc-cell:first-child {{
      border-bottom: 1px solid #d1d5db;
      padding-bottom: 12px;
      margin-bottom: 12px;
    }}
    .bmc-col-cs {{ flex: 1.1; }}
    .bmc-col-cost {{ flex: 1; }}
    .bmc-col-rev {{ flex: 1; }}
    .bmc-cell h3 {{
      font-size: 0.6875rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #9ca3af;
      margin-bottom: 8px;
    }}
    .bmc-cell ul {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .bmc-cell li {{
      position: relative;
      padding-left: 14px;
      margin-bottom: 5px;
      color: #374151;
      line-height: 1.5;
    }}
    .bmc-cell li::before {{
      content: '•';
      position: absolute;
      left: 0;
      color: #9ca3af;
    }}

    /* ── Article ── */
    .article-section {{
      padding: 56px 0 80px;
    }}
    .article-section .container {{
      max-width: 720px;
      margin: 0 auto;
      padding: 0 32px;
    }}
    .article-section blockquote {{
      border-left: 3px solid #d1d5db;
      padding: 14px 20px;
      margin: 28px 0;
      color: #374151;
      font-style: italic;
      background: #f9fafb;
      border-radius: 0 6px 6px 0;
      font-size: 1.025rem;
    }}
    .article-section blockquote p {{ margin-bottom: 8px; }}
    .article-section blockquote p:last-child {{ margin-bottom: 0; }}
    .article-section blockquote strong {{ font-style: normal; }}
    .article-section blockquote table {{
      font-style: normal;
      width: 100%;
      border-collapse: collapse;
      font-size: 0.875rem;
      margin: 8px 0;
    }}
    .article-section blockquote table th,
    .article-section blockquote table td {{
      text-align: left;
      padding: 6px 10px;
      border-bottom: 1px solid #e5e7eb;
    }}
    .article-section blockquote table th {{ font-weight: 600; color: #6b7280; }}
    .article-section h2 {{
      font-size: 1.375rem;
      font-weight: 700;
      color: #111;
      margin: 48px 0 16px;
      letter-spacing: -0.02em;
    }}
    .article-section h3 {{
      font-size: 1.0625rem;
      font-weight: 600;
      color: #1a1a1a;
      margin: 28px 0 10px;
    }}
    .article-section p {{
      margin-bottom: 18px;
      color: #374151;
      font-size: 1rem;
    }}
    .article-section ul {{
      margin: 0 0 18px 0;
      padding-left: 20px;
    }}
    .article-section li {{
      color: #374151;
      margin-bottom: 6px;
    }}
    .article-section table {{
      width: 100%;
      border-collapse: collapse;
      margin: 20px 0;
      font-size: 0.875rem;
    }}
    .article-section th, .article-section td {{
      text-align: left;
      padding: 10px 14px;
      border-bottom: 1px solid #e5e7eb;
    }}
    .article-section th {{ font-weight: 600; color: #6b7280; background: #f9fafb; }}
    .article-section strong {{ color: #111; }}
    .article-section code {{
      background: #f3f4f6;
      padding: 1px 5px;
      border-radius: 3px;
      font-size: 0.875em;
    }}

    /* ── Footer ── */
    .site-footer {{
      background: #fff;
      border-top: 1px solid #e5e5e5;
      padding: 28px 32px;
      text-align: center;
      font-size: 0.8125rem;
      color: #9ca3af;
    }}
    .site-footer a {{ color: #6b7280; }}
    .site-footer a:hover {{ color: #1a1a1a; }}

    /* ── Language visibility ── */
    [data-lang="zh"] {{ display: none; }}
    body.zh [data-lang="en"] {{ display: none; }}
    body.zh [data-lang="zh"] {{ display: revert; }}

    /* ── Responsive ── */
    @media (max-width: 768px) {{
      .bmc-row {{ flex-direction: column; }}
      .bmc-col {{ border-right: none; border-bottom: 1px solid #d1d5db; }}
      .bmc-col:last-child {{ border-bottom: none; }}
      .case-header h1 {{ font-size: 1.5rem; }}
    }}
  </style>
</head>
<body id="page-body">

  <!-- Navigation -->
  <nav class="site-nav">
    <span class="logo">BusinessModelCraft</span>
    <div class="nav-links">
      <a href="https://businessmodelcraft.com/en" target="_blank">Home</a>
      <a href="https://businessmodelcraft.com/en/examples" target="_blank">Examples</a>
      <button class="lang-btn" onclick="toggleLang()" id="lang-toggle">中文</button>
    </div>
  </nav>

  <!-- Header -->
  <header class="case-header">
    <div class="container">
      <span class="industry-tag" data-lang="en">{industry_en}</span>
      <span class="industry-tag" data-lang="zh">{industry_zh}</span>
      <h1 data-lang="en">{display_title_en}</h1>
      <h1 data-lang="zh">{display_title_zh}</h1>
      <p class="case-intro" data-lang="en">{intro_en}</p>
      <p class="case-intro" data-lang="zh">{intro_zh}</p>
    </div>
  </header>

  <!-- BMC Canvas -->
  <section class="bmc-section">
    <div class="container">
      <h2 data-lang="en">Business Model Canvas</h2>
      <h2 data-lang="zh">商业模式画布</h2>
      <div data-lang="en">{canvas_en}</div>
      <div data-lang="zh">{canvas_zh}</div>
    </div>
  </section>

  <!-- Article -->
  <main class="article-section">
    <div class="container">
      <article data-lang="en">{article_en}</article>
      <article data-lang="zh">{article_zh}</article>
    </div>
  </main>

  <!-- Footer -->
  <footer class="site-footer">
    <p>Generated by <a href="https://businessmodelcraft.com" target="_blank">BusinessModelCraft</a> · 
       Skill: business-model-craft-skill</p>
  </footer>

  <script>
    function toggleLang() {{
      const body = document.getElementById('page-body');
      const btn = document.getElementById('lang-toggle');
      if (body.classList.contains('zh')) {{
        body.classList.remove('zh');
        btn.textContent = '中文';
        document.documentElement.lang = 'en';
      }} else {{
        body.classList.add('zh');
        btn.textContent = 'English';
        document.documentElement.lang = 'zh';
      }}
    }}
  </script>
</body>
</html>'''


def generate_html(slug: str, output_dir: str) -> str:
    """
    从 output_dir/slug/ 下的三件套文件生成本地 HTML 页面。
    返回生成的 HTML 文件路径。
    """
    slug_dir = Path(output_dir) / slug

    json_path = slug_dir / f"{slug}.json"
    zh_path   = slug_dir / f"{slug}.zh.md"
    en_path   = slug_dir / f"{slug}.en.md"

    if not json_path.exists():
        raise FileNotFoundError(f"JSON 文件不存在: {json_path}")

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 读取 Markdown 文件（若不存在则用空字符串）
    zh_md = zh_path.read_text(encoding='utf-8') if zh_path.exists() else ''
    en_md = en_path.read_text(encoding='utf-8') if en_path.exists() else ''

    # 去除中文版开头可能存在的提示块（保留到 HTML 文章中）
    # 中文版提示块格式：> 📌 该公司的分析已发布于 [...]

    content = data.get('content', {})
    canvas_en_data = content.get('canvas_en', {})
    canvas_zh_data = content.get('canvas_zh', {})

    canvas_en_html = render_bmc_grid(canvas_en_data, 'en')
    canvas_zh_html = render_bmc_grid(canvas_zh_data, 'zh')

    article_en_html = md_to_html(en_md)
    article_zh_html = md_to_html(zh_md)

    page_title = data.get('displayTitle_en', data.get('name_en', slug))

    html_content = HTML_TEMPLATE.format(
        lang_attr='en',
        title=page_title,
        industry_en=data.get('industry_en', ''),
        industry_zh=data.get('industry_zh', ''),
        display_title_en=data.get('displayTitle_en', data.get('name_en', '')),
        display_title_zh=data.get('displayTitle_zh', data.get('name_zh', '')),
        intro_en=content.get('intro_en', '').replace('\n', '<br>'),
        intro_zh=content.get('intro_zh', '').replace('\n', '<br>'),
        canvas_en=canvas_en_html,
        canvas_zh=canvas_zh_html,
        article_en=article_en_html,
        article_zh=article_zh_html,
    )

    html_path = slug_dir / f"{slug}.html"
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return str(html_path)


# ─────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────

def main():
    """
    用法：
      python3 scripts/generate_html.py <slug> [output_dir]

    示例：
      python3 scripts/generate_html.py costco ~/Documents/BusinessModelCraft
    
    环境变量：
      BMC_OUTPUT_DIR - 默认输出目录（可选），默认值：~/Documents/BusinessModelCraft
    """
    if len(sys.argv) < 2:
        print("用法：python3 scripts/generate_html.py <slug> [output_dir]")
        sys.exit(1)

    slug = sys.argv[1]
    # 优先级：命令行参数 > 环境变量 > 默认值
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.environ.get(
        'BMC_OUTPUT_DIR',
        os.path.join(os.path.expanduser('~'), 'Documents', 'BusinessModelCraft')
    )

    try:
        html_path = generate_html(slug, output_dir)
        print(f"✅ HTML 生成成功：{html_path}")
        print(f"🌐 本地预览链接：file://{html_path}")
    except Exception as e:
        print(f"❌ 生成失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
