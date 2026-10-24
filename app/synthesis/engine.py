"""Layer 7: Synthesis / Manager Engine.

Combines Layer 4 (Segmentation & Domains), Layer 5 (Hybrid RAG & Context Citations),
and Layer 6 (Sequence Reasoning, Milestones & Calibrated Confidence) into a single unified
SynthesizedRepositoryReport.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Set, Tuple

from app.parser.schema import FileNode
from app.rag.engine import HybridRAGEngine
from app.segmentation.schema import SegmentationResult, DomainType
from app.sequence.schema import SequenceNarrationResult, BuildStepNarrative
from app.synthesis.schema import (
    ArchitectureOverview,
    SynthesizedMilestone,
    SynthesizedRepositoryReport,
)


class SynthesisEngine:
    """Master synthesizer combining structural, semantic, and sequential repository intelligence."""

    def synthesize(
        self,
        repo_name: str,
        segmentation_result: SegmentationResult,
        narration_result: SequenceNarrationResult,
        parsed_files: Optional[List[FileNode]] = None,
        rag_engine: Optional[HybridRAGEngine] = None,
        file_contents: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SynthesizedRepositoryReport:
        """Executes full synthesis across analytical layers."""
        parsed_files = parsed_files or []
        file_contents = file_contents or {}
        metadata = metadata or {}

        # 1. Build Architecture Overview from Layer 4 + Layer 2 metadata
        domain_counts: Dict[str, int] = {}
        if segmentation_result.domain_counts:
            domain_counts = {str(k): v for k, v in segmentation_result.domain_counts.items()}
        elif segmentation_result.files:
            for s_node in segmentation_result.files:
                d_val = s_node.domain.value if hasattr(s_node.domain, "value") else str(s_node.domain)
                domain_counts[d_val] = domain_counts.get(d_val, 0) + 1

        # Detect primary language & entry points
        lang_counts: Dict[str, int] = {}
        entry_points: List[str] = []
        symbols_by_file: Dict[str, List[str]] = {}

        for node in parsed_files:
            lang_counts[node.language] = lang_counts.get(node.language, 0) + 1
            if node.entry_point and not self._is_test_path(node.path):
                entry_points.append(node.path)

            # Extract genuine code symbols (classes, functions, exports), strictly excluding filenames
            syms: List[str] = []
            if node.classes:
                syms.extend(node.classes)
            if node.functions:
                syms.extend(node.functions)
            if node.exports:
                syms.extend(node.exports)
            valid_syms = [s for s in syms if s and "/" not in s and "\\" not in s and not s.endswith(".py")]
            if valid_syms:
                symbols_by_file[node.path] = sorted(list(set(valid_syms)))

        primary_lang = max(lang_counts.items(), key=lambda x: x[1])[0] if lang_counts else "unknown"

        # Tally cyclic and isolated file totals
        cyclic_count = sum(len(step.files) for step in narration_result.steps if step.is_cyclic_cluster)
        total_files_count = len(segmentation_result.files) if (segmentation_result and segmentation_result.files) else (len(parsed_files) if parsed_files else sum(domain_counts.values()))
        milestone_files_count = sum(len(step.files) for step in narration_result.steps)
        isolated_count = max(0, total_files_count - milestone_files_count)
        total_loc_count = sum(len(content.splitlines()) for content in file_contents.values()) if file_contents else 0

        arch_overview = ArchitectureOverview(
            total_files=total_files_count,
            total_domains=len(domain_counts),
            domain_file_counts=domain_counts,
            primary_language=primary_lang,
            entry_point_files=sorted(entry_points),
            cyclic_cluster_file_count=cyclic_count,
            isolated_file_count=isolated_count,
            total_loc=total_loc_count,
        )

        # 2. Enrich each BuildStepNarrative with RAG citations and structural exports
        synthesized_milestones: List[SynthesizedMilestone] = []
        synthesized_test_track: List[SynthesizedMilestone] = []

        for idx, step in enumerate(narration_result.steps, start=1):
            disp_id = step.display_id or str(step.step_number or idx)
            synth_m = self._enrich_step(
                step=step,
                symbols_by_file=symbols_by_file,
                rag_engine=rag_engine,
                track="core",
                track_label="Milestone",
                display_id=disp_id,
                display_number=idx,
            )
            synthesized_milestones.append(synth_m)

        test_track_steps = getattr(narration_result, "test_track", []) or []
        for idx, step in enumerate(test_track_steps, start=1):
            disp_id = step.display_id or f"T{step.step_number or idx}"
            synth_test_m = self._enrich_step(
                step=step,
                symbols_by_file=symbols_by_file,
                rag_engine=rag_engine,
                track="test_track",
                track_label="Test files",
                display_id=disp_id,
                display_number=idx,
            )
            synthesized_test_track.append(synth_test_m)

        # Collect internal file-level import edges for graph visualizations (deduped by (source, target))
        file_dependencies: List[Dict[str, Any]] = []
        seen_edges: Set[Tuple[str, str]] = set()
        if parsed_files:
            for node in parsed_files:
                for imp in node.imports:
                    if not imp.is_external and imp.resolved and imp.target:
                        src = imp.source_path or node.path
                        tgt = imp.target
                        pair = (src, tgt)
                        if pair not in seen_edges:
                            seen_edges.add(pair)
                            file_dependencies.append({
                                "source": src,
                                "target": tgt,
                                "type": "import",
                            })

        timestamp_str = datetime.now(timezone.utc).isoformat()
        narration_source = getattr(narration_result, "source", "template")
        metadata["narration_source"] = narration_source

        return SynthesizedRepositoryReport(
            repo_name=repo_name,
            architecture_overview=arch_overview,
            confidence_disclosure=narration_result.confidence_disclosure,
            milestones=synthesized_milestones,
            test_track=synthesized_test_track,
            total_milestones=len(synthesized_milestones) + len(synthesized_test_track),
            synthesis_timestamp=timestamp_str,
            file_symbols=symbols_by_file,
            file_dependencies=file_dependencies,
            metadata=metadata,
            narration_source=narration_source,
        )

    def _enrich_step(
        self,
        step: BuildStepNarrative,
        symbols_by_file: Dict[str, List[str]],
        rag_engine: Optional[HybridRAGEngine],
        track: str,
        track_label: str,
        display_id: str,
        display_number: int,
    ) -> SynthesizedMilestone:
        """Enriches a single build narrative step with symbols, citations, and domain breakdown."""
        milestone_symbols: List[str] = []
        milestone_file_symbols: Dict[str, List[str]] = {}
        for f in step.files:
            if f in symbols_by_file:
                clean_syms = [s for s in symbols_by_file[f] if not s.startswith("_")]
                milestone_symbols.extend(clean_syms)
                milestone_file_symbols[f] = clean_syms
        milestone_symbols = sorted(list(set(milestone_symbols)))[:10]

        deep_dive_citations: List[str] = []
        if rag_engine and step.files:
            milestone_file_set = set(step.files)
            for sample_file in step.files[:3]:
                query_str = f"What is the primary role and exported interface of {sample_file}?"
                try:
                    rag_res = rag_engine.query(query_str, target_path=sample_file)
                    for c in rag_res.citations:
                        if c.file_path in milestone_file_set:
                            if c.line_range_str not in deep_dive_citations:
                                deep_dive_citations.append(c.line_range_str)
                except Exception:
                    pass
            deep_dive_citations = merge_citation_strings(deep_dive_citations)[:8]

        arch_role = self._determine_architectural_role(step)
        domain_breakdown_counts = {d: len(flist) for d, flist in step.domain_groups.items()}

        return SynthesizedMilestone(
            tier=display_number,
            tier_index=step.tier_index,
            title=step.title,
            summary=step.pedagogical_explanation,
            dominant_domain=step.dominant_domain,
            domain_breakdown=domain_breakdown_counts,
            files=step.files,
            confidence=step.dominant_confidence,
            confidence_breakdown=step.confidence_breakdown,
            is_cyclic=step.is_cyclic_cluster,
            is_isolated=(step.tier_index == -1),
            architectural_role=arch_role,
            key_symbols_and_exports=milestone_symbols,
            file_symbols=milestone_file_symbols,
            deep_dive_citations=deep_dive_citations,
            prerequisite_tiers=[],
            dependent_tiers=[],
            pedagogical_hints=[],
            implementation_gotchas=[],
            track=track,
            track_label=track_label,
            display_id=display_id,
        )

    @staticmethod
    def _is_test_path(path: str) -> bool:
        """Checks if a file path matches tests/, test_*.py, *_test.py, or conftest.py."""
        norm = path.replace("\\", "/").strip("/")
        parts = norm.split("/")
        filename = parts[-1]
        if "tests" in parts or parts[0] == "tests" or "/tests/" in f"/{norm}/":
            return True
        if filename.startswith("test_") and filename.endswith(".py"):
            return True
        if filename.endswith("_test.py"):
            return True
        if filename == "conftest.py":
            return True
        return False

    def _determine_architectural_role(self, step: BuildStepNarrative) -> str:
        """Assigns clear, pedagogical architectural role description to each step."""
        if getattr(step, "track", "core") == "test_track":
            return "Test Harness & Validation Assertions"
        if step.tier_index == -1:
            return "Isolated / Auxiliary Support Components"
        if step.is_cyclic_cluster:
            return "Mutually-Coupled Core Architectural Backbone"

        domain = step.dominant_domain.lower()
        if step.step_number == 1 or step.tier_index == 0:
            return "Foundational Primitives & Zero-Dependency Leaf Utilities"
        elif "config" in domain or "build" in domain or "devops" in domain:
            return "Environment Configuration & Build Infrastructure"
        elif "core" in domain or "backend" in domain:
            return "Core Domain Extensions & Business Logic Handlers"
        elif "tests" in domain:
            return "Test Harness & Validation Assertions"
        elif "docs" in domain:
            return "System Documentation & Specifications"
        elif "frontend" in domain:
            return "User Interface & Presentation Layer"
        elif "examples" in domain:
            return "End-to-End Usage Demos & Tutorial Applications"
        else:
            return "Intermediate Integration Layer"


def merge_citation_strings(citations: List[str]) -> List[str]:
    """Parse citation strings and merge overlapping citation ranges into one range per function."""
    if not citations:
        return []
    import re
    parsed = []
    pattern = re.compile(r"^([^:]+):L(\d+)-L(\d+)(?:\s*\(([^)]+)\))?$")
    for c in citations:
        m = pattern.match(c.strip())
        if m:
            file_path = m.group(1)
            start_l = int(m.group(2))
            end_l = int(m.group(3))
            sym = m.group(4)
            parsed.append((file_path, sym, start_l, end_l))
        else:
            parsed.append((c, None, None, None))

    from collections import defaultdict
    grouped = defaultdict(list)
    order = []
    for item in parsed:
        if item[2] is None:
            continue
        key = (item[0], item[1])
        if key not in grouped:
            order.append(key)
        grouped[key].append((item[2], item[3]))

    merged_strings = []
    for key in order:
        file_path, sym = key
        ranges = sorted(grouped[key], key=lambda x: (x[0], x[1]))
        cur_s, cur_e = ranges[0]
        for ns, ne in ranges[1:]:
            if ns <= cur_e + 1:
                cur_e = max(cur_e, ne)
            else:
                sym_str = f" ({sym})" if sym else ""
                merged_strings.append(f"{file_path}:L{cur_s}-L{cur_e}{sym_str}")
                cur_s, cur_e = ns, ne
        sym_str = f" ({sym})" if sym else ""
        merged_strings.append(f"{file_path}:L{cur_s}-L{cur_e}{sym_str}")

    for item in parsed:
        if item[2] is None and item[0] not in merged_strings:
            merged_strings.append(item[0])

    return merged_strings
