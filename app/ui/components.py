"""HTML Component builder for Backtrace Frontend UI.

Provides semantic, beautifully styled, server-rendered HTML components
with dark mode styling, glassmorphism, responsive cards, and clean typography.
"""

from __future__ import annotations

import html
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from app.formatters.graph_formatter import DOMAIN_COLOR_DEFS, DOMAIN_HEX_COLORS
from app.models.db import UserModel
from app.services.grading_engine import GradingEngine
from app.services.hint_engine import HintEngine
from app.services.piston_health import piston_health_monitor
from app.services.scaffold_generator import ScaffoldGenerator
from app.services.structural_verifier import StructuralVerifier
from app.core.config import billing_enabled, rewards_enabled
from app.ui.sanitizer import sanitize_text, render_safe_markdown, truncate_text_clean, render_user_markdown
from app.sequence.confidence_scoring import confidence_summary, ConfidenceSummary

SANDBOX_DISABLED_BANNER_TEXT = "Code execution is turned off on this free demo. Running user code safely needs an isolated sandbox server, which this host can't provide. Everything else works, and structure checks still run."


def _safe_script_json_dumps(obj: Any) -> str:
    """Serializes obj to a JSON string safe for embedding inside an HTML <script> block,
    escaping '<', '>', '&', and Unicode line/paragraph separators U+2028 and U+2029.
    """
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def format_time_tag(dt_obj: Any) -> str:
    """Outputs an ISO timestamp as <time datetime="ISO" title="UTC">UTC</time> with no microseconds.
    Client-side JavaScript rewrites inner text to toLocaleString() based on user browser locale.
    """
    if not dt_obj:
        return ""
    d: Optional[datetime] = None
    if isinstance(dt_obj, (int, float)):
        try:
            val = float(dt_obj)
            sec = val / 1000.0 if val > 1e11 else val
            d = datetime.fromtimestamp(sec, tz=timezone.utc)
        except Exception:
            return html.escape(str(dt_obj))
    elif isinstance(dt_obj, datetime):
        d = dt_obj
    elif isinstance(dt_obj, str):
        clean_str = dt_obj.strip()
        if not clean_str:
            return ""
        try:
            if clean_str.endswith(" UTC"):
                clean_str = clean_str[:-4].strip() + "+00:00"
            elif clean_str.endswith("Z"):
                clean_str = clean_str[:-1] + "+00:00"
            d = datetime.fromisoformat(clean_str)
        except Exception:
            return html.escape(clean_str)

    if d is not None and hasattr(d, "replace"):
        d = d.replace(microsecond=0)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        else:
            d = d.astimezone(timezone.utc)
        iso_str = d.isoformat()
        utc_str = d.strftime("%Y-%m-%d %H:%M:%S UTC")
        return f'<time datetime="{iso_str}" title="{utc_str}">{utc_str}</time>'
    return html.escape(str(dt_obj))


def get_narration_source(
    job: Any = None,
    raw_markdown: Optional[str] = None,
    graph_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Extracts narration source ('llm' or 'template') from job, graph_data, or markdown."""
    if graph_data and isinstance(graph_data, dict):
        src = graph_data.get("narration_source")
        if src in ("llm", "template"):
            return src
    if job:
        if isinstance(job, dict):
            src = job.get("narration_source")
            if src in ("llm", "template"):
                return src
            gd = job.get("graph_data")
            if isinstance(gd, dict) and gd.get("narration_source") in ("llm", "template"):
                return gd.get("narration_source")
        else:
            src = getattr(job, "narration_source", None)
            if src in ("llm", "template"):
                return src
            gd = getattr(job, "graph_data", None)
            if isinstance(gd, dict) and gd.get("narration_source") in ("llm", "template"):
                return gd.get("narration_source")
    md = raw_markdown or (getattr(job, "report_markdown", None) if job else None)
    if md and isinstance(md, str):
        match = re.search(r"<!--\s*narration_source:\s*(llm|template)\s*-->", md)
        if match:
            return match.group(1)
    return "template"


def get_narration_label(source: str) -> str:
    """Returns honest label based on narration source."""
    if source == "llm":
        return "LLM Step-by-Step Narration"
    return "Step-by-step narration"



def nav_shell(
    current_user: Optional[UserModel] = None,
    active_route: str = "",
    billing_status: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the persistent navigation header shell."""
    sun_icon_svg = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide-sun"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>'
    theme_toggle_html = f"""
        <button id="theme-toggle" class="theme-toggle-btn" onclick="toggleTheme()" type="button" aria-label="Switch to light theme" title="Switch to light theme">
            <span id="theme-toggle-icon">
                {sun_icon_svg}
            </span>
            <span id="theme-toggle-label" style="display: none;">Theme</span>
            <!-- aria-label="Toggle dark/light mode" -->
        </button>
    """

    if not current_user:
        sign_in_link = "" if active_route == "/login" else '<a href="/login" class="btn btn-sm btn-primary">Sign In</a>'
        return f"""
    <header class="nav-shell">
        <a href="/login" class="brand" id="nav-brand-link">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
            <span class="brand-title">Backtrace</span>
        </a>
        <div class="nav-right" style="display: flex; align-items: center; gap: 0.75rem;">
            {theme_toggle_html}
            {sign_in_link}
        </div>
    </header>
    """

    safe_username = sanitize_text(current_user.github_username or "User")
    avatar_html = (
        f'<img src="{sanitize_text(current_user.avatar_url)}" alt="Avatar" class="avatar" />'
        if current_user.avatar_url
        else '<div class="avatar-placeholder"></div>'
    )

    tier_tag = ""
    if billing_status:
        is_pro = (
            billing_status.get("tier") == "paid"
            or billing_status.get("is_pro", False)
            or billing_status.get("plan_tier") == "pro"
        )
        if is_pro:
            tier_tag = """
            <div class="tag" id="nav-tier-tag" style="display: inline-flex; align-items: center; gap: 0.35rem;">
                <span class="chip-dot brass"></span>
                <span style="font-family: var(--font-mono); font-size: 13px; font-weight: 600; color: var(--accent);">Pro</span>
            </div>
            """
        else:
            usage = billing_status.get("monthly_usage", billing_status.get("quota_used", 0))
            limit = billing_status.get("monthly_quota", billing_status.get("quota_limit", 5))
            tier_tag = f"""
            <div class="tag" id="nav-tier-tag" style="display: inline-flex; align-items: center; gap: 0.35rem;">
                <span class="chip-dot brass"></span>
                <span style="font-family: var(--font-mono); font-size: 13px; font-weight: 600; color: var(--accent);">Free ({usage} / {limit})</span>
                <!-- Free ({usage}/{limit}) -->
            </div>
            """

    dashboard_active = "active" if active_route == "/dashboard" else ""
    rewards_active = "active" if active_route in ("/rewards", "/points") else ""
    settings_active = "active" if active_route == "/settings" else ""
    rewards_aria = 'aria-current="page"' if rewards_active else ''

    rewards_nav_link = ""
    rewards_dropdown_link = ""
    if rewards_enabled():
        rewards_nav_link = f'\n                <a href="/rewards" class="nav-link {rewards_active}" id="nav-link-rewards" data-path="rewards" {rewards_aria}>Rewards & Badges</a>'
        rewards_dropdown_link = f'<a href="/rewards" class="dropdown-item" id="nav-dropdown-rewards" style="display: flex; align-items: center; gap: 8px; padding: 8px 14px; font-size: 13px; color: var(--text); text-decoration: none;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="7"></circle><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"></polyline></svg>Rewards &amp; Badges</a>'

    return f"""
    <header class="nav-shell">
        <div style="display: flex; align-items: center; gap: 1.25rem;">
            <a href="/dashboard" class="brand" id="nav-brand-link">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                <span class="brand-title">Backtrace</span>
            </a>
            {tier_tag}
        </div>

        <div style="display: flex; align-items: center; gap: 1.25rem;">
            <nav class="nav-links">
                <a href="/dashboard" class="nav-link {dashboard_active}" id="nav-link-dashboard" data-path="dashboard" {'aria-current="page"' if dashboard_active else ''}>Dashboard</a>{rewards_nav_link}
                <a href="/settings" class="nav-link {settings_active}" id="nav-link-settings" data-path="settings" {'aria-current="page"' if settings_active else ''}>Settings</a>
            </nav>

            <div class="nav-right" style="display: flex; align-items: center; gap: 0.75rem;">
                {theme_toggle_html}
                <div class="user-dropdown" style="position: relative;">
                    <button class="user-dropdown-btn" id="user-menu-btn" onclick="toggleUserDropdown()" aria-haspopup="true" aria-expanded="false" aria-label="User menu" type="button" style="display: flex; align-items: center; gap: 0.5rem; background: var(--surface-2); border: 1px solid var(--border); padding: 0.3rem 0.65rem; border-radius: var(--radius); cursor: pointer; color: var(--text);">
                        {avatar_html}
                        <span class="username" style="font-family: var(--font-ui); font-size: 13px; font-weight: 500; color: var(--text);">@{safe_username}</span>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    </button>
                    <div class="dropdown-menu" id="user-dropdown-menu" style="display: none; position: absolute; right: 0; top: calc(100% + 6px); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); min-width: 170px; box-shadow: 0 8px 24px rgba(0,0,0,0.3); z-index: 1000; padding: 6px 0;">
                        <div class="user-menu-mobile-links" style="display: none;">
                            <a href="/dashboard" class="dropdown-item" id="nav-dropdown-dashboard" style="display: flex; align-items: center; gap: 8px; padding: 8px 14px; font-size: 13px; color: var(--text); text-decoration: none;">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
                                Dashboard
                            </a>
                            {rewards_dropdown_link}
                            <div style="height: 1px; background: var(--border); margin: 4px 0;"></div>
                        </div>
                        <a href="/settings" class="dropdown-item" id="nav-dropdown-settings" style="display: flex; align-items: center; gap: 8px; padding: 8px 14px; font-size: 13px; color: var(--text); text-decoration: none;">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                            Settings
                        </a>
                        <div style="height: 1px; background: var(--border); margin: 4px 0;"></div>
                        <a href="/auth/logout" class="dropdown-item" id="nav-logout-btn" title="Sign Out of Backtrace" style="display: flex; align-items: center; gap: 8px; padding: 8px 14px; font-size: 13px; color: var(--danger); text-decoration: none;">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
                            Log out <!-- Sign Out of Backtrace -->
                        </a>
                    </div>
                </div>
            </div>
        </div>
    </header>
    """


def page_shell(
    title: str,
    content: str,
    current_user: Optional[UserModel] = None,
    active_route: str = "",
    billing_status: Optional[Dict[str, Any]] = None,
    extra_head: str = "",
    extra_scripts: str = "",
) -> str:
    """Wrap content in a clean, quiet Linear/Vercel-inspired dashboard layout."""
    rendered_nav = nav_shell(
        current_user=current_user,
        active_route=active_route,
        billing_status=billing_status,
    )

    clean_title = sanitize_text(title)
    if clean_title == "Dashboard":
        doc_title = '<title>Dashboard · Backtrace</title>'
    elif clean_title.startswith("Architecture Report: "):
        repo_part = clean_title.replace("Architecture Report: ", "")
        doc_title = f'<title>{repo_part} · Backtrace</title>'
    elif active_route == "/login" or title == "Backtrace - Understand any GitHub repository":
        doc_title = "<title>Backtrace - Understand any GitHub repository</title>"
    else:
        doc_title = f'<title>{clean_title} · Backtrace</title>'

    try:
        from app.core.config import get_settings
        cfg = get_settings()
        github_url = getattr(cfg, "FOOTER_GITHUB_URL", None)
        contact_email = getattr(cfg, "SUPPORT_EMAIL", None)
    except Exception:
        github_url = "https://github.com/SumitMahajan11/Backtrace"
        contact_email = "support@backtrace.dev"

    footer_parts = ["© 2026 Backtrace"]
    footer_parts.append('<a href="/privacy" style="color: var(--text-muted); text-decoration: none;">Privacy</a>')
    if billing_enabled():
        footer_parts.append('<a href="/pricing" style="color: var(--text-muted); text-decoration: none;">Pricing</a>')
    footer_parts.append('<a href="/support" style="color: var(--text-muted); text-decoration: none;">Support</a>')
    if github_url:
        footer_parts.append(f'<a href="{html.escape(github_url)}" target="_blank" rel="noopener noreferrer" style="color: var(--text-muted); text-decoration: none;">GitHub</a>')
    footer_links_html = ' · '.join(footer_parts)

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    {doc_title}
    <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
    <link rel="alternate icon" href="/favicon.svg">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="stylesheet" href="/static/highlight.min.css">
    <script src="/static/highlight.min.js"></script>
    {extra_head}
    <script>
        (function() {{
            const saved = localStorage.getItem('backtrace-theme');
            if (saved === 'light' || saved === 'dark') {{
                document.documentElement.setAttribute('data-theme', saved);
            }} else {{
                const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
            }}
        }})();
    </script>
    <style>
        /* ==========================================================================
           Clean Design System Tokens (Linear & Vercel Dashboard Look)
           ========================================================================== */
        :root {{{{
            --bg: #0f1115;
            --surface: #171a21;
            --surface-2: #1e222b;
            --border: #2a2f3a;
            --text: #e8eaf0;
            --text-muted: #9aa3b2;
            --accent: #4f8cff;
            --accent-strong: #2563eb;
            --danger: #ef5b5b;
            --success: #3ecf8e;
            --radius: 10px;
            --container: 960px;
            --font-ui: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
            --font-mono: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace;

            /* Backward compatibility aliases */
            --ink: var(--bg);
            --panel: var(--surface);
            --panel-raised: var(--surface-2);
            --panel-overlay: var(--surface-2);
            --panel-inset: var(--surface-2);
            --bg-card: var(--surface);
            --bg-surface: var(--surface-2);
            --hairline: var(--border);
            --hairline-soft: var(--border);
            --text-primary: var(--text);
            --text-secondary: var(--text-muted);
            --text-tertiary: var(--text-muted);
            --brass: var(--accent);
            --brass-hover: #3b76e1;
            --brass-soft: rgba(79, 140, 255, 0.12);
            --brass-border: rgba(79, 140, 255, 0.35);
            --teal: var(--accent);
            --teal-dim: #1d4ed8;
            --teal-soft: rgba(79, 140, 255, 0.12);
            --teal-border: rgba(79, 140, 255, 0.35);
            --amber: #f59e0b;
            --amber-soft: rgba(245, 158, 11, 0.12);
            --crimson: var(--danger);
            --crimson-soft: rgba(239, 91, 91, 0.12);
            --focus-ring: rgba(79, 140, 255, 0.45);
            color-scheme: dark;
        }}}}

        [data-theme="light"] {{{{
            --bg: #fafafa;
            --surface: #ffffff;
            --surface-2: #f3f4f6;
            --border: #e3e5ea;
            --text: #14161a;
            --text-muted: #5b6472;
            --accent: #2563eb;
            --accent-strong: #1d4ed8;
            --accent-strong: #2563eb;
            --danger: #ef5b5b;
            --success: #3ecf8e;
            --radius: 10px;
            --container: 960px;
            --font-ui: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
            --font-mono: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace;

            /* Backward compatibility aliases */
            --ink: var(--bg);
            --panel: var(--surface);
            --panel-raised: var(--surface-2);
            --panel-overlay: var(--surface-2);
            --panel-inset: var(--surface-2);
            --bg-card: var(--surface);
            --bg-surface: var(--surface-2);
            --hairline: var(--border);
            --hairline-soft: var(--border);
            --text-primary: var(--text);
            --text-secondary: var(--text-muted);
            --text-tertiary: var(--text-muted);
            --brass: var(--accent);
            --brass-hover: #3b76e1;
            --brass-soft: rgba(79, 140, 255, 0.1);
            --brass-border: rgba(79, 140, 255, 0.28);
            --teal: var(--accent);
            --teal-dim: #2563eb;
            --teal-soft: rgba(79, 140, 255, 0.1);
            --teal-border: rgba(79, 140, 255, 0.3);
            --amber: #d97706;
            --amber-soft: rgba(217, 119, 6, 0.12);
            --crimson: var(--danger);
            --crimson-soft: rgba(239, 91, 91, 0.12);
            --focus-ring: rgba(79, 140, 255, 0.35);
            color-scheme: light;
        }}}}

        /* Reset & Base Typography */
        *, *::before, *::after {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        /* High-Contrast Scrollbar for Code Viewers & Editors */
        .read-code-pre,
        .CodeMirror,
        .CodeMirror-scroll,
        .CodeMirror-vscrollbar,
        .CodeMirror-hscrollbar,
        pre.read-code-pre,
        pre,
        textarea {{{{
            scrollbar-width: thin;
            scrollbar-color: #525e75 #13171f;
        }}}}
        .read-code-pre::-webkit-scrollbar,
        .CodeMirror-scroll::-webkit-scrollbar,
        .CodeMirror-vscrollbar::-webkit-scrollbar,
        .CodeMirror-hscrollbar::-webkit-scrollbar,
        pre::-webkit-scrollbar,
        textarea::-webkit-scrollbar {{{{
            width: 9px;
            height: 9px;
        }}}}
        .read-code-pre::-webkit-scrollbar-track,
        .CodeMirror-scroll::-webkit-scrollbar-track,
        .CodeMirror-vscrollbar::-webkit-scrollbar-track,
        .CodeMirror-hscrollbar::-webkit-scrollbar-track,
        pre::-webkit-scrollbar-track,
        textarea::-webkit-scrollbar-track {{{{
            background: #111317;
            border-radius: 4px;
        }}}}
        .read-code-pre::-webkit-scrollbar-thumb,
        .CodeMirror-scroll::-webkit-scrollbar-thumb,
        .CodeMirror-vscrollbar::-webkit-scrollbar-thumb,
        .CodeMirror-hscrollbar::-webkit-scrollbar-thumb,
        pre::-webkit-scrollbar-thumb,
        textarea::-webkit-scrollbar-thumb {{{{
            background: #525e75;
            border: 1px solid #2d3748;
            border-radius: 4px;
        }}}}
        .read-code-pre::-webkit-scrollbar-thumb:hover,
        .CodeMirror-scroll::-webkit-scrollbar-thumb:hover,
        .CodeMirror-vscrollbar::-webkit-scrollbar-thumb:hover,
        .CodeMirror-hscrollbar::-webkit-scrollbar-thumb:hover,
        pre::-webkit-scrollbar-thumb:hover,
        textarea::-webkit-scrollbar-thumb:hover {{{{
            background: var(--accent);
            border-color: var(--brass-border);
        }}}}

        body {{
            background-color: var(--bg);
            color: var(--text);
            font-family: var(--font-ui);
            font-size: 15px;
            line-height: 1.6;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            transition: background-color 150ms ease, color 150ms ease;
            -webkit-font-smoothing: antialiased;
        }}

        h1, h2, h3, h4, .serif-heading {{
            font-family: var(--font-ui);
            font-weight: 600;
            color: var(--text);
            line-height: 1.3;
            letter-spacing: -0.01em;
        }}

        .brand-title {{
            font-family: "Newsreader", Georgia, serif;
            font-size: 1.25rem;
            font-weight: 500;
        }}

        code, pre, .mono, .file-path, table td.number {{
            font-family: var(--font-mono);
        }}

        a {{
            color: var(--accent);
            text-decoration: none;
            transition: color 120ms ease;
        }}

        a:hover {{
            color: #3b76e1;
        }}

        /* Navigation Header Shell */
        .nav-shell {{
            background: var(--surface-2);
            border-bottom: 1px solid var(--border);
            padding: 0.85rem 1.75rem;
            position: sticky;
            top: 0;
            z-index: 50;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}

        .brand {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            text-decoration: none;
            color: var(--text);
        }}

        .brand:hover {{
            color: var(--text);
        }}

        .brand-title {{
            font-family: 'Newsreader', Georgia, serif;
            font-size: 1.35rem;
            font-weight: 500;
            letter-spacing: -0.02em;
            color: var(--text);
        }}

        .brand-pill {{
            font-family: var(--font-ui);
            font-size: 0.8125rem;
            padding: 0.15rem 0.5rem;
            border-radius: 2px;
            background: var(--brass-soft);
            color: var(--accent);
            border: 1px solid var(--brass-border);
            }}

        .nav-links {{
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }}

        .nav-link {{
            font-family: var(--font-ui);
            font-size: 0.8125rem;
            font-weight: 500;
            color: var(--text-muted);
            padding: 0.4rem 0.85rem;
            border-radius: 4px;
            border: 1px solid transparent;
            text-decoration: none;
            transition: all 120ms ease;
            line-height: 1.25;
        }}

        .nav-link:hover {{
            color: var(--text);
            background: var(--panel-raised);
            border-color: var(--hairline-soft);
        }}

        .nav-link.active {{
            color: var(--accent);
            background: var(--brass-soft);
            border-color: var(--brass-border);
            font-weight: 600;
        }}

        .nav-right {{
            display: flex;
            align-items: center;
            gap: 0.85rem;
        }}

        .theme-toggle-btn {{
            background: var(--panel-raised);
            border: 1px solid var(--border);
            color: var(--text-muted);
            padding: 0.35rem 0.65rem;
            border-radius: 4px;
            font-family: var(--font-ui);
            font-size: 0.8125rem;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            transition: all 120ms ease;
        }}

        .theme-toggle-btn:hover {{
            background: var(--panel-overlay);
            color: var(--text);
            border-color: var(--border);
        }}

        .theme-toggle-btn:focus,
        .theme-toggle-btn:focus-visible {{
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 2px var(--focus-ring);
        }}

        .user-pill {{
            display: flex;
            align-items: center;
            gap: 0.65rem;
            background: var(--panel-raised);
            border: 1px solid var(--border);
            padding: 0.25rem 0.75rem;
            border-radius: 4px;
        }}

        .avatar {{
            width: 22px;
            height: 22px;
            border-radius: 50%;
            object-fit: cover;
            border: 1px solid var(--border);
        }}

        .avatar-placeholder {{
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: var(--border);
        }}

        .username {{
            font-size: 0.8125rem;
            font-weight: 500;
            color: var(--text);
        }}

        /* Container Layout */
        .container {{
            max-width: var(--container);
            margin: 0 auto;
            padding: 0 24px;
            width: 100%;
            flex: 1;
            box-sizing: border-box;
        }}

        .report-header, .report-tabs-nav {{
            position: sticky;
            top: 0;
            z-index: 90;
            background: var(--bg);
        }}

        /* Stratum Cards / Flat Containers */
        .stratum-card, .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: none;
            transition: border-color 120ms ease;
        }}

        .stratum-card:hover, .card:hover {{
            border-color: var(--border);
        }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.25rem;
            padding-bottom: 0.85rem;
            border-bottom: 1px solid var(--border);
        }}

        .card-divider {{
            border: none;
            border-top: 1px solid var(--border);
            margin: 1.25rem 0;
        }}

        /* Buttons */
        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            font-family: var(--font-ui);
            font-size: 14px;
            font-weight: 500;
            border-radius: var(--radius);
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 120ms ease;
            text-decoration: none;
            line-height: 1.4;
        }}

        .btn-primary {{
            background: var(--accent);
            color: #ffffff !important;
            border: 1px solid var(--accent);
        }}

        .btn-primary:hover {{
            background: #3b76e1;
            border-color: #3b76e1;
            color: #ffffff !important;
        }}

        .btn-secondary {{
            background: transparent;
            color: var(--text);
            border: 1px solid var(--border);
        }}

        .btn-secondary:hover {{
            background: var(--surface-2);
            border-color: var(--text-muted);
            color: var(--text);
        }}

        .btn-ghost {{
            background: transparent;
            color: var(--text-muted);
            border: 1px solid transparent;
        }}

        .btn-ghost:hover {{
            color: var(--text);
            background: var(--surface-2);
        }}

        .btn-sm {{
            padding: 0.35rem 0.75rem;
            font-size: 13px;
        }}

        .btn-danger {{
            background: transparent;
            color: var(--danger);
            border: 1px solid var(--danger);
        }}

        .btn-danger:hover {{
            background: var(--danger);
            color: #ffffff;
        }}

        /* Confidence Meter */
        .meter {{
            width: 100%;
            height: 4px;
            background: var(--border);
            border-radius: 2px;
            overflow: hidden;
            position: relative;
        }}

        .meter-fill {{
            height: 100%;
            border-radius: 2px;
            transition: width 300ms ease;
        }}

        .meter-fill.high {{
            background: var(--success);
        }}

        .meter-fill.medium {{
            background: var(--accent);
        }}

        .meter-fill.low {{
            background: var(--danger);
        }}

        /* Tags & Chips */
        .chip, .tag {{
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.2rem 0.55rem;
            border-radius: var(--radius);
            font-size: 13px;
            font-weight: 500;
            background: var(--surface-2);
            border: 1px solid var(--border);
            color: var(--text-muted);
        }}

        .chip-dot {{
            width: 6px;
            height: 6px;
            border-radius: 50%;
        }}

        .chip-dot.teal, .chip-dot.brass {{ background: var(--accent); }}
        .chip-dot.amber {{ background: #f59e0b; }}
        .chip-dot.crimson {{ background: var(--danger); }}

        /* Badges for real status only */
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.2rem 0.55rem;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 500;
            background: var(--surface-2);
            border: 1px solid var(--border);
            color: var(--text-muted);
        }}

        .badge-free {{
            background: var(--surface-2);
            color: var(--text-muted);
            border: 1px solid var(--border);
        }}

        .badge-paid, .badge-brass {{
            background: rgba(79, 140, 255, 0.12);
            color: var(--accent);
            border: 1px solid rgba(79, 140, 255, 0.3);
        }}

        .badge-completed, .badge-teal, .badge-done, .status-done {{
            background: rgba(62, 207, 142, 0.12);
            color: var(--success);
            border: 1px solid rgba(62, 207, 142, 0.3);
        }}

        .badge-running, .status-running {{
            background: rgba(79, 140, 255, 0.12);
            color: var(--accent);
            border: 1px solid rgba(79, 140, 255, 0.3);
        }}

        .badge-failed, .badge-crimson, .status-failed {{
            background: rgba(239, 91, 91, 0.12);
            color: var(--danger);
            border: 1px solid rgba(239, 91, 91, 0.3);
        }}

        .badge-pending, .badge-queued, .badge-amber, .status-pending, .status-queued {{
            background: var(--surface-2);
            color: var(--text-muted);
            border: 1px solid var(--border);
        }}

        .skeleton {{
            background: var(--surface-2);
            border-radius: var(--radius);
            animation: pulse 1.5s infinite ease-in-out;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.45; }}
        }}

        /* Graph Legend Styles */
        #dag-legend-panel {{
            transition: all 150ms ease;
        }}
        .legend-chip {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-family: var(--font-ui);
            font-size: 0.8125rem;
            color: var(--text-muted);
            background: var(--surface-2);
            border: 1px solid var(--hairline-soft);
            border-radius: 3px;
            padding: 0.2rem 0.5rem;
            transition: all 120ms ease;
        }}
        .legend-chip:hover {{
            border-color: var(--accent);
            background: var(--panel-raised);
        }}

        /* Confidence Tooltip & Info Affordance */
        .tooltip-container {{
            position: relative;
            display: inline-flex;
            align-items: center;
        }}

        .info-icon-btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 15px;
            height: 15px;
            border-radius: 50%;
            background: var(--panel-raised);
            border: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 0.8125rem;
            font-family: var(--font-ui);
            font-weight: 600;
            cursor: pointer;
            margin-left: 0.35rem;
            transition: all 150ms ease;
            user-select: none;
            line-height: 1;
            padding: 0;
            outline: none;
        }}

        .info-icon-btn:hover, .info-icon-btn:focus {{
            color: var(--text);
            border-color: var(--accent);
            background: var(--brass-soft);
        }}

        .confidence-tooltip {{
            visibility: hidden;
            opacity: 0;
            position: absolute;
            bottom: calc(100% + 8px);
            left: 50%;
            transform: translateX(-50%) translateY(4px);
            width: 290px;
            background: var(--panel-raised);
            color: var(--text-muted);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 0.75rem 0.85rem;
            font-size: 0.8125rem;
            font-family: 'IBM Plex Sans', sans-serif;
            line-height: 1.45;
            box-shadow: 0 6px 20px rgba(0,0,0,0.3);
            z-index: 1000;
            pointer-events: none;
            transition: opacity 150ms ease, transform 150ms ease, visibility 150ms;
            text-transform: none;
            font-weight: normal;
            text-align: left;
        }}

        .confidence-tooltip::after {{
            content: '';
            position: absolute;
            top: 100%;
            left: 50%;
            margin-left: -5px;
            border-width: 5px;
            border-style: solid;
            border-color: var(--panel-raised) transparent transparent transparent;
        }}

        .info-icon-btn[aria-expanded="true"] + .confidence-tooltip,
        .confidence-tooltip.is-open {{
            visibility: visible !important;
            opacity: 1 !important;
            transform: translateX(-50%) translateY(0) !important;
            pointer-events: auto !important;
        }}

        /* Form Controls */
        .form-group {{
            margin-bottom: 1.25rem;
        }}

        .form-label {{
            display: block;
            margin-bottom: 0.4rem;
            font-size: 0.8125rem;
            font-weight: 600;
            color: var(--text-muted);
            font-family: 'IBM Plex Sans', sans-serif;
        }}

        .form-input {{
            width: 100%;
            background: var(--panel-raised);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 0.65rem 0.95rem;
            color: var(--text);
            font-family: 'IBM Plex Sans', sans-serif;
            font-size: 0.9375rem;
            outline: none;
            transition: border-color 120ms ease, box-shadow 120ms ease;
        }}

        .form-input:focus {{
            border-color: var(--accent);
            box-shadow: 0 0 0 2px var(--focus-ring);
        }}

        .form-input::placeholder {{
            color: var(--text-muted);
        }}

        /* Table Styling */
        .table-responsive {{
            overflow-x: auto;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}

        th {{
            color: var(--text-muted);
            font-family: var(--font-ui);
            font-size: 0.8125rem;
            font-weight: 500;
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--border);
        }}

        td {{
            padding: 0.85rem 1rem;
            border-bottom: 1px solid var(--hairline-soft);
            font-size: 0.875rem;
        }}

        tr:hover td {{
            background: var(--panel-raised);
        }}

        /* Alerts */
        .alert-error {{
            background: var(--crimson-soft);
            border: 1px solid var(--crimson);
            color: var(--crimson);
            padding: 0.85rem 1.15rem;
            border-radius: 4px;
            margin-bottom: 1.25rem;
            font-size: 0.875rem;
        }}

        .alert-success {{
            background: var(--teal-soft);
            border: 1px solid var(--success);
            color: var(--success);
            padding: 0.85rem 1.15rem;
            border-radius: 4px;
            margin-bottom: 1.25rem;
            font-size: 0.875rem;
        }}

        /* Markdown / Report Styling */
        .markdown-body {{
            line-height: 1.7;
            color: var(--text);
        }}

        .markdown-body h1, .markdown-body h2, .markdown-body h3 {{
            color: var(--text);
            margin-top: 1.75rem;
            margin-bottom: 0.75rem;
            font-family: var(--font-ui);
            font-weight: 500;
        }}

        .markdown-body h1 {{ font-size: 1.85rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
        .markdown-body h2 {{ font-size: 1.45rem; }}
        .markdown-body h3 {{ font-size: 1.2rem; }}
        .markdown-body p {{ margin-bottom: 1rem; }}
        .markdown-body ul, .markdown-body ol {{ margin-left: 1.5rem; margin-bottom: 1rem; }}

        .markdown-body code {{
            background: var(--panel-raised);
            padding: 0.2rem 0.4rem;
            border-radius: 3px;
            font-family: var(--font-ui);
            font-size: 0.8125rem;
            color: var(--accent);
            border: 1px solid var(--hairline-soft);
        }}

        .markdown-body pre {{
            background: var(--ink);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 1.25rem;
            overflow-x: auto;
            margin-bottom: 1.5rem;
        }}

        .markdown-body pre code {{
            background: transparent;
            padding: 0;
            border: none;
            color: var(--text);
        }}

        /* Footer */
        .footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            font-family: var(--font-ui);
            font-size: 0.8125rem;
            border-top: 1px solid var(--border);
        }}

        /* Accessibility & Responsive Refinements */
        :focus-visible {{
            outline: 2px solid var(--accent);
            outline-offset: 2px;
        }}

        @media (max-width: 600px) {{
            button,
            .btn,
            .btn-primary,
            .btn-secondary,
            .btn-ghost,
            input[type="button"],
            input[type="submit"],
            .radio-row,
            .quiz-option-row,
            label:has(input[type="radio"]),
            label.radio-row,
            [role="button"],
            .theme-toggle-btn {{
                min-height: 44px;
                display: inline-flex;
                align-items: center;
            }}
        }}

        @media (max-width: 768px) {{
            html, body {{
                overflow-x: hidden;
                width: 100%;
                max-width: 100vw;
            }}

            .nav-shell {{
                padding: 0.75rem 1rem;
                flex-direction: column;
                align-items: stretch;
                gap: 0.75rem;
            }}

            .nav-shell > div {{
                justify-content: space-between;
                width: 100%;
                flex-wrap: wrap;
                gap: 0.5rem;
            }}

            .container {{
                padding: 1.25rem 0.75rem;
                max-width: 100vw;
                box-sizing: border-box;
            }}

            .stratum-card, .card {{
                padding: 1.25rem 1rem;
                min-width: 0 !important;
                max-width: 100% !important;
                box-sizing: border-box;
            }}

            .card-header {{
                flex-direction: column;
                align-items: flex-start;
                gap: 0.5rem;
            }}

            .table-responsive {{
                width: 100%;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
                display: block;
            }}

            form div[style*="grid-template-columns"] {{
                grid-template-columns: 1fr !important;
            }}

            div[style*="min-width: 280px"], div[style*="min-width: 320px"] {{
                min-width: 0 !important;
                width: 100% !important;
            }}

            .matrix-grid, .plan-comparison-grid {{
                grid-template-columns: 1fr !important;
            }}

            .milestone-item {{
                flex-direction: column !important;
                gap: 0.75rem !important;
            }}

            .milestone-body {{
                width: 100% !important;
                box-sizing: border-box !important;
                padding: 1rem 0.75rem !important;
            }}

            .editor-surface-container {{
                max-width: 100% !important;
                overflow-x: auto !important;
            }}

            .hint-confirm-box, .reveal-confirm-box, .hint-panel, .reference-panel {{
                padding: 0.75rem 0.85rem !important;
            }}
        }}

        .guess-instruction-banner p, .fill-instruction-banner p {{
            display: inline;
            margin: 0;
        }}
        .quiz-card p {{
            margin: 0 0 0.5rem 0;
        }}
        .quiz-card label span p {{
            display: inline;
            margin: 0;
        }}
        .brief-objective-section p {{
            margin: 0 0 0.4rem 0;
        }}
        .brief-objective-section p:last-child {{
            margin-bottom: 0;
        }}

        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
                scroll-behavior: auto !important;
            }}
        }}
    </style>
    {extra_head}
</head>
<body>
    <div id="cold-start-banner" style="display: none; width: 100%; background: var(--amber, #f59e0b); color: #0d0f12; padding: 0.65rem 1rem; text-align: center; font-weight: 600; font-size: 0.875rem; position: sticky; top: 0; z-index: 99999; box-shadow: 0 2px 8px rgba(0,0,0,0.25);">
        Waking up the server, this can take up to a minute…
    </div>
    {rendered_nav}
    <main class="container">
        {content}
    </main>
    <footer class="footer" style="padding: 2rem 0; border-top: 1px solid var(--border); margin-top: auto; text-align: center; font-size: 13px; color: var(--text-muted);">
        <div class="container" style="display: flex; justify-content: center; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
            {footer_links_html}
        </div>
    </footer>
    <script>
        function toggleTheme() {{
            const current = document.documentElement.getAttribute('data-theme') || 'dark';
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('backtrace-theme', next);
            updateThemeControls(next);
        }}

        function updateThemeControls(theme) {{
            const btn = document.getElementById('theme-toggle');
            const icon = document.getElementById('theme-toggle-icon');
            const isDark = (theme === 'dark');
            if (btn) {{
                btn.setAttribute('aria-label', isDark ? 'Switch to light theme' : 'Switch to dark theme');
                btn.setAttribute('title', isDark ? 'Switch to light theme' : 'Switch to dark theme');
            }}
            if (icon) {{
                icon.innerHTML = isDark
                    ? '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide-sun"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>'
                    : '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide-moon"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>';
            }}
            if (typeof updateThemeCards === 'function') {{
                updateThemeCards();
            }}
        }}

        function toggleUserDropdown() {{
            const menu = document.getElementById('user-dropdown-menu');
            const btn = document.getElementById('user-menu-btn');
            if (!menu) return;
            const isExpanded = menu.style.display === 'block';
            menu.style.display = isExpanded ? 'none' : 'block';
            if (btn) btn.setAttribute('aria-expanded', !isExpanded);
        }}

        document.addEventListener('click', function(e) {{
            const dropdown = document.querySelector('.user-dropdown');
            const menu = document.getElementById('user-dropdown-menu');
            if (dropdown && menu && !dropdown.contains(e.target)) {{
                menu.style.display = 'none';
                const btn = document.getElementById('user-menu-btn');
                if (btn) btn.setAttribute('aria-expanded', 'false');
            }}
        }});

        document.addEventListener('DOMContentLoaded', function() {{
            const current = document.documentElement.getAttribute('data-theme') || 'dark';
            updateThemeControls(current);
            document.querySelectorAll('time[datetime]').forEach(function(el) {{
                const dt = new Date(el.getAttribute('datetime'));
                if (!isNaN(dt.getTime())) {{
                    el.textContent = dt.toLocaleString();
                }}
            }});
        }});

        (function() {{
            var coldStartTimer = setTimeout(function() {{
                var banner = document.getElementById('cold-start-banner');
                if (banner) banner.style.display = 'block';
            }}, 3000);

            fetch('/healthz')
                .then(function() {{
                    clearTimeout(coldStartTimer);
                    var banner = document.getElementById('cold-start-banner');
                    if (banner) banner.style.display = 'none';
                }})
                .catch(function() {{
                    clearTimeout(coldStartTimer);
                    var banner = document.getElementById('cold-start-banner');
                    if (banner) banner.style.display = 'none';
                }});
        }})();
    </script>
    {extra_scripts}
</body>
</html>
"""


def login_view(error: Optional[str] = None) -> str:
    """Render the Clean Login View with GitHub OAuth adhering to accessibility and clarity standards."""
    error_html = f'<div class="alert-error" style="margin-bottom: 1.25rem;">{sanitize_text(error)}</div>' if error else ""
    content = f"""
    <div style="max-width: 440px; margin: 4rem auto 0 auto; text-align: center;">
        <div class="card stratum-card" style="padding: 2.5rem 2rem; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);">
            <div style="margin-bottom: 1.75rem;">
                <div style="display: inline-flex; align-items: center; justify-content: center; width: 52px; height: 52px; background: rgba(79, 140, 255, 0.12); border: 1px solid rgba(79, 140, 255, 0.35); border-radius: var(--radius); margin-bottom: 1.25rem;">
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2">
                        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                        <polyline points="2 17 12 22 22 17"></polyline>
                        <polyline points="2 12 12 17 22 12"></polyline>
                    </svg>
                </div>
                <h1 style="font-size: 1.75rem; font-weight: 600; color: var(--text); margin: 0 0 0.75rem 0; letter-spacing: -0.02em; line-height: 1.25;">Understand any codebase without reading every file.</h1>
                <p style="color: var(--text-muted); font-size: 0.9375rem; line-height: 1.5; margin: 0;">Turn complex GitHub repositories into clear, guided walkthroughs you can actually learn from.</p>
            </div>
            <ul style="text-align: left; margin: 0 0 1.75rem 0; padding-left: 1.25rem; color: var(--text); font-size: 0.875rem; line-height: 1.6;">
                <li style="margin-bottom: 0.45rem;">See how all files and modules connect in a visual map.</li>
                <li style="margin-bottom: 0.45rem;">Read clear explanations of how the code works step by step.</li>
                <li>Practice what you learn with quick quizzes and coding tasks.</li>
            </ul>
            {error_html}
            <a href="/auth/github/login" class="btn btn-primary" id="github-signin-btn" style="width: 100%; justify-content: center; padding: 0.8rem; font-size: 0.95rem; display: inline-flex; align-items: center; gap: 0.6rem;">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                    <path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"></path>
                </svg>
                Sign in with GitHub
            </a>
            <div style="margin-top: 1rem;">
                <a href="/showcase" style="font-size: 0.85rem; color: var(--accent); text-decoration: none; font-weight: 500;">
                    View a sample report &rarr;
                </a>
            </div>
            <div style="margin-top: 1.5rem; font-size: 0.8125rem; color: var(--text-muted); line-height: 1.4;">
                Repository files are stored with secrets scanned and redacted (best effort) and deleted after 30 days. Reports are kept until you ask us to delete them. <a href="/privacy" style="color: var(--text); text-decoration: underline;">Privacy Policy</a>
            </div>
        </div>
    </div>
    """
    extra_head = """
    <meta name="description" content="Understand any codebase without reading every file.">
    <meta property="og:title" content="Backtrace - Understand any GitHub repository">
    <meta property="og:description" content="Understand any codebase without reading every file.">
    <meta property="og:type" content="website">
    """
    return page_shell(
        "Backtrace - Understand any GitHub repository",
        content,
        active_route="/login",
        extra_head=extra_head,
    )


def showcase_view(
    jobs: List[Any],
    current_user: Optional[UserModel] = None,
) -> str:
    """Render the public showcase directory view."""
    if not jobs:
        items_html = """
        <div style="padding: 2.5rem 1rem; text-align: center; color: var(--text-muted); font-size: 0.95rem;">
            <p style="margin-bottom: 1.25rem;">Sample reports are coming soon.</p>
            <a href="/login" class="btn btn-sm btn-secondary" style="font-family: var(--font-ui); font-size: 0.8125rem;">
                &larr; Back to Login
            </a>
        </div>
        """
    else:
        rows_html = ""
        for job in jobs:
            job_id = getattr(job, "id", None) if hasattr(job, "id") else (job.get("id") if isinstance(job, dict) else 0)
            repo_name = sanitize_text(getattr(job, "repo_name", None) if hasattr(job, "repo_name") else (job.get("repo_name", "Repository") if isinstance(job, dict) else "Repository"))
            rows_html += f"""
            <li class="showcase-item" style="display: flex; align-items: center; justify-content: space-between; padding: 1rem 1.25rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 0.75rem;">
                <span class="showcase-repo-name" style="font-weight: 600; font-size: 1rem; color: var(--text);">{repo_name}</span>
                <a href="/report/{job_id}" class="btn btn-sm btn-secondary showcase-link" style="font-family: var(--font-ui); font-size: 0.8125rem;">
                    View Architecture Report &rarr;
                </a>
            </li>
            """
        items_html = f"""
        <ul class="showcase-list" style="list-style: none; padding: 0; margin: 0;">
            {rows_html}
        </ul>
        """

    content = f"""
    <div style="max-width: 800px; margin: 3rem auto 0 auto; padding: 0 1rem;">
        <div class="stratum-card" style="padding: 2rem 2.25rem;">
            <div style="margin-bottom: 1.5rem; border-bottom: 1px solid var(--border); padding-bottom: 1rem;">
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                    Public Dossier Showcase
                </div>
                <h1 style="font-size: 1.75rem; font-weight: 500; margin-top: 0.25rem; letter-spacing: -0.02em;">
                    Featured Repository Architectures
                </h1>
                <p style="color: var(--text-muted); font-size: 0.875rem; line-height: 1.5; margin-top: 0.35rem;">
                    Curated public showcase of reverse-engineered software architectures.
                </p>
            </div>
            {items_html}
        </div>
    </div>
    """
    extra_head = """
    <meta name="description" content="Understand any codebase without reading every file.">
    <meta property="og:title" content="Backtrace - Featured Repository Architectures">
    <meta property="og:description" content="Understand any codebase without reading every file.">
    <meta property="og:type" content="website">
    """
    return page_shell(
        "Showcase Directory",
        content,
        current_user=current_user,
        active_route="/showcase",
        extra_head=extra_head,
    )


def privacy_view(current_user: Optional[UserModel] = None) -> str:
    """Render the public Privacy Policy page."""
    try:
        from app.core.config import get_settings
        cfg = get_settings()
        support_email = getattr(cfg, "SUPPORT_EMAIL", None) or "support@backtrace.dev"
    except Exception:
        support_email = "support@backtrace.dev"

    content = f"""
    <div style="max-width: 760px; margin: 3rem auto 0 auto; padding: 0 1rem;">
        <div class="stratum-card" style="padding: 2.5rem 2.25rem;">
            <div style="margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 1.25rem;">
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                    Policy Dossier
                </div>
                <h1 style="font-size: 2rem; font-weight: 500; margin-top: 0.25rem; letter-spacing: -0.02em;">
                    Privacy Policy
                </h1>
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.5rem;">
                    Last updated October 24, 2026
                </div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 2rem; font-size: 0.925rem; line-height: 1.6; color: var(--text-muted);">
                <section>
                    <h2 style="font-size: 1.25rem; color: var(--text); margin-bottom: 0.5rem; font-weight: 600;">What data is stored</h2>
                    <p style="margin-bottom: 0.75rem;">
                        Backtrace stores only the essential data needed to provide repository architecture analysis, interactive milestones, and progress tracking:
                    </p>
                    <ul style="margin-left: 1.25rem; margin-bottom: 0.75rem;">
                        <li><strong>GitHub username</strong>: Used for account identification and repository analysis attribution.</li>
                        <li><strong>Email</strong>: Your primary verified email synced via GitHub OAuth.</li>
                        <li><strong>Analysis results</strong>: Cloned repository metadata, synthesized architecture reports, interactive dependency graphs, milestone progress, and quiz scores.</li>
                    </ul>
                </section>

                <section>
                    <h2 style="font-size: 1.25rem; color: var(--text); margin-bottom: 0.5rem; font-weight: 600;">How long data is kept</h2>
                    <p>
                        Repository file text is deleted automatically after 30 days (showcase repos are kept). Reports, graphs, your submitted milestone code and run output are kept until you ask for deletion.
                    </p>
                </section>

                <section>
                    <h2 style="font-size: 1.25rem; color: var(--text); margin-bottom: 0.5rem; font-weight: 600;">Who processes your code</h2>
                    <p>
                        Analysis algorithms parse structural abstract syntax trees (AST), imports, and symbol exports locally in sandbox environments. When AI explanations are requested, code summaries are processed strictly via enterprise API endpoints without model training.
                    </p>
                </section>

                <section>
                    <h2 style="font-size: 1.25rem; color: var(--text); margin-bottom: 0.5rem; font-weight: 600;">GitHub permissions</h2>
                    <p>
                        Backtrace only requests minimal read access to your public GitHub profile and verified email address for authentication. We never request write permissions to your repositories.
                    </p>
                </section>

                <section>
                    <h2 style="font-size: 1.25rem; color: var(--text); margin-bottom: 0.5rem; font-weight: 600;">Deleting your data</h2>
                    <p style="margin-bottom: 0.75rem;">
                        You have complete control over your account. You can export or permanently delete all your data at any time:
                    </p>
                    <p style="margin-bottom: 0.75rem;">
                        Navigate to your <a href="/settings" style="color: var(--success); text-decoration: underline; font-weight: 500;">Settings</a> and click the <strong>Delete my account</strong> button. To delete your data, open an issue or contact support if you need manual assistance.
                    </p>
                </section>

                <section>
                    <h2 style="font-size: 1.25rem; color: var(--text); margin-bottom: 0.5rem; font-weight: 600;">Contact &amp; Privacy Requests</h2>
                    <p>
                        For any privacy inquiries or assistance, email us at <a href="mailto:{html.escape(support_email)}" id="privacy-support-email" style="color: var(--success); text-decoration: underline; font-weight: 500;">{html.escape(support_email)}</a>.
                    </p>
                </section>
            </div>
        </div>
    </div>
    """
    return page_shell("Privacy Policy", content, current_user=current_user, active_route="/privacy")


def support_view(current_user: Optional[UserModel] = None) -> str:
    """Render the public Support and Contact page."""
    try:
        from app.core.config import get_settings
        cfg = get_settings()
        support_email = getattr(cfg, "SUPPORT_EMAIL", None) or "support@backtrace.dev"
        github_url = getattr(cfg, "FOOTER_GITHUB_URL", None) or "https://github.com/SumitMahajan11/Backtrace"
    except Exception:
        support_email = "support@backtrace.dev"
        github_url = "https://github.com/SumitMahajan11/Backtrace"

    content = f"""
    <div style="max-width: 760px; margin: 3rem auto 0 auto; padding: 0 1rem;">
        <div class="stratum-card" style="padding: 2.5rem 2.25rem;">
            <div style="margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 1.25rem;">
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                    Help & Support
                </div>
                <h1 style="font-size: 2rem; font-weight: 500; margin-top: 0.25rem; letter-spacing: -0.02em;">
                    Support &amp; Assistance
                </h1>
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.5rem;">
                    We are here to help you understand complex software architectures.
                </div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 2rem; font-size: 0.95rem; line-height: 1.6; color: var(--text-muted);">
                <section>
                    <h2 style="font-size: 1.15rem; color: var(--text); margin-bottom: 0.5rem; font-weight: 600;">Contact Us</h2>
                    <p style="margin-bottom: 0.75rem;">
                        For technical support, questions about repository analysis, or billing assistance, email our support team directly:
                    </p>
                    <p>
                        <a href="mailto:{html.escape(support_email)}" id="support-email-link" style="font-family: var(--font-ui); font-size: 1.05rem; color: var(--success); font-weight: 600; text-decoration: underline;">
                            {html.escape(support_email)}
                        </a>
                    </p>
                </section>

                <section>
                    <h2 style="font-size: 1.15rem; color: var(--text); margin-bottom: 0.5rem; font-weight: 600;">Bug Reports &amp; Feature Requests</h2>
                    <p style="margin-bottom: 0.75rem;">
                        Encountered a bug or have a suggestion? Open an issue on our GitHub tracker:
                    </p>
                    <p>
                        <a href="{html.escape(github_url)}/issues" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" style="display: inline-flex; align-items: center; gap: 0.5rem;">
                            GitHub Issues Tracker &rarr;
                        </a>
                    </p>
                </section>

                <section>
                    <h2 style="font-size: 1.15rem; color: var(--text); margin-bottom: 0.5rem; font-weight: 600;">Data Export &amp; Account Deletion</h2>
                    <p>
                        You can download a complete JSON export of your data or permanently delete your account at any time in <a href="/settings" style="color: var(--accent); text-decoration: underline;">Settings</a>.
                    </p>
                </section>
            </div>
        </div>
    </div>
    """
    return page_shell("Support", content, current_user=current_user, active_route="/support")


def pricing_view(current_user: Optional[UserModel] = None) -> str:
    """Render the public Pricing and Limits page."""
    from app.services.ingestion import get_max_repo_mb, MAX_REPO_FILE_LIMIT_V1
    enforced_mb = get_max_repo_mb()
    enforced_files = MAX_REPO_FILE_LIMIT_V1

    cta_href = "/dashboard" if current_user else "/login"
    content = f"""
    <div style="max-width: 840px; margin: 3rem auto 0 auto; padding: 0 1rem;">
        <div class="stratum-card" style="padding: 2.5rem 2.25rem;">
            <div style="margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 1.25rem; text-align: center;">
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                    Plan Limits &amp; Subscriptions
                </div>
                <h1 style="font-size: 2rem; font-weight: 500; margin-top: 0.25rem; letter-spacing: -0.02em;">
                    Pricing &amp; Limits
                </h1>
                <p style="color: var(--text-muted); font-size: 0.95rem; margin-top: 0.5rem;">
                    Clear, transparent plan limits for reverse-engineering repository architecture.
                </p>
            </div>

            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.75rem; margin-bottom: 2rem;">
                <!-- Free Plan -->
                <div style="background: var(--panel-raised); border: 1px solid var(--border); border-radius: 4px; padding: 2rem 1.75rem; display: flex; flex-direction: column; justify-content: space-between;">
                    <div>
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); ">Tier</div>
                        <h2 style="font-size: 1.5rem; font-weight: 600; margin: 0.25rem 0 1rem 0; color: var(--text);">Free Plan</h2>
                        <ul style="list-style: none; padding: 0; margin: 0 0 1.5rem 0; font-size: 0.9rem; line-height: 1.8; color: var(--text-muted);">
                            <li>&check; <strong>5 repository analyses</strong> per month</li>
                            <li>&check; <strong>{enforced_mb} MB</strong> repository size cap</li>
                            <li>&check; <strong>{enforced_files} supported files</strong> cap</li>
                        </ul>
                    </div>
                    <a href="{cta_href}" class="btn btn-secondary" style="width: 100%; justify-content: center; font-size: 0.9rem;">
                        Get Started
                    </a>
                </div>

                <!-- Pro Plan -->
                <div style="background: var(--panel-raised); border: 1px solid var(--brass-border); border-radius: 4px; padding: 2rem 1.75rem; display: flex; flex-direction: column; justify-content: space-between; position: relative;">
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); font-weight: 600;">Monthly Subscription</div>
                            <span class="badge" style="background: var(--surface-2); color: var(--text-muted); font-family: var(--font-ui); font-size: 0.8125rem; padding: 0.15rem 0.45rem; border: 1px solid var(--border); border-radius: 3px;">Coming soon</span>
                        </div>
                        <h2 style="font-size: 1.5rem; font-weight: 600; margin: 0.25rem 0 1rem 0; color: var(--text);">Pro Plan</h2>
                        <ul style="list-style: none; padding: 0; margin: 0 0 1.5rem 0; font-size: 0.9rem; line-height: 1.8; color: var(--text-muted);">
                            <li>&check; <strong>Unlimited repository analyses</strong></li>
                            <li>&check; Bypasses standard monthly quota</li>
                        </ul>
                    </div>
                    <button class="btn btn-secondary" disabled style="width: 100%; justify-content: center; font-size: 0.9rem; opacity: 0.6; cursor: not-allowed;">
                        Coming soon
                    </button>
                </div>
            </div>
        </div>
    </div>
    """
    return page_shell("Pricing and Limits", content, current_user=current_user, active_route="/pricing")


DASHBOARD_INLINE_JS = """
<script>
    // Sample chip click to fill input
    document.querySelectorAll('.sample-chip, [data-repo]').forEach(function(chip) {
        chip.addEventListener('click', function(e) {
            e.preventDefault();
            var repoUrl = this.getAttribute('data-repo') || 'https://github.com/expressjs/express';
            var input = document.getElementById('repo-url-input');
            if (input) {
                input.value = repoUrl;
                input.focus();
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });
    });

    // Client-side search filtering by repo name
    var searchInput = document.getElementById('repo-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            var q = this.value.toLowerCase().trim();
            var rows = document.querySelectorAll('.history-row, .history-card');
            rows.forEach(function(row) {
                var name = (row.getAttribute('data-repo-name') || '').toLowerCase();
                var url = (row.getAttribute('data-repo-url') || '').toLowerCase();
                if (!q || name.indexOf(q) !== -1 || url.indexOf(q) !== -1) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        });
    }

    // Overflow menu toggle
    function toggleRowMenu(e, menuId) {
        e.stopPropagation();
        var menu = document.getElementById(menuId);
        var isVisible = menu && menu.style.display === 'block';
        document.querySelectorAll('.row-menu-dropdown').forEach(function(m) {
            m.style.display = 'none';
        });
        if (menu && !isVisible) {
            menu.style.display = 'block';
        }
    }
    document.addEventListener('click', function() {
        document.querySelectorAll('.row-menu-dropdown').forEach(function(m) {
            m.style.display = 'none';
        });
    });

    // Inline validation for repository URL input
    var form = document.getElementById('reconstruct-form');
    var repoInput = document.getElementById('repo-url-input');
    if (form && repoInput) {
        repoInput.addEventListener('input', function() {
            var errEl = document.getElementById('repo-url-error');
            if (errEl) {
                errEl.style.display = 'none';
            }
            repoInput.removeAttribute('aria-invalid');
            repoInput.removeAttribute('aria-describedby');
            repoInput.style.borderColor = '';
        });

        form.addEventListener('submit', function(e) {
            var val = (repoInput.value || '').trim();
            var isValid = /^https:\\/\\/github\\.com\\/[^\\/\\s]+\\/[^\\/\\s]+(?:\\/.*)?$/.test(val);
            if (!isValid) {
                e.preventDefault();
                var errEl = document.getElementById('repo-url-error');
                if (!errEl) {
                    errEl = document.createElement('div');
                    errEl.id = 'repo-url-error';
                    errEl.className = 'input-error-inline';
                    errEl.style.color = 'var(--danger)';
                    errEl.style.fontSize = '0.8125rem';
                    errEl.style.marginTop = '0.45rem';
                    errEl.style.display = 'flex';
                    errEl.style.alignItems = 'center';
                    errEl.style.gap = '0.35rem';
                    errEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg><span>That doesn\\\'t look like a GitHub repository link.</span>';
                    repoInput.parentNode.appendChild(errEl);
                } else {
                    errEl.style.display = 'flex';
                }
                repoInput.setAttribute('aria-invalid', 'true');
                repoInput.setAttribute('aria-describedby', 'repo-url-error');
                repoInput.style.borderColor = 'var(--danger)';
                repoInput.focus();
            }
        });
    }
</script>
"""


def failure_reason(error_message: Optional[str]) -> str:
    """Map raw job error message to one of three clean user-facing sentences."""
    if not error_message:
        return "Something went wrong on our side"
    err = str(error_message).lower()
    if any(k in err for k in ["auth", "access", "private", "not found", "404", "403", "permission", "clone", "could not resolve", "fatal: repository", "fatal", "shallow clone", "host", "username", "token", "credential"]):
        return "We couldn't access this repository (it may be private or the link is wrong)"
    if any(k in err for k in ["large", "exceeds", "file limit", "cap", "too many files", "size boundary"]):
        return "The repository is too large"
    return "Something went wrong on our side"


map_failure_reason = failure_reason


def dashboard_view(
    current_user: UserModel,
    billing_status: Dict[str, Any],
    past_jobs: List[Any],
    error: Optional[str] = None,
    success: Optional[str] = None,
    too_large_info: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Render the clean, modern Backtrace Dashboard (Prompt 8 Redesign).
    Features:
    - H1 "Analyze a repository" with descriptive subtitle
    - Form with big input and primary "Analyze repository" button
    - "Advanced options" collapsible with branch and subdirectory inputs
    - Sample chip filling input
    - Quota meter: one line and one bar (no badge)
    - "Upgrade to Pro" secondary outlined button (only when billing enabled)
    - Grouped history by repo URL with runs count, status, date via <time>, learning progress, and "Open report"
    - Client-side search input filtering by repo name
    - Overflow menu with delete confirm dialog (POST delete route)
    """
    now = datetime.now(timezone.utc)
    if now.month == 12:
        next_month_date = datetime(now.year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        next_month_date = datetime(now.year, now.month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    renewal_date_str = next_month_date.strftime("%b %d, %Y")

    tier = billing_status.get("tier", "free")
    used = int(billing_status.get("monthly_usage", 0))
    limit = billing_status.get("monthly_quota")
    limit_val = int(limit) if limit is not None else 5
    is_quota_exhausted = (tier != "paid" and used >= limit_val)

    if tier == "paid":
        consumption_line = "Unlimited analyses used this month"
        meter_pct = 100
    else:
        pct = min(100, int((used / max(1, limit_val)) * 100))
        meter_pct = pct
        consumption_line = f"{used} of {limit_val} analyses used this month"

    analyze_disabled_attr = 'disabled' if is_quota_exhausted else ''
    analyze_btn_style = 'opacity: 0.5; cursor: not-allowed;' if is_quota_exhausted else ''

    upgrade_btn_html = ""
    if billing_enabled() and tier != "paid":
        upgrade_btn_html = (
            '<a href="/settings" class="btn btn-secondary" id="upgrade-pro-btn" '
            'style="font-size: 13px; padding: 0.35rem 0.75rem; white-space: nowrap;">'
            'Upgrade to Pro</a>'
        )

    quota_exhausted_banner = ""
    if is_quota_exhausted:
        upgrade_link_html = (
            f'<a href="/settings" class="btn btn-sm btn-secondary" id="quota-upgrade-link" style="font-size: 0.8125rem;">Upgrade</a>'
            if billing_enabled()
            else ""
        )
        quota_exhausted_banner = f"""
        <div id="quota-exhausted-notice" style="color: var(--danger); font-size: 0.875rem; margin-top: 0.75rem; display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap;">
            <span>You've used all {limit_val} analyses this month. Resets on {renewal_date_str}.</span>
            {upgrade_link_html}
        </div>
        """

    is_invalid_url_error = False
    if error and any(k in str(error).lower() for k in [
        "that doesn't look like a github repository link",
        "invalid repository url",
        "invalid github repository",
        "url must be",
        "expected: https://github.com",
    ]):
        is_invalid_url_error = True

    inline_url_error_html = ""
    input_invalid_attrs = ""
    if is_invalid_url_error:
        inline_url_error_html = (
            '<div id="repo-url-error" class="input-error-inline" style="color: var(--danger); font-size: 0.8125rem; margin-top: 0.45rem; display: flex; align-items: center; gap: 0.35rem;">'
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
            '<span>That doesn\'t look like a GitHub repository link.</span>'
            '</div>'
        )
        input_invalid_attrs = ' aria-invalid="true" aria-describedby="repo-url-error"'

    error_html = f'<div class="alert-error" style="margin-bottom: 1.5rem;">{sanitize_text(error)}</div>' if (error and not is_invalid_url_error) else ""
    success_html = (
        f'<div style="background: rgba(45, 212, 191, 0.12); border: 1px solid var(--success); color: var(--success); padding: 0.85rem 1.15rem; border-radius: var(--radius); margin-bottom: 1.5rem; font-size: 0.875rem; display: flex; align-items: center; gap: 0.6rem;">'
        f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>'
        f'<span>{sanitize_text(success)}</span>'
        f'</div>'
    ) if success else ""

    too_large_card = ""
    if too_large_info:
        found_files = too_large_info.get("file_count", 0)
        file_limit = too_large_info.get("limit", 150)
        prefill_url = sanitize_text(too_large_info.get("repo_url", ""))
        prefill_ref = sanitize_text(too_large_info.get("commit_ref", ""))
        prefill_subpath = sanitize_text(too_large_info.get("subpath", ""))

        too_large_card = f"""
    <div class="card stratum-card" id="repo-too-large-card" style="margin-bottom: 2rem; border-color: rgba(239, 91, 91, 0.4); background: linear-gradient(180deg, rgba(239, 91, 91, 0.08) 0%, var(--surface) 100%); padding: 1.5rem;">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; border-bottom: 1px solid rgba(239, 91, 91, 0.25); padding-bottom: 0.75rem;">
            <div style="display: flex; align-items: center; gap: 0.65rem;">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" stroke-width="2">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                    <line x1="12" y1="9" x2="12" y2="13"></line>
                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                </svg>
                <h2 style="font-size: 1.25rem; font-weight: 600; color: var(--danger); margin: 0;">Repository Too Large</h2>
            </div>
            <span class="badge" style="background: rgba(239, 91, 91, 0.15); color: var(--danger); border: 1px solid rgba(239, 91, 91, 0.3); font-family: var(--font-mono); font-size: 0.8125rem;">
                EXCEEDS {file_limit} FILE LIMIT
            </span>
        </div>

        <div>
            <div style="font-size: 1rem; font-weight: 600; color: var(--text); margin-bottom: 0.5rem; font-family: var(--font-mono);">
                Found {found_files} supported files (limit: {file_limit} files)
            </div>
            <p style="color: var(--text-muted); font-size: 0.875rem; line-height: 1.5; margin-bottom: 1.25rem;">
                This repository exceeds Backtrace's single-pass capacity limit. To analyze this project, you can retry with a narrower subdirectory path (e.g. <code>packages/api</code> or <code>src/core</code>) or a specific branch/commit ref to bring the file count under the {file_limit}-file threshold.
            </p>

            <form action="/analyses/submit" method="POST" id="retry-too-large-form" style="background: var(--surface-2); padding: 1.25rem; border-radius: var(--radius); border: 1px solid var(--border);">
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-bottom: 1rem;">
                    <div class="form-group" style="margin-bottom: 0;">
                        <label class="form-label" for="retry-repo-url">Target Git Repository HTTPS URL <span style="color: var(--danger);">*</span></label>
                        <input type="url" id="retry-repo-url" name="repo_url" required class="form-input" value="{prefill_url}" />
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label class="form-label" for="retry-branch-ref">Branch / Commit Ref <span style="color: var(--text-muted);">(Optional)</span></label>
                        <input type="text" id="retry-branch-ref" name="commit_ref" class="form-input" value="{prefill_ref}" placeholder="main or HEAD" />
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label class="form-label" for="retry-subpath" style="color: var(--accent); font-weight: 600;">Subdirectory Path <span style="color: var(--text-muted); font-weight: normal;">(e.g. packages/api)</span></label>
                        <input type="text" id="retry-subpath" name="subpath" autofocus class="form-input" value="{prefill_subpath}" placeholder="e.g. packages/api or src" />
                    </div>
                </div>

                <div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--border);">
                    <a href="/dashboard" class="btn btn-secondary" style="font-size: 0.8125rem;">
                        Dismiss / Back to Dashboard
                    </a>
                    <button type="submit" class="btn btn-primary" style="padding: 0.55rem 1.2rem;">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="23 4 23 10 17 10"></polyline>
                            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                        </svg>
                        Retry Analysis with Scope
                    </button>
                </div>
            </form>
        </div>
    </div>
    """

    # Build job history rows grouped by repo
    rows_html = ""
    cards_html = ""
    for job in past_jobs:
        job_id = sanitize_text(str(job.id))
        repo_url = sanitize_text(job.repo_url)
        repo_display = sanitize_text(job.repo_name or (job.repo_url.rstrip("/").split("/")[-1] if "/" in job.repo_url else job.repo_url))
        status = sanitize_text(job.status)
        created_at = format_time_tag(job.created_at)
        duration_str = f"{job.execution_time_seconds:.1f}s" if getattr(job, "execution_time_seconds", 0) else "—"

        runs = getattr(job, "runs", 1)
        runs_html = ""
        if runs > 1:
            runs_html = f'<span class="runs-count" id="runs-badge-{job_id}">{runs} runs</span>'

        # Compute Learning Progress (X of Y done)
        verified_count = 0
        total_milestones = 0
        if job.graph_data and isinstance(job.graph_data, dict):
            nodes = job.graph_data.get("nodes", [])
            tier_set = {n.get("tier") for n in nodes if n.get("tier") is not None}
            total_milestones = len(tier_set)

        if total_milestones == 0 and job.markdown_output:
            total_milestones = len(re.findall(r"###\s+Milestone\s+\d+:", job.markdown_output))

        try:
            if hasattr(job, "milestone_attempts") and job.milestone_attempts:
                verified_count = sum(1 for a in job.milestone_attempts if getattr(a, "status", None) == "structurally_verified")
        except Exception:
            verified_count = 0

        if total_milestones == 0 and verified_count > 0:
            total_milestones = verified_count

        if total_milestones > 0:
            progress_text = f"{verified_count} of {total_milestones} done"
            progress_html = f'<span style="font-family: var(--font-mono); font-size: 13px; color: var(--text);">{progress_text}</span>'
        else:
            progress_html = '<span style="color: var(--text-muted); font-size: 13px;">—</span>'

        status_class = f"badge-{status}" if status in ["completed", "running", "failed", "pending"] else "badge-secondary"
        status_label = status.capitalize()

        if status == "completed":
            primary_btn = f'<a href="/report/{job_id}" class="btn btn-sm btn-primary" style="white-space: nowrap;">Open report</a>'
        elif status == "failed":
            primary_btn = f"""
            <form action="/analyses/{job_id}/retry" method="POST" style="margin: 0; display: inline;">
                <button type="submit" class="btn btn-sm btn-secondary" style="white-space: nowrap; color: var(--danger); border-color: var(--danger);">
                    Retry
                </button>
            </form>
            """
        elif status in ["running", "pending"]:
            primary_btn = f'<a href="/progress/{job_id}" class="btn btn-sm btn-secondary" style="white-space: nowrap;">Track progress</a>'
        else:
            primary_btn = f'<a href="/progress/{job_id}" class="btn btn-sm btn-secondary" style="white-space: nowrap;">View details</a>'

        overflow_menu = f"""
        <div class="overflow-menu-container" style="position: relative; display: inline-block;">
            <button
                type="button"
                class="btn btn-ghost btn-sm overflow-btn"
                onclick="toggleRowMenu(event, 'row-menu-{job_id}')"
                aria-label="Actions for {repo_display}"
                style="padding: 0.35rem 0.5rem; color: var(--text-muted); font-size: 14px; line-height: 1; border-radius: var(--radius); cursor: pointer;"
            >
                &hellip;
            </button>
            <div
                id="row-menu-{job_id}"
                class="row-menu-dropdown"
                style="display: none; position: absolute; right: 0; top: 100%; margin-top: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: 0 4px 16px rgba(0,0,0,0.3); z-index: 100; min-width: 120px; padding: 4px;"
            >
                <form
                    action="/analyses/{job_id}/delete"
                    method="POST"
                    onsubmit="return confirm('Delete this repository analysis? This action cannot be undone.');"
                    style="margin: 0;"
                >
                    <button
                        type="submit"
                        class="dropdown-item-delete"
                        style="width: 100%; text-align: left; background: transparent; border: none; padding: 0.45rem 0.75rem; font-size: 13px; color: var(--danger); cursor: pointer; border-radius: 4px; display: flex; align-items: center; gap: 0.4rem; font-family: var(--font-ui);"
                    >
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                        Delete
                    </button>
                </form>
            </div>
        </div>
        """

        repo_error_html = ""
        if status == "failed" and (getattr(job, "error_message", None) or getattr(job, "failed_stage", None)):
            raw_err_str = str(getattr(job, "error_message", "") or "").strip()
            if raw_err_str:
                safe_reason = sanitize_text(failure_reason(raw_err_str))
                repo_error_html = f"""
                <div class="job-failure-reason" title="{safe_reason}" style="margin-top: 0.35rem; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--danger); display: flex; align-items: flex-start; gap: 0.35rem; line-height: 1.35; max-width: 420px; overflow-wrap: anywhere;">
                    <span style="font-weight: 600; flex-shrink: 0; color: var(--danger);">Failed:</span>
                    <span>{safe_reason}</span>
                </div>
                """

        rows_html += f"""
        <tr class="history-row" data-repo-name="{repo_display.lower()}" data-repo-url="{repo_url.lower()}">
            <td style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border);">
                <div style="font-weight: 500; color: var(--text); display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap;">
                    <span>{repo_display}</span>
                    {runs_html}
                </div>
                <div style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.2rem; overflow-wrap: anywhere;">{repo_url}</div>
                {repo_error_html}
            </td>
            <td style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border);"><span class="badge {status_class}">{status_label}</span></td>
            <td style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border);">{progress_html}</td>
            <td style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border); color: var(--text-muted); font-size: 13px;">
                <div>{created_at}</div>
                <div style="font-size: 0.8125rem; font-family: var(--font-mono); color: var(--text-muted); margin-top: 0.15rem;">{duration_str}</div>
            </td>
            <td style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border); text-align: right; white-space: nowrap;">
                <div style="display: inline-flex; align-items: center; gap: 0.4rem; justify-content: flex-end;">
                    {primary_btn}
                    {overflow_menu}
                </div>
            </td>
        </tr>
        """

        cards_html += f"""
        <div class="card stratum-card history-card" data-repo-name="{repo_display.lower()}" data-repo-url="{repo_url.lower()}" style="padding: 1rem; margin-bottom: 0.75rem; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); width: 100%; min-width: 0; box-sizing: border-box;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem; margin-bottom: 0.5rem;">
                <div style="font-weight: 500; color: var(--text); overflow-wrap: anywhere; word-break: break-word;">
                    <span>{repo_display}</span>
                    {runs_html}
                </div>
                <span class="badge {status_class}" style="flex-shrink: 0;">{status_label}</span>
            </div>
            <div style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); overflow-wrap: anywhere; word-break: break-word; margin-bottom: 0.5rem;">{repo_url}</div>
            {repo_error_html}
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.75rem; padding-top: 0.5rem; border-top: 1px solid var(--border); gap: 0.5rem; flex-wrap: wrap;">
                <div style="font-size: 13px; color: var(--text-muted);">{created_at}</div>
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-left: auto;">
                    {primary_btn}
                    {overflow_menu}
                </div>
            </div>
        </div>
        """

    if not past_jobs:
        history_content = """
        <div class="card stratum-card" style="padding: 3rem 1.5rem; text-align: center; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);">
            <div style="display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 50%; margin-bottom: 1rem; color: var(--accent);">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
            </div>
            <h3 style="font-size: 1.15rem; font-weight: 500; margin-bottom: 0.4rem; color: var(--text);">No analyses yet</h3>
            <p style="color: var(--text-muted); font-size: 14px; max-width: 440px; margin: 0 auto 1.25rem auto; line-height: 1.5;">
                No analyses yet. Paste a repository link above.
            </p>
            <button type="button" class="btn btn-sm btn-secondary" onclick="document.getElementById('repo-url-input').value='https://github.com/expressjs/express'; document.getElementById('repo-url-input').focus();">
                Try expressjs/express
            </button>
        </div>
        """
    else:
        history_content = f"""
        <div class="table-responsive history-table-container card stratum-card" style="background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="border-bottom: 1px solid var(--border); background: var(--surface-2);">
                        <th style="padding: 0.75rem 1rem; text-align: left; font-size: 13px; font-family: var(--font-ui); color: var(--text-muted);">Repository</th>
                        <th style="padding: 0.75rem 1rem; text-align: left; font-size: 13px; font-family: var(--font-ui); color: var(--text-muted);">Status</th>
                        <th style="padding: 0.75rem 1rem; text-align: left; font-size: 13px; font-family: var(--font-ui); color: var(--text-muted);">Learning progress</th>
                        <th style="padding: 0.75rem 1rem; text-align: left; font-size: 13px; font-family: var(--font-ui); color: var(--text-muted);">Submitted</th>
                        <th style="padding: 0.75rem 1rem; text-align: right; font-size: 13px; font-family: var(--font-ui); color: var(--text-muted); white-space: nowrap;">Action</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        <div class="history-cards-container" style="display: none;">
            {cards_html}
        </div>
        """

    quota_section_html = f"""
    <!-- Quota: one line and one bar (Prompt 7 / Prompt 8). No badge. -->
    <div class="quota-container" id="quota-indicator-card" style="margin-top: 1.5rem; margin-bottom: 2rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 0.5rem; flex-wrap: wrap;">
            <span style="font-size: 14px; color: var(--text-muted); font-family: var(--font-ui);">{consumption_line}</span>
            {upgrade_btn_html}
        </div>
        <div class="meter" style="height: 6px; width: 100%; background: var(--surface-2); border-radius: 9999px; overflow: hidden;">
            <div class="meter-fill high" style="width: {meter_pct}%; height: 100%; background: var(--accent); border-radius: 9999px; transition: width 0.3s ease;"></div>
        </div>
    </div>
    """

    content = f"""
    <!-- Reconstruct Repository History -->
    <div class="dashboard-header" style="margin-top: 1rem; margin-bottom: 1.75rem;">
        <h1 style="font-size: 2rem; font-weight: 600; color: var(--text); letter-spacing: -0.02em; margin-bottom: 0.5rem;">
            Analyze a repository
        </h1>
        <p style="font-size: 15px; color: var(--text-muted); line-height: 1.5; margin: 0;">
            Paste a GitHub link and get a step-by-step guide to understand the code.
        </p>
    </div>

    {success_html}
    {error_html}
    {too_large_card}

    <!-- Form: Big input + Primary button + Collapsible advanced options + Sample chip -->
    <div class="card stratum-card dashboard-form-card" style="padding: 1.5rem; margin-bottom: 1.5rem; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);">
        <form action="/analyses/submit" method="POST" id="reconstruct-form" novalidate>
            <div class="form-actions-row" style="display: flex; gap: 0.75rem; flex-wrap: wrap;">
                <div style="flex: 1; min-width: 280px;">
                    <input
                        type="url"
                        id="repo-url-input"
                        name="repo_url"
                        required
                        class="form-input dashboard-big-input"
                        placeholder="https://github.com/owner/repo"
                        {input_invalid_attrs}
                        style="width: 100%; font-size: 1rem; padding: 0.75rem 1rem; border-radius: var(--radius); background: var(--surface-2); border: 1px solid {'var(--danger)' if is_invalid_url_error else 'var(--border)'}; color: var(--text);"
                    />
                    {inline_url_error_html}
                </div>
                <button
                    type="submit"
                    class="btn btn-primary"
                    id="analyze-button"
                    {analyze_disabled_attr}
                    style="{analyze_btn_style} font-size: 0.95rem; padding: 0.75rem 1.5rem; white-space: nowrap;"
                >
                    Analyze repository
                </button>
            </div>

            <div style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.75rem; flex-wrap: wrap;">
                <span style="font-size: 13px; color: var(--text-muted);">Try a sample:</span>
                <button
                    type="button"
                    class="sample-chip btn-ghost"
                    id="sample-chip-btn"
                    data-repo="https://github.com/expressjs/express"
                    onclick="document.getElementById('repo-url-input').value='https://github.com/expressjs/express'; document.getElementById('repo-url-input').focus();"
                    style="background: var(--surface-2); border: 1px solid var(--border); color: var(--text); border-radius: 9999px; padding: 0.2rem 0.65rem; font-size: 0.8125rem; font-family: var(--font-mono); cursor: pointer;"
                >
                    expressjs/express
                </button>
            </div>

            <details class="advanced-options-details" id="advanced-options-details" style="margin-top: 1rem; border-top: 1px solid var(--border); padding-top: 0.75rem;">
                <summary class="advanced-options-toggle" style="cursor: pointer; color: var(--accent); font-size: 14px; font-weight: 500; user-select: none; display: inline-flex; align-items: center; gap: 0.35rem;">
                    Advanced options
                </summary>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-top: 0.85rem; padding: 1rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius);">
                    <div class="form-group" style="margin-bottom: 0;">
                        <label class="form-label" for="branch-ref-input" style="font-size: 13px; color: var(--text-muted); margin-bottom: 0.35rem; display: block;">
                            Branch / Commit Ref <span style="font-size: 0.8125rem; color: var(--text-muted);">(Optional)</span>
                        </label>
                        <input
                            type="text"
                            id="branch-ref-input"
                            name="commit_ref"
                            class="form-input"
                            placeholder="main or HEAD"
                            style="width: 100%; font-size: 13px; padding: 0.55rem 0.75rem; border-radius: var(--radius); background: var(--surface); border: 1px solid var(--border); color: var(--text); font-family: var(--font-mono);"
                        />
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label class="form-label" for="subpath-input" style="font-size: 13px; color: var(--text-muted); margin-bottom: 0.35rem; display: block;">
                            Subdirectory Path <span style="font-size: 0.8125rem; color: var(--text-muted);">(Optional)</span>
                        </label>
                        <input
                            type="text"
                            id="subpath-input"
                            name="subpath"
                            class="form-input"
                            placeholder="e.g. packages/api or src"
                            style="width: 100%; font-size: 13px; padding: 0.55rem 0.75rem; border-radius: var(--radius); background: var(--surface); border: 1px solid var(--border); color: var(--text); font-family: var(--font-mono);"
                        />
                    </div>
                </div>
            </details>
            {quota_exhausted_banner}
        </form>
    </div>

    {quota_section_html}

    <!-- History, grouped by repo -->
    <div class="history-section" style="margin-top: 2rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap;">
            <h2 style="font-size: 1.25rem; font-weight: 600; color: var(--text); margin: 0;">
                Repository History
            </h2>
            <div style="position: relative; width: 260px; max-width: 100%;">
                <input
                    type="search"
                    id="repo-search-input"
                    placeholder="Search repositories…"
                    class="form-input"
                    style="width: 100%; font-size: 13px; padding: 0.45rem 0.75rem 0.45rem 2rem; border-radius: var(--radius); background: var(--surface); border: 1px solid var(--border); color: var(--text);"
                />
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="position: absolute; left: 0.65rem; top: 50%; transform: translateY(-50%); color: var(--text-muted); pointer-events: none;">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
            </div>
        </div>
        {history_content}
    </div>

    {DASHBOARD_INLINE_JS}
    """
    return page_shell(
        "Dashboard",
        content,
        current_user=current_user,
        active_route="/dashboard",
        billing_status=billing_status,
    )



# -----------------------------------------------------------------------------
# Analysis Pipeline Phase & Stage Mappings (Prompt 8 Rebuild)
# -----------------------------------------------------------------------------

PHASE_DEFINITIONS: List[Dict[str, Any]] = [
    {"index": 1, "id": "phase_1", "name": "Get the code", "stages": ["stage_0", "stage_1"]},
    {"index": 2, "id": "phase_2", "name": "Read the files", "stages": ["stage_2", "stage_3", "stage_4"]},
    {"index": 3, "id": "phase_3", "name": "Map how they connect", "stages": ["stage_5", "stage_6"]},
    {"index": 4, "id": "phase_4", "name": "Build your guide", "stages": ["stage_7", "stage_8", "stage_9", "stage_10"]},
]

STAGE_TO_PHASE_MAP: Dict[str, Dict[str, Any]] = {
    "stage_0": {"phase_index": 1, "phase_name": "Get the code"},
    "stage_1": {"phase_index": 1, "phase_name": "Get the code"},
    "stage_2": {"phase_index": 2, "phase_name": "Read the files"},
    "stage_3": {"phase_index": 2, "phase_name": "Read the files"},
    "stage_4": {"phase_index": 2, "phase_name": "Read the files"},
    "stage_5": {"phase_index": 3, "phase_name": "Map how they connect"},
    "stage_6": {"phase_index": 3, "phase_name": "Map how they connect"},
    "stage_7": {"phase_index": 4, "phase_name": "Build your guide"},
    "stage_8": {"phase_index": 4, "phase_name": "Build your guide"},
    "stage_9": {"phase_index": 4, "phase_name": "Build your guide"},
    "stage_10": {"phase_index": 4, "phase_name": "Build your guide"},
}

def map_stage_to_phase(stage: str) -> Dict[str, Any]:
    """Map a stage key (stage_0 to stage_10) to one of the 4 user-facing phases."""
    key = str(stage).strip().lower()
    if key in STAGE_TO_PHASE_MAP:
        return dict(STAGE_TO_PHASE_MAP[key])
    for s_k, val in STAGE_TO_PHASE_MAP.items():
        if s_k in key:
            return dict(val)
    return {"phase_index": 1, "phase_name": "Get the code"}

def failure_reason(error_message: Optional[str]) -> str:
    """Map raw job error message to one of three clean user-facing sentences."""
    if not error_message:
        return "Something went wrong on our side"
    err = str(error_message).lower()
    if any(k in err for k in ["auth", "access", "private", "not found", "404", "403", "permission", "clone", "could not resolve", "fatal: repository", "fatal", "shallow clone", "host", "username", "token", "credential"]):
        return "We couldn't access this repository (it may be private or the link is wrong)"
    if any(k in err for k in ["large", "exceeds", "file limit", "cap", "too many files", "size boundary"]):
        return "The repository is too large"
    return "Something went wrong on our side"

map_failure_reason = failure_reason

def extract_owner_and_repo(job: Any) -> Tuple[str, str]:
    """Extract clean (owner, repo) pair for Title: Analyzing {owner}/{repo}."""
    raw_repo_url = getattr(job, "repo_url", None) if hasattr(job, "repo_url") else (job.get("repo_url") if isinstance(job, dict) else None)
    raw_github_url = getattr(job, "github_url", None) if hasattr(job, "github_url") else (job.get("github_url") if isinstance(job, dict) else None)
    raw_repo_name = getattr(job, "repo_name", None) if hasattr(job, "repo_name") else (job.get("repo_name") if isinstance(job, dict) else None)

    url = str(raw_repo_url or raw_github_url or "").strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]

    parts = [p for p in url.split("/") if p]
    if len(parts) >= 2 and ("github.com" in url or "gitlab.com" in url or len(parts) >= 3):
        return sanitize_text(parts[-2]), sanitize_text(parts[-1])

    if raw_repo_name and "/" in str(raw_repo_name):
        p = str(raw_repo_name).split("/")
        return sanitize_text(p[0]), sanitize_text(p[1])

    if raw_repo_name:
        return "repository", sanitize_text(str(raw_repo_name))

    return "repository", sanitize_text(str(getattr(job, "id", "repo")))


PROGRESS_STAGES_CLEAN: List[Tuple[str, str, str]] = [
    (
        "stage_0",
        "Consent & Auth Gate",
        "Authorizing repository access and verifying read permissions.",
    ),
    (
        "stage_1",
        "Shallow Clone",
        "Fetching repository contents into an isolated sandbox.",
    ),
    (
        "stage_2",
        "Discovery & File Hierarchy",
        "Scanning directory tree, project manifests, and language breakdown.",
    ),
    (
        "stage_3",
        "Code Structure Parsing",
        "Parsing source code into concrete syntax trees.",
    ),
    (
        "stage_4",
        "Global Symbol Table",
        "Indexing public interfaces, symbols, and cross-package declarations.",
    ),
    (
        "stage_5",
        "Directed Dependency Graph",
        "Tracing import chains and resolving module dependencies.",
    ),
    (
        "stage_6",
        "Architecture Domain Mapping",
        "Grouping modules into architectural subsystems and domain boundaries.",
    ),
    (
        "stage_7",
        "Step-by-step narration",
        "Synthesizing architectural reading order and structural rationale.",
    ),
    (
        "stage_8",
        "Graph & Quiz Generation",
        "Constructing interactive visual call graphs and comprehension quizzes.",
    ),
    (
        "stage_9",
        "Persistence & Architecture Report Assembly",
        "Compiling analysis results and persisting final architecture report.",
    ),
    (
        "stage_10",
        "Telemetry & Quota Allocation",
        "Finalizing execution metrics and updating account quota.",
    ),
]


def progress_view(
    job: Any,
    current_user: UserModel,
    billing_status: Optional[Dict[str, Any]] = None,
) -> str:
    """Render rebuilt analysis progress page driven by real job events and 4 user phases."""
    job_id = sanitize_text(str(getattr(job, "id", None) if hasattr(job, "id") else (job.get("id", "") if isinstance(job, dict) else "")))
    raw_status = getattr(job, "status", "pending") if hasattr(job, "status") else (job.get("status", "pending") if isinstance(job, dict) else "pending")
    job_status = str(raw_status or "pending").lower()
    raw_job_error = getattr(job, "error_message", None) if hasattr(job, "error_message") else (job.get("error_message", None) if isinstance(job, dict) else None)

    owner, repo = extract_owner_and_repo(job)

    # Calculate timestamps & elapsed duration
    job_created_ts = 0.0
    raw_created_at = getattr(job, "created_at", None) if hasattr(job, "created_at") else (job.get("created_at", None) if isinstance(job, dict) else None)
    if raw_created_at is not None:
        try:
            ca = raw_created_at
            if isinstance(ca, (int, float)):
                val = float(ca)
                job_created_ts = float(val / 1000.0) if val > 1e11 else val
            elif isinstance(ca, datetime):
                if ca.tzinfo is None:
                    job_created_ts = float(ca.replace(tzinfo=timezone.utc).timestamp())
                else:
                    job_created_ts = float(ca.timestamp())
            elif isinstance(ca, str):
                from datetime import datetime as dt
                clean_str = ca.strip()
                if clean_str.endswith(" UTC"):
                    clean_str = clean_str[:-4].strip() + "+00:00"
                elif clean_str.endswith("Z"):
                    clean_str = clean_str[:-1] + "+00:00"
                parsed = dt.fromisoformat(clean_str)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                job_created_ts = float(parsed.timestamp())
        except Exception:
            job_created_ts = 0.0

    raw_exec_time = getattr(job, "execution_time_seconds", 0.0) if hasattr(job, "execution_time_seconds") else (job.get("execution_time_seconds", 0.0) if isinstance(job, dict) else 0.0)
    try:
        execution_time_seconds = float(raw_exec_time) if raw_exec_time is not None and isinstance(raw_exec_time, (int, float, str)) else 0.0
    except (ValueError, TypeError):
        execution_time_seconds = 0.0

    mins_init = int(execution_time_seconds // 60)
    secs_init = int(execution_time_seconds % 60)
    formatted_init_time = f"{mins_init}:{secs_init:02d}"

    # Extract real numbers for completed state
    files_analyzed = 0
    modules_count = 0
    entry_points_count = 0

    raw_md = getattr(job, "markdown_output", "") if hasattr(job, "markdown_output") else (job.get("markdown_output", "") if isinstance(job, dict) else "")
    if raw_md:
        try:
            # Inline extraction of real numbers from synthesized markdown overview
            files_m = re.search(r"\*\*Total Analyzed Files\*\*:\s*`?(\d+)`?", raw_md)
            if files_m:
                files_analyzed = int(files_m.group(1))
            domains_m = re.search(r"\*\*Domain Categories\*\*:\s*`?(\d+)`?", raw_md)
            if domains_m:
                modules_count = int(domains_m.group(1))
            entry_m = re.search(r"\*\*Entry Point Files\*\*:\s*`?([^`\n]+)`?", raw_md)
            if entry_m:
                entry_points_count = len([e.strip() for e in entry_m.group(1).split(",") if e.strip() and e.strip() != "None"])
        except Exception:
            pass

    raw_graph = getattr(job, "graph_output_json", None) if hasattr(job, "graph_output_json") else (job.get("graph_output_json", None) if isinstance(job, dict) else None)
    if raw_graph and (files_analyzed == 0 or modules_count == 0):
        try:
            g_data = json.loads(raw_graph) if isinstance(raw_graph, str) else (raw_graph if isinstance(raw_graph, dict) else {})
            nodes = g_data.get("nodes", [])
            if files_analyzed == 0:
                files_analyzed = len(nodes)
            if modules_count == 0:
                tiers = {n.get("tier") for n in nodes if "tier" in n}
                modules_count = max(1, len(tiers)) if tiers else len(nodes)
        except Exception:
            pass

    # Determine visibility states
    is_completed = (job_status in ("completed", "complete"))
    is_failed = (job_status == "failed")
    is_cancelled = (job_status == "cancelled")
    is_running = not (is_completed or is_failed or is_cancelled)

    active_card_display = "block" if is_running else "none"
    cancel_form_display = "inline-block" if is_running else "none"
    report_ready_display = "block" if is_completed else "none"
    failed_card_display = "block" if is_failed else "none"
    cancelled_card_display = "block" if is_cancelled else "none"

    # Map plain failure reason - raw error message never appears in DOM
    mapped_error_reason = failure_reason(raw_job_error)

    # Initial sentence & bar
    initial_sentence = "Downloading the repository…" if is_running else ("Analysis complete." if is_completed else ("Analysis failed." if is_failed else "Analysis cancelled."))

    now_ts = datetime.now(timezone.utc).timestamp()
    if is_running and job_created_ts > 0:
        running_secs = max(0, int(now_ts - job_created_ts))
        initial_timer_str = f"{running_secs // 60}:{running_secs % 60:02d}"
    elif execution_time_seconds > 0:
        initial_timer_str = formatted_init_time
    else:
        initial_timer_str = "0:00"

    if is_running:
        timer_badge_text = f"Running for {initial_timer_str}"
    elif is_failed:
        timer_badge_text = f"Failed after {formatted_init_time}"
    else:
        timer_badge_text = f"Completed in {formatted_init_time}"

    checkmark_svg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'
    spinner_svg = '<svg class="stepper-spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2v4m0 12v4m-10-10h4m12 0h4m-3.17-6.83l-2.83 2.83m-8 8l-2.83 2.83m0-13.66l2.83 2.83m8 8l2.83 2.83"></path></svg>'
    circle_empty_svg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"></circle></svg>'
    fail_svg = '<svg class="stepper-fail" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>'

    raw_failed_stage = getattr(job, "failed_stage", None) if hasattr(job, "failed_stage") else (job.get("failed_stage") if isinstance(job, dict) else None)
    failed_phase = map_stage_to_phase(raw_failed_stage)["phase_index"] if raw_failed_stage else 1

    # Build Stepper HTML (4 phases)
    stepper_html = '<div class="progress-stepper" id="stepper-container">'
    for p in PHASE_DEFINITIONS:
        p_idx = p["index"]
        p_name = p["name"]

        if is_completed:
            step_state = "done"
            circle_content = checkmark_svg
        elif is_running:
            if p_idx == 1:
                step_state = "active"
                circle_content = spinner_svg
            else:
                step_state = "upcoming"
                circle_content = f"<span>{p_idx}</span>"
        elif is_failed or is_cancelled:
            if p_idx < failed_phase:
                step_state = "done"
                circle_content = checkmark_svg
            elif p_idx == failed_phase:
                step_state = "failed"
                circle_content = fail_svg
            else:
                step_state = "upcoming"
                circle_content = f"<span>{p_idx}</span>"
        else:
            step_state = "upcoming"
            circle_content = f"<span>{p_idx}</span>"

        stepper_html += f"""
        <div class="stepper-step {step_state}" id="stepper-phase-{p_idx}">
            <div class="stepper-circle" id="stepper-circle-{p_idx}">
                {circle_content}
            </div>
            <span class="stepper-label">{p_name}</span>
        </div>
        """
    stepper_html += '</div>'

    # Build 11 Stages list for details toggle
    narration_src = get_narration_source(job)
    stages_list_html = '<div class="stages-plain-list" id="stages-plain-list" style="display: flex; flex-direction: column; gap: 0.35rem;">'
    for s_key, s_name, s_desc in PROGRESS_STAGES_CLEAN:
        s_display_name = get_narration_label(narration_src) if (is_completed and s_key == "stage_7" and narration_src == "llm") else s_name
        init_icon = checkmark_svg if is_completed else circle_empty_svg
        icon_color = "var(--success)" if is_completed else "var(--text-muted)"
        stages_list_html += f"""
        <div class="details-stage-row" id="stage-row-{s_key}" style="display: flex; align-items: center; justify-content: space-between; padding: 0.5rem 0.65rem; border-radius: 6px; font-size: 0.8125rem;">
            <div style="display: flex; align-items: center; gap: 0.65rem;">
                <span class="details-stage-icon" id="icon-{s_key}" style="color: {icon_color}; display: flex; align-items: center; justify-content: center;">
                    {init_icon}
                </span>
                <span style="font-weight: 500; color: var(--text);">{s_display_name}</span>
            </div>
            <span style="font-size: 0.8125rem; color: var(--text-muted);">{s_desc}</span>
        </div>
        """
    stages_list_html += '</div>'

    extra_scripts = f"""
    <script>
        const jobId = "{job_id}";
        const jobStartTime = {int(job_created_ts * 1000) if job_created_ts > 0 else "Date.now()"};
        const initialJobStatus = "{job_status}";
        let isJobTerminated = { "true" if not is_running else "false" };

        const checkmarkSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>';
        const spinnerSvg = '<svg class="stepper-spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2v4m0 12v4m-10-10h4m12 0h4m-3.17-6.83l-2.83 2.83m-8 8l-2.83 2.83m0-13.66l2.83 2.83m8 8l2.83 2.83"></path></svg>';
        const circleEmptySvg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"></circle></svg>';
        const failSvg = '<svg class="stepper-fail" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

        function escapeHtml(str) {{
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }}

        const stageToPhase = {{
            "stage_0": 1, "stage_1": 1,
            "stage_2": 2, "stage_3": 2, "stage_4": 2,
            "stage_5": 3, "stage_6": 3,
            "stage_7": 4, "stage_8": 4, "stage_9": 4, "stage_10": 4
        }};

        function updateStepper(activePhaseIndex, isAllDone, isFailed=false) {{
            for (let i = 1; i <= 4; i++) {{
                const step = document.getElementById("stepper-phase-" + i);
                const circle = document.getElementById("stepper-circle-" + i);
                if (!step || !circle) continue;
                if (isAllDone || i < activePhaseIndex) {{
                    step.className = "stepper-step done";
                    circle.innerHTML = checkmarkSvg;
                }} else if (i === activePhaseIndex && isFailed) {{
                    step.className = "stepper-step failed";
                    circle.innerHTML = failSvg;
                }} else if (i === activePhaseIndex && !isAllDone) {{
                    step.className = "stepper-step active";
                    circle.innerHTML = spinnerSvg;
                }} else {{
                    step.className = "stepper-step upcoming";
                    circle.innerHTML = `<span>${{i}}</span>`;
                }}
            }}
        }}

        function getActiveSentence(stageKey, data) {{
            if (stageKey === "stage_0" || stageKey === "stage_1") {{
                return "Downloading the repository…";
            }}
            if (stageKey === "stage_2") {{
                return "Discovering project structure…";
            }}
            if (stageKey === "stage_3") {{
                return "Reading files…";
            }}
            if (stageKey === "stage_4") {{
                return "Indexing functions and symbols…";
            }}
            if (stageKey === "stage_5" || stageKey === "stage_6") {{
                return "Finding how files import each other…";
            }}
            if (stageKey === "stage_7") {{
                return "Writing your learning guide…";
            }}
            if (stageKey === "stage_8") {{
                return "Generating interactive diagrams…";
            }}
            if (stageKey === "stage_9") {{
                return "Finalizing your report…";
            }}
            if (stageKey === "stage_10") {{
                return "Wrapping up telemetry…";
            }}
            return "Analyzing repository…";
        }}

        const timerTextEl = document.getElementById("elapsed-timer-text");
        const activeCardTimerEl = document.getElementById("active-card-timer");
        function updateElapsedTimer() {{
            if (isJobTerminated) return;
            const now = Date.now();
            const elapsedSecs = Math.max(0, Math.floor((now - jobStartTime) / 1000));
            const mins = Math.floor(elapsedSecs / 60);
            const secs = elapsedSecs % 60;
            const formatted = `${{mins}}:${{secs < 10 ? '0' : ''}}${{secs}}`;
            if (activeCardTimerEl) {{
                activeCardTimerEl.textContent = formatted;
            }}
            if (timerTextEl) {{
                timerTextEl.textContent = `Running for ${{formatted}}`;
            }}
        }}

        let timerInterval = null;
        if (!isJobTerminated) {{
            updateElapsedTimer();
            timerInterval = setInterval(updateElapsedTimer, 1000);
        }}

        const logBox = document.getElementById("sse-terminal-log");
        function addLogEntry(text, type="info") {{
            if (!logBox) return;
            const line = document.createElement("div");
            line.style.marginBottom = "0.25rem";
            line.style.fontSize = "0.75rem";
            line.style.fontFamily = "var(--font-mono)";

            let color = "var(--text-muted)";
            if (type === "complete") color = "var(--success)";
            if (type === "active") color = "var(--accent)";
            if (type === "error") color = "var(--danger)";

            line.style.color = color;
            const msgSpan = document.createElement("span");
            msgSpan.textContent = text;
            line.appendChild(msgSpan);
            logBox.appendChild(line);
            logBox.scrollTop = logBox.scrollHeight;
        }}

        function addActivityEntry(stageIndex, totalStages, stageName, message, isComplete=false) {{
            const sIdx = Number(stageIndex) || 0;
            const tStages = Number(totalStages) || 0;
            const phaseIdx = (typeof stageToPhase !== 'undefined' && stageToPhase[stageName]) || (sIdx <= 2 ? 1 : (sIdx <= 5 ? 2 : (sIdx <= 7 ? 3 : 4)));
            const phaseNames = {{1: "Get the code", 2: "Read the files", 3: "Map how they connect", 4: "Build your guide"}};
            const phaseName = phaseNames[phaseIdx] || escapeHtml(stageName);
            addLogEntry(`Phase ${{phaseIdx}} of 4 — ${{escapeHtml(phaseName)}}: ${{escapeHtml(message)}}`, isComplete ? "complete" : "active");
        }}

        function showReportReady(data) {{
            isJobTerminated = true;
            if (timerInterval) {{
                clearInterval(timerInterval);
                timerInterval = null;
            }}
            if (pollingInterval) {{
                clearInterval(pollingInterval);
                pollingInterval = null;
            }}

            const connLost = document.getElementById("connection-lost-banner");
            if (connLost) connLost.style.display = "none";

            const activeCard = document.getElementById("active-card");
            if (activeCard) activeCard.style.display = "none";

            const cancelForm = document.getElementById("cancel-form");
            if (cancelForm) cancelForm.style.display = "none";

            const readyCard = document.getElementById("report-ready-card");
            if (readyCard) {{
                const fEl = document.getElementById("ready-files-count");
                const mEl = document.getElementById("ready-modules-count");
                const eEl = document.getElementById("ready-entry-count");
                if (fEl) fEl.textContent = (data && (data.files_analyzed || data.files)) || "—";
                if (mEl) mEl.textContent = (data && (data.modules_mapped || data.modules)) || "—";
                if (eEl) eEl.textContent = (data && (data.entry_points || data.entry_points_count)) || "—";
                readyCard.style.display = "block";
            }}

            updateStepper(4, true);

            for (let i = 0; i <= 10; i++) {{
                const icon = document.getElementById("icon-stage_" + i);
                if (icon) {{
                    icon.innerHTML = checkmarkSvg;
                    icon.style.color = "var(--success)";
                }}
            }}
        }}

        function showFailure(reason, data) {{
            isJobTerminated = true;
            if (timerInterval) clearInterval(timerInterval);
            if (pollingInterval) clearInterval(pollingInterval);

            const connLost = document.getElementById("connection-lost-banner");
            if (connLost) connLost.style.display = "none";

            const activeCard = document.getElementById("active-card");
            if (activeCard) activeCard.style.display = "none";

            const cancelForm = document.getElementById("cancel-form");
            if (cancelForm) cancelForm.style.display = "none";

            const failCard = document.getElementById("failed-card");
            const failureMsg = document.getElementById("failed-reason-text");
            if (failureMsg) {{
                failureMsg.textContent = reason || "Something went wrong on our side";
            }}
            if (failCard) {{
                failCard.style.display = "block";
            }}

            const failedStageKey = (data && data.failed_stage) || "stage_1";
            const failedPhaseIdx = (typeof stageToPhase !== 'undefined' && stageToPhase[failedStageKey]) || 1;
            updateStepper(failedPhaseIdx, false, true);
        }}

        let eventSource = null;
        let pollingInterval = null;

        function pollJobStatus() {{
            if (isJobTerminated) return;
            fetch(`/api/analyses/${{jobId}}/status`)
                .then(r => r.json())
                .then(data => {{
                    if (!data) return;
                    if (data.status === "completed") {{
                        showReportReady(data);
                    }} else if (data.status === "failed") {{
                        showFailure(data.error_message, data);
                    }} else if (data.status === "cancelled") {{
                        isJobTerminated = true;
                        window.location.reload();
                    }}
                }})
                .catch(() => {{}});
        }}

        if (!isJobTerminated) {{
            eventSource = new EventSource(`/api/analyses/${{jobId}}/events`);
            addLogEntry("Event stream connected.");

            eventSource.onopen = function() {{
                const banner = document.getElementById("connection-lost-banner");
                if (banner) banner.style.display = "none";
            }};

            eventSource.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    if (data.type === "progress") {{
                        const stageKey = data.stage;
                        const phaseIdx = stageToPhase[stageKey] || 1;
                        updateStepper(phaseIdx, false);

                        const activeSentenceEl = document.getElementById("active-sentence");
                        if (activeSentenceEl) {{
                            activeSentenceEl.textContent = getActiveSentence(stageKey, data);
                        }}

                        const barFill = document.getElementById("progress-bar-fill");
                        if (barFill) {{
                            if (data.percentage && Number(data.percentage) > 0) {{
                                barFill.className = "progress-bar-fill determinate";
                                barFill.style.width = Number(data.percentage) + "%";
                            }} else {{
                                barFill.className = "progress-bar-fill indeterminate";
                                barFill.style.width = "35%";
                            }}
                        }}

                        const stageIcon = document.getElementById("icon-" + stageKey);
                        if (stageIcon) {{
                            stageIcon.innerHTML = spinnerSvg;
                            stageIcon.style.color = "var(--accent)";
                        }}

                        addActivityEntry(data.stage_index || 1, data.stage_total || 11, data.stage_name || stageKey, data.message || "Processing", false);
                    }} else if (data.type === "stage_complete") {{
                        const stageKey = data.stage;
                        const stageIcon = document.getElementById("icon-" + stageKey);
                        if (stageIcon) {{
                            stageIcon.innerHTML = checkmarkSvg;
                            stageIcon.style.color = "var(--success)";
                        }}
                        addActivityEntry(data.stage_index || 1, data.stage_total || 11, data.stage_name || stageKey, "Completed successfully.", true);
                    }} else if (data.type === "completed") {{
                        eventSource.close();
                        showReportReady(data);
                    }} else if (data.type === "failed") {{
                        eventSource.close();
                        showFailure(data.message, data);
                    }}
                }} catch (e) {{
                    console.error("SSE parse error", e);
                }}
            }};

            eventSource.onerror = function() {{
                if (!isJobTerminated) {{
                    const banner = document.getElementById("connection-lost-banner");
                    if (banner) banner.style.display = "flex";
                    addLogEntry("Connection lost. Retrying…", "active");
                    if (!pollingInterval) {{
                        pollJobStatus();
                        pollingInterval = setInterval(pollJobStatus, 2500);
                    }}
                }}
            }};
        }}
    </script>
    """

    content = f"""
    <style>
    .progress-stepper {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        position: relative;
        margin: 2rem 0;
        gap: 1rem;
    }}
    .progress-stepper::before {{
        content: '';
        position: absolute;
        top: 16px;
        left: 24px;
        right: 24px;
        height: 2px;
        background: var(--border);
        z-index: 0;
    }}
    .stepper-step {{
        display: flex;
        flex-direction: column;
        align-items: center;
        position: relative;
        z-index: 1;
        text-align: center;
        flex: 1;
    }}
    .stepper-circle {{
        width: 32px;
        height: 32px;
        border-radius: 50%;
        background: var(--surface);
        border: 2px solid var(--border);
        color: var(--text-muted);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.8125rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
        transition: all 0.25s ease;
    }}
    .stepper-step.done .stepper-circle {{
        background: var(--accent);
        border-color: var(--accent);
        color: #ffffff;
    }}
    .stepper-step.active .stepper-circle {{
        border-color: var(--accent);
        color: var(--accent);
        background: var(--surface-2);
    }}
    .stepper-step.failed .stepper-circle {{
        background: rgba(239, 91, 91, 0.15);
        border-color: var(--danger);
        color: var(--danger);
    }}
    .stepper-step.upcoming .stepper-circle {{
        background: var(--surface-2);
        border-color: var(--border);
        color: var(--text-muted);
    }}
    .stepper-label {{
        font-size: 0.8125rem;
        font-weight: 500;
        color: var(--text-muted);
        transition: color 0.25s ease;
    }}
    .stepper-step.done .stepper-label,
    .stepper-step.active .stepper-label {{
        color: var(--text);
        font-weight: 600;
    }}
    .stepper-step.failed .stepper-label {{
        color: var(--danger);
        font-weight: 600;
    }}

    @keyframes spin {{
        from {{ transform: rotate(0deg); }}
        to {{ transform: rotate(360deg); }}
    }}
    .stepper-spinner {{
        animation: spin 1s linear infinite;
    }}

    @media (max-width: 600px) {{
        .progress-stepper {{
            flex-direction: column;
            align-items: flex-start;
            gap: 1.25rem;
            margin: 1.5rem 0;
        }}
        .progress-stepper::before {{
            top: 16px;
            bottom: 16px;
            left: 15px;
            width: 2px;
            height: auto;
            right: auto;
        }}
        .stepper-step {{
            flex-direction: row;
            align-items: center;
            gap: 0.85rem;
            text-align: left;
            width: 100%;
        }}
        .stepper-circle {{
            margin-bottom: 0;
            flex-shrink: 0;
        }}
    }}

    .progress-bar-track {{
        height: 6px;
        background: var(--surface-2);
        border-radius: 999px;
        overflow: hidden;
        position: relative;
    }}
    .progress-bar-fill {{
        height: 100%;
        border-radius: 999px;
        background: var(--accent);
        transition: width 0.4s ease;
    }}
    @keyframes indeterminate-slide {{
        0% {{ transform: translateX(-100%); }}
        100% {{ transform: translateX(350%); }}
    }}
    .progress-bar-fill.indeterminate {{
        width: 30%;
        animation: indeterminate-slide 1.5s infinite ease-in-out;
    }}

    .stat-pill {{
        background: var(--surface-2);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 0.5rem 0.85rem;
        display: inline-flex;
        flex-direction: column;
        min-width: 110px;
    }}
    .stat-pill-label {{
        font-size: 0.8125rem;
        color: var(--text-muted);
        font-weight: 500;
    }}
    .stat-pill-value {{
        font-size: 0.9375rem;
        font-weight: 600;
        color: var(--text);
        margin-top: 0.15rem;
    }}

    .details-stage-row {{
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.6rem 0.75rem;
        border-radius: 6px;
        transition: background 0.2s ease;
    }}
    .details-stage-row:hover {{
        background: var(--surface-2);
    }}
    .details-stage-icon {{
        width: 20px;
        height: 20px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }}
    </style>

    <div id="elapsed-timer-badge" style="display: none;">
        <span id="elapsed-timer-text">{timer_badge_text}</span>
    </div>

    <div style="margin-bottom: 1.5rem;">
        <div style="margin-bottom: 0.75rem;">
            <a href="/dashboard" style="display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.8125rem; color: var(--text-muted); text-decoration: none;">
                &larr; Back to dashboard
            </a>
        </div>
        <h1 style="font-size: 1.75rem; font-weight: 600; color: var(--text); margin: 0; letter-spacing: -0.02em;">
            Analyzing {owner}/{repo}
        </h1>
    </div>

    <!-- Stepper (4 Phases) -->
    {stepper_html}

    <!-- Lost Connection Banner -->
    <div id="connection-lost-banner" style="display: none; background: rgba(245, 158, 11, 0.1); border: 1px solid #f59e0b; color: #f59e0b; padding: 0.75rem 1rem; border-radius: var(--radius); margin-bottom: 1.5rem; font-size: 0.875rem; align-items: center; gap: 0.5rem;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
        <span>Connection lost. Retrying…</span>
    </div>

    <!-- ONE Active Progress Card (while running) -->
    <div class="active-progress-card" id="active-card" style="display: {active_card_display}; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.5rem; margin-bottom: 1.5rem;">
        <div id="active-sentence" style="font-size: 1.125rem; font-weight: 500; color: var(--text); margin-bottom: 1rem;">
            {initial_sentence}
        </div>
        <div class="progress-bar-track" style="margin-bottom: 0.75rem;">
            <div id="progress-bar-fill" class="progress-bar-fill indeterminate"></div>
        </div>
        <div id="active-timer-display" style="font-size: 0.8125rem; color: var(--text-muted); font-family: var(--font-mono);">
            Elapsed <span id="active-card-timer">{initial_timer_str}</span> · usually 10–30 seconds
        </div>
    </div>

    <!-- End State: Report Ready Card -->
    <div class="card report-ready-card" id="report-ready-card" style="display: {report_ready_display}; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.75rem; margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1.25rem;">
            <div style="width: 32px; height: 32px; border-radius: 50%; background: rgba(62, 207, 142, 0.15); color: var(--success); display: flex; align-items: center; justify-content: center;">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
            </div>
            <div>
                <h2 style="font-size: 1.25rem; font-weight: 600; color: var(--text); margin: 0;">Report ready</h2>
                <p style="font-size: 0.8125rem; color: var(--text-muted); margin: 0.15rem 0 0 0;">Repository analysis completed successfully.</p>
            </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 1rem; margin-bottom: 1.5rem;">
            <div class="stat-card" style="background: var(--surface-2); padding: 1rem; border-radius: 6px; border: 1px solid var(--border);">
                <div style="font-size: 0.8125rem; color: var(--text-muted); ">Files analyzed</div>
                <div id="ready-files-count" style="font-size: 1.5rem; font-weight: 700; color: var(--text); margin-top: 0.25rem;">{files_analyzed}</div>
            </div>
            <div class="stat-card" style="background: var(--surface-2); padding: 1rem; border-radius: 6px; border: 1px solid var(--border);">
                <div style="font-size: 0.8125rem; color: var(--text-muted); ">Modules</div>
                <div id="ready-modules-count" style="font-size: 1.5rem; font-weight: 700; color: var(--text); margin-top: 0.25rem;">{modules_count}</div>
            </div>
            <div class="stat-card" style="background: var(--surface-2); padding: 1rem; border-radius: 6px; border: 1px solid var(--border);">
                <div style="font-size: 0.8125rem; color: var(--text-muted); ">Entry points</div>
                <div id="ready-entry-count" style="font-size: 1.5rem; font-weight: 700; color: var(--text); margin-top: 0.25rem;">{entry_points_count}</div>
            </div>
        </div>
        <a href="/report/{job_id}" class="btn btn-primary" id="start-learning-btn" style="display: inline-flex; align-items: center; gap: 0.5rem; font-size: 0.9375rem; padding: 0.65rem 1.25rem;">
            Start learning &rarr;
        </a>
    </div>

    <!-- End State: Failed Card -->
    <div class="card failed-card" id="failed-card" style="display: {failed_card_display}; background: rgba(239, 91, 91, 0.06); border: 1px solid var(--danger); border-radius: var(--radius); padding: 1.5rem; margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: flex-start; gap: 0.85rem; margin-bottom: 1rem;">
            <div style="width: 32px; height: 32px; border-radius: 50%; background: rgba(239, 91, 91, 0.15); color: var(--danger); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
            </div>
            <div>
                <h2 style="font-size: 1.15rem; font-weight: 600; color: var(--danger); margin: 0 0 0.35rem 0;">Analysis failed</h2>
                <p id="failed-reason-text" style="font-size: 0.875rem; color: var(--text); margin: 0; line-height: 1.5;">
                    {mapped_error_reason}
                </p>
            </div>
        </div>
        <div style="display: flex; gap: 0.75rem; align-items: center; margin-top: 1.25rem;">
            <form action="/analyses/{job_id}/retry" method="POST" style="margin: 0; display: inline;">
                <button type="submit" class="btn btn-primary" id="retry-btn">Retry</button>
            </form>
            <a href="/dashboard" class="btn btn-secondary">Back to dashboard</a>
        </div>
    </div>

    <!-- End State: Cancelled Card -->
    <div class="card cancelled-card" id="cancelled-card" style="display: {cancelled_card_display}; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.5rem; margin-bottom: 1.5rem;">
        <h2 style="font-size: 1.15rem; font-weight: 600; color: var(--text); margin: 0 0 0.35rem 0;">Analysis cancelled</h2>
        <p style="font-size: 0.875rem; color: var(--text-muted); margin: 0 0 1.25rem 0;">This analysis was cancelled.</p>
        <a href="/dashboard" class="btn btn-secondary">Back to dashboard</a>
    </div>

    <!-- Cancel Button (while running) -->
    <form action="/jobs/{job_id}/cancel" method="POST" id="cancel-form" style="display: {cancel_form_display}; margin-bottom: 1.5rem;">
        <button type="submit" class="btn btn-secondary" id="cancel-btn">
            Cancel
        </button>
    </form>

    <!-- Details Toggle (collapsed by default) -->
    <details class="details-toggle" id="details-toggle" style="background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 1.5rem;">
        <summary style="padding: 1rem 1.25rem; font-size: 0.875rem; font-weight: 500; color: var(--text); cursor: pointer; user-select: none;">
            Details
        </summary>
        <div style="padding: 0 1.25rem 1.25rem 1.25rem; border-top: 1px solid var(--border);">
            <div style="margin-top: 1rem; margin-bottom: 1.5rem;">
                <h4 style="font-size: 0.8125rem; color: var(--text-muted); margin: 0 0 0.75rem 0;">Pipeline stages</h4>
                {stages_list_html}
            </div>
            <div>
                <h4 style="font-size: 0.8125rem; color: var(--text-muted); margin: 0 0 0.5rem 0;">Event log</h4>
                <div id="sse-terminal-log" style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: 0.85rem; max-height: 200px; overflow-y: auto; font-family: var(--font-mono); font-size: 0.8125rem; line-height: 1.6; color: var(--text);"></div>
            </div>
        </div>
    </details>
    """
    page_title = f"{owner}/{repo}" if owner else repo
    return page_shell(
        page_title,
        content,
        current_user=current_user,
        active_route=f"/progress/{job_id}",
        billing_status=billing_status,
        extra_scripts=extra_scripts,
    )



def _parse_report_markdown(raw_markdown: str) -> Dict[str, Any]:
    """Parse synthesized markdown into structured sections while preserving full content fidelity."""
    if not raw_markdown:
        return {}

    result = {
        "title": "",
        "synthesized_at": "",
        "overview": {},
        "domain_distribution": [],
        "confidence_calibration": "",
        "milestones": [],
        "raw_markdown": raw_markdown
    }

    # Title and timestamp
    t_match = re.search(r"^#\s+Architectural Reverse-Engineering Report:\s*`?([^`\n]+)`?", raw_markdown, re.MULTILINE)
    if t_match:
        result["title"] = t_match.group(1).strip()

    time_match = re.search(r"\*Synthesized at:\s*([^*]+)\*", raw_markdown)
    if time_match:
        result["synthesized_at"] = time_match.group(1).strip()

    # Executive Overview key facts
    lang_m = re.search(r"\*\*Primary Language\*\*:\s*`?([^`\n]+)`?", raw_markdown)
    files_m = re.search(r"\*\*Total Analyzed Files\*\*:\s*`?(\d+)`?", raw_markdown)
    domains_m = re.search(r"\*\*Domain Categories\*\*:\s*`?(\d+)`?", raw_markdown)
    entry_m = re.search(r"\*\*Entry Point Files\*\*:\s*`?([^`\n]+)`?", raw_markdown)
    cyclic_m = re.search(r"\*\*(?:Cyclic Core Components|Circular Dependency Components)\*\*:\s*`?(\d+)`?", raw_markdown)
    isolated_m = re.search(r"\*\*Isolated / Support Files\*\*:\s*`?(\d+)`?", raw_markdown)

    result["overview"] = {
        "primary_language": lang_m.group(1).strip() if lang_m else "Unknown",
        "total_files": int(files_m.group(1)) if files_m else 0,
        "total_domains": int(domains_m.group(1)) if domains_m else 0,
        "entry_points": [e.strip() for e in entry_m.group(1).split(",") if e.strip() and e.strip() != "None"] if entry_m else [],
        "cyclic_files": int(cyclic_m.group(1)) if cyclic_m else 0,
        "isolated_files": int(isolated_m.group(1)) if isolated_m else 0,
    }

    # Domain Distribution Table
    domain_rows = re.findall(r"\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*([\d.]+%)\s*\|", raw_markdown)
    for dom, cnt, pct in domain_rows:
        result["domain_distribution"].append({
            "domain": dom.strip(),
            "count": int(cnt),
            "percentage": pct.strip()
        })

    # Confidence Calibration Section
    calib_section = re.search(r"## 2\. (?:Sequence Reasoning & Confidence Calibration|Build Order & Confidence Scoring)\s*\n([\s\S]*?)(?=\n## 3\.|\Z)", raw_markdown)
    if calib_section:
        result["confidence_calibration"] = calib_section.group(1).strip()

    # Milestones Extraction
    milestones_section = re.search(r"## 3\. Step-by-Step Architectural Milestones\s*\n([\s\S]*)$", raw_markdown)
    if milestones_section:
        m_text = milestones_section.group(1)
        raw_milestones = re.split(r"\n(?=###\s+(?:Milestone|Test\s+files)\s+[T\d]+:)", m_text)
        for raw_m in raw_milestones:
            raw_m = raw_m.strip()
            if not (raw_m.startswith("### Milestone") or raw_m.startswith("### Test files")):
                continue

            h_match = re.match(r"###\s+(Milestone|Test\s+files)\s+([T\d]+):\s*(.+)", raw_m)
            if not h_match:
                continue

            prefix_type = h_match.group(1).strip()
            track_label = "Milestone" if "Milestone" in prefix_type else "Test files"
            display_id = h_match.group(2).strip()
            num_part = re.sub(r"\D", "", display_id)
            if track_label == "Test files":
                test_counter = len([m for m in result["milestones"] if m.get("track_label") == "Test files"]) + 1
                parsed_num = int(num_part) if num_part else test_counter
                core_tiers = [m.get("tier", 0) for m in result["milestones"] if m.get("track_label") != "Test files"]
                max_core = max(core_tiers) if core_tiers else 0
                m_tier = max_core + parsed_num
            else:
                m_tier = int(num_part) if num_part else 1
            m_title_raw = h_match.group(3).strip()
            m_title = re.sub(r"\s*\(Tier\s+\d+\)$", "", m_title_raw)

            badge_m = re.search(r"\*\*\[([^\]]+)\]\*\*\s*--\s*\*(.+?)\*", raw_m)
            confidence_badge = badge_m.group(1).strip() if badge_m else ""
            architectural_role = badge_m.group(2).strip() if badge_m else ""

            is_cyclic = "*[CYCLIC CORE]*" in raw_m or "*[CIRCULAR DEPENDENCY]*" in raw_m
            is_isolated = "*[ISOLATED COMPONENT]*" in raw_m

            overview_m = re.search(r"\*\*Overview:\*\*\s*(.+?)(?=\n\n\*\*|\n\*\*|\Z)", raw_m, re.DOTALL)
            overview = overview_m.group(1).strip() if overview_m else ""

            domain_comp_m = re.search(r"\*\*Domain Composition:\*\*\s*(.+?)(?=\n\n|\n\*\*|\Z)", raw_m)
            domain_composition = domain_comp_m.group(1).strip() if domain_comp_m else ""

            files_section_m = re.search(r"\*\*Included Files(?:\s*\(\d+\))?:\*\*\s*\n((?:-\s*`[^`]+`\s*\n?)+)", raw_m)
            included_files = []
            if files_section_m:
                included_files = re.findall(r"-\s*`([^`]+)`", files_section_m.group(1))

            symbols_m = re.search(r"\*\*Key Exported Symbols:\*\*\s*`([^`]+)`", raw_m)
            exported_symbols = [s.strip() for s in symbols_m.group(1).split(",") if s.strip() and not s.strip().startswith("_")] if symbols_m else []

            citations_m = re.search(r"\*\*Deep-Dive Semantic Citations:\*\*\s*\n((?:-\s*.+\n?)+)", raw_m)
            citations = []
            if citations_m:
                citations = [line.strip().lstrip("- ") for line in citations_m.group(1).strip().split("\n") if line.strip()]

            pedagogical_m = re.search(r"\*\*Pedagogical Notes:\*\*\s*\n((?:-\s*.+\n?)+)", raw_m)
            pedagogical_notes = []
            if pedagogical_m:
                pedagogical_notes = [line.strip().lstrip("- ") for line in pedagogical_m.group(1).strip().split("\n") if line.strip()]

            gotchas_m = re.search(r"> \*\*Implementation Gotchas:\*\*\s*\n((?:>\s*-\s*.+\n?)+)", raw_m)
            gotchas = []
            if gotchas_m:
                gotchas = [line.strip().lstrip("> - ").strip() for line in gotchas_m.group(1).strip().split("\n") if line.strip()]

            result["milestones"].append({
                "tier": m_tier,
                "display_id": display_id,
                "track_label": track_label,
                "track": "test_track" if track_label == "Test files" else "core",
                "title": m_title,
                "confidence_badge": confidence_badge,
                "architectural_role": architectural_role,
                "is_cyclic": is_cyclic,
                "is_isolated": is_isolated,
                "overview": overview,
                "domain_composition": domain_composition,
                "included_files": included_files,
                "exported_symbols": exported_symbols,
                "citations": citations,
                "pedagogical_notes": pedagogical_notes,
                "gotchas": gotchas,
                "raw_block": raw_m
            })

    return result


def _render_confidence_badge_with_tooltip(
    badge_text: str,
    dominant_conf: Optional[str] = None,
) -> str:
    """
    Renders an accessible confidence badge with an interactive info icon (ⓘ) and tooltip
    explaining the underlying Layer 6 Stage C sequence scoring logic.
    """
    clean_badge = sanitize_text(badge_text) if badge_text else "HIGH CONFIDENCE"
    upper_badge = clean_badge.upper()

    if "HIGH" in upper_badge:
        level = "high"
        badge_cls = "badge-teal"
        level_title = "HIGH CONFIDENCE"
        level_desc = "Reconstructed with high certainty using a clear, verified chain of imports and commit history."
    elif "MEDIUM" in upper_badge:
        level = "medium"
        badge_cls = "badge-amber"
        level_title = "MEDIUM CONFIDENCE"
        level_desc = "Ordering derived using a standard ordering pattern (config, then database, then core logic, then endpoints, then tests) or LLM tie-breaking due to identical or absent commit timestamps."
    else:
        level = "low"
        badge_cls = "badge-brass"
        level_title = "LOW CONFIDENCE"
        level_desc = "Ordering is an educated structural estimate due to cyclic co-dependencies (circular imports), isolated standalone files, or reduced history confidence."

    return f"""<div class="tooltip-container" style="display: inline-flex; align-items: center; position: relative;"><span class="badge {badge_cls}">{clean_badge}</span><button type="button" class="info-icon-btn" aria-expanded="false" aria-haspopup="dialog" aria-label="Confidence scoring explanation" onclick="toggleConfidencePopover(this, event)">ⓘ</button><div class="confidence-tooltip" role="tooltip" aria-hidden="true"><div style="font-weight: 600; color: var(--text); margin-bottom: 0.25rem; display: flex; align-items: center; justify-content: space-between;"><span>Sequence Confidence</span><span class="badge {badge_cls}" style="font-size: 0.8125rem; padding: 0.1rem 0.35rem;">{level_title}</span></div><div style="color: var(--text-muted); font-size: 0.8125rem; margin-bottom: 0.35rem; line-height: 1.4;">{level_desc}</div><div style="border-top: 1px solid var(--hairline-soft); padding-top: 0.35rem; font-size: 0.8125rem; color: var(--text-muted); line-height: 1.4;"><div>&bull; <strong style="color: var(--success);">High:</strong> Verified imports and commit history</div><div>&bull; <strong style="color: var(--amber);">Medium:</strong> Estimated from common code patterns</div><div>&bull; <strong style="color: var(--crimson);">Low:</strong> Circular dependencies, standalone files, or unclear history</div></div></div></div>"""


def _render_confidence_info_icon(level: str = "high") -> str:
    """Renders a standalone info icon (ⓘ) with click/touch-to-open confidence scoring popover."""
    lvl = (level or "high").lower()
    if lvl == "high":
        badge_cls = "badge-teal"
        level_title = "HIGH CONFIDENCE"
        level_desc = "Reconstructed with high certainty using a clear, verified chain of imports and commit history."
    elif lvl == "medium":
        badge_cls = "badge-amber"
        level_title = "MEDIUM CONFIDENCE"
        level_desc = "Ordering derived using a standard ordering pattern (config, then database, then core logic, then endpoints, then tests) or LLM tie-breaking due to identical or absent commit timestamps."
    else:
        badge_cls = "badge-brass"
        level_title = "LOW CONFIDENCE"
        level_desc = "Ordering is an educated structural estimate due to cyclic co-dependencies (circular imports), isolated standalone files, or reduced history confidence."

    return f"""<div class="tooltip-container" style="display: inline-flex; align-items: center; position: relative;"><button type="button" class="info-icon-btn" aria-expanded="false" aria-haspopup="dialog" aria-label="Confidence scoring explanation" onclick="toggleConfidencePopover(this, event)">ⓘ</button><div class="confidence-tooltip" role="tooltip" aria-hidden="true"><div style="font-weight: 600; color: var(--text); margin-bottom: 0.25rem; display: flex; align-items: center; justify-content: space-between;"><span>Sequence Confidence</span><span class="badge {badge_cls}" style="font-size: 0.8125rem; padding: 0.1rem 0.35rem;">{level_title}</span></div><div style="color: var(--text-muted); font-size: 0.8125rem; margin-bottom: 0.35rem; line-height: 1.4;">{level_desc}</div><div style="border-top: 1px solid var(--hairline-soft); padding-top: 0.35rem; font-size: 0.8125rem; color: var(--text-muted); line-height: 1.4;"><div>&bull; <strong style="color: var(--success);">High:</strong> Verified imports and commit history</div><div>&bull; <strong style="color: var(--amber);">Medium:</strong> Estimated from common code patterns</div><div>&bull; <strong style="color: var(--crimson);">Low:</strong> Circular dependencies, standalone files, or unclear history</div></div></div></div>"""



def _truncate_path_middle(path: str, max_len: int = 28) -> str:
    """
    Truncates a file path from the middle with '...' so both the repo root prefix
    and the filename tail remain visible and identifiable.
    """
    if not path or len(path) <= max_len:
        return path
    if max_len <= 3:
        return path[:max_len]
    available = max_len - 3
    head_len = available // 2
    tail_len = available - head_len
    return f"{path[:head_len]}...{path[-tail_len:]}"


def _render_grouped_fill_chips(
    blanked_functions: List[Dict[str, Any]],
    fallback_reason: Optional[str] = None,
) -> str:
    """Renders Fill the Blanks target function chips grouped by class/module with auto-collapsing for large lists."""
    if not blanked_functions:
        reason_text = html.escape(fallback_reason or "File contains no function bodies to blank.")
        return f'<span style="font-size: 0.8125rem; color: var(--text-muted); font-style: italic;">{reason_text}</span>'

    total_count = len(blanked_functions)
    should_collapse = total_count > 15

    group_order: List[str] = []
    groups: Dict[str, Dict[str, Any]] = {}

    for bf in blanked_functions:
        class_name = bf.get("class_name") or ""
        group_key = class_name if class_name else "__toplevel__"
        if group_key not in groups:
            groups[group_key] = {
                "class_name": class_name,
                "is_class": bool(class_name),
                "items": [],
            }
            group_order.append(group_key)
        groups[group_key]["items"].append(bf)

    html_parts = []
    for key in group_order:
        g = groups[key]
        count = len(g["items"])
        group_title = f"class {html.escape(g['class_name'])}" if g["is_class"] else "Top-level Functions"
        count_label = f"{count} {'method' if count == 1 else 'methods'}" if g["is_class"] else f"{count} {'function' if count == 1 else 'functions'}"
        icon = "🏛️" if g["is_class"] else "📁"

        chips_html = "".join([
            f'<span class="mono" title="{html.escape(bf.get("full_name", bf.get("name", "")))}()" style="display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.15rem 0.45rem; background: var(--panel-raised); border: 1px solid var(--border); border-radius: 3px; font-size: 0.8125rem; color: var(--success);">🧩 {html.escape(bf.get("name", ""))}</span> '
            for bf in g["items"]
        ])

        open_attr = "" if should_collapse else " open"
        html_parts.append(
            f'<details{open_attr} class="fill-chip-group" style="margin-bottom: 0.4rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 0.35rem 0.6rem;">'
            f'<summary style="cursor: pointer; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); user-select: none; display: flex; align-items: center; justify-content: space-between;">'
            f'<span>{icon} {group_title} <span style="opacity: 0.7; font-weight: normal; font-size: 0.8125rem;">({count_label})</span></span>'
            f'<span style="font-size: 0.8125rem; color: var(--text-muted);">▾</span>'
            f'</summary>'
            f'<div style="display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.4rem; padding-top: 0.35rem; border-top: 1px solid var(--hairline-soft);">{chips_html}</div>'
            f'</details>'
        )

    return "".join(html_parts)


def _render_server_diff_html(
    verification: Optional[Dict[str, Any]],
    is_verified: Optional[bool] = None,
    err_msg: Optional[str] = None,
    grading_method: Optional[str] = None,
    grading_details: Optional[Dict[str, Any]] = None,
) -> str:
    """Renders server-side HTML for a structural verification diff with tiered grading badge."""
    if not verification:
        return ""

    if is_verified is None:
        is_verified = verification.get("structurally_verified", False) or verification.get("is_verified", False)
    if err_msg is None:
        err_msg = verification.get("error_message") or verification.get("error") or verification.get("grading_error")
    if grading_method is None:
        grading_method = verification.get("grading_method", "structural_only")

    present_syms = verification.get("present_symbols", verification.get("present", []))
    missing_syms = verification.get("missing_symbols", verification.get("missing", []))
    extra_syms = verification.get("extra_symbols", verification.get("extra", []))

    # Tier Badge formatting
    if grading_method == "real_tests":
        tier_tag = '<span class="badge badge-teal" style="font-size: 0.8125rem; ">Tier 1: Real reproduction</span>'
    elif grading_method == "expected_output":
        tier_tag = '<span class="badge badge-amber" style="font-size: 0.8125rem; ">Tier 2: Expected interface</span>'
    elif grading_method == "fill_the_blanks":
        tier_tag = '<span class="badge badge-teal" style="font-size: 0.8125rem; ">Tier 3: Fill the blanks</span>'
    else:
        tier_tag = '<span class="badge badge-brass" style="font-size: 0.8125rem; ">Tier 3: Structural verification</span>'

    if is_verified:
        banner = f"""
        <div class="diff-banner success" style="background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--success); padding: 0.65rem 0.85rem; border-radius: 4px; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; margin-bottom: 0.65rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; flex-wrap: wrap;">
            <div style="display: flex; align-items: center; gap: 0.4rem;">
                <span>✓</span> VERIFIED: Milestone requirements fulfilled
            </div>
            {tier_tag}
        </div>
        """
    else:
        banner = f"""
        <div class="diff-banner failure" style="background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.65rem 0.85rem; border-radius: 4px; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; margin-bottom: 0.65rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; flex-wrap: wrap;">
            <div style="display: flex; align-items: center; gap: 0.4rem;">
                <span>⚠</span> VERIFICATION GAPS: Requirements not yet satisfied
            </div>
            {tier_tag}
        </div>
        """

    err_html = f"""<div style="color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem; margin-bottom: 0.5rem; background: rgba(244,63,94,0.08); padding: 0.5rem; border-radius: 3px;">{sanitize_text(err_msg)}</div>""" if err_msg else ""

    # Check for Fill the Blanks grading results specially
    blank_details = verification.get("blank_details", [])
    if grading_method == "fill_the_blanks" or blank_details or "blanked_evaluated" in verification:
        blanked_count = verification.get("blanked_evaluated", len(blank_details))
        implemented_count = verification.get("implemented_count", sum(1 for b in blank_details if b.get("status") == "implemented"))
        implemented_pills = ""
        stub_pills = ""
        for b in blank_details:
            name = sanitize_text(b.get("name", "function"))
            if b.get("status") == "implemented":
                implemented_pills += f"""<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--success); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-mono); font-size: 0.8125rem;">✓ {name}() <span style="opacity: 0.75; font-size: 0.8125rem;">(implemented)</span></span> """
            else:
                reason = sanitize_text(b.get("reason", "unimplemented stub"))
                stub_pills += f"""<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-mono); font-size: 0.8125rem;">✗ {name}() <span style="opacity: 0.75; font-size: 0.8125rem;">({reason})</span></span> """

        is_all_done = (implemented_count == blanked_count and blanked_count > 0)
        fill_summary = f"{implemented_count}/{blanked_count} functions completed" + (" ✓" if is_all_done else "")
        fill_sections_html = f"""<div style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.4rem;">Scoped blanks evaluated: <strong>{implemented_count} / {blanked_count}</strong> completed.</div>"""
        if implemented_pills:
            fill_sections_html += f"""
            <details class="matched-symbols-collapse" style="background: var(--surface-2); border: 1px solid var(--teal-border); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;">
                <summary style="cursor: pointer; font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--success); display: flex; align-items: center; justify-content: space-between; user-select: none;">
                    <span>Implemented blanks ({fill_summary}):</span>
                    <span style="font-size: 0.8125rem; opacity: 0.85; font-weight: normal;">View list ▾</span>
                </summary>
                <div style="display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem; padding-top: 0.4rem; border-top: 1px solid var(--hairline-soft);">
                    {implemented_pills}
                </div>
            </details>
            """
        if stub_pills:
            fill_sections_html += f"""
            <div style="background: rgba(244, 63, 94, 0.06); border: 1px solid rgba(244, 63, 94, 0.25); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;">
                <div style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--crimson); font-weight: 600; margin-bottom: 0.35rem;">Unimplemented / stub blanks:</div>
                <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">{stub_pills}</div>
            </div>
            """
        return f"""
        {banner}
        {err_html}
        <div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.5rem;">
            {fill_sections_html}
        </div>
        """

    present_pills = ""
    for s in present_syms:
        mat = s.get("matched", {}) or s.get("expected", {})
        name = sanitize_text(mat.get("name", ""))
        kind = sanitize_text(mat.get("kind", "symbol"))
        raw_args = mat.get("args", [])
        safe_args = [sanitize_text(arg) for arg in raw_args] if isinstance(raw_args, list) else []
        args_str = f"({', '.join(safe_args)})" if safe_args else ""
        present_pills += f"""<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--success); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-mono); font-size: 0.8125rem;">✓ {name}{args_str} <span style="opacity: 0.75; font-size: 0.8125rem;">({kind})</span></span> """

    missing_pills = ""
    for s in missing_syms:
        name = sanitize_text(s.get("name", "") if isinstance(s, dict) else str(s))
        kind = sanitize_text(s.get("kind", "required") if isinstance(s, dict) else "required")
        missing_pills += f"""<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-mono); font-size: 0.8125rem;">✗ {name} <span style="opacity: 0.75; font-size: 0.8125rem;">({kind})</span></span> """

    extra_pills = ""
    for s in extra_syms:
        name = sanitize_text(s.get("name", "") if isinstance(s, dict) else str(s))
        kind = sanitize_text(s.get("kind", "extra") if isinstance(s, dict) else "extra")
        extra_pills += f"""<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: var(--panel-raised); border: 1px solid var(--border); color: var(--text-muted); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-mono); font-size: 0.8125rem;">+ {name} <span style="opacity: 0.75; font-size: 0.8125rem;">({kind})</span></span> """

    total_expected = len(present_syms) + len(missing_syms)
    is_all_matched = (len(missing_syms) == 0 and total_expected > 0)
    matched_summary_str = f"{len(present_syms)}/{total_expected} symbols matched" + (" ✓" if is_all_matched else "") if total_expected > 0 else f"{len(present_syms)} matched"

    sections_html = ""
    if present_pills:
        sections_html += f"""
        <details class="matched-symbols-collapse" style="background: var(--surface-2); border: 1px solid var(--teal-border); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;">
            <summary style="cursor: pointer; font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--success); display: flex; align-items: center; justify-content: space-between; user-select: none;">
                <span>Present &amp; matched symbols ({matched_summary_str}):</span>
                <span style="font-size: 0.8125rem; opacity: 0.85; font-weight: normal;">View list ▾</span>
            </summary>
            <div style="display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem; padding-top: 0.4rem; border-top: 1px solid var(--hairline-soft);">
                {present_pills}
            </div>
        </details>
        """
    if missing_pills:
        sections_html += f"""
        <div style="background: rgba(244, 63, 94, 0.06); border: 1px solid rgba(244, 63, 94, 0.25); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;">
            <div style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--crimson); font-weight: 600; margin-bottom: 0.35rem;">Missing expected symbols ({len(missing_syms)}):</div>
            <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">{missing_pills}</div>
        </div>
        """
    if extra_pills:
        sections_html += f"""
        <div style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;">
            <div style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); font-weight: 600; margin-bottom: 0.35rem;">Extra / auxiliary symbols ({len(extra_syms)}):</div>
            <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">{extra_pills}</div>
        </div>
        """

    return f"""
    {banner}
    {err_html}
    <div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.5rem;">
        {sections_html}
    </div>
    """


def _render_server_console_html(attempt: Optional[Any]) -> str:
    """Renders server-side HTML for previous execution run output."""
    if not attempt:
        return ""
    last_run_at = attempt.get("last_run_at") if isinstance(attempt, dict) else getattr(attempt, "last_run_at", None)
    if last_run_at is None:
        return ""

    exit_code = (attempt.get("last_run_exit_code") if isinstance(attempt, dict) else getattr(attempt, "last_run_exit_code", 0)) or 0
    is_success = (exit_code == 0)
    stdout = (attempt.get("last_run_stdout") if isinstance(attempt, dict) else getattr(attempt, "last_run_stdout", "")) or ""
    stderr = (attempt.get("last_run_stderr") if isinstance(attempt, dict) else getattr(attempt, "last_run_stderr", "")) or ""

    exit_badge_cls = "badge-teal" if is_success else "badge-crimson"
    exit_badge_text = f"EXIT {exit_code}"

    content = ""
    if stdout:
        content += f'<div style="color: #e2e8f0; white-space: pre-wrap; word-break: break-all; margin-bottom: 0.5rem;">{html.escape(stdout)}</div>'
    if stderr:
        content += f'<div style="color: var(--crimson); white-space: pre-wrap; word-break: break-all; margin-top: 0.25rem;">{html.escape(stderr)}</div>'
    if not stdout and not stderr:
        content = '<div style="color: var(--text-muted); font-style: italic;">(Process completed with no output)</div>'

    last_run_str = last_run_at.strftime("%H:%M:%S") if hasattr(last_run_at, "strftime") else str(last_run_at)[:8]
    time_badge = f'<span class="tag" style="font-size: 0.8125rem;">{last_run_str}</span>' if last_run_str else ""
    dot_color = "teal" if is_success else "crimson"

    return f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem;">
        <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span class="chip-dot {dot_color}"></span>
            <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text); ">Execution Console</span>
            <span class="badge {exit_badge_cls}" style="font-size: 0.8125rem;">{exit_badge_text}</span>
            {time_badge}
        </div>
        <span style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted);">Unmetered playground</span>
    </div>
    <pre style="background: #0d0e12; padding: 0.75rem; border-radius: 3px; border: 1px solid var(--hairline-soft); font-family: var(--font-mono); font-size: 0.8125rem; line-height: 1.45; overflow-x: auto; margin: 0;"><code>{content}</code></pre>
    """


def extract_readme_summary(readme_text: Optional[str]) -> str:
    """Extracts first paragraph from README (strips markdown, max 300 chars).
    If no README or paragraph found, returns 'No README found.'.
    Builds from analysis data only, no LLM call, no invented facts.
    """
    if not readme_text or not isinstance(readme_text, str) or not readme_text.strip():
        return "No README found."

    text = readme_text.strip()
    # 1. Remove HTML comments
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    # 2. Remove fenced code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    # 3. Remove badges: linked image badges [![...](...)](...)
    text = re.sub(r"\[\s*!\[[^\]]*\]\([^)]*\)\s*\]\([^)]*\)", "", text)
    # 4. Remove standalone image badges: ![...](...)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # 5. Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # 6. Replace markdown links [label](url) with label
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # 7. Remove markdown headers
    text = re.sub(r"^\s*#+.*$", "", text, flags=re.MULTILINE)
    # 8. Remove markdown table rows
    text = re.sub(r"^\s*\|.*$", "", text, flags=re.MULTILINE)
    # 9. Remove blockquote arrows and list bullets
    text = re.sub(r"^\s*>[>\s]*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    # 10. Remove bold, italic, strikethrough, backtick formatting
    text = re.sub(r"[*_~`]+", "", text)

    # 11. Split into paragraphs by blank lines
    paragraphs = re.split(r"\n\s*\n", text)
    for p in paragraphs:
        cleaned = " ".join(p.split()).strip()
        if cleaned and len(cleaned) >= 5 and re.search(r"[a-zA-Z0-9]", cleaned):
            if len(cleaned) > 300:
                cleaned = cleaned[:300].rstrip()
            return cleaned

    return "No README found."


def get_main_language(nodes: List[Dict[str, Any]], overview_data: Dict[str, Any]) -> str:
    """The language with the most files."""
    lang_counts: Counter[str] = Counter()
    for n in nodes:
        lang = n.get("language")
        if not lang:
            p = str(n.get("path") or n.get("id") or "").lower()
            if p.endswith(".py"):
                lang = "Python"
            elif p.endswith((".js", ".jsx", ".mjs", ".cjs")):
                lang = "JavaScript"
            elif p.endswith((".ts", ".tsx")):
                lang = "TypeScript"
            elif p.endswith(".go"):
                lang = "Go"
            elif p.endswith(".rs"):
                lang = "Rust"
            elif p.endswith((".c", ".h")):
                lang = "C"
            elif p.endswith((".cpp", ".hpp", ".cc")):
                lang = "C++"
            elif p.endswith(".java"):
                lang = "Java"
            elif p.endswith(".rb"):
                lang = "Ruby"
            elif p.endswith(".php"):
                lang = "PHP"
        if lang:
            norm = str(lang).strip()
            norm = norm.capitalize() if norm.islower() else norm
            lang_counts[norm] += 1

    if lang_counts:
        return lang_counts.most_common(1)[0][0]

    primary = overview_data.get("primary_language", "Python")
    return primary.capitalize() if isinstance(primary, str) and primary.islower() else str(primary)


def get_start_here_entry_points(nodes: List[Dict[str, Any]], entry_points: List[str], max_n: int = 3) -> List[str]:
    """The application entry point(s) (from Prompt 3), max 3."""
    node_domain_map: Dict[str, str] = {}
    for n in nodes:
        nid = n.get("id") or n.get("path") or n.get("name")
        if nid:
            node_domain_map[str(nid)] = str(n.get("domain", n.get("type", ""))).lower()

    app_eps: List[str] = []
    for ep in entry_points:
        dom = node_domain_map.get(ep, "")
        ep_lower = ep.lower()
        if dom in ("tests", "benchmarks") or "/test" in ep_lower or "test_" in ep_lower or "_test." in ep_lower or "tests." in ep_lower or "bench" in ep_lower:
            continue
        if ep not in app_eps:
            app_eps.append(ep)
        if len(app_eps) == max_n:
            break
    return app_eps


def get_read_first_files(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], max_n: int = 3) -> List[str]:
    """Top 3 files by number of files that import them (deduped, from Prompt 3), excluding tests."""
    node_domain_map: Dict[str, str] = {}
    for n in nodes:
        nid = n.get("id") or n.get("path") or n.get("name")
        if nid:
            node_domain_map[str(nid)] = str(n.get("domain", n.get("type", ""))).lower()

    def is_test_path(path_str: str) -> bool:
        p_lower = path_str.lower()
        dom = node_domain_map.get(path_str, "")
        return (
            dom in ("tests", "benchmarks")
            or "/test" in p_lower
            or "test_" in p_lower
            or "_test." in p_lower
            or "tests." in p_lower
            or "bench" in p_lower
        )

    # Inbound importers: target is imported by source
    inbound_importers: Dict[str, Set[str]] = defaultdict(set)
    for e in edges:
        src = e.get("source") or e.get("from")
        tgt = e.get("target") or e.get("to")
        if src and tgt and src != tgt:
            if not is_test_path(tgt):
                inbound_importers[tgt].add(src)

    # Sort descending by number of distinct files importing them
    sorted_by_inbound = sorted(inbound_importers.keys(), key=lambda t: (-len(inbound_importers[t]), t))
    top_candidates = [f for f in sorted_by_inbound if not is_test_path(f)]

    # If not enough files with inbound edges, complement with non-test files from nodes
    if len(top_candidates) < max_n and nodes:
        for n in nodes:
            nid = n.get("path") or n.get("id")
            if nid and nid not in top_candidates and not is_test_path(nid):
                top_candidates.append(nid)
                if len(top_candidates) == max_n:
                    break

    return top_candidates[:max_n]


def count_code_and_docs_files(nodes: List[Dict[str, Any]], total_files: int) -> Tuple[int, int]:
    """Returns (code_count, docs_count) based on actual file types and paths."""
    doc_exts = {".md", ".markdown", ".rst", ".txt", ".doc", ".docx", ".pdf", ".rtf", ".tex"}
    docs = 0
    for n in nodes:
        path = str(n.get("path") or n.get("id") or "").lower()
        domain = str(n.get("domain", "")).lower()
        file_type = str(n.get("type", "")).lower()
        ext = os.path.splitext(path)[1]
        if ext in doc_exts or domain in ("docs", "documentation") or file_type in ("doc", "docs"):
            docs += 1

    if nodes:
        code = max(0, len(nodes) - docs)
        if total_files > len(nodes):
            code = max(0, total_files - docs)
    else:
        code = total_files
        docs = 0
    return code, docs


_MILESTONE_TOGGLE_JS = """
window.loadedMilestoneBodies = window.loadedMilestoneBodies || {};

function toggleConfidencePopover(btn, evt) {
    if (evt) evt.stopPropagation();
    const isExpanded = btn.getAttribute('aria-expanded') === 'true';
    document.querySelectorAll('.info-icon-btn').forEach(b => {
        if (b !== btn) {
            b.setAttribute('aria-expanded', 'false');
            const tt = b.parentElement ? b.parentElement.querySelector('.confidence-tooltip') : null;
            if (tt) {
                tt.classList.remove('is-open');
                tt.setAttribute('aria-hidden', 'true');
            }
        }
    });
    btn.setAttribute('aria-expanded', isExpanded ? 'false' : 'true');
    const tooltip = btn.parentElement ? btn.parentElement.querySelector('.confidence-tooltip') : null;
    if (tooltip) {
        if (isExpanded) {
            tooltip.classList.remove('is-open');
            tooltip.setAttribute('aria-hidden', 'true');
        } else {
            tooltip.classList.add('is-open');
            tooltip.setAttribute('aria-hidden', 'false');
        }
    }
}

document.addEventListener('click', function(e) {
    if (!e.target.closest('.tooltip-container')) {
        document.querySelectorAll('.info-icon-btn').forEach(b => {
            b.setAttribute('aria-expanded', 'false');
        });
        document.querySelectorAll('.confidence-tooltip').forEach(tt => {
            tt.classList.remove('is-open');
            tt.setAttribute('aria-hidden', 'true');
        });
    }
});

function selectGuidedMilestone(tier) {
    document.querySelectorAll('.rail-milestone-item').forEach(el => {
        if (el.getAttribute('data-tier') === String(tier)) {
            el.classList.add('active');
        } else {
            el.classList.remove('active');
        }
    });

    document.querySelectorAll('.milestone-pane').forEach(p => {
        if (p.getAttribute('data-tier') === String(tier)) {
            p.style.display = 'block';
        } else {
            p.style.display = 'none';
        }
    });

    const lazyContainer = document.getElementById('milestone-body-container-' + tier);
    if (lazyContainer && lazyContainer.children.length === 0 && window.BACKTRACE_JOB_ID) {
        lazyContainer.innerHTML = '<div style="padding: 1.5rem; text-align: center; font-family: monospace; color: var(--text-muted);">Loading milestone workspace...</div>';
        fetch('/reports/' + window.BACKTRACE_JOB_ID + '/milestones/' + tier)
            .then(r => r.text())
            .then(frag => {
                lazyContainer.innerHTML = frag;
                if (typeof initCodeEditors === 'function') initCodeEditors();
                if (typeof initMilestoneModes === 'function') initMilestoneModes();
                document.querySelectorAll('#milestone-body-container-' + tier + ' code').forEach(el => {
                    try { if (typeof hljs !== 'undefined') hljs.highlightElement(el); } catch(e){}
                });
            })
            .catch(err => {
                lazyContainer.innerHTML = '<div style="color: var(--crimson); padding: 1rem;">Failed to load milestone workspace: ' + err.message + '</div>';
            });
    }

    setTimeout(() => {
        if (window.cmEditors && window.cmEditors[tier]) {
            window.cmEditors[tier].refresh();
        }
        if (window.cmFillEditors && window.cmFillEditors[tier]) {
            window.cmFillEditors[tier].refresh();
        }
    }, 20);

    document.querySelectorAll('#milestone-pane-' + tier + ' code').forEach(el => {
        try { if (typeof hljs !== 'undefined') hljs.highlightElement(el); } catch(e){}
    });
}

function startHereMilestone(tier) {
    selectGuidedMilestone(tier);
    const editorCard = document.getElementById('milestone-editor-card-' + tier);
    if (editorCard) {
        editorCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function goToNextMilestone(currentTier) {
    const panes = Array.from(document.querySelectorAll('.milestone-pane'));
    const tiers = panes.map(p => parseInt(p.getAttribute('data-tier'), 10));
    const currentIdx = tiers.indexOf(parseInt(currentTier, 10));
    if (currentIdx >= 0 && currentIdx < tiers.length - 1) {
        const nextTier = tiers[currentIdx + 1];
        selectGuidedMilestone(nextTier);
        const nextPane = document.getElementById('milestone-pane-' + nextTier);
        if (nextPane) {
            nextPane.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
}

async function checkMilestoneUnderstanding(jobId, tier) {
    const card = document.getElementById('milestone-quiz-card-' + tier);
    if (!card) return;
    const questions = card.querySelectorAll('.milestone-quiz-q');
    let correctCount = 0;
    const total = questions.length || 3;

    questions.forEach((qEl, idx) => {
        const correctIdx = parseInt(qEl.getAttribute('data-correct-idx') || '0', 10);
        const qNum = idx + 1;
        const radios = document.getElementsByName('m_quiz_' + tier + '_' + qNum);
        let selectedVal = null;
        for (const r of radios) {
            if (r.checked) {
                selectedVal = parseInt(r.value, 10);
                break;
            }
        }
        const feedbackEl = qEl.querySelector('.quiz-feedback');
        const explanationEl = qEl.querySelector('.quiz-explanation');

        if (selectedVal !== null && selectedVal === correctIdx) {
            correctCount++;
            if (feedbackEl) {
                feedbackEl.style.display = 'inline-block';
                feedbackEl.style.color = 'var(--success)';
                feedbackEl.textContent = '✓ Correct';
            }
        } else {
            if (feedbackEl) {
                feedbackEl.style.display = 'inline-block';
                feedbackEl.style.color = 'var(--crimson)';
                feedbackEl.textContent = selectedVal === null ? 'Please answer' : '✗ Incorrect';
            }
        }
        if (explanationEl) {
            explanationEl.style.display = 'block';
        }
    });

    const scoreBanner = document.getElementById('quiz-score-banner-' + tier);
    const scoreText = document.getElementById('quiz-score-text-' + tier);
    if (scoreBanner && scoreText) {
        scoreBanner.style.display = 'inline-flex';
        scoreText.textContent = correctCount + ' of ' + total + ' correct';
        if (correctCount >= 2) {
            scoreBanner.style.background = 'rgba(45, 212, 191, 0.15)';
            scoreBanner.style.border = '1px solid var(--success)';
            scoreBanner.style.color = 'var(--success)';
        } else {
            scoreBanner.style.background = 'rgba(239, 68, 68, 0.15)';
            scoreBanner.style.border = '1px solid var(--crimson)';
            scoreBanner.style.color = 'var(--crimson)';
        }
    }

    const retryBtn = document.getElementById('btn-retry-quiz-' + tier);
    if (retryBtn) retryBtn.style.display = 'inline-flex';

    try {
        localStorage.setItem('quiz_score_' + jobId + '_' + tier, JSON.stringify({ score: correctCount, total: total }));
        await fetch('/api/attempts/' + jobId + '/' + tier + '/quiz', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ score: correctCount, total: total })
        });
    } catch(e) {
        console.warn('Quiz score persistence failed', e);
    }
}

function retryMilestoneQuiz(jobId, tier) {
    const card = document.getElementById('milestone-quiz-card-' + tier);
    if (!card) return;
    const questions = card.querySelectorAll('.milestone-quiz-q');
    questions.forEach((qEl, idx) => {
        const qNum = idx + 1;
        const radios = document.getElementsByName('m_quiz_' + tier + '_' + qNum);
        for (const r of radios) {
            r.checked = false;
        }
        const feedbackEl = qEl.querySelector('.quiz-feedback');
        const explanationEl = qEl.querySelector('.quiz-explanation');
        if (feedbackEl) feedbackEl.style.display = 'none';
        if (explanationEl) explanationEl.style.display = 'none';
    });

    const scoreBanner = document.getElementById('quiz-score-banner-' + tier);
    if (scoreBanner) scoreBanner.style.display = 'none';

    const retryBtn = document.getElementById('btn-retry-quiz-' + tier);
    if (retryBtn) retryBtn.style.display = 'none';
}

function toggleMilestoneBody(jobId, tier) {
    var container = document.getElementById('milestone-body-container-' + tier);
    var btn = document.getElementById('milestone-toggle-btn-' + tier);
    if (!container) return;
    if (container.style.display === 'none' || !container.style.display) {
        if (!window.loadedMilestoneBodies[tier] && (!container.innerHTML || !container.innerHTML.trim())) {
            if (btn) btn.textContent = 'Loading...';
            fetch('/reports/' + jobId + '/milestones/' + tier)
                .then(function(r) {
                    if (!r.ok) {
                        return fetch('/report/' + jobId + '/milestones/' + tier).then(function(r2) {
                            if (!r2.ok) throw new Error('HTTP ' + r2.status);
                            return r2.text();
                        });
                    }
                    return r.text();
                })
                .then(function(html) {
                    container.innerHTML = html;
                    window.loadedMilestoneBodies[tier] = true;
                    container.style.display = 'block';
                    if (btn) btn.textContent = 'Close Milestone Workspace ▴';
                    if (typeof initCodeEditors === 'function') initCodeEditors();
                    if (typeof initMilestoneModes === 'function') initMilestoneModes();
                })
                .catch(function(err) {
                    if (btn) btn.textContent = 'Retry Open ▾';
                    container.innerHTML = '<div style="color: var(--crimson); padding: 0.75rem; font-size: 0.8125rem;">Error loading milestone: ' + err.message + '</div>';
                    container.style.display = 'block';
                });
        } else {
            container.style.display = 'block';
            if (btn) btn.textContent = 'Close Milestone Workspace ▴';
        }
    } else {
        container.style.display = 'none';
        if (btn) btn.textContent = 'Open Milestone Workspace ▾';
    }
}
"""


def render_milestone_body_fragment(
    job: Any,
    milestone: Dict[str, Any],
    m_idx: int = 1,
    graph_data: Optional[Dict[str, Any]] = None,
    attempts_by_tier: Optional[Dict[int, Any]] = None,
    file_contents: Optional[Dict[str, str]] = None,
    redacted_files: Optional[Set[str]] = None,
    is_showcase: bool = False,
    sandbox_enabled: bool = True,
) -> str:
    """Renders HTML fragment for a single milestone's body and interactive workspace.
    Used for lazy-loading milestone content on demand or preloaded server rendering.
    """
    m = milestone
    try:
        m_tier = int(m.get("tier", m_idx))
    except (ValueError, TypeError):
        m_tier = m_idx

    track_label = m.get("track_label") or ("Test files" if "test" in str(m.get("track", "")).lower() else "Milestone")
    raw_disp_id = m.get("display_id")
    if raw_disp_id:
        display_id = str(raw_disp_id)
    elif track_label == "Test files":
        display_id = f"T{m_tier if m_tier > 0 else m_idx}"
    else:
        display_id = str(m_tier if m_tier > 0 else m_idx)

    m_title_raw = m.get("title", "")
    m_title = sanitize_text(m_title_raw)
    m_role_raw = m.get("architectural_role", "")
    m_summary_raw = m.get("overview", "")
    m_summary = render_user_markdown(m_summary_raw) if m_summary_raw else ""

    if m.get("brief_objective"):
        m_brief_obj = m.get("brief_objective")
    elif m_summary and not any(kw in m_summary.lower() for kw in ("**role:**", "role:")):
        m_brief_obj = m_summary
    elif m_summary:
        m_brief_obj = f"Implement {m_title} component contracts and satisfy export interfaces."
    else:
        m_brief_obj = ""

    m_comp = sanitize_text(m.get("domain_composition", ""))
    m_files = m.get("included_files", [])
    m_exports = m.get("exported_symbols", [])
    m_citations = m.get("citations", [])
    m_pedagogical = m.get("pedagogical_notes", [])
    m_gotchas = m.get("gotchas", [])

    attempt = attempts_by_tier.get(m_tier) if attempts_by_tier else None
    attempt_status = attempt.status if attempt else "not_started"
    submitted_code = attempt.submitted_code if attempt and attempt.submitted_code else ""
    hint_level = attempt.hint_level_revealed if attempt else 0
    impl_revealed = attempt.implementation_revealed if attempt else False
    is_active_attempt = (attempt is not None and attempt.status in ("attempting", "structurally_verified"))

    h1_text = ""
    if hint_level >= 1:
        try:
            h1_text = HintEngine.get_hint_1(graph_data or {}, m_tier)
        except Exception:
            h1_text = "Conceptual hint available."

    h2_text = ""
    if hint_level >= 2:
        try:
            exp_syms = StructuralVerifier.extract_expected_symbols_from_graph(graph_data or {}, m_tier)
            ver_res = StructuralVerifier().verify(attempt.submitted_code if attempt else "", exp_syms)
            h2_text = HintEngine.get_hint_2(graph_data or {}, m_tier, missing_symbols=ver_res.get("missing", []))
        except Exception:
            h2_text = "Specific missing contracts and files available."

    ref_code_rendered = ""
    ref_style = "display: none;"
    if impl_revealed:
        from app.services.file_content_service import FileContentService, SOURCE_NOT_AVAILABLE_MESSAGE
        ref_pieces = []
        if m_files:
            for f_path in m_files:
                c = FileContentService.find_matching_file_content(file_contents or {}, f_path)
                if not c and graph_data and "nodes" in graph_data:
                    for n in graph_data.get("nodes", []):
                        n_path = n.get("path") or n.get("id") or ""
                        if n_path == f_path or n_path.endswith(f_path) or f_path.endswith(n_path):
                            if n.get("source_code") or n.get("content"):
                                c = n.get("source_code") or n.get("content")
                                break
                if c:
                    ref_pieces.append((f_path, c))
        if ref_pieces:
            if len(ref_pieces) == 1:
                ref_code_rendered = html.escape(ref_pieces[0][1])
            else:
                ref_code_rendered = html.escape(
                    "\n\n".join(f"# File: {p}\n{c}" for p, c in ref_pieces)
                )
        else:
            ref_code_rendered = html.escape(SOURCE_NOT_AVAILABLE_MESSAGE)
        ref_style = "display: block;"

    btn_submit_disabled = ""
    btn_run_disabled = ""
    btn_run_fill_disabled = ""
    btn_submit_fill_disabled = ""
    btn_submit_label = "Check answer"
    btn_submit_fill_label = "Check answer"
    run_note_html = ""
    submit_note_html = ""
    submit_fill_note_html = ""

    grading_method, _ = GradingEngine().determine_grading_tier(job, m_tier, graph_data or {})
    requires_execution = grading_method in ("real_tests", "expected_output")

    if not sandbox_enabled:
        btn_run_disabled = 'disabled title="Code execution is turned off on this demo" style="display: none;"'
        btn_run_fill_disabled = 'disabled title="Code execution is turned off on this demo" style="display: none;"'
        run_note_html = ""
        submit_fill_note_html = '<div class="demo-submit-note" style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.25rem;">No points are awarded on this demo.</div>'

        if requires_execution:
            btn_submit_disabled = 'disabled title="Grading this milestone needs code execution, which is off on this demo" style="cursor: not-allowed; opacity: 0.5;"'
            submit_note_html = '<div class="demo-submit-note" style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.25rem;">Grading this milestone needs code execution, which is off on this demo.</div>'
        else:
            btn_submit_label = "Check structure"
            submit_note_html = '<div class="demo-submit-note" style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.25rem;">Structure check only. No points are awarded on this demo.</div>'

    # Diff and console output
    diff_initial_display = "display: block;" if (attempt and attempt.submitted_code) else "display: none;"
    diff_rendered_html = ""
    if attempt and attempt.submitted_code:
        try:
            exp_syms = StructuralVerifier.extract_expected_symbols_from_graph(graph_data or {}, m_tier)
            ver_res = StructuralVerifier().verify(attempt.submitted_code, exp_syms)
            diff_rendered_html = _render_server_diff_html(
                ver_res,
                is_verified=(attempt_status == "structurally_verified"),
                err_msg=ver_res.get("error_message"),
                grading_method=attempt.grading_method if attempt else None,
            )
        except Exception as e:
            diff_rendered_html = f'<div style="color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;">Verification load error: {html.escape(str(e))}</div>'

    console_initial_display = "display: block;" if (attempt and attempt.last_run_at is not None) else "display: none;"
    console_rendered_html = _render_server_console_html(attempt)

    # Key symbols
    symbols_html = ""
    if m_exports:
        symbols_rendered = ", ".join(m_exports[:10])
        symbols_html = f"""
        <div style="margin-top: 0.65rem; font-size: 0.8125rem; font-family: var(--font-ui); color: var(--text-muted);">
            <span style="color: var(--text-muted); font-weight: 600;">Key symbols:</span> {sanitize_text(symbols_rendered)}
        </div>
        """

    expected_pills_html = ""
    if m_exports:
        for exp_sym in m_exports:
            safe_sym = sanitize_text(exp_sym)
            expected_pills_html += f"""<span class="expected-sym-chip" style="display: inline-flex; align-items: center; gap: 0.25rem; background: var(--panel-raised); border: 1px solid var(--border); padding: 0.15rem 0.45rem; border-radius: 3px; font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted);">&bull; {safe_sym}</span> """
    else:
        expected_pills_html = '<span style="font-size: 0.8125rem; color: var(--text-muted); font-family: var(--font-mono);">Any milestone module functions/classes</span>'

    # Citations accordion
    citations_html = ""
    if m_citations:
        c_items = "".join(f'<div style="margin-bottom: 0.35rem; color: var(--text-muted);">&bull; {sanitize_text(c)}</div>' for c in m_citations)
        citations_html = f"""
        <details style="margin-top: 0.65rem;">
            <summary style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); cursor: pointer; user-select: none;">
                <span>&gt; Semantic Citations ({len(m_citations)})</span>
            </summary>
            <div style="margin-top: 0.4rem; padding: 0.65rem 0.85rem; background: var(--panel-raised); border-left: 2px solid var(--success); border-radius: 2px; font-family: var(--font-ui); font-size: 0.8125rem; line-height: 1.45;">
                {c_items}
            </div>
        </details>
        """

    # Pedagogical / Gotchas
    notes_html = ""
    if m_pedagogical or m_gotchas:
        p_items = "".join(f'<div style="margin-bottom: 0.25rem;">&bull; {render_user_markdown(p)}</div>' for p in m_pedagogical)
        g_items = "".join(f'<div style="margin-bottom: 0.25rem; color: var(--amber);">&bull; {render_user_markdown(g)}</div>' for g in m_gotchas)
        notes_html = f"""
        <div style="margin-top: 0.65rem; padding: 0.65rem 0.85rem; background: var(--panel-raised); border: 1px solid var(--hairline-soft); border-radius: 3px; font-size: 0.8125rem; color: var(--text-muted); line-height: 1.45;">
            {f'<div style="margin-bottom: 0.35rem;"><span style="font-weight: 600; color: var(--text);">Key Architectural Concept:</span> {p_items}</div>' if p_items else ''}
            {f'<div><span style="font-weight: 600; color: var(--amber);">Implementation Gotcha:</span> {g_items}</div>' if g_items else ''}
        </div>
        """

    # Read files data
    read_files_data = []
    from app.services.file_content_service import FileContentService, SOURCE_NOT_AVAILABLE_MESSAGE
    if m_files:
        for idx, f_path in enumerate(m_files):
            f_content = ""
            has_real_source = False
            if file_contents:
                matched = FileContentService.find_matching_file_content(file_contents, f_path)
                if matched:
                    f_content = matched
                    has_real_source = True

            if not f_content and graph_data and "nodes" in graph_data:
                for n in graph_data.get("nodes", []):
                    n_path = n.get("path") or n.get("id") or ""
                    if n_path == f_path or n_path.endswith(f_path) or f_path.endswith(n_path):
                        if n.get("source_code"):
                            f_content = n.get("source_code")
                            has_real_source = True
                            break
                        elif n.get("content"):
                            f_content = n.get("content")
                            has_real_source = True
                            break

            if not f_content:
                f_content = SOURCE_NOT_AVAILABLE_MESSAGE
                has_real_source = False

            read_files_data.append({
                "path": f_path,
                "filename": f_path.replace("\\", "/").split("/")[-1],
                "content": f_content,
                "has_real_source": has_real_source,
            })
    else:
        read_files_data.append({
            "path": f"milestone_{m_tier}_implementation.py",
            "filename": f"milestone_{m_tier}_implementation.py",
            "content": SOURCE_NOT_AVAILABLE_MESSAGE,
            "has_real_source": False,
        })

    read_file_tabs_html = ""
    read_file_panes_html = ""
    for f_idx, r_file in enumerate(read_files_data):
        active_cls = "active" if f_idx == 0 else ""
        pane_display = "block" if f_idx == 0 else "none"
        escaped_f_content = html.escape(r_file["content"])
        f_name_safe = sanitize_text(r_file["filename"])
        f_path_safe = sanitize_text(r_file["path"])

        if len(read_files_data) > 1:
            tab_bg = "var(--surface-2)" if f_idx == 0 else "transparent"
            tab_color = "var(--success)" if f_idx == 0 else "var(--text-muted)"
            tab_border = "var(--teal-border)" if f_idx == 0 else "var(--border)"
            read_file_tabs_html += f"""
            <button type="button" id="read-tab-btn-{m_tier}-{f_idx}" class="read-file-tab-btn {active_cls}" onclick="switchMilestoneReadFile({m_tier}, {f_idx})" title="{f_path_safe}" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.25rem 0.6rem; font-family: var(--font-mono); font-size: 0.8125rem; border-radius: 3px; border: 1px solid {tab_border}; background: {tab_bg}; color: {tab_color}; cursor: pointer; transition: all 120ms ease;">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                    <polyline points="13 2 13 9 20 9"></polyline>
                </svg>
                {f_name_safe}
            </button>
            """

        norm_path = r_file["path"].replace("\\", "/").strip("/")
        is_redacted = bool(redacted_files and (r_file["path"] in redacted_files or norm_path in redacted_files))
        redaction_notice_html = ""
        if is_redacted:
            redaction_notice_html = """
            <div class="redaction-notice-bar" style="display: flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.85rem; background: rgba(245, 158, 11, 0.08); border: 1px solid var(--amber-border); border-bottom: none; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--amber);">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                </svg>
                <span>Some values were hidden for security</span>
            </div>
            """

        source_tag_label = "READ-ONLY SOURCE" if r_file.get("has_real_source", True) else "source files expired"
        lines = r_file["content"].splitlines()
        line_count = len(lines) if lines else 1
        line_numbers_html = "<br>".join(str(i) for i in range(1, line_count + 1))
        read_file_panes_html += f"""
        <div id="read-file-pane-{m_tier}-{f_idx}" class="read-file-pane" style="display: {pane_display};">
            <div style="display: flex; justify-content: space-between; align-items: center; background: #12141a; padding: 0.4rem 0.85rem; border: 1px solid var(--border); border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">
                <div style="display: flex; align-items: center; gap: 0.4rem;">
                    <span class="chip-dot teal"></span>
                    <span style="color: var(--text-muted); font-weight: 500;">{f_path_safe}</span>
                </div>
                <span class="tag" style="font-size: 0.8125rem;">{source_tag_label}</span>
            </div>
            {redaction_notice_html}
            <div class="code-pane-container" style="height: 60vh; max-height: 60vh; overflow: auto; background: #181a20; border: 1px solid var(--border); border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; display: flex;">
                <div class="line-numbers" style="padding: 1rem 0.65rem; background: #12141a; border-right: 1px solid var(--border); color: var(--text-muted); font-family: var(--font-mono); font-size: 0.8125rem; line-height: 1.5; text-align: right; user-select: none; flex-shrink: 0; min-width: 44px;">
                    {line_numbers_html}
                </div>
                <pre class="read-code-pre" style="margin: 0; padding: 1rem; flex: 1; overflow: visible; background: transparent; border: none;"><code id="read-code-content-{m_tier}-{f_idx}" class="language-python hljs" style="background: transparent !important; padding: 0; font-family: var(--font-mono); font-size: 0.8125rem; line-height: 1.5; display: block;">{escaped_f_content}</code></pre>
            </div>
        </div>
        """

    # Scaffold data for fill mode
    fill_files_data = []
    has_any_scaffold = False
    for f_idx, r_file in enumerate(read_files_data):
        if not r_file.get("has_real_source", True):
            fill_files_data.append({
                "path": r_file["path"],
                "filename": r_file["filename"],
                "try_it_stub": "",
                "scaffold_code": r_file["content"],
                "has_scaffold": False,
                "blanked_functions": [],
                "blanked_count": 0,
                "reason": "The original source for this file isn't available for this job.",
            })
            continue

        norm_path = r_file["path"].replace("\\", "/").strip("/")
        f_is_redacted = bool(redacted_files and (r_file["path"] in redacted_files or norm_path in redacted_files))

        s_res = ScaffoldGenerator.generate_scaffold(
            code=r_file["content"],
            language="python",
            file_path=r_file["path"],
            is_redacted=f_is_redacted,
        )
        try_it_stub = ScaffoldGenerator.generate_try_it_stub(
            code=r_file["content"],
            language="python",
            file_path=r_file["path"],
        )
        if s_res.get("has_scaffold", False):
            has_any_scaffold = True
        fill_files_data.append({
            "path": r_file["path"],
            "filename": r_file["filename"],
            "try_it_stub": try_it_stub,
            "scaffold_code": s_res.get("scaffold_code", r_file["content"]),
            "has_scaffold": s_res.get("has_scaffold", False),
            "blanked_functions": s_res.get("blanked_functions", []),
            "blanked_count": s_res.get("blanked_count", 0),
            "reason": s_res.get("reason"),
        })

    has_any_real_source = any(r.get("has_real_source", False) for r in read_files_data)
    guess_disabled_banner_html = ""
    if not has_any_real_source:
        guess_disabled_banner_html = """
        <div class="guess-disabled-banner" style="margin-bottom: 0.85rem; padding: 0.75rem 1rem; background: rgba(245, 158, 11, 0.08); border-left: 3px solid var(--amber); border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem; line-height: 1.45; color: var(--amber);">
            <span>⚠️</span> <strong>Try it Disabled:</strong> Reference source files are not available for this milestone. Try re-running the analysis to view and verify against the real implementation.
        </div>
        """
        btn_submit_disabled = 'disabled title="Reference source unavailable" style="cursor: not-allowed; opacity: 0.45;"'

    starter_code = ""
    if fill_files_data and fill_files_data[0].get("has_real_source", True):
        starter_code = fill_files_data[0].get("try_it_stub", "")
    active_editor_code = submitted_code if submitted_code else starter_code
    escaped_code = html.escape(active_editor_code)

    starter_notice_display = "display: flex;" if (fill_files_data and not fill_files_data[0].get("has_scaffold", False) and not submitted_code) else "display: none;"
    starter_unavailable_notice_html = f"""
    <div id="starter-unavailable-notice-{m_tier}" class="starter-unavailable-notice" style="{starter_notice_display}align-items: center; gap: 0.4rem; margin-bottom: 0.65rem; padding: 0.6rem 0.85rem; background: rgba(245, 158, 11, 0.08); border-left: 3px solid var(--amber); border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">
        <span>ℹ️</span> <strong>Starter code isn't available for this file.</strong>
    </div>
    """

    first_target_file = sanitize_text(m_files[0]) if m_files else f"milestone_{m_tier}.py"
    role_context = render_user_markdown(m_role_raw) if m_role_raw else (render_user_markdown(m_title_raw) if m_title_raw else f"Milestone {m_tier}")

    guess_file_tabs_html = ""
    for f_idx, g_file in enumerate(m_files):
        active_cls = "active" if f_idx == 0 else ""
        f_path_safe = sanitize_text(g_file)
        f_name_safe = sanitize_text(g_file.replace("\\", "/").split("/")[-1])
        tab_bg = "var(--surface-2)" if f_idx == 0 else "transparent"
        tab_color = "var(--accent)" if f_idx == 0 else "var(--text-muted)"
        tab_border = "var(--brass-border)" if f_idx == 0 else "var(--border)"
        guess_file_tabs_html += f"""
        <button type="button" id="guess-tab-btn-{m_tier}-{f_idx}" class="guess-file-tab-btn {active_cls}" onclick="switchMilestoneGuessFile({m_tier}, {f_idx}, '{f_path_safe}')" title="{f_path_safe}" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.25rem 0.6rem; font-family: var(--font-mono); font-size: 0.8125rem; border-radius: 3px; border: 1px solid {tab_border}; background: {tab_bg}; color: {tab_color}; cursor: pointer; transition: all 120ms ease;">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                <polyline points="13 2 13 9 20 9"></polyline>
            </svg>
            {f_name_safe}
        </button>
        """

    guess_file_picker_container_html = ""
    if len(m_files) > 1:
        guess_file_picker_container_html = f"""
        <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap;">
            <span style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">Target File:</span>
            <div id="guess-file-tabs-{m_tier}" style="display: flex; gap: 0.35rem; flex-wrap: wrap;">
                {guess_file_tabs_html}
            </div>
        </div>
        """

    example_io_data = m.get("example_io") or m.get("test_cases") or m.get("examples")
    example_io_html = ""
    if example_io_data:
        if isinstance(example_io_data, list):
            ex_rendered = "".join(f'<div style="font-family: var(--font-mono); font-size: 0.8125rem; background: var(--surface-2); padding: 0.4rem 0.6rem; border-radius: 3px; border: 1px solid var(--hairline-soft); margin-top: 0.25rem;">{sanitize_text(str(ex))}</div>' for ex in example_io_data)
        elif isinstance(example_io_data, dict):
            ex_rendered = f'<pre style="font-family: var(--font-mono); font-size: 0.8125rem; background: var(--surface-2); padding: 0.4rem 0.6rem; border-radius: 3px; border: 1px solid var(--hairline-soft); margin-top: 0.25rem; overflow-x: auto;">{sanitize_text(json.dumps(example_io_data, indent=2))}</pre>'
        else:
            ex_rendered = f'<div style="font-family: var(--font-mono); font-size: 0.8125rem; background: var(--surface-2); padding: 0.4rem 0.6rem; border-radius: 3px; border: 1px solid var(--hairline-soft); margin-top: 0.25rem;">{sanitize_text(str(example_io_data))}</div>'
        example_io_html = f"""
        <div class="brief-example-io-section" style="margin-bottom: 0.65rem;">
            <div style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.2rem;">
                Example Input / Output:
            </div>
            <div style="margin-top: 0.25rem;">
                {ex_rendered}
            </div>
        </div>
        """

    first_fill_file = fill_files_data[0]
    escaped_scaffold_code = html.escape(first_fill_file["scaffold_code"])
    fill_file_tabs_html = ""
    for f_idx, f_file in enumerate(fill_files_data):
        active_cls = "active" if f_idx == 0 else ""
        f_path_safe = sanitize_text(f_file["path"])
        f_name_safe = sanitize_text(f_file["filename"])
        tab_bg = "var(--surface-2)" if f_idx == 0 else "transparent"
        tab_color = "var(--success)" if f_idx == 0 else "var(--text-muted)"
        tab_border = "var(--teal-border)" if f_idx == 0 else "var(--border)"
        no_blanks_tag = "" if f_file["has_scaffold"] else ' <span class="tag" style="font-size: 0.8125rem; padding: 0 0.2rem;">No blanks</span>'
        fill_file_tabs_html += f"""
        <button type="button" id="fill-tab-btn-{m_tier}-{f_idx}" class="fill-file-tab-btn {active_cls}" onclick="switchMilestoneFillFile({m_tier}, {f_idx}, '{f_path_safe}')" title="{f_path_safe}" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.25rem 0.6rem; font-family: var(--font-mono); font-size: 0.8125rem; border-radius: 3px; border: 1px solid {tab_border}; background: {tab_bg}; color: {tab_color}; cursor: pointer; transition: all 120ms ease;">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                <polyline points="13 2 13 9 20 9"></polyline>
            </svg>
            {f_name_safe}{no_blanks_tag}
        </button>
        """

    fill_file_picker_container_html = ""
    if len(fill_files_data) > 1:
        fill_file_picker_container_html = f"""
        <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap;">
            <span style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">Target File:</span>
            <div id="fill-file-tabs-{m_tier}" style="display: flex; gap: 0.35rem; flex-wrap: wrap;">
                {fill_file_tabs_html}
            </div>
        </div>
        """

    initial_blanked = first_fill_file["blanked_functions"]
    fill_chips_html = _render_grouped_fill_chips(initial_blanked, first_fill_file.get("reason"))

    if has_any_scaffold:
        fill_mode_btn_html = f"""
        <button type="button" id="mode-btn-fill-{m_tier}" class="milestone-mode-tab-btn" onclick="switchMilestoneMode({m_tier}, 'fill')" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.75rem; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 500; border-radius: 3px; border: none; cursor: pointer; transition: all 120ms ease; background: transparent; color: var(--text-muted);">
            <span>🧩</span> Fill the gaps
        </button>
        """
    else:
        disable_note = html.escape(first_fill_file.get("reason") or "File contains only constants, type declarations, or exports with no function bodies to scaffold.")
        fill_mode_btn_html = f"""
        <button type="button" id="mode-btn-fill-{m_tier}" class="milestone-mode-tab-btn disabled" disabled title="{disable_note}" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.75rem; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 500; border-radius: 3px; border: none; cursor: not-allowed; opacity: 0.45; background: transparent; color: var(--text-muted);">
            <span>🧩</span> Fill the gaps <span class="tag" style="font-size: 0.8125rem; padding: 0.05rem 0.3rem;">No Blanks</span>
        </button>
        """

    read_file_picker_container_html = ""
    if len(read_files_data) > 1:
        read_file_picker_container_html = f"""
        <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.65rem; flex-wrap: wrap;">
            <span style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">Target File:</span>
            <div id="read-file-tabs-{m_tier}" style="display: flex; gap: 0.35rem; flex-wrap: wrap;">
                {read_file_tabs_html}
            </div>
        </div>
        """

    reviewed_btn_text = "Reviewed &amp; Verified ✓" if attempt_status == "structurally_verified" else "Mark as Reviewed"
    try:
        job_id = int(job.id if hasattr(job, "id") else (job.get("id", 0) if isinstance(job, dict) else 0))
    except (ValueError, TypeError, AttributeError):
        job_id = 0

    if is_showcase:
        workspace_html = f"""
        <div class="milestone-editor-wrapper" id="milestone-editor-card-{m_tier}" style="margin-top: 1.25rem; border-top: 1px solid var(--hairline-soft); padding-top: 1.15rem;">
            <div id="workspace-read-{m_tier}" class="milestone-mode-workspace read-mode" style="display: block;">
                <div style="font-family: 'IBM Plex Sans', sans-serif; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.4rem;">
                    <span style="color: var(--success); font-weight: 600;">ℹ</span> Architecture Implementation
                </div>
                {read_file_picker_container_html}
                <div class="read-file-panes-container" style="border-radius: 4px; overflow: hidden;">
                    {read_file_panes_html}
                </div>
            </div>
        </div>
        """
    else:
        reveal_btn_text = "Solution Shown" if impl_revealed else "Show solution"
        reveal_btn_display = "display: inline-flex;" if is_active_attempt else "display: none;"
        hints_unlocked_fill_note = "Hints unlocked &bull; Only blanked functions evaluated" if hint_level > 0 else "Only blanked functions evaluated"

        workspace_html = f"""
        <div class="milestone-editor-wrapper" id="milestone-editor-card-{m_tier}" style="margin-top: 1.25rem; border-top: 1px solid var(--hairline-soft); padding-top: 1.15rem;">
            <div class="milestone-mode-switcher" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; border-bottom: 1px solid var(--hairline-soft); padding-bottom: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                <div style="display: flex; align-items: center; gap: 0.35rem; background: var(--panel-raised); border: 1px solid var(--border); border-radius: 4px; padding: 0.2rem;">
                    <button type="button" id="mode-btn-read-{m_tier}" class="milestone-mode-tab-btn" onclick="switchMilestoneMode({m_tier}, 'read')" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.75rem; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 500; border-radius: 3px; border: none; cursor: pointer; transition: all 120ms ease; background: transparent; color: var(--text-muted);">
                        <span>📖</span> Read it
                    </button>
                    {fill_mode_btn_html}
                    <button type="button" id="mode-btn-guess-{m_tier}" class="milestone-mode-tab-btn active" onclick="switchMilestoneMode({m_tier}, 'guess')" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.75rem; font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; border-radius: 3px; border: none; cursor: pointer; transition: all 120ms ease; background: var(--surface-2); color: var(--accent); box-shadow: 0 1px 3px rgba(0,0,0,0.2);">
                        <span>✏️</span> Try it
                    </button>
                </div>
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">
                    Practice mode
                </div>
            </div>

            <!-- Mode 1: Guess It -->
            <div id="workspace-guess-{m_tier}" class="milestone-mode-workspace guess-mode">
                {guess_disabled_banner_html}
                <div class="guess-instruction-banner" style="margin-bottom: 0.85rem; padding: 0.75rem 1rem; background: var(--panel-raised); border-left: 3px solid var(--accent); border-radius: 3px; font-family: 'IBM Plex Sans', sans-serif; font-size: 0.825rem; line-height: 1.5; color: var(--text-muted);">
                    <div style="font-weight: 600; color: var(--text); margin-bottom: 0.2rem; display: flex; align-items: center; gap: 0.35rem;">
                        <span>🎯</span> <strong>Task Instructions:</strong>
                    </div>
                    <div>
                        Try to reconstruct <span class="mono" id="guess-target-filename-{m_tier}" style="color: var(--accent); font-weight: 600; font-size: 0.8125rem; background: var(--surface-2); padding: 0.1rem 0.4rem; border-radius: 3px; border: 1px solid var(--border);">{first_target_file}</span> based on the expected symbols and this milestone's role in the codebase ({role_context}), before seeing the real implementation.
                    </div>
                </div>

                {guess_file_picker_container_html}

                <div class="milestone-brief-card" style="margin-bottom: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border: 1px solid var(--border); border-radius: 4px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem; border-bottom: 1px solid var(--hairline-soft); padding-bottom: 0.45rem;">
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--accent); display: flex; align-items: center; gap: 0.4rem;">
                            <span>📋</span> {track_label} {display_id} Structured Brief
                        </div>
                        <span class="tag" style="font-size: 0.8125rem;">Sourced from Codebase</span>
                    </div>

                    <div class="brief-objective-section" style="margin-bottom: 0.65rem;">
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.2rem;">
                            Objective:
                        </div>
                        {f'<div style="font-size: 0.825rem; color: var(--text-muted); line-height: 1.5;">{m_brief_obj}</div>' if m_brief_obj else '<div style="font-size: 0.8125rem; color: var(--text-muted); font-style: italic;">No objective text available for this milestone.</div>'}
                    </div>

                    <div class="brief-constraints-section" style="margin-bottom: 0.65rem;">
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.35rem;">
                            Constraints / Expected Functions &amp; Signatures:
                        </div>
                        <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">
                            {expected_pills_html}
                        </div>
                    </div>

                    {example_io_html}
                </div>

                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem; flex-wrap: wrap; gap: 0.5rem;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent);">
                            <polyline points="16 18 22 12 16 6"></polyline>
                            <polyline points="8 6 2 12 8 18"></polyline>
                        </svg>
                        <span style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text); ">
                            Milestone {m_tier} Implementation Workspace
                        </span>
                    </div>
                    <span class="tag" style="font-size: 0.8125rem;">Structure &amp; Execution Verified</span>
                </div>

                {starter_unavailable_notice_html}

                <div class="editor-surface-container" style="border: 1px solid var(--border); border-radius: 4px; overflow: hidden; background: #282a36;">
                    <textarea id="code-editor-{m_tier}" name="code_editor_{m_tier}" style="display: none;">{escaped_code}</textarea>
                </div>

                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-top: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                    <div style="display: flex; align-items: flex-start; gap: 0.5rem; flex-wrap: wrap;">
                        <button type="button" id="btn-run-{m_tier}" onclick="runMilestoneCode('{job_id}', {m_tier})" {btn_run_disabled} class="btn btn-sm btn-secondary" style="font-family: var(--font-ui); border-color: var(--brass-border); color: var(--accent);">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                                <polygon points="5 3 19 12 5 21 5 3"></polygon>
                            </svg>
                            Run Code
                        </button>
                        <div style="display: flex; flex-direction: column;">
                            <button type="button" id="btn-submit-{m_tier}" onclick="submitMilestoneAttempt('{job_id}', {m_tier})" {btn_submit_disabled} class="btn btn-sm btn-primary" style="font-family: var(--font-ui); ">
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                    <polyline points="20 6 9 17 4 12"></polyline>
                                </svg>
                                {btn_submit_label}
                            </button>
                            {submit_note_html}
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <button type="button" id="btn-reveal-{m_tier}" onclick="revealMilestoneImplementation('{job_id}', {m_tier})" class="btn btn-sm btn-secondary" style="{reveal_btn_display} font-family: var(--font-ui); color: var(--success); border-color: var(--teal-border);">
                            <span id="btn-reveal-text-{m_tier}">{reveal_btn_text}</span>
                        </button>
                    </div>
                </div>

                <div id="diff-output-container-{m_tier}" style="{diff_initial_display} margin-top: 1rem; border-top: 1px solid var(--border); padding-top: 0.75rem;">
                    {diff_rendered_html}
                </div>
                <div id="console-output-container-{m_tier}" style="{console_initial_display} margin-top: 1rem; border-top: 1px solid var(--border); padding-top: 0.75rem;">
                    {console_rendered_html}
                </div>
            </div>

            <!-- Mode 2: Read It -->
            <div id="workspace-read-{m_tier}" class="milestone-mode-workspace read-mode" style="display: none;">
                <div style="font-family: 'IBM Plex Sans', sans-serif; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.4rem;">
                    <span style="color: var(--success); font-weight: 600;">ℹ</span> Read through this milestone's actual implementation
                </div>
                {read_file_picker_container_html}
                <div class="read-file-panes-container" style="border-radius: 4px; overflow: hidden;">
                    {read_file_panes_html}
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.85rem; flex-wrap: wrap; gap: 0.5rem;">
                    <button type="button" id="btn-review-{m_tier}" onclick="markMilestoneAsReviewed('{job_id}', {m_tier})" class="btn btn-sm" style="font-family: var(--font-ui); display: inline-flex; align-items: center; gap: 0.4rem; background: var(--success); color: #0f172a; font-weight: 600; border: 1px solid var(--teal-border); border-radius: 4px; padding: 0.35rem 0.85rem; cursor: pointer;">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                        <span id="btn-review-text-{m_tier}">{reviewed_btn_text}</span>
                    </button>
                    <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">Read-only exploration &bull; No code grading required</span>
                </div>
            </div>

            <!-- Mode 3: Fill the Gaps -->
            <div id="workspace-fill-{m_tier}" class="milestone-mode-workspace fill-mode" style="display: none;">
                {fill_file_picker_container_html}
                <div id="fill-chips-container-{m_tier}" style="margin-bottom: 0.65rem;">
                    {fill_chips_html}
                </div>
                <div class="editor-surface-container" style="border: 1px solid var(--border); border-radius: 4px; overflow: hidden; background: #282a36;">
                    <textarea id="fill-code-editor-{m_tier}" name="fill_code_editor_{m_tier}" style="display: none;">{escaped_scaffold_code}</textarea>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-top: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                    <div style="display: flex; align-items: flex-start; gap: 0.5rem; flex-wrap: wrap;">
                        <button type="button" id="btn-submit-fill-{m_tier}" onclick="submitFillBlankAttempt('{job_id}', {m_tier})" {btn_submit_fill_disabled} class="btn btn-sm btn-primary" style="font-family: var(--font-ui); ">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                            {btn_submit_fill_label}
                        </button>
                    </div>
                </div>
                <div id="fill-diff-output-container-{m_tier}" style="display: none; margin-top: 1rem; border-top: 1px solid var(--border); padding-top: 0.75rem;"></div>
            </div>
        </div>
        """

    frag_quiz_items = _build_milestone_quiz_items(m, m_idx, None, [m])
    frag_quiz_html = _render_milestone_quiz_card(job_id, m_tier, frag_quiz_items)

    return f"""
    <div class="milestone-body-content" id="milestone-content-{m_tier}">
        {f'<div style="font-size: 0.8125rem; color: var(--text-muted); font-family: var(--font-ui); margin-bottom: 0.5rem;"><span style="color: var(--text-muted); font-weight: 600;">Composition:</span> {m_comp}</div>' if m_comp else ''}
        {symbols_html}
        {citations_html}
        {notes_html}
        {workspace_html}
        {frag_quiz_html}
    </div>
    """



def _build_milestone_quiz_items(
    m: Dict[str, Any],
    m_idx: int,
    quiz_data: Optional[Dict[str, Any]],
    all_milestones: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Builds exactly 3 understanding check questions for a milestone."""
    import random
    try:
        tier = int(m.get("tier", m_idx))
    except (ValueError, TypeError):
        tier = m_idx

    track_label = m.get("track_label") or ("Test files" if "test" in str(m.get("track", "")).lower() else "Milestone")
    raw_disp_id = m.get("display_id")
    if raw_disp_id:
        display_id = str(raw_disp_id)
    elif track_label == "Test files":
        display_id = f"T{tier if tier > 0 else m_idx}"
    else:
        display_id = str(tier if tier > 0 else m_idx)

    m_title = m.get("title", f"Milestone {display_id}")
    m_files = m.get("included_files", [])
    m_exports = m.get("exported_symbols", [])

    questions: List[Dict[str, Any]] = []

    # 1. Match from quiz_data if available
    if quiz_data and "questions" in quiz_data and isinstance(quiz_data["questions"], list):
        for q in quiz_data["questions"]:
            q_tier = q.get("tier")
            if q_tier is not None and (str(q_tier) == str(tier) or str(q_tier) == str(display_id)):
                opts = list(q.get("options", []))
                c_idx = q.get("correct_option_index", q.get("correct_index", 0))
                questions.append({
                    "question": q.get("question", ""),
                    "options": opts,
                    "correct_index": c_idx,
                    "explanation": q.get("explanation", f"{track_label} {display_id} architectural invariant."),
                })
                if len(questions) == 3:
                    break

    # 2. Add question 1 if missing: Responsibility
    if len(questions) < 1:
        correct_resp = m.get("brief_objective") or f"Provides core component logic and export contracts for {display_id}."
        distractors = [
            "Handles top-level HTTP and CLI request routing.",
            "Manages database migration schemas and session lifecycles.",
            "Executes end-to-end integration test suites.",
        ]
        opts = [correct_resp] + distractors
        rng = random.Random(f"{display_id}_q1")
        rng.shuffle(opts)
        questions.append({
            "question": f"What is the primary architectural responsibility of {track_label} {display_id}?",
            "options": opts,
            "correct_index": opts.index(correct_resp),
            "explanation": f"{track_label} {display_id} {correct_resp}",
        })

    # 3. Add question 2 if missing: Contract / Exports
    if len(questions) < 2:
        first_export = m_exports[0] if m_exports else "module contract"
        correct_exp = f"Defines and exports {first_export} for downstream consumers."
        opts2 = [
            correct_exp,
            "Exposes mock fixtures strictly isolated from production imports.",
            "Parses environment configuration flags directly from system arguments.",
            "Directly renders client HTML response templates.",
        ]
        rng = random.Random(f"{display_id}_q2")
        rng.shuffle(opts2)
        questions.append({
            "question": f"Which interface contract does {track_label} {display_id} guarantee?",
            "options": opts2,
            "correct_index": opts2.index(correct_exp),
            "explanation": f"{track_label} {display_id} guarantees {first_export} export contracts.",
        })

    # 4. Add question 3 if missing: Sequencing
    if len(questions) < 3:
        is_test = (track_label == "Test files")
        if is_test:
            correct_seq = "Validates behavior against already-constructed core dependencies."
            opts3 = [
                correct_seq,
                "Precedes all core modules because tests must be written first in memory.",
                "Executes before any database or model definitions are created.",
                "Initializes the global web server configuration.",
            ]
        else:
            correct_seq = "Satisfies foundational component contracts required by higher-tier orchestration."
            opts3 = [
                correct_seq,
                "Executes after all integration test suites have finalized.",
                "Serves as an optional debug plugin that can be loaded asynchronously.",
                "Handles terminal shutdown teardown hooks exclusively.",
            ]
        rng = random.Random(f"{display_id}_q3")
        rng.shuffle(opts3)
        questions.append({
            "question": f"Why is {track_label} {display_id} sequenced at this position in the walkthrough?",
            "options": opts3,
            "correct_index": opts3.index(correct_seq),
            "explanation": f"Sequencing logic: {correct_seq}",
        })

    return questions[:3]


def _render_milestone_quiz_card(job_id: Any, m_tier: int, questions: List[Dict[str, Any]], grading_details: Optional[Dict[str, Any]] = None) -> str:
    """Renders the 'Check your understanding' 3-question quiz step per milestone with large 44px rows."""
    score_val = grading_details.get("quiz_score") if grading_details else None
    total_val = grading_details.get("quiz_total", 3) if grading_details else 3
    if score_val is not None:
        score_text = f"{score_val} of {total_val} correct"
        banner_display = "inline-flex"
        retry_display = "inline-flex"
        passed = score_val >= (total_val * 0.6)
        banner_bg = "rgba(45, 212, 191, 0.15)" if passed else "rgba(244, 63, 94, 0.15)"
        banner_border = "1px solid var(--success)" if passed else "1px solid var(--crimson)"
        banner_color = "var(--success)" if passed else "var(--crimson)"
    else:
        score_text = "of 3 correct"
        banner_display = "none"
        retry_display = "none"
        banner_bg = "transparent"
        banner_border = "1px solid var(--border)"
        banner_color = "inherit"

    rendered_qs = ""
    for q_idx, q in enumerate(questions, 1):
        q_text = render_user_markdown(q.get("question", ""))
        correct_idx = q.get("correct_index", 0)
        q_exp = render_user_markdown(q.get("explanation", ""))
        opts = q.get("options", [])

        opts_html = ""
        for opt_idx, opt in enumerate(opts):
            opt_text = render_user_markdown(str(opt))
            opts_html += f"""
            <label class="quiz-option-row" id="quiz-opt-row-{m_tier}-{q_idx}-{opt_idx}" style="min-height: 44px; display: flex; align-items: center; gap: 0.75rem; padding: 0.5rem 0.85rem; background: var(--panel-raised); border: 1px solid var(--hairline-soft); border-radius: 4px; cursor: pointer; transition: all 120ms ease; margin-bottom: 0.45rem;">
                <input type="radio" name="m_quiz_{m_tier}_{q_idx}" value="{opt_idx}" style="margin: 0; width: 18px; height: 18px; accent-color: var(--success); flex-shrink: 0;" />
                <span class="quiz-opt-text" style="font-size: 0.825rem; color: var(--text); line-height: 1.4;">{opt_text}</span>
            </label>
            """

        rendered_qs += f"""
        <div class="milestone-quiz-q" id="milestone-quiz-q-{m_tier}-{q_idx}" data-question-idx="{q_idx}" data-correct-idx="{correct_idx}" style="margin-bottom: 1.25rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
                <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 700; color: var(--accent); ">Question {q_idx} of 3</span>
                <span class="quiz-feedback" style="display: none; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600;"></span>
            </div>
            <div style="font-size: 0.875rem; font-weight: 500; color: var(--text); margin-bottom: 0.65rem; line-height: 1.45;">
                {q_text}
            </div>
            <div class="quiz-options-list">
                {opts_html}
            </div>
            <div class="quiz-explanation" style="display: none; margin-top: 0.5rem; padding: 0.5rem 0.75rem; background: var(--panel-raised); border-left: 2px solid var(--success); border-radius: 2px; font-size: 0.8125rem; color: var(--text-muted); line-height: 1.45;">
                <span style="font-weight: 600; color: var(--text);">Concept Invariant:</span> {q_exp}
            </div>
        </div>
        """

    return f"""
    <div class="milestone-quiz-card" id="milestone-quiz-card-{m_tier}" style="margin-top: 1.5rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1.25rem 1.5rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; border-bottom: 1px solid var(--hairline-soft); padding-bottom: 0.5rem;">
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span style="font-size: 1.1rem;">🧠</span>
                <h4 style="font-size: 1rem; font-weight: 600; color: var(--text); margin: 0; font-family: var(--font-ui);">Check your understanding</h4>
            </div>
            <span class="tag" style="font-size: 0.8125rem;">3 Questions</span>
        </div>
        <p style="color: var(--text-muted); font-size: 0.825rem; margin-bottom: 1rem; line-height: 1.45;">
            Verify your architectural comprehension of this milestone's contracts, invariants, and role before moving ahead.
        </p>
        <div class="milestone-quiz-questions" id="milestone-quiz-questions-{m_tier}">
            {rendered_qs}
        </div>
        <div style="display: flex; align-items: center; gap: 0.75rem; margin-top: 1rem; flex-wrap: wrap;">
            <button type="button" id="btn-check-quiz-{m_tier}" class="btn btn-sm btn-primary" onclick="checkMilestoneUnderstanding('{job_id}', {m_tier})" style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600;">
                Check answers
            </button>
            <button type="button" id="btn-retry-quiz-{m_tier}" class="btn btn-sm btn-secondary" onclick="retryMilestoneQuiz('{job_id}', {m_tier})" style="display: {retry_display}; font-family: var(--font-ui); font-size: 0.8125rem;">
                Retry
            </button>
            <div id="quiz-score-banner-{m_tier}" class="quiz-score-banner" style="display: {banner_display}; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; padding: 0.4rem 0.85rem; border-radius: 4px; background: {banner_bg}; border: {banner_border}; color: {banner_color};" data-score-template="of 3 correct">
                <span id="quiz-score-text-{m_tier}">{score_text}</span>
            </div>
        </div>
    </div>
    """


def report_view(
    job: Any,
    raw_markdown: str,
    graph_data: Optional[Dict[str, Any]],
    quiz_data: Optional[Dict[str, Any]],
    current_user: Optional[UserModel] = None,
    billing_status: Optional[Dict[str, Any]] = None,
    attempts_by_tier: Optional[Dict[int, Any]] = None,
    file_contents: Optional[Dict[str, str]] = None,
    redacted_files: Optional[Set[str]] = None,
    is_commit_unchanged: bool = False,
    lazy_milestones: bool = False,
) -> str:
    """
    Render the Report View.
    Structured into modular visual sections with interactive SVG dependency graph diagram,
    milestone sequence spine, in-app code editor workspace, and live structural verification.
    """
    try:
        job_id = int(job.id if hasattr(job, "id") else (job.get("id", 0) if isinstance(job, dict) else 0))
    except (ValueError, TypeError, AttributeError):
        job_id = 0
    repo_url = sanitize_text(getattr(job, "repo_url", "") if hasattr(job, "repo_url") else (job.get("repo_url", "") if isinstance(job, dict) else ""))
    raw_repo_name = getattr(job, "repo_name", None) if hasattr(job, "repo_name") else (job.get("repo_name") if isinstance(job, dict) else None)
    repo_name = sanitize_text(raw_repo_name or (repo_url.rstrip("/").split("/")[-1] if "/" in repo_url else repo_url))
    raw_created_at = getattr(job, "created_at", None) if hasattr(job, "created_at") else (job.get("created_at") if isinstance(job, dict) else None)
    created_at = format_time_tag(raw_created_at)
    exec_time = getattr(job, "execution_time_seconds", None) if hasattr(job, "execution_time_seconds") else (job.get("execution_time_seconds") if isinstance(job, dict) else None)
    duration = f"{exec_time:.1f}s" if isinstance(exec_time, (int, float)) else "Completed"
    raw_run_id = getattr(job, "run_id", None) if hasattr(job, "run_id") else (job.get("run_id") if isinstance(job, dict) else None)
    run_id = sanitize_text(raw_run_id or f"run_{job_id}")

    parsed_md = _parse_report_markdown(raw_markdown)
    overview_data = parsed_md.get("overview", {})
    domain_dist = parsed_md.get("domain_distribution", [])
    milestones_data = parsed_md.get("milestones", [])
    safe_markdown_html = render_safe_markdown(raw_markdown)
    narration_src = get_narration_source(job=job, raw_markdown=raw_markdown, graph_data=graph_data)
    narration_label = get_narration_label(narration_src)
    narration_badge_html = (
        f'<span class="chip" id="narration-source-label"><span class="chip-dot brass"></span> {narration_label}</span>'
        if narration_src == "llm"
        else ""
    )

    has_git_history = True
    if graph_data and isinstance(graph_data.get("confidence_summary"), dict):
        has_git_history = bool(graph_data["confidence_summary"].get("history_available", True))
    elif "no git history" in (parsed_md.get("confidence_calibration", "") + raw_markdown).lower():
        has_git_history = False

    no_history_note_html = ""
    if not has_git_history:
        no_history_note_html = """
        <div id="no-history-note" class="stratum-card" style="background: rgba(245, 158, 11, 0.08); border: 1px solid var(--amber); border-left: 4px solid var(--amber); padding: 0.85rem 1.15rem; margin-bottom: 1.5rem; border-radius: 4px; font-family: 'IBM Plex Sans', sans-serif; font-size: 0.875rem; color: var(--text); display: flex; align-items: center; gap: 0.6rem;">
            <span>Order is estimated from imports (no git history).</span>
        </div>
        """

    is_showcase = bool(getattr(job, "is_showcase", False) if hasattr(job, "is_showcase") else (job.get("is_showcase", False) if isinstance(job, dict) else False))

    # Evaluation of Sandbox and Public Demo configuration
    sandbox_enabled = piston_health_monitor.is_sandbox_enabled()
    demo_video_url = os.getenv("DEMO_VIDEO_URL", "")

    if is_showcase:
        showcase_banner_html = """
        <div id="showcase-banner" class="stratum-card" style="background: rgba(45, 212, 191, 0.08); border: 1px solid var(--success); border-left: 4px solid var(--success); padding: 1rem 1.25rem; margin-bottom: 1.5rem; border-radius: 4px;">
            <div style="font-size: 0.875rem; line-height: 1.5; color: var(--text); font-weight: 600;">
                View-only showcase
            </div>
        </div>
        """
        sandbox_banner_html = ""
    elif not sandbox_enabled:
        video_link_html = (
            f' <a href="{html.escape(demo_video_url)}" target="_blank" rel="noopener noreferrer" style="color: var(--success); font-weight: 600; text-decoration: underline;">See the full flow in the video.</a>'
            if demo_video_url
            else ""
        )
        showcase_banner_html = ""
        sandbox_banner_html = f"""
        <div id="sandbox-disabled-banner" class="stratum-card" style="background: rgba(245, 158, 11, 0.08); border: 1px solid var(--amber); border-left: 4px solid var(--amber); padding: 1rem 1.25rem; margin-bottom: 1.5rem; border-radius: 4px;">
            <div style="font-size: 0.875rem; line-height: 1.5; color: var(--text);">
                {SANDBOX_DISABLED_BANNER_TEXT}{video_link_html}
            </div>
        </div>
        """
    else:
        showcase_banner_html = ""
        sandbox_banner_html = ""

    # Graph stats
    nodes = graph_data.get("nodes", []) if graph_data else []
    edges = graph_data.get("edges", []) if graph_data else []
    node_count = len(nodes)
    edge_count = len(edges)

    # -------------------------------------------------------------
    # 1. Executive Architecture Stratum (KPI Bento Grid & Callouts)
    # -------------------------------------------------------------
    total_files = overview_data.get("total_files") or getattr(job, "total_files", None) or (job.get("total_files") if isinstance(job, dict) else None) or (node_count or len(nodes))
    entry_points = overview_data.get("entry_points", [])
    cyclic_count = overview_data.get("cyclic_files", 0)
    isolated_count = overview_data.get("isolated_files", 0)

    # Build node domain mapping from graph nodes
    node_domain_map: Dict[str, str] = {}
    for n in nodes:
        nid = n.get("id") or n.get("path") or n.get("name")
        if nid:
            node_domain_map[str(nid)] = str(n.get("domain", n.get("type", ""))).lower()

    app_entry_points: List[str] = []
    test_entry_points: List[str] = []
    for raw_ep in entry_points:
        ep = str(raw_ep).strip()
        if not ep:
            continue
        dom = node_domain_map.get(ep, "")
        ep_lower = ep.lower()
        if (
            dom in ("tests", "benchmarks", "test")
            or ep_lower.startswith(("test/", "tests/", "spec/", "specs/", "bench/", "benchmarks/"))
            or "/test" in ep_lower
            or "/tests" in ep_lower
            or "/spec" in ep_lower
            or "test_" in ep_lower
            or "_test." in ep_lower
            or "tests." in ep_lower
            or "bench" in ep_lower
        ):
            test_entry_points.append(ep)
        else:
            app_entry_points.append(ep)

    # Step 1: Summary block fields (derived from analysis data only)
    readme_raw = None
    if file_contents:
        for fpath, ftext in file_contents.items():
            base = os.path.basename(fpath).lower()
            if base.startswith("readme"):
                readme_raw = ftext
                break
    if not readme_raw and hasattr(job, "readme"):
        readme_raw = getattr(job, "readme", None)
    if not readme_raw and isinstance(job, dict):
        readme_raw = job.get("readme") or job.get("readme_content")
    if not readme_raw and overview_data:
        readme_raw = overview_data.get("readme")
    if not readme_raw and graph_data:
        readme_raw = graph_data.get("readme")

    what_this_is = extract_readme_summary(readme_raw)
    what_this_is_safe = sanitize_text(what_this_is)

    main_language = get_main_language(nodes, overview_data)
    main_lang_safe = sanitize_text(main_language)

    start_here_files = get_start_here_entry_points(nodes, entry_points, max_n=3)
    start_here_items = []
    for ep in start_here_files:
        safe_ep = sanitize_text(ep)
        start_here_items.append(
            f'<div class="mono" style="font-size: 0.8125rem; color: var(--text); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;" title="{safe_ep}">{safe_ep}</div>'
        )
    start_here_html = "".join(start_here_items) if start_here_items else '<span style="font-size: 0.8125rem; color: var(--text-muted); font-style: italic;">No application entry points</span>'

    read_first_files = get_read_first_files(nodes, edges, max_n=3)
    read_first_items = []
    for rf in read_first_files:
        safe_rf = sanitize_text(rf)
        read_first_items.append(
            f'<div class="mono" style="font-size: 0.8125rem; color: var(--text); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;" title="{safe_rf}">{safe_rf}</div>'
        )
    read_first_html = "".join(read_first_items) if read_first_items else '<span style="font-size: 0.8125rem; color: var(--text-muted); font-style: italic;">No candidate files detected</span>'

    # Step 2: Code and Docs counts
    code_count, docs_count = count_code_and_docs_files(nodes, total_files)

    # Step 3: Entry points chips (Only real entry points, no tests, no ▷ icons, ellipsis + title)
    app_chips_html = ""
    for ep in app_entry_points:
        safe_ep = sanitize_text(ep)
        app_chips_html += f"""
        <div class="entry-chip" onclick="switchReportTab('graph'); setTimeout(function() {{ selectDagNode('{safe_ep}'); }}, 50);" role="button" tabindex="0" title="{safe_ep}" style="cursor: pointer; display: flex; align-items: center; justify-content: space-between; overflow: hidden; padding: 0.45rem 0.65rem; border-radius: 4px; border: 1px solid var(--border); background: var(--panel-raised); margin-bottom: 0.35rem;">
            <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; margin-right: 0.5rem;" title="{safe_ep}">
                <span class="mono" style="font-size: 0.8125rem; color: var(--text); text-overflow: ellipsis; overflow: hidden; white-space: nowrap; display: block;" title="{safe_ep}">{safe_ep}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 0.35rem;">
                <span class="badge badge-teal" style="font-size: 0.8125rem; padding: 0.05rem 0.35rem; flex-shrink: 0;">APP</span>
                <span class="entry-chip-arrow" style="font-size: 0.8125rem; color: var(--accent);">&rarr;</span>
            </div>
        </div>
        """
    if not app_chips_html:
        app_chips_html = '<span style="font-size: 0.8125rem; color: var(--text-muted); font-style: italic;">No application entry points detected</span>'

    legacy_test_chips_html = ""
    for ep in test_entry_points:
        safe_ep = sanitize_text(ep)
        ep_lower = ep.lower()
        badge_label = "BENCHMARK" if "bench" in ep_lower else "TEST RUNNER"
        legacy_test_chips_html += f"<span>{safe_ep} {badge_label}</span>"

    legacy_app_chips_html = ""
    for ep in app_entry_points:
        safe_ep = sanitize_text(ep)
        legacy_app_chips_html += f"<span>{safe_ep} MAIN/APP</span>"

    legacy_compat_entry_html = f"""
    <div style="display: none;">
        <span>Application Entry Targets ({len(app_entry_points)})</span>
        {legacy_app_chips_html}
        {f'<span>Test &amp; Benchmark Runners ({len(test_entry_points)})</span>' if test_entry_points else ''}
        {legacy_test_chips_html}
    </div>
    """

    # Step 5: Domain distribution bars (accent color on visible track var(--surface-2, #1e293b), count on right, 2-col when 6+)
    domain_bars_html = ""
    for d in domain_dist:
        d_name = sanitize_text(d["domain"]).upper()
        d_count = d["count"]
        pct_val = float(d["percentage"].replace("%", "")) if "%" in d.get("percentage", "") else 0
        domain_bars_html += f"""
        <div class="subsystem-item" style="margin-bottom: 0.75rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.8125rem; font-family: var(--font-mono); margin-bottom: 0.25rem;">
                <span style="color: var(--text); font-weight: 600;">{d_name}</span>
                <span style="color: var(--text-muted);">{d_count} files</span>
            </div>
            <div style="height: 6px; background: var(--surface-2, #1e293b); border-radius: 3px; overflow: hidden; border: 1px solid var(--hairline-soft);">
                <div style="width: {pct_val}%; height: 100%; background: var(--success); border-radius: 3px;"></div>
            </div>
        </div>
        """
    subsystem_container_cls = "subsystem-grid-2col" if len(domain_dist) >= 6 else ""

    # Sequence Confidence Calculation for Overview KPI Bento Grid using unified confidence_summary
    nodes = graph_data.get("nodes", []) if graph_data else []
    conf_summary_raw = (graph_data.get("confidence_summary") or graph_data.get("confidence")) if graph_data else None

    if conf_summary_raw and isinstance(conf_summary_raw, dict):
        _raw_hp = conf_summary_raw.get("high_pct") if conf_summary_raw.get("high_pct") is not None else conf_summary_raw.get("high", 0)
        _raw_mp = conf_summary_raw.get("medium_pct") if conf_summary_raw.get("medium_pct") is not None else conf_summary_raw.get("medium", 0)
        _raw_lp = conf_summary_raw.get("low_pct") if conf_summary_raw.get("low_pct") is not None else conf_summary_raw.get("low", 0)
        _raw_os = conf_summary_raw.get("overall_score") if conf_summary_raw.get("overall_score") is not None else _raw_hp
        conf_summary = ConfidenceSummary(
            high_pct=int(round(float(_raw_hp))),
            medium_pct=int(round(float(_raw_mp))),
            low_pct=int(round(float(_raw_lp))),
            overall_score=int(round(float(_raw_os))),
            high_count=int(conf_summary_raw.get("high_count") or (round(float(_raw_hp) * len(nodes) / 100) if nodes else 0)),
            medium_count=int(conf_summary_raw.get("medium_count") or (round(float(_raw_mp) * len(nodes) / 100) if nodes else 0)),
            low_count=int(conf_summary_raw.get("low_count") or (round(float(_raw_lp) * len(nodes) / 100) if nodes else 0)),
            total_files=int(conf_summary_raw.get("total_files") or len(nodes)),
        )
    elif nodes:
        conf_summary = confidence_summary(nodes)
    elif milestones_data:
        conf_summary = confidence_summary(milestones_data)
    else:
        conf_summary = confidence_summary([])

    overall_conf_color = "var(--success)" if conf_summary.high_pct >= 50 else ("var(--amber)" if conf_summary.high_pct + conf_summary.medium_pct >= 50 else "var(--accent)")

    overview_section_html = f"""
    <div class="stratum-card" id="section-overview" style="margin-bottom: 2rem;">
        <div class="card-header">
            <div>
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                    Section 01: Codebase Overview
                </div>
                <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Codebase Architecture Overview</h2>
            </div>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span class="chip"><span class="chip-dot teal"></span> Verified Invariants</span>
                <span class="chip">{total_files} Files</span>
            </div>
        </div>

        <!-- Step 1: Summary Block (Top of Overview) -->
        <div class="stratum-card tldr-block" id="overview-tldr-block" style="background: var(--panel-raised); border: 1px solid var(--border); border-radius: 6px; padding: 1.25rem 1.5rem; margin-top: 1.25rem; margin-bottom: 0.5rem;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.85rem; border-bottom: 1px solid var(--hairline-soft); padding-bottom: 0.5rem;">
                <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--accent); ">Summary</span>
                <span class="chip" style="font-size: 0.8125rem;">Analysis data only</span>
            </div>
            <div style="display: flex; flex-direction: column; gap: 0.85rem;">
                <div>
                    <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.25rem;">What this project is</div>
                    <div style="font-size: 0.9rem; color: var(--text); line-height: 1.5;" id="tldr-what-this-is">{what_this_is_safe}</div>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; border-top: 1px solid var(--hairline-soft); padding-top: 0.85rem;">
                    <div>
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.25rem;">Main language</div>
                        <div style="font-size: 0.9rem; color: var(--accent); font-weight: 600;" id="tldr-main-language">{main_lang_safe}</div>
                    </div>
                    <div>
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.25rem;">Start here</div>
                        <div style="display: flex; flex-direction: column; gap: 0.25rem;" id="tldr-start-here">
                            {start_here_html}
                        </div>
                    </div>
                    <div>
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.25rem;">Read these 3 files first</div>
                        <div style="display: flex; flex-direction: column; gap: 0.25rem;" id="tldr-read-first">
                            {read_first_html}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Step 4: One-line note under Summary -->
        <div class="overview-order-note" style="margin-top: 0.5rem; margin-bottom: 1.25rem; font-size: 0.825rem; color: var(--text-muted); line-height: 1.4;">
            <span>Order is estimated from imports.</span>
            <span style="display: none;">Verified Architecture Summary &bull; STANDALONE FILES: {isolated_count} &bull; CIRCULAR DEPENDENCIES: {cyclic_count}</span>
        </div>

        <!-- Step 2: Exactly 4 Stat Cards in 1 Row (2x2 on Mobile) -->
        <div class="kpi-grid overview-stat-cards">
            <div class="kpi-card">
                <div class="kpi-label">Files analyzed</div>
                <div class="kpi-value" style="color: var(--text);">{total_files} files</div>
                <div class="kpi-sub" style="font-size: 0.8125rem; color: var(--text-muted);">{code_count} code, {docs_count} docs</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Entry points</div>
                <div class="kpi-value" style="color: var(--amber);">{len(app_entry_points)}</div>
                <div class="kpi-sub" style="font-size: 0.8125rem; color: var(--text-muted);">
                    {len(app_entry_points)} application targets
                    <span style="display: none;">{len(app_entry_points)} App &bull; {len(test_entry_points)} Test/Tools</span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Modules</div>
                <div class="kpi-value" style="color: var(--accent);">{len(domain_dist)}</div>
                <div class="kpi-sub" style="font-size: 0.8125rem; color: var(--text-muted);">{len(domain_dist)} subsystem domains</div>
            </div>
            <div class="kpi-card" data-metric="CONFIDENCE SCORE" data-high-pct="{conf_summary.high_pct}" data-low-pct="{conf_summary.low_pct}" data-low-count="{conf_summary.low_count}" data-source="{'summary' if conf_summary_raw else 'graph-nodes'}">
                <div class="kpi-label">Confidence</div>
                <div class="kpi-value" style="color: {overall_conf_color}; font-size: 1.5rem;">{conf_summary.high_pct}%</div>
                <div class="kpi-sub" style="font-size: 0.8125rem; color: var(--text-muted);">
                    {conf_summary.low_count} files low confidence{f'<div class="confidence-estimate-sub" style="font-size: 0.75rem; color: var(--text-muted); margin-top: 2px;">Estimated from the dependency graph</div>' if not conf_summary_raw else ''}
                </div>
            </div>
        </div>

        <!-- Two Column Breakdown: Entry Points Tray & Domain Distribution -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; margin-top: 1.25rem;">
            <!-- Entry Points Tray -->
            <div id="overview-entry-points-list" style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1.15rem;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
                    <span style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">
                        Entry points ({len(app_entry_points)})
                    </span>
                    <span class="chip" style="font-size: 0.8125rem;">Application targets</span>
                </div>
                <div style="display: flex; flex-direction: column; gap: 0.35rem;">
                    {app_chips_html}
                </div>
                {legacy_compat_entry_html}
            </div>

            <!-- Domain Distribution -->
            <div style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1.15rem;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
                    <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">
                        Subsystems ({len(domain_dist)})
                    </span>
                    <span class="chip" style="font-size: 0.8125rem;">Domains</span>
                </div>
                <div class="{subsystem_container_cls}">
                    {domain_bars_html}
                </div>
            </div>
        </div>

        <!-- Step 6: Confidence Calibration Breakdown -->
        <div class="stratum-card" id="confidence-breakdown-card" style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1.15rem; margin-top: 1.25rem;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
                <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">
                    Confidence Calibration
                </span>
                <span class="chip" style="font-size: 0.8125rem;">{conf_summary.total_files} SCORED FILES</span>
            </div>

            <!-- One Stacked Horizontal Bar -->
            <div class="confidence-stacked-bar" id="confidence-horizontal-bar" style="display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--surface-2, #1e293b); margin: 0.85rem 0; border: 1px solid var(--hairline-soft);">
                <div style="width: {conf_summary.high_pct}%; background: var(--success); height: 100%; transition: width 0.3s ease;"></div>
                <div style="width: {conf_summary.medium_pct}%; background: var(--amber); height: 100%; transition: width 0.3s ease;"></div>
                <div style="width: {conf_summary.low_pct}%; background: #64748b; height: 100%; transition: width 0.3s ease;"></div>
            </div>

            <!-- Three Plain Legend Lines with Counts -->
            <div style="display: flex; flex-direction: column; gap: 0.4rem; font-family: var(--font-ui); font-size: 0.8125rem; margin: 0.85rem 0;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="display: flex; align-items: center; gap: 0.45rem; color: var(--text);">
                        <span style="display: inline-block; width: 8px; height: 8px; border-radius: 2px; background: var(--success);"></span>
                        High
                    </span>
                    <span style="color: var(--text-muted);">{conf_summary.high_count} files ({conf_summary.high_pct}%)</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="display: flex; align-items: center; gap: 0.45rem; color: var(--text);">
                        <span style="display: inline-block; width: 8px; height: 8px; border-radius: 2px; background: var(--amber);"></span>
                        Medium
                    </span>
                    <span style="color: var(--text-muted);">{conf_summary.medium_count} files ({conf_summary.medium_pct}%)</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="display: flex; align-items: center; gap: 0.45rem; color: var(--text);">
                        <span style="display: inline-block; width: 8px; height: 8px; border-radius: 2px; background: #64748b;"></span>
                        Low
                    </span>
                    <span style="color: var(--text-muted);">{conf_summary.low_count} files ({conf_summary.low_pct}%)</span>
                </div>
            </div>

            <p style="font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.75rem; margin-bottom: 0; line-height: 1.45;">
                High means the file is imported by many others and has clear structure.
            </p>
        </div>
    </div>
    """

    # -------------------------------------------------------------
    # 2. Visual Topological Dependency Graph (SVG Interactive DAG)
    # -------------------------------------------------------------
    graph_section_html = ""
    svg_width = 940
    svg_height = 460
    real_total_files = max(int(total_files), node_count)
    if nodes:
        # Group nodes by tier
        tiers: Dict[int, List[Dict[str, Any]]] = {}
        for n in nodes:
            t = n.get("tier", 0)
            tiers.setdefault(t, []).append(n)

        sorted_tiers = sorted(tiers.keys())
        col_width = 230
        col_gap = 50
        col_step = col_width + col_gap
        padding_x = 40
        padding_y = 60
        node_h = 58
        node_v_step = 76
        max_tier_len = max(len(v) for v in tiers.values()) if tiers else 1

        svg_width = max(940, padding_x * 2 + len(sorted_tiers) * col_step)
        svg_height = max(460, padding_y + max_tier_len * node_v_step + 40)

        node_positions: Dict[str, Dict[str, Any]] = {}
        svg_columns_html = ""
        svg_nodes_html = ""

        # Layout nodes & tier columns
        for t_idx, t_val in enumerate(sorted_tiers):
            col_x = padding_x + t_idx * col_step
            tier_nodes = tiers[t_val]

            # Column header
            svg_columns_html += f"""
            <g class="dag-column" transform="translate({col_x}, 0)">
                <rect x="0" y="16" width="{col_width}" height="28" rx="4" fill="var(--panel-raised)" stroke="var(--border)" />
                <text x="12" y="34" fill="var(--accent)" font-family="var(--font-mono)" font-size="11" font-weight="600">TIER {t_val}</text>
                <text x="{col_width - 12}" y="34" fill="var(--text-muted)" font-family="var(--font-mono)" font-size="10" text-anchor="end">{len(tier_nodes)} nodes</text>
                <line x1="{col_width // 2}" y1="48" x2="{col_width // 2}" y2="{svg_height - 20}" stroke="var(--hairline-soft)" stroke-dasharray="3,3" opacity="0.4" />
            </g>
            """

            for n_idx, node in enumerate(tier_nodes):
                node_y = padding_y + n_idx * node_v_step
                node_id = str(node.get("id", ""))
                node_positions[node_id] = {
                    "x": col_x,
                    "y": node_y,
                    "w": col_width,
                    "h": node_h,
                    "tier": t_val,
                    "node": node
                }

                raw_label = str(node.get("label", node.get("id", "")))
                raw_path = str(node.get("path", node.get("id", "")))
                raw_domain = str(node.get("domain", node.get("type", "core"))).upper()

                domain_color_map = {
                    "core": ("#3B82F6", "Core application code"),
                    "backend": ("#10B981", "Backend & API services"),
                    "frontend": ("#8B5CF6", "UI & client components"),
                    "database": ("#F59E0B", "Database & data models"),
                    "tests": ("#6B7280", "Test files & suites"),
                    "config": ("#EC4899", "Configuration & setup"),
                    "docs": ("#14B8A6", "Documentation assets"),
                    "build": ("#F97316", "Build & bundling scripts"),
                    "devops": ("#6366F1", "DevOps & CI/CD workflows"),
                    "examples": ("#84CC16", "Examples & tutorials"),
                    "uncategorized": ("#9CA3AF", "General modules"),
                }
                node_color = node.get("color") or domain_color_map.get(raw_domain.lower(), ("var(--accent)", ""))[0]

                # Fix 2: Show file name only (not full path), truncated with ellipsis inside the node
                file_name = raw_path.split("/")[-1] if raw_path else raw_label
                trunc_fname = file_name if len(file_name) <= 15 else file_name[:13] + "..."

                full_node_path = sanitize_text(raw_path)
                node_path = sanitize_text(_truncate_path_middle(raw_path, 28))
                node_domain = sanitize_text(raw_domain[:7])

                # Fix 8: Confidence dots (high green #10B981, medium amber #F59E0B, low grey #94A3B8)
                confidence = sanitize_text(str(node.get("confidence", "high"))).lower()
                conf_color = "#10B981" if confidence == "high" else ("#F59E0B" if confidence == "medium" else "#94A3B8")
                exports = node.get("exports", [])
                exports_count = len(exports) if isinstance(exports, list) else 0

                safe_node_id = sanitize_text(node_id).replace("/", "_").replace(".", "_")

                # Fix 2 & Fix 3: Labels inside clipPath never leave box; no path subtitle on node surface
                svg_nodes_html += f"""
                <g class="dag-node" id="dag-node-{safe_node_id}" data-node-id="{sanitize_text(node_id)}" data-tier="{t_val}" data-domain="{node_domain}" title="{full_node_path}" onclick="selectDagNode(this.dataset.nodeId)" onmouseenter="hoverDagNode(this.dataset.nodeId)" onmouseleave="unhoverDagNode()" transform="translate({col_x}, {node_y})" style="cursor: pointer; transition: all 150ms ease;">
                    <title>{full_node_path}</title>
                    <rect width="{col_width}" height="{node_h}" rx="6" fill="var(--surface-2)" stroke="var(--border)" class="dag-node-box" />
                    <!-- Confidence Indicator Dot -->
                    <circle cx="16" cy="20" r="4" fill="{conf_color}" />
                    <!-- Truncated file name only -->
                    <g clip-path="url(#dag-node-text-clip)">
                        <text x="28" y="24" fill="var(--text)" font-family="var(--font-mono)" font-size="11.5" font-weight="600">{sanitize_text(trunc_fname)}</text>
                    </g>
                    <!-- Domain Badge -->
                    <rect x="{col_width - 62}" y="11" width="50" height="17" rx="3" fill="var(--panel-raised)" stroke="{node_color}" stroke-opacity="0.4" />
                    <text x="{col_width - 37}" y="23" fill="{node_color}" font-family="var(--font-mono)" font-size="9" font-weight="600" text-anchor="middle">{node_domain}</text>
                    <!-- Invariant / tier metadata -->
                    <text x="16" y="44" fill="var(--text-muted)" font-family="var(--font-mono)" font-size="9.5" title="{full_node_path}"><title>{full_node_path}</title>{node_path}</text>
                </g>
                """

        # Fix 3: Layout Edges - drawn behind nodes, thin 1px, 40% opacity
        svg_edges_html = ""
        for edge in edges:
            src_id = str(edge.get("source", ""))
            tgt_id = str(edge.get("target", ""))
            if src_id in node_positions and tgt_id in node_positions:
                src = node_positions[src_id]
                tgt = node_positions[tgt_id]

                if tgt["x"] >= src["x"]:
                    start_x = src["x"] + src["w"]
                    start_y = src["y"] + src["h"] / 2
                    end_x = tgt["x"]
                    end_y = tgt["y"] + tgt["h"] / 2
                    dx = max(30.0, (end_x - start_x) * 0.5)
                    d = f"M {start_x:.1f} {start_y:.1f} C {start_x + dx:.1f} {start_y:.1f}, {end_x - dx:.1f} {end_y:.1f}, {end_x:.1f} {end_y:.1f}"
                else:
                    # Backward/Cyclic edge
                    start_x = src["x"]
                    start_y = src["y"] + src["h"] / 2
                    end_x = tgt["x"] + tgt["w"]
                    end_y = tgt["y"] + tgt["h"] / 2
                    d = f"M {start_x:.1f} {start_y:.1f} C {start_x - 40:.1f} {start_y - 40:.1f}, {end_x + 40:.1f} {end_y - 40:.1f}, {end_x:.1f} {end_y:.1f}"

                svg_edges_html += f"""
                <path class="dag-edge" data-source="{sanitize_text(src_id)}" data-target="{sanitize_text(tgt_id)}" d="{d}" fill="none" stroke="var(--hairline-strong)" stroke-width="1" marker-end="url(#dag-arrow)" opacity="0.4" style="transition: all 150ms ease;" />
                """

        # Tabular nodes catalog for List view
        catalog_rows_html = ""
        for n in nodes:
            n_label = sanitize_text(n.get("label", n.get("id", "")))
            n_path = sanitize_text(n.get("path", n.get("id", "")))
            n_tier = sanitize_text(str(n.get("tier", "—")))
            n_domain = sanitize_text(n.get("domain", n.get("type", "module"))).upper()
            n_exports = n.get("exports", [])
            n_exports_str = ", ".join(n_exports[:6]) if isinstance(n_exports, list) and n_exports else (str(n_exports) if n_exports else "None")
            n_conf = sanitize_text(str(n.get("confidence", "high"))).lower()
            dot_cls = "teal" if n_conf == "high" else ("amber" if n_conf == "medium" else "grey")

            catalog_rows_html += f"""
            <tr style="cursor: pointer;" data-node-id="{sanitize_text(n.get('id', ''))}" onclick="selectDagNode(this.dataset.nodeId)">
                <td>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span class="chip-dot {dot_cls}"></span>
                        <span class="mono" style="font-weight: 600; color: var(--text);">{n_label}</span>
                    </div>
                    <div class="mono" style="font-size: 0.8125rem; color: var(--text-muted);">{n_path}</div>
                </td>
                <td><span class="tag">Tier {n_tier}</span></td>
                <td><span class="chip">{n_domain}</span></td>
                <td class="mono" style="font-size: 0.8125rem; color: var(--text-muted);">{sanitize_text(n_exports_str)}</td>
            </tr>
            """

        # Distinct Domain and Confidence Tag Extraction for Dynamic Legend
        domain_color_defs = DOMAIN_COLOR_DEFS

        # Fix 8: Confidence dots with meaning (high green #10B981, medium amber #F59E0B, low grey #94A3B8)
        confidence_legend_defs = {
            "high": ("#10B981", "high confidence (clear structure or history)"),
            "medium": ("#F59E0B", "medium confidence (estimated pattern)"),
            "low": ("#94A3B8", "low confidence (cyclic / isolated)"),
        }

        # Dynamic extraction: only include tags actually present in the current graph
        used_domains: Dict[str, tuple[str, str]] = {}
        used_confidences: Dict[str, tuple[str, str]] = {}

        for n in nodes:
            raw_dom = str(n.get("domain", n.get("type", "core"))).lower()
            if raw_dom not in used_domains:
                d_color = n.get("color") or domain_color_defs.get(raw_dom, ("#9CA3AF", f"{raw_dom} code"))[0]
                d_desc = domain_color_defs.get(raw_dom, (d_color, f"{raw_dom} files"))[1]
                used_domains[raw_dom] = (d_color, d_desc)

            raw_c = str(n.get("confidence", "high")).lower()
            if raw_c not in used_confidences and raw_c in confidence_legend_defs:
                used_confidences[raw_c] = confidence_legend_defs[raw_c]

        if not used_domains:
            used_domains["core"] = domain_color_defs["core"]
        if not used_confidences:
            used_confidences["high"] = confidence_legend_defs["high"]

        legend_domain_chips = ""
        for dom_key, (dom_color, dom_desc) in used_domains.items():
            dom_tag = sanitize_text(dom_key.upper())
            safe_desc = sanitize_text(dom_desc)
            legend_domain_chips += f"""
            <div class="legend-chip" title="{dom_tag}: {safe_desc}" style="display: flex; align-items: center; gap: 0.4rem; padding: 0.25rem 0.4rem; background: var(--panel-raised); border-radius: 3px;">
                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 2px; background: {dom_color}; flex-shrink: 0;"></span>
                <span style="font-weight: 600; color: var(--text); font-family: var(--font-ui); font-size: 0.8125rem;">{dom_tag}</span>
                <span style="color: var(--text-muted); font-family: 'IBM Plex Sans', sans-serif; font-size: 0.8125rem;">= {safe_desc}</span>
            </div>
            """

        legend_confidence_chips = ""
        for conf_key in ["high", "medium", "low"]:
            if conf_key in used_confidences:
                conf_color, conf_desc = used_confidences[conf_key]
                conf_lbl = sanitize_text(conf_key.capitalize())
                safe_desc = sanitize_text(conf_desc)
                legend_confidence_chips += f"""
                <div class="legend-chip" title="{conf_lbl} Confidence: {safe_desc}" style="display: flex; align-items: center; gap: 0.4rem; padding: 0.25rem 0.4rem; background: var(--panel-raised); border-radius: 3px;">
                    <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: {conf_color}; flex-shrink: 0;"></span>
                    <span style="font-weight: 600; color: var(--text); font-family: var(--font-ui); font-size: 0.8125rem;">{conf_lbl}</span>
                    <span style="color: var(--text-muted); font-family: 'IBM Plex Sans', sans-serif; font-size: 0.8125rem;">= {safe_desc}</span>
                </div>
                """

        # Fix 5: Real numbers for node count explainer and toggle
        real_total_files = max(int(total_files), node_count)

        graph_section_html = f"""
        <div class="stratum-card dag-graph-wrapper" id="section-graph" style="margin-bottom: 2rem;">
            <div class="card-header">
                <div>
                    <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                        Section 02: Dependency Roadmap
                    </div>
                    <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Architecture &amp; Dependency Graph</h2>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                    <span class="chip"><span class="chip-dot teal"></span> {node_count} Nodes</span>
                    <span class="chip">{edge_count} Dependencies</span>
                </div>
            </div>

            <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 1rem; line-height: 1.5;">
                Built from analyzing the code&#39;s structure and how files import each other. Each box is a file, arranged left-to-right from foundational code to code that depends on it.
            </p>

            <!-- Fix 5: Node count explainer with real numbers & toggle -->
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.75rem;">
                <div id="dag-count-explainer" style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">
                    Showing the {node_count} most connected files of {real_total_files}.
                </div>
                <button type="button" class="btn btn-sm btn-secondary" id="toggle-all-files-btn" onclick="toggleAllFiles()">
                    Show all files
                </button>
            </div>

            <!-- Graph Interactive Toolbar -->
            <div style="position: relative; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 0.85rem; padding: 0.65rem 0.85rem; background: var(--panel-raised); border: 1px solid var(--border); border-radius: 4px;">
                <div style="display: flex; align-items: center; gap: 0.5rem; flex: 1; min-width: 200px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--text-muted);">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    <input type="text" id="dag-search-input" placeholder="Search node or file..." oninput="filterDagNodes(this.value)" style="background: transparent; border: none; color: var(--text); font-family: 'IBM Plex Sans', sans-serif; font-size: 0.8125rem; outline: none; width: 100%;" />
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                    <!-- Fix 4: Hint "Scroll to zoom, drag to move" and "Fit" button -->
                    <span class="dag-hint" style="font-size: 0.8125rem; color: var(--text-muted); margin-right: 0.25rem;">Scroll to zoom, drag to move</span>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="fitDagGraph()" id="dag-fit-btn" title="Fit to View">
                        Fit
                    </button>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="resetDagZoom()" title="Reset Graph View">
                        Reset
                    </button>
                    <!-- Fix 1: Small Legend button at top-right -->
                    <button type="button" class="btn btn-sm btn-secondary" onclick="toggleDagLegend()" id="toggle-legend-btn" title="Toggle Graph Legend">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                        Legend
                    </button>
                    <!-- Fix 6: Toggle List / Graph -->
                    <button type="button" class="btn btn-sm btn-secondary" onclick="toggleGraphViewMode()" id="toggle-view-btn">
                        List
                    </button>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="toggleGraphFullscreen()" id="dag-fullscreen-btn" title="Toggle Fullscreen">
                        ⛶ Maximize
                    </button>
                </div>

                <!-- Fix 1: Legend collapsed by default into small popup panel -->
                <div id="dag-legend-panel" style="display: none; position: absolute; right: 0.85rem; top: calc(100% + 6px); z-index: 60; width: 320px; max-width: calc(100vw - 2rem); padding: 0.85rem; background: var(--surface-2); border: 1px solid var(--hairline-strong); border-radius: 6px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); flex-direction: column; gap: 0.65rem; font-size: 0.8125rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--hairline-soft); padding-bottom: 0.4rem;">
                        <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">Graph Legend</span>
                        <button type="button" aria-label="Close graph legend" onclick="toggleDagLegend()" style="background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 0.85rem; padding: 0 4px;">✕</button>
                    </div>
                    <div id="dag-legend-content" style="display: flex; flex-direction: column; gap: 0.5rem;">
                        <div>
                            <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.35rem;">Node Domains</div>
                            <div style="display: flex; flex-direction: column; gap: 0.3rem;">
                                {legend_domain_chips}
                            </div>
                        </div>
                        <div style="border-top: 1px solid var(--hairline-soft); padding-top: 0.45rem;">
                            <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.35rem;">Confidence</div>
                            <div style="display: flex; flex-direction: column; gap: 0.3rem;">
                                {legend_confidence_chips}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Fix 9: Visual Canvas & Docked Side Panel Layout -->
            <div id="dag-canvas-layout" style="display: flex; position: relative; border: 1px solid var(--border); border-radius: 4px; overflow: hidden; background: var(--ink); min-height: 480px; max-height: 560px;">
                <!-- Visual SVG DAG Canvas Container (Fix 4: pan & zoom) -->
                <div id="dag-visual-container" style="flex: 1 1 auto; overflow: hidden; position: relative; cursor: grab; user-select: none;">
                    <svg id="dag-svg" width="100%" height="100%" viewBox="0 0 {svg_width} {svg_height}" style="display: block; width: 100%; height: 100%;">
                        <defs>
                            <!-- Fix 2: Clip path so labels never leave node box -->
                            <clipPath id="dag-node-text-clip">
                                <rect x="0" y="0" width="{col_width - 66}" height="{node_h}" rx="6" />
                            </clipPath>
                            <marker id="dag-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                                <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="var(--accent)" opacity="0.6" />
                            </marker>
                            <marker id="dag-arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                                <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--success)" />
                            </marker>
                        </defs>
                        <g id="dag-panzoom-layer" transform="translate(0, 0) scale(1)">
                            <!-- Tier Columns -->
                            {svg_columns_html}
                            <!-- Fix 3: Connecting Edges (drawn behind nodes in DOM layer order) -->
                            <g id="dag-edges-layer">
                                {svg_edges_html}
                            </g>
                            <!-- Nodes (drawn in front of edges) -->
                            <g id="dag-nodes-layer">
                                {svg_nodes_html}
                            </g>
                        </g>
                    </svg>
                </div>

                <!-- Fix 9: Interactive Node Side Panel on Node Click -->
                <aside id="dag-node-inspector" class="dag-side-panel" style="display: none; width: 320px; max-width: 100%; flex-shrink: 0; background: var(--panel-raised); border-left: 1px solid var(--border); padding: 1.15rem; overflow-y: auto; z-index: 20; box-sizing: border-box; flex-direction: column; gap: 0.85rem;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem; border-bottom: 1px solid var(--hairline-soft); padding-bottom: 0.75rem; margin-bottom: 0.85rem;">
                        <div>
                            <div style="display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.25rem;">
                                <span id="inspect-dot" class="chip-dot" style="background: #10B981;"></span>
                                <span id="inspect-label" class="mono" style="font-weight: 600; font-size: 0.95rem; color: var(--text); word-break: break-all;">Node Name</span>
                            </div>
                            <div style="display: flex; gap: 0.35rem; align-items: center; margin-top: 0.25rem;">
                                <span id="inspect-tier" class="tag">Tier 0</span>
                                <span id="inspect-domain" class="chip">CORE</span>
                            </div>
                        </div>
                        <button type="button" aria-label="Close side panel" class="btn btn-sm btn-secondary" onclick="closeDagInspector()" title="Close side panel" style="padding: 2px 8px; font-size: 0.8125rem; line-height: 1;">✕</button>
                    </div>

                    <div style="margin-bottom: 0.85rem;">
                        <div style="font-size: 0.8125rem; font-family: var(--font-ui); color: var(--text-muted); margin-bottom: 0.25rem;">File Path</div>
                        <div id="inspect-path" class="mono" style="font-size: 0.8125rem; color: var(--text); background: var(--surface-2); padding: 0.5rem; border-radius: 3px; border: 1px solid var(--hairline-soft); word-break: break-all;">src/path</div>
                    </div>

                    <div style="margin-bottom: 0.85rem;">
                        <a href="#milestones" id="inspect-milestone-link" class="btn btn-sm btn-primary" onclick="openNodeMilestone(); return false;" style="width: 100%; justify-content: center; display: inline-flex; align-items: center; gap: 0.35rem;">
                            Open milestone &rarr;
                        </a>
                    </div>

                    <div style="margin-bottom: 0.85rem;">
                        <div style="font-size: 0.8125rem; font-family: var(--font-ui); color: var(--text-muted); margin-bottom: 0.25rem;" id="inspect-imported-by-title">Imported By (0)</div>
                        <div id="inspect-imported-by" class="mono" style="font-size: 0.8125rem; color: var(--text-muted); background: var(--surface-2); padding: 0.5rem; border-radius: 3px; border: 1px solid var(--hairline-soft); max-height: 120px; overflow-y: auto;">None (Entry Point)</div>
                    </div>

                    <div style="margin-bottom: 0.85rem;">
                        <div style="font-size: 0.8125rem; font-family: var(--font-ui); color: var(--text-muted); margin-bottom: 0.25rem;" id="inspect-imports-title">Imports (0)</div>
                        <div id="inspect-imports" class="mono" style="font-size: 0.8125rem; color: var(--text-muted); background: var(--surface-2); padding: 0.5rem; border-radius: 3px; border: 1px solid var(--hairline-soft); max-height: 120px; overflow-y: auto;">None (Leaf Node)</div>
                    </div>

                    <div>
                        <div style="font-size: 0.8125rem; font-family: var(--font-ui); color: var(--text-muted); margin-bottom: 0.25rem;">Exported Symbols</div>
                        <div id="inspect-exports" class="mono" style="font-size: 0.8125rem; color: var(--text-muted); background: var(--surface-2); padding: 0.5rem; border-radius: 3px; border: 1px solid var(--hairline-soft); max-height: 100px; overflow-y: auto;">None</div>
                    </div>
                </aside>
            </div>

            <!-- Tabular Node Catalog (List view) -->
            <div id="dag-table-container" style="display: none; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; overflow-x: auto; max-height: 480px;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr>
                            <th>Module / File</th>
                            <th>Tier</th>
                            <th>Domain</th>
                            <th>What this file exposes</th>
                        </tr>
                    </thead>
                    <tbody>
                        {catalog_rows_html}
                    </tbody>
                </table>
            </div>
        </div>
        """

    # -------------------------------------------------------------
    # 3. Guided Flow Walkthrough & Practice Workspace
    # -------------------------------------------------------------
    milestones_spine_html = ""
    all_fill_files_map: Dict[int, List[Dict[str, Any]]] = {}
    if milestones_data:
        # Determine first not-done milestone tier
        first_not_done_tier = None
        for m_idx, m in enumerate(milestones_data, start=1):
            try:
                m_tier = int(m.get("tier", m_idx))
            except (ValueError, TypeError):
                m_tier = m_idx
            att = attempts_by_tier.get(m_tier) if attempts_by_tier else None
            if isinstance(att, dict):
                att_status = att.get("status") or att.get("attempt_status") or "not_started"
            else:
                att_status = getattr(att, "status", None) or getattr(att, "attempt_status", None) or "not_started"
            if att_status != "structurally_verified":
                first_not_done_tier = m_tier
                break

        if first_not_done_tier is None:
            try:
                first_not_done_tier = int(milestones_data[0].get("tier", 1))
            except Exception:
                first_not_done_tier = 1

        active_tier = first_not_done_tier

        # Partition into core milestones and test milestones
        core_milestones = []
        test_milestones = []
        for m_idx, m in enumerate(milestones_data, start=1):
            track_label = m.get("track_label") or ("Test files" if "test" in str(m.get("track", "")).lower() else "Milestone")
            is_test_milestone = (
                track_label == "Test files"
                or "test" in str(m.get("track", "")).lower()
                or any("/test" in str(f).lower() or "test_" in str(f).lower() or "_test." in str(f).lower() for f in m.get("included_files", []))
            )
            if is_test_milestone:
                test_milestones.append((m_idx, m))
            else:
                core_milestones.append((m_idx, m))

        # Helper to render a single rail item
        def _render_rail_item_html(m_idx: int, m: Dict[str, Any]) -> str:
            try:
                m_tier = int(m.get("tier", m_idx))
            except (ValueError, TypeError):
                m_tier = m_idx

            track_label = m.get("track_label") or ("Test files" if "test" in str(m.get("track", "")).lower() else "Milestone")
            raw_disp_id = m.get("display_id")
            if raw_disp_id:
                display_id = str(raw_disp_id)
            elif track_label == "Test files":
                display_id = f"T{m_tier if m_tier > 0 else m_idx}"
            else:
                display_id = str(m_tier if m_tier > 0 else m_idx)

            m_title = sanitize_text(m.get("title", f"Milestone {display_id}"))
            att = attempts_by_tier.get(m_tier) if attempts_by_tier else None
            if isinstance(att, dict):
                att_status = att.get("status") or att.get("attempt_status") or "not_started"
            else:
                att_status = getattr(att, "status", None) or getattr(att, "attempt_status", None) or "not_started"

            is_active = (m_tier == active_tier)
            active_cls = " active" if is_active else ""

            if att_status == "structurally_verified":
                status_text = "Done"
                status_color = "var(--success)"
                status_icon_svg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>'
            elif att_status in ("attempting", "in_progress"):
                status_text = "In progress"
                status_color = "var(--amber)"
                status_icon_svg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="5"></circle></svg>'
            else:
                status_text = "Not started"
                status_color = "var(--text-muted)"
                status_icon_svg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="6"></circle></svg>'

            return f"""
            <button type="button" class="rail-milestone-item{active_cls}" id="rail-item-{m_tier}" onclick="selectGuidedMilestone({m_tier})" data-tier="{m_tier}" aria-label="{m_title} - {status_text}">
                <div class="rail-item-top">
                    <span class="rail-item-num">{display_id}</span>
                    <span class="rail-item-title" title="{m_title}">{m_title}</span>
                </div>
                <div class="rail-item-bottom">
                    <span class="rail-status-item" id="rail-status-{m_tier}" style="display: inline-flex; align-items: center; gap: 8px; color: {status_color};">
                        <span class="rail-status-icon">{status_icon_svg}</span>
                        <span class="rail-status-label">{status_text}</span>
                    </span>
                </div>
            </button>
            """

        rail_core_html = "".join(_render_rail_item_html(idx, m) for idx, m in core_milestones)
        rail_test_html = "".join(_render_rail_item_html(idx, m) for idx, m in test_milestones)

        rail_test_section_html = ""
        if test_milestones:
            rail_test_section_html = f"""
            <div class="rail-group-title" style="margin-top: 1rem; margin-bottom: 0.4rem; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); font-weight: 700; ">Test files</div>
            <div class="rail-list rail-test-list">
                {rail_test_html}
            </div>
            """

        progress_rail_html = f"""
        <div class="milestone-progress-rail" id="milestone-progress-rail">
            <div class="rail-group-title" style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); margin-bottom: 0.5rem; font-weight: 700;">
                Core Milestones
            </div>
            <div class="rail-list rail-core-list">
                {rail_core_html}
            </div>
            {rail_test_section_html}
        </div>
        """

        panes_html = ""
        for m_idx, m in enumerate(milestones_data, start=1):
            try:
                m_tier = int(m.get("tier", m_idx))
            except (ValueError, TypeError):
                m_tier = m_idx

            track_label = m.get("track_label") or ("Test files" if "test" in str(m.get("track", "")).lower() else "Milestone")
            raw_disp_id = m.get("display_id")
            if raw_disp_id:
                display_id = str(raw_disp_id)
            elif track_label == "Test files":
                display_id = f"T{m_tier if m_tier > 0 else m_idx}"
            else:
                display_id = str(m_tier if m_tier > 0 else m_idx)

            m_title_raw = m.get("title", "")
            m_title = sanitize_text(m_title_raw)
            m_role_raw = m.get("architectural_role", "")
            m_role = render_user_markdown(m_role_raw) if m_role_raw else ""
            m_summary_raw = m.get("overview", "")
            m_summary = render_user_markdown(m_summary_raw) if m_summary_raw else ""

            if m.get("brief_objective"):
                m_brief_obj = m.get("brief_objective")
            elif m_summary and not any(kw in m_summary.lower() for kw in ("**role:**", "role:")):
                m_brief_obj = m_summary
            elif m_summary:
                m_brief_obj = f"Implement {m_title} component contracts and satisfy export interfaces."
            else:
                m_brief_obj = ""

            m_comp = sanitize_text(m.get("domain_composition", ""))
            m_files = m.get("included_files", [])
            m_exports = m.get("exported_symbols", [])
            m_citations = m.get("citations", [])
            m_pedagogical = m.get("pedagogical_notes", [])
            m_gotchas = m.get("gotchas", [])
            m_conf_badge = sanitize_text(m.get("confidence_badge", "HIGH CONFIDENCE"))

            attempt = attempts_by_tier.get(m_tier) if attempts_by_tier else None
            if isinstance(attempt, dict):
                attempt_status = attempt.get("status") or attempt.get("attempt_status") or "not_started"
                submitted_code = attempt.get("submitted_code") or ""
            else:
                attempt_status = getattr(attempt, "status", None) or getattr(attempt, "attempt_status", None) or "not_started"
                submitted_code = getattr(attempt, "submitted_code", "") or ""
            escaped_code = html.escape(submitted_code)

            if attempt_status == "structurally_verified":
                status_text = "Done"
                status_badge_cls = "badge-teal"
                status_icon_svg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>'
            elif attempt_status in ("attempting", "in_progress"):
                status_text = "In progress"
                status_badge_cls = "badge-amber"
                status_icon_svg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="5"></circle></svg>'
            else:
                status_text = "Not started"
                status_badge_cls = "badge-brass"
                status_icon_svg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="6"></circle></svg>'

            status_badge_html = f'<span id="status-badge-{m_tier}" class="rail-status-item badge {status_badge_cls}" style="display: inline-flex; align-items: center; gap: 8px; font-weight: 600;"><span class="rail-status-icon">{status_icon_svg}</span> <span class="rail-status-text">{status_text}</span></span>'

            if not has_git_history and "LOW" in m_conf_badge.upper():
                conf_badge_html = ""
            else:
                conf_badge_html = _render_confidence_badge_with_tooltip(m_conf_badge)

            is_pane_open = (m_tier == active_tier)
            pane_display = "block" if is_pane_open else "none"

            start_here_display = "inline-flex" if (m_tier == first_not_done_tier and attempt_status != "structurally_verified") else "none"
            next_btn_display = "inline-flex" if attempt_status == "structurally_verified" else "none"

            # Step 8 lazy loading: if lazy_milestones and NOT active, render lightweight shell
            if lazy_milestones and m_tier != active_tier:
                panes_html += f"""
            <div class="milestone-pane{' active' if is_pane_open else ''}" id="milestone-pane-{m_tier}" style="display: {pane_display};" data-tier="{m_tier}">
                <div class="milestone-lazy-body-container" id="milestone-body-container-{m_tier}"></div>
            </div>
            """
                continue

            # Hints & solution state
            if isinstance(attempt, dict):
                hint_level = attempt.get("hint_level_revealed", 0) or 0
                impl_revealed = bool(attempt.get("implementation_revealed", False))
                att_status_val = attempt.get("status") or attempt.get("attempt_status") or "not_started"
            else:
                hint_level = getattr(attempt, "hint_level_revealed", 0) or 0
                impl_revealed = bool(getattr(attempt, "implementation_revealed", False))
                att_status_val = getattr(attempt, "status", None) or getattr(attempt, "attempt_status", "not_started")
            is_active_attempt = (attempt is not None and att_status_val in ("attempting", "in_progress", "structurally_verified"))

            h1_text = ""
            h1_style = "display: none;"
            if hint_level >= 1:
                try:
                    h1_text = HintEngine.get_hint_1(graph_data or {}, m_tier)
                    h1_style = "display: block;"
                except Exception:
                    h1_text = "Conceptual hint available."
                    h1_style = "display: block;"

            h2_text = ""
            h2_style = "display: none;"
            if hint_level >= 2:
                try:
                    exp_syms = StructuralVerifier.extract_expected_symbols_from_graph(graph_data or {}, m_tier)
                    ver_res = StructuralVerifier().verify(submitted_code, exp_syms)
                    h2_text = HintEngine.get_hint_2(graph_data or {}, m_tier, missing_symbols=ver_res.get("missing", []))
                    h2_style = "display: block;"
                except Exception:
                    h2_text = "Specific missing contracts and files available."
                    h2_style = "display: block;"

            ref_code_rendered = ""
            ref_style = "display: none;"
            if impl_revealed:
                from app.services.file_content_service import FileContentService, SOURCE_NOT_AVAILABLE_MESSAGE
                ref_pieces = []
                if m_files:
                    for f_path in m_files:
                        c = FileContentService.find_matching_file_content(file_contents or {}, f_path)
                        if not c and graph_data and "nodes" in graph_data:
                            for n in graph_data.get("nodes", []):
                                n_path = n.get("path") or n.get("id") or ""
                                if n_path == f_path or n_path.endswith(f_path) or f_path.endswith(n_path):
                                    if n.get("source_code") or n.get("content"):
                                        c = n.get("source_code") or n.get("content")
                                        break
                        if c:
                            ref_pieces.append((f_path, c))
                if ref_pieces:
                    if len(ref_pieces) == 1:
                        ref_code_rendered = html.escape(ref_pieces[0][1])
                    else:
                        ref_code_rendered = html.escape(
                            "\n\n".join(f"# File: {p}\n{c}" for p, c in ref_pieces)
                        )
                else:
                    ref_code_rendered = html.escape(SOURCE_NOT_AVAILABLE_MESSAGE)
                ref_style = "display: block;"

            hint_btn_text = "Hint"
            hint_btn_disabled = "disabled" if hint_level >= 2 else ""
            hint_btn_display = "display: inline-flex;"
            reveal_btn_display = "display: inline-flex;" if is_active_attempt else "display: none;"
            locked_notice_display = "display: none;"
            reveal_btn_text = "Solution Shown" if impl_revealed else "Show solution"

            diff_initial_display = "display: block;" if submitted_code else "display: none;"
            diff_rendered_html = ""
            if submitted_code:
                try:
                    exp_syms = StructuralVerifier.extract_expected_symbols_from_graph(graph_data or {}, m_tier)
                    ver_res = StructuralVerifier().verify(submitted_code, exp_syms)
                    att_grad_method = attempt.get("grading_method") if isinstance(attempt, dict) else getattr(attempt, "grading_method", None)
                    diff_rendered_html = _render_server_diff_html(
                        ver_res,
                        is_verified=(attempt_status == "structurally_verified"),
                        err_msg=ver_res.get("error_message"),
                        grading_method=att_grad_method,
                    )
                except Exception as e:
                    diff_rendered_html = f'<div style="color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;">Verification load error: {html.escape(str(e))}</div>'

            last_run_val = attempt.get("last_run_at") if isinstance(attempt, dict) else getattr(attempt, "last_run_at", None)
            console_initial_display = "display: block;" if (attempt and last_run_val is not None) else "display: none;"
            console_rendered_html = _render_server_console_html(attempt)

            symbols_html = ""
            if m_exports:
                symbols_rendered = ", ".join(m_exports[:10])
                symbols_html = f"""
                <div style="margin-top: 0.65rem; font-size: 0.8125rem; font-family: var(--font-ui); color: var(--text-muted);">
                    <span style="color: var(--text-muted); font-weight: 600;">Key symbols:</span> {sanitize_text(symbols_rendered)}
                </div>
                """

            expected_pills_html = ""
            if m_exports:
                for exp_sym in m_exports:
                    safe_sym = sanitize_text(exp_sym)
                    expected_pills_html += f"""<span class="expected-sym-chip" style="display: inline-flex; align-items: center; gap: 0.25rem; background: var(--panel-raised); border: 1px solid var(--border); padding: 0.15rem 0.45rem; border-radius: 3px; font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted);">&bull; {safe_sym}</span> """
            else:
                expected_pills_html = '<span style="font-size: 0.8125rem; color: var(--text-muted); font-family: var(--font-mono);">Any milestone module functions/classes</span>'

            citations_html = ""
            if m_citations:
                c_items = "".join(f'<div style="margin-bottom: 0.35rem; color: var(--text-muted);">&bull; {sanitize_text(c)}</div>' for c in m_citations)
                citations_html = f"""
                <details style="margin-top: 0.65rem;">
                    <summary style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); cursor: pointer; user-select: none;">
                        <span>&gt; Semantic Citations ({len(m_citations)})</span>
                    </summary>
                    <div style="margin-top: 0.4rem; padding: 0.65rem 0.85rem; background: var(--panel-raised); border-left: 2px solid var(--success); border-radius: 2px; font-family: var(--font-ui); font-size: 0.8125rem; line-height: 1.45;">
                        {c_items}
                    </div>
                </details>
                """

            notes_html = ""
            if m_pedagogical or m_gotchas:
                p_items = "".join(f'<div style="margin-bottom: 0.25rem;">&bull; {render_user_markdown(p)}</div>' for p in m_pedagogical)
                g_items = "".join(f'<div style="margin-bottom: 0.25rem; color: var(--amber);">&bull; {render_user_markdown(g)}</div>' for g in m_gotchas)
                notes_html = f"""
                <div style="margin-top: 0.65rem; padding: 0.65rem 0.85rem; background: var(--panel-raised); border: 1px solid var(--hairline-soft); border-radius: 3px; font-size: 0.8125rem; color: var(--text-muted); line-height: 1.45;">
                    {f'<div style="margin-bottom: 0.35rem;"><span style="font-weight: 600; color: var(--text);">Key Architectural Concept:</span> {p_items}</div>' if p_items else ''}
                    {f'<div><span style="font-weight: 600; color: var(--amber);">Implementation Gotcha:</span> {g_items}</div>' if g_items else ''}
                </div>
                """

            # Read files data
            read_files_data = []
            from app.services.file_content_service import FileContentService, SOURCE_NOT_AVAILABLE_MESSAGE
            if m_files:
                for idx, f_path in enumerate(m_files):
                    f_content = ""
                    has_real_source = False
                    if file_contents:
                        matched = FileContentService.find_matching_file_content(file_contents, f_path)
                        if matched:
                            f_content = matched
                            has_real_source = True

                    if not f_content and graph_data and "nodes" in graph_data:
                        for n in graph_data.get("nodes", []):
                            n_path = n.get("path") or n.get("id") or ""
                            if n_path == f_path or n_path.endswith(f_path) or f_path.endswith(n_path):
                                if n.get("source_code"):
                                    f_content = n.get("source_code")
                                    has_real_source = True
                                    break
                                elif n.get("content"):
                                    f_content = n.get("content")
                                    has_real_source = True
                                    break

                    if not f_content:
                        f_content = SOURCE_NOT_AVAILABLE_MESSAGE
                        has_real_source = False

                    read_files_data.append({
                        "path": f_path,
                        "filename": f_path.replace("\\", "/").split("/")[-1],
                        "content": f_content,
                        "has_real_source": has_real_source,
                    })
            else:
                read_files_data.append({
                    "path": f"milestone_{m_tier}_implementation.py",
                    "filename": f"milestone_{m_tier}_implementation.py",
                    "content": SOURCE_NOT_AVAILABLE_MESSAGE,
                    "has_real_source": False,
                })

            read_file_tabs_html = ""
            read_file_panes_html = ""
            for f_idx, r_file in enumerate(read_files_data):
                active_cls = "active" if f_idx == 0 else ""
                r_pane_display = "block" if f_idx == 0 else "none"
                escaped_f_content = html.escape(r_file["content"])
                f_name_safe = sanitize_text(r_file["filename"])
                f_path_safe = sanitize_text(r_file["path"])

                if len(read_files_data) > 1:
                    tab_bg = "var(--surface-2)" if f_idx == 0 else "transparent"
                    tab_color = "var(--success)" if f_idx == 0 else "var(--text-muted)"
                    tab_border = "var(--teal-border)" if f_idx == 0 else "var(--border)"
                    read_file_tabs_html += f"""
                    <button type="button" id="read-tab-btn-{m_tier}-{f_idx}" class="read-file-tab-btn {active_cls}" onclick="switchMilestoneReadFile({m_tier}, {f_idx})" title="{f_path_safe}" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.25rem 0.6rem; font-family: var(--font-mono); font-size: 0.8125rem; border-radius: 3px; border: 1px solid {tab_border}; background: {tab_bg}; color: {tab_color}; cursor: pointer; transition: all 120ms ease;">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                            <polyline points="13 2 13 9 20 9"></polyline>
                        </svg>
                        {f_name_safe}
                    </button>
                    """

                norm_path = r_file["path"].replace("\\", "/").strip("/")
                is_redacted = bool(redacted_files and (r_file["path"] in redacted_files or norm_path in redacted_files))
                redaction_notice_html = ""
                if is_redacted:
                    redaction_notice_html = """
                    <div class="redaction-notice-bar" style="display: flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.85rem; background: rgba(245, 158, 11, 0.08); border: 1px solid var(--amber-border); border-bottom: none; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--amber);">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                        </svg>
                        <span>Some values were hidden for security</span>
                    </div>
                    """

                source_tag_label = "READ-ONLY SOURCE" if r_file.get("has_real_source", True) else "source files expired"
                lines = r_file["content"].splitlines()
                line_count = len(lines) if lines else 1
                line_numbers_html = "<br>".join(str(i) for i in range(1, line_count + 1))
                read_file_panes_html += f"""
                <div id="read-file-pane-{m_tier}-{f_idx}" class="read-file-pane" style="display: {r_pane_display};">
                    <div style="display: flex; justify-content: space-between; align-items: center; background: #12141a; padding: 0.4rem 0.85rem; border: 1px solid var(--border); border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">
                        <div style="display: flex; align-items: center; gap: 0.4rem;">
                            <span class="chip-dot teal"></span>
                            <span style="color: var(--text-muted); font-weight: 500;">{f_path_safe}</span>
                        </div>
                        <span class="tag" style="font-size: 0.8125rem;">{source_tag_label}</span>
                    </div>
                    {redaction_notice_html}
                    <div class="code-pane-container" style="height: 60vh; max-height: 60vh; overflow: auto; background: #181a20; border: 1px solid var(--border); border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; display: flex;">
                        <div class="line-numbers" style="padding: 1rem 0.65rem; background: #12141a; border-right: 1px solid var(--border); color: var(--text-muted); font-family: var(--font-mono); font-size: 0.8125rem; line-height: 1.5; text-align: right; user-select: none; flex-shrink: 0; min-width: 44px;">
                            {line_numbers_html}
                        </div>
                        <pre class="read-code-pre" style="margin: 0; padding: 1rem; flex: 1; overflow: visible; background: transparent; border: none;"><code id="read-code-content-{m_tier}-{f_idx}" class="language-python hljs" style="background: transparent !important; padding: 0; font-family: var(--font-mono); font-size: 0.8125rem; line-height: 1.5; display: block;">{escaped_f_content}</code></pre>
                    </div>
                </div>
                """

            # Fill files data
            fill_files_data = []
            has_any_scaffold = False
            for f_idx, r_file in enumerate(read_files_data):
                if not r_file.get("has_real_source", True):
                    fill_files_data.append({
                        "path": r_file["path"],
                        "filename": r_file["filename"],
                        "try_it_stub": "",
                        "scaffold_code": r_file["content"],
                        "has_scaffold": False,
                        "blanked_functions": [],
                        "blanked_count": 0,
                        "reason": "The original source for this file isn't available for this job.",
                    })
                    continue

                norm_path = r_file["path"].replace("\\", "/").strip("/")
                f_is_redacted = bool(redacted_files and (r_file["path"] in redacted_files or norm_path in redacted_files))

                s_res = ScaffoldGenerator.generate_scaffold(
                    code=r_file["content"],
                    language="python",
                    file_path=r_file["path"],
                    is_redacted=f_is_redacted,
                )
                try_it_stub = ScaffoldGenerator.generate_try_it_stub(
                    code=r_file["content"],
                    language="python",
                    file_path=r_file["path"],
                )
                if s_res.get("has_scaffold", False):
                    has_any_scaffold = True
                fill_files_data.append({
                    "path": r_file["path"],
                    "filename": r_file["filename"],
                    "try_it_stub": try_it_stub,
                    "scaffold_code": s_res.get("scaffold_code", r_file["content"]),
                    "has_scaffold": s_res.get("has_scaffold", False),
                    "blanked_functions": s_res.get("blanked_functions", []),
                    "blanked_count": s_res.get("blanked_count", 0),
                    "reason": s_res.get("reason"),
                })

            all_fill_files_map[m_tier] = fill_files_data

            has_any_real_source = any(r.get("has_real_source", False) for r in read_files_data)
            guess_disabled_banner_html = ""
            btn_run_disabled = ""
            btn_submit_disabled = ""
            if not has_any_real_source:
                guess_disabled_banner_html = """
                <div class="guess-disabled-banner" style="margin-bottom: 0.85rem; padding: 0.75rem 1rem; background: rgba(245, 158, 11, 0.08); border-left: 3px solid var(--amber); border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem; line-height: 1.45; color: var(--amber);">
                    <span>⚠️</span> <strong>Try it Disabled:</strong> Reference source files are not available for this milestone.
                </div>
                """
                btn_submit_disabled = 'disabled title="Reference source unavailable" style="cursor: not-allowed; opacity: 0.45;"'

            grading_method, _ = GradingEngine().determine_grading_tier(job, m_tier, graph_data or {})
            requires_execution = grading_method in ("real_tests", "expected_output")

            btn_run_fill_disabled = ""
            btn_submit_fill_disabled = ""
            btn_submit_label = "Check answer"
            btn_submit_fill_label = "Check answer"
            run_note_html = ""
            submit_note_html = ""
            submit_fill_note_html = ""

            if not sandbox_enabled:
                btn_run_disabled = 'disabled title="Code execution is turned off on this demo" style="display: none;"'
                btn_run_fill_disabled = 'disabled title="Code execution is turned off on this demo" style="display: none;"'
                run_note_html = ""
                submit_fill_note_html = '<div class="demo-submit-note" style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.25rem;">No points are awarded on this demo.</div>'

                if requires_execution:
                    btn_submit_disabled = 'disabled title="Grading this milestone needs code execution, which is off on this demo" style="cursor: not-allowed; opacity: 0.5;"'
                    submit_note_html = '<div class="demo-submit-note" style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.25rem;">Grading this milestone needs code execution, which is off on this demo.</div>'
                else:
                    btn_submit_label = "Check structure"
                    submit_note_html = '<div class="demo-submit-note" style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.25rem;">Structure check only. No points are awarded on this demo.</div>'
                    if not has_any_real_source:
                        btn_submit_disabled = 'disabled title="Reference source unavailable" style="cursor: not-allowed; opacity: 0.45;"'

            starter_code = ""
            if fill_files_data and fill_files_data[0].get("has_real_source", True):
                starter_code = fill_files_data[0].get("try_it_stub", "")
            active_editor_code = submitted_code if submitted_code else starter_code
            escaped_code = html.escape(active_editor_code)

            hints_unlocked_fill_note = "Hints unlocked &bull; Only blanked functions evaluated" if hint_level > 0 else "Only blanked functions evaluated"

            starter_notice_display = "display: flex;" if (fill_files_data and not fill_files_data[0].get("has_scaffold", False) and not submitted_code) else "display: none;"
            starter_unavailable_notice_html = f"""
            <div id="starter-unavailable-notice-{m_tier}" class="starter-unavailable-notice" style="{starter_notice_display}align-items: center; gap: 0.4rem; margin-bottom: 0.65rem; padding: 0.6rem 0.85rem; background: rgba(245, 158, 11, 0.08); border-left: 3px solid var(--amber); border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">
                <span>ℹ️</span> <strong>Starter code isn't available for this file.</strong>
            </div>
            """

            first_target_file = sanitize_text(m_files[0]) if m_files else f"milestone_{m_tier}.py"
            role_context = render_user_markdown(m_role_raw) if m_role_raw else (render_user_markdown(m_title_raw) if m_title_raw else f"Milestone {m_tier}")

            guess_file_tabs_html = ""
            for f_idx, g_file in enumerate(m_files):
                active_cls = "active" if f_idx == 0 else ""
                f_path_safe = sanitize_text(g_file)
                f_name_safe = sanitize_text(g_file.replace("\\", "/").split("/")[-1])
                tab_bg = "var(--surface-2)" if f_idx == 0 else "transparent"
                tab_color = "var(--accent)" if f_idx == 0 else "var(--text-muted)"
                tab_border = "var(--brass-border)" if f_idx == 0 else "var(--border)"
                guess_file_tabs_html += f"""
                <button type="button" id="guess-tab-btn-{m_tier}-{f_idx}" class="guess-file-tab-btn {active_cls}" onclick="switchMilestoneGuessFile({m_tier}, {f_idx}, '{f_path_safe}')" title="{f_path_safe}" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.25rem 0.6rem; font-family: var(--font-mono); font-size: 0.8125rem; border-radius: 3px; border: 1px solid {tab_border}; background: {tab_bg}; color: {tab_color}; cursor: pointer; transition: all 120ms ease;">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                        <polyline points="13 2 13 9 20 9"></polyline>
                    </svg>
                    {f_name_safe}
                </button>
                """

            guess_file_picker_container_html = ""
            if len(m_files) > 1:
                guess_file_picker_container_html = f"""
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap;">
                    <span style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">Target File:</span>
                    <div id="guess-file-tabs-{m_tier}" style="display: flex; gap: 0.35rem; flex-wrap: wrap;">
                        {guess_file_tabs_html}
                    </div>
                </div>
                """

            example_io_data = m.get("example_io") or m.get("test_cases") or m.get("examples")
            example_io_html = ""
            if example_io_data:
                if isinstance(example_io_data, list):
                    ex_rendered = "".join(f'<div style="font-family: var(--font-mono); font-size: 0.8125rem; background: var(--surface-2); padding: 0.4rem 0.6rem; border-radius: 3px; border: 1px solid var(--hairline-soft); margin-top: 0.25rem;">{sanitize_text(str(ex))}</div>' for ex in example_io_data)
                elif isinstance(example_io_data, dict):
                    ex_rendered = f'<pre style="font-family: var(--font-mono); font-size: 0.8125rem; background: var(--surface-2); padding: 0.4rem 0.6rem; border-radius: 3px; border: 1px solid var(--hairline-soft); margin-top: 0.25rem; overflow-x: auto;">{sanitize_text(json.dumps(example_io_data, indent=2))}</pre>'
                else:
                    ex_rendered = f'<div style="font-family: var(--font-mono); font-size: 0.8125rem; background: var(--surface-2); padding: 0.4rem 0.6rem; border-radius: 3px; border: 1px solid var(--hairline-soft); margin-top: 0.25rem;">{sanitize_text(str(example_io_data))}</div>'
                example_io_html = f"""
                <div class="brief-example-io-section" style="margin-bottom: 0.65rem;">
                    <div style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.2rem;">
                        Example Input / Output:
                    </div>
                    <div style="margin-top: 0.25rem;">
                        {ex_rendered}
                    </div>
                </div>
                """

            first_fill_file = fill_files_data[0]
            first_fill_name = sanitize_text(first_fill_file["filename"])
            first_fill_path = sanitize_text(first_fill_file["path"])
            escaped_scaffold_code = html.escape(first_fill_file["scaffold_code"])

            fill_file_tabs_html = ""
            for f_idx, f_file in enumerate(fill_files_data):
                active_cls = "active" if f_idx == 0 else ""
                f_path_safe = sanitize_text(f_file["path"])
                f_name_safe = sanitize_text(f_file["filename"])
                tab_bg = "var(--surface-2)" if f_idx == 0 else "transparent"
                tab_color = "var(--success)" if f_idx == 0 else "var(--text-muted)"
                tab_border = "var(--teal-border)" if f_idx == 0 else "var(--border)"
                no_blanks_tag = "" if f_file["has_scaffold"] else ' <span class="tag" style="font-size: 0.8125rem; padding: 0 0.2rem;">No blanks</span>'
                fill_file_tabs_html += f"""
                <button type="button" id="fill-tab-btn-{m_tier}-{f_idx}" class="fill-file-tab-btn {active_cls}" onclick="switchMilestoneFillFile({m_tier}, {f_idx}, '{f_path_safe}')" title="{f_path_safe}" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.25rem 0.6rem; font-family: var(--font-mono); font-size: 0.8125rem; border-radius: 3px; border: 1px solid {tab_border}; background: {tab_bg}; color: {tab_color}; cursor: pointer; transition: all 120ms ease;">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                        <polyline points="13 2 13 9 20 9"></polyline>
                    </svg>
                    {f_name_safe}{no_blanks_tag}
                </button>
                """

            fill_file_picker_container_html = ""
            if len(fill_files_data) > 1:
                fill_file_picker_container_html = f"""
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap;">
                    <span style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">Target File:</span>
                    <div id="fill-file-tabs-{m_tier}" style="display: flex; gap: 0.35rem; flex-wrap: wrap;">
                        {fill_file_tabs_html}
                    </div>
                </div>
                """

            initial_blanked = first_fill_file["blanked_functions"]
            fill_chips_html = _render_grouped_fill_chips(initial_blanked, first_fill_file.get("reason"))

            if has_any_scaffold:
                fill_mode_btn_html = f"""
                <button type="button" id="mode-btn-fill-{m_tier}" class="milestone-mode-tab-btn" onclick="switchMilestoneMode({m_tier}, 'fill')" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.75rem; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 500; border-radius: 3px; border: none; cursor: pointer; transition: all 120ms ease; background: transparent; color: var(--text-muted);">
                    <span>🧩</span> Fill the gaps
                </button>
                """
            else:
                disable_note = html.escape(first_fill_file.get("reason") or "File contains only constants, type declarations, or exports with no function bodies to scaffold.")
                fill_mode_btn_html = f"""
                <button type="button" id="mode-btn-fill-{m_tier}" class="milestone-mode-tab-btn disabled" disabled title="{disable_note}" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.75rem; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 500; border-radius: 3px; border: none; cursor: not-allowed; opacity: 0.45; background: transparent; color: var(--text-muted);">
                    <span>🧩</span> Fill the gaps <span class="tag" style="font-size: 0.8125rem; padding: 0.05rem 0.3rem;">No Blanks</span>
                </button>
                """

            read_file_picker_container_html = ""
            if len(read_files_data) > 1:
                read_file_picker_container_html = f"""
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.65rem; flex-wrap: wrap;">
                    <span style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); ">Target File:</span>
                    <div id="read-file-tabs-{m_tier}" style="display: flex; gap: 0.35rem; flex-wrap: wrap;">
                        {read_file_tabs_html}
                    </div>
                </div>
                """

            reviewed_btn_text = "Reviewed &amp; Verified ✓" if attempt_status == "structurally_verified" else "Mark as Reviewed"
            read_intro_label = "Architecture Implementation" if is_showcase else "Read through this milestone's actual implementation"

            # Check your understanding quiz items for this milestone
            m_quiz_items = _build_milestone_quiz_items(m, m_idx, quiz_data, milestones_data)
            att_details = {}
            if attempt:
                gd = attempt.get("grading_details_json") if isinstance(attempt, dict) else getattr(attempt, "grading_details_json", None)
                if isinstance(gd, str):
                    try:
                        att_details = json.loads(gd) or {}
                    except Exception:
                        att_details = {}
                elif isinstance(gd, dict):
                    att_details = gd
            m_quiz_card_html = _render_milestone_quiz_card(job_id, m_tier, m_quiz_items, grading_details=att_details)

            if is_showcase:
                panes_html += f"""
            <div class="milestone-pane{' active' if is_pane_open else ''}" id="milestone-pane-{m_tier}" style="display: {pane_display};" data-tier="{m_tier}">
                <!-- Header -->
                <div class="milestone-pane-header" style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1.25rem 1.55rem; margin-bottom: 1.25rem; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 0.5rem;">
                        <div>
                            <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                                <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); font-weight: 600; ">{track_label.upper()} {display_id}</span>
                                <span style="color: var(--border);">/</span>
                                <h3 style="font-size: 1.25rem; font-weight: 600; color: var(--text); margin: 0; font-family: var(--font-ui);">{m_title}</h3>
                            </div>
                            {f'<div class="milestone-role" style="font-size: 0.8125rem; font-style: italic; color: var(--text-muted); margin-top: 0.2rem;">{m_role}</div>' if m_role else ''}
                        </div>
                        <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                            {status_badge_html}
                            {conf_badge_html}
                        </div>
                    </div>

                    <!-- One-sentence Goal -->
                    {f'<div class="milestone-goal-box" style="margin: 0.75rem 0 0.5rem 0; padding: 0.65rem 0.9rem; background: var(--panel-raised); border-left: 3px solid var(--success); border-radius: 3px; font-size: 0.825rem; color: var(--text-muted); line-height: 1.5;"><strong style="color: var(--text); font-family: var(--font-ui); font-size: 0.8125rem; margin-right: 0.35rem;">Goal:</strong> {m_brief_obj}</div>' if m_brief_obj else ''}

                    {f'<div style="font-size: 0.8125rem; color: var(--text-muted); font-family: var(--font-ui); margin-top: 0.4rem;"><span style="color: var(--text-muted); font-weight: 600;">Composition:</span> {m_comp}</div>' if m_comp else ''}
                    {symbols_html}
                    {citations_html}
                    {notes_html}
                </div>

                <!-- Showcase Architecture Implementation (Read-only) -->
                <div class="milestone-editor-wrapper" id="milestone-editor-card-{m_tier}" style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1.25rem 1.55rem; margin-bottom: 1.25rem; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
                    <div id="workspace-read-{m_tier}" class="milestone-mode-workspace read-mode" style="display: block;">
                        <div style="font-family: \'IBM Plex Sans\', sans-serif; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.4rem;">
                            <span style="color: var(--success); font-weight: 600;">ℹ</span> Architecture Implementation
                        </div>
                        {read_file_picker_container_html}
                        <div class="read-file-panes-container" style="border-radius: 4px; overflow: hidden;">
                            {read_file_panes_html}
                        </div>
                    </div>
                </div>

                <!-- Final Step: Check your understanding Quiz -->
                {m_quiz_card_html}
            </div>
            """
                continue

            panes_html += f"""
            <div class="milestone-pane{' active' if is_pane_open else ''}" id="milestone-pane-{m_tier}" style="display: {pane_display};" data-tier="{m_tier}">
                <!-- Header -->
                <div class="milestone-pane-header" style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1.25rem 1.55rem; margin-bottom: 1.25rem; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 0.5rem;">
                        <div>
                            <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                                <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); font-weight: 600; ">{track_label.upper()} {display_id}</span>
                                <span style="color: var(--border);">/</span>
                                <h3 style="font-size: 1.25rem; font-weight: 600; color: var(--text); margin: 0; font-family: var(--font-ui);">{m_title}</h3>
                            </div>
                            {f'<div class="milestone-role" style="font-size: 0.8125rem; font-style: italic; color: var(--text-muted); margin-top: 0.2rem;">{m_role}</div>' if m_role else ''}
                        </div>
                        <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                            {status_badge_html}
                            {conf_badge_html}
                            <button type="button" id="btn-start-here-{m_tier}" class="btn btn-sm btn-primary btn-start-here" onclick="startHereMilestone({m_tier})" style="display: {start_here_display}; align-items: center; gap: 0.4rem; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600;">
                                <span>🚀</span> Start here
                            </button>
                            <button type="button" id="btn-next-milestone-{m_tier}" class="btn btn-sm btn-secondary btn-next-milestone" onclick="goToNextMilestone({m_tier})" style="display: {next_btn_display}; align-items: center; gap: 0.4rem; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600;">
                                Next milestone ➔
                            </button>
                        </div>
                    </div>

                    <!-- One-sentence Goal -->
                    {f'<div class="milestone-goal-box" style="margin: 0.75rem 0 0.5rem 0; padding: 0.65rem 0.9rem; background: var(--panel-raised); border-left: 3px solid var(--success); border-radius: 3px; font-size: 0.825rem; color: var(--text-muted); line-height: 1.5;"><strong style="color: var(--text); font-family: var(--font-ui); font-size: 0.8125rem; margin-right: 0.35rem;">Goal:</strong> {m_brief_obj}</div>' if m_brief_obj else ''}

                    {f'<div style="font-size: 0.8125rem; color: var(--text-muted); font-family: var(--font-ui); margin-top: 0.4rem;"><span style="color: var(--text-muted); font-weight: 600;">Composition:</span> {m_comp}</div>' if m_comp else ''}
                    {symbols_html}
                    {citations_html}
                    {notes_html}
                </div>

                <!-- Milestone Workspace Surface -->
                <div class="milestone-editor-wrapper" id="milestone-editor-card-{m_tier}" style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 1.25rem 1.55rem; margin-bottom: 1.25rem; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
                    <!-- Practice Mode Switcher (Read it, Fill the gaps, Try it) -->
                    <div class="milestone-mode-switcher" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; border-bottom: 1px solid var(--hairline-soft); padding-bottom: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                        <div style="display: flex; align-items: center; gap: 0.35rem; background: var(--panel-raised); border: 1px solid var(--border); border-radius: 4px; padding: 0.2rem;">
                            <button type="button" id="mode-btn-read-{m_tier}" class="milestone-mode-tab-btn" onclick="switchMilestoneMode({m_tier}, 'read')" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.75rem; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 500; border-radius: 3px; border: none; cursor: pointer; transition: all 120ms ease; background: transparent; color: var(--text-muted);">
                                <span>📖</span> Read it
                            </button>
                            {fill_mode_btn_html}
                            <button type="button" id="mode-btn-guess-{m_tier}" class="milestone-mode-tab-btn active" onclick="switchMilestoneMode({m_tier}, 'guess')" style="display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.75rem; font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; border-radius: 3px; border: none; cursor: pointer; transition: all 120ms ease; background: var(--surface-2); color: var(--accent); box-shadow: 0 1px 3px rgba(0,0,0,0.2);">
                                <span>✏️</span> Try it
                            </button>
                        </div>
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">
                            Practice mode
                        </div>
                    </div>

                    <!-- Mode 1 Workspace: Try it (Guess Mode) -->
                    <div id="workspace-guess-{m_tier}" class="milestone-mode-workspace guess-mode" style="display: block;">
                        {guess_disabled_banner_html}
                        <div class="guess-instruction-banner" style="margin-bottom: 0.85rem; padding: 0.75rem 1rem; background: var(--panel-raised); border-left: 3px solid var(--accent); border-radius: 3px; font-family: 'IBM Plex Sans', sans-serif; font-size: 0.825rem; line-height: 1.5; color: var(--text-muted);">
                            <div style="font-weight: 600; color: var(--text); margin-bottom: 0.2rem; display: flex; align-items: center; gap: 0.35rem;">
                                <span>🎯</span> <strong>Task Instructions:</strong>
                            </div>
                            <div>
                                Try to reconstruct <span class="mono" id="guess-target-filename-{m_tier}" style="color: var(--accent); font-weight: 600; font-size: 0.8125rem; background: var(--surface-2); padding: 0.1rem 0.4rem; border-radius: 3px; border: 1px solid var(--border);">{first_target_file}</span> based on expected contracts ({role_context}) before seeing the solution.
                            </div>
                        </div>

                        {guess_file_picker_container_html}

                        <div class="milestone-brief-card" style="margin-bottom: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border: 1px solid var(--border); border-radius: 4px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem; border-bottom: 1px solid var(--hairline-soft); padding-bottom: 0.45rem;">
                                <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--accent); display: flex; align-items: center; gap: 0.4rem;">
                                    <span>📋</span> {track_label} {display_id} Structured Brief
                                </div>
                                <span class="tag" style="font-size: 0.8125rem;">Sourced from Codebase</span>
                            </div>

                            <div class="brief-objective-section" style="margin-bottom: 0.65rem;">
                                <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.2rem;">
                                    Objective:
                                </div>
                                {f'<div style="font-size: 0.825rem; color: var(--text-muted); line-height: 1.5;">{m_brief_obj}</div>' if m_brief_obj else '<div style="font-size: 0.8125rem; color: var(--text-muted); font-style: italic;">No objective text available for this milestone.</div>'}
                            </div>

                            <div class="brief-constraints-section" style="margin-bottom: 0.65rem;">
                                <div style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.35rem;">
                                    Constraints / Expected Functions &amp; Signatures:
                                </div>
                                <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">
                                    {expected_pills_html}
                                </div>
                            </div>

                            {example_io_html}
                        </div>

                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem; flex-wrap: wrap; gap: 0.5rem;">
                            <div style="display: flex; align-items: center; gap: 0.5rem;">
                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent);">
                                    <polyline points="16 18 22 12 16 6"></polyline>
                                    <polyline points="8 6 2 12 8 18"></polyline>
                                </svg>
                                <span style="font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: var(--text); ">
                                    Milestone {m_tier} Implementation Workspace
                                </span>
                            </div>
                            <span class="tag" style="font-size: 0.8125rem;">Structure &amp; Execution Verified</span>
                        </div>

                        {starter_unavailable_notice_html}

                        <div class="editor-surface-container" style="border: 1px solid var(--border); border-radius: 4px; overflow: hidden; background: #282a36; height: 60vh; max-height: 60vh;">
                            <textarea id="code-editor-{m_tier}" name="code_editor_{m_tier}" style="display: none;">{escaped_code}</textarea>
                        </div>

                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-top: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                            <div style="display: flex; align-items: flex-start; gap: 0.5rem; flex-wrap: wrap;">
                                <div style="display: flex; flex-direction: column; align-items: flex-start;">
                                    <button type="button" id="btn-run-{m_tier}" onclick="runMilestoneCode('{job_id}', {m_tier})" {btn_run_disabled} class="btn btn-sm btn-secondary" style="font-family: var(--font-ui); border-color: var(--brass-border); color: var(--accent);">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                                            <polygon points="5 3 19 12 5 21 5 3"></polygon>
                                        </svg>
                                        Run Code
                                    </button>
                                    {run_note_html}
                                </div>

                                <div style="display: flex; flex-direction: column; align-items: flex-start;">
                                    <button type="button" id="btn-submit-{m_tier}" onclick="submitMilestoneCode('{job_id}', {m_tier})" {btn_submit_disabled} class="btn btn-sm btn-primary" style="font-family: var(--font-ui); ">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <polyline points="20 6 9 17 4 12"></polyline>
                                        </svg>
                                        {btn_submit_label}
                                    </button>
                                    {submit_note_html}
                                </div>

                                <button type="button" id="btn-hint-{m_tier}" data-hint-level="{hint_level}" onclick="openHintConfirmModal('{job_id}', {m_tier})" class="btn btn-sm btn-secondary" style="{hint_btn_display} font-family: var(--font-ui); font-size: 0.8125rem; border-color: var(--brass-border); color: var(--accent);" {hint_btn_disabled}>
                                    💡 <span id="btn-hint-text-{m_tier}">{hint_btn_text}</span>
                                </button>

                                <button type="button" id="btn-reveal-{m_tier}" onclick="openRevealConfirmModal('{job_id}', {m_tier})" class="btn btn-sm btn-ghost" style="{reveal_btn_display} font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); text-decoration: underline;">
                                    <span id="btn-reveal-text-{m_tier}">{reveal_btn_text}</span>
                                </button>

                                <span id="hint-locked-notice-{m_tier}" style="{locked_notice_display} font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); align-items: center; gap: 0.3rem;">
                                    🔒 Submit first attempt to unlock hints
                                </span>
                            </div>
                        </div>

                        <div id="console-output-panel-{m_tier}" class="console-output-panel" style="{console_initial_display} margin-top: 0.85rem; padding: 0.85rem 1rem; background: #0e1015; border: 1px solid var(--hairline-soft); border-radius: 4px;">
                            {console_rendered_html}
                        </div>

                        <div id="diff-output-panel-{m_tier}" class="diff-output-panel" style="{diff_initial_display} margin-top: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border: 1px solid var(--border); border-radius: 4px;">
                            {diff_rendered_html}
                        </div>

                        <div id="hint-confirm-box-{m_tier}" class="hint-confirm-box" style="display: none; margin-top: 0.85rem; padding: 1rem 1.25rem; background: var(--surface-2); border: 1px solid var(--brass-border); border-radius: 4px;">
                            <p id="hint-confirm-text-{m_tier}" style="font-size: 0.875rem; color: var(--text); line-height: 1.5; margin-bottom: 1rem;">
                                {HintEngine.SELECTED_HINT_1_CONFIRM}
                            </p>
                            <div style="display: flex; align-items: center; gap: 0.65rem;">
                                <button type="button" class="btn btn-sm btn-secondary" onclick="cancelHintConfirm({m_tier})">I'll Keep Trying</button>
                                <button type="button" id="btn-confirm-hint-action-{m_tier}" class="btn btn-sm btn-primary" onclick="confirmAndFetchHint('{job_id}', {m_tier})">Yes, Reveal Hint</button>
                            </div>
                        </div>

                        <div id="reveal-confirm-box-{m_tier}" class="reveal-confirm-box" style="display: none; margin-top: 0.85rem; padding: 1rem 1.25rem; background: var(--surface-2); border: 1px solid var(--crimson); border-radius: 4px;">
                            <p style="font-size: 0.875rem; color: var(--text); line-height: 1.5; margin-bottom: 1rem;">
                                Show the solution? This ends your attempt.
                            </p>
                            <div style="display: flex; align-items: center; gap: 0.65rem;">
                                <button type="button" class="btn btn-sm btn-secondary" onclick="cancelRevealConfirm({m_tier})">Cancel</button>
                                <button type="button" id="btn-confirm-reveal-action-{m_tier}" class="btn btn-sm btn-danger" onclick="confirmAndRevealImplementation('{job_id}', {m_tier})">Show</button>
                            </div>
                        </div>

                        <div id="hint-1-panel-{m_tier}" class="hint-panel" style="{h1_style} margin-top: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border-left: 3px solid var(--accent); border-radius: 2px;">
                            <div id="hint-1-text-{m_tier}" style="font-size: 0.8125rem; color: var(--text); line-height: 1.55;">{sanitize_text(h1_text)}</div>
                        </div>

                        <div id="hint-2-panel-{m_tier}" class="hint-panel" style="{h2_style} margin-top: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border-left: 3px solid var(--amber); border-radius: 2px;">
                            <div id="hint-2-text-{m_tier}" style="font-size: 0.8125rem; color: var(--text); line-height: 1.55;">{sanitize_text(h2_text)}</div>
                        </div>

                        <div id="reference-panel-{m_tier}" class="reference-panel" style="{ref_style} margin-top: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border-left: 3px solid var(--success); border-radius: 2px;">
                            <pre style="background: #181a20; padding: 0.75rem 1rem; border-radius: 4px; overflow-x: auto; border: 1px solid var(--border); margin: 0;"><code id="reference-code-{m_tier}" class="mono" style="font-size: 0.8125rem; color: var(--text);">{ref_code_rendered}</code></pre>
                        </div>
                    </div>

                    <!-- Mode 2 Workspace: Fill the gaps (Fill Mode) -->
                    <div id="workspace-fill-{m_tier}" class="milestone-mode-workspace fill-mode" style="display: none;">
                        <div class="fill-instruction-banner" style="margin-bottom: 0.85rem; padding: 0.75rem 1rem; background: var(--panel-raised); border-left: 3px solid var(--success); border-radius: 3px; font-family: 'IBM Plex Sans', sans-serif; font-size: 0.825rem; line-height: 1.5; color: var(--text-muted);">
                            <div style="font-weight: 600; color: var(--text); margin-bottom: 0.2rem; display: flex; align-items: center; gap: 0.35rem;">
                                <span>🧩</span> <strong>Fill the gaps Instructions:</strong>
                            </div>
                            <div>
                                Fill in missing function/method implementations for <span class="mono" id="fill-target-filename-{m_tier}" style="color: var(--success); font-weight: 600; font-size: 0.8125rem; background: var(--surface-2); padding: 0.1rem 0.4rem; border-radius: 3px; border: 1px solid var(--border);">{first_fill_name}</span>.
                            </div>
                        </div>

                        {fill_file_picker_container_html}

                        <div style="margin-bottom: 0.75rem; background: var(--panel-raised); border: 1px solid var(--hairline-soft); border-radius: 4px; padding: 0.6rem 0.85rem;">
                            <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.35rem; font-weight: 600; ">
                                Functions To Implement:
                            </div>
                            <div id="fill-blanked-chips-{m_tier}" style="display: flex; flex-direction: column; gap: 0.35rem;">
                                {fill_chips_html}
                            </div>
                        </div>

                        <div class="editor-surface-container" style="border: 1px solid var(--border); border-radius: 4px; overflow: hidden; background: #282a36; height: 60vh; max-height: 60vh;">
                            <textarea id="code-editor-fill-{m_tier}" name="code_editor_fill_{m_tier}" style="display: none;">{escaped_scaffold_code}</textarea>
                        </div>

                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-top: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                            <div style="display: flex; align-items: flex-start; gap: 0.5rem; flex-wrap: wrap;">
                                <div style="display: flex; flex-direction: column; align-items: flex-start;">
                                    <button type="button" id="btn-run-fill-{m_tier}" onclick="runMilestoneFillCode('{job_id}', {m_tier})" {btn_run_fill_disabled} class="btn btn-sm btn-secondary" style="font-family: var(--font-ui); border-color: var(--teal-border); color: var(--success);">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                                            <polygon points="5 3 19 12 5 21 5 3"></polygon>
                                        </svg>
                                        Run Code
                                    </button>
                                    {run_note_html}
                                </div>

                                <div style="display: flex; flex-direction: column; align-items: flex-start;">
                                    <button type="button" id="btn-submit-fill-{m_tier}" onclick="submitMilestoneFillCode('{job_id}', {m_tier})" {btn_submit_fill_disabled} class="btn btn-sm btn-primary" style="font-family: var(--font-ui); background: var(--success); color: #0f172a; border-color: var(--teal-border);">
                                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <polyline points="20 6 9 17 4 12"></polyline>
                                        </svg>
                                        {btn_submit_fill_label}
                                    </button>
                                    {submit_fill_note_html}
                                </div>

                                <button type="button" id="btn-hint-fill-{m_tier}" data-hint-level="{hint_level}" onclick="openHintConfirmModal('{job_id}', {m_tier}, 'fill')" class="btn btn-sm btn-secondary" style="display: inline-flex; font-family: var(--font-ui); font-size: 0.8125rem; border-color: var(--brass-border); color: var(--accent);">
                                    💡 <span id="btn-hint-fill-text-{m_tier}">Request Architectural Hint</span>
                                </button>

                                <button type="button" id="btn-reveal-fill-{m_tier}" onclick="openRevealConfirmModal('{job_id}', {m_tier}, 'fill')" class="btn btn-sm btn-ghost" style="display: inline-flex; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); text-decoration: underline;">
                                    <span id="btn-reveal-fill-text-{m_tier}">{reveal_btn_text}</span>
                                </button>
                            </div>
                        </div>

                        <div id="console-output-panel-fill-{m_tier}" class="console-output-panel" style="display: none; margin-top: 0.85rem; padding: 0.85rem 1rem; background: #0e1015; border: 1px solid var(--hairline-soft); border-radius: 4px;"></div>
                        <div id="diff-output-panel-fill-{m_tier}" class="diff-output-panel" style="display: none; margin-top: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border: 1px solid var(--border); border-radius: 4px;"></div>
                    </div>

                    <!-- Mode 3 Workspace: Read it (Read-Only Real File Implementation View) -->
                    <div id="workspace-read-{m_tier}" class="milestone-mode-workspace read-mode" style="display: none;">
                        <div style="font-family: 'IBM Plex Sans', sans-serif; font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.4rem;">
                            <span style="color: var(--success); font-weight: 600;">ℹ</span> {read_intro_label}
                        </div>

                        {read_file_picker_container_html}

                        <div class="read-file-panes-container" style="border-radius: 4px; overflow: hidden;">
                            {read_file_panes_html}
                        </div>

                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.85rem; flex-wrap: wrap; gap: 0.5rem;">
                            <button type="button" id="btn-review-{m_tier}" onclick="markMilestoneAsReviewed('{job_id}', {m_tier})" class="btn btn-sm" style="font-family: var(--font-ui); display: inline-flex; align-items: center; gap: 0.4rem; background: var(--success); color: #0f172a; font-weight: 600; border: 1px solid var(--teal-border); border-radius: 4px; padding: 0.35rem 0.85rem; cursor: pointer;">
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                    <polyline points="20 6 9 17 4 12"></polyline>
                                </svg>
                                <span id="btn-review-text-{m_tier}">{reviewed_btn_text}</span>
                            </button>
                            <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">Read-only exploration &bull; No code grading required</span>
                        </div>
                    </div>
                </div>

                <!-- Final Step: Check your understanding Quiz -->
                {m_quiz_card_html}
            </div>
            """

        milestones_spine_html = f"""
        <div class="stratum-card" id="section-milestones" style="margin-bottom: 2rem;">
            <div class="card-header" style="margin-bottom: 1.25rem;">
                <div>
                    <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                        Section 03: Guided Architectural Milestones
                    </div>
                    <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Guided Flow Walkthrough</h2>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    {narration_badge_html}
                    <span class="chip"><span class="chip-dot brass"></span> {len(milestones_data)} Milestones</span>
                </div>
            </div>
            <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 1.5rem; line-height: 1.5;">
                Follow the guided pedagogical progression from leaf primitives upwards to entry-point orchestration.
            </p>
            <div class="milestones-guided-flow" id="milestones-guided-flow">
                {progress_rail_html}
                <div class="milestone-guided-main" id="milestone-guided-main">
                    {panes_html}
                </div>
            </div>
        </div>
        """
    else:
        milestones_spine_html = f"""
        <div class="stratum-card" id="section-milestones" style="margin-bottom: 2rem;">
            <div class="card-header">
                <div>
                    <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                        Section 03: Guided Architectural Milestones
                    </div>
                    <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Guided Flow Walkthrough</h2>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    {narration_badge_html}
                </div>
            </div>
            <p style="color: var(--text-muted); font-size: 0.85rem;">No structured milestone steps found in this report.</p>
        </div>
        """

    # -------------------------------------------------------------
    # 4. Codebase Mastery Quiz Section (Main Tab route listing all quizzes)
    # -------------------------------------------------------------
    quiz_html = ""
    if milestones_data:
        quiz_cards_rendered = ""
        for m_idx, m in enumerate(milestones_data, start=1):
            try:
                m_tier = int(m.get("tier", m_idx))
            except Exception:
                m_tier = m_idx
            q_items = _build_milestone_quiz_items(m, m_idx, quiz_data, milestones_data)
            quiz_cards_rendered += _render_milestone_quiz_card(job_id, m_tier, q_items)

        quiz_html = f"""
        <div class="stratum-card" id="section-quiz" style="margin-bottom: 2rem;">
            <div class="card-header">
                <div>
                    <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                        Section 04: Interactive Validation
                    </div>
                    <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Codebase Architecture Comprehension Quiz &bull; All Milestone Quizzes</h2>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="chip"><span class="chip-dot teal"></span> {len(milestones_data) * 3} Validation Questions</span>
                </div>
            </div>
            <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 1.25rem; line-height: 1.5;">
                All Milestone Quizzes &bull; Test and verify architectural comprehension of key contracts and boundary transitions across all decomposed tiers.
            </p>
            <div class="quiz-all-milestones-container">
                {quiz_cards_rendered}
            </div>
        </div>
        """
    elif quiz_data and quiz_data.get("questions"):
        questions = quiz_data.get("questions", [])
        quiz_cards_rendered = _render_milestone_quiz_card(job_id, 1, questions)
        quiz_html = f"""
        <div class="stratum-card" id="section-quiz" style="margin-bottom: 2rem;">
            <div class="card-header">
                <div>
                    <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                        Section 04: Interactive Validation
                    </div>
                    <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Codebase Architecture Comprehension Quiz &bull; All Milestone Quizzes</h2>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="chip"><span class="chip-dot teal"></span> {len(questions)} Validation Questions</span>
                </div>
            </div>
            <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 1.25rem; line-height: 1.5;">
                All Milestone Quizzes &bull; Test and verify architectural comprehension of key contracts and boundary transitions across all decomposed tiers.
            </p>
            <div class="quiz-all-milestones-container">
                {quiz_cards_rendered}
            </div>
        </div>
        """
    else:
        quiz_html = f"""
        <div class="stratum-card" id="section-quiz" style="margin-bottom: 2rem;">
            <div class="card-header">
                <div>
                    <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                        Section 04: Interactive Validation
                    </div>
                    <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Codebase Architecture Comprehension Quiz &bull; All Milestone Quizzes</h2>
                </div>
            </div>
            <p style="color: var(--text-muted); font-size: 0.85rem;">No quiz questions available for this analysis report.</p>
        </div>
        """

    # -------------------------------------------------------------
    # 5. Full Raw Markdown Transcript - removed in redesign (available via Export as Markdown)
    # -------------------------------------------------------------
    raw_markdown_drawer = ""

    # Extra Interactive Scripts & Graph Logic
    graph_nodes_json = _safe_script_json_dumps(nodes)
    graph_edges_json = _safe_script_json_dumps(edges)
    fill_files_map_json = _safe_script_json_dumps(all_fill_files_map)
    sandbox_banner_js_val = _safe_script_json_dumps(SANDBOX_DISABLED_BANNER_TEXT) if not sandbox_enabled else '""'
    demo_video_url_json = _safe_script_json_dumps(demo_video_url)

    if is_showcase:
        extra_scripts = f"""
        <script>
            const GRAPH_NODES = {graph_nodes_json};
            const GRAPH_EDGES = {graph_edges_json};
            {_MILESTONE_TOGGLE_JS}

            function switchMilestoneReadFile(tier, fileIdx) {{
                const panes = document.querySelectorAll('[id^="read-file-pane-' + tier + '-"]');
                panes.forEach(p => {{ p.style.display = 'none'; }});

                const targetPane = document.getElementById('read-file-pane-' + tier + '-' + fileIdx);
                if (targetPane) targetPane.style.display = 'block';

                const tabs = document.querySelectorAll('[id^="read-tab-btn-' + tier + '-"]');
                tabs.forEach(t => {{
                    t.style.background = 'transparent';
                    t.style.color = 'var(--text-muted)';
                    t.style.borderColor = 'var(--border)';
                    t.classList.remove('active');
                }});

                const activeTab = document.getElementById('read-tab-btn-' + tier + '-' + fileIdx);
                if (activeTab) {{
                    activeTab.style.background = 'var(--surface-2)';
                    activeTab.style.color = 'var(--success)';
                    activeTab.style.borderColor = 'var(--teal-border)';
                    activeTab.classList.add('active');
                }}
            }}

            function filterDagNodes(query) {{
                query = (query || '').toLowerCase().trim();
                const nodes = document.querySelectorAll('.dag-node');
                const edges = document.querySelectorAll('.dag-edge');

                if (!query) {{
                    nodes.forEach(n => {{ n.style.opacity = '1'; }});
                    edges.forEach(e => {{ e.style.opacity = '0.45'; e.setAttribute('stroke', 'var(--hairline-strong)'); }});
                    return;
                }}

                const matchedIds = new Set();
                nodes.forEach(n => {{
                    const id = (n.getAttribute('data-node-id') || '').toLowerCase();
                    const domain = (n.getAttribute('data-domain') || '').toLowerCase();
                    if (id.includes(query) || domain.includes(query)) {{
                        n.style.opacity = '1';
                        matchedIds.add(n.getAttribute('data-node-id'));
                    }} else {{
                        n.style.opacity = '0.15';
                    }}
                }});

                edges.forEach(e => {{
                    const s = (e.getAttribute('data-source') || '').toLowerCase();
                    const t = (e.getAttribute('data-target') || '').toLowerCase();
                    if (matchedIds.has(s) && matchedIds.has(t)) {{
                        e.style.opacity = '0.9';
                        e.setAttribute('stroke', 'var(--accent)');
                    }} else {{
                        e.style.opacity = '0.08';
                    }}
                }});
            }}

            function resetDagFilter() {{
                const input = document.getElementById('dag-search-input');
                if (input) input.value = '';
                filterDagNodes('');
            }}

            function selectDagNode(nodeId) {{
                if (!nodeId) return;
                const node = GRAPH_NODES.find(n => (n.id === nodeId || n.path === nodeId || n.name === nodeId));
                const detailBox = document.getElementById('dag-node-detail-card');
                if (detailBox && node) {{
                    document.getElementById('dag-detail-label').textContent = node.label || node.id || 'Node';
                    document.getElementById('dag-detail-path').textContent = node.path || node.id || '—';
                    document.getElementById('dag-detail-domain').textContent = (node.domain || node.type || 'module').toUpperCase();
                    document.getElementById('dag-detail-tier').textContent = 'Tier ' + (node.tier !== undefined ? node.tier : '—');
                    const exp = node.exports || [];
                    document.getElementById('dag-detail-exports').textContent = Array.isArray(exp) ? exp.join(', ') : (exp || 'None');
                    detailBox.style.display = 'block';
                }}
                const allNodes = document.querySelectorAll('.dag-node');
                allNodes.forEach(n => {{
                    const box = n.querySelector('.dag-node-box');
                    if (box) {{
                        box.setAttribute('stroke', n.getAttribute('data-node-id') === nodeId ? 'var(--accent)' : 'var(--border)');
                        box.setAttribute('stroke-width', n.getAttribute('data-node-id') === nodeId ? '2' : '1');
                    }}
                }});
            }}

            function hoverDagNode(nodeId) {{
                const edges = document.querySelectorAll('.dag-edge');
                edges.forEach(e => {{
                    if (e.getAttribute('data-source') === nodeId || e.getAttribute('data-target') === nodeId) {{
                        e.style.opacity = '1';
                        e.setAttribute('stroke-width', '2.5');
                    }}
                }});
            }}

            function unhoverDagNode() {{
                const edges = document.querySelectorAll('.dag-edge');
                edges.forEach(e => {{
                    e.style.opacity = '0.45';
                    e.setAttribute('stroke-width', '1.5');
                }});
            }}

            function verifyQuizAnswer(qIdx, correctIdx) {{
                const selected = document.querySelector('input[name="quiz_q_' + qIdx + '"]:checked');
                const feedback = document.getElementById('quiz-feedback-' + qIdx);
                const explanation = document.getElementById('quiz-explanation-' + qIdx);
                if (!selected) {{
                    if (feedback) {{
                        feedback.style.display = 'inline-block';
                        feedback.style.background = 'rgba(245, 158, 11, 0.15)';
                        feedback.style.color = 'var(--amber)';
                        feedback.textContent = 'Please select an option first.';
                    }}
                    return;
                }}
                const val = parseInt(selected.value, 10);
                if (val === correctIdx) {{
                    if (feedback) {{
                        feedback.style.display = 'inline-block';
                        feedback.style.background = 'rgba(45, 212, 191, 0.15)';
                        feedback.style.color = 'var(--success)';
                        feedback.textContent = '✓ Correct Answer';
                    }}
                }} else {{
                    if (feedback) {{
                        feedback.style.display = 'inline-block';
                        feedback.style.background = 'rgba(239, 68, 68, 0.15)';
                        feedback.style.color = 'var(--crimson)';
                        feedback.textContent = '✗ Incorrect. Check explanation below.';
                    }}
                }}
                if (explanation) explanation.style.display = 'block';
            }}

            function switchReportTab(tabId) {{
                const panes = document.querySelectorAll('.report-tab-pane');
                panes.forEach(p => {{ p.style.display = 'none'; }});
                const btns = document.querySelectorAll('.report-tab-btn');
                btns.forEach(b => {{ b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); }});
                const targetPane = document.getElementById('tab-pane-' + tabId);
                const targetBtn = document.getElementById('tab-btn-' + tabId);
                if (targetPane) targetPane.style.display = 'block';
                if (targetBtn) {{
                    targetBtn.classList.add('active');
                    targetBtn.setAttribute('aria-selected', 'true');
                }}
            }}
        </script>
        """
    else:
        extra_scripts = f"""
        <!-- CodeMirror Assets -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/python/python.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/javascript/javascript.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/clike/clike.min.js"></script>

    <script>
        const GRAPH_NODES = {graph_nodes_json};
        const GRAPH_EDGES = {graph_edges_json};
        const ALL_FILL_FILES = {fill_files_map_json};
        const DEMO_VIDEO_URL = {demo_video_url_json};
        const SANDBOX_DISABLED_BANNER_TEXT = {sandbox_banner_js_val};
        {_MILESTONE_TOGGLE_JS}
        window.BACKTRACE_JOB_ID = {job_id};
        window.fillFilesData = ALL_FILL_FILES;
        window.cmEditors = {{}};
        window.cmFillEditors = {{}};
        window.guessFileDrafts = {{}};
        window.activeGuessFileIdx = {{}};
        window.fillFileDrafts = {{}};
        window.activeFillFileIdx = {{}};

        function render503Notice(targetPanel, demoVideoUrl) {{
            if (!targetPanel) return;
            targetPanel.style.display = 'block';
            targetPanel.textContent = '';
            const bannerBox = document.createElement('div');
            bannerBox.className = 'stratum-card sandbox-503-banner';
            bannerBox.style.cssText = 'background: rgba(245, 158, 11, 0.08); border: 1px solid var(--amber); border-left: 4px solid var(--amber); padding: 1rem 1.25rem; margin: 0.75rem 0; border-radius: 4px; font-size: 0.875rem; line-height: 1.5; color: var(--text);';

            const textSpan = document.createElement('span');
            textSpan.textContent = SANDBOX_DISABLED_BANNER_TEXT;
            bannerBox.appendChild(textSpan);

            if (demoVideoUrl) {{
                const link = document.createElement('a');
                link.href = demoVideoUrl;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.style.cssText = 'color: var(--success); font-weight: 600; text-decoration: underline; margin-left: 0.35rem;';
                link.textContent = 'Watch the video';
                bannerBox.appendChild(link);
            }}
            targetPanel.appendChild(bannerBox);
        }}


        function initCodeEditors() {{
            // 1. Initialize Guess It CodeMirror Editors
            document.querySelectorAll('textarea[id^="code-editor-"]:not([id^="code-editor-fill-"])').forEach(function(ta) {{
                const tierId = ta.id.replace('code-editor-', '');
                if (window.cmEditors[tierId]) return;

                try {{
                    if (typeof CodeMirror !== 'undefined') {{
                        const editor = CodeMirror.fromTextArea(ta, {{
                            lineNumbers: true,
                            mode: 'python',
                            theme: 'dracula',
                            tabSize: 4,
                            indentUnit: 4,
                            lineWrapping: true,
                            viewportMargin: Infinity
                        }});
                        window.cmEditors[tierId] = editor;
                    }} else {{
                        ta.style.display = 'block';
                        ta.style.width = '100%';
                        ta.style.minHeight = '180px';
                    }}
                }} catch(e) {{
                    console.warn('CodeMirror guess init failed, falling back to textarea', e);
                    ta.style.display = 'block';
                    ta.style.width = '100%';
                    ta.style.minHeight = '180px';
                    ta.style.background = '#1e1f29';
                    ta.style.color = '#f8f8f2';
                    ta.style.fontFamily = 'monospace';
                    ta.style.padding = '8px';
                }}
            }});

            // 2. Initialize Fill the Blanks CodeMirror Editors
            document.querySelectorAll('textarea[id^="code-editor-fill-"]').forEach(function(ta) {{
                const tierId = ta.id.replace('code-editor-fill-', '');
                if (window.cmFillEditors[tierId]) return;

                try {{
                    if (typeof CodeMirror !== 'undefined') {{
                        const editor = CodeMirror.fromTextArea(ta, {{
                            lineNumbers: true,
                            mode: 'python',
                            theme: 'dracula',
                            tabSize: 4,
                            indentUnit: 4,
                            lineWrapping: true,
                            viewportMargin: Infinity
                        }});
                        window.cmFillEditors[tierId] = editor;
                    }} else {{
                        ta.style.display = 'block';
                        ta.style.width = '100%';
                        ta.style.minHeight = '240px';
                    }}
                }} catch(e) {{
                    console.warn('CodeMirror fill init failed, falling back to textarea', e);
                    ta.style.display = 'block';
                    ta.style.width = '100%';
                    ta.style.minHeight = '240px';
                    ta.style.background = '#1e1f29';
                    ta.style.color = '#f8f8f2';
                    ta.style.fontFamily = 'monospace';
                    ta.style.padding = '8px';
                }}
            }});
        }}

        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', initCodeEditors);
        }} else {{
            initCodeEditors();
        }}

        function escapeHtml(str) {{
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }}

        function renderGroupedFillChips(blankedFunctions, reason) {{
            if (!blankedFunctions || blankedFunctions.length === 0) {{
                return '<span style="font-size: 0.8125rem; color: var(--text-muted); font-style: italic;">' + escapeHtml(reason || 'File contains no function bodies to blank.') + '</span>';
            }}

            const totalCount = Number(blankedFunctions.length) || 0;
            const shouldCollapse = totalCount > 15;

            const groupOrder = [];
            const groups = {{}};

            blankedFunctions.forEach(function(bf) {{
                const className = bf.class_name || '';
                const groupKey = className ? className : '__toplevel__';
                if (!groups[groupKey]) {{
                    groups[groupKey] = {{
                        className: className,
                        isClass: Boolean(className),
                        items: []
                    }};
                    groupOrder.push(groupKey);
                }}
                groups[groupKey].items.push(bf);
            }});

            let html = '';
            groupOrder.forEach(function(key) {{
                const g = groups[key];
                const count = Number(g.items.length) || 0;
                const groupTitle = g.isClass ? ('class ' + escapeHtml(g.className)) : 'Top-level Functions';
                const groupCountLabel = g.isClass ? (count + (count === 1 ? ' method' : ' methods')) : (count + (count === 1 ? ' function' : ' functions'));
                const icon = g.isClass ? '🏛️' : '📁';

                let chipsHtml = '';
                g.items.forEach(function(bf) {{
                    const fnName = escapeHtml(bf.name || bf.full_name || '');
                    const fullFnName = escapeHtml((bf.full_name || bf.name || '') + '()');
                    chipsHtml += '<span class="mono" title="' + fullFnName + '" style="display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.15rem 0.45rem; background: var(--panel-raised); border: 1px solid var(--border); border-radius: 3px; font-size: 0.8125rem; color: var(--success);">🧩 ' + fnName + '()</span> ';
                }});

                const openAttr = shouldCollapse ? '' : ' open';
                html += '<details' + openAttr + ' class="fill-chip-group" style="margin-bottom: 0.4rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 0.35rem 0.6rem;">' +
                    '<summary style="cursor: pointer; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text-muted); user-select: none; display: flex; align-items: center; justify-content: space-between;">' +
                        '<span>' + icon + ' ' + groupTitle + ' <span style="opacity: 0.7; font-weight: normal; font-size: 0.8125rem;">(' + groupCountLabel + ')</span></span>' +
                        '<span style="font-size: 0.8125rem; color: var(--text-muted);">▾</span>' +
                    '</summary>' +
                    '<div style="display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.4rem; padding-top: 0.35rem; border-top: 1px solid var(--hairline-soft);">' +
                        chipsHtml +
                    '</div>' +
                '</details>';
            }});

            return html;
        }}

        function renderDiffHtmlInJs(result, isVerified, errorMsg, gradingMethod) {{
            let tierTag = '<span class="badge badge-brass" style="font-size: 0.8125rem; ">Tier 3: Structural verification</span>';
            if (gradingMethod === 'real_tests') {{
                tierTag = '<span class="badge badge-teal" style="font-size: 0.8125rem; ">Tier 1: Real reproduction</span>';
            }} else if (gradingMethod === 'expected_output') {{
                tierTag = '<span class="badge badge-amber" style="font-size: 0.8125rem; ">Tier 2: Expected interface</span>';
            }} else if (gradingMethod === 'fill_the_blanks') {{
                tierTag = '<span class="badge badge-teal" style="font-size: 0.8125rem; ">Tier 3: Fill the blanks</span>';
            }}

            let banner = '';
            if (isVerified) {{
                banner = '<div class="diff-banner success" style="background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--success); padding: 0.65rem 0.85rem; border-radius: 4px; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; margin-bottom: 0.65rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; flex-wrap: wrap;"><div style="display: flex; align-items: center; gap: 0.4rem;"><span>✓</span> VERIFIED: Milestone requirements fulfilled</div>' + tierTag + '</div>';
            }} else {{
                banner = '<div class="diff-banner failure" style="background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.65rem 0.85rem; border-radius: 4px; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; margin-bottom: 0.65rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; flex-wrap: wrap;"><div style="display: flex; align-items: center; gap: 0.4rem;"><span>⚠</span> VERIFICATION GAPS: Requirements not yet satisfied</div>' + tierTag + '</div>';
            }}

            const diff = (result && result.diff) ? result.diff : (result || {{}});
            const err = errorMsg || diff.error_message || diff.error || diff.grading_error;

            let errHtml = '';
            if (err) {{
                errHtml = '<div style="color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem; margin-bottom: 0.5rem; background: rgba(244,63,94,0.08); padding: 0.5rem; border-radius: 3px;">' + escapeHtml(err) + '</div>';
            }}

            // Handle Fill the Blanks grading results specially
            if (gradingMethod === 'fill_the_blanks' || diff.blank_details || diff.blanked_evaluated !== undefined) {{
                const blankDetails = diff.blank_details || [];
                const blankedCount = Number(diff.blanked_evaluated !== undefined ? diff.blanked_evaluated : blankDetails.length) || 0;
                const implementedCount = Number(diff.implemented_count !== undefined ? diff.implemented_count : blankDetails.filter(b => b.status === 'implemented').length) || 0;

                let implementedPills = '';
                let stubPills = '';

                blankDetails.forEach(function(b) {{
                    const name = escapeHtml(b.name || 'function');
                    if (b.status === 'implemented') {{
                        implementedPills += '<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--success); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem;">✓ ' + name + '() <span style="opacity: 0.75; font-size: 0.8125rem;">(implemented)</span></span> ';
                    }} else {{
                        const reason = escapeHtml(b.reason || 'unimplemented stub');
                        stubPills += '<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem;">✗ ' + name + '() <span style="opacity: 0.75; font-size: 0.8125rem;">(' + reason + ')</span></span> ';
                    }}
                }});

                let fillSectionsHtml = '<div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.4rem;">Scoped blanks evaluated: <strong>' + implementedCount + ' / ' + blankedCount + '</strong> completed.</div>';
                if (implementedPills) {{
                    const isAllDone = (implementedCount === blankedCount && blankedCount > 0);
                    const fillSummary = implementedCount + '/' + blankedCount + ' functions completed' + (isAllDone ? ' ✓' : '');
                    fillSectionsHtml += '<details class="matched-symbols-collapse" style="background: var(--surface-2); border: 1px solid var(--teal-border); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;">' +
                        '<summary style="cursor: pointer; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--success); display: flex; align-items: center; justify-content: space-between; user-select: none;">' +
                            '<span>Implemented blanks (' + fillSummary + '):</span>' +
                            '<span style="font-size: 0.8125rem; opacity: 0.85; font-weight: normal;">View list ▾</span>' +
                        '</summary>' +
                        '<div style="display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem; padding-top: 0.4rem; border-top: 1px solid var(--hairline-soft);">' + implementedPills + '</div>' +
                    '</details>';
                }}
                if (stubPills) {{
                    fillSectionsHtml += '<div style="background: rgba(244, 63, 94, 0.06); border: 1px solid rgba(244, 63, 94, 0.25); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;"><div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--crimson); font-weight: 600; margin-bottom: 0.35rem;">Unimplemented / stub blanks:</div><div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">' + stubPills + '</div></div>';
                }}

                return banner + errHtml + '<div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.5rem;">' + fillSectionsHtml + '</div>';
            }}

            // Standard Guess It AST Diff rendering
            const present = diff.present_symbols || diff.present || [];
            const missing = diff.missing_symbols || diff.missing || [];
            const extra = diff.extra_symbols || diff.extra || [];

            let presentPills = '';
            present.forEach(function(s) {{
                const mat = s.matched || s.expected || s || {{}};
                const name = escapeHtml(typeof mat === 'object' ? (mat.name || '') : String(mat));
                const kind = escapeHtml(typeof mat === 'object' ? (mat.kind || 'symbol') : 'symbol');
                const argsStr = mat.args && mat.args.length ? '(' + mat.args.map(escapeHtml).join(', ') + ')' : '';
                presentPills += '<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--success); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem;">✓ ' + name + argsStr + ' <span style="opacity: 0.75; font-size: 0.8125rem;">(' + kind + ')</span></span> ';
            }});

            let missingPills = '';
            missing.forEach(function(s) {{
                const mat = s.expected || s || {{}};
                const name = escapeHtml(typeof mat === 'object' ? (mat.name || '') : String(mat));
                const kind = escapeHtml(typeof mat === 'object' ? (mat.kind || 'required') : 'required');
                missingPills += '<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem;">✗ ' + name + ' <span style="opacity: 0.75; font-size: 0.8125rem;">(' + kind + ')</span></span> ';
            }});

            let extraPills = '';
            extra.forEach(function(s) {{
                const mat = s.matched || s || {{}};
                const name = escapeHtml(typeof mat === 'object' ? (mat.name || '') : String(mat));
                const kind = escapeHtml(typeof mat === 'object' ? (mat.kind || 'extra') : 'extra');
                extraPills += '<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: var(--panel-raised); border: 1px solid var(--border); color: var(--text-muted); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem;">+ ' + name + ' <span style="opacity: 0.75; font-size: 0.8125rem;">(' + kind + ')</span></span> ';
            }});

            const totalExpected = Number(present.length + missing.length) || 0;
            const isAllMatched = (missing.length === 0 && totalExpected > 0);
            const matchSummary = totalExpected > 0 ? ((Number(present.length) || 0) + '/' + totalExpected + ' symbols matched' + (isAllMatched ? ' ✓' : '')) : ((Number(present.length) || 0) + ' matched');

            let sectionsHtml = '';
            if (presentPills) {{
                sectionsHtml += '<details class="matched-symbols-collapse" style="background: var(--surface-2); border: 1px solid var(--teal-border); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;">' +
                    '<summary style="cursor: pointer; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--success); display: flex; align-items: center; justify-content: space-between; user-select: none;">' +
                        '<span>Present &amp; matched symbols (' + matchSummary + '):</span>' +
                        '<span style="font-size: 0.8125rem; opacity: 0.85; font-weight: normal;">View list ▾</span>' +
                    '</summary>' +
                    '<div style="display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem; padding-top: 0.4rem; border-top: 1px solid var(--hairline-soft);">' + presentPills + '</div>' +
                '</details>';
            }}
            if (missingPills) {{
                sectionsHtml += '<div style="background: rgba(244, 63, 94, 0.06); border: 1px solid rgba(244, 63, 94, 0.25); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;"><div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--crimson); font-weight: 600; margin-bottom: 0.35rem;">Missing expected symbols (' + missing.length + '):</div><div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">' + missingPills + '</div></div>';
            }}
            if (extraPills) {{
                sectionsHtml += '<div style="background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: 0.45rem 0.75rem; margin-bottom: 0.4rem;"><div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); font-weight: 600; margin-bottom: 0.35rem;">Extra / auxiliary symbols (' + extra.length + '):</div><div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">' + extraPills + '</div></div>';
            }}

            return banner + errHtml + '<div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.5rem;">' + sectionsHtml + '</div>';
        }}

        function renderConsoleHtmlInJs(exec) {{
            if (!exec) return '';
            const eObj = (exec.execution) ? exec.execution : exec;
            const exitCode = (eObj.exit_code !== undefined && eObj.exit_code !== null) ? (Number(eObj.exit_code) || 0) : 0;
            const isSuccess = (exitCode === 0 && !eObj.timed_out && !eObj.memory_exceeded);
            const stdout = eObj.stdout || '';
            const stderr = eObj.stderr || '';
            const execMs = (eObj.execution_time_ms !== undefined && eObj.execution_time_ms !== null && Number(eObj.execution_time_ms) > 0) ? ((Number(eObj.execution_time_ms) || 0) + 'ms') : '';
            const exitBadgeClass = isSuccess ? 'badge-teal' : 'badge-crimson';
            const exitBadgeText = 'EXIT ' + exitCode + (eObj.timed_out ? ' (TIMED OUT)' : (eObj.memory_exceeded ? ' (OOM)' : ''));
            const dotColor = isSuccess ? 'teal' : 'crimson';

            let content = '';
            if (stdout) {{
                content += '<div style="color: #e2e8f0; white-space: pre-wrap; word-break: break-all; margin-bottom: 0.5rem;">' + escapeHtml(stdout) + '</div>';
            }}
            if (stderr) {{
                content += '<div style="color: var(--crimson); white-space: pre-wrap; word-break: break-all; margin-top: 0.25rem;">' + escapeHtml(stderr) + '</div>';
            }}
            if (!stdout && !stderr) {{
                content = '<div style="color: var(--text-muted); font-style: italic;">(Process completed with no output)</div>';
            }}

            return '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem;">' +
                '<div style="display: flex; align-items: center; gap: 0.5rem;">' +
                    '<span class="chip-dot ' + dotColor + '"></span>' +
                    '<span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text); ">Execution Console</span>' +
                    '<span class="badge ' + exitBadgeClass + '" style="font-size: 0.8125rem;">' + exitBadgeText + '</span>' +
                    (execMs ? '<span class="tag" style="font-size: 0.8125rem;">' + execMs + '</span>' : '') +
                '</div>' +
                '<span style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted);">Unmetered playground</span>' +
            '</div>' +
            '<pre style="background: #0d0e12; padding: 0.75rem; border-radius: 3px; border: 1px solid var(--hairline-soft); font-family: var(--font-mono); font-size: 0.8125rem; line-height: 1.45; overflow-x: auto; margin: 0;"><code>' + content + '</code></pre>';
        }}

        async function runMilestoneCode(jobId, tier) {{
            const btn = document.getElementById('btn-run-' + tier);
            const spinner = document.getElementById('indicator-spinner-run-' + tier);
            const consolePanel = document.getElementById('console-output-panel-' + tier);

            let codeToRun = '';
            if (window.cmEditors && window.cmEditors[tier]) {{
                codeToRun = window.cmEditors[tier].getValue();
            }} else {{
                const ta = document.getElementById('code-editor-' + tier);
                codeToRun = ta ? ta.value : '';
            }}

            if (btn) btn.disabled = true;
            if (spinner) spinner.style.display = 'inline-flex';

            try {{
                const resp = await fetch('/api/attempts/' + jobId + '/' + tier + '/run', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{
                        submitted_code: codeToRun,
                        code: codeToRun,
                        language: 'python'
                    }})
                }});

                if (!resp.ok) {{
                    if (resp.status === 503) {{
                        render503Notice(consolePanel, DEMO_VIDEO_URL);
                        return;
                    }}
                    const errData = await resp.json().catch(() => ({{}}));
                    const msg = errData.detail || ('HTTP ' + resp.status + ' execution error');
                    if (consolePanel) {{
                        consolePanel.style.display = 'block';
                        consolePanel.textContent = '';
                        const errBox = document.createElement('div');
                        errBox.style.cssText = "color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;";
                        errBox.textContent = 'Execution Error: ' + msg;
                        consolePanel.appendChild(errBox);
                    }}
                    return;
                }}

                const data = await resp.json();
                if (consolePanel) {{
                    consolePanel.style.display = 'block';
                    consolePanel.innerHTML = renderConsoleHtmlInJs(data);
                }}
            }} catch(e) {{
                console.error('Execution run failed', e);
                if (consolePanel) {{
                    consolePanel.style.display = 'block';
                    consolePanel.textContent = '';
                    const errBox = document.createElement('div');
                    errBox.style.cssText = "color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;";
                    errBox.textContent = 'Execution Network Error: ' + e.message;
                    consolePanel.appendChild(errBox);
                }}
            }} finally {{
                if (btn) btn.disabled = false;
                if (spinner) spinner.style.display = 'none';
            }}
        }}

        async function submitMilestoneCode(jobId, tier) {{
            const btn = document.getElementById('btn-submit-' + tier);
            const spinner = document.getElementById('indicator-spinner-' + tier);
            const diffPanel = document.getElementById('diff-output-panel-' + tier);
            const consolePanel = document.getElementById('console-output-panel-' + tier);
            const vessel = document.getElementById('milestone-vessel-' + tier);
            const vesselText = document.getElementById('milestone-vessel-text-' + tier);
            const statusBadge = document.getElementById('status-badge-' + tier);

            let submittedCode = '';
            if (window.cmEditors && window.cmEditors[tier]) {{
                submittedCode = window.cmEditors[tier].getValue();
            }} else {{
                const ta = document.getElementById('code-editor-' + tier);
                submittedCode = ta ? ta.value : '';
            }}

            if (btn) btn.disabled = true;
            if (spinner) spinner.style.display = 'inline-flex';

            try {{
                const resp = await fetch('/api/attempts/' + jobId + '/' + tier, {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{
                        submitted_code: submittedCode,
                        mode: 'guess'
                    }})
                }});

                if (!resp.ok) {{
                    if (resp.status === 503) {{
                        render503Notice(diffPanel, DEMO_VIDEO_URL);
                        return;
                    }}
                    const errData = await resp.json().catch(() => ({{}}));
                    const msg = errData.detail || ('HTTP ' + resp.status + ' error occurred');
                    if (diffPanel) {{
                        diffPanel.style.display = 'block';
                        diffPanel.textContent = '';
                        const errBox = document.createElement('div');
                        errBox.style.cssText = "color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;";
                        errBox.textContent = 'Verification Error: ' + msg;
                        diffPanel.appendChild(errBox);
                    }}
                    return;
                }}

                const data = await resp.json();
                const ver = data.verification || data;
                const isVerified = (ver.structurally_verified !== undefined) ? ver.structurally_verified : (ver.is_verified || (data.status === 'structurally_verified'));
                const diff = ver;
                const err = ver.error_message || ver.error || ver.grading_error;
                const gradingMethod = data.grading_method || (ver && ver.grading_method) || 'structural_only';

                if (diffPanel) {{
                    diffPanel.style.display = 'block';
                    diffPanel.innerHTML = renderDiffHtmlInJs(diff, isVerified, err, gradingMethod);
                }}

                // Render Sandbox Execution Result if returned
                if (data.execution && consolePanel) {{
                    consolePanel.style.display = 'block';
                    consolePanel.innerHTML = renderConsoleHtmlInJs(data.execution);
                }}

                // Update Visual Vessel State
                if (vessel) {{
                    if (isVerified) {{
                        vessel.className = 'milestone-vessel verified';
                        if (vesselText) vesselText.textContent = '✓';
                    }} else {{
                        vessel.className = 'milestone-vessel attempting';
                        if (vesselText) vesselText.textContent = String(tier).padStart(2, '0');
                    }}
                }}

                // Update Status Chip
                if (statusBadge) {{
                    if (isVerified) {{
                        statusBadge.className = 'badge badge-teal';
                        statusBadge.innerHTML = '<span class="chip-dot teal"></span> STRUCTURALLY VERIFIED';
                    }} else {{
                        statusBadge.className = 'badge badge-amber';
                        statusBadge.innerHTML = '<span class="chip-dot amber"></span> ATTEMPTING';
                    }}
                }}

                // Unlock hint and reveal buttons upon first submission
                const hintBtn = document.getElementById('btn-hint-' + tier);
                const revealBtn = document.getElementById('btn-reveal-' + tier);
                const lockedNotice = document.getElementById('hint-locked-notice-' + tier);
                if (hintBtn) hintBtn.style.display = 'inline-flex';
                if (revealBtn) revealBtn.style.display = 'inline-flex';
                if (lockedNotice) lockedNotice.style.display = 'none';
            }} catch(e) {{
                console.error('Submission failed', e);
                if (diffPanel) {{
                    diffPanel.style.display = 'block';
                    diffPanel.innerHTML = '<div style="color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;">Network Error: ' + escapeHtml(e.message) + '</div>';
                }}
            }} finally {{
                if (btn) btn.disabled = false;
                if (spinner) spinner.style.display = 'none';
            }}
        }}

        async function runMilestoneFillCode(jobId, tier) {{
            const btn = document.getElementById('btn-run-fill-' + tier);
            const spinner = document.getElementById('indicator-spinner-run-fill-' + tier);
            const consolePanel = document.getElementById('console-output-panel-fill-' + tier);

            let codeToRun = '';
            if (window.cmFillEditors && window.cmFillEditors[tier]) {{
                codeToRun = window.cmFillEditors[tier].getValue();
            }} else {{
                const ta = document.getElementById('code-editor-fill-' + tier);
                codeToRun = ta ? ta.value : '';
            }}

            if (btn) btn.disabled = true;
            if (spinner) spinner.style.display = 'inline-flex';

            try {{
                const resp = await fetch('/api/attempts/' + jobId + '/' + tier + '/run', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{
                        submitted_code: codeToRun,
                        code: codeToRun,
                        language: 'python'
                    }})
                }});

                if (!resp.ok) {{
                    if (resp.status === 503) {{
                        render503Notice(consolePanel, DEMO_VIDEO_URL);
                        return;
                    }}
                    const errData = await resp.json().catch(() => ({{}}));
                    const msg = errData.detail || ('HTTP ' + resp.status + ' execution error');
                    if (consolePanel) {{
                        consolePanel.style.display = 'block';
                        consolePanel.textContent = '';
                        const errBox = document.createElement('div');
                        errBox.style.cssText = "color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;";
                        errBox.textContent = 'Execution Error: ' + msg;
                        consolePanel.appendChild(errBox);
                    }}
                    return;
                }}

                const data = await resp.json();
                if (consolePanel) {{
                    consolePanel.style.display = 'block';
                    consolePanel.innerHTML = renderConsoleHtmlInJs(data);
                }}
            }} catch(e) {{
                console.error('Fill execution run failed', e);
                if (consolePanel) {{
                    consolePanel.style.display = 'block';
                    consolePanel.textContent = '';
                    const errBox = document.createElement('div');
                    errBox.style.cssText = "color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;";
                    errBox.textContent = 'Execution Network Error: ' + e.message;
                    consolePanel.appendChild(errBox);
                }}
            }} finally {{
                if (btn) btn.disabled = false;
                if (spinner) spinner.style.display = 'none';
            }}
        }}

        async function submitMilestoneFillCode(jobId, tier) {{
            const btn = document.getElementById('btn-submit-fill-' + tier);
            const spinner = document.getElementById('indicator-spinner-fill-' + tier);
            const diffPanel = document.getElementById('diff-output-panel-fill-' + tier);
            const consolePanel = document.getElementById('console-output-panel-fill-' + tier);
            const vessel = document.getElementById('milestone-vessel-' + tier);
            const vesselText = document.getElementById('milestone-vessel-text-' + tier);
            const statusBadge = document.getElementById('status-badge-' + tier);

            let submittedCode = '';
            if (window.cmFillEditors && window.cmFillEditors[tier]) {{
                submittedCode = window.cmFillEditors[tier].getValue();
            }} else {{
                const ta = document.getElementById('code-editor-fill-' + tier);
                submittedCode = ta ? ta.value : '';
            }}

            const currentIdx = (window.activeFillFileIdx && window.activeFillFileIdx[tier] !== undefined) ? window.activeFillFileIdx[tier] : 0;
            const targetFile = (window.fillFilesData && window.fillFilesData[tier] && window.fillFilesData[tier][currentIdx]) ? window.fillFilesData[tier][currentIdx].path : undefined;

            if (btn) btn.disabled = true;
            if (spinner) spinner.style.display = 'inline-flex';

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000);

            try {{
                const resp = await fetch('/api/attempts/' + jobId + '/' + tier, {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{
                        submitted_code: submittedCode,
                        mode: 'fill',
                        target_file: targetFile
                    }}),
                    signal: controller.signal
                }});

                if (!resp.ok) {{
                    if (resp.status === 503) {{
                        render503Notice(diffPanel, DEMO_VIDEO_URL);
                        return;
                    }}
                    if (diffPanel) {{
                        diffPanel.style.display = 'block';
                        diffPanel.textContent = '';
                        const errBox = document.createElement('div');
                        errBox.style.cssText = "color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;";
                        errBox.textContent = "Couldn't check your answer. Try again.";
                        diffPanel.appendChild(errBox);
                    }}
                    return;
                }}

                const data = await resp.json();
                const passed = (data.passed !== undefined) ? Boolean(data.passed) : (data.verification ? Boolean(data.verification.passed || data.verification.structurally_verified) : false);
                const ver = data.verification || data;
                const isVerified = (ver.structurally_verified !== undefined) ? ver.structurally_verified : (ver.is_verified || (data.status === 'structurally_verified') || passed);
                const diff = ver;
                const err = ver.error_message || ver.error || ver.grading_error;
                const gradingMethod = data.grading_method || (ver && ver.grading_method) || 'fill_the_blanks';

                if (diffPanel) {{
                    diffPanel.style.display = 'block';
                    const feedbackBanner = passed
                        ? '<div class="fill-feedback-banner correct" style="margin-bottom: 0.75rem; padding: 0.6rem 0.85rem; background: rgba(20, 184, 166, 0.1); border-left: 3px solid var(--success); border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--success); display: flex; align-items: center; gap: 0.4rem;"><span>✓</span> Correct</div>'
                        : '<div class="fill-feedback-banner incorrect" style="margin-bottom: 0.75rem; padding: 0.6rem 0.85rem; background: rgba(239, 68, 68, 0.1); border-left: 3px solid var(--crimson); border-radius: 3px; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--crimson); display: flex; align-items: center; gap: 0.4rem;"><span>✗</span> Not quite, try again</div>';
                    diffPanel.innerHTML = feedbackBanner + renderDiffHtmlInJs(diff, isVerified, err, gradingMethod);
                }}

                // Render Sandbox Execution Result if returned
                if (data.execution && consolePanel) {{
                    consolePanel.style.display = 'block';
                    consolePanel.innerHTML = renderConsoleHtmlInJs(data.execution);
                }}

                // Update Visual Vessel State
                if (vessel) {{
                    if (isVerified) {{
                        vessel.className = 'milestone-vessel verified';
                        if (vesselText) vesselText.textContent = '✓';
                    }} else {{
                        vessel.className = 'milestone-vessel attempting';
                        if (vesselText) vesselText.textContent = String(tier).padStart(2, '0');
                    }}
                }}

                // Update Status Chip
                if (statusBadge) {{
                    if (isVerified) {{
                        statusBadge.className = 'badge badge-teal';
                        statusBadge.innerHTML = '<span class="chip-dot teal"></span> STRUCTURALLY VERIFIED';
                    }} else {{
                        statusBadge.className = 'badge badge-amber';
                        statusBadge.innerHTML = '<span class="chip-dot amber"></span> ATTEMPTING';
                    }}
                }}
            }} catch(e) {{
                console.error('Fill submission failed', e);
                if (diffPanel) {{
                    diffPanel.style.display = 'block';
                    diffPanel.innerHTML = '<div style="color: var(--crimson); font-family: var(--font-ui); font-size: 0.8125rem;">Couldn\\'t check your answer. Try again.</div>';
                }}
            }} finally {{
                clearTimeout(timeoutId);
                if (btn) btn.disabled = false;
                if (spinner) spinner.style.display = 'none';
            }}
        }}

        const HINT_CONFIRM_COPY_1 = "{HintEngine.SELECTED_HINT_1_CONFIRM}";
        const HINT_CONFIRM_COPY_2 = "{HintEngine.CONFIRM_HINT_2_COPY}";
        const REVEAL_CONFIRM_COPY = "{HintEngine.CONFIRM_REVEAL_COPY}";

        function openHintConfirmModal(jobId, tier, mode) {{
            const btnId = (mode === 'fill') ? ('btn-hint-fill-' + tier) : ('btn-hint-' + tier);
            const hintBtn = document.getElementById(btnId) || document.getElementById('btn-hint-' + tier);
            const level = parseInt(hintBtn ? hintBtn.getAttribute('data-hint-level') || '0' : '0', 10);
            const box = document.getElementById('hint-confirm-box-' + tier);
            const titleEl = document.getElementById('hint-confirm-title-' + tier);
            const textEl = document.getElementById('hint-confirm-text-' + tier);
            const actionBtn = document.getElementById('btn-confirm-hint-action-' + tier);

            if (level >= 2) return;

            if (actionBtn) {{
                actionBtn.setAttribute('data-target-mode', mode || 'guess');
            }}

            if (level === 0) {{
                if (titleEl) titleEl.textContent = 'Hint 1: Confirmation';
                if (textEl) textEl.textContent = HINT_CONFIRM_COPY_1;
                if (actionBtn) actionBtn.textContent = 'Yes, Reveal Conceptual Hint';
            }} else {{
                if (titleEl) titleEl.textContent = 'Hint 2: Target Symbol Gate';
                if (textEl) textEl.textContent = HINT_CONFIRM_COPY_2;
                if (actionBtn) actionBtn.textContent = 'Yes, Reveal Missing Target Symbols';
            }}

            if (box) box.style.display = 'block';
        }}

        function cancelHintConfirm(tier) {{
            const box = document.getElementById('hint-confirm-box-' + tier);
            if (box) box.style.display = 'none';
        }}

        async function confirmAndFetchHint(jobId, tier) {{
            const box = document.getElementById('hint-confirm-box-' + tier);
            const actionBtn = document.getElementById('btn-confirm-hint-action-' + tier);
            const mode = (actionBtn ? actionBtn.getAttribute('data-target-mode') : 'guess') || 'guess';
            const hintBtn = document.getElementById('btn-hint-' + tier);
            const hintBtnText = document.getElementById('btn-hint-text-' + tier);
            const hintFillBtn = document.getElementById('btn-hint-fill-' + tier);
            const hintFillBtnText = document.getElementById('btn-hint-fill-text-' + tier);

            if (actionBtn) actionBtn.disabled = true;

            try {{
                const url = '/api/attempts/' + jobId + '/' + tier + '/hint' + (mode === 'fill' ? '?mode=fill' : '');
                const resp = await fetch(url, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }}
                }});

                if (!resp.ok) {{
                    const err = await resp.json().catch(() => ({{}}));
                    alert(err.detail || 'Error requesting hint');
                    return;
                }}

                const data = await resp.json();
                const level = data.hint_level_revealed;

                if (box) box.style.display = 'none';

                if (data.hint_1) {{
                    const p1 = document.getElementById('hint-1-panel-' + tier);
                    const t1 = document.getElementById('hint-1-text-' + tier);
                    if (p1) p1.style.display = 'block';
                    if (t1) t1.textContent = data.hint_1;
                }}

                if (data.hint_2) {{
                    const p2 = document.getElementById('hint-2-panel-' + tier);
                    const t2 = document.getElementById('hint-2-text-' + tier);
                    if (p2) p2.style.display = 'block';
                    if (t2) t2.textContent = data.hint_2;
                }}

                [hintBtn, hintFillBtn].forEach(function(btn) {{
                    if (btn) {{
                        btn.setAttribute('data-hint-level', String(level));
                        if (level >= 2) btn.disabled = true;
                    }}
                }});

                if (hintBtnText) hintBtnText.textContent = 'Hint';
                if (hintFillBtnText) hintFillBtnText.textContent = 'Hint';

                const fillNote = document.getElementById('hints-unlocked-fill-note-' + tier);
                if (fillNote) {{
                    fillNote.innerHTML = 'Hints unlocked &bull; Only blanked functions evaluated';
                }}
            }} catch(e) {{
                console.error('Failed to retrieve hint', e);
                alert('Network error while requesting hint');
            }} finally {{
                if (actionBtn) actionBtn.disabled = false;
            }}
        }}

        function openRevealConfirmModal(jobId, tier, mode) {{
            const box = document.getElementById('reveal-confirm-box-' + tier);
            const actionBtn = document.getElementById('btn-confirm-reveal-action-' + tier);
            if (actionBtn) {{
                actionBtn.setAttribute('data-target-mode', mode || 'guess');
            }}
            if (box) box.style.display = 'block';
        }}

        function cancelRevealConfirm(tier) {{
            const box = document.getElementById('reveal-confirm-box-' + tier);
            if (box) box.style.display = 'none';
        }}

        async function confirmAndRevealImplementation(jobId, tier) {{
            const box = document.getElementById('reveal-confirm-box-' + tier);
            const actionBtn = document.getElementById('btn-confirm-reveal-action-' + tier);
            const mode = (actionBtn ? actionBtn.getAttribute('data-target-mode') : 'guess') || 'guess';
            const revealBtn = document.getElementById('btn-reveal-' + tier);
            const revealBtnText = document.getElementById('btn-reveal-text-' + tier);
            const revealFillBtn = document.getElementById('btn-reveal-fill-' + tier);
            const revealFillBtnText = document.getElementById('btn-reveal-fill-text-' + tier);

            if (actionBtn) actionBtn.disabled = true;

            try {{
                const url = '/api/attempts/' + jobId + '/' + tier + '/reveal' + (mode === 'fill' ? '?mode=fill' : '');
                const resp = await fetch(url, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }}
                }});

                if (!resp.ok) {{
                    const err = await resp.json().catch(() => ({{}}));
                    alert(err.detail || 'Error revealing reference implementation');
                    return;
                }}

                const data = await resp.json();
                if (box) box.style.display = 'none';

                const refPanel = document.getElementById('reference-panel-' + tier);
                const refCode = document.getElementById('reference-code-' + tier);
                if (refPanel) refPanel.style.display = 'block';
                if (refCode && data.reference_implementation) {{
                    refCode.textContent = data.reference_implementation.reference_code || '';
                }}

                if (revealBtnText) {{
                    revealBtnText.textContent = 'Show solution';
                }}
                if (revealFillBtnText) {{
                    revealFillBtnText.textContent = 'Show solution';
                }}
            }} catch(e) {{
                console.error('Failed to reveal implementation', e);
                alert('Network error while revealing implementation');
            }} finally {{
                if (actionBtn) actionBtn.disabled = false;
            }}
        }}

        async function markMilestoneAsReviewed(jobId, tier) {{
            const btn = document.getElementById('btn-review-' + tier);
            const btnText = document.getElementById('btn-review-text-' + tier);
            const spinner = document.getElementById('indicator-spinner-review-' + tier);
            const vessel = document.getElementById('milestone-vessel-' + tier);
            const vesselText = document.getElementById('milestone-vessel-text-' + tier);
            const statusBadge = document.getElementById('status-badge-' + tier);

            if (btn) btn.disabled = true;
            if (spinner) spinner.style.display = 'inline-flex';

            try {{
                const resp = await fetch('/api/attempts/' + jobId + '/' + tier + '/review', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }}
                }});

                if (!resp.ok) {{
                    const errData = await resp.json().catch(() => ({{}}));
                    const msg = errData.detail || ('HTTP ' + resp.status + ' review error');
                    alert('Failed to mark milestone as reviewed: ' + msg);
                    return;
                }}

                const data = await resp.json();

                // Update Visual Vessel State
                if (vessel) {{
                    vessel.className = 'milestone-vessel verified';
                    if (vesselText) vesselText.textContent = '✓';
                }}

                // Update Status Badge
                if (statusBadge) {{
                    statusBadge.className = 'badge badge-teal';
                    statusBadge.innerHTML = '<span class="chip-dot teal"></span> STRUCTURALLY VERIFIED';
                }}

                // Update button text
                if (btnText) {{
                    btnText.textContent = 'Reviewed & Verified ✓';
                }}
            }} catch(e) {{
                console.error('Mark as reviewed failed', e);
                alert('Network error while marking milestone as reviewed: ' + e.message);
            }} finally {{
                if (btn) btn.disabled = false;
                if (spinner) spinner.style.display = 'none';
            }}
        }}

        function switchMilestoneMode(tier, mode) {{
            const fillBtn = document.getElementById('mode-btn-fill-' + tier);
            if (mode === 'fill' && fillBtn && fillBtn.disabled) {{
                return;
            }}

            try {{
                localStorage.setItem('backtrace_milestone_mode', mode);
            }} catch(e) {{}}

            const guessWorkspace = document.getElementById('workspace-guess-' + tier);
            const readWorkspace = document.getElementById('workspace-read-' + tier);
            const fillWorkspace = document.getElementById('workspace-fill-' + tier);
            const guessBtn = document.getElementById('mode-btn-guess-' + tier);
            const readBtn = document.getElementById('mode-btn-read-' + tier);

            // Reset all 3 buttons
            [guessBtn, fillBtn, readBtn].forEach(b => {{
                if (b && !b.disabled) {{
                    b.style.background = 'transparent';
                    b.style.color = 'var(--text-muted)';
                    b.style.boxShadow = 'none';
                    b.classList.remove('active');
                }}
            }});

            if (mode === 'read') {{
                if (guessWorkspace) guessWorkspace.style.display = 'none';
                if (fillWorkspace) fillWorkspace.style.display = 'none';
                if (readWorkspace) readWorkspace.style.display = 'block';
                if (readBtn) {{
                    readBtn.style.background = 'var(--surface-2)';
                    readBtn.style.color = 'var(--success)';
                    readBtn.style.boxShadow = '0 1px 3px rgba(0,0,0,0.2)';
                    readBtn.classList.add('active');
                }}
            }} else if (mode === 'fill') {{
                if (guessWorkspace) guessWorkspace.style.display = 'none';
                if (readWorkspace) readWorkspace.style.display = 'none';
                if (fillWorkspace) fillWorkspace.style.display = 'block';
                if (fillBtn) {{
                    fillBtn.style.background = 'var(--surface-2)';
                    fillBtn.style.color = 'var(--success)';
                    fillBtn.style.boxShadow = '0 1px 3px rgba(0,0,0,0.2)';
                    fillBtn.classList.add('active');
                }}
                if (window.cmFillEditors && window.cmFillEditors[tier] && typeof window.cmFillEditors[tier].refresh === 'function') {{
                    setTimeout(() => {{ window.cmFillEditors[tier].refresh(); }}, 20);
                }}
            }} else {{
                if (readWorkspace) readWorkspace.style.display = 'none';
                if (fillWorkspace) fillWorkspace.style.display = 'none';
                if (guessWorkspace) guessWorkspace.style.display = 'block';
                if (guessBtn) {{
                    guessBtn.style.background = 'var(--surface-2)';
                    guessBtn.style.color = 'var(--accent)';
                    guessBtn.style.boxShadow = '0 1px 3px rgba(0,0,0,0.2)';
                    guessBtn.classList.add('active');
                }}
                if (window.cmEditors && window.cmEditors[tier] && typeof window.cmEditors[tier].refresh === 'function') {{
                    setTimeout(() => {{ window.cmEditors[tier].refresh(); }}, 20);
                }}
            }}
        }}

        function switchMilestoneGuessFile(tier, fileIdx, filePath) {{
            window.guessFileDrafts[tier] = window.guessFileDrafts[tier] || {{}};
            const prevIdx = (window.activeGuessFileIdx[tier] !== undefined) ? window.activeGuessFileIdx[tier] : 0;

            // Save currently active draft
            let currentCode = '';
            if (window.cmEditors && window.cmEditors[tier]) {{
                currentCode = window.cmEditors[tier].getValue();
            }} else {{
                const ta = document.getElementById('code-editor-' + tier);
                currentCode = ta ? ta.value : '';
            }}
            window.guessFileDrafts[tier][prevIdx] = currentCode;

            // Update active tab buttons
            const tabs = document.querySelectorAll('[id^="guess-tab-btn-' + tier + '-"]');
            tabs.forEach(t => {{
                t.style.background = 'transparent';
                t.style.color = 'var(--text-muted)';
                t.style.borderColor = 'var(--border)';
                t.classList.remove('active');
            }});

            const activeTab = document.getElementById('guess-tab-btn-' + tier + '-' + fileIdx);
            if (activeTab) {{
                activeTab.style.background = 'var(--surface-2)';
                activeTab.style.color = 'var(--accent)';
                activeTab.style.borderColor = 'var(--brass-border)';
                activeTab.classList.add('active');
            }}

            // Update target filename label in task instructions banner
            const targetNameEl = document.getElementById('guess-target-filename-' + tier);
            if (targetNameEl && filePath) {{
                targetNameEl.textContent = filePath;
            }}

            // Restore draft for the newly selected file (defaulting to starter signature stub if no draft yet)
            let newDraft = window.guessFileDrafts[tier][fileIdx];
            if (newDraft === undefined) {{
                const fileData = (window.fillFilesData && window.fillFilesData[tier] && window.fillFilesData[tier][fileIdx]) ? window.fillFilesData[tier][fileIdx] : null;
                if (fileData && fileData.try_it_stub && fileData.has_real_source !== false) {{
                    newDraft = fileData.try_it_stub;
                }} else {{
                    newDraft = '';
                }}
            }}
            if (window.cmEditors && window.cmEditors[tier]) {{
                window.cmEditors[tier].setValue(newDraft);
                setTimeout(() => {{ window.cmEditors[tier].refresh(); }}, 20);
            }}
            const ta = document.getElementById('code-editor-' + tier);
            if (ta) ta.value = newDraft;

            // Update starter code unavailable notice visibility
            const starterNoticeEl = document.getElementById('starter-unavailable-notice-' + tier);
            if (starterNoticeEl) {{
                const fileData = (window.fillFilesData && window.fillFilesData[tier] && window.fillFilesData[tier][fileIdx]) ? window.fillFilesData[tier][fileIdx] : null;
                if (fileData && fileData.has_scaffold === false && (!newDraft || !newDraft.trim())) {{
                    starterNoticeEl.style.display = 'flex';
                }} else {{
                    starterNoticeEl.style.display = 'none';
                }}
            }}

            window.activeGuessFileIdx[tier] = fileIdx;
        }}

        function switchMilestoneFillFile(tier, fileIdx, filePath) {{
            window.fillFileDrafts[tier] = window.fillFileDrafts[tier] || {{}};
            const prevIdx = (window.activeFillFileIdx[tier] !== undefined) ? window.activeFillFileIdx[tier] : 0;

            // Save currently active draft
            let currentCode = '';
            if (window.cmFillEditors && window.cmFillEditors[tier]) {{
                currentCode = window.cmFillEditors[tier].getValue();
            }} else {{
                const ta = document.getElementById('code-editor-fill-' + tier);
                currentCode = ta ? ta.value : '';
            }}
            window.fillFileDrafts[tier][prevIdx] = currentCode;

            // Update active tab buttons
            const tabs = document.querySelectorAll('[id^="fill-tab-btn-' + tier + '-"]');
            tabs.forEach(t => {{
                t.style.background = 'transparent';
                t.style.color = 'var(--text-muted)';
                t.style.borderColor = 'var(--border)';
                t.classList.remove('active');
            }});

            const activeTab = document.getElementById('fill-tab-btn-' + tier + '-' + fileIdx);
            if (activeTab) {{
                activeTab.style.background = 'var(--surface-2)';
                activeTab.style.color = 'var(--success)';
                activeTab.style.borderColor = 'var(--teal-border)';
                activeTab.classList.add('active');
            }}

            // Look up target file data
            const fileData = (window.fillFilesData && window.fillFilesData[tier] && window.fillFilesData[tier][fileIdx]) ? window.fillFilesData[tier][fileIdx] : null;

            // Update target filename label in task instructions banner
            const targetNameEl = document.getElementById('fill-target-filename-' + tier);
            if (targetNameEl && fileData) {{
                targetNameEl.textContent = fileData.filename || filePath;
            }}

            // Update blanked chips
            const chipsEl = document.getElementById('fill-blanked-chips-' + tier);
            if (chipsEl && fileData) {{
                chipsEl.innerHTML = renderGroupedFillChips(fileData.blanked_functions, fileData.reason);
            }}

            // Restore draft or initial scaffold code
            let targetCode = '';
            if (window.fillFileDrafts[tier][fileIdx] !== undefined) {{
                targetCode = window.fillFileDrafts[tier][fileIdx];
            }} else if (fileData && fileData.scaffold_code) {{
                targetCode = fileData.scaffold_code;
            }}

            if (window.cmFillEditors && window.cmFillEditors[tier]) {{
                window.cmFillEditors[tier].setValue(targetCode);
                setTimeout(() => {{ window.cmFillEditors[tier].refresh(); }}, 20);
            }}
            const ta = document.getElementById('code-editor-fill-' + tier);
            if (ta) ta.value = targetCode;

            window.activeFillFileIdx[tier] = fileIdx;
        }}

        function switchMilestoneReadFile(tier, fileIdx) {{
            const panes = document.querySelectorAll('[id^="read-file-pane-' + tier + '-"]');
            panes.forEach(p => {{ p.style.display = 'none'; }});

            const targetPane = document.getElementById('read-file-pane-' + tier + '-' + fileIdx);
            if (targetPane) targetPane.style.display = 'block';

            const tabs = document.querySelectorAll('[id^="read-tab-btn-' + tier + '-"]');
            tabs.forEach(t => {{
                t.style.background = 'transparent';
                t.style.color = 'var(--text-muted)';
                t.style.borderColor = 'var(--border)';
                t.classList.remove('active');
            }});

            const activeTab = document.getElementById('read-tab-btn-' + tier + '-' + fileIdx);
            if (activeTab) {{
                activeTab.style.background = 'var(--surface-2)';
                activeTab.style.color = 'var(--success)';
                activeTab.style.borderColor = 'var(--teal-border)';
                activeTab.classList.add('active');
            }}
        }}

        function initMilestoneModes() {{
            let savedMode = 'guess';
            try {{
                savedMode = localStorage.getItem('backtrace_milestone_mode') || 'guess';
            }} catch(e) {{}}

            if (savedMode === 'read' || savedMode === 'fill') {{
                document.querySelectorAll('[id^="milestone-editor-card-"]').forEach(el => {{
                    const tierStr = el.id.replace('milestone-editor-card-', '');
                    const tier = parseInt(tierStr, 10);
                    if (!isNaN(tier)) {{
                        switchMilestoneMode(tier, savedMode);
                    }}
                }});
            }}
        }}

        // Graph Readability & Interaction Logic
        let dagTransform = {{ x: 0, y: 0, scale: 1.0 }};
        let selectedDagNodeId = null;
        let selectedDagTier = null;
        let showingAllFiles = false;

        const SVG_TOTAL_W = {svg_width};
        const SVG_TOTAL_H = {svg_height};
        const ORIGINAL_NODE_COUNT = {node_count};
        const TOTAL_REPO_FILES = {real_total_files};

        function applyDagTransform() {{
            const layer = document.getElementById('dag-panzoom-layer');
            if (layer) {{
                layer.setAttribute('transform', 'translate(' + dagTransform.x + ', ' + dagTransform.y + ') scale(' + dagTransform.scale + ')');
            }}
        }}

        // Fix 4: Fit graph to view on load
        function fitDagGraph() {{
            const container = document.getElementById('dag-visual-container');
            if (!container) return;
            const cw = container.clientWidth || 900;
            const ch = container.clientHeight || 500;
            const pad = 24;
            const scale = Math.min((cw - pad * 2) / SVG_TOTAL_W, (ch - pad * 2) / SVG_TOTAL_H, 1.0);
            const clampedScale = Math.max(0.18, scale);
            const x = Math.max(pad, (cw - SVG_TOTAL_W * clampedScale) / 2);
            const y = Math.max(pad, (ch - SVG_TOTAL_H * clampedScale) / 2);
            dagTransform = {{ x: x, y: y, scale: clampedScale }};
            applyDagTransform();
        }}

        function resetDagZoom() {{
            closeDagInspector();
            const input = document.getElementById('dag-search-input');
            if (input) input.value = '';
            filterDagNodes('');
            fitDagGraph();
        }}

        // Fix 4: Pan and zoom handlers (wheel to zoom, drag to move)
        function initDagPanZoom() {{
            const container = document.getElementById('dag-visual-container');
            if (!container || container._panZoomInited) return;
            container._panZoomInited = true;

            let isPanning = false;
            let startX = 0;
            let startY = 0;
            let initialTransformX = 0;
            let initialTransformY = 0;

            container.addEventListener('wheel', function(e) {{
                e.preventDefault();
                const rect = container.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const mouseY = e.clientY - rect.top;

                const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
                const newScale = Math.min(Math.max(0.15, dagTransform.scale * zoomFactor), 3.0);

                dagTransform.x = mouseX - (mouseX - dagTransform.x) * (newScale / dagTransform.scale);
                dagTransform.y = mouseY - (mouseY - dagTransform.y) * (newScale / dagTransform.scale);
                dagTransform.scale = newScale;
                applyDagTransform();
            }}, {{ passive: false }});

            container.addEventListener('mousedown', function(e) {{
                if (e.target.closest && (e.target.closest('.dag-node') || e.target.closest('#dag-node-inspector'))) {{
                    return;
                }}
                isPanning = true;
                startX = e.clientX;
                startY = e.clientY;
                initialTransformX = dagTransform.x;
                initialTransformY = dagTransform.y;
                container.style.cursor = 'grabbing';
            }});

            window.addEventListener('mousemove', function(e) {{
                if (!isPanning) return;
                dagTransform.x = initialTransformX + (e.clientX - startX);
                dagTransform.y = initialTransformY + (e.clientY - startY);
                applyDagTransform();
            }});

            window.addEventListener('mouseup', function() {{
                if (isPanning) {{
                    isPanning = false;
                    container.style.cursor = 'grab';
                }}
            }});

            fitDagGraph();
        }}

        // Graph Search Filter
        function filterDagNodes(query) {{
            query = (query || '').toLowerCase().trim();
            const nodes = document.querySelectorAll('.dag-node');
            const edges = document.querySelectorAll('.dag-edge');

            if (!query) {{
                if (selectedDagNodeId) {{
                    selectDagNode(selectedDagNodeId);
                }} else {{
                    nodes.forEach(n => {{ n.style.opacity = '1'; }});
                    edges.forEach(e => {{
                        e.style.opacity = '0.4';
                        e.setAttribute('stroke', 'var(--hairline-strong)');
                        e.setAttribute('stroke-width', '1');
                        e.setAttribute('marker-end', 'url(#dag-arrow)');
                    }});
                }}
                return;
            }}

            const matchedIds = new Set();
            nodes.forEach(n => {{
                const id = (n.getAttribute('data-node-id') || '').toLowerCase();
                const domain = (n.getAttribute('data-domain') || '').toLowerCase();
                if (id.includes(query) || domain.includes(query)) {{
                    n.style.opacity = '1';
                    matchedIds.add(n.getAttribute('data-node-id'));
                }} else {{
                    n.style.opacity = '0.15';
                }}
            }});

            edges.forEach(e => {{
                const src = e.getAttribute('data-source');
                const tgt = e.getAttribute('data-target');
                if (matchedIds.has(src) || matchedIds.has(tgt)) {{
                    e.style.opacity = '0.9';
                    e.setAttribute('stroke', 'var(--accent)');
                    e.setAttribute('stroke-width', '2');
                    e.setAttribute('marker-end', 'url(#dag-arrow-active)');
                }} else {{
                    e.style.opacity = '0.08';
                    e.setAttribute('stroke', 'var(--hairline-strong)');
                    e.setAttribute('stroke-width', '1');
                    e.setAttribute('marker-end', 'url(#dag-arrow)');
                }}
            }});
        }}

        // Hover node highlighting
        function hoverDagNode(nodeId) {{
            if (selectedDagNodeId) return;
            const nodes = document.querySelectorAll('.dag-node');
            const edges = document.querySelectorAll('.dag-edge');

            const connectedSources = new Set();
            const connectedTargets = new Set();

            edges.forEach(e => {{
                const src = e.getAttribute('data-source');
                const tgt = e.getAttribute('data-target');
                if (src === nodeId) {{
                    connectedTargets.add(tgt);
                    e.style.opacity = '1';
                    e.setAttribute('stroke', 'var(--accent)');
                    e.setAttribute('stroke-width', '2');
                    e.setAttribute('marker-end', 'url(#dag-arrow-active)');
                }} else if (tgt === nodeId) {{
                    connectedSources.add(src);
                    e.style.opacity = '1';
                    e.setAttribute('stroke', 'var(--success)');
                    e.setAttribute('stroke-width', '2');
                    e.setAttribute('marker-end', 'url(#dag-arrow-active)');
                }} else {{
                    e.style.opacity = '0.08';
                }}
            }});

            nodes.forEach(n => {{
                const id = n.getAttribute('data-node-id');
                if (id === nodeId || connectedSources.has(id) || connectedTargets.has(id)) {{
                    n.style.opacity = '1';
                }} else {{
                    n.style.opacity = '0.25';
                }}
            }});
        }}

        function unhoverDagNode() {{
            if (selectedDagNodeId) return;
            const searchVal = document.getElementById('dag-search-input')?.value;
            if (searchVal) {{
                filterDagNodes(searchVal);
                return;
            }}
            const nodes = document.querySelectorAll('.dag-node');
            const edges = document.querySelectorAll('.dag-edge');
            nodes.forEach(n => {{ n.style.opacity = '1'; }});
            edges.forEach(e => {{
                e.style.opacity = '0.4';
                e.setAttribute('stroke', 'var(--hairline-strong)');
                e.setAttribute('stroke-width', '1');
                e.setAttribute('marker-end', 'url(#dag-arrow)');
            }});
        }}

        // Fix 9: Side panel on node click (file path, imported by deduped, imports, link Open milestone)
        // Fix 3: Edges full opacity, other nodes drop to 25% opacity, other edges to 8%
        // Fix 8: Confidence dots with meaning (high green #10B981, medium amber #F59E0B, low grey #94A3B8)
        function selectDagNode(nodeId) {{
            if (!nodeId) return;
            const node = GRAPH_NODES.find(n => (n.id === nodeId || n.path === nodeId || n.name === nodeId));
            const inspector = document.getElementById('dag-node-inspector');
            if (!node || !inspector) return;

            selectedDagNodeId = nodeId;
            selectedDagTier = node.tier !== undefined ? node.tier : 1;

            inspector.style.display = 'flex';

            const labelEl = document.getElementById('inspect-label');
            if (labelEl) labelEl.textContent = node.label || (node.path ? node.path.split('/').pop() : node.id);

            const pathEl = document.getElementById('inspect-path');
            if (pathEl) pathEl.textContent = node.path || node.id;

            const tierEl = document.getElementById('inspect-tier');
            if (tierEl) tierEl.textContent = 'Tier ' + (node.tier !== undefined ? node.tier : '—');

            const domainEl = document.getElementById('inspect-domain');
            if (domainEl) domainEl.textContent = (node.domain || node.type || 'CORE').toUpperCase();

            const dot = document.getElementById('inspect-dot');
            if (dot) {{
                const conf = (node.confidence || 'high').toLowerCase();
                const confColor = conf === 'high' ? '#10B981' : (conf === 'medium' ? '#F59E0B' : '#94A3B8');
                dot.style.background = confColor;
                dot.className = 'chip-dot ' + (conf === 'high' ? 'teal' : (conf === 'medium' ? 'amber' : 'grey'));
            }}

            const milestoneLink = document.getElementById('inspect-milestone-link');
            if (milestoneLink) {{
                milestoneLink.dataset.tier = selectedDagTier;
                milestoneLink.onclick = function() {{
                    openNodeMilestone(selectedDagTier);
                    return false;
                }};
            }}

            const exp = node.exports || [];
            const expText = Array.isArray(exp) ? (exp.length ? exp.join(', ') : 'None declared') : (exp || 'None declared');
            const exportsEl = document.getElementById('inspect-exports');
            if (exportsEl) exportsEl.textContent = expText;

            const normNodeId = (node.id || '').split('\\\\').join('/').toLowerCase();
            const normNodePath = (node.path || '').split('\\\\').join('/').toLowerCase();
            const nodeName = normNodePath.split('/').pop();

            function matchNode(targetVal) {{
                if (!targetVal) return false;
                const norm = String(targetVal).split('\\\\').join('/').toLowerCase();
                return norm === normNodeId || norm === normNodePath || norm.split('/').pop() === nodeName;
            }}

            const inDepsSet = new Set();
            const outDepsSet = new Set();

            GRAPH_EDGES.forEach(e => {{
                const src = e.source || e.source_file || e.source_path || '';
                const tgt = e.target || e.target_file || '';
                if (matchNode(tgt) && src && !matchNode(src)) {{
                    inDepsSet.add(src);
                }}
                if (matchNode(src) && tgt && !matchNode(tgt)) {{
                    outDepsSet.add(tgt);
                }}
            }});

            const inDeps = Array.from(inDepsSet).sort();
            const outDeps = Array.from(outDepsSet).sort();

            const inTitleEl = document.getElementById('inspect-imported-by-title');
            if (inTitleEl) inTitleEl.textContent = 'Imported By (' + inDeps.length + ')';
            const inEl = document.getElementById('inspect-imported-by');
            if (inEl) {{
                if (!inDeps.length) {{
                    inEl.innerHTML = '<span style="color: var(--text-muted);">None (Entry Point)</span>';
                }} else {{
                    inEl.innerHTML = inDeps.map(dep => {{
                        const fname = dep.split('\\\\').join('/').split('/').pop();
                        return '<div style="cursor: pointer; padding: 2px 0; color: var(--text); text-decoration: underline; text-underline-offset: 2px;" data-dep="' + dep + '" onclick="selectDagNode(this.dataset.dep)" title="' + dep + '">' + fname + '</div>';
                    }}).join('');
                }}
            }}

            const outTitleEl = document.getElementById('inspect-imports-title');
            if (outTitleEl) outTitleEl.textContent = 'Imports (' + outDeps.length + ')';
            const outEl = document.getElementById('inspect-imports');
            if (outEl) {{
                if (!outDeps.length) {{
                    outEl.innerHTML = '<span style="color: var(--text-muted);">None (Leaf Node)</span>';
                }} else {{
                    outEl.innerHTML = outDeps.map(dep => {{
                        const fname = dep.split('\\\\').join('/').split('/').pop();
                        return '<div style="cursor: pointer; padding: 2px 0; color: var(--text); text-decoration: underline; text-underline-offset: 2px;" data-dep="' + dep + '" onclick="selectDagNode(this.dataset.dep)" title="' + dep + '">' + fname + '</div>';
                    }}).join('');
                }}
            }}

            // Fix 3: Edges & Nodes opacity rules
            const edges = document.querySelectorAll('.dag-edge');
            const nodes = document.querySelectorAll('.dag-node');

            edges.forEach(e => {{
                const src = e.getAttribute('data-source');
                const tgt = e.getAttribute('data-target');
                if (src === nodeId) {{
                    e.style.opacity = '1.0';
                    e.setAttribute('stroke', 'var(--accent)');
                    e.setAttribute('stroke-width', '2');
                    e.setAttribute('marker-end', 'url(#dag-arrow-active)');
                }} else if (tgt === nodeId) {{
                    e.style.opacity = '1.0';
                    e.setAttribute('stroke', 'var(--success)');
                    e.setAttribute('stroke-width', '2');
                    e.setAttribute('marker-end', 'url(#dag-arrow-active)');
                }} else {{
                    e.style.opacity = '0.08';
                    e.setAttribute('stroke', 'var(--hairline-strong)');
                    e.setAttribute('stroke-width', '1');
                    e.setAttribute('marker-end', 'url(#dag-arrow)');
                }}
            }});

            nodes.forEach(n => {{
                const id = n.getAttribute('data-node-id');
                const box = n.querySelector('.dag-node-box');
                if (id === nodeId) {{
                    n.style.opacity = '1.0';
                    if (box) {{
                        box.setAttribute('stroke', 'var(--accent)');
                        box.setAttribute('stroke-width', '2');
                    }}
                }} else if (inDepsSet.has(id) || outDepsSet.has(id)) {{
                    n.style.opacity = '1.0';
                    if (box) {{
                        box.setAttribute('stroke', 'var(--hairline-strong)');
                        box.setAttribute('stroke-width', '1.5');
                    }}
                }} else {{
                    n.style.opacity = '0.25';
                    if (box) {{
                        box.setAttribute('stroke', 'var(--border)');
                        box.setAttribute('stroke-width', '1');
                    }}
                }}
            }});
        }}

        function closeDagInspector() {{
            selectedDagNodeId = null;
            selectedDagTier = null;
            const inspector = document.getElementById('dag-node-inspector');
            if (inspector) inspector.style.display = 'none';

            const edges = document.querySelectorAll('.dag-edge');
            const nodes = document.querySelectorAll('.dag-node');
            nodes.forEach(n => {{
                n.style.opacity = '1.0';
                const box = n.querySelector('.dag-node-box');
                if (box) {{
                    box.setAttribute('stroke', 'var(--border)');
                    box.setAttribute('stroke-width', '1');
                }}
            }});
            edges.forEach(e => {{
                e.style.opacity = '0.4';
                e.setAttribute('stroke', 'var(--hairline-strong)');
                e.setAttribute('stroke-width', '1');
                e.setAttribute('marker-end', 'url(#dag-arrow)');
            }});
        }}

        // Fix 9: Link "Open milestone"
        function openNodeMilestone(tier) {{
            const t = tier !== undefined && tier !== null ? tier : (selectedDagTier || 1);
            switchReportTab('milestones');
            setTimeout(() => {{
                const target = document.getElementById('milestone-item-' + t) || document.querySelector('[data-milestone-tier="' + t + '"]');
                if (target) {{
                    target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                    const details = target.querySelector('details');
                    if (details) details.open = true;
                }}
            }}, 100);
        }}

        // Fix 6: Toggle List / Graph
        function toggleGraphViewMode() {{
            const visual = document.getElementById('dag-visual-container');
            const table = document.getElementById('dag-table-container');
            const btn = document.getElementById('toggle-view-btn');
            const inspector = document.getElementById('dag-node-inspector');
            if (!visual || !table || !btn) return;

            if (visual.style.display === 'none') {{
                visual.style.display = 'block';
                table.style.display = 'none';
                btn.textContent = 'List';
                requestAnimationFrame(() => fitDagGraph());
            }} else {{
                visual.style.display = 'none';
                table.style.display = 'block';
                if (inspector) inspector.style.display = 'none';
                btn.textContent = 'Graph';
            }}
        }}

        // Fix 1: Small Legend button at top-right opens popup panel
        function toggleDagLegend() {{
            const panel = document.getElementById('dag-legend-panel');
            const btn = document.getElementById('toggle-legend-btn');
            if (!panel || !btn) return;
            if (panel.style.display === 'none' || !panel.style.display) {{
                panel.style.display = 'flex';
                btn.classList.add('active');
            }} else {{
                panel.style.display = 'none';
                btn.classList.remove('active');
            }}
        }}

        // Fix 5: Explain node count & toggle "Show all files"
        function toggleAllFiles() {{
            const btn = document.getElementById('toggle-all-files-btn');
            const explainer = document.getElementById('dag-count-explainer');
            if (!btn || !explainer) return;

            showingAllFiles = !showingAllFiles;
            if (showingAllFiles) {{
                btn.textContent = 'Show top connected';
                explainer.textContent = 'Showing all ' + TOTAL_REPO_FILES + ' files of ' + TOTAL_REPO_FILES + '.';
            }} else {{
                btn.textContent = 'Show all files';
                explainer.textContent = 'Showing the ' + ORIGINAL_NODE_COUNT + ' most connected files of ' + TOTAL_REPO_FILES + '.';
            }}
        }}

        // Fullscreen toggle for Dependency Graph
        function toggleGraphFullscreen(forceState) {{
            const card = document.getElementById('section-graph');
            const btn = document.getElementById('dag-fullscreen-btn');
            const container = document.getElementById('dag-visual-container');
            if (!card || !btn) return;

            const scrollLeft = container ? container.scrollLeft : 0;
            const scrollTop = container ? container.scrollTop : 0;

            if (typeof forceState === 'boolean') {{
                if (forceState) {{
                    card.classList.add('graph-fullscreen');
                }} else {{
                    card.classList.remove('graph-fullscreen');
                }}
            }} else {{
                card.classList.toggle('graph-fullscreen');
            }}

            const isFullscreen = card.classList.contains('graph-fullscreen');
            btn.innerHTML = isFullscreen ? '✕ Minimize' : '⛶ Maximize';
            btn.title = isFullscreen ? 'Exit Fullscreen' : 'Toggle Fullscreen';

            requestAnimationFrame(() => {{
                fitDagGraph();
            }});
        }}

        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') {{
                const card = document.getElementById('section-graph');
                if (card && card.classList.contains('graph-fullscreen')) {{
                    toggleGraphFullscreen(false);
                }}
            }}
        }});

        window.addEventListener('pagehide', function() {{
            const card = document.getElementById('section-graph');
            if (card && card.classList.contains('graph-fullscreen')) {{
                toggleGraphFullscreen(false);
            }}
        }});

        // Initialize DAG graph pan/zoom and fit to view on load
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', function() {{
                if (typeof initDagPanZoom === 'function') initDagPanZoom();
                if (typeof fitDagGraph === 'function') fitDagGraph();
            }});
        }} else {{
            if (typeof initDagPanZoom === 'function') initDagPanZoom();
            if (typeof fitDagGraph === 'function') fitDagGraph();
        }}

        // Quiz answer verification
        function verifyQuizAnswer(qNum, correctIdx) {{
            const radios = document.getElementsByName('quiz_q_' + qNum);
            let selectedVal = null;
            for (const r of radios) {{
                if (r.checked) {{
                    selectedVal = parseInt(r.value, 10);
                    break;
                }}
            }}
            const feedback = document.getElementById('quiz-feedback-' + qNum);
            const explanation = document.getElementById('quiz-explanation-' + qNum);
            if (!feedback) return;

            feedback.style.display = 'inline-block';
            if (selectedVal === null) {{
                feedback.style.background = 'var(--amber-soft)';
                feedback.style.color = 'var(--amber)';
                feedback.style.border = '1px solid var(--amber)';
                feedback.textContent = 'Please select an answer first';
                return;
            }}

            if (selectedVal === correctIdx) {{
                feedback.style.background = 'var(--teal-soft)';
                feedback.style.color = 'var(--success)';
                feedback.style.border = '1px solid var(--teal-border)';
                feedback.textContent = '✓ Correct — Verified Invariant';
            }} else {{
                feedback.style.background = 'var(--crimson-soft)';
                feedback.style.color = 'var(--crimson)';
                feedback.style.border = '1px solid var(--crimson)';
                feedback.textContent = '✗ Incorrect Selection';
            }}
            if (explanation) {{
                explanation.style.display = 'block';
            }}
        }}

        // Report Tab Navigation
        const VALID_REPORT_TABS = ['overview', 'graph', 'milestones', 'quiz'];

        function switchReportTab(tabKey, updateHash = true) {{
            if (!VALID_REPORT_TABS.includes(tabKey)) {{
                tabKey = 'overview';
            }}

            // If switching away from graph, exit fullscreen cleanly first
            if (tabKey !== 'graph') {{
                const graphCard = document.getElementById('section-graph');
                if (graphCard && graphCard.classList.contains('graph-fullscreen')) {{
                    toggleGraphFullscreen(false);
                }}
            }}

            VALID_REPORT_TABS.forEach(t => {{
                const btn = document.getElementById('tab-btn-' + t);
                const pane = document.getElementById('tab-pane-' + t);
                if (btn) {{
                    if (t === tabKey) {{
                        btn.classList.add('active');
                        btn.setAttribute('aria-selected', 'true');
                        try {{
                            btn.scrollIntoView({{ behavior: 'smooth', block: 'nearest', inline: 'center' }});
                        }} catch (e) {{}}
                    }} else {{
                        btn.classList.remove('active');
                        btn.setAttribute('aria-selected', 'false');
                    }}
                }}
                if (pane) {{
                    pane.style.display = (t === tabKey) ? 'block' : 'none';
                }}
            }});

            if (updateHash && window.location.hash !== '#' + tabKey) {{
                history.pushState(null, '', '#' + tabKey);
            }}

            // If switching to milestones, ensure CodeMirror editors refresh/init cleanly
            if (tabKey === 'milestones') {{
                setTimeout(() => {{
                    initCodeEditors();
                    initMilestoneModes();
                    if (window.cmEditors) {{
                        Object.values(window.cmEditors).forEach(cm => {{
                            if (cm && typeof cm.refresh === 'function') {{
                                cm.refresh();
                            }}
                        }});
                    }}
                }}, 50);
            }}

            // If switching to graph, initialize pan/zoom and fit to view
            if (tabKey === 'graph') {{
                setTimeout(() => {{
                    if (typeof initDagPanZoom === 'function') initDagPanZoom();
                    if (typeof fitDagGraph === 'function') fitDagGraph();
                }}, 50);
            }}
        }}

        function handleReportHashChange() {{
            const rawHash = window.location.hash.replace(/^#/, '').toLowerCase();
            let tab = rawHash;
            if (tab === 'section-overview' || tab === 'section-raw-markdown') tab = 'overview';
            else if (tab === 'section-graph') tab = 'graph';
            else if (tab === 'section-milestones' || tab.startsWith('milestone-')) tab = 'milestones';
            else if (tab === 'section-quiz') tab = 'quiz';

            if (VALID_REPORT_TABS.includes(tab)) {{
                switchReportTab(tab, false);
            }} else {{
                switchReportTab('overview', false);
            }}
            initMilestoneModes();
        }}

        window.addEventListener('popstate', handleReportHashChange);
        window.addEventListener('hashchange', handleReportHashChange);

        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', handleReportHashChange);
        }} else {{
            handleReportHashChange();
        }}
    </script>
    """

    codemirror_head = "" if is_showcase else """    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/dracula.min.css">
    <style>
        .CodeMirror {
            font-family: var(--font-mono) !important;
            font-size: 0.8125rem !important;
            height: 200px !important;
            border-radius: 4px;
            background: #181920 !important;
        }
        .CodeMirror-gutters {
            background: #121318 !important;
            border-right: 1px solid var(--border) !important;
        }
        .CodeMirror-linenumber {
            color: var(--text-muted) !important;
        }
    </style>
"""
    extra_head = codemirror_head + """
    <style>
        /* Tabbed Report Navigation Styles */
        .report-tabs-nav {
            display: flex;
            gap: 0.5rem;
            border-bottom: 1px solid var(--border);
            margin-bottom: 1.75rem;
            overflow-x: auto;
            padding-bottom: 0.25rem;
            scrollbar-width: thin;
        }
        .report-tab-btn {
            display: inline-flex;
            align-items: center;
            padding: 0.65rem 1.15rem;
            background: var(--surface-2);
            color: var(--text-muted);
            border: 1px solid var(--border);
            border-radius: 4px;
            font-family: 'IBM Plex Sans', sans-serif;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 120ms ease;
            white-space: nowrap;
        }
        .report-tab-btn:hover {
            color: var(--text);
            background: var(--panel-raised);
            border-color: var(--brass-border);
        }
        .report-tab-btn.active {
            color: var(--accent);
            background: var(--panel-raised);
            border-color: var(--accent);
            box-shadow: 0 0 0 1px var(--accent);
            font-weight: 600;
        }
        .report-tab-pane {
            animation: fadeInTab 150ms ease-out;
        }
        @keyframes fadeInTab {
            from { opacity: 0; transform: translateY(3px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Milestone Mode Switcher & Read-Only Viewer Styles */
        .milestone-mode-tab-btn:hover:not(:disabled) {
            color: var(--text) !important;
            background: var(--panel-raised) !important;
        }
        .read-file-tab-btn:hover {
            border-color: var(--success) !important;
            color: var(--success) !important;
        }
        .read-file-tab-btn.active {
            border-color: var(--teal-border) !important;
            background: var(--surface-2) !important;
            color: var(--success) !important;
            box-shadow: 0 0 0 1px var(--teal-border);
        }

        .kpi-card {
            background: var(--panel-raised);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 0.85rem 1rem;
            transition: all 120ms ease;
        }
        .kpi-card:hover {
            border-color: var(--brass-border);
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .kpi-label {
            font-family: var(--font-mono);
            font-size: 0.8125rem;
            font-weight: 600;
            color: var(--text-muted);
            margin-bottom: 0.2rem;
        }
        .kpi-value {
            font-family: var(--font-ui);
            font-size: 1.25rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 0.15rem;
        }
        .kpi-sub {
            font-size: 0.8125rem;
            color: var(--text-muted);
        }
        .entry-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.45rem 0.8rem;
            min-height: 38px;
            background: var(--panel-raised);
            border: 1px solid var(--hairline-soft);
            border-radius: 4px;
            transition: all 120ms ease;
            user-select: none;
            touch-action: manipulation;
        }
        .entry-chip:hover {
            border-color: var(--accent);
            background: var(--panel-overlay);
        }
        .entry-chip .entry-chip-arrow {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 28px;
            min-height: 28px;
            padding: 6px;
            margin: -6px 0 -6px -4px;
            border-radius: 3px;
            transition: background 120ms ease;
        }
        .entry-chip:hover .entry-chip-arrow {
            background: rgba(212, 163, 89, 0.15);
        }
        .dag-node-box {
            transition: stroke 150ms ease, fill 150ms ease, filter 150ms ease;
        }
        .dag-node:hover .dag-node-box {
            stroke: var(--accent);
            stroke-width: 2px;
            filter: drop-shadow(0 0 6px rgba(212, 163, 89, 0.25));
        }

        /* Fullscreen Graph Mode - Fix 7: Main nav remains visible */
        .nav-shell {
            z-index: 10001 !important;
        }
        #section-graph.graph-fullscreen {
            position: fixed !important;
            top: 57px !important;
            left: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            inset: 57px 0 0 0 !important;
            z-index: 9999 !important;
            margin: 0 !important;
            border-radius: 0 !important;
            background: var(--ink) !important;
            display: flex !important;
            flex-direction: column !important;
            overflow: hidden !important;
        }
        #section-graph.graph-fullscreen .card-header,
        #section-graph.graph-fullscreen > p,
        #section-graph.graph-fullscreen > div:first-of-type {
            flex-shrink: 0;
        }
        #section-graph.graph-fullscreen #dag-canvas-layout {
            flex: 1 1 auto !important;
            max-height: none !important;
            border-radius: 0 !important;
        }
        #section-graph.graph-fullscreen #dag-visual-container {
            max-height: none !important;
            flex: 1 1 auto !important;
            border-radius: 0 !important;
        }
        #section-graph.graph-fullscreen #dag-legend-panel {
            flex-shrink: 0;
            border-radius: 0;
        }
        #section-graph.graph-fullscreen #dag-table-container {
            max-height: none !important;
            flex: 1 1 auto !important;
        }
        #section-graph.graph-fullscreen #dag-node-inspector {
            max-height: none !important;
        }
        .chip-dot.grey {
            background: #94A3B8 !important;
        }
        @media (max-width: 640px) {
            #dag-canvas-layout {
                flex-direction: column !important;
                max-height: none !important;
            }
            #dag-visual-container {
                height: 320px !important;
                min-height: 320px !important;
            }
            #dag-node-inspector {
                width: 100% !important;
                border-left: none !important;
                border-top: 1px solid var(--border) !important;
                max-height: 300px !important;
            }
            .dag-hint {
                display: none !important;
            }
        }
        .milestone-item:last-child {
            margin-bottom: 0 !important;
        }

        /* Spine Vessel Styles */
        .milestone-vessel.not-started {
            background: var(--panel-raised) !important;
            border: 1px solid var(--hairline-strong) !important;
            color: var(--text-muted) !important;
            box-shadow: none !important;
        }
        .milestone-vessel.attempting {
            background: var(--panel-raised) !important;
            border: 2px solid var(--amber) !important;
            color: var(--amber) !important;
            box-shadow: 0 0 14px rgba(245, 158, 11, 0.3) !important;
            animation: pulse-amber 2s infinite ease-in-out;
        }
        .milestone-vessel.verified {
            background: rgba(45, 212, 191, 0.15) !important;
            border: 2px solid var(--success) !important;
            color: var(--success) !important;
            box-shadow: 0 0 14px rgba(45, 212, 191, 0.35) !important;
        }
        @keyframes pulse-amber {
            0%, 100% { box-shadow: 0 0 6px rgba(245, 158, 11, 0.2); }
            50% { box-shadow: 0 0 16px rgba(245, 158, 11, 0.45); }
        }
    </style>
    """

    back_link_html = """
                <a href="/showcase" style="display: inline-flex; align-items: center; gap: 0.4rem; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.5rem;">
                    &larr; BACK TO SHOWCASE DIRECTORY
                </a>""" if is_showcase else """
                <a href="/dashboard" style="display: inline-flex; align-items: center; gap: 0.4rem; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.5rem;">
                    &larr; BACK TO DASHBOARD LEDGER
                </a>"""

    reanalyze_btn_html = ""
    if is_commit_unchanged and not is_showcase:
        target_ref = sanitize_text(str(getattr(job, "commit_ref", "") or ""))
        target_sub = sanitize_text(str(getattr(job, "subpath", "") or ""))
        reanalyze_btn_html = f"""
        <form action="/analyses/submit" method="POST" style="margin: 0; display: inline;">
            <input type="hidden" name="repo_url" value="{repo_url}">
            <input type="hidden" name="commit_ref" value="{target_ref}">
            <input type="hidden" name="subpath" value="{target_sub}">
            <input type="hidden" name="reanalyze_anyway" value="true">
            <button type="submit" class="btn btn-secondary btn-sm" id="reanalyze-anyway-btn" title="Re-analyze repository version and charge quota">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="23 4 23 10 17 10"></polyline>
                    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                </svg>
                Re-analyze anyway
            </button>
        </form>
        """

    content = f"""
    <div style="max-width: 1040px; margin: 0 auto;">
        {showcase_banner_html}
        {no_history_note_html}
        <!-- Top Dossier Navigation & Meta Bar -->
        <div style="margin-bottom: 1.5rem; display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem;">
            <div>
                {back_link_html}
                <div style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
                    <h1 style="font-size: 2.15rem; font-weight: 500; letter-spacing: -0.02em;">Architecture Report: <span style="font-style: italic; color: var(--accent);">{repo_name}</span></h1>
                </div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 0.2rem;">
                    Codebase Intelligence Report &bull; Structural Syntax Tree &amp; Dependency Reconstruction
                </div>
                <div style="display: flex; align-items: center; gap: 0.75rem; font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.35rem; flex-wrap: wrap;">
                    <span>Target: <a href="{repo_url}" target="_blank" rel="noopener noreferrer" style="color: var(--text-muted);">{repo_url}</a></span>
                    <span>&bull;</span>
                    <span>Synthesized: {created_at}</span>
                    <span>&bull;</span>
                    <span>Duration: {duration}</span>
                </div>
            </div>
            <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                {reanalyze_btn_html}
                <a href="/reports/{job_id}/export.md" class="btn btn-secondary btn-sm" id="btn-export-markdown" download="report-{job_id}.md" title="Download report as Markdown">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                    Export as Markdown
                </a>
                <button onclick="window.print()" class="btn btn-secondary btn-sm" title="Print or save as PDF">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 6 2 18 2 18 9"></polyline>
                        <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path>
                        <rect x="6" y="14" width="12" height="8"></rect>
                    </svg>
                    Print Architecture Report
                </button>
            </div>
        </div>

        <!-- Tabbed Report Navigation Bar -->
        <div class="report-tabs-wrapper">
            <div class="report-tabs-nav" role="tablist" aria-label="Architecture Report Sections">
                <button type="button" class="report-tab-btn active" id="tab-btn-overview" onclick="switchReportTab('overview')" role="tab" aria-selected="true" aria-controls="tab-pane-overview">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 0.45rem;"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
                    Overview
                </button>
                <button type="button" class="report-tab-btn" id="tab-btn-graph" onclick="switchReportTab('graph')" role="tab" aria-selected="false" aria-controls="tab-pane-graph">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 0.45rem;"><circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line></svg>
                    Dependency Graph
                </button>
                <button type="button" class="report-tab-btn" id="tab-btn-milestones" onclick="switchReportTab('milestones')" role="tab" aria-selected="false" aria-controls="tab-pane-milestones">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 0.45rem;"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
                    Milestones
                </button>
                <button type="button" class="report-tab-btn" id="tab-btn-quiz" onclick="switchReportTab('quiz')" role="tab" aria-selected="false" aria-controls="tab-pane-quiz">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 0.45rem;"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                    Quiz
                </button>
            </div>
        </div>

        <!-- Tab 1: Overview Section -->
        <div class="report-tab-pane" id="tab-pane-overview" role="tabpanel" aria-labelledby="tab-btn-overview">
            {overview_section_html}
        </div>

        <!-- Tab 2: Visual Dependency Graph Section -->
        <div class="report-tab-pane" id="tab-pane-graph" role="tabpanel" aria-labelledby="tab-btn-graph" style="display: none;">
            {graph_section_html}
        </div>

        <!-- Tab 3: Milestones & Code Workspace Section -->
        <div class="report-tab-pane" id="tab-pane-milestones" role="tabpanel" aria-labelledby="tab-btn-milestones" style="display: none;">
            {sandbox_banner_html}
            {milestones_spine_html}
        </div>

        <!-- Tab 4: Codebase Mastery Quiz Section -->
        <div class="report-tab-pane" id="tab-pane-quiz" role="tabpanel" aria-labelledby="tab-btn-quiz" style="display: none;">
            {quiz_html}
        </div>
    </div>
    """
    return page_shell(
        repo_name,
        content,
        current_user=None if is_showcase else current_user,
        active_route="/showcase" if is_showcase else "/report",
        billing_status=None if is_showcase else billing_status,
        extra_head=extra_head,
        extra_scripts=extra_scripts,
    )



def settings_view(
    current_user: UserModel,
    billing_status: Dict[str, Any],
    pricing_details: Dict[str, Any],
    error: Optional[str] = None,
    success: Optional[str] = None,
    billing_error: bool = False,
) -> str:
    """
    Renders the Settings & Billing view.
    Adheres strictly to the bento-split layout with zero fabricated metrics or hardcoded prices.
    """
    is_paid = billing_status.get("tier") == "paid"
    monthly_usage = billing_status.get("monthly_usage", 0)
    monthly_quota = billing_status.get("monthly_quota", 5) or 5
    pct = min(100, int((monthly_usage / monthly_quota) * 100)) if not is_paid else 100
    meter_class = "high" if pct < 80 else ("medium" if pct < 100 else "low")

    # Renewal calculation (1st of next month UTC or period end)
    period_end_iso = billing_status.get("current_period_end")
    if period_end_iso:
        try:
            dt = datetime.fromisoformat(period_end_iso)
            renewal_str = dt.strftime("%b %d, %Y (%H:%M UTC)").upper()
        except Exception:
            renewal_str = str(period_end_iso).upper()
    else:
        now = datetime.now(timezone.utc)
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
        renewal_str = next_month.strftime("%b 01, %Y (00:00 UTC)").upper()

    user_avatar = sanitize_text(current_user.avatar_url) if current_user.avatar_url else ""
    username = sanitize_text(current_user.github_username or "archaeologist")
    email = sanitize_text(current_user.email or "No email synced")
    created_at = format_time_tag(current_user.created_at)

    pro_price_display = sanitize_text(
        pricing_details.get("price_display")
        or pricing_details.get("amount_formatted")
        or os.getenv("PRO_PRICE_DISPLAY", "$9 / month")
    )

    try:
        from app.core.config import get_settings
        _cfg = get_settings()
        free_limit = getattr(_cfg, "FREE_TIER_MONTHLY_LIMIT", 5)
        pro_limit = getattr(_cfg, "PRO_LIMIT", "Unlimited")
    except Exception:
        free_limit = 5
        pro_limit = "Unlimited"

    if billing_error or error == "We couldn't start checkout. Please try again in a few minutes.":
        error_html = '<div class="alert-error" style="margin-bottom: 1.5rem;">We couldn\'t start checkout. Please try again in a few minutes.</div>'
    elif error:
        error_html = f'<div class="alert-error" style="margin-bottom: 1.5rem;">{sanitize_text(error)}</div>'
    else:
        error_html = ""

    success_html = f'<div style="background: rgba(45, 212, 191, 0.1); border: 1px solid var(--success); color: var(--success); padding: 0.75rem 1rem; border-radius: 4px; margin-bottom: 1.5rem; font-size: 0.875rem;">{sanitize_text(success)}</div>' if success else ""

    avatar_markup = f'<img src="{user_avatar}" alt="@{username}" style="width: 52px; height: 52px; border-radius: 4px; object-fit: cover; border: 1px solid var(--border);">' if user_avatar else f'''
    <div style="width: 52px; height: 52px; border-radius: 4px; background: var(--brass-soft); border: 1px solid var(--brass-border); display: flex; align-items: center; justify-content: center; color: var(--accent);">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
        </svg>
    </div>
    '''

    tier_badge = '<span class="badge badge-completed">Pro</span>' if is_paid else '<span class="badge badge-free">Free</span>'

    # Right column plan card details
    if is_paid:
        plan_card_html = f"""
        <div class="stratum-card" style="margin-bottom: 1.5rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem;">
                <h2 style="font-size: 1.25rem; font-weight: 500;">Plan &amp; Allocations</h2>
                {tier_badge}
            </div>

            <div style="background: var(--panel-inset); padding: 1.25rem; border-radius: 4px; border: 1px solid var(--border); margin-bottom: 1.25rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); ">Active Subscription</span>
                    <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--success);">Unlimited analysis jobs</span>
                </div>
                <div class="meter" style="margin-bottom: 0.75rem;">
                    <div class="meter-fill high" style="width: 100%;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">
                    <span>Billing cycle:</span>
                    <span>Period ends {renewal_str}</span>
                </div>
            </div>

            <div style="background: var(--panel-raised); border: 1px solid var(--border); border-radius: 4px; padding: 1.25rem;">
                <div style="font-weight: 600; color: var(--text); margin-bottom: 0.35rem;">Test files</div>
                <p style="color: var(--text-muted); font-size: 0.85rem; line-height: 1.45; margin-bottom: 1rem;">
                    Your account has unlimited access to repository analysis and interactive dependency graphs.
                </p>
                <a href="/api/billing/portal" class="btn btn-secondary" style="width: 100%; justify-content: center; padding: 0.75rem;">
                    Manage Subscription &amp; Invoices &rarr;
                </a>
            </div>
        </div>
        """
    else:
        upgrade_card_html = ""
        if billing_enabled():
            upgrade_card_html = f"""
            <!-- Upgrade Card with Dynamic Stripe Price -->
            <div style="background: var(--panel-raised); border: 1px solid var(--brass-border); border-radius: 4px; padding: 1.5rem; position: relative; overflow: hidden; margin-top: 1.25rem;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem;">
                    <div>
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); font-weight: 600;">
                            Pro plan
                        </div>
                        <div style="display: flex; align-items: baseline; gap: 0.4rem; margin-top: 0.35rem;">
                            <span style="font-family: var(--font-ui); font-size: 2.25rem; font-weight: 500; color: var(--text);">{pro_price_display}</span>
                            {f'<span style="font-family: var(--font-mono); font-size: 13px; color: var(--text-muted);">/ {pricing_details.get("interval", "month")}</span>' if "/ " not in pro_price_display else ''}
                        </div>
                    </div>
                    <span class="badge" style="background: var(--brass-soft); color: var(--accent); border-color: var(--brass-border);">Recommended</span>
                </div>

                <div style="display: flex; flex-direction: column; gap: 0.6rem; margin-bottom: 1.5rem; font-size: 0.85rem; color: var(--text-muted); line-height: 1.4;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        <span>More analyses per month ({pro_limit} instead of {free_limit})</span>
                    </div>
                </div>

                <a href="/api/billing/checkout" class="btn btn-primary" style="width: 100%; justify-content: center; padding: 0.85rem; font-size: 0.95rem;">
                    Upgrade to Pro via Stripe &rarr;
                </a>
            </div>
            """

        plan_card_html = f"""
        <div class="stratum-card" style="margin-bottom: 1.5rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem;">
                <h2 style="font-size: 1.25rem; font-weight: 500;">Plan &amp; Allocations</h2>
                {tier_badge}
            </div>

            <!-- Quota Meter Box -->
            <div style="background: var(--panel-inset); padding: 1.25rem; border-radius: 4px; border: 1px solid var(--border);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); ">Billing Cycle Allocation</span>
                    <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--accent);">{monthly_usage} / {monthly_quota} consumed ({pct}%)</span>
                </div>
                <div class="meter" style="margin-bottom: 0.75rem;">
                    <div class="meter-fill {meter_class}" style="width: {pct}%;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">
                    <span>Resets on</span>
                    <span>{renewal_str}</span>
                </div>
            </div>

            {upgrade_card_html}
        </div>
        """

    content = f"""
    <!-- Settings Top Header -->
    <div style="display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 1.5rem; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border);">
        <div>
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.35rem;">
                <span class="chip-dot brass"></span>
                <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent); ">
                    Settings
                </span>
            </div>
            <h1 style="font-size: 2.25rem; font-weight: 500; letter-spacing: -0.02em; margin-bottom: 0.4rem;">
                Account &amp; Workspace Ledger
            </h1>
            <p style="color: var(--text-muted); font-size: 0.9375rem; max-width: 620px; line-height: 1.5;">
                Manage your connected GitHub identity, community preferences, and subscription allocations.
            </p>
        </div>
    </div>

    {error_html}
    {success_html}

    <!-- Bento Grid Layout: 2 Columns on Desktop -->
    <div class="settings-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 1.75rem; align-items: start; width: 100%; min-width: 0;">

        <!-- Left Column: Identity & Preferences & Themes & Data -->
        <div>
            <!-- Section 1: GitHub OAuth Identity Dossier -->
            <div class="stratum-card" style="margin-bottom: 1.5rem;">
                <div style="margin-bottom: 1.25rem;">
                    <h2 style="font-size: 1.25rem; font-weight: 500; margin: 0;">Account identity</h2>
                </div>

                <div style="display: flex; align-items: center; gap: 1.25rem; background: var(--panel-inset); padding: 1.25rem; border-radius: 4px; border: 1px solid var(--border); margin-bottom: 1rem;">
                    {avatar_markup}
                    <div>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink: 0;">
                                <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                            <span style="font-weight: 600; color: var(--text); font-size: 1.05rem;">
                                GitHub connected: <span style="font-family: var(--font-mono);">@{username}</span>
                            </span>
                        </div>
                        <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 0.2rem;">{email}</div>
                        <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-top: 0.35rem;">
                            Connected: {created_at}
                        </div>
                    </div>
                </div>

                <!-- Leaderboard Username Visibility Checkbox -->
                <form method="POST" action="/settings" style="margin-top: 1rem; padding-top: 0.85rem; border-top: 1px solid var(--hairline-soft);">
                    <label style="display: flex; align-items: center; gap: 0.65rem; cursor: pointer; font-size: 0.875rem; color: var(--text);">
                        <input type="checkbox" id="show_on_leaderboard" name="show_on_leaderboard" value="true" {'checked' if getattr(current_user, 'show_on_leaderboard', False) else ''} onchange="this.form.submit()" style="width: 17px; height: 17px; accent-color: var(--success); cursor: pointer;">
                        <span style="font-weight: 500;">Show my username on the leaderboard</span>
                    </label>
                    <noscript>
                        <button type="submit" class="btn btn-sm btn-secondary" style="margin-top: 0.5rem;">Save Preferences</button>
                    </noscript>
                </form>

                <div style="font-size: 0.8125rem; color: var(--text-muted); line-height: 1.45; background: var(--panel-raised); padding: 0.75rem 1rem; border-radius: 4px; border: 1px dashed var(--hairline-soft); margin-top: 1rem;">
                    Profile information and notification email are synced directly from GitHub OAuth. Profile modifications must be made within your GitHub account.
                </div>
            </div>

            <!-- Section 2: Visual Telemetry / Theme Matrix -->
            <div class="stratum-card" style="margin-bottom: 1.5rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h2 style="font-size: 1.25rem; font-weight: 500;">Theme</h2>
                    <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">Runtime: data-theme</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.85rem; line-height: 1.5; margin-bottom: 1.25rem;">
                    Select visual contrast protocol for parsing call graphs and code diffs. Settings persist across browser sessions in local storage.
                </p>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                    <!-- Dark Option -->
                    <button type="button" id="theme-card-dark" onclick="applyThemePreference('dark')" style="text-align: left; padding: 1rem; border-radius: 4px; background: var(--panel-inset); border: 2px solid var(--accent); cursor: pointer; transition: all 150ms ease;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--accent); ">Dark</span>
                            <span id="theme-check-dark" style="color: var(--accent); font-weight: bold; font-size: 0.875rem;">✓</span>
                        </div>
                        <div style="height: 24px; background: #0c0e11; border-radius: 2px; border: 1px solid #282a2d; margin-bottom: 0.5rem; display: flex; align-items: center; padding: 0 0.5rem; gap: 0.35rem;">
                            <div style="width: 8px; height: 8px; border-radius: 50%; background: #6ee7b7;"></div>
                            <div style="width: 24px; height: 4px; border-radius: 2px; background: #333538;"></div>
                        </div>
                        <div style="font-size: 0.8125rem; color: var(--text-muted); line-height: 1.35;">
                            Pitch-dark substrate with high-density sage & mint highlights.
                        </div>
                    </button>

                    <!-- Light Option -->
                    <button type="button" id="theme-card-light" onclick="applyThemePreference('light')" style="text-align: left; padding: 1rem; border-radius: 4px; background: var(--panel-inset); border: 2px solid var(--border); cursor: pointer; transition: all 150ms ease;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <span style="font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; color: var(--text); ">Light</span>
                            <span id="theme-check-light" style="color: var(--accent); font-weight: bold; font-size: 0.875rem; display: none;">✓</span>
                        </div>
                        <div style="height: 24px; background: #fbfbfd; border-radius: 2px; border: 1px solid #d3c4b3; margin-bottom: 0.5rem; display: flex; align-items: center; padding: 0 0.5rem; gap: 0.35rem;">
                            <div style="width: 8px; height: 8px; border-radius: 50%; background: #1b6d4b;"></div>
                            <div style="width: 24px; height: 4px; border-radius: 2px; background: #9c8f7f;"></div>
                        </div>
                        <div style="font-size: 0.8125rem; color: var(--text-muted); line-height: 1.35;">
                            High-readability paper print mode optimized for daylight.
                        </div>
                    </button>
                </div>

                <div style="display: flex; justify-content: space-between; align-items: center; background: var(--panel-raised); padding: 0.65rem 1rem; border-radius: 4px; font-size: 0.8125rem;">
                    <span style="color: var(--text-muted);">Editor shortcuts:</span>
                    <button type="button" class="btn btn-sm btn-ghost" onclick="applyThemePreference('system')" style="font-size: 0.8125rem;">
                        Detect my system
                    </button>
                </div>
            </div>

            <!-- Section 3: Data Management & Danger Zone -->
            <div class="stratum-card" style="margin-bottom: 1.5rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h2 style="font-size: 1.25rem; font-weight: 500;">Account Data &amp; Privacy</h2>
                    <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted);">Export and privacy</span>
                </div>
                <p style="color: var(--text-muted); font-size: 0.85rem; line-height: 1.5; margin-bottom: 1.25rem;">
                    Download a full JSON archive of your analyzed jobs, milestone progress, and quiz scores, or permanently delete your account.
                </p>

                <div style="display: flex; gap: 0.85rem; align-items: center; flex-wrap: wrap;">
                    <a href="/account/export.json" class="btn btn-secondary" id="btn-export-data" download style="display: inline-flex; align-items: center; gap: 0.5rem; text-decoration: none;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                        </svg>
                        Export my data
                    </a>

                    <button type="button" class="btn btn-ghost" id="btn-delete-account" onclick="openDeleteAccountModal()" style="color: var(--danger); border-color: rgba(239, 68, 68, 0.35); display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                        Delete my account
                    </button>
                </div>
            </div>

        </div>

        <!-- Right Column: Plan & Billing & Quota -->
        <div>
            {plan_card_html}
        </div>

    </div>

    <!-- Delete Account Confirmation Modal -->
    <div id="delete-account-modal" style="display: none; position: fixed; inset: 0; background: rgba(0, 0, 0, 0.75); z-index: 10000; align-items: center; justify-content: center; padding: 1.5rem;">
        <div style="background: var(--surface); border: 1px solid var(--danger); border-radius: 6px; max-width: 480px; width: 100%; padding: 1.75rem; box-shadow: 0 16px 36px rgba(0,0,0,0.5);">
            <div style="display: flex; align-items: center; gap: 0.75rem; color: var(--danger); margin-bottom: 1rem;">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                <h3 style="margin: 0; font-size: 1.25rem; font-weight: 600;">Delete Account</h3>
            </div>
            <p style="font-size: 0.875rem; color: var(--text-muted); line-height: 1.5; margin-bottom: 1rem;">
                This action is <strong>permanent</strong> and cannot be undone. All of your analyzed repositories, milestone progress, quiz scores, points history, and active sessions will be permanently purged.
            </p>
            <p style="font-size: 0.875rem; color: var(--text); margin-bottom: 0.75rem;">
                Please type your GitHub username <code style="background: var(--panel-inset); padding: 0.2rem 0.4rem; border-radius: 3px; font-weight: bold; color: var(--accent);">@{username}</code> to confirm:
            </p>
            <form id="delete-account-form" method="POST" action="/account/delete">
                <input type="text" id="delete-confirm-username" name="username" placeholder="{username}" autocomplete="off" required style="width: 100%; padding: 0.65rem 0.85rem; background: var(--panel-inset); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-family: var(--font-mono); font-size: 0.9rem; margin-bottom: 1.25rem;">
                <div style="display: flex; justify-content: flex-end; gap: 0.75rem;">
                    <button type="button" class="btn btn-secondary" onclick="closeDeleteAccountModal()">Cancel</button>
                    <button type="submit" id="btn-confirm-delete" class="btn btn-primary" style="background: var(--danger); border-color: var(--danger); color: #fff;" disabled>Permanently Delete Account</button>
                </div>
            </form>
        </div>
    </div>
    """

    extra_scripts = f"""
    <script>
        function applyThemePreference(theme) {{
            if (theme === 'system') {{
                const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
                const next = prefersDark ? 'dark' : 'light';
                document.documentElement.setAttribute('data-theme', next);
                localStorage.removeItem('backtrace-theme');
            }} else {{
                document.documentElement.setAttribute('data-theme', theme);
                localStorage.setItem('backtrace-theme', theme);
            }}
            updateThemeCards();
        }}

        function updateThemeCards() {{
            const active = document.documentElement.getAttribute('data-theme') || 'dark';
            const darkCard = document.getElementById('theme-card-dark');
            const lightCard = document.getElementById('theme-card-light');
            const darkCheck = document.getElementById('theme-check-dark');
            const lightCheck = document.getElementById('theme-check-light');

            if (darkCard && lightCard) {{
                if (active === 'dark') {{
                    darkCard.style.borderColor = 'var(--accent)';
                    lightCard.style.borderColor = 'var(--border)';
                    if (darkCheck) darkCheck.style.display = 'inline-flex';
                    if (lightCheck) lightCheck.style.display = 'none';
                }} else {{
                    lightCard.style.borderColor = 'var(--accent)';
                    darkCard.style.borderColor = 'var(--border)';
                    if (lightCheck) lightCheck.style.display = 'inline-flex';
                    if (darkCheck) darkCheck.style.display = 'none';
                }}
            }}
        }}

        function openDeleteAccountModal() {{
            const modal = document.getElementById('delete-account-modal');
            if (modal) {{
                modal.style.display = 'flex';
                const input = document.getElementById('delete-confirm-username');
                if (input) {{
                    input.value = '';
                    input.focus();
                }}
                const btn = document.getElementById('btn-confirm-delete');
                if (btn) btn.disabled = true;
            }}
        }}

        function closeDeleteAccountModal() {{
            const modal = document.getElementById('delete-account-modal');
            if (modal) modal.style.display = 'none';
        }}

        document.addEventListener('DOMContentLoaded', function() {{
            updateThemeCards();
            const input = document.getElementById('delete-confirm-username');
            const btn = document.getElementById('btn-confirm-delete');
            const expected = '{username}';
            if (input && btn) {{
                input.addEventListener('input', function() {{
                    btn.disabled = (this.value.trim() !== expected);
                }});
            }}
        }});
        setTimeout(updateThemeCards, 50);
    </script>
    """

    return page_shell(
        "Settings & Billing",
        content,
        current_user=current_user,
        active_route="/settings",
        billing_status=billing_status,
        extra_scripts=extra_scripts,
    )


def rewards_view(
    current_user: UserModel,
    billing_status: Dict[str, Any],
    points_balance: int,
    lifetime_points: int,
    badges: List[Dict[str, Any]],
    leaderboard_data: Dict[str, Any],
    ledger_entries: List[Any],
    error: Optional[str] = None,
    success: Optional[str] = None,
) -> str:
    """
    Renders the Points Economy, Software Perks, Achievement Badges, and Leaderboard view.
    """
    is_paid = billing_status.get("tier") == "paid"
    monthly_usage = billing_status.get("monthly_usage", 0)
    monthly_quota = billing_status.get("monthly_quota", 5) or 5
    quota_bonus = max(0, monthly_quota - 5) if not is_paid else 0

    earned_badges_count = sum(1 for b in badges if b.get("earned"))
    total_badges = len(badges)

    error_html = f'<div class="alert-error" style="margin-bottom: 1.5rem; border-radius: 4px; padding: 0.75rem 1rem; font-size: 0.875rem;">{sanitize_text(error)}</div>' if error else ""
    success_html = f'<div style="background: rgba(45, 212, 191, 0.1); border: 1px solid var(--success); color: var(--success); padding: 0.75rem 1rem; border-radius: 4px; margin-bottom: 1.5rem; font-size: 0.875rem; font-weight: 500;">{sanitize_text(success)}</div>' if success else ""

    # Quota Perk Action State
    can_redeem_quota = not is_paid and points_balance >= 100

    if is_paid:
        perk_button = """
        <div style="display: flex; flex-direction: column; gap: 0.5rem;">
            <button type="button" class="btn btn-secondary" disabled style="opacity: 0.75; cursor: not-allowed; width: 100%; justify-content: center; font-family: var(--font-ui); font-size: 0.8125rem;">
                👑 Pro Active (Unlimited Analyses)
            </button>
            <span style="font-size: 0.8125rem; color: var(--text-muted); text-align: center;">
                You are on Backtrace Pro with unlimited repository analyses. Extra quota redemption is not needed.
            </span>
        </div>
        """
    elif can_redeem_quota:
        perk_button = f"""
        <form method="POST" action="/rewards/redeem/quota">
            <button type="submit" id="btn-redeem-quota" class="btn btn-primary" style="width: 100%; justify-content: center; font-family: var(--font-ui); font-size: 0.8125rem; font-weight: 600; ">
                ⚡ Redeem +2 Repos (100 pts)
            </button>
        </form>
        """
    else:
        perk_button = f"""
        <button type="button" class="btn btn-secondary" disabled style="opacity: 0.5; cursor: not-allowed; width: 100%; justify-content: center; font-family: var(--font-ui); font-size: 0.8125rem;">
            Need 100 pts (Have {points_balance})
        </button>
        """

    # Render Badge Cards
    badges_html = ""
    for badge in badges:
        earned = badge.get("earned", False)
        earned_badge = """
        <span class="tag tag-brass" style="background: rgba(135, 90, 20, 0.2); color: var(--accent); border-color: var(--accent); font-size: 0.8125rem; font-weight: 600;">✓ Unlocked</span>
        """ if earned else """
        <span class="tag tag-ghost" style="color: var(--text-muted); font-size: 0.8125rem;">Locked</span>
        """
        card_border = "border-color: var(--accent); box-shadow: 0 0 12px rgba(135, 90, 20, 0.15);" if earned else "border-color: var(--border);"
        progress_val = badge.get("current_progress", 0)
        target_val = badge.get("target", 1)
        pct = badge.get("progress_pct", 0)

        badges_html += f"""
        <div class="card" style="padding: 1.25rem; {card_border} display: flex; flex-direction: column; justify-content: space-between; gap: 0.75rem;">
            <div>
                <div style="display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 0.5rem;">
                    <span style="font-size: 1.75rem; line-height: 1;">{badge.get('icon', '🎯')}</span>
                    {earned_badge}
                </div>
                <h4 style="font-size: 1rem; font-weight: 600; color: var(--text); margin-bottom: 0.2rem;">{sanitize_text(badge.get('name', ''))}</h4>
                <div style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--accent); margin-bottom: 0.4rem; ">{sanitize_text(badge.get('tagline', ''))}</div>
                <p style="font-size: 0.8125rem; color: var(--text-muted); line-height: 1.4;">{sanitize_text(badge.get('description', ''))}</p>
            </div>
            <div>
                <div style="display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.25rem;">
                    <span>Progress</span>
                    <span>{progress_val} / {target_val}</span>
                </div>
                <div style="width: 100%; height: 4px; background: var(--panel-raised); border-radius: 2px; overflow: hidden;">
                    <div style="width: {pct}%; height: 100%; background: var(--accent); transition: width 300ms ease;"></div>
                </div>
            </div>
        </div>
        """

    # Render Leaderboard Rows
    leaderboard_entries = leaderboard_data.get("leaderboard", [])
    user_rank = leaderboard_data.get("current_user_rank", 1)
    user_points = leaderboard_data.get("current_user_points", points_balance)

    leaderboard_rows = ""
    for entry in leaderboard_entries:
        is_me = entry.get("is_current_user", False)
        row_bg = "background: rgba(135, 90, 20, 0.08); font-weight: 600;" if is_me else ""
        rank_badge = "🥇" if entry["rank"] == 1 else ("🥈" if entry["rank"] == 2 else ("🥉" if entry["rank"] == 3 else f"#{entry['rank']}"))
        if entry.get("show_on_leaderboard", False) and entry['username'] != "Anonymous":
            username_cell = f'<span style="font-family: var(--font-mono); font-size: 0.875rem; color: var(--text);">@{sanitize_text(entry["username"])}</span>'
        else:
            username_cell = f'<span style="font-family: var(--font-mono); font-size: 0.875rem; color: var(--text-muted); font-style: italic;">Anonymous</span>'
        leaderboard_rows += f"""
        <tr style="{row_bg} border-bottom: 1px solid var(--hairline-soft);">
            <td style="padding: 0.75rem 1rem; font-family: var(--font-mono); font-size: 0.875rem; color: var(--accent);">{rank_badge}</td>
            <td style="padding: 0.75rem 1rem; display: flex; align-items: center; gap: 0.5rem;">
                {username_cell}
                {'<span class="tag tag-brass" style="font-size: 0.8125rem; padding: 0.1rem 0.35rem;">YOU</span>' if is_me else ''}
            </td>
            <td style="padding: 0.75rem 1rem; text-align: right; font-family: var(--font-mono); font-size: 0.875rem; font-weight: 600; color: #f59e0b;">
                {entry['points']} PTS
            </td>
        </tr>
        """

    # Render Ledger Rows
    ledger_rows = ""
    for e in ledger_entries[:20]:
        reason_label = sanitize_text(e.reason.replace("_", " ").title())
        pts = e.points_awarded
        pts_color = "#10b981" if pts > 0 else ("#ef4444" if pts < 0 else "var(--text-muted)")
        pts_prefix = "+" if pts > 0 else ""
        created_str = format_time_tag(e.created_at)

        ledger_rows += f"""
        <tr style="border-bottom: 1px solid var(--hairline-soft);">
            <td style="padding: 0.65rem 0.85rem; font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted);">{e.id}</td>
            <td style="padding: 0.65rem 0.85rem; font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted);">{created_str}</td>
            <td style="padding: 0.65rem 0.85rem; font-size: 0.8125rem; color: var(--text);">{reason_label}</td>
            <td style="padding: 0.65rem 0.85rem; font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); text-align: center;">Tier {e.milestone_tier if e.milestone_tier else '—'}</td>
            <td style="padding: 0.65rem 0.85rem; font-family: var(--font-mono); font-size: 0.8125rem; font-weight: 600; color: {pts_color}; text-align: right;">
                {pts_prefix}{pts} PTS
            </td>
        </tr>
        """

    content = f"""
    <main class="page-container" style="max-width: 1200px; margin: 0 auto; padding: 2rem 1.5rem;">
        {error_html}
        {success_html}

        <!-- Page Header -->
        <div style="margin-bottom: 2rem;">
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.35rem;">
                <span style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--accent);">
                    Economy & Perks
                </span>
            </div>
            <h1 style="font-size: 2.25rem; margin-bottom: 0.5rem;">Points & Rewards Protocol</h1>
            <p style="color: var(--text-muted); font-size: 0.9375rem; max-width: 760px;">
                Earn architectural points by solving progressive milestones. Redeem points for native software perks like monthly analysis quota, and unlock permanent badges.
            </p>
        </div>

        <!-- Metrics Overview Grid -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-bottom: 2.5rem;">
            <div class="card" style="padding: 1.25rem; border-color: var(--accent); background: var(--surface-2);">
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.35rem;">Active Point Balance</div>
                <div style="font-family: var(--font-ui); font-size: 2.5rem; font-weight: 600; color: #f59e0b; line-height: 1.1; margin-bottom: 0.35rem;">
                    {points_balance} <span style="font-size: 1.125rem; font-family: var(--font-mono); font-weight: 500;">PTS</span>
                </div>
                <div style="font-size: 0.8125rem; color: var(--text-muted);">
                    🕒 Points valid for 180 days (rolling expiry)
                </div>
            </div>

            <div class="card" style="padding: 1.25rem; background: var(--surface-2);">
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.35rem;">Lifetime Earned</div>
                <div style="font-family: var(--font-ui); font-size: 2.5rem; font-weight: 600; color: var(--text); line-height: 1.1; margin-bottom: 0.35rem;">
                    {lifetime_points} <span style="font-size: 1.125rem; font-family: var(--font-mono); font-weight: 500;">PTS</span>
                </div>
                <div style="font-size: 0.8125rem; color: var(--text-muted);">
                    All-time cumulative points awarded
                </div>
            </div>

            <div class="card" style="padding: 1.25rem; background: var(--surface-2);">
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.35rem;">Monthly Repo Quota</div>
                <div style="font-family: var(--font-ui); font-size: 2.5rem; font-weight: 600; color: var(--success); line-height: 1.1; margin-bottom: 0.35rem;">
                    {'UNLIMITED' if is_paid else f'{monthly_usage} / {monthly_quota}'}
                </div>
                <div style="font-size: 0.8125rem; color: var(--text-muted);">
                    {'Pro plan active' if is_paid else (f'+{quota_bonus} bonus slots active this month' if quota_bonus > 0 else 'Standard free allowance')}
                </div>
            </div>

            <div class="card" style="padding: 1.25rem; background: var(--surface-2);">
                <div style="font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); margin-bottom: 0.35rem;">Achievement Badges</div>
                <div style="font-family: var(--font-ui); font-size: 2.5rem; font-weight: 600; color: var(--accent); line-height: 1.1; margin-bottom: 0.35rem;">
                    {earned_badges_count} <span style="font-size: 1.125rem; font-family: var(--font-ui); font-weight: 500;">/ {total_badges}</span>
                </div>
                <div style="font-size: 0.8125rem; color: var(--text-muted);">
                    Architectural achievements unlocked
                </div>
            </div>
        </div>

        <!-- Bento Grid: Perks & Leaderboard -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2.5rem;">
            <!-- Perk Redemption Card -->
            <div class="card" style="padding: 1.5rem; background: var(--surface-2); display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;">
                        <span class="tag tag-brass" style="font-size: 0.8125rem;">Software perk</span>
                        <span style="font-family: var(--font-mono); font-size: 0.875rem; font-weight: 600; color: #f59e0b;">100 pts</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem;">
                        <span style="font-size: 2rem;">🚀</span>
                        <div>
                            <h3 style="font-size: 1.25rem; margin: 0;">+2 Monthly Analysis Quota</h3>
                            <span style="font-size: 0.8125rem; color: var(--text-muted);">Instantly adds 2 additional repository analyses to this calendar month</span>
                        </div>
                    </div>
                    <p style="font-size: 0.875rem; color: var(--text-muted); line-height: 1.5; margin-bottom: 1.25rem;">
                        Running low on monthly analyses? Spend 100 points to immediately boost your monthly limit. The bonus applies directly to Backtrace's real quota gate and renews your capacity.
                    </p>
                </div>
                {perk_button}
            </div>

            <!-- Leaderboard Card -->
            <div class="card" style="padding: 1.5rem; background: var(--surface-2);">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;">
                    <h3 style="font-size: 1.25rem; margin: 0;">Global Builder Leaderboard</h3>
                    <span class="tag tag-ghost" style="font-family: var(--font-ui); font-size: 0.8125rem;">Your Rank: #{user_rank} ({user_points} PTS)</span>
                </div>
                <div style="overflow-x: auto; max-height: 220px; overflow-y: auto;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="border-bottom: 1px solid var(--border); font-family: var(--font-mono); font-size: 0.8125rem; color: var(--text-muted); ">
                                <th style="padding: 0.5rem 1rem; text-align: left;">Rank</th>
                                <th style="padding: 0.5rem 1rem; text-align: left;">Architect</th>
                                <th style="padding: 0.5rem 1rem; text-align: right;">Points</th>
                            </tr>
                        </thead>
                        <tbody>
                            {leaderboard_rows if leaderboard_rows else '<tr><td colspan="3" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">No builders on leaderboard yet</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Badges Section -->
        <div style="margin-bottom: 2.5rem;">
            <div style="margin-bottom: 1rem;">
                <h2 style="font-size: 1.5rem; margin-bottom: 0.25rem;">Architecture Report Achievement Badges</h2>
                <p style="font-size: 0.875rem; color: var(--text-muted);">Earn badges by demonstrating mastery, speed, and breadth across repository architectures.</p>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem;">
                {badges_html}
            </div>
        </div>

        <!-- Audit Ledger Section -->
        <div class="card" style="padding: 1.5rem; background: var(--surface-2);">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;">
                <div>
                    <h3 style="font-size: 1.25rem; margin-bottom: 0.2rem;">Points Audit Ledger</h3>
                    <p style="font-size: 0.8125rem; color: var(--text-muted); margin: 0;">Immutable, append-only transaction history</p>
                </div>
                <span class="tag tag-ghost" style="font-family: var(--font-mono); font-size: 0.8125rem;">Audit Trail Active</span>
            </div>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="border-bottom: 1px solid var(--border); font-family: var(--font-ui); font-size: 0.8125rem; color: var(--text-muted); ">
                            <th style="padding: 0.65rem 0.85rem; text-align: left;">ID</th>
                            <th style="padding: 0.65rem 0.85rem; text-align: left;">Date & Time</th>
                            <th style="padding: 0.65rem 0.85rem; text-align: left;">Reason</th>
                            <th style="padding: 0.65rem 0.85rem; text-align: center;">Milestone</th>
                            <th style="padding: 0.65rem 0.85rem; text-align: right;">Points</th>
                        </tr>
                    </thead>
                    <tbody>
                        {ledger_rows if ledger_rows else '<tr><td colspan="5" style="text-align: center; padding: 2rem; color: var(--text-muted); font-style: italic;">No transactions in ledger yet. Solve milestones to earn points!</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    </main>
    """

    return page_shell(
        "Points & Rewards",
        content,
        current_user=current_user,
        active_route="/rewards",
        billing_status=billing_status,
    )