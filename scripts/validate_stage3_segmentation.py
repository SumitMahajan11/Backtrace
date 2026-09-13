"""Stage 3 Layer 4 Code Base Segmentation Validation Script.

Evaluates domain classification rates across 7 representative repositories:
1. tokio-rs/tokio (Rust systems library)
2. tlaplus/Examples (TLA+ formal specifications)
3. fmtlib/fmt (C++ formatting library)
4. flask (Python web framework)
5. gin (Go web framework)
6. spring-petclinic (Java web application)
7. expressjs/express (JS/TS web framework)
"""

import sys
from typing import Dict, List, Tuple
from app.parser.schema import FileNode
from app.segmentation.engine import SegmentationEngine
from app.segmentation.schema import DomainType

# Define representative file lists for all 7 benchmark repositories

REPOS: Dict[str, Tuple[str, List[str]]] = {
    "tokio-rs/tokio": (
        "Rust (Library)",
        [
            "tokio/src/lib.rs",
            "tokio/src/net/tcp/listener.rs",
            "tokio/src/net/tcp/stream.rs",
            "tokio/src/net/udp.rs",
            "tokio/src/sync/mpsc/mod.rs",
            "tokio/src/sync/oneshot.rs",
            "tokio/src/sync/rwlock.rs",
            "tokio/src/time/driver.rs",
            "tokio/src/time/sleep.rs",
            "tokio/src/runtime/thread_pool/mod.rs",
            "tokio/src/runtime/task/mod.rs",
            "tokio-util/src/codec/length_delimited.rs",
            "tokio-util/src/io/read_buf.rs",
            "tokio/tests/tcp_listener.rs",
            "tokio/tests/sync_mpsc.rs",
            "tokio/tests/time_period.rs",
            "Cargo.toml",
            "tokio/Cargo.toml",
            "README.md",
            "LICENSE",
            ".github/workflows/ci.yml",
            "benches/data_dump.bin",
        ],
    ),
    "tlaplus/Examples": (
        "TLA+ (Formal Spec)",
        [
            "specifications/DieHard/DieHard.tla",
            "specifications/DieHard/DieHard.cfg",
            "specifications/Paxos/Paxos.tla",
            "specifications/Paxos/Paxos.cfg",
            "specifications/raft/raft.tla",
            "specifications/raft/raft.cfg",
            "specifications/Econ/Econ.tla",
            "specifications/TransactionCommit/TwoPhase.tla",
            "specifications/TransactionCommit/TwoPhase.cfg",
            "specifications/N-Body/NBody.tla",
            "docs/README.md",
            "LICENSE",
            ".github/workflows/verify.yml",
            "tools/tlc_output.log",
        ],
    ),
    "fmtlib/fmt": (
        "C++ (Library)",
        [
            "include/fmt/core.h",
            "include/fmt/format.h",
            "include/fmt/ranges.h",
            "include/fmt/os.h",
            "include/fmt/chronos.h",
            "src/format.cc",
            "src/os.cc",
            "test/core-test.cc",
            "test/format-test.cc",
            "test/ranges-test.cc",
            "CMakeLists.txt",
            "README.md",
            "LICENSE",
            "support/ci.yml",
            "test/data/fixture.raw",
        ],
    ),
    "flask": (
        "Python (Web Framework)",
        [
            "src/flask/__init__.py",
            "src/flask/app.py",
            "src/flask/blueprints.py",
            "src/flask/cli.py",
            "src/flask/json/__init__.py",
            "src/flask/helpers.py",
            "src/flask/testing.py",
            "tests/test_basic.py",
            "tests/test_blueprints.py",
            "tests/test_cli.py",
            "docs/index.md",
            "docs/deploying.rst",
            "pyproject.toml",
            "LICENSE.rst",
            "scratch/notes.tmp",
        ],
    ),
    "gin": (
        "Go (Web Framework)",
        [
            "gin.go",
            "context.go",
            "routergroup.go",
            "mode.go",
            "render/render.go",
            "binding/binding.go",
            "context_test.go",
            "gin_test.go",
            "routergroup_test.go",
            "go.mod",
            "go.sum",
            "README.md",
            "LICENSE",
            ".github/workflows/ci.yml",
            "testdata/sample.blob",
        ],
    ),
    "spring-petclinic": (
        "Java (Web App)",
        [
            "src/main/java/org/springframework/samples/petclinic/PetClinicApplication.java",
            "src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java",
            "src/main/java/org/springframework/samples/petclinic/owner/OwnerRepository.java",
            "src/main/java/org/springframework/samples/petclinic/owner/Owner.java",
            "src/main/java/org/springframework/samples/petclinic/vet/VetController.java",
            "src/main/resources/templates/owners/createOrUpdateOwnerForm.html",
            "src/main/resources/templates/welcome.html",
            "src/main/resources/db/h2/schema.sql",
            "src/main/resources/db/h2/data.sql",
            "src/test/java/org/springframework/samples/petclinic/owner/OwnerControllerTests.java",
            "pom.xml",
            "README.md",
            "LICENSE.txt",
            ".github/workflows/maven.yml",
            "dummy_cache.tmp",
        ],
    ),
    "expressjs/express": (
        "JS/TS (Web Framework)",
        [
            "lib/express.js",
            "lib/application.js",
            "lib/router/index.js",
            "lib/router/route.js",
            "lib/middleware/init.js",
            "test/express.js",
            "test/app.router.js",
            "test/res.send.js",
            "package.json",
            "Readme.md",
            "LICENSE",
            ".github/workflows/ci.yml",
            "examples/content-negotiation/index.js",
            "coverage/lcov.info",
        ],
    ),
}


def infer_language(path: str) -> str:
    ext = path.split(".")[-1].lower() if "." in path else ""
    mapping = {
        "rs": "rust",
        "tla": "tla+",
        "cfg": "tla+",
        "cc": "cpp",
        "h": "cpp",
        "hpp": "cpp",
        "cpp": "cpp",
        "c": "c",
        "py": "python",
        "go": "go",
        "java": "java",
        "js": "javascript",
        "ts": "typescript",
        "html": "html",
        "css": "css",
        "sql": "sql",
        "md": "markdown",
        "rst": "rst",
        "toml": "toml",
        "yml": "yaml",
        "yaml": "yaml",
        "json": "json",
        "sh": "shell",
    }
    return mapping.get(ext, "unknown")


def run_validation():
    engine = SegmentationEngine()
    print("=" * 115)
    print(f"{'Repository':<20} | {'Type':<22} | {'Files':<6} | {'Core':<5} | {'Back':<5} | {'Front':<5} | {'DB':<4} | {'Docs':<5} | {'Cfg':<4} | {'Uncat (Rate)':<14}")
    print("=" * 115)

    for repo_name, (repo_type, file_paths) in REPOS.items():
        file_nodes = [FileNode(path=p, language=infer_language(p)) for p in file_paths]
        result = engine.segment_repository(file_nodes=file_nodes, all_repo_files=file_paths)

        counts = result.domain_counts
        total = len(file_paths)
        core_cnt = counts.get("core", 0)
        back_cnt = counts.get("backend", 0)
        front_cnt = counts.get("frontend", 0)
        db_cnt = counts.get("database", 0)
        docs_cnt = counts.get("docs", 0)
        cfg_cnt = counts.get("config", 0)
        uncat_cnt = counts.get("uncategorized", 0)
        uncat_rate = (uncat_cnt / total) * 100

        print(f"{repo_name:<20} | {repo_type:<22} | {total:<6} | {core_cnt:<5} | {back_cnt:<5} | {front_cnt:<5} | {db_cnt:<4} | {docs_cnt:<5} | {cfg_cnt:<4} | {uncat_cnt:<2} ({uncat_rate:4.1f}%)")

    print("=" * 115)


if __name__ == "__main__":
    run_validation()
