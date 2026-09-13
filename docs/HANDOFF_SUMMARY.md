# HANDOFF SUMMARY — Full Context for Continuing This Project

> This document is written so you (the next AI agent, or the user briefing one) can pick up this project with zero context loss. Read this in full before doing anything else. Companion documents referenced throughout are: `README.md`, `ARCHITECTURE.md`, `TECH_STACK.md`, `DECISIONS_LOG.md`, `ROADMAP.md`, `OPEN_QUESTIONS.md`, and the Stage 1 build prompts (`PROMPT_1A_INGESTION.md`, `PROMPT_1B_SECURITY_SANDBOXING.md`, `PROMPT_1C_STORAGE_SKELETON.md`).

---

## 1. What this project is

A platform where a user submits a GitHub repository URL (zip upload deferred to v2), and the system:
1. Analyzes and explains the codebase — similar to existing tools like DeepWiki
2. **Reconstructs and narrates the likely order the project was originally built in** — a step-by-step "how this was made" teaching experience

**The second part is the genuine differentiator.** Market research (done via live web search during planning) confirmed that existing tools — DeepWiki (Cognition/Devin, backed by $696M+ raised), CodeAutopsy, code2tutorial.com, Git Pitcher, gitreverse, tutorial-creator — all explain **what a codebase is and how it's structured now**. None of them attempt genuine build-sequence inference. That gap is this project's core bet.

## 2. Who's building this and how

- **Solo developer.** No team, no plans to add one.
- Has built **13-15 real projects** previously via "vibe coding" (AI-assisted rapid development), across **9 confirmed languages**: Python, JavaScript, TypeScript, Java, Rust, Go, C++, Shell, TLA+. These real repos are both the reason the language list was chosen (evidence-based, not aspirational) and will serve as the primary test suite going forward.
- Approach to this project: vibe-coded but backed by real research/planning (this entire conversation was that planning process).
- **Budget: free/minimal wherever possible.** Will pay for LLM API usage only when genuinely necessary; avoids other paid infra until forced to.

## 3. How this user works (important for the next agent's own behavior)

The user explicitly requested, mid-conversation, that any AI assistant:
- **Counter-argue and challenge ideas rather than agreeing by default.** This rule was stated explicitly and should be treated as standing instruction, not a one-time request.
- Give short, direct points — not lecture-style explanations.
- Ask clarifying questions when scoping decisions, but the user will often override suggestions and make a final call — once they've made a firm decision (e.g., "all languages, all layers, single milestone, I won't negotiate this"), stop arguing that specific point and adapt around it instead of re-litigating it.
- Wants **maximum ambition/scope** ("think big," "don't underestimate my commitment") — but has also been receptive to technical pushback when it's framed as an architecture/engineering constraint rather than a doubt about their ability or work ethic. Framing matters: "this adds operational overhead" lands better than "this is too much for you."
- Wants detailed, well-structured build prompts broken out **per layer/component**, not one giant prompt per phase — this was the user's own suggestion and was adopted going forward.
- Wants documentation to stay current with minimal manual effort from them — hence this whole document set exists and should be updated (not replaced) as the project evolves.

## 4. Full system architecture — 11 layers

(Full detail lives in `ARCHITECTURE.md`; summarized here for completeness.)

1. **Ingestion** — clone repo, filter junk, produce clean file tree + content
2. **Static Structural Analysis** — per-language parser modules (NOT split by domain — split by language, since domain categorization requires this layer's output to already exist, making domain-based splitting circular). Covers: Python, JS, TS, Java, Rust, Go, C++, Shell, TLA+. HTML/CSS, SQL, and HCL are explicitly NOT parsed here — see below.
3. **Historical Signal Extraction** — git commit log/order/messages/timestamps, only available when ingesting via GitHub link (not zip, since zip has no history)
4. **Segmentation** — groups files into frontend/backend/database/docs/config/tests; HTML/CSS detection happens here (not Layer 2); files that can't be confidently categorized are marked "uncategorized" rather than force-guessed
5. **RAG Engine** — retrieval-augmented generation; powers chat/Q&A/"explain this file." This is explicitly a **retrieval** system for answers that already exist in the repo — NOT used for sequence reconstruction.
6. **Sequence Reasoning Engine** — the core differentiator. This is a **reasoning/inference** problem, not retrieval, since the build order isn't explicitly written anywhere. Internally staged: (1) candidate generation via LLM using dependency graph + segments + SQL/HCL signals, (2) deterministic graph validation to catch LLM mistakes cheaply, (3) confidence scoring (flags "solid"/history-backed vs "guessed"/structure-only parts), (4) narration into the final teaching explanation. SQL and HCL feed into this layer directly as separate signal types (schema relationships, infrastructure config) rather than being Layer 2 parsers.
7. **Synthesis/"Manager"** — combines Layers 4, 5, 6 outputs into one coherent narrative instead of three disconnected outputs
8. **Output Formatting** — renders as report, interactive flowchart, chat, or optional quiz, per user choice
9. **Storage/Consent/Caching** — caches by **repo URL + commit hash** (not URL alone, so updated repos get fresh analysis); stores user data only with consent (used for both prompt improvement and potential future model training); default 30-day auto-delete unless user opts to keep longer; daily DB backups
10. **Security/Sandboxing** — added specifically because the system processes untrusted code. See Section 6 below for full detail (this was expanded significantly after initial underspecification).
11. **Job Queue/Progress Tracking** — Celery/RQ-based background processing since full pipeline runs exceed normal HTTP timeouts; frontend polls for progress; in-app-only completion notification for v1 (no email service yet)

**Adjacent subsystems (outside the 11 pipeline layers):**
- Site-level user accounts: GitHub, Google, email, phone login (separate from the GitHub OAuth used specifically for private repo access)
- Private repo access: GitHub OAuth App, `repo:read` scope only, short-lived tokens, no raw credential storage — deferred as a fast-follow after public repos work
- Billing: Stripe; free tier (limited analyses/month, smaller repos) + paid tier (higher limits, larger repos, private repo support)
- Monitoring: Sentry (free tier)
- Analytics: PostHog (free tier)
- CI/CD: GitHub Actions → auto-deploy to Render/Vercel

## 5. Tech stack (full detail in `TECH_STACK.md`)

- **Backend:** Python 3.11+, FastAPI
- **Frontend:** Next.js (React) + Tailwind CSS
- **Vector store:** FAISS (in-process, free)
- **LLM APIs:** Claude (prioritized for Layer 6 reasoning) and Gemini (free tier, used for cheaper bulk tasks like Layer 5 embeddings), abstracted behind one interface so providers can be swapped later
- **Database:** SQLite for v1 → Postgres later (schema/data-access layer built via SQLAlchemy so migration is a connection-string change, not a rewrite)
- **Hosting:** Render/Railway (backend, free tier) + Vercel (frontend, free tier) — note free tiers sleep after inactivity
- **Auth:** existing provider (Auth0/Clerk/Supabase Auth), not hand-rolled
- **Job queue:** Celery or RQ
- **Git operations:** GitPython
- **Per-language parsers:** Python `ast` (built-in), JS/TS `@babel/parser`/`ts-morph`, Java `javalang`, Rust `syn` (via helper binary), Go `go/parser` (via helper binary), Shell (custom lightweight parser), C++ (`libclang` bindings — not yet confirmed, flagged as open question), TLA+ (detect-presence-only, not full parsing), HTML/CSS (detect-only, feeds Layer 4)

## 6. Security threat model (this was significantly expanded after initial critique — treat this as the authoritative version)

The system must assume every submitted repo is potentially hostile. Full detail lives in `PROMPT_1B_SECURITY_SANDBOXING.md`. Key categories covered:
- Code execution during clone/checkout (git hooks, `.gitattributes` filter/diff drivers, LFS smudge filters) — all must be disabled before any git operation runs
- Filesystem escape (symlinks pointing outside sandbox, path traversal via crafted filenames)
- Network abuse (SSRF via crafted clone URLs — must validate resolved IPs aren't internal/private ranges; full network cutoff after clone phase completes, not just "no network access" vaguely stated)
- Resource exhaustion (zip bombs — decompression size limits independent of file count; ReDoS in any regex, mitigated via linear-time regex engines or timeouts; deep directory nesting limits)
- Supply chain pull-in (git submodules must NOT be auto-fetched, only flagged as metadata)
- Secrets exposure (entropy-based + pattern-based scanning, redact in place, log counts only, never expose which patterns matched)
- Container escape (non-root user, read-only filesystem, dropped capabilities, seccomp profiles, resource limits, no privileged mode, no Docker socket/host mounts)
- Race conditions (randomly-generated unpredictable temp directory names, restrictive permissions from creation)

**Important technical correction made during planning:** the original ingestion design specified a shallow git clone, which would have silently broken Layer 3's need for full commit history later. Corrected approach: full clone with `--no-checkout`, then checkout HEAD only — gets full history cheaply while still producing a clean working tree.

## 7. Key decisions and the reasoning behind them (full chronological log in `DECISIONS_LOG.md`)

- **LLM APIs, not custom-trained models.** Training custom ML models was considered and explicitly rejected — even DeepWiki (well-funded, dedicated team) uses existing LLM APIs, not custom training. This was a firm technical recommendation the user ultimately accepted.
- **RAG is scoped only to Layer 5** (retrieval of answers that already exist in-repo). It does NOT power sequence reconstruction (Layer 6), which is a reasoning/inference task RAG structurally cannot solve, since the answer isn't written down anywhere in the repo to retrieve.
- **No phased MVP — single milestone is the full finished product** (all 11 layers, all 9 languages, working end-to-end). This was debated at length: the alternative (build one language end-to-end first, then expand) was proposed as lower-risk for a solo builder, since it would surface integration problems earlier and provide a smaller morale-sustaining checkpoint. **The user made a firm, final, non-negotiable call to proceed with the single full-scope milestone.** An internal build-and-test order (`ROADMAP.md`) was created specifically to reduce solo-debugging risk within that single-milestone approach — but be aware there is no smaller "shippable" checkpoint before the entire system is done. This is the single highest-risk decision in the whole plan and should not be re-argued, but the next agent should stay aware of the tradeoff it implies (long stretch with nothing demoable).
- **Language scope (9 languages) was narrowed from an open-ended wishlist to an evidence-based list** by checking the user's actual 13-15 real repos, rather than guessing at "important" languages. This process is worth repeating if language scope is ever revisited — ask for real evidence, not aspiration.
- **File/repo size limits:** v1 cap is 150+ files (raised from an initial 50-file proposal), scaling to 1800-2900+ files in v4/v5.
- **Zip upload deferred to v2** — the one scope-narrowing concession the user did accept, because zip files have no git history (breaks Layer 3) and add separate parsing logic for reduced signal quality early on.

## 8. Current progress / what's actually been built so far

**Nothing has been coded yet.** This entire conversation was planning and specification. What exists right now:
- Full architecture spec (documents listed at the top of this file)
- Three detailed build prompts for **Stage 1 only** (Foundation): 
  - `PROMPT_1B_SECURITY_SANDBOXING.md` (build first)
  - `PROMPT_1A_INGESTION.md` (build second, runs inside the sandbox from 1B)
  - `PROMPT_1C_STORAGE_SKELETON.md` (build third)
- These three prompts replace an earlier, less-detailed single "Stage 1" prompt, which is now superseded/discardable

**Recommended tool for actual building:** Claude Code (terminal or desktop app) — this chat interface is meant for planning/prototyping/document generation, not maintaining a large persistent multi-service codebase over months. This was explicitly recommended to the user.

## 9. Internal build order (full detail in `ROADMAP.md`)

Reminder: this is a build **sequence** for the solo developer's own sanity, not a phased release plan — nothing ships until all of it is done, per the user's decision in Section 7.

- **Stage 1 — Foundation:** Layer 1 (Ingestion), Layer 9 (Storage skeleton), Layer 10 (Security/Sandboxing) — **prompts already written, ready to build**
- **Stage 2 — Structural Backbone:** Layer 2 (build one language parser fully first, then replicate pattern across remaining 8), Layer 3 (git history extraction, parallel-buildable)
- **Stage 3 — Understanding Layer:** Layer 4 (Segmentation, depends on Layer 2 output existing), Layer 5 (RAG engine, parallel-buildable with Layer 4)
- **Stage 4 — Reasoning Core:** Layer 6, requires Layers 2+3+4 all existing first; build its 4 internal stages in strict order
- **Stage 5 — Integration:** Layer 7 (needs 4+5+6 all producing real output), Layer 8 (needs Layer 7 stable), Layer 11 (wire in once there's a real pipeline worth queuing)
- **Stage 6 — Hardening:** full Layer 9, remaining language parsers, edge cases, auth/billing/monitoring/analytics/CI-CD

**Next immediate action per this roadmap:** build Stage 1 using the three prompts already written, verify against acceptance criteria in each prompt, then request/generate the Stage 2 prompts (per-language parsers) the same detailed, split-by-component way.

## 10. Open questions still deferred (full list in `OPEN_QUESTIONS.md`)

- Legal/ToS wording (safe technical behavior is built in already; actual documents not yet drafted)
- Exact billing tier numbers (free analyses/month, size thresholds for paywall, any paid-only features)
- Content moderation escalation process (report mechanism decided, review process not yet designed)
- C++ parsing library choice (`libclang` bindings proposed, not confirmed)
- TLA+ parsing depth (currently "detect presence only" — revisit if it needs to be deeper)
- Public API exposure (backend is being built API-first so this is a future config decision, not an architecture change)
- Email notifications (deferred, in-app only for v1)

## 11. Instructions for the next agent

1. Read all six companion documents in full before making any new recommendations — don't re-derive decisions already made and logged in `DECISIONS_LOG.md`.
2. Maintain the "counter-argue, don't just agree" working style described in Section 3 — this is a standing preference, not a one-off.
3. Do not attempt to re-open the "single milestone, no phased MVP" decision — it was already argued in both directions and firmly decided. Adapt planning around it instead.
4. Continue the established pattern for future build prompts: **detailed, split per layer/component (not per stage), with explicit threat modeling for anything security-relevant, explicit "out of scope" sections, and concrete acceptance criteria** — this pattern was specifically requested and refined over multiple iterations, don't regress to shorter/vaguer prompts.
5. When new decisions are made, **append to `DECISIONS_LOG.md` rather than rewriting it**, and update `ARCHITECTURE.md`/`ROADMAP.md` only if the change actually affects layer design or build order.
6. The user has 13-15 real repos available as ground truth for testing — use them as the reference for validating language coverage, parser correctness, and eventually Layer 6's sequence-reasoning quality.
