"""Layer 11: Pipeline Orchestration & Execution Engine.

Orchestrates the 11-layer architecture into a unified execution pipeline with real-time
progress tracking, stage isolation, and error boundaries.
"""

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Any

from app.formatters.graph_formatter import GraphExportFormatter
from app.formatters.markdown_formatter import MarkdownReportFormatter
from app.formatters.quiz_formatter import QuizFormatter
from app.orchestration.schema import (
    PipelineProgressEvent,
    PipelineResult,
    PipelineStage,
)
from app.parser.python_parser import PythonLanguageParser
from app.parser.go_parser import GoLanguageParser
from app.parser.javascript_parser import JavaScriptLanguageParser
from app.parser.rust_parser import RustLanguageParser
from app.parser.java_parser import JavaLanguageParser
from app.parser.cpp_parser import CppLanguageParser
from app.parser.shell_parser import ShellLanguageParser
from app.parser.tla_parser import TlaLanguageParser
from app.rag.engine import HybridRAGEngine
from app.segmentation.engine import SegmentationEngine
from app.segmentation.schema import DomainType
from app.sequence.baseline_ordering import BaselineOrderingEngine
from app.sequence.confidence_scoring import ConfidenceScoringEngine
from app.sequence.constrained_tie_breaking import ConstrainedTieBreakerEngine
from app.sequence.narration_engine import NarrationEngine
from app.models.history import CommitHistoryResult
from app.services.history_extractor import HistoryExtractorService
from app.services.ingestion import MAX_REPO_FILE_LIMIT_V1
from app.services.metrics import metrics_collector
from app.synthesis.engine import SynthesisEngine
from app.utils.logging import get_logger, set_run_id

logger = get_logger("orchestrator", layer="orchestration")


class PipelineOrchestrator:
    """Master orchestrator executing the 11-layer reverse engineering pipeline."""

    def __init__(self):
        # Register all Layer 2 parsers
        self.parsers = [
            PythonLanguageParser(),
            GoLanguageParser(),
            JavaScriptLanguageParser(),
            RustLanguageParser(),
            JavaLanguageParser(),
            CppLanguageParser(),
            ShellLanguageParser(),
            TlaLanguageParser(),
        ]
        self.seg_engine = SegmentationEngine()
        self.stage_a = BaselineOrderingEngine()
        self.stage_b = ConstrainedTieBreakerEngine()
        self.stage_c = ConfidenceScoringEngine()
        self.stage_d = NarrationEngine()
        self.synthesis_engine = SynthesisEngine()
        self.md_formatter = MarkdownReportFormatter()
        self.graph_formatter = GraphExportFormatter()
        self.quiz_formatter = QuizFormatter()
        self.history_extractor = HistoryExtractorService()

    def run_pipeline(
        self,
        repo_name: str,
        file_paths: List[str],
        file_contents: Dict[str, str],
        git_repo_path: Optional[Path] = None,
        progress_callback: Optional[Callable[[PipelineProgressEvent], None]] = None,
        heartbeat_callback: Optional[Callable[[], None]] = None,
        enable_rag: bool = True,
        llm_provider: Optional[Callable[[str, str], str]] = None,
        run_id: Optional[str] = None,
    ) -> PipelineResult:
        """Synchronously executes the end-to-end pipeline across all layers."""
        start_time = time.time()
        active_run_id = run_id or str(uuid.uuid4())
        set_run_id(active_run_id)
        events: List[PipelineProgressEvent] = []

        logger.info(
            f"Initiating reverse engineering pipeline for repository '{repo_name}'",
            extra={"layer": "layer_11_orchestration", "run_id": active_run_id},
        )

        def emit(stage: PipelineStage, progress: float, msg: str, details: Optional[Dict[str, Any]] = None):
            ev = PipelineProgressEvent(
                stage=stage,
                progress_pct=progress,
                message=msg,
                stage_details=details or {},
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            events.append(ev)
            logger.info(
                f"[{stage.value}] {msg}",
                extra={"layer": stage.value, "run_id": active_run_id, "details": details or {}},
            )
            if progress_callback:
                try:
                    progress_callback(ev)
                except Exception:
                    pass
            if heartbeat_callback:
                try:
                    heartbeat_callback()
                except Exception:
                    pass

        try:
            # -------------------------------------------------------------
            # Stage 1: Ingestion & Workspace Validation (Layers 1, 10)
            # -------------------------------------------------------------
            s1_start = time.time()
            emit(PipelineStage.INGESTION, 10.0, f"Validating {len(file_paths)} repository files")

            # Enforce v1 repository size boundary (150+ file cap)
            if len(file_paths) > MAX_REPO_FILE_LIMIT_V1:
                limit_msg = (
                    f"Repository exceeds v1 cap of {MAX_REPO_FILE_LIMIT_V1} files "
                    f"(found {len(file_paths)} files). Processing halted to prevent unbounded resource exhaustion."
                )
                emit(PipelineStage.FAILED, 100.0, limit_msg, {"file_count": len(file_paths), "limit": MAX_REPO_FILE_LIMIT_V1})
                metrics_collector.record_pipeline_run(active_run_id, False, time.time() - start_time)
                return PipelineResult(
                    success=False,
                    repo_name=repo_name,
                    events=events,
                    error=limit_msg,
                    run_id=active_run_id,
                    execution_time_seconds=round(time.time() - start_time, 3),
                )

            all_repo_files = set(file_paths)
            metrics_collector.record_layer_metric("layer_1_ingestion", (time.time() - s1_start) * 1000, run_id=active_run_id)

            # -------------------------------------------------------------
            # Stage 2: Static AST Parsing & Git History (Layers 2, 3)
            # -------------------------------------------------------------
            s2_start = time.time()
            emit(PipelineStage.PARSING, 25.0, "Parsing structural AST import graphs and symbol exports")
            parsed_nodes = []
            collected_parse_errors: List[Dict[str, Any]] = []

            for parser in self.parsers:
                matching_paths = [p for p in file_paths if any(p.endswith(ext) for ext in parser.file_extensions)]
                if matching_paths:
                    matching_contents = {p: file_contents[p] for p in matching_paths if p in file_contents}
                    res = parser.parse_repository(matching_paths, matching_contents)
                    parsed_nodes.extend(res.files)
                    for pe in res.parse_errors:
                        collected_parse_errors.append(pe.model_dump())

            # Extract git history signals if git directory exists
            hist_res = None
            if git_repo_path and git_repo_path.exists():
                try:
                    hist_res = self.history_extractor.extract_history(git_repo_path)
                except Exception:
                    hist_res = None

            if hist_res is None:
                hist_res = CommitHistoryResult(
                    history_available=False,
                    history_confidence="reduced",
                    commit_count_processed=0,
                    commit_count_total=0,
                )
            metrics_collector.record_layer_metric("layer_2_parsing", (time.time() - s2_start) * 1000, run_id=active_run_id)

            # -------------------------------------------------------------
            # Stage 3: Segmentation & Hybrid RAG (Layers 4, 5)
            # -------------------------------------------------------------
            s3_start = time.time()
            emit(PipelineStage.UNDERSTANDING, 45.0, "Segmenting architecture domains and indexing RAG vectors")
            seg_result = self.seg_engine.segment_repository(parsed_nodes, file_paths)
            uncategorized_files = [
                f.path for f in seg_result.files if f.domain == DomainType.UNCATEGORIZED
            ]

            rag_engine = None
            if enable_rag and parsed_nodes:
                rag_engine = HybridRAGEngine(dimension=128)
                rag_engine.index_repository(parsed_nodes, file_contents)
            metrics_collector.record_layer_metric("layer_4_segmentation", (time.time() - s3_start) * 1000, run_id=active_run_id)

            # -------------------------------------------------------------
            # Stage 4: Sequence Reasoning (Layer 6 Stages A, B, C, D)
            # -------------------------------------------------------------
            s4_start = time.time()
            emit(PipelineStage.SEQUENCE_REASONING, 70.0, "Computing calibrated topological sequence reasoning")
            a_res = self.stage_a.compute_baseline_order(
                file_nodes=parsed_nodes,
                segmentation_result=seg_result,
                all_repo_files=file_paths,
                file_contents=file_contents,
            )
            b_res = self.stage_b.refine_baseline_order(
                a_res,
                commit_history=hist_res,
                file_contents=file_contents,
            )
            c_res = self.stage_c.compute_confidence_scores(b_res, commit_history=hist_res)
            d_res = self.stage_d.generate_narration(c_res, b_res, file_contents=file_contents, llm_provider=llm_provider)
            metrics_collector.record_layer_metric("layer_6_sequence_reasoning", (time.time() - s4_start) * 1000, run_id=active_run_id)

            # -------------------------------------------------------------
            # Stage 5: Synthesis & Formatting (Layers 7, 8)
            # -------------------------------------------------------------
            s5_start = time.time()
            emit(PipelineStage.SYNTHESIS, 90.0, "Synthesizing unified repository architecture and formatting outputs")
            synth_report = self.synthesis_engine.synthesize(
                repo_name=repo_name,
                segmentation_result=seg_result,
                narration_result=d_res,
                parsed_files=parsed_nodes,
                rag_engine=rag_engine,
                file_contents=file_contents,
            )

            md_out = self.md_formatter.format_report(synth_report)

            # Explicitly surface uncategorized files and parse errors in the Markdown output
            if uncategorized_files:
                md_out += "\n\n## Uncategorized & Unsupported Files\n"
                md_out += "The following files could not be classified into architectural domains:\n"
                for uf in uncategorized_files:
                    md_out += f"- `{uf}`\n"

            if collected_parse_errors:
                md_out += "\n\n## Isolated Parse Warnings\n"
                md_out += "The following files contained syntax errors and were isolated from AST graphs:\n"
                for pe in collected_parse_errors:
                    md_out += f"- `{pe.get('path', 'unknown')}` ({pe.get('language', 'unknown')}): {pe.get('error_message', '')}\n"

            graph_out = self.graph_formatter.format_json_dag(synth_report)
            quiz_out = self.quiz_formatter.generate_quiz(synth_report)
            metrics_collector.record_layer_metric("layer_7_synthesis", (time.time() - s5_start) * 1000, run_id=active_run_id)

            emit(PipelineStage.COMPLETE, 100.0, f"Successfully reverse-engineered {repo_name}")
            elapsed = time.time() - start_time
            metrics_collector.record_pipeline_run(active_run_id, True, elapsed)

            return PipelineResult(
                success=True,
                repo_name=repo_name,
                report=synth_report,
                markdown_output=md_out,
                graph_output=graph_out,
                quiz_output=quiz_out,
                events=events,
                parse_errors=collected_parse_errors,
                uncategorized_files=uncategorized_files,
                run_id=active_run_id,
                execution_time_seconds=elapsed,
            )

        except Exception as e:
            emit(PipelineStage.FAILED, 100.0, f"Pipeline failed: {str(e)}")
            elapsed = time.time() - start_time
            metrics_collector.record_pipeline_run(active_run_id, False, elapsed)
            return PipelineResult(
                success=False,
                repo_name=repo_name,
                events=events,
                error=str(e),
                run_id=active_run_id,
                execution_time_seconds=elapsed,
            )


