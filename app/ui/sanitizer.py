"""Strict HTML Sanitization and Safe Markdown Renderer for XSS Defense (Prompt 3)."""

import html
import re
from typing import Optional


def sanitize_text(raw_text: Optional[str]) -> str:
    """
    Rigorously escapes all HTML special characters (&, <, >, ", ') to prevent XSS.
    Ensures attacker-controlled strings like '<script>alert(1)</script>' render completely inert.
    """
    if raw_text is None:
        return ""
    return html.escape(str(raw_text), quote=True)


def render_safe_markdown(markdown_text: Optional[str]) -> str:
    """
    Safely converts Markdown text into structured HTML while strictly neutralizing XSS injections.
    
    Security Workflow:
    1. First, all raw text is escaped so embedded HTML tags (<script>, <img>, <iframe>) become harmless text entities.
    2. Then, markdown syntax (code blocks, headers, bold, italics, bullet lists, blockquotes) is safely expanded into valid semantic HTML.
    """
    if not markdown_text:
        return "<p class='text-muted'>No report content available.</p>"

    # 1. Escape all raw HTML entities first (Defense in depth)
    escaped = html.escape(markdown_text, quote=True)

    # 2. Extract and protect code blocks
    code_blocks = []
    def save_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        idx = len(code_blocks)
        code_blocks.append(f"<pre class='code-block'><code class='language-{lang}'>{code}</code></pre>")
        return f"__CODE_BLOCK_{idx}__"

    # Match ```lang ... ```
    escaped = re.sub(r"```([a-zA-Z0-9_-]*)\n?(.*?)```", save_code_block, escaped, flags=re.DOTALL)

    # 3. Process inline formatting
    # Inline code: `code`
    escaped = re.sub(r"`([^`]+)`", r"<code class='inline-code'>\1</code>", escaped)
    # Bold: **text**
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    # Italic: *text*
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)

    # 4. Process line-by-line structures (Headers, lists, blockquotes, tables, paragraphs)
    lines = escaped.split("\n")
    html_lines = []
    in_list = False
    in_table = False
    table_is_header = True

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            if in_table:
                html_lines.append("</tbody></table></div>")
                in_table = False
            html_lines.append("<br/>")
            continue

        # Markdown Tables: lines starting and ending with |
        if stripped.startswith("|") and stripped.endswith("|"):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            # Check if separator row (| :--- | :--- |)
            if re.match(r"^\|[\s:\-+|]+\|$", stripped):
                table_is_header = False
                continue

            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                html_lines.append("<div class='table-responsive'><table class='report-table'>")
                html_lines.append("<thead><tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr></thead><tbody>")
                in_table = True
                table_is_header = False
            else:
                html_lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        else:
            if in_table:
                html_lines.append("</tbody></table></div>")
                in_table = False

        # Headers
        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3 class='report-h3'>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2 class='report-h2'>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1 class='report-h1'>{stripped[2:]}</h1>")
        # Blockquotes
        elif stripped.startswith("&gt; "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<blockquote class='report-quote'>{stripped[5:]}</blockquote>")
        # Unordered Lists
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul class='report-list'>")
                in_list = True
            html_lines.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            # Check if placeholder
            if stripped.startswith("__CODE_BLOCK_"):
                html_lines.append(stripped)
            else:
                html_lines.append(f"<p class='report-p'>{stripped}</p>")

    if in_list:
        html_lines.append("</ul>")
    if in_table:
        html_lines.append("</tbody></table></div>")

    final_html = "\n".join(html_lines)

    # Restore code blocks
    for idx, block in enumerate(code_blocks):
        final_html = final_html.replace(f"__CODE_BLOCK_{idx}__", block)

    return final_html
