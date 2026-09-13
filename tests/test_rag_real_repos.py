"""Integration tests for Layer 5 Hybrid RAG Engine on real open-source repo samples."""

import pytest
from app.parser.python_parser import PythonLanguageParser
from app.parser.go_parser import GoLanguageParser
from app.rag.engine import HybridRAGEngine


def test_rag_on_flask_sample():
    flask_files = {
        "src/flask/__init__.py": "from .app import Flask\nfrom .blueprints import Blueprint\n",
        "src/flask/app.py": "class Flask:\n    def __init__(self, import_name):\n        self.import_name = import_name\n",
        "src/flask/blueprints.py": "class Blueprint:\n    def __init__(self, name):\n        self.name = name\n    def send_static_file(self, filename):\n        return filename\n",
    }

    parser = PythonLanguageParser()
    parse_result = parser.parse_repository(
        file_paths=list(flask_files.keys()),
        file_contents=flask_files,
    )

    rag = HybridRAGEngine(dimension=128)
    indexed_chunks_count = rag.index_repository(parse_result.files, flask_files)
    assert indexed_chunks_count >= 3

    # Query for send_static_file
    res = rag.query("How does Blueprint send static files in blueprints.py?", target_path="src/flask/blueprints.py")
    assert len(res.retrieved_chunks) >= 1
    assert any(c.file_path == "src/flask/blueprints.py" for c in res.citations)
    assert "[Source: src/flask/blueprints.py" in res.formatted_context


def test_rag_on_gin_sample():
    gin_files = {
        "gin.go": "package gin\nimport \"net/http\"\ntype Engine struct {}\n",
        "context.go": "package gin\nimport \"fmt\"\ntype Context struct {}\nfunc (c *Context) Next() {}\n",
    }

    parser = GoLanguageParser()
    parse_result = parser.parse_repository(
        file_paths=list(gin_files.keys()),
        file_contents=gin_files,
    )

    rag = HybridRAGEngine(dimension=128)
    indexed_count = rag.index_repository(parse_result.files, gin_files)
    assert indexed_count >= 2

    res = rag.query("What methods are on Context in context.go?", target_path="context.go")
    assert len(res.retrieved_chunks) >= 1
    assert res.citations[0].file_path == "context.go"
