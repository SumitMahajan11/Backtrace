"""Dependency graph retriever using Layer 2 import edges for 1-hop neighbor context retrieval."""

from typing import Dict, List, Set, Tuple
from app.parser.schema import FileNode
from app.rag.schema import CodeChunk


class GraphDependencyRetriever:
    """Traverses Layer 2 dependency edges to retrieve structurally connected code chunks."""

    def __init__(self, file_nodes: List[FileNode]):
        self.file_nodes = file_nodes
        self.importers_map: Dict[str, Set[str]] = {}
        self.imported_deps_map: Dict[str, Set[str]] = {}
        self._build_graph_maps()

    def _build_graph_maps(self) -> None:
        """Constructs bidirectional graph mappings between files."""
        for fn in self.file_nodes:
            src = fn.path
            if src not in self.imported_deps_map:
                self.imported_deps_map[src] = set()
            if src not in self.importers_map:
                self.importers_map[src] = set()

            for edge in fn.imports:
                if edge.resolved and not edge.is_external:
                    tgt = edge.target
                    self.imported_deps_map[src].add(tgt)

                    if tgt not in self.importers_map:
                        self.importers_map[tgt] = set()
                    self.importers_map[tgt].add(src)

    def get_connected_files(self, file_path: str) -> Set[str]:
        """Returns 1-hop direct connected files (both importers and imported dependencies)."""
        connected: Set[str] = set()
        if file_path in self.imported_deps_map:
            connected.update(self.imported_deps_map[file_path])
        if file_path in self.importers_map:
            connected.update(self.importers_map[file_path])
        connected.discard(file_path)
        return connected

    def retrieve_graph_chunks(
        self,
        target_path: str,
        all_chunks: List[CodeChunk],
        symbol_query: str = "",
        max_chunks: int = 5,
    ) -> List[CodeChunk]:
        """Retrieves chunks from target file and its 1-hop connected files in the dependency graph.

        Args:
            target_path: Center file path for dependency traversal.
            all_chunks: Complete repository chunk pool.
            symbol_query: Optional string to match symbol names in connected chunks.
            max_chunks: Upper bound on graph chunks returned.

        Returns:
            List of CodeChunk objects retrieved via dependency graph traversal.
        """
        connected_files = self.get_connected_files(target_path)
        target_set = {target_path}.union(connected_files)

        candidate_chunks = [c for c in all_chunks if c.file_path in target_set]
        if not candidate_chunks:
            return []

        # Sort: target_path chunks first, then symbol matches, then connected files
        sq_lower = symbol_query.lower() if symbol_query else ""

        def chunk_priority(c: CodeChunk) -> Tuple[bool, bool]:
            is_target_file = (c.file_path == target_path)
            is_symbol_match = bool(sq_lower and ((c.symbol_name and sq_lower in c.symbol_name.lower()) or (sq_lower in c.content.lower())))
            return (is_target_file, is_symbol_match)

        candidate_chunks.sort(key=chunk_priority, reverse=True)
        return candidate_chunks[:max_chunks]
