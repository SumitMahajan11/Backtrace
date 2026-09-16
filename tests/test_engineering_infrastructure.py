"""Engineering Infrastructure Verification Suite (Stage 6 Section 6.4).

Verifies:
1. Dynamic health check endpoint (returns real status and 200/503 based on DB/storage state).
2. Structured logging correlated by a single run_id across all layers.
3. Pipeline monitoring metrics tracking layer duration and failure rates.
4. CI/CD workflow configuration for automated headless testing.
"""

import io
import json
import logging
from pathlib import Path
import pytest
from sqlalchemy import create_engine

from app.api.health import inspect_health
from app.orchestration.pipeline import PipelineOrchestrator
from app.services.metrics import PipelineMetricsCollector
from app.utils.logging import StructuredJsonFormatter, get_logger, set_run_id


def test_health_check_endpoint_healthy_state():
    """
    Acceptance Criteria: Health check returns dynamic real status (not hardcoded).
    When dependencies are connected, returns status='healthy' and code=200.
    """
    payload, status_code = inspect_health()

    assert status_code == 200
    assert payload["status"] == "healthy"
    assert "checks" in payload
    assert payload["checks"]["database"]["status"] == "healthy"
    assert payload["checks"]["database"]["latency_ms"] >= 0.0
    assert payload["checks"]["storage_cache"]["status"] == "healthy"
    assert payload["checks"]["pipeline_orchestrator"]["status"] == "healthy"
    assert payload["checks"]["pipeline_orchestrator"]["registered_parsers"] >= 8


def test_health_check_endpoint_unhealthy_state():
    """
    Acceptance Criteria: Health check returns real dynamic failure (status='unhealthy' and 503)
    when database is unreachable, proving it is not a hardcoded 200.
    """
    # Create invalid engine pointing to an unopenable/corrupted target
    bad_engine = create_engine("sqlite:////non_existent_folder_xyz/bad.db")

    payload, status_code = inspect_health(target_engine=bad_engine)

    assert status_code == 503
    assert payload["status"] == "unhealthy"
    assert payload["checks"]["database"]["status"] == "unhealthy"
    assert "error" in payload["checks"]["database"]


def test_structured_logging_with_correlated_run_id():
    """
    Acceptance Criteria: A single analysis run's logs can be grep'd by run_id
    across all layers end to end.
    """
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(StructuredJsonFormatter())

    root_logger = logging.getLogger("reverse")
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    orchestrator = PipelineOrchestrator()
    target_run_id = "corr-test-uuid-9999"

    file_paths = ["src/main.py", "src/helper.py"]
    file_contents = {
        "src/main.py": "from src.helper import help_func\n",
        "src/helper.py": "def help_func(): pass\n",
    }

    result = orchestrator.run_pipeline(
        repo_name="acme/logging-test",
        file_paths=file_paths,
        file_contents=file_contents,
        enable_rag=False,
        run_id=target_run_id,
    )

    assert result.success is True
    assert result.run_id == target_run_id

    # Flush log output and verify
    handler.flush()
    log_output = log_stream.getvalue().strip()
    root_logger.removeHandler(handler)

    lines = [line for line in log_output.split("\n") if line.strip()]
    assert len(lines) > 0

    matching_run_id_count = 0
    layers_observed = set()

    for line in lines:
        try:
            record = json.loads(line)
            if record.get("run_id") == target_run_id:
                matching_run_id_count += 1
                if "layer" in record:
                    layers_observed.add(record["layer"])
        except json.JSONDecodeError:
            pass

    # Confirm that multiple stages/layers emitted logs with this exact run_id
    assert matching_run_id_count >= 5
    assert "ingestion" in layers_observed or "layer_1_ingestion" in layers_observed
    assert "parsing" in layers_observed or "layer_2_parsing" in layers_observed
    assert "complete" in layers_observed


def test_metrics_collector_layer_timings_and_failure_rates():
    """
    Acceptance Criteria: Monitoring hooks emit metrics (duration per layer, failure rate).
    """
    collector = PipelineMetricsCollector()

    # Record 3 successful layers and 1 run
    collector.record_layer_metric("layer_1_ingestion", 120.5, status="success", run_id="run-1")
    collector.record_layer_metric("layer_2_parsing", 250.0, status="success", run_id="run-1")
    collector.record_pipeline_run(run_id="run-1", success=True, total_duration_seconds=0.37)

    # Record 1 failed pipeline run
    collector.record_pipeline_run(run_id="run-2", success=False, total_duration_seconds=0.15)

    stats = collector.get_summary_statistics()

    assert stats["total_pipeline_runs"] == 2
    assert stats["failed_pipeline_runs"] == 1
    assert stats["failure_rate_pct"] == 50.0
    assert "layer_1_ingestion" in stats["average_layer_latencies_ms"]
    assert stats["average_layer_latencies_ms"]["layer_1_ingestion"] == 120.5


def test_ci_cd_workflow_syntax():
    """
    Acceptance Criteria: CI/CD workflow file exists with proper triggers and headless pytest step.
    """
    workflow_path = Path(".github/workflows/ci.yml")
    assert workflow_path.exists()
    content = workflow_path.read_text(encoding="utf-8")

    assert "pull_request:" in content
    assert "pytest" in content
    assert "ubuntu-latest" in content
    assert "windows-latest" in content
