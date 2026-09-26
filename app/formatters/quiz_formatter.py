"""Layer 8: Quiz & Learning Checkpoint Formatter.

Generates pedagogical quizzes and comprehension checkpoints derived from repository architecture.
"""

from typing import Dict, List, Any
from app.synthesis.schema import SynthesizedRepositoryReport


class QuizQuestion(dict):
    """Structured question model for interactive learning mode."""


class QuizFormatter:
    """Generates structured educational checkpoint quizzes from synthesized repository reports."""

    def generate_quiz(self, report: SynthesizedRepositoryReport) -> Dict[str, Any]:
        """Creates a collection of multiple-choice and reflection questions for learners."""
        questions: List[Dict[str, Any]] = []
        ov = report.architecture_overview

        # Question 1: Foundational Architecture
        if report.milestones:
            m0 = report.milestones[0]
            questions.append({
                "id": "q_foundational",
                "tier": m0.tier,
                "question": f"Why should a developer begin reverse-engineering `{report.repo_name}` at Milestone {m0.tier} ({m0.title})?",
                "options": [
                    f"These {len(m0.files)} files are leaf primitives with 0 internal dependencies.",
                    "These files contain the top-level CLI entry point.",
                    "These files contain end-to-end integration tests.",
                    "These files were the most recently edited in git history.",
                ],
                "correct_option_index": 0,
                "explanation": f"Milestone 0 represents starting foundational files (files with no internal dependencies) that can be understood in isolation without prior knowledge of the rest of the codebase.",
            })

        # Question 2: Cyclic Core handling
        cyclic_milestone = next((m for m in report.milestones if m.is_cyclic), None)
        if cyclic_milestone:
            questions.append({
                "id": "q_cyclic_core",
                "tier": cyclic_milestone.tier,
                "question": f"Milestone {cyclic_milestone.tier} contains a mutual dependency cycle ({len(cyclic_milestone.files)} files). How should this cluster be approached?",
                "options": [
                    "Read them sequentially in alphabetical order because order is strict.",
                    "Read them as a coupled system / cohesive unit, since their interfaces are co-dependent.",
                    "Skip them completely because cycles are always invalid code bugs.",
                    "Read only the largest file and ignore the others.",
                ],
                "correct_option_index": 1,
                "explanation": "These files depend on each other in a loop, so there's no single correct order — an estimate is used instead. They are best understood together as a subsystem.",
            })

        # Intermediate / Higher Tier Architecture questions
        base_tier = report.milestones[0].tier if report.milestones else 0
        non_base_milestones = [m for m in report.milestones if m.tier != base_tier and not m.is_cyclic]
        for m_target in non_base_milestones:
            questions.append({
                "id": f"q_tier_{m_target.tier}_role",
                "tier": m_target.tier,
                "question": f"What is the architectural role of Milestone {m_target.tier} ({m_target.title})?",
                "options": [
                    f"It implements the {m_target.dominant_domain} layer that builds upon and depends on lower-tier foundational modules.",
                    "It defines low-level leaf utilities with zero internal imports.",
                    "It is completely isolated and detached from all other repository components.",
                    "It acts exclusively as a temporary build artifact cache.",
                ],
                "correct_option_index": 0,
                "explanation": f"Milestone {m_target.tier} serves the {m_target.dominant_domain} layer, consuming the abstractions provided by lower tiers.",
            })

        # Question 4: Domain Distribution
        dom_names = list(ov.domain_file_counts.keys())
        if dom_names:
            dominant = max(ov.domain_file_counts.items(), key=lambda x: x[1])
            dom_milestone = next((m for m in report.milestones if m.dominant_domain == dominant[0]), report.milestones[0] if report.milestones else None)
            dom_tier = dom_milestone.tier if dom_milestone else 0
            questions.append({
                "id": "q_domain_profile",
                "tier": dom_tier,
                "question": f"Which domain represents the largest portion of files in `{report.repo_name}`?",
                "options": [f"`{d}`" for d in dom_names[:4]],
                "correct_option_index": 0 if dom_names[0] == dominant[0] else dom_names[:4].index(dominant[0]) if dominant[0] in dom_names[:4] else 0,
                "explanation": f"`{dominant[0]}` accounts for {dominant[1]} out of {ov.total_files} analyzed files in the codebase.",
            })

        return {
            "repo_name": report.repo_name,
            "total_questions": len(questions),
            "questions": questions,
        }
