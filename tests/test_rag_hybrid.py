"""Unit tests for Hybrid RAG Engine combining vector search and graph traversal."""

from app.parser.schema import FileNode, ImportEdge
from app.rag.engine import HybridRAGEngine
from app.rag.schema import CodeChunk


def test_adversarial_vector_miss_graph_hit():
    """Adversarial test: Vector search alone misses a caller file due to zero lexical overlap,

    but Hybrid Graph retrieval successfully recovers it via direct import edge connection.
    """
    file_nodes = [
        FileNode(
            path="src/core/vault.py",
            language="python",
            functions=["secret_encryption_routine"],
            imports=[],
        ),
        FileNode(
            path="src/system/orchestrator.py",
            language="python",
            functions=["boot_sequence"],
            imports=[
                ImportEdge(target="src/core/vault.py", resolved=True, is_external=False),
            ],
        ),
        FileNode(
            path="docs/crypto_glossary.md",
            language="markdown",
            functions=[],
            imports=[],
        ),
    ]

    file_contents = {
        # Target file
        "src/core/vault.py": "def secret_encryption_routine(key_bytes):\n    return f'encrypted_{key_bytes}'\n",
        
        # Direct Caller file with ZERO lexical overlap to the query term "cipher_key"
        "src/system/orchestrator.py": "from src.core.vault import secret_encryption_routine\n\ndef boot_sequence():\n    token = secret_encryption_routine('boot_init_payload')\n    return token\n",
        
        # Distractor File with high lexical similarity to query
        "docs/crypto_glossary.md": "Glossary for cipher_key and secret_encryption_routine algorithms in the system.\n",
    }

    engine = HybridRAGEngine(dimension=128, max_context_chunks=5)
    engine.index_repository(file_nodes, file_contents)

    # 1. Test Vector-Only Search for query "cipher_key algorithms"
    # Vector search alone brings crypto_glossary.md, but NOT orchestrator.py
    query_text = "cipher_key algorithms in vault.py"
    vector_only_res = engine.retriever.retrieve(query=query_text, target_path=None, vector_top_k=1, graph_top_k=0)
    vector_only_files = [rc.chunk.file_path for rc in vector_only_res]
    
    assert "src/system/orchestrator.py" not in vector_only_files

    # 2. Test Hybrid Search with target_path="src/core/vault.py"
    # Hybrid search MUST pull in src/system/orchestrator.py via graph traversal!
    hybrid_res = engine.query(query_text=query_text, target_path="src/core/vault.py")
    hybrid_files = [rc.chunk.file_path for rc in hybrid_res.retrieved_chunks]
    sources_by_file = {rc.chunk.file_path: rc.retrieval_sources for rc in hybrid_res.retrieved_chunks}

    assert "src/system/orchestrator.py" in hybrid_files
    assert "graph" in sources_by_file["src/system/orchestrator.py"]


def test_hybrid_retrieval_finds_direct_caller_via_graph():
    file_nodes = [
        FileNode(
            path="src/payment.py",
            language="python",
            functions=["calculate_tax_rate"],
            imports=[],
        ),
        FileNode(
            path="src/checkout_handler.py",
            language="python",
            functions=["process_checkout"],
            imports=[
                ImportEdge(target="src/payment.py", resolved=True, is_external=False),
            ],
        ),
    ]

    file_contents = {
        "src/payment.py": "def calculate_tax_rate(amount):\n    return amount * 0.15\n",
        "src/checkout_handler.py": "from src.payment import calculate_tax_rate\n\ndef process_checkout(cart):\n    tax = calculate_tax_rate(cart.total)\n    return cart.total + tax\n",
    }

    engine = HybridRAGEngine(dimension=128, max_context_chunks=5)
    engine.index_repository(file_nodes, file_contents)

    result = engine.query(
        query_text="Explain tax calculation in payment.py",
        target_path="src/payment.py",
    )

    retrieved_paths = [rc.chunk.file_path for rc in result.retrieved_chunks]
    sources = {rc.chunk.file_path: rc.retrieval_sources for rc in result.retrieved_chunks}

    assert "src/checkout_handler.py" in retrieved_paths
    assert "graph" in sources["src/checkout_handler.py"]
    assert len(result.citations) >= 1
    assert result.citations[0].line_range_str.startswith("src/")
    assert "[Source: src/" in result.formatted_context


def test_hybrid_retrieval_vector_only_simple_query():
    file_nodes = [
        FileNode(
            path="src/logger.py",
            language="python",
            functions=["log_event"],
            imports=[],
        ),
    ]
    file_contents = {
        "src/logger.py": "def log_event(message):\n    print(message)\n",
    }

    engine = HybridRAGEngine(dimension=128)
    engine.index_repository(file_nodes, file_contents)

    result = engine.query(query_text="How to log messages?")
    assert len(result.retrieved_chunks) >= 1
    assert result.retrieved_chunks[0].chunk.file_path == "src/logger.py"
    assert "vector" in result.retrieved_chunks[0].retrieval_sources
