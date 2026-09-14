"""Layer 8: Markdown Report Formatter.

Generates production-grade GitHub Flavored Markdown architecture reports from
Layer 7 SynthesizedRepositoryReport.
"""

from typing import List
from app.synthesis.schema import SynthesizedRepositoryReport, SynthesizedMilestone


class MarkdownReportFormatter:
    """Renders structured synthesized repository intelligence into comprehensive Markdown documents."""

    def format_report(self, report: SynthesizedRepositoryReport) -> str:
        """Formats the entire report as a polished, navigable Markdown document."""
        lines: List[str] = []

        # 1. Header & Title
        lines.append(f"# Architectural Reverse-Engineering Report: `{report.repo_name}`")
        lines.append(f"*Synthesized at: {report.synthesis_timestamp}*\n")

        # 2. Executive Architecture Overview
        lines.append("## 1. Executive Architecture Overview")
        ov = report.architecture_overview
        lines.append(f"- **Primary Language**: `{ov.primary_language}`")
        lines.append(f"- **Total Analyzed Files**: `{ov.total_files}`")
        lines.append(f"- **Domain Categories**: `{ov.total_domains}`")
        lines.append(f"- **Entry Point Files**: `{', '.join(ov.entry_point_files) if ov.entry_point_files else 'None'}`")
        lines.append(f"- **Cyclic Core Components**: `{ov.cyclic_cluster_file_count}` files")
        lines.append(f"- **Isolated / Support Files**: `{ov.isolated_file_count}` files\n")

        lines.append("### Domain Distribution")
        lines.append("| Domain Category | File Count | Percentage |")
        lines.append("| :--- | :--- | :--- |")
        total_f = ov.total_files or 1
        for domain, count in sorted(ov.domain_file_counts.items(), key=lambda x: -x[1]):
            pct = (count / total_f) * 100
            lines.append(f"| `{domain}` | {count} | {pct:.1f}% |")
        lines.append("")

        # 3. Confidence & Sequence Calibration Disclosure
        lines.append("## 2. Sequence Reasoning & Confidence Calibration")
        lines.append(report.confidence_disclosure)
        lines.append("")

        # 4. Milestone-by-Milestone Walkthrough
        lines.append("## 3. Step-by-Step Architectural Milestones")
        for m in report.milestones:
            badge = f"**[{m.confidence.upper()} CONFIDENCE]**"
            if m.is_cyclic:
                badge += " *[CYCLIC CORE]*"
            elif m.is_isolated:
                badge += " *[ISOLATED COMPONENT]*"

            lines.append(f"### Milestone {m.tier}: {m.title}")
            lines.append(f"{badge} — *{m.architectural_role}*\n")
            lines.append(f"**Overview:** {m.summary}\n")

            # Domain Breakdown if multi-domain
            if len(m.domain_breakdown) > 1:
                breakdown_str = ", ".join(f"{d.capitalize()}: {c}" for d, c in sorted(m.domain_breakdown.items(), key=lambda x: -x[1]))
                lines.append(f"**Domain Composition:** {breakdown_str}\n")

            # File List
            lines.append(f"**Included Files ({len(m.files)}):**")
            for f in m.files:
                lines.append(f"- `{f}`")
            lines.append("")

            # Exports / Symbols
            if m.key_symbols_and_exports:
                lines.append(f"**Key Exported Symbols:** `{', '.join(m.key_symbols_and_exports)}`\n")

            # Deep-dive citations
            if m.deep_dive_citations:
                lines.append("**Deep-Dive Semantic Citations:**")
                for cite in m.deep_dive_citations:
                    lines.append(f"- {cite}")
                lines.append("")

            # Pedagogical Hints & Gotchas
            if m.pedagogical_hints:
                lines.append("**Pedagogical Notes:**")
                for hint in m.pedagogical_hints:
                    lines.append(f"- {hint}")
                lines.append("")

            if m.implementation_gotchas:
                lines.append("> [!WARNING]")
                lines.append("> **Implementation Gotchas:**")
                for gotcha in m.implementation_gotchas:
                    lines.append(f"> - {gotcha}")
                lines.append("")

            lines.append("---")

        return "\n".join(lines)
