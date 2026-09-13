# Tech Stack

## Backend
**Python + FastAPI**
Reasoning: the RAG/embeddings/LLM ecosystem (LangChain, FAISS, sentence-transformers, GitPython) is overwhelmingly Python-first. FastAPI is async, fast, has automatic docs, and is what DeepWiki itself uses for the same kind of workload.

## Frontend
**Next.js (React) + Tailwind CSS**
Reasoning: handles report/chat/flowchart UI needs well, large free component ecosystem, deploys free on Vercel, pairs naturally with a FastAPI backend.

## Vector Store (Layer 5)
**FAISS**
Reasoning: free, runs in-process (no separate hosted service cost), fast enough for single-repo-at-a-time analysis. Chroma is a fine alternative if persistence-out-of-the-box is preferred later.

## LLM APIs
**Claude and Gemini, abstracted behind one interface (not hard-locked to one provider)**
- Gemini: usable free tier, good for cheaper bulk tasks (e.g., Layer 5 embeddings/RAG answers)
- Claude: stronger structured reasoning, prioritized for Layer 6 (sequence inference)
- Abstraction layer matters so provider swaps later don't require rewriting the pipeline (DeepWiki does the same)

## Layer 2 parsing libraries (per language)
| Language | Library/approach |
|---|---|
| Python | `ast` (built-in) |
| JS/TS | `@babel/parser` or `ts-morph` |
| Java | `javalang` |
| Rust | `syn` (via small Rust helper binary, or regex fallback) |
| Go | `go/parser` (via small Go helper binary) |
| Shell | lightweight custom parser (source/function-call detection) |
| C++ | to be evaluated — likely `libclang` bindings |
| TLA+ | lightweight "detect presence" only, not full parsing (rare, structurally different from code languages) |
| HTML/CSS | detection only (feeds Layer 4), no dependency parsing |

## Git history (Layer 3)
**GitPython** — mature, handles commit logs/timestamps directly.

## Database (Layer 9)
**SQLite for v1 → Postgres later**
Reasoning: zero setup, zero hosting cost, file-based, fine until real concurrent user load justifies the migration.

## Hosting
- Backend: Render or Railway (free tier)
- Frontend: Vercel (free tier)
- Note: free backend tiers sleep after inactivity — first request after idle will be slow. Acceptable for v1.

## Auth
**Existing auth provider (Auth0, Clerk, or Supabase Auth) rather than hand-rolled login**
Reasoning: login/session security is a solved, security-sensitive problem — not worth building from scratch solo.

## Billing
**Stripe** (or equivalent) for usage metering and paid-tier gating.

## Monitoring
**Sentry (free tier)** for error tracking from day one.

## Analytics
**PostHog (free tier)** for usage tracking from day one.

## CI/CD
**GitHub Actions → auto-deploy to Render/Vercel** from the start.

## Job Queue (Layer 11)
**Celery or RQ** for background pipeline processing + progress polling endpoint.

## Security scanning (Layer 10)
- Containerized sandboxing for all untrusted code parsing (no network access, resource limits, read-only filesystem where possible)
- Secret detection: regex/entropy-based scanner (same category of tool as truffleHog) for API keys/tokens/passwords before storage or LLM calls
