"""Layer 8: Graph & Flowchart Formatter.

Generates interactive JSON DAG structures and Mermaid diagrams from synthesized repository data.
"""

from typing import Dict, List, Any
from app.synthesis.schema import SynthesizedRepositoryReport


DOMAIN_COLOR_DEFS: Dict[str, tuple[str, str]] = {
    "core": ("#3B82F6", "core application code"),
    "backend": ("#10B981", "backend & API services"),
    "frontend": ("#8B5CF6", "UI & client components"),
    "database": ("#F59E0B", "database & data models"),
    "tests": ("#6B7280", "test files & suites"),
    "config": ("#EC4899", "configuration & setup"),
    "docs": ("#14B8A6", "documentation assets"),
    "build": ("#F97316", "build & bundling scripts"),
    "devops": ("#6366F1", "DevOps & CI/CD workflows"),
    "examples": ("#84CC16", "examples & tutorials"),
    "uncategorized": ("#9CA3AF", "general modules"),
}

DOMAIN_HEX_COLORS: Dict[str, str] = {k: v[0] for k, v in DOMAIN_COLOR_DEFS.items()}


class GraphExportFormatter:
    """Formats repository architecture and dependency sequences for visual frontend graph renderers."""

    def format_json_dag(self, report: SynthesizedRepositoryReport) -> Dict[str, Any]:
        """Generates a structured JSON node-link graph model."""
        nodes: List[Dict[str, Any]] = []
        tier_groups: Dict[int, List[str]] = {}

        for m in report.milestones:
            tier_groups[m.tier] = m.files
            for f in m.files:
                file_exports = report.file_symbols.get(f, m.file_symbols.get(f, []))
                f_domain = m.dominant_domain
                if f_domain == "mixed" or not f_domain:
                    p_lower = f.lower()
                    if "test" in p_lower:
                        f_domain = "tests"
                    elif "config" in p_lower or p_lower.endswith((".toml", ".yaml", ".json", ".ini", ".env")):
                        f_domain = "config"
                    elif "doc" in p_lower or p_lower.endswith(".md"):
                        f_domain = "docs"
                    elif "front" in p_lower or "ui" in p_lower or "web" in p_lower or "component" in p_lower:
                        f_domain = "frontend"
                    elif "db" in p_lower or "model" in p_lower or "schema" in p_lower or "sql" in p_lower:
                        f_domain = "database"
                    elif "api" in p_lower or "route" in p_lower or "server" in p_lower or "service" in p_lower:
                        f_domain = "backend"
                    else:
                        f_domain = "core"

                nodes.append({
                    "id": f,
                    "label": f.split("/")[-1],
                    "path": f,
                    "tier": m.tier,
                    "domain": f_domain,
                    "color": DOMAIN_HEX_COLORS.get(f_domain.lower(), "#9CA3AF"),
                    "confidence": m.confidence,
                    "confidence_breakdown": m.confidence_breakdown,
                    "is_cyclic": m.is_cyclic,
                    "is_isolated": m.is_isolated,
                    "exports": file_exports,
                })

        # File-level dependency edges
        file_edges: List[Dict[str, Any]] = list(report.file_dependencies) if report.file_dependencies else []

        # Milestone-level dependency edges
        milestone_edges: List[Dict[str, Any]] = []
        for m in report.milestones:
            for dep_tier in m.dependent_tiers:
                milestone_edges.append({
                    "source": f"tier_{m.tier}",
                    "target": f"tier_{dep_tier}",
                    "type": "tier_dependency",
                })

        return {
            "repo_name": report.repo_name,
            "total_nodes": len(nodes),
            "total_files": report.architecture_overview.total_files,
            "total_loc": report.architecture_overview.total_loc,
            "architecture_overview": report.architecture_overview.model_dump(),
            "nodes": nodes,
            "edges": file_edges,
            "tier_groups": tier_groups,
            "milestone_edges": milestone_edges,
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
