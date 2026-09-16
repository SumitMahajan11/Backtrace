"""Pipeline Monitoring and Metrics Hooks (Layer 11 Infrastructure).

Emits structured pipeline performance metrics (per-layer latency, failure rate, file volume)
and maintains running aggregate statistics for monitoring scrapers or APMs.
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.logging import get_run_id

logger = logging.getLogger("reverse.metrics")


@dataclass
class LayerMetricEvent:
    """Individual metric data point for an executed pipeline layer."""
    run_id: str
    layer_name: str
    duration_ms: float
    status: str  # "success" | "failed"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = field(default_factory=dict)


class PipelineMetricsCollector:
    """Collects and aggregates per-layer and pipeline-wide execution metrics."""

    def __init__(self):
        self._history: List[LayerMetricEvent] = []
        self._total_runs: int = 0
        self._failed_runs: int = 0
        self._layer_durations_ms: Dict[str, List[float]] = defaultdict(list)

    def record_layer_metric(
        self,
        layer_name: str,
        duration_ms: float,
        status: str = "success",
        run_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> LayerMetricEvent:
        """Records a layer completion event, updates aggregates, and emits structured log."""
        active_run_id = run_id or get_run_id() or "none"
        event = LayerMetricEvent(
            run_id=active_run_id,
            layer_name=layer_name,
            duration_ms=round(duration_ms, 2),
            status=status,
            details=details or {},
        )
        self._history.append(event)
        self._layer_durations_ms[layer_name].append(duration_ms)

        # Structured log emission for log-based metric scrapers (DataDog, CloudWatch, Prometheus)
        metric_log = {
            "metric_type": "pipeline_layer_duration",
            "run_id": active_run_id,
            "layer": layer_name,
            "duration_ms": round(duration_ms, 2),
            "status": status,
        }
        logger.info(json.dumps(metric_log))
        return event

    def record_pipeline_run(self, run_id: str, success: bool, total_duration_seconds: float) -> None:
        """Records an overall pipeline run outcome."""
        self._total_runs += 1
        if not success:
            self._failed_runs += 1

        metric_log = {
            "metric_type": "pipeline_total_execution",
            "run_id": run_id,
            "status": "success" if success else "failed",
            "duration_seconds": round(total_duration_seconds, 3),
        }
        logger.info(json.dumps(metric_log))

    def get_summary_statistics(self) -> Dict[str, Any]:
        """Calculates running summary statistics across recorded pipeline executions."""
        avg_layer_latencies = {}
        for layer, latencies in self._layer_durations_ms.items():
            avg_layer_latencies[layer] = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

        failure_rate = (self._failed_runs / self._total_runs) if self._total_runs > 0 else 0.0

        return {
            "total_pipeline_runs": self._total_runs,
            "failed_pipeline_runs": self._failed_runs,
            "failure_rate_pct": round(failure_rate * 100, 2),
            "average_layer_latencies_ms": avg_layer_latencies,
        }


# Global singleton instance for easy import across orchestrators
metrics_collector = PipelineMetricsCollector()
