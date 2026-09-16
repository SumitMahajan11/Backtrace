"""Layer 8: Graph & Flowchart Formatter.

Generates interactive JSON DAG structures and Mermaid diagrams from synthesized repository data.
"""

from typing import Dict, List, Any
from app.synthesis.schema import SynthesizedRepositoryReport


DOMAIN_HEX_COLORS = {
    "core": "#3B82F6",       # Blue
    "backend": "#10B981",    # Emerald
    "frontend": "#8B5CF6",   # Purple
    "database": "#F59E0B",   # Amber
    "tests": "#6B7280",      # Gray
    "config": "#EC4899",     # Pink
    "docs": "#14B8A6",       # Teal
    "build": "#F97316",      # Orange
    "devops": "#6366F1",     # Indigo
    "examples": "#84CC16",   # Lime
    "uncategorized": "#9CA3AF",
}


class GraphExportFormatter:
    """Formats repository architecture and dependency sequences for visual frontend graph renderers."""

    def format_json_dag(self, report: SynthesizedRepositoryReport) -> Dict[str, Any]:
        """Generates a structured JSON node-link graph model."""
        nodes: List[Dict[str, Any]] = []
        tier_groups: Dict[int, List[str]] = {}

        for m in report.milestones:
            tier_groups[m.tier] = m.files
            for f in m.files:
                nodes.append({
                    "id": f,
                    "label": f.split("/")[-1],
                    "path": f,
                    "tier": m.tier,
                    "domain": m.dominant_domain,
                    "color": DOMAIN_HEX_COLORS.get(m.dominant_domain.lower(), "#9CA3AF"),
                    "confidence": m.confidence,
                    "confidence_breakdown": m.confidence_breakdown,
                    "is_cyclic": m.is_cyclic,
                    "is_isolated": m.is_isolated,
                    "exports": m.key_symbols_and_exports,
                })

        # Milestone-level dependency edges
        edges: List[Dict[str, Any]] = []
        for m in report.milestones:
            for dep_tier in m.dependent_tiers:
                edges.append({
                    "source": f"tier_{m.tier}",
                    "target": f"tier_{dep_tier}",
                    "type": "tier_dependency",
                })

        return {
            "repo_name": report.repo_name,
            "total_nodes": len(nodes),
            "nodes": nodes,
            "tier_groups": tier_groups,
            "milestone_edges": edges,
        }

    def format_mermaid(self, report: SynthesizedRepositoryReport) -> str:
        """Generates a clean Mermaid sequence/flowchart representation."""
        lines = ["graph TD"]

        # Subgraph per milestone tier
        for m in report.milestones:
            tier_id = f"Tier_{m.tier}"
            title_clean = m.title.replace('"', '').replace('(', '').replace(')', '')
            lines.append(f'  subgraph {tier_id} ["Milestone {m.tier}: {title_clean}"]')
            for idx, f in enumerate(m.files[:8]):  # Sample up to 8 files per subgraph to avoid massive diagrams
                node_id = f"node_{m.tier}_{idx}"
                fname = f.split('/')[-1]
                lines.append(f'    {node_id}["{fname}"]')
            if len(m.files) > 8:
                lines.append(f'    more_{m.tier}["... +{len(m.files)-8} more files"]')
            lines.append("  end")

        # Connect consecutive non-isolated tiers
        active_tiers = [m.tier for m in report.milestones if not m.is_isolated]
        for i in range(len(active_tiers) - 1):
            t_curr = active_tiers[i]
            t_next = active_tiers[i + 1]
            lines.append(f"  Tier_{t_curr} --> Tier_{t_next}")

        return "\n".join(lines)
