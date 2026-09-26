# 🧠 Backtrace Application Core (`app/`)

This directory contains the entire application source code for the **Backtrace** platform.

---

## 🏛️ Module Overview & Map

| Package | Purpose & Responsibility | Key Files |
| :--- | :--- | :--- |
| **`api/`** | FastAPI endpoints & HTTP request handling | [main.py](file:///d:/Projects/Reverse/app/api/main.py), [frontend.py](file:///d:/Projects/Reverse/app/api/frontend.py), [attempts.py](file:///d:/Projects/Reverse/app/api/attempts.py), [health.py](file:///d:/Projects/Reverse/app/api/health.py) |
| **`core/`** | Global application configuration, logging, settings | [config.py](file:///d:/Projects/Reverse/app/core/config.py), [logging.py](file:///d:/Projects/Reverse/app/core/logging.py) |
| **`db/`** | Database session, connection pooling, and Base ORM setup | [session.py](file:///d:/Projects/Reverse/app/db/session.py), [base.py](file:///d:/Projects/Reverse/app/db/base.py) |
| **`formatters/`** | Report rendering (Markdown, JSON, export formats) | [markdown.py](file:///d:/Projects/Reverse/app/formatters/markdown.py), [json_formatter.py](file:///d:/Projects/Reverse/app/formatters/json_formatter.py) |
| **`models/`** | SQLAlchemy database models and Pydantic schemas | [db.py](file:///d:/Projects/Reverse/app/models/db.py), [analysis.py](file:///d:/Projects/Reverse/app/models/analysis.py), [attempt.py](file:///d:/Projects/Reverse/app/models/attempt.py) |
| **`monitoring/`** | Prometheus metrics, health diagnostics, telemetry | [metrics.py](file:///d:/Projects/Reverse/app/monitoring/metrics.py) |
| **`orchestration/`** | 11-Layer pipeline orchestrator & execution flow | [pipeline.py](file:///d:/Projects/Reverse/app/orchestration/pipeline.py), [schema.py](file:///d:/Projects/Reverse/app/orchestration/schema.py) |
| **`parser/`** | Polyglot AST parsers (Python, JS, Go, Rust, Java, C++, Shell, TLA+) | [python_parser.py](file:///d:/Projects/Reverse/app/parser/python_parser.py), [go_parser.py](file:///d:/Projects/Reverse/app/parser/go_parser.py), [rust_parser.py](file:///d:/Projects/Reverse/app/parser/rust_parser.py) |
| **`rag/`** | Semantic chunker, hybrid vector store, BM25 indexing | [chunker.py](file:///d:/Projects/Reverse/app/rag/chunker.py), [vector_store.py](file:///d:/Projects/Reverse/app/rag/vector_store.py), [hybrid.py](file:///d:/Projects/Reverse/app/rag/hybrid.py) |
| **`security/`** | Secret scanning, IP rate limiting, sandbox seccomp filters | [secret_scanner.py](file:///d:/Projects/Reverse/app/security/secret_scanner.py), [rate_limiter.py](file:///d:/Projects/Reverse/app/security/rate_limiter.py) |
| **`segmentation/`** | Milestone clustering & dependency graph building | [graph.py](file:///d:/Projects/Reverse/app/segmentation/graph.py), [rules.py](file:///d:/Projects/Reverse/app/segmentation/rules.py) |
| **`sequence/`** | Build-sequence reconstruction algorithm & tie-breakers | [engine.py](file:///d:/Projects/Reverse/app/sequence/engine.py), [tie_breakers.py](file:///d:/Projects/Reverse/app/sequence/tie_breakers.py) |
| **`services/`** | Piston sandbox execution, LLM synthesis, hints, grading | [piston.py](file:///d:/Projects/Reverse/app/services/piston.py), [synthesis.py](file:///d:/Projects/Reverse/app/services/synthesis.py), [grading.py](file:///d:/Projects/Reverse/app/services/grading.py) |
| **`storage/`** | Job repositories, disk caching, state persistence | [analysis_job_repository.py](file:///d:/Projects/Reverse/app/storage/analysis_job_repository.py), [caching.py](file:///d:/Projects/Reverse/app/storage/caching.py) |
| **`synthesis/`** | LLM prompt templates and chapter generation | [prompts.py](file:///d:/Projects/Reverse/app/synthesis/prompts.py), [generator.py](file:///d:/Projects/Reverse/app/synthesis/generator.py) |
| **`ui/`** | Web dashboard templates, components, and styling | [components.py](file:///d:/Projects/Reverse/app/ui/components.py) |
| **`utils/`** | Git utilities, subpath validation, subprocess runners | [git.py](file:///d:/Projects/Reverse/app/utils/git.py), [subpath.py](file:///d:/Projects/Reverse/app/utils/subpath.py) |

---

## 💡 How Request Flow Works

1. **User Submits Repo**: `POST /api/analyze` receives a GitHub repository URL (and optional branch/subpath).
2. **Layer 1-4 Pipeline Execution**:
   - `orchestration/pipeline.py` clones repo to a temporary workspace.
   - `security/secret_scanner.py` verifies no leaked API keys or credentials exist.
   - `parser/` extracts AST definitions (functions, classes, dependencies).
   - `segmentation/graph.py` builds the directed acyclic graph (DAG).
   - `sequence/engine.py` topologically sorts nodes into chronological build milestones.
3. **Layer 5-7 Synthesis & RAG**:
   - `rag/hybrid.py` indexes code chunks.
   - `synthesis/` prompts LLM to generate narrative chapters explaining each milestone.
   - `services/scaffold.py` prepares starter challenge scaffolds.
4. **Interactive Verification & Gamification**:
   - User submits code solution on Web UI (`ui/`).
   - `services/piston.py` executes code safely in Piston container.
   - `services/grading.py` and `services/hints.py` evaluate test pass rates and award points.
