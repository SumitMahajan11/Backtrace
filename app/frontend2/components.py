"""Frontend v2 UI Components and Application Shell."""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import billing_enabled, rewards_enabled
from app.core.failure_reason import failure_reason
from app.frontend2.icons import render_icon
from app.models.db import UserModel
from app.ui.sanitizer import sanitize_text


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
    <header class="nav-shell">
        <div class="nav-shell-inner">
            <div class="f2-header-left">
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
    <header class="nav-shell">
        <div class="nav-shell-inner">
            <div class="f2-header-left">
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
                <button type="button" class="f2-subnav-tab" id="f2-subnav-learning" onclick="switchReportTab('learning')">
                    {render_icon('book', 16)} Learn
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
            <a href="#learning" class="f2-bottom-tab" id="f2-bottom-learning" onclick="switchReportTab('learning'); return false;">
                {render_icon('book', 20)}
                <span>Learn</span>
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

        function switchReportTab(tabId) {{
            // Trigger legacy frontend1 tab button if present
            const btn = document.getElementById('tab-btn-' + tabId);
            if (btn) {{
                btn.click();
            }}

            // Update subnav active class
            document.querySelectorAll('.f2-subnav-tab').forEach(el => el.classList.remove('active'));
            const sub = document.getElementById('f2-subnav-' + tabId);
            if (sub) sub.classList.add('active');

            // Update bottom bar active class
            document.querySelectorAll('.f2-bottom-tab').forEach(el => el.classList.remove('active'));
            const bot = document.getElementById('f2-bottom-' + tabId);
            if (bot) bot.classList.add('active');
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

