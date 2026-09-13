"""Stage 3 Layer 4 Code Base Segmentation Validation on FULL 2,700+ File Dataset.

Fetches the complete, exact recursive file trees for all 7 benchmark repositories via GitHub API:
1. tokio-rs/tokio (Rust systems library)
2. tlaplus/Examples (TLA+ formal specifications)
3. fmtlib/fmt (C++ formatting library)
4. pallets/flask (Python web framework)
5. gin-gonic/gin (Go web framework)
6. spring-projects/spring-petclinic (Java web app)
7. expressjs/express (JS/TS web framework)

Runs Layer 4 SegmentationEngine on all ~2,750 real repository file paths and compares
domain distributions before and after adding the DomainType.CORE category.
"""

import json
import os
import sys
import urllib.request
from typing import Dict, List, Tuple

from app.parser.schema import FileNode
from app.segmentation.engine import SegmentationEngine
from app.segmentation.rules import ConventionRulesEngine
from app.segmentation.schema import DomainType

REPOS = {
    "tokio-rs/tokio": ("master", "Rust (Library)"),
    "tlaplus/Examples": ("master", "TLA+ (Formal Spec)"),
    "fmtlib/fmt": ("main", "C++ (Library)"),
    "pallets/flask": ("main", "Python (Web Framework)"),
    "gin-gonic/gin": ("master", "Go (Web Framework)"),
    "spring-projects/spring-petclinic": ("main", "Java (Web App)"),
    "expressjs/express": ("master", "JS/TS (Web Framework)"),
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


def fetch_repo_files(repo: str, branch: str) -> List[str]:
    """Fetches full file tree via GitHub API."""
    url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Python-Stage3-Validator"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        files = [item["path"] for item in data.get("tree", []) if item.get("type") == "blob"]
        return files


def run_full_validation():
    print("=" * 125)
    print("FETCHING FULL FILE TREES FOR ALL 7 BENCHMARK REPOSITORIES VIA GITHUB API...")
    print("=" * 125)

    repo_files_map: Dict[str, List[str]] = {}
    total_files_all = 0

    for repo, (branch, repo_type) in REPOS.items():
        try:
            files = fetch_repo_files(repo, branch)
            repo_files_map[repo] = files
            total_files_all += len(files)
            print(f"  [OK] {repo:<35} ({repo_type:<22}): {len(files):>5} files fetched")
        except Exception as e:
            print(f"  [ERROR] {repo:<35}: {e}")
            sys.exit(1)

    print("-" * 125)
    print(f"TOTAL FILES ACROSS ALL 7 REPOSITORIES: {total_files_all}")
    print("=" * 125)

    engine = SegmentationEngine()

    print("\n" + "=" * 125)
    print("FULL DATASET DOMAIN DISTRIBUTION TABLE (WITH DomainType.CORE CATEGORY)")
    print("=" * 125)
    print(f"{'Repository':<33} | {'Type':<22} | {'Files':<6} | {'Core':<5} | {'Back':<5} | {'Front':<5} | {'DB':<4} | {'Docs':<5} | {'Cfg':<5} | {'Tests':<5} | {'Uncat (Rate)':<14}")
    print("-" * 125)

    grand_total = 0
    grand_uncat = 0
    grand_core = 0

    for repo, (branch, repo_type) in REPOS.items():
        file_paths = repo_files_map[repo]
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
        test_cnt = counts.get("tests", 0)
        uncat_cnt = counts.get("uncategorized", 0)
        uncat_rate = (uncat_cnt / total) * 100

        grand_total += total
        grand_uncat += uncat_cnt
        grand_core += core_cnt

        print(f"{repo:<33} | {repo_type:<22} | {total:<6} | {core_cnt:<5} | {back_cnt:<5} | {front_cnt:<5} | {db_cnt:<4} | {docs_cnt:<5} | {cfg_cnt:<5} | {test_cnt:<5} | {uncat_cnt:<3} ({uncat_rate:5.1f}%)")

    print("=" * 125)
    overall_uncat_rate = (grand_uncat / grand_total) * 100
    print(f"GRAND TOTAL: {grand_total} files analyzed across all 7 repos.")
    print(f"TOTAL CORE CLASSIFICATIONS: {grand_core} files")
    print(f"OVERALL UNCATEGORIZED RATE: {grand_uncat} / {grand_total} ({overall_uncat_rate:.1f}%)")
    print("=" * 125)


if __name__ == "__main__":
    run_full_validation()
