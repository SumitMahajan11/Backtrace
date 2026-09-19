"""HTML Component builder for Backtrace Frontend UI.

Provides semantic, beautifully styled, server-rendered HTML components
with dark mode styling, glassmorphism, responsive cards, and clean typography.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.models.db import UserModel
from app.services.hint_engine import HintEngine
from app.services.structural_verifier import StructuralVerifier
from app.ui.sanitizer import sanitize_text, render_safe_markdown


def nav_shell(
    current_user: Optional[UserModel] = None,
    active_route: str = "",
    billing_status: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the persistent Archival Dossier navigation header shell."""
    if not current_user:
        return """
    <header class="nav-shell">
        <a href="/login" class="brand" id="nav-brand-link">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
            <span class="brand-title">Backtrace</span>
            <span class="brand-pill">Dossier Engine</span>
        </a>
        <div class="nav-right" style="display: flex; align-items: center; gap: 0.75rem;">
            <button id="theme-toggle" class="theme-toggle-btn" onclick="toggleTheme()" type="button" aria-label="Toggle dark/light mode" title="Toggle Light/Dark Theme">
                <span id="theme-toggle-icon">◐</span>
                <span id="theme-toggle-label">Theme</span>
            </button>
            <a href="/login" class="btn btn-sm btn-primary">Sign In</a>
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
            <div class="tag tag-brass" id="nav-tier-tag" style="display: inline-flex; align-items: center; gap: 0.35rem;">
                <span class="chip-dot brass"></span>
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; font-weight: 600; color: var(--brass);">PRO</span>
            </div>
            """
        else:
            usage = billing_status.get("monthly_usage", billing_status.get("quota_used", 0))
            limit = billing_status.get("monthly_quota", billing_status.get("quota_limit", 5))
            tier_tag = f"""
            <div class="tag tag-brass" id="nav-tier-tag" style="display: inline-flex; align-items: center; gap: 0.35rem;">
                <span class="chip-dot brass"></span>
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; font-weight: 600; color: var(--brass);">FREE ({usage}/{limit})</span>
            </div>
            """

    dashboard_active = "active" if active_route == "/dashboard" else ""
    rewards_active = "active" if active_route in ("/rewards", "/points") else ""
    settings_active = "active" if active_route == "/settings" else ""

    return f"""
    <header class="nav-shell">
        <div style="display: flex; align-items: center; gap: 1.25rem;">
            <a href="/dashboard" class="brand" id="nav-brand-link">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                <span class="brand-title">Backtrace</span>
                <span class="brand-pill">Dossier Engine</span>
            </a>
            {tier_tag}
        </div>

        <div style="display: flex; align-items: center; gap: 1.25rem;">
            <nav class="nav-links">
                <a href="/dashboard" class="nav-link {dashboard_active}" id="nav-link-dashboard" data-path="dashboard" {'aria-current="page"' if dashboard_active else ''}>Dashboard</a>
                <a href="/rewards" class="nav-link {rewards_active}" id="nav-link-rewards" data-path="rewards" {'aria-current="page"' if rewards_active else ''}>Rewards & Badges</a>
                <a href="/settings" class="nav-link {settings_active}" id="nav-link-settings" data-path="settings" {'aria-current="page"' if settings_active else ''}>Settings</a>
            </nav>

            <div class="nav-right" style="display: flex; align-items: center; gap: 0.75rem;">
                <button id="theme-toggle" class="theme-toggle-btn" onclick="toggleTheme()" type="button" aria-label="Toggle dark/light mode" title="Toggle Light/Dark Theme">
                    <span id="theme-toggle-icon">◐</span>
                    <span id="theme-toggle-label">Theme</span>
                </button>
                <div class="user-pill" style="display: flex; align-items: center; gap: 0.65rem; background: var(--panel-raised); border: 1px solid var(--hairline); padding: 0.25rem 0.65rem; border-radius: 4px;">
                    {avatar_html}
                    <span class="username" style="font-family: 'IBM Plex Mono', monospace; font-size: 0.8125rem; font-weight: 500; color: var(--text-primary);">@{safe_username}</span>
                    <a href="/auth/logout" class="btn btn-sm btn-ghost" id="nav-logout-btn" style="padding: 0.2rem 0.5rem; font-size: 0.75rem; text-transform: uppercase; color: var(--text-tertiary);" title="Sign out of Backtrace">Log out</a>
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
    """Wrap content in a consistent, modern Archival Dossier application layout."""
    rendered_nav = nav_shell(
        current_user=current_user,
        active_route=active_route,
        billing_status=billing_status,
    )

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{sanitize_text(title)} // Backtrace Repository Archaeology</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&display=swap" rel="stylesheet">
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
           Backtrace Archival Dossier — Design System Tokens
           ========================================================================== */
        :root, :root[data-theme="dark"] {{
            --ink: #0d0f12;
            --panel: #13171f;
            --panel-raised: #1a202c;
            --panel-overlay: #232a38;
            
            --hairline: #262f3e;
            --hairline-soft: #1c2330;
            
            --text-primary: #f0f4f8;
            --text-secondary: #94a3b8;
            --text-tertiary: #8295ab;
            
            --brass: #d4a359;
            --brass-hover: #deb46f;
            --brass-soft: rgba(212, 163, 89, 0.12);
            --brass-border: rgba(212, 163, 89, 0.35);

            --teal: #2dd4bf;
            --teal-dim: #115e59;
            --teal-soft: rgba(45, 212, 191, 0.12);
            --teal-border: rgba(45, 212, 191, 0.35);

            --amber: #f59e0b;
            --amber-soft: rgba(245, 158, 11, 0.12);

            --crimson: #f43f5e;
            --crimson-soft: rgba(244, 63, 94, 0.12);
            
            --focus-ring: rgba(212, 163, 89, 0.5);
            color-scheme: dark;
        }}

        :root[data-theme="light"] {{
            --ink: #f7f9fc;
            --panel: #ffffff;
            --panel-raised: #eef2f7;
            --panel-overlay: #e2e8f0;
            
            --hairline: #cbd5e1;
            --hairline-soft: #e2e8f0;
            
            --text-primary: #0f172a;
            --text-secondary: #475569;
            --text-tertiary: #52637a;
            
            --brass: #875a14;
            --brass-hover: #9e6b1a;
            --brass-soft: rgba(135, 90, 20, 0.12);
            --brass-border: rgba(135, 90, 20, 0.3);

            --teal: #0d9488;
            --teal-dim: #134e4a;
            --teal-soft: rgba(13, 148, 136, 0.1);
            --teal-border: rgba(13, 148, 136, 0.3);

            --amber: #d97706;
            --amber-soft: rgba(217, 119, 6, 0.12);

            --crimson: #e11d48;
            --crimson-soft: rgba(225, 29, 72, 0.12);

            --focus-ring: rgba(135, 90, 20, 0.4);
            color-scheme: light;
        }}

        /* Reset & Base Typography */
        *, *::before, *::after {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--ink);
            color: var(--text-primary);
            font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            font-size: 0.9375rem;
            line-height: 1.5;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            transition: background-color 150ms ease, color 150ms ease;
            -webkit-font-smoothing: antialiased;
        }}

        h1, h2, h3, h4, .serif-heading {{
            font-family: 'Newsreader', Georgia, serif;
            font-weight: 500;
            color: var(--text-primary);
            line-height: 1.25;
            letter-spacing: -0.01em;
        }}

        code, pre, .mono, .chip, .tag, .badge {{
            font-family: 'IBM Plex Mono', monospace;
        }}

        a {{
            color: var(--brass);
            text-decoration: none;
            transition: color 120ms ease;
        }}

        a:hover {{
            color: var(--brass-hover);
        }}

        /* Navigation Header Shell */
        .nav-shell {{
            background: var(--panel);
            border-bottom: 1px solid var(--hairline);
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
            color: var(--text-primary);
        }}

        .brand:hover {{
            color: var(--text-primary);
        }}

        .brand-title {{
            font-family: 'Newsreader', Georgia, serif;
            font-size: 1.35rem;
            font-weight: 500;
            letter-spacing: -0.02em;
            color: var(--text-primary);
        }}

        .brand-pill {{
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.6875rem;
            padding: 0.15rem 0.5rem;
            border-radius: 2px;
            background: var(--brass-soft);
            color: var(--brass);
            border: 1px solid var(--brass-border);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .nav-links {{
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }}

        .nav-link {{
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.8125rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: var(--text-secondary);
            padding: 0.4rem 0.85rem;
            border-radius: 4px;
            border: 1px solid transparent;
            text-decoration: none;
            transition: all 120ms ease;
            line-height: 1.25;
        }}

        .nav-link:hover {{
            color: var(--text-primary);
            background: var(--panel-raised);
            border-color: var(--hairline-soft);
        }}

        .nav-link.active {{
            color: var(--brass);
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
            border: 1px solid var(--hairline);
            color: var(--text-secondary);
            padding: 0.35rem 0.65rem;
            border-radius: 4px;
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.75rem;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            transition: all 120ms ease;
        }}

        .theme-toggle-btn:hover {{
            background: var(--panel-overlay);
            color: var(--text-primary);
            border-color: var(--hairline);
        }}

        .theme-toggle-btn:focus,
        .theme-toggle-btn:focus-visible {{
            outline: none;
            border-color: var(--brass);
            box-shadow: 0 0 0 2px var(--focus-ring);
        }}

        .user-pill {{
            display: flex;
            align-items: center;
            gap: 0.65rem;
            background: var(--panel-raised);
            border: 1px solid var(--hairline);
            padding: 0.25rem 0.75rem;
            border-radius: 4px;
        }}

        .avatar {{
            width: 22px;
            height: 22px;
            border-radius: 50%;
            object-fit: cover;
            border: 1px solid var(--hairline);
        }}

        .avatar-placeholder {{
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: var(--hairline);
        }}

        .username {{
            font-size: 0.8125rem;
            font-weight: 500;
            color: var(--text-primary);
        }}

        /* Container Layout */
        .container {{
            max-width: 1120px;
            margin: 0 auto;
            padding: 2.25rem 1.5rem;
            width: 100%;
            flex: 1;
        }}

        /* Stratum Cards / Dossier Containers */
        .stratum-card {{
            background: var(--panel);
            border: 1px solid var(--hairline);
            border-radius: 4px;
            padding: 1.75rem;
            margin-bottom: 1.75rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
            transition: border-color 120ms ease;
        }}

        .stratum-card:hover {{
            border-color: var(--hairline);
        }}

        .card {{
            background: var(--panel);
            border: 1px solid var(--hairline);
            border-radius: 4px;
            padding: 1.75rem;
            margin-bottom: 1.75rem;
        }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.25rem;
            padding-bottom: 0.85rem;
            border-bottom: 1px solid var(--hairline-soft);
        }}

        /* Buttons */
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.55rem 1.15rem;
            font-family: 'IBM Plex Sans', sans-serif;
            font-size: 0.875rem;
            font-weight: 600;
            border-radius: 4px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 120ms ease;
            text-decoration: none;
            line-height: 1.25;
        }}

        .btn-primary {{
            background: var(--brass);
            color: #0d0f12 !important;
            border-color: var(--brass);
        }}

        .btn-primary:hover {{
            background: var(--brass-hover);
            border-color: var(--brass-hover);
            color: #0d0f12 !important;
        }}

        .btn-secondary {{
            background: var(--panel-raised);
            color: var(--text-primary);
            border-color: var(--hairline);
        }}

        .btn-secondary:hover {{
            background: var(--panel-overlay);
            border-color: var(--text-secondary);
        }}

        .btn-ghost {{
            background: transparent;
            color: var(--text-secondary);
        }}

        .btn-ghost:hover {{
            color: var(--text-primary);
            background: var(--panel-raised);
        }}

        .btn-sm {{
            padding: 0.35rem 0.75rem;
            font-size: 0.8125rem;
        }}

        .btn-danger {{
            background: var(--crimson-soft);
            color: var(--crimson);
            border-color: var(--crimson);
        }}

        .btn-danger:hover {{
            background: var(--crimson);
            color: #ffffff;
        }}

        /* Confidence Meter */
        .meter {{
            width: 100%;
            height: 4px;
            background: var(--hairline-soft);
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
            background: var(--teal);
            box-shadow: 0 0 6px rgba(45, 212, 191, 0.4);
        }}

        .meter-fill.medium {{
            background: var(--amber);
        }}

        .meter-fill.low {{
            background: var(--crimson);
        }}

        /* Tags & Chips */
        .chip, .tag {{
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.2rem 0.55rem;
            border-radius: 2px;
            font-size: 0.6875rem;
            font-weight: 500;
            letter-spacing: 0.04em;
            background: var(--panel-raised);
            border: 1px solid var(--hairline);
            color: var(--text-secondary);
            text-transform: uppercase;
        }}

        .chip-dot {{
            width: 6px;
            height: 6px;
            border-radius: 50%;
        }}

        .chip-dot.teal {{ background: var(--teal); }}
        .chip-dot.brass {{ background: var(--brass); }}
        .chip-dot.amber {{ background: var(--amber); }}
        .chip-dot.crimson {{ background: var(--crimson); }}

        /* Badges */
        .badge {{
            display: inline-flex;
            align-items: center;
            padding: 0.2rem 0.5rem;
            border-radius: 2px;
            font-size: 0.6875rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .badge-free {{
            background: var(--panel-raised);
            color: var(--text-secondary);
            border: 1px solid var(--hairline);
        }}

        .badge-paid, .badge-brass {{
            background: var(--brass-soft);
            color: var(--brass);
            border: 1px solid var(--brass-border);
        }}

        .badge-completed, .badge-teal {{
            background: var(--teal-soft);
            color: var(--teal);
            border: 1px solid var(--teal-border);
        }}

        .badge-running {{
            background: var(--brass-soft);
            color: var(--brass);
            border: 1px solid var(--brass-border);
        }}

        .badge-failed, .badge-crimson {{
            background: var(--crimson-soft);
            color: var(--crimson);
            border: 1px solid var(--crimson);
        }}

        .badge-pending, .badge-amber {{
            background: var(--amber-soft);
            color: var(--amber);
            border: 1px solid var(--amber);
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
            color: var(--text-secondary);
            font-family: 'IBM Plex Sans', sans-serif;
        }}

        .form-input {{
            width: 100%;
            background: var(--panel-raised);
            border: 1px solid var(--hairline);
            border-radius: 4px;
            padding: 0.65rem 0.95rem;
            color: var(--text-primary);
            font-family: 'IBM Plex Sans', sans-serif;
            font-size: 0.9375rem;
            outline: none;
            transition: border-color 120ms ease, box-shadow 120ms ease;
        }}

        .form-input:focus {{
            border-color: var(--brass);
            box-shadow: 0 0 0 2px var(--focus-ring);
        }}

        .form-input::placeholder {{
            color: var(--text-tertiary);
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
            color: var(--text-tertiary);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.75rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--hairline);
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
            border: 1px solid var(--teal);
            color: var(--teal);
            padding: 0.85rem 1.15rem;
            border-radius: 4px;
            margin-bottom: 1.25rem;
            font-size: 0.875rem;
        }}

        /* Markdown / Report Styling */
        .markdown-body {{
            line-height: 1.7;
            color: var(--text-primary);
        }}

        .markdown-body h1, .markdown-body h2, .markdown-body h3 {{
            color: var(--text-primary);
            margin-top: 1.75rem;
            margin-bottom: 0.75rem;
            font-family: 'Newsreader', Georgia, serif;
            font-weight: 500;
        }}

        .markdown-body h1 {{ font-size: 1.85rem; border-bottom: 1px solid var(--hairline); padding-bottom: 0.5rem; }}
        .markdown-body h2 {{ font-size: 1.45rem; }}
        .markdown-body h3 {{ font-size: 1.2rem; }}
        .markdown-body p {{ margin-bottom: 1rem; }}
        .markdown-body ul, .markdown-body ol {{ margin-left: 1.5rem; margin-bottom: 1rem; }}
        
        .markdown-body code {{
            background: var(--panel-raised);
            padding: 0.2rem 0.4rem;
            border-radius: 3px;
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.8125rem;
            color: var(--brass);
            border: 1px solid var(--hairline-soft);
        }}

        .markdown-body pre {{
            background: var(--ink);
            border: 1px solid var(--hairline);
            border-radius: 4px;
            padding: 1.25rem;
            overflow-x: auto;
            margin-bottom: 1.5rem;
        }}

        .markdown-body pre code {{
            background: transparent;
            padding: 0;
            border: none;
            color: var(--text-primary);
        }}

        /* Footer */
        .footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-tertiary);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.75rem;
            border-top: 1px solid var(--hairline);
        }}

        /* Accessibility & Responsive Refinements (Prompt 8) */
        :focus-visible {{
            outline: 2px solid var(--brass);
            outline-offset: 2px;
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
    {rendered_nav}
    <main class="container">
        {content}
    </main>
    <footer class="footer">
        Backtrace 11-Layer Reverse Code Intelligence &bull; Secured with GitHub OAuth &amp; Stripe
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
            const icon = document.getElementById('theme-toggle-icon');
            const label = document.getElementById('theme-toggle-label');
            if (icon) {{
                icon.textContent = theme === 'dark' ? '☾' : '☼';
            }}
            if (label) {{
                label.textContent = theme === 'dark' ? 'Dark' : 'Light';
            }}
            if (typeof updateThemeCards === 'function') {{
                updateThemeCards();
            }}
        }}

        document.addEventListener('DOMContentLoaded', function() {{
            const current = document.documentElement.getAttribute('data-theme') || 'dark';
            updateThemeControls(current);
        }});
    </script>
    {extra_scripts}
</body>
</html>
"""


def login_view(error: Optional[str] = None) -> str:
    """Render the Clean Login View with GitHub OAuth adhering to Archival Dossier tokens."""
    error_html = f'<div class="alert-error">{sanitize_text(error)}</div>' if error else ""
    content = f"""
    <div style="max-width: 440px; margin: 4rem auto 0 auto; text-align: center;">
        <div class="stratum-card" style="padding: 2.5rem 2rem;">
            <div style="margin-bottom: 2rem;">
                <div style="display: inline-flex; align-items: center; justify-content: center; width: 56px; height: 56px; background: var(--brass-soft); border: 1px solid var(--brass-border); border-radius: 4px; margin-bottom: 1.25rem;">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--brass)" stroke-width="2">
                        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                        <polyline points="2 17 12 22 22 17"></polyline>
                        <polyline points="2 12 12 17 22 12"></polyline>
                    </svg>
                </div>
                <h1 style="font-size: 1.85rem; font-weight: 500; margin-bottom: 0.5rem; letter-spacing: -0.02em;">Welcome to Backtrace</h1>
                <p style="color: var(--text-secondary); font-size: 0.9rem; line-height: 1.5;">Reverse-engineer codebase architecture into executable mental models.</p>
                <div style="display: flex; align-items: center; justify-content: center; gap: 0.5rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--hairline-soft);">
                    <span>AUTHENTICATION GATE</span>
                    <span>&bull;</span>
                    <span>GITHUB OAUTH 2.0</span>
                </div>
            </div>
            {error_html}
            <a href="/auth/github/login" class="btn btn-primary" style="width: 100%; justify-content: center; padding: 0.8rem; font-size: 0.95rem;">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                    <path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"></path>
                </svg>
                Sign in with GitHub
            </a>
            <div style="margin-top: 1.5rem; font-size: 0.75rem; color: var(--text-tertiary); font-family: 'IBM Plex Mono', monospace;">
                ZERO-PERSISTENCE CODE CLONE PROTOCOL
            </div>
        </div>
    </div>
    """
    return page_shell("Sign In", content)


def dashboard_view(
    current_user: UserModel,
    billing_status: Dict[str, Any],
    past_jobs: List[Any],
    error: Optional[str] = None,
) -> str:
    """
    Render the Archival Dossier Dashboard.
    Features:
    - Editorial Header & Inquest Ledger Metadata
    - Real Free/Paid Quota Meter & Renewal Date
    - Stratum Card: Reconstruct Repository History with sample URL chip & assurance signals
    - Analysis History Ledger with empty state or populated ledger table/cards
    - Real Retry Action for failed jobs (POST /analyses/{job_id}/retry)
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if now.month == 12:
        next_month_date = datetime(now.year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    else:
        next_month_date = datetime(now.year, now.month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    renewal_date_str = next_month_date.strftime("%b %d, %Y").upper()

    tier = billing_status.get("tier", "free")
    used = int(billing_status.get("monthly_usage", 0))
    limit = billing_status.get("monthly_quota")

    if tier == "paid":
        quota_badge = '<span class="badge badge-paid">PRO TIER</span>'
        consumption_text = "UNLIMITED INQUESTS"
        meter_pct = 100
        tier_action = '<a href="/api/billing/portal" class="btn btn-sm btn-secondary">Manage Billing</a>'
    else:
        quota_badge = '<span class="badge badge-free">FREE TIER</span>'
        limit_val = int(limit) if limit is not None else 5
        pct = min(100, int((used / max(1, limit_val)) * 100))
        meter_pct = pct
        consumption_text = f"{used} / {limit_val} JOBS ALLOTTED ({pct}% CONSUMED)"
        tier_action = '<a href="/api/billing/checkout" class="btn btn-sm btn-primary">Upgrade to Pro</a>'

    error_html = f'<div class="alert-error" style="margin-bottom: 1.5rem;">{sanitize_text(error)}</div>' if error else ""

    # Build job history rows
    rows_html = ""
    for job in past_jobs:
        job_id = sanitize_text(str(job.id))
        repo_url = sanitize_text(job.repo_url)
        repo_display = sanitize_text(job.repo_name or (job.repo_url.rstrip("/").split("/")[-1] if "/" in job.repo_url else job.repo_url))
        status = sanitize_text(job.status)
        created_at = sanitize_text(job.created_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(job.created_at, "strftime") else str(job.created_at))
        duration_str = f"{job.execution_time_seconds:.1f}s" if getattr(job, "execution_time_seconds", 0) else "—"

        status_badge_class = f"badge-{status}" if status in ["completed", "running", "failed", "pending"] else "badge-free"

        # Compute Learning Progress (X/Y Milestones Verified)
        verified_count = 0
        total_milestones = 0
        if job.graph_data and isinstance(job.graph_data, dict):
            nodes = job.graph_data.get("nodes", [])
            tier_set = {n.get("tier") for n in nodes if n.get("tier") is not None}
            total_milestones = len(tier_set)

        if total_milestones == 0 and job.markdown_output:
            total_milestones = len(re.findall(r"###\s+Milestone\s+\d+:", job.markdown_output))

        if hasattr(job, "milestone_attempts") and job.milestone_attempts:
            verified_count = sum(1 for a in job.milestone_attempts if a.status == "structurally_verified")
        elif hasattr(job, "id") and current_user:
            try:
                from app.storage.milestone_attempt_repository import MilestoneAttemptRepository
                # If session is active or available, could query, else defaults to 0
                pass
            except Exception:
                pass

        if total_milestones == 0 and verified_count > 0:
            total_milestones = verified_count

        if status == "completed":
            total_milestones = max(1, total_milestones)
            pct = int((verified_count / total_milestones) * 100)
            if verified_count == total_milestones:
                progress_badge = f'<span class="badge badge-teal" style="font-family: \'IBM Plex Mono\', monospace; font-size: 0.75rem;"><span class="chip-dot teal"></span> {verified_count}/{total_milestones} VERIFIED</span>'
            elif verified_count > 0:
                progress_badge = f'<span class="badge badge-amber" style="font-family: \'IBM Plex Mono\', monospace; font-size: 0.75rem;"><span class="chip-dot amber"></span> {verified_count}/{total_milestones} VERIFIED</span>'
            else:
                progress_badge = f'<span class="badge badge-free" style="font-family: \'IBM Plex Mono\', monospace; font-size: 0.75rem;"><span class="chip-dot brass"></span> 0/{total_milestones} VERIFIED</span>'
        else:
            progress_badge = '<span style="color: var(--text-tertiary); font-family: \'IBM Plex Mono\', monospace; font-size: 0.75rem;">—</span>'

        action_btn = ""
        if status == "completed":
            action_btn = f'<a href="/report/{job_id}" class="btn btn-sm btn-primary">View Dossier</a>'
        elif status in ["running", "pending"]:
            action_btn = f'<a href="/progress/{job_id}" class="btn btn-sm btn-secondary">Track Progress</a>'
        else:
            action_btn = f"""
            <div style="display: flex; align-items: center; justify-content: flex-end; gap: 0.5rem;">
                <form action="/analyses/{job_id}/retry" method="POST" style="margin: 0; display: inline;">
                    <button type="submit" class="btn btn-sm btn-secondary" style="color: var(--crimson); border-color: var(--crimson);">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 0.25rem;">
                            <polyline points="1 4 1 10 7 10"></polyline>
                            <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
                        </svg>
                        Retry Inquest
                    </button>
                </form>
            </div>
            """

        rows_html += f"""
        <tr>
            <td>
                <div style="font-weight: 600; color: var(--text-primary);">{repo_display}</div>
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-tertiary);">{repo_url}</div>
            </td>
            <td><span class="badge {status_badge_class}">{status.upper()}</span></td>
            <td>{progress_badge}</td>
            <td style="color: var(--text-secondary); font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;">{created_at}</td>
            <td style="color: var(--text-secondary); font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;">{duration_str}</td>
            <td style="text-align: right;">{action_btn}</td>
        </tr>
        """

    if not past_jobs:
        history_content = """
        <div style="padding: 3rem 1.5rem; text-align: center; background: var(--panel-raised); border-radius: 4px; border: 1px dashed var(--hairline);">
            <div style="display: inline-flex; align-items: center; justify-content: center; width: 48px; height: 48px; background: var(--brass-soft); border: 1px solid var(--brass-border); border-radius: 50%; margin-bottom: 1rem; color: var(--brass);">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                </svg>
            </div>
            <h3 style="font-size: 1.25rem; font-weight: 500; margin-bottom: 0.4rem;">No analyses yet</h3>
            <p style="color: var(--text-secondary); font-size: 0.875rem; max-width: 480px; margin: 0 auto 1.25rem auto; line-height: 1.5;">
                No analyses yet. Paste a GitHub URL above to reconstruct your first build history.
            </p>
            <button type="button" class="btn btn-sm btn-secondary" onclick="document.getElementById('repo-url-input').value='https://github.com/expressjs/express'; document.getElementById('repo-url-input').focus();">
                <span style="color: var(--brass); font-weight: 600; margin-right: 0.25rem;">Sample:</span> https://github.com/expressjs/express
            </button>
        </div>
        """
    else:
        history_content = f"""
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Repository Specification</th>
                        <th>Status</th>
                        <th>Learning Progress</th>
                        <th>Submitted (UTC)</th>
                        <th>Duration</th>
                        <th style="text-align: right;">Action</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """

    content = f"""
    <div style="display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 1.5rem; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--hairline);">
        <div style="max-width: 680px;">
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.35rem;">
                <span class="chip-dot brass"></span>
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); text-transform: uppercase; letter-spacing: 0.05em;">
                    DOSSIER REPOSITORY INGESTION
                </span>
            </div>
            <h1 style="font-size: 2.25rem; font-weight: 500; letter-spacing: -0.02em; margin-bottom: 0.5rem;">
                Root-Cause Inquest Ledger
            </h1>
            <p style="color: var(--text-secondary); font-size: 0.95rem; line-height: 1.5;">
                Submit version-controlled source archives to initiate deep lineage deconstruction, chronological strata synthesis, and automated code regression attribution.
            </p>
        </div>
        
        <!-- Tier & Quota Indicator -->
        <div class="stratum-card" style="padding: 1rem 1.25rem; min-width: 280px; margin: 0;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); text-transform: uppercase;">
                    QUOTA STATUS
                </span>
                {quota_badge}
            </div>
            <div style="font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 0.8125rem; color: var(--text-primary); margin-bottom: 0.4rem;">
                {consumption_text}
            </div>
            <div class="meter" style="margin-bottom: 0.65rem; height: 5px;">
                <div class="meter-fill high" style="width: {meter_pct}%;"></div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; color: var(--text-tertiary); border-top: 1px solid var(--hairline-soft); padding-top: 0.5rem;">
                <span>RENEWS: <strong style="color: var(--text-secondary);">{renewal_date_str}</strong></span>
                {tier_action}
            </div>
        </div>
    </div>

    {error_html}

    <!-- Main Stratum Card: Repo Submission Form -->
    <div class="stratum-card" style="margin-bottom: 2.5rem;">
        <div class="card-header">
            <div style="display: flex; align-items: center; gap: 0.65rem;">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--brass)" stroke-width="2">
                    <circle cx="18" cy="18" r="3"></circle>
                    <circle cx="6" cy="6" r="3"></circle>
                    <path d="M13 6h3a2 2 0 0 1 2 2v7"></path>
                    <line x1="6" y1="9" x2="6" y2="21"></line>
                </svg>
                <h2 style="font-size: 1.35rem; font-weight: 500;">Reconstruct Repository History</h2>
            </div>
            <div class="chip">
                <span class="chip-dot brass"></span>
                <span>Zero-Persistence Sandbox</span>
            </div>
        </div>

        <form action="/analyses/submit" method="POST" id="reconstruct-form">
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; margin-bottom: 1.25rem;">
                <div class="form-group" style="margin-bottom: 0;">
                    <label class="form-label" for="repo-url-input">
                        Target Git Repository HTTPS URL <span style="color: var(--crimson); font-weight: bold;">*</span>
                    </label>
                    <input 
                        type="url" 
                        id="repo-url-input"
                        name="repo_url" 
                        required 
                        class="form-input" 
                        placeholder="https://github.com/organization/repository" 
                        pattern="https://github.com/.+/.+"
                        title="Please enter a valid GitHub repository URL"
                    />
                </div>
                <div class="form-group" style="margin-bottom: 0;">
                    <label class="form-label" for="branch-ref-input">
                        Branch / Commit Ref <span style="color: var(--text-tertiary); font-weight: normal;">(Optional)</span>
                    </label>
                    <input 
                        type="text" 
                        id="branch-ref-input"
                        name="commit_ref" 
                        class="form-input" 
                        placeholder="main or HEAD" 
                    />
                </div>
            </div>

            <div style="display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--hairline-soft);">
                <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;">
                    <span class="chip"><span class="chip-dot teal"></span> Granular AST Parsing</span>
                    <span class="chip"><span class="chip-dot brass"></span> Deterministic Strata Slicing</span>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="document.getElementById('repo-url-input').value='https://github.com/expressjs/express'; document.getElementById('repo-url-input').focus();" style="font-size: 0.75rem;">
                        Sample: expressjs/express
                    </button>
                </div>
                <button type="submit" class="btn btn-primary" style="padding: 0.65rem 1.25rem;">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                        <polyline points="2 17 12 22 22 17"></polyline>
                        <polyline points="2 12 12 17 22 12"></polyline>
                    </svg>
                    Begin Forensic Reconstruction
                </button>
            </div>
        </form>
    </div>

    <!-- Analysis History Section -->
    <div class="stratum-card">
        <div class="card-header">
            <div style="display: flex; align-items: center; gap: 0.65rem;">
                <h2 style="font-size: 1.35rem; font-weight: 500;">Analysis History Ledger</h2>
                <span class="chip">{len(past_jobs)} INQUEST RECORDS</span>
            </div>
            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary);">
                ORDERED BY SUBMISSION CHRONOLOGY
            </div>
        </div>
        {history_content}
    </div>
    """
    return page_shell(
        "Dashboard",
        content,
        current_user=current_user,
        active_route="/dashboard",
        billing_status=billing_status,
    )


def progress_view(
    job: Any,
    current_user: UserModel,
    billing_status: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the Live Progress view with Server-Sent Events (SSE) updates adhering to Archival Dossier tokens."""
    job_id = sanitize_text(str(job.id))
    repo_url = sanitize_text(job.repo_url)

    stages_data = [
        (
            "stage_0",
            "00",
            "Consent & Auth Gate",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>',
            "Authorizing repository access and establishing a secure ephemeral execution boundary.",
            "Verified GitHub OAuth scopes and validated repository read permissions against security policies.",
        ),
        (
            "stage_1",
            "01",
            "Shallow Clone",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>',
            "Fetching the target codebase into an isolated, memory-bounded analysis container.",
            "Executed blobless shallow git clone (depth=1) into an isolated ephemeral sandbox environment.",
        ),
        (
            "stage_2",
            "02",
            "Discovery & File Hierarchy",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>',
            "Scanning the file system, cataloging project manifests, and measuring language breakdown.",
            "Mapped file tree layout, language distribution, build manifests, and package boundaries.",
        ),
        (
            "stage_3",
            "03",
            "AST & Syntax Parsing",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>',
            "Parsing source code into concrete syntax trees to extract functions, classes, and statements.",
            "Extracted concrete syntax trees (CST/AST) and parsed structural import/export declarations.",
        ),
        (
            "stage_4",
            "04",
            "Global Symbol Table",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>',
            "Indexing public API interfaces, exported symbols, and type declarations across packages.",
            "Cataloged function signatures, class hierarchies, interfaces, and public API boundaries.",
        ),
        (
            "stage_5",
            "05",
            "Directed Dependency Graph",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line></svg>',
            "Tracing import chains and resolving internal dependencies into a topological directed graph.",
            "Constructed directed acyclic graph (DAG) and resolved cross-module import relationships.",
        ),
        (
            "stage_6",
            "06",
            "Architecture Domain Mapping",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>',
            "Grouping modules into architectural subsystems, core domains, and circular dependency clusters.",
            "Segmented codebase into architectural tiers, cyclic clusters, and entry-point strata.",
        ),
        (
            "stage_7",
            "07",
            "LLM Cognitive Narration",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 0 1 10 10c0 5.523-4.477 10-10 10a9.96 9.96 0 0 1-4.887-1.277L2 22l1.277-5.113A9.96 9.96 0 0 1 2 12C2 6.477 6.477 2 12 2z"></path></svg>',
            "Synthesizing an architectural reading order and explaining how components collaborate.",
            "Synthesized chronological reading order, subsystem responsibilities, and structural rationale.",
        ),
        (
            "stage_8",
            "08",
            "Graph & Quiz Generation",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
            "Constructing interactive visual call graphs and generating architectural comprehension quizzes.",
            "Generated interactive visual dependency graph nodes and multi-level comprehension quizzes.",
        ),
        (
            "stage_9",
            "09",
            "Persistence & Dossier Assembly",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>',
            "Compiling the verified analysis results and structuring the comprehensive dossier.",
            "Assembled structured schema payload and persisted final report records into the datastore.",
        ),
        (
            "stage_10",
            "10",
            "Telemetry & Quota Allocation",
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
            "Finalizing performance metrics, recording execution duration, and updating account quota.",
            "Recorded execution duration, tracked AST token metrics, and updated user cycle quota.",
        ),
    ]

    stages_html = ""
    for s_key, s_num, s_title, s_svg, s_narrative, s_tech in stages_data:
        stages_html += f"""
        <div class="stage-item" id="card-{s_key}" style="display: flex; gap: 1.15rem; align-items: flex-start; position: relative; margin-bottom: 1rem; transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease;">
            <div id="icon-vessel-{s_key}" class="stage-icon-vessel" style="flex-shrink: 0; width: 36px; height: 36px; border-radius: 50%; background: var(--panel-raised); border: 1px solid var(--hairline); display: flex; align-items: center; justify-content: center; font-size: 0.75rem; color: var(--text-tertiary); z-index: 2; transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);">
                <span id="icon-{s_key}" style="display: flex; align-items: center; justify-content: center;">{s_svg}</span>
            </div>
            <div id="body-{s_key}" class="stage-body" style="flex: 1; background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px; padding: 1.15rem 1.35rem; transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1); box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.4rem;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); font-weight: 600; letter-spacing: 0.05em;">STAGE {s_num}</span>
                        <span style="color: var(--hairline);">/</span>
                        <h3 style="font-size: 1rem; font-weight: 600; color: var(--text-primary); margin: 0; font-family: 'Newsreader', Georgia, serif; letter-spacing: -0.01em;">{s_title}</h3>
                    </div>
                    <span class="badge badge-free" id="badge-{s_key}" style="font-size: 0.625rem; padding: 0.2rem 0.5rem; transition: all 0.3s ease;">QUEUED</span>
                </div>
                <p style="color: var(--text-primary); font-size: 0.875rem; line-height: 1.5; margin: 0 0 0.5rem 0;">
                    {s_narrative}
                </p>
                <details class="tech-details-drawer" style="margin-top: 0.35rem;">
                    <summary style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); cursor: pointer; user-select: none; display: inline-flex; align-items: center; gap: 0.35rem; transition: color 120ms ease;">
                        <span>&gt; Technical Details</span>
                    </summary>
                    <div class="tech-details-content" style="margin-top: 0.4rem; padding: 0.5rem 0.75rem; background: var(--panel-raised); border-left: 2px solid var(--brass); border-radius: 2px; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-secondary); line-height: 1.45;">
                        {s_tech}
                    </div>
                </details>
            </div>
        </div>
        """

    extra_scripts = f"""
    <script>
        const jobId = "{job_id}";
        const eventSource = new EventSource(`/api/analyses/${{jobId}}/events`);
        const statusHeader = document.getElementById("overall-status");
        const statusDesc = document.getElementById("current-stage-title");
        const stageCounter = document.getElementById("completed-stage-count");
        const pctLabel = document.getElementById("percentage-label");
        const progressBar = document.getElementById("progress-fill");
        const logBox = document.getElementById("sse-terminal-log");

        let completedCount = 0;
        const completedStages = new Set();
        const checkmarkSvg = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>';

        function addLogEntry(text, type="info") {{
            if (!logBox) return;
            const now = new Date().toISOString().substring(11, 19) + " UTC";
            const line = document.createElement("div");
            line.style.marginBottom = "0.25rem";
            line.style.fontFamily = "'IBM Plex Mono', monospace";
            line.style.fontSize = "0.75rem";
            
            let color = "var(--text-secondary)";
            if (type === "complete") color = "var(--teal)";
            if (type === "active") color = "var(--brass)";
            if (type === "error") color = "var(--crimson)";

            const timeSpan = document.createElement("span");
            timeSpan.style.color = "var(--text-tertiary)";
            timeSpan.style.marginRight = "0.5rem";
            timeSpan.textContent = `[${{now}}]`;

            const msgSpan = document.createElement("span");
            msgSpan.style.color = color;
            msgSpan.textContent = text;

            line.appendChild(timeSpan);
            line.appendChild(msgSpan);
            logBox.appendChild(line);
            logBox.scrollTop = logBox.scrollHeight;
        }}

        addLogEntry(`Initializing SSE event stream for Inquest Job #${{jobId}}...`);

        eventSource.onmessage = function(event) {{
            try {{
                const data = JSON.parse(event.data);
                
                if (data.type === "progress") {{
                    const stageKey = data.stage;
                    const message = data.message || "Running...";
                    const pct = data.percentage || 0;
                    
                    if (progressBar) progressBar.style.width = pct + "%";
                    if (pctLabel) pctLabel.textContent = pct + "%";
                    if (statusDesc) statusDesc.textContent = message;

                    addLogEntry(`[STAGE] ${{stageKey}}: ${{message}}`, "active");

                    const vessel = document.getElementById("icon-vessel-" + stageKey);
                    const body = document.getElementById("body-" + stageKey);
                    const badge = document.getElementById("badge-" + stageKey);

                    if (vessel && body && badge && !completedStages.has(stageKey)) {{
                        vessel.style.borderColor = "var(--brass)";
                        vessel.style.background = "var(--brass-soft)";
                        vessel.style.color = "var(--brass)";
                        vessel.style.boxShadow = "0 0 0 4px var(--brass-soft)";
                        body.style.borderColor = "var(--brass-border)";
                        body.style.background = "var(--panel-raised)";
                        body.style.transform = "translateX(4px)";
                        badge.className = "badge";
                        badge.style.background = "var(--brass-soft)";
                        badge.style.color = "var(--brass)";
                        badge.style.borderColor = "var(--brass-border)";
                        badge.textContent = "PROCESSING";
                    }}
                }} else if (data.type === "stage_complete") {{
                    const stageKey = data.stage;
                    completedStages.add(stageKey);
                    completedCount = completedStages.size;
                    
                    if (stageCounter) stageCounter.textContent = completedCount;

                    addLogEntry(`[VERIFIED] ${{stageKey}} resolved successfully`, "complete");

                    const vessel = document.getElementById("icon-vessel-" + stageKey);
                    const icon = document.getElementById("icon-" + stageKey);
                    const body = document.getElementById("body-" + stageKey);
                    const badge = document.getElementById("badge-" + stageKey);

                    if (vessel && icon && body && badge) {{
                        vessel.style.borderColor = "var(--teal)";
                        vessel.style.background = "var(--teal-soft)";
                        vessel.style.color = "var(--teal)";
                        vessel.style.boxShadow = "none";
                        icon.innerHTML = checkmarkSvg;
                        body.style.borderColor = "var(--teal-border)";
                        body.style.background = "var(--panel)";
                        body.style.transform = "translateX(0)";
                        badge.className = "badge badge-completed";
                        badge.style.background = "var(--teal-soft)";
                        badge.style.color = "var(--teal)";
                        badge.style.borderColor = "var(--teal-border)";
                        badge.textContent = "VERIFIED";
                    }}
                }} else if (data.type === "completed") {{
                    if (progressBar) progressBar.style.width = "100%";
                    if (pctLabel) pctLabel.textContent = "100%";
                    if (stageCounter) stageCounter.textContent = "11";
                    if (statusHeader) statusHeader.innerHTML = '<span class="badge badge-completed" style="background: var(--teal-soft); color: var(--teal); border-color: var(--teal-border);">INQUEST COMPLETE</span>';
                    if (statusDesc) statusDesc.textContent = "All 11 strata layers synthesized. Finalizing dossier...";
                    
                    addLogEntry(`Inquest synthesis completed successfully. Redirecting to dossier...`, "complete");
                    eventSource.close();
                    
                    setTimeout(() => {{
                        window.location.href = `/report/${{jobId}}`;
                    }}, 1200);
                }} else if (data.type === "failed") {{
                    if (statusHeader) statusHeader.innerHTML = '<span class="badge badge-failed">INQUEST FAILED</span>';
                    if (statusDesc) statusDesc.textContent = data.message || "An error occurred during analysis.";
                    addLogEntry(`[ERROR] ${{data.message || 'Pipeline encountered fatal execution failure'}}`, "error");
                    eventSource.close();
                }}
            }} catch (err) {{
                console.error("SSE parse error", err);
            }}
        }};

        eventSource.onerror = function() {{
            addLogEntry("SSE stream disconnected or complete. Polling status...", "info");
        }};
    </script>
    """

    content = f"""
    <div style="margin-bottom: 1.5rem;">
        <a href="/dashboard" style="display: inline-flex; align-items: center; gap: 0.4rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.75rem;">
            &larr; BACK TO DASHBOARD LEDGER
        </a>
    </div>

    <!-- Top Dossier Analytical Header Card -->
    <div class="stratum-card" style="margin-bottom: 2rem; position: relative; overflow: hidden;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1rem; border-bottom: 1px solid var(--hairline-soft); padding-bottom: 0.75rem;">
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); font-weight: 600;">// FORENSIC STRATA SYNTHESIS</span>
                <span style="color: var(--hairline);">/</span>
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary);">REAL-TIME INQUEST PIPELINE</span>
            </div>
            <div class="tag">
                <span class="chip-dot brass"></span>
                <span>ACTIVE INQUEST RUNNER</span>
            </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 1.25rem; margin-bottom: 1.5rem;">
            <div>
                <h1 style="font-size: 2rem; font-weight: 500; letter-spacing: -0.02em; margin-bottom: 0.35rem;">
                    Inquest Dossier: <span style="font-style: italic; color: var(--brass);">Job #{job_id}</span>
                </h1>
                <div style="display: flex; align-items: center; gap: 0.75rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-tertiary); flex-wrap: wrap;">
                    <span>TARGET: <strong style="color: var(--text-secondary);">{repo_url}</strong></span>
                    <span>&bull;</span>
                    <span>ENGINE: <strong>11-Layer Reverse Intelligence</strong></span>
                </div>
            </div>
            <div id="overall-status">
                <span class="badge" style="background: var(--brass-soft); color: var(--brass); border-color: var(--brass-border);">IN PROGRESS</span>
            </div>
        </div>

        <!-- Continuous Eased Meter & Current State Summary -->
        <div style="background: var(--panel-raised); padding: 1.25rem; border-radius: 4px; border: 1px solid var(--hairline);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem; flex-wrap: wrap; gap: 0.5rem;">
                <span id="current-stage-title" style="font-weight: 500; font-size: 0.9375rem; color: var(--text-primary); font-family: 'Newsreader', Georgia, serif;">
                    Initializing 11-Layer Inquest Pipeline...
                </span>
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--brass); font-weight: 600;">
                    <span id="completed-stage-count">0</span> OF 11 STAGES RESOLVED (<span id="percentage-label">5%</span>)
                </span>
            </div>
            <div class="meter" style="height: 6px; margin-bottom: 0.65rem; background: var(--panel-overlay); border-radius: 3px; overflow: hidden;">
                <div class="meter-fill high" id="progress-fill" style="width: 5%; height: 100%; background: linear-gradient(90deg, var(--brass), var(--teal)); border-radius: 3px; transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);"></div>
            </div>
            <div style="display: flex; justify-content: space-between; font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary);">
                <span>S00: AUTH GATE</span>
                <span>S03: AST PARSE</span>
                <span>S06: ARCH DOMAINS</span>
                <span>S08: GRAPH/QUIZ</span>
                <span>S10: TELEMETRY</span>
            </div>
        </div>
    </div>

    <!-- Main Grid: Timeline Centerpiece with Collapsible Live Diagnostics Drawer -->
    <div style="display: grid; grid-template-columns: 1fr; gap: 2rem; align-items: start;">
        
        <!-- 11-Layer Narrative Timeline Centerpiece -->
        <div class="stratum-card">
            <div class="card-header" style="margin-bottom: 1.5rem;">
                <div>
                    <h2 style="font-size: 1.35rem; font-weight: 500; margin-bottom: 0.2rem;">Architectural Inquest Stages</h2>
                    <p style="font-size: 0.8125rem; color: var(--text-tertiary); margin: 0;">Step-by-step forensic strata extraction from raw Git commit trees to synthesized dossier.</p>
                </div>
                <div class="tag">
                    <span class="chip-dot brass"></span>
                    <span>11 STRATA SEQUENCE</span>
                </div>
            </div>

            <div class="timeline-spine" style="position: relative;">
                {stages_html}
            </div>
        </div>

        <!-- Collapsible Diagnostics & Live Telemetry Drawer -->
        <div class="stratum-card" style="padding: 1.25rem 1.5rem;">
            <details id="sse-drawer" open style="cursor: pointer;">
                <summary style="display: flex; justify-content: space-between; align-items: center; list-style: none; user-select: none;">
                    <div style="display: flex; align-items: center; gap: 0.65rem;">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--brass)" stroke-width="2">
                            <polyline points="4 17 10 11 4 5"></polyline>
                            <line x1="12" y1="19" x2="20" y2="19"></line>
                        </svg>
                        <h3 style="font-size: 1.05rem; font-weight: 600; margin: 0; color: var(--text-primary);">Live Event Stream Log</h3>
                    </div>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span class="chip-dot teal"></span>
                        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--teal); font-weight: 600;">STREAM ACTIVE</span>
                    </div>
                </summary>

                <div style="margin-top: 1.25rem; cursor: default;">
                    <div id="sse-terminal-log" style="background: var(--ink); border: 1px solid var(--hairline); border-radius: 4px; padding: 1rem; height: 180px; overflow-y: auto; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; line-height: 1.5; margin-bottom: 1rem;">
                        <!-- Real-time events appended here -->
                    </div>

                    <div style="display: flex; justify-content: space-between; align-items: center; font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); border-top: 1px solid var(--hairline-soft); padding-top: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                        <span>CHANNEL: <strong>/api/analyses/{job_id}/events</strong></span>
                        <span>DOCKET: <strong>JOB-{job_id}</strong></span>
                        <span>TENANT SECURITY: <strong style="color: var(--teal);">IDOR VERIFIED</strong></span>
                    </div>
                </div>
            </details>
        </div>

    </div>
    """
    return page_shell(
        f"Inquest Progress: Job #{job_id}",
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
    cyclic_m = re.search(r"\*\*Cyclic Core Components\*\*:\s*`?(\d+)`?", raw_markdown)
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
    calib_section = re.search(r"## 2\. Sequence Reasoning & Confidence Calibration\s*\n([\s\S]*?)(?=\n## 3\.|\Z)", raw_markdown)
    if calib_section:
        result["confidence_calibration"] = calib_section.group(1).strip()

    # Milestones Extraction
    milestones_section = re.search(r"## 3\. Step-by-Step Architectural Milestones\s*\n([\s\S]*)$", raw_markdown)
    if milestones_section:
        m_text = milestones_section.group(1)
        raw_milestones = re.split(r"\n(?=###\s+Milestone\s+\d+:)", m_text)
        for raw_m in raw_milestones:
            raw_m = raw_m.strip()
            if not raw_m.startswith("### Milestone"):
                continue
            
            h_match = re.match(r"###\s+Milestone\s+(\d+):\s*(.+)", raw_m)
            if not h_match:
                continue
            
            m_tier = int(h_match.group(1))
            m_title_raw = h_match.group(2).strip()
            m_title = re.sub(r"\s*\(Tier\s+\d+\)$", "", m_title_raw)

            badge_m = re.search(r"\*\*\[([^\]]+)\]\*\*\s*--\s*\*(.+?)\*", raw_m)
            confidence_badge = badge_m.group(1).strip() if badge_m else ""
            architectural_role = badge_m.group(2).strip() if badge_m else ""

            is_cyclic = "*[CYCLIC CORE]*" in raw_m
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
            exported_symbols = [s.strip() for s in symbols_m.group(1).split(",") if s.strip()] if symbols_m else []

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
        tier_tag = '<span class="badge badge-teal" style="font-size: 0.65rem; letter-spacing: 0.04em;">TIER 1 // REAL REPO TEST SUITE</span>'
    elif grading_method == "expected_output":
        tier_tag = '<span class="badge badge-amber" style="font-size: 0.65rem; letter-spacing: 0.04em;">TIER 2 // EXPECTED OUTPUT</span>'
    else:
        tier_tag = '<span class="badge badge-brass" style="font-size: 0.65rem; letter-spacing: 0.04em;">TIER 3 // STATIC AST DIFF</span>'

    if is_verified:
        banner = f"""
        <div class="diff-banner success" style="background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--teal); padding: 0.65rem 0.85rem; border-radius: 4px; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; margin-bottom: 0.65rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; flex-wrap: wrap;">
            <div style="display: flex; align-items: center; gap: 0.4rem;">
                <span>✓</span> VERIFIED: Milestone requirements fulfilled
            </div>
            {tier_tag}
        </div>
        """
    else:
        banner = f"""
        <div class="diff-banner failure" style="background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.65rem 0.85rem; border-radius: 4px; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; margin-bottom: 0.65rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; flex-wrap: wrap;">
            <div style="display: flex; align-items: center; gap: 0.4rem;">
                <span>⚠</span> VERIFICATION GAPS: Requirements not yet satisfied
            </div>
            {tier_tag}
        </div>
        """

    err_html = f"""<div style="color: var(--crimson); font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; margin-bottom: 0.5rem; background: rgba(244,63,94,0.08); padding: 0.5rem; border-radius: 3px;">{sanitize_text(err_msg)}</div>""" if err_msg else ""

    present_pills = ""
    for s in present_syms:
        mat = s.get("matched", {}) or s.get("expected", {})
        name = sanitize_text(mat.get("name", ""))
        kind = sanitize_text(mat.get("kind", "symbol"))
        raw_args = mat.get("args", [])
        safe_args = [sanitize_text(arg) for arg in raw_args] if isinstance(raw_args, list) else []
        args_str = f"({', '.join(safe_args)})" if safe_args else ""
        present_pills += f"""<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--teal); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;">✓ {name}{args_str} <span style="opacity: 0.75; font-size: 0.6875rem;">({kind})</span></span> """

    missing_pills = ""
    for s in missing_syms:
        name = sanitize_text(s.get("name", "") if isinstance(s, dict) else str(s))
        kind = sanitize_text(s.get("kind", "required") if isinstance(s, dict) else "required")
        missing_pills += f"""<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;">✗ {name} <span style="opacity: 0.75; font-size: 0.6875rem;">({kind})</span></span> """

    extra_pills = ""
    for s in extra_syms:
        name = sanitize_text(s.get("name", "") if isinstance(s, dict) else str(s))
        kind = sanitize_text(s.get("kind", "extra") if isinstance(s, dict) else "extra")
        extra_pills += f"""<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: var(--panel-raised); border: 1px solid var(--hairline); color: var(--text-secondary); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;">+ {name} <span style="opacity: 0.75; font-size: 0.6875rem;">({kind})</span></span> """

    sections_html = ""
    if present_pills:
        sections_html += f"""
        <div>
            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--teal); font-weight: 600; margin-bottom: 0.25rem;">PRESENT &amp; MATCHED SYMBOLS ({len(present_syms)}):</div>
            <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">{present_pills}</div>
        </div>
        """
    if missing_pills:
        sections_html += f"""
        <div>
            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--crimson); font-weight: 600; margin-bottom: 0.25rem;">MISSING EXPECTED SYMBOLS ({len(missing_syms)}):</div>
            <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">{missing_pills}</div>
        </div>
        """
    if extra_pills:
        sections_html += f"""
        <div>
            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); font-weight: 600; margin-bottom: 0.25rem;">EXTRA / AUXILIARY SYMBOLS ({len(extra_syms)}):</div>
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
    if not attempt or attempt.last_run_at is None:
        return ""

    exit_code = attempt.last_run_exit_code if attempt.last_run_exit_code is not None else 0
    is_success = (exit_code == 0)
    stdout = attempt.last_run_stdout or ""
    stderr = attempt.last_run_stderr or ""

    exit_badge_cls = "badge-teal" if is_success else "badge-crimson"
    exit_badge_text = f"EXIT {exit_code}"

    content = ""
    if stdout:
        content += f'<div style="color: #e2e8f0; white-space: pre-wrap; word-break: break-all; margin-bottom: 0.5rem;">{html.escape(stdout)}</div>'
    if stderr:
        content += f'<div style="color: var(--crimson); white-space: pre-wrap; word-break: break-all; margin-top: 0.25rem;">{html.escape(stderr)}</div>'
    if not stdout and not stderr:
        content = '<div style="color: var(--text-tertiary); font-style: italic;">(Process completed with no output)</div>'

    last_run_str = attempt.last_run_at.strftime("%H:%M:%S") if hasattr(attempt.last_run_at, "strftime") else ""
    time_badge = f'<span class="tag" style="font-size: 0.65rem;">{last_run_str}</span>' if last_run_str else ""
    dot_color = "teal" if is_success else "crimson"

    return f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; border-bottom: 1px solid var(--hairline); padding-bottom: 0.4rem;">
        <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span class="chip-dot {dot_color}"></span>
            <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; font-weight: 600; color: var(--text-primary); text-transform: uppercase;">Execution Console</span>
            <span class="badge {exit_badge_cls}" style="font-size: 0.65rem;">{exit_badge_text}</span>
            {time_badge}
        </div>
        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; color: var(--text-tertiary);">UNMETERED PLAYGROUND</span>
    </div>
    <pre style="background: #0d0e12; padding: 0.75rem; border-radius: 3px; border: 1px solid var(--hairline-soft); font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; line-height: 1.45; overflow-x: auto; margin: 0;"><code>{content}</code></pre>
    """


def report_view(
    job: Any,
    raw_markdown: str,
    graph_data: Optional[Dict[str, Any]],
    quiz_data: Optional[Dict[str, Any]],
    current_user: UserModel,
    billing_status: Optional[Dict[str, Any]] = None,
    attempts_by_tier: Optional[Dict[int, Any]] = None,
) -> str:
    """
    Render the Archival Dossier Report View.
    Structured into modular visual sections with interactive SVG dependency graph diagram,
    milestone sequence spine, in-app code editor workspace, and live structural verification.
    """
    job_id = sanitize_text(str(job.id))
    repo_url = sanitize_text(job.repo_url)
    repo_name = sanitize_text(job.repo_name or (job.repo_url.rstrip("/").split("/")[-1] if "/" in job.repo_url else job.repo_url))
    created_at = sanitize_text(job.created_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(job.created_at, "strftime") else str(job.created_at))
    duration = f"{job.execution_time_seconds:.1f}s" if job.execution_time_seconds else "Completed"
    run_id = sanitize_text(job.run_id or f"run_{job_id}")

    parsed_md = _parse_report_markdown(raw_markdown)
    overview_data = parsed_md.get("overview", {})
    domain_dist = parsed_md.get("domain_distribution", [])
    milestones_data = parsed_md.get("milestones", [])
    safe_markdown_html = render_safe_markdown(raw_markdown)

    # Graph stats
    nodes = graph_data.get("nodes", []) if graph_data else []
    edges = graph_data.get("edges", []) if graph_data else []
    node_count = len(nodes)
    edge_count = len(edges)

    # -------------------------------------------------------------
    # 1. Executive Architecture Stratum (KPI Bento Grid & Callouts)
    # -------------------------------------------------------------
    primary_lang = sanitize_text(overview_data.get("primary_language", "Python")).upper()
    total_files = overview_data.get("total_files", node_count or len(nodes))
    entry_points = overview_data.get("entry_points", [])
    cyclic_count = overview_data.get("cyclic_files", 0)
    isolated_count = overview_data.get("isolated_files", 0)
    total_tiers = len(set(n.get("tier", 0) for n in nodes)) if nodes else (len(milestones_data) or 1)

    entry_chips_html = ""
    for ep in entry_points:
        safe_ep = sanitize_text(ep)
        entry_chips_html += f"""
        <div class="entry-chip">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--brass);">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            <span class="mono" style="font-size: 0.75rem; color: var(--text-primary);">{safe_ep}</span>
        </div>
        """
    if not entry_chips_html:
        entry_chips_html = '<span style="font-size: 0.8125rem; color: var(--text-tertiary);">No distinct external entry points detected</span>'

    # Domain Distribution Bars
    domain_bars_html = ""
    for d in domain_dist:
        d_name = sanitize_text(d["domain"]).upper()
        d_count = d["count"]
        d_pct = sanitize_text(d["percentage"])
        pct_val = float(d["percentage"].replace("%", "")) if "%" in d["percentage"] else 0
        domain_bars_html += f"""
        <div style="margin-bottom: 0.85rem;">
            <div style="display: flex; justify-content: space-between; font-size: 0.75rem; font-family: 'IBM Plex Mono', monospace; margin-bottom: 0.25rem;">
                <span style="color: var(--text-primary); font-weight: 600;">{d_name}</span>
                <span style="color: var(--text-secondary);">{d_count} files ({d_pct})</span>
            </div>
            <div style="height: 6px; background: var(--panel-raised); border-radius: 3px; overflow: hidden; border: 1px solid var(--hairline-soft);">
                <div style="width: {pct_val}%; height: 100%; background: var(--brass); border-radius: 3px;"></div>
            </div>
        </div>
        """

    # Confidence Calibration Callout
    calib_raw = parsed_md.get("confidence_calibration", "")
    calib_html = ""
    if calib_raw:
        calib_html = f"""
        <div style="background: var(--panel-raised); border: 1px solid var(--hairline); border-left: 3px solid var(--teal); border-radius: 4px; padding: 1rem 1.25rem; margin-top: 1.25rem;">
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.35rem;">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--teal);">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                </svg>
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; color: var(--teal); text-transform: uppercase; letter-spacing: 0.05em;">
                    Sequence Reasoning &amp; Confidence Calibration
                </span>
            </div>
            <div style="font-size: 0.8125rem; color: var(--text-secondary); line-height: 1.55;">
                {render_safe_markdown(calib_raw)}
            </div>
        </div>
        """

    overview_section_html = f"""
    <div class="stratum-card" id="section-overview" style="margin-bottom: 2rem;">
        <div class="card-header">
            <div>
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); text-transform: uppercase; letter-spacing: 0.05em;">
                    Section 01 // Architectural Synthesis Stratum
                </div>
                <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Executive Codebase Architecture &amp; Topography</h2>
            </div>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span class="chip"><span class="chip-dot teal"></span> Verified Invariants</span>
                <span class="chip">{total_files} Files</span>
            </div>
        </div>

        <!-- 6-Card KPI Bento Grid -->
        <div class="kpi-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.75rem; margin: 1.25rem 0;">
            <div class="kpi-card">
                <div class="kpi-label">PRIMARY LANGUAGE</div>
                <div class="kpi-value" style="color: var(--brass);">{primary_lang}</div>
                <div class="kpi-sub">AST Syntax Engine</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">TOTAL ANALYZED FILES</div>
                <div class="kpi-value" style="color: var(--text-primary);">{total_files}</div>
                <div class="kpi-sub">Decomposed Modules</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">TOPOLOGICAL DEPTH</div>
                <div class="kpi-value" style="color: var(--teal);">{total_tiers} Tiers</div>
                <div class="kpi-sub">Leaf to Root Sequence</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">ENTRY POINTS</div>
                <div class="kpi-value" style="color: var(--amber);">{len(entry_points)}</div>
                <div class="kpi-sub">Application Targets</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">GRAPH DEPENDENCIES</div>
                <div class="kpi-value" style="color: var(--text-primary);">{edge_count}</div>
                <div class="kpi-sub">Import / Call Edges</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">SUBSYSTEM DOMAINS</div>
                <div class="kpi-value" style="color: var(--brass);">{len(domain_dist)}</div>
                <div class="kpi-sub">Categorized Strata</div>
            </div>
        </div>

        <!-- Invariant Pull-Quote Memo Callout -->
        <div class="dossier-pullquote" style="margin: 1.25rem 0; padding: 1.15rem 1.35rem; background: var(--panel); border: 1px solid var(--hairline); border-left: 3px solid var(--brass); border-radius: 4px;">
            <div style="font-family: 'Newsreader', Georgia, serif; font-style: italic; font-size: 1.05rem; color: var(--text-primary); line-height: 1.5; margin-bottom: 0.4rem;">
                &ldquo;Topologically ordered leaf-to-root architectural synthesis computed from static CST/AST parsing and cross-module import analysis.&rdquo;
            </div>
            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary);">
                RECONSTRUCTED INVARIANT LEDGER &bull; ISOLATED FILES: {isolated_count} &bull; CYCLIC CLUSTERS: {cyclic_count}
            </div>
        </div>

        <!-- Two Column Breakdown: Entry Points Tray & Domain Distribution -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; margin-top: 1.25rem;">
            <!-- Entry Points Tray -->
            <div style="background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px; padding: 1.15rem;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">
                        Execution Entry Targets ({len(entry_points)})
                    </span>
                    <span class="chip" style="font-size: 0.625rem;">ROOT STRATA</span>
                </div>
                <div style="display: flex; flex-direction: column; gap: 0.4rem;">
                    {entry_chips_html}
                </div>
            </div>

            <!-- Domain Distribution -->
            <div style="background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px; padding: 1.15rem;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">
                        Domain Composition
                    </span>
                    <span class="chip" style="font-size: 0.625rem;">{len(domain_dist)} DOMAINS</span>
                </div>
                {domain_bars_html}
            </div>
        </div>

        {calib_html}
    </div>
    """

    # -------------------------------------------------------------
    # 2. Visual Topological Dependency Graph (SVG Interactive DAG)
    # -------------------------------------------------------------
    graph_section_html = ""
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
        node_h = 68
        node_v_step = 88
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
                <rect x="0" y="16" width="{col_width}" height="28" rx="4" fill="var(--panel-raised)" stroke="var(--hairline)" />
                <text x="12" y="34" fill="var(--brass)" font-family="'IBM Plex Mono', monospace" font-size="11" font-weight="600">TIER {t_val}</text>
                <text x="{col_width - 12}" y="34" fill="var(--text-tertiary)" font-family="'IBM Plex Mono', monospace" font-size="10" text-anchor="end">{len(tier_nodes)} nodes</text>
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

                node_label = sanitize_text(node.get("label", node.get("id", "")))
                node_path = sanitize_text(node.get("path", node.get("id", "")))
                node_domain = sanitize_text(node.get("domain", node.get("type", "core"))).upper()
                confidence = sanitize_text(str(node.get("confidence", "high"))).lower()
                conf_color = "var(--teal)" if confidence == "high" else ("var(--amber)" if confidence == "medium" else "var(--brass)")
                exports = node.get("exports", [])
                exports_count = len(exports) if isinstance(exports, list) else 0

                safe_node_id = sanitize_text(node_id).replace("/", "_").replace(".", "_")

                svg_nodes_html += f"""
                <g class="dag-node" id="dag-node-{safe_node_id}" data-node-id="{sanitize_text(node_id)}" data-tier="{t_val}" data-domain="{node_domain}" onclick="selectDagNode('{sanitize_text(node_id)}')" onmouseenter="hoverDagNode('{sanitize_text(node_id)}')" onmouseleave="unhoverDagNode()" transform="translate({col_x}, {node_y})" style="cursor: pointer; transition: all 150ms ease;">
                    <rect width="{col_width}" height="{node_h}" rx="6" fill="var(--panel)" stroke="var(--hairline)" class="dag-node-box" />
                    <!-- Confidence Indicator Dot -->
                    <circle cx="16" cy="20" r="4" fill="{conf_color}" />
                    <!-- Node Label -->
                    <text x="28" y="24" fill="var(--text-primary)" font-family="'IBM Plex Mono', monospace" font-size="12" font-weight="600">{node_label}</text>
                    <!-- Domain Badge -->
                    <rect x="{col_width - 62}" y="10" width="50" height="18" rx="3" fill="var(--panel-raised)" stroke="var(--hairline)" />
                    <text x="{col_width - 37}" y="22" fill="var(--brass)" font-family="'IBM Plex Mono', monospace" font-size="9" font-weight="600" text-anchor="middle">{node_domain[:7]}</text>
                    <!-- File Path Subtitle -->
                    <text x="16" y="44" fill="var(--text-tertiary)" font-family="'IBM Plex Mono', monospace" font-size="10">{node_path[-28:]}</text>
                    <!-- Exports / Invariant count -->
                    <text x="16" y="58" fill="var(--text-secondary)" font-family="'IBM Plex Mono', monospace" font-size="9.5">{exports_count} exports &bull; Tier {t_val}</text>
                </g>
                """

        # Layout Edges with Smooth Bezier Curves
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
                <path class="dag-edge" data-source="{sanitize_text(src_id)}" data-target="{sanitize_text(tgt_id)}" d="{d}" fill="none" stroke="var(--hairline-strong)" stroke-width="1.5" marker-end="url(#dag-arrow)" opacity="0.45" style="transition: all 150ms ease;" />
                """

        # Tabular nodes catalog for secondary accessibility view
        catalog_rows_html = ""
        for n in nodes:
            n_label = sanitize_text(n.get("label", n.get("id", "")))
            n_path = sanitize_text(n.get("path", n.get("id", "")))
            n_tier = sanitize_text(str(n.get("tier", "—")))
            n_domain = sanitize_text(n.get("domain", n.get("type", "module"))).upper()
            n_exports = n.get("exports", [])
            n_exports_str = ", ".join(n_exports[:6]) if isinstance(n_exports, list) and n_exports else (str(n_exports) if n_exports else "None")
            n_conf = sanitize_text(str(n.get("confidence", "high"))).lower()
            dot_cls = "teal" if n_conf == "high" else ("amber" if n_conf == "medium" else "crimson")

            catalog_rows_html += f"""
            <tr style="cursor: pointer;" onclick="selectDagNode('{sanitize_text(n.get('id', ''))}')">
                <td>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <span class="chip-dot {dot_cls}"></span>
                        <span class="mono" style="font-weight: 600; color: var(--text-primary);">{n_label}</span>
                    </div>
                    <div class="mono" style="font-size: 0.6875rem; color: var(--text-tertiary);">{n_path}</div>
                </td>
                <td><span class="tag">Tier {n_tier}</span></td>
                <td><span class="chip">{n_domain}</span></td>
                <td class="mono" style="font-size: 0.75rem; color: var(--text-secondary);">{sanitize_text(n_exports_str)}</td>
            </tr>
            """

        graph_section_html = f"""
        <div class="stratum-card" id="section-graph" style="margin-bottom: 2rem;">
            <div class="card-header">
                <div>
                    <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); text-transform: uppercase; letter-spacing: 0.05em;">
                        Section 02 // Topological Structure
                    </div>
                    <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Architecture &amp; Dependency Graph</h2>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                    <span class="chip"><span class="chip-dot teal"></span> {node_count} Nodes</span>
                    <span class="chip">{edge_count} Dependencies</span>
                </div>
            </div>

            <p style="color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 1rem; line-height: 1.5;">
                Computed from static AST syntax tree parsing and cross-module import resolution. Nodes represent decomposed compilation modules grouped horizontally by topological tier (leaf-to-root).
            </p>

            <!-- Graph Interactive Toolbar -->
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 0.85rem; padding: 0.65rem 0.85rem; background: var(--panel-raised); border: 1px solid var(--hairline); border-radius: 4px;">
                <div style="display: flex; align-items: center; gap: 0.5rem; flex: 1; min-width: 200px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--text-tertiary);">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    <input type="text" id="dag-search-input" placeholder="Search node or file..." oninput="filterDagNodes(this.value)" style="background: transparent; border: none; color: var(--text-primary); font-family: 'IBM Plex Sans', sans-serif; font-size: 0.8125rem; outline: none; width: 100%;" />
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <button type="button" class="btn btn-sm btn-secondary" onclick="resetDagZoom()" title="Reset Graph View">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path><path d="M3 3v5h5"></path></svg>
                        Reset
                    </button>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="toggleGraphViewMode()" id="toggle-view-btn">
                        Table Catalog
                    </button>
                </div>
            </div>

            <!-- Visual SVG DAG Canvas Container -->
            <div id="dag-visual-container" style="background: var(--ink); border: 1px solid var(--hairline); border-radius: 4px; overflow: auto; position: relative; max-height: 520px;">
                <svg id="dag-svg" width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}" style="display: block; min-width: {svg_width}px;">
                    <defs>
                        <marker id="dag-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="var(--brass)" opacity="0.8" />
                        </marker>
                        <marker id="dag-arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                            <path d="M 0 1 L 9 5 L 0 9 z" fill="var(--teal)" />
                        </marker>
                    </defs>
                    <!-- Tier Columns -->
                    {svg_columns_html}
                    <!-- Connecting Edges -->
                    <g id="dag-edges-layer">
                        {svg_edges_html}
                    </g>
                    <!-- Nodes -->
                    <g id="dag-nodes-layer">
                        {svg_nodes_html}
                    </g>
                </svg>
            </div>

            <!-- Tabular Node Catalog (Collapsible / Toggleable) -->
            <div id="dag-table-container" style="display: none; background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px; overflow-x: auto; max-height: 480px;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr>
                            <th>Module / File</th>
                            <th>Tier</th>
                            <th>Domain</th>
                            <th>Exported Invariants</th>
                        </tr>
                    </thead>
                    <tbody>
                        {catalog_rows_html}
                    </tbody>
                </table>
            </div>

            <!-- Interactive Node Inspector Drawer -->
            <div id="dag-node-inspector" style="display: none; margin-top: 1rem; padding: 1rem 1.25rem; background: var(--panel-raised); border: 1px solid var(--hairline); border-radius: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
                    <div>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <span id="inspect-dot" class="chip-dot teal"></span>
                            <span id="inspect-label" class="mono" style="font-weight: 600; font-size: 0.95rem; color: var(--text-primary);">Node Name</span>
                            <span id="inspect-tier" class="tag">Tier 0</span>
                            <span id="inspect-domain" class="chip">CORE</span>
                        </div>
                        <div id="inspect-path" class="mono" style="font-size: 0.75rem; color: var(--text-tertiary); margin-top: 0.2rem;">src/path</div>
                    </div>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="closeDagInspector()">Close</button>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-top: 0.75rem;">
                    <div>
                        <div style="font-size: 0.6875rem; font-family: 'IBM Plex Mono', monospace; color: var(--text-tertiary); margin-bottom: 0.25rem;">EXPORTED SYMBOLS</div>
                        <div id="inspect-exports" class="mono" style="font-size: 0.75rem; color: var(--text-secondary); background: var(--panel); padding: 0.5rem; border-radius: 3px; border: 1px solid var(--hairline-soft);">None</div>
                    </div>
                    <div>
                        <div style="font-size: 0.6875rem; font-family: 'IBM Plex Mono', monospace; color: var(--text-tertiary); margin-bottom: 0.25rem;">CONNECTED DEPENDENCIES</div>
                        <div id="inspect-deps" class="mono" style="font-size: 0.75rem; color: var(--text-secondary); background: var(--panel); padding: 0.5rem; border-radius: 3px; border: 1px solid var(--hairline-soft);">None</div>
                    </div>
                </div>
            </div>
        </div>
        """

    # -------------------------------------------------------------
    # 3. Step-by-Step Architectural Milestones Timeline Spine & In-App Code Editor
    # -------------------------------------------------------------
    milestones_spine_html = ""
    if milestones_data:
        items_html = ""
        for m in milestones_data:
            m_tier = m.get("tier", 0)
            m_num_str = f"{m_tier:02d}"
            m_title = sanitize_text(m.get("title", ""))
            m_role = sanitize_text(m.get("architectural_role", ""))
            m_summary = sanitize_text(m.get("overview", ""))
            m_comp = sanitize_text(m.get("domain_composition", ""))
            m_files = m.get("included_files", [])
            m_exports = m.get("exported_symbols", [])
            m_citations = m.get("citations", [])
            m_pedagogical = m.get("pedagogical_notes", [])
            m_gotchas = m.get("gotchas", [])
            m_conf_badge = sanitize_text(m.get("confidence_badge", "HIGH CONFIDENCE"))

            # Confidence Badge color
            conf_badge_cls = "badge-teal" if "HIGH" in m_conf_badge else ("badge-amber" if "MEDIUM" in m_conf_badge else "badge-brass")

            # Milestone Attempt State Persistence
            attempt = attempts_by_tier.get(m_tier) if attempts_by_tier else None
            attempt_status = attempt.status if attempt else "not_started"
            submitted_code = attempt.submitted_code if attempt and attempt.submitted_code else ""
            escaped_code = html.escape(submitted_code)

            # Vessel state and Status Badge styling
            if attempt_status == "structurally_verified":
                vessel_cls = "milestone-vessel verified"
                vessel_icon = "✓"
                status_chip = f'<span id="status-badge-{m_tier}" class="badge badge-teal" style="font-weight: 700;"><span class="chip-dot teal"></span> STRUCTURALLY VERIFIED</span>'
            elif attempt_status == "attempting":
                vessel_cls = "milestone-vessel attempting"
                vessel_icon = m_num_str
                status_chip = f'<span id="status-badge-{m_tier}" class="badge badge-amber" style="font-weight: 700;"><span class="chip-dot amber"></span> ATTEMPTING</span>'
            else:
                vessel_cls = "milestone-vessel not-started"
                vessel_icon = m_num_str
                status_chip = f'<span id="status-badge-{m_tier}" class="badge badge-brass" style="font-weight: 600;"><span class="chip-dot brass"></span> NOT STARTED</span>'

            # Progressive Hint State
            hint_level = attempt.hint_level_revealed if attempt else 0
            impl_revealed = attempt.implementation_revealed if attempt else False
            is_active_attempt = (attempt is not None and attempt.status in ("attempting", "structurally_verified"))

            # Pre-render Hint 1 if revealed
            h1_text = ""
            h1_style = "display: none;"
            if hint_level >= 1:
                try:
                    h1_text = HintEngine.get_hint_1(graph_data or {}, m_tier)
                    h1_style = "display: block;"
                except Exception:
                    h1_text = "Conceptual hint available."
                    h1_style = "display: block;"

            # Pre-render Hint 2 if revealed
            h2_text = ""
            h2_style = "display: none;"
            if hint_level >= 2:
                try:
                    exp_syms = StructuralVerifier.extract_expected_symbols_from_graph(graph_data or {}, m_tier)
                    ver_res = StructuralVerifier().verify(attempt.submitted_code if attempt else "", exp_syms)
                    h2_text = HintEngine.get_hint_2(graph_data or {}, m_tier, missing_symbols=ver_res.get("missing", []))
                    h2_style = "display: block;"
                except Exception:
                    h2_text = "Specific missing contracts and files available."
                    h2_style = "display: block;"

            # Pre-render Reference Implementation if revealed
            ref_code_rendered = ""
            ref_style = "display: none;"
            if impl_revealed:
                try:
                    ref_data = HintEngine.get_reference_implementation(graph_data or {}, m_tier)
                    ref_code_rendered = html.escape(ref_data.get("reference_code", ""))
                    ref_style = "display: block;"
                except Exception:
                    ref_code_rendered = "# Reference implementation available."
                    ref_style = "display: block;"

            # Hint button text & state
            if hint_level == 0:
                hint_btn_text = "Request Architectural Hint"
                hint_btn_disabled = ""
            elif hint_level == 1:
                hint_btn_text = "Request Next Hint (Hint 2)"
                hint_btn_disabled = ""
            else:
                hint_btn_text = "Hints Unlocked (2/2)"
                hint_btn_disabled = "disabled"

            hint_btn_display = "display: inline-flex;" if is_active_attempt else "display: none;"
            reveal_btn_display = "display: inline-flex;" if is_active_attempt else "display: none;"
            locked_notice_display = "display: none;" if is_active_attempt else "display: inline-flex;"
            reveal_btn_text = "Reference Revealed" if impl_revealed else "Reveal Implementation"

            # Pre-rendered Diff output if attempt has previous submitted code
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
                    diff_rendered_html = f'<div style="color: var(--crimson); font-family: \'IBM Plex Mono\', monospace; font-size: 0.75rem;">Verification load error: {html.escape(str(e))}</div>'

            # Pre-rendered Console output if attempt has previous run results
            console_initial_display = "display: block;" if (attempt and attempt.last_run_at is not None) else "display: none;"
            console_rendered_html = _render_server_console_html(attempt)

            # File chips
            files_chips_html = ""
            for f_item in m_files:
                safe_f = sanitize_text(f_item)
                files_chips_html += f"""
                <span class="mono" style="display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.2rem 0.5rem; background: var(--panel-raised); border: 1px solid var(--hairline); border-radius: 3px; font-size: 0.75rem; color: var(--text-primary);">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--brass);">
                        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                        <polyline points="13 2 13 9 20 9"></polyline>
                    </svg>
                    {safe_f}
                </span>
                """

            # Symbols tags
            symbols_html = ""
            if m_exports:
                symbols_rendered = ", ".join(m_exports[:10])
                symbols_html = f"""
                <div style="margin-top: 0.65rem; font-size: 0.75rem; font-family: 'IBM Plex Mono', monospace; color: var(--text-secondary);">
                    <span style="color: var(--text-tertiary); font-weight: 600;">KEY SYMBOLS:</span> {sanitize_text(symbols_rendered)}
                </div>
                """

            # Expected symbols pills in workspace
            expected_pills_html = ""
            if m_exports:
                for exp_sym in m_exports:
                    safe_sym = sanitize_text(exp_sym)
                    expected_pills_html += f"""<span class="expected-sym-chip" style="display: inline-flex; align-items: center; gap: 0.25rem; background: var(--panel-raised); border: 1px solid var(--hairline); padding: 0.15rem 0.45rem; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; color: var(--text-secondary);">&bull; {safe_sym}</span> """
            else:
                expected_pills_html = '<span style="font-size: 0.75rem; color: var(--text-tertiary); font-family: \'IBM Plex Mono\', monospace;">Any milestone module functions/classes</span>'

            # Citations accordion
            citations_html = ""
            if m_citations:
                c_items = "".join(f'<div style="margin-bottom: 0.35rem; color: var(--text-secondary);">&bull; {sanitize_text(c)}</div>' for c in m_citations)
                citations_html = f"""
                <details style="margin-top: 0.65rem;">
                    <summary style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); cursor: pointer; user-select: none;">
                        <span>&gt; Semantic Citations ({len(m_citations)})</span>
                    </summary>
                    <div style="margin-top: 0.4rem; padding: 0.65rem 0.85rem; background: var(--panel-raised); border-left: 2px solid var(--teal); border-radius: 2px; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; line-height: 1.45;">
                        {c_items}
                    </div>
                </details>
                """

            # Pedagogical / Gotchas callouts
            notes_html = ""
            if m_pedagogical or m_gotchas:
                p_items = "".join(f'<div style="margin-bottom: 0.25rem;">&bull; {sanitize_text(p)}</div>' for p in m_pedagogical)
                g_items = "".join(f'<div style="margin-bottom: 0.25rem; color: var(--amber);">&bull; {sanitize_text(g)}</div>' for g in m_gotchas)
                notes_html = f"""
                <div style="margin-top: 0.65rem; padding: 0.65rem 0.85rem; background: var(--panel-raised); border: 1px solid var(--hairline-soft); border-radius: 3px; font-size: 0.75rem; color: var(--text-secondary); line-height: 1.45;">
                    {f'<div style="margin-bottom: 0.35rem;"><span style="font-weight: 600; color: var(--text-primary);">Pedagogical Invariant:</span> {p_items}</div>' if p_items else ''}
                    {f'<div><span style="font-weight: 600; color: var(--amber);">Implementation Gotcha:</span> {g_items}</div>' if g_items else ''}
                </div>
                """

            items_html += f"""
            <div class="milestone-item" id="milestone-stratum-{m_tier}" style="display: flex; gap: 1.25rem; align-items: flex-start; position: relative; margin-bottom: 2rem;">
                <!-- Step Vessel -->
                <div id="milestone-vessel-{m_tier}" class="{vessel_cls}" style="flex-shrink: 0; width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; font-weight: 700; z-index: 2; transition: all 200ms ease;">
                    <span id="milestone-vessel-text-{m_tier}">{vessel_icon}</span>
                </div>
                <!-- Milestone Body Card -->
                <div class="milestone-body" style="flex: 1; background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px; padding: 1.35rem 1.55rem; box-shadow: 0 2px 12px rgba(0,0,0,0.08);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.45rem;">
                        <div>
                            <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); font-weight: 600; letter-spacing: 0.05em;">MILESTONE {m_tier}</span>
                                <span style="color: var(--hairline);">/</span>
                                <h3 style="font-size: 1.2rem; font-weight: 600; color: var(--text-primary); margin: 0; font-family: 'Newsreader', Georgia, serif;">{m_title}</h3>
                            </div>
                            {f'<div style="font-size: 0.8125rem; font-style: italic; color: var(--text-secondary); margin-top: 0.15rem;">{m_role}</div>' if m_role else ''}
                        </div>
                        <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                            {status_chip}
                            <span class="badge {conf_badge_cls}">{m_conf_badge}</span>
                        </div>
                    </div>

                    <p style="color: var(--text-primary); font-size: 0.875rem; line-height: 1.55; margin: 0.5rem 0;">
                        {m_summary}
                    </p>

                    {f'<div style="font-size: 0.75rem; color: var(--text-tertiary); font-family: \'IBM Plex Mono\', monospace; margin-bottom: 0.5rem;"><span style="color: var(--text-secondary); font-weight: 600;">Composition:</span> {m_comp}</div>' if m_comp else ''}

                    <!-- Included Files Tray -->
                    <div style="margin-top: 0.65rem;">
                        <div style="font-size: 0.6875rem; font-family: 'IBM Plex Mono', monospace; color: var(--text-tertiary); margin-bottom: 0.35rem; font-weight: 600; text-transform: uppercase;">
                            Included Files ({len(m_files)})
                        </div>
                        <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">
                            {files_chips_html}
                        </div>
                    </div>

                    {symbols_html}
                    {citations_html}
                    {notes_html}

                    <!-- Prompt 12: In-App Code Editor Component & Prompt 13 Progressive Hint Gate & Prompt 16 Execution -->
                    <div class="milestone-editor-wrapper" id="milestone-editor-card-{m_tier}" style="margin-top: 1.25rem; border-top: 1px solid var(--hairline-soft); padding-top: 1.15rem;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem; flex-wrap: wrap; gap: 0.5rem;">
                            <div style="display: flex; align-items: center; gap: 0.5rem;">
                                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--brass);">
                                    <polyline points="16 18 22 12 16 6"></polyline>
                                    <polyline points="8 6 2 12 8 18"></polyline>
                                </svg>
                                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; color: var(--text-primary); text-transform: uppercase; letter-spacing: 0.05em;">
                                    Milestone {m_tier} Implementation Workspace
                                </span>
                            </div>
                            <div style="display: flex; align-items: center; gap: 0.5rem;">
                                <span class="tag" style="font-size: 0.6875rem;">AST &amp; RUNTIME VERIFIED</span>
                            </div>
                        </div>

                        <!-- Expected Invariant Target Pills -->
                        <div style="margin-bottom: 0.75rem; background: var(--panel-raised); border: 1px solid var(--hairline-soft); border-radius: 4px; padding: 0.6rem 0.85rem;">
                            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); margin-bottom: 0.35rem; font-weight: 600; text-transform: uppercase;">
                                Target Invariants &amp; Expected Symbols:
                            </div>
                            <div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">
                                {expected_pills_html}
                            </div>
                        </div>

                        <!-- CodeMirror Embedded Surface -->
                        <div class="editor-surface-container" style="border: 1px solid var(--hairline); border-radius: 4px; overflow: hidden; background: #282a36;">
                            <textarea id="code-editor-{m_tier}" name="code_editor_{m_tier}" style="display: none;">{escaped_code}</textarea>
                        </div>

                        <!-- Actions & Submission Toolbar (Prompt 16: Run vs Submit) -->
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
                            <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                                <!-- Run Action Button (Unmetered, no grading, real stdout/stderr/exit code) -->
                                <button type="button" id="btn-run-{m_tier}" onclick="runMilestoneCode('{job_id}', {m_tier})" class="btn btn-sm btn-secondary" style="font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.02em; border-color: var(--brass-border); color: var(--brass);">
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                                        <polygon points="5 3 19 12 5 21 5 3"></polygon>
                                    </svg>
                                    Run Code
                                </button>
                                <span id="indicator-spinner-run-{m_tier}" style="display: none; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-secondary); align-items: center; gap: 0.3rem;">
                                    <span class="chip-dot brass pulse"></span> Executing in Sandbox...
                                </span>

                                <!-- Submit Action Button (Structural Check + Runtime Execution + Graded Attempt State) -->
                                <button type="button" id="btn-submit-{m_tier}" onclick="submitMilestoneCode('{job_id}', {m_tier})" class="btn btn-sm btn-primary" style="font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.02em;">
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <polyline points="20 6 9 17 4 12"></polyline>
                                    </svg>
                                    Submit Verification
                                </button>
                                <span id="indicator-spinner-{m_tier}" style="display: none; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-secondary); align-items: center; gap: 0.3rem;">
                                    <span class="chip-dot teal pulse"></span> Verifying &amp; Running...
                                </span>

                                <!-- Hint Action Button (Unlocked after 1st submission) -->
                                <button type="button" id="btn-hint-{m_tier}" data-hint-level="{hint_level}" onclick="openHintConfirmModal('{job_id}', {m_tier})" class="btn btn-sm btn-secondary" style="{hint_btn_display} font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem; border-color: var(--brass-border); color: var(--brass);" {hint_btn_disabled}>
                                    💡 <span id="btn-hint-text-{m_tier}">{hint_btn_text}</span>
                                </button>

                                <!-- Reveal Implementation Action Button (Separate, explicitly distinct action) -->
                                <button type="button" id="btn-reveal-{m_tier}" onclick="openRevealConfirmModal('{job_id}', {m_tier})" class="btn btn-sm btn-ghost" style="{reveal_btn_display} font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-tertiary); text-decoration: underline;">
                                    <span id="btn-reveal-text-{m_tier}">{reveal_btn_text}</span>
                                </button>

                                <!-- Untouched Milestone Hint Locked Notice -->
                                <span id="hint-locked-notice-{m_tier}" style="{locked_notice_display} font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: var(--text-tertiary); align-items: center; gap: 0.3rem;">
                                    🔒 Submit first attempt to unlock hints
                                </span>
                            </div>
                            <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary);">
                                Run: Sandbox execution &bull; Submit: Graded AST diff
                            </div>
                        </div>

                        <!-- Prompt 16: Live Execution Console Output Panel (Run & Submit Results) -->
                        <div id="console-output-panel-{m_tier}" class="console-output-panel" style="{console_initial_display} margin-top: 0.85rem; padding: 0.85rem 1rem; background: #0e1015; border: 1px solid var(--hairline-soft); border-radius: 4px;">
                            {console_rendered_html}
                        </div>

                        <!-- Live Inline Structural Diff Result Panel -->
                        <div id="diff-output-panel-{m_tier}" class="diff-output-panel" style="{diff_initial_display} margin-top: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border: 1px solid var(--hairline); border-radius: 4px;">
                            {diff_rendered_html}
                        </div>

                        <!-- Prompt 13: Confirmation Screen for Hint -->
                        <div id="hint-confirm-box-{m_tier}" class="hint-confirm-box" style="display: none; margin-top: 0.85rem; padding: 1rem 1.25rem; background: var(--panel); border: 1px solid var(--brass-border); border-radius: 4px; box-shadow: 0 4px 16px rgba(0,0,0,0.2);">
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem;">
                                <div style="display: flex; align-items: center; gap: 0.4rem;">
                                    <span class="chip-dot brass"></span>
                                    <span id="hint-confirm-title-{m_tier}" style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; color: var(--brass); text-transform: uppercase; letter-spacing: 0.05em;">
                                        Pedagogical Confirmation Gate
                                    </span>
                                </div>
                                <span class="tag" style="font-size: 0.65rem;">FIRM NOT MOCKING</span>
                            </div>
                            <p id="hint-confirm-text-{m_tier}" style="font-size: 0.875rem; color: var(--text-primary); line-height: 1.5; margin-bottom: 1rem;">
                                {HintEngine.SELECTED_HINT_1_CONFIRM}
                            </p>
                            <div style="display: flex; align-items: center; gap: 0.65rem;">
                                <button type="button" class="btn btn-sm btn-secondary" onclick="cancelHintConfirm({m_tier})">
                                    I'll Keep Trying
                                </button>
                                <button type="button" id="btn-confirm-hint-action-{m_tier}" class="btn btn-sm btn-primary" onclick="confirmAndFetchHint('{job_id}', {m_tier})">
                                    Yes, Reveal Hint
                                </button>
                            </div>
                        </div>

                        <!-- Prompt 13: Confirmation Screen for Reveal Implementation -->
                        <div id="reveal-confirm-box-{m_tier}" class="reveal-confirm-box" style="display: none; margin-top: 0.85rem; padding: 1rem 1.25rem; background: var(--panel); border: 1px solid var(--crimson); border-radius: 4px; box-shadow: 0 4px 16px rgba(0,0,0,0.2);">
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem;">
                                <div style="display: flex; align-items: center; gap: 0.4rem;">
                                    <span class="chip-dot crimson"></span>
                                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; color: var(--crimson); text-transform: uppercase; letter-spacing: 0.05em;">
                                        Reference Reveal Gate
                                    </span>
                                </div>
                                <span class="badge badge-crimson" style="font-size: 0.65rem;">PERMANENT ACTION</span>
                            </div>
                            <p style="font-size: 0.875rem; color: var(--text-primary); line-height: 1.5; margin-bottom: 1rem;">
                                {HintEngine.CONFIRM_REVEAL_COPY}
                            </p>
                            <div style="display: flex; align-items: center; gap: 0.65rem;">
                                <button type="button" class="btn btn-sm btn-secondary" onclick="cancelRevealConfirm({m_tier})">
                                    Cancel
                                </button>
                                <button type="button" id="btn-confirm-reveal-action-{m_tier}" class="btn btn-sm btn-danger" onclick="confirmAndRevealImplementation('{job_id}', {m_tier})">
                                    Confirm &amp; Reveal Reference Implementation
                                </button>
                            </div>
                        </div>

                        <!-- Progressive Hint 1 Tray -->
                        <div id="hint-1-panel-{m_tier}" class="hint-panel" style="{h1_style} margin-top: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border-left: 3px solid var(--brass); border-radius: 2px;">
                            <div style="display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.35rem;">
                                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; font-weight: 700; color: var(--brass); text-transform: uppercase; letter-spacing: 0.05em;">
                                    Hint 1 // Conceptual Architecture (No Code Leaked)
                                </span>
                            </div>
                            <div id="hint-1-text-{m_tier}" style="font-size: 0.8125rem; color: var(--text-primary); line-height: 1.55;">
                                {sanitize_text(h1_text)}
                            </div>
                        </div>

                        <!-- Progressive Hint 2 Tray -->
                        <div id="hint-2-panel-{m_tier}" class="hint-panel" style="{h2_style} margin-top: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border-left: 3px solid var(--amber); border-radius: 2px;">
                            <div style="display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.35rem;">
                                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; font-weight: 700; color: var(--amber); text-transform: uppercase; letter-spacing: 0.05em;">
                                    Hint 2 // Target Files &amp; Required AST Contracts (Zero Literal Code)
                                </span>
                            </div>
                            <div id="hint-2-text-{m_tier}" style="font-size: 0.8125rem; color: var(--text-primary); line-height: 1.55;">
                                {sanitize_text(h2_text)}
                            </div>
                        </div>

                        <!-- Revealed Reference Implementation Panel -->
                        <div id="reference-panel-{m_tier}" class="reference-panel" style="{ref_style} margin-top: 0.85rem; padding: 0.85rem 1rem; background: var(--panel-raised); border-left: 3px solid var(--teal); border-radius: 2px;">
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.45rem;">
                                <div style="display: flex; align-items: center; gap: 0.4rem;">
                                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; font-weight: 700; color: var(--teal); text-transform: uppercase; letter-spacing: 0.05em;">
                                        Reference Structural Architecture
                                    </span>
                                </div>
                                <span class="tag" style="font-size: 0.65rem;">STATIC AST SKELETON</span>
                            </div>
                            <pre style="background: #181a20; padding: 0.75rem 1rem; border-radius: 4px; overflow-x: auto; border: 1px solid var(--hairline); margin: 0;"><code id="reference-code-{m_tier}" class="mono" style="font-size: 0.78rem; color: var(--text-primary);">{ref_code_rendered}</code></pre>
                        </div>
                    </div>
                </div>
            </div>
            """

        milestones_spine_html = f"""
        <div class="stratum-card" id="section-milestones" style="margin-bottom: 2rem;">
            <div class="card-header">
                <div>
                    <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); text-transform: uppercase; letter-spacing: 0.05em;">
                        Section 03 // Architectural Reading Sequence
                    </div>
                    <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Step-by-Step Milestones &amp; Reading Spine</h2>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="chip"><span class="chip-dot brass"></span> {len(milestones_data)} Milestones</span>
                </div>
            </div>
            <p style="color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 1.5rem; line-height: 1.5;">
                Recommended pedagogical walkthrough synthesized from leaf dependencies upwards to top-level entry orchestration.
            </p>
            <div class="milestone-spine-track" style="position: relative;">
                <div style="position: absolute; left: 21px; top: 20px; bottom: 20px; width: 2px; background: var(--hairline); z-index: 1;"></div>
                {items_html}
            </div>
        </div>
        """

    # -------------------------------------------------------------
    # 4. Codebase Mastery Quiz Section
    # -------------------------------------------------------------
    quiz_html = ""
    if quiz_data and "questions" in quiz_data:
        questions = quiz_data.get("questions", [])
        quiz_items_rendered = ""
        for i, q in enumerate(questions, 1):
            q_text = sanitize_text(q.get("question", ""))
            q_tier = sanitize_text(str(q.get("tier", "—")))
            q_exp = sanitize_text(q.get("explanation", ""))
            options = q.get("options", [])
            correct_idx = q.get("correct_index", 0)

            opts_html = ""
            for opt_idx, opt in enumerate(options):
                opt_text = sanitize_text(opt)
                opts_html += f"""
                <label style="display: flex; align-items: flex-start; gap: 0.6rem; padding: 0.6rem 0.85rem; background: var(--panel-raised); border: 1px solid var(--hairline-soft); border-radius: 4px; cursor: pointer; transition: all 120ms ease; margin-bottom: 0.4rem;">
                    <input type="radio" name="quiz_q_{i}" value="{opt_idx}" style="margin-top: 0.2rem; accent-color: var(--brass);" />
                    <span style="font-size: 0.8125rem; color: var(--text-primary); line-height: 1.4;">{opt_text}</span>
                </label>
                """

            quiz_items_rendered += f"""
            <div class="quiz-card" style="background: var(--panel); border: 1px solid var(--hairline); border-radius: 4px; padding: 1.25rem; margin-bottom: 1rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); font-weight: 600;">QUESTION {i:02d}</span>
                    <span class="tag">Tier {q_tier} Invariant</span>
                </div>
                <div style="font-size: 0.9rem; font-weight: 500; color: var(--text-primary); margin-bottom: 0.85rem; line-height: 1.45;">
                    {q_text}
                </div>
                <div style="margin-bottom: 0.75rem;">
                    {opts_html}
                </div>
                <div style="display: flex; align-items: center; gap: 0.65rem;">
                    <button type="button" class="btn btn-sm btn-secondary" onclick="verifyQuizAnswer({i}, {correct_idx})">Verify Answer</button>
                    <div id="quiz-feedback-{i}" style="display: none; font-size: 0.75rem; font-family: 'IBM Plex Mono', monospace; padding: 0.35rem 0.65rem; border-radius: 3px;"></div>
                </div>
                <div id="quiz-explanation-{i}" style="display: none; margin-top: 0.65rem; padding: 0.65rem 0.85rem; background: var(--panel-raised); border-left: 2px solid var(--teal); border-radius: 2px; font-size: 0.75rem; color: var(--text-secondary); line-height: 1.45;">
                    <span style="font-weight: 600; color: var(--text-primary);">Pedagogical Invariant:</span> {q_exp}
                </div>
            </div>
            """

        quiz_html = f"""
        <div class="stratum-card" id="section-quiz" style="margin-bottom: 2rem;">
            <div class="card-header">
                <div>
                    <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); text-transform: uppercase; letter-spacing: 0.05em;">
                        Section 04 // Interactive Validation
                    </div>
                    <h2 style="font-size: 1.45rem; font-weight: 500; margin-top: 0.15rem;">Codebase Structural Invariants Quiz</h2>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="chip"><span class="chip-dot teal"></span> {len(questions)} Validation Items</span>
                </div>
            </div>
            <p style="color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 1.25rem; line-height: 1.5;">
                Test and verify architectural comprehension of the key contracts, boundary transitions, and invariants across decomposed tiers.
            </p>
            <div>
                {quiz_items_rendered}
            </div>
        </div>
        """

    # -------------------------------------------------------------
    # 5. Full Raw Markdown Transcript (Collapsible Archive)
    # -------------------------------------------------------------
    raw_markdown_drawer = f"""
    <div class="stratum-card" id="section-raw-markdown" style="margin-bottom: 2rem;">
        <details>
            <summary style="font-family: 'IBM Plex Mono', monospace; font-size: 0.8125rem; font-weight: 600; color: var(--text-secondary); cursor: pointer; user-select: none; display: flex; align-items: center; justify-content: space-between;">
                <span>&gt; Complete Raw Synthesis Markdown Transcript</span>
                <span class="chip" style="font-size: 0.625rem;">GITHUB FLAVORED MARKDOWN</span>
            </summary>
            <div class="markdown-body" style="margin-top: 1.25rem; padding-top: 1.25rem; border-top: 1px solid var(--hairline);">
                {safe_markdown_html}
            </div>
        </details>
    </div>
    """

    # Extra Interactive Scripts & Graph Logic
    graph_nodes_json = json.dumps(nodes).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    graph_edges_json = json.dumps(edges).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    extra_scripts = f"""
    <!-- CodeMirror Assets -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/python/python.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/javascript/javascript.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/clike/clike.min.js"></script>

    <script>
        const GRAPH_NODES = {graph_nodes_json};
        const GRAPH_EDGES = {graph_edges_json};
        window.cmEditors = {{}};

        function initCodeEditors() {{
            document.querySelectorAll('textarea[id^="code-editor-"]').forEach(function(ta) {{
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
                    console.warn('CodeMirror init failed, falling back to textarea', e);
                    ta.style.display = 'block';
                    ta.style.width = '100%';
                    ta.style.minHeight = '180px';
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

        function renderDiffHtmlInJs(result, isVerified, errorMsg, gradingMethod) {{
            let tierTag = '<span class="badge badge-brass" style="font-size: 0.65rem; letter-spacing: 0.04em;">TIER 3 // STATIC AST DIFF</span>';
            if (gradingMethod === 'real_tests') {{
                tierTag = '<span class="badge badge-teal" style="font-size: 0.65rem; letter-spacing: 0.04em;">TIER 1 // REAL REPO TEST SUITE</span>';
            }} else if (gradingMethod === 'expected_output') {{
                tierTag = '<span class="badge badge-amber" style="font-size: 0.65rem; letter-spacing: 0.04em;">TIER 2 // EXPECTED OUTPUT</span>';
            }}

            let banner = '';
            if (isVerified) {{
                banner = '<div class="diff-banner success" style="background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--teal); padding: 0.65rem 0.85rem; border-radius: 4px; font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.75rem; font-weight: 600; margin-bottom: 0.65rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; flex-wrap: wrap;"><div style="display: flex; align-items: center; gap: 0.4rem;"><span>✓</span> VERIFIED: Milestone requirements fulfilled</div>' + tierTag + '</div>';
            }} else {{
                banner = '<div class="diff-banner failure" style="background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.65rem 0.85rem; border-radius: 4px; font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.75rem; font-weight: 600; margin-bottom: 0.65rem; display: flex; justify-content: space-between; align-items: center; gap: 0.4rem; flex-wrap: wrap;"><div style="display: flex; align-items: center; gap: 0.4rem;"><span>⚠</span> VERIFICATION GAPS: Requirements not yet satisfied</div>' + tierTag + '</div>';
            }}

            const diff = (result && result.diff) ? result.diff : (result || {{}});
            const present = diff.present_symbols || diff.present || [];
            const missing = diff.missing_symbols || diff.missing || [];
            const extra = diff.extra_symbols || diff.extra || [];
            const err = errorMsg || diff.error_message || diff.error;

            let errHtml = '';
            if (err) {{
                errHtml = '<div style="color: var(--crimson); font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.75rem; margin-bottom: 0.5rem; background: rgba(244,63,94,0.08); padding: 0.5rem; border-radius: 3px;">' + escapeHtml(err) + '</div>';
            }}

            let presentPills = '';
            present.forEach(function(s) {{
                const mat = s.matched || s.expected || s || {{}};
                const name = escapeHtml(typeof mat === 'object' ? (mat.name || '') : String(mat));
                const kind = escapeHtml(typeof mat === 'object' ? (mat.kind || 'symbol') : 'symbol');
                const argsStr = mat.args && mat.args.length ? '(' + mat.args.map(escapeHtml).join(', ') + ')' : '';
                presentPills += '<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(45, 212, 191, 0.12); border: 1px solid var(--teal-border); color: var(--teal); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.75rem;">✓ ' + name + argsStr + ' <span style="opacity: 0.75; font-size: 0.6875rem;">(' + kind + ')</span></span> ';
            }});

            let missingPills = '';
            missing.forEach(function(s) {{
                const mat = s.expected || s || {{}};
                const name = escapeHtml(typeof mat === 'object' ? (mat.name || '') : String(mat));
                const kind = escapeHtml(typeof mat === 'object' ? (mat.kind || 'required') : 'required');
                missingPills += '<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(244, 63, 94, 0.12); border: 1px solid rgba(244, 63, 94, 0.35); color: var(--crimson); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.75rem;">✗ ' + name + ' <span style="opacity: 0.75; font-size: 0.6875rem;">(' + kind + ')</span></span> ';
            }});

            let extraPills = '';
            extra.forEach(function(s) {{
                const mat = s.matched || s || {{}};
                const name = escapeHtml(typeof mat === 'object' ? (mat.name || '') : String(mat));
                const kind = escapeHtml(typeof mat === 'object' ? (mat.kind || 'extra') : 'extra');
                extraPills += '<span style="display: inline-flex; align-items: center; gap: 0.3rem; background: var(--panel-raised); border: 1px solid var(--hairline); color: var(--text-secondary); padding: 0.2rem 0.5rem; border-radius: 3px; font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.75rem;">+ ' + name + ' <span style="opacity: 0.75; font-size: 0.6875rem;">(' + kind + ')</span></span> ';
            }});

            let sectionsHtml = '';
            if (presentPills) {{
                sectionsHtml += '<div><div style="font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.6875rem; color: var(--teal); font-weight: 600; margin-bottom: 0.25rem;">PRESENT &amp; MATCHED SYMBOLS (' + present.length + '):</div><div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">' + presentPills + '</div></div>';
            }}
            if (missingPills) {{
                sectionsHtml += '<div><div style="font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.6875rem; color: var(--crimson); font-weight: 600; margin-bottom: 0.25rem;">MISSING EXPECTED SYMBOLS (' + missing.length + '):</div><div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">' + missingPills + '</div></div>';
            }}
            if (extraPills) {{
                sectionsHtml += '<div><div style="font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.6875rem; color: var(--text-tertiary); font-weight: 600; margin-bottom: 0.25rem;">EXTRA / AUXILIARY SYMBOLS (' + extra.length + '):</div><div style="display: flex; flex-wrap: wrap; gap: 0.35rem;">' + extraPills + '</div></div>';
            }}

            return banner + errHtml + '<div style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.5rem;">' + sectionsHtml + '</div>';
        }}

        function renderConsoleHtmlInJs(exec) {{
            if (!exec) return '';
            const eObj = (exec.execution) ? exec.execution : exec;
            const exitCode = (eObj.exit_code !== undefined && eObj.exit_code !== null) ? eObj.exit_code : 0;
            const isSuccess = (exitCode === 0 && !eObj.timed_out && !eObj.memory_exceeded);
            const stdout = eObj.stdout || '';
            const stderr = eObj.stderr || '';
            const execMs = (eObj.execution_time_ms !== undefined && eObj.execution_time_ms !== null) ? (eObj.execution_time_ms + 'ms') : '';
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
                content = '<div style="color: var(--text-tertiary); font-style: italic;">(Process completed with no output)</div>';
            }}

            return '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; border-bottom: 1px solid var(--hairline); padding-bottom: 0.4rem;">' +
                '<div style="display: flex; align-items: center; gap: 0.5rem;">' +
                    '<span class="chip-dot ' + dotColor + '"></span>' +
                    '<span style="font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.72rem; font-weight: 600; color: var(--text-primary); text-transform: uppercase;">Execution Console</span>' +
                    '<span class="badge ' + exitBadgeClass + '" style="font-size: 0.65rem;">' + exitBadgeText + '</span>' +
                    (execMs ? '<span class="tag" style="font-size: 0.65rem;">' + execMs + '</span>' : '') +
                '</div>' +
                '<span style="font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.65rem; color: var(--text-tertiary);">UNMETERED PLAYGROUND</span>' +
            '</div>' +
            '<pre style="background: #0d0e12; padding: 0.75rem; border-radius: 3px; border: 1px solid var(--hairline-soft); font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.78rem; line-height: 1.45; overflow-x: auto; margin: 0;"><code>' + content + '</code></pre>';
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
                    const errData = await resp.json().catch(() => ({{}}));
                    const msg = errData.detail || ('HTTP ' + resp.status + ' execution error');
                    if (consolePanel) {{
                        consolePanel.style.display = 'block';
                        consolePanel.innerHTML = '<div style="color: var(--crimson); font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.8125rem;">Execution Error: ' + escapeHtml(msg) + '</div>';
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
                    consolePanel.innerHTML = '<div style="color: var(--crimson); font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.8125rem;">Execution Network Error: ' + escapeHtml(e.message) + '</div>';
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
                        submitted_code: submittedCode
                    }})
                }});

                if (!resp.ok) {{
                    const errData = await resp.json().catch(() => ({{}}));
                    const msg = errData.detail || ('HTTP ' + resp.status + ' error occurred');
                    if (diffPanel) {{
                        diffPanel.style.display = 'block';
                        diffPanel.innerHTML = '<div style="color: var(--crimson); font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.8125rem;">Verification Error: ' + escapeHtml(msg) + '</div>';
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
                    diffPanel.innerHTML = '<div style="color: var(--crimson); font-family: \\'IBM Plex Mono\\', monospace; font-size: 0.8125rem;">Network Error: ' + escapeHtml(e.message) + '</div>';
                }}
            }} finally {{
                if (btn) btn.disabled = false;
                if (spinner) spinner.style.display = 'none';
            }}
        }}

        const HINT_CONFIRM_COPY_1 = "{HintEngine.SELECTED_HINT_1_CONFIRM}";
        const HINT_CONFIRM_COPY_2 = "{HintEngine.CONFIRM_HINT_2_COPY}";
        const REVEAL_CONFIRM_COPY = "{HintEngine.CONFIRM_REVEAL_COPY}";

        function openHintConfirmModal(jobId, tier) {{
            const hintBtn = document.getElementById('btn-hint-' + tier);
            const level = parseInt(hintBtn ? hintBtn.getAttribute('data-hint-level') || '0' : '0', 10);
            const box = document.getElementById('hint-confirm-box-' + tier);
            const titleEl = document.getElementById('hint-confirm-title-' + tier);
            const textEl = document.getElementById('hint-confirm-text-' + tier);
            const actionBtn = document.getElementById('btn-confirm-hint-action-' + tier);

            if (level >= 2) return;

            if (level === 0) {{
                if (titleEl) titleEl.textContent = 'Pedagogical Confirmation Gate // Hint 1';
                if (textEl) textEl.textContent = HINT_CONFIRM_COPY_1;
                if (actionBtn) actionBtn.textContent = 'Yes, Reveal Conceptual Hint';
            }} else {{
                if (titleEl) titleEl.textContent = 'Target Symbol Gate // Hint 2';
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
            const hintBtn = document.getElementById('btn-hint-' + tier);
            const hintBtnText = document.getElementById('btn-hint-text-' + tier);

            if (actionBtn) actionBtn.disabled = true;

            try {{
                const resp = await fetch('/api/attempts/' + jobId + '/' + tier + '/hint', {{
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

                if (hintBtn) {{
                    hintBtn.setAttribute('data-hint-level', String(level));
                    if (level === 1) {{
                        if (hintBtnText) hintBtnText.textContent = 'Request Next Hint (Hint 2)';
                    }} else if (level >= 2) {{
                        if (hintBtnText) hintBtnText.textContent = 'Hints Unlocked (2/2)';
                        hintBtn.disabled = true;
                    }}
                }}
            }} catch(e) {{
                console.error('Failed to retrieve hint', e);
                alert('Network error while requesting hint');
            }} finally {{
                if (actionBtn) actionBtn.disabled = false;
            }}
        }}

        function openRevealConfirmModal(jobId, tier) {{
            const box = document.getElementById('reveal-confirm-box-' + tier);
            if (box) box.style.display = 'block';
        }}

        function cancelRevealConfirm(tier) {{
            const box = document.getElementById('reveal-confirm-box-' + tier);
            if (box) box.style.display = 'none';
        }}

        async function confirmAndRevealImplementation(jobId, tier) {{
            const box = document.getElementById('reveal-confirm-box-' + tier);
            const actionBtn = document.getElementById('btn-confirm-reveal-action-' + tier);
            const revealBtn = document.getElementById('btn-reveal-' + tier);
            const revealBtnText = document.getElementById('btn-reveal-text-' + tier);

            if (actionBtn) actionBtn.disabled = true;

            try {{
                const resp = await fetch('/api/attempts/' + jobId + '/' + tier + '/reveal', {{
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
                    revealBtnText.textContent = 'Reference Revealed';
                }}
            }} catch(e) {{
                console.error('Failed to reveal implementation', e);
                alert('Network error while revealing implementation');
            }} finally {{
                if (actionBtn) actionBtn.disabled = false;
            }}
        }}

        // Graph Search Filter
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
                const src = e.getAttribute('data-source');
                const tgt = e.getAttribute('data-target');
                if (matchedIds.has(src) || matchedIds.has(tgt)) {{
                    e.style.opacity = '0.9';
                    e.setAttribute('stroke', 'var(--brass)');
                }} else {{
                    e.style.opacity = '0.08';
                }}
            }});
        }}

        // Hover node highlighting
        function hoverDagNode(nodeId) {{
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
                    e.setAttribute('stroke', 'var(--brass)');
                    e.setAttribute('stroke-width', '2.5');
                    e.setAttribute('marker-end', 'url(#dag-arrow-active)');
                }} else if (tgt === nodeId) {{
                    connectedSources.add(src);
                    e.style.opacity = '1';
                    e.setAttribute('stroke', 'var(--teal)');
                    e.setAttribute('stroke-width', '2.5');
                    e.setAttribute('marker-end', 'url(#dag-arrow-active)');
                }} else {{
                    e.style.opacity = '0.1';
                }}
            }});
            
            nodes.forEach(n => {{
                const id = n.getAttribute('data-node-id');
                if (id === nodeId || connectedSources.has(id) || connectedTargets.has(id)) {{
                    n.style.opacity = '1';
                }} else {{
                    n.style.opacity = '0.2';
                }}
            }});
        }}

        function unhoverDagNode() {{
            const searchVal = document.getElementById('dag-search-input')?.value;
            if (searchVal) {{
                filterDagNodes(searchVal);
                return;
            }}
            const nodes = document.querySelectorAll('.dag-node');
            const edges = document.querySelectorAll('.dag-edge');
            nodes.forEach(n => {{ n.style.opacity = '1'; }});
            edges.forEach(e => {{
                e.style.opacity = '0.45';
                e.setAttribute('stroke', 'var(--hairline-strong)');
                e.setAttribute('stroke-width', '1.5');
                e.setAttribute('marker-end', 'url(#dag-arrow)');
            }});
        }}

        // Node Inspector
        function selectDagNode(nodeId) {{
            const node = GRAPH_NODES.find(n => n.id === nodeId);
            const inspector = document.getElementById('dag-node-inspector');
            if (!node || !inspector) return;
            
            inspector.style.display = 'block';
            document.getElementById('inspect-label').textContent = node.label || node.id;
            document.getElementById('inspect-path').textContent = node.path || node.id;
            document.getElementById('inspect-tier').textContent = 'Tier ' + (node.tier !== undefined ? node.tier : '—');
            document.getElementById('inspect-domain').textContent = (node.domain || 'CORE').toUpperCase();
            
            const dot = document.getElementById('inspect-dot');
            const conf = (node.confidence || 'high').toLowerCase();
            dot.className = 'chip-dot ' + (conf === 'high' ? 'teal' : (conf === 'medium' ? 'amber' : 'crimson'));
            
            const exports = node.exports || [];
            document.getElementById('inspect-exports').textContent = exports.length ? exports.join(', ') : 'No public exports declared';
            
            // Inbound & outbound deps
            const inDeps = GRAPH_EDGES.filter(e => e.target === nodeId).map(e => e.source);
            const outDeps = GRAPH_EDGES.filter(e => e.source === nodeId).map(e => e.target);
            
            let depStr = '';
            if (outDeps.length) depStr += 'Imports (' + outDeps.length + '): ' + outDeps.join(', ');
            if (inDeps.length) depStr += (depStr ? ' | ' : '') + 'Imported By (' + inDeps.length + '): ' + inDeps.join(', ');
            document.getElementById('inspect-deps').textContent = depStr || 'Isolated / Leaf Node';
            
            inspector.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
        }}

        function closeDagInspector() {{
            const inspector = document.getElementById('dag-node-inspector');
            if (inspector) inspector.style.display = 'none';
        }}

        function resetDagZoom() {{
            const input = document.getElementById('dag-search-input');
            if (input) input.value = '';
            unhoverDagNode();
            closeDagInspector();
            const container = document.getElementById('dag-visual-container');
            if (container) container.scrollLeft = 0;
        }}

        function toggleGraphViewMode() {{
            const visual = document.getElementById('dag-visual-container');
            const table = document.getElementById('dag-table-container');
            const btn = document.getElementById('toggle-view-btn');
            if (!visual || !table || !btn) return;
            
            if (visual.style.display === 'none') {{
                visual.style.display = 'block';
                table.style.display = 'none';
                btn.textContent = 'Table Catalog';
            }} else {{
                visual.style.display = 'none';
                table.style.display = 'block';
                btn.textContent = 'Visual Graph';
            }}
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
                feedback.style.color = 'var(--teal)';
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
    </script>
    """

    extra_head = """
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/dracula.min.css">
    <style>
        .kpi-card {
            background: var(--panel-raised);
            border: 1px solid var(--hairline);
            border-radius: 4px;
            padding: 0.85rem 1rem;
            transition: all 120ms ease;
        }
        .kpi-card:hover {
            border-color: var(--brass-border);
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .kpi-label {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.6875rem;
            font-weight: 600;
            color: var(--text-tertiary);
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 0.2rem;
        }
        .kpi-value {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 1.25rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 0.15rem;
        }
        .kpi-sub {
            font-size: 0.6875rem;
            color: var(--text-secondary);
        }
        .entry-chip {
            display: flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.35rem 0.65rem;
            background: var(--panel-raised);
            border: 1px solid var(--hairline-soft);
            border-radius: 3px;
            transition: all 120ms ease;
        }
        .entry-chip:hover {
            border-color: var(--brass);
            background: var(--panel-overlay);
        }
        .dag-node-box {
            transition: stroke 150ms ease, fill 150ms ease, filter 150ms ease;
        }
        .dag-node:hover .dag-node-box {
            stroke: var(--brass);
            stroke-width: 2px;
            filter: drop-shadow(0 0 6px rgba(212, 163, 89, 0.25));
        }
        .milestone-item:last-child {
            margin-bottom: 0 !important;
        }

        /* CodeMirror & Spine Vessel Styles */
        .CodeMirror {
            font-family: 'IBM Plex Mono', monospace !important;
            font-size: 0.8125rem !important;
            height: 200px !important;
            border-radius: 4px;
            background: #181920 !important;
        }
        .CodeMirror-gutters {
            background: #121318 !important;
            border-right: 1px solid var(--hairline) !important;
        }
        .CodeMirror-linenumber {
            color: var(--text-tertiary) !important;
        }

        .milestone-vessel.not-started {
            background: var(--panel-raised) !important;
            border: 1px solid var(--hairline-strong) !important;
            color: var(--text-tertiary) !important;
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
            border: 2px solid var(--teal) !important;
            color: var(--teal) !important;
            box-shadow: 0 0 14px rgba(45, 212, 191, 0.35) !important;
        }
        @keyframes pulse-amber {
            0%, 100% { box-shadow: 0 0 6px rgba(245, 158, 11, 0.2); }
            50% { box-shadow: 0 0 16px rgba(245, 158, 11, 0.45); }
        }
    </style>
    """

    content = f"""
    <div style="max-width: 1040px; margin: 0 auto;">
        <!-- Top Dossier Navigation & Meta Bar -->
        <div style="margin-bottom: 1.75rem; display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem;">
            <div>
                <a href="/dashboard" style="display: inline-flex; align-items: center; gap: 0.4rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                    &larr; BACK TO DASHBOARD LEDGER
                </a>
                <div style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
                    <h1 style="font-size: 2.15rem; font-weight: 500; letter-spacing: -0.02em;">Repository Dossier: <span style="font-style: italic; color: var(--brass);">{repo_name}</span></h1>
                </div>
                <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.2rem;">
                    Codebase Intelligence Report &bull; Structural Syntax Tree &amp; Dependency Reconstruction
                </div>
                <div style="display: flex; align-items: center; gap: 0.75rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-tertiary); margin-top: 0.35rem; flex-wrap: wrap;">
                    <span>TARGET: <a href="{repo_url}" target="_blank" rel="noopener noreferrer" style="color: var(--text-secondary);">{repo_url}</a></span>
                    <span>&bull;</span>
                    <span>SYNTHESIZED: {created_at}</span>
                    <span>&bull;</span>
                    <span>DURATION: {duration}</span>
                </div>
            </div>
            <div style="display: flex; gap: 0.5rem; align-items: center;">
                <button onclick="window.print()" class="btn btn-secondary btn-sm" title="Print or save as PDF">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 6 2 18 2 18 9"></polyline>
                        <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path>
                        <rect x="6" y="14" width="12" height="8"></rect>
                    </svg>
                    Print Dossier
                </button>
            </div>
        </div>

        <!-- Section 01: Executive Architecture Stratum (KPI Bento Grid & Callouts) -->
        {overview_section_html}

        <!-- Section 02: Visual Topological Dependency Graph (SVG Interactive DAG) -->
        {graph_section_html}

        <!-- Section 03: Step-by-Step Milestones Timeline Spine -->
        {milestones_spine_html}

        <!-- Section 04: Codebase Mastery Quiz -->
        {quiz_html}

        <!-- Section 05: Raw Markdown Transcript Drawer -->
        {raw_markdown_drawer}
    </div>
    """
    return page_shell(
        "Repository Dossier",
        content,
        current_user=current_user,
        active_route="/report",
        billing_status=billing_status,
        extra_head=extra_head,
        extra_scripts=extra_scripts,
    )



def settings_view(
    current_user: UserModel,
    billing_status: Dict[str, Any],
    pricing_details: Dict[str, Any],
    error: Optional[str] = None,
    success: Optional[str] = None,
) -> str:
    """
    Renders the Settings & Billing view with Archival Dossier aesthetic.
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
    created_at = sanitize_text(current_user.created_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(current_user.created_at, "strftime") else str(current_user.created_at))

    amount_formatted = sanitize_text(pricing_details.get("amount_formatted", "Upgrade"))
    interval = sanitize_text(pricing_details.get("interval", "month"))

    error_html = f'<div class="alert-error" style="margin-bottom: 1.5rem;">{sanitize_text(error)}</div>' if error else ""
    success_html = f'<div style="background: rgba(45, 212, 191, 0.1); border: 1px solid var(--teal); color: var(--teal); padding: 0.75rem 1rem; border-radius: 4px; margin-bottom: 1.5rem; font-size: 0.875rem;">{sanitize_text(success)}</div>' if success else ""

    avatar_markup = f'<img src="{user_avatar}" alt="@{username}" style="width: 52px; height: 52px; border-radius: 4px; object-fit: cover; border: 1px solid var(--hairline);">' if user_avatar else f'''
    <div style="width: 52px; height: 52px; border-radius: 4px; background: var(--brass-soft); border: 1px solid var(--brass-border); display: flex; align-items: center; justify-content: center; color: var(--brass);">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
        </svg>
    </div>
    '''

    tier_badge = '<span class="badge badge-completed">PRO TIER</span>' if is_paid else '<span class="badge badge-free">FREE TIER</span>'

    # Right column plan card details
    if is_paid:
        plan_card_html = f"""
        <div class="stratum-card" style="margin-bottom: 1.5rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem;">
                <h2 style="font-size: 1.25rem; font-weight: 500;">Plan &amp; Allocations</h2>
                {tier_badge}
            </div>
            
            <div style="background: var(--panel-inset); padding: 1.25rem; border-radius: 4px; border: 1px solid var(--hairline); margin-bottom: 1.25rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase;">Active Subscription</span>
                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.8125rem; font-weight: 600; color: var(--teal);">UNLIMITED INQUESTS</span>
                </div>
                <div class="meter" style="margin-bottom: 0.75rem;">
                    <div class="meter-fill high" style="width: 100%;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary);">
                    <span>BILLING CYCLE:</span>
                    <span>PERIOD ENDS {renewal_str}</span>
                </div>
            </div>

            <div style="background: var(--panel-raised); border: 1px solid var(--hairline); border-radius: 4px; padding: 1.25rem;">
                <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 0.35rem;">Enterprise Forensic Suite</div>
                <p style="color: var(--text-secondary); font-size: 0.85rem; line-height: 1.45; margin-bottom: 1rem;">
                    Your account has unmetered access to the 11-Layer Reverse Intelligence engine, priority AST parsing, and interactive dependency graphs.
                </p>
                <a href="/api/billing/portal" class="btn btn-secondary" style="width: 100%; justify-content: center; padding: 0.75rem;">
                    Manage Subscription &amp; Invoices &rarr;
                </a>
            </div>
        </div>
        """
    else:
        plan_card_html = f"""
        <div class="stratum-card" style="margin-bottom: 1.5rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem;">
                <h2 style="font-size: 1.25rem; font-weight: 500;">Plan &amp; Allocations</h2>
                {tier_badge}
            </div>

            <!-- Quota Meter Box -->
            <div style="background: var(--panel-inset); padding: 1.25rem; border-radius: 4px; border: 1px solid var(--hairline); margin-bottom: 1.25rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase;">Billing Cycle Allocation</span>
                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.8125rem; font-weight: 600; color: var(--brass);">{monthly_usage} / {monthly_quota} CONSUMED ({pct}%)</span>
                </div>
                <div class="meter" style="margin-bottom: 0.75rem;">
                    <div class="meter-fill {meter_class}" style="width: {pct}%;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary);">
                    <span>AUTOMATIC RESET:</span>
                    <span>{renewal_str}</span>
                </div>
            </div>

            <!-- Upgrade Card with Dynamic Stripe Price -->
            <div style="background: var(--panel-raised); border: 1px solid var(--brass-border); border-radius: 4px; padding: 1.5rem; position: relative; overflow: hidden;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem;">
                    <div>
                        <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;">
                            ENTERPRISE FORENSIC SUITE
                        </div>
                        <div style="display: flex; align-items: baseline; gap: 0.4rem; margin-top: 0.35rem;">
                            <span style="font-family: 'Newsreader', serif; font-size: 2.25rem; font-weight: 500; color: var(--text-primary);">{amount_formatted}</span>
                            <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.8125rem; color: var(--text-tertiary);">/ {interval}</span>
                        </div>
                    </div>
                    <span class="badge" style="background: var(--brass-soft); color: var(--brass); border-color: var(--brass-border);">RECOMMENDED</span>
                </div>

                <div style="display: flex; flex-col; gap: 0.6rem; margin-bottom: 1.5rem; font-size: 0.85rem; color: var(--text-secondary); line-height: 1.4;">
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--teal)" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        <span><strong>Unlimited</strong> repository architecture reconstructions</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--teal)" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        <span>Priority AST parsing &amp; deterministic strata slicing queue</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 0.5rem;">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--teal)" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        <span>Interactive dependency graph visualization &amp; comprehension quizzes</span>
                    </div>
                </div>

                <a href="/api/billing/checkout" class="btn btn-primary" style="width: 100%; justify-content: center; padding: 0.85rem; font-size: 0.95rem;">
                    Upgrade to Pro via Stripe &rarr;
                </a>
            </div>
        </div>
        """

    content = f"""
    <!-- Settings Top Archival Header -->
    <div style="display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 1.5rem; margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--hairline);">
        <div>
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.35rem;">
                <span class="chip-dot brass"></span>
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); text-transform: uppercase; letter-spacing: 0.05em;">
                    INSTITUTIONAL LEDGER // SETTINGS
                </span>
            </div>
            <h1 style="font-size: 2.25rem; font-weight: 500; letter-spacing: -0.02em; margin-bottom: 0.4rem;">
                Account &amp; Workspace Ledger
            </h1>
            <p style="color: var(--text-secondary); font-size: 0.9375rem; max-width: 620px; line-height: 1.5;">
                Manage your connected GitHub identity, visual contrast standard, and subscription allocations.
            </p>
        </div>
        <div style="display: flex; gap: 0.75rem; align-items: center;">
            <div class="tag">
                <span class="chip-dot teal"></span>
                <span>GITHUB OAUTH CONNECTED</span>
            </div>
        </div>
    </div>

    {error_html}
    {success_html}

    <!-- Bento Grid Layout: 2 Columns on Desktop -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1.75rem; align-items: start;">
        
        <!-- Left Column: Identity & Theme & Logout -->
        <div>
            <!-- Section 1: GitHub OAuth Identity Dossier -->
            <div class="stratum-card" style="margin-bottom: 1.5rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.25rem;">
                    <h2 style="font-size: 1.25rem; font-weight: 500;">Institutional Identity</h2>
                    <span class="tag">CONNECTED</span>
                </div>

                <div style="display: flex; align-items: center; gap: 1.25rem; background: var(--panel-inset); padding: 1.25rem; border-radius: 4px; border: 1px solid var(--hairline); margin-bottom: 1rem;">
                    {avatar_markup}
                    <div>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <span style="font-weight: 600; color: var(--text-primary); font-size: 1.05rem;">@{username}</span>
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="var(--teal)" stroke="var(--teal)" stroke-width="1.5">
                                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                            </svg>
                        </div>
                        <div style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.15rem;">{email}</div>
                        <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); margin-top: 0.35rem;">
                            REGISTERED: {created_at}
                        </div>
                    </div>
                </div>

                <div style="font-size: 0.8125rem; color: var(--text-tertiary); line-height: 1.45; background: var(--panel-raised); padding: 0.75rem 1rem; border-radius: 4px; border: 1px dashed var(--hairline-soft);">
                    Profile information and notification email are synced directly from GitHub OAuth. Profile modifications must be made within your GitHub account.
                </div>
            </div>

            <!-- Section 2: Visual Telemetry / Theme Matrix -->
            <div class="stratum-card" style="margin-bottom: 1.5rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h2 style="font-size: 1.25rem; font-weight: 500;">Archival Visual Standard</h2>
                    <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary);">RUNTIME: DATA-THEME</span>
                </div>
                <p style="color: var(--text-secondary); font-size: 0.85rem; line-height: 1.5; margin-bottom: 1.25rem;">
                    Select visual contrast protocol for parsing call graphs and code diffs. Settings persist across browser sessions in local storage.
                </p>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                    <!-- Dark Option -->
                    <button type="button" id="theme-card-dark" onclick="applyThemePreference('dark')" style="text-align: left; padding: 1rem; border-radius: 4px; background: var(--panel-inset); border: 2px solid var(--brass); cursor: pointer; transition: all 150ms ease;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; color: var(--brass); text-transform: uppercase;">Dark Dossier</span>
                            <span id="theme-check-dark" style="color: var(--brass); font-weight: bold; font-size: 0.875rem;">✓</span>
                        </div>
                        <div style="height: 24px; background: #0c0e11; border-radius: 2px; border: 1px solid #282a2d; margin-bottom: 0.5rem; display: flex; align-items: center; padding: 0 0.5rem; gap: 0.35rem;">
                            <div style="width: 8px; height: 8px; border-radius: 50%; background: #d4a359;"></div>
                            <div style="width: 24px; height: 4px; border-radius: 2px; background: #333538;"></div>
                        </div>
                        <div style="font-size: 0.75rem; color: var(--text-tertiary); line-height: 1.35;">
                            Pitch-dark substrate with high-density brass highlights.
                        </div>
                    </button>

                    <!-- Light Option -->
                    <button type="button" id="theme-card-light" onclick="applyThemePreference('light')" style="text-align: left; padding: 1rem; border-radius: 4px; background: var(--panel-inset); border: 2px solid var(--hairline); cursor: pointer; transition: all 150ms ease;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; color: var(--text-primary); text-transform: uppercase;">Light Archival</span>
                            <span id="theme-check-light" style="color: var(--brass); font-weight: bold; font-size: 0.875rem; display: none;">✓</span>
                        </div>
                        <div style="height: 24px; background: #fbfbfd; border-radius: 2px; border: 1px solid #d3c4b3; margin-bottom: 0.5rem; display: flex; align-items: center; padding: 0 0.5rem; gap: 0.35rem;">
                            <div style="width: 8px; height: 8px; border-radius: 50%; background: #614000;"></div>
                            <div style="width: 24px; height: 4px; border-radius: 2px; background: #9c8f7f;"></div>
                        </div>
                        <div style="font-size: 0.75rem; color: var(--text-tertiary); line-height: 1.35;">
                            High-readability paper print mode optimized for daylight.
                        </div>
                    </button>
                </div>

                <div style="display: flex; justify-content: space-between; align-items: center; background: var(--panel-raised); padding: 0.65rem 1rem; border-radius: 4px; font-size: 0.8125rem;">
                    <span style="color: var(--text-secondary);">Hardware Synchronization:</span>
                    <button type="button" class="btn btn-sm btn-ghost" onclick="applyThemePreference('system')" style="font-size: 0.75rem;">
                        Detect OS Scheme
                    </button>
                </div>
            </div>

            <!-- Section 3: Danger Zone / Authentication Revocation -->
            <div class="stratum-card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <h2 style="font-size: 1.25rem; font-weight: 500;">Authentication &amp; Session</h2>
                </div>
                <p style="color: var(--text-secondary); font-size: 0.85rem; line-height: 1.45; margin-bottom: 1.25rem;">
                    Revoke active browser authorization token and return to authentication gate.
                </p>
                <div style="display: flex; justify-content: space-between; align-items: center; background: var(--panel-inset); padding: 1rem 1.25rem; border-radius: 4px; border: 1px solid var(--hairline);">
                    <div>
                        <div style="font-weight: 600; font-size: 0.9rem; color: var(--text-primary);">Sign Out of Backtrace</div>
                        <div style="font-size: 0.75rem; color: var(--text-tertiary);">Revokes session cookies immediately</div>
                    </div>
                    <form action="/auth/logout" method="GET" style="margin: 0;">
                        <button type="submit" class="btn btn-sm btn-danger">
                            Log Out
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <!-- Right Column: Plan & Billing & Quota -->
        <div>
            {plan_card_html}
        </div>

    </div>
    """

    extra_scripts = """
    <script>
        function applyThemePreference(theme) {
            if (theme === 'system') {
                const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
                const next = prefersDark ? 'dark' : 'light';
                document.documentElement.setAttribute('data-theme', next);
                localStorage.removeItem('backtrace-theme');
            } else {
                document.documentElement.setAttribute('data-theme', theme);
                localStorage.setItem('backtrace-theme', theme);
            }
            updateThemeCards();
        }

        function updateThemeCards() {
            const active = document.documentElement.getAttribute('data-theme') || 'dark';
            const darkCard = document.getElementById('theme-card-dark');
            const lightCard = document.getElementById('theme-card-light');
            const darkCheck = document.getElementById('theme-check-dark');
            const lightCheck = document.getElementById('theme-check-light');
            
            if (darkCard && lightCard) {
                if (active === 'dark') {
                    darkCard.style.borderColor = 'var(--brass)';
                    lightCard.style.borderColor = 'var(--hairline)';
                    if (darkCheck) darkCheck.style.display = 'inline-flex';
                    if (lightCheck) lightCheck.style.display = 'none';
                } else {
                    lightCard.style.borderColor = 'var(--brass)';
                    darkCard.style.borderColor = 'var(--hairline)';
                    if (lightCheck) lightCheck.style.display = 'inline-flex';
                    if (darkCheck) darkCheck.style.display = 'none';
                }
            }
        }
        document.addEventListener('DOMContentLoaded', updateThemeCards);
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
    success_html = f'<div style="background: rgba(45, 212, 191, 0.1); border: 1px solid var(--teal); color: var(--teal); padding: 0.75rem 1rem; border-radius: 4px; margin-bottom: 1.5rem; font-size: 0.875rem; font-weight: 500;">{sanitize_text(success)}</div>' if success else ""

    # Quota Perk Action State
    can_redeem_quota = not is_paid and points_balance >= 100

    if is_paid:
        perk_button = """
        <div style="display: flex; flex-direction: column; gap: 0.5rem;">
            <button type="button" class="btn btn-secondary" disabled style="opacity: 0.75; cursor: not-allowed; width: 100%; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 0.8125rem;">
                👑 Pro Active (Unlimited Analyses)
            </button>
            <span style="font-size: 0.75rem; color: var(--text-tertiary); text-align: center;">
                You are on Backtrace Pro with unlimited repository analyses. Extra quota redemption is not needed.
            </span>
        </div>
        """
    elif can_redeem_quota:
        perk_button = f"""
        <form method="POST" action="/rewards/redeem/quota">
            <button type="submit" id="btn-redeem-quota" class="btn btn-primary" style="width: 100%; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 0.8125rem; font-weight: 600; letter-spacing: 0.02em;">
                ⚡ Redeem +2 Repos (100 PTS)
            </button>
        </form>
        """
    else:
        perk_button = f"""
        <button type="button" class="btn btn-secondary" disabled style="opacity: 0.5; cursor: not-allowed; width: 100%; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 0.8125rem;">
            Need 100 PTS (Have {points_balance})
        </button>
        """

    # Render Badge Cards
    badges_html = ""
    for badge in badges:
        earned = badge.get("earned", False)
        earned_badge = """
        <span class="tag tag-brass" style="background: rgba(135, 90, 20, 0.2); color: var(--brass); border-color: var(--brass); font-size: 0.6875rem; font-weight: 600;">✓ UNLOCKED</span>
        """ if earned else """
        <span class="tag tag-ghost" style="color: var(--text-tertiary); font-size: 0.6875rem;">LOCKED</span>
        """
        card_border = "border-color: var(--brass); box-shadow: 0 0 12px rgba(135, 90, 20, 0.15);" if earned else "border-color: var(--hairline);"
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
                <h4 style="font-size: 1rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0.2rem;">{sanitize_text(badge.get('name', ''))}</h4>
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--brass); margin-bottom: 0.4rem; text-transform: uppercase;">{sanitize_text(badge.get('tagline', ''))}</div>
                <p style="font-size: 0.8125rem; color: var(--text-secondary); line-height: 1.4;">{sanitize_text(badge.get('description', ''))}</p>
            </div>
            <div>
                <div style="display: flex; justify-content: space-between; font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); margin-bottom: 0.25rem;">
                    <span>Progress</span>
                    <span>{progress_val} / {target_val}</span>
                </div>
                <div style="width: 100%; height: 4px; background: var(--panel-raised); border-radius: 2px; overflow: hidden;">
                    <div style="width: {pct}%; height: 100%; background: var(--brass); transition: width 300ms ease;"></div>
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
        leaderboard_rows += f"""
        <tr style="{row_bg} border-bottom: 1px solid var(--hairline-soft);">
            <td style="padding: 0.75rem 1rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.875rem; color: var(--brass);">{rank_badge}</td>
            <td style="padding: 0.75rem 1rem; display: flex; align-items: center; gap: 0.5rem;">
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.875rem; color: var(--text-primary);">@{sanitize_text(entry['username'])}</span>
                {'<span class="tag tag-brass" style="font-size: 0.625rem; padding: 0.1rem 0.35rem;">YOU</span>' if is_me else ''}
            </td>
            <td style="padding: 0.75rem 1rem; text-align: right; font-family: 'IBM Plex Mono', monospace; font-size: 0.875rem; font-weight: 600; color: #f59e0b;">
                {entry['points']} PTS
            </td>
        </tr>
        """

    # Render Ledger Rows
    ledger_rows = ""
    for e in ledger_entries[:20]:
        reason_label = sanitize_text(e.reason.replace("_", " ").title())
        pts = e.points_awarded
        pts_color = "#10b981" if pts > 0 else ("#ef4444" if pts < 0 else "var(--text-tertiary)")
        pts_prefix = "+" if pts > 0 else ""
        created_str = e.created_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(e.created_at, "strftime") else str(e.created_at)[:19]

        ledger_rows += f"""
        <tr style="border-bottom: 1px solid var(--hairline-soft);">
            <td style="padding: 0.65rem 0.85rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-tertiary);">{e.id}</td>
            <td style="padding: 0.65rem 0.85rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-secondary);">{created_str}</td>
            <td style="padding: 0.65rem 0.85rem; font-size: 0.8125rem; color: var(--text-primary);">{reason_label}</td>
            <td style="padding: 0.65rem 0.85rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-secondary); text-align: center;">Tier {e.milestone_tier if e.milestone_tier else '—'}</td>
            <td style="padding: 0.65rem 0.85rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.8125rem; font-weight: 600; color: {pts_color}; text-align: right;">
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
                <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--brass);">
                    Economy & Perks
                </span>
            </div>
            <h1 style="font-size: 2.25rem; margin-bottom: 0.5rem;">Points & Rewards Protocol</h1>
            <p style="color: var(--text-secondary); font-size: 0.9375rem; max-width: 760px;">
                Earn architectural points by solving progressive milestones. Redeem points for native software perks like monthly analysis quota, and unlock permanent badges.
            </p>
        </div>

        <!-- Metrics Overview Grid -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-bottom: 2.5rem;">
            <div class="card" style="padding: 1.25rem; border-color: var(--brass); background: var(--panel);">
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-tertiary); text-transform: uppercase; margin-bottom: 0.35rem;">Active Point Balance</div>
                <div style="font-family: 'Newsreader', Georgia, serif; font-size: 2.5rem; font-weight: 600; color: #f59e0b; line-height: 1.1; margin-bottom: 0.35rem;">
                    {points_balance} <span style="font-size: 1.125rem; font-family: 'IBM Plex Mono', monospace; font-weight: 500;">PTS</span>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-tertiary);">
                    🕒 Points valid for 180 days (rolling expiry)
                </div>
            </div>

            <div class="card" style="padding: 1.25rem; background: var(--panel);">
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-tertiary); text-transform: uppercase; margin-bottom: 0.35rem;">Lifetime Earned</div>
                <div style="font-family: 'Newsreader', Georgia, serif; font-size: 2.5rem; font-weight: 600; color: var(--text-primary); line-height: 1.1; margin-bottom: 0.35rem;">
                    {lifetime_points} <span style="font-size: 1.125rem; font-family: 'IBM Plex Mono', monospace; font-weight: 500;">PTS</span>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-tertiary);">
                    All-time cumulative points awarded
                </div>
            </div>

            <div class="card" style="padding: 1.25rem; background: var(--panel);">
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-tertiary); text-transform: uppercase; margin-bottom: 0.35rem;">Monthly Repo Quota</div>
                <div style="font-family: 'Newsreader', Georgia, serif; font-size: 2.5rem; font-weight: 600; color: var(--teal); line-height: 1.1; margin-bottom: 0.35rem;">
                    {'UNLIMITED' if is_paid else f'{monthly_usage} / {monthly_quota}'}
                </div>
                <div style="font-size: 0.75rem; color: var(--text-tertiary);">
                    {'Pro plan active' if is_paid else (f'+{quota_bonus} bonus slots active this month' if quota_bonus > 0 else 'Standard free allowance')}
                </div>
            </div>

            <div class="card" style="padding: 1.25rem; background: var(--panel);">
                <div style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: var(--text-tertiary); text-transform: uppercase; margin-bottom: 0.35rem;">Prestige Badges</div>
                <div style="font-family: 'Newsreader', Georgia, serif; font-size: 2.5rem; font-weight: 600; color: var(--brass); line-height: 1.1; margin-bottom: 0.35rem;">
                    {earned_badges_count} <span style="font-size: 1.125rem; font-family: 'IBM Plex Mono', monospace; font-weight: 500;">/ {total_badges}</span>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-tertiary);">
                    Architectural achievements unlocked
                </div>
            </div>
        </div>

        <!-- Bento Grid: Perks & Leaderboard -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2.5rem;">
            <!-- Perk Redemption Card -->
            <div class="card" style="padding: 1.5rem; background: var(--panel); display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;">
                        <span class="tag tag-brass" style="font-size: 0.6875rem;">SOFTWARE PERK</span>
                        <span style="font-family: 'IBM Plex Mono', monospace; font-size: 0.875rem; font-weight: 600; color: #f59e0b;">100 PTS</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.75rem;">
                        <span style="font-size: 2rem;">🚀</span>
                        <div>
                            <h3 style="font-size: 1.25rem; margin: 0;">+2 Monthly Analysis Quota</h3>
                            <span style="font-size: 0.8125rem; color: var(--text-secondary);">Instantly adds 2 additional repository analyses to this calendar month</span>
                        </div>
                    </div>
                    <p style="font-size: 0.875rem; color: var(--text-secondary); line-height: 1.5; margin-bottom: 1.25rem;">
                        Running low on monthly analyses? Spend 100 points to immediately boost your monthly limit. The bonus applies directly to Backtrace's real quota gate and renews your capacity.
                    </p>
                </div>
                {perk_button}
            </div>

            <!-- Leaderboard Card -->
            <div class="card" style="padding: 1.5rem; background: var(--panel);">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;">
                    <h3 style="font-size: 1.25rem; margin: 0;">Global Builder Leaderboard</h3>
                    <span class="tag tag-ghost" style="font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;">Your Rank: #{user_rank} ({user_points} PTS)</span>
                </div>
                <div style="overflow-x: auto; max-height: 220px; overflow-y: auto;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="border-bottom: 1px solid var(--hairline); font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); text-transform: uppercase;">
                                <th style="padding: 0.5rem 1rem; text-align: left;">Rank</th>
                                <th style="padding: 0.5rem 1rem; text-align: left;">Architect</th>
                                <th style="padding: 0.5rem 1rem; text-align: right;">Points</th>
                            </tr>
                        </thead>
                        <tbody>
                            {leaderboard_rows if leaderboard_rows else '<tr><td colspan="3" style="text-align: center; padding: 1.5rem; color: var(--text-tertiary);">No builders on leaderboard yet</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Badges Section -->
        <div style="margin-bottom: 2.5rem;">
            <div style="margin-bottom: 1rem;">
                <h2 style="font-size: 1.5rem; margin-bottom: 0.25rem;">Dossier Prestige Badges</h2>
                <p style="font-size: 0.875rem; color: var(--text-secondary);">Earn badges by demonstrating mastery, speed, and breadth across repository architectures.</p>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem;">
                {badges_html}
            </div>
        </div>

        <!-- Audit Ledger Section -->
        <div class="card" style="padding: 1.5rem; background: var(--panel);">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem;">
                <div>
                    <h3 style="font-size: 1.25rem; margin-bottom: 0.2rem;">Points Audit Ledger</h3>
                    <p style="font-size: 0.8125rem; color: var(--text-secondary); margin: 0;">Immutable, append-only transaction history</p>
                </div>
                <span class="tag tag-ghost" style="font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem;">Audit Trail Active</span>
            </div>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="border-bottom: 1px solid var(--hairline); font-family: 'IBM Plex Mono', monospace; font-size: 0.6875rem; color: var(--text-tertiary); text-transform: uppercase;">
                            <th style="padding: 0.65rem 0.85rem; text-align: left;">ID</th>
                            <th style="padding: 0.65rem 0.85rem; text-align: left;">Date & Time</th>
                            <th style="padding: 0.65rem 0.85rem; text-align: left;">Reason</th>
                            <th style="padding: 0.65rem 0.85rem; text-align: center;">Milestone</th>
                            <th style="padding: 0.65rem 0.85rem; text-align: right;">Points</th>
                        </tr>
                    </thead>
                    <tbody>
                        {ledger_rows if ledger_rows else '<tr><td colspan="5" style="text-align: center; padding: 2rem; color: var(--text-tertiary); font-style: italic;">No transactions in ledger yet. Solve milestones to earn points!</td></tr>'}
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


