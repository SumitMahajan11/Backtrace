"""Tests for 'Try it' mode stub generation and body protection (Prompt Part B & C).

Verifies that for a file with a 20-line function body:
1. The HTML sent in "Try it" mode does NOT contain any line from the function body.
2. The editor contains only imports, def/class signature, and a pass # TODO body.
3. For non-Python files, only the first 5 lines plus '// your turn' are present.
4. "Show solution" confirmation modal and unified buttons are rendered properly.
"""

import html as html_lib
import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.main import app
from app.models.db import Base, UserModel
from app.security.auth import create_access_token
from app.services.scaffold_generator import ScaffoldGenerator
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.user_repository import UserRepository


BODY_LINES = [f"step_{i}_result = (x * {i + 1}) + {i * 7}  # 20-line algorithm line {i}" for i in range(20)]
TWENTY_LINE_BODY = "\n".join("        " + line for line in BODY_LINES)

FIXTURE_20_LINE_SOURCE = f'''import math
from typing import List, Optional

class AlgorithmEngine:
    def execute(self, x: int) -> int:
{TWENTY_LINE_BODY}
        return step_19_result
'''


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal, engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db):
    TestingSessionLocal, _ = test_db

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def create_user(test_db):
    SessionLocal, _ = test_db

    def _create(github_id: int, username: str) -> UserModel:
        with SessionLocal() as session:
            user = UserRepository.upsert_github_user(
                session=session,
                github_id=github_id,
                github_username=username,
                email=f"{username}@example.com",
            )
            session.commit()
            session.refresh(user)
            return user

    return _create


def test_try_it_mode_html_does_not_contain_body_lines(client, create_user, test_db):
    """
    Part B: For a fixture file with a 20-line function body, the HTML sent
    in "Try it" mode must not contain any line from the body.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=50501, username="tryit_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    report_md = """# Architectural Report
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Algorithm
**[HIGH CONFIDENCE]** -- *Algorithm*
**Overview:** Algorithm module.
**Included Files:**
- `app/engine.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/example-org/try-it-demo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {
                        "id": "app/engine.py",
                        "path": "app/engine.py",
                        "tier": 0,
                        "source_code": FIXTURE_20_LINE_SOURCE,
                    },
                ],
                "edges": [],
            },
        )
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Extract the Try it mode workspace HTML
    workspace_match = re.search(r'<div id="workspace-guess-0"[^>]*>(.*?)(?=<div id="workspace-fill-0")', html, re.DOTALL)
    assert workspace_match is not None, "workspace-guess-0 not found in HTML"
    try_it_workspace_html = workspace_match.group(1)

    # Extract the code editor textarea content
    editor_match = re.search(r'<textarea id="code-editor-0"[^>]*>(.*?)</textarea>', html, re.DOTALL)
    assert editor_match is not None, "code-editor-0 textarea not found"
    editor_content = editor_match.group(1)
    editor_unescaped = html_lib.unescape(editor_content)

    # 1. Assert NO line from the 20-line body appears in the Try it workspace HTML or editor content
    for line in BODY_LINES:
        assert line not in try_it_workspace_html, f"Found body line leaked in Try it workspace: {line}"
        assert line not in editor_content, f"Found body line leaked in Try it editor: {line}"
        assert line not in editor_unescaped, f"Found body line leaked in unescaped editor: {line}"

    # 2. Assert imports and signature ARE preserved in the editor
    assert "import math" in editor_unescaped
    assert "class AlgorithmEngine:" in editor_unescaped
    assert "def execute(self, x: int) -> int:" in editor_unescaped
    assert "pass  # TODO" in editor_unescaped

    # 3. Assert unified button set: primary "Check answer", secondary "Hint", tertiary "Show solution"
    assert "Check answer" in try_it_workspace_html
    assert "Hint" in try_it_workspace_html
    assert "Show solution" in try_it_workspace_html
    assert "Reveal Implementation" not in try_it_workspace_html

    # 4. Assert modal asks: "Show the solution? This ends your attempt." with Cancel and Show
    assert "Show the solution? This ends your attempt." in try_it_workspace_html
    assert "Cancel" in try_it_workspace_html
    assert "Show" in try_it_workspace_html


def test_try_it_stub_generation_unit():
    """Unit tests for ScaffoldGenerator.generate_try_it_stub on Python and non-Python files."""
    # Python fixture with 20-line body
    stub = ScaffoldGenerator.generate_try_it_stub(FIXTURE_20_LINE_SOURCE, language="python", file_path="app/engine.py")
    assert "import math" in stub
    assert "from typing import List, Optional" in stub
    assert "class AlgorithmEngine:" in stub
    assert "def execute(self, x: int) -> int:" in stub
    assert "pass  # TODO" in stub
    for line in BODY_LINES:
        assert line not in stub

    # Non-Python file: only first 5 lines + // your turn
    js_code = "\n".join([f"const item_{i} = {i};" for i in range(12)])
    js_stub = ScaffoldGenerator.generate_try_it_stub(js_code, language="javascript", file_path="src/index.js")
    js_lines = js_stub.splitlines()
    assert len(js_lines) == 6
    assert js_lines[0] == "const item_0 = 0;"
    assert js_lines[4] == "const item_4 = 4;"
    assert js_lines[5] == "// your turn"
    assert "const item_5" not in js_stub
    assert "const item_11" not in js_stub
