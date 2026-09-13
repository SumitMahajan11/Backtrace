"""Unit tests for ASTCodeChunker in Layer 5 RAG Engine."""

from app.parser.schema import FileNode
from app.rag.chunker import ASTCodeChunker


def test_ast_symbol_aware_chunking():
    code = """class Blueprint:
    def __init__(self, name):
        self.name = name

    def send_static_file(self, filename):
        return filename
"""
    file_node = FileNode(
        path="src/flask/blueprints.py",
        language="python",
        classes=["Blueprint"],
        functions=["__init__", "send_static_file"],
    )

    chunker = ASTCodeChunker(max_chunk_lines=20)
    chunks = chunker.chunk_file("src/flask/blueprints.py", code, file_node=file_node)

    assert len(chunks) >= 1
    # Confirm line accuracy and file path metadata
    for chunk in chunks:
        assert chunk.file_path == "src/flask/blueprints.py"
        assert chunk.start_line >= 1
        assert chunk.end_line <= 7
        assert chunk.line_range_str.startswith("src/flask/blueprints.py:L")


def test_sliding_window_overlap_chunking():
    lines = [f"line_{i} = {i}" for i in range(1, 101)]
    code = "\n".join(lines)

    chunker = ASTCodeChunker(max_chunk_lines=30, overlap_lines=5)
    chunks = chunker.chunk_file("large_file.py", code)

    assert len(chunks) > 1
    # Check overlap: chunk 1 end_line and chunk 2 start_line should overlap by 5 lines
    c1, c2 = chunks[0], chunks[1]
    assert c2.start_line < c1.end_line
