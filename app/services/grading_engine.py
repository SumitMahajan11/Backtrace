"""Tiered Grading Logic Engine (Prompt 17).

Implements the 3-tier grading priority hierarchy per milestone:
1. real_tests: Runs real test suite from the repository against user code via Piston.
2. expected_output: Diffs real stdout against stored curated expected output for popular/demo repos.
3. structural_only: Fallback to static AST symbol matching + error-free runtime (exit code 0).
"""

from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from app.services.curated_milestone_expectations import CuratedExpectationsRegistry
from app.services.execution_verifier import ExecutionVerifier
from app.services.structural_verifier import StructuralVerifier


class GradingEngine:
    """Orchestrates tiered milestone grading with permanent auditability."""

    def __init__(
        self,
        execution_verifier: Optional[ExecutionVerifier] = None,
        structural_verifier: Optional[StructuralVerifier] = None,
    ):
        self.exec_verifier = execution_verifier or ExecutionVerifier()
        self.struct_verifier = structural_verifier or StructuralVerifier()

    @staticmethod
    def _find_milestone_dict(graph_data: Dict[str, Any], milestone_tier: int) -> Optional[Dict[str, Any]]:
        """Finds the dictionary for a specific milestone tier within graph_data."""
        milestones = graph_data.get("milestones", [])
        for m in milestones:
            if m.get("tier") == milestone_tier:
                return m
        return None

    def determine_grading_tier(
        self,
        job: Any,
        milestone_tier: int,
        graph_data: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Determines the grading tier for a given repository milestone.
        Returns:
            (grading_method, context_data)
            where grading_method is 'real_tests' | 'expected_output' | 'structural_only'
        """
        g_data = graph_data or (job.graph_data if hasattr(job, "graph_data") else {}) or {}
        m_dict = self._find_milestone_dict(g_data, milestone_tier) or {}

        # -----------------------------------------------------------------
        # Tier 1: Real Tests detected in repository for milestone
        # -----------------------------------------------------------------
        # 1a. Explicit test_code or test_files on milestone
        test_code = m_dict.get("test_code")
        test_files = m_dict.get("test_files") or []

        # 1b. Check graph_data test registry
        tests_reg = g_data.get("tests", {}) or g_data.get("test_suites", {})
        tier_test_entry = tests_reg.get(str(milestone_tier)) or tests_reg.get(milestone_tier)

        if test_code:
            return "real_tests", {
                "test_code": test_code,
                "test_files": test_files,
                "description": f"Real test harness for Milestone {milestone_tier}",
            }

        if tier_test_entry:
            if isinstance(tier_test_entry, str):
                return "real_tests", {
                    "test_code": tier_test_entry,
                    "test_files": test_files,
                    "description": f"Real test suite from repository for Milestone {milestone_tier}",
                }
            elif isinstance(tier_test_entry, dict) and tier_test_entry.get("test_code"):
                return "real_tests", tier_test_entry

        # 1c. Check if included files or graph nodes contain explicit test companion files
        included_files = m_dict.get("included_files", [])
        repo_nodes = g_data.get("nodes", [])
        for node in repo_nodes:
            node_id = str(node.get("id", ""))
            if (node_id.startswith("test_") or "/test_" in node_id or "_test." in node_id) and node.get("tier") == milestone_tier:
                if node.get("test_code") or node.get("source_code"):
                    return "real_tests", {
                        "test_code": node.get("test_code") or node.get("source_code"),
                        "test_files": [node_id],
                        "description": f"Repository test module {node_id}",
                    }

        # -----------------------------------------------------------------
        # Tier 2: Curated Expected Output Definition
        # -----------------------------------------------------------------
        repo_url = getattr(job, "github_url", None) or getattr(job, "repo_url", None)
        repo_name = getattr(job, "repo_name", None)

        curated = CuratedExpectationsRegistry.get_curated_expected_output(
            repo_url=repo_url,
            repo_name=repo_name,
            milestone_tier=milestone_tier,
            milestone_data=m_dict,
            graph_data=g_data,
        )
        if curated:
            return "expected_output", curated

        # -----------------------------------------------------------------
        # Tier 3: Static AST Structural Check + Error-free Runtime Fallback
        # -----------------------------------------------------------------
        return "structural_only", {
            "description": "Zero-test repository fallback: Static AST syntax check + runtime exit code verification",
        }

    def grade_attempt(
        self,
        job: Any,
        milestone_tier: int,
        submitted_code: str,
        language: str = "python",
        graph_data: Optional[Dict[str, Any]] = None,
        mode: str = "guess",
        target_file: Optional[str] = None,
        session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Executes grading against user-submitted code following the 3-tier hierarchy or scoped fill-the-blanks mode.
        Returns complete grading payload including grading_method, status, verification, and execution.
        """
        g_data = graph_data or (job.graph_data if hasattr(job, "graph_data") else {}) or {}

        # =================================================================
        # FILL THE BLANKS MODE: Scoped verification of blanked regions only
        # =================================================================
        if mode == "fill":
            from app.services.scaffold_generator import ScaffoldGenerator
            from app.services.file_content_service import FileContentService

            ref_code = ""

            # 1. Look up real file contents from DB / session if available
            if session is not None or hasattr(job, "github_url") or hasattr(job, "repo_url"):
                try:
                    if session is not None:
                        file_contents = FileContentService.get_file_contents_for_job(session=session, job=job)
                    else:
                        from app.db.session import SessionLocal
                        with SessionLocal() as db_sess:
                            file_contents = FileContentService.get_file_contents_for_job(session=db_sess, job=job)

                    if target_file and file_contents:
                        ref_code = FileContentService.find_matching_file_content(file_contents, target_file) or ""
                    elif file_contents:
                        tier_nodes = [n for n in g_data.get("nodes", []) if n.get("tier") == milestone_tier]
                        for tn in tier_nodes:
                            p = tn.get("path") or tn.get("id")
                            if p:
                                c = FileContentService.find_matching_file_content(file_contents, p)
                                if c:
                                    ref_code = c
                                    break
                except Exception:
                    ref_code = ""

            # 2. Check nodes in g_data
            if not ref_code and "nodes" in g_data:
                if target_file:
                    for n in g_data.get("nodes", []):
                        n_path = n.get("path") or n.get("id") or ""
                        if n_path == target_file or n_path.endswith(target_file) or target_file.endswith(n_path):
                            if n.get("source_code") or n.get("content"):
                                ref_code = n.get("source_code") or n.get("content")
                                break
                if not ref_code:
                    for n in g_data.get("nodes", []):
                        if n.get("tier") == milestone_tier:
                            if n.get("source_code") or n.get("content"):
                                ref_code = n.get("source_code") or n.get("content")
                                break

            # 3. If real source is genuinely unavailable, do NOT fall back to fake stubs (Part C)
            if not ref_code:
                return {
                    "grading_method": "fill_the_blanks",
                    "status": "attempting",
                    "verification": {
                        "is_verified": False,
                        "structurally_verified": False,
                        "error_message": "The original source for this file isn't available for this job — try re-running the analysis to view the real implementation.",
                    },
                    "execution": {
                        "stdout": "",
                        "stderr": "The original source for this file isn't available for this job — try re-running the analysis to view the real implementation.",
                        "exit_code": 1,
                        "status": "error",
                    },
                    "details": {
                        "passed": False,
                        "reason": "The original source for this file isn't available for this job — try re-running the analysis to view the real implementation.",
                    },
                }

            scaffold_info = ScaffoldGenerator.generate_scaffold(ref_code, language=language, file_path=target_file)
            fill_result = ScaffoldGenerator.grade_fill_blanks(
                submitted_code=submitted_code,
                scaffold_info=scaffold_info,
                language=language,
            )

            passed = fill_result.get("passed", False)
            status_str = "structurally_verified" if passed else "attempting"

            # Execute code in isolated runner for console output
            exec_result = {}
            try:
                exec_result = self.exec_verifier.execute(
                    submitted_code=submitted_code,
                    language=language,
                )
            except Exception:
                exec_result = {
                    "stdout": "",
                    "stderr": "",
                    "exit_code": 0 if passed else 1,
                    "status": "success" if passed else "error",
                }

            grading_details = {
                "grading_method": "fill_the_blanks",
                "passed": passed,
                "total_blanked": fill_result.get("total_blanked", 0),
                "implemented_count": fill_result.get("implemented_count", 0),
                "summary": (
                    f"Fill the Blanks: All {fill_result.get('total_blanked', 0)} blanked functions implemented successfully"
                    if passed
                    else f"Fill the Blanks: {fill_result.get('implemented_count', 0)} of {fill_result.get('total_blanked', 0)} blanked functions implemented"
                ),
            }

            fill_result["grading_method"] = "fill_the_blanks"
            fill_result["grading_tier_label"] = "FILL THE BLANKS // SCOPED REGIONS"

            return {
                "grading_method": "fill_the_blanks",
                "status": status_str,
                "passed": passed,
                "verification": fill_result,
                "execution": exec_result,
                "details": grading_details,
            }

        grading_tier, context_info = self.determine_grading_tier(job, milestone_tier, g_data)

        # Extract expected symbols for AST diff reporting
        expected_symbols = StructuralVerifier.extract_expected_symbols_from_graph(g_data, milestone_tier)
        ast_verification = self.struct_verifier.verify(submitted_code, expected_symbols)
        ast_verified = ast_verification.get("structurally_verified", False)

        # =================================================================
        # TIER 1: Real Tests Execution
        # =================================================================
        if grading_tier == "real_tests":
            test_code = context_info.get("test_code", "")
            # Combine user code with test suite
            harness_code = f"""# ==========================================
# User Submitted Implementation
# ==========================================
{submitted_code}

# ==========================================
# Real Repository Test Harness
# ==========================================
{test_code}
"""
            exec_result = self.exec_verifier.execute(
                submitted_code=harness_code,
                language=language,
            )

            exit_code = exec_result.get("exit_code", -1)
            stdout = exec_result.get("stdout", "")
            stderr = exec_result.get("stderr", "")

            # Check for standard test failures (exit 0 and no FAIL/ERROR in common runners)
            has_error = (exit_code != 0) or ("FAILED (" in stdout) or ("FAIL:" in stdout) or ("FAIL:" in stderr)
            passed = (not has_error) and (not exec_result.get("timed_out", False))

            grading_details = {
                "grading_method": "real_tests",
                "passed": passed,
                "test_files": context_info.get("test_files", []),
                "exit_code": exit_code,
                "summary": "All repository unit tests passed" if passed else "Repository test suite reported failures",
                "test_output": stdout if stdout else stderr,
            }

            status_str = "structurally_verified" if passed else "attempting"

            # Sync AST verification status with test result
            ast_verification["structurally_verified"] = passed
            ast_verification["is_verified"] = passed
            ast_verification["grading_method"] = "real_tests"
            ast_verification["grading_tier_label"] = "TIER 1: REAL REPO TESTS"

            return {
                "grading_method": "real_tests",
                "status": status_str,
                "passed": passed,
                "verification": ast_verification,
                "execution": exec_result,
                "details": grading_details,
            }

        # =================================================================
        # TIER 2: Expected Output Diffing
        # =================================================================
        elif grading_tier == "expected_output":
            expected_stdout = context_info.get("expected_stdout", "")
            match_mode = context_info.get("match_mode", "contains")

            exec_result = self.exec_verifier.execute(
                submitted_code=submitted_code,
                language=language,
            )

            exit_code = exec_result.get("exit_code", -1)
            stdout = exec_result.get("stdout", "")
            stderr = exec_result.get("stderr", "")

            output_matched = False
            if exit_code == 0:
                if match_mode == "exact":
                    output_matched = (stdout.strip() == expected_stdout.strip())
                elif match_mode == "regex":
                    output_matched = bool(re.search(expected_stdout, stdout))
                else:  # contains
                    output_matched = (expected_stdout.strip() in stdout)

            passed = output_matched and (exit_code == 0) and not exec_result.get("timed_out", False)
            status_str = "structurally_verified" if passed else "attempting"

            diff_summary = ""
            if not passed:
                if exit_code != 0:
                    diff_summary = f"Runtime process failed with exit code {exit_code}"
                else:
                    diff_summary = f"Expected stdout to match [{expected_stdout.strip()}], but received [{stdout.strip()}]"
            else:
                diff_summary = "Runtime stdout matched curated expected output definition"

            grading_details = {
                "grading_method": "expected_output",
                "passed": passed,
                "expected_stdout": expected_stdout,
                "match_mode": match_mode,
                "actual_stdout": stdout,
                "exit_code": exit_code,
                "diff_summary": diff_summary,
            }

            ast_verification["structurally_verified"] = passed
            ast_verification["is_verified"] = passed
            ast_verification["grading_method"] = "expected_output"
            ast_verification["grading_tier_label"] = "TIER 2: EXPECTED OUTPUT"
            if not passed and diff_summary:
                ast_verification["grading_error"] = diff_summary

            return {
                "grading_method": "expected_output",
                "status": status_str,
                "passed": passed,
                "verification": ast_verification,
                "execution": exec_result,
                "details": grading_details,
            }

        # =================================================================
        # TIER 3: Structural AST Check + Error-free Runtime Fallback
        # =================================================================
        else:
            from app.services.execution_verifier import ExecutionVerifierConnectionError

            try:
                exec_result = self.exec_verifier.execute(
                    submitted_code=submitted_code,
                    language=language,
                )
                exit_code = exec_result.get("exit_code", -1)
                runs_without_error = (exit_code == 0) and (not exec_result.get("timed_out", False))
                degraded_mode = False
            except ExecutionVerifierConnectionError:
                # Prompt 21 Graceful Degradation: Tier 3 (structural_only) does not depend strictly on execution
                exec_result = {
                    "status": "degraded_skipped",
                    "reason": "Code execution engine is temporarily unavailable (degraded to AST structural analysis)",
                    "stdout": "",
                    "stderr": "",
                    "exit_code": 0,
                    "execution_time_ms": 0.0,
                }
                exit_code = 0
                runs_without_error = True
                degraded_mode = True

            passed = ast_verified and runs_without_error
            status_str = "structurally_verified" if passed else "attempting"

            grading_details = {
                "grading_method": "structural_only",
                "passed": passed,
                "ast_verified": ast_verified,
                "runs_without_error": runs_without_error,
                "exit_code": exit_code,
                "degraded_mode": degraded_mode,
                "summary": (
                    "AST contracts matched (execution engine offline - structural verification succeeded)"
                    if passed and degraded_mode
                    else (
                        "AST contracts matched and code executed without error"
                        if passed
                        else (
                            "AST contracts missing"
                            if not ast_verified
                            else f"Code raised runtime error (exit {exit_code})"
                        )
                    )
                ),
            }

            ast_verification["structurally_verified"] = passed
            ast_verification["is_verified"] = passed
            ast_verification["grading_method"] = "structural_only"
            ast_verification["grading_tier_label"] = "TIER 3: STATIC AST DIFF"
            if not runs_without_error and exit_code != 0:
                ast_verification["runtime_warning"] = f"Code failed with exit code {exit_code}"

            return {
                "grading_method": "structural_only",
                "status": status_str,
                "passed": passed,
                "verification": ast_verification,
                "execution": exec_result,
                "details": grading_details,
            }
