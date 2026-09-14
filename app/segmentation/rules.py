"""Rule-based convention engine for primary file segmentation."""

import os
import re
from typing import Optional, Tuple
from app.segmentation.schema import ConfidenceLevel, DomainType


class ConventionRulesEngine:
    """Primary classifier using directory structure, filenames, and file extensions."""

    # Test patterns
    TEST_FOLDERS = {"tests", "test", "spec", "specs", "__tests__", "testing"}
    TEST_PATTERNS = [
        re.compile(r"^test_.*", re.IGNORECASE),
        re.compile(r".*_test\..*", re.IGNORECASE),
        re.compile(r".*\.test\..*", re.IGNORECASE),
        re.compile(r".*\.spec\..*", re.IGNORECASE),
        re.compile(r".*_spec\..*", re.IGNORECASE),
    ]

    # Documentation patterns
    DOC_FOLDERS = {"docs", "doc", "documentation", "man"}
    DOC_EXTENSIONS = {".md", ".rst", ".adoc", ".txt"}
    DOC_FILES = {"license", "changelog", "contributing", "readme", "architecture"}

    # Configuration patterns
    CONFIG_FOLDERS = {".github", ".vscode", ".idea", "config", "configs", "configuration", "ci", "scripts", "build"}
    CONFIG_EXACT_FILES = {
        "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "requirements.txt", "pipfile", "poetry.lock", "pyproject.toml", "setup.py", "setup.cfg",
        "cargo.toml", "cargo.lock", "go.mod", "go.sum", "pom.xml", "build.gradle", "gradlew",
        "tsconfig.json", "jsconfig.json", "docker-compose.yml", "docker-compose.yaml",
        "dockerfile", "makefile", "cmakelists.txt", "rakefile", ".gitignore", ".env", ".flaskenv"
    }

    # Database patterns
    DATABASE_FOLDERS = {"db", "database", "migrations", "migration", "schema", "schemas", "sql"}
    DATABASE_EXTENSIONS = {".sql"}

    # Examples and tutorial patterns
    EXAMPLES_FOLDERS = {
        "examples", "example", "demo", "demos", "sample", "samples",
        "tutorial", "tutorials", "showcase", "cookbook"
    }

    # Frontend patterns
    FRONTEND_FOLDERS = {
        "frontend", "client", "web", "ui", "components", "views",
        "pages", "styles", "assets", "static", "public", "layouts", "hooks"
    }
    FRONTEND_EXTENSIONS = {".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss", ".sass", ".less", ".html"}

    # Backend patterns
    BACKEND_FOLDERS = {
        "backend", "server", "api", "routes", "controllers", "services",
        "handlers", "endpoints", "models", "repository", "dao"
    }
    BACKEND_ENTRYPOINTS = {
        "main.go", "app.py", "server.js", "main.rs", "application.java", "wsgi.py", "asgi.py"
    }
    BACKEND_FILENAME_KEYWORDS = {
        "controller", "route", "service", "handler", "endpoint", "repository", "dao"
    }

    @classmethod
    def classify(cls, file_path: str, language: Optional[str] = None) -> Tuple[DomainType, ConfidenceLevel]:
        """Classifies a file path into a DomainType based on conventions.
        
        Returns:
            Tuple of (DomainType, ConfidenceLevel). If unclassifiable by rules,
            returns (DomainType.UNCATEGORIZED, ConfidenceLevel.LOW).
        """
        normalized_path = file_path.replace("\\", "/").strip("/")
        parts = [p.lower() for p in normalized_path.split("/")]
        filename = parts[-1] if parts else ""
        filename_lower = filename.lower()
        ext = os.path.splitext(filename_lower)[1]

        # 1. Tests rule (highest precedence for path/filename test indicators)
        if any(folder in cls.TEST_FOLDERS for folder in parts[:-1]):
            return DomainType.TESTS, ConfidenceLevel.HIGH

        for pattern in cls.TEST_PATTERNS:
            if pattern.match(filename):
                return DomainType.TESTS, ConfidenceLevel.HIGH

        # 2. Config rule (exact files, config folders, dotfiles)
        if filename_lower in cls.CONFIG_EXACT_FILES or filename_lower.startswith(".env"):
            return DomainType.CONFIG, ConfidenceLevel.HIGH

        if any(folder in cls.CONFIG_FOLDERS for folder in parts[:-1]):
            return DomainType.CONFIG, ConfidenceLevel.HIGH

        if filename_lower.startswith("dockerfile") or filename_lower.startswith(".eslint") or filename_lower.startswith(".prettier"):
            return DomainType.CONFIG, ConfidenceLevel.HIGH

        if ext in {".cfg", ".toml", ".yaml", ".yml", ".ini", ".properties"}:
            return DomainType.CONFIG, ConfidenceLevel.HIGH

        # 3. Documentation rule
        if any(folder in cls.DOC_FOLDERS for folder in parts[:-1]):
            return DomainType.DOCS, ConfidenceLevel.HIGH

        stem = os.path.splitext(filename_lower)[0]
        if stem in cls.DOC_FILES or any(stem.startswith(df) for df in cls.DOC_FILES):
            return DomainType.DOCS, ConfidenceLevel.HIGH

        if ext in cls.DOC_EXTENSIONS:
            return DomainType.DOCS, ConfidenceLevel.HIGH

        # 4. Database rule
        if any(folder in cls.DATABASE_FOLDERS for folder in parts[:-1]):
            return DomainType.DATABASE, ConfidenceLevel.HIGH

        if ext in cls.DATABASE_EXTENSIONS:
            return DomainType.DATABASE, ConfidenceLevel.HIGH

        # 5. Examples / Tutorials / Demos rule
        if any(folder in cls.EXAMPLES_FOLDERS for folder in parts[:-1]):
            return DomainType.EXAMPLES, ConfidenceLevel.HIGH

        # 6. Frontend rule
        if any(folder in cls.FRONTEND_FOLDERS for folder in parts[:-1]):
            return DomainType.FRONTEND, ConfidenceLevel.HIGH

        if ext in cls.FRONTEND_EXTENSIONS:
            return DomainType.FRONTEND, ConfidenceLevel.HIGH

        # 7. Backend rule
        if any(folder in cls.BACKEND_FOLDERS for folder in parts[:-1]):
            return DomainType.BACKEND, ConfidenceLevel.HIGH

        if filename_lower in cls.BACKEND_ENTRYPOINTS:
            return DomainType.BACKEND, ConfidenceLevel.HIGH

        if any(kw in stem for kw in cls.BACKEND_FILENAME_KEYWORDS):
            return DomainType.BACKEND, ConfidenceLevel.HIGH

        # 7. Core / Library code rule (for systems/library repos without web endpoints)
        CORE_FOLDERS = {"core", "runtime", "kernel", "lib", "library", "internal", "pkg", "include", "src", "specifications", "specs"}
        CODE_EXTENSIONS = {
            ".rs", ".go", ".py", ".java", ".js", ".ts", ".cpp", ".c", ".h", ".hpp", ".cc", ".tla", ".swift", ".kt", ".rb", ".php", ".cs"
        }

        if any(folder in CORE_FOLDERS for folder in parts[:-1]) and ext in CODE_EXTENSIONS:
            return DomainType.CORE, ConfidenceLevel.HIGH

        # Language heuristic fallback if in root or standard code directory
        if ext in CODE_EXTENSIONS or language in {"go", "rust", "java", "python", "javascript", "typescript", "cpp", "c", "tla+", "shell"}:
            first_dir = parts[0] if len(parts) > 1 else ""
            if first_dir in CORE_FOLDERS:
                return DomainType.CORE, ConfidenceLevel.HIGH
            elif len(parts) == 1 and ext in CODE_EXTENSIONS:
                return DomainType.CORE, ConfidenceLevel.HIGH
            elif len(parts) > 1 and ext in CODE_EXTENSIONS and not any(f in cls.FRONTEND_FOLDERS | cls.BACKEND_FOLDERS | cls.DATABASE_FOLDERS for f in parts[:-1]):
                return DomainType.CORE, ConfidenceLevel.MEDIUM

        return DomainType.UNCATEGORIZED, ConfidenceLevel.LOW
