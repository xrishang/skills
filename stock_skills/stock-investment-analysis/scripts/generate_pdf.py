"""generate_pdf.py — 把 report.md + charts/*.png 合并生成 PDF 报告

实现方式:Markdown → HTML(带 CSS)→ 调用本机浏览器 headless 渲染 → PDF

跨平台支持:
- Windows:Microsoft Edge(系统自带)
- macOS:Microsoft Edge 或 Safari
- Linux:google-chrome / microsoft-edge / chromium

浏览器渲染原生支持中文字体(系统字体),比 xhtml2pdf 的 @font-face 稳定可靠。
图片路径在 HTML 里用绝对 file:// URL,浏览器能直接读本地文件。

使用:
    python scripts/generate_pdf.py --md output/01956.HK/report.md --pdf output/01956.HK/report.pdf
"""
from __future__ import annotations
import argparse
import sys
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

try:
    import markdown
except ImportError:
    print('错误: 需要先 pip install markdown', file=sys.stderr)
    sys.exit(2)

try:
    from pypdf import PdfReader, PdfWriter
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


CSS = """
@page {
    size: A4;
    margin: 1.8cm 1.6cm 2cm 1.6cm;
}

body {
    font-family: "Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    font-size: 10.5pt;
    line-height: 1.6;
    color: #1f1f1f;
    max-width: 100%;
    margin: 0 auto;
}

h1 {
    font-size: 20pt;
    color: #1a3a5c;
    border-bottom: 2px solid #1a3a5c;
    padding-bottom: 6px;
    margin-top: 0;
    margin-bottom: 14px;
    page-break-before: avoid;
}

h2 {
    font-size: 15pt;
    color: #1a3a5c;
    border-left: 4px solid #1a3a5c;
    padding-left: 8px;
    margin-top: 24px;
    margin-bottom: 8px;
    page-break-after: avoid;
}

h3 {
    font-size: 12.5pt;
    color: #2c5282;
    margin-top: 16px;
    margin-bottom: 6px;
    page-break-after: avoid;
}

h4 { font-size: 11.5pt; color: #444; margin-top: 10px; page-break-after: avoid; }

p { margin: 6px 0; }

blockquote {
    border-left: 3px solid #ddd;
    margin: 8px 0;
    padding: 6px 12px;
    color: #555;
    background: #fafafa;
    font-size: 10pt;
    page-break-inside: avoid;
}

code {
    font-family: "Consolas", "Courier New", monospace;
    font-size: 9.5pt;
    background: #f4f4f4;
    padding: 1px 4px;
    border-radius: 3px;
}

pre {
    background: #f4f4f4;
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 9.5pt;
    overflow-x: auto;
    line-height: 1.4;
    page-break-inside: avoid;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0;
    font-size: 9.8pt;
    page-break-inside: avoid;
}

th, td {
    border: 1px solid #ccc;
    padding: 5px 8px;
    text-align: left;
    vertical-align: top;
}

th {
    background: #f0f4f8;
    font-weight: bold;
    color: #1a3a5c;
}

tr:nth-child(even) { background: #fafafa; }

img {
    max-width: 95%;
    height: auto;
    display: block;
    margin: 10px auto;
    border: 1px solid #eee;
    page-break-inside: avoid;
}

ul, ol { margin: 4px 0; padding-left: 22px; }
li { margin: 3px 0; }

hr { border: none; border-top: 1px solid #ddd; margin: 14px 0; }

strong { color: #c0392b; font-weight: bold; }
em { color: #555; }
"""


def find_browser() -> str | None:
    """找到可用的浏览器(Edge / Chrome / Chromium),按优先级"""
    candidates = [
        # Windows Edge
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        # Windows Chrome
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        # macOS
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        # Linux
        'microsoft-edge-stable',
        'microsoft-edge',
        'google-chrome-stable',
        'google-chrome',
        'chromium-browser',
        'chromium',
    ]
    for c in candidates:
        if shutil.which(c) or Path(c).exists():
            return c
    return None


def md_to_html(md_text: str, md_dir: Path) -> str:
    """Markdown → HTML,把相对图片路径转成 file:// 绝对 URL"""
    def fix_md_img(match):
        alt = match.group(1)
        url = match.group(2)
        if url.startswith('http') or url.startswith('file://') or url.startswith('/'):
            return f'![{alt}]({url})'
        abs_path = (md_dir / url).resolve()
        # Path.as_uri() 自动生成正确的 file:/// URL(Windows 下盘符前有 3 个斜杠)
        return f'![{alt}]({abs_path.as_uri()})'

    md_text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', fix_md_img, md_text)

    extensions = ['tables', 'fenced_code', 'nl2br', 'sane_lists']
    html = markdown.markdown(md_text, extensions=extensions, output_format='html5')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<style>{CSS}</style>
</head>
<body>
{html}
</body>
</html>"""


def html_to_pdf(html_path: Path, pdf_path: Path, browser: str) -> None:
    """调用浏览器 headless 把 HTML 渲染成 PDF"""
    html_url = html_path.resolve().as_uri()

    for headless_mode in ['--headless=new', '--headless']:
        cmd = [
            browser,
            headless_mode,
            '--disable-gpu',
            '--print-to-pdf=' + str(pdf_path.resolve()),
            '--virtual-time-budget=10000',
            '--run-all-compositor-stages-before-draw',
            html_url,
        ]
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8',
                errors='replace',
            )
            if pdf_path.exists() and pdf_path.stat().st_size > 1000:
                return
        except subprocess.TimeoutExpired:
            continue
    raise RuntimeError('浏览器未生成 PDF')


def crop_header_footer(pdf_path: Path, crop_pts: float = 42.0) -> None:
    """裁掉浏览器默认加的页眉(日期 + URL)和页脚(页码)。

    浏览器 headless --print-to-pdf 会在页面边距区域自动渲染:
    - 顶部:日期 + URL(约 y=15-24pt 区域)
    - 底部:页码(约 y=817-827pt 区域)

    --no-pdf-header-footer 需要 Chrome 112+,老版 Edge 111 不支持。
    这里用 pypdf 裁掉 mediabox 的上下边距(约 1.5cm),视觉上去掉页眉页脚。
    内容不受影响 — CSS @page 的 margin(1.8cm/2cm)远大于裁切量(1.5cm)。
    """
    if not HAS_PYPDF:
        return
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for page in reader.pages:
        mb = page.mediabox
        page.mediabox.upper_right = (float(mb.right), float(mb.top) - crop_pts)
        page.mediabox.lower_left = (float(mb.left), float(mb.bottom) + crop_pts)
        writer.add_page(page)
    with open(pdf_path, 'wb') as f:
        writer.write(f)


def derive_pdf_name_from_md(md_path: Path) -> str | None:
    """从 report.md 的 H1 标题推断汉字 PDF 文件名。

    三种模式:
    - 个股:"公司名(代码)投资价值分析报告" → "公司名(代码)投资分析.pdf"
    - ETF:"ETF 资金流向分析报告 — 主题 Top N" → "主题ETF资金流向分析.pdf"
    - 选股:"全市场选股报告 — 日期" → "全市场选股报告_日期.pdf"
    无法识别时返回 None(由调用方 fallback 到 report.pdf)。
    """
    import re
    try:
        text = md_path.read_text(encoding='utf-8')
    except Exception:
        return None

    h1 = None
    for line in text.split('\n'):
        if line.startswith('# '):
            h1 = line[2:].strip()
            break
    if not h1:
        return None

    def clean(name: str) -> str:
        # Windows 文件名非法字符
        for ch in r'\/:*?"<>|':
            name = name.replace(ch, '')
        return name.strip()

    # 模式 1:个股 — "公司名(代码)投资价值分析报告" 或 "公司名(代码) 投资价值分析报告"
    m = re.match(r'^(.+?)\s*[（(]([0-9A-Za-z\.]+HK)[)）]\s*投资', h1)
    if m:
        company = m.group(1).strip()
        code = m.group(2)
        # 简化公司名:去掉常见冗长后缀
        for suffix in ['科技股份有限公司', '股份有限公司', '有限责任公司', '科技', '集团', '控股', '公司']:
            if company.endswith(suffix) and len(company) > len(suffix) + 2:
                company = company[:-len(suffix)]
                break
        company = clean(company)
        return f'{company}({code})投资分析.pdf'

    # 模式 2:ETF — "ETF 资金流向分析报告 — 主题 Top N"
    m = re.match(r'^ETF.*?[-—]\s*(.+?)(?:\s+Top\s*\d+)?$', h1)
    if m:
        topic = m.group(1).strip()
        topic = re.sub(r'\s+', '', topic)
        topic = clean(topic)
        return f'{topic}ETF资金流向分析.pdf'

    # 模式 3:选股 — "全市场选股报告 — 日期"
    m = re.match(r'^全市场选股报告.*?[-—]\s*([\d-]+)', h1)
    if m:
        date = m.group(1)
        return f'全市场选股报告_{date}.pdf'

    # fallback:直接用 H1 清理后,截断到 60 字
    name = clean(h1).replace('—', '_').replace('-', '_')
    name = re.sub(r'\s+', '', name)
    if len(name) > 60:
        name = name[:60]
    return f'{name}.pdf' if name else None


def main():
    parser = argparse.ArgumentParser(description='Markdown 报告 → PDF(浏览器渲染)')
    parser.add_argument('--md', required=True, help='report.md 路径')
    parser.add_argument('--pdf', default=None, help='输出 PDF 路径(默认从 H1 标题推断汉字名)')
    parser.add_argument('--keep-html', action='store_true', help='保留中间 HTML 文件(调试用)')
    args = parser.parse_args()

    md_path = Path(args.md).resolve()
    if not md_path.exists():
        print(f'错误: 找不到 {md_path}', file=sys.stderr)
        sys.exit(1)

    if args.pdf:
        pdf_path = Path(args.pdf).resolve()
    else:
        # 从 H1 标题推断汉字文件名
        derived = derive_pdf_name_from_md(md_path)
        if derived:
            # 清理非法字符,避免路径问题
            safe = derived
            for ch in r'\/:*?"<>|':
                safe = safe.replace(ch, '')
            pdf_path = md_path.parent / safe
        else:
            pdf_path = md_path.with_suffix('.pdf')

    browser = find_browser()
    if not browser:
        print('错误: 找不到 Edge / Chrome / Chromium 浏览器。', file=sys.stderr)
        print('请安装 Microsoft Edge(Windows 自带)或 Google Chrome,或将可执行文件路径加入 PATH。', file=sys.stderr)
        sys.exit(3)

    md_text = md_path.read_text(encoding='utf-8')
    html = md_to_html(md_text, md_path.parent)

    # 写临时 HTML
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.html', delete=False, encoding='utf-8'
    ) as tmp:
        tmp.write(html)
        html_path = Path(tmp.name)

    try:
        html_to_pdf(html_path, pdf_path, browser)
        crop_header_footer(pdf_path)
    except Exception as e:
        print(f'PDF 生成失败: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(4)
    finally:
        if not args.keep_html:
            try:
                html_path.unlink()
            except Exception:
                pass

    if not pdf_path.exists():
        print('错误: PDF 未生成,未知原因', file=sys.stderr)
        sys.exit(5)

    size_kb = pdf_path.stat().st_size / 1024
    print(f'[generate_pdf] 浏览器: {Path(browser).name}', file=sys.stderr)
    print(f'[generate_pdf] 输出: {pdf_path} ({size_kb:.1f} KB)', file=sys.stderr)


if __name__ == '__main__':
    main()
