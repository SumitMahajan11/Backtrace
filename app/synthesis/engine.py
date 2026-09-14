"""Layer 7: Synthesis / Manager Engine.

Combines Layer 4 (Segmentation & Domains), Layer 5 (Hybrid RAG & Context Citations),
and Layer 6 (Sequence Reasoning, Milestones & Calibrated Confidence) into a single unified
SynthesizedRepositoryReport.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

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
        exports_by_file: Dict[str, List[str]] = {}

        for node in parsed_files:
            lang_counts[node.language] = lang_counts.get(node.language, 0) + 1
            if node.entry_point:
                entry_points.append(node.path)
            if node.exports:
                exports_by_file[node.path] = node.exports

        primary_lang = max(lang_counts.items(), key=lambda x: x[1])[0] if lang_counts else "unknown"

        # Tally cyclic and isolated file totals
        cyclic_count = sum(len(step.files) for step in narration_result.steps if step.is_cyclic_cluster)
        isolated_count = sum(len(step.files) for step in narration_result.steps if step.tier_index == -1)

        arch_overview = ArchitectureOverview(
            total_files=len(parsed_files) if parsed_files else sum(domain_counts.values()),
            total_domains=len(domain_counts),
            domain_file_counts=domain_counts,
            primary_language=primary_lang,
            entry_point_files=sorted(entry_points),
            cyclic_cluster_file_count=cyclic_count,
            isolated_file_count=isolated_count,
        )

        # 2. Enrich each BuildStepNarrative with RAG citations and structural exports
        synthesized_milestones: List[SynthesizedMilestone] = []

        for step in narration_result.steps:
            # Collect exports across files in this milestone
            milestone_exports: List[str] = []
            for f in step.files:
                if f in exports_by_file:
                    milestone_exports.extend(exports_by_file[f])
            milestone_exports = sorted(list(set(milestone_exports)))[:10]

            # Query RAG if engine provided to extract contextual citations
            deep_dive_citations: List[str] = []
            if rag_engine and step.files:
                sample_file = step.files[0]
                query_str = f"What is the primary role and exported interface of {sample_file}?"
                try:
                    rag_res = rag_engine.query(query_str, target_path=sample_file)
                    for c in rag_res.citations:
                        deep_dive_citations.append(c.line_range_str)
                except Exception:
                    pass

            # Define high-level architectural role based on dominant domain & position
            arch_role = self._determine_architectural_role(step)

            domain_breakdown_counts = {d: len(flist) for d, flist in step.domain_groups.items()}

            synth_m = SynthesizedMilestone(
                tier=step.tier_index,
                title=step.title,
                summary=step.pedagogical_explanation,
                dominant_domain=step.dominant_domain,
                domain_breakdown=domain_breakdown_counts,
                files=step.files,
                confidence=step.dominant_confidence,
                is_cyclic=step.is_cyclic_cluster,
                is_isolated=(step.tier_index == -1),
                architectural_role=arch_role,
                key_symbols_and_exports=milestone_exports or step.key_symbols_or_concepts,
                deep_dive_citations=deep_dive_citations,
                prerequisite_tiers=[],
                dependent_tiers=[],
                pedagogical_hints=[],
                implementation_gotchas=[],
            )
            synthesized_milestones.append(synth_m)

        timestamp_str = datetime.now(timezone.utc).isoformat()

        return SynthesizedRepositoryReport(
            repo_name=repo_name,
            architecture_overview=arch_overview,
            confidence_disclosure=narration_result.confidence_disclosure,
            milestones=synthesized_milestones,
            total_milestones=len(synthesized_milestones),
            synthesis_timestamp=timestamp_str,
            metadata=metadata,
        )

    def _determine_architectural_role(self, step: BuildStepNarrative) -> str:
        """Assigns clear, pedagogical architectural role description to each step."""
        if step.tier_index == -1:
            return "Isolated / Auxiliary Support Components"
        if step.is_cyclic_cluster:
            return "Mutually-Coupled Core Architectural Backbone"
        
        domain = step.dominant_domain.lower()
        if step.tier_index == 0:
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
