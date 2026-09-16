"""HTML Component builder for Backtrace Frontend UI.

Provides semantic, beautifully styled, server-rendered HTML components
with dark mode styling, glassmorphism, responsive cards, and clean typography.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from app.models.db import UserModel
from app.ui.sanitizer import sanitize_text, render_safe_markdown


def page_shell(
    title: str,
    content: str,
    current_user: Optional[UserModel] = None,
    extra_head: str = "",
    extra_scripts: str = "",
) -> str:
    """Wrap content in a consistent, modern dark-mode application layout."""
    user_nav = ""
    if current_user:
        safe_username = sanitize_text(current_user.github_username or "User")
        avatar_html = (
            f'<img src="{sanitize_text(current_user.avatar_url)}" alt="Avatar" class="avatar" />'
            if current_user.avatar_url
            else ""
        )
        user_nav = f"""
        <div class="user-pill">
            {avatar_html}
            <span class="username">{safe_username}</span>
            <a href="/auth/logout" class="btn btn-sm btn-ghost">Logout</a>
        </div>
        """
    else:
        user_nav = '<a href="/login" class="btn btn-sm btn-primary">Sign In</a>'

    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{sanitize_text(title)} - Backtrace</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #0B0F19;
            --bg-surface: #111827;
            --bg-card: #1F2937;
            --bg-elevated: #374151;
            --border: #374151;
            --border-subtle: #2D3748;
            --text-primary: #F9FAFB;
            --text-secondary: #9CA3AF;
            --text-muted: #6B7280;
            --primary: #6366F1;
            --primary-hover: #4F46E5;
            --primary-glow: rgba(99, 102, 241, 0.25);
            --accent: #10B981;
            --accent-glow: rgba(16, 185, 129, 0.2);
            --warning: #F59E0B;
            --danger: #EF4444;
            --danger-bg: rgba(239, 68, 68, 0.1);
            --radius-sm: 6px;
            --radius-md: 10px;
            --radius-lg: 16px;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background-color: var(--bg-base);
            color: var(--text-primary);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            line-height: 1.6;
        }}
        a {{
            color: var(--primary);
            text-decoration: none;
            transition: color 0.15s ease;
        }}
        a:hover {{
            color: #818CF8;
        }}
        .header {{
            background: rgba(17, 24, 39, 0.85);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border-subtle);
            padding: 1rem 2rem;
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
            font-weight: 700;
            font-size: 1.25rem;
            letter-spacing: -0.025em;
            color: var(--text-primary);
        }}
        .brand-badge {{
            background: linear-gradient(135deg, var(--primary), #8B5CF6);
            color: white;
            font-size: 0.75rem;
            padding: 0.15rem 0.5rem;
            border-radius: var(--radius-sm);
            font-weight: 600;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
            padding: 2.5rem 1.5rem;
            width: 100%;
            flex: 1;
        }}
        .card {{
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-lg);
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border-subtle);
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.65rem 1.25rem;
            font-size: 0.95rem;
            font-weight: 600;
            border-radius: var(--radius-md);
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.2s ease;
            text-decoration: none;
        }}
        .btn-primary {{
            background: var(--primary);
            color: white;
            box-shadow: 0 0 15px var(--primary-glow);
        }}
        .btn-primary:hover {{
            background: var(--primary-hover);
            color: white;
        }}
        .btn-secondary {{
            background: var(--bg-card);
            color: var(--text-primary);
            border-color: var(--border);
        }}
        .btn-secondary:hover {{
            background: var(--bg-elevated);
        }}
        .btn-ghost {{
            background: transparent;
            color: var(--text-secondary);
        }}
        .btn-ghost:hover {{
            color: var(--text-primary);
            background: var(--bg-card);
        }}
        .btn-sm {{
            padding: 0.4rem 0.85rem;
            font-size: 0.85rem;
        }}
        .user-pill {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            padding: 0.35rem 0.75rem;
            border-radius: 9999px;
        }}
        .avatar {{
            width: 24px;
            height: 24px;
            border-radius: 50%;
            object-fit: cover;
        }}
        .username {{
            font-size: 0.875rem;
            font-weight: 600;
            color: var(--text-primary);
        }}
        .form-group {{
            margin-bottom: 1.5rem;
        }}
        .form-label {{
            display: block;
            margin-bottom: 0.5rem;
            font-size: 0.875rem;
            font-weight: 600;
            color: var(--text-secondary);
        }}
        .form-input {{
            width: 100%;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 0.75rem 1rem;
            color: var(--text-primary);
            font-size: 1rem;
            outline: none;
            transition: border-color 0.15s ease;
        }}
        .form-input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-glow);
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.65rem;
            border-radius: var(--radius-sm);
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .badge-free {{
            background: rgba(107, 114, 128, 0.2);
            color: #9CA3AF;
            border: 1px solid #4B5563;
        }}
        .badge-paid {{
            background: rgba(16, 185, 129, 0.15);
            color: #34D399;
            border: 1px solid #059669;
        }}
        .badge-completed {{
            background: rgba(16, 185, 129, 0.15);
            color: #34D399;
        }}
        .badge-running {{
            background: rgba(99, 102, 241, 0.15);
            color: #818CF8;
        }}
        .badge-failed {{
            background: rgba(239, 68, 68, 0.15);
            color: #F87171;
        }}
        .badge-pending {{
            background: rgba(245, 158, 11, 0.15);
            color: #FBBF24;
        }}
        .table-responsive {{
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th {{
            color: var(--text-secondary);
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 0.85rem 1rem;
            border-bottom: 1px solid var(--border-subtle);
        }}
        td {{
            padding: 1rem;
            border-bottom: 1px solid var(--border-subtle);
            font-size: 0.95rem;
        }}
        tr:hover td {{
            background: rgba(255, 255, 255, 0.02);
        }}
        .alert-error {{
            background: var(--danger-bg);
            border: 1px solid var(--danger);
            color: #FCA5A5;
            padding: 1rem;
            border-radius: var(--radius-md);
            margin-bottom: 1.5rem;
        }}
        /* Markdown / Report Styling */
        .markdown-body {{
            line-height: 1.8;
            color: #D1D5DB;
        }}
        .markdown-body h1, .markdown-body h2, .markdown-body h3 {{
            color: var(--text-primary);
            margin-top: 1.75rem;
            margin-bottom: 0.75rem;
            font-weight: 700;
        }}
        .markdown-body h1 {{ font-size: 1.75rem; border-bottom: 1px solid var(--border-subtle); padding-bottom: 0.5rem; }}
        .markdown-body h2 {{ font-size: 1.4rem; }}
        .markdown-body h3 {{ font-size: 1.15rem; }}
        .markdown-body p {{ margin-bottom: 1rem; }}
        .markdown-body ul, .markdown-body ol {{ margin-left: 1.5rem; margin-bottom: 1rem; }}
        .markdown-body code {{
            background: #111827;
            padding: 0.2rem 0.4rem;
            border-radius: 4px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
            color: #F472B6;
        }}
        .markdown-body pre {{
            background: #0D1117;
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-md);
            padding: 1.25rem;
            overflow-x: auto;
            margin-bottom: 1.5rem;
        }}
        .markdown-body pre code {{
            background: transparent;
            padding: 0;
            color: #E5E7EB;
        }}
        /* Graph Visualizer */
        .graph-container {{
            background: #0B0F19;
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-md);
            padding: 1.5rem;
            margin-top: 1.5rem;
        }}
        .graph-node {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 0.75rem 1rem;
            margin-bottom: 0.75rem;
        }}
        .graph-node-title {{
            font-weight: 600;
            color: var(--primary);
            font-family: 'JetBrains Mono', monospace;
        }}
        /* Quiz Styling */
        .quiz-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 1.25rem;
            margin-bottom: 1.25rem;
        }}
        .quiz-question {{
            font-weight: 600;
            margin-bottom: 1rem;
            color: var(--text-primary);
        }}
        .quiz-option {{
            display: block;
            padding: 0.65rem 1rem;
            background: var(--bg-surface);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-sm);
            margin-bottom: 0.5rem;
            cursor: pointer;
            transition: all 0.15s ease;
        }}
        .quiz-option:hover {{
            border-color: var(--primary);
            background: var(--bg-elevated);
        }}
        .footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            font-size: 0.85rem;
            border-top: 1px solid var(--border-subtle);
        }}
    </style>
    {extra_head}
</head>
<body>
    <header class="header">
        <a href="/dashboard" class="brand">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
            <span>Backtrace</span>
            <span class="brand-badge">Engine v1.0</span>
        </a>
        <div class="nav-right">
            {user_nav}
        </div>
    </header>
    <main class="container">
        {content}
    </main>
    <footer class="footer">
        Backtrace 11-Layer Reverse Code Intelligence &bull; Secured with GitHub OAuth &amp; Stripe
    </footer>
    {extra_scripts}
</body>
</html>
"""


def login_view(error: Optional[str] = None) -> str:
    """Render the Clean Login View with GitHub OAuth."""
    error_html = f'<div class="alert-error">{sanitize_text(error)}</div>' if error else ""
    content = f"""
    <div style="max-width: 440px; margin: 4rem auto 0 auto; text-align: center;">
        <div class="card" style="padding: 2.5rem 2rem;">
            <div style="margin-bottom: 2rem;">
                <div style="display: inline-flex; align-items: center; justify-content: center; width: 64px; height: 64px; background: rgba(99, 102, 241, 0.1); border-radius: 16px; margin-bottom: 1rem;">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#6366F1" stroke-width="2">
                        <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                        <polyline points="2 17 12 22 22 17"></polyline>
                        <polyline points="2 12 12 17 22 12"></polyline>
                    </svg>
                </div>
                <h1 style="font-size: 1.75rem; font-weight: 700; margin-bottom: 0.5rem; letter-spacing: -0.025em;">Welcome to Backtrace</h1>
                <p style="color: var(--text-secondary); font-size: 0.95rem;">Reverse-engineer codebase architecture into executable mental models.</p>
            </div>
            {error_html}
            <a href="/auth/github/login" class="btn btn-primary" style="width: 100%; justify-content: center; padding: 0.85rem; font-size: 1rem;">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"></path>
                </svg>
                Sign in with GitHub
            </a>
            <div style="margin-top: 1.5rem; font-size: 0.8rem; color: var(--text-muted);">
                By continuing you agree to Backtrace terms and automated repo analysis boundaries.
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
    """Render the User Dashboard with Repo submission form, Quota badge, and Job History."""
    tier = billing_status.get("tier", "free")
    used = billing_status.get("monthly_usage", 0)
    limit = billing_status.get("monthly_quota")
    limit_str = "Unlimited" if tier == "paid" else f"{used} / {limit}"
    badge_class = "badge-paid" if tier == "paid" else "badge-free"

    tier_action = ""
    if tier == "free":
        tier_action = '<a href="/api/billing/checkout" class="btn btn-sm btn-primary" style="margin-left: 0.75rem;">Upgrade to Pro</a>'
    else:
        tier_action = '<a href="/api/billing/portal" class="btn btn-sm btn-secondary" style="margin-left: 0.75rem;">Manage Subscription</a>'

    error_html = f'<div class="alert-error">{sanitize_text(error)}</div>' if error else ""

    # Build job history table
    rows_html = ""
    if not past_jobs:
        rows_html = """
        <tr>
            <td colspan="5" style="text-align: center; color: var(--text-muted); padding: 2.5rem;">
                No repository analyses yet. Submit a GitHub URL above to get started!
            </td>
        </tr>
        """
    else:
        for job in past_jobs:
            job_id = sanitize_text(str(job.id))
            repo_url = sanitize_text(job.repo_url)
            status = sanitize_text(job.status)
            created_at = sanitize_text(job.created_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(job.created_at, "strftime") else str(job.created_at))
            status_badge_class = f"badge-{status}" if status in ["completed", "running", "failed", "pending"] else "badge-free"
            
            action_btn = ""
            if status == "completed":
                action_btn = f'<a href="/report/{job_id}" class="btn btn-sm btn-primary">View Report</a>'
            elif status in ["running", "pending"]:
                action_btn = f'<a href="/progress/{job_id}" class="btn btn-sm btn-secondary">Track Progress</a>'
            else:
                action_btn = f'<span style="color: var(--danger); font-size: 0.85rem;">{sanitize_text(job.error_message or "Failed")}</span>'

            rows_html += f"""
            <tr>
                <td style="font-family: 'JetBrains Mono', monospace; font-size: 0.875rem;">{repo_url}</td>
                <td><span class="badge {status_badge_class}">{status}</span></td>
                <td style="color: var(--text-secondary); font-size: 0.85rem;">{created_at}</td>
                <td style="text-align: right;">{action_btn}</td>
            </tr>
            """

    content = f"""
    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 2rem;">
        <div>
            <h1 style="font-size: 2rem; font-weight: 700; letter-spacing: -0.025em; margin-bottom: 0.25rem;">Analysis Dashboard</h1>
            <p style="color: var(--text-secondary);">Manage repository intelligence jobs and inspect structural reports.</p>
        </div>
        <div style="display: flex; align-items: center;">
            <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); padding: 0.5rem 1rem; border-radius: var(--radius-md); display: flex; align-items: center; gap: 0.75rem;">
                <div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase;">Plan &amp; Quota</div>
                    <div style="font-weight: 600; font-size: 0.95rem;">
                        <span class="badge {badge_class}">{tier.upper()}</span>
                        <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.25rem;">({limit_str})</span>
                    </div>
                </div>
                {tier_action}
            </div>
        </div>
    </div>

    {error_html}

    <div class="card">
        <h2 style="font-size: 1.25rem; font-weight: 600; margin-bottom: 1.25rem;">Start New Codebase Analysis</h2>
        <form action="/analyses/submit" method="POST" style="display: flex; gap: 1rem; flex-wrap: wrap;">
            <div style="flex: 1; min-width: 300px;">
                <input 
                    type="url" 
                    name="repo_url" 
                    required 
                    class="form-input" 
                    placeholder="https://github.com/owner/repository" 
                    pattern="https://github.com/.+/.+"
                    title="Please enter a valid GitHub repository URL"
                />
            </div>
            <button type="submit" class="btn btn-primary">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="13 2 13 9 20 9"></polyline>
                    <path d="M13 2v7h7"></path>
                    <path d="M5 2h6l8 8v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"></path>
                </svg>
                Analyze Codebase
            </button>
        </form>
    </div>

    <div class="card">
        <div class="card-header">
            <h2 style="font-size: 1.25rem; font-weight: 600;">Your Analysis History</h2>
            <span style="color: var(--text-muted); font-size: 0.85rem;">{len(past_jobs)} total</span>
        </div>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Repository</th>
                        <th>Status</th>
                        <th>Date Submitted</th>
                        <th style="text-align: right;">Action</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
    """
    return page_shell("Dashboard", content, current_user=current_user)


def progress_view(job: Any, current_user: UserModel) -> str:
    """Render the Live Progress view with Server-Sent Events (SSE) updates."""
    job_id = sanitize_text(str(job.id))
    repo_url = sanitize_text(job.repo_url)
    
    stages = [
        ("stage_0", "0. Consent & Auth Gate"),
        ("stage_1", "1. Shallow Clone"),
        ("stage_2", "2. Discovery & Structure"),
        ("stage_3", "3. Static Analysis & AST"),
        ("stage_4", "4. Symbol Table"),
        ("stage_5", "5. Dependency Graph"),
        ("stage_6", "6. Architecture Mapping"),
        ("stage_7", "7. LLM Narrative & Synthesis"),
        ("stage_8", "8. Report & Quiz Generation"),
        ("stage_9", "9. Storage & Caching"),
        ("stage_10", "10. Telemetry & Metrics"),
    ]

    stages_html = ""
    for stage_key, stage_label in stages:
        stages_html += f"""
        <div class="stage-row" id="row-{stage_key}" style="display: flex; align-items: center; justify-content: space-between; padding: 0.85rem 1rem; border-radius: var(--radius-sm); margin-bottom: 0.5rem; background: var(--bg-surface); border: 1px solid var(--border-subtle); transition: all 0.2s ease;">
            <div style="display: flex; align-items: center; gap: 0.75rem;">
                <span class="stage-icon" id="icon-{stage_key}" style="display: inline-flex; width: 22px; height: 22px; align-items: center; justify-content: center; border-radius: 50%; background: var(--bg-card); font-size: 0.75rem; color: var(--text-muted);">○</span>
                <span style="font-weight: 500; font-size: 0.9rem;">{stage_label}</span>
            </div>
            <span class="stage-status" id="status-{stage_key}" style="font-size: 0.8rem; color: var(--text-muted);">Waiting</span>
        </div>
        """

    extra_scripts = f"""
    <script>
        const jobId = "{job_id}";
        const eventSource = new EventSource(`/api/analyses/${{jobId}}/events`);
        const statusHeader = document.getElementById("overall-status");
        const statusDesc = document.getElementById("status-desc");
        const progressBar = document.getElementById("progress-fill");

        eventSource.onmessage = function(event) {{
            try {{
                const data = JSON.parse(event.data);
                
                if (data.type === "progress") {{
                    const stageKey = data.stage;
                    const message = data.message || "Running...";
                    const pct = data.percentage || 0;
                    
                    progressBar.style.width = pct + "%";
                    statusDesc.textContent = message;

                    const row = document.getElementById("row-" + stageKey);
                    const icon = document.getElementById("icon-" + stageKey);
                    const statusText = document.getElementById("status-" + stageKey);

                    if (row && icon && statusText) {{
                        row.style.borderColor = "var(--primary)";
                        row.style.background = "rgba(99, 102, 241, 0.08)";
                        icon.textContent = "●";
                        icon.style.color = "var(--primary)";
                        statusText.textContent = "Processing";
                        statusText.style.color = "var(--primary)";
                    }}
                }} else if (data.type === "stage_complete") {{
                    const stageKey = data.stage;
                    const row = document.getElementById("row-" + stageKey);
                    const icon = document.getElementById("icon-" + stageKey);
                    const statusText = document.getElementById("status-" + stageKey);

                    if (row && icon && statusText) {{
                        row.style.borderColor = "var(--accent)";
                        row.style.background = "rgba(16, 185, 129, 0.05)";
                        icon.textContent = "✓";
                        icon.style.color = "var(--accent)";
                        statusText.textContent = "Completed";
                        statusText.style.color = "var(--accent)";
                    }}
                }} else if (data.type === "completed") {{
                    progressBar.style.width = "100%";
                    statusHeader.innerHTML = '<span class="badge badge-completed">Analysis Complete</span>';
                    statusDesc.textContent = "All 11 layers completed successfully. Redirecting to report...";
                    eventSource.close();
                    setTimeout(() => {{
                        window.location.href = `/report/${{jobId}}`;
                    }}, 1200);
                }} else if (data.type === "failed") {{
                    statusHeader.innerHTML = '<span class="badge badge-failed">Analysis Failed</span>';
                    statusDesc.textContent = data.message || "An error occurred during analysis.";
                    eventSource.close();
                }}
            }} catch (err) {{
                console.error("SSE parse error", err);
            }}
        }};

        eventSource.onerror = function() {{
            statusDesc.textContent = "Connection lost or completed. Checking status...";
        }};
    </script>
    """

    content = f"""
    <div style="max-width: 760px; margin: 0 auto;">
        <div style="margin-bottom: 1.5rem;">
            <a href="/dashboard" style="display: inline-flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; color: var(--text-secondary); margin-bottom: 1rem;">
                &larr; Back to Dashboard
            </a>
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h1 style="font-size: 1.75rem; font-weight: 700; letter-spacing: -0.025em;">Pipeline Execution</h1>
                <div id="overall-status"><span class="badge badge-running">Running</span></div>
            </div>
            <p style="color: var(--text-secondary); font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; margin-top: 0.25rem;">
                {repo_url}
            </p>
        </div>

        <div class="card" style="padding: 1.5rem;">
            <div style="margin-bottom: 1rem; display: flex; justify-content: space-between; align-items: center;">
                <span id="status-desc" style="font-weight: 500; color: var(--text-primary); font-size: 0.95rem;">Initializing 11-Layer Engine...</span>
            </div>
            <div style="width: 100%; height: 8px; background: var(--bg-card); border-radius: 9999px; overflow: hidden; margin-bottom: 1.5rem;">
                <div id="progress-fill" style="width: 5%; height: 100%; background: linear-gradient(90deg, var(--primary), var(--accent)); transition: width 0.3s ease;"></div>
            </div>

            <div style="margin-top: 1.5rem;">
                <h3 style="font-size: 0.9rem; font-weight: 600; text-transform: uppercase; color: var(--text-muted); margin-bottom: 0.75rem; letter-spacing: 0.05em;">
                    Engine Stage Breakdown
                </h3>
                {stages_html}
            </div>
        </div>
    </div>
    """
    return page_shell("Analysis Progress", content, current_user=current_user, extra_scripts=extra_scripts)


def report_view(
    job: Any,
    raw_markdown: str,
    graph_data: Optional[Dict[str, Any]],
    quiz_data: Optional[Dict[str, Any]],
    current_user: UserModel,
) -> str:
    """Render the Full Report View: Markdown output, Dependency Graph, and Quiz."""
    job_id = sanitize_text(str(job.id))
    repo_url = sanitize_text(job.repo_url)

    # 1. Render sanitized Markdown
    safe_markdown_html = render_safe_markdown(raw_markdown)

    # 2. Render Graph View
    graph_html = ""
    if graph_data and "nodes" in graph_data:
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
        nodes_rendered = ""
        for n in nodes[:25]:  # show top nodes
            node_id = sanitize_text(n.get("id", ""))
            node_type = sanitize_text(n.get("type", "module"))
            node_deps = sanitize_text(str(n.get("dependencies", [])))
            nodes_rendered += f"""
            <div class="graph-node">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span class="graph-node-title">{node_id}</span>
                    <span class="badge badge-free" style="font-size: 0.7rem;">{node_type}</span>
                </div>
                <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.25rem;">
                    Dependencies: {node_deps}
                </div>
            </div>
            """
        graph_html = f"""
        <div class="card">
            <h2 style="font-size: 1.25rem; font-weight: 600; margin-bottom: 0.5rem;">Architecture &amp; Dependency Graph</h2>
            <p style="color: var(--text-secondary); font-size: 0.875rem; margin-bottom: 1rem;">
                Extracted from Layer 5 (graph_formatter.py) &bull; {len(nodes)} modules &bull; {len(edges)} connections
            </p>
            <div class="graph-container">
                {nodes_rendered}
            </div>
        </div>
        """

    # 3. Render Quiz View
    quiz_html = ""
    if quiz_data and "questions" in quiz_data:
        questions = quiz_data.get("questions", [])
        quiz_items_rendered = ""
        for i, q in enumerate(questions, 1):
            q_text = sanitize_text(q.get("question", ""))
            options = q.get("options", [])
            options_rendered = ""
            for opt in options:
                safe_opt = sanitize_text(opt)
                options_rendered += f"""
                <label class="quiz-option">
                    <input type="radio" name="q_{i}" style="margin-right: 0.5rem;">
                    {safe_opt}
                </label>
                """
            quiz_items_rendered += f"""
            <div class="quiz-card">
                <div class="quiz-question">{i}. {q_text}</div>
                <div>{options_rendered}</div>
            </div>
            """
        quiz_html = f"""
        <div class="card">
            <h2 style="font-size: 1.25rem; font-weight: 600; margin-bottom: 0.5rem;">Codebase Mastery Quiz</h2>
            <p style="color: var(--text-secondary); font-size: 0.875rem; margin-bottom: 1rem;">
                Generated from Layer 8 (quiz_formatter.py) to test comprehension of key architectural components.
            </p>
            {quiz_items_rendered}
        </div>
        """

    content = f"""
    <div style="max-width: 900px; margin: 0 auto;">
        <div style="margin-bottom: 1.5rem; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
            <div>
                <a href="/dashboard" style="display: inline-flex; align-items: center; gap: 0.5rem; font-size: 0.875rem; color: var(--text-secondary); margin-bottom: 0.5rem;">
                    &larr; Back to Dashboard
                </a>
                <h1 style="font-size: 2rem; font-weight: 700; letter-spacing: -0.025em;">Codebase Intelligence Report</h1>
                <p style="color: var(--text-secondary); font-family: 'JetBrains Mono', monospace; font-size: 0.9rem;">
                    {repo_url}
                </p>
            </div>
            <div style="display: flex; gap: 0.75rem;">
                <button onclick="window.print()" class="btn btn-secondary btn-sm">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="6 9 6 2 18 2 18 9"></polyline>
                        <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path>
                        <rect x="6" y="14" width="12" height="8"></rect>
                    </svg>
                    Print / Export
                </button>
            </div>
        </div>

        <div class="card">
            <div class="markdown-body">
                {safe_markdown_html}
            </div>
        </div>

        {graph_html}
        {quiz_html}
    </div>
    """
    return page_shell("Report", content, current_user=current_user)
