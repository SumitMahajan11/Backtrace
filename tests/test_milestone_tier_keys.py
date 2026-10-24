"""
Tests verifying milestone keys are unique display numbers (1..N) while preserving tier_index for ordering.
Covers:
- Synthesis with milestones sharing tier_index generates unique 1-based display tiers.
- Report view renders exactly 4 milestone panes and 4 rail items when two milestones share tier_index.
- Attempts API accepts milestone_tier 1..4.
"""

import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import UserModel, AnalysisJobModel
from app.parser.schema import FileNode
from app.segmentation.schema import SegmentationResult
from app.sequence.narration_engine import NarrationEngine
from app.sequence.schema import (
    RepoConfidenceSummary,
    ScoredFileEntry,
    ScoredOrderingResult,
)
from app.security.auth import create_access_token
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.user_repository import UserRepository
from app.synthesis.engine import SynthesisEngine
from app.formatters.markdown_formatter import MarkdownReportFormatter
from app.formatters.quiz_formatter import QuizFormatter
from app.ui.components import report_view


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


def test_milestones_sharing_tier_index_render_4_panes_and_rail_items(test_db, client):
    """
    Part D requirement:
    A report with 4 milestones, two sharing tier_index (e.g. tier_index=0 for file1 and file2),
    renders exactly 4 milestone panes, 4 rail items, and the attempts API accepts 1..4.
    """
    SessionLocal, _ = test_db

    # Setup user and auth
    with SessionLocal() as session:
        user = UserRepository.upsert_github_user(
            session=session,
            github_id=9901,
            github_username="tier_tester",
            email="tier@example.com",
        )
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/example/multitier",
            repo_name="multitier",
            status="completed",
        )
        token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
        job_id = job.id

    client.cookies.set("access_token", token)

    from app.sequence.schema import BuildStepNarrative, SequenceNarrationResult

    steps = [
        BuildStepNarrative(
            step_number=1,
            title="Setup util1",
            tier_index=0,
            files=["app/util1.py"],
            domain_groups={"core": ["app/util1.py"]},
            dominant_domain="core",
            is_cyclic_cluster=False,
            dominant_confidence="high",
            confidence_breakdown={"high": 1},
            pedagogical_explanation="Start with util1.",
            track="core",
            track_label="Milestone",
            display_id="1",
        ),
        BuildStepNarrative(
            step_number=2,
            title="Setup util2",
            tier_index=0,
            files=["app/util2.py"],
            domain_groups={"core": ["app/util2.py"]},
            dominant_domain="core",
            is_cyclic_cluster=False,
            dominant_confidence="high",
            confidence_breakdown={"high": 1},
            pedagogical_explanation="Also implement util2 which shares the same tier.",
            track="core",
            track_label="Milestone",
            display_id="2",
        ),
        BuildStepNarrative(
            step_number=3,
            title="Core domain",
            tier_index=1,
            files=["app/core.py"],
            domain_groups={"core": ["app/core.py"]},
            dominant_domain="core",
            is_cyclic_cluster=False,
            dominant_confidence="high",
            confidence_breakdown={"high": 1},
            pedagogical_explanation="Now core domain logic.",
            track="core",
            track_label="Milestone",
            display_id="3",
        ),
        BuildStepNarrative(
            step_number=4,
            title="API endpoints",
            tier_index=2,
            files=["app/api.py"],
            domain_groups={"core": ["app/api.py"]},
            dominant_domain="core",
            is_cyclic_cluster=False,
            dominant_confidence="high",
            confidence_breakdown={"high": 1},
            pedagogical_explanation="Finally the API layer.",
            track="core",
            track_label="Milestone",
            display_id="4",
        ),
    ]

    narration = SequenceNarrationResult(
        overview="4 milestones overview",
        steps=steps,
        test_track=[],
        isolated_files_summary="",
        confidence_disclosure="High confidence calibration",
        source="template",
    )
    seg_res = SegmentationResult(domain_counts={"core": 4})
    parsed_files = [
        FileNode(path="app/util1.py", language="python", exports=["fn1"]),
        FileNode(path="app/util2.py", language="python", exports=["fn2"]),
        FileNode(path="app/core.py", language="python", exports=["CoreClass"]),
        FileNode(path="app/api.py", language="python", exports=["api"]),
    ]

    synth_report = SynthesisEngine().synthesize(
        repo_name="multitier",
        segmentation_result=seg_res,
        narration_result=narration,
        parsed_files=parsed_files,
    )

    # 1. Assert synthesis generated 4 milestones with 1-based unique display tiers 1..4
    assert len(synth_report.milestones) == 4
    tiers = [m.tier for m in synth_report.milestones]
    assert tiers == [1, 2, 3, 4], f"Expected 1-based unique tiers [1, 2, 3, 4], got {tiers}"

    # Assert tier_index is preserved for ordering
    tier_indices = [m.tier_index for m in synth_report.milestones]
    assert tier_indices == [0, 0, 1, 2], f"Expected tier_indices [0, 0, 1, 2], got {tier_indices}"

    markdown_report = MarkdownReportFormatter().format_report(synth_report)
    quiz_data = QuizFormatter().generate_quiz(synth_report)

    # Save report to job in DB
    with SessionLocal() as session:
        j = session.query(AnalysisJobModel).filter_by(id=job_id).first()
        j.markdown_output = markdown_report
        session.commit()

    # 2. Render report HTML
    html = report_view(
        job={"id": job_id, "repo_name": "multitier", "repo_url": "https://github.com/example/multitier"},
        raw_markdown=markdown_report,
        graph_data={"nodes": [], "edges": []},
        quiz_data=quiz_data,
    )

    # Assert exactly 4 milestone panes are rendered
    pane_ids = re.findall(r'<div class="milestone-pane[^"]*"\s+id="milestone-pane-(\d+)"', html)
    assert len(pane_ids) == 4, f"Expected 4 milestone panes, got {len(pane_ids)}: {pane_ids}"
    assert pane_ids == ["1", "2", "3", "4"]

    # Assert exactly 4 rail items are rendered
    rail_ids = re.findall(r'id="rail-item-(\d+)"', html)
    assert len(rail_ids) == 4, f"Expected 4 rail items, got {len(rail_ids)}: {rail_ids}"
    assert rail_ids == ["1", "2", "3", "4"]

    # 3. Assert Attempts API accepts tiers 1..4
    for tier in [1, 2, 3, 4]:
        resp = client.get(f"/api/attempts/{job_id}/{tier}")
        assert resp.status_code == 200, f"Attempts API failed for tier {tier}: {resp.text}"
        data = resp.json()
        assert data["attempt"]["milestone_tier"] == tier
