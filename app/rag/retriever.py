"""Hybrid retriever combining vector similarity search and graph dependency traversal."""

import re
from typing import Dict, List, Optional, Set
from app.parser.schema import FileNode
from app.rag.embedder import CodeEmbedder
from app.rag.graph_retriever import GraphDependencyRetriever
from app.rag.schema import CodeChunk, RetrievedChunk
from app.rag.vector_store import FAISSVectorStore


class HybridRetriever:
    """Combines vector similarity search with 1-hop dependency graph retrieval."""

    def __init__(
        self,
        vector_store: FAISSVectorStore,
        embedder: CodeEmbedder,
        file_nodes: List[FileNode],
        max_context_chunks: int = 10,
    ):
        self.vector_store = vector_store
        self.embedder = embedder
        self.graph_retriever = GraphDependencyRetriever(file_nodes)
        self.max_context_chunks = max_context_chunks

    def retrieve(
        self,
        query: str,
        target_path: Optional[str] = None,
        vector_top_k: int = 5,
        graph_top_k: int = 5,
    ) -> List[RetrievedChunk]:
        """Performs hybrid vector + graph retrieval for a query.

        Args:
            query: Natural language query or code search string.
            target_path: Optional target file path to focus graph traversal around.
            vector_top_k: Number of top chunks to fetch via vector search.
            graph_top_k: Number of top chunks to fetch via graph traversal.

        Returns:
            List of RetrievedChunk objects with deduplicated chunks and source tags.
        """
        # 1. Perform Vector Similarity Search
        query_vec = self.embedder.embed_text(query)
        vector_matches = self.vector_store.search_similar(query_vec, top_k=vector_top_k)

        # Map chunk_id -> (CodeChunk, score, set_of_sources)
        retrieved_map: Dict[str, Tuple[CodeChunk, float, Set[str]]] = {}

        for chunk, score in vector_matches:
            retrieved_map[chunk.chunk_id] = (chunk, float(score), {"vector"})

        # 2. Perform Graph Dependency Retrieval if target_path is provided or detected in query
        focus_path = target_path or self._detect_file_path_in_query(query)

        if focus_path:
            graph_chunks = self.graph_retriever.retrieve_graph_chunks(
                target_path=focus_path,
                all_chunks=self.vector_store.chunks,
                symbol_query=query,
                max_chunks=graph_top_k,
            )

            for g_chunk in graph_chunks:
                if g_chunk.chunk_id in retrieved_map:
                    chunk, score, sources = retrieved_map[g_chunk.chunk_id]
                    sources.add("graph")
                    retrieved_map[g_chunk.chunk_id] = (chunk, score, sources)
                else:
                    # Default score for graph-only retrieved chunks
                    retrieved_map[g_chunk.chunk_id] = (g_chunk, 0.5, {"graph"})

        # 3. Assemble and sort fused results
        fused_chunks: List[RetrievedChunk] = []
        for chunk_id, (chunk, score, sources_set) in retrieved_map.items():
            fused_chunks.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=score,
                    retrieval_sources=sorted(list(sources_set)),
                )
            )

        # Sort: chunks retrieved by BOTH first, then vector/graph by highest score
        fused_chunks.sort(
            key=lambda rc: (len(rc.retrieval_sources) > 1, rc.score),
            reverse=True,
        )

        # 4. Strict Context Budgeting
        return fused_chunks[: self.max_context_chunks]

    def _detect_file_path_in_query(self, query: str) -> Optional[str]:
        """Extracts a matching indexed file path mentioned in the query text."""
        indexed_files = {c.file_path for c in self.vector_store.chunks}
        for file_path in indexed_files:
            filename = file_path.split("/")[-1]
            if file_path in query or (filename and filename in query):
                return file_path
        return None
