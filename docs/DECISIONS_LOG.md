# Decisions Log

This is a chronological record of every major decision made during planning, including what was rejected and why — so nothing needs to be re-argued from scratch in a future session.

---

### Core concept
**Decided:** Build a platform that reverse-engineers user-submitted repos, explaining both what the code does AND reconstructing the likely build sequence, then teaches it back to the user.
**Rejected alternative framing:** Pure "explain this codebase" tool (already well-served by DeepWiki, CodeAutopsy, code2tutorial).

### Model approach: LLM APIs vs. training custom models
**Decided:** Use existing LLM APIs (Claude, Gemini), not train custom ML models.
**Reasoning:** Training custom models is a multi-year, research-grade undertaking requiring data collection, labeling, compute, and ML engineering expertise — unrealistic for a solo builder on a short timeline. Even DeepWiki (well-funded, built by Cognition/Devin team) uses existing LLM APIs, not custom-trained models.
**Note:** Builder's stated "AI usage" philosophy is to prefer non-AI/deterministic methods where possible and use AI only where no other method works — this does not reduce actual AI usage in Layers 4/5/6/7, since those tasks genuinely require it.

### RAG's actual role
**Decided:** RAG (retrieval-augmented generation) is scoped specifically to Layer 5 — answering questions whose answers already exist somewhere in the repo (chat, "explain this file"). It is explicitly NOT used for build-sequence reconstruction, which is a reasoning/inference problem, not a retrieval problem.

### Repo ingestion format
**Decided:** v1 = GitHub link only. Zip file upload deferred to v2+.
**Reasoning:** Zip files have no git history (kills Layer 3 entirely) and require separate extraction/parsing logic, adding complexity for reduced signal quality in early testing.

### Language support scope
**Decided:** 9 languages for Layer 2 parsers: Python, JavaScript, TypeScript, Java, Rust, Go, C++, Shell, TLA+.
**Process:** Initial proposal included many more (HCL, SQL, and an open-ended "10-15 more" placeholder). Narrowed down via evidence: builder confirmed these are the actual languages present across their 13-15 real projects.
**Rejected from Layer 2 (but not dropped from the system — routed elsewhere):**
- HTML/CSS — minimal real dependency graph exists; routed to Layer 4 as detection-only
- SQL — different signal shape (schema/foreign-keys, not imports); routed as a separate signal type feeding Layer 6 directly
- HCL — infrastructure config, not application logic with imports/flow; routed as a separate signal type feeding Layer 6 directly

### Layer 2 internal structure
**Decided:** Split into independent per-language parser sub-modules (not split by domain/frontend-backend-database).
**Reasoning:** Domain categorization (frontend/backend/db) requires Layer 2's parsing output to already exist — splitting Layer 2 itself by domain would be circular. Language-based splitting has a clean, deterministic boundary (file extension); domain-based splitting has fuzzy, overlapping boundaries. Domain segmentation is Layer 4's job, not Layer 2's.

### Layer 6 internal structure
**Decided:** Staged into 4 steps: candidate generation → graph validation → confidence scoring → narration.
**Reasoning:** Reasoning tasks become more reliable when broken into checkable steps, particularly with a deterministic validation step that can catch LLM mistakes cheaply before they reach the user.
**Revised at Stage 4 kickoff:** the division of labor between stages was refined once implementation was imminent. Original framing had the LLM propose a full candidate order first, validated against the graph afterward. Revised: topological sort of the dependency graph (deterministic, from Layer 2's data) produces the baseline ordering and tiers first — this can never violate a real dependency fact, since it's derived directly from one. The LLM's role shifts to tie-breaking within tiers the graph can't distinguish (using segments/history), constrained so it can refine but never contradict the deterministic backbone. Cycle detection (circular dependencies) is handled explicitly as part of the baseline step, grouping cyclic files as a tied cluster rather than forcing a false linear order. This wastes less of the one piece of ground truth available (the graph) and reduces the LLM's opportunity to hallucinate causality.

### MVP scope / milestone structure
**Decided:** No phased MVP. Single milestone = the full finished product (all 11 layers, all 9 languages, working end-to-end).
**Process note:** This was debated — the alternative (single-language proof-of-concept first, then expand) was proposed as lower-risk for a solo builder, since it would surface integration problems earlier. Builder made a firm final call to proceed with the full-scope single milestone. An internal build-and-test order (see ROADMAP.md) was created afterward specifically to reduce solo-debugging risk within that single-milestone approach.

### File/repo size limits
**Decided:** v1 cap: 150+ files. Later versions (v4/v5): 1800-2900+ files.
**Process note:** Builder initially proposed 50 files for v1; raised to 150 as a better balance between covering real mid-sized projects and keeping LLM costs (Layers 4/6/7) predictable.

### Private repo access
**Decided:** GitHub OAuth App with `repo:read` scope only, short-lived tokens, no raw credential storage. Deferred to a fast-follow after public repo support ships.

### Site-level user accounts
**Decided:** Separate from GitHub OAuth (which is only for repo access). Support login via GitHub, Google, email, and phone number. Use an existing auth provider (Auth0/Clerk/Supabase Auth) rather than building from scratch.

### Security (Layer 10)
**Decided:** Added as its own dedicated layer, not folded into ingestion. Covers sandboxed/isolated code parsing, zip bomb protection, and secret detection/redaction before storage or LLM calls.

### Async processing (Layer 11)
**Decided:** Added as its own layer using Celery/RQ, with a frontend polling mechanism for progress. Required because full pipeline processing exceeds normal HTTP request timeouts.

### Billing / abuse prevention
**Decided:** Add a billing system (Stripe) alongside rate limiting, rather than rate-limiting alone. Free tier = limited analyses/month with smaller repos; paid tier = higher limits, larger repos, private repo support.

### Data retention & consent
**Decided:** User-consented data collection covers both prompt-improvement use and potential future training use. Default 30-day auto-delete of analysis results unless user opts to keep longer.

### Trust / hallucination handling
**Decided:** Adopt DeepWiki's approach — every claim in the output links back to the specific file/line it came from, so users can verify rather than blindly trust the output.

### Legal/IP
**Decided:** Terms-of-service wording deferred until project is finished, but the underlying safe technical behavior (secret redaction, data deletion mechanism) is built into the system now rather than bolted on later.

### Layer 4/5 scope upgrade (post-Stage 2)
**Decided:** Layer 4 (Segmentation) keeps folder/naming-convention rules as the primary classification signal, but adds dependency-graph community detection (using Layer 2's already-produced import graph) as a secondary signal for files conventions can't confidently classify. Layer 5 (RAG) upgrades from plain vector-only retrieval to hybrid vector+graph retrieval, using the same existing dependency graph to pull in structurally-connected files alongside semantically-similar ones.
**Rejected alternative:** A more radical redefinition proposed mid-session — "dynamic AST chunking with overlap" as part of Layer 4 — was rejected as a scope conflation. Chunking-with-overlap is an embedding/retrieval concern (Layer 5's job), not a domain-classification concern (Layer 4's job); adopting it as written would have merged the two layers' responsibilities.
**Reasoning:** Both upgrades are cheap because Layer 2 already computes the dependency graph — this is reusing existing data, not standing up new infrastructure or a new ML subsystem. This is different in kind from earlier scope-creep patterns (e.g., "add more languages") because it has a clear technical justification tied to data already on hand, not just ambition for its own sake.

### Layer 4 domain taxonomy: added "core/library" category
**Decided:** Add a 7th domain category, `core`/`library`, alongside frontend/backend/database/docs/config/tests.
**Reasoning:** Real-world validation against systems/library repos (tokio: 53% uncategorized, tlaplus: 43% uncategorized) showed the original 6-category taxonomy was designed around application-shaped repos (frontend+backend+database) and didn't fit repos that are primarily core library logic with no UI or persistence layer. Rather than accept a high uncategorized rate as permanent for an entire class of real repos, added a category that honestly captures "this is core logic, not one of the other 5 buckets" instead of forcing it into "uncategorized" by default.
**Note:** This still preserves the "don't force-guess" principle — `uncategorized` remains for files that don't confidently fit ANY of the 7 categories, including `core`. This is additive, not a replacement of the uncategorized fallback.

### Operational decisions (lower-stakes, builder deferred to assistant's call)
- Re-analysis/caching: cache key = repo URL + commit hash, so updated repos trigger fresh analysis automatically
- Notification on completion: in-app only for v1, no email service yet
- Content moderation: passive/reactive for v1 (report mechanism + manual takedown), no active scanning
- API design: backend built API-first (clean separation from UI) from day one, so a future public API is a config change, not a rewrite
- Testing strategy: manual verification against builder's own 13-15 real repos as primary test suite, plus lightweight automated tests specifically for Layer 2's parsers
- CI/CD: auto-deploy from day one via GitHub Actions
- Analytics: PostHog free tier from day one
- Backup: daily automated database backup to cloud storage

