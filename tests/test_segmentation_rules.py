"""Unit tests for Layer 4 ConventionRulesEngine."""

import pytest
from app.segmentation.rules import ConventionRulesEngine
from app.segmentation.schema import ConfidenceLevel, DomainType


@pytest.mark.parametrize(
    "path,language,expected_domain,expected_confidence",
    [
        # Tests domain
        ("tests/test_parser.py", "python", DomainType.TESTS, ConfidenceLevel.HIGH),
        ("src/components/Button.test.tsx", "typescript", DomainType.TESTS, ConfidenceLevel.HIGH),
        ("context_test.go", "go", DomainType.TESTS, ConfidenceLevel.HIGH),
        ("spec/models/user_spec.rb", None, DomainType.TESTS, ConfidenceLevel.HIGH),

        # Docs domain
        ("docs/ARCHITECTURE.md", None, DomainType.DOCS, ConfidenceLevel.HIGH),
        ("README.md", None, DomainType.DOCS, ConfidenceLevel.HIGH),
        ("LICENSE", None, DomainType.DOCS, ConfidenceLevel.HIGH),
        ("docs/spec_guide.md", "markdown", DomainType.DOCS, ConfidenceLevel.HIGH),

        # Config domain
        ("package.json", None, DomainType.CONFIG, ConfidenceLevel.HIGH),
        ("go.mod", None, DomainType.CONFIG, ConfidenceLevel.HIGH),
        ("Cargo.toml", None, DomainType.CONFIG, ConfidenceLevel.HIGH),
        ("docker-compose.yml", None, DomainType.CONFIG, ConfidenceLevel.HIGH),
        (".github/workflows/ci.yml", None, DomainType.CONFIG, ConfidenceLevel.HIGH),
        ("tsconfig.json", None, DomainType.CONFIG, ConfidenceLevel.HIGH),

        # Database domain
        ("db/migrations/001_init.sql", None, DomainType.DATABASE, ConfidenceLevel.HIGH),
        ("schema.sql", None, DomainType.DATABASE, ConfidenceLevel.HIGH),

        # Frontend domain
        ("src/frontend/components/Header.tsx", "typescript", DomainType.FRONTEND, ConfidenceLevel.HIGH),
        ("ui/views/dashboard.vue", "vue", DomainType.FRONTEND, ConfidenceLevel.HIGH),
        ("public/styles/main.css", "css", DomainType.FRONTEND, ConfidenceLevel.HIGH),

        # Backend domain
        ("api/routes/user.py", "python", DomainType.BACKEND, ConfidenceLevel.HIGH),
        ("server/controllers/auth.js", "javascript", DomainType.BACKEND, ConfidenceLevel.HIGH),
        ("main.go", "go", DomainType.BACKEND, ConfidenceLevel.HIGH),
        ("src/backend/Service.java", "java", DomainType.BACKEND, ConfidenceLevel.HIGH),

        # Core / Library domain
        ("src/lib.rs", "rust", DomainType.CORE, ConfidenceLevel.HIGH),
        ("tokio/src/net/tcp/listener.rs", "rust", DomainType.CORE, ConfidenceLevel.HIGH),
        ("include/fmt/format.h", "cpp", DomainType.CORE, ConfidenceLevel.HIGH),
        ("specifications/Paxos/Paxos.tla", "tla+", DomainType.CORE, ConfidenceLevel.HIGH),
        ("pkg/util/parser.go", "go", DomainType.CORE, ConfidenceLevel.HIGH),

        # Ambiguous / Uncategorized
        ("random_blob.xyz", None, DomainType.UNCATEGORIZED, ConfidenceLevel.LOW),
    ],
)
def test_convention_classification(path, language, expected_domain, expected_confidence):
    domain, confidence = ConventionRulesEngine.classify(path, language=language)
    assert domain == expected_domain
    assert confidence == expected_confidence
