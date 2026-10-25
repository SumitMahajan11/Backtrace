import pytest
from app.sequence.confidence_scoring import confidence_summary, ConfidenceSummary
from app.ui.components import report_view


def test_confidence_summary_10_files():
    """Given a list of 10 files (2 high, 3 medium, 5 low), assert high_pct 20, low_pct 50,

    and that the overview and milestone-table context use the same numbers.
    """
    files = [
        {"path": "f1.py", "confidence": "high"},
        {"path": "f2.py", "confidence": "high"},
        {"path": "f3.py", "confidence": "medium"},
        {"path": "f4.py", "confidence": "medium"},
        {"path": "f5.py", "confidence": "medium"},
        {"path": "f6.py", "confidence": "low"},
        {"path": "f7.py", "confidence": "low"},
        {"path": "f8.py", "confidence": "low"},
        {"path": "f9.py", "confidence": "low"},
        {"path": "f10.py", "confidence": "low"},
    ]

    summary = confidence_summary(files)

    # 1. Assert mathematical metrics
    assert summary.high_pct == 20
    assert summary.medium_pct == 30
    assert summary.low_pct == 50
    assert summary.overall_score == 20
    assert summary.high_count == 2
    assert summary.medium_count == 3
    assert summary.low_count == 5
    assert summary.total_files == 10
    assert summary.high_pct + summary.medium_pct + summary.low_pct == 100

    # 2. Test Overview component output in report_view
    raw_markdown = """# Test Repo
## 2. Build Order & Confidence Scoring
| **Total Scored Files** | **2** (20%) | **3** (30%) | **5** (50%) | **10** (100%) | - |
## 3. Step-by-Step Architectural Milestones
### Milestone 1: Core
"""
    job = {
        "id": 1,
        "repo_name": "TestRepo",
        "repo_url": "https://github.com/org/testrepo",
        "is_showcase": False,
    }
    graph_data = {
        "nodes": files,
        "edges": [],
        "confidence_summary": summary,
    }

    html_out = report_view(
        job=job,
        raw_markdown=raw_markdown,
        graph_data=graph_data,
        quiz_data=None,
    )

    # Card titled "Confidence" shows the high % (20%)
    assert '<div class="kpi-label">Confidence</div>' in html_out
    assert ">20%</div>" in html_out
    assert 'data-high-pct="20"' in html_out

    # A separate line shows "X files low confidence" using a count (5 files low confidence), not a percent
    assert "5 files low confidence" in html_out
    assert "50% files low confidence" not in html_out

    # Overview and milestone table context use the exact same numbers
    assert "(20%)" in html_out
    assert "(50%)" in html_out


def test_confidence_summary_edge_cases():
    """Test empty list and remainder distributions."""
    empty_sum = confidence_summary([])
    assert empty_sum.high_pct == 0
    assert empty_sum.medium_pct == 0
    assert empty_sum.low_pct == 0
    assert empty_sum.overall_score == 0

    # 3 files: 1 high, 1 med, 1 low -> 34%, 33%, 33% summing to 100
    three_files = ["high", "medium", "low"]
    three_sum = confidence_summary(three_files)
    assert three_sum.high_pct + three_sum.medium_pct + three_sum.low_pct == 100
    assert three_sum.overall_score == three_sum.high_pct
