"""Layer 8: Quiz & Learning Checkpoint Formatter.

Generates pedagogical quizzes and comprehension checkpoints derived from repository architecture.
"""

import random
from typing import Any, Dict, List
from app.synthesis.schema import SynthesizedMilestone, SynthesizedRepositoryReport


GENERIC_ARCHITECTURAL_DISTRACTORS = [
    "Coordinates background asynchronous worker queues and task retry handlers.",
    "Provides automated continuous integration configurations and container build scripts.",
    "Implements client-side telemetry collection and user session analytics.",
    "Defines database migration schemas and foreign-key constraints.",
    "Implements external payment gateway webhooks and signature validation.",
    "Manages distributed caching layers and key expiration policies.",
]


def _derive_component_name(files: List[str]) -> str:
    """Extracts a concise component or module name from a milestone's files."""
    if not files:
        return "core"
    norm_paths = [p.replace("\\", "/").strip("/") for p in files]
    if len(norm_paths) == 1:
        filename = norm_paths[0].split("/")[-1]
        return filename.rsplit(".", 1)[0]
    first_parts = norm_paths[0].split("/")
    if len(first_parts) > 1:
        return first_parts[-2]
    filename = first_parts[-1]
    return filename.rsplit(".", 1)[0]


def _derive_milestone_option_text(m: SynthesizedMilestone) -> str:
    """Derives a distinct pedagogical option description from a milestone's real content."""
    comp = _derive_component_name(m.files)
    symbols_part = ""
    if m.key_symbols_and_exports:
        top_symbols = m.key_symbols_and_exports[:2]
        symbols_part = f" (e.g. {', '.join(top_symbols)})"

    if getattr(m, "track", "core") == "test_track" or m.dominant_domain == "tests":
        return f"Provides automated test suites and validation assertions for {comp}{symbols_part}."
    elif m.is_cyclic:
        return f"Implements mutually coupled core domain logic coordinating {comp}{symbols_part}."
    elif m.is_isolated:
        return f"Serves as standalone auxiliary utility support for {comp}{symbols_part}."
    elif m.tier == 1 and getattr(m, "track", "core") == "core":
        return f"Defines foundational leaf primitives with zero internal prerequisites for {comp}{symbols_part}."
    else:
        role = m.architectural_role or f"{m.dominant_domain.capitalize()} Services"
        return f"Implements {role.lower()} within the {m.dominant_domain} layer for {comp}{symbols_part}."


class QuizFormatter:
    """Generates structured educational checkpoint quizzes from synthesized repository reports."""

    def generate_quiz(self, report: SynthesizedRepositoryReport) -> Dict[str, Any]:
        """Creates a collection of multiple-choice questions for learners."""
        questions: List[Dict[str, Any]] = []
        all_milestones: List[SynthesizedMilestone] = list(report.milestones or []) + list(
            getattr(report, "test_track", []) or []
        )

        if not all_milestones:
            return {
                "repo_name": report.repo_name,
                "total_questions": 0,
                "questions": [],
            }

        # Derive unique real-content descriptions for each milestone
        raw_descriptions = [_derive_milestone_option_text(m) for m in all_milestones]
        seen_descriptions: Dict[str, int] = {}
        unique_descriptions: List[str] = []
        for idx, (m, desc) in enumerate(zip(all_milestones, raw_descriptions)):
            if desc in seen_descriptions:
                count = seen_descriptions[desc] + 1
                seen_descriptions[desc] = count
                disp = m.display_id or str(idx + 1)
                unique_descriptions.append(f"{desc[:-1]} ({m.track_label} {disp} module).")
            else:
                seen_descriptions[desc] = 1
                unique_descriptions.append(desc)

        num_milestones = len(all_milestones)

        for i, m in enumerate(all_milestones):
            track_label = getattr(m, "track_label", None) or ("Test files" if getattr(m, "track", "core") == "test_track" else "Milestone")
            display_id = getattr(m, "display_id", None) or str(m.tier or (i + 1))
            q_id = f"q_{m.track}_{display_id}"

            correct_option = unique_descriptions[i]

            # Select 3 distractors from OTHER milestones' real content
            if num_milestones >= 4:
                distractor_indices = [(i + 1 + offset) % num_milestones for offset in range(3)]
                distractors = [unique_descriptions[j] for j in distractor_indices]
            else:
                distractors = [unique_descriptions[j] for j in range(num_milestones) if j != i]
                needed = 3 - len(distractors)
                for offset in range(needed):
                    fallback = GENERIC_ARCHITECTURAL_DISTRACTORS[(i * 2 + offset) % len(GENERIC_ARCHITECTURAL_DISTRACTORS)]
                    distractors.append(fallback)

            raw_options = [(correct_option, True)] + [(d, False) for d in distractors]

            # Shuffle option order with a stable seed based on question id
            rng = random.Random(q_id)
            shuffled_options = list(raw_options)
            rng.shuffle(shuffled_options)

            options_text = [text for text, _ in shuffled_options]
            correct_option_index = next(idx for idx, (_, is_correct) in enumerate(shuffled_options) if is_correct)

            # Question text does NOT contain the milestone title, correct file name, or answer string
            question_text = f"What is the primary architectural responsibility of {track_label} {display_id}?"

            questions.append({
                "id": q_id,
                "tier": m.tier,
                "question": question_text,
                "options": options_text,
                "correct_option_index": correct_option_index,
                "explanation": f"{track_label} {display_id} {correct_option[0].lower() + correct_option[1:]}",
            })

        return {
            "repo_name": report.repo_name,
            "total_questions": len(questions),
            "questions": questions,
        }
