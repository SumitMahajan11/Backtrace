"""FAISS-based vector store for code chunk indexing and similarity search."""

from typing import List, Tuple
import faiss
import numpy as np

from app.rag.schema import CodeChunk


class FAISSVectorStore:
    """Stores code chunk embeddings in FAISS IndexFlatIP and provides vector search."""

    def __init__(self, dimension: int = 128):
        self.dimension = dimension
        self.index = faiss.IndexFlatIP(self.dimension)
        self.chunks: List[CodeChunk] = []

    def add_chunks(self, chunks: List[CodeChunk], embeddings: np.ndarray) -> None:
        """Adds code chunks and their corresponding embedding vectors to the FAISS index."""
        if not chunks or len(embeddings) == 0:
            return

        if len(chunks) != len(embeddings):
            raise ValueError(f"Mismatch between chunks count ({len(chunks)}) and embeddings ({len(embeddings)}).")

        embeddings_32 = np.ascontiguousarray(embeddings.astype(np.float32))
        self.index.add(embeddings_32)
        self.chunks.extend(chunks)

    def search_similar(self, query_embedding: np.ndarray, top_k: int = 5) -> List[Tuple[CodeChunk, float]]:
        """Searches the vector store for top_k most similar chunks.

        Returns:
            List of (CodeChunk, similarity_score) tuples sorted by highest score first.
        """
        if self.index.ntotal == 0 or top_k <= 0:
            return []

        q_vec = np.ascontiguousarray(query_embedding.reshape(1, -1).astype(np.float32))
        k = min(top_k, self.index.ntotal)

        distances, indices = self.index.search(q_vec, k)

        results: List[Tuple[CodeChunk, float]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx >= 0 and idx < len(self.chunks):
                results.append((self.chunks[idx], float(dist)))

        return results

    def get_chunks_by_file(self, file_path: str) -> List[CodeChunk]:
        """Returns all chunks belonging to a specific file."""
        return [c for c in self.chunks if c.file_path == file_path]

    def clear(self) -> None:
        """Clears the FAISS index and chunk store."""
        self.index.reset()
        self.chunks.clear()
