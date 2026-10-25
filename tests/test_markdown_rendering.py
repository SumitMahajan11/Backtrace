"""Tests for Safe User Markdown Rendering and XSS Sanitization."""

import html
import re

import pytest

from app.models.db import AnalysisJobModel, UserModel
from app.ui.components import report_view
from app.ui.sanitizer import render_user_markdown


def strip_html_tags_to_visible_text(html_content: str) -> str:
    """Simulates browser visible text by stripping tags and decoding HTML entities once."""
    tags_stripped = re.sub(r"<[^>]+>", "", html_content)
    return html.unescape(tags_stripped)


def test_tom_and_jerry_rendering():
    """Input 'Tom & Jerry' renders visible text 'Tom & Jerry' (HTML source has &amp; exactly once, never &amp;amp;)."""
    raw_input = "Tom & Jerry"
    html_out = render_user_markdown(raw_input)
    assert html_out.count("&amp;") == 1
    assert "&amp;amp;" not in html_out
    visible_text = strip_html_tags_to_visible_text(html_out)
    assert "Tom & Jerry" in visible_text


def test_role_markdown_rendering():
    """Input '**Role:** dev' renders <strong>Role:</strong> and the visible text has no '**'."""
    raw_input = "**Role:** dev"
    html_out = render_user_markdown(raw_input)
    assert "<strong>Role:</strong>" in html_out
    visible_text = strip_html_tags_to_visible_text(html_out)
    assert "**" not in visible_text
    assert "Role: dev" in visible_text


def test_backticks_code_rendering():
    """Input 'use `foo()`' renders <code>foo()</code> and the visible text has no backtick."""
    raw_input = "use `foo()`"
    html_out = render_user_markdown(raw_input)
    assert "<code>foo()</code>" in html_out
    visible_text = strip_html_tags_to_visible_text(html_out)
    assert "`" not in visible_text
    assert "use foo()" in visible_text


def test_script_tag_xss_stripped():
    """Input '<script>alert(1)</script>' has no <script> in output."""
    raw_input = "<script>alert(1)</script>"
    html_out = render_user_markdown(raw_input)
    assert "<script" not in html_out
    assert "</script>" not in html_out


def test_img_onerror_xss_stripped():
    """Input '<img src=x onerror=alert(1)>' has no onerror in output."""
    raw_input = '<img src=x onerror=alert(1)>'
    html_out = render_user_markdown(raw_input)
    assert "onerror" not in html_out
    assert "<img" not in html_out


def test_javascript_url_xss_stripped():
    """Input '[x](javascript:alert(1))' has no javascript: in output."""
    raw_input = "[x](javascript:alert(1))"
    html_out = render_user_markdown(raw_input)
    assert "javascript:" not in html_out


def test_full_milestone_card_and_quiz_rendered_through_real_templates():
    """Render a full milestone card and quiz question through the real templates and assert the visible text (strip tags) contains none of: '&amp;', '**', '`'."""
    user = UserModel(
        id=42,
        github_id=42042,
        github_username="test_user",
        email="test@example.com",
    )

    job = AnalysisJobModel(
        id="job_render_test",
        user_id=42,
        repo_url="https://github.com/org/render-test-repo",
        repo_name="render-test-repo",
        status="completed",
    )

    raw_markdown = """# Architecture Synthesis Report: `render-test-repo`

## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Foundation
**[HIGH CONFIDENCE]** -- *Tom & Jerry Core Architecture*
**Overview:** **Role:** dev managing `auth_service` and `db_pool` primitives.
**Domain Composition:** 100% Core
**Included Files:**
- `app/core.py`
"""

    quiz_data = {
        "questions": [
            {
                "question": "What is the role of `core.py` in Tom & Jerry architecture?",
                "options": ["Provides `auth_service`", "Handles `db_pool`"],
                "explanation": "See `app/core.py` for **Role:** definition.",
                "correct_index": 0,
                "tier": 0,
            }
        ]
    }

    graph_data = {
        "nodes": [
            {
                "id": "app/core.py",
                "path": "app/core.py",
                "tier": 0,
                "symbols": [{"name": "init_core", "kind": "function", "args": []}],
            }
        ],
        "edges": [],
    }

    rendered_html = report_view(
        job=job,
        raw_markdown=raw_markdown,
        graph_data=graph_data,
        quiz_data=quiz_data,
        current_user=user,
    )

    # 1. HTML source verification for milestones and quiz
    assert "id=\"workspace-guess-0\"" in rendered_html
    assert "id=\"section-quiz\"" in rendered_html
    assert "<strong>Role:</strong>" in rendered_html
    assert "<code>auth_service</code>" in rendered_html
    assert "<code>core.py</code>" in rendered_html
    assert "&amp;amp;" not in rendered_html

    # 2. Extract milestone card section and quiz section
    milestone_start = rendered_html.find('id="section-milestones"')
    milestone_end = rendered_html.find('id="section-quiz"')
    assert milestone_start != -1 and milestone_end != -1

    milestone_html = rendered_html[milestone_start:milestone_end]
    quiz_html = rendered_html[milestone_end:]

    # Visible text of milestone card (task instructions + structured brief)
    milestone_visible = strip_html_tags_to_visible_text(milestone_html)
    assert "Tom & Jerry Core Architecture" in milestone_visible
    assert "app/core.py" in milestone_visible
    assert "&amp;" not in milestone_visible
    assert "**" not in milestone_visible
    assert "`" not in milestone_visible

    # Visible text of quiz questions, options, explanation
    quiz_visible = strip_html_tags_to_visible_text(quiz_html)
    assert "What is the role of core.py in Tom & Jerry architecture?" in quiz_visible
    assert "Provides auth_service" in quiz_visible
    assert "See app/core.py for Role: definition." in quiz_visible
    assert "&amp;" not in quiz_visible
    assert "**" not in quiz_visible
    assert "`" not in quiz_visible
