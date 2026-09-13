"""Main Layer 5 Hybrid Vector + Graph RAG Engine orchestrator."""

from typing import Dict, List, Optional

from app.parser.schema import FileNode
from app.rag.chunker import ASTCodeChunker
from app.rag.embedder import CodeEmbedder
from app.rag.retriever import HybridRetriever
from app.rag.schema import CitationSource, CodeChunk, RAGQueryResult, RetrievedChunk
from app.rag.vector_store import FAISSVectorStore


class HybridRAGEngine:
    """Orchestrates AST-aware chunking, vector indexing, hybrid graph retrieval, and citation formatting."""

    def __init__(self, dimension: int = 128, use_gemini: bool = False, max_context_chunks: int = 10):
        self.chunker = ASTCodeChunker()
        self.embedder = CodeEmbedder(dimension=dimension, use_gemini=use_gemini)
        self.vector_store = FAISSVectorStore(dimension=dimension)
        self.max_context_chunks = max_context_chunks
        self.retriever: Optional[HybridRetriever] = None
        self.file_nodes: List[FileNode] = []

    def index_repository(self, file_nodes: List[FileNode], file_contents: Dict[str, str]) -> int:
        """Chunks and indexes an entire repository into the vector store.

        Args:
            file_nodes: Parsed FileNode objects from Layer 2.
            file_contents: Dict mapping file paths to full source code text.

        Returns:
            Total number of indexed code chunks.
        """
        self.vector_store.clear()
        self.file_nodes = file_nodes
        node_map: Dict[str, FileNode] = {fn.path: fn for fn in file_nodes}

        all_chunks: List[CodeChunk] = []
        for path, content in file_contents.items():
            fn = node_map.get(path)
            chunks = self.chunker.chunk_file(path, content, file_node=fn)
            all_chunks.extend(chunks)

        if all_chunks:
            contents = [c.content for c in all_chunks]
            embeddings = self.embedder.embed_batch(contents)
            self.vector_store.add_chunks(all_chunks, embeddings)

        self.retriever = HybridRetriever(
            vector_store=self.vector_store,
            embedder=self.embedder,
            file_nodes=self.file_nodes,
            max_context_chunks=self.max_context_chunks,
        )

        return len(all_chunks)

    def query(
        self,
        query_text: str,
        target_path: Optional[str] = None,
        vector_top_k: int = 5,
        graph_top_k: int = 5,
    ) -> RAGQueryResult:
        """Executes a hybrid RAG query returning retrieved chunks, citations, and formatted prompt context.

        Args:
            query_text: Natural language query or code question.
            target_path: Optional file path to center dependency graph search around.
            vector_top_k: Number of vector chunks to retrieve.
            graph_top_k: Number of graph chunks to retrieve.

        Returns:
            RAGQueryResult with retrieved chunks, citations, and formatted context.
        """
        if not self.retriever:
            return RAGQueryResult(query=query_text)

        retrieved_chunks = self.retriever.retrieve(
            query=query_text,
            target_path=target_path,
            vector_top_k=vector_top_k,
            graph_top_k=graph_top_k,
        )

        formatted_context_blocks: List[str] = []
        citations: List[CitationSource] = []

        for rc in retrieved_chunks:
            c = rc.chunk
            header = f"[Source: {c.line_range_str} | Retrieved via: {', '.join(rc.retrieval_sources)}]"
            block = f"{header}\n{c.content}\n"
            formatted_context_blocks.append(block)

            citations.append(
                CitationSource(
                    file_path=c.file_path,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    symbol_name=c.symbol_name,
                    line_range_str=c.line_range_str,
                )
            )

        formatted_context = "\n---\n".join(formatted_context_blocks)

        return RAGQueryResult(
            query=query_text,
            retrieved_chunks=retrieved_chunks,
            formatted_context=formatted_context,
            citations=citations,
        )
