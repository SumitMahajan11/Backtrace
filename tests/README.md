# 🧪 Backtrace Test Suite (`tests/`)

This directory houses the comprehensive test suite for Backtrace, ensuring full verification across all 11 architectural layers.

---

## 🏗️ Test Organization

| Test Category | Files | What It Tests |
| :--- | :--- | :--- |
| **AST Parsers** | `test_*_parser.py` | Accurate node extraction, function calls, class graphs across all 8 supported languages |
| **Pipeline & Orchestration** | `test_pipeline_orchestrator.py`, `test_ingestion.py` | Full end-to-end repository cloning, preflight checks, and layer transition flow |
| **Segmentation & Graph** | `test_segmentation_*.py` | Dependency graph building, topological cycle breaking, milestone clustering |
| **Build Sequence Engine** | `test_sequence_*.py` | Chronological build ordering heuristics and confidence scoring |
| **RAG & Search** | `test_rag_*.py` | Code chunking, BM25 keyword matching, vector embeddings, and hybrid retrieval |
| **Security & Sandbox** | `test_secret_scanner_*.py`, `test_rate_limiter.py`, `test_security_sandboxing.py` | High-entropy secret detection, sliding-window rate limiting, and Piston isolation |
| **Frontend & UI** | `test_frontend_ui.py`, `test_dashboard_redesign.py`, `test_nav_shell.py` | Server-side rendered dashboard components, navigation shell, attempts UI |
| **Real Repo Validation** | `test_real_repo_validation.py`, `test_rag_real_repos.py` | Integration tests against real-world sample repositories (Flask, Gin, Redis-py, etc.) |

---

## 🏃 Running Tests

### Run All Tests
```bash
python -m pytest
```

### Run a Specific Module
```bash
python -m pytest tests/test_python_parser.py
```

### Run by Keyword Filter
```bash
python -m pytest -k "parser or sequence"
```

### Run with Coverage
```bash
python -m pytest --cov=app --cov-report=term-missing tests/
```

---

## 📁 Fixtures
- `tests/fixtures/`: Contains cached analysis outputs, synthetic test projects, and mock repository snapshots for deterministic testing.
- `tests/conftest.py`: Shared pytest fixtures, in-memory database setups, and test clients.
