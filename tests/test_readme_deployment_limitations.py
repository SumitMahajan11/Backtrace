from pathlib import Path
import pytest


def test_readme_contains_deployment_limitations_section():
    root = Path(__file__).resolve().parent.parent
    readme_path = root / "README.md"
    assert readme_path.exists(), "README.md must exist in root directory"

    content = readme_path.read_text(encoding="utf-8")
    assert "## ⚠️ Deployment Limitations" in content or "## Deployment Limitations" in content, (
        "README.md must have a 'Deployment Limitations' section"
    )

    # Validate the 3 required limitations
    assert "WSL" in content and "awake" in content, (
        "Deployment Limitations must document running only while WSL is awake"
    )
    assert "tunnel URL changes per restart" in content or "tunnel" in content.lower() and "restart" in content.lower(), (
        "Deployment Limitations must document ephemeral tunnel URL changes on restart"
    )
    assert "localhost only" in content.lower() or "localhost" in content.lower() and "oauth" in content.lower(), (
        "Deployment Limitations must document OAuth functionality on localhost"
    )
