"""Frontend v2 UI Components and Application Shell."""

from __future__ import annotations

import html
import os
import re
from typing import Any, Dict, Optional

from app.core.config import billing_enabled, rewards_enabled
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
    safe_username = html.escape(sanitize_text(raw_username))

    avatar_html = (
        f'<img src="{html.escape(sanitize_text(current_user.avatar_url))}" alt="Avatar" class="avatar" />'
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
    safe_title = html.escape(clean_title)

    if clean_title == "Dashboard":
        doc_title = "<title>Dashboard · Backtrace</title>"
    elif clean_title.startswith("Architecture Report: "):
        repo_part = html.escape(clean_title.replace("Architecture Report: ", ""))
        doc_title = f"<title>{repo_part} · Backtrace</title>"
    elif active_route == "/login" or title == "Backtrace - Understand any GitHub repository":
        doc_title = "<title>Backtrace - Understand any GitHub repository</title>"
    else:
        doc_title = f"<title>{safe_title} · Backtrace</title>"

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
