# Project: Reverse-Engineering / Build-Sequence Reconstruction Platform

## One-line pitch
A platform where a user submits a GitHub repo (or later, a zip file), and the system:
1. Analyzes and explains the codebase (like DeepWiki/RAG-based tools do), **and**
2. Reconstructs and teaches the *likely order the project was built in* — a step-by-step "how this was made" narrative that no major existing tool currently does.

## Why this is different from existing tools
Existing tools (DeepWiki, CodeAutopsy, code2tutorial, Git Pitcher, gitreverse) explain **what a codebase is and how it's structured now**. None of them attempt genuine **build-sequence reconstruction** — inferring and narrating the order in which the project was likely developed. That is this project's core differentiator.

## Documents in this set
- `README.md` — this file, high-level overview
- `ARCHITECTURE.md` — the full 11-layer system design
- `TECH_STACK.md` — chosen tools/frameworks per component, and why
- `DECISIONS_LOG.md` — chronological record of every major decision made, including rejected alternatives and reasoning (so nothing gets re-argued from scratch later)
- `ROADMAP.md` — internal build-and-test order (even though the shipping milestone is the full finished product, not incremental releases)
- `OPEN_QUESTIONS.md` — items intentionally deferred, to revisit before or during later stages

## Core project facts (quick reference)
- **Builder:** Solo developer, vibe-coding with research backing
- **Milestone:** One single final milestone — full product, not phased MVP releases (explicit choice, see DECISIONS_LOG.md)
- **v1 scope:** GitHub links only (no zip yet), all 9 target languages, all 11 layers
- **File limit v1:** 150+ files (scaling to 1800–2900+ in later versions)
- **Monetization:** Free at launch, paid tiers added later
- **AI usage philosophy:** Use non-AI/deterministic methods wherever possible; use AI only where no other method can do the job (this describes most of Layers 4, 5, 6, 7 — it does not mean "minimal AI usage" overall)
