"""Unit tests for FAISSVectorStore and CodeEmbedder."""

import numpy as np
from app.rag.embedder import CodeEmbedder
from app.rag.schema import CodeChunk
from app.rag.vector_store import FAISSVectorStore


def test_faiss_vector_store_add_and_search():
    embedder = CodeEmbedder(dimension=128, use_gemini=False)
    store = FAISSVectorStore(dimension=128)

    chunk1 = CodeChunk(
        chunk_id="c1",
        file_path="src/auth.py",
        start_line=1,
        end_line=10,
        content="def authenticate_user(username, password): pass",
        symbol_name="authenticate_user",
    )
    chunk2 = CodeChunk(
        chunk_id="c2",
        file_path="src/db.py",
        start_line=1,
        end_line=10,
        content="def connect_database(connection_string): pass",
        symbol_name="connect_database",
    )

    chunks = [chunk1, chunk2]
    vecs = embedder.embed_batch([c.content for c in chunks])
    store.add_chunks(chunks, vecs)

    assert store.index.ntotal == 2

    # Query for authentication
    q_vec = embedder.embed_text("authenticate user credentials")
    results = store.search_similar(q_vec, top_k=1)

    assert len(results) == 1
    top_chunk, score = results[0]
    assert top_chunk.chunk_id == "c1"
    assert top_chunk.symbol_name == "authenticate_user"
    assert score > 0.0
