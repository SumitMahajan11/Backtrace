"""Tests for Pricing Page Limits matching Enforced Constants."""

from fastapi.testclient import TestClient
from app.main import app
from app.services.ingestion import get_max_repo_mb, MAX_REPO_FILE_LIMIT_V1
from app.ui.components import pricing_view


def test_pricing_page_numbers_equal_enforced_limits():
    """Verify the pricing page states the enforced repo size in MB and file cap."""
    enforced_mb = get_max_repo_mb()
    enforced_files = MAX_REPO_FILE_LIMIT_V1

    html = pricing_view()

    # Must state the enforced numbers
    assert f"{enforced_mb} MB" in html, f"Expected '{enforced_mb} MB' in pricing HTML"
    assert f"{enforced_files} supported files" in html, f"Expected '{enforced_files} supported files' in pricing HTML"
    assert "repository size cap" in html
    assert "supported files" in html
    assert f"{enforced_mb} MB" in html


def test_pricing_page_via_client():
    """Verify GET /pricing endpoint renders the enforced size cap and file cap."""
    client = TestClient(app)
    response = client.get("/pricing")
    assert response.status_code == 200
    assert "200 MB" in response.text
    assert "150 supported files" in response.text
    assert f"{get_max_repo_mb()} MB" in response.text
