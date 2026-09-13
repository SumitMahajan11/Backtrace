# System Architecture — 11 Layers

## Layer 1 — Ingestion
Takes a GitHub link (v1) or zip file (v2+) → clones/extracts → filters out junk (node_modules, .git internals except commit history, binaries, build artifacts) → produces a clean file tree + raw file contents.

**Depends on:** nothing (entry point)
**Feeds:** Layer 2, Layer 3, Layer 10

---

## Layer 2 — Static Structural Analysis (per-language parser modules)
No AI. Deterministic parsing of imports, dependencies, and entry points, done via **independent per-language parser sub-modules** so no single module's failure breaks the others.

**Locked language list (evidence-based, from the builder's own 13–15 real repos):**
Python, JavaScript, TypeScript, Java, Rust, Go, C++, Shell, TLA+

**Explicitly NOT parsed here (handled elsewhere — see below):**
- HTML/CSS → detected/located only, feeds Layer 4 (minimal real dependency graph exists)
- SQL → separate schema/foreign-key signal type, feeds Layer 6 directly
- HCL (Terraform-style config) → separate infrastructure signal type, feeds Layer 6 directly

**Depends on:** Layer 1
**Feeds:** Layer 4, Layer 5, Layer 6

---

## Layer 3 — Historical Signal Extraction
If GitHub link (has git history): pulls commit log, commit order, commit messages, file-creation timestamps via GitPython.
If zip only (v2+): this layer is skipped entirely — no fabricated history, output stays honestly "structure-based guess."

**Depends on:** Layer 1
**Feeds:** Layer 6

---

## Layer 4 — Segmentation
Groups files into logical domains (frontend / backend / database / docs / config / tests) using Layer 2's parser output plus folder/file-naming conventions. Rule-based first; LLM assist only for genuinely ambiguous cases. Files that can't be confidently categorized are marked **"uncategorized"** rather than force-guessed — this is the deliberate fallback rule to reduce mistake rate.

**Depends on:** Layer 2
**Feeds:** Layer 6, Layer 7

---

## Layer 5 — RAG Engine (Retrieval-Augmented Generation)
Chunks and embeds code (from Layer 1/2 output) into a vector store (FAISS). Powers "explain this file/function" and the conversational chat Q&A feature. This is a pure **retrieval** system — it answers questions whose answers already exist somewhere in the repo.

**Depends on:** Layer 1, Layer 2
**Feeds:** Layer 7

---

## Layer 6 — Sequence Reasoning Engine (the core differentiator)
Unlike Layer 5, this is a **reasoning/inference** system — the answer (build order) doesn't exist explicitly anywhere in the repo; it must be inferred. Internally staged into four steps:

1. **Candidate generation** — LLM proposes a rough build order using the dependency graph (Layer 2) + segments (Layer 4) + SQL/HCL signals
2. **Graph validation** — deterministic check that the proposed order doesn't violate hard dependency facts (non-AI, catches LLM mistakes cheaply)
3. **Confidence scoring** — flags which parts of the sequence are "solid" (backed by real commit history from Layer 3) vs. "guessed" (structure-only inference)
4. **Narration** — turns the validated, scored sequence into the actual step-by-step teaching explanation

**Depends on:** Layer 2, Layer 3, Layer 4
**Feeds:** Layer 7

> [!NOTE]
> **Known Technical Debt & Architectural Limitation (Intra-Package Symbol Resolution):**
> Intra-package symbol resolution for same-package files (e.g. Go package directories, Python same-folder modules) relies on regex word-boundary name matching and a generic symbol blacklist (`app`, `cli`, `json`, `data`, `handler`, `config`, etc.). This is explicitly a heuristic stopgap. On unseen external repositories, non-blacklisted common domain names (`Client`, `Store`, `Manager`) can cause false bidirectional dependency edges. The long-term architectural resolution is introducing full AST symbol tables / LSP scope indexing.

---

## Layer 7 — Synthesis / "Manager"
Combines Layer 4 (structure), Layer 5 (explanations), and Layer 6 (sequence) into one coherent narrative, rather than three disconnected outputs. This is what makes the product feel like one system instead of three bolted-together tools.

**Depends on:** Layer 4, Layer 5, Layer 6
**Feeds:** Layer 8

---

## Layer 8 — Output Formatting
Renders Layer 7's unified output as a report, interactive flowchart, chat interface, or optional quiz — whichever the user selects. Pure presentation; no new reasoning happens here.

**Depends on:** Layer 7
**Feeds:** end user

---

## Layer 9 — Storage / Consent / Caching
- Caches analysis results keyed by **repo URL + commit hash** (not just repo URL, so updated repos always get fresh analysis instead of serving stale cached results)
- Stores user data only with explicit consent; consent covers both "prompt improvement" and "potential future training" uses
- Default 30-day auto-delete of analysis results unless the user opts to keep them longer
- Cleans up temporary clone/extract folders after processing
- Daily automated backup of the database to cloud storage

**Depends on:** interacts with all layers
**Feeds:** all layers (shared service)

---

## Layer 10 — Security / Sandboxing
Added specifically because the system processes **untrusted user-submitted code**:
- All parsing/analysis of uploaded code runs inside an isolated sandbox (containerized, no network access, resource-limited, read-only filesystem where possible)
- Zip bomb protection: decompression size caps, not just file-count limits
- Secret detection: regex/entropy-based scanning to detect and redact API keys, tokens, and passwords before storage or before sending content to any LLM

**Depends on:** Layer 1
**Feeds:** Layer 2 (only sandboxed/cleaned content proceeds)

---

## Layer 11 — Job Queue / Progress Tracking
Because full pipeline processing (especially with LLM calls in Layers 4/6/7 and embeddings in Layer 5) takes far longer than a normal HTTP request timeout:
- Background job queue (Celery or RQ) orchestrates the pipeline running layer-by-layer
- Frontend polls a status endpoint to show live progress
- In-app completion notification for v1 (no email service yet — deferred as a later addition)

**Depends on:** coordinates all layers
**Feeds:** Layer 8 (progress UI), end user

---

## Layer dependency flow (simplified)

```
Layer 1 (Ingestion)
   ├──> Layer 10 (Security/Sandboxing)
   │        └──> Layer 2 (Structural Analysis, per-language)
   │                 ├──> Layer 4 (Segmentation)
   │                 └──> Layer 5 (RAG Engine)
   └──> Layer 3 (Historical Signals)
            └──> Layer 6 (Sequence Reasoning) <── also depends on Layer 2 + Layer 4

Layer 4 + Layer 5 + Layer 6 ──> Layer 7 (Synthesis/Manager)
                                     └──> Layer 8 (Output Formatting) ──> User

Layer 9 (Storage/Consent/Caching) and Layer 11 (Job Queue/Progress)
   run alongside all of the above as shared services.
```

## Adjacent subsystems (outside the pipeline layers)
- **Site auth:** GitHub, Google, email, phone login (separate from GitHub OAuth used for repo access)
- **Private repo access:** GitHub OAuth App, `repo:read` scope only, short-lived tokens, no raw credential storage
- **Billing:** Free tier (limited analyses/month, smaller repos) + paid tier (higher limits, larger repos, private repo support)
- **Monitoring:** Sentry (free tier) for error tracking
- **Analytics:** PostHog (free tier) for usage tracking
- **CI/CD:** GitHub Actions → auto-deploy to Render/Vercel
