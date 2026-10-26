"""Frontend v2 UI Components and Application Shell."""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.config import billing_enabled, rewards_enabled
from app.core.failure_reason import failure_reason
from app.frontend1.components import (
    ConfidenceSummary,
    _parse_report_markdown,
    _truncate_path_middle,
    render_safe_markdown,
    get_narration_source,
    get_narration_label,
    confidence_summary,
    count_code_and_docs_files,
    extract_readme_summary,
    get_main_language,
    get_read_first_files,
    get_start_here_entry_points,
    DOMAIN_COLOR_DEFS,
    SANDBOX_DISABLED_BANNER_TEXT,
    piston_health_monitor,
    report_view as fe1_report_view,
)
from app.frontend2.icons import render_icon
from app.models.db import UserModel
from app.ui.sanitizer import sanitize_text

# Re-export Overview helper functions
extract_readme_summary = extract_readme_summary
get_main_language = get_main_language
get_start_here_entry_points = get_start_here_entry_points
get_read_first_files = get_read_first_files
count_code_and_docs_files = count_code_and_docs_files



def nav_shell(
    current_user: Optional[UserModel] = None,
    active_route: str = "",
    billing_status: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the persistent navigation header shell for Frontend v2."""
    sun_icon_svg = render_icon("sun", 16)
    theme_toggle_html = f"""
        <button id="theme-toggle" class="theme-toggle-btn" onclick="toggleTheme()" type="button" aria-label="Toggle dark/light mode" title="Switch to light theme">
            <span id="theme-toggle-icon">
                {sun_icon_svg}
            </span>
            <span id="theme-toggle-label" style="display: none;">Theme</span>
        </button>
    """

    if not current_user:
        brand_href = "/login"
        sign_in_link = "" if active_route == "/login" else '<a href="/login" class="btn btn-sm btn-primary">Sign In</a>'
        return f"""
    <header class="f2-header nav-shell">
        <div class="nav-shell-inner">
            <div class="f2-nav-left">
                <a href="{brand_href}" class="brand" id="nav-brand-link">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2" aria-hidden="true">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12 6 12 12 16 14"></polyline>
                    </svg>
                    <span class="brand-title">Backtrace</span>
                </a>
            </div>
            <div class="nav-right">
                {theme_toggle_html}
                {sign_in_link}
            </div>
        </div>
    </header>
    """

    raw_username = current_user.github_username or "User"
    safe_username = sanitize_text(raw_username)

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
            <div class="tag tag-pro" id="nav-tier-tag">
                <span>Pro</span>
            </div>
            """

    dashboard_active = "active" if active_route == "/dashboard" else ""
    rewards_active = "active" if active_route in ("/rewards", "/points") else ""
    settings_active = "active" if active_route == "/settings" else ""
    rewards_aria = 'aria-current="page"' if rewards_active else ""

    rewards_nav_link = ""
    rewards_dropdown_link = ""
    if rewards_enabled():
        rewards_nav_link = f'\n                <a href="/rewards" class="nav-link {rewards_active}" id="nav-link-rewards" data-path="rewards" {rewards_aria}>Rewards &amp; Badges</a>'
        rewards_dropdown_link = f'<a href="/rewards" class="dropdown-item" id="nav-dropdown-rewards">{render_icon("check-circle", 14)} Rewards &amp; Badges</a>'

    return f"""
    <header class="f2-header nav-shell">
        <div class="nav-shell-inner">
            <div class="f2-nav-left">
                <a href="/dashboard" class="brand" id="nav-brand-link">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2" aria-hidden="true">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12 6 12 12 16 14"></polyline>
                    </svg>
                    <span class="brand-title">Backtrace</span>
                </a>
                {tier_tag}
            </div>

            <nav class="nav-links">
                <a href="/dashboard" class="nav-link {dashboard_active}" id="nav-link-dashboard" data-path="dashboard" {'aria-current="page"' if dashboard_active else ''}>Dashboard</a>{rewards_nav_link}
                <a href="/settings" class="nav-link {settings_active}" id="nav-link-settings" data-path="settings" {'aria-current="page"' if settings_active else ''}>Settings</a>
            </nav>

            <div class="nav-right">
                {theme_toggle_html}
                <div class="user-dropdown">
                    <button class="user-dropdown-btn" id="user-menu-btn" onclick="toggleUserDropdown()" aria-haspopup="true" aria-expanded="false" aria-label="User menu" type="button">
                        {avatar_html}
                        <span class="username">@{safe_username}</span>
                        {render_icon("arrow-right", 12)}
                    </button>
                    <div class="dropdown-menu" id="user-dropdown-menu" style="display: none;">
                        <a href="/dashboard" class="dropdown-item" id="nav-dropdown-dashboard">
                            {render_icon("home", 14)} Dashboard
                        </a>
                        {rewards_dropdown_link}
                        <a href="/settings" class="dropdown-item" id="nav-dropdown-settings">
                            {render_icon("user", 14)} Settings
                        </a>
                        <div style="height: 1px; background: var(--border-subtle); margin: 4px 0;"></div>
                        <a href="/auth/logout" class="dropdown-item" id="nav-logout-btn" title="Sign Out of Backtrace" style="color: var(--danger);">
                            {render_icon("close", 14)} Log out
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
    """Wrap content in Frontend v2 design system shell with responsive navigation."""
    rendered_nav = nav_shell(
        current_user=current_user,
        active_route=active_route,
        billing_status=billing_status,
    )

    clean_title = sanitize_text(title)

    if clean_title == "Dashboard":
        doc_title = "<title>Dashboard · Backtrace</title>"
    elif clean_title.startswith("Architecture Report: "):
        repo_part = clean_title.replace("Architecture Report: ", "")
        doc_title = f"<title>{repo_part} · Backtrace</title>"
    elif active_route == "/login" or title == "Backtrace - Understand any GitHub repository":
        doc_title = "<title>Backtrace - Understand any GitHub repository</title>"
    else:
        doc_title = f"<title>{clean_title} · Backtrace</title>"

    # Determine if this is a report page
    is_report = bool(
        active_route
        and (
            active_route == "/report"
            or active_route.startswith("/report/")
            or active_route == "/showcase"
            or "tab-btn-overview" in content
            or "report-tab" in content
            or "tab-pane-overview" in content
        )
    )

    report_subnav_html = ""
    bottom_bar_html = ""
    if is_report:
        report_subnav_html = f"""
        <div class="f2-report-subnav">
            <div class="f2-report-subnav-inner">
                <button type="button" class="f2-subnav-tab active" id="f2-subnav-overview" onclick="switchReportTab('overview')">
                    {render_icon('home', 16)} Overview
                </button>
                <button type="button" class="f2-subnav-tab" id="f2-subnav-graph" onclick="switchReportTab('graph')">
                    {render_icon('map', 16)} Map
                </button>
                <button type="button" class="f2-subnav-tab" id="f2-subnav-milestones" data-tab="milestones" onclick="switchReportTab('milestones')">
                    {render_icon('book', 16)} Milestones
                </button>
                <button type="button" class="f2-subnav-tab" id="f2-subnav-quiz" onclick="switchReportTab('quiz')">
                    {render_icon('check-circle', 16)} Quiz
                </button>
            </div>
        </div>
        """

        bottom_bar_html = f"""
        <nav class="f2-bottom-bar" id="report-bottom-bar" aria-label="Report navigation">
            <a href="#overview" class="f2-bottom-tab active" id="f2-bottom-overview" onclick="switchReportTab('overview'); return false;">
                {render_icon('home', 20)}
                <span>Overview</span>
            </a>
            <a href="#graph" class="f2-bottom-tab" id="f2-bottom-graph" onclick="switchReportTab('graph'); return false;">
                {render_icon('map', 20)}
                <span>Map</span>
            </a>
            <a href="#milestones" class="f2-bottom-tab" id="f2-bottom-milestones" onclick="switchReportTab('milestones'); return false;">
                {render_icon('book', 20)}
                <span>Milestones</span>
            </a>
            <a href="#quiz" class="f2-bottom-tab" id="f2-bottom-quiz" onclick="switchReportTab('quiz'); return false;">
                {render_icon('check-circle', 20)}
                <span>Quiz</span>
            </a>
        </nav>
        """

    footer_parts = ["© 2026 Backtrace"]
    footer_parts.append('<a href="/privacy">Privacy</a>')
    if billing_enabled():
        footer_parts.append('<a href="/pricing">Pricing</a>')
    footer_parts.append('<a href="/support">Support</a>')
    footer_links_html = " · ".join(footer_parts)

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    {doc_title}
    <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
    <link rel="alternate icon" href="/favicon.svg">
    <link rel="stylesheet" href="/static/frontend2/tokens.css">
    <link rel="stylesheet" href="/static/frontend2/base.css">
    <link rel="stylesheet" href="/static/frontend2/shell.css">
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
</head>
<body class="f2-shell">
    {rendered_nav}
    {report_subnav_html}

    <main class="f2-main">
        {content}
    </main>

    <footer class="f2-footer">
        <div class="f2-footer-inner">
            <span>Backtrace Analysis Platform</span>
            <div class="footer-links">
                {footer_links_html}
            </div>
        </div>
    </footer>

    {bottom_bar_html}

    <script>
        function toggleTheme() {{
            const current = document.documentElement.getAttribute('data-theme') || 'dark';
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('backtrace-theme', next);
            const btn = document.getElementById('theme-toggle');
            if (btn) {{
                btn.setAttribute('title', next === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
            }}
        }}

        function toggleUserDropdown() {{
            const menu = document.getElementById('user-dropdown-menu');
            const btn = document.getElementById('user-menu-btn');
            if (!menu) return;
            const isHidden = menu.style.display === 'none' || menu.style.display === '';
            menu.style.display = isHidden ? 'block' : 'none';
            if (btn) btn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
        }}

        document.addEventListener('click', function(e) {{
            const btn = document.getElementById('user-menu-btn');
            const menu = document.getElementById('user-dropdown-menu');
            if (btn && menu && !btn.contains(e.target) && !menu.contains(e.target)) {{
                menu.style.display = 'none';
                btn.setAttribute('aria-expanded', 'false');
            }}
        }});

        if (typeof window.switchReportTab !== 'function') {{
            window.switchReportTab = function(tabId) {{
                if (tabId === 'learning') tabId = 'milestones';
                const btn = document.getElementById('tab-btn-' + tabId);
                if (btn) {{
                    btn.click();
                }}

                document.querySelectorAll('.f2-subnav-tab').forEach(el => el.classList.remove('active'));
                const sub = document.getElementById('f2-subnav-' + tabId) || document.getElementById('f2-subnav-' + (tabId === 'milestones' ? 'learning' : tabId));
                if (sub) sub.classList.add('active');

                document.querySelectorAll('.f2-bottom-tab').forEach(el => el.classList.remove('active'));
                const bot = document.getElementById('f2-bottom-' + tabId) || document.getElementById('f2-bottom-' + (tabId === 'milestones' ? 'learning' : tabId));
                if (bot) bot.classList.add('active');
            }};
        }}
    </script>
    {extra_scripts}
</body>
</html>
"""


def format_time_tag(dt_obj: Any) -> str:
    """Outputs an ISO timestamp as <time datetime="ISO" title="UTC">UTC</time> with no microseconds."""
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


def format_relative_time(dt_obj: Any) -> str:
    """Formats timestamp into a concise relative time string like '42s ago'."""
    if not dt_obj:
        return "recently"
    d: Optional[datetime] = None
    if isinstance(dt_obj, (int, float)):
        try:
            val = float(dt_obj)
            sec = val / 1000.0 if val > 1e11 else val
            d = datetime.fromtimestamp(sec, tz=timezone.utc)
        except Exception:
            return "recently"
    elif isinstance(dt_obj, datetime):
        d = dt_obj
    elif isinstance(dt_obj, str):
        try:
            clean_str = dt_obj.strip()
            if clean_str.endswith(" UTC"):
                clean_str = clean_str[:-4].strip() + "+00:00"
            elif clean_str.endswith("Z"):
                clean_str = clean_str[:-1] + "+00:00"
            d = datetime.fromisoformat(clean_str)
        except Exception:
            return "recently"

    if d is not None:
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        else:
            d = d.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        diff = max(0, int((now - d).total_seconds()))
        if diff < 60:
            return f"{diff}s ago"
        elif diff < 3600:
            return f"{diff // 60}m ago"
        elif diff < 86400:
            return f"{diff // 3600}h ago"
        else:
            return f"{diff // 86400}d ago"
    return "recently"


DASHBOARD_F2_JS = """
<script>
    function fillRepoInput(url) {
        var input = document.getElementById('repo-url-input');
        if (input) {
            input.value = url;
            input.focus();
        }
    }

    function editRepoLink(url) {
        var input = document.getElementById('repo-url-input');
        if (input) {
            input.value = url;
            input.focus();
            if (input.scrollIntoView) {
                input.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        }
    }

    function toggleRowMenu(event, menuId) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        var allMenus = document.querySelectorAll('.row-menu-dropdown');
        allMenus.forEach(function(m) {
            if (m.id !== menuId) m.style.display = 'none';
        });
        var menu = document.getElementById(menuId);
        if (menu) {
            menu.style.display = (menu.style.display === 'none' || menu.style.display === '') ? 'block' : 'none';
        }
    }

    document.addEventListener('click', function(e) {
        var openMenus = document.querySelectorAll('.row-menu-dropdown');
        openMenus.forEach(function(menu) {
            if (!menu.contains(e.target) && !e.target.closest('.overflow-menu-container')) {
                menu.style.display = 'none';
            }
        });
    });

    document.addEventListener('DOMContentLoaded', function() {
        var searchInput = document.getElementById('repo-search-input');
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                var query = this.value.trim().toLowerCase();
                var rows = document.querySelectorAll('.history-row');
                var cards = document.querySelectorAll('.history-card');

                rows.forEach(function(row) {
                    var name = row.getAttribute('data-repo-name') || '';
                    var url = row.getAttribute('data-repo-url') || '';
                    if (query === '' || name.indexOf(query) !== -1 || url.indexOf(query) !== -1) {
                        row.style.display = '';
                    } else {
                        row.style.display = 'none';
                    }
                });

                cards.forEach(function(card) {
                    var name = card.getAttribute('data-repo-name') || '';
                    var url = card.getAttribute('data-repo-url') || '';
                    if (query === '' || name.indexOf(query) !== -1 || url.indexOf(query) !== -1) {
                        card.style.display = '';
                    } else {
                        card.style.display = 'none';
                    }
                });
            });
        }

        var banner = document.getElementById('cold-start-banner');
        if (banner) {
            var timer = setTimeout(function() {
                banner.style.display = 'block';
            }, 3000);
            fetch('/healthz').then(function() {
                clearTimeout(timer);
                banner.style.display = 'none';
            }).catch(function() {
                banner.style.display = 'block';
            });
        }
    });
</script>
"""


def dashboard_view(
    current_user: UserModel,
    billing_status: Dict[str, Any],
    past_jobs: List[Any],
    error: Optional[str] = None,
    success: Optional[str] = None,
    too_large_info: Optional[Dict[str, Any]] = None,
) -> str:
    """Render Frontend v2 Dashboard with Stitch design system."""
    now = datetime.now(timezone.utc)
    if now.month == 12:
        next_month_date = datetime(now.year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        next_month_date = datetime(now.year, now.month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    renewal_date_str = next_month_date.strftime("%b %d, %Y")
    renewal_mon_d = next_month_date.strftime("%b %d").replace(" 0", " ")

    b_status = billing_status or {}
    tier = b_status.get("tier", "free")
    used = int(b_status.get("monthly_usage", 0))
    limit = b_status.get("monthly_quota")
    limit_val = int(limit) if limit is not None else 5
    is_quota_exhausted = (tier != "paid" and used >= limit_val)

    if tier == "paid":
        consumption_line = "Unlimited analyses used this month"
        resets_line = ""
        meter_pct = 100
    else:
        pct = min(100, int((used / max(1, limit_val)) * 100))
        meter_pct = pct
        consumption_line = f"Free · {used} of {limit_val} analyses this month"
        resets_line = f'<span class="quota-reset-text">Resets {renewal_mon_d}</span>'

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
        <div id="quota-exhausted-notice" class="quota-exhausted-notice">
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
            '<div id="repo-url-error" class="input-error-inline" style="color: var(--error); font-size: 0.8125rem; margin-top: 0.45rem; display: flex; align-items: center; gap: 0.35rem;">'
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
            '<span>That doesn\'t look like a GitHub repository link.</span>'
            '</div>'
        )
        input_invalid_attrs = ' aria-invalid="true" aria-describedby="repo-url-error"'

    error_html = f'<div class="alert-error" style="margin-bottom: 1.5rem; padding: 0.85rem 1rem; border-radius: var(--radius); background: rgba(255,180,171,0.1); border: 1px solid var(--error); color: var(--error);">{sanitize_text(error)}</div>' if (error and not is_invalid_url_error) else ""
    success_html = (
        f'<div style="background: rgba(101, 242, 181, 0.12); border: 1px solid var(--success); color: var(--success); padding: 0.85rem 1.15rem; border-radius: var(--radius); margin-bottom: 1.5rem; font-size: 0.875rem; display: flex; align-items: center; gap: 0.6rem;">'
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
    <div class="card stratum-card" id="repo-too-large-card" style="margin-bottom: 2rem; border-color: rgba(239, 91, 91, 0.4); background: linear-gradient(180deg, rgba(239, 91, 91, 0.08) 0%, var(--surface) 100%); padding: 1.5rem; border-radius: var(--radius-xl);">
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

            <form action="/analyses/submit" method="POST" id="retry-too-large-form" style="background: var(--surface-container); padding: 1.25rem; border-radius: var(--radius); border: 1px solid var(--border);">
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
                        Retry Analysis with Scope
                    </button>
                </div>
            </form>
        </div>
    </div>
    """

    # Build history rows and mobile cards
    rows_html = ""
    cards_html = ""
    for job in past_jobs:
        job_id = sanitize_text(str(job.id))
        raw_repo_url = getattr(job, "repo_url", None) or getattr(job, "github_url", "") or ""
        repo_url = sanitize_text(raw_repo_url)
        raw_repo_name = getattr(job, "repo_name", None) or (raw_repo_url.rstrip("/").split("/")[-1] if "/" in raw_repo_url else raw_repo_url)
        repo_display = sanitize_text(raw_repo_name)
        status = sanitize_text(str(getattr(job, "status", "") or "").lower())

        safe_repo_url_js = repo_url.replace("'", "\\'").replace('"', '&quot;')
        time_tag = format_time_tag(job.created_at)
        rel_time = format_relative_time(job.created_at)
        duration_str = f"{job.execution_time_seconds:.1f}s" if getattr(job, "execution_time_seconds", 0) else "—"

        runs = getattr(job, "runs", 1)
        runs_html = f'<span class="runs-count" id="runs-badge-{job_id}">{runs} runs</span>' if runs > 1 else ""

        # Compute milestones if available
        verified_count = 0
        total_milestones = 0
        if getattr(job, "graph_data", None) and isinstance(job.graph_data, dict):
            nodes = job.graph_data.get("nodes", [])
            tier_set = {n.get("tier") for n in nodes if n.get("tier") is not None}
            total_milestones = len(tier_set)
        if total_milestones == 0 and getattr(job, "markdown_output", None):
            total_milestones = len(re.findall(r"###\s+Milestone\s+\d+:", job.markdown_output))
        try:
            if hasattr(job, "milestone_attempts") and job.milestone_attempts:
                verified_count = sum(1 for a in job.milestone_attempts if getattr(a, "status", None) == "structurally_verified")
        except Exception:
            verified_count = 0
        if total_milestones == 0 and verified_count > 0:
            total_milestones = verified_count

        overflow_menu = f"""
        <div class="overflow-menu-container">
            <button
                type="button"
                class="overflow-btn"
                onclick="toggleRowMenu(event, 'row-menu-{job_id}')"
                aria-label="Actions for {repo_display}"
            >
                &hellip;
            </button>
            <div id="row-menu-{job_id}" class="row-menu-dropdown" style="display: none;">
                <form action="/analyses/{job_id}/delete" method="POST" onsubmit="return confirm('Delete this repository analysis? This action cannot be undone.');" style="margin: 0;">
                    <button type="submit" class="dropdown-item-delete">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                        Delete
                    </button>
                </form>
            </div>
        </div>
        """

        if status in ("running", "processing", "pending", "queued"):
            status_pill_html = '<span class="status-pill badge-running"><span class="status-pulse"></span>Analyzing</span>'
            accent_cls = "accent-running"
            primary_btn = f'<a href="/progress/{job_id}" class="btn btn-sm btn-secondary" style="white-space: nowrap;">Track progress</a>'
            card_body = f"""
            <div class="indeterminate-bar" role="progressbar" aria-label="Analysis in progress"><div class="indeterminate-fill"></div></div>
            <div style="font-size: 0.8125rem; color: var(--primary-fixed-dim); margin-top: 0.25rem;">Analyzing…</div>
            """
            table_progress = '<span style="color: var(--primary-fixed-dim); font-size: 0.8125rem;">Analyzing…</span>'
            table_time = f'<div>{time_tag}</div><div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.15rem;">Started {rel_time}</div>'
            card_actions = f"""
            <div class="history-card-actions">
                <span class="started-time">Started {rel_time} <span style="font-size: 0.75rem; color: var(--text-muted);">{time_tag}</span></span>
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-left: auto;">
                    {primary_btn}
                    {overflow_menu}
                </div>
            </div>
            """

        elif status in ("completed", "complete"):
            status_pill_html = '<span class="status-pill badge-ready"><span class="status-dot"></span>Ready</span>'
            accent_cls = "accent-ready"
            primary_btn = f'<a href="/report/{job_id}" class="btn btn-sm btn-primary" style="white-space: nowrap;">Open report</a>'
            if total_milestones > 0:
                milestone_prog = f'{verified_count} of {total_milestones} milestones completed'
                table_prog = f'{verified_count} of {total_milestones} done'
                card_body = f'<div style="font-size: 0.8125rem; color: var(--on-surface-variant); margin-top: 0.25rem;">{milestone_prog} · <span class="runs-count">{total_milestones} milestones</span></div>'
                table_progress = f'<span style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--on-surface);">{table_prog}</span>'
            else:
                card_body = ""
                table_progress = '<span style="color: var(--text-muted); font-size: 0.8125rem;">—</span>'

            table_time = f'<div>{time_tag}</div><div style="font-size: 0.75rem; font-family: var(--font-mono); color: var(--text-muted); margin-top: 0.15rem;">{duration_str}</div>'
            card_actions = f"""
            <div class="history-card-actions">
                <div style="font-size: 0.8125rem; color: var(--text-muted);">{time_tag}</div>
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-left: auto;">
                    {primary_btn}
                    {overflow_menu}
                </div>
            </div>
            """

        elif status == "failed":
            status_pill_html = '<span class="status-pill badge-failed">Failed</span>'
            accent_cls = "accent-failed"
            raw_err_str = str(getattr(job, "error_message", "") or "").strip()
            safe_reason = sanitize_text(failure_reason(raw_err_str))
            error_line_html = f"""
            <div class="job-failure-reason" title="{safe_reason}">
                <span style="font-weight: 600; color: var(--error);">Failed:</span>
                <span>{safe_reason}</span>
            </div>
            """
            retry_form = f"""
            <form action="/analyses/{job_id}/retry" method="POST" style="margin: 0; display: inline;">
                <button type="submit" class="btn btn-sm btn-secondary retry-btn" style="white-space: nowrap; color: var(--error); border-color: var(--error);">
                    Retry
                </button>
            </form>
            """
            edit_btn = f"""
            <button type="button" class="btn btn-sm btn-secondary edit-link-btn" onclick="editRepoLink('{safe_repo_url_js}')" style="white-space: nowrap;">
                Edit link
            </button>
            """
            card_body = error_line_html
            table_progress = error_line_html
            table_time = f'<div>{time_tag}</div>'
            card_actions = f"""
            <div class="history-card-actions">
                <div style="font-size: 0.8125rem; color: var(--text-muted);">{time_tag}</div>
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-left: auto;">
                    {edit_btn}
                    {retry_form}
                    {overflow_menu}
                </div>
            </div>
            """
            primary_btn = f"{edit_btn} {retry_form}"

        elif status == "cancelled":
            status_pill_html = '<span class="status-pill badge-cancelled">Cancelled</span>'
            accent_cls = "accent-cancelled"
            cancel_text = '<p class="job-cancelled-text">You cancelled this analysis.</p>'
            retry_form = f"""
            <form action="/analyses/{job_id}/retry" method="POST" style="margin: 0; display: inline;">
                <button type="submit" class="btn btn-sm btn-secondary retry-btn" style="white-space: nowrap;">
                    Retry
                </button>
            </form>
            """
            card_body = cancel_text
            table_progress = cancel_text
            table_time = f'<div>{time_tag}</div>'
            card_actions = f"""
            <div class="history-card-actions">
                <div style="font-size: 0.8125rem; color: var(--text-muted);">{time_tag}</div>
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-left: auto;">
                    {retry_form}
                    {overflow_menu}
                </div>
            </div>
            """
            primary_btn = retry_form

        else:
            status_pill_html = f'<span class="status-pill badge-cancelled">{status.capitalize()}</span>'
            accent_cls = "accent-cancelled"
            primary_btn = f'<a href="/progress/{job_id}" class="btn btn-sm btn-secondary" style="white-space: nowrap;">View details</a>'
            card_body = ""
            table_progress = '<span style="color: var(--text-muted); font-size: 0.8125rem;">—</span>'
            table_time = f'<div>{time_tag}</div>'
            card_actions = f"""
            <div class="history-card-actions">
                <div style="font-size: 0.8125rem; color: var(--text-muted);">{time_tag}</div>
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-left: auto;">
                    {primary_btn}
                    {overflow_menu}
                </div>
            </div>
            """

        rows_html += f"""
        <tr class="history-row" data-repo-name="{repo_display.lower()}" data-repo-url="{repo_url.lower()}">
            <td style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border-subtle);">
                <div style="font-weight: 600; color: var(--on-surface); display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;">
                    <span>{repo_display}</span>
                    {runs_html}
                </div>
                <div style="font-family: var(--font-mono); font-size: 0.8125rem; color: var(--on-surface-variant); margin-top: 0.2rem; overflow-wrap: anywhere;">{repo_url}</div>
            </td>
            <td class="status-col" style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border-subtle);">{status_pill_html}</td>
            <td style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border-subtle);">{table_progress}</td>
            <td style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border-subtle); color: var(--on-surface-variant); font-size: 0.8125rem;">{table_time}</td>
            <td class="actions-col" style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border-subtle); text-align: right;">
                <div style="display: inline-flex; align-items: center; gap: 0.5rem; justify-content: flex-end;">
                    {primary_btn}
                    {overflow_menu}
                </div>
            </td>
        </tr>
        """

        cards_html += f"""
        <div class="card stratum-card history-card" data-repo-name="{repo_display.lower()}" data-repo-url="{repo_url.lower()}">
            <div class="history-card-accent {accent_cls}"></div>
            <div class="history-card-top">
                <div class="history-card-repo">
                    <div class="repo-display-title">
                        <span>{repo_display}</span>
                        {runs_html}
                    </div>
                    <div class="repo-url-sub">{repo_url}</div>
                </div>
                {status_pill_html}
            </div>
            {card_body}
            {card_actions}
        </div>
        """

    if not past_jobs:
        history_content = """
        <div class="empty-state-card" id="empty-state-card">
            <div class="empty-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
            </div>
            <h3>No analyses yet</h3>
            <p>No analyses yet. Paste a repository link above.</p>
            <button type="button" class="btn btn-sm btn-secondary" onclick="fillRepoInput('https://github.com/expressjs/express')">
                Try expressjs/express
            </button>
        </div>
        """
    else:
        history_content = f"""
        <div class="history-table-container">
            <table class="history-table">
                <thead>
                    <tr>
                        <th style="width: 35%;">Repository</th>
                        <th class="status-col">Status</th>
                        <th>Milestones</th>
                        <th>Submitted</th>
                        <th class="actions-col">Action</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        <div class="history-cards-container">
            {cards_html}
        </div>
        """

    quota_section_html = f"""
    <div class="quota-meter-card" id="quota-indicator-card">
        <div class="quota-header-row">
            <div class="quota-info">
                <span class="quota-main-text">{consumption_line}</span>
                {resets_line}
            </div>
            {upgrade_btn_html}
        </div>
        <div class="meter">
            <div class="meter-fill" style="width: {meter_pct}%;"></div>
        </div>
    </div>
    """

    content = f"""
    <!-- Cold Start Banner -->
    <div id="cold-start-banner" style="display: none; width: 100%; background: var(--amber, #f59e0b); color: #0d0f12; padding: 0.65rem 1rem; text-align: center; font-weight: 600; font-size: 0.875rem; position: sticky; top: 0; z-index: 99999; box-shadow: 0 2px 8px rgba(0,0,0,0.25);">
        Waking up the server, this can take up to a minute…
    </div>

    <div class="f2-dashboard-container">
        <div class="dashboard-hero">
            <h1>Analyze a repository</h1>
            <p>Paste a GitHub link and get a step-by-step guide to understand the code.</p>
        </div>

        {success_html}
        {error_html}
        {too_large_card}

        <!-- Analyze Card -->
        <div class="analyze-card">
            <form action="/analyses/submit" method="POST" id="reconstruct-form" class="analyze-form" novalidate>
                <div class="analyze-input-row">
                    <div class="analyze-input-wrapper">
                        <span class="analyze-input-icon">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>
                        </span>
                        <input
                            type="url"
                            id="repo-url-input"
                            name="repo_url"
                            required
                            class="dashboard-input"
                            placeholder="https://github.com/owner/repo"
                            {input_invalid_attrs}
                        />
                        {inline_url_error_html}
                    </div>
                    <button
                        type="submit"
                        class="btn btn-primary btn-analyze"
                        id="analyze-button"
                        {analyze_disabled_attr}
                        style="{analyze_btn_style} min-height: 48px;"
                    >
                        <span>Analyze repository</span>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                    </button>
                </div>

                <details class="advanced-options-details" id="advanced-options-details">
                    <summary class="advanced-options-toggle" id="adv-toggle-btn">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                        <span>Advanced options</span>
                    </summary>
                    <div class="advanced-options-grid" id="adv-panel">
                        <div class="form-field">
                            <label class="form-label" for="branch-ref-input">
                                Branch or tag <span class="form-label-opt">(Optional)</span>
                            </label>
                            <input
                                type="text"
                                id="branch-ref-input"
                                name="commit_ref"
                                placeholder="main or HEAD"
                            />
                        </div>
                        <div class="form-field">
                            <label class="form-label" for="subpath-input">
                                Subfolder <span class="form-label-opt">(Optional)</span>
                            </label>
                            <input
                                type="text"
                                id="subpath-input"
                                name="subpath"
                                placeholder="/src or packages/api"
                            />
                        </div>
                    </div>
                </details>
                {quota_exhausted_banner}
            </form>

            <div class="demos-section">
                <div class="demos-header">
                    <h3 class="demos-title">Instant demos</h3>
                    <p class="demos-sub">Open instantly. Doesn't use an analysis.</p>
                </div>
                <div class="chips-row">
                    <button type="button" class="sample-chip" onclick="fillRepoInput('fastapi/fastapi')">
                        <span class="chip-dot chip-dot-mint"></span>
                        <span>fastapi</span>
                    </button>
                    <button type="button" class="sample-chip" onclick="fillRepoInput('pydantic/pydantic')">
                        <span class="chip-dot chip-dot-cyan"></span>
                        <span>pydantic</span>
                    </button>
                    <button type="button" class="sample-chip" onclick="fillRepoInput('encode/httpx')">
                        <span class="chip-dot chip-dot-blue"></span>
                        <span>httpx</span>
                    </button>
                    <button type="button" class="sample-chip" id="sample-chip-btn" data-repo="https://github.com/expressjs/express" onclick="fillRepoInput('https://github.com/expressjs/express')">
                        <span class="chip-dot chip-dot-cyan"></span>
                        <span>expressjs/express</span>
                    </button>
                </div>
            </div>
        </div>

        {quota_section_html}

        <!-- Recent Analyses Section -->
        <div class="history-section">
            <div class="history-header">
                <div class="history-title-group">
                    <h2>Recent analyses</h2>
                    <span class="count-badge">{len(past_jobs)}</span>
                    <span style="display: none;">Repository History</span>
                </div>
                <div class="search-input-wrapper">
                    <span class="search-icon">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                    </span>
                    <input
                        type="search"
                        id="repo-search-input"
                        placeholder="Search repositories…"
                        class="search-input"
                    />
                </div>
            </div>
            {history_content}
        </div>
    </div>

    {DASHBOARD_F2_JS}
    """

    return page_shell(
        "Dashboard",
        content,
        current_user=current_user,
        active_route="/dashboard",
        billing_status=billing_status,
        extra_head='<link rel="stylesheet" href="/static/frontend2/dashboard.css">',
    )


# -----------------------------------------------------------------------------
# Frontend v2 Analysis Pipeline Phase & Stage Mappings
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

    t_match = re.search(r"^#\s+Architectural Reverse-Engineering Report:\s*`?([^`\n]+)`?", raw_markdown, re.MULTILINE)
    if t_match:
        result["title"] = t_match.group(1).strip()

    time_match = re.search(r"\*Synthesized at:\s*([^*]+)\*", raw_markdown)
    if time_match:
        result["synthesized_at"] = time_match.group(1).strip()

    lang_m = re.search(r"\*\*Primary Language\*\*:\s*`?([^`\n]+)`?", raw_markdown)
    files_m = re.search(r"\*\*Total Analyzed Files\*\*:\s*`?(\d+)`?", raw_markdown)
    domains_m = re.search(r"\*\*Domain Categories\*\*:\s*`?(\d+)`?", raw_markdown)
    entry_m = re.search(r"\*\*Entry Point Files\*\*:\s*`?([^`\n]+)`?", raw_markdown)

    entry_raw_val = entry_m.group(1).strip().strip("`").strip() if entry_m else None

    result["overview"] = {
        "primary_language": lang_m.group(1).strip() if lang_m else "Unknown",
        "total_files": int(files_m.group(1)) if files_m else 0,
        "total_domains": int(domains_m.group(1)) if domains_m else 0,
        "entry_points": [e.strip() for e in entry_m.group(1).split(",") if e.strip() and e.strip().lower() not in ("none", "0", "n/a", "null")] if entry_m else [],
        "entry_points_raw": entry_raw_val,
    }

    return result


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
    """Render Frontend v2 Analysis Progress page adhering to Stitch aesthetics and backend reality."""
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
    raw_md = (
        getattr(job, "report_markdown", None)
        or getattr(job, "markdown_output", "")
        or (job.get("report_markdown") or job.get("markdown_output", "") if isinstance(job, dict) else "")
    )
    raw_graph = (
        getattr(job, "graph_data", None)
        or getattr(job, "graph_output_json", None)
        or (job.get("graph_data") or job.get("graph_output_json") if isinstance(job, dict) else None)
    )

    parsed_md = _parse_report_markdown(raw_md) if isinstance(raw_md, str) and raw_md else {}
    ov_data = parsed_md.get("overview", {})

    g_data = {}
    if raw_graph:
        try:
            g_data = json.loads(raw_graph) if isinstance(raw_graph, str) else (raw_graph if isinstance(raw_graph, dict) else {})
        except Exception:
            g_data = {}

    nodes = g_data.get("nodes", []) if isinstance(g_data, dict) else []

    files_analyzed = (
        ov_data.get("total_files")
        or getattr(job, "total_files", None)
        or (job.get("total_files") if isinstance(job, dict) else None)
        or len(nodes)
        or 0
    )

    modules_count = (
        ov_data.get("total_domains")
        or (len({n.get("domain") for n in nodes if n.get("domain")}) if nodes else 0)
        or (len({n.get("tier") for n in nodes if "tier" in n}) if nodes else 0)
        or 0
    )

    raw_eps = ov_data.get("entry_points", [])
    if not raw_eps and nodes:
        raw_eps = [
            n.get("id") or n.get("name") or n.get("path")
            for n in nodes
            if n.get("is_entry_point") or n.get("type") in ("entry_point", "entry")
        ]

    app_eps = []
    for raw_ep in raw_eps:
        ep = str(raw_ep).strip()
        if not ep:
            continue
        ep_lower = ep.lower()
        if (
            ep_lower.startswith(("test/", "tests/", "spec/", "specs/", "bench/", "benchmarks/"))
            or "/test" in ep_lower
            or "/tests" in ep_lower
            or "/spec" in ep_lower
            or "test_" in ep_lower
            or "_test." in ep_lower
            or "tests." in ep_lower
            or "bench" in ep_lower
        ):
            continue
        app_eps.append(ep)

    entry_points_count = len(app_eps) if app_eps else (len(raw_eps) if raw_eps else 0)

    try:
        files_analyzed = int(files_analyzed) if isinstance(files_analyzed, (int, float, str)) else 0
    except Exception:
        files_analyzed = 0

    try:
        modules_count = int(modules_count) if isinstance(modules_count, (int, float, str)) else 0
    except Exception:
        modules_count = 0

    try:
        entry_points_count = int(entry_points_count) if isinstance(entry_points_count, (int, float, str)) else 0
    except Exception:
        entry_points_count = 0

    entry_raw_val = ov_data.get("entry_points_raw")
    if entry_points_count > 0:
        entry_points_display = str(entry_points_count)
    elif entry_raw_val is not None:
        entry_points_display = "0"
    else:
        entry_points_display = "—"

    is_completed = (job_status in ("completed", "complete"))
    is_failed = (job_status == "failed")
    is_cancelled = (job_status == "cancelled")
    is_running = not (is_completed or is_failed or is_cancelled)

    active_card_display = "block" if is_running else "none"
    cancel_trigger_display = "block" if is_running else "none"
    report_ready_display = "block" if is_completed else "none"
    failed_card_display = "block" if is_failed else "none"
    cancelled_card_display = "block" if is_cancelled else "none"

    mapped_error_reason = failure_reason(raw_job_error)

    now_ts = datetime.now(timezone.utc).timestamp()
    if is_running and job_created_ts > 0:
        running_secs = max(0, int(now_ts - job_created_ts))
        initial_timer_str = f"{running_secs // 60}:{running_secs % 60:02d}"
    elif execution_time_seconds > 0:
        initial_timer_str = formatted_init_time
    else:
        initial_timer_str = "0:00"

    initial_sentence = (
        "Downloading the repository…"
        if is_running
        else ("Analysis complete." if is_completed else ("Analysis failed." if is_failed else "Analysis cancelled."))
    )

    raw_failed_stage = getattr(job, "failed_stage", None) if hasattr(job, "failed_stage") else (job.get("failed_stage") if isinstance(job, dict) else None)
    failed_phase = map_stage_to_phase(raw_failed_stage)["phase_index"] if raw_failed_stage else 1

    initial_phase_idx = 4 if is_completed else (failed_phase if (is_failed or is_cancelled) else 1)

    # 4 Segmented Bars
    bars_html = '<div class="segmented-progress-bars" id="segmented-bars">'
    for p_i in range(1, 5):
        if is_completed:
            b_cls = "done"
        elif is_running:
            if p_i == 1:
                b_cls = "active"
            else:
                b_cls = ""
        elif is_failed or is_cancelled:
            if p_i < failed_phase:
                b_cls = "done"
            elif p_i == failed_phase:
                b_cls = "failed"
            else:
                b_cls = ""
        else:
            b_cls = ""
        bars_html += f'<div class="segment-bar {b_cls}" id="segment-bar-{p_i}"></div>'
    bars_html += '</div>'

    # 4 Phase Cards
    phase_default_msgs = {
        1: "Authorizing and cloning repository contents into an isolated sandbox.",
        2: "Scanning directory tree, parsing concrete syntax trees, and indexing symbols.",
        3: "Tracing import chains and mapping architectural domain boundaries.",
        4: "Synthesizing architectural narrative, diagrams, quizzes, and final guide.",
    }

    phase_cards_html = '<div class="phase-cards-container" id="phase-cards">'
    for p in PHASE_DEFINITIONS:
        p_idx = p["index"]
        p_name = p["name"]

        if is_completed:
            c_state = "done"
            ind_content = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'
            card_msg = "Completed successfully."
        elif is_running:
            if p_idx == 1:
                c_state = "active"
                ind_content = '<svg class="spinner-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2v4m0 12v4m-10-10h4m12 0h4m-3.17-6.83l-2.83 2.83m-8 8l-2.83 2.83m0-13.66l2.83 2.83m8 8l2.83 2.83"></path></svg>'
                card_msg = initial_sentence
            else:
                c_state = "queued"
                ind_content = f"<span>{p_idx}</span>"
                card_msg = phase_default_msgs.get(p_idx, "Queued")
        elif is_failed or is_cancelled:
            if p_idx < failed_phase:
                c_state = "done"
                ind_content = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'
                card_msg = "Completed successfully."
            elif p_idx == failed_phase:
                c_state = "failed"
                ind_content = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>'
                card_msg = mapped_error_reason if is_failed else "Cancelled by user."
            else:
                c_state = "queued"
                ind_content = f"<span>{p_idx}</span>"
                card_msg = phase_default_msgs.get(p_idx, "Queued")
        else:
            c_state = "queued"
            ind_content = f"<span>{p_idx}</span>"
            card_msg = phase_default_msgs.get(p_idx, "Queued")

        phase_cards_html += f"""
        <div class="phase-card {c_state}" id="phase-card-{p_idx}">
            <div class="phase-card-indicator" id="phase-indicator-{p_idx}">
                {ind_content}
            </div>
            <div class="phase-card-content">
                <div class="phase-card-header">
                    <h3 class="phase-card-title" id="phase-title-{p_idx}">{p_name}</h3>
                </div>
                <p class="phase-card-msg" id="phase-msg-{p_idx}">{card_msg}</p>
            </div>
        </div>
        """
    phase_cards_html += '</div>'

    # Build 11 Stages list for details toggle
    narration_src = get_narration_source(job)
    checkmark_svg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'
    circle_empty_svg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"></circle></svg>'

    stages_list_html = '<div class="stage-rows-list" id="stage-rows-list">'
    for s_key, s_name, s_desc in PROGRESS_STAGES_CLEAN:
        s_display_name = get_narration_label(narration_src) if (is_completed and s_key == "stage_7" and narration_src == "llm") else s_name
        init_icon = checkmark_svg if is_completed else circle_empty_svg
        icon_color = "var(--tertiary-fixed-dim)" if is_completed else "var(--text-muted)"
        stages_list_html += f"""
        <div class="stage-row" id="stage-row-{s_key}">
            <div class="stage-row-left">
                <span class="stage-row-icon" id="icon-{s_key}" style="color: {icon_color};">
                    {init_icon}
                </span>
                <span class="stage-row-title">{s_display_name}</span>
            </div>
            <span class="stage-row-desc">{s_desc}</span>
        </div>
        """
    stages_list_html += '</div>'

    # Safe JavaScript definitions
    PROGRESS_F2_JS = f"""
    <script>
        const jobId = "{job_id}";
        const jobStartTime = {int(job_created_ts * 1000) if job_created_ts > 0 else "Date.now()"};
        let isJobTerminated = { "true" if not is_running else "false" };

        const checkmarkSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>';
        const spinnerSvg = '<svg class="spinner-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 2v4m0 12v4m-10-10h4m12 0h4m-3.17-6.83l-2.83 2.83m-8 8l-2.83 2.83m0-13.66l2.83 2.83m8 8l2.83 2.83"></path></svg>';
        const failSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

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
            const stepText = document.getElementById("step-n-of-4-text");
            const badge = document.getElementById("stepper-status-badge");
            if (stepText) {{
                stepText.textContent = isAllDone ? "Analysis complete" : "Step " + activePhaseIndex + " of 4";
            }}
            if (badge) {{
                badge.textContent = isAllDone ? "COMPLETED" : (isFailed ? "FAILED" : "IN PROGRESS");
            }}

            for (let i = 1; i <= 4; i++) {{
                const bar = document.getElementById("segment-bar-" + i);
                const card = document.getElementById("phase-card-" + i);
                const ind = document.getElementById("phase-indicator-" + i);

                if (isAllDone || i < activePhaseIndex) {{
                    if (bar) bar.className = "segment-bar done";
                    if (card) card.className = "phase-card done";
                    if (ind) ind.innerHTML = checkmarkSvg;
                }} else if (i === activePhaseIndex && isFailed) {{
                    if (bar) bar.className = "segment-bar failed";
                    if (card) card.className = "phase-card failed";
                    if (ind) ind.innerHTML = failSvg;
                }} else if (i === activePhaseIndex && !isAllDone) {{
                    if (bar) bar.className = "segment-bar active";
                    if (card) card.className = "phase-card active";
                    if (ind) ind.innerHTML = spinnerSvg;
                }} else {{
                    if (bar) bar.className = "segment-bar";
                    if (card) card.className = "phase-card queued";
                    if (ind) ind.innerHTML = `<span>${{i}}</span>`;
                }}
            }}
        }}

        const activeCardTimerEl = document.getElementById("active-card-timer");
        const elapsedTimerEl = document.getElementById("elapsed-timer");
        function updateElapsedTimer() {{
            if (isJobTerminated) return;
            const now = Date.now();
            const elapsedSecs = Math.max(0, Math.floor((now - jobStartTime) / 1000));
            const mins = Math.floor(elapsedSecs / 60);
            const secs = elapsedSecs % 60;
            const formatted = `${{mins}}:${{secs < 10 ? '0' : ''}}${{secs}}`;
            if (activeCardTimerEl) activeCardTimerEl.textContent = formatted;
            if (elapsedTimerEl) elapsedTimerEl.textContent = formatted;
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
            if (type === "complete") color = "var(--tertiary-fixed-dim)";
            if (type === "active") color = "var(--primary-fixed)";
            if (type === "error") color = "var(--error)";

            line.style.color = color;
            const msgSpan = document.createElement("span");
            msgSpan.textContent = text;
            line.appendChild(msgSpan);
            logBox.appendChild(line);
            logBox.scrollTop = logBox.scrollHeight;
        }}

        function addActivityEntry(stageIndex, totalStages, stageName, message, isComplete=false) {{
            const sIdx = Number(stageIndex) || 0;
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

            const cancelWrapper = document.getElementById("cancel-trigger-wrapper");
            if (cancelWrapper) cancelWrapper.style.display = "none";

            const readyCard = document.getElementById("report-ready-card");
            if (readyCard) {{
                const fEl = document.getElementById("ready-files-count");
                const mEl = document.getElementById("ready-modules-count");
                const eEl = document.getElementById("ready-entry-count");
                if (fEl) fEl.textContent = (data && (data.files_analyzed != null ? data.files_analyzed : data.files)) || "—";
                if (mEl) mEl.textContent = (data && (data.modules_mapped != null ? data.modules_mapped : data.modules)) || "—";
                const epVal = (data && (data.entry_points != null ? data.entry_points : data.entry_points_count));
                if (eEl) eEl.textContent = (epVal != null) ? String(epVal) : "—";
                readyCard.style.display = "block";
            }}

            updateStepper(4, true);

            for (let i = 0; i <= 10; i++) {{
                const icon = document.getElementById("icon-stage_" + i);
                if (icon) {{
                    icon.innerHTML = checkmarkSvg;
                    icon.style.color = "var(--tertiary-fixed-dim)";
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

            const cancelWrapper = document.getElementById("cancel-trigger-wrapper");
            if (cancelWrapper) cancelWrapper.style.display = "none";

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

        function openCancelModal() {{
            const modal = document.getElementById("cancel-modal");
            if (modal) modal.classList.add("open");
        }}

        function closeCancelModal() {{
            const modal = document.getElementById("cancel-modal");
            if (modal) modal.classList.remove("open");
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

        function handleSSEData(data) {{
            if (!data) return;
            if (data.type === "progress") {{
                const stageKey = data.stage;
                const phaseIdx = stageToPhase[stageKey] || 1;
                updateStepper(phaseIdx, false);

                const activeSentenceEl = document.getElementById("active-sentence");
                if (activeSentenceEl) {{
                    activeSentenceEl.textContent = data.message || "Analyzing repository…";
                }}

                const activePhaseMsg = document.getElementById("phase-msg-" + phaseIdx);
                if (activePhaseMsg && data.message) {{
                    activePhaseMsg.textContent = data.message;
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
                    stageIcon.style.color = "var(--primary)";
                }}

                addActivityEntry(data.stage_index || 1, data.stage_total || 11, data.stage_name || stageKey, data.message || "Processing", false);
            }} else if (data.type === "stage_complete") {{
                const stageKey = data.stage;
                const stageIcon = document.getElementById("icon-" + stageKey);
                if (stageIcon) {{
                    stageIcon.innerHTML = checkmarkSvg;
                    stageIcon.style.color = "var(--tertiary-fixed-dim)";
                }}
                addActivityEntry(data.stage_index || 1, data.stage_total || 11, data.stage_name || stageKey, "Completed successfully.", true);
            }} else if (data.type === "completed") {{
                if (eventSource) eventSource.close();
                showReportReady(data);
            }} else if (data.type === "failed") {{
                if (eventSource) eventSource.close();
                showFailure(data.message, data);
            }}
        }}
        window._handleSSEData = handleSSEData;

        if (!isJobTerminated) {{
            eventSource = new EventSource(`/api/analyses/${{jobId}}/events`);
            window._eventSource = eventSource;
            addLogEntry("Event stream connected.");

            eventSource.onopen = function() {{
                const banner = document.getElementById("connection-lost-banner");
                if (banner) banner.style.display = "none";
            }};

            eventSource.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    handleSSEData(data);
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
    <div class="progress-page-container">
        <div class="back-link-wrapper">
            <a href="/dashboard" class="back-link">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>
                <span>Back to dashboard</span>
            </a>
        </div>

        <!-- Connection Lost Banner -->
        <div id="connection-lost-banner" class="connection-lost-banner">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
            <span>Connection lost. Retrying…</span>
        </div>

        <!-- Top Repository & Telemetry Card -->
        <div class="telemetry-card" id="repo-telemetry-card">
            <div class="repo-info-group">
                <div class="repo-icon-badge">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="6" y1="3" x2="6" y2="15"></line><circle cx="18" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle><path d="M18 9a9 9 0 0 1-9 9"></path></svg>
                </div>
                <h1 class="repo-title-text" title="Analyzing {owner}/{repo}"><span class="analyzing-prefix" style="color: var(--text-muted); font-weight: normal; font-size: 0.9em;">Analyzing </span>{owner}/{repo}</h1>
            </div>
            <div class="timer-pill">
                <span class="timer-pulse-dot"></span>
                <span id="elapsed-timer">{initial_timer_str}</span>
            </div>
        </div>

        <!-- Stepper (Segmented Progress Bars & Step Header) -->
        <div class="progress-stepper" id="progress-stepper">
            <div class="stepper-header">
                <span class="stepper-step-title" id="step-n-of-4-text">Step {initial_phase_idx} of 4</span>
                <span class="stepper-status-badge" id="stepper-status-badge">{'IN PROGRESS' if is_running else ('COMPLETED' if is_completed else ('FAILED' if is_failed else 'CANCELLED'))}</span>
            </div>
            {bars_html}
            {phase_cards_html}
        </div>

        <!-- Active Progress Card (while running) -->
        <div class="active-card" id="active-card" style="display: {active_card_display};">
            <div id="active-sentence" class="active-sentence">
                {initial_sentence}
            </div>
            <div class="progress-bar-track">
                <div id="progress-bar-fill" class="progress-bar-fill indeterminate"></div>
            </div>
            <div id="active-timer-display" class="active-timer-display">
                Elapsed <span id="active-card-timer">{initial_timer_str}</span> · usually 10–30 seconds
            </div>
        </div>

        <!-- End State: Report Ready Card -->
        <div class="card report-ready-card" id="report-ready-card" style="display: {report_ready_display};">
            <div class="ready-header">
                <div class="ready-icon-circle">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
                </div>
                <div>
                    <h2 style="font-size: 1.25rem; font-weight: 600; color: var(--text); margin: 0;">Report ready</h2>
                    <p style="font-size: 0.8125rem; color: var(--text-muted); margin: 0.2rem 0 0 0;">Repository analysis completed successfully.</p>
                </div>
            </div>
            <div class="ready-stats-grid">
                <div class="ready-stat-card">
                    <div class="ready-stat-label">Files analyzed</div>
                    <div id="ready-files-count" class="ready-stat-value">{files_analyzed}</div>
                </div>
                <div class="ready-stat-card">
                    <div class="ready-stat-label">Modules</div>
                    <div id="ready-modules-count" class="ready-stat-value">{modules_count}</div>
                </div>
                <div class="ready-stat-card">
                    <div class="ready-stat-label">Entry points</div>
                    <div id="ready-entry-count" class="ready-stat-value">{entry_points_display}</div>
                </div>
            </div>
            <div class="ready-actions">
                <a href="/report/{job_id}" class="btn btn-primary" id="start-learning-btn" style="min-height: 44px; display: inline-flex; align-items: center; gap: 0.5rem;">
                    <span>Start learning</span>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                </a>
                <a href="/report/{job_id}" class="btn btn-secondary" id="open-map-btn" style="min-height: 44px; display: inline-flex; align-items: center; gap: 0.5rem;">
                    <span>Open map</span>
                </a>
            </div>
        </div>

        <!-- End State: Failed Card -->
        <div class="card failed-card" id="failed-card" style="display: {failed_card_display};">
            <div class="failed-header">
                <div class="failed-icon-circle">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                </div>
                <div>
                    <h2 style="font-size: 1.15rem; font-weight: 600; color: var(--error); margin: 0 0 0.35rem 0;">Analysis failed</h2>
                    <p id="failed-reason-text" class="failed-reason-text">
                        {mapped_error_reason}
                    </p>
                </div>
            </div>
            <div class="failed-actions">
                <form action="/analyses/{job_id}/retry" method="POST" style="margin: 0; display: inline;">
                    <button type="submit" class="btn btn-primary" id="retry-btn" style="min-height: 44px;">Retry</button>
                </form>
                <a href="/dashboard" class="btn btn-secondary" style="min-height: 44px; display: inline-flex; align-items: center;">Back to dashboard</a>
            </div>
        </div>

        <!-- End State: Cancelled Card -->
        <div class="card cancelled-card" id="cancelled-card" style="display: {cancelled_card_display};">
            <h2 style="font-size: 1.15rem; font-weight: 600; color: var(--text); margin: 0 0 0.35rem 0;">Analysis cancelled</h2>
            <p style="font-size: 0.875rem; color: var(--text-muted); margin: 0 0 1.25rem 0;">This analysis was cancelled.</p>
            <a href="/dashboard" class="btn btn-secondary" style="min-height: 44px; display: inline-flex; align-items: center;">Back to dashboard</a>
        </div>

        <!-- Cancel Button Trigger (while running) -->
        <div class="cancel-analysis-wrapper" id="cancel-trigger-wrapper" style="display: {cancel_trigger_display};">
            <button type="button" class="btn-open-cancel" id="open-cancel-btn" onclick="openCancelModal()">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                <span>Cancel analysis</span>
            </button>
        </div>

        <!-- Cancel Confirmation Bottom Sheet / Modal -->
        <div class="cancel-modal-overlay" id="cancel-modal">
            <div class="cancel-modal-box">
                <div class="cancel-modal-header">
                    <div style="width: 36px; height: 36px; border-radius: 50%; background: rgba(255,180,171,0.15); color: var(--error); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                    </div>
                    <div>
                        <h2 style="font-size: 1.15rem; font-weight: 600; color: var(--text); margin: 0 0 0.25rem 0;">Cancel analysis?</h2>
                        <p style="font-size: 0.8125rem; color: var(--text-muted); margin: 0; line-height: 1.4;">Cancel this analysis? You can start it again anytime.</p>
                    </div>
                </div>
                <div class="cancel-modal-actions">
                    <form action="/jobs/{job_id}/cancel" method="POST" id="cancel-form" style="margin: 0; width: 100%;">
                        <button type="submit" class="btn-confirm-cancel" id="cancel-btn">
                            Cancel analysis
                        </button>
                    </form>
                    <button type="button" class="btn-dismiss-cancel" onclick="closeCancelModal()">
                        Keep going
                    </button>
                </div>
            </div>
        </div>

        <!-- Collapsible Activity Section -->
        <details class="details-toggle activity-drawer" id="details-toggle">
            <summary class="activity-summary">
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary-fixed-dim)" stroke-width="2"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>
                    <span>Activity</span>
                </div>
                <span style="font-size: 0.8125rem; color: var(--text-muted);">Show activity &#9662;</span>
            </summary>
            <div class="activity-content">
                <div style="margin-top: 1rem;">
                    <h4 style="font-size: 0.8125rem; color: var(--text-muted); margin: 0 0 0.5rem 0; text-transform: uppercase; letter-spacing: 0.05em; font-family: var(--font-mono);">Pipeline Stages</h4>
                    {stages_list_html}
                </div>
                <div>
                    <h4 style="font-size: 0.8125rem; color: var(--text-muted); margin: 0 0 0.5rem 0; text-transform: uppercase; letter-spacing: 0.05em; font-family: var(--font-mono);">Event Log</h4>
                    <div id="sse-terminal-log" class="terminal-log-box"></div>
                </div>
            </div>
        </details>
    </div>

    {PROGRESS_F2_JS}
    """

    page_title = f"{owner}/{repo}" if owner else repo
    return page_shell(
        page_title,
        content,
        current_user=current_user,
        active_route=f"/progress/{job_id}",
        billing_status=billing_status,
        extra_head='<link rel="stylesheet" href="/static/frontend2/progress.css">',
    )


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
    """Render the Report View in Frontend v2.

    Wraps the Learn/Milestones and Quiz tabs from frontend1 unchanged in the new frontend2 tab chrome,
    while modernizing the Shell, Overview tab, and Map tab with responsive layout and zero placeholders.
    """
    # 1. Render through frontend1 to get exact milestones, quiz, and runtime script
    fe1_html = fe1_report_view(
        job=job,
        raw_markdown=raw_markdown,
        graph_data=graph_data,
        quiz_data=quiz_data,
        current_user=current_user,
        billing_status=billing_status,
        attempts_by_tier=attempts_by_tier,
        file_contents=file_contents,
        redacted_files=redacted_files,
        is_commit_unchanged=is_commit_unchanged,
        lazy_milestones=lazy_milestones,
    )

    # Extract milestones pane and wrap milestone body containers if needed
    m_match = re.search(r'(<div class="report-tab-pane" id="tab-pane-milestones".*?)(?=<div class="report-tab-pane" id="tab-pane-quiz")', fe1_html, re.DOTALL)
    milestones_pane = m_match.group(1).strip() if m_match else '<div class="report-tab-pane" id="tab-pane-milestones" role="tabpanel" aria-labelledby="tab-btn-milestones" style="display: none;"></div>'

    # Ensure each milestone pane has milestone-header and milestone-body-container
    panes = re.split(r'(?=<div class="milestone-pane)', milestones_pane)
    injected_panes = []
    for p in panes:
        if not p.startswith('<div class="milestone-pane'):
            injected_panes.append(p)
            continue
        tier_m = re.search(r'data-tier="(\d+)"', p) or re.search(r'id="milestone-pane-(\d+)"', p)
        tier = tier_m.group(1) if tier_m else "1"
        if f'id="milestone-body-container-{tier}"' in p:
            injected_panes.append(p)
            continue
        p = re.sub(
            r'<div class="milestone-pane-header"',
            f'<div class="milestone-header milestone-pane-header" id="milestone-header-{tier}" data-tier="{tier}" onclick="toggleMilestoneBody(window.BACKTRACE_JOB_ID, {tier})" style="cursor: pointer;"',
            p,
            count=1
        )
        editor_idx = p.find(f'id="milestone-editor-card-{tier}"')
        if editor_idx != -1:
            div_start = p.rfind('<div class="milestone-editor-wrapper"', 0, editor_idx)
            if div_start != -1:
                p = p[:div_start] + f'<div class="milestone-body-container" id="milestone-body-container-{tier}" style="display: block;">\n' + p[div_start:]
                last_div = p.rfind('</div>')
                if last_div != -1:
                    p = p[:last_div] + '</div>\n' + p[last_div:]
        injected_panes.append(p)
    milestones_pane = "".join(injected_panes)

    # Extract quiz pane
    q_match = re.search(r'(<div class="report-tab-pane" id="tab-pane-quiz".*?)(?=\s*</div>\s*</div>\s*(?:<script|</main>|$))', fe1_html, re.DOTALL)
    quiz_pane = q_match.group(1).strip() if q_match else '<div class="report-tab-pane" id="tab-pane-quiz" role="tabpanel" aria-labelledby="tab-btn-quiz" style="display: none;"></div>'
    if not quiz_pane.endswith('</div>'):
        quiz_pane += '</div>'

    # Extract runtime scripts
    s_match = re.search(r'(<script>\s*const GRAPH_NODES =.*?</script>)', fe1_html, re.DOTALL)
    runtime_script = s_match.group(1) if s_match else ''

    # Sync tab switching with frontend2 bottom bar and subnav
    if runtime_script:
        sync_code = """
            if (tabKey === 'learning') tabKey = 'milestones';
            ['overview', 'graph', 'milestones', 'quiz'].forEach(k => {
                const s = document.getElementById('f2-subnav-' + (k === 'milestones' ? 'learning' : k)) || document.getElementById('f2-subnav-' + k);
                const b = document.getElementById('f2-bottom-' + (k === 'milestones' ? 'learning' : k)) || document.getElementById('f2-bottom-' + k);
                if (s) s.classList.toggle('active', (k === tabKey || (k === 'milestones' && tabKey === 'learning')));
                if (b) b.classList.toggle('active', (k === tabKey || (k === 'milestones' && tabKey === 'learning')));
            });
            if (!VALID_REPORT_TABS.includes(tabKey)) {
        """
        runtime_script = runtime_script.replace("if (!VALID_REPORT_TABS.includes(tabKey)) {", sync_code)

    # CodeMirror cdnjs styles
    cm_head = """    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
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

    # CodeMirror and helper scripts
    cm_scripts = """    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/python/python.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/javascript/javascript.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/clike/clike.min.js"></script>
    <script src="/static/highlight.min.js"></script>
"""

    quiz_helper_js = """    <script>
    function selectQuizOption(tier, qIdx, optIdx, prefix) {
        prefix = prefix || '';
        const selector = 'input[name="' + prefix + 'm_quiz_' + tier + '_' + qIdx + '"][value="' + optIdx + '"]';
        const radio = document.querySelector(selector);
        if (radio) {
            radio.checked = true;
            radio.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    document.addEventListener('change', function(e) {
        if (e.target && e.target.matches('input[type="radio"][name*="m_quiz_"]')) {
            const qEl = e.target.closest('.milestone-quiz-q');
            if (!qEl) return;
            const correctIdx = parseInt(qEl.getAttribute('data-correct-idx') || '0', 10);
            const selectedVal = parseInt(e.target.value, 10);
            const feedbackEl = qEl.querySelector('.quiz-feedback');
            const explanationEl = qEl.querySelector('.quiz-explanation');
            if (feedbackEl) {
                feedbackEl.style.display = 'inline-block';
                if (selectedVal === correctIdx) {
                    feedbackEl.style.color = 'var(--success)';
                    feedbackEl.textContent = '✓ Correct';
                } else {
                    feedbackEl.style.color = 'var(--crimson)';
                    feedbackEl.textContent = '✗ Incorrect';
                }
            }
            if (explanationEl) {
                explanationEl.style.display = 'block';
            }
        }
    });
    </script>
"""

    # Extract Job Metadata
    try:
        job_id = int(job.id if hasattr(job, "id") else (job.get("id", 0) if isinstance(job, dict) else 0))
    except (ValueError, TypeError, AttributeError):
        job_id = 0
    repo_url = sanitize_text(getattr(job, "repo_url", "") if hasattr(job, "repo_url") else (job.get("repo_url", "") if isinstance(job, dict) else ""))
    raw_repo_name = getattr(job, "repo_name", None) if hasattr(job, "repo_name") else (job.get("repo_name") if isinstance(job, dict) else None)
    repo_name = sanitize_text(raw_repo_name or (repo_url.rstrip("/").split("/")[-1] if "/" in repo_url else repo_url))
    raw_created_at = getattr(job, "created_at", None) if hasattr(job, "created_at") else (job.get("created_at") if isinstance(job, dict) else None)
    created_at = format_time_tag(raw_created_at) if raw_created_at else ""
    if "Just now" in created_at:
        created_at = ""
    exec_time = getattr(job, "execution_time_seconds", None) if hasattr(job, "execution_time_seconds") else (job.get("execution_time_seconds") if isinstance(job, dict) else None)
    duration = f"{exec_time:.1f}s" if isinstance(exec_time, (int, float)) else "Completed"
    is_showcase = bool(getattr(job, "is_showcase", False) if hasattr(job, "is_showcase") else (job.get("is_showcase", False) if isinstance(job, dict) else False))

    parsed_md = _parse_report_markdown(raw_markdown)
    overview_data = parsed_md.get("overview", {})
    domain_dist = parsed_md.get("domain_distribution", [])
    milestones_data = parsed_md.get("milestones", [])
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
        <div id="no-history-note" class="f2-notice-card warning">
            <span>Order is estimated from imports (no git history).</span>
        </div>
        """

    sandbox_enabled = piston_health_monitor.is_sandbox_enabled()
    demo_video_url = os.getenv("DEMO_VIDEO_URL", "")

    if is_showcase:
        showcase_banner_html = """
        <div id="showcase-banner" class="f2-notice-card success">
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
        <div id="sandbox-disabled-banner" class="f2-notice-card warning">
            <div style="font-size: 0.875rem; line-height: 1.5; color: var(--text);">
                {SANDBOX_DISABLED_BANNER_TEXT}{video_link_html}
            </div>
        </div>
        """
    else:
        showcase_banner_html = ""
        sandbox_banner_html = ""

    nodes = graph_data.get("nodes", []) if graph_data else []
    edges = graph_data.get("edges", []) if graph_data else []
    node_count = len(nodes)
    edge_count = len(edges)

    total_files = overview_data.get("total_files") or getattr(job, "total_files", None) or (job.get("total_files") if isinstance(job, dict) else None) or (node_count or len(nodes))
    entry_points = overview_data.get("entry_points", [])
    cyclic_count = overview_data.get("cyclic_files", 0)
    isolated_count = overview_data.get("isolated_files", 0)

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

    # Start here files - DROP per-file line counts
    start_here_files = get_start_here_entry_points(nodes, entry_points, max_n=3)
    start_here_items = []
    for ep in start_here_files:
        safe_ep = sanitize_text(ep)
        start_here_items.append(
            f'<div class="mono start-here-item" title="{safe_ep}">{safe_ep}</div>'
        )
    start_here_html = "".join(start_here_items) if start_here_items else '<span class="empty-field-text">No application entry points</span>'

    # Read first files - DROP per-file line counts
    read_first_files = get_read_first_files(nodes, edges, max_n=3)
    read_first_items = []
    for rf in read_first_files:
        safe_rf = sanitize_text(rf)
        read_first_items.append(
            f'<div class="mono read-first-item" title="{safe_rf}">{safe_rf}</div>'
        )
    read_first_html = "".join(read_first_items) if read_first_items else '<span class="empty-field-text">No candidate files detected</span>'

    code_count, docs_count = count_code_and_docs_files(nodes, total_files)

    app_chips_html = ""
    for ep in app_entry_points:
        safe_ep = sanitize_text(ep)
        app_chips_html += f"""
        <div class="entry-chip" onclick="switchReportTab('graph'); setTimeout(function() {{ selectDagNode('{safe_ep}'); }}, 50);" role="button" tabindex="0" title="{safe_ep}">
            <div class="entry-chip-label" title="{safe_ep}">
                <span class="mono">{safe_ep}</span>
            </div>
            <div class="entry-chip-meta">
                <span class="badge badge-teal">APP</span>
                <span class="entry-chip-arrow">&rarr;</span>
            </div>
        </div>
        """
    if not app_chips_html:
        app_chips_html = '<span class="empty-field-text">No application entry points detected</span>'

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

    # Domain bars - DROP per-file descriptions & mini import map
    domain_bars_html = ""
    for d in domain_dist:
        d_name = sanitize_text(d["domain"]).upper()
        d_count = d["count"]
        pct_val = float(d["percentage"].replace("%", "")) if "%" in d.get("percentage", "") else 0
        domain_bars_html += f"""
        <div class="subsystem-item">
            <div class="subsystem-header">
                <span class="subsystem-name">{d_name}</span>
                <span class="subsystem-count">{d_count} files</span>
            </div>
            <div class="subsystem-track">
                <div class="subsystem-fill" style="width: {pct_val}%;"></div>
            </div>
        </div>
        """
    subsystem_container_cls = "subsystem-grid-2col" if len(domain_dist) >= 6 else ""

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
    <div class="stratum-card f2-overview-card" id="section-overview">
        <div class="card-header f2-card-header">
            <div>
                <div class="f2-section-eyebrow">
                    Section 01: Codebase Overview
                </div>
                <h2 class="f2-section-heading">Codebase Architecture Overview</h2>
            </div>
            <div class="card-header-chips">
                <span class="chip"><span class="chip-dot teal"></span> Verified Invariants</span>
                <span class="chip">{total_files} Files</span>
            </div>
        </div>

        <div class="stratum-card tldr-block" id="overview-tldr-block">
            <div class="tldr-header">
                <span class="tldr-title">Summary</span>
                <span class="chip">Analysis data only</span>
            </div>
            <div class="tldr-content">
                <div>
                    <div class="tldr-label">What this project is</div>
                    <div class="tldr-body" id="tldr-what-this-is">{what_this_is_safe}</div>
                </div>
                <div class="tldr-grid">
                    <div>
                        <div class="tldr-label">Main language</div>
                        <div class="tldr-value" id="tldr-main-language">{main_lang_safe}</div>
                    </div>
                    <div>
                        <div class="tldr-label">Start here</div>
                        <div class="tldr-files-list" id="tldr-start-here">
                            {start_here_html}
                        </div>
                    </div>
                    <div>
                        <div class="tldr-label">Read these 3 files first</div>
                        <div class="tldr-files-list" id="tldr-read-first">
                            {read_first_html}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="overview-order-note">
            <span>Order is estimated from imports.</span>
            <span style="display: none;">Verified Architecture Summary &bull; STANDALONE FILES: {isolated_count} &bull; CIRCULAR DEPENDENCIES: {cyclic_count}</span>
        </div>

        <div class="kpi-grid overview-stat-cards">
            <div class="kpi-card">
                <div class="kpi-label">Files analyzed</div>
                <div class="kpi-value">{total_files} files</div>
                <div class="kpi-sub">{code_count} code, {docs_count} docs</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Entry points</div>
                <div class="kpi-value" style="color: var(--amber);">{len(app_entry_points)}</div>
                <div class="kpi-sub">
                    {len(app_entry_points)} application targets
                    <span style="display: none;">{len(app_entry_points)} App &bull; {len(test_entry_points)} Test/Tools</span>
                </div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Modules</div>
                <div class="kpi-value" style="color: var(--accent);">{len(domain_dist)}</div>
                <div class="kpi-sub">{len(domain_dist)} subsystem domains</div>
            </div>
            <div class="kpi-card" data-metric="CONFIDENCE SCORE" data-high-pct="{conf_summary.high_pct}" data-low-pct="{conf_summary.low_pct}" data-low-count="{conf_summary.low_count}" data-source="{'summary' if conf_summary_raw else 'graph-nodes'}">
                <div class="kpi-label">Confidence</div>
                <div class="kpi-value" style="color: {overall_conf_color}; font-size: 1.5rem;">{conf_summary.high_pct}%</div>
                <div class="kpi-sub">
                    {conf_summary.low_count} files low confidence{f'<div class="confidence-estimate-sub">Estimated from the dependency graph</div>' if not conf_summary_raw else ''}
                </div>
            </div>
        </div>

        <div class="f2-overview-breakdown-grid">
            <div id="overview-entry-points-list" class="f2-panel-card">
                <div class="f2-panel-header">
                    <span class="f2-panel-title">
                        Entry points ({len(app_entry_points)})
                    </span>
                    <span class="chip">Application targets</span>
                </div>
                <div class="entry-chips-container">
                    {app_chips_html}
                </div>
                {legacy_compat_entry_html}
            </div>

            <div class="f2-panel-card">
                <div class="f2-panel-header">
                    <span class="f2-panel-title">
                        Subsystems ({len(domain_dist)})
                    </span>
                    <span class="chip">Domains</span>
                </div>
                <div class="{subsystem_container_cls}">
                    {domain_bars_html}
                </div>
            </div>
        </div>

        <div class="stratum-card f2-panel-card" id="confidence-breakdown-card" style="margin-top: 1.25rem;">
            <div class="f2-panel-header">
                <span class="f2-panel-title">
                    Confidence Calibration
                </span>
                <span class="chip">{conf_summary.total_files} SCORED FILES</span>
            </div>

            <div class="confidence-stacked-bar" id="confidence-horizontal-bar">
                <div style="width: {conf_summary.high_pct}%; background: var(--success); height: 100%; transition: width 0.3s ease;"></div>
                <div style="width: {conf_summary.medium_pct}%; background: var(--amber); height: 100%; transition: width 0.3s ease;"></div>
                <div style="width: {conf_summary.low_pct}%; background: #64748b; height: 100%; transition: width 0.3s ease;"></div>
            </div>

            <div class="confidence-legend-list">
                <div class="confidence-legend-row">
                    <span class="legend-key">
                        <span class="legend-swatch" style="background: var(--success);"></span>
                        High
                    </span>
                    <span class="legend-count">{conf_summary.high_count} files ({conf_summary.high_pct}%)</span>
                </div>
                <div class="confidence-legend-row">
                    <span class="legend-key">
                        <span class="legend-swatch" style="background: var(--amber);"></span>
                        Medium
                    </span>
                    <span class="legend-count">{conf_summary.medium_count} files ({conf_summary.medium_pct}%)</span>
                </div>
                <div class="confidence-legend-row">
                    <span class="legend-key">
                        <span class="legend-swatch" style="background: #64748b;"></span>
                        Low
                    </span>
                    <span class="legend-count">{conf_summary.low_count} files ({conf_summary.low_pct}%)</span>
                </div>
            </div>

            <p class="confidence-explainer-text">
                High means the file is imported by many others and has clear structure.
            </p>
        </div>
    </div>
    """

    # -------------------------------------------------------------
    # 2. Dependency Graph (Map tab)
    # -------------------------------------------------------------
    graph_section_html = ""
    svg_width = 940
    svg_height = 460
    real_total_files = max(int(total_files), node_count)
    if nodes:
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

        # Layout nodes & tier columns - 1-based Layer N
        for t_idx, t_val in enumerate(sorted_tiers):
            col_x = padding_x + t_idx * col_step
            tier_nodes = tiers[t_val]
            layer_num = t_idx + 1

            svg_columns_html += f"""
            <g class="dag-column" transform="translate({col_x}, 0)">
                <rect x="0" y="16" width="{col_width}" height="28" rx="4" fill="var(--panel-raised)" stroke="var(--border)" />
                <text x="12" y="34" fill="var(--accent)" font-family="var(--font-mono)" font-size="11" font-weight="600">Layer {layer_num}</text>
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

                file_name = raw_path.split("/")[-1] if raw_path else raw_label
                trunc_fname = file_name if len(file_name) <= 15 else file_name[:13] + "..."

                full_node_path = sanitize_text(raw_path)
                node_path = sanitize_text(_truncate_path_middle(raw_path, 28))
                node_domain = sanitize_text(raw_domain[:7])

                confidence = sanitize_text(str(node.get("confidence", "high"))).lower()
                conf_color = "#10B981" if confidence == "high" else ("#F59E0B" if confidence == "medium" else "#94A3B8")

                safe_node_id = sanitize_text(node_id).replace("/", "_").replace(".", "_")

                svg_nodes_html += f"""
                <g class="dag-node" id="dag-node-{safe_node_id}" data-node-id="{sanitize_text(node_id)}" data-tier="{t_val}" data-domain="{node_domain}" title="{full_node_path}" onclick="selectDagNode(this.dataset.nodeId)" onmouseenter="hoverDagNode(this.dataset.nodeId)" onmouseleave="unhoverDagNode()" transform="translate({col_x}, {node_y})" style="cursor: pointer; transition: all 150ms ease;">
                    <title>{full_node_path}</title>
                    <rect width="{col_width}" height="{node_h}" rx="6" fill="var(--surface-2)" stroke="var(--border)" class="dag-node-box" />
                    <circle cx="16" cy="20" r="4" fill="{conf_color}" />
                    <g clip-path="url(#dag-node-text-clip)">
                        <text x="28" y="24" fill="var(--text)" font-family="var(--font-mono)" font-size="11.5" font-weight="600">{sanitize_text(trunc_fname)}</text>
                    </g>
                    <rect x="{col_width - 62}" y="11" width="50" height="17" rx="3" fill="var(--panel-raised)" stroke="{node_color}" stroke-opacity="0.4" />
                    <text x="{col_width - 37}" y="23" fill="{node_color}" font-family="var(--font-mono)" font-size="9" font-weight="600" text-anchor="middle">{node_domain}</text>
                    <text x="16" y="44" fill="var(--text-muted)" font-family="var(--font-mono)" font-size="9.5" title="{full_node_path}"><title>{full_node_path}</title>{node_path}</text>
                </g>
                """

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
                    start_x = src["x"]
                    start_y = src["y"] + src["h"] / 2
                    end_x = tgt["x"] + tgt["w"]
                    end_y = tgt["y"] + tgt["h"] / 2
                    d = f"M {start_x:.1f} {start_y:.1f} C {start_x - 40:.1f} {start_y - 40:.1f}, {end_x + 40:.1f} {end_x + 40:.1f}, {end_x:.1f} {end_y:.1f}"

                svg_edges_html += f"""
                <path class="dag-edge" data-source="{sanitize_text(src_id)}" data-target="{sanitize_text(tgt_id)}" d="{d}" fill="none" stroke="var(--hairline-strong)" stroke-width="1" marker-end="url(#dag-arrow)" opacity="0.4" style="transition: all 150ms ease;" />
                """

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

        domain_color_defs = DOMAIN_COLOR_DEFS
        confidence_legend_defs = {
            "high": ("#10B981", "high confidence (clear structure or history)"),
            "medium": ("#F59E0B", "medium confidence (estimated pattern)"),
            "low": ("#94A3B8", "low confidence (cyclic / isolated)"),
        }

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
            <div class="legend-chip" title="{dom_tag}: {safe_desc}">
                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 2px; background: {dom_color}; flex-shrink: 0;"></span>
                <span style="font-weight: 600; color: var(--text); font-family: var(--font-ui); font-size: 0.8125rem;">{dom_tag}</span>
                <span style="color: var(--text-muted); font-size: 0.8125rem;">= {safe_desc}</span>
            </div>
            """

        legend_confidence_chips = ""
        for conf_key in ["high", "medium", "low"]:
            if conf_key in used_confidences:
                conf_color, conf_desc = used_confidences[conf_key]
                conf_lbl = sanitize_text(conf_key.capitalize())
                safe_desc = sanitize_text(conf_desc)
                legend_confidence_chips += f"""
                <div class="legend-chip" title="{conf_lbl} Confidence: {safe_desc}">
                    <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: {conf_color}; flex-shrink: 0;"></span>
                    <span style="font-weight: 600; color: var(--text); font-family: var(--font-ui); font-size: 0.8125rem;">{conf_lbl}</span>
                    <span style="color: var(--text-muted); font-size: 0.8125rem;">= {safe_desc}</span>
                </div>
                """

        graph_section_html = f"""
        <div class="stratum-card dag-graph-wrapper f2-map-card" id="section-graph">
            <div class="card-header f2-card-header">
                <div>
                    <div class="f2-section-eyebrow">
                        Section 02: Dependency Roadmap
                    </div>
                    <h2 class="f2-section-heading">Architecture &amp; Dependency Graph</h2>
                </div>
                <div class="card-header-chips">
                    <span class="chip"><span class="chip-dot teal"></span> {node_count} Nodes</span>
                    <span class="chip">{edge_count} Dependencies</span>
                </div>
            </div>

            <p class="dag-explainer-p">
                Built from analyzing the code&#39;s structure and how files import each other. Each box is a file, arranged left-to-right from foundational code to code that depends on it.
            </p>

            <div class="dag-counter-row">
                <div id="dag-count-explainer" class="dag-count-text">
                    Showing the {node_count} most connected files of {real_total_files}.
                </div>
                <button type="button" class="btn btn-sm btn-secondary" id="toggle-all-files-btn" onclick="toggleAllFiles()">
                    Show all files
                </button>
            </div>

            <div class="dag-toolbar-container">
                <div class="dag-search-box">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--text-muted);">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    <input type="text" id="dag-search-input" placeholder="Search node or file..." oninput="filterDagNodes(this.value)" />
                </div>
                <div class="dag-toolbar-actions">
                    <span class="dag-hint">Scroll to zoom, drag to move</span>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="fitDagGraph()" id="dag-fit-btn" title="Fit to View">
                        Fit
                    </button>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="resetDagZoom()" title="Reset Graph View">
                        Reset
                    </button>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="toggleDagLegend()" id="toggle-legend-btn" title="Toggle Graph Legend">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                        Legend
                    </button>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="toggleGraphViewMode()" id="toggle-view-btn">
                        List
                    </button>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="toggleGraphFullscreen()" id="dag-fullscreen-btn" title="Toggle Fullscreen">
                        ⛶ Maximize
                    </button>
                </div>

                <div id="dag-legend-panel">
                    <div class="dag-legend-header">
                        <span class="dag-legend-title">Graph Legend</span>
                        <button type="button" aria-label="Close graph legend" onclick="toggleDagLegend()" class="dag-legend-close">✕</button>
                    </div>
                    <div id="dag-legend-content">
                        <div>
                            <div class="legend-subtitle">Node Domains</div>
                            <div class="legend-chips-col">
                                {legend_domain_chips}
                            </div>
                        </div>
                        <div class="legend-section-divider">
                            <div class="legend-subtitle">Confidence</div>
                            <div class="legend-chips-col">
                                {legend_confidence_chips}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div id="dag-canvas-layout" class="f2-dag-canvas-layout">
                <div id="dag-visual-container">
                    <svg id="dag-svg" width="100%" height="100%" viewBox="0 0 {svg_width} {svg_height}">
                        <defs>
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
                            {svg_columns_html}
                            <g id="dag-edges-layer">
                                {svg_edges_html}
                            </g>
                            <g id="dag-nodes-layer">
                                {svg_nodes_html}
                            </g>
                        </g>
                    </svg>
                </div>

                <aside id="dag-node-inspector" class="dag-side-panel" style="display: none;">
                    <div class="dag-inspector-header">
                        <div>
                            <div class="inspector-title-row">
                                <span id="inspect-dot" class="chip-dot" style="background: #10B981;"></span>
                                <span id="inspect-label" class="mono inspector-node-label">Node Name</span>
                            </div>
                            <div class="inspector-domain-row">
                                <span id="inspect-domain" class="chip">CORE</span>
                            </div>
                        </div>
                        <button type="button" aria-label="Close side panel" class="btn btn-sm btn-secondary" onclick="closeDagInspector()" title="Close side panel" style="padding: 2px 8px; font-size: 0.8125rem; line-height: 1;">✕</button>
                    </div>

                    <div class="inspector-section">
                        <div class="inspector-section-label">File Path</div>
                        <div id="inspect-path" class="mono inspector-box">src/path</div>
                    </div>

                    <div class="inspector-section">
                        <a href="#milestones" id="inspect-milestone-link" class="btn btn-sm btn-primary" onclick="openNodeMilestone(); return false;" style="width: 100%; justify-content: center; display: inline-flex; align-items: center; gap: 0.35rem;">
                            Open milestone &rarr;
                        </a>
                    </div>

                    <div class="inspector-section">
                        <div class="inspector-section-label" id="inspect-imported-by-title">Imported By (0)</div>
                        <div id="inspect-imported-by" class="mono inspector-box" style="max-height: 120px; overflow-y: auto;">None (Entry Point)</div>
                    </div>

                    <div class="inspector-section">
                        <div class="inspector-section-label" id="inspect-imports-title">Imports (0)</div>
                        <div id="inspect-imports" class="mono inspector-box" style="max-height: 120px; overflow-y: auto;">None (Leaf Node)</div>
                    </div>

                    <div>
                        <div class="inspector-section-label">Exported Symbols</div>
                        <div id="inspect-exports" class="mono inspector-box" style="max-height: 100px; overflow-y: auto;">None</div>
                    </div>
                </aside>
            </div>

            <div id="dag-table-container" style="display: none;" class="dag-table-wrapper">
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

    back_link_html = """
        <a href="/showcase" class="f2-back-link">
            &larr; BACK TO SHOWCASE DIRECTORY
        </a>""" if is_showcase else """
        <a href="/dashboard" class="f2-back-link">
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

    meta_spans = [
        f'<span>Target: <a href="{repo_url}" target="_blank" rel="noopener noreferrer" style="color: var(--text-muted);">{repo_url}</a></span>'
    ]
    if raw_created_at and created_at and "Just now" not in created_at:
        meta_spans.append(f'<span>Synthesized: {created_at}</span>')
    meta_spans.append(f'<span>Duration: {duration}</span>')
    if narration_badge_html:
        meta_spans.append(narration_badge_html)
    f2_meta_html = " <span>&bull;</span> ".join(meta_spans)

    top_dossier_html = f"""
    <div class="f2-report-header">
        <div class="f2-report-header-top">
            {back_link_html}
            <div class="f2-report-actions">
                {reanalyze_btn_html}
                <a href="/reports/{job_id}/export.md" class="btn btn-secondary btn-sm" id="btn-export-markdown" download="report-{job_id}.md" title="Download report as Markdown">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                    Export as Markdown
                </a>
                <button type="button" onclick="window.print()" class="btn btn-secondary btn-sm" title="Print or save as PDF">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 6 2 18 2 18 9"></polyline>
                        <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path>
                        <rect x="6" y="14" width="12" height="8"></rect>
                    </svg>
                    Print Architecture Report
                </button>
            </div>
        </div>
        <div class="f2-report-dossier">
            <h1 class="f2-report-title">Architecture Report: <span style="font-style: italic; color: var(--accent);">{repo_name}</span></h1>
            <div class="f2-report-subtitle">
                Codebase Intelligence Report &bull; Structural Syntax Tree &amp; Dependency Reconstruction
            </div>
            <div class="f2-report-meta">
                {f2_meta_html}
            </div>
        </div>
    </div>
    """

    tabs_nav_html = """
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
    """

    content = f"""
    <div class="f2-report-container" style="max-width: 1040px; margin: 0 auto;">
        {showcase_banner_html}
        {no_history_note_html}
        {top_dossier_html}
        {tabs_nav_html}

        <div class="report-tab-pane" id="tab-pane-overview" role="tabpanel" aria-labelledby="tab-btn-overview">
            {overview_section_html}
        </div>

        <div class="report-tab-pane" id="tab-pane-graph" role="tabpanel" aria-labelledby="tab-btn-graph" style="display: none;">
            {graph_section_html}
        </div>

        {milestones_pane}

        {quiz_pane}
    </div>
    """

    extra_head = cm_head + """
    <link rel="stylesheet" href="/static/frontend2/report.css">
    <link rel="stylesheet" href="/static/frontend2/map.css">
    """

    extra_scripts = cm_scripts + (runtime_script or "") + quiz_helper_js

    return page_shell(
        repo_name,
        content,
        current_user=None if is_showcase else current_user,
        active_route="/showcase" if is_showcase else "/report",
        billing_status=None if is_showcase else billing_status,
        extra_head=extra_head,
        extra_scripts=extra_scripts,
    )


