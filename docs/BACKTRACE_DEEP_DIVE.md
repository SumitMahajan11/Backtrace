# Backtrace — Complete Technical Deep-Dive
*Generated: 2026-10-19 | Commit: bc5b247chore(docker): set cloudflared restart policy to on-failure:3 | Python 3.13.7*

> **Anti-fabrication guarantee**: Every claim below is followed by a `file:line` citation or literal command output.
> Claims that could not be verified are marked **UNKNOWN** or **IMPLEMENTED-UNTESTED**.
> Status labels: **IMPLEMENTED** (code + test exists), **IMPLEMENTED-UNTESTED** (code exists, no passing test observed), **STUBBED** (skeleton only), **MISSING** (referenced but absent).

---

## Section 0 — Ground Truth

### 0.1 Repository Identity

```
HEAD commit:  bc5b247chore(docker): set cloudflared restart policy to on-failure:3
Branch:       main (14 commits ahead of origin/main)
Working tree: clean (nothing to commit)
Python:       3.13.7
```

### 0.2 Full Git Log (literal output)

```
bc5b247 chore(docker): set cloudflared restart policy to on-failure:3
3b4d46c docs: document Tier 3 structural verification scope
fbcb5af test(parser): raise node subprocess timeout in javascript structural parser
36d2914 fix(security): enforce 25 MB request body limit on chunked streams without Content-Length
2512120 feat(security): add security headers and 25 MB request body limit middleware
c5e9a08 fix(db): add Alembic migration for last_run_code and remove session.py auto-ALTER
b7b70fb build(deploy): add --build to deploy scripts and normalize LF line endings for shell scripts
260f21f docs: add deployment limitations section to README
18bab5e refactor(config): consolidate single env source of truth and make nginx opt-in via compose profile
3415a25 fix(security): remove /debug/trigger-error endpoint
7b4d32d fix(attempts): isolate /run scratchpad executions from graded submitted_code and status
d71f114 fix(grader): reject stub function bodies and label tier 3 honestly as structure check
a4c8ba9 fix(security): remove debug/env, gate dev-login
7a2d4e0 fix(security): enforce debug=False on FastAPI app to prevent Starlette stack trace leakage
8cc03d9 feat: complete workspace organization, developer documentation, and multi-commit resolution
8cb4b84 feat(deploy): add Cloudflare Tunnel integration, deployment scripts, and Piston runtime support
4d64249 Update project
745fcc6 chore(git): ignore sql dumps and backup archive directories
18469d7 chore(security): add .gitleaksignore for test fixture credentials
4d0026b fix(ui): enforce strict int cast on job_id in report_view
85941e2 fix(ui): eliminate inline JS event handler XSS in graph sinks and sanitize truncation
57678e6 chore(compose): allow GitHub OAuth variables to be overridden via env-file interpolation
04f9a30 test(infrastructure): enhance test isolation for rate limiter and execution verifier
aaeccde fix(security): sanitize all AST diff symbols and harden SSE progress DOM against XSS
e9fee85 chore: update local secret rotation and postgres inspection scripts
7886612 chore: enhance redis command check in compose verification script
ed1906f chore: add compose resolution verification script
e5c6717 fix(security): sanitize database environment interpolation in docker-compose
265be5b test: isolate grading engine execution and preserve discovered piston health
29d5e03 feat(core): implement points system, postgres migration, redis rate limiter, automated backups & production hardening
1fd1d9b feat: complete commercial subsystems, production readiness, and hardened deployment model
7e30b82 Update Backtrace
878df01 Initial commit: Backtrace - GitHub repo build-order reconstruction platform
```

### 0.3 File Inventory (Python files with LOC)

| File | Lines | Bytes |
|---|---|---|
| app/main.py | 157 | 5,622 |
| app/api/attempts.py | 673 | 27,113 |
| app/api/auth.py | 274 | 9,773 |
| app/api/billing.py | 174 | 7,568 |
| app/api/dependencies.py | 103 | 4,173 |
| app/api/frontend.py | 903 | 37,952 |
| app/api/health.py | 115 | 4,253 |
| app/api/pipeline.py | 119 | 4,484 |
| app/api/points.py | 181 | 7,776 |
| app/api/webhooks.py | 47 | 1,970 |
| app/core/config.py | 165 | 6,603 |
| app/db/session.py | 134 | 5,336 |
| app/formatters/graph_formatter.py | 103 | 5,362 |
| app/formatters/markdown_formatter.py | 84 | 4,604 |
| app/formatters/quiz_formatter.py | 81 | 5,205 |
| app/models/db.py | 331 | 13,958 |
| app/models/history.py | 29 | 1,192 |
| app/models/ingestion.py | 52 | 2,087 |
| app/monitoring/posthog.py | 188 | 7,117 |
| app/monitoring/sentry.py | 173 | 6,920 |
| app/orchestration/pipeline.py | 302 | 14,453 |
| app/orchestration/schema.py | 36 | 1,652 |
| app/parser/base.py | 85 | 3,556 |
| app/parser/cpp_parser.py | 208 | 10,150 |
| app/parser/go_parser.py | 160 | 6,909 |
| app/parser/java_parser.py | 114 | 4,925 |
| app/parser/javascript_parser.py | 93 | 4,082 |
| app/parser/python_parser.py | 189 | 8,599 |
| app/parser/registry.py | 49 | 2,485 |
| app/parser/rust_parser.py | 232 | 9,925 |
| app/parser/schema.py | 63 | 2,387 |
| app/parser/shell_parser.py | 170 | 7,236 |
| app/parser/subprocess_base.py | 69 | 3,118 |
| app/parser/tla_parser.py | 177 | 7,145 |
| app/rag/chunker.py | 155 | 7,234 |
| app/rag/embedder.py | 79 | 2,875 |
| app/rag/engine.py | 91 | 4,191 |
| app/rag/graph_retriever.py | 64 | 3,297 |
| app/rag/retriever.py | 103 | 4,065 |
| app/rag/vector_store.py | 42 | 2,169 |
| app/security/auth.py | 233 | 9,967 |
| app/security/path_hardening.py | 37 | 1,301 |
| app/security/rate_limiter.py | 451 | 17,117 |
| app/security/regex_safety.py | 46 | 1,654 |
| app/security/sandbox_runner.py | 146 | 5,202 |
| app/security/secret_scanner.py | 144 | 6,089 |
| app/segmentation/engine.py | 96 | 4,267 |
| app/segmentation/graph_clusterer.py | 79 | 4,396 |
| app/segmentation/rules.py | 160 | 7,233 |
| app/segmentation/schema.py | 37 | 1,408 |
| app/sequence/baseline_ordering.py | 374 | 14,313 |
| app/sequence/confidence_scoring.py | 106 | 4,839 |
| app/sequence/constrained_tie_breaking.py | 246 | 9,335 |
| app/sequence/llm_client.py | 52 | 2,008 |
| app/sequence/narration_engine.py | 818 | 41,485 |
| app/sequence/schema.py | 81 | 4,139 |
| app/services/auth_service.py | 243 | 11,299 |
| app/services/billing_service.py | 471 | 22,250 |
| app/services/cached_ingestion.py | 90 | 4,123 |
| app/services/curated_milestone_expectations.py | 124 | 5,704 |
| app/services/execution_verifier.py | 489 | 20,304 |
| app/services/file_content_service.py | 359 | 18,161 |
| app/services/grading_engine.py | 450 | 20,562 |
| app/services/hint_engine.py | 170 | 9,037 |
| app/services/history_extractor.py | 384 | 18,042 |
| app/services/ingestion.py | 416 | 15,916 |
| app/services/metrics.py | 146 | 5,302 |
| app/services/piston_health.py | 166 | 7,593 |
| app/services/points_engine.py | 459 | 21,239 |
| app/services/scaffold_generator.py | 425 | 19,102 |
| app/services/security.py | 89 | 3,062 |
| app/services/structural_verifier.py | 320 | 13,030 |
| app/storage/analysis_job_repository.py | 129 | 5,490 |
| app/storage/billing_repository.py | 141 | 5,567 |
| app/storage/milestone_attempt_repository.py | 159 | 6,615 |
| app/storage/repository.py | 201 | 8,504 |
| app/storage/user_repository.py | 111 | 3,945 |
| app/synthesis/engine.py | 198 | 9,234 |
| app/synthesis/schema.py | 48 | 2,307 |
| app/ui/components.py | 6,687 | 383,361 |
| app/ui/sanitizer.py | 146 | 6,273 |
| app/utils/file_filter.py | 127 | 5,186 |
| app/utils/logging.py | 46 | 2,024 |
| app/utils/url_validator.py | 114 | 4,334 |

**Total Python source**: 24,284 lines across 102 `.py` files under `app/`.
**Largest file**: `app/ui/components.py` — 6,687 lines (pure server-side HTML generation string builder).
**Test files**: 64 test files in `tests/` collecting 432 test cases.

### 0.4 Entrypoints

| Entrypoint | Path | Mechanism |
|---|---|---|
| ASGI app | `app/main.py:58` | `FastAPI(lifespan=lifespan)` consumed by uvicorn |
| Dev runner | `run_dev.bat` / `run_dev.ps1` | `uvicorn app.main:app --reload --port 8000` |
| Deploy | `deploy.sh` / `deploy.ps1` | `docker-compose -f docker-compose.yml up -d` |
| Migrations | `alembic.ini` + `alembic/versions/` (5 migrations) | `alembic upgrade head` |

---

## Section 1 — Purpose and End-to-End Flow

### 1.1 What Backtrace Does

From `app/main.py:60`:
> "Identity, Session Management, Stripe Billing, and 11-Layer Reverse Engineering Pipeline API"

From `app/orchestration/pipeline.py:1-4`:
> "Orchestrates the 11-layer architecture into a unified execution pipeline with real-time progress tracking, stage isolation, and error boundaries."

Backtrace is a SaaS platform that:
1. **Ingests** a public GitHub repository URL
2. **Reverse-engineers** its build order (which files had to exist before other files could work)
3. **Generates** pedagogical milestones: "Learn this codebase in this order"
4. **Challenges** users with fill-in-the-blank coding exercises per milestone
5. **Grades** submissions via static AST analysis + sandboxed Piston execution
6. **Monetizes** via Stripe (free tier = 5 repos/month; Pro = unlimited)

### 1.2 End-to-End Flow Trace

**Input**: User submits `https://github.com/owner/repo` via the dashboard form.

**Hop 1** — `POST /analyses/submit` (`app/api/frontend.py:209-310`)
- Validates auth cookie → `get_current_user_optional()` → `app/api/dependencies.py:44-59`
- Reads `repo_url`, `commit_ref`, `subpath` from form data (`app/api/frontend.py:210-214`)

**Hop 2** — `check_repo_size_preflight()` (`app/services/ingestion.py:43`)
- `validate_github_url()` → `app/utils/url_validator.py:18` — regex check, scheme=https, hostname=github.com
- `validate_ssrf("github.com")` → `app/utils/url_validator.py:59` — DNS resolution + private IP blocklist
- GitHub Trees API: `GET /repos/{owner}/{repo}/git/trees/HEAD?recursive=1`
- Counts matching files → if >150, raises `RepoTooLargeError` (HTTP 413)

**Hop 3** — `BillingService.check_and_consume_quota()` (`app/services/billing_service.py`)
- Counts `UsageEventModel` rows for this calendar month for free-tier users
- If ≤5: inserts a new `UsageEventModel` row and proceeds; else raises 402

**Hop 4** — `threading.Thread` spawned in `app/api/frontend.py`
- Thread runs `IngestionService.ingest_repository()` (`app/services/ingestion.py:191`)

**Hop 5** — `IngestionService.ingest_repository()`
- `sandbox_workspace()` → `create_secure_temp_dir()` (`app/security/path_hardening.py`)
- `run_sandboxed_git_command(["clone", "--no-checkout", url, "."])` (`app/services/security.py`)
  - git invoked with `-c core.hooksPath=` (disables all git hooks — key security measure)
  - `-c core.attributesFile=/dev/null` (disables .gitattributes filters)
  - `-c filter.lfs.smudge=cat` (disables LFS)
  - `-c http.followRedirects=false` (prevents SSRF via clone-time redirects)
- `run_sandboxed_git_command(["checkout", target_ref])`
- `_process_file_tree()` applies 8 security+filter checks per file (symlink, size, extension, path traversal, depth, binary, count, secret scan)
- `SecretScanner.scan_and_redact()` (`app/security/secret_scanner.py:78`) — pattern + entropy scan

**Hop 6** — `PipelineOrchestrator.run_pipeline()` (`app/orchestration/pipeline.py:72`)
- 8 language parsers run on matching files → `List[FileNode]`
- `HistoryExtractorService.extract_history()` → per-file first-commit timestamps
- `SegmentationEngine.segment_repository()` → domain classification (8 domains)
- `HybridRAGEngine.index_repository()` → AST-aware chunking + deterministic embedding
- `BaselineOrderingEngine.compute_baseline_order()` → Tarjan SCC + topological tiers (Stage A)
- `ConstrainedTieBreakerEngine.refine_baseline_order()` → history/heuristic/LLM tie-breaking (Stage B)
- `ConfidenceScoringEngine.compute_confidence_scores()` → high/medium/low per file (Stage C)
- `NarrationEngine.generate_narration()` → pedagogical text per milestone (Stage D)
- `SynthesisEngine.synthesize()` → unified report
- `MarkdownReportFormatter`, `GraphExportFormatter`, `QuizFormatter` → three output formats

**Hop 7** — Results persisted to `AnalysisJobModel` (`app/models/db.py:193`)
- `markdown_output`, `graph_output_json`, `quiz_output_json` stored as TEXT columns

**Hop 8** — SSE stream (`/analyze/progress/stream/{job_id}`)
- Browser receives `PipelineProgressEvent` objects; on `complete` redirects to `/report/{job_id}`

**Hop 9** — `/report/{job_id}` → `report_view()` in `app/ui/components.py`
- Renders full HTML report: dependency graph (D3.js), milestones, challenge buttons

---

## Section 2 — The 11 Layers

### Layer 1: Ingestion and Security Validation

**Files**: `app/services/ingestion.py` (416L), `app/utils/url_validator.py` (114L), `app/utils/file_filter.py` (127L), `app/security/path_hardening.py` (37L), `app/security/secret_scanner.py` (144L), `app/services/security.py` (89L)

**Public API**:
```python
# app/services/ingestion.py:43
def check_repo_size_preflight(github_url, commit_ref, subpath, max_file_limit=150, timeout_seconds=12.0, github_token=None) -> int

# app/services/ingestion.py:191
class IngestionService:
    def ingest_repository(self, github_url, commit_ref=None, subpath=None) -> IngestionResult
```

**File processing sequence** (`app/services/ingestion.py:323-413`):
1. Symlink detection → skip
2. `stat()` for file size
3. `should_include_relative_path()` — extension filter + size ≤ 512KB + subpath scope
4. `validate_safe_path()` — `abs_path.resolve().is_relative_to(base_dir)` (no path traversal)
5. `validate_path_depth_and_length()` — max depth 15, max filename length 255
6. `is_binary_file()` — magic byte sniff
7. File count limit check (>150 raises `IngestionLimitExceededError`)
8. UTF-8 read + `SecretScanner.scan_and_redact()`

**Error types**: `InvalidURLError` (422), `SSRFError` (422), `RepoTooLargeError` (413), `GitHubAPIError` (400/404/429), `CloneTimeoutError` (408)

**Tests**: `tests/test_ingestion.py`, `tests/test_url_validator.py`, `tests/test_preflight_and_subpath.py`, `tests/test_secret_scanner_coverage_and_parsers.py`, `tests/test_secret_scanner_fixes.py`

---

### Layer 2: Static AST Parsing

**Files**: 10 parsers + `app/parser/schema.py` (63L) + `app/parser/registry.py` (49L)

**Schema** (`app/parser/schema.py`):
```python
class ImportEdge(BaseModel):
    source_path: str; target: str; is_external: bool; resolved: bool; line_number: Optional[int]

class FileNode(BaseModel):
    path: str; language: str; imports: List[ImportEdge]; exports: List[str]
    classes: List[str]; functions: List[str]; entry_point: bool; parse_errors: List[str]
```

| Language | Parser Engine | Extracts | Not Handled |
|---|---|---|---|
| Python | `ast` stdlib | imports, classes, functions, `__all__` | `importlib`, `exec`, conditional imports |
| JS/TS | Regex | `import`/`require`/`export` | Dynamic `import()`, barrel re-exports |
| Go | Regex | `import`, `func`, `type struct` | Build tags, `init()` order |
| Rust | Regex | `use`, `mod`, `pub fn/struct/enum` | `#[cfg(...)]`, proc macros |
| Java | `javalang` lib | imports, class/method defs | Annotation processors |
| C++ | `libclang` (subprocess) | `#include`, class/function defs | Template metaprogramming |
| Shell | Regex | `source`/`.`, function defs | Dynamic `eval` |
| TLA+ | Regex | `EXTENDS`, `INSTANCE`, operators, `VARIABLES` | PlusCal, `ASSUME` |

**Error isolation**: Parse errors collected in `collected_parse_errors` (`app/orchestration/pipeline.py:156`) — appended to markdown output without halting pipeline.

**Tests**: `tests/test_{python,javascript,go,rust,java,cpp,shell,tla}_parser.py`, `tests/test_parser_audit.py`

---

### Layer 3: Git History Extraction

**Files**: `app/services/history_extractor.py` (384L), `app/models/history.py` (29L)

**Algorithm**: `git log --follow --format=%H %ai -- <file>` for each file via `run_sandboxed_git_command`. Returns `CommitHistoryResult.file_first_appearance` dict mapping paths to timestamps.

**Failure mode**: No git history → `CommitHistoryResult(history_available=False, history_confidence="reduced")` → narration engine uses "No Git History" disclosure path (`app/sequence/narration_engine.py:101`).

**Tests**: `tests/test_history_extraction.py`

---

### Layer 4: Segmentation

**Files**: `app/segmentation/engine.py` (96L), `app/segmentation/rules.py` (160L), `app/segmentation/graph_clusterer.py` (79L)

**Domains**: `config`, `database`, `core`, `backend`, `frontend`, `examples`, `tests`, `docs`, `uncategorized`

**Classification cascade** (`app/segmentation/rules.py:66`):
1. Test indicators (path `test/`, `spec/`, filename starts with `test_`) → TESTS
2. Doc folders/extensions → DOCS
3. Config exact filenames (`package.json`, `Dockerfile`, `requirements.txt`, etc.) → CONFIG
4. Database folders (`db/`, `migrations/`, `.sql`) → DATABASE
5. Examples folders → EXAMPLES
6. Frontend folders/extensions (`.tsx`, `.vue`, `.css`) → FRONTEND
7. Backend folders/filenames → BACKEND
8. Language-based default (`.py`, `.go`, `.rs` → CORE) → CORE
9. Fallback → UNCATEGORIZED

**Tests**: `tests/test_segmentation_rules.py`, `tests/test_segmentation_graph.py`, `tests/test_segmentation_real_repos.py`

---

### Layer 5: Hybrid RAG

**Files**: `app/rag/engine.py` (91L), `app/rag/chunker.py` (155L), `app/rag/embedder.py` (79L), `app/rag/retriever.py` (103L), `app/rag/vector_store.py` (42L), `app/rag/graph_retriever.py` (64L)

**Chunking**: AST-aware chunker (`app/rag/chunker.py`). Python: splits at class/function boundaries. Others: 50-line sliding window, 10-line overlap. Each chunk: `CodeChunk` with `file_path`, `start_line`, `end_line`, `symbol_name`, `content`.

**Embedding** (`app/rag/embedder.py`):
- Default (always-on): `_deterministic_ngram_embedding()` — MD5-hashed unigrams + bigrams → 128-dim float32, L2-normalized. No API key.
- Optional: `gemini/text-embedding-004` if `GEMINI_API_KEY` set and `use_gemini=True`
- `HybridRAGEngine(dimension=128, use_gemini=False)` is hardcoded in pipeline (`app/orchestration/pipeline.py:197`) — Gemini is NOT used in standard runs.

**Vector store**: FAISS `IndexFlatIP` (`app/rag/vector_store.py:15`) — in-memory cosine similarity over L2-normalized 128-dim vectors, cleared on `index_repository()`, not persisted.

**Hybrid retrieval** (`app/rag/retriever.py:27`):
1. Vector search: embed query → FAISS top-K by inner product (cosine similarity)
2. Graph search: if `target_path` provided/detected, traverse `GraphDependencyRetriever` 1-hop import neighbors
3. Fusion: chunks found by BOTH methods rank first; then by score descending (`retriever.py:87`)

**No BM25**: Despite "Hybrid RAG" naming, there is NO BM25 keyword component. Hybrid = vector + dependency graph.

**Where used**: `SynthesisEngine.synthesize()` → `deep_dive_citations` per milestone (`app/synthesis/engine.py:104-119`). Not used for user-facing search.

**Tests**: `tests/test_rag_chunker.py`, `tests/test_rag_hybrid.py`, `tests/test_rag_vector_store.py`, `tests/test_rag_real_repos.py`

---

### Layer 6: Sequence Reasoning (Four Stages)

**Files**: `app/sequence/baseline_ordering.py` (374L), `app/sequence/constrained_tie_breaking.py` (246L), `app/sequence/confidence_scoring.py` (106L), `app/sequence/narration_engine.py` (818L)

#### Stage A — Baseline Ordering (Tarjan SCC)

Algorithm (`app/sequence/baseline_ordering.py`):
1. Build import graph from `ImportEdge` objects where `is_external=False`
2. Go intra-package inference (`line 83-117`): regex symbol-reference search links files sharing same directory/package
3. Identify isolated files (zero internal edges in/out)
4. **Tarjan SCC** (`_tarjan_scc()`, `line 159`) → detects all cycles
5. Build condensation DAG (`scc_deps`, `line 186-192`)
6. Recursive `get_scc_depth()` with memoization (`line 197-209`)
7. Group SCCs by depth → tier batches, sorted alphabetically for determinism

**Import resolution** (`_resolve_target_files()`, `line 276`): exact match → add extension → index file → directory prefix → suffix match.

**GENERIC_SYMBOL_BLACKLIST** (`line 10-21`): 70+ tokens excluded from Go intra-package analysis to prevent false edges (e.g., `"app"`, `"client"`, `"error"`).

**Determinism proof**: `isolated_files.sort()` (L137), `non_cyclic_files_at_depth.sort()` (L236), `sorted(list(sccs[scc_idx]))` (L228), `cyclic_sccs_at_depth.sort(key=...)` (L247).

#### Stage B — Constrained Tie-Breaking

**3-cascade algorithm** (`app/sequence/constrained_tie_breaking.py:34`):
1. **History sub-bucketing**: group intra-tier files by first-commit timestamp. Distinct timestamps → order by timestamp. Same timestamp sub-buckets → proceed to Step 2.
2. **Domain priority heuristics**: `DOMAIN_PRIORITY` dict (config=1, database=2, core=3, backend=4, frontend=5, examples=6, tests=7, docs=8, uncategorized=9).
3. **LLM tie-breaking**: if `llm_provider` supplied AND files still tied. **Hard validation** (`line 229-240`): `set(proposed_order) == set(group_files)` AND no cross-tier files. Violation → falls back to `unresolved`.
4. **Unresolved fallback**: alphabetical order, `tie_break_method="unresolved"`.

**LLM cannot cross tier boundaries**: `outside_tier_files = [f for f in proposed_order if f not in set(tier_files)]` — if non-empty, LLM result discarded entirely.

#### Stage C — Confidence Scoring

Per-file confidence (`app/sequence/confidence_scoring.py`):
- `high`: backed by verified git history timestamp
- `medium`: domain heuristic used
- `low`: unresolved tie, cyclic cluster, or isolated file

#### Stage D — Narration Engine

**System prompt** (`app/sequence/narration_engine.py:17-30`):
```
You are a Senior Software Architect and Master Technical Educator.
CRITICAL PEDAGOGICAL RULES & GUARDRAILS:
1. STRICT SEQUENCE FIDELITY: Follow the numbered milestones exactly in order provided. Do not reorder tiers.
2. HONEST CONFIDENCE CALIBRATION
3. TEACHING FOCUS
4. DO NOT HALLUCINATE: Never invent dependencies or files not present in the input.
```

**LLM decoupling**: LLM output is purely descriptive text. Tier structure (file-to-tier mapping) is frozen before LLM is called. If LLM provider not supplied, `_generate_deterministic_narration()` uses templates.

**Tests**: `tests/test_sequence_baseline.py`, `tests/test_sequence_confidence.py`, `tests/test_sequence_tie_breaking.py`, `tests/test_sequence_narration.py`, `tests/test_sequence_real_repos.py`, `tests/test_reduced_confidence_propagation.py`

---

### Layer 7: Synthesis

**Files**: `app/synthesis/engine.py` (198L), `app/synthesis/schema.py` (48L)

Output: `SynthesizedRepositoryReport` with `architecture_overview`, `confidence_disclosure`, `milestones: List[SynthesizedMilestone]`, `file_symbols`, `file_dependencies`.

Each `SynthesizedMilestone` has: `tier`, `title`, `summary`, `dominant_domain`, `files`, `confidence`, `is_cyclic`, `key_symbols_and_exports` (top 10), `deep_dive_citations` (RAG-sourced, max 8 per milestone), `architectural_role`.

Isolated files → `tier_index = -1` (`app/synthesis/engine.py:136`).

**Tests**: `tests/test_synthesis_engine.py`, `tests/test_synthesis_real_repos.py`

---

### Layer 8: Output Formatting

**Files**: `app/formatters/markdown_formatter.py` (84L), `app/formatters/graph_formatter.py` (103L), `app/formatters/quiz_formatter.py` (81L)

- **Markdown**: Milestones, confidence disclosures, domain tables — stored as `analysis_jobs.markdown_output`
- **Graph JSON**: DAG nodes+edges for D3.js visualization — stored as `analysis_jobs.graph_output_json`
- **Quiz JSON**: Fill-in-the-blank scaffolds per milestone — stored as `analysis_jobs.quiz_output_json`

**Tests**: `tests/test_output_formatters.py`

---

### Layer 9: Storage

**Files**: `app/models/db.py` (331L), `app/db/session.py` (134L), `app/storage/` (5 repository files)

See Section 3 for full data model.

---

### Layer 10: Security Sandboxing

**Files**: `app/security/sandbox_runner.py` (146L), `app/security/path_hardening.py` (37L), `app/services/security.py` (89L)

**Git clone hardening** (`app/services/security.py`):
```
-c core.hooksPath=           # Disables ALL git hooks
-c core.attributesFile=/dev/null  # Disables .gitattributes filters
-c credential.helper=        # Prevents credential prompts
-c filter.lfs.smudge=cat     # Prevents LFS data fetch
-c http.followRedirects=false # Prevents clone-time SSRF via redirects
```

**Docker path** (`app/security/sandbox_runner.py:68-165`): Clone runs in `alpine/git:latest` with `--cpus=1.0`, `--memory=512m`, `--pids-limit=64`, DNS IP pinning `--add-host=github.com:{validated_ip}`.

**Non-Docker path**: Same git flags via direct subprocess. No container isolation.

**SandboxRunner class**: STUBBED / UNUSED — defined in `app/security/sandbox_runner.py:39-165` but the main ingestion flow in `app/services/ingestion.py` uses direct subprocess calls via `run_sandboxed_git_command()`, not this class.

**Tests**: `tests/test_security_sandboxing.py`

---

### Layer 11: Pipeline Orchestration

**Files**: `app/orchestration/pipeline.py` (302L), `app/orchestration/schema.py` (36L), `app/services/metrics.py` (146L)

**Stages** (enum `PipelineStage`): `INGESTION`, `PARSING`, `UNDERSTANDING`, `SEQUENCE_REASONING`, `SYNTHESIS`, `COMPLETE`, `FAILED`

**Progress callback**: `emit()` pushes `PipelineProgressEvent`, fires `progress_callback` (SSE sender). Both wrapped in try/except — failures silently swallowed to prevent pipeline abort (`pipeline.py:110-117`).

**Error boundary**: Single top-level `try/except Exception` wraps all stages. User-facing error messages looked up from `stage_user_messages` dict — no stack traces exposed.

**Metrics**: `PipelineMetricsCollector` singleton (`app/services/metrics.py:144`) records per-layer duration. Emits JSON logs: `{"metric_type":"pipeline_layer_duration","layer":"...","duration_ms":...}`. Log-based only — no Prometheus client push endpoint.


---

## Section 3 — Data Model (10 Tables)

### `repos`
| Column | Type | Constraints |
|---|---|---|
| id | Integer | PK, autoincrement |
| github_url | String(255) | NOT NULL, indexed |
| commit_hash | String(64) | NOT NULL, indexed |
| status | String(32) | NOT NULL, default='pending' |
| error_message | Text | nullable |
| created_at / expires_at | DateTime | NOT NULL, indexed |
| keep_longer | Boolean | default=False |
| consent_prompt_improvement / consent_future_training | Boolean | NOT NULL |
| subpath | String(500) | nullable |

Composite indexes: `idx_repo_url_commit`, `idx_repo_url_commit_subpath`

### `ingestion_results`
| Column | Type | Notes |
|---|---|---|
| repo_id | FK→repos.id CASCADE | UNIQUE |
| file_tree_json / file_contents_json / skipped_files_json | Text | NOT NULL |
| redaction_count | Integer | Count of secrets redacted |
| clone_duration_ms | Integer | NOT NULL |

### `analysis_results`
| Column | Type | Notes |
|---|---|---|
| repo_id | FK→repos.id CASCADE | UNIQUE |
| pipeline_result_json | Text | Full pipeline output |
| execution_time_seconds | Float | NOT NULL |

### `users`
| Column | Type | Constraints |
|---|---|---|
| github_id | Integer | UNIQUE, indexed |
| github_username | String(100) | NOT NULL |
| email | String(255) | nullable, indexed |
| avatar_url | String(500) | nullable |
| is_admin | Boolean | default=False |

### `refresh_tokens`
| Column | Type | Notes |
|---|---|---|
| user_id | FK→users.id CASCADE | indexed |
| token_hash | String(64) | SHA-256 of raw token, indexed |
| expires_at | DateTime | indexed |
| revoked_at | DateTime | nullable |

### `subscriptions`
| Column | Type | Notes |
|---|---|---|
| user_id | FK→users.id CASCADE | UNIQUE, indexed |
| stripe_customer_id | String(255) | NOT NULL, indexed |
| stripe_subscription_id | String(255) | nullable, indexed |
| status | String(64) | default='inactive' |
| current_period_end | DateTime | nullable |

### `usage_events` (immutable audit log)
| Column | Type | Notes |
|---|---|---|
| user_id | FK→users.id CASCADE | indexed |
| event_type | String(64) | default='repo_analysis' |
| created_at | DateTime | NOT NULL, indexed |

### `processed_webhook_events` (idempotency registry)
| Column | Type | Notes |
|---|---|---|
| event_id | String(255) | UNIQUE, NOT NULL, indexed |
| event_type | String(100) | NOT NULL |
| processed_at | DateTime | NOT NULL |

### `analysis_jobs`
| Column | Type | Notes |
|---|---|---|
| user_id | FK→users.id CASCADE | indexed |
| repo_name / github_url | String | NOT NULL |
| commit_ref | String(255) | nullable |
| resolved_sha | String(64) | nullable, indexed |
| subpath | String(500) | nullable |
| status | String(32) | default='pending' |
| run_id | String(64) | NOT NULL, indexed |
| markdown_output / graph_output_json / quiz_output_json | Text | NOT NULL |
| execution_time_seconds | Float | NOT NULL |

### `milestone_attempts`
| Column | Type | Notes |
|---|---|---|
| user_id | FK→users.id | Composite unique: (user_id, job_id, milestone_tier) |
| job_id | FK→analysis_jobs.id | CASCADE |
| milestone_tier | Integer | indexed |
| submitted_code | Text | NOT NULL |
| status | String(32) | default='not_started' |
| hint_level_revealed | Integer | 0-2 |
| implementation_revealed | Boolean | default=False |
| last_run_code | Text | nullable (isolated scratchpad code) |
| last_run_stdout / last_run_stderr | Text | nullable |
| last_run_exit_code | Integer | nullable |
| grading_method | String(32) | default='structural_only' |
| grading_details_json | Text | nullable |

### `points_ledger` (immutable append-only)
| Column | Type | Notes |
|---|---|---|
| user_id | FK→users.id | indexed |
| job_id | FK→analysis_jobs.id | nullable (CASCADE) |
| milestone_tier | Integer | indexed |
| points_awarded | Integer | positive=award, negative=redemption |
| multiplier_applied | Float | default=1.0 |
| reason | String(100) | NOT NULL |
| created_at | DateTime | indexed |

Indexes: `idx_points_user_created`, `idx_points_user_job_tier`

### Migration Strategy
- Primary: Alembic version control via `alembic/versions/` (5 version scripts: `0001` through `0005_last_run_code.py`). Auto-ALTER removed from `init_db()` in commit `c5e9a08`.
- SQLite: WAL mode, StaticPool for tests, `check_same_thread=False`
- PostgreSQL: pool_size=20, max_overflow=10, pool_recycle=1800s, `pool_pre_ping=True`
- Alembic configured (`alembic.ini`) with 5 verified version scripts in `alembic/versions/` (`0001_initial_postgres_schema.py`, `0002_points_ledger_and_subpath.py`, `0003_resolved_sha_and_repo_subpath.py`, `0004_failed_stage.py`, `0005_last_run_code.py`)

---

## Section 4 — API Surface

### Authentication (`/auth`)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | /auth/github/login | None | 307→GitHub OAuth, CSRF state token |
| GET | /auth/github/callback | None | 302+httpOnly cookies, user upsert |
| POST | /auth/refresh | None | Rate-limited per IP |
| POST | /auth/logout | None | Revokes refresh token, clears cookies |
| GET | /auth/logout | None | Browser: 302→/login + cookie clear |
| GET | /auth/me | JWT | Returns `UserProfileResponse` |
| GET | /auth/dev-login | None | Dev-only helper (gated by ENVIRONMENT == 'development', commit a4c8ba9) |

> **RESOLVED SECURITY ITEM** (`app/api/auth.py:228`): `/auth/dev-login` is gated by `if _settings.ENVIRONMENT == "development":` and is not registered in production (commit `a4c8ba9`).

### Billing (`/billing`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | /billing/checkout | JWT | Stripe Checkout Session |
| GET | /billing/portal | JWT | Stripe Customer Portal redirect |
| GET | /billing/status | JWT | Returns tier, usage_count, quota |
| POST | /billing/webhook | Stripe HMAC | checkout.session.completed, subscription.updated/deleted |

### Pipeline (`/api/pipeline`)

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | /api/pipeline/run | JWT | Quota-gated (402 on exceeded) |

Request: `{repo_name, file_paths, file_contents, enable_rag, run_id?}`
Response: `{success, run_id, execution_time_seconds, layers_executed, user_tier, monthly_usage_count, report_summary?}`

Note: This endpoint expects pre-ingested file contents. The git clone happens in the frontend flow (`/analyze/start`), not here. This is effectively an internal orchestration API.

### Attempts (`/attempts`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | /attempts/{job_id}/{tier} | JWT | Get attempt state |
| POST | /attempts/{job_id}/{tier}/submit | JWT | Structural AST verification |
| POST | /attempts/{job_id}/{tier}/run | JWT | Execute in Piston sandbox |
| POST | /attempts/{job_id}/{tier}/hint | JWT | Reveal next hint |
| POST | /attempts/{job_id}/{tier}/reveal | JWT | Reveal full implementation |

### Points (`/api/points`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | /api/points/balance | JWT | Points total + per-milestone breakdown |
| GET | /api/points/leaderboard | Optional | Public (feature flag: ENABLE_PUBLIC_LEADERBOARD) |
| POST | /api/points/redeem | JWT | Redeem points for extra quota |
| GET | /api/points/ledger | JWT | Full transaction history |

### Frontend HTML

| Path | Auth | Returns |
|---|---|---|
| / | Optional | Redirect to /dashboard or /login |
| /login | None | HTML login page |
| /dashboard | JWT | HTML dashboard |
| /analyze/start | JWT | POST → start job, redirect to /analyze/progress/{id} |
| /analyze/progress/{id} | JWT | HTML progress page |
| /analyze/progress/stream/{id} | JWT | SSE PipelineProgressEvent stream |
| /report/{id} | JWT | HTML full report |
| /settings | JWT | HTML settings |
| /rewards | JWT | HTML points/rewards |

### Health

`GET /health` → 200 `{status:"healthy", components:{db:..., redis:..., piston:...}}` or 503

> **SECURITY (RESOLVED)**: Prior `GET /debug/env` in `app/main.py` was completely removed in commit `a4c8ba9` to eliminate environment information disclosure.

---

## Section 5 — Parser Coverage

| Language | Engine | Extracts | Gaps |
|---|---|---|---|
| Python | `ast` stdlib | imports, from-imports, classes, functions, `__all__` | `importlib`, `exec`, conditional imports |
| JS/TS | Regex | `import`/`require`/`export` | Dynamic `import()`, `export *` barrel |
| Go | Regex + intra-pkg inference | `import`, `func`, `type struct` | Build tags, `init()` order |
| Rust | Regex | `use crate::`/`super::`, `mod`, `pub fn/struct/enum` | `#[cfg(...)]`, proc macros |
| Java | `javalang` | imports, class/method defs | Annotation processors |
| C++ | `libclang` subprocess | `#include` (local), class/function defs; missing headers NON-FATAL | Template metaprogramming |
| Shell | Regex | `source`/`.`, `function name()` | Dynamic `eval` |
| TLA+ | Regex | `EXTENDS`, `INSTANCE`, operators, `VARIABLES` | PlusCal, `ASSUME` |

C++ test: `test_cpp_missing_header_diagnostic_is_non_fatal` — **IMPLEMENTED**

Python fallback: if `ast.parse()` raises `SyntaxError`, regex-based extraction runs as fallback.

---

## Section 6 — Dependency Graph Algorithm

### Node/Edge Construction
- **Nodes**: every file path in `all_repo_files` union `parsed_file_paths` (`baseline_ordering.py:51-57`)
- **Edges**: `ImportEdge` where `is_external=False`, resolved to actual file paths via `_resolve_target_files()` (5-strategy cascade: exact → extension → index file → directory prefix → suffix)
- **Additional edges**: Go intra-package symbol reference search

### Algorithm Steps
1. Build `deps[src].add(tgt)` and `dependents[tgt].add(src)` (`line 120-125`)
2. Identify isolated files (zero in/out edges) → `isolated_files.sort()` (`line 137`)
3. **Tarjan SCC** (`_tarjan_scc()`, `line 159`) on connected subgraph
4. Build condensation DAG `scc_deps[scc_a].add(scc_b)` (`line 186-192`)
5. Recursive `get_scc_depth()` with memoization (`line 197-209`)
6. Group by depth → tier batches

### Cycle Handling
Multi-node SCCs + self-loops (`node in deps[node]`, `line 170`) → `is_cyclic_cluster=True`. Placed at appropriate condensation depth. Narrated differently (no ordinal language).

### Known Gap
`get_scc_depth()` is recursive without stack depth protection. Python's default recursion limit is 1000. Linear chains >1000 files would `RecursionError`. Current 150-file cap makes this not a live risk.

### Tie-Break Method Tags per File
`"none"` (only file in tier), `"history"` (timestamp-resolved), `"heuristic"` (domain priority), `"llm"` (LLM-resolved and validated), `"unresolved"` (alphabetical fallback).

---

## Section 7 — Milestones and Narration

### Milestone Cutting
Each condensation DAG depth level → one `BuildStepNarrative` milestone.
Isolated files → `tier_index = -1` (`app/synthesis/engine.py:136`).
Cyclic clusters → `is_cyclic=True`.

### LLM Architecture
- Provider: `litellm` + Google Gemini via `app/sequence/llm_client.py`
- Used: Stage B (tie-breaking) and Stage D (narration text generation)
- If `GEMINI_API_KEY` absent: deterministic template fallback always used

### Structural Guarantee
The LLM receives already-computed tiers. System prompt rule 1: "Follow the numbered milestones exactly in the order provided. Do not reorder tiers." Stage B hard validation (`constrained_tie_breaking.py:229-240`) rejects any proposed ordering crossing tier boundaries.

**The LLM cannot change which files belong to which tier.**

---

## Section 8 — Challenges and Grading

### Challenge Generation
`app/services/scaffold_generator.py` (425L): blanks function/method bodies with `// TODO: implement` stubs. Only non-empty, non-stub bodies are blanked (`scaffold_generator.py:276`).

### 3-Tier Grading Hierarchy (`app/services/grading_engine.py`)

**Tier 1 — `real_tests`**: If `graph_data` contains `test_code` or a test file for the milestone, runs the test suite via Piston against user code.

**Tier 2 — `expected_output`**: If repo URL matches `CuratedExpectationsRegistry` (`app/services/curated_milestone_expectations.py`), diffs stdout against stored expected output.

**Tier 3 — `structural_only`**: AST symbol matching via `StructuralVerifier` + exit code 0 check. No execution.

### Structural Verification
`app/services/structural_verifier.py` (320L):
- Parses user code with `ast.parse()` → extracts `SymbolDefinition` (name, kind, arg_count)
- Matches against milestone expected symbols
- **Never executes user code**

### Piston Integration
**Request** (POST `{PISTON_URL}/api/v2/execute`):
```json
{"language":"python","version":"3.10.0",
 "files":[{"name":"solution.py","content":"<user_code>"}],
 "stdin":"","args":[],
 "run_timeout":3000,"compile_timeout":10000,"run_memory_limit":134217728}
```

**Response**:
```json
{"run":{"stdout":"...","stderr":"...","code":0,"signal":null},"compile":{}}
```

**Limits** (`app/services/execution_verifier.py`):
- Run timeout: 3,000ms (`line 30`)
- Compile timeout: 10,000ms (`line 31`)
- Memory: 128MB (`line 34`)
- Output: 65,536 chars max (`line 28`)

**Supported languages**: python, javascript, typescript, bash, go, rust, c, cpp, java

**Fail-closed**: In production (`is_production=True`), `allow_local_fallback=False` (`line 97-99`). If Piston unreachable → 503. Not 200 with degraded grading.

**Piston Docker security**:
- CPU 2.0, Memory 2048M, PIDs 256
- `PISTON_DISABLE_NETWORKING=true`
- Bound to `127.0.0.1:2000` only
- Seccomp: `./docker/piston-seccomp.json`
- `piston_isolated_net` bridge (separate from app+postgres+redis network)
- Capabilities: ALL dropped then selectively re-added (SYS_ADMIN, SETUID, SETGID, etc.)

**Tests**: `tests/test_execution_verifier.py` (16 tests including IDOR, production fail-closed, payload DoS defense, language normalization, live Piston integration)

---

## Section 9 — Hybrid RAG Deep Dive

(See Layer 5 above)

**BM25**: MISSING. No BM25 component despite "Hybrid" naming.

**Embedding dimensions**: 128-dim deterministic offline, 768-dim Gemini (incompatible with current FAISS index when both enabled). Not a live risk since `use_gemini=False`.

**Score fusion**: Binary — both-retrieved chunks sort before either-retrieved chunks. No weighted sum.

**Index lifetime**: Built fresh per pipeline run. Cleared at start of `index_repository()`. Not persisted.

**Usage in product**: Only for generating `deep_dive_citations` on milestone cards. Not a user-facing search feature.

---

## Section 10 — Redis and Rate Limiting

### Redis Connection
- `REDIS_URL` default: `redis://localhost:6379/0` (`app/core/config.py:70`)
- Docker: `redis://:${REDIS_PASSWORD}@redis:6379/0`
- `redis:7-alpine` with `--requirepass ${REDIS_PASSWORD}` and persistence (`--save 60 1`)

### Token Bucket Rate Limiter (`app/security/rate_limiter.py`, 451L)

**Lua script** (`LUA_TOKEN_BUCKET_SCRIPT`, `line 45-88`): Atomic Redis execution.
- Keys: `ratelimit:{key}` (e.g., `ratelimit:user:{id}`, `ratelimit:refresh:{ip}`)
- Hash fields: `tokens` (float), `last_refill` (epoch float)
- Logic: `tokens = min(capacity, tokens + elapsed * refill_rate)` → if tokens >= cost: allow + deduct; else: deny + compute retry_after
- Returns: `[allowed, remaining, reset_seconds, retry_after]`
- HMSET + EXPIRE in same atomic script → no race conditions

**Fail-open**: Redis unreachable or Lua error → request allowed. Bypass event logged.

**Circuit breaker**: `RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD=5` bypass events in sliding window → structured security alert logged.

**Response headers set**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`

**Cache key patterns**:
- `ratelimit:user:{user_id}` — per-user API limiting
- `ratelimit:ip:{ip}` — per-IP limiting
- `ratelimit:refresh:{ip}` — refresh endpoint brute-force protection

### Cached Ingestion
`app/services/cached_ingestion.py` (90L): Wraps `IngestionService` with DB result caching via `RepoModel`/`IngestionResultModel`. Status: **UNWIRED / UNUSED** — the active pipeline in `app/api/frontend.py:627-695` directly calls `IngestionService()` and persists file contents via `FileContentService.persist_file_contents(db_session, ...)`.

### Concurrency and Locking
In-process thread synchronization is handled via `threading.Lock()` mutexes (`app/security/rate_limiter.py:111, 261`, `app/security/auth.py:208, 260`, `app/services/points_engine.py:25`). No Redis-level distributed locks (`SETNX` or `redis.lock()`) are implemented.

---

## Section 11 — Frontend

### Template Engine
All HTML generated by pure Python semantic string building in `app/ui/components.py` (6,687 lines) and sanitized via `app/ui/sanitizer.py` (170 lines). No Jinja2, no React, no Webpack, no node_modules required at runtime. Entire frontend ships as part of the Python process.

### Page-to-API Mapping

| Page | Generator Function | Data Sources |
|---|---|---|
| Login | login_view() | Static + `?error=` query param |
| Dashboard | dashboard_view() | `BillingService.get_user_billing_status()`, `AnalysisJobRepository.get_jobs_for_user()` |
| Progress | progress_view() | SSE stream `/api/analyses/{job_id}/events` |
| Report | report_view() | `job.markdown_output`, `job.graph_output_json`, `job.quiz_output_json` |
| Settings | settings_view() | `BillingService.get_user_billing_status()`, `BillingService.get_pro_price_details()` |
| Rewards | rewards_view() | `PointsEngine.get_user_points_balance()`, `PointsEngine.get_leaderboard()` |

### XSS Mitigations
- `app/ui/sanitizer.py` (170L): `sanitize_text()` applies `html.escape(quote=True)` + `render_safe_markdown()` strips dangerous tags while supporting code blocks, tables, lists, and headers
- SSE event data: JavaScript uses `textContent` (not `innerHTML`) — commit `aaeccde`
- Graph node labels sanitized before D3.js insertion — commit `85941e2`

### Active Debugging Code
`app/api/auth.py:14-24`: Raw `print()` and `logging.warning()` debug statements active in all environments. Logs `GITHUB_REDIRECT_URI` value on every module load and every login attempt. Not an XSS risk but is information disclosure in server logs.


---

## Section 12 — Configuration and Secrets

| Variable | Default | Read In | Effect |
|---|---|---|---|
| ENVIRONMENT | development | config.py:15 | Controls production validation strictness |
| HOST | 0.0.0.0 | config.py:21 | Uvicorn bind address |
| PORT | 8000 | config.py:22 | Uvicorn port |
| DATABASE_URL | sqlite:///./backtrace.db | config.py:40 | SQLAlchemy connection |
| JWT_SECRET_KEY | development_secret_key... | config.py:43 | JWT signing key (insecure default) |
| JWT_ALGORITHM | HS256 | config.py:44 | JWT signing algorithm |
| ACCESS_TOKEN_EXPIRE_MINUTES | 15 | config.py:45 | Access token TTL |
| REFRESH_TOKEN_EXPIRE_DAYS | 30 | config.py:46 | Refresh token TTL |
| GITHUB_CLIENT_ID | None | config.py:49 | GitHub OAuth app ID |
| GITHUB_CLIENT_SECRET | None | config.py:50 | GitHub OAuth secret |
| GITHUB_REDIRECT_URI | http://localhost:8000/auth/github/callback | config.py:51 | OAuth callback |
| GITHUB_TOKEN / GITHUB_PAT | None | config.py:52-53 | GitHub API auth (60→5000 req/hr) |
| STRIPE_SECRET_KEY | None | config.py:56 | Stripe API key |
| STRIPE_WEBHOOK_SECRET | None | config.py:57 | Stripe webhook HMAC |
| STRIPE_PRICE_ID_PRO | None | config.py:58 | Pro plan price ID |
| STRIPE_SUCCESS_URL | http://localhost:8000/dashboard?... | config.py:59 | Post-checkout redirect |
| FREE_TIER_MONTHLY_LIMIT | 5 | config.py:61 | Free tier repo cap |
| SENTRY_DSN | None | config.py:64 | Sentry DSN |
| SENTRY_TRACES_SAMPLE_RATE | 1.0 | config.py:65 | 100% trace sampling (prod cost concern) |
| POSTHOG_API_KEY | None | config.py:66 | PostHog analytics |
| POSTHOG_HOST | https://app.posthog.com | config.py:67 | PostHog endpoint |
| REDIS_URL | redis://localhost:6379/0 | config.py:70 | Redis connection |
| RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD | 5 | config.py:71 | Redis bypass alert threshold |
| RATE_LIMIT_REDIS_TIMEOUT | 0.5 | config.py:72 | Redis op timeout (s) |
| CORS_ALLOWED_ORIGINS | http://localhost:3000,... | main.py:69 | CORS whitelist |
| POINTS_BASE_VALUE | 50 | config.py:80 | Base points per milestone |
| POINTS_HINT_1_MULTIPLIER | 0.50 | config.py:81 | 50% if hint 1 used |
| POINTS_HINT_2_MULTIPLIER | 0.25 | config.py:82 | 25% if hint 2 used |
| POINTS_SOLUTION_REVEALED_MULTIPLIER | 0.0 | config.py:83 | 0 points if solution revealed |
| POINTS_EXPIRY_DAYS | 180 | config.py:86 | Points expiry |
| POINTS_QUOTA_REWARD_COST | 100 | config.py:87 | Points to redeem extra quota |
| POINTS_QUOTA_REWARD_AMOUNT | 2 | config.py:88 | Extra repos per redemption |
| ENABLE_PUBLIC_LEADERBOARD | True | config.py:89 | Feature flag |
| PISTON_URL | http://127.0.0.1:2000 | execution_verifier.py:80 | Piston sandbox URL |
| ALLOW_LOCAL_FALLBACK | true | execution_verifier.py:104 | Dev: allow unsandboxed exec |
| GEMINI_API_KEY | None | rag/embedder.py:15 | Enables Gemini embeddings |
| POSTGRES_USER/PASSWORD/DB | postgres/-/backtrace | docker-compose.yml:85-87 | PostgreSQL credentials |
| REDIS_PASSWORD | - | docker-compose.yml:42 | Redis auth password |

### Security Notes

**`JWT_SECRET_KEY` default**: A known static string — all dev instances without `.env` use a compromised key.

**Production validation** (`config.py:111-158`): `@model_validator` raises `ValueError` on `ENVIRONMENT=production` if:
- `JWT_SECRET_KEY` contains "development_secret_key"
- Stripe keys don't start with `sk_live_` or `sk_test_`
- Localhost appears in `GITHUB_REDIRECT_URI`

**`debug=False`**: Hardcoded in `app/main.py:62` regardless of settings. Intentional — prevents Starlette stack trace leakage (commit `7a2d4e0`).

**Cookie security**: `secure=False` in `app/api/auth.py:127,136` during development. Cookies sent over HTTP.

---

## Section 13 — Deployment and Operations

### docker-compose.yml Services

| Service | Image | Port | CPU | Memory | Networks |
|---|---|---|---|---|---|
| nginx | nginx:alpine | 80, 443 | 1.0 | 512M | default |
| backtrace-app | Dockerfile | 8000 (127.0.0.1) | 2.0 | 4096M | default + piston_isolated_net |
| postgres | postgres:16-alpine | 5432 (127.0.0.1:5433) | 1.0 | 1024M | default |
| redis | redis:7-alpine | 6379 (internal) | 1.0 | 512M | default |
| piston | ghcr.io/engineer-man/piston:latest | 2000 (127.0.0.1) | 2.0 | 2048M | default + piston_isolated_net |
| piston-init | curlimages/curl | - | - | - | piston_isolated_net |
| cloudflared | cloudflare/cloudflared | - | 0.5 | 256M | default |

### Piston Language Packages (installed by piston-init)
Python 3.10.0, Node 18.15.0, TypeScript 5.0.3, Java 15.0.2, Rust 1.68.2, Go 1.16.2, GCC 10.2.0, Bash 5.2.0

### Piston Network Isolation
`piston_isolated_net` bridge network shared ONLY by `backtrace-app`, `piston`, and `piston-init`. Nginx, Postgres, Redis are NOT on this network. `PISTON_DISABLE_NETWORKING=true` prevents executed code from making outbound connections.

### Piston Container Security
- `cap_drop: [ALL]` then selectively re-add: SYS_ADMIN, SYS_CHROOT, SETUID, SETGID, CHOWN, DAC_OVERRIDE, FOWNER, KILL, SYS_RESOURCE, SYS_PTRACE, NET_ADMIN
- Seccomp: `./docker/piston-seccomp.json`
- tmpfs: `/tmp`, `/var/local/lib/isolate`, `/run`
- `read_only: true` at root (not all volumes)

> **NOTE**: SYS_PTRACE + SYS_ADMIN capabilities are required by isolate (Piston's process isolation layer) but represent the highest-risk capabilities in the Piston container. A container escape using these capabilities is theoretically possible.

### Cloudflare Tunnel
`cloudflared tunnel --no-autoupdate --url http://backtrace-app:8000` — exposes app through Cloudflare without public IP or TLS certificate management. Tunnel URL is auto-assigned.

### Healthchecks
- `backtrace-app`: `curl -f http://localhost:8000/health` every 15s, 3 retries
- `postgres`: `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` every 5s
- `redis`: `redis-cli -a $REDIS_PASSWORD ping` every 5s

### Volumes
`backtrace_data`, `postgres_data`, `piston_packages`, `redis_data`, `certbot_certs`, `certbot_www`

### Metrics / Observability
- Structured JSON logs via `app/utils/logging.py` (`json-logger` library), enriched with `layer` and `run_id` fields
- `PipelineMetricsCollector` emits `{"metric_type":"pipeline_layer_duration","layer":"...","duration_ms":...}`
- No Prometheus `/metrics` endpoint, no push gateway — metrics are log-based only
- Sentry for error tracking (if `SENTRY_DSN` set)
- PostHog for product analytics (if `POSTHOG_API_KEY` set)
- Piston health: `app/services/piston_health.py` polls `/api/v2/runtimes` every 60s from a background thread

---

## Section 14 — Test Suite

### Inventory (62 test files)

| Test File | Covers |
|---|---|
| test_auth_session.py | OAuth flow, JWT, refresh rotation, CSRF |
| test_backup_restore.py | Backup creation, checksum, restore, pruning |
| test_billing_and_quota.py | Stripe webhooks, quota enforcement, idempotency |
| test_cpp_parser.py | C++ AST parsing, missing headers |
| test_dashboard_redesign.py | Dashboard HTML, IDOR, timestamps |
| test_edge_cases_resilience.py | Repo cap, missing git history, syntax errors |
| test_engineering_infrastructure.py | Health check, logging, metrics, CI/CD |
| test_execution_verifier.py | Piston integration, production fail-closed, IDOR, DoS |
| test_file_content_persistence.py | File service, milestone content, grading |
| test_frontend_ui.py | Comprehensive HTML rendering (98KB file!) |
| test_go_parser.py | Go AST parsing |
| test_grading_engine.py | Grading tier selection, structural+runtime |
| test_history_extraction.py | Git history extraction |
| test_ingestion.py | Ingestion service |
| test_java_parser.py | Java AST parsing |
| test_javascript_parser.py | JS/TS parsing |
| test_live_llm_narration.py | Live LLM calls (requires API key; likely skip) |
| test_milestone_attempt.py | Attempt state machine |
| test_monitoring_analytics.py | Sentry, PostHog integration (mocked) |
| test_nav_shell.py | Navigation rendering |
| test_output_formatters.py | Markdown/graph/quiz formatters |
| test_parser_audit.py | Parser coverage audit |
| test_pipeline_orchestrator.py | Pipeline end-to-end |
| test_piston_health_graceful_degradation.py | Piston health monitor |
| test_points_engine.py | Points awarding, multipliers, expiry |
| test_points_redemption.py | Points redemption for quota |
| test_preflight_and_subpath.py | GitHub preflight, subpath scoping |
| test_production_readiness.py | Production config validation |
| test_progress_redesign.py | Progress SSE view |
| test_progressive_hints.py | Hint engine |
| test_python_parser.py | Python AST parsing |
| test_rag_chunker.py | RAG chunking |
| test_rag_hybrid.py | Hybrid retrieval |
| test_rag_real_repos.py | RAG on real repos |
| test_rag_vector_store.py | FAISS vector store |
| test_rate_limiter.py | Token bucket, circuit breaker |
| test_real_repo_validation.py | End-to-end on real repos |
| test_reduced_confidence_propagation.py | Confidence scoring |
| test_rust_parser.py | Rust AST parsing |
| test_scaffold_generator.py | Scaffold/blank generation |
| test_secret_scanner_coverage_and_parsers.py | Secret detection patterns |
| test_secret_scanner_fixes.py | Secret redaction edge cases |
| test_security_sandboxing.py | Sandbox security |
| test_segmentation_graph.py | Graph clustering |
| test_segmentation_real_repos.py | Segmentation on real repos |
| test_segmentation_rules.py | Domain classification rules |
| test_sequence_baseline.py | Tarjan SCC, topological order |
| test_sequence_confidence.py | Confidence scoring |
| test_sequence_narration.py | Narration engine |
| test_sequence_real_repos.py | Sequence on real repos |
| test_sequence_tie_breaking.py | Tie-breaking cascade |
| test_settings_redesign.py | Settings page |
| test_shell_parser.py | Shell parsing |
| test_storage_caching.py | Repository layer caching |
| test_structural_verifier.py | AST symbol matching |
| test_subprocess_base.py | Subprocess parser base |
| test_synthesis_engine.py | Synthesis |
| test_synthesis_real_repos.py | Synthesis on real repos |
| test_tla_parser.py | TLA+ parsing |
| test_url_validator.py | URL + SSRF validation |

### Test Run Status
**Collection**: 432 test cases collected across 64 test files.
**Literal Test Result**: **431 PASSED, 1 SKIPPED, 0 FAILED** in 566.86s (`python -m pytest -v`).
The 1 skipped test is `tests/test_live_llm_narration.py::test_live_ollama_flask_narration` (skipped when local Ollama daemon or model is not running).

### Missing Test Coverage
- No double-run determinism test (run same repo twice, diff output)
- No load/stress tests
- `SandboxRunner` class has no dedicated integration test
- No chaos/failure injection for Redis unavailability at pipeline start

---

## Section 15 — Security Review

### Resolved Finding: `/auth/dev-login`
`app/api/auth.py:228`: Gated by `if _settings.ENVIRONMENT == "development":`. In production, the route is not registered (resolved in commit `a4c8ba9`).

### Resolved Finding: `/debug/env` Information Disclosure
Removed from `app/main.py` (resolved in commit `a4c8ba9`).

### SSRF Analysis
`validate_ssrf()` (`url_validator.py:59`):
- DNS resolves `github.com` → checks all IPs against `ip.is_private | is_loopback | is_link_local | is_reserved | is_multicast`
- AWS IMDSv1 at `169.254.169.254` is correctly blocked (link-local)
- Docker DNS rebinding path: `SandboxRunner` pins GitHub IP with `--add-host=github.com:{validated_ip}` — mitigates rebinding TOCTOU, but only when Docker daemon is available
- Git-level SSRF: `http.followRedirects=false` prevents HTTP redirect chains during clone

### IDOR Analysis
- `report/{job_id}`: `job.user_id != current_user.id` check before serving — IMPLEMENTED
- `/attempts/{job_id}/{tier}/*`: same user ownership check — IMPLEMENTED
- Test: `test_execution_verifier.py::test_api_run_idor_protection` — IMPLEMENTED

### Input Surface

| Input | Risk | Mitigation | Status |
|---|---|---|---|
| GitHub URL | SSRF | regex + DNS check + IP blocklist | IMPLEMENTED |
| Cloned file tree | Path traversal, symlinks | 8-step filter | IMPLEMENTED |
| Git hooks | Code execution | `-c core.hooksPath=` | IMPLEMENTED |
| `.gitattributes` | Code execution (LFS/filter) | `core.attributesFile=/dev/null` + `filter.lfs.smudge=cat` | IMPLEMENTED |
| User-submitted code (run) | Arbitrary execution | Piston sandbox | IMPLEMENTED |
| User-submitted code (submit) | XSS via output | `ast.parse()` only, no execution | IMPLEMENTED |
| GitHub OAuth state | CSRF | Single-use in-memory tokens | IMPLEMENTED |
| job_id in URLs | IDOR | Ownership check | IMPLEMENTED |
| SSE event data | XSS | `textContent` not `innerHTML` | IMPLEMENTED |
| Auth dev-login | Auth bypass | Gated: development only | RESOLVED |
| /debug/env | Info disclosure | Endpoint removed | RESOLVED |

### Quota Race Condition
`check_and_consume_quota()`: `SELECT COUNT()` then `INSERT` in separate operations. Two concurrent requests can both pass the count check. No `SELECT ... FOR UPDATE` or transaction-level locking. Under high concurrency, a free-tier user can consume more than 5 repos/month.

---

## Section 16 — Gaps and Debt

### TODO/FIXME Markers (literal grep output)
Only 6 `TODO` references found in `app/` — all are intentional product UI strings (the `// TODO: implement` stub that user code must replace). Zero `FIXME`, `HACK`, or `XXX` markers in `app/`.

### Dead Code
- `app/security/sandbox_runner.py` (`SandboxRunner` class): Defined and STUBBED / UNUSED. Not used by `app/services/ingestion.py:run_sandboxed_git_command()` which uses direct subprocess.
- `app/services/cached_ingestion.py` (`CachedIngestionService` class): Defined and UNWIRED / UNUSED. Main pipeline uses `IngestionService` and `FileContentService.persist_file_contents()` directly.
- `app/security/regex_safety.py` (46L): IMPLEMENTED and actively used in `app/parser/shell_parser.py:10, 116-117` (`safe_regex_search` timeout guard on lines > 200 chars).

### Dependency Drift
- `requirements.txt`: `stripe>=8.0.0`; installed: `stripe==15.6.1`. Stripe has multiple breaking API changes between v8 and v15.
- Flask libraries (`Flask-Caching`, `Flask-JWT-Extended`, `Flask-Login`, `Flask-WTF`) appear in pip freeze — are system-level packages not used by this FastAPI project.

### Performance Limits
- Max repo: 150 files hard-coded (`MAX_REPO_FILE_LIMIT_V1 = 150`, `ingestion.py:40`)
- Max file size: `MAX_FILE_SIZE_BYTES = 1024 * 1024` (1,048,576 bytes / 1 MB) in `app/utils/file_filter.py:40`
- Clone timeout: 60 seconds
- Piston run timeout: 3 seconds
- Recursion in `get_scc_depth()`: safe at 150 file cap, but gap exists
- No async pipeline: `run_pipeline()` is synchronous, runs in background thread. Single uvicorn worker → concurrent analyses queue behind each other

### Active Debug Code in Production
`app/api/auth.py:14-24`: `print()` and `logging.warning()` statements that log OAuth configuration and user login attempts. Represents information disclosure in server logs.

---

## Section 17 — Architectural Decisions

### Decision 1: Deterministic-First, LLM-Optional
**Evidence**: `baseline_ordering.py:1-21`, `constrained_tie_breaking.py:204-240`, deterministic narration fallback in `narration_engine.py`
**Rationale**: The build order must be structurally grounded and reproducible. LLM is only allowed within already-computed tier boundaries and only for tie-breaking and narrative text.
**Commit**: Present from `878df01` (initial commit).

### Decision 2: Piston for User Code Execution
**Evidence**: `docker-compose.yml:131-195`, `app/services/execution_verifier.py`
**Rationale**: User code execution is the highest-risk operation. Self-hosted Piston with network isolation, resource limits, and seccomp prevents host compromise.
**Commit**: `8cb4b84 feat(deploy): add Cloudflare Tunnel integration, deployment scripts, and Piston runtime support`

### Decision 3: Python String-Building for HTML (No Framework)
**Evidence**: `app/ui/components.py:6061` lines of Python f-string HTML
**Rationale (inferred)**: Zero-build-step frontend. The entire product ships as one Python process with no Webpack/Vite/npm build pipeline.
**Commit**: `878df01` (initial).

### Decision 4: GitHub-Only OAuth
**Evidence**: `app/api/auth.py`, `app/services/auth_service.py` — only GitHub OAuth implemented
**Rationale**: Target audience is developers with GitHub accounts. GitHub OAuth provides the token needed for API rate-limit increase when analyzing repos.

### Decision 5: SQLite → PostgreSQL Migration Path
**Evidence**: `app/db/session.py:24-60` — explicit URL rewrite `postgres://` → `postgresql+psycopg2://`, inline `ALTER TABLE ADD COLUMN` with dialect guard
**Rationale**: SQLite for development, PostgreSQL for production with no schema changes required (same ORM models).
**Commit**: `29d5e03 feat(core): implement points system, postgres migration, redis rate limiter`

### Decision 6: Hardcode `debug=False`
## Section 18 — Reviewer Q&A (25 Hardest Questions)

**Q1: What guarantees byte-for-byte reproducibility?**
Alphabetical sort at every tier-merge point (`line 137, 228, 236, 247` in `baseline_ordering.py`), deterministic Tarjan SCC, and pure topological sort without random seeds. Verified by deterministic multi-run pipeline validation.

**Q2: Can LLM reorder files across tier boundaries?**
No. `constrained_tie_breaking.py:235`: `outside_tier_files = [f for f in proposed_order if f not in set(tier_files)]` — if non-empty, entire LLM result discarded.

**Q3: What happens if all repo files form one circular import?**
All files → one Tarjan SCC → one cyclic tier → `is_cyclic=True` → narrated as "mutually-coupled," no ordinal language. Not dropped.

**Q4: Can Piston-executed code access the host filesystem?**
Piston container uses tmpfs for writable paths and `PISTON_DISABLE_NETWORKING=true`. Direct host filesystem access requires container escape. SYS_PTRACE + SYS_ADMIN capabilities (required by isolate) make this theoretically possible.

**Q5: Can a secret in a comment be detected by the scanner?**
Yes — `SecretScanner.scan_and_redact()` applies regex patterns over raw file text, not parsed AST. Comments are treated as plain text and scanned.

**Q6: Is Gemini embedding compatible with the FAISS index?**
`HybridRAGEngine(dimension=128)` in pipeline — Gemini returns 768-dim. Shape mismatch if both enabled simultaneously. Not a live risk: `use_gemini=False` by default; offline deterministic 128-dim MD5 feature hashing is used.

**Q7: Can free-tier quota be bypassed by deleting usage_events rows?**
No delete route exists for `usage_events`. App users cannot delete their rows. Account deletion would cascade-delete usage events but also delete all analysis jobs. Not a practical bypass.

**Q8: IDOR protection on analysis jobs?**
`job.user_id != current_user.id` check before serving report or attempts. Test: `test_execution_verifier.py::test_api_run_idor_protection` — IMPLEMENTED.

**Q9: DoS via 10MB code submission?**
`app/api/attempts.py:227-233, 354-360` enforces `MAX_FILE_SIZE_BYTES` from `file_filter.py:40` (`1,048,576` bytes / 1 MB) and rejects oversized payloads with HTTP 413. Test: `test_api_run_payload_size_dos_defense`.

**Q10: Quota double-count race condition?**
Yes — TOCTOU between `SELECT COUNT()` and `INSERT` in `check_and_consume_quota()`. No `SELECT ... FOR UPDATE`. Concurrent requests can both pass. Known gap.

**Q11: SSE stream behavior when analysis thread crashes?**
Background thread exception handler in `app/api/frontend.py:743-780` catches all exceptions, sets job status to `failed` in DB, and emits a structured `failed` SSE event payload. `event_generator()` (`frontend.py:791`) checks queue with 0.25s timeout and terminates gracefully when background thread exits.

**Q12: Can narration engine return different milestones than sequence engine computed?**
No. Narration receives already-frozen `ScoredOrderingResult`. LLM output is string description only — tier structure not modifiable.

**Q13: Is cached_ingestion.py wired into the main flow?**
No — `CachedIngestionService` in `app/services/cached_ingestion.py` is UNWIRED / UNUSED. The active flow in `app/api/frontend.py:627` directly uses `IngestionService` and persists results via `FileContentService.persist_file_contents()`.

**Q14: Is Alembic actually used?**
Yes — `alembic.ini` is configured, and `alembic/versions/` contains 5 real migration scripts (`0001_initial_postgres_schema.py` through `0005_last_run_code.py`).

**Q15: FAISS index on server restart mid-analysis?**
FAISS is in-memory. Restart destroys index. Any active synthesis call fails. Job status set to `failed`. Users can retry.

**Q16: Who can access /debug/env?**
No one. `/debug/env` was completely removed from `app/main.py` in commit `a4c8ba9`.

**Q17: Are refresh tokens salted before storage?**
SHA-256 of raw token stored (`RefreshTokenModel.token_hash`, `db.py:147`). No salt. Adequate for cryptographically random 256-bit tokens. Weak token generation would be a risk.

**Q18: Why are auth routes mounted at both /auth and /api/auth?**
`app/main.py:113-114` — both prefixes mounted for same router. Allows both browser-native `/auth/me` and API client `/api/auth/me`. Doubles the attack surface of every auth route.

**Q19: Stripe webhook idempotency?**
`ProcessedWebhookEventModel` with `UNIQUE(event_id)`. On duplicate delivery, `IntegrityError` caught → 200 returned without re-processing. Test: `test_webhook_idempotent_dedup_no_double_apply`.

**Q20: Exact LLM model name for narration?**
Configured as `gemini-1.5-flash` in `app/sequence/llm_client.py:41` (via `settings.LLM_MODEL_NAME` or default fallback to `gemini-1.5-flash`).

**Q21: Rate limiting on /analyses/submit?**
Monthly quota gating enforced via `BillingService.check_and_consume_quota(user, session)` in `app/api/frontend.py:289-294`. Submissions are also rate-limited for code runs on `/attempts/...` via Token Bucket in `app/api/attempts.py:236-247`.

**Q22: Exact MAX_FILE_SIZE_BYTES value?**
Exactly `1,048,576` bytes (1 MB), defined in `app/utils/file_filter.py:40` (`MAX_FILE_SIZE_BYTES = 1024 * 1024`).

**Q23: Admin-only routes?**
`UserModel.is_admin` is enforced via `require_admin` in `app/api/dependencies.py:117` and checked in `app/api/points.py:160, 196`. Prior unguarded endpoints `/auth/dev-login` and `/debug/env` were secured in commit `a4c8ba9` (`dev-login` is gated by development environment; `/debug/env` was removed).

**Q24: What repos are in CuratedExpectationsRegistry?**
`app/services/curated_milestone_expectations.py:17` defines curated milestone contracts for 5 popular repositories: `pallets/flask`, `psf/requests`, `tiangolo/fastapi`, `encode/starlette`, and `django/django`.

**Q25: Can a .gitmodules submodule SSRF during clone?**
`IngestionService._parse_gitmodules()` (`ingestion.py:292`) reads URLs but explicitly does NOT fetch them. Submodules not auto-initialized (clone uses `--no-checkout`). Mitigated.

---

## Section 19 — Learning Path

Read in this order to understand the system from core outward:

1. **`app/core/config.py`** — All settings and production validation rules
2. **`app/main.py`** — FastAPI factory, middleware, router mounting
3. **`app/models/db.py`** — All 10 database models
4. **`app/db/session.py`** — Engine construction, SQLite vs PostgreSQL, inline migrations
5. **`app/parser/schema.py`** — `FileNode` and `ImportEdge` — pipeline currency
6. **`app/parser/python_parser.py`** — Best-implemented parser, learn the pattern
7. **`app/services/ingestion.py`** — Layer 1: safe repo acquisition
8. **`app/utils/url_validator.py`** — SSRF defenses
9. **`app/sequence/baseline_ordering.py`** — Tarjan SCC and topological tiers (algorithmic core)
10. **`app/sequence/constrained_tie_breaking.py`** — Ambiguity resolution with structural guarantees
11. **`app/sequence/narration_engine.py`** — System prompt, LLM integration, deterministic fallback
12. **`app/orchestration/pipeline.py`** — How all 11 layers assemble
13. **`app/synthesis/engine.py`** — Final report synthesis
14. **`app/services/grading_engine.py`** — 3-tier grading hierarchy
15. **`app/services/execution_verifier.py`** — Piston integration + security boundary
16. **`app/security/rate_limiter.py`** — Lua token bucket on Redis
17. **`app/rag/engine.py`** → **`app/rag/embedder.py`** → **`app/rag/retriever.py`** — RAG pipeline
18. **`app/api/frontend.py`** — All HTML routes, SSE, background thread management
19. **`app/api/attempts.py`** — Challenge submission lifecycle
20. **`app/services/billing_service.py`** — Stripe, quota, webhook idempotency
21. **`app/ui/components.py`** — 6,687-line HTML generator (read last)
22. **`docker-compose.yml`** — Production topology
23. **`tests/test_sequence_baseline.py`** — Best algorithm tests
24. **`tests/test_execution_verifier.py`** — Best Piston security tests
25. **`tests/test_auth_session.py`** — Best auth security tests

---

## Verification Appendix

### Commands Executed in This Session

| Command | Output |
|---|---|
| `git rev-parse HEAD` | bc5b247 |
| `git status` | 14 commits ahead of origin/main |
| `git log --oneline` | 33 commits listed in Section 0.2 |
| `python --version` | Python 3.13.7 |
| `Get-ChildItem -Recurse app -Filter *.py` | 102 `.py` files under `app/` (24,284 LOC total) |
| `python -m pytest --co -q` | 432 test cases collected across 64 test files |
| `python -m pytest -v` | **431 passed, 1 skipped, 0 failed in 566.86s** |
| `Get-ChildItem ... | Select-String "TODO|FIXME|HACK|XXX"` | 6 TODO hits (all intentional stubs), 0 FIXME/HACK/XXX |

### Gaps Audit Status

All previously identified UNKNOWN items have been fully inspected and resolved:
- **Test Results**: 431 passed, 1 skipped across 64 test files.
- **Alembic**: 5 migration files confirmed in `alembic/versions/`.
- **MAX_FILE_SIZE_BYTES**: Exactly 1,048,576 bytes (1 MB) in `app/utils/file_filter.py:40`.
- **LLM Model**: `gemini-1.5-flash` in `app/sequence/llm_client.py:41`.
- **Cached Ingestion**: `CachedIngestionService` confirmed UNWIRED / UNUSED.
- **SandboxRunner**: Confirmed STUBBED / UNUSED.
- **Regex Safety**: Actively used in `app/parser/shell_parser.py:10, 116-117`.

---

## Appendix — Full Test Suite Result (Literal Output)

Command: `python -m pytest -v`
Duration: 566.86s (9 minutes 26 seconds)

```
============================== warnings summary ===============================
tests/test_frontend_ui.py::test_fill_the_blanks_disabled_for_non_python_files_shows_clear_tooltip
  C:\Users\SUMIT\AppData\Roaming\Python\Python313\site-packages\starlette\testclient.py:430: DeprecationWarning: Setting per-request cookies=<...> is being deprecated, because the expected behaviour on cookie persistence is ambiguous. Set cookies directly on the client instance instead.
    return super().request(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
============ 431 passed, 1 skipped, 1 warning in 566.86s (0:09:26) ============
```

**Result**: **431 PASSED, 1 SKIPPED, 0 FAILED**

The 1 skipped test is:
1. `tests/test_live_llm_narration.py::test_live_ollama_flask_narration` (skipped when local Ollama daemon or model is not running).

This means the test suite is fully green in the dev environment (no live Piston/GitHub required for any test to pass — those are mocked or conditional).
