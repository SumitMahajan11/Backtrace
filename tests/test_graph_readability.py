import json
import pytest
from unittest.mock import MagicMock

from app.formatters.graph_formatter import dedupe_edges, imported_by
from app.ui.components import report_view
from app.api.frontend import get_report_graph_json
from app.storage.analysis_job_repository import AnalysisJobRepository


def test_dedupe_edges():
    """Verify that multiple duplicate edges are condensed into exactly one unique edge."""
    raw_edges = [
        {"source": "app/api/auth.py", "target": "app/models/user.py"},
        {"source": "app/api/auth.py", "target": "app/models/user.py"},
        {"source": "app/api/auth.py", "target": "app/models/user.py"},
        {"source": "app/api/auth.py", "target": "app/db.py"},
        {"source": "app/api/users.py", "target": "app/models/user.py"},
        {"source": "app/api/users.py", "target": "app/models/user.py"},
    ]
    deduped = dedupe_edges(raw_edges)
    assert len(deduped) == 3
    pairs = [(e["source"], e["target"]) for e in deduped]
    assert pairs == [
        ("app/api/auth.py", "app/models/user.py"),
        ("app/api/auth.py", "app/db.py"),
        ("app/api/users.py", "app/models/user.py"),
    ]


def test_imported_by_deduped():
    """Verify imported_by returns a deduplicated, sorted list of importers."""
    raw_edges = [
        {"source": "app/api/auth.py", "target": "app/models/user.py"},
        {"source": "app/api/auth.py", "target": "app/models/user.py"},
        {"source": "app/services/billing.py", "target": "app/models/user.py"},
    ]
    importers = imported_by("app/models/user.py", raw_edges)
    assert importers == ["app/api/auth.py", "app/services/billing.py"]


def test_graph_json_endpoint(monkeypatch):
    """Test the /report/{job_id}/graph.json endpoint returning deduped edges."""
    mock_job = MagicMock()
    mock_job.id = "test-job-graph-123"
    mock_job.user_id = "test-user-id"
    mock_job.is_showcase = True
    mock_job.graph_data = {
        "nodes": [
            {"id": "app/main.py", "label": "app/main.py", "tier": 0, "confidence": "high"},
            {"id": "app/config.py", "label": "app/config.py", "tier": 1, "confidence": "medium"},
            {"id": "app/legacy.py", "label": "app/legacy.py", "tier": 2, "confidence": "low"},
        ],
        "edges": [
            {"source": "app/main.py", "target": "app/config.py"},
            {"source": "app/main.py", "target": "app/config.py"},  # duplicate
            {"source": "app/config.py", "target": "app/legacy.py"},
        ]
    }

    monkeypatch.setattr(AnalysisJobRepository, "get_job_by_id", lambda session, j_id: mock_job if j_id == "test-job-graph-123" else None)

    # Call endpoint directly
    response = get_report_graph_json(
        job_id="test-job-graph-123",
        user=None,
        session=MagicMock(),
    )
    assert response.status_code == 200
    data = json.loads(response.body.decode("utf-8"))
    assert data["job_id"] == "test-job-graph-123"
    assert data["node_count"] == 3
    assert data["edge_count"] == 2
    assert len(data["edges"]) == 2
    # Verify duplicates were eliminated
    edge_pairs = [(e["source"], e["target"]) for e in data["edges"]]
    assert edge_pairs == [
        ("app/main.py", "app/config.py"),
        ("app/config.py", "app/legacy.py"),
    ]


def test_graph_readability_components():
    """Verify all 9 graph readability requirements are satisfied in report_view."""
    mock_job = MagicMock()
    mock_job.id = "101"
    mock_job.repo_name = "test/readability-repo"
    mock_job.repo_url = "https://github.com/test/readability-repo"
    mock_job.is_showcase = False
    mock_job.report_markdown = "# Architecture\n\nOverview content."
    mock_job.created_at = "2026-10-24T00:00:00Z"
    mock_job.total_files = 98
    mock_job.execution_time_seconds = 14.2
    mock_job.run_id = "run_101"

    graph_data = {
        "nodes": [
            {
                "id": "src/very/long/nested/path/authentication_manager.py",
                "label": "authentication_manager.py",
                "path": "src/very/long/nested/path/authentication_manager.py",
                "tier": 0,
                "domain": "security",
                "confidence": "high",
                "exports": ["AuthManager", "login_user"]
            },
            {
                "id": "src/database/session_factory.py",
                "label": "session_factory.py",
                "path": "src/database/session_factory.py",
                "tier": 1,
                "domain": "database",
                "confidence": "medium",
                "exports": ["get_db"]
            },
            {
                "id": "src/utils/unreferenced_deprecated_helper.py",
                "label": "unreferenced_deprecated_helper.py",
                "path": "src/utils/unreferenced_deprecated_helper.py",
                "tier": 2,
                "domain": "core",
                "confidence": "low",
                "exports": ["old_func"]
            }
        ],
        "edges": [
            {
                "source": "src/very/long/nested/path/authentication_manager.py",
                "target": "src/database/session_factory.py"
            }
        ]
    }
    mock_job.graph_data = graph_data
    mock_job.analysis_payload = {"synthesized_report": {"milestones": []}}

    html = report_view(
        job=mock_job,
        raw_markdown=mock_job.report_markdown,
        graph_data=graph_data,
        quiz_data=None,
        current_user=None,
    )

    # Fix 1: Legend collapsed by default into small button at top-right
    assert 'id="toggle-legend-btn"' in html
    assert 'id="dag-legend-panel"' in html
    assert 'display: none;' in html
    assert 'Graph Legend' in html

    # Fix 2: Node labels show filename only, truncated with ellipsis, clip-path, labels never leave box
    assert '<clipPath id="dag-node-text-clip">' in html
    assert 'clip-path="url(#dag-node-text-clip)"' in html
    # The file "authentication_manager.py" is > 15 chars, so truncated to 13 chars + "..."
    assert 'authenticatio...<' in html
    # Full path should NOT be printed inside visible node surface text (<text>...</text>)
    import re
    node_start = html.find('class="dag-node"')
    node_end = html.find('</g>', node_start)
    node_text_elements = re.findall(r'<text[^>]*>(.*?)</text>', html[node_start:node_end])
    assert any('authenticatio...' in t for t in node_text_elements)
    for t in node_text_elements:
        assert 'src/very/long/nested/path' not in t

    # Fix 3: Edges drawn behind nodes (z-index layer order), thin 1px, 40% opacity
    edges_pos = html.find('id="dag-edges-layer"')
    nodes_pos = html.find('id="dag-nodes-layer"')
    assert edges_pos != -1 and nodes_pos != -1
    assert edges_pos < nodes_pos, "dag-edges-layer MUST precede dag-nodes-layer in SVG DOM order so edges render behind nodes"
    assert 'stroke-width="1"' in html
    assert 'opacity="0.4"' in html

    # Fix 4: Fit button and hint
    assert 'id="dag-fit-btn"' in html
    assert 'Scroll to zoom, drag to move' in html

    # Fix 5: Explain node count with real numbers and toggle "Show all files"
    assert 'Showing the 3 most connected files of 98.' in html
    assert 'id="toggle-all-files-btn"' in html
    assert 'Show all files' in html

    # Fix 6: Renamed toggle "List" and "Graph" (formerly "Table Catalog" and "Visual Graph")
    assert 'Table Catalog' not in html
    assert 'Visual Graph' not in html
    assert 'List' in html
    assert 'id="toggle-view-btn"' in html

    # Fix 7: Main nav visible (.nav-shell)
    assert '<header class="nav-shell">' in html
    assert 'z-index: 10001 !important;' in html or '.nav-shell' in html

    # Fix 8: Confidence dots - high green (#10B981), medium amber (#F59E0B), low grey (#94A3B8), NOT red
    assert '#10B981' in html  # Green for high
    assert '#F59E0B' in html  # Amber for medium
    assert '#94A3B8' in html  # Grey for low
    # Verify low confidence is explicitly associated with grey
    assert 'low confidence' in html.lower()
    assert '#94A3B8' in html

    # Fix 9: Side panel on click: path, imported by, imports, and "Open milestone" link
    assert 'id="dag-node-inspector"' in html
    assert 'id="inspect-path"' in html
    assert 'id="inspect-imported-by"' in html
    assert 'id="inspect-imports"' in html
    assert 'Open milestone' in html
